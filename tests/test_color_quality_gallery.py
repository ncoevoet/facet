"""Parts B & C: the gallery endpoint applies the colour-temp / hue-bucket
facets and the on-the-fly quality-tier filter.

Mirrors tests/test_extended_iqa_gallery.py's harness: a tmp DB, the real gallery
router, dependency-overridden anonymous user, and the sync/async conn factories
patched onto the router module.
"""

import sqlite3
from contextlib import asynccontextmanager, contextmanager
from unittest import mock

import aiosqlite
import pytest
from fastapi.testclient import TestClient

from api import create_app
from api.auth import get_optional_user
from api.routers.gallery import (
    HUE_BUCKETS,
    _quality_tier_bounds,
)
from db.schema import init_database


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
    "quality_thresholds": {"good": 6, "great": 7, "excellent": 8, "best": 9},
    "features": {},
}


# --- pure unit: tier bounds + hue bucket ranges ---------------------------- #

def test_quality_tier_bounds_uses_config_thresholds():
    with mock.patch("api.routers.gallery.VIEWER_CONFIG", _VIEWER_CONFIG):
        assert _quality_tier_bounds("excellent") == (8.0, None)
        assert _quality_tier_bounds("good") == (7.0, 8.0)
        assert _quality_tier_bounds("fair") == (6.0, 7.0)
        assert _quality_tier_bounds("poor") == (None, 6.0)
        assert _quality_tier_bounds("bogus") is None


def test_hue_buckets_cover_the_circle():
    # Red wraps the 0/360 boundary; all other buckets are single ranges.
    assert HUE_BUCKETS["red"] == [(0.0, 15.0), (345.0, 360.0)]
    assert set(HUE_BUCKETS) == {
        "red", "orange", "yellow", "green", "cyan", "blue", "purple", "magenta"
    }


# --- integration ------------------------------------------------------------ #

@pytest.fixture()
def gallery_db(tmp_path):
    db_path = str(tmp_path / "g.db")
    init_database(db_path)
    conn = sqlite3.connect(db_path)
    # path, aggregate, dominant_hue, color_temp
    rows = [
        ("/g/warm_red.jpg", 9.0, 10.0, "warm"),     # excellent + red bucket
        ("/g/cool_blue.jpg", 7.5, 220.0, "cool"),   # good tier + blue bucket
        ("/g/fair_neutral.jpg", 6.5, None, "neutral"),  # fair tier, no hue
        ("/g/poor_green.jpg", 3.0, 120.0, "neutral"),   # poor tier + green bucket
    ]
    for path, agg, hue, temp in rows:
        conn.execute(
            "INSERT INTO photos (path, filename, aggregate, dominant_hue, color_temp) "
            "VALUES (?, ?, ?, ?, ?)",
            (path, path.rsplit("/", 1)[-1], agg, hue, temp),
        )
    conn.commit()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(photos)")}
    conn.close()
    return db_path, cols


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


def test_color_temp_filter(gallery_db):
    db_path, cols = gallery_db
    resp = _run(db_path, cols, "/api/photos?color_temp=warm")
    assert resp.status_code == 200
    paths = {p["path"] for p in resp.json()["photos"]}
    assert paths == {"/g/warm_red.jpg"}


def test_hue_bucket_filter(gallery_db):
    db_path, cols = gallery_db
    resp = _run(db_path, cols, "/api/photos?hue_bucket=blue")
    assert resp.status_code == 200
    paths = {p["path"] for p in resp.json()["photos"]}
    assert paths == {"/g/cool_blue.jpg"}


def test_hue_bucket_red_wraps_boundary(gallery_db):
    db_path, cols = gallery_db
    resp = _run(db_path, cols, "/api/photos?hue_bucket=red")
    assert resp.status_code == 200
    paths = {p["path"] for p in resp.json()["photos"]}
    assert paths == {"/g/warm_red.jpg"}  # hue 10.0 falls in red


@pytest.mark.parametrize(
    "tier,expected",
    [
        ("excellent", {"/g/warm_red.jpg"}),
        ("good", {"/g/cool_blue.jpg"}),
        ("fair", {"/g/fair_neutral.jpg"}),
        ("poor", {"/g/poor_green.jpg"}),
    ],
)
def test_quality_tier_filter(gallery_db, tier, expected):
    db_path, cols = gallery_db
    resp = _run(db_path, cols, f"/api/photos?quality_tier={tier}")
    assert resp.status_code == 200
    paths = {p["path"] for p in resp.json()["photos"]}
    assert paths == expected


def test_color_facet_columns_returned(gallery_db):
    db_path, cols = gallery_db
    resp = _run(db_path, cols, "/api/photos?color_temp=cool")
    assert resp.status_code == 200
    photo = resp.json()["photos"][0]
    assert photo["color_temp"] == "cool"
    assert photo["dominant_hue"] == 220.0
