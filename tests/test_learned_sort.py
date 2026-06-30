"""
Gallery exposes an opt-in learned_score ("My Taste") sort.

Reads the denormalized photos.learned_score column (synced from the global
personal ranker); never overwrites aggregate. Trained photos sort by
learned_score; untrained (NULL) photos sink, and the query must not crash on an
untrained DB.
"""

import sqlite3
from contextlib import asynccontextmanager
from unittest import mock

import aiosqlite
import pytest
from fastapi.testclient import TestClient

from api import create_app
from api.auth import get_optional_user
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
    from contextlib import contextmanager

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
def gallery_db(tmp_path):
    db_path = str(tmp_path / "g.db")
    init_database(db_path)
    conn = sqlite3.connect(db_path)
    # 3 photos with equal aggregate so learned_score decides the order.
    for name in ('a', 'b', 'c'):
        conn.execute(
            "INSERT INTO photos (path, filename, aggregate) VALUES (?, ?, 5.0)",
            (f'/g/{name}.jpg', f'{name}.jpg'),
        )
    # Denormalized global ranker scores (what the gallery sort reads): a (high),
    # b (low); c stays untrained (NULL) and must sink.
    conn.execute("UPDATE photos SET learned_score = 9.0 WHERE path = '/g/a.jpg'")
    conn.execute("UPDATE photos SET learned_score = 2.0 WHERE path = '/g/b.jpg'")
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


def test_learned_score_sort_orders_and_sinks_nulls(gallery_db):
    db_path, cols = gallery_db
    resp = _run(db_path, cols, "/api/photos?sort=learned_score&sort_direction=DESC")
    assert resp.status_code == 200
    photos = resp.json()["photos"]
    paths = [p["path"] for p in photos]
    # a (9.0) before b (2.0); c (untrained NULL) last.
    assert paths == ["/g/a.jpg", "/g/b.jpg", "/g/c.jpg"]
    assert photos[0]["learned_score"] == 9.0
    assert photos[2]["learned_score"] is None


def test_learned_score_sort_no_crash_on_untrained_db(tmp_path):
    """An untrained DB (empty learned_scores) sorts by path, no crash, all NULL."""
    db_path = str(tmp_path / "u.db")
    init_database(db_path)
    conn = sqlite3.connect(db_path)
    for name in ('x', 'y'):
        conn.execute("INSERT INTO photos (path, filename, aggregate) VALUES (?, ?, 5.0)",
                     (f'/u/{name}.jpg', f'{name}.jpg'))
    conn.commit()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(photos)")}
    conn.close()
    resp = _run(db_path, cols, "/api/photos?sort=learned_score")
    assert resp.status_code == 200
    photos = resp.json()["photos"]
    assert {p["path"] for p in photos} == {"/u/x.jpg", "/u/y.jpg"}
    assert all(p["learned_score"] is None for p in photos)
