"""An open install (no ``viewer.edition_password``) is read-only.

Every ``require_edition`` / ``require_auth`` route refuses an anonymous caller
on an open single-user install, and the on-demand generators stop writing.

The open-install caller is the plain ``client`` (no dependency overrides): it
resolves to a bare ``CurrentUser()`` through the REAL ``require_edition``.
``anonymous_client`` answers 401 before ``is_edition`` is ever read and
``edition_client`` overrides ``require_edition`` itself, so neither can express
"open install"; the routes are enumerated from the app's dependency tree so a
new ``require_edition`` route joins the sweep without anyone remembering to.
"""

from unittest import mock

import pytest
from fastapi.testclient import TestClient

from api import create_app
from api.auth import (
    CurrentUser,
    get_optional_user,
    is_edition_authenticated,
    require_auth,
    require_authenticated,
    require_edition,
)

_OPEN_CFG = {"password": "", "edition_password": "", "features": {}}
_LOCKED_CFG = {"password": "", "edition_password": "x", "features": {}}
OPEN_DETAIL = "Set viewer.edition_password to enable editing"


def _depends_on(dependant, target):
    return any(
        sub.call is target or _depends_on(sub, target)
        for sub in dependant.dependencies
    )


def _routes_requiring(dep):
    app = create_app()
    routes = []
    for top in app.routes:
        original = getattr(top, "original_router", None)
        routes.extend(original.routes if original is not None else [top])
    found = []
    for route in routes:
        dependant = getattr(route, "dependant", None)
        if dependant is None or not _depends_on(dependant, dep):
            continue
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            found.append((method, route.path))
    return sorted(found)


def _concrete(path):
    import re
    return re.sub(r"\{[^}]+\}", "1", path)


EDITION_ROUTES = _routes_requiring(require_edition)
_RATING_ROUTES = [
    ("POST", "/api/photo/set_rating"),
    ("POST", "/api/photo/toggle_favorite"),
    ("POST", "/api/photo/toggle_rejected"),
]


def _call(client, method, path):
    return client.request(method, _concrete(path), json={})


@pytest.fixture()
def open_install():
    with (
        mock.patch("api.auth.VIEWER_CONFIG", dict(_OPEN_CFG)),
        mock.patch("api.auth.is_multi_user_enabled", return_value=False),
        mock.patch("api.auth.config_load_failed", return_value=False),
    ):
        yield


class TestCurrentUserOnOpenInstall:
    def test_bare_user_is_not_edition(self, open_install):
        assert CurrentUser().is_edition is False

    def test_explicitly_unauthenticated_user_is_not_edition(self, open_install):
        assert CurrentUser(edition_authenticated=False).is_edition is False

    def test_is_edition_authenticated_is_false(self, open_install):
        assert is_edition_authenticated(CurrentUser()) is False

    def test_edition_claim_still_wins_on_a_locked_install(self):
        with (
            mock.patch("api.auth.VIEWER_CONFIG", dict(_LOCKED_CFG)),
            mock.patch("api.auth.is_multi_user_enabled", return_value=False),
        ):
            assert CurrentUser(edition_authenticated=True).is_edition is True
            assert CurrentUser().is_edition is False

    def test_auth_status_reports_not_edition(self, open_install):
        body = TestClient(create_app()).get("/api/auth/status").json()
        assert body["edition_authenticated"] is False
        assert body["edition_password_required"] is False


