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
from db.schema import init_database


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAMPLE_PHOTO = {
    "filename": "a.jpg", "aggregate": 7.0, "aesthetic": 6.0,
    "comp_score": 5.0, "tech_sharpness": 4.0, "color_score": 5.0,
    "exposure_score": 6.0, "category": "default",
    "image_width": 4000, "image_height": 3000,
}


def _photo(path, date_taken, **overrides):
    return {**_SAMPLE_PHOTO, "path": path, "date_taken": date_taken, **overrides}


def _make_db(path, photos, persons=None, faces=None):
    init_database(path)
    conn = sqlite3.connect(path)
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
    for i, face in enumerate(faces or []):
        face_id, photo_path, person_id = face
        conn.execute(
            "INSERT INTO faces (id, photo_path, face_index, embedding, person_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (face_id, photo_path, i, b"\x00" * 4, person_id),
        )
    conn.commit()
    conn.close()


def _existing_columns(db_path):
    """The real column set for the temp DB's photos table.

    Mirrors tests/test_extended_iqa_gallery.py's ``gallery_db`` fixture:
    pre-seeds ``api.db_helpers._existing_columns_cache`` from the SAME temp
    DB the request will query, so ``build_photo_select_columns`` (which
    intersects ``PHOTO_OPTIONAL_COLS`` against this set) selects every
    optional column the real schema defines instead of a hand-picked subset.
    """
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
            mock.patch("api.db_helpers._existing_columns_cache", _existing_columns(db_path)),
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
            mock.patch("api.db_helpers._existing_columns_cache", _existing_columns(db_path)),
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
            mock.patch("api.db_helpers._existing_columns_cache", _existing_columns(db_path)),
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
            mock.patch("api.db_helpers._existing_columns_cache", _existing_columns(db_path)),
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
            mock.patch("api.db_helpers._existing_columns_cache", _existing_columns(db_path)),
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
            mock.patch("api.db_helpers._existing_columns_cache", _existing_columns(db_path)),
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
            mock.patch("api.db_helpers._existing_columns_cache", _existing_columns(db_path)),
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
            mock.patch("api.db_helpers._existing_columns_cache", _existing_columns(db_path)),
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
            mock.patch("api.db_helpers._existing_columns_cache", _existing_columns(db_path)),
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
            mock.patch("api.db_helpers._existing_columns_cache", _existing_columns(db_path)),
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
            mock.patch("api.db_helpers._existing_columns_cache", _existing_columns(db_path)),
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
            mock.patch("api.db_helpers._existing_columns_cache", _existing_columns(db_path)),
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
            mock.patch("api.db_helpers._existing_columns_cache", _existing_columns(db_path)),
            mock.patch.dict("api.config._count_cache", {}, clear=True),
        ):
            resp = TestClient(app).get("/api/photo?path=/found.jpg")
        assert resp.status_code == 200
        data = resp.json()
        assert data["path"] == "/found.jpg"
        assert data["aggregate"] == 7.0


# ---------------------------------------------------------------------------
# Extended Metric Columns
# ---------------------------------------------------------------------------

