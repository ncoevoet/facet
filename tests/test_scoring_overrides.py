"""Tests for db.scoring_overrides and the photo_scoring_overrides schema.

photo_scoring_overrides is a side table, not columns on `photos`, because
save_photo/save_photos_batch write photos via INSERT OR REPLACE
(processing/scorer.py), which would silently wipe any new column added
directly on that row on the next rescan. These tests cover schema migration
idempotency and the get/set/clear CRUD helpers.
"""

import sqlite3

import pytest

from db.connection import get_connection
from db.schema import init_database, PHOTO_SCORING_OVERRIDES_COLUMNS
from db.scoring_overrides import (
    get_photo_scoring_overrides, set_photo_scoring_override, clear_photo_scoring_override,
)


@pytest.fixture
def db_path(tmp_path):
    db = str(tmp_path / "overrides.db")
    init_database(db)
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO photos (path) VALUES ('/a.jpg'), ('/b.jpg')")
    conn.commit()
    conn.close()
    return db


class TestSchemaMigration:
    def test_init_database_is_idempotent(self, tmp_path):
        db = str(tmp_path / "idempotent.db")
        init_database(db)
        init_database(db)  # second run must not raise or duplicate columns

        conn = sqlite3.connect(db)
        cols = [row[1] for row in conn.execute("PRAGMA table_info(photo_scoring_overrides)")]
        conn.close()
        assert cols == [name for name, _ in PHOTO_SCORING_OVERRIDES_COLUMNS]

    def test_albums_gains_scoring_context_column(self, tmp_path):
        db = str(tmp_path / "albums.db")
        init_database(db)
        conn = sqlite3.connect(db)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(albums)")}
        conn.close()
        assert 'scoring_context' in cols

    def test_photo_scoring_overrides_cascades_on_photo_delete(self, tmp_path):
        db = str(tmp_path / "cascade.db")
        init_database(db)
        conn = sqlite3.connect(db)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("INSERT INTO photos (path) VALUES ('/a.jpg')")
        conn.execute(
            "INSERT INTO photo_scoring_overrides (photo_path, category_override) VALUES ('/a.jpg', 'sports')"
        )
        conn.commit()
        conn.execute("DELETE FROM photos WHERE path = '/a.jpg'")
        conn.commit()
        remaining = conn.execute("SELECT COUNT(*) FROM photo_scoring_overrides").fetchone()[0]
        conn.close()
        assert remaining == 0


class TestGetSetClearOverride:
    def test_set_then_get_round_trips(self, db_path):
        set_photo_scoring_override(db_path, '/a.jpg', category_override='sports', source='manual')
        overrides = get_photo_scoring_overrides(db_path)
        assert overrides['/a.jpg'] == {'scoring_context': None, 'category_override': 'sports'}

    def test_set_preserves_the_other_field(self, db_path):
        set_photo_scoring_override(db_path, '/a.jpg', category_override='sports')
        set_photo_scoring_override(db_path, '/a.jpg', scoring_context='action_stage')
        overrides = get_photo_scoring_overrides(db_path)
        assert overrides['/a.jpg']['category_override'] == 'sports'
        assert overrides['/a.jpg']['scoring_context'] == 'action_stage'

    def test_paths_filter_restricts_the_lookup(self, db_path):
        set_photo_scoring_override(db_path, '/a.jpg', category_override='sports')
        set_photo_scoring_override(db_path, '/b.jpg', category_override='wildlife')
        overrides = get_photo_scoring_overrides(db_path, paths=['/a.jpg'])
        assert list(overrides.keys()) == ['/a.jpg']

    def test_empty_paths_list_returns_empty(self, db_path):
        set_photo_scoring_override(db_path, '/a.jpg', category_override='sports')
        assert get_photo_scoring_overrides(db_path, paths=[]) == {}

    def test_no_paths_argument_loads_every_override(self, db_path):
        set_photo_scoring_override(db_path, '/a.jpg', category_override='sports')
        set_photo_scoring_override(db_path, '/b.jpg', category_override='wildlife')
        overrides = get_photo_scoring_overrides(db_path)
        assert set(overrides.keys()) == {'/a.jpg', '/b.jpg'}

    def test_clear_one_field_keeps_the_row(self, db_path):
        set_photo_scoring_override(
            db_path, '/a.jpg', category_override='sports', scoring_context='action_stage'
        )
        clear_photo_scoring_override(db_path, '/a.jpg', field='category_override')
        overrides = get_photo_scoring_overrides(db_path)
        assert overrides['/a.jpg']['category_override'] is None
        assert overrides['/a.jpg']['scoring_context'] == 'action_stage'

    def test_clear_last_field_deletes_the_row(self, db_path):
        set_photo_scoring_override(db_path, '/a.jpg', category_override='sports')
        clear_photo_scoring_override(db_path, '/a.jpg', field='category_override')
        assert get_photo_scoring_overrides(db_path) == {}

    def test_clear_rejects_unknown_field(self, db_path):
        set_photo_scoring_override(db_path, '/a.jpg', category_override='sports')
        with pytest.raises(ValueError):
            clear_photo_scoring_override(db_path, '/a.jpg', field='bogus')

    def test_open_connection_lets_caller_own_the_commit(self, db_path):
        with get_connection(db_path) as conn:
            set_photo_scoring_override(conn, '/a.jpg', category_override='sports')
            conn.commit()
        overrides = get_photo_scoring_overrides(db_path)
        assert overrides['/a.jpg']['category_override'] == 'sports'
