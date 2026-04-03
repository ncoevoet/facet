"""
Tests for the faces API router — rating, favorites, face assignment.

Uses mock-based approach since face operations are mutations.
"""

from contextlib import contextmanager
from unittest import mock

from fastapi.testclient import TestClient

from api import create_app
from api.auth import CurrentUser, require_authenticated


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_AUTH_MODULE = "api.auth"


def _cm(conn):
    """Wrap a mock connection in a context manager compatible with get_db()."""
    @contextmanager
    def _ctx():
        yield conn
    return _ctx


def _make_app_and_client(raise_server_exceptions=True):
    app = create_app()
    client = TestClient(app, raise_server_exceptions=raise_server_exceptions)
    return app, client


def _override_auth_user(app, user):
    """Override auth to return the given user."""
    app.dependency_overrides[require_authenticated] = lambda: user
    return app


# ---------------------------------------------------------------------------
# Set Rating
# ---------------------------------------------------------------------------

class TestSetRating:
    """POST /api/photo/set_rating — star rating (0-5)."""

    def test_set_rating_success(self):
        conn_mock = mock.MagicMock()
        conn_mock.execute.return_value = mock.MagicMock()

        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", {"password": "", "edition_password": "", "features": {}}),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=False),
            mock.patch("api.routers.faces.is_multi_user_enabled", return_value=False),
        ):
            app, client = _make_app_and_client()
            user = CurrentUser(user_id="u1", role="admin", edition_authenticated=True)
            _override_auth_user(app, user)
            with mock.patch("api.routers.faces.get_db", _cm(conn_mock)):
                resp = client.post(
                    "/api/photo/set_rating",
                    json={"photo_path": "/photo.jpg", "rating": 3},
                )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["rating"] == 3

    def test_set_rating_validation(self):
        """Rating outside 0-5 should yield 422 from Pydantic validation."""
        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", {"password": "", "edition_password": "", "features": {}}),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=False),
            mock.patch("api.routers.faces.is_multi_user_enabled", return_value=False),
        ):
            app, client = _make_app_and_client(raise_server_exceptions=False)
            user = CurrentUser(user_id="u1", role="admin", edition_authenticated=True)
            _override_auth_user(app, user)
            resp = client.post(
                "/api/photo/set_rating",
                json={"photo_path": "/photo.jpg", "rating": 6},
            )
        assert resp.status_code == 422

    def test_set_rating_requires_auth(self):
        """Without authentication, set_rating should return 401."""
        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", {"password": "secret", "edition_password": "", "features": {}}),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=True),
        ):
            app, client = _make_app_and_client(raise_server_exceptions=False)
            # No auth override — unauthenticated request
            resp = client.post(
                "/api/photo/set_rating",
                json={"photo_path": "/photo.jpg", "rating": 3},
            )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Toggle Favorite
# ---------------------------------------------------------------------------

class TestToggleFavorite:
    """POST /api/photo/toggle_favorite — toggle favorite flag."""

    def test_toggle_favorite_success(self):
        conn_mock = mock.MagicMock()
        # Simulate existing photo row with is_favorite=0
        row_mock = mock.MagicMock()
        row_mock.__getitem__ = lambda self, key: 0  # is_favorite = 0
        conn_mock.execute.return_value.fetchone.return_value = row_mock

        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", {"password": "", "edition_password": "", "features": {}}),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=False),
            mock.patch("api.routers.faces.is_multi_user_enabled", return_value=False),
        ):
            app, client = _make_app_and_client()
            user = CurrentUser(user_id="u1", role="admin", edition_authenticated=True)
            _override_auth_user(app, user)
            with mock.patch("api.routers.faces.get_db", _cm(conn_mock)):
                resp = client.post(
                    "/api/photo/toggle_favorite",
                    json={"photo_path": "/photo.jpg"},
                )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["is_favorite"] is True
        # Verify UPDATE was called
        calls = [str(c) for c in conn_mock.execute.call_args_list]
        assert any("UPDATE" in c for c in calls)


# ---------------------------------------------------------------------------
# Assign Face
# ---------------------------------------------------------------------------

class TestAssignFace:
    """POST /api/face/{face_id}/assign — assign a face to a person."""

    def test_assign_face_not_found(self):
        conn_mock = mock.MagicMock()
        conn_mock.execute.return_value.fetchone.return_value = None

        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", {"password": "", "edition_password": "", "features": {}}),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=False),
            mock.patch("api.routers.faces.is_multi_user_enabled", return_value=False),
        ):
            app, client = _make_app_and_client(raise_server_exceptions=False)
            user = CurrentUser(user_id="u1", role="admin", edition_authenticated=True)
            _override_auth_user(app, user)
            with mock.patch("api.routers.faces.get_db", _cm(conn_mock)):
                resp = client.post(
                    "/api/face/999/assign",
                    json={"person_id": 1},
                )
        assert resp.status_code == 404

    def test_assign_face_success(self):
        conn_mock = mock.MagicMock()
        # First call: SELECT person_id FROM faces WHERE id = ?
        face_row = mock.MagicMock()
        face_row.__getitem__ = lambda self, key: None  # person_id = None (unassigned)
        conn_mock.execute.return_value.fetchone.return_value = face_row

        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", {"password": "", "edition_password": "", "features": {}}),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=False),
            mock.patch("api.routers.faces.is_multi_user_enabled", return_value=False),
        ):
            app, client = _make_app_and_client()
            user = CurrentUser(user_id="u1", role="admin", edition_authenticated=True)
            _override_auth_user(app, user)
            with mock.patch("api.routers.faces.get_db", _cm(conn_mock)):
                resp = client.post(
                    "/api/face/1/assign",
                    json={"person_id": 5},
                )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
