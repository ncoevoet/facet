"""
Tests for the sqlite-vec KNN routing of the CLIP-only similar-photo branch
(_find_similar_visual / _vec_knn_similar in api/routers/gallery.py).

Topic 2 steps 1-2: the no-pHash-candidate branch routes through vec0 KNN when
sqlite-vec is available, and falls back to the brute-force NumPy scan (with
identical results) when it is not.
"""

import sqlite3

import numpy as np
import pytest

import sqlite_vec

from api.routers.gallery import _find_similar_visual, _vec_knn_similar
from utils.embedding import embedding_to_bytes


DIM = 16


def _load_vec(conn):
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)


def _make_vec_db(path, embeddings, with_vec=True):
    """Build a temp DB of photos (no pHash) + an optional populated photos_vec.

    `embeddings` is a dict {photo_path: np.ndarray}. No photo gets a pHash, so
    _find_similar_visual always enters the CLIP-only branch.
    """
    conn = sqlite3.connect(path)
    _load_vec(conn)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE photos (
            path TEXT PRIMARY KEY, filename TEXT, phash TEXT,
            clip_embedding BLOB, date_taken TEXT,
            aggregate REAL, aesthetic REAL, is_rejected INTEGER DEFAULT 0
        )"""
    )
    for p, emb in embeddings.items():
        conn.execute(
            "INSERT INTO photos (path, filename, phash, clip_embedding, date_taken, aggregate, aesthetic) "
            "VALUES (?, ?, NULL, ?, '2024:01:01 00:00:00', 5.0, 5.0)",
            [p, p.lstrip('/'), embedding_to_bytes(emb)],
        )
    if with_vec:
        conn.execute(
            f"CREATE VIRTUAL TABLE photos_vec USING vec0(path TEXT PRIMARY KEY, embedding float[{DIM}] distance_metric=cosine)"
        )
        for p, emb in embeddings.items():
            conn.execute(
                "INSERT INTO photos_vec (path, embedding) VALUES (?, ?)",
                [p, embedding_to_bytes(emb)],
            )
    conn.commit()
    return conn


def _numpy_expected(embeddings, source_path, min_sim=0.0):
    """Brute-force cosine top list, the reference the vec path must match."""
    src = embeddings[source_path] / np.linalg.norm(embeddings[source_path])
    scored = []
    for p, emb in embeddings.items():
        if p == source_path:
            continue
        e = emb / np.linalg.norm(emb)
        sim = max(0.0, float(np.dot(src, e)))
        if sim >= min_sim:
            scored.append((p, sim))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


@pytest.fixture
def embeddings():
    rng = np.random.RandomState(42)
    return {f"/p{i}.jpg": rng.randn(DIM).astype(np.float32) for i in range(60)}


def test_vec_branch_uses_match_and_matches_numpy_top10(tmp_path, embeddings):
    """vec0 KNN top-10 ordering is identical to the NumPy cosine reference."""
    db = str(tmp_path / "vec.db")
    conn = _make_vec_db(db, embeddings, with_vec=True)
    source_path = "/p0.jpg"
    source = dict(conn.execute("SELECT * FROM photos WHERE path = ?", [source_path]).fetchone())

    results, _ = _find_similar_visual(conn, source, source_path, 0.0, "1=1", [])

    expected = _numpy_expected(embeddings, source_path, 0.0)
    expected_top10 = [p for p, _ in expected[:10]]
    got_top10 = [r['path'] for r in results[:10]]
    assert got_top10 == expected_top10
    # Similarity values agree with the cosine reference within float tolerance.
    exp_by_path = dict(expected)
    for r in results[:10]:
        assert r['similarity'] == pytest.approx(exp_by_path[r['path']], abs=1e-4)
    conn.close()


def test_vec_helper_returns_none_when_table_missing(tmp_path, embeddings):
    """No photos_vec table → _vec_knn_similar signals fallback (returns None)."""
    db = str(tmp_path / "novec.db")
    conn = _make_vec_db(db, embeddings, with_vec=False)
    source = dict(conn.execute("SELECT * FROM photos WHERE path = ?", ["/p0.jpg"]).fetchone())
    src_emb = np.frombuffer(source['clip_embedding'], dtype=np.float32)
    assert _vec_knn_similar(conn, src_emb, "/p0.jpg", 0.0, "1=1", []) is None
    conn.close()


def test_numpy_fallback_identical_when_vec_unavailable(tmp_path, embeddings):
    """With photos_vec absent, _find_similar_visual's NumPy fallback returns the
    same top-10 as the vec path would have (step 2 regression guard)."""
    db = str(tmp_path / "fallback.db")
    conn = _make_vec_db(db, embeddings, with_vec=False)
    source_path = "/p0.jpg"
    source = dict(conn.execute("SELECT * FROM photos WHERE path = ?", [source_path]).fetchone())

    results, _ = _find_similar_visual(conn, source, source_path, 0.0, "1=1", [])

    expected = _numpy_expected(embeddings, source_path, 0.0)
    assert [r['path'] for r in results[:10]] == [p for p, _ in expected[:10]]
    conn.close()


def test_vec_respects_visibility_filter(tmp_path, embeddings):
    """Rejected photos excluded by the visibility post-filter never appear."""
    db = str(tmp_path / "vis.db")
    conn = _make_vec_db(db, embeddings, with_vec=True)
    # Reject the photo that would be the single nearest neighbour.
    expected = _numpy_expected(embeddings, "/p0.jpg", 0.0)
    nearest = expected[0][0]
    conn.execute("UPDATE photos SET is_rejected = 1 WHERE path = ?", [nearest])
    conn.commit()

    source = dict(conn.execute("SELECT * FROM photos WHERE path = ?", ["/p0.jpg"]).fetchone())
    results, _ = _find_similar_visual(conn, source, "/p0.jpg", 0.0, "is_rejected = 0", [])
    assert nearest not in {r['path'] for r in results}
    conn.close()
