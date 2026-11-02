"""Tests for the timeline endpoint (api/routers/timeline.py)."""

import sqlite3
from contextlib import ExitStack, asynccontextmanager, contextmanager
from unittest import mock

import aiosqlite
import pytest
from fastapi.testclient import TestClient

from api import create_app
from api.auth import get_optional_user
from db.schema import init_database


def test_iso_week_boundaries_and_calendar_date_limits_use_capture_days(tmp_path):
    path = str(tmp_path / 'iso-weeks.db')
    dates = ['2020:12:28 12:00:00', '2021-01-01T12:00:00', '2021:01:03 12:00:00',
             '2021:01:04 12:00:00', '2021-01-10T12:00:00', '2021:01:11 12:00:00']
    _make_db(path, [_photo(f'/week/{index}.jpg', day) for index, day in enumerate(dates)])
    with ExitStack() as stack:
        for patch in _timeline_hide_defaults_patches(path, {}):
            stack.enter_context(patch)
        client = TestClient(_app_no_auth())
        params = {'granularity': 'week', 'direction': 'newer'}
        result = client.get('/api/timeline', params=params)
        assert result.status_code == 200, result.text
        assert [(group['date'], group['count']) for group in result.json()['groups']] == [('2020-W53', 3), ('2021-W01', 2), ('2021-W02', 1)]
        narrowed = client.get('/api/timeline', params={**params, 'date_from': '2021-01-02', 'date_to': '2021-01-04'})
        assert narrowed.status_code == 200, narrowed.text
        assert [(group['date'], group['count']) for group in narrowed.json()['groups']] == [('2020-W53', 1), ('2021-W01', 1)]
        assert {photo['path'] for group in narrowed.json()['groups'] for photo in group['photos']} == {'/week/2.jpg', '/week/3.jpg'}
        later = client.get('/api/timeline', params={**params, 'cursor': '2020-W53'})
        assert later.status_code == 200, later.text
        assert [group['date'] for group in later.json()['groups']] == ['2021-W01', '2021-W02']


def test_month_groups_apply_partial_calendar_day_bounds(tmp_path):
    path = str(tmp_path / 'month-limits.db')
    _make_db(path, [_photo('/month/early.jpg', '2024:02:01 12:00:00'), _photo('/month/middle.jpg', '2024-02-15T12:00:00'),
                    _photo('/month/late.jpg', '2024:02:29 12:00:00')])
    with ExitStack() as stack:
        for patch in _timeline_hide_defaults_patches(path, {}):
            stack.enter_context(patch)
        response = TestClient(_app_no_auth()).get('/api/timeline', params={'granularity': 'month', 'date_from': '2024-02-10', 'date_to': '2024-02-20'})
        assert response.status_code == 200, response.text
        groups = response.json()['groups']
        assert [(group['date'], group['count']) for group in groups] == [('2024-02', 1)]
        assert [photo['path'] for photo in groups[0]['photos']] == ['/month/middle.jpg']


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
            if args and args[0] == 'BEGIN':
                return _Cursor([])
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


