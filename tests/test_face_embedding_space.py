"""Embedding-space guard for face clustering.

Face embeddings from different recognition models are not comparable. Every face
is tagged with `embedding_model`; clustering loads only the active space so a
future model swap can't silently corrupt clusters by mixing vector spaces.
"""

import sqlite3

import numpy as np

from db.schema import init_database
from faces.clusterer import ACTIVE_EMBEDDING_MODEL, FaceClusterer


def _emb():
    return np.zeros(512, dtype=np.float32).tobytes()


def _seed_face(conn, path, model="__default__"):
    conn.execute("INSERT OR IGNORE INTO photos(path) VALUES (?)", (path,))
    n = conn.execute(
        "SELECT COUNT(*) FROM faces WHERE photo_path = ?", (path,)
    ).fetchone()[0]
    if model == "__default__":
        # Insert WITHOUT the column so the schema DEFAULT applies.
        conn.execute(
            "INSERT INTO faces(photo_path, face_index, embedding) VALUES (?, ?, ?)",
            (path, n, _emb()),
        )
    else:
        conn.execute(
            "INSERT INTO faces(photo_path, face_index, embedding, embedding_model) "
            "VALUES (?, ?, ?, ?)",
            (path, n, _emb(), model),
        )


def test_schema_default_tags_new_faces(tmp_path):
    """A face inserted without embedding_model gets the active-space default."""
    db = str(tmp_path / "s.db")
    init_database(db)
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys = ON")
    _seed_face(conn, "p/a.jpg")
    conn.commit()
    row = conn.execute("SELECT embedding_model FROM faces").fetchone()
    conn.close()
    assert row[0] == ACTIVE_EMBEDDING_MODEL


def test_load_embeddings_excludes_foreign_space(tmp_path):
    """Only active-space + NULL-tagged faces load; a foreign space is excluded."""
    db = str(tmp_path / "f.db")
    init_database(db)
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys = ON")
    _seed_face(conn, "p/active.jpg", ACTIVE_EMBEDDING_MODEL)
    _seed_face(conn, "p/legacy.jpg", None)          # NULL == legacy ArcFace
    _seed_face(conn, "p/adaface.jpg", "adaface_test")  # incompatible space
    conn.commit()
    conn.close()

    face_ids, embeddings = FaceClusterer(db).load_embeddings()
    assert len(face_ids) == 2            # active + legacy NULL, NOT adaface
    assert embeddings.shape == (2, 512)


def test_load_embeddings_warns_on_mixed_space(tmp_path, caplog):
    """Excluding foreign-space faces emits a warning (no silent drop)."""
    db = str(tmp_path / "w.db")
    init_database(db)
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys = ON")
    _seed_face(conn, "p/active.jpg", ACTIVE_EMBEDDING_MODEL)
    _seed_face(conn, "p/x1.jpg", "adaface_test")
    _seed_face(conn, "p/x2.jpg", "adaface_test")
    conn.commit()
    conn.close()

    with caplog.at_level("WARNING", logger="facet.face_cluster"):
        FaceClusterer(db).load_embeddings()
    messages = [r.getMessage() for r in caplog.records]
    assert any("non-active embedding space" in m for m in messages)
    assert any("adaface_test" in m for m in messages)


def _unit_embedding():
    vec = np.zeros(512, dtype=np.float32)
    vec[0] = 1.0
    return vec


def test_incremental_noise_face_stays_with_named_person(tmp_path):
    """A named person's face relabelled as HDBSCAN noise is not orphaned."""
    db = str(tmp_path / "noise.db")
    init_database(db)
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("INSERT INTO photos(path) VALUES ('p/alice.jpg')")
    vec = _unit_embedding()
    emb = vec.tobytes()
    cur = conn.execute(
        "INSERT INTO persons(name, face_count, centroid, auto_clustered) "
        "VALUES ('Alice', 2, ?, 0)",
        (emb,),
    )
    alice_id = cur.lastrowid
    face_ids = []
    for idx in range(2):
        c = conn.execute(
            "INSERT INTO faces(photo_path, face_index, embedding, embedding_model, person_id) "
            "VALUES ('p/alice.jpg', ?, ?, ?, ?)",
            (idx, emb, ACTIVE_EMBEDDING_MODEL, alice_id),
        )
        face_ids.append(c.lastrowid)
    conn.execute(
        "UPDATE persons SET representative_face_id = ? WHERE id = ?",
        (face_ids[0], alice_id),
    )
    conn.commit()
    conn.close()

    clusterer = FaceClusterer(db)
    embeddings = np.array([vec, vec], dtype=np.float32)
    face_to_cluster = {face_ids[0]: 0, face_ids[1]: -1}
    clusterer._update_database(face_to_cluster, embeddings, face_ids, force=False)

    conn = sqlite3.connect(db)
    rows = dict(conn.execute("SELECT id, person_id FROM faces").fetchall())
    face_count = conn.execute(
        "SELECT face_count FROM persons WHERE id = ?", (alice_id,)
    ).fetchone()[0]
    conn.close()
    assert rows[face_ids[1]] == alice_id
    assert rows[face_ids[0]] == alice_id
    assert face_count == 2


def test_migration_backfills_existing_faces(tmp_path):
    """Adding embedding_model to an old faces table backfills rows to the default."""
    db = str(tmp_path / "m.db")
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE photos (path TEXT PRIMARY KEY);
        CREATE TABLE faces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            photo_path TEXT NOT NULL,
            face_index INTEGER NOT NULL,
            embedding BLOB NOT NULL
        );
        """
    )
    conn.execute("INSERT INTO photos(path) VALUES ('p/old.jpg')")
    conn.execute(
        "INSERT INTO faces(photo_path, face_index, embedding) VALUES ('p/old.jpg', 0, ?)",
        (_emb(),),
    )
    conn.commit()
    conn.close()

    # init_database migrates the existing faces table, adding embedding_model.
    init_database(db)

    conn = sqlite3.connect(db)
    row = conn.execute("SELECT embedding_model FROM faces").fetchone()
    conn.close()
    assert row[0] == ACTIVE_EMBEDDING_MODEL
