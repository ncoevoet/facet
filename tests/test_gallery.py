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
        phash TEXT, is_burst_lead INTEGER, burst_group_id INTEGER,
        is_duplicate_lead INTEGER, duplicate_group_id INTEGER,
        sequence_group_id INTEGER, sequence_kind TEXT, sequence_ev_offset REAL,
        is_sequence_lead INTEGER DEFAULT 0,
        aggregate REAL,
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
    CREATE TABLE photo_sequence_overrides (
        photo_path TEXT PRIMARY KEY, sequence_kind TEXT, override_group_key TEXT,
        source TEXT, created_at TEXT, created_by TEXT, applied_at TEXT
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
    "phash", "is_burst_lead", "burst_group_id", "is_duplicate_lead",
    "duplicate_group_id", "aggregate", "category", "image_width",
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

    def test_anonymous_on_access_controlled_install_sees_no_photos(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        photos = [_photo(f"/p{i}.jpg", "2024:06:15 12:00:00") for i in range(5)]
        _make_db(db_path, photos)
        app = _create_app_no_auth()
        with (
            mock.patch("api.routers.gallery.get_db", _conn_factory(db_path)),
            mock.patch("api.routers.gallery.get_async_db", _async_conn_factory(db_path)),
            mock.patch("api.routers.gallery.VIEWER_CONFIG", _VIEWER_CONFIG),
            mock.patch("api.db_helpers._existing_columns_cache", _TEST_PHOTOS_COLUMNS),
            mock.patch("api.db_helpers.VIEWER_CONFIG", {"password": "secret"}),
            mock.patch("api.db_helpers.is_multi_user_enabled", lambda: False),
            mock.patch.dict("api.config._count_cache", {}, clear=True),
        ):
            resp = TestClient(app).get("/api/photos?page=1&per_page=50")
        assert resp.status_code == 200
        data = resp.json()
        assert data["photos"] == []
        assert data["total"] == 0

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
# Folder (path_prefix) Filter
# ---------------------------------------------------------------------------

class TestGalleryPathPrefixFilter:
    """GET /api/photos?path_prefix= — subtree match on the directory boundary.

    The viewer's folder picker feeds these prefixes straight from /api/folders,
    so the normalisation and escaping below are part of that contract.
    """

    PHOTOS = [
        _photo("/lib/A/one.jpg", "2024:01:01 10:00:00"),
        _photo("/lib/A/B/C/deep.jpg", "2024:01:01 10:00:00"),
        _photo("/lib/Alpha/other.jpg", "2024:01:01 10:00:00"),
        _photo("/lib/100_MEDIA/wild.jpg", "2024:01:01 10:00:00"),
        _photo("/lib/100XMEDIA/decoy.jpg", "2024:01:01 10:00:00"),
        _photo("/lib/100%FUN/party.jpg", "2024:01:01 10:00:00"),
        _photo("/lib/100XFUN/decoy2.jpg", "2024:01:01 10:00:00"),
        _photo("C:\\lib\\W\\win.jpg", "2024:01:01 10:00:00"),
    ]

    def _paths_for(self, tmp_path, path_prefix):
        db_path = str(tmp_path / f"test-{abs(hash(path_prefix))}.db")
        _make_db(db_path, self.PHOTOS)
        app = _create_app_no_auth()
        with (
            mock.patch("api.routers.gallery.get_db", _conn_factory(db_path)),
            mock.patch("api.routers.gallery.get_async_db", _async_conn_factory(db_path)),
            mock.patch("api.routers.gallery.VIEWER_CONFIG", _VIEWER_CONFIG),
            mock.patch("api.db_helpers._existing_columns_cache", _TEST_PHOTOS_COLUMNS),
            mock.patch.dict("api.config._count_cache", {}, clear=True),
        ):
            resp = TestClient(app).get("/api/photos", params={"path_prefix": path_prefix, "per_page": 50})
        assert resp.status_code == 200
        return sorted(p["path"] for p in resp.json()["photos"])

    def test_matches_the_whole_subtree(self, tmp_path):
        assert self._paths_for(tmp_path, "/lib/A") == ["/lib/A/B/C/deep.jpg", "/lib/A/one.jpg"]

    def test_trailing_slash_variants_are_equivalent(self, tmp_path):
        bare = self._paths_for(tmp_path, "/lib/A")
        assert self._paths_for(tmp_path, "/lib/A/") == bare
        assert self._paths_for(tmp_path, "/lib/A///") == bare

    def test_stops_at_the_directory_boundary(self, tmp_path):
        assert "/lib/Alpha/other.jpg" not in self._paths_for(tmp_path, "/lib/A")

    def test_underscore_is_not_a_like_wildcard(self, tmp_path):
        assert self._paths_for(tmp_path, "/lib/100_MEDIA") == ["/lib/100_MEDIA/wild.jpg"]

    def test_percent_is_not_a_like_wildcard(self, tmp_path):
        assert self._paths_for(tmp_path, "/lib/100%FUN") == ["/lib/100%FUN/party.jpg"]

    def test_windows_paths_match_a_forward_slash_prefix(self, tmp_path):
        assert self._paths_for(tmp_path, "C:/lib/W/") == ["C:\\lib\\W\\win.jpg"]

    def test_empty_prefix_filters_nothing(self, tmp_path):
        assert len(self._paths_for(tmp_path, "")) == len(self.PHOTOS)


# ---------------------------------------------------------------------------
# Hide Bursts
# ---------------------------------------------------------------------------

class TestGalleryHideBursts:
    """GET /api/photos?hide_bursts=1 — only real burst members are hidden.

    Regression for issue #68: an interrupted scan whose burst post-processing
    never ran leaves is_burst_lead = 0 with burst_group_id NULL on photos that
    belong to no burst; those must stay visible and uncounted.
    """

    _PHOTOS = [
        _photo("/orphan.jpg", "2024:06:15 12:00:00", is_burst_lead=0, burst_group_id=None),
        _photo("/lead.jpg", "2024:06:15 12:00:01", is_burst_lead=1, burst_group_id=1),
        _photo("/member.jpg", "2024:06:15 12:00:02", is_burst_lead=0, burst_group_id=1),
    ]

    def _fetch(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, self._PHOTOS)
        app = _create_app_no_auth()
        with (
            mock.patch("api.routers.gallery.get_db", _conn_factory(db_path)),
            mock.patch("api.routers.gallery.get_async_db", _async_conn_factory(db_path)),
            mock.patch("api.routers.gallery.VIEWER_CONFIG", _VIEWER_CONFIG),
            mock.patch("api.db_helpers._existing_columns_cache", _TEST_PHOTOS_COLUMNS),
            mock.patch.dict("api.config._count_cache", {}, clear=True),
        ):
            resp = TestClient(app).get("/api/photos?page=1&hide_bursts=1")
        assert resp.status_code == 200
        return resp.json()

    def test_photo_without_burst_group_stays_visible(self, tmp_path):
        data = self._fetch(tmp_path)
        paths = {p["path"] for p in data["photos"]}
        assert "/orphan.jpg" in paths
        assert "/lead.jpg" in paths

    def test_real_burst_member_is_hidden(self, tmp_path):
        data = self._fetch(tmp_path)
        paths = {p["path"] for p in data["photos"]}
        assert "/member.jpg" not in paths
        assert data["total"] == 2

    def test_photo_without_burst_group_is_not_counted_as_hidden(self, tmp_path):
        data = self._fetch(tmp_path)
        assert data["hidden_summary"]["bursts"] == 1
        assert data["hidden_summary"]["total"] == 1


class TestGalleryHideBrackets:
    """GET /api/photos?hide_brackets=1 — a bracket contributes its base frame only.

    Deliberately independent of burst state: a quarter of real bracket sets share
    a burst group with unrelated frames, where the lead is not the base exposure,
    so hiding burst non-leads leaves the flanking exposures on show.
    """

    _PHOTOS = [
        _photo("/plain.jpg", "2024:06:15 11:00:00"),
        # A bracket whose frames are burst LEADS, so hide_bursts would not touch them.
        _photo("/b-under.jpg", "2024:06:15 12:00:00", is_burst_lead=1, burst_group_id=None,
               sequence_group_id=1, sequence_kind="bracket", sequence_ev_offset=-2.0),
        _photo("/b-base.jpg", "2024:06:15 12:00:01", is_burst_lead=1, burst_group_id=None,
               sequence_group_id=1, sequence_kind="bracket", sequence_ev_offset=0.0),
        _photo("/b-over.jpg", "2024:06:15 12:00:02", is_burst_lead=1, burst_group_id=None,
               sequence_group_id=1, sequence_kind="bracket", sequence_ev_offset=2.0),
    ]

    def _fetch(self, tmp_path, query):
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, self._PHOTOS)
        app = _create_app_no_auth()
        with (
            mock.patch("api.routers.gallery.get_db", _conn_factory(db_path)),
            mock.patch("api.routers.gallery.get_async_db", _async_conn_factory(db_path)),
            mock.patch("api.routers.gallery.VIEWER_CONFIG", _VIEWER_CONFIG),
            mock.patch("api.db_helpers._existing_columns_cache", _TEST_PHOTOS_COLUMNS),
            mock.patch.dict("api.config._count_cache", {}, clear=True),
        ):
            resp = TestClient(app).get(f"/api/photos?page=1&{query}")
        assert resp.status_code == 200
        return resp.json()

    def test_only_the_base_exposure_survives(self, tmp_path):
        data = self._fetch(tmp_path, "hide_brackets=1")
        paths = {p["path"] for p in data["photos"]}
        assert paths == {"/plain.jpg", "/b-base.jpg"}

    def test_ordinary_photos_are_untouched(self, tmp_path):
        data = self._fetch(tmp_path, "hide_brackets=1")
        assert "/plain.jpg" in {p["path"] for p in data["photos"]}

    def test_off_shows_every_frame(self, tmp_path):
        data = self._fetch(tmp_path, "hide_brackets=0")
        assert len(data["photos"]) == 4

    def test_hidden_frames_are_counted_for_the_banner(self, tmp_path):
        data = self._fetch(tmp_path, "hide_brackets=1")
        assert data["hidden_summary"]["brackets"] == 2
        assert data["hidden_summary"]["total"] == 2

    def test_burst_hiding_alone_would_not_have_hidden_them(self, tmp_path):
        # The premise of the filter: these frames are burst leads.
        data = self._fetch(tmp_path, "hide_bursts=1")
        assert len(data["photos"]) == 4


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

    def test_truncated_selects_worst_tail(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, [
            _photo(f"/p{i}.jpg", "2024:01:01 10:00:00", aggregate=float(i))
            for i in range(10)
        ])
        # keep 10% -> keep 1 (p9), cut 9; cap at 3 selects the WORST 3, not the
        # best of the cut. p0/p1/p2 (lowest aggregate) must be the selection.
        with mock.patch("api.routers.gallery._SELECT_BOTTOM_MAX", 3):
            data = self._get(db_path, "keep_percent=10&sort=aggregate&sort_direction=DESC").json()
        assert (data["total"], data["keep"], data["cut"]) == (10, 1, 9)
        assert data["truncated"] is True
        assert set(data["paths"]) == {"/p0.jpg", "/p1.jpg", "/p2.jpg"}


class TestGalleryHidePanoramas:
    """A panorama must survive both default hide toggles at once.

    `hide_bursts` and `hide_panoramas` both ship on, are ANDed, and pick their
    representative on unrelated criteria: the burst lead is score-ranked, the
    panorama lead is the middle frame by capture. A sweep is routinely shredded
    across several burst groups -- one real 33-frame set landed in seven -- so
    the two clauses could agree on no frame at all and the whole set vanished.
    The bracket test above cannot catch this: its frames are all burst leads.
    """

    _PHOTOS = [
        _photo("/plain.jpg", "2024:06:15 11:00:00"),
        # A sweep split across two burst groups. The panorama lead (/p-c) is
        # deliberately NOT the lead of its burst group.
        _photo("/p-a.jpg", "2024:06:15 12:00:00", is_burst_lead=1, burst_group_id=10,
               sequence_group_id=1, sequence_kind="panorama", is_sequence_lead=0),
        _photo("/p-b.jpg", "2024:06:15 12:00:01", is_burst_lead=0, burst_group_id=10,
               sequence_group_id=1, sequence_kind="panorama", is_sequence_lead=0),
        _photo("/p-c.jpg", "2024:06:15 12:00:02", is_burst_lead=0, burst_group_id=11,
               sequence_group_id=1, sequence_kind="panorama", is_sequence_lead=1),
        _photo("/p-d.jpg", "2024:06:15 12:00:03", is_burst_lead=1, burst_group_id=11,
               sequence_group_id=1, sequence_kind="panorama", is_sequence_lead=0),
    ]

    def _fetch(self, tmp_path, query):
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, self._PHOTOS)
        app = _create_app_no_auth()
        with (
            mock.patch("api.routers.gallery.get_db", _conn_factory(db_path)),
            mock.patch("api.routers.gallery.get_async_db", _async_conn_factory(db_path)),
            mock.patch("api.routers.gallery.VIEWER_CONFIG", _VIEWER_CONFIG),
            mock.patch("api.db_helpers._existing_columns_cache", _TEST_PHOTOS_COLUMNS),
            mock.patch.dict("api.config._count_cache", {}, clear=True),
        ):
            resp = TestClient(app).get(f"/api/photos?page=1&{query}")
        assert resp.status_code == 200
        return [p["path"] for p in resp.json()["photos"]]

    def test_the_representative_survives_both_default_toggles(self, tmp_path):
        paths = self._fetch(tmp_path, "hide_bursts=1&hide_panoramas=1&per_page=50")
        assert "/p-c.jpg" in paths, "the whole panorama vanished with both toggles on"
        assert sorted(p for p in paths if p.startswith("/p-")) == ["/p-c.jpg"]

    def test_hide_panoramas_alone_keeps_only_the_representative(self, tmp_path):
        paths = self._fetch(tmp_path, "hide_panoramas=1&per_page=50")
        assert sorted(p for p in paths if p.startswith("/p-")) == ["/p-c.jpg"]

    def test_ordinary_photos_are_untouched(self, tmp_path):
        assert "/plain.jpg" in self._fetch(tmp_path, "hide_bursts=1&hide_panoramas=1&per_page=50")


