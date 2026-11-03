"""Tests for the memories endpoint (api/routers/memories.py)."""

from contextlib import asynccontextmanager
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from api import create_app


@pytest.fixture()
def client():
    app = create_app()
    return TestClient(app)


def _async_cm(conn):
    """Async context-manager factory; passes the mock conn through."""
    @asynccontextmanager
    async def _ctx():
        yield conn
    return _ctx


def _make_async_conn(rows):
    """Build a mock async conn whose execute returns a cursor with these rows;
    executed (sql, params) pairs are recorded on ``.executed`` for assertions."""
    class _Cursor:
        async def fetchall(self):
            return rows

        async def fetchone(self):
            return rows[0] if rows else None

        async def close(self):
            pass

    class _Conn:
        def __init__(self):
            self.executed = []

        async def execute(self, *a, **kw):
            self.executed.append(a)
            return _Cursor()

    return _Conn()


async def _async_noop(*args, **kwargs):
    """No-op coroutine used to mock async helpers like attach_person_data_async."""
    return None


def _make_photo_row(path, date_taken, aggregate, tags=""):
    """Build a dict that behaves like a sqlite3.Row for split_photo_tags."""
    row = {
        "path": path,
        "date_taken": date_taken,
        "aggregate": aggregate,
        "tags": tags,
        "filename": path.split("/")[-1],
    }
    # Make it act like a sqlite3.Row (supports dict() and key access)
    return mock.MagicMock(spec=[], __getitem__=row.__getitem__, keys=row.keys)


