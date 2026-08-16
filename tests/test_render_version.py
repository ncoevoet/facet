"""The render-version stamp that drives the thumbnail-migration banner.

A stored thumbnail is baked at scan time, so the RAW display-profile fix left
every existing row rendering the old, exposure-equalizing way.
``photos.render_version`` is what says which rows are still on it; these tests
pin the three things that make the stamp trustworthy — a rescanned row ends up
stamped current rather than NULL, a render that comes back black never
overwrites a good thumbnail, and the count the banner reads comes from the
statistics cache rather than a scan of ``photos`` per request.
"""

import sqlite3
import sys
from unittest import mock

import pytest

from db.render_version import CURRENT_RENDER_VERSION, count_pending_render
from db.schema import init_database

_RAW_PATH = '/photos/raw/frame.CR3'


@pytest.fixture()
def library_db(tmp_path):
    """A schema-current database holding one unstamped RAW row."""
    db_path = str(tmp_path / 'library.db')
    init_database(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO photos (path, filename, thumbnail, histogram_data) VALUES (?, ?, ?, ?)",
        (_RAW_PATH, 'frame.CR3', b'old-thumb', b'\x00' * 1024))
    conn.commit()
    conn.close()
    return db_path


# ---------------------------------------------------------------------------
# 1. The stamp survives the writer that rewrites `photos` wholesale
# ---------------------------------------------------------------------------

class TestScanStampsCurrentVersion:
    """``save_photos_batch`` INSERT-OR-REPLACEs the row, so an unstamped column
    would be silently NULLed on every rescan. The stamp is derived state that
    must be rewritten with the thumbnail it describes."""

    def test_scanned_row_is_stamped_current_not_null(self, tmp_path):
        from tests.test_rescan_preservation import _base_result
        from processing.scorer import Facet

        db_path = str(tmp_path / 'scan.db')
        init_database(db_path)
        facet = Facet.__new__(Facet)
        facet.db_path = db_path
        with mock.patch('processing.scorer.generate_photo_thumbnail', return_value=b'thumb'), \
             mock.patch('processing.scorer.thumbnail_source', return_value=None), \
             mock.patch('processing.scorer.get_plugin_manager', return_value=None, create=True):
            facet.save_photos_batch([(_base_result(_RAW_PATH, 7.0), None)])

        conn = sqlite3.connect(db_path)
        stamp = conn.execute(
            "SELECT render_version FROM photos WHERE path = ?", (_RAW_PATH,)).fetchone()[0]
        conn.close()
        assert stamp == CURRENT_RENDER_VERSION

    def test_rescan_restamps_a_row_written_before_the_stamp_existed(self, library_db):
        from tests.test_rescan_preservation import _base_result
        from processing.scorer import Facet

        conn = sqlite3.connect(library_db)
        assert conn.execute("SELECT render_version FROM photos").fetchone()[0] is None
        assert count_pending_render(conn) == 1
        conn.close()

        facet = Facet.__new__(Facet)
        facet.db_path = library_db
        with mock.patch('processing.scorer.generate_photo_thumbnail', return_value=b'new-thumb'), \
             mock.patch('processing.scorer.thumbnail_source', return_value=None), \
             mock.patch('processing.scorer.get_plugin_manager', return_value=None, create=True):
            facet.save_photos_batch([(_base_result(_RAW_PATH, 8.0), None)])

        conn = sqlite3.connect(library_db)
        assert conn.execute("SELECT render_version FROM photos").fetchone()[0] == CURRENT_RENDER_VERSION
        assert count_pending_render(conn) == 0
        conn.close()

    def test_a_restricted_pass_does_not_stamp_an_existing_row(self):
        """A ``--recompute-*`` pass rebuilds no thumbnail, so it must not claim one."""
        from processing.scorer import _photos_partial_upsert

        sql = _photos_partial_upsert(('aesthetic',))
        assert 'render_version' in sql.split('ON CONFLICT')[0]
        assert 'render_version' not in sql.split('ON CONFLICT')[1]


# ---------------------------------------------------------------------------
# 2. A decode that "succeeds" into a black frame must not overwrite anything
# ---------------------------------------------------------------------------

def _black_frame(height=1200, width=1800):
    import numpy as np
    from PIL import Image

    return Image.fromarray(np.zeros((height, width, 3), dtype=np.uint8))


