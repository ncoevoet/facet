"""Tests for the map photo endpoints (api/routers/map.py).

The map GET endpoints are async (Topic 2 step 3), so these tests patch
get_async_db with a real aiosqlite-backed temp DB rather than a MagicMock
(a MagicMock is not awaitable). The PUT /api/photo/gps endpoint stays sync.
"""

import sqlite3
from contextlib import asynccontextmanager
from unittest import mock

import aiosqlite
import pytest
from fastapi.testclient import TestClient

from api import create_app


_MAP_SCHEMA = """
    CREATE TABLE photos (
        path TEXT PRIMARY KEY, filename TEXT, date_taken TEXT,
        gps_latitude REAL, gps_longitude REAL,
        aggregate REAL, category TEXT, is_rejected INTEGER DEFAULT 0
    );
"""


def _make_map_db(path, photos):
    conn = sqlite3.connect(path)
    conn.executescript(_MAP_SCHEMA)
    for p in photos:
        cols = list(p.keys())
        placeholders = ", ".join("?" for _ in cols)
        conn.execute(
            f"INSERT INTO photos ({', '.join(cols)}) VALUES ({placeholders})",
            [p[c] for c in cols],
        )
    conn.commit()
    conn.close()


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


def _fake_vis(user_id, table_alias=None):
    return ("1=1", [])


@pytest.fixture()
def client():
    app = create_app()
    return TestClient(app)


_GPS_COLS = {"gps_latitude", "gps_longitude", "path"}


class TestPhotosMap:
    """Tests for GET /api/photos/map."""

    def test_no_gps_columns_returns_empty(self, client):
        """When gps_latitude/gps_longitude columns don't exist, return empty."""
        with mock.patch(
            "api.routers.map.get_existing_columns", return_value={"path", "aggregate"}
        ):
            resp = client.get("/api/photos/map", params={"bounds": "40.0,-74.0,41.0,-73.0"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["photos"] == []
        assert body["clusters"] == []

    def test_invalid_bounds_format(self, client):
        """Invalid bounds string returns error (before any DB access)."""
        with mock.patch("api.routers.map.get_existing_columns", return_value=_GPS_COLS):
            resp = client.get("/api/photos/map", params={"bounds": "invalid"})

        assert resp.status_code == 400
        assert "detail" in resp.json()

    def test_invalid_bounds_wrong_count(self, client):
        """Bounds with wrong number of values returns error."""
        with mock.patch("api.routers.map.get_existing_columns", return_value=_GPS_COLS):
            resp = client.get("/api/photos/map", params={"bounds": "40.0,-74.0,41.0"})

        assert resp.status_code == 400
        assert "detail" in resp.json()

    def test_clustering_at_low_zoom(self, client, tmp_path):
        """At zoom < threshold, returns clusters grouped by grid cells."""
        db = str(tmp_path / "map.db")
        _make_map_db(db, [
            {"path": "/a.jpg", "filename": "a.jpg", "gps_latitude": 40.5, "gps_longitude": -73.5, "aggregate": 9.0},
            {"path": "/a2.jpg", "filename": "a2.jpg", "gps_latitude": 40.51, "gps_longitude": -73.51, "aggregate": 5.0},
            {"path": "/b.jpg", "filename": "b.jpg", "gps_latitude": 41.0, "gps_longitude": -73.0, "aggregate": 8.0},
        ])
        with (
            mock.patch("api.routers.map.get_existing_columns", return_value=_GPS_COLS),
            mock.patch("api.routers.map.get_async_db", _async_conn_factory(db)),
            mock.patch("api.routers.map.get_visibility_clause", _fake_vis),
        ):
            resp = client.get("/api/photos/map", params={
                "bounds": "40.0,-74.0,42.0,-72.0",
                "zoom": 5,
            })

        assert resp.status_code == 200
        body = resp.json()
        assert "clusters" in body
        assert body["photos"] == []
        total = sum(c["count"] for c in body["clusters"])
        assert total == 3

    def test_individual_points_at_high_zoom(self, client, tmp_path):
        """At zoom >= threshold, returns individual photo points, sorted by aggregate."""
        db = str(tmp_path / "map.db")
        _make_map_db(db, [
            {"path": "/a.jpg", "filename": "a.jpg", "gps_latitude": 40.7128, "gps_longitude": -74.0060,
             "aggregate": 8.5, "date_taken": "2024-01-15", "category": "landscape"},
            {"path": "/b.jpg", "filename": "b.jpg", "gps_latitude": 40.7130, "gps_longitude": -74.0058,
             "aggregate": 7.2, "date_taken": "2024-02-20", "category": "portrait"},
        ])
        with (
            mock.patch("api.routers.map.get_existing_columns", return_value=_GPS_COLS),
            mock.patch("api.routers.map.get_async_db", _async_conn_factory(db)),
            mock.patch("api.routers.map.get_visibility_clause", _fake_vis),
        ):
            resp = client.get("/api/photos/map", params={
                "bounds": "40.71,-74.01,40.72,-74.00",
                "zoom": 15,
            })

        assert resp.status_code == 200
        body = resp.json()
        assert body["clusters"] == []
        assert len(body["photos"]) == 2
        assert body["photos"][0]["path"] == "/a.jpg"
        assert body["photos"][0]["lat"] == 40.7128

    def test_empty_results(self, client, tmp_path):
        """Returns empty list when no photos in bounds."""
        db = str(tmp_path / "map.db")
        _make_map_db(db, [
            {"path": "/far.jpg", "filename": "far.jpg", "gps_latitude": 10.0, "gps_longitude": 10.0, "aggregate": 5.0},
        ])
        with (
            mock.patch("api.routers.map.get_existing_columns", return_value=_GPS_COLS),
            mock.patch("api.routers.map.get_async_db", _async_conn_factory(db)),
            mock.patch("api.routers.map.get_visibility_clause", _fake_vis),
        ):
            resp = client.get("/api/photos/map", params={
                "bounds": "0.0,0.0,1.0,1.0",
                "zoom": 15,
            })

        assert resp.status_code == 200
        body = resp.json()
        assert body["photos"] == []


class TestPhotosMapCount:
    """Tests for GET /api/photos/map/count."""

    def test_no_gps_columns_returns_zero(self, client):
        with mock.patch("api.routers.map.get_existing_columns", return_value={"path"}):
            resp = client.get("/api/photos/map/count")

        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_returns_count(self, client, tmp_path):
        db = str(tmp_path / "count.db")
        _make_map_db(db, [
            {"path": f"/p{i}.jpg", "filename": f"p{i}.jpg", "gps_latitude": 40.0 + i * 0.01,
             "gps_longitude": -73.0, "aggregate": 5.0}
            for i in range(42)
        ])
        with (
            mock.patch("api.routers.map.get_existing_columns", return_value=_GPS_COLS),
            mock.patch("api.routers.map.get_async_db", _async_conn_factory(db)),
            mock.patch("api.routers.map.get_visibility_clause", _fake_vis),
        ):
            resp = client.get("/api/photos/map/count")

        assert resp.status_code == 200
        assert resp.json()["count"] == 42

    def test_returns_zero_when_no_gps_photos(self, client, tmp_path):
        db = str(tmp_path / "empty.db")
        _make_map_db(db, [])
        with (
            mock.patch("api.routers.map.get_existing_columns", return_value=_GPS_COLS),
            mock.patch("api.routers.map.get_async_db", _async_conn_factory(db)),
            mock.patch("api.routers.map.get_visibility_clause", _fake_vis),
        ):
            resp = client.get("/api/photos/map/count")

        assert resp.status_code == 200
        assert resp.json()["count"] == 0