class TestEditionRoutesRefuseAnOpenInstall:
    def test_inventory_is_not_empty(self):
        writes = [r for r in EDITION_ROUTES if r[0] != "GET"]
        reads = [r for r in EDITION_ROUTES if r[0] == "GET"]
        assert len(EDITION_ROUTES) >= 82
        assert len(writes) >= 66
        assert len(reads) >= 16

    @pytest.mark.parametrize("method,path", EDITION_ROUTES)
    def test_open_install_is_refused(self, open_install, method, path):
        resp = _call(TestClient(create_app(), raise_server_exceptions=False), method, path)
        assert resp.status_code == 403, (method, path, resp.status_code)
        assert resp.json()["detail"] == OPEN_DETAIL

    @pytest.mark.parametrize(
        "method,path",
        [("POST", "/api/albums"), ("POST", "/api/persons/merge"), ("GET", "/api/plugins")],
    )
    def test_locked_install_with_edition_session_is_not_refused(self, method, path):
        app = create_app()
        app.dependency_overrides[get_optional_user] = lambda: CurrentUser(
            user_id="_legacy", role="user", edition_authenticated=True
        )
        with (
            mock.patch("api.auth.VIEWER_CONFIG", dict(_LOCKED_CFG)),
            mock.patch("api.auth.is_multi_user_enabled", return_value=False),
        ):
            resp = _call(TestClient(app, raise_server_exceptions=False), method, path)
        assert resp.status_code != 403

    def test_locked_install_without_edition_keeps_the_old_detail(self):
        app = create_app()
        app.dependency_overrides[get_optional_user] = lambda: CurrentUser(
            user_id="_legacy", role="user"
        )
        with (
            mock.patch("api.auth.VIEWER_CONFIG", dict(_LOCKED_CFG)),
            mock.patch("api.auth.is_multi_user_enabled", return_value=False),
        ):
            resp = TestClient(app).post("/api/albums", json={})
        assert resp.status_code == 403
        assert resp.json()["detail"] == "Edition access required"

    @pytest.mark.parametrize("role,refused", [("user", True), ("admin", False)])
    def test_multi_user_roles(self, role, refused):
        app = create_app()
        user = CurrentUser(user_id="u1", role=role)
        app.dependency_overrides[require_authenticated] = lambda: user
        app.dependency_overrides[get_optional_user] = lambda: user
        with (
            mock.patch("api.auth.VIEWER_CONFIG", dict(_LOCKED_CFG)),
            mock.patch("api.auth.is_multi_user_enabled", return_value=True),
        ):
            resp = TestClient(app, raise_server_exceptions=False).post("/api/albums", json={})
        assert (resp.status_code == 403) is refused


class TestRatingRoutes:
    def test_the_rating_routes_are_require_auth_routes(self):
        found = _routes_requiring(require_auth)
        for route in _RATING_ROUTES:
            assert route in found

    @pytest.mark.parametrize("method,path", _RATING_ROUTES)
    def test_open_install_is_refused_with_the_actionable_detail(self, open_install, method, path):
        resp = TestClient(create_app(), raise_server_exceptions=False).post(
            path, json={"photo_path": "/p.jpg", "rating": 3}
        )
        assert resp.status_code == 403
        assert resp.json()["detail"] == OPEN_DETAIL

    @pytest.mark.parametrize("method,path", _RATING_ROUTES)
    def test_multi_user_regular_user_is_not_refused(self, method, path):
        app = create_app()
        user = CurrentUser(user_id="u1", role="user")
        app.dependency_overrides[require_authenticated] = lambda: user
        with (
            mock.patch("api.auth.VIEWER_CONFIG", dict(_LOCKED_CFG)),
            mock.patch("api.auth.is_multi_user_enabled", return_value=True),
        ):
            resp = TestClient(app, raise_server_exceptions=False).post(
                path, json={"photo_path": "/p.jpg", "rating": 3}
            )
        assert resp.status_code != 403


class TestFaceListingsStayReadable:
    @pytest.mark.parametrize(
        "path", ["/api/photo/faces?path=/nope.jpg", "/api/person/1/faces"]
    )
    def test_open_install_reads_them(self, open_install, path):
        assert TestClient(create_app()).get(path).status_code == 200

    @pytest.mark.parametrize(
        "path", ["/api/photo/faces?path=/nope.jpg", "/api/person/1/faces"]
    )
    def test_locked_install_without_a_session_is_401(self, path):
        with (
            mock.patch("api.auth.VIEWER_CONFIG", {**_LOCKED_CFG, "password": "viewer"}),
            mock.patch("api.auth.is_multi_user_enabled", return_value=False),
        ):
            assert TestClient(create_app()).get(path).status_code == 401

    @pytest.mark.parametrize(
        "path", ["/api/photo/faces?path=/nope.jpg", "/api/person/1/faces"]
    )
    def test_locked_install_viewer_session_without_edition_reads_them(self, path):
        app = create_app()
        user = CurrentUser(user_id="_legacy", role="user")
        app.dependency_overrides[require_authenticated] = lambda: user
        with (
            mock.patch("api.auth.VIEWER_CONFIG", {**_LOCKED_CFG, "password": "viewer"}),
            mock.patch("api.auth.is_multi_user_enabled", return_value=False),
        ):
            assert TestClient(app).get(path).status_code == 200
