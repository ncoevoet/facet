"""
Tests for the personal ranker (optimization/personal_ranker.py), Topic 1 steps 1-4.

Pure-function tests verify the RankNet/BT head separates a clean signal
(~100% train, held-out > 0.8). Integration tests verify the CV gate, the
<30-comparison guard, and that a passing gate writes learned_scores.
"""

import sqlite3

import numpy as np
import pytest

from db.schema import init_database
from optimization import personal_ranker as pr


# --- pure-function tests (step 2 verify) ---

def test_fit_separates_single_feature():
    """One feature decides the winner -> ~100% train accuracy, CV > 0.8."""
    rng = np.random.default_rng(0)
    n, f = 200, 6
    a = rng.normal(size=(n, f))
    b = rng.normal(size=(n, f))
    diff = a - b
    # Feature 0 alone decides: a wins iff diff[:,0] > 0.
    y = (diff[:, 0] > 0).astype(np.int64)
    weights = np.ones(n)
    w = pr._fit_logistic(diff, y, weights, C=1.0)
    assert pr._pairwise_accuracy(w, diff, y) >= 0.99
    assert pr._cv_accuracy(diff, y, weights, C=1.0, n_folds=5) > 0.8
    # The decisive feature has the largest-magnitude weight.
    assert abs(w[0]) == pytest.approx(np.abs(w).max())


def test_baseline_accuracy():
    agg_a = np.array([8.0, 3.0, 5.0])
    agg_b = np.array([4.0, 6.0, 5.0])
    y = np.array([1, 1, 0])   # a, a(wrong-by-agg), b
    # pred = agg_a>agg_b -> [True, False, False]; correct vs y -> [T, F, T] = 2/3
    assert pr._baseline_accuracy(agg_a, agg_b, y) == pytest.approx(2 / 3)


# --- integration fixtures ---

_METRIC_COLS = (
    "aesthetic, quality_score, face_quality, face_sharpness, eye_sharpness, "
    "tech_sharpness, comp_score, power_point_score, leading_lines_score, "
    "exposure_score, color_score, contrast_score, dynamic_range_stops, "
    "mean_saturation, noise_sigma, isolation_bonus"
)
_METRIC_VALS = "5, 5, 5, 50, 5, 5, 5, 5, 5, 5, 5, 5, 7, 0.5, 1, 5"


def _emb_bytes(signal, dim=16, rng=None):
    """Embedding whose component 0 carries the preference signal."""
    v = np.full(dim, 0.1, dtype=np.float32)
    v[0] = signal
    if rng is not None:
        v[1:] += rng.normal(scale=0.01, size=dim - 1).astype(np.float32)
    return v.tobytes()


def _seed_photos(db_path, n=40, seed=3, aggregate="signal"):
    """Insert n photos; component-0 of the embedding is the preference signal.

    aggregate="signal" makes aggregate track the signal (baseline strong);
    aggregate="noise" makes it uninformative (baseline ~50%).
    """
    rng = np.random.default_rng(seed)
    conn = sqlite3.connect(db_path)
    signals = {}
    for i in range(n):
        s = float(rng.uniform(0.2, 2.0))
        path = f'/r/p{i:03d}.jpg'
        signals[path] = s
        agg = s * 5.0 if aggregate == "signal" else float(rng.uniform(1, 9))
        conn.execute(
            f"INSERT INTO photos (path, filename, clip_embedding, aggregate, {_METRIC_COLS}) "
            f"VALUES (?, ?, ?, ?, {_METRIC_VALS})",
            (path, f'p{i:03d}.jpg', _emb_bytes(s, rng=rng), agg),
        )
    conn.commit()
    conn.close()
    return signals


def _add_comparisons(db_path, signals, count=60, seed=11, by="signal"):
    """Pairs whose winner is decided by the embedding signal (or by aggregate)."""
    rng = np.random.default_rng(seed)
    paths = list(signals)
    conn = sqlite3.connect(db_path)
    added = 0
    while added < count:
        ia, ib = rng.choice(len(paths), size=2, replace=False)
        pa, pb = paths[ia], paths[ib]
        winner_path = pa if signals[pa] > signals[pb] else pb
        winner = 'a' if winner_path == pa else 'b'
        cur = conn.execute(
            "INSERT OR IGNORE INTO comparisons (photo_a_path, photo_b_path, winner, source) "
            "VALUES (?, ?, ?, 'vote')",
            (pa, pb, winner),
        )
        added += cur.rowcount
    conn.commit()
    conn.close()