class TestGalleryExtendedMetricColumns:
    """GET /api/photos must surface every optional metric column with its
    real value, not just the handful the old hand-rolled test schema had
    columns for.

    ``build_photo_select_columns`` (api/db_helpers.py) intersects
    ``PHOTO_OPTIONAL_COLS`` — the real optional-column list — against
    whatever the photos table actually has. A test schema missing a column
    hides it from this SELECT forever, so a serialisation regression on that
    column (wrong key, dropped value, wrong type) could never fail this
    suite. This seeds a row that populates every one of them and asserts the
    payload carries the exact value through, not merely the key.
    """

    _EXTENDED_METRICS = {
        "histogram_spread": 42.5,
        "mean_luminance": 128.75,
        "power_point_score": 6.25,
        "shadow_clipped": 1,
        "highlight_clipped": 0,
        "is_silhouette": 1,
        "is_group_portrait": 0,
        "leading_lines_score": 3.4,
        "channel_clip_shadow_pct": 2.1,
        "channel_clip_highlight_pct": 0.5,
        "face_confidence": 0.91,
        "mean_saturation": 55.3,
        "quality_score": 7.8,
        "topiq_score": 6.9,
        "aesthetic_iaa": 5.4,
        "face_quality_iqa": 8.1,
        "liqe_score": 4.2,
        "qrealign_score": 7.3,
        "aesthetic_v25": 6.6,
        "deqa_score": 5.9,
        "subject_sharpness": 120.4,
        "subject_prominence": 0.35,
        "subject_placement": 0.62,
        "bg_separation": 0.78,
        "caption": "A hiker on a ridge at sunset",
        "caption_translated": "Un randonneur sur une crête au coucher du soleil",
        "gps_latitude": 45.1885,
        "gps_longitude": 5.7245,
        "dominant_hue": 27.5,
        "color_temp": "warm",
        "form_symmetry": 6.1,
        "form_balance": 7.2,
        "form_edge_entropy": 5.5,
        "form_fractal": 4.8,
        "color_harmony": 8.3,
        "narrative_moment": "celebration",
        "narrative_moment_confidence": 0.87,
        "junk_kind": "not_junk",
        # Not asserting the "NULL whenever width/height are real" invariant
        # here (see db/schema.py) -- this test only checks serialisation.
        "image_aspect": 1.6,
    }

    def test_extended_metric_columns_survive_into_the_payload(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, [
            _photo("/extended.jpg", "2024:06:15 12:00:00", **self._EXTENDED_METRICS)
        ])
        app = _create_app_no_auth()
        with (
            mock.patch("api.routers.gallery.get_db", _conn_factory(db_path)),
            mock.patch("api.routers.gallery.get_async_db", _async_conn_factory(db_path)),
            mock.patch("api.routers.gallery.VIEWER_CONFIG", _VIEWER_CONFIG),
            mock.patch("api.db_helpers._existing_columns_cache", _existing_columns(db_path)),
            # caption_translated is only selected when translation is on
            # (see build_photo_select_columns) -- pin it rather than
            # depending on the repo's own scoring_config.json content.
            mock.patch("api.db_helpers._FULL_CONFIG", {"translation": {"target_language": "fr"}}),
            mock.patch.dict("api.config._count_cache", {}, clear=True),
        ):
            resp = TestClient(app).get("/api/photos?page=1")
        assert resp.status_code == 200
        photo = resp.json()["photos"][0]
        for col, expected in self._EXTENDED_METRICS.items():
            assert photo[col] == expected, f"{col}: expected {expected!r}, got {photo.get(col)!r}"


