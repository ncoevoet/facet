"""Tests for the PRAGMA user_version migration ladder (db/schema.py)."""

import sqlite3

import pytest

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

    def test_pre_fts_db_gets_fts_rebuilt_on_init(self, tmp_path):
        db = str(tmp_path / "prefts.db")
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE photos (path TEXT PRIMARY KEY, filename TEXT, "
            "caption TEXT, aesthetic REAL, aggregate REAL)"
        )
        conn.execute(
            "INSERT INTO photos (path, filename, caption, aesthetic, aggregate) "
            "VALUES ('/a.jpg', 'a.jpg', 'a red bicycle', 5.0, 6.0)"
        )
        conn.execute("PRAGMA user_version = 0")
        conn.commit()
        conn.close()

        init_database(db)

        conn = sqlite3.connect(db)
        try:
            matched = conn.execute(
                "SELECT path FROM photos_fts WHERE photos_fts MATCH 'bicycle'"
            ).fetchall()
        finally:
            conn.close()
        assert matched == [('/a.jpg',)]


class _KilledDuringRebuild(BaseException):
    """A process kill: BaseException, so no `except Exception` on the way can swallow it."""


def _fts_library(path, fts_state):
    """300 captioned photos whose photos_fts is missing ('missing') or narrower ('outdated')."""
    init_database(path)
    conn = sqlite3.connect(path)
    conn.executemany(
        "INSERT INTO photos (path, filename, aggregate, caption) VALUES (?, ?, ?, ?)",
        [(f"/l/{i}.jpg", f"{i}.jpg", 5, f"zebra crossing number {i}") for i in range(300)])
    for trigger in ('photos_fts_ai', 'photos_fts_ad', 'photos_fts_au'):
        conn.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    conn.execute("DROP TABLE IF EXISTS photos_fts")
    if fts_state == 'outdated':
        # The pre-covering schema: path, caption, tags only.
        conn.execute("CREATE VIRTUAL TABLE photos_fts USING fts5(path UNINDEXED, caption, tags, "
                     "content='photos', content_rowid='rowid')")
    conn.commit()
    conn.close()


def _fts_matches(path, term):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM photos_fts WHERE photos_fts MATCH ?", (term,)).fetchone()[0]
    finally:
        conn.close()


@pytest.mark.parametrize("fts_state", ["missing", "outdated"])
def test_a_start_killed_during_the_fts_rebuild_never_commits_an_empty_index(
        tmp_path, monkeypatch, fts_state):
    """The FTS drop, CREATE and rebuild commit together. A start killed during the rebuild
    must not leave an empty photos_fts that the next start takes for current (text search
    would then find nothing until a manual --rebuild-fts)."""
    import db.schema as schema

    db = str(tmp_path / f"fts_{fts_state}.db")
    _fts_library(db, fts_state)

    class KillOnRebuild(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if "VALUES('rebuild')" in sql:
                raise _KilledDuringRebuild()
            return super().execute(sql, *args, **kwargs)

    real_connect = sqlite3.connect
    monkeypatch.setattr(schema.sqlite3, "connect",
                        lambda *a, **kw: real_connect(*a, factory=KillOnRebuild, **kw))
    with pytest.raises(_KilledDuringRebuild):
        init_database(db)
    monkeypatch.undo()

    # Nothing of the interrupted FTS step is committed: the table is as it was before.
    conn = sqlite3.connect(db)
    try:
        exists = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name = 'photos_fts'").fetchone()[0]
        columns = {r[1] for r in conn.execute("PRAGMA table_info(photos_fts)")}
    finally:
        conn.close()
    assert bool(exists) is (fts_state == 'outdated')
    if fts_state == 'outdated':
        assert columns == {'path', 'caption', 'tags'}

    init_database(db)  # the next start
    assert _fts_matches(db, 'zebra') == 300
def test_face_review_feedback_indexes_are_created_on_existing_databases(tmp_path):
    db = str(tmp_path / 'feedback-indexes.db')
    init_database(db)
    with sqlite3.connect(db) as conn:
        conn.execute('DROP INDEX idx_face_review_feedback_face')
        conn.execute('DROP INDEX idx_face_review_feedback_person')
    init_database(db)
    with sqlite3.connect(db) as conn:
        names = {row[1] for row in conn.execute('PRAGMA index_list(face_review_feedback)')}
        assert {'idx_face_review_feedback_face', 'idx_face_review_feedback_person'} <= names
