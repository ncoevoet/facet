"""Incremental re-clustering must not orphan API-created / named persons that
carry a NULL centroid.

Persons created through the viewer (create / split / assign) are inserted with
``centroid = NULL`` — only the clusterer ever writes a centroid. The old
``_load_existing_persons`` selected ``WHERE centroid IS NOT NULL``, so those
persons were dropped from the preservation set: every incremental run then did
``UPDATE faces SET person_id = NULL`` and never re-attached them, and the
end-of-run cleanup deleted the now-empty named person. Reproduced live as
"Alice: 6 faces -> 0".

These tests drive ``FaceClusterer._update_database`` directly with a
hand-built cluster labelling so they are deterministic (no HDBSCAN) and need no
image files, and assert the named/NULL-centroid person survives with all her
faces via the previous-owner history rule — through both the clustered and the
noise re-labelling paths.
"""

import sqlite3

import numpy as np
import pytest

from db import init_database
from faces.clusterer import FaceClusterer

DIM = 512
ACTIVE_MODEL = "arcface_buffalo_l"


def _unit_lobe(seed, n, dim=DIM, scale=0.02):
    """n tight, L2-normalized vectors clustered around one random axis."""
    rng = np.random.default_rng(seed)
    axis = rng.normal(size=dim)
    axis /= np.linalg.norm(axis)
    pts = axis + rng.normal(scale=scale, size=(n, dim))
    return (pts / np.linalg.norm(pts, axis=1, keepdims=True)).astype(np.float32)


def _seed_person(conn, pid, name, centroid=None, auto_clustered=0, face_count=0):
    conn.execute(
        "INSERT INTO persons(id, name, centroid, auto_clustered, face_count) "
        "VALUES (?, ?, ?, ?, ?)",
        (pid, name, centroid, auto_clustered, face_count),
    )


def _seed_faces(conn, person_id, vectors, path_prefix):
    """Insert one face per row of ``vectors`` owned by ``person_id``.

    Returns the parallel ``(face_ids, embeddings)`` the clusterer expects.
    """
    face_ids = []
    for i, vec in enumerate(vectors):
        path = f"{path_prefix}{i}.jpg"
        conn.execute("INSERT OR IGNORE INTO photos(path) VALUES (?)", (path,))
        cur = conn.execute(
            "INSERT INTO faces(photo_path, face_index, embedding, person_id, "
            "confidence, embedding_model) VALUES (?, ?, ?, ?, ?, ?)",
            (path, i, sqlite3.Binary(vec.tobytes()), person_id, 0.9, ACTIVE_MODEL),
        )
        face_ids.append(cur.lastrowid)
    return face_ids, np.asarray(vectors, dtype=np.float32)


@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "faces.db"
    init_database(str(p))
    return str(p)


def _owner_counts(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return dict(
            conn.execute(
                "SELECT person_id, COUNT(*) FROM faces GROUP BY person_id"
            ).fetchall()
        )
    finally:
        conn.close()


def _person(db_path, pid):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute("SELECT * FROM persons WHERE id = ?", (pid,)).fetchone()
    finally:
        conn.close()


class TestNullCentroidPersonSurvivesReclustering:
    def test_clustered_faces_are_handed_back_by_history(self, db_path):
        """The exact repro: Alice is named, has a NULL centroid and 6 faces.

        HDBSCAN would re-derive those 6 as a fresh cluster; because Alice has no
        centroid the similarity rule cannot match it, so only the previous-owner
        history rule can keep them. Before the fix Alice was not even in the
        preservation set, so all 6 faces were orphaned and she was deleted.
        """
        conn = sqlite3.connect(db_path)
        _seed_person(conn, 1, name="Alice", centroid=None, auto_clustered=0)
        vectors = _unit_lobe(seed=7, n=6)
        face_ids, embeddings = _seed_faces(conn, 1, vectors, "alice/")
        conn.commit()
        conn.close()

        clusterer = FaceClusterer(db_path)
        # Whole lobe re-derived as one new cluster (label 0), as HDBSCAN would.
        face_to_cluster = {fid: 0 for fid in face_ids}
        clusterer._update_database(face_to_cluster, embeddings, face_ids, force=False)

        assert _person(db_path, 1) is not None, "named person was deleted"
        assert _owner_counts(db_path) == {1: 6}, "faces orphaned off their named person"

        alice = _person(db_path, 1)
        assert alice["face_count"] == 6
        # Bonus: the run should have given Alice a real centroid.
        assert alice["centroid"] is not None

    def test_noise_relabelled_faces_are_restored(self, db_path):
        """Same person, but every face is re-labelled noise (-1) this run.

        The noise-restore path must re-attach them to their preserved person.
        """
        conn = sqlite3.connect(db_path)
        _seed_person(conn, 1, name="Bob", centroid=None, auto_clustered=0)
        vectors = _unit_lobe(seed=8, n=5)
        face_ids, embeddings = _seed_faces(conn, 1, vectors, "bob/")
        conn.commit()
        conn.close()

        clusterer = FaceClusterer(db_path)
        face_to_cluster = {fid: -1 for fid in face_ids}
        clusterer._update_database(face_to_cluster, embeddings, face_ids, force=False)

        assert _person(db_path, 1) is not None
        assert _owner_counts(db_path) == {1: 5}


class TestEmptyPreservedPersonCleanup:
    def test_unnamed_auto_husk_deleted_named_kept(self, db_path):
        """After a re-cluster leaves preserved persons with zero faces, an
        unnamed auto-clustered person is a husk and must be dropped, while a
        named person is kept even when momentarily empty."""
        conn = sqlite3.connect(db_path)
        _seed_person(conn, 1, name="Named", centroid=None, auto_clustered=0)
        _seed_person(conn, 2, name=None, centroid=None, auto_clustered=1)
        conn.commit()
        conn.close()

        clusterer = FaceClusterer(db_path)
        # A run that assigns nothing (both preserved persons end with 0 faces).
        clusterer._update_database({}, np.empty((0, DIM), np.float32), [], force=False)

        assert _person(db_path, 2) is None, "empty unnamed auto husk should be deleted"
        assert _person(db_path, 1) is not None, "named person must be kept even if empty"