class TestSelectBottomPercent:
    """GET /api/photos/select_bottom_percent — 'keep top N%' percentile selection."""

    def _get(self, db_path, query):
        app = _create_app_no_auth()
        with (
            mock.patch("api.routers.gallery.get_db", _conn_factory(db_path)),
            mock.patch("api.routers.gallery.get_async_db", _async_conn_factory(db_path)),
            mock.patch("api.routers.gallery.VIEWER_CONFIG", _VIEWER_CONFIG),
            mock.patch("api.db_helpers._existing_columns_cache", _existing_columns(db_path)),
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
            mock.patch("api.db_helpers._existing_columns_cache", _existing_columns(db_path)),
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
            mock.patch("api.db_helpers._existing_columns_cache", _existing_columns(db_path)),
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


# ---------------------------------------------------------------------------
# Photo Set Scope (GET /api/photos?sequence_kind=...&sequence_group_id=...
#                                  |burst_group_id=...|duplicate_group_id=...)
# ---------------------------------------------------------------------------

class TestGallerySetScopeFilter:
    """The photo-detail "open this set in the gallery" action.

    Never round-tripped through the URL client-side (sequence_group_id is
    renumbered from 1 on every detection pass), but server-side it must both
    narrow to the one set AND suppress EVERY hide toggle, not just the one
    matching the scope's own kind -- without that, the default hide toggles
    (all on) would collapse the filtered gallery back down to a single lead
    tile. A photo can belong to a bracket AND a burst AND a duplicate group
    at once (an AEB set fired in continuous drive mode is grouped as both a
    bracket and a burst), so suppressing only the matching toggle is
    insufficient by construction -- see
    test_bracket_scope_survives_hide_bursts_when_the_set_is_also_a_burst.
    """

    _PHOTOS = [
        _photo("/plain.jpg", "2024:06:15 11:00:00"),
        _photo("/b-under.jpg", "2024:06:15 12:00:00",
               sequence_group_id=1, sequence_kind="bracket", sequence_ev_offset=-2.0),
        _photo("/b-base.jpg", "2024:06:15 12:00:01",
               sequence_group_id=1, sequence_kind="bracket", sequence_ev_offset=0.0),
        _photo("/b-over.jpg", "2024:06:15 12:00:02",
               sequence_group_id=1, sequence_kind="bracket", sequence_ev_offset=2.0),
        _photo("/p-a.jpg", "2024:06:15 13:00:00",
               sequence_group_id=2, sequence_kind="panorama", is_sequence_lead=0),
        _photo("/p-b.jpg", "2024:06:15 13:00:01",
               sequence_group_id=2, sequence_kind="panorama", is_sequence_lead=1),
        _photo("/p-c.jpg", "2024:06:15 13:00:02",
               sequence_group_id=2, sequence_kind="panorama", is_sequence_lead=0),
        _photo("/burst-a.jpg", "2024:06:15 14:00:00", burst_group_id=5, is_burst_lead=0),
        _photo("/burst-b.jpg", "2024:06:15 14:00:01", burst_group_id=5, is_burst_lead=1),
        _photo("/dup-a.jpg", "2024:06:15 15:00:00", duplicate_group_id=9, is_duplicate_lead=1),
        _photo("/dup-b.jpg", "2024:06:15 15:00:01", duplicate_group_id=9, is_duplicate_lead=0),
    ]

    _ALL_HIDE_TOGGLES = "hide_bursts=1&hide_duplicates=1&hide_brackets=1&hide_panoramas=1"

    def _fetch(self, tmp_path, query, photos=None):
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, photos if photos is not None else self._PHOTOS)
        app = _create_app_no_auth()
        with (
            mock.patch("api.routers.gallery.get_db", _conn_factory(db_path)),
            mock.patch("api.routers.gallery.get_async_db", _async_conn_factory(db_path)),
            mock.patch("api.routers.gallery.VIEWER_CONFIG", _VIEWER_CONFIG),
            mock.patch("api.db_helpers._existing_columns_cache", _existing_columns(db_path)),
            mock.patch.dict("api.config._count_cache", {}, clear=True),
        ):
            resp = TestClient(app).get(f"/api/photos?page=1&per_page=50&{query}")
        assert resp.status_code == 200
        return {p["path"] for p in resp.json()["photos"]}

    def test_bracket_scope_returns_every_frame_with_default_hide_toggles(self, tmp_path):
        paths = self._fetch(
            tmp_path, f"sequence_kind=bracket&sequence_group_id=1&{self._ALL_HIDE_TOGGLES}")
        assert paths == {"/b-under.jpg", "/b-base.jpg", "/b-over.jpg"}

    def test_panorama_scope_returns_every_frame_with_default_hide_toggles(self, tmp_path):
        paths = self._fetch(
            tmp_path, f"sequence_kind=panorama&sequence_group_id=2&{self._ALL_HIDE_TOGGLES}")
        assert paths == {"/p-a.jpg", "/p-b.jpg", "/p-c.jpg"}

    def test_burst_scope_returns_every_frame_with_default_hide_toggles(self, tmp_path):
        paths = self._fetch(tmp_path, f"burst_group_id=5&{self._ALL_HIDE_TOGGLES}")
        assert paths == {"/burst-a.jpg", "/burst-b.jpg"}

    def test_duplicate_scope_returns_every_frame_with_default_hide_toggles(self, tmp_path):
        paths = self._fetch(tmp_path, f"duplicate_group_id=9&{self._ALL_HIDE_TOGGLES}")
        assert paths == {"/dup-a.jpg", "/dup-b.jpg"}

    def test_scope_narrows_to_only_that_set(self, tmp_path):
        """Every hide toggle is suppressed while scoped, but the WHERE clause
        narrowing to the scoped set's own id is unaffected -- unrelated sets
        stay scoped out even though their hide toggles are also off."""
        paths = self._fetch(tmp_path, f"burst_group_id=5&{self._ALL_HIDE_TOGGLES}")
        assert "/b-under.jpg" not in paths
        assert "/p-a.jpg" not in paths
        assert "/dup-a.jpg" not in paths
        assert "/plain.jpg" not in paths

    def test_unscoped_request_still_collapses_every_set_to_its_lead(self, tmp_path):
        paths = self._fetch(tmp_path, self._ALL_HIDE_TOGGLES)
        assert paths == {"/plain.jpg", "/b-base.jpg", "/p-b.jpg", "/burst-b.jpg", "/dup-a.jpg"}

    def test_bracket_scope_excludes_a_panorama_sharing_the_same_group_id(self, tmp_path):
        """The bracket and panorama detection passes own disjoint rows but
        each renumbers its own groups from 1 every run, so a bracket and a
        panorama can legitimately share sequence_group_id=1 at the same
        time on real data. The scope filter must key on the
        (sequence_kind, sequence_group_id) PAIR -- if sequence_kind were
        ever dropped from the WHERE clause, this query would silently pull
        in the panorama's frames too.
        """
        colliding_group_id = [
            _photo("/b-under.jpg", "2024:06:15 12:00:00",
                   sequence_group_id=1, sequence_kind="bracket", sequence_ev_offset=-2.0),
            _photo("/b-base.jpg", "2024:06:15 12:00:01",
                   sequence_group_id=1, sequence_kind="bracket", sequence_ev_offset=0.0),
            _photo("/b-over.jpg", "2024:06:15 12:00:02",
                   sequence_group_id=1, sequence_kind="bracket", sequence_ev_offset=2.0),
            _photo("/p-a.jpg", "2024:06:15 13:00:00",
                   sequence_group_id=1, sequence_kind="panorama", is_sequence_lead=0),
            _photo("/p-b.jpg", "2024:06:15 13:00:01",
                   sequence_group_id=1, sequence_kind="panorama", is_sequence_lead=1),
            _photo("/p-c.jpg", "2024:06:15 13:00:02",
                   sequence_group_id=1, sequence_kind="panorama", is_sequence_lead=0),
        ]
        paths = self._fetch(
            tmp_path, f"sequence_kind=bracket&sequence_group_id=1&{self._ALL_HIDE_TOGGLES}",
            photos=colliding_group_id,
        )
        assert paths == {"/b-under.jpg", "/b-base.jpg", "/b-over.jpg"}

    def test_bracket_scope_survives_hide_bursts_when_the_set_is_also_a_burst(self, tmp_path):
        """A real AEB set fired in continuous drive mode is grouped as BOTH a
        bracket (by the sequence pass) and a burst (by the burst pass), with
        none of the sequence-lead frames necessarily the burst lead. Scoping
        to the bracket must suppress hide_bursts too, or hide_bursts=1 (on by
        default) collapses the set to its one burst-lead frame.
        """
        overlapping = [
            _photo("/ab-1.jpg", "2024:06:15 18:00:00", sequence_group_id=4, sequence_kind="bracket",
                   sequence_ev_offset=-2.0, burst_group_id=20, is_burst_lead=0),
            _photo("/ab-2.jpg", "2024:06:15 18:00:01", sequence_group_id=4, sequence_kind="bracket",
                   sequence_ev_offset=-1.0, burst_group_id=20, is_burst_lead=0),
            _photo("/ab-3.jpg", "2024:06:15 18:00:02", sequence_group_id=4, sequence_kind="bracket",
                   sequence_ev_offset=0.0, burst_group_id=20, is_burst_lead=1),
            _photo("/ab-4.jpg", "2024:06:15 18:00:03", sequence_group_id=4, sequence_kind="bracket",
                   sequence_ev_offset=1.0, burst_group_id=20, is_burst_lead=0),
            _photo("/ab-5.jpg", "2024:06:15 18:00:04", sequence_group_id=4, sequence_kind="bracket",
                   sequence_ev_offset=2.0, burst_group_id=20, is_burst_lead=0),
        ]
        paths = self._fetch(
            tmp_path, f"sequence_kind=bracket&sequence_group_id=4&{self._ALL_HIDE_TOGGLES}",
            photos=overlapping,
        )
        assert paths == {"/ab-1.jpg", "/ab-2.jpg", "/ab-3.jpg", "/ab-4.jpg", "/ab-5.jpg"}


