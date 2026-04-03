"""RBAC permission boundary tests.

Verifies that require_edition, require_auth, and require_superadmin
dependency functions enforce correct access control for each user role.
"""

from unittest import mock

import pytest
from fastapi.testclient import TestClient

from api import create_app
from api.auth import (
    CurrentUser,
    require_authenticated,
    require_edition,
    require_auth,
    require_superadmin,
    get_optional_user,
)

_AUTH_MODULE = "api.auth"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _viewer_config(**overrides):
    """Return a minimal viewer config dict with optional overrides."""
    cfg = {"password": "", "edition_password": "", "features": {}}
    cfg.update(overrides)
    return cfg


def _make_app_and_client(raise_server_exceptions=True):
    """Create a fresh app + client pair."""
    app = create_app()
    client = TestClient(app, raise_server_exceptions=raise_server_exceptions)
    return app, client


# ---------------------------------------------------------------------------
# Class 1: require_edition enforcement
# ---------------------------------------------------------------------------


class TestRequireEditionEnforcement:
    """Endpoints guarded by require_edition must reject non-edition users."""

    ENDPOINT = "/api/albums"  # POST uses require_edition

    @pytest.fixture(autouse=True)
    def _patch_config(self):
        viewer_cfg = _viewer_config(edition_password="secret")
        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", viewer_cfg),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=True),
        ):
            yield

    def test_unauthenticated_gets_401(self):
        """No token at all should yield 401."""
        app, client = _make_app_and_client(raise_server_exceptions=False)
        resp = client.post(self.ENDPOINT, json={"name": "test"})
        assert resp.status_code == 401

    def test_regular_user_gets_403(self):
        """A regular user (role=user) should be rejected by require_edition."""
        app, client = _make_app_and_client(raise_server_exceptions=False)
        regular = CurrentUser(user_id="u1", role="user")
        app.dependency_overrides[require_authenticated] = lambda: regular
        resp = client.post(self.ENDPOINT, json={"name": "test"})
        assert resp.status_code == 403

    def test_admin_passes(self):
        """An admin user should pass the require_edition check."""
        app, client = _make_app_and_client(raise_server_exceptions=False)
        admin = CurrentUser(user_id="a1", role="admin")
        app.dependency_overrides[require_authenticated] = lambda: admin
        # Mock DB to avoid real database access
        with mock.patch("api.routers.albums.get_db"):
            resp = client.post(self.ENDPOINT, json={"name": "test"})
        # Should NOT be 401 or 403 — auth passed
        assert resp.status_code not in (401, 403)

    def test_superadmin_passes(self):
        """A superadmin user should pass the require_edition check."""
        app, client = _make_app_and_client(raise_server_exceptions=False)
        sa = CurrentUser(user_id="sa1", role="superadmin")
        app.dependency_overrides[require_authenticated] = lambda: sa
        with mock.patch("api.routers.albums.get_db"):
            resp = client.post(self.ENDPOINT, json={"name": "test"})
        assert resp.status_code not in (401, 403)


# ---------------------------------------------------------------------------
# Class 2: require_auth enforcement (dual-path)
# ---------------------------------------------------------------------------


