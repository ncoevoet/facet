"""
Tests for the gallery API router — photo listing, type counts, single photo.

Uses real SQLite databases (same approach as test_refactor_round2.py) to verify
query building, pagination, sorting, filtering, and validation.
"""

import sqlite3
from contextlib import contextmanager
from unittest import mock

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
        star_rating INTEGER DEFAULT 0,
        is_favorite INTEGER DEFAULT 0,
        is_rejected INTEGER DEFAULT 0
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
    return {**_SAMPLE_PHOTO, "path": path, "date_taken": date_taken, **overrides}


def _make_db(path, photos, persons=None, faces=None):
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
    """Yield a real aiosqlite Connection bound to the test DB.

    The /api/photos handler is async (R7 closure); tests that previously
    only patched get_db must also patch get_async_db with this factory so
    the endpoint reaches the temp DB instead of the production one.
    """
    from contextlib import asynccontextmanager
    import aiosqlite

    @asynccontextmanager
    async def factory():
        c = await aiosqlite.connect(db_path)
        c.row_factory = aiosqlite.Row
        try:
            yield c
        finally:
            await c.close()
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
    "quality_thresholds": {},
    "features": {},
}

# Columns declared in _PHOTOS_SCHEMA above — used to pre-seed
# _existing_columns_cache so the async /api/photos handler builds its
# SELECT list against the test schema, not the production DB schema.
_TEST_PHOTOS_COLUMNS = {
    "path", "filename", "date_taken", "camera_model", "lens_model", "iso",
    "f_stop", "shutter_speed", "focal_length", "focal_length_35mm",
    "aesthetic", "face_count", "face_quality", "eye_sharpness",
    "face_sharpness", "face_ratio", "tech_sharpness", "color_score",
    "exposure_score", "comp_score", "isolation_bonus", "is_blink",
    "phash", "is_burst_lead", "aggregate", "category", "image_width",
    "image_height", "tags", "composition_pattern", "person_id",
    "is_monochrome", "dynamic_range_stops", "noise_sigma", "contrast_score",
    "star_rating", "is_favorite", "is_rejected",
}


# ---------------------------------------------------------------------------
# Gallery Photos
# ---------------------------------------------------------------------------