# ---------------------------------------------------------------------------
# GET /api/photo/set
# ---------------------------------------------------------------------------

class TestPhotoSetEndpoint:
    """GET /api/photo/set -- resolve the set a photo belongs to, keyed on path.

    Priority is sequence, then burst, then duplicate, resolved from the
    photo's own row -- see .claude/patterns/panorama-detection.md.
    """

    _PHOTOS = [
        _photo("/lone.jpg", "2024:06:15 10:00:00"),
        _photo("/b-under.jpg", "2024:06:15 12:00:00",
               sequence_group_id=1, sequence_kind="bracket", sequence_ev_offset=-2.0, is_sequence_lead=0),
        _photo("/b-base.jpg", "2024:06:15 12:00:01",
               sequence_group_id=1, sequence_kind="bracket", sequence_ev_offset=0.0, is_sequence_lead=1),
        _photo("/b-over.jpg", "2024:06:15 12:00:02",
               sequence_group_id=1, sequence_kind="bracket", sequence_ev_offset=1.0, is_sequence_lead=0),
        _photo("/p-a.jpg", "2024:06:15 13:00:02",
               sequence_group_id=2, sequence_kind="panorama", is_sequence_lead=0),
        _photo("/p-b.jpg", "2024:06:15 13:00:00",
               sequence_group_id=2, sequence_kind="panorama", is_sequence_lead=1),
        _photo("/p-c.jpg", "2024:06:15 13:00:01",
               sequence_group_id=2, sequence_kind="panorama", is_sequence_lead=0),
        _photo("/burst-a.jpg", "2024:06:15 14:00:01", burst_group_id=5, is_burst_lead=0),
        _photo("/burst-b.jpg", "2024:06:15 14:00:00", burst_group_id=5, is_burst_lead=1),
        _photo("/dup-a.jpg", "2024:06:15 15:00:00", duplicate_group_id=9, is_duplicate_lead=1),
        _photo("/dup-b.jpg", "2024:06:15 15:00:01", duplicate_group_id=9, is_duplicate_lead=0),
        # A sequence AND a burst group -- sequence must win.
        _photo("/seq-over-burst.jpg", "2024:06:15 16:00:00",
               sequence_group_id=3, sequence_kind="bracket", sequence_ev_offset=0.0, is_sequence_lead=1,
               burst_group_id=7),
        _photo("/seq-over-burst-sibling.jpg", "2024:06:15 16:00:01",
               sequence_group_id=3, sequence_kind="bracket", sequence_ev_offset=1.0, is_sequence_lead=0),
        # A burst AND a duplicate group -- burst must win.
        _photo("/burst-over-dup.jpg", "2024:06:15 17:00:00", burst_group_id=11, is_burst_lead=1,
               duplicate_group_id=13),
        _photo("/burst-over-dup-sibling.jpg", "2024:06:15 17:00:01", burst_group_id=11, is_burst_lead=0),
    ]

    def _fetch(self, tmp_path, path):
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, self._PHOTOS)
        app = _create_app_no_auth()
        with (
            mock.patch("api.routers.gallery.get_async_db", _async_conn_factory(db_path)),
            mock.patch("api.db_helpers._existing_columns_cache", _existing_columns(db_path)),
        ):
            return TestClient(app, raise_server_exceptions=False).get(f"/api/photo/set?path={path}")

    def test_photo_not_found(self, tmp_path):
        resp = self._fetch(tmp_path, "/nonexistent.jpg")
        assert resp.status_code == 404

    def test_a_photo_in_no_set_reports_an_empty_result(self, tmp_path):
        resp = self._fetch(tmp_path, "/lone.jpg")
        assert resp.status_code == 200
        assert resp.json() == {"kind": None, "group_id": None, "count": 0, "ev_span": None, "members": []}

    def test_bracket_set_orders_by_distance_from_base_and_reports_ev_span(self, tmp_path):
        """The span is darkest-to-brightest, not the largest offset: this set is
        shot at -2/0/+1, which covers three stops and never reaches +2."""
        data = self._fetch(tmp_path, "/b-base.jpg").json()
        assert data["kind"] == "bracket"
        assert data["group_id"] == 1
        assert data["count"] == 3
        assert data["ev_span"] == 3.0
        assert [m["path"] for m in data["members"]] == ["/b-base.jpg", "/b-over.jpg", "/b-under.jpg"]
        base = next(m for m in data["members"] if m["path"] == "/b-base.jpg")
        assert base["is_lead"] is True
        assert base["ev_offset"] == 0.0
        under = next(m for m in data["members"] if m["path"] == "/b-under.jpg")
        assert under["ev_offset"] == -2.0
        assert under["is_lead"] is False

    def test_panorama_set_orders_by_capture_time_and_has_no_ev_span(self, tmp_path):
        data = self._fetch(tmp_path, "/p-a.jpg").json()
        assert data["kind"] == "panorama"
        assert data["group_id"] == 2
        assert data["count"] == 3
        assert data["ev_span"] is None
        assert [m["path"] for m in data["members"]] == ["/p-b.jpg", "/p-c.jpg", "/p-a.jpg"]
        lead = next(m for m in data["members"] if m["path"] == "/p-b.jpg")
        assert lead["is_lead"] is True

    def test_burst_set_orders_by_capture_time_and_has_no_ev_span(self, tmp_path):
        data = self._fetch(tmp_path, "/burst-a.jpg").json()
        assert data["kind"] == "burst"
        assert data["group_id"] == 5
        assert data["count"] == 2
        assert data["ev_span"] is None
        assert [m["path"] for m in data["members"]] == ["/burst-b.jpg", "/burst-a.jpg"]
        lead = next(m for m in data["members"] if m["path"] == "/burst-b.jpg")
        assert lead["is_lead"] is True

    def test_duplicate_set(self, tmp_path):
        data = self._fetch(tmp_path, "/dup-b.jpg").json()
        assert data["kind"] == "duplicate"
        assert data["group_id"] == 9
        assert data["count"] == 2
        lead = next(m for m in data["members"] if m["path"] == "/dup-a.jpg")
        assert lead["is_lead"] is True

    def test_sequence_takes_precedence_over_burst(self, tmp_path):
        data = self._fetch(tmp_path, "/seq-over-burst.jpg").json()
        assert data["kind"] == "bracket"
        assert data["group_id"] == 3
        assert {m["path"] for m in data["members"]} == {"/seq-over-burst.jpg", "/seq-over-burst-sibling.jpg"}

    def test_burst_takes_precedence_over_duplicate(self, tmp_path):
        data = self._fetch(tmp_path, "/burst-over-dup.jpg").json()
        assert data["kind"] == "burst"
        assert data["group_id"] == 11
        assert {m["path"] for m in data["members"]} == {"/burst-over-dup.jpg", "/burst-over-dup-sibling.jpg"}


# ---------------------------------------------------------------------------
# Shared conftest.seeded_photos fixture
# ---------------------------------------------------------------------------

class TestSeededPhotosFixture:
    """Proves conftest's ``seeded_photos`` is actually wired to the live app.

    Every other class in this file mocks ``get_db``/``get_async_db`` onto a
    private ``tmp_path`` database. ``seeded_photos`` instead writes into the
    SAME shared session database ``edition_client``'s app reads from
    (``DB_PATH``), so this test needs neither mock -- if the rows weren't
    landing in the right database, this would 404/empty rather than pass.
    """

    def test_edition_client_sees_seeded_rows_without_mocking(self, edition_client, seeded_photos):
        prefix = seeded_photos[0]["path"].rsplit("/", 1)[0] + "/"
        resp = edition_client.get(f"/api/photos?path_prefix={prefix}&per_page=50")
        assert resp.status_code == 200
        photos_by_path = {p["path"]: p for p in resp.json()["photos"]}
        assert set(photos_by_path) == {p["path"] for p in seeded_photos}
        for expected in seeded_photos:
            assert photos_by_path[expected["path"]]["aggregate"] == expected["aggregate"]
            assert photos_by_path[expected["path"]]["category"] == expected["category"]
