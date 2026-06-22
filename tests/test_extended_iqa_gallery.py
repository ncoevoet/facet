"""Part A: the extended-IQA columns (qalign_score, aesthetic_v25, deqa_score)
are returned by the gallery endpoint and usable as range filters.

Mirrors tests/test_learned_sort.py's harness: a tmp DB, the real gallery
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
from api.db_helpers import PHOTO_OPTIONAL_COLS
from api.routers.gallery import SCORE_RANGE_COLUMNS
from db.schema import init_database


EXTENDED_IQA_COLUMNS = ("qalign_score", "aesthetic_v25", "deqa_score")


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


# --- registration sanity (pure, no DB) ------------------------------------- #

def test_extended_iqa_columns_registered_as_optional_cols():
    for col in EXTENDED_IQA_COLUMNS:
        assert col in PHOTO_OPTIONAL_COLS, f"{col} missing from PHOTO_OPTIONAL_COLS"


def test_extended_iqa_columns_registered_as_range_filters():
    range_cols = {c[0] for c in SCORE_RANGE_COLUMNS}
    for col in EXTENDED_IQA_COLUMNS:
        assert col in range_cols, f"{col} not registered in SCORE_RANGE_COLUMNS"
    # And each exposes the expected min_/max_ filter keys.
    by_col = {c[0]: c for c in SCORE_RANGE_COLUMNS}
    assert by_col["qalign_score"][1:3] == ("min_qalign", "max_qalign")
    assert by_col["aesthetic_v25"][1:3] == ("min_aesthetic_v25", "max_aesthetic_v25")
    assert by_col["deqa_score"][1:3] == ("min_deqa", "max_deqa")


# --- integration: returned + filterable ------------------------------------ #

@pytest.fixture()
def gallery_db(tmp_path):
    db_path = str(tmp_path / "g.db")
    init_database(db_path)
    conn = sqlite3.connect(db_path)
    # Three photos with distinct extended-IQA values so range filters can split them.
    rows = [
        ("/g/a.jpg", "a.jpg", 9.0, 9.0, 9.0),
        ("/g/b.jpg", "b.jpg", 5.0, 5.0, 5.0),
        ("/g/c.jpg", "c.jpg", 1.0, 1.0, 1.0),
    ]
    for path, fn, q, av, dq in rows:
        conn.execute(
            "INSERT INTO photos (path, filename, aggregate, qalign_score, aesthetic_v25, deqa_score) "
            "VALUES (?, ?, 5.0, ?, ?, ?)",
            (path, fn, q, av, dq),
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


def test_extended_iqa_columns_returned_in_gallery(gallery_db):
    db_path, cols = gallery_db
    resp = _run(db_path, cols, "/api/photos?sort=qalign_score&sort_direction=DESC")
    assert resp.status_code == 200
    photos = {p["path"]: p for p in resp.json()["photos"]}
    assert set(photos) == {"/g/a.jpg", "/g/b.jpg", "/g/c.jpg"}
    a = photos["/g/a.jpg"]
    for col in EXTENDED_IQA_COLUMNS:
        assert col in a, f"{col} not returned by the gallery endpoint"
    assert a["qalign_score"] == 9.0
    assert a["aesthetic_v25"] == 9.0
    assert a["deqa_score"] == 9.0


@pytest.mark.parametrize(
    "min_key,expected",
    [
        ("min_qalign", {"/g/a.jpg", "/g/b.jpg"}),
        ("min_aesthetic_v25", {"/g/a.jpg", "/g/b.jpg"}),
        ("min_deqa", {"/g/a.jpg", "/g/b.jpg"}),
    ],
)
def test_extended_iqa_range_filter_applies(gallery_db, min_key, expected):
    db_path, cols = gallery_db
    # min >= 4 keeps the 9.0 and 5.0 photos, drops the 1.0 one.
    resp = _run(db_path, cols, f"/api/photos?{min_key}=4")
    assert resp.status_code == 200
    paths = {p["path"] for p in resp.json()["photos"]}
    assert paths == expected
