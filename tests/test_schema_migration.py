"""Tests for the PRAGMA user_version migration ladder (db/schema.py)."""

import sqlite3

from db.schema import PHOTOS_COLUMNS, SCHEMA_VERSION, init_database


def _build_v0_db(path):
    """A frozen pre-ladder DB: a minimal photos table, user_version=0."""
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE photos (path TEXT PRIMARY KEY, filename TEXT, "
        "aesthetic REAL, aggregate REAL)"
    )
    conn.execute(
        "INSERT INTO photos (path, filename, aesthetic, aggregate) "
        "VALUES ('/a.jpg', 'a.jpg', 5.0, 6.0)"
    )
    conn.execute("PRAGMA user_version = 0")
    conn.commit()
    conn.close()


def _user_version(path):
    conn = sqlite3.connect(path)
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


class TestSchemaMigrationLadder:
    def test_old_db_upgrades_and_keeps_data(self, tmp_path):
        db = str(tmp_path / "old.db")
        _build_v0_db(db)

        init_database(db)

        assert _user_version(db) == SCHEMA_VERSION
        conn = sqlite3.connect(db)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(photos)").fetchall()}
        row = conn.execute(
            "SELECT filename, aggregate FROM photos WHERE path = '/a.jpg'"
        ).fetchone()
        conn.close()
        # The additive sweep filled in every current column...
        assert {c[0] for c in PHOTOS_COLUMNS}.issubset(cols)
        # ...without disturbing existing data.
        assert row == ('a.jpg', 6.0)

    def test_fresh_db_is_stamped(self, tmp_path):
        db = str(tmp_path / "fresh.db")
        init_database(db)
        assert _user_version(db) == SCHEMA_VERSION

    def test_second_init_is_a_noop(self, tmp_path):
        db = str(tmp_path / "x.db")
        init_database(db)
        first = _user_version(db)
        init_database(db)
        assert first == _user_version(db) == SCHEMA_VERSION