def _timeline_hide_defaults_patches(db_path, defaults):
    """Patch the timeline router onto a real temp DB, with a given viewer.defaults."""
    return (
        mock.patch("api.routers.timeline.get_async_db", _async_conn_factory(db_path)),
        mock.patch("api.routers.timeline.get_visibility_clause", return_value=("1=1", [])),
        mock.patch("api.routers.timeline.read_source_async", return_value=("photos", [], False)),
        mock.patch("api.db_helpers.VIEWER_CONFIG", {"defaults": defaults}),
        mock.patch("api.db_helpers._existing_columns_cache", _existing_columns(db_path)),
    )


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

    def test_default_hides_burst_follower(self, tmp_path):
        db_path = str(tmp_path / "timeline.db")
        _make_db(db_path, self._PHOTOS)
        client = TestClient(_app_no_auth())
        patches = _timeline_hide_defaults_patches(db_path, {"hide_bursts": True})
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
        patches = _timeline_hide_defaults_patches(db_path, {"hide_bursts": True})
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
        patches = _timeline_hide_defaults_patches(db_path, {"hide_bursts": True})
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
        tl_patches = _timeline_hide_defaults_patches(db_path, {"hide_bursts": True})
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
        tl_patches = _timeline_hide_defaults_patches(db_path, {"hide_bursts": True})
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

    def test_explicit_all_type_matches_timeline_instead_of_reapplying_configured_category(self, tmp_path):
        db_path = str(tmp_path / 'timeline-category.db')
        _make_db(db_path, [
            _photo('/normal.jpg', '2025:03:10 10:00:00', category='landscape', is_monochrome=0),
            _photo('/rejected.jpg', '2025:03:10 12:00:00', category='landscape', is_rejected=1),
            _photo('/favorite.jpg', '2025:03:10 14:00:00', category='landscape', is_favorite=1),
        ])
        client = TestClient(_app_no_auth())
        config = {**_GALLERY_VIEWER_CONFIG, 'defaults': {**_GALLERY_VIEWER_CONFIG['defaults'], 'type': 'configured'}}
        with ExitStack() as stack:
            for patch in (*_timeline_hide_defaults_patches(db_path, {}), *self._gallery_patches(db_path)):
                stack.enter_context(patch)
            stack.enter_context(mock.patch('api.routers.gallery.VIEWER_CONFIG', config))
            stack.enter_context(mock.patch.dict('api.routers.gallery.TYPE_FILTERS', {'configured': {'category': 'portrait'}}))
            timeline = client.get('/api/timeline/dates', params={'year': 2025})
            narrowed = client.get('/api/photos', params={'date_from': '2025-03-10', 'date_to': '2025-03-10'})
            opened_day = client.get('/api/photos', params={'type': '', 'date_from': '2025-03-10', 'date_to': '2025-03-10'})
        assert timeline.status_code == narrowed.status_code == opened_day.status_code == 200
        assert narrowed.json()['photo_total'] == 0
        assert timeline.json()['dates'][0]['count'] == opened_day.json()['photo_total'] == 3
        assert {row['path'] for row in opened_day.json()['photos']} == {'/normal.jpg', '/rejected.jpg', '/favorite.jpg'}