@pytest.fixture()
def ranker_db(tmp_path):
    db_path = str(tmp_path / "ranker.db")
    init_database(db_path)
    return db_path


def _learned_count(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM learned_scores WHERE learned_score IS NOT NULL"
        ).fetchone()[0]
    finally:
        conn.close()


# --- integration tests (steps 3-4) ---

def test_too_few_comparisons_returns_error(ranker_db):
    signals = _seed_photos(ranker_db, n=20, aggregate="noise")
    _add_comparisons(ranker_db, signals, count=10)
    result = pr.train_ranker(ranker_db)
    assert 'error' in result
    assert result['n_pairs'] < pr.MIN_COMPARISONS
    assert _learned_count(ranker_db) == 0


def test_embedding_signal_beats_baseline_and_writes(ranker_db):
    # Winner decided by embedding signal; aggregate is uninformative (~50% baseline).
    signals = _seed_photos(ranker_db, n=40, aggregate="noise")
    _add_comparisons(ranker_db, signals, count=80)
    result = pr.train_ranker(ranker_db, min_improvement_pp=2.0)
    assert 'error' not in result
    assert result['cv_accuracy'] > 80.0
    assert result['cv_accuracy'] - result['baseline_accuracy'] >= 2.0
    assert result['gated'] is False
    assert result['written'] > 0
    assert _learned_count(ranker_db) == result['written']


def test_gate_blocks_when_no_improvement_over_aggregate(ranker_db):
    # Winner perfectly tracks aggregate -> baseline ~100%, ranker can't beat it -> gated.
    signals = _seed_photos(ranker_db, n=40, aggregate="signal")
    _add_comparisons(ranker_db, signals, count=80)
    result = pr.train_ranker(ranker_db, min_improvement_pp=2.0)
    assert result.get('gated') is True
    assert result['written'] == 0
    assert _learned_count(ranker_db) == 0


def test_force_writes_despite_gate(ranker_db):
    signals = _seed_photos(ranker_db, n=40, aggregate="signal")
    _add_comparisons(ranker_db, signals, count=80)
    result = pr.train_ranker(ranker_db, min_improvement_pp=2.0, force=True)
    assert result['gated'] is False
    assert result['written'] > 0
    assert _learned_count(ranker_db) > 0


# --- inference scan: narrow columns, streamed rows (issue #76) ---

def test_scoring_columns_exclude_unused_blobs(ranker_db):
    """The inference scan must not pull thumbnails it never reads.

    Regression: _collect_scored ran SELECT * and materialized every row, so a
    ~126k-photo library dragged ~5.9 GB of thumbnail BLOBs into RAM on a
    background thread inside the viewer process.
    """
    conn = sqlite3.connect(ranker_db)
    try:
        cols = pr._scoring_columns(conn)
        all_cols = {r[1] for r in conn.execute("PRAGMA table_info(photos)")}
    finally:
        conn.close()

    assert 'thumbnail' not in cols
    assert 'histogram_data' not in cols
    assert 'caption_embedding' not in cols
    # Everything else survives: the feature builder reads config-driven columns,
    # so an allow-list would silently drop one the moment a filter named it.
    assert set(cols) == all_cols - set(pr._UNUSED_BLOB_COLS)
    assert 'clip_embedding' in cols, "the embedding IS the feature"


