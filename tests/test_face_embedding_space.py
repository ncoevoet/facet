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
