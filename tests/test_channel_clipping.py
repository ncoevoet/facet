"""Per-channel clipping: the stored columns, the backfill, and the gallery filter.

The invariant every test here defends is that NULL means *unknown*, never
*clean*. A library holds a long tail of rows whose histogram is still the
legacy luminance-only blob; those have no per-channel data to derive from, so
deriving 0% for them would state a fact nobody measured — and would make them
answer "show me photos with no clipping".

Mirrors tests/test_extended_iqa_gallery.py's harness for the endpoint half.
"""

import sqlite3
import struct
from contextlib import asynccontextmanager, contextmanager
from unittest import mock

import aiosqlite
import numpy as np
import pytest
from fastapi.testclient import TestClient

from api import create_app
from api.auth import get_optional_user
from api.db_helpers import PHOTO_OPTIONAL_COLS
from api.routers.gallery import SCORE_RANGE_COLUMNS
from db.maintenance import backfill_channel_clipping
from db.schema import init_database
from utils.histogram import HISTOGRAM_BINS, pack_histogram

CLIPPING_COLUMNS = ("channel_clip_shadow_pct", "channel_clip_highlight_pct")


def _blob(highlight_share=0.0, shadow_share=0.0, channel=1):
    """A current-format blob whose given channel clips by the requested share.

    ``channel`` indexes pack_histogram's arguments: 1=R, 2=G, 3=B.
    """
    total = 10000.0
    channels = [np.zeros(HISTOGRAM_BINS) for _ in range(4)]
    for counts in channels:
        counts[128] = total
    clipped = channels[channel]
    clipped[128] = total * (1 - highlight_share - shadow_share)
    clipped[255] = total * highlight_share
    clipped[0] = total * shadow_share
    return pack_histogram(*channels)


def _legacy_blob():
    counts = np.zeros(HISTOGRAM_BINS)
    counts[255] = 1.0
    return struct.pack('256f', *counts)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_clipping_columns_are_served_by_the_gallery():
    for col in CLIPPING_COLUMNS:
        assert col in PHOTO_OPTIONAL_COLS, f"{col} missing from PHOTO_OPTIONAL_COLS"


def test_clipping_columns_are_registered_as_range_filters():
    by_col = {c[0]: c for c in SCORE_RANGE_COLUMNS}
    assert by_col["channel_clip_shadow_pct"][1:3] == (
        "min_channel_clip_shadow", "max_channel_clip_shadow")
    assert by_col["channel_clip_highlight_pct"][1:3] == (
        "min_channel_clip_highlight", "max_channel_clip_highlight")


def test_the_backfill_flag_takes_the_library_lock():
    from facet import LIBRARY_JOB_ARGS

    assert 'backfill_clipping' in LIBRARY_JOB_ARGS


def test_the_scan_upsert_writes_the_columns():
    """A column absent from the INSERT list is silently NULLed on every rescan,
    which is exactly how this data would quietly disappear."""
    import inspect

    from processing.scorer import Facet

    source = inspect.getsource(Facet.save_photos_batch)
    for col in CLIPPING_COLUMNS:
        assert col in source, f"{col} missing from the photos upsert"
        assert f":{col}" in source, f"{col} has no bound parameter in the upsert"


# ---------------------------------------------------------------------------
# Backfill
# ---------------------------------------------------------------------------

@pytest.fixture()
def clipping_db(tmp_path):
    db_path = str(tmp_path / "clip.db")
    init_database(db_path)
    conn = sqlite3.connect(db_path)
    rows = [
        ("/c/blown.jpg", _blob(highlight_share=0.30, channel=3)),
        ("/c/mild.jpg", _blob(highlight_share=0.02, channel=1)),
        ("/c/crushed.jpg", _blob(shadow_share=0.12, channel=1)),
        ("/c/clean.jpg", _blob()),
        ("/c/legacy.jpg", _legacy_blob()),
        ("/c/nohist.jpg", None),
    ]
    for path, blob in rows:
        conn.execute(
            "INSERT INTO photos (path, filename, aggregate, histogram_data) VALUES (?, ?, 5.0, ?)",
            (path, path.rsplit('/', 1)[-1], blob))
    conn.commit()
    conn.close()
    return db_path


def _clipping(db_path):
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT path, channel_clip_shadow_pct, channel_clip_highlight_pct FROM photos").fetchall()
    conn.close()
    return {r[0]: (r[1], r[2]) for r in rows}