class TestDegenerateDecodeIsRefused:
    """LibRaw zero-fills a severely truncated Panasonic RW2 and returns a valid,
    full-size, entirely black image — it does NOT return None. The CLI migration
    is unattended, which is the worst place for that to pass unnoticed."""

    def test_the_cli_refresh_discards_a_black_render(self, monkeypatch, caplog):
        import facet

        monkeypatch.setattr('utils.load_display_image',
                            lambda path, sequence_kind=None: _black_frame())
        with caplog.at_level('WARNING'):
            blob = facet._display_thumbnail_bytes('/disk/frame.RW2', 640, 80)
        assert blob is None
        assert any('black' in r.message for r in caplog.records), caplog.text

    def test_a_real_render_is_not_mistaken_for_a_black_one(self, monkeypatch):
        import numpy as np
        from PIL import Image

        import facet

        scene = np.zeros((1200, 1800, 3), dtype=np.uint8)
        scene[600:620, 900:920] = 255
        monkeypatch.setattr('utils.load_display_image',
                            lambda path, sequence_kind=None: Image.fromarray(scene))
        assert facet._display_thumbnail_bytes('/disk/frame.CR3', 640, 80) is not None


class TestThumbnailSignalPredicate:

    def test_a_zero_filled_frame_has_no_signal(self):
        from utils import generate_photo_thumbnail, thumbnail_has_signal

        assert thumbnail_has_signal(generate_photo_thumbnail(_black_frame(2000, 3000))) is False

    def test_a_night_frame_with_one_small_highlight_has_signal(self):
        """The predicate reads the MAXIMUM, so an intentionally dark photo passes."""
        import numpy as np
        from PIL import Image

        from utils import generate_photo_thumbnail, thumbnail_has_signal

        scene = np.zeros((2000, 3000, 3), dtype=np.uint8)
        scene[990:1010, 1490:1510] = 255
        assert thumbnail_has_signal(generate_photo_thumbnail(Image.fromarray(scene))) is True

    def test_missing_bytes_have_no_signal(self):
        from utils import thumbnail_has_signal

        assert thumbnail_has_signal(None) is False


# ---------------------------------------------------------------------------
# 3. The status count is served from cache, never from a scan per request
# ---------------------------------------------------------------------------

class TestMigrationStatus:

    def test_config_reports_the_pending_count(self, client, monkeypatch):
        monkeypatch.setattr('db.stats_cache.get_pending_render_count', lambda *a, **k: 42)
        payload = client.get('/api/config').json()
        assert payload['render_migration'] == {'pending': 42}

    def test_a_fresh_cache_entry_answers_without_touching_photos(self, library_db, monkeypatch):
        from db.stats_cache import PENDING_RENDER_KEY, get_pending_render_count
        import db.render_version as render_version_mod

        conn = sqlite3.connect(library_db)
        conn.execute("INSERT OR REPLACE INTO stats_cache (key, value, updated_at) "
                     "VALUES (?, '5', ?)", (PENDING_RENDER_KEY, _now()))
        conn.commit()
        conn.close()

        def _forbidden(_conn):
            raise AssertionError("the cached count must not rescan photos")

        monkeypatch.setattr(render_version_mod, 'count_pending_render', _forbidden)
        monkeypatch.setattr('db.stats_cache.count_pending_render', _forbidden)
        assert get_pending_render_count(library_db) == 5

    def test_a_stale_entry_is_recomputed_and_re_cached(self, library_db):
        from db.stats_cache import PENDING_RENDER_KEY, get_pending_render_count

        conn = sqlite3.connect(library_db)
        conn.execute("INSERT OR REPLACE INTO stats_cache (key, value, updated_at) "
                     "VALUES (?, '999', 0)", (PENDING_RENDER_KEY,))
        conn.commit()
        conn.close()

        assert get_pending_render_count(library_db) == 1
        conn = sqlite3.connect(library_db)
        assert conn.execute("SELECT value FROM stats_cache WHERE key = ?",
                            (PENDING_RENDER_KEY,)).fetchone()[0] == '1'
        conn.close()


def _now():
    import time

    return time.time()


@pytest.fixture(autouse=True)
def _drop_stub_modules():
    yield
    sys.modules.pop('rawpy', None)