class TestMemoriesEndpoint:
    """Tests for GET /api/memories."""

    def test_check_compares_the_stored_fields_without_strftime(self, client):
        """The memories check runs on every cold app open over the whole
        library: the per-row REPLACE+strftime conversion must stay gone, with
        the fixed-format EXIF fields compared directly and the month-day
        parameter carrying the stored colon separators."""
        conn = _make_async_conn([])
        with (
            mock.patch("api.routers.memories.get_async_db", _async_cm(conn)),
            mock.patch("api.routers.memories.get_visibility_clause", return_value=("1=1", [])),
            mock.patch("api.routers.memories.get_photos_from_clause", return_value=("photos", [])),
        ):
            resp = client.get("/api/memories/check", params={"date": "2025-03-14"})

        assert resp.status_code == 200
        sql, params = conn.executed[0]
        assert "strftime" not in sql and "REPLACE" not in sql
        assert "SUBSTR(date_taken, 6, 5)" in sql
        assert "SUBSTR(date_taken, 1, 4)" in sql
        assert "GLOB" in sql  # malformed dates stay excluded, as strftime's NULL did
        assert params[0] == "03:14" and params[1] == "2025"

    def test_invalid_date_format_returns_400(self, client):
        """Non-ISO date string should return 400."""
        with (
            mock.patch("api.routers.memories.get_async_db", _async_cm(_make_async_conn([]))),
            mock.patch("api.routers.memories.get_visibility_clause", return_value=("1=1", [])),
            mock.patch("api.routers.memories.build_photo_select_columns", return_value=["path", "date_taken", "aggregate", "tags"]),
            mock.patch("api.routers.memories.get_photos_from_clause", return_value=("photos", [])),
        ):
            resp = client.get("/api/memories", params={"date": "not-a-date"})

        assert resp.status_code == 400
        assert "Invalid date" in resp.json()["detail"]

    def test_explicit_date_parameter(self, client):
        """When date= is provided, use that date instead of today."""
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []

        with (
            mock.patch("api.routers.memories.get_async_db", _async_cm(_make_async_conn([]))),
            mock.patch("api.routers.memories.get_visibility_clause", return_value=("1=1", [])),
            mock.patch("api.routers.memories.build_photo_select_columns", return_value=["path", "date_taken", "aggregate", "tags"]),
            mock.patch("api.routers.memories.get_photos_from_clause", return_value=("photos", [])),
            mock.patch("api.routers.memories.split_photo_tags", return_value=[]),
            mock.patch("api.routers.memories.attach_person_data_async", _async_noop),
        ):
            resp = client.get("/api/memories", params={"date": "2025-03-14"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["date"] == "2025-03-14"
        assert body["has_memories"] is False
        assert body["years"] == []


    def test_defaults_to_today(self, client):
        """When no date is provided, defaults to today."""
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []

        with (
            mock.patch("api.routers.memories.get_async_db", _async_cm(_make_async_conn([]))),
            mock.patch("api.routers.memories.get_visibility_clause", return_value=("1=1", [])),
            mock.patch("api.routers.memories.build_photo_select_columns", return_value=["path", "date_taken", "aggregate", "tags"]),
            mock.patch("api.routers.memories.get_photos_from_clause", return_value=("photos", [])),
            mock.patch("api.routers.memories.split_photo_tags", return_value=[]),
            mock.patch("api.routers.memories.attach_person_data_async", _async_noop),
        ):
            resp = client.get("/api/memories")

        assert resp.status_code == 200
        body = resp.json()
        # date should be today's date in ISO format
        assert "date" in body
        assert body["has_memories"] is False

    def test_year_grouping(self, client):
        """Photos from multiple years are grouped by year."""
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []  # raw rows

        photos = [
            {"path": "/a.jpg", "date_taken": "2023:03:14 10:00:00", "aggregate": 8.5, "tags": "", "tags_list": [], "filename": "a.jpg", "_year": "2023", "_rn": 1, "_year_total": 2},
            {"path": "/b.jpg", "date_taken": "2023:03:14 11:00:00", "aggregate": 7.0, "tags": "", "tags_list": [], "filename": "b.jpg", "_year": "2023", "_rn": 2, "_year_total": 2},
            {"path": "/c.jpg", "date_taken": "2022:03:14 09:00:00", "aggregate": 9.0, "tags": "", "tags_list": [], "filename": "c.jpg", "_year": "2022", "_rn": 1, "_year_total": 1},
        ]

        with (
            mock.patch("api.routers.memories.get_async_db", _async_cm(_make_async_conn([]))),
            mock.patch("api.routers.memories.get_visibility_clause", return_value=("1=1", [])),
            mock.patch("api.routers.memories.build_photo_select_columns", return_value=["path", "date_taken", "aggregate", "tags"]),
            mock.patch("api.routers.memories.get_photos_from_clause", return_value=("photos", [])),
            mock.patch("api.routers.memories.split_photo_tags", return_value=photos),
            mock.patch("api.routers.memories.attach_person_data_async", _async_noop),
            mock.patch("api.routers.memories.format_date", return_value="14/03/2023 10:00"),
            mock.patch("api.routers.memories.sanitize_float_values"),
            mock.patch("api.config.VIEWER_CONFIG", {"display": {"tags_per_photo": 10}}),
        ):
            resp = client.get("/api/memories", params={"date": "2025-03-14"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["has_memories"] is True
        assert len(body["years"]) == 2

        # Years sorted in reverse order
        assert body["years"][0]["year"] == "2023"
        assert body["years"][1]["year"] == "2022"

        # 2023 has 2 photos, 2022 has 1
        assert body["years"][0]["total_count"] == 2
        assert body["years"][1]["total_count"] == 1

    def test_empty_results(self, client):
        """No matching photos returns empty years list."""
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []

        with (
            mock.patch("api.routers.memories.get_async_db", _async_cm(_make_async_conn([]))),
            mock.patch("api.routers.memories.get_visibility_clause", return_value=("1=1", [])),
            mock.patch("api.routers.memories.build_photo_select_columns", return_value=["path", "date_taken", "aggregate", "tags"]),
            mock.patch("api.routers.memories.get_photos_from_clause", return_value=("photos", [])),
            mock.patch("api.routers.memories.split_photo_tags", return_value=[]),
            mock.patch("api.routers.memories.attach_person_data_async", _async_noop),
        ):
            resp = client.get("/api/memories", params={"date": "2025-06-15"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["has_memories"] is False
        assert body["years"] == []

    def test_top_per_year_limit(self, client):
        """Each year is limited to TOP_PER_YEAR photos (at DB level via ROW_NUMBER)."""
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []

        # DB returns only top 5 (ROW_NUMBER <= 5), but _year_total reflects the full 8
        photos = [
            {"path": f"/{i}.jpg", "date_taken": f"2023:03:14 {10+i:02d}:00:00", "aggregate": float(7-i), "tags": "", "tags_list": [], "filename": f"{i}.jpg", "_year": "2023", "_rn": i+1, "_year_total": 8}
            for i in range(5)
        ]

        with (
            mock.patch("api.routers.memories.get_async_db", _async_cm(_make_async_conn([]))),
            mock.patch("api.routers.memories.get_visibility_clause", return_value=("1=1", [])),
            mock.patch("api.routers.memories.build_photo_select_columns", return_value=["path"]),
            mock.patch("api.routers.memories.get_photos_from_clause", return_value=("photos", [])),
            mock.patch("api.routers.memories.split_photo_tags", return_value=photos),
            mock.patch("api.routers.memories.attach_person_data_async", _async_noop),
            mock.patch("api.routers.memories.format_date", return_value="14/03/2023"),
            mock.patch("api.routers.memories.sanitize_float_values"),
            mock.patch("api.config.VIEWER_CONFIG", {"display": {"tags_per_photo": 10}}),
        ):
            resp = client.get("/api/memories", params={"date": "2025-03-14"})

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["years"]) == 1
        assert len(body["years"][0]["photos"]) == 5
        assert body["years"][0]["total_count"] == 8
