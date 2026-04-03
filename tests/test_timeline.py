"""Tests for the timeline endpoint (api/routers/timeline.py)."""

from contextlib import contextmanager
from unittest import mock

import pytest


def _cm(conn):
    @contextmanager
    def _ctx():
        yield conn
    return _ctx()
from fastapi.testclient import TestClient

from api import create_app


@pytest.fixture()
def client():
    app = create_app()
    return TestClient(app)


class TestTimelineEndpoint:
    """Tests for GET /api/timeline."""

    def test_returns_date_groups(self, client):
        """Returns photos grouped by date."""
        mock_conn = mock.MagicMock()

        # First call: date_rows query
        date_rows = [
            {"photo_date": "2025-03-10", "cnt": 5},
            {"photo_date": "2025-03-09", "cnt": 3},
        ]
        # Second call onwards: photo queries per date group
        photo_rows_1 = [
            {"path": "/a.jpg", "date_taken": "2025:03:10 14:00:00", "aggregate": 8.5, "tags": "landscape", "filename": "a.jpg"},
        ]
        photo_rows_2 = [
            {"path": "/b.jpg", "date_taken": "2025:03:09 10:00:00", "aggregate": 7.0, "tags": "portrait", "filename": "b.jpg"},
        ]

        mock_conn.execute.return_value.fetchall.side_effect = [date_rows, photo_rows_1, photo_rows_2]

        with (
            mock.patch("api.routers.timeline.get_db", lambda: _cm(mock_conn)),
            mock.patch("api.routers.timeline.get_visibility_clause", return_value=("1=1", [])),
            mock.patch("api.routers.timeline.get_photos_from_clause", return_value=("photos", [])),
            mock.patch("api.routers.timeline.build_photo_select_columns", return_value=["path", "date_taken", "aggregate", "tags"]),
            mock.patch("api.routers.timeline.VIEWER_CONFIG", {"display": {"tags_per_photo": 10}}),
            mock.patch("api.routers.timeline.split_photo_tags", side_effect=lambda rows, limit: [dict(r) for r in rows]),
            mock.patch("api.routers.timeline.attach_person_data"),
            mock.patch("api.routers.timeline.sanitize_float_values"),
            mock.patch("api.routers.timeline.format_date", return_value="10/03/2025"),
        ):
            resp = client.get("/api/timeline", params={"limit": 50})

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["groups"]) == 2
        assert body["groups"][0]["date"] == "2025-03-10"
        assert body["groups"][0]["count"] == 5
        assert body["has_more"] is False


    def test_cursor_pagination(self, client):
        """Cursor parameter filters dates before/after the cursor."""
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchall.side_effect = [
            [],  # no date_rows after cursor
        ]

        with (
            mock.patch("api.routers.timeline.get_db", lambda: _cm(mock_conn)),
            mock.patch("api.routers.timeline.get_visibility_clause", return_value=("1=1", [])),
            mock.patch("api.routers.timeline.get_photos_from_clause", return_value=("photos", [])),
            mock.patch("api.routers.timeline.build_photo_select_columns", return_value=["path"]),
            mock.patch("api.routers.timeline.VIEWER_CONFIG", {"display": {"tags_per_photo": 10}}),
        ):
            resp = client.get("/api/timeline", params={
                "cursor": "2025-03-10",
                "direction": "older",
                "limit": 10,
            })

        assert resp.status_code == 200
        body = resp.json()
        assert body["groups"] == []
        assert body["has_more"] is False

    def test_has_more_when_extra_dates(self, client):
        """has_more is True when more dates exist beyond the limit."""
        mock_conn = mock.MagicMock()

        # Return limit+1 rows to trigger has_more
        date_rows = [{"photo_date": f"2025-03-{10-i:02d}", "cnt": 1} for i in range(4)]
        photo_rows = [[{"path": f"/{i}.jpg", "date_taken": f"2025:03:{10-i:02d} 10:00:00", "aggregate": 5.0, "tags": "", "filename": f"{i}.jpg"}] for i in range(3)]

        mock_conn.execute.return_value.fetchall.side_effect = [date_rows] + photo_rows

        with (
            mock.patch("api.routers.timeline.get_db", lambda: _cm(mock_conn)),
            mock.patch("api.routers.timeline.get_visibility_clause", return_value=("1=1", [])),
            mock.patch("api.routers.timeline.get_photos_from_clause", return_value=("photos", [])),
            mock.patch("api.routers.timeline.build_photo_select_columns", return_value=["path", "date_taken", "aggregate", "tags"]),
            mock.patch("api.routers.timeline.VIEWER_CONFIG", {"display": {"tags_per_photo": 10}}),
            mock.patch("api.routers.timeline.split_photo_tags", side_effect=lambda rows, limit: [dict(r) for r in rows]),
            mock.patch("api.routers.timeline.attach_person_data"),
            mock.patch("api.routers.timeline.sanitize_float_values"),
            mock.patch("api.routers.timeline.format_date", return_value=""),
        ):
            resp = client.get("/api/timeline", params={"limit": 3})

        assert resp.status_code == 200
        body = resp.json()
        assert body["has_more"] is True
        assert body["next_cursor"] is not None
        assert len(body["groups"]) == 3

    def test_date_from_and_date_to_filtering(self, client):
        """date_from and date_to parameters filter the results."""
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchall.side_effect = [
            [{"photo_date": "2025-03-12", "cnt": 2}],
            [{"path": "/x.jpg", "date_taken": "2025:03:12 10:00:00", "aggregate": 6.0, "tags": "", "filename": "x.jpg"}],
        ]

        with (
            mock.patch("api.routers.timeline.get_db", lambda: _cm(mock_conn)),
            mock.patch("api.routers.timeline.get_visibility_clause", return_value=("1=1", [])),
            mock.patch("api.routers.timeline.get_photos_from_clause", return_value=("photos", [])),
            mock.patch("api.routers.timeline.build_photo_select_columns", return_value=["path", "date_taken", "aggregate", "tags"]),
            mock.patch("api.routers.timeline.VIEWER_CONFIG", {"display": {"tags_per_photo": 10}}),
            mock.patch("api.routers.timeline.split_photo_tags", side_effect=lambda rows, limit: [dict(r) for r in rows]),
            mock.patch("api.routers.timeline.attach_person_data"),
            mock.patch("api.routers.timeline.sanitize_float_values"),
            mock.patch("api.routers.timeline.format_date", return_value="12/03/2025"),
        ):
            resp = client.get("/api/timeline", params={
                "date_from": "2025-03-10",
                "date_to": "2025-03-15",
            })

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["groups"]) == 1
        assert body["groups"][0]["date"] == "2025-03-12"

    def test_newer_direction(self, client):
        """direction=newer fetches dates after the cursor."""
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchall.side_effect = [
            [{"photo_date": "2025-03-15", "cnt": 1}],
            [{"path": "/n.jpg", "date_taken": "2025:03:15 10:00:00", "aggregate": 6.0, "tags": "", "filename": "n.jpg"}],
        ]

        with (
            mock.patch("api.routers.timeline.get_db", lambda: _cm(mock_conn)),
            mock.patch("api.routers.timeline.get_visibility_clause", return_value=("1=1", [])),
            mock.patch("api.routers.timeline.get_photos_from_clause", return_value=("photos", [])),
            mock.patch("api.routers.timeline.build_photo_select_columns", return_value=["path", "date_taken", "aggregate", "tags"]),
            mock.patch("api.routers.timeline.VIEWER_CONFIG", {"display": {"tags_per_photo": 10}}),
            mock.patch("api.routers.timeline.split_photo_tags", side_effect=lambda rows, limit: [dict(r) for r in rows]),
            mock.patch("api.routers.timeline.attach_person_data"),
            mock.patch("api.routers.timeline.sanitize_float_values"),
            mock.patch("api.routers.timeline.format_date", return_value="15/03/2025"),
        ):
            resp = client.get("/api/timeline", params={
                "cursor": "2025-03-10",
                "direction": "newer",
            })

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["groups"]) == 1

    def test_db_error_returns_empty(self):
        """On database exception, returns empty result instead of 500."""
        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)
        mock_conn = mock.MagicMock()
        mock_conn.execute.side_effect = Exception("DB error")

        with (
            mock.patch("api.routers.timeline.get_db", lambda: _cm(mock_conn)),
            mock.patch("api.routers.timeline.get_visibility_clause", return_value=("1=1", [])),
            mock.patch("api.routers.timeline.get_photos_from_clause", return_value=("photos", [])),
        ):
            resp = client.get("/api/timeline")

        assert resp.status_code == 200
        body = resp.json()
        assert body["groups"] == []
        assert body["has_more"] is False