class TestGallerySequenceOverrideFilter:
    """Pending panorama corrections, surfaced on the payload and listable.

    A correction lives in `photo_sequence_overrides` and changes nothing in
    `photos` until the next detection run rewrites the labels, so it is
    invisible in `sequence_kind` by construction. Without a way to list them the
    only record that a correction is still waiting on that run is the user's
    memory.
    """

    _PHOTOS = [
        _photo("/plain.jpg", "2024:06:15 11:00:00"),
        _photo("/killed.jpg", "2024:06:15 12:00:00",
               sequence_group_id=1, sequence_kind="panorama", is_sequence_lead=1),
        _photo("/forced-a.jpg", "2024:06:15 13:00:00"),
        _photo("/forced-b.jpg", "2024:06:15 13:00:01"),
    ]

    _OVERRIDES = [
        ("/killed.jpg", None, None),
        ("/forced-a.jpg", "panorama", "/forced-a.jpg"),
        ("/forced-b.jpg", "panorama", "/forced-a.jpg"),
    ]

    def _fetch(self, tmp_path, query):
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, self._PHOTOS)
        conn = sqlite3.connect(db_path)
        conn.executemany(
            "INSERT INTO photo_sequence_overrides "
            "(photo_path, sequence_kind, override_group_key, source) VALUES (?, ?, ?, 'user')",
            self._OVERRIDES,
        )
        conn.commit()
        conn.close()
        app = _create_app_no_auth()
        with (
            mock.patch("api.routers.gallery.get_db", _conn_factory(db_path)),
            mock.patch("api.routers.gallery.get_async_db", _async_conn_factory(db_path)),
            mock.patch("api.routers.gallery.VIEWER_CONFIG", _VIEWER_CONFIG),
            mock.patch("api.db_helpers._existing_columns_cache", _TEST_PHOTOS_COLUMNS),
            mock.patch.dict("api.config._count_cache", {}, clear=True),
        ):
            resp = TestClient(app).get(f"/api/photos?page=1&per_page=50&{query}")
        assert resp.status_code == 200
        return resp.json()["photos"]

    def test_a_suppression_reads_as_suppressed(self, tmp_path):
        by_path = {p["path"]: p for p in self._fetch(tmp_path, "")}
        assert by_path["/killed.jpg"]["sequence_override"] == "suppressed"

    def test_a_forced_set_reports_its_kind(self, tmp_path):
        by_path = {p["path"]: p for p in self._fetch(tmp_path, "")}
        assert by_path["/forced-a.jpg"]["sequence_override"] == "panorama"

    def test_an_uncorrected_photo_reports_nothing(self, tmp_path):
        by_path = {p["path"]: p for p in self._fetch(tmp_path, "")}
        assert by_path["/plain.jpg"]["sequence_override"] is None

    def test_any_lists_both_directions(self, tmp_path):
        paths = {p["path"] for p in self._fetch(tmp_path, "sequence_override=any")}
        assert paths == {"/killed.jpg", "/forced-a.jpg", "/forced-b.jpg"}

    def test_suppressed_excludes_forced_sets(self, tmp_path):
        paths = {p["path"] for p in self._fetch(tmp_path, "sequence_override=suppressed")}
        assert paths == {"/killed.jpg"}

    def test_forced_excludes_suppressions(self, tmp_path):
        paths = {p["path"] for p in self._fetch(tmp_path, "sequence_override=forced")}
        assert paths == {"/forced-a.jpg", "/forced-b.jpg"}

    def test_an_unknown_value_filters_nothing(self, tmp_path):
        paths = {p["path"] for p in self._fetch(tmp_path, "sequence_override=nonsense")}
        assert "/plain.jpg" in paths

    def test_the_hide_toggles_still_compose(self, tmp_path):
        """A suppressed frame is still a labelled panorama until the re-run, so
        `hide_panoramas` must keep applying to it -- the filter narrows the
        view, it does not exempt rows from the visibility rules."""
        paths = {p["path"] for p in self._fetch(
            tmp_path, "sequence_override=any&hide_panoramas=1")}
        assert "/killed.jpg" in paths  # it is its own set's lead
        assert paths == {"/killed.jpg", "/forced-a.jpg", "/forced-b.jpg"}
