"""Tests for the map photo endpoints (api/routers/map.py)."""

from contextlib import nullcontext
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from api import create_app


@pytest.fixture()
def client():
    app = create_app()
    return TestClient(app)


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
        """Invalid bounds string returns error."""
        with (
            mock.patch("api.routers.map.get_existing_columns", return_value={"gps_latitude", "gps_longitude", "path"}),
            mock.patch("api.routers.map.get_db") as mock_get_conn,
            mock.patch("api.routers.map.get_visibility_clause", return_value=("1=1", [])),
        ):
            mock_conn = mock.MagicMock()
            mock_get_conn.return_value = nullcontext(mock_conn)
            resp = client.get("/api/photos/map", params={"bounds": "invalid"})

        assert resp.status_code == 400
        assert "detail" in resp.json()

    def test_invalid_bounds_wrong_count(self, client):
        """Bounds with wrong number of values returns error."""
        with (
            mock.patch("api.routers.map.get_existing_columns", return_value={"gps_latitude", "gps_longitude"}),
            mock.patch("api.routers.map.get_db") as mock_get_conn,
            mock.patch("api.routers.map.get_visibility_clause", return_value=("1=1", [])),
        ):
            mock_conn = mock.MagicMock()
            mock_get_conn.return_value = nullcontext(mock_conn)
            resp = client.get("/api/photos/map", params={"bounds": "40.0,-74.0,41.0"})

        assert resp.status_code == 400
        assert "detail" in resp.json()

    def test_clustering_at_low_zoom(self, client):
        """At zoom < 10, returns clusters grouped by grid cells."""
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            {"avg_lat": 40.5, "avg_lng": -73.5, "count": 15, "representative_path": "/photos/a.jpg"},
            {"avg_lat": 41.0, "avg_lng": -73.0, "count": 8, "representative_path": "/photos/b.jpg"},
        ]

        with (
            mock.patch("api.routers.map.get_existing_columns", return_value={"gps_latitude", "gps_longitude"}),
            mock.patch("api.routers.map.get_db", return_value=nullcontext(mock_conn)),
            mock.patch("api.routers.map.get_visibility_clause", return_value=("1=1", [])),
        ):
            resp = client.get("/api/photos/map", params={
                "bounds": "40.0,-74.0,42.0,-72.0",
                "zoom": 5,
            })

        assert resp.status_code == 200
        body = resp.json()
        assert "clusters" in body
        assert len(body["clusters"]) == 2
        assert body["clusters"][0]["count"] == 15
        assert body["clusters"][0]["representative_path"] == "/photos/a.jpg"


    def test_individual_points_at_high_zoom(self, client):
        """At zoom >= 10, returns individual photo points."""
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            {"path": "/photos/a.jpg", "lat": 40.7128, "lng": -74.0060, "aggregate": 8.5, "filename": "a.jpg", "date_taken": "2024-01-15", "category": "landscape"},
            {"path": "/photos/b.jpg", "lat": 40.7130, "lng": -74.0058, "aggregate": 7.2, "filename": "b.jpg", "date_taken": "2024-02-20", "category": "portrait"},
        ]

        with (
            mock.patch("api.routers.map.get_existing_columns", return_value={"gps_latitude", "gps_longitude"}),
            mock.patch("api.routers.map.get_db", return_value=nullcontext(mock_conn)),
            mock.patch("api.routers.map.get_visibility_clause", return_value=("1=1", [])),
        ):
            resp = client.get("/api/photos/map", params={
                "bounds": "40.71,-74.01,40.72,-74.00",
                "zoom": 15,
            })

        assert resp.status_code == 200
        body = resp.json()
        assert "photos" in body
        assert len(body["photos"]) == 2
        assert body["photos"][0]["path"] == "/photos/a.jpg"
        assert body["photos"][0]["lat"] == 40.7128


    def test_empty_results(self, client):
        """Returns empty list when no photos in bounds."""
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []

        with (
            mock.patch("api.routers.map.get_existing_columns", return_value={"gps_latitude", "gps_longitude"}),
            mock.patch("api.routers.map.get_db", return_value=nullcontext(mock_conn)),
            mock.patch("api.routers.map.get_visibility_clause", return_value=("1=1", [])),
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

    def test_returns_count(self, client):
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = {"cnt": 42}

        with (
            mock.patch("api.routers.map.get_existing_columns", return_value={"gps_latitude", "gps_longitude"}),
            mock.patch("api.routers.map.get_db", return_value=nullcontext(mock_conn)),
            mock.patch("api.routers.map.get_visibility_clause", return_value=("1=1", [])),
        ):
            resp = client.get("/api/photos/map/count")

        assert resp.status_code == 200
        assert resp.json()["count"] == 42


    def test_returns_zero_when_no_gps_photos(self, client):
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = {"cnt": 0}

        with (
            mock.patch("api.routers.map.get_existing_columns", return_value={"gps_latitude", "gps_longitude"}),
            mock.patch("api.routers.map.get_db", return_value=nullcontext(mock_conn)),
            mock.patch("api.routers.map.get_visibility_clause", return_value=("1=1", [])),
        ):
            resp = client.get("/api/photos/map/count")

        assert resp.status_code == 200
        assert resp.json()["count"] == 0