def test_collect_scored_matches_a_select_star_scan(ranker_db):
    """Narrowing the column list must not change a single score."""
    _seed_photos(ranker_db, n=25)

    def raw_fn(row, emb):
        return float(emb[0]) + float(row['aggregate'] or 0.0)

    narrow = pr._collect_scored(ranker_db, emb_dim=16, raw_fn=raw_fn)

    conn = sqlite3.connect(ranker_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM photos WHERE clip_embedding IS NOT NULL")]
    finally:
        conn.close()
    from utils.embedding import bytes_to_normalized_embedding
    expected = [(r['path'], float(raw_fn(r, bytes_to_normalized_embedding(r['clip_embedding']))))
                for r in rows]

    assert narrow == expected


# --- write path: chunked commits (issue #76) ---

def _scored_rows(n):
    return [(f'/r/p{i:03d}.jpg', float(i)) for i in range(n)]


def test_persist_scores_commits_in_chunks(ranker_db, monkeypatch):
    """One transaction over the whole library holds SQLite's write lock.

    Regression: DELETE + N inserts + a full-table NULL sweep + N per-row updates
    committed once, so an interactive rating write waited out busy_timeout and
    500'd. Committing in slices releases the lock between them.
    """
    _seed_photos(ranker_db, n=12)
    monkeypatch.setattr(pr, "_WRITE_CHUNK", 3)

    commits = {"n": 0}
    real_connection = pr.get_connection

    from contextlib import contextmanager

    class _CountingConn:
        """sqlite3.Connection.commit is read-only, so proxy the connection."""

        def __init__(self, conn):
            self._conn = conn

        def __getattr__(self, name):
            return getattr(self._conn, name)

        def commit(self):
            commits["n"] += 1
            return self._conn.commit()

    @contextmanager
    def counting_connection(db_path, *args, **kwargs):
        with real_connection(db_path, *args, **kwargs) as conn:
            yield _CountingConn(conn)

    monkeypatch.setattr(pr, "get_connection", counting_connection)
    written = pr._persist_scores(ranker_db, _scored_rows(12), None, None, n_pairs=7)

    assert written == 12
    # 1 delete + 4 insert slices + at least one mirror slice.
    assert commits["n"] >= 6, f"expected several commits, got {commits['n']}"


def test_persist_scores_result_matches_a_single_transaction(ranker_db):
    """Chunking is a locking change only — the stored rows must be identical."""
    _seed_photos(ranker_db, n=12)
    scored = _scored_rows(12)
    pr._persist_scores(ranker_db, scored, None, None, n_pairs=7)

    conn = sqlite3.connect(ranker_db)
    try:
        stored = dict(conn.execute(
            "SELECT photo_path, learned_score FROM learned_scores").fetchall())
        mirrored = dict(conn.execute(
            "SELECT path, learned_score FROM photos WHERE learned_score IS NOT NULL").fetchall())
    finally:
        conn.close()

    # Percentile-normalized 0..10 over the rank order, exactly as before.
    expected = {path: 10.0 * i / 11 for i, (path, _) in enumerate(scored)}
    assert stored == pytest.approx(expected)
    assert mirrored == pytest.approx(expected)


def test_mirror_clears_scores_photos_no_longer_have(ranker_db):
    """The set-based mirror replaces a full-table NULL sweep — it must still clear."""
    _seed_photos(ranker_db, n=12)
    pr._persist_scores(ranker_db, _scored_rows(12), None, None, n_pairs=7)
    # Second run scores only half the library; the rest must go back to NULL.
    pr._persist_scores(ranker_db, _scored_rows(6), None, None, n_pairs=7)

    conn = sqlite3.connect(ranker_db)
    try:
        non_null = conn.execute(
            "SELECT COUNT(*) FROM photos WHERE learned_score IS NOT NULL").fetchone()[0]
    finally:
        conn.close()
    assert non_null == 6, "photos dropped from the ranker must not keep a stale score"


def test_mirror_ignores_rows_from_another_scope(ranker_db):
    """A per-user row must not leak into the global photos.learned_score.

    photo_path is the whole primary key of learned_scores, so a photo carries at
    most one row across all scopes. The global mirror therefore has to repeat the
    (category IS NULL AND user_id IS NULL) predicate, or a leftover per-user row
    would be mirrored as if it were the global score.
    """
    _seed_photos(ranker_db, n=12)
    conn = sqlite3.connect(ranker_db)
    try:
        conn.execute(
            "INSERT INTO learned_scores (photo_path, learned_score, comparison_count, "
            "category, updated_at, user_id) VALUES (?, 9.9, 1, NULL, 'now', 'alice')",
            ('/r/p011.jpg',))
        conn.commit()
    finally:
        conn.close()

    # Global training scores only the first 6 photos; p011 stays alice-only.
    pr._persist_scores(ranker_db, _scored_rows(6), None, None, n_pairs=7)

    conn = sqlite3.connect(ranker_db)
    try:
        leaked = conn.execute(
            "SELECT learned_score FROM photos WHERE path = ?", ('/r/p011.jpg',)).fetchone()[0]
    finally:
        conn.close()
    assert leaked is None, "another scope's score leaked into the global mirror"
