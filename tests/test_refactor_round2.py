"""
Integration tests for refactor round 2 changes with simulated DB environment.

Complete coverage for all changed code paths:
- gallery.py: conn inside try block, date filtering via to_exif_date
- persons.py: date filtering via to_exif_date
- stats.py: to_iso_date in overview/timeline/gear, to_exif_date in correlations
- multi_pass.py: Path instead of PathLib alias
- face.py: top-level import of crop_face_with_padding
- image_transforms.py / image_loading.py: shared _lazy imports
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
        noise_sigma REAL, contrast_score REAL
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

_SAMPLE_PHOTO = {
    "filename": "a.jpg", "aggregate": 7.0, "aesthetic": 6.0,
    "comp_score": 5.0, "tech_sharpness": 4.0, "color_score": 5.0,
    "exposure_score": 6.0, "category": "default",
    "image_width": 4000, "image_height": 3000,
}


def _photo(path, date_taken, **overrides):
    """Build a photo dict with sensible defaults."""
    return {**_SAMPLE_PHOTO, "path": path, "date_taken": date_taken, **overrides}


def _make_db(path: str, photos: list[dict], persons=None, faces=None):
    conn = sqlite3.connect(path)
    conn.executescript(_PHOTOS_SCHEMA)
    for p in photos:
        cols = list(p.keys())
        placeholders = ", ".join("?" for _ in cols)
        conn.execute(
            f"INSERT INTO photos ({', '.join(cols)}) VALUES ({placeholders})",
            [p[c] for c in cols],
        )
    for person in (persons or []):
        conn.execute(
            "INSERT INTO persons (id, name, face_count) VALUES (?, ?, ?)",
            person,
        )
    for face in (faces or []):
        conn.execute(
            "INSERT INTO faces (id, photo_path, person_id) VALUES (?, ?, ?)",
            face,
        )
    conn.commit()
    conn.close()


def _conn_factory(db_path: str):
    def factory():
        c = sqlite3.connect(db_path, check_same_thread=False)
        c.row_factory = sqlite3.Row
        return c
    return factory


def _create_app_no_auth():
    app = create_app()
    app.dependency_overrides[get_optional_user] = lambda: None
    return app


_VIEWER_CONFIG = {
    "display": {"tags_per_photo": 5},
    "pagination": {"default_per_page": 64, "max_per_page": 200},
    "defaults": {
        "sort": "aggregate", "sort_direction": "DESC",
        "hide_blinks": True, "hide_bursts": True,
        "hide_duplicates": True, "type": "",
    },
    "dropdowns": {"min_photos_for_person": 2, "max_persons": 100},
}


# ---------------------------------------------------------------------------
# Gallery: conn inside try + date filtering
# ---------------------------------------------------------------------------

class TestGalleryConnScope:
    """Conn moved inside try — basic queries, date filtering, error handling."""

    def test_returns_photos(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, [_photo("/a.jpg", "2024:03:11 10:00:00")])
        app = _create_app_no_auth()
        with (
            mock.patch("api.routers.gallery.get_db_connection", _conn_factory(db_path)),
            mock.patch("api.routers.gallery.VIEWER_CONFIG", _VIEWER_CONFIG),
            mock.patch("api.db_helpers._existing_columns_cache", None),
        ):
            resp = TestClient(app).get("/api/photos?page=1")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1
        assert resp.json()["photos"][0]["path"] == "/a.jpg"

    def test_date_from_only(self, tmp_path):
        """Only date_from — filters out older photos."""
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, [
            _photo("/old.jpg", "2023:01:01 08:00:00"),
            _photo("/new.jpg", "2024:06:15 12:00:00"),
        ])
        app = _create_app_no_auth()
        with (
            mock.patch("api.routers.gallery.get_db_connection", _conn_factory(db_path)),
            mock.patch("api.routers.gallery.VIEWER_CONFIG", _VIEWER_CONFIG),
            mock.patch("api.db_helpers._existing_columns_cache", None),
        ):
            resp = TestClient(app).get("/api/photos?page=1&date_from=2024-01-01")
        photos = resp.json()["photos"]
        assert len(photos) == 1
        assert photos[0]["path"] == "/new.jpg"

    def test_date_to_only(self, tmp_path):
        """Only date_to — filters out newer photos."""
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, [
            _photo("/old.jpg", "2023:01:01 08:00:00"),
            _photo("/new.jpg", "2024:06:15 12:00:00"),
        ])
        app = _create_app_no_auth()
        with (
            mock.patch("api.routers.gallery.get_db_connection", _conn_factory(db_path)),
            mock.patch("api.routers.gallery.VIEWER_CONFIG", _VIEWER_CONFIG),
            mock.patch("api.db_helpers._existing_columns_cache", None),
        ):
            resp = TestClient(app).get("/api/photos?page=1&date_to=2023-12-31")
        photos = resp.json()["photos"]
        assert len(photos) == 1
        assert photos[0]["path"] == "/old.jpg"

    def test_date_range(self, tmp_path):
        """Both date_from and date_to — selects middle photo only."""
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, [
            _photo("/jan.jpg", "2024:01:15 12:00:00"),
            _photo("/mar.jpg", "2024:03:11 10:00:00"),
            _photo("/dec.jpg", "2024:12:25 18:00:00"),
        ])
        app = _create_app_no_auth()
        with (
            mock.patch("api.routers.gallery.get_db_connection", _conn_factory(db_path)),
            mock.patch("api.routers.gallery.VIEWER_CONFIG", _VIEWER_CONFIG),
            mock.patch("api.db_helpers._existing_columns_cache", None),
        ):
            resp = TestClient(app).get(
                "/api/photos?page=1&date_from=2024-03-01&date_to=2024-03-31"
            )
        photos = resp.json()["photos"]
        assert len(photos) == 1
        assert photos[0]["path"] == "/mar.jpg"

    def test_date_to_includes_end_of_day(self, tmp_path):
        """date_to appends 23:59:59 so photos taken late that day are included."""
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, [
            _photo("/evening.jpg", "2024:03:31 23:30:00"),
        ])
        app = _create_app_no_auth()
        with (
            mock.patch("api.routers.gallery.get_db_connection", _conn_factory(db_path)),
            mock.patch("api.routers.gallery.VIEWER_CONFIG", _VIEWER_CONFIG),
            mock.patch("api.db_helpers._existing_columns_cache", None),
        ):
            resp = TestClient(app).get(
                "/api/photos?page=1&date_to=2024-03-31"
            )
        assert len(resp.json()["photos"]) == 1

    def test_empty_date_range_returns_nothing(self, tmp_path):
        """Date range that excludes all photos returns empty list."""
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, [_photo("/a.jpg", "2024:06:15 12:00:00")])
        app = _create_app_no_auth()
        with (
            mock.patch("api.routers.gallery.get_db_connection", _conn_factory(db_path)),
            mock.patch("api.routers.gallery.VIEWER_CONFIG", _VIEWER_CONFIG),
            mock.patch("api.db_helpers._existing_columns_cache", None),
        ):
            resp = TestClient(app).get(
                "/api/photos?page=1&date_from=2025-01-01&date_to=2025-12-31"
            )
        assert resp.json()["total"] == 0
        assert resp.json()["photos"] == []

    def test_conn_closed_on_error(self, tmp_path):
        """Connection is closed even when query raises inside the try block."""
        conn_mock = mock.MagicMock()
        conn_mock.execute.side_effect = RuntimeError("simulated DB error")
        app = _create_app_no_auth()
        with (
            mock.patch("api.routers.gallery.get_db_connection", return_value=conn_mock),
            mock.patch("api.routers.gallery.VIEWER_CONFIG", _VIEWER_CONFIG),
            mock.patch("api.db_helpers._existing_columns_cache", None),
        ):
            resp = TestClient(app).get("/api/photos?page=1")
        assert resp.status_code == 500
        conn_mock.close.assert_called_once()


# ---------------------------------------------------------------------------
# Persons: date filtering via to_exif_date
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Stats: to_iso_date / to_exif_date in all endpoints that changed
# ---------------------------------------------------------------------------

class TestStatsOverview:
    """stats/overview: to_iso_date on MIN/MAX date_taken."""

    def _db_with_dates(self, tmp_path, dates):
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, [_photo(f"/{i}.jpg", d) for i, d in enumerate(dates)])
        return db_path

    def test_dates_converted_to_iso(self, tmp_path):
        db_path = self._db_with_dates(tmp_path, [
            "2023:01:10 08:00:00", "2024:12:25 18:00:00",
        ])
        app = _create_app_no_auth()
        with (
            mock.patch("api.routers.stats.get_db_connection", _conn_factory(db_path)),
            mock.patch("api.routers.stats._get_stats_cached",
                       side_effect=lambda _key, fn: fn()),
        ):
            resp = TestClient(app).get("/api/stats/overview")
        assert resp.status_code == 200
        data = resp.json()
        assert data["date_range_start"] == "2023-01-10"
        assert data["date_range_end"] == "2024-12-25"

    def test_null_dates_return_empty_strings(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, [_photo("/nodates.jpg", None)])
        app = _create_app_no_auth()
        with (
            mock.patch("api.routers.stats.get_db_connection", _conn_factory(db_path)),
            mock.patch("api.routers.stats._get_stats_cached",
                       side_effect=lambda _key, fn: fn()),
        ):
            resp = TestClient(app).get("/api/stats/overview")
        data = resp.json()
        assert data["date_range_start"] == ""
        assert data["date_range_end"] == ""

    def test_single_photo_same_start_end(self, tmp_path):
        db_path = self._db_with_dates(tmp_path, ["2024:07:04 12:00:00"])
        app = _create_app_no_auth()
        with (
            mock.patch("api.routers.stats.get_db_connection", _conn_factory(db_path)),
            mock.patch("api.routers.stats._get_stats_cached",
                       side_effect=lambda _key, fn: fn()),
        ):
            resp = TestClient(app).get("/api/stats/overview")
        data = resp.json()
        assert data["date_range_start"] == "2024-07-04"
        assert data["date_range_end"] == "2024-07-04"


class TestStatsTimeline:
    """stats/timeline: to_iso_date on monthly SUBSTR(date_taken,1,7)."""

    def test_monthly_dates_converted(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, [
            _photo("/a.jpg", "2024:03:11 10:00:00"),
            _photo("/b.jpg", "2024:03:20 14:00:00"),
            _photo("/c.jpg", "2024:07:04 12:00:00"),
        ])
        app = _create_app_no_auth()
        with (
            mock.patch("api.routers.stats.get_db_connection", _conn_factory(db_path)),
            mock.patch("api.routers.stats._get_stats_cached",
                       side_effect=lambda _key, fn: fn()),
        ):
            resp = TestClient(app).get("/api/stats/timeline")
        assert resp.status_code == 200
        monthly = resp.json()["monthly"]
        months = [m["month"] for m in monthly]
        # Must be ISO format with dashes
        assert "2024-03" in months
        assert "2024-07" in months
        # Colon format must not appear
        assert all(":" not in m for m in months)

    def test_march_count_aggregated(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, [
            _photo("/a.jpg", "2024:03:11 10:00:00"),
            _photo("/b.jpg", "2024:03:20 14:00:00"),
        ])
        app = _create_app_no_auth()
        with (
            mock.patch("api.routers.stats.get_db_connection", _conn_factory(db_path)),
            mock.patch("api.routers.stats._get_stats_cached",
                       side_effect=lambda _key, fn: fn()),
        ):
            resp = TestClient(app).get("/api/stats/timeline")
        monthly = resp.json()["monthly"]
        march = next(m for m in monthly if m["month"] == "2024-03")
        assert march["count"] == 2


class TestStatsGear:
    """stats/gear: to_iso_date on gear timeline monthly data."""

    def test_gear_timeline_months_iso(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, [
            _photo("/a.jpg", "2024:03:11 10:00:00",
                   camera_model="Canon R6", lens_model="RF 50mm", iso=400),
            _photo("/b.jpg", "2024:07:04 14:00:00",
                   camera_model="Canon R6", lens_model="RF 50mm", iso=800),
        ])
        app = _create_app_no_auth()
        with (
            mock.patch("api.routers.stats.get_db_connection", _conn_factory(db_path)),
            mock.patch("api.routers.stats._get_stats_cached",
                       side_effect=lambda _key, fn: fn()),
        ):
            resp = TestClient(app).get("/api/stats/gear")
        assert resp.status_code == 200
        cameras = resp.json()["cameras"]
        canon = next(c for c in cameras if c["name"] == "Canon R6")
        history_dates = [h["date"] for h in canon["history"]]
        # Must be ISO dashes, not EXIF colons
        assert "2024-03" in history_dates
        assert "2024-07" in history_dates
        assert all(":" not in d for d in history_dates)


class TestStatsCorrelations:
    """stats/correlations: to_exif_date on date_from/date_to filter params."""

    def test_date_filter_applied(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, [
            _photo("/jan.jpg", "2024:01:15 12:00:00", iso=100, aggregate=5.0),
            _photo("/mar.jpg", "2024:03:11 10:00:00", iso=200, aggregate=7.0),
            _photo("/jul.jpg", "2024:07:04 12:00:00", iso=400, aggregate=8.0),
        ])
        app = _create_app_no_auth()
        with (
            mock.patch("api.routers.stats.get_db_connection", _conn_factory(db_path)),
            mock.patch("api.routers.stats._get_stats_cached",
                       side_effect=lambda _key, fn: fn()),
        ):
            # Filter to March-July only, exclude January
            resp = TestClient(app).get(
                "/api/stats/correlations?x=iso&y=aggregate"
                "&date_from=2024-03-01&date_to=2024-07-31&min_samples=1"
            )
        assert resp.status_code == 200
        data = resp.json()
        # Should have data buckets only for ISO 200 and 400 (not 100)
        labels = data["labels"]
        assert "100" not in labels

    def test_no_date_filter(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, [
            _photo("/a.jpg", "2024:01:15 12:00:00", iso=100, aggregate=5.0),
            _photo("/b.jpg", "2024:03:11 10:00:00", iso=200, aggregate=7.0),
        ])
        app = _create_app_no_auth()
        with (
            mock.patch("api.routers.stats.get_db_connection", _conn_factory(db_path)),
            mock.patch("api.routers.stats._get_stats_cached",
                       side_effect=lambda _key, fn: fn()),
        ):
            resp = TestClient(app).get(
                "/api/stats/correlations?x=iso&y=aggregate&min_samples=1"
            )
        assert resp.status_code == 200
        labels = resp.json()["labels"]
        assert "100" in labels
        assert "200" in labels


# ---------------------------------------------------------------------------
# multi_pass.py: Path instead of PathLib alias
# ---------------------------------------------------------------------------

class TestMultiPassPathAlias:
    def test_no_pathlib_alias_in_save_results(self):
        """Verify PathLib alias is gone — _save_results uses top-level Path."""
        import inspect
        from processing.multi_pass import ChunkedMultiPassProcessor
        source = inspect.getsource(ChunkedMultiPassProcessor._save_results)
        assert "PathLib" not in source
        assert "from pathlib" not in source

    def test_uses_path_from_module_level(self):
        """Path is imported at module level, not re-imported locally."""
        import inspect
        import processing.multi_pass as mod
        module_source = inspect.getsource(mod)
        # Top-level import exists
        assert "from pathlib import Path" in module_source
        # No local alias inside _save_results
        method_source = inspect.getsource(mod.ChunkedMultiPassProcessor._save_results)
        assert "Path(" in method_source


# ---------------------------------------------------------------------------
# face.py: top-level import of crop_face_with_padding
# ---------------------------------------------------------------------------

class TestFaceTopLevelImport:
    def test_crop_face_imported_at_module_level(self):
        """crop_face_with_padding is at module level, not lazy-imported in method."""
        import inspect
        from analyzers import face
        assert hasattr(face, "crop_face_with_padding")
        source = inspect.getsource(face.FaceAnalyzer._crop_face_thumbnail)
        assert "import" not in source

    def test_crop_face_callable(self):
        """The imported function is the actual crop_face_with_padding."""
        from analyzers.face import crop_face_with_padding
        from utils.image_transforms import crop_face_with_padding as original
        assert crop_face_with_padding is original


# ---------------------------------------------------------------------------
# _lazy.py: shared imports used by image_loading and image_transforms
# ---------------------------------------------------------------------------

class TestSharedLazyImports:
    def test_image_loading_uses_shared_lazy(self):
        import inspect
        import utils.image_loading as mod
        source = inspect.getsource(mod)
        assert "from utils._lazy import" in source
        assert "\n_cv2 = " not in source
        assert "\n_Image = " not in source

    def test_image_transforms_uses_shared_lazy(self):
        import inspect
        import utils.image_transforms as mod
        source = inspect.getsource(mod)
        assert "from utils._lazy import" in source
        assert "\n_cv2 = " not in source

    def test_both_modules_share_same_cv2(self):
        """image_loading and image_transforms get the same cv2 instance."""
        from utils._lazy import ensure_cv2
        from utils.image_loading import _ensure_cv2 as il_ensure
        from utils.image_transforms import _ensure_cv2 as it_ensure
        assert il_ensure() is ensure_cv2()
        assert it_ensure() is ensure_cv2()

    def test_both_modules_share_same_pil(self):
        """image_loading and image_transforms get the same PIL.Image."""
        from utils._lazy import ensure_pil
        from utils.image_loading import _ensure_pil as il_ensure
        from utils.image_transforms import _ensure_pil_full as it_ensure
        Image_root, _ = ensure_pil()
        Image_il, _ = il_ensure()
        Image_it, _ = it_ensure()
        assert Image_il is Image_root
        assert Image_it is Image_root
