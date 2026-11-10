"""Tests for the capsules endpoint (api/routers/capsules.py)."""

import time
from contextlib import nullcontext
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from api import create_app
from api.auth import CurrentUser, require_authenticated

_AUTH_MODULE = "api.auth"
_ROUTER_MODULE = "api.routers.capsules"


def _make_capsule(id_="c1", type_="journey", title="Trip", subtitle="A trip",
                  cover="/photo.jpg", photo_count=5, paths=None):
    """Build a fake capsule dict."""
    return {
        "id": id_,
        "type": type_,
        "title": title,
        "title_key": "",
        "title_params": {},
        "subtitle": subtitle,
        "cover_photo_path": cover,
        "photo_count": photo_count,
        "icon": "map",
        "params": {"paths": ["/a.jpg", "/b.jpg"] if paths is None else paths},
    }


@pytest.fixture()
def client():
    app = create_app()
    return TestClient(app, raise_server_exceptions=False)


class TestListCapsules:
    """Tests for GET /api/capsules."""

    def test_list_capsules_returns_data(self, client):
        """Cached capsules are returned with pagination metadata."""
        capsules = [_make_capsule("c1"), _make_capsule("c2")]

        # Seed the cache directly so no DB or generator is needed
        cache_entry = {"data": capsules, "ts": time.time()}
        with mock.patch(f"{_ROUTER_MODULE}._capsule_cache", {(None, "", ""): cache_entry}):
            resp = client.get("/api/capsules")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert len(body["capsules"]) == 2
        assert body["capsules"][0]["id"] == "c1"
        assert body["has_more"] is False

    def test_list_capsules_pagination(self, client):
        """Pagination slices the cached list correctly."""
        capsules = [_make_capsule(f"c{i}") for i in range(5)]
        cache_entry = {"data": capsules, "ts": time.time()}

        with mock.patch(f"{_ROUTER_MODULE}._capsule_cache", {(None, "", ""): cache_entry}):
            resp = client.get("/api/capsules", params={"page": 1, "per_page": 2})

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 5
        assert len(body["capsules"]) == 2
        assert body["has_more"] is True

    def test_list_capsules_generates_on_cache_miss(self, client):
        """When cache is empty, capsules are generated from DB."""
        capsules = [_make_capsule("gen1")]

        mock_conn = mock.MagicMock()
        with (
            mock.patch(f"{_ROUTER_MODULE}._capsule_cache", {}),
            mock.patch(f"{_ROUTER_MODULE}.get_db", return_value=nullcontext(mock_conn)),
            mock.patch(f"{_ROUTER_MODULE}.generate_all_capsules", create=True),
            mock.patch("analyzers.capsule_generator.generate_all_capsules", return_value=capsules),
        ):
            resp = client.get("/api/capsules")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["capsules"][0]["id"] == "gen1"


class TestStartupCacheFallback:
    """The startup pass runs anonymously; a user without their own cache may borrow its result."""

    def test_empty_startup_result_is_not_borrowed(self):
        from api.routers.capsules import _get_cached_capsules
        cache = {(None, "", ""): {"data": [], "ts": time.time()}}
        with mock.patch(f"{_ROUTER_MODULE}._capsule_cache", cache):
            assert _get_cached_capsules("alice") == (None, False)

    def test_populated_startup_result_is_borrowed(self):
        from api.routers.capsules import _get_cached_capsules
        capsules = [_make_capsule("c1")]
        cache = {(None, "", ""): {"data": capsules, "ts": time.time()}}
        with mock.patch(f"{_ROUTER_MODULE}._capsule_cache", cache):
            assert _get_cached_capsules("alice") == (capsules, True)