class TestRequireAuthEnforcement:
    """require_auth behaves differently in multi-user vs legacy mode."""

    ENDPOINT = "/api/photo/set_rating"  # POST uses require_auth

    def test_multi_user_regular_user_passes(self):
        """In multi-user mode, any logged-in user (even role=user) passes."""
        viewer_cfg = _viewer_config()
        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", viewer_cfg),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=True),
        ):
            app, client = _make_app_and_client(raise_server_exceptions=False)
            user = CurrentUser(user_id="u1", role="user")
            app.dependency_overrides[require_authenticated] = lambda: user
            with mock.patch("api.routers.faces.get_db"):
                resp = client.post(
                    self.ENDPOINT,
                    json={"path": "/fake.jpg", "rating": 3},
                )
            # Should pass auth (may fail on DB but not 401/403)
            assert resp.status_code not in (401, 403)

    def test_legacy_mode_non_edition_gets_403(self):
        """In legacy mode with edition_password set, a non-edition user gets 403."""
        viewer_cfg = _viewer_config(edition_password="secret")
        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", viewer_cfg),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=False),
        ):
            app, client = _make_app_and_client(raise_server_exceptions=False)
            # Authenticated but NOT edition-authenticated
            user = CurrentUser(user_id="viewer1", role="user", edition_authenticated=False)
            app.dependency_overrides[require_authenticated] = lambda: user
            resp = client.post(
                self.ENDPOINT,
                json={"path": "/fake.jpg", "rating": 3},
            )
            assert resp.status_code == 403

    def test_legacy_mode_edition_user_passes(self):
        """In legacy mode, an edition-authenticated user passes require_auth."""
        viewer_cfg = _viewer_config(edition_password="secret")
        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", viewer_cfg),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=False),
        ):
            app, client = _make_app_and_client(raise_server_exceptions=False)
            user = CurrentUser(user_id="viewer1", role="user", edition_authenticated=True)
            app.dependency_overrides[require_authenticated] = lambda: user
            with mock.patch("api.routers.faces.get_db"):
                resp = client.post(
                    self.ENDPOINT,
                    json={"path": "/fake.jpg", "rating": 3},
                )
            assert resp.status_code not in (401, 403)

    def test_multi_user_no_user_id_gets_401(self):
        """In multi-user mode, a CurrentUser with no user_id is rejected."""
        viewer_cfg = _viewer_config()
        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", viewer_cfg),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=True),
        ):
            app, client = _make_app_and_client(raise_server_exceptions=False)
            # Authenticated (no-password fallback) but no user_id
            user = CurrentUser()
            app.dependency_overrides[require_authenticated] = lambda: user
            resp = client.post(
                self.ENDPOINT,
                json={"path": "/fake.jpg", "rating": 3},
            )
            assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Class 3: require_superadmin enforcement
# ---------------------------------------------------------------------------


class TestRequireSuperadminEnforcement:
    """Endpoints guarded by require_superadmin must reject non-superadmin users."""

    SCAN_START = "/api/scan/start"
    SCAN_STATUS = "/api/scan/status"

    def _viewer_with_scan(self):
        return _viewer_config(features={"show_scan_button": True})

    def test_admin_gets_403_on_scan(self):
        """An admin (not superadmin) should be rejected by require_superadmin."""
        viewer_cfg = self._viewer_with_scan()
        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", viewer_cfg),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=True),
        ):
            app, client = _make_app_and_client(raise_server_exceptions=False)
            admin = CurrentUser(user_id="a1", role="admin")
            app.dependency_overrides[require_authenticated] = lambda: admin
            resp = client.post(
                self.SCAN_START,
                json={"directory": "/photos"},
            )
            assert resp.status_code == 403

    def test_superadmin_passes_scan(self):
        """A superadmin should pass the require_superadmin check."""
        viewer_cfg = self._viewer_with_scan()
        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", viewer_cfg),
            mock.patch("api.routers.scan.VIEWER_CONFIG", viewer_cfg),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=True),
        ):
            app, client = _make_app_and_client(raise_server_exceptions=False)
            sa = CurrentUser(user_id="sa1", role="superadmin")
            app.dependency_overrides[require_authenticated] = lambda: sa
            resp = client.get(self.SCAN_STATUS)
            # Should pass auth — may return 200 or other non-auth error
            assert resp.status_code not in (401, 403)

    def test_non_multi_user_mode_gets_403(self):
        """Even a superadmin role is rejected when multi-user mode is disabled."""
        viewer_cfg = self._viewer_with_scan()
        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", viewer_cfg),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=False),
        ):
            app, client = _make_app_and_client(raise_server_exceptions=False)
            sa = CurrentUser(user_id="sa1", role="superadmin")
            app.dependency_overrides[require_authenticated] = lambda: sa
            resp = client.post(
                self.SCAN_START,
                json={"directory": "/photos"},
            )
            assert resp.status_code == 403

    def test_unauthenticated_gets_401_on_scan(self):
        """No token at all should yield 401, not 403."""
        viewer_cfg = self._viewer_with_scan()
        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", viewer_cfg),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=True),
        ):
            app, client = _make_app_and_client(raise_server_exceptions=False)
            resp = client.get(self.SCAN_STATUS)
            assert resp.status_code == 401

    def test_regular_user_gets_403_on_scan(self):
        """A regular user (role=user) should be rejected by require_superadmin."""
        viewer_cfg = self._viewer_with_scan()
        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", viewer_cfg),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=True),
        ):
            app, client = _make_app_and_client(raise_server_exceptions=False)
            user = CurrentUser(user_id="u1", role="user")
            app.dependency_overrides[require_authenticated] = lambda: user
            resp = client.get(self.SCAN_STATUS)
            assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Class 4: CurrentUser property unit tests