class TestTimelineApiHideDefaultsRealDb:
    """GET /api/timeline itself wires the hide-toggle fix at two independent
    call sites: the date/count query and the per-day photo batch query below
    it. Neither had real-DB coverage — a mock-conn test cannot see whether the
    WHERE clause actually filtered anything (issue #112 follow-up).
    """

    _PHOTOS = [
        _photo("/lead.jpg", "2025:03:10 10:00:00", aggregate=5.0,
               is_burst_lead=1, burst_group_id=1),
        _photo("/follower.jpg", "2025:03:10 10:00:01", aggregate=9.0,
               is_burst_lead=0, burst_group_id=1),
    ]

    def _patches(self, db_path, defaults):
        return _timeline_hide_defaults_patches(db_path, defaults) + (
            mock.patch("api.routers.timeline.VIEWER_CONFIG", {"display": {"tags_per_photo": 10}}),
        )

    def test_density_month_counts_include_both_iso_and_exif_capture_dates(self, tmp_path):
        db_path = str(tmp_path / 'mixed-dates.db')
        _make_db(db_path, [_photo('/iso.jpg', '2024-02-29 10:00:00'), _photo('/exif.jpg', '2024:02:29 11:00:00')])
        client = TestClient(_app_no_auth())
        with ExitStack() as stack:
            for patch in self._patches(db_path, {}):
                stack.enter_context(patch)
            whole_year = client.get('/api/timeline/dates', params={'year': 2024}).json()
            month_days = client.get('/api/timeline/dates', params={'year': 2024, 'month': 2}).json()
            feed = client.get('/api/timeline', params={'date_from': '2024-02-01', 'date_to': '2024-02-29'}).json()
        assert whole_year['dates'][0]['count'] == month_days['dates'][0]['count'] == feed['groups'][0]['count'] == 2
        assert {photo['path'] for photo in feed['groups'][0]['photos']} == {'/iso.jpg', '/exif.jpg'}

    def test_density_preview_orders_mixed_date_formats_by_camera_local_clock(self, tmp_path):
        db_path = str(tmp_path / 'mixed-order.db')
        _make_db(db_path, [
            _photo('/iso-evening.jpg', '2024-02-29T19:00:00'),
            _photo('/exif-morning.jpg', '2024:02:29 09:00:00'),
            _photo('/iso-noon.jpg', '2024-02-29 12:00:00'),
        ])
        client = TestClient(_app_no_auth())
        with ExitStack() as stack:
            for patch in self._patches(db_path, {}):
                stack.enter_context(patch)
            newer_first = client.get('/api/timeline', params={'sort_by': 'date_taken', 'photos_per_group': 1}).json()
            older_first = client.get('/api/timeline', params={'sort_by': 'date_taken', 'direction': 'newer', 'photos_per_group': 1}).json()
        assert newer_first['groups'][0]['photos'][0]['path'] == '/iso-evening.jpg'
        assert older_first['groups'][0]['photos'][0]['path'] == '/exif-morning.jpg'

    def test_photo_feed_orders_each_date_and_pages_without_repeating_days(self, tmp_path):
        db_path = str(tmp_path / 'feed.db')
        _make_db(db_path, [
            _photo('/morning.jpg', '2026:11:01 09:00:00'),
            _photo('/evening.jpg', '2026:11:01 19:00:00'),
            _photo('/noon.jpg', '2026:11:01 12:00:00'),
            _photo('/earlier.jpg', '2026:10:30 10:00:00'),
            _photo('/unknown.jpg', None),
        ])
        client = TestClient(_app_no_auth())
        with ExitStack() as stack:
            for patch in self._patches(db_path, {}):
                stack.enter_context(patch)
            first = client.get('/api/timeline', params={'limit': 1, 'photos_per_group': 2, 'sort_by': 'date_taken'}).json()
            assert first['groups'][0]['count'] == 3
            assert [photo['path'] for photo in first['groups'][0]['photos']] == ['/evening.jpg', '/noon.jpg']
            assert first['next_cursor'] == '2026-11-01'
            second = client.get('/api/timeline', params={'cursor': first['next_cursor'], 'limit': 1, 'sort_by': 'date_taken'}).json()
            assert [group['date'] for group in second['groups']] == ['2026-10-30']
            assert second['has_more'] is False
            newer = client.get('/api/timeline', params={'direction': 'newer', 'date_from': '2026-11-01', 'photos_per_group': 2, 'sort_by': 'date_taken'}).json()
            assert [photo['path'] for photo in newer['groups'][0]['photos']] == ['/morning.jpg', '/noon.jpg']

    def test_photo_feed_counts_and_membership_use_one_read_snapshot(self, tmp_path):
        db_path = str(tmp_path / 'snapshot.db')
        _make_db(db_path, [_photo('/before.jpg', '2026:11:01 09:00:00')])
        with sqlite3.connect(db_path) as writer:
            writer.execute('PRAGMA journal_mode=WAL')
        inserted = False

        @asynccontextmanager
        async def concurrent_read():
            nonlocal inserted
            async with aiosqlite.connect(db_path) as conn:
                conn.row_factory = aiosqlite.Row

                class WithConcurrentCommit:
                    async def execute(self, query, params=()):
                        nonlocal inserted
                        if 'ROW_NUMBER()' in query and not inserted:
                            # A genuine other-connection commit between the count and photo reads.
                            with sqlite3.connect(db_path) as writer:
                                writer.execute("INSERT INTO photos(path,filename,date_taken) VALUES('/later.jpg','later.jpg','2026:11:01 20:00:00')")
                            inserted = True
                        return await conn.execute(query, params)

                yield WithConcurrentCommit()

        with ExitStack() as stack:
            for patch in self._patches(db_path, {}):
                stack.enter_context(patch)
            stack.enter_context(mock.patch('api.routers.timeline.get_async_db', concurrent_read))
            response = TestClient(_app_no_auth()).get('/api/timeline', params={'sort_by': 'date_taken'})
        assert response.status_code == 200
        assert inserted
        group = response.json()['groups'][0]
        assert group['count'] == 1
        assert [photo['path'] for photo in group['photos']] == ['/before.jpg']

    def test_default_hides_burst_follower_in_count_and_photos(self, tmp_path):
        db_path = str(tmp_path / "timeline.db")
        _make_db(db_path, self._PHOTOS)
        client = TestClient(_app_no_auth())
        patches = self._patches(db_path, {"hide_bursts": True})
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            resp = client.get("/api/timeline", params={"photos_per_group": 10})
        assert resp.status_code == 200
        groups = resp.json()["groups"]
        assert len(groups) == 1
        assert groups[0]["count"] == 1
        assert [p["path"] for p in groups[0]["photos"]] == ["/lead.jpg"]

    def test_explicit_hide_bursts_zero_shows_both_in_count_and_photos(self, tmp_path):
        db_path = str(tmp_path / "timeline.db")
        _make_db(db_path, self._PHOTOS)
        client = TestClient(_app_no_auth())
        patches = self._patches(db_path, {"hide_bursts": True})
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            resp = client.get("/api/timeline", params={"photos_per_group": 10, "hide_bursts": "0"})
        assert resp.status_code == 200
        groups = resp.json()["groups"]
        assert len(groups) == 1
        assert groups[0]["count"] == 2
        assert {p["path"] for p in groups[0]["photos"]} == {"/lead.jpg", "/follower.jpg"}


