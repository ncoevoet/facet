"""
Tests for the stats API router endpoints.

Covers: score_distribution, top_cameras, categories, correlations.
Uses real SQLite databases (same pattern as test_refactor_round2.py).
"""

import sqlite3
from unittest import mock

import pytest
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
        face_confidence REAL
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


def _conn_factory(db_path: str):
    from contextlib import contextmanager

    @contextmanager
    def factory():
        c = sqlite3.connect(db_path, check_same_thread=False)
        c.row_factory = sqlite3.Row
        try:
            yield c
        finally:
            c.close()
    return factory


def _create_app_no_auth():
    app = create_app()
    app.dependency_overrides[get_optional_user] = lambda: None
    return app


# Common mock context for all stats tests: bypass cache + clear stale state.
def _stats_mocks(db_path):
    """Return a context manager that patches get_db, cache, and column cache."""
    from contextlib import ExitStack

    class _Ctx:
        def __enter__(self):
            self._stack = ExitStack()
            self._stack.enter_context(
                mock.patch("api.routers.stats.get_db", _conn_factory(db_path)))
            self._stack.enter_context(
                mock.patch("api.routers.stats._get_stats_cached",
                           side_effect=lambda _key, fn: fn()))
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