class TestBackfill:
    def test_derives_the_columns_from_stored_blobs(self, clipping_db):
        assert backfill_channel_clipping(clipping_db, verbose=False) == 4
        values = _clipping(clipping_db)
        assert values["/c/blown.jpg"][1] == pytest.approx(30.0, abs=0.05)
        assert values["/c/mild.jpg"][1] == pytest.approx(2.0, abs=0.05)
        assert values["/c/crushed.jpg"][0] == pytest.approx(12.0, abs=0.05)

    def test_a_photo_with_no_clipping_is_zero_not_null(self, clipping_db):
        backfill_channel_clipping(clipping_db, verbose=False)
        assert _clipping(clipping_db)["/c/clean.jpg"] == (0.0, 0.0)

    def test_a_legacy_row_stays_unknown(self, clipping_db):
        backfill_channel_clipping(clipping_db, verbose=False)
        assert _clipping(clipping_db)["/c/legacy.jpg"] == (None, None)

    def test_a_row_with_no_histogram_stays_unknown(self, clipping_db):
        backfill_channel_clipping(clipping_db, verbose=False)
        assert _clipping(clipping_db)["/c/nohist.jpg"] == (None, None)

    def test_is_resumable_and_claims_no_row_twice(self, clipping_db):
        assert backfill_channel_clipping(clipping_db, verbose=False) == 4
        # A second run finds nothing left: the legacy rows must not be re-read
        # forever just because their columns are still NULL.
        assert backfill_channel_clipping(clipping_db, verbose=False) == 0

    def test_resumes_after_an_interrupted_run(self, clipping_db):
        assert backfill_channel_clipping(clipping_db, batch_size=1, verbose=False) == 4
        conn = sqlite3.connect(clipping_db)
        conn.execute("UPDATE photos SET channel_clip_highlight_pct = NULL, "
                     "channel_clip_shadow_pct = NULL WHERE path = '/c/mild.jpg'")
        conn.commit()
        conn.close()
        assert backfill_channel_clipping(clipping_db, verbose=False) == 1
        assert _clipping(clipping_db)["/c/mild.jpg"][1] == pytest.approx(2.0, abs=0.05)

    def test_batches_smaller_than_the_row_count_still_finish(self, clipping_db):
        assert backfill_channel_clipping(clipping_db, batch_size=2, verbose=False) == 4


# ---------------------------------------------------------------------------
# Gallery filter
# ---------------------------------------------------------------------------

def _async_conn_factory(db_path):
    @asynccontextmanager
    async def factory():
        c = await aiosqlite.connect(db_path)
        c.row_factory = aiosqlite.Row
        try:
            yield c
        finally:
            await c.close()
    return factory


def _sync_conn_factory(db_path):
    @contextmanager
    def factory():
        c = sqlite3.connect(db_path)
        c.row_factory = sqlite3.Row
        try:
            yield c
        finally:
            c.close()
    return factory


_VIEWER_CONFIG = {
    "display": {"tags_per_photo": 5},
    "pagination": {"default_per_page": 64, "max_per_page": 200},
    "defaults": {
        "sort": "aggregate", "sort_direction": "DESC",
        "hide_blinks": False, "hide_bursts": False,
        "hide_duplicates": False, "type": "",
    },
    "dropdowns": {"min_photos_for_person": 2, "max_persons": 100},
    "quality_thresholds": {},
    "features": {},
}


@pytest.fixture()
def filtered_db(clipping_db):
    backfill_channel_clipping(clipping_db, verbose=False)
    conn = sqlite3.connect(clipping_db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(photos)")}
    conn.close()
    return clipping_db, cols


def _run(db_path, cols, query):
    app = create_app()
    app.dependency_overrides[get_optional_user] = lambda: None
    with (
        mock.patch("api.routers.gallery.get_db", _sync_conn_factory(db_path)),
        mock.patch("api.routers.gallery.get_async_db", _async_conn_factory(db_path)),
        mock.patch("api.routers.gallery.VIEWER_CONFIG", _VIEWER_CONFIG),
        mock.patch("api.db_helpers._existing_columns_cache", cols),
        mock.patch.dict("api.config._count_cache", {}, clear=True),
    ):
        return TestClient(app).get(query)


class TestGalleryFilter:
    def test_the_columns_are_returned_to_the_client(self, filtered_db):
        db_path, cols = filtered_db
        resp = _run(db_path, cols, "/api/photos")
        assert resp.status_code == 200
        photos = {p["path"]: p for p in resp.json()["photos"]}
        assert photos["/c/blown.jpg"]["channel_clip_highlight_pct"] == pytest.approx(30.0, abs=0.05)
        # Unknown must travel as null, so the client can tell it from clean.
        assert photos["/c/legacy.jpg"]["channel_clip_highlight_pct"] is None

    def test_a_minimum_returns_only_photos_above_it(self, filtered_db):
        db_path, cols = filtered_db
        resp = _run(db_path, cols, "/api/photos?min_channel_clip_highlight=5")
        assert resp.status_code == 200
        assert {p["path"] for p in resp.json()["photos"]} == {"/c/blown.jpg"}

    def test_a_lower_minimum_widens_the_set(self, filtered_db):
        db_path, cols = filtered_db
        resp = _run(db_path, cols, "/api/photos?min_channel_clip_highlight=1")
        assert {p["path"] for p in resp.json()["photos"]} == {"/c/blown.jpg", "/c/mild.jpg"}

    def test_the_shadow_filter_is_independent_of_the_highlight_one(self, filtered_db):
        db_path, cols = filtered_db
        resp = _run(db_path, cols, "/api/photos?min_channel_clip_shadow=5")
        assert {p["path"] for p in resp.json()["photos"]} == {"/c/crushed.jpg"}

    def test_an_unmeasured_photo_is_never_returned_as_clipped(self, filtered_db):
        db_path, cols = filtered_db
        resp = _run(db_path, cols, "/api/photos?min_channel_clip_highlight=0")
        assert "/c/legacy.jpg" not in {p["path"] for p in resp.json()["photos"]}

    def test_an_unmeasured_photo_is_never_returned_as_clean_either(self, filtered_db):
        """The failure this guards: treating NULL as 0 would hand every
        un-migrated row to a "photos with clean highlights" filter."""
        db_path, cols = filtered_db
        resp = _run(db_path, cols, "/api/photos?max_channel_clip_highlight=1")
        paths = {p["path"] for p in resp.json()["photos"]}
        assert "/c/legacy.jpg" not in paths
        assert "/c/nohist.jpg" not in paths
        assert paths == {"/c/clean.jpg", "/c/crushed.jpg"}
