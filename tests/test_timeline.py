"""Tests for the timeline endpoint (api/routers/timeline.py)."""

import sqlite3
from contextlib import asynccontextmanager, contextmanager
from unittest import mock

import aiosqlite
import pytest
from fastapi.testclient import TestClient

from api import create_app
from api.auth import get_optional_user
from db.schema import init_database


def _cm(conn):
    @contextmanager
    def _ctx():
        yield conn
    return _ctx()


def _async_cm(conn):
    """Async context manager wrapping a mock connection — for get_async_db patches."""
    @asynccontextmanager
    async def _ctx():
        yield conn
    return _ctx


def _make_async_conn(fetchall_side_effects):
    """Build a mock that mimics aiosqlite.Connection.

    Each call to ``await conn.execute(...)`` returns a cursor whose
    ``await cursor.fetchall()`` returns the next item from ``fetchall_side_effects``.
    """
    class _Cursor:
        def __init__(self, rows):
            self._rows = rows

        async def fetchall(self):
            return self._rows

        async def fetchone(self):
            return self._rows[0] if self._rows else None

        async def close(self):
            pass

    rows_iter = iter(fetchall_side_effects)

    class _Conn:
        async def execute(self, *args, **kwargs):
            try:
                return _Cursor(next(rows_iter))
            except StopIteration:
                return _Cursor([])

    return _Conn()


@pytest.fixture()
def client():
    app = create_app()
    return TestClient(app)


# ---------------------------------------------------------------------------
# Real-DB helpers — the mock-conn helpers above discard execute() args, so
# they cannot assert what the WHERE clause actually filtered. These back the
# gate tests with a real, schema-initialised SQLite DB instead.
# ---------------------------------------------------------------------------

_SAMPLE_PHOTO = {
    "filename": "a.jpg", "aggregate": 7.0, "aesthetic": 6.0,
    "comp_score": 5.0, "tech_sharpness": 4.0, "color_score": 5.0,
    "exposure_score": 6.0, "category": "default",
    "image_width": 4000, "image_height": 3000,
}


def _photo(path, date_taken, **overrides):
    return {**_SAMPLE_PHOTO, "path": path, "date_taken": date_taken, **overrides}


def _make_db(path, photos):
    init_database(path)
    conn = sqlite3.connect(path)
    for p in photos:
        cols = list(p.keys())
        placeholders = ", ".join("?" for _ in cols)
        conn.execute(
            f"INSERT INTO photos ({', '.join(cols)}) VALUES ({placeholders})",
            [p[c] for c in cols],
        )
    conn.commit()
    conn.close()