class TestTimelineYearsRealDb:
    """GET /api/timeline/years — no coverage previously existed at all."""

    _PHOTOS = [
        _photo("/lead.jpg", "2025:03:10 10:00:00", aggregate=5.0,
               is_burst_lead=1, burst_group_id=1),
        _photo("/follower.jpg", "2025:03:10 10:00:01", aggregate=9.0,
               is_burst_lead=0, burst_group_id=1),
        _photo("/other-year.jpg", "2024:01:05 10:00:00", aggregate=4.0),
    ]

    def test_default_hides_burst_follower(self, tmp_path):
        db_path = str(tmp_path / "timeline.db")
        _make_db(db_path, self._PHOTOS)
        client = TestClient(_app_no_auth())
        patches = _timeline_hide_defaults_patches(db_path, {"hide_bursts": True})
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            resp = client.get("/api/timeline/years")
        assert resp.status_code == 200
        years = {y["year"]: y["count"] for y in resp.json()["years"]}
        assert years == {"2025": 1, "2024": 1}

    def test_explicit_hide_bursts_zero_counts_everything(self, tmp_path):
        db_path = str(tmp_path / "timeline.db")
        _make_db(db_path, self._PHOTOS)
        client = TestClient(_app_no_auth())
        patches = _timeline_hide_defaults_patches(db_path, {"hide_bursts": True})
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

    def test_default_hides_burst_follower(self, tmp_path):
        db_path = str(tmp_path / "timeline.db")
        _make_db(db_path, self._PHOTOS)
        client = TestClient(_app_no_auth())
        patches = _timeline_hide_defaults_patches(db_path, {"hide_bursts": True})
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            resp = client.get("/api/timeline/months", params={"year": 2025})
        assert resp.status_code == 200
        months = {m["month"]: m["count"] for m in resp.json()["months"]}
        assert months == {"2025-03": 1, "2025-06": 1}

    def test_explicit_hide_bursts_zero_counts_everything(self, tmp_path):
        db_path = str(tmp_path / "timeline.db")
        _make_db(db_path, self._PHOTOS)
        client = TestClient(_app_no_auth())
        patches = _timeline_hide_defaults_patches(db_path, {"hide_bursts": True})
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
            mock.patch("api.routers.timeline.read_source_async", return_value=("photos", [], False)),
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
            mock.patch("api.routers.timeline.read_source_async", return_value=("photos", [], False)),
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
            mock.patch("api.routers.timeline.read_source_async", return_value=("photos", [], False)),
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
            mock.patch("api.routers.timeline.read_source_async", return_value=("photos", [], False)),
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
            mock.patch("api.routers.timeline.read_source_async", return_value=("photos", [], False)),
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

    def test_db_error_returns_retryable_failure(self):
        """A failed read must not masquerade as a successfully empty library."""
        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)

        class _BrokenConn:
            async def execute(self, *a, **kw):
                raise Exception("DB error")

        with (
            mock.patch("api.routers.timeline.get_async_db", _async_cm(_BrokenConn())),
            mock.patch("api.routers.timeline.get_visibility_clause", return_value=("1=1", [])),
            mock.patch("api.routers.timeline.read_source_async", return_value=("photos", [], False)),
        ):
            resp = client.get("/api/timeline")

        assert resp.status_code == 503
        assert resp.json() == {"detail": "Timeline is temporarily unavailable"}


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
            mock.patch("api.routers.timeline.read_source_async", return_value=("photos", [], False)),
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
            mock.patch("api.routers.timeline.read_source_async", return_value=("photos", [], False)),
        ):
            resp = client.get("/api/timeline/dates", params={"year": 2025, "month": 6})

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["dates"]) == 1

    @pytest.mark.parametrize('endpoint,params', [
        ('dates', {'year': 2025}), ('years', {}), ('months', {'year': 2025}),
    ])
    def test_db_error_returns_retryable_summary_failure(self, endpoint, params):
        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)

        class _BrokenConn:
            async def execute(self, *a, **kw):
                raise Exception("DB error")

        with (
            mock.patch("api.routers.timeline.get_async_db", _async_cm(_BrokenConn())),
            mock.patch("api.routers.timeline.get_visibility_clause", return_value=("1=1", [])),
            mock.patch("api.routers.timeline.read_source_async", return_value=("photos", [], False)),
        ):
            resp = client.get(f"/api/timeline/{endpoint}", params=params)

        assert resp.status_code == 503
        assert resp.json()['detail'] == f'Timeline {endpoint} are temporarily unavailable'

    def test_missing_year_returns_422(self, client):
        resp = client.get("/api/timeline/dates")
        assert resp.status_code == 422