# ---------------------------------------------------------------------------


class TestCurrentUserProperties:
    """Unit tests for CurrentUser.is_edition, is_superadmin, is_authenticated."""

    def test_user_role_not_edition(self):
        """A regular user in multi-user mode should NOT have edition access."""
        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", _viewer_config()),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=True),
        ):
            user = CurrentUser(user_id="u1", role="user")
            assert user.is_edition is False

    def test_admin_role_is_edition(self):
        """An admin in multi-user mode should have edition access."""
        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", _viewer_config()),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=True),
        ):
            user = CurrentUser(user_id="a1", role="admin")
            assert user.is_edition is True

    def test_superadmin_is_edition_and_superadmin(self):
        """A superadmin should have both is_edition and is_superadmin."""
        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", _viewer_config()),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=True),
        ):
            user = CurrentUser(user_id="sa1", role="superadmin")
            assert user.is_edition is True
            assert user.is_superadmin is True

    def test_no_password_mode_is_authenticated(self):
        """In no-password mode (no viewer password), a bare CurrentUser is authenticated."""
        viewer_cfg = _viewer_config(password="")
        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", viewer_cfg),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=False),
        ):
            user = CurrentUser()  # no user_id, no role
            assert user.is_authenticated is True

    def test_legacy_no_edition_password_is_edition(self):
        """When edition_password is empty in legacy mode, any user has edition access."""
        viewer_cfg = _viewer_config(edition_password="")
        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", viewer_cfg),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=False),
        ):
            user = CurrentUser(user_id="viewer1", role="user")
            assert user.is_edition is True

    def test_legacy_with_edition_password_requires_auth(self):
        """When edition_password is set in legacy mode, edition_authenticated must be True."""
        viewer_cfg = _viewer_config(edition_password="secret")
        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", viewer_cfg),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=False),
        ):
            not_edition = CurrentUser(user_id="v1", role="user", edition_authenticated=False)
            assert not_edition.is_edition is False

            edition = CurrentUser(user_id="v1", role="user", edition_authenticated=True)
            assert edition.is_edition is True

    def test_superadmin_role_without_multi_user(self):
        """is_superadmin depends only on role, not on multi-user mode."""
        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", _viewer_config()),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=False),
        ):
            user = CurrentUser(user_id="sa1", role="superadmin")
            assert user.is_superadmin is True

    def test_password_mode_no_user_id_not_authenticated(self):
        """With a viewer password set, a bare CurrentUser is NOT authenticated."""
        viewer_cfg = _viewer_config(password="secret")
        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", viewer_cfg),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=False),
        ):
            user = CurrentUser()  # no user_id
            assert user.is_authenticated is False

    def test_multi_user_no_user_id_not_authenticated(self):
        """In multi-user mode, a bare CurrentUser is NOT authenticated."""
        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", _viewer_config()),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=True),
        ):
            user = CurrentUser()
            assert user.is_authenticated is False
