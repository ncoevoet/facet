"""
Tests for the stats API router endpoints.

Covers: score_distribution, top_cameras, categories, correlations.

The stats GET endpoints are async (Topic 2 step 4): they read through
``get_async_db`` (aiosqlite) and cache via ``_get_stats_cached_async``. The
tests therefore patch ``get_async_db`` with a real aiosqlite-backed temp DB
(a MagicMock is not awaitable) and bypass the async cache so each request
recomputes against the seeded data. The POST write endpoint stays sync.
"""

import sqlite3
from contextlib import asynccontextmanager
from unittest import mock

import aiosqlite
from fastapi.testclient import TestClient

from api import create_app
from api.auth import get_optional_user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PHOTOS_SCHEMA = """
    CREATE TABLE photos (
        path TEXT PRIMARY KEY, filename TEXT, date_taken TEXT,
        camera_model TEXT, lens_model TEXT, iso REAL,
        f_stop REAL, shutter_speed TEXT, focal_length REAL,
        focal_length_35mm REAL,
        aesthetic REAL, face_count INTEGER, face_quality REAL,
        eye_sharpness REAL, face_sharpness REAL, face_ratio REAL,
        tech_sharpness REAL, color_score REAL, exposure_score REAL,
        comp_score REAL, isolation_bonus REAL, is_blink INTEGER,
        phash TEXT, is_burst_lead INTEGER, aggregate REAL,
        category TEXT, image_width INTEGER, image_height INTEGER,
        tags TEXT, composition_pattern TEXT, person_id INTEGER,
        is_monochrome INTEGER, dynamic_range_stops REAL,
        noise_sigma REAL, contrast_score REAL,
        mean_saturation REAL, quality_score REAL,
        power_point_score REAL, leading_lines_score REAL,
        face_confidence REAL,
        is_silhouette INTEGER DEFAULT 0, is_group_portrait INTEGER DEFAULT 0,
        mean_luminance REAL
    );
    CREATE TABLE faces (
        id INTEGER PRIMARY KEY, photo_path TEXT, face_index INTEGER,
        person_id INTEGER, confidence REAL
    );
    CREATE TABLE persons (
        id INTEGER PRIMARY KEY, name TEXT, representative_face_id INTEGER,
        face_count INTEGER, face_thumbnail BLOB
    );
"""

_DEFAULTS = {
    "filename": "photo.jpg",
    "aggregate": 7.0,
    "aesthetic": 6.0,
    "comp_score": 5.0,
    "tech_sharpness": 4.0,
    "color_score": 5.0,
    "exposure_score": 6.0,
    "category": "default",
    "image_width": 4000,
    "image_height": 3000,
}


def _photo(path, **overrides):
    """Build a photo dict with sensible defaults."""
    return {**_DEFAULTS, "path": path, **overrides}


def _make_stats_db(db_path, photos):
    """Create a photos table and insert rows."""
    conn = sqlite3.connect(db_path)
    conn.executescript(_PHOTOS_SCHEMA)
    for p in photos:
        cols = list(p.keys())
        placeholders = ", ".join("?" for _ in cols)
        conn.execute(
            f"INSERT INTO photos ({', '.join(cols)}) VALUES ({placeholders})",
            [p[c] for c in cols],
        )
    conn.commit()
    conn.close()


def _async_conn_factory(db_path: str):
    """Yield a real aiosqlite Connection bound to the test DB.

    The stats GET handlers are async and reach the DB via get_async_db; a
    MagicMock is not awaitable, so tests patch get_async_db with this factory.
    """
    @asynccontextmanager
    async def factory():
        c = await aiosqlite.connect(db_path)
        c.row_factory = aiosqlite.Row
        try:
            yield c
        finally:
            await c.close()
    return factory


async def _cache_passthrough(_key, compute_fn):
    """Async cache stand-in: always recompute (await the async compute_fn)."""
    return await compute_fn()


def _create_app_no_auth():
    app = create_app()
    app.dependency_overrides[get_optional_user] = lambda: None
    return app


# Common mock context for all stats tests: bypass cache + clear stale state.
def _stats_mocks(db_path):
    """Return a context manager that patches get_async_db, the async cache,
    and the column/count caches so each request hits the seeded temp DB."""
    from contextlib import ExitStack

    class _Ctx:
        def __enter__(self):
            self._stack = ExitStack()
            self._stack.enter_context(
                mock.patch("api.routers.stats.get_async_db",
                           _async_conn_factory(db_path)))
            self._stack.enter_context(
                mock.patch("api.routers.stats._get_stats_cached_async",
                           _cache_passthrough))
            self._stack.enter_context(
                mock.patch("api.db_helpers._existing_columns_cache", None))
            self._stack.enter_context(
                mock.patch.dict("api.config._count_cache", {}, clear=True))
            return self

        def __exit__(self, *exc):
            self._stack.__exit__(*exc)

    return _Ctx()


