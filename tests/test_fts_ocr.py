"""Part A: ocr_text is part of the covering FTS5 schema and --rebuild-fts
indexes it so OCR text becomes searchable via photos_fts MATCH.
"""

import sqlite3

from db.fts import rebuild_fts
from db.schema import (
    PHOTOS_FTS_COLUMNS,
    fts_schema_is_current,
    init_database,
)


def test_ocr_text_is_a_covering_fts_column():
    assert "ocr_text" in PHOTOS_FTS_COLUMNS


def test_rebuild_fts_indexes_ocr_text(tmp_path):
    db_path = str(tmp_path / "f.db")
    init_database(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO photos (path, filename, ocr_text) VALUES (?, ?, ?)",
        ("/p/sign.jpg", "sign.jpg", "DANGER high voltage keep out"),
    )
    conn.execute(
        "INSERT INTO photos (path, filename, ocr_text) VALUES (?, ?, ?)",
        ("/p/plain.jpg", "plain.jpg", None),
    )
    conn.commit()
    conn.close()

    rebuild_fts(db_path)

    conn = sqlite3.connect(db_path)
    # The on-disk FTS schema must include ocr_text after rebuild.
    fts_cols = {r[1] for r in conn.execute("PRAGMA table_info(photos_fts)")}
    assert "ocr_text" in fts_cols

    rows = conn.execute(
        "SELECT path FROM photos_fts WHERE photos_fts MATCH ?",
        ("voltage",),
    ).fetchall()
    conn.close()

    paths = {r[0] for r in rows}
    assert paths == {"/p/sign.jpg"}


def test_outdated_fts_schema_detected_when_ocr_text_missing(tmp_path):
    """A pre-ocr_text photos_fts is detected as outdated so init/rebuild recreates it."""
    db_path = str(tmp_path / "old.db")
    init_database(db_path)

    conn = sqlite3.connect(db_path)
    # Simulate the older covering schema (no ocr_text column).
    for trig in ("photos_fts_ai", "photos_fts_ad", "photos_fts_au"):
        conn.execute(f"DROP TRIGGER IF EXISTS {trig}")
    conn.execute("DROP TABLE IF EXISTS photos_fts")
    conn.execute(
        """CREATE VIRTUAL TABLE photos_fts USING fts5(
            path UNINDEXED, filename, caption, caption_translated,
            tags, camera_model, lens_model, category,
            content='photos', content_rowid='rowid'
        )"""
    )
    conn.commit()
    assert fts_schema_is_current(conn) is False
    conn.close()

    # rebuild_fts drops + recreates with the current (ocr_text-bearing) schema.
    rebuild_fts(db_path)
    conn = sqlite3.connect(db_path)
    fts_cols = {r[1] for r in conn.execute("PRAGMA table_info(photos_fts)")}
    conn.close()
    assert "ocr_text" in fts_cols