class TestCapsulePhotos:
    """Tests for GET /api/capsules/{capsule_id}/photos."""

    def test_capsule_photos_not_found(self, client):
        """Unknown capsule ID returns 404."""
        # Empty cache forces generation, which also finds nothing
        capsules = [_make_capsule("existing")]
        cache_entry = {"data": capsules, "ts": time.time()}

        with mock.patch(f"{_ROUTER_MODULE}._capsule_cache", {(None, "", ""): cache_entry}):
            resp = client.get("/api/capsules/nonexistent/photos")

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_capsule_photos_returns_photos(self, client):
        """Valid capsule returns its photos in path order."""
        from contextlib import asynccontextmanager
        capsule = _make_capsule("c1", paths=["/x.jpg", "/y.jpg"])
        cache_entry = {"data": [capsule], "ts": time.time()}

        photo_rows = [
            {"path": "/y.jpg", "tags": "", "date_taken": "2024:01:01 12:00:00", "filename": "y.jpg"},
            {"path": "/x.jpg", "tags": "", "date_taken": "2024:01:02 12:00:00", "filename": "x.jpg"},
        ]

        # Async conn mock — /api/capsules/{id}/photos now uses get_async_db.
        class _Cursor:
            async def fetchall(self): return photo_rows
            async def fetchone(self): return photo_rows[0]
            async def close(self): pass

        class _Conn:
            async def execute(self, *a, **kw): return _Cursor()

        @asynccontextmanager
        async def _async_cm():
            yield _Conn()

        async def _async_noop(*args, **kwargs):
            return None

        with (
            mock.patch(f"{_ROUTER_MODULE}._capsule_cache", {(None, "", ""): cache_entry}),
            mock.patch(f"{_ROUTER_MODULE}.get_async_db", _async_cm),
            mock.patch(f"{_ROUTER_MODULE}.build_photo_select_columns", return_value=["path", "tags", "date_taken"]),
            mock.patch(f"{_ROUTER_MODULE}.get_visibility_clause", return_value=("1=1", [])),
            mock.patch(f"{_ROUTER_MODULE}.split_photo_tags", return_value=photo_rows),
            mock.patch(f"{_ROUTER_MODULE}.attach_person_data_async", _async_noop),
            mock.patch(f"{_ROUTER_MODULE}.sanitize_float_values"),
            mock.patch(f"{_ROUTER_MODULE}.format_date", return_value="01/01/2024 12:00"),
            mock.patch("api.config.VIEWER_CONFIG", {"display": {"tags_per_photo": 10}}),
        ):
            resp = client.get("/api/capsules/c1/photos")

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["photos"]) == 2
        # Should be reordered to match capsule path order
        assert body["photos"][0]["path"] == "/x.jpg"
        assert body["photos"][1]["path"] == "/y.jpg"
        assert body["capsule"]["id"] == "c1"

    def test_capsule_photos_empty_paths(self, client):
        """Capsule with no paths returns empty photos list."""
        capsule = _make_capsule("c1", paths=[])
        cache_entry = {"data": [capsule], "ts": time.time()}

        with mock.patch(f"{_ROUTER_MODULE}._capsule_cache", {(None, "", ""): cache_entry}):
            resp = client.get("/api/capsules/c1/photos")

        assert resp.status_code == 200
        body = resp.json()
        assert body["photos"] == []


class TestSaveCapsuleAsAlbum:
    """Tests for POST /api/capsules/{capsule_id}/save-album."""

    def test_save_as_album_requires_edition(self):
        """Non-edition user gets 403."""
        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)

        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", {"password": "", "edition_password": "secret", "features": {}}),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=True),
        ):
            regular = CurrentUser(user_id="u1", role="user")
            app.dependency_overrides[require_authenticated] = lambda: regular
            resp = client.post("/api/capsules/c1/save-album")

        assert resp.status_code == 403

    def test_save_as_album_success(self):
        """Edition user can save a capsule as an album."""
        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)

        capsule = _make_capsule("c1", paths=["/a.jpg", "/b.jpg"])
        cache_entry = {"data": [capsule], "ts": time.time()}

        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.lastrowid = 42

        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", {"password": "", "edition_password": "", "features": {}}),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=True),
            mock.patch(f"{_ROUTER_MODULE}._capsule_cache", {(None, "", ""): cache_entry}),
            mock.patch(f"{_ROUTER_MODULE}.get_db", return_value=nullcontext(mock_conn)),
        ):
            admin = CurrentUser(user_id="a1", role="admin")
            app.dependency_overrides[require_authenticated] = lambda: admin
            resp = client.post("/api/capsules/c1/save-album")

        assert resp.status_code == 200
        body = resp.json()
        assert body["album_id"] == 42
        assert body["name"] == "Trip"