class TestTimelineDates:
    """Tests for GET /api/timeline/dates."""

    def test_returns_date_counts(self, client):
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            {"group_key": "2025-03-10", "cnt": 15, "hero_photo_path": "/photos/a.jpg"},
            {"group_key": "2025-03-11", "cnt": 8, "hero_photo_path": "/photos/b.jpg"},
        ]

        with (
            mock.patch("api.routers.timeline.get_db", lambda: _cm(mock_conn)),
            mock.patch("api.routers.timeline.get_visibility_clause", return_value=("1=1", [])),
            mock.patch("api.routers.timeline.get_photos_from_clause", return_value=("photos", [])),
        ):
            resp = client.get("/api/timeline/dates", params={"year": 2025})

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["dates"]) == 2
        assert body["dates"][0]["date"] == "2025-03-10"
        assert body["dates"][0]["count"] == 15


    def test_year_and_month_filter(self, client):
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            {"group_key": "2025-06-15", "cnt": 3, "hero_photo_path": "/photos/c.jpg"},
        ]

        with (
            mock.patch("api.routers.timeline.get_db", lambda: _cm(mock_conn)),
            mock.patch("api.routers.timeline.get_visibility_clause", return_value=("1=1", [])),
            mock.patch("api.routers.timeline.get_photos_from_clause", return_value=("photos", [])),
        ):
            resp = client.get("/api/timeline/dates", params={"year": 2025, "month": 6})

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["dates"]) == 1

    def test_db_error_returns_empty_dates(self):
        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)
        mock_conn = mock.MagicMock()
        mock_conn.execute.side_effect = Exception("DB error")

        with (
            mock.patch("api.routers.timeline.get_db", lambda: _cm(mock_conn)),
            mock.patch("api.routers.timeline.get_visibility_clause", return_value=("1=1", [])),
            mock.patch("api.routers.timeline.get_photos_from_clause", return_value=("photos", [])),
        ):
            resp = client.get("/api/timeline/dates", params={"year": 2025})

        assert resp.status_code == 200
        assert resp.json()["dates"] == []

    def test_missing_year_returns_422(self, client):
        resp = client.get("/api/timeline/dates")
        assert resp.status_code == 422