def _existing_columns(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return {row[1] for row in conn.execute("PRAGMA table_info(photos)")}
    finally:
        conn.close()


def _conn_factory(db_path):
    @contextmanager
    def factory():
        c = sqlite3.connect(db_path, check_same_thread=False)
        c.row_factory = sqlite3.Row
        try:
            yield c
        finally:
            c.close()
    return factory


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


def _app_no_auth():
    app = create_app()
    app.dependency_overrides[get_optional_user] = lambda: None
    return app


_GALLERY_VIEWER_CONFIG = {
    "display": {"tags_per_photo": 5},
    "pagination": {"default_per_page": 64, "max_per_page": 200},
    "defaults": {"sort": "aggregate", "sort_direction": "DESC", "type": ""},
    "dropdowns": {"min_photos_for_person": 2, "max_persons": 100},
    "quality_thresholds": {},
    "features": {},
}


class TestTimelineHideDefaultsRealDb:
    """Issue #112: /api/timeline* must resolve absent hide toggles from
    viewer.defaults, the same way the gallery it hands the user to already
    counts by default, instead of counting/ranking over every frame.
    """

    _PHOTOS = [
        _photo("/lead.jpg", "2025:03:10 10:00:00", aggregate=5.0,
               is_burst_lead=1, burst_group_id=1),
        _photo("/follower.jpg", "2025:03:10 10:00:01", aggregate=9.0,
               is_burst_lead=0, burst_group_id=1),
    ]

    def _timeline_patches(self, db_path, defaults):
        return (
            mock.patch("api.routers.timeline.get_async_db", _async_conn_factory(db_path)),
            mock.patch("api.routers.timeline.get_visibility_clause", return_value=("1=1", [])),
            mock.patch("api.routers.timeline.get_photos_from_clause", return_value=("photos", [])),
            mock.patch("api.db_helpers.VIEWER_CONFIG", {"defaults": defaults}),
            mock.patch("api.db_helpers._existing_columns_cache", _existing_columns(db_path)),
        )

    def test_default_hides_burst_follower(self, tmp_path):
        db_path = str(tmp_path / "timeline.db")
        _make_db(db_path, self._PHOTOS)
        client = TestClient(_app_no_auth())
        patches = self._timeline_patches(db_path, {"hide_bursts": True})
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            resp = client.get("/api/timeline/dates", params={"year": 2025})
        assert resp.status_code == 200
        dates = resp.json()["dates"]
        assert len(dates) == 1
        assert dates[0]["count"] == 1

    def test_explicit_hide_bursts_zero_shows_both(self, tmp_path):
        db_path = str(tmp_path / "timeline.db")
        _make_db(db_path, self._PHOTOS)
        client = TestClient(_app_no_auth())
        patches = self._timeline_patches(db_path, {"hide_bursts": True})
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            resp = client.get("/api/timeline/dates", params={"year": 2025, "hide_bursts": "0"})
        assert resp.status_code == 200
        dates = resp.json()["dates"]
        assert len(dates) == 1
        assert dates[0]["count"] == 2

    def test_hero_is_the_lead_even_though_the_follower_scores_higher(self, tmp_path):
        """Pins that the hero query shares the same WHERE as the count: the
        follower has the higher aggregate (9.0 vs 5.0) but must not surface
        as the hero while it is hidden by the default."""
        db_path = str(tmp_path / "timeline.db")
        _make_db(db_path, self._PHOTOS)
        client = TestClient(_app_no_auth())
        patches = self._timeline_patches(db_path, {"hide_bursts": True})
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            resp = client.get("/api/timeline/dates", params={"year": 2025})
        assert resp.status_code == 200
        dates = resp.json()["dates"]
        assert dates[0]["hero_photo_path"] == "/lead.jpg"

    def _gallery_patches(self, db_path):
        return (
            mock.patch("api.routers.gallery.get_db", _conn_factory(db_path)),
            mock.patch("api.routers.gallery.get_async_db", _async_conn_factory(db_path)),
            mock.patch("api.routers.gallery.get_visibility_clause", return_value=("1=1", [])),
            mock.patch("api.routers.gallery.VIEWER_CONFIG", _GALLERY_VIEWER_CONFIG),
            mock.patch.dict("api.config._count_cache", {}, clear=True),
        )

    def test_day_count_matches_gallery_total_default_state(self, tmp_path):
        """The success criterion: /api/timeline/dates day count must equal
        /api/photos' total for the same day, in both toggle states."""
        db_path = str(tmp_path / "timeline.db")
        _make_db(db_path, self._PHOTOS)
        client = TestClient(_app_no_auth())
        tl_patches = self._timeline_patches(db_path, {"hide_bursts": True})
        gallery_patches = self._gallery_patches(db_path)
        with (
            tl_patches[0], tl_patches[1], tl_patches[2], tl_patches[3], tl_patches[4],
            gallery_patches[0], gallery_patches[1], gallery_patches[2],
            gallery_patches[3], gallery_patches[4],
        ):
            tl_resp = client.get("/api/timeline/dates", params={"year": 2025})
            gallery_resp = client.get("/api/photos", params={
                "date_from": "2025-03-10", "date_to": "2025-03-10",
                "hide_bursts": "1", "per_page": 50,
            })
        assert tl_resp.status_code == 200
        assert gallery_resp.status_code == 200
        assert tl_resp.json()["dates"][0]["count"] == gallery_resp.json()["total"]

    def test_day_count_matches_gallery_total_toggle_off(self, tmp_path):
        db_path = str(tmp_path / "timeline.db")
        _make_db(db_path, self._PHOTOS)
        client = TestClient(_app_no_auth())
        tl_patches = self._timeline_patches(db_path, {"hide_bursts": True})
        gallery_patches = self._gallery_patches(db_path)
        with (
            tl_patches[0], tl_patches[1], tl_patches[2], tl_patches[3], tl_patches[4],
            gallery_patches[0], gallery_patches[1], gallery_patches[2],
            gallery_patches[3], gallery_patches[4],
        ):
            tl_resp = client.get("/api/timeline/dates", params={"year": 2025, "hide_bursts": "0"})
            gallery_resp = client.get("/api/photos", params={
                "date_from": "2025-03-10", "date_to": "2025-03-10",
                "hide_bursts": "0", "per_page": 50,
            })
        assert tl_resp.status_code == 200
        assert gallery_resp.status_code == 200
        assert tl_resp.json()["dates"][0]["count"] == gallery_resp.json()["total"]


class TestTimelineYearsRealDb:
    """GET /api/timeline/years — no coverage previously existed at all."""

    _PHOTOS = [
        _photo("/lead.jpg", "2025:03:10 10:00:00", aggregate=5.0,
               is_burst_lead=1, burst_group_id=1),
        _photo("/follower.jpg", "2025:03:10 10:00:01", aggregate=9.0,
               is_burst_lead=0, burst_group_id=1),
        _photo("/other-year.jpg", "2024:01:05 10:00:00", aggregate=4.0),
    ]

    def _patches(self, db_path, defaults):
        return (
            mock.patch("api.routers.timeline.get_async_db", _async_conn_factory(db_path)),
            mock.patch("api.routers.timeline.get_visibility_clause", return_value=("1=1", [])),
            mock.patch("api.routers.timeline.get_photos_from_clause", return_value=("photos", [])),
            mock.patch("api.db_helpers.VIEWER_CONFIG", {"defaults": defaults}),
            mock.patch("api.db_helpers._existing_columns_cache", _existing_columns(db_path)),
        )

    def test_default_hides_burst_follower(self, tmp_path):
        db_path = str(tmp_path / "timeline.db")
        _make_db(db_path, self._PHOTOS)
        client = TestClient(_app_no_auth())
        patches = self._patches(db_path, {"hide_bursts": True})
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            resp = client.get("/api/timeline/years")
        assert resp.status_code == 200
        years = {y["year"]: y["count"] for y in resp.json()["years"]}
        assert years == {"2025": 1, "2024": 1}

    def test_explicit_hide_bursts_zero_counts_everything(self, tmp_path):
        db_path = str(tmp_path / "timeline.db")
        _make_db(db_path, self._PHOTOS)
        client = TestClient(_app_no_auth())
        patches = self._patches(db_path, {"hide_bursts": True})
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            resp = client.get("/api/timeline/years", params={"hide_bursts": "0"})
        assert resp.status_code == 200
        years = {y["year"]: y["count"] for y in resp.json()["years"]}
        assert years == {"2025": 2, "2024": 1}


class TestTimelineMonthsRealDb:
    """GET /api/timeline/months — no coverage previously existed at all."""

    _PHOTOS = [
        _photo("/lead.jpg", "2025:03:10 10:00:00", aggregate=5.0,
               is_burst_lead=1, burst_group_id=1),
        _photo("/follower.jpg", "2025:03:10 10:00:01", aggregate=9.0,
               is_burst_lead=0, burst_group_id=1),
        _photo("/other-month.jpg", "2025:06:05 10:00:00", aggregate=4.0),
    ]

    def _patches(self, db_path, defaults):
        return (
            mock.patch("api.routers.timeline.get_async_db", _async_conn_factory(db_path)),
            mock.patch("api.routers.timeline.get_visibility_clause", return_value=("1=1", [])),
            mock.patch("api.routers.timeline.get_photos_from_clause", return_value=("photos", [])),
            mock.patch("api.db_helpers.VIEWER_CONFIG", {"defaults": defaults}),
            mock.patch("api.db_helpers._existing_columns_cache", _existing_columns(db_path)),
        )

    def test_default_hides_burst_follower(self, tmp_path):
        db_path = str(tmp_path / "timeline.db")
        _make_db(db_path, self._PHOTOS)
        client = TestClient(_app_no_auth())
        patches = self._patches(db_path, {"hide_bursts": True})
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            resp = client.get("/api/timeline/months", params={"year": 2025})
        assert resp.status_code == 200
        months = {m["month"]: m["count"] for m in resp.json()["months"]}
        assert months == {"2025-03": 1, "2025-06": 1}

    def test_explicit_hide_bursts_zero_counts_everything(self, tmp_path):
        db_path = str(tmp_path / "timeline.db")
        _make_db(db_path, self._PHOTOS)
        client = TestClient(_app_no_auth())
        patches = self._patches(db_path, {"hide_bursts": True})
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            resp = client.get("/api/timeline/months", params={"year": 2025, "hide_bursts": "0"})
        assert resp.status_code == 200
        months = {m["month"]: m["count"] for m in resp.json()["months"]}
        assert months == {"2025-03": 2, "2025-06": 1}


class TestTimelineEndpoint:
    """Tests for GET /api/timeline."""

    def test_returns_date_groups(self, client):
        """Returns photos grouped by date."""
        date_rows = [
            {"photo_date": "2025-03-10", "cnt": 5},
            {"photo_date": "2025-03-09", "cnt": 3},
        ]
        # The async endpoint runs two queries: dates, then one big photo query
        # using ROW_NUMBER() (not one per date as the old sync code suggested).
        photo_rows = [
            {"path": "/a.jpg", "date_taken": "2025:03:10 14:00:00", "aggregate": 8.5, "tags": "landscape", "filename": "a.jpg", "_photo_date": "2025-03-10", "_rn": 1},
            {"path": "/b.jpg", "date_taken": "2025:03:09 10:00:00", "aggregate": 7.0, "tags": "portrait", "filename": "b.jpg", "_photo_date": "2025-03-09", "_rn": 1},
        ]

        async_conn = _make_async_conn([date_rows, photo_rows])

        async def _no_op_attach(*args, **kwargs):
            return None

        with (
            mock.patch("api.routers.timeline.get_async_db", _async_cm(async_conn)),
            mock.patch("api.routers.timeline.get_visibility_clause", return_value=("1=1", [])),
            mock.patch("api.routers.timeline.get_photos_from_clause", return_value=("photos", [])),
            mock.patch("api.routers.timeline.build_photo_select_columns", return_value=["path", "date_taken", "aggregate", "tags"]),
            mock.patch("api.routers.timeline.VIEWER_CONFIG", {"display": {"tags_per_photo": 10}}),
            mock.patch("api.routers.timeline.split_photo_tags", side_effect=lambda rows, limit: [dict(r) for r in rows]),
            mock.patch("api.routers.timeline.attach_person_data_async", _no_op_attach),
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
        async_conn = _make_async_conn([[]])  # no date_rows after cursor

        with (
            mock.patch("api.routers.timeline.get_async_db", _async_cm(async_conn)),
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
        # Return limit+1 rows to trigger has_more
        date_rows = [{"photo_date": f"2025-03-{10-i:02d}", "cnt": 1} for i in range(4)]
        photo_rows = [
            {"path": f"/{i}.jpg", "date_taken": f"2025:03:{10-i:02d} 10:00:00",
             "aggregate": 5.0, "tags": "", "filename": f"{i}.jpg",
             "_photo_date": f"2025-03-{10-i:02d}", "_rn": 1}
            for i in range(3)
        ]

        async_conn = _make_async_conn([date_rows, photo_rows])

        async def _no_op_attach(*args, **kwargs):
            return None

        with (
            mock.patch("api.routers.timeline.get_async_db", _async_cm(async_conn)),
            mock.patch("api.routers.timeline.get_visibility_clause", return_value=("1=1", [])),
            mock.patch("api.routers.timeline.get_photos_from_clause", return_value=("photos", [])),
            mock.patch("api.routers.timeline.build_photo_select_columns", return_value=["path", "date_taken", "aggregate", "tags"]),
            mock.patch("api.routers.timeline.VIEWER_CONFIG", {"display": {"tags_per_photo": 10}}),
            mock.patch("api.routers.timeline.split_photo_tags", side_effect=lambda rows, limit: [dict(r) for r in rows]),
            mock.patch("api.routers.timeline.attach_person_data_async", _no_op_attach),
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
        async_conn = _make_async_conn([
            [{"photo_date": "2025-03-12", "cnt": 2}],
            [{"path": "/x.jpg", "date_taken": "2025:03:12 10:00:00", "aggregate": 6.0, "tags": "", "filename": "x.jpg", "_photo_date": "2025-03-12", "_rn": 1}],
        ])

        async def _no_op_attach(*args, **kwargs):
            return None

        with (
            mock.patch("api.routers.timeline.get_async_db", _async_cm(async_conn)),
            mock.patch("api.routers.timeline.get_visibility_clause", return_value=("1=1", [])),
            mock.patch("api.routers.timeline.get_photos_from_clause", return_value=("photos", [])),
            mock.patch("api.routers.timeline.build_photo_select_columns", return_value=["path", "date_taken", "aggregate", "tags"]),
            mock.patch("api.routers.timeline.VIEWER_CONFIG", {"display": {"tags_per_photo": 10}}),
            mock.patch("api.routers.timeline.split_photo_tags", side_effect=lambda rows, limit: [dict(r) for r in rows]),
            mock.patch("api.routers.timeline.attach_person_data_async", _no_op_attach),
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
        async_conn = _make_async_conn([
            [{"photo_date": "2025-03-15", "cnt": 1}],
            [{"path": "/n.jpg", "date_taken": "2025:03:15 10:00:00", "aggregate": 6.0, "tags": "", "filename": "n.jpg", "_photo_date": "2025-03-15", "_rn": 1}],
        ])

        async def _no_op_attach(*args, **kwargs):
            return None

        with (
            mock.patch("api.routers.timeline.get_async_db", _async_cm(async_conn)),
            mock.patch("api.routers.timeline.get_visibility_clause", return_value=("1=1", [])),
            mock.patch("api.routers.timeline.get_photos_from_clause", return_value=("photos", [])),
            mock.patch("api.routers.timeline.build_photo_select_columns", return_value=["path", "date_taken", "aggregate", "tags"]),
            mock.patch("api.routers.timeline.VIEWER_CONFIG", {"display": {"tags_per_photo": 10}}),
            mock.patch("api.routers.timeline.split_photo_tags", side_effect=lambda rows, limit: [dict(r) for r in rows]),
            mock.patch("api.routers.timeline.attach_person_data_async", _no_op_attach),
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

        class _BrokenConn:
            async def execute(self, *a, **kw):
                raise Exception("DB error")

        with (
            mock.patch("api.routers.timeline.get_async_db", _async_cm(_BrokenConn())),
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
        async_conn = _make_async_conn([[
            {"group_key": "2025-03-10", "cnt": 15, "hero_photo_path": "/photos/a.jpg"},
            {"group_key": "2025-03-11", "cnt": 8, "hero_photo_path": "/photos/b.jpg"},
        ]])

        with (
            mock.patch("api.routers.timeline.get_async_db", _async_cm(async_conn)),
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
        async_conn = _make_async_conn([[
            {"group_key": "2025-06-15", "cnt": 3, "hero_photo_path": "/photos/c.jpg"},
        ]])

        with (
            mock.patch("api.routers.timeline.get_async_db", _async_cm(async_conn)),
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

        class _BrokenConn:
            async def execute(self, *a, **kw):
                raise Exception("DB error")

        with (
            mock.patch("api.routers.timeline.get_async_db", _async_cm(_BrokenConn())),
            mock.patch("api.routers.timeline.get_visibility_clause", return_value=("1=1", [])),
            mock.patch("api.routers.timeline.get_photos_from_clause", return_value=("photos", [])),
        ):
            resp = client.get("/api/timeline/dates", params={"year": 2025})

        assert resp.status_code == 200
        assert resp.json()["dates"] == []

    def test_missing_year_returns_422(self, client):
        resp = client.get("/api/timeline/dates")
        assert resp.status_code == 422