# ---------------------------------------------------------------------------
# TestScoreDistribution
# ---------------------------------------------------------------------------

class TestScoreDistribution:

    def test_returns_histogram_buckets(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _make_stats_db(db_path, [
            _photo("/a.jpg", aggregate=3.0),
            _photo("/b.jpg", aggregate=5.5),
            _photo("/c.jpg", aggregate=8.0),
            _photo("/d.jpg", aggregate=8.2),
        ])
        app = _create_app_no_auth()
        with _stats_mocks(db_path):
            resp = TestClient(app).get("/api/stats/score_distribution")
        assert resp.status_code == 200
        buckets = resp.json()
        assert isinstance(buckets, list)
        assert len(buckets) > 0
        # Each bucket has the expected keys
        for b in buckets:
            assert "range" in b
            assert "count" in b
            assert "percentage" in b
        # Total count across buckets matches number of photos
        assert sum(b["count"] for b in buckets) == 4

    def test_empty_db_returns_empty(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _make_stats_db(db_path, [])
        app = _create_app_no_auth()
        with _stats_mocks(db_path):
            resp = TestClient(app).get("/api/stats/score_distribution")
        assert resp.status_code == 200
        assert resp.json() == []


# ---------------------------------------------------------------------------
# TestTopCameras
# ---------------------------------------------------------------------------

class TestTopCameras:

    def test_returns_camera_counts(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        # HAVING cnt >= 10, so we need at least 10 photos per camera
        photos = []
        for i in range(15):
            photos.append(_photo(f"/canon_{i}.jpg", camera_model="Canon R6",
                                 aggregate=7.0 + i * 0.1))
        for i in range(12):
            photos.append(_photo(f"/sony_{i}.jpg", camera_model="Sony A7IV",
                                 aggregate=6.0 + i * 0.1))
        _make_stats_db(db_path, photos)
        app = _create_app_no_auth()
        with _stats_mocks(db_path):
            resp = TestClient(app).get("/api/stats/top_cameras")
        assert resp.status_code == 200
        cameras = resp.json()
        assert len(cameras) == 2
        names = [c["name"] for c in cameras]
        assert "Canon R6" in names
        assert "Sony A7IV" in names
        # Sorted by avg_agg desc — Canon has higher average
        assert cameras[0]["name"] == "Canon R6"
        # Counts are correct
        canon = next(c for c in cameras if c["name"] == "Canon R6")
        sony = next(c for c in cameras if c["name"] == "Sony A7IV")
        assert canon["count"] == 15
        assert sony["count"] == 12

    def test_cameras_below_threshold_excluded(self, tmp_path):
        """Cameras with fewer than 10 photos are excluded (HAVING cnt >= 10)."""
        db_path = str(tmp_path / "test.db")
        photos = [_photo(f"/few_{i}.jpg", camera_model="Rare Camera")
                  for i in range(5)]
        _make_stats_db(db_path, photos)
        app = _create_app_no_auth()
        with _stats_mocks(db_path):
            resp = TestClient(app).get("/api/stats/top_cameras")
        assert resp.status_code == 200
        assert resp.json() == []


# ---------------------------------------------------------------------------
# TestCategories
# ---------------------------------------------------------------------------

class TestCategories:

    def test_returns_category_list(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _make_stats_db(db_path, [
            _photo("/a.jpg", category="portrait"),
            _photo("/b.jpg", category="portrait"),
            _photo("/c.jpg", category="landscape"),
            _photo("/d.jpg", category="street"),
        ])
        app = _create_app_no_auth()
        with _stats_mocks(db_path):
            resp = TestClient(app).get("/api/stats/categories")
        assert resp.status_code == 200
        categories = resp.json()
        assert isinstance(categories, list)
        cat_names = [c["category"] for c in categories]
        assert "portrait" in cat_names
        assert "landscape" in cat_names
        assert "street" in cat_names
        # Sorted by count desc — portrait has 2
        assert categories[0]["category"] == "portrait"
        assert categories[0]["count"] == 2

    def test_category_stats_include_averages(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _make_stats_db(db_path, [
            _photo("/a.jpg", category="landscape", aggregate=8.0, aesthetic=7.0),
            _photo("/b.jpg", category="landscape", aggregate=6.0, aesthetic=5.0),
        ])
        app = _create_app_no_auth()
        with _stats_mocks(db_path):
            resp = TestClient(app).get("/api/stats/categories")
        assert resp.status_code == 200
        categories = resp.json()
        landscape = categories[0]
        assert landscape["avg_score"] == 7.0
        assert landscape["avg_aesthetic"] == 6.0
        assert "percentage" in landscape


# ---------------------------------------------------------------------------
# TestCorrelations
# ---------------------------------------------------------------------------

class TestCorrelations:

    def test_returns_data_points(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _make_stats_db(db_path, [
            _photo(f"/iso100_{i}.jpg", iso=100, aggregate=7.0)
            for i in range(5)
        ] + [
            _photo(f"/iso800_{i}.jpg", iso=800, aggregate=5.0)
            for i in range(5)
        ])
        app = _create_app_no_auth()
        with _stats_mocks(db_path):
            resp = TestClient(app).get(
                "/api/stats/correlations?x=iso&y=aggregate&min_samples=1")
        assert resp.status_code == 200
        data = resp.json()
        assert "labels" in data
        assert "metrics" in data
        assert len(data["labels"]) >= 2
        assert "aggregate" in data["metrics"]
        # ISO 100 and 800 should both appear
        assert "100" in data["labels"]
        assert "800" in data["labels"]

    def test_invalid_x_axis_returns_400(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _make_stats_db(db_path, [])
        app = _create_app_no_auth()
        with _stats_mocks(db_path):
            resp = TestClient(app).get(
                "/api/stats/correlations?x=invalid_axis&y=aggregate")
        assert resp.status_code == 400

    def test_invalid_metric_returns_400(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _make_stats_db(db_path, [])
        app = _create_app_no_auth()
        with _stats_mocks(db_path):
            resp = TestClient(app).get(
                "/api/stats/correlations?x=iso&y=not_a_real_metric")
        assert resp.status_code == 400

    def test_empty_db_returns_empty_labels(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _make_stats_db(db_path, [])
        app = _create_app_no_auth()
        with _stats_mocks(db_path):
            resp = TestClient(app).get(
                "/api/stats/correlations?x=iso&y=aggregate&min_samples=1")
        assert resp.status_code == 200
        assert resp.json()["labels"] == []

    def test_group_by_branch(self, tmp_path):
        """group_by exercises the asyncio.to_thread aggregation path."""
        db_path = str(tmp_path / "test.db")
        _make_stats_db(db_path, [
            _photo(f"/canon_i100_{i}.jpg", camera_model="Canon R6", iso=100, aggregate=8.0)
            for i in range(4)
        ] + [
            _photo(f"/sony_i800_{i}.jpg", camera_model="Sony A7IV", iso=800, aggregate=5.0)
            for i in range(4)
        ])
        app = _create_app_no_auth()
        with _stats_mocks(db_path):
            resp = TestClient(app).get(
                "/api/stats/correlations"
                "?x=iso&y=aggregate&group_by=camera_model&min_samples=1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["group_by"] == "camera_model"
        assert "Canon R6" in data["groups"]
        assert "Sony A7IV" in data["groups"]
        # Canon photos are all ISO 100 with aggregate 8.0
        canon = data["groups"]["Canon R6"]
        assert canon["100"]["aggregate"] == 8.0
        assert canon["100"]["count"] == 4


# ---------------------------------------------------------------------------
# TestOverview
# ---------------------------------------------------------------------------

class TestOverview:

    def test_overview_aggregates(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _make_stats_db(db_path, [
            _photo("/a.jpg", aggregate=8.0, aesthetic=7.0, comp_score=6.0,
                   date_taken="2024:01:01 10:00:00"),
            _photo("/b.jpg", aggregate=6.0, aesthetic=5.0, comp_score=4.0,
                   date_taken="2024:06:01 10:00:00"),
        ])
        app = _create_app_no_auth()
        with _stats_mocks(db_path):
            resp = TestClient(app).get("/api/stats/overview")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_photos"] == 2
        assert data["avg_score"] == 7.0
        assert data["avg_aesthetic"] == 6.0
        assert data["avg_composition"] == 5.0
        # Dates are formatted to ISO (YYYY-MM-DD...) from the EXIF colon form
        assert data["date_range_start"].startswith("2024-01-01")
        assert data["date_range_end"].startswith("2024-06-01")

    def test_overview_empty_db(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _make_stats_db(db_path, [])
        app = _create_app_no_auth()
        with _stats_mocks(db_path):
            resp = TestClient(app).get("/api/stats/overview")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_photos"] == 0

    def test_overview_anonymous_sees_nothing_on_protected_install(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _make_stats_db(db_path, [
            _photo("/a.jpg", aggregate=8.0),
            _photo("/b.jpg", aggregate=6.0),
        ])
        app = _create_app_no_auth()
        with _stats_mocks(db_path), \
                mock.patch.dict("api.db_helpers.VIEWER_CONFIG", {"password": "secret"}):
            resp = TestClient(app).get("/api/stats/overview")
        assert resp.status_code == 200
        assert resp.json()["total_photos"] == 0


# ---------------------------------------------------------------------------
# TestGear / TestSettings / TestTimeline
# ---------------------------------------------------------------------------

class TestGear:

    def test_gear_groups_cameras_and_lenses(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _make_stats_db(db_path, [
            _photo(f"/c_{i}.jpg", camera_model="Canon R6", lens_model="RF 50mm",
                   date_taken="2024:01:01 10:00:00")
            for i in range(3)
        ])
        app = _create_app_no_auth()
        with _stats_mocks(db_path):
            resp = TestClient(app).get("/api/stats/gear")
        assert resp.status_code == 200
        data = resp.json()
        assert any(c["name"] == "Canon R6" and c["count"] == 3 for c in data["cameras"])
        assert any(lens["name"] == "RF 50mm" and lens["count"] == 3 for lens in data["lenses"])
        # Combo present with a consolidated monthly history
        combo = next(c for c in data["combos"] if c["name"] == "Canon R6 + RF 50mm")
        assert combo["count"] == 3
        assert combo["history"] and combo["history"][0]["count"] == 3


class TestSettings:

    def test_settings_buckets(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _make_stats_db(db_path, [
            _photo("/a.jpg", iso=100, f_stop=2.8, focal_length=50,
                   shutter_speed="1/1000"),
            _photo("/b.jpg", iso=3200, f_stop=5.6, focal_length=200,
                   shutter_speed="1/60"),
        ])
        app = _create_app_no_auth()
        with _stats_mocks(db_path):
            resp = TestClient(app).get("/api/stats/settings")
        assert resp.status_code == 200
        data = resp.json()
        iso_labels = {b["label"] for b in data["iso"]}
        assert "100" in iso_labels and "3200" in iso_labels
        assert sum(b["count"] for b in data["score_distribution"]) == 2


class TestTimeline:

    def test_timeline_monthly_and_yearly(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _make_stats_db(db_path, [
            _photo("/a.jpg", date_taken="2024:01:15 10:00:00", aggregate=8.0),
            _photo("/b.jpg", date_taken="2024:01:20 11:00:00", aggregate=6.0),
            _photo("/c.jpg", date_taken="2023:12:25 09:00:00", aggregate=7.0),
        ])
        app = _create_app_no_auth()
        with _stats_mocks(db_path):
            resp = TestClient(app).get("/api/stats/timeline")
        assert resp.status_code == 200
        data = resp.json()
        # 2024-01 has 2 photos averaging 7.0
        jan = next(m for m in data["monthly"] if m["month"].startswith("2024-01"))
        assert jan["count"] == 2
        assert jan["avg_score"] == 7.0
        years = {y["year"]: y["count"] for y in data["yearly"]}
        assert years["2024"] == 2
        assert years["2023"] == 1


# ---------------------------------------------------------------------------
# TestCategoriesBreakdown / TestCategoriesOverlap
# ---------------------------------------------------------------------------

class TestCategoriesBreakdown:

    def test_breakdown_counts_and_distributions(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _make_stats_db(db_path, [
            _photo("/a.jpg", category="portrait", aggregate=8.0),
            _photo("/b.jpg", category="portrait", aggregate=8.0),
            _photo("/c.jpg", category="landscape", aggregate=6.0),
        ])
        app = _create_app_no_auth()
        with _stats_mocks(db_path):
            resp = TestClient(app).get("/api/stats/categories/breakdown")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        portrait = next(c for c in data["categories"] if c["name"] == "portrait")
        assert portrait["count"] == 2
        assert "portrait" in data["distributions"]


class TestCategoriesOverlap:

    def test_overlap_runs_filter_evaluation(self, tmp_path):
        """Exercises the asyncio.to_thread per-row CategoryFilter path."""
        db_path = str(tmp_path / "test.db")
        _make_stats_db(db_path, [
            _photo("/a.jpg", category="portrait", face_ratio=0.3, face_count=1),
            _photo("/b.jpg", category="landscape", face_ratio=0.0, face_count=0),
            _photo("/c.jpg", category="", face_ratio=0.0, face_count=0),
        ])
        app = _create_app_no_auth()
        with _stats_mocks(db_path):
            resp = TestClient(app).get("/api/stats/categories/overlap")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert data["uncategorized"] == 1
        assert isinstance(data["overlaps"], list)
        assert isinstance(data["per_category"], list)