class TestGalleryPhotos:
    """GET /api/photos — pagination, sorting, filtering, validation."""

    def test_returns_photos_with_pagination(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        photos = [_photo(f"/p{i}.jpg", "2024:06:15 12:00:00") for i in range(5)]
        _make_db(db_path, photos)
        app = _create_app_no_auth()
        with (
            mock.patch("api.routers.gallery.get_db", _conn_factory(db_path)),
            mock.patch("api.routers.gallery.get_async_db", _async_conn_factory(db_path)),
            mock.patch("api.routers.gallery.VIEWER_CONFIG", _VIEWER_CONFIG),
            mock.patch("api.db_helpers._existing_columns_cache", _TEST_PHOTOS_COLUMNS),
            mock.patch.dict("api.config._count_cache", {}, clear=True),
        ):
            resp = TestClient(app).get("/api/photos?page=1&per_page=2")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["photos"]) == 2
        assert data["total"] == 5
        assert data["has_more"] is True

    def test_sort_by_aesthetic_desc(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, [
            _photo("/low.jpg", "2024:01:01 10:00:00", aesthetic=3.0),
            _photo("/mid.jpg", "2024:01:01 10:00:00", aesthetic=6.0),
            _photo("/high.jpg", "2024:01:01 10:00:00", aesthetic=9.0),
        ])
        app = _create_app_no_auth()
        with (
            mock.patch("api.routers.gallery.get_db", _conn_factory(db_path)),
            mock.patch("api.routers.gallery.get_async_db", _async_conn_factory(db_path)),
            mock.patch("api.routers.gallery.VIEWER_CONFIG", _VIEWER_CONFIG),
            mock.patch("api.db_helpers._existing_columns_cache", _TEST_PHOTOS_COLUMNS),
            mock.patch.dict("api.config._count_cache", {}, clear=True),
        ):
            resp = TestClient(app).get("/api/photos?page=1&sort=aesthetic&sort_direction=DESC")
        photos = resp.json()["photos"]
        aesthetics = [p["aesthetic"] for p in photos]
        assert aesthetics == sorted(aesthetics, reverse=True)
        assert aesthetics[0] == 9.0

    def test_invalid_sort_falls_back_to_aggregate(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, [_photo("/a.jpg", "2024:01:01 10:00:00")])
        app = _create_app_no_auth()
        with (
            mock.patch("api.routers.gallery.get_db", _conn_factory(db_path)),
            mock.patch("api.routers.gallery.get_async_db", _async_conn_factory(db_path)),
            mock.patch("api.routers.gallery.VIEWER_CONFIG", _VIEWER_CONFIG),
            mock.patch("api.db_helpers._existing_columns_cache", _TEST_PHOTOS_COLUMNS),
            mock.patch.dict("api.config._count_cache", {}, clear=True),
        ):
            resp = TestClient(app).get("/api/photos?page=1&sort=NONEXISTENT")
        assert resp.status_code == 200
        assert resp.json()["sort_col"] == "aggregate"

    def test_camera_filter(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, [
            _photo("/canon.jpg", "2024:01:01 10:00:00", camera_model="Canon R6"),
            _photo("/nikon.jpg", "2024:01:01 10:00:00", camera_model="Nikon Z6"),
        ])
        app = _create_app_no_auth()
        with (
            mock.patch("api.routers.gallery.get_db", _conn_factory(db_path)),
            mock.patch("api.routers.gallery.get_async_db", _async_conn_factory(db_path)),
            mock.patch("api.routers.gallery.VIEWER_CONFIG", _VIEWER_CONFIG),
            mock.patch("api.db_helpers._existing_columns_cache", _TEST_PHOTOS_COLUMNS),
            mock.patch.dict("api.config._count_cache", {}, clear=True),
        ):
            resp = TestClient(app).get("/api/photos?page=1&camera=Canon+R6")
        photos = resp.json()["photos"]
        assert len(photos) == 1
        assert photos[0]["camera_model"] == "Canon R6"

    def test_date_range_filter(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, [
            _photo("/may.jpg", "2024:05:15 12:00:00"),
            _photo("/jun.jpg", "2024:06:15 12:00:00"),
            _photo("/jul.jpg", "2024:07:15 12:00:00"),
        ])
        app = _create_app_no_auth()
        with (
            mock.patch("api.routers.gallery.get_db", _conn_factory(db_path)),
            mock.patch("api.routers.gallery.get_async_db", _async_conn_factory(db_path)),
            mock.patch("api.routers.gallery.VIEWER_CONFIG", _VIEWER_CONFIG),
            mock.patch("api.db_helpers._existing_columns_cache", _TEST_PHOTOS_COLUMNS),
            mock.patch.dict("api.config._count_cache", {}, clear=True),
        ):
            resp = TestClient(app).get("/api/photos?page=1&date_from=2024-06-01&date_to=2024-06-30")
        photos = resp.json()["photos"]
        assert len(photos) == 1
        assert photos[0]["path"] == "/jun.jpg"

    def test_category_filter(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, [
            _photo("/portrait.jpg", "2024:01:01 10:00:00", category="portrait"),
            _photo("/landscape.jpg", "2024:01:01 10:00:00", category="landscape"),
            _photo("/portrait2.jpg", "2024:01:01 10:00:00", category="portrait"),
        ])
        app = _create_app_no_auth()
        with (
            mock.patch("api.routers.gallery.get_db", _conn_factory(db_path)),
            mock.patch("api.routers.gallery.get_async_db", _async_conn_factory(db_path)),
            mock.patch("api.routers.gallery.VIEWER_CONFIG", _VIEWER_CONFIG),
            mock.patch("api.db_helpers._existing_columns_cache", _TEST_PHOTOS_COLUMNS),
            mock.patch.dict("api.config._count_cache", {}, clear=True),
        ):
            resp = TestClient(app).get("/api/photos?page=1&category=portrait")
        photos = resp.json()["photos"]
        assert len(photos) == 2
        assert all(p["category"] == "portrait" for p in photos)

    def test_per_page_over_limit_returns_422(self, tmp_path):
        """per_page > 500 returns 422 validation error."""
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, [_photo("/a.jpg", "2024:01:01 10:00:00")])
        app = _create_app_no_auth()
        with (
            mock.patch("api.routers.gallery.get_db", _conn_factory(db_path)),
            mock.patch("api.routers.gallery.get_async_db", _async_conn_factory(db_path)),
            mock.patch("api.routers.gallery.VIEWER_CONFIG", _VIEWER_CONFIG),
            mock.patch("api.db_helpers._existing_columns_cache", _TEST_PHOTOS_COLUMNS),
            mock.patch.dict("api.config._count_cache", {}, clear=True),
        ):
            resp = TestClient(app).get("/api/photos?page=1&per_page=9999")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Type Counts
# ---------------------------------------------------------------------------

class TestGalleryTypeCountsEndpoint:
    """GET /api/type_counts — sidebar type counts."""

    def test_type_counts_returns_list(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, [_photo("/a.jpg", "2024:01:01 10:00:00")])
        app = _create_app_no_auth()
        with mock.patch("api.types.get_photo_types", return_value=[{"id": "all", "label": "All", "count": 1}]):
            resp = TestClient(app).get("/api/type_counts")
        assert resp.status_code == 200
        data = resp.json()
        assert "types" in data
        assert isinstance(data["types"], list)


# ---------------------------------------------------------------------------
# Single Photo
# ---------------------------------------------------------------------------

class TestGallerySinglePhoto:
    """GET /api/photo — single photo lookup."""

    def test_photo_not_found(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, [])
        app = _create_app_no_auth()
        with (
            mock.patch("api.routers.gallery.get_db", _conn_factory(db_path)),
            mock.patch("api.routers.gallery.get_async_db", _async_conn_factory(db_path)),
            mock.patch("api.routers.gallery.VIEWER_CONFIG", _VIEWER_CONFIG),
            mock.patch("api.db_helpers._existing_columns_cache", _TEST_PHOTOS_COLUMNS),
            mock.patch.dict("api.config._count_cache", {}, clear=True),
        ):
            resp = TestClient(app, raise_server_exceptions=False).get(
                "/api/photo?path=/nonexistent.jpg"
            )
        assert resp.status_code == 404

    def test_photo_found(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, [_photo("/found.jpg", "2024:06:15 12:00:00")])
        app = _create_app_no_auth()
        with (
            mock.patch("api.routers.gallery.get_db", _conn_factory(db_path)),
            mock.patch("api.routers.gallery.get_async_db", _async_conn_factory(db_path)),
            mock.patch("api.routers.gallery.VIEWER_CONFIG", _VIEWER_CONFIG),
            mock.patch("api.db_helpers._existing_columns_cache", _TEST_PHOTOS_COLUMNS),
            mock.patch.dict("api.config._count_cache", {}, clear=True),
        ):
            resp = TestClient(app).get("/api/photo?path=/found.jpg")
        assert resp.status_code == 200
        data = resp.json()
        assert data["path"] == "/found.jpg"
        assert data["aggregate"] == 7.0


class TestSelectBottomPercent:
    """GET /api/photos/select_bottom_percent — 'keep top N%' percentile selection."""

    def _get(self, db_path, query):
        app = _create_app_no_auth()
        with (
            mock.patch("api.routers.gallery.get_db", _conn_factory(db_path)),
            mock.patch("api.routers.gallery.get_async_db", _async_conn_factory(db_path)),
            mock.patch("api.routers.gallery.VIEWER_CONFIG", _VIEWER_CONFIG),
            mock.patch("api.db_helpers._existing_columns_cache", _TEST_PHOTOS_COLUMNS),
            mock.patch.dict("api.config._count_cache", {}, clear=True),
        ):
            return TestClient(app).get(f"/api/photos/select_bottom_percent?{query}")

    def test_returns_bottom_paths_by_sort(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, [
            _photo(f"/p{i}.jpg", "2024:01:01 10:00:00", aggregate=float(i))
            for i in range(10)
        ])
        resp = self._get(db_path, "keep_percent=30&sort=aggregate&sort_direction=DESC")
        assert resp.status_code == 200
        data = resp.json()
        assert (data["total"], data["keep"], data["cut"]) == (10, 3, 7)
        assert data["truncated"] is False
        assert len(data["paths"]) == 7
        # Top 3 by aggregate (9, 8, 7) are kept -> never selected.
        assert {"/p9.jpg", "/p8.jpg", "/p7.jpg"}.isdisjoint(data["paths"])
        # The worst (aggregate 0) is in the cut.
        assert "/p0.jpg" in data["paths"]

    def test_rejects_invalid_percent(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, [_photo("/a.jpg", "2024:01:01 10:00:00")])
        assert self._get(db_path, "keep_percent=abc").status_code == 422
        assert self._get(db_path, "keep_percent=0").status_code == 422
        assert self._get(db_path, "keep_percent=100").status_code == 422
        assert self._get(db_path, "").status_code == 422

    def test_respects_active_filters(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, [
            _photo("/c1.jpg", "2024:01:01 10:00:00", aggregate=1.0, camera_model="Canon R6"),
            _photo("/c2.jpg", "2024:01:01 10:00:00", aggregate=9.0, camera_model="Canon R6"),
            _photo("/n1.jpg", "2024:01:01 10:00:00", aggregate=2.0, camera_model="Nikon Z6"),
        ])
        resp = self._get(db_path, "keep_percent=50&sort=aggregate&sort_direction=DESC&camera=Canon+R6")
        data = resp.json()
        # Scoped to the 2 Canon photos: keep ceil(2*0.5)=1 (agg 9), cut 1 (agg 1).
        assert data["total"] == 2
        assert data["paths"] == ["/c1.jpg"]

    def test_keep_all_yields_empty_cut(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, [
            _photo(f"/p{i}.jpg", "2024:01:01 10:00:00", aggregate=float(i)) for i in range(3)
        ])
        data = self._get(db_path, "keep_percent=99").json()
        assert data["cut"] == 0
        assert data["paths"] == []
