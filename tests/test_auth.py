"""Tests for authentication: JWT tokens, password hashing, rate limiting, and login endpoints."""

from datetime import timedelta
from unittest import mock

import jwt
import pytest
from fastapi.testclient import TestClient

from api import create_app
from api.auth import (
    AUTH_COOKIE_NAME,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
    verify_legacy_password,
    _is_hashed,
    RateLimiter,
)

_AUTH_MODULE = "api.routers.auth"

# A real edition-gated route (Depends(require_edition)): asserting on a field
# of /api/auth/status only proves what the status payload reports, not what an
# unauthorized caller can actually do.
_EDITION_ENDPOINT = "/api/albums"
_EDITION_BODY = {"name": "regression"}
_INCOMPLETE_EDITION_BODY = {}
_FOREIGN_JWT_SECRET = "other-secret-never-issued-by-this-server"
_UNSIGNED_ALGORITHM = "none"


# ---------------------------------------------------------------------------
# JWT token unit tests
# ---------------------------------------------------------------------------


class TestJWTTokens:
    """Unit tests for create_access_token / decode_access_token."""

    def test_create_and_decode_roundtrip(self):
        payload = {"sub": "alice", "role": "admin", "edition": True}
        token = create_access_token(payload)
        decoded = decode_access_token(token)
        assert decoded is not None
        assert decoded["sub"] == "alice"
        assert decoded["role"] == "admin"
        assert decoded["edition"] is True

    def test_expired_token_returns_none(self):
        token = create_access_token(
            {"sub": "alice"}, expires_delta=timedelta(seconds=-1)
        )
        assert decode_access_token(token) is None

    def test_invalid_token_returns_none(self):
        assert decode_access_token("not-a-jwt") is None
        assert decode_access_token("") is None


# ---------------------------------------------------------------------------
# Password hashing unit tests
# ---------------------------------------------------------------------------


class TestPasswordHashing:
    """Unit tests for hash_password / verify_password."""

    def test_hash_and_verify(self):
        h = hash_password("secret123")
        assert verify_password("secret123", h)

    def test_wrong_password_rejected(self):
        h = hash_password("correct")
        assert not verify_password("wrong", h)

    def test_invalid_stored_hash_returns_false(self):
        assert not verify_password("anything", "not-a-valid-hash")
        assert not verify_password("anything", "")


# ---------------------------------------------------------------------------
# Legacy password verification
# ---------------------------------------------------------------------------


class TestVerifyLegacyPassword:
    """Unit tests for verify_legacy_password and _is_hashed."""

    def test_plaintext_match(self):
        assert verify_legacy_password("hello", "hello")

    def test_plaintext_no_match(self):
        assert not verify_legacy_password("hello", "world")

    def test_hashed_match(self):
        h = hash_password("secret")
        assert verify_legacy_password("secret", h)

    def test_hashed_no_match(self):
        h = hash_password("secret")
        assert not verify_legacy_password("wrong", h)

    def test_empty_stored_returns_false(self):
        assert not verify_legacy_password("anything", "")

    def test_non_ascii_plaintext_match(self):
        assert verify_legacy_password("café123", "café123")

    def test_non_ascii_plaintext_no_match(self):
        assert not verify_legacy_password("wrongpass", "café123")

    def test_is_hashed_detection(self):
        h = hash_password("test")
        assert _is_hashed(h)
        assert not _is_hashed("plaintext")
        assert not _is_hashed("")
        assert not _is_hashed("short:value")


# ---------------------------------------------------------------------------
# Rate limiter unit tests
# ---------------------------------------------------------------------------


class TestRateLimiter:
    """Unit tests for the sliding-window RateLimiter."""

    def test_allows_up_to_max(self):
        rl = RateLimiter(max_attempts=5, window_seconds=60)
        for _ in range(5):
            assert rl.is_allowed("ip1")

    def test_blocks_after_max(self):
        rl = RateLimiter(max_attempts=5, window_seconds=60)
        for _ in range(5):
            rl.is_allowed("ip1")
        assert not rl.is_allowed("ip1")

    def test_different_keys_independent(self):
        rl = RateLimiter(max_attempts=2, window_seconds=60)
        assert rl.is_allowed("a")
        assert rl.is_allowed("a")
        assert not rl.is_allowed("a")
        # Different key still has budget
        assert rl.is_allowed("b")
        assert rl.is_allowed("b")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_limiter():
    """Return a fresh RateLimiter to avoid cross-test interference."""
    return RateLimiter(max_attempts=5, window_seconds=60)


def _make_client(raise_server_exceptions=True):
    return TestClient(create_app(), raise_server_exceptions=raise_server_exceptions)


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def _expired_bearer(**claims):
    """Return an Authorization header carrying an already-expired token."""
    return _bearer(create_access_token(
        {"sub": "_legacy", "role": "user", **claims},
        expires_delta=timedelta(seconds=-1),
    ))


def _foreign_secret_bearer(**claims):
    """A well-formed token signed with a secret this server never issued."""
    return _bearer(jwt.encode(
        {"sub": "_legacy", "role": "user", **claims},
        _FOREIGN_JWT_SECRET, algorithm="HS256",
    ))


def _unsigned_bearer(**claims):
    """An ``alg: none`` token — the classic signature-stripping forgery."""
    return _bearer(jwt.encode(
        {"sub": "_legacy", "role": "user", **claims},
        key=None, algorithm=_UNSIGNED_ALGORITHM,
    ))


_REJECTED_BEARERS = [_expired_bearer, _foreign_secret_bearer, _unsigned_bearer]
_REJECTED_BEARER_IDS = ["expired", "wrong_secret", "alg_none"]


# ---------------------------------------------------------------------------
# No-password mode (HTTP)
# ---------------------------------------------------------------------------


class TestNoPasswordMode:
    """Login when no viewer password is set (open access)."""

    @pytest.fixture(autouse=True)
    def _patch(self):
        viewer_cfg = {"password": "", "edition_password": "", "features": {}}
        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", viewer_cfg),
            mock.patch("api.auth.VIEWER_CONFIG", viewer_cfg),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=False),
            mock.patch("api.auth.is_multi_user_enabled", return_value=False),
            mock.patch(f"{_AUTH_MODULE}._login_limiter", _fresh_limiter()),
        ):
            yield

    @pytest.fixture()
    def client(self):
        return _make_client()

    def test_login_no_password_returns_token(self, client):
        resp = client.post("/api/auth/login", json={"password": ""})
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"

    def test_auth_status_shows_authenticated(self, client):
        resp = client.get("/api/auth/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["authenticated"] is True

    def test_expired_bearer_does_not_lock_the_install_out(self, client):
        """A 48h-old token must not be worse than sending no token at all."""
        resp = client.get("/api/auth/status", headers=_expired_bearer())
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is True

    def test_garbage_bearer_does_not_lock_the_install_out(self, client):
        resp = client.get(
            "/api/auth/status", headers={"Authorization": "Bearer not-a-jwt"}
        )
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is True

    def test_expired_bearer_reaches_a_state_changing_route(self, client):
        """POST has no cookie fallback, so only the Bearer path can save it."""
        resp = client.post("/api/auth/edition/logout", headers=_expired_bearer())
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Legacy password mode (HTTP)
# ---------------------------------------------------------------------------


class TestLegacyPasswordMode:
    """Login with a legacy viewer password (single-user)."""

    @pytest.fixture(autouse=True)
    def _patch(self):
        viewer_cfg = {"password": "correct-pw", "edition_password": "", "features": {}}
        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", viewer_cfg),
            mock.patch("api.auth.VIEWER_CONFIG", viewer_cfg),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=False),
            mock.patch("api.auth.is_multi_user_enabled", return_value=False),
            mock.patch(f"{_AUTH_MODULE}._login_limiter", _fresh_limiter()),
            mock.patch(f"{_AUTH_MODULE}.upgrade_legacy_password"),
        ):
            yield

    @pytest.fixture()
    def client(self):
        return _make_client()

    def test_login_correct_password(self, client):
        resp = client.post("/api/auth/login", json={"password": "correct-pw"})
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body

    def test_login_wrong_password(self, client):
        resp = client.post("/api/auth/login", json={"password": "wrong"})
        assert resp.status_code == 401

    def test_login_rate_limited(self, client):
        limiter = RateLimiter(max_attempts=5, window_seconds=60)
        with mock.patch(f"{_AUTH_MODULE}._login_limiter", limiter):
            for _ in range(5):
                client.post("/api/auth/login", json={"password": "wrong"})
            resp = client.post("/api/auth/login", json={"password": "wrong"})
            assert resp.status_code == 429

    def test_expired_bearer_stays_unauthenticated(self, client):
        """The open-install fallback must not widen to a locked deployment."""
        resp = client.get("/api/auth/status", headers=_expired_bearer())
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is False


# ---------------------------------------------------------------------------
# HttpOnly auth cookie (image/GET fallback on locked deployments)
# ---------------------------------------------------------------------------


class TestAuthCookie:
    """Login mirrors the JWT in an HttpOnly cookie; GETs accept it, POSTs don't."""

    @pytest.fixture(autouse=True)
    def _patch(self):
        viewer_cfg = {"password": "correct-pw", "edition_password": "", "features": {}}
        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", viewer_cfg),
            mock.patch("api.auth.VIEWER_CONFIG", viewer_cfg),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=False),
            mock.patch("api.auth.is_multi_user_enabled", return_value=False),
            mock.patch(f"{_AUTH_MODULE}._login_limiter", _fresh_limiter()),
            mock.patch(f"{_AUTH_MODULE}.upgrade_legacy_password"),
        ):
            yield

    @pytest.fixture()
    def client(self):
        return _make_client()

    def test_login_sets_httponly_cookie(self, client):
        resp = client.post("/api/auth/login", json={"password": "correct-pw"})
        assert resp.status_code == 200
        set_cookie = resp.headers.get("set-cookie", "")
        assert AUTH_COOKIE_NAME in set_cookie
        assert "HttpOnly" in set_cookie

    def test_cookie_authenticates_get(self, client):
        """An <img>-style request (cookie only, no Bearer) is authenticated."""
        token = create_access_token({"sub": "_legacy", "role": "user"})
        client.cookies.set(AUTH_COOKIE_NAME, token)
        resp = client.get("/api/auth/status")
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is True

    def test_anonymous_get_stays_anonymous(self, client):
        resp = client.get("/api/auth/status")
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is False

    def test_cookie_does_not_authenticate_post(self, client):
        """State-changing routes stay Bearer-only (no CSRF surface)."""
        token = create_access_token({"sub": "_legacy", "role": "user", "edition": True})
        client.cookies.set(AUTH_COOKIE_NAME, token)
        resp = client.post("/api/auth/edition/logout")
        assert resp.status_code == 401

    def test_invalid_cookie_is_anonymous_not_500(self, client):
        client.cookies.set(AUTH_COOKIE_NAME, "not-a-jwt")
        resp = client.get("/api/auth/status")
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is False

    def test_logout_expires_cookie(self, client):
        resp = client.post("/api/auth/logout")
        assert resp.status_code == 200
        set_cookie = resp.headers.get("set-cookie", "")
        assert AUTH_COOKIE_NAME in set_cookie


# ---------------------------------------------------------------------------
# Edition password mode (HTTP)
# ---------------------------------------------------------------------------


class TestEditionPasswordMode:
    """Edition login with a separate edition password."""

    @pytest.fixture(autouse=True)
    def _patch(self):
        viewer_cfg = {"password": "", "edition_password": "ed-pw", "features": {}}
        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", viewer_cfg),
            mock.patch("api.auth.VIEWER_CONFIG", viewer_cfg),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=False),
            mock.patch("api.auth.is_multi_user_enabled", return_value=False),
            mock.patch(f"{_AUTH_MODULE}._login_limiter", _fresh_limiter()),
            mock.patch(f"{_AUTH_MODULE}.upgrade_legacy_password"),
        ):
            yield

    @pytest.fixture()
    def client(self):
        return _make_client()

    def test_edition_login_correct(self, client):
        resp = client.post(
            "/api/auth/edition/login", json={"password": "ed-pw"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body

    def test_edition_login_wrong(self, client):
        resp = client.post(
            "/api/auth/edition/login", json={"password": "wrong"}
        )
        assert resp.status_code == 401

    @pytest.mark.parametrize("make_headers", _REJECTED_BEARERS, ids=_REJECTED_BEARER_IDS)
    def test_unusable_bearer_keeps_access_but_drops_edition(self, client, make_headers):
        """The reported install: no viewer password, edition password set."""
        resp = client.get("/api/auth/status", headers=make_headers(edition=True))
        assert resp.status_code == 200
        body = resp.json()
        assert body["authenticated"] is True
        assert body["edition_authenticated"] is False

    @pytest.mark.parametrize("make_headers", _REJECTED_BEARERS, ids=_REJECTED_BEARER_IDS)
    def test_unusable_bearer_is_refused_by_a_real_edition_route(self, client, make_headers):
        """A forged or stale ``edition`` claim must not survive as edition
        access on the route that actually mutates state."""
        resp = client.post(
            _EDITION_ENDPOINT, json=_EDITION_BODY, headers=make_headers(edition=True)
        )
        assert resp.status_code == 403

    def test_edition_login_rejected_in_multi_user(self, client):
        with mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=True):
            resp = client.post(
                "/api/auth/edition/login", json={"password": "ed-pw"}
            )
            assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Unparseable scoring_config.json (fail closed)
# ---------------------------------------------------------------------------


@pytest.fixture()
def load_config_from():
    """Drive the real ``api.config`` parse-failure flag from a chosen path.

    Returns a callable taking the path to read and reporting whether the parse
    failure was recorded. The previous flag value is always restored: leaking
    an armed flag would lock every later test out of the open-install path.
    """
    import api.config as api_config

    previous = api_config._config_load_failed

    def _load(path):
        with mock.patch.object(api_config, "_CONFIG_PATH", str(path)):
            api_config._read_config()
        return api_config.config_load_failed()

    yield _load
    api_config._config_load_failed = previous


class TestUnparseableConfigFailsClosed:
    """A config that EXISTS but does not parse must lock the install down.

    The empty config it degrades to carries neither ``password`` nor
    ``edition_password``, so it used to be indistinguishable from a
    deliberately open install and unlocked every edition route. A genuinely
    absent config is a different thing — a fresh, never-configured install
    that is legitimately open — and must keep working.
    """

    CORRUPT_CONFIG = '{"viewer": {"edition_password": "ed-pw"'

    @pytest.fixture(autouse=True)
    def _patch(self):
        viewer_cfg = {"password": "", "edition_password": "", "features": {}}
        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", viewer_cfg),
            mock.patch("api.auth.VIEWER_CONFIG", viewer_cfg),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=False),
            mock.patch("api.auth.is_multi_user_enabled", return_value=False),
        ):
            yield

    def _corrupt_config(self, tmp_path):
        path = tmp_path / "scoring_config.json"
        path.write_text(self.CORRUPT_CONFIG)
        return path

    def test_corrupt_config_is_recorded_as_a_load_failure(self, tmp_path, load_config_from):
        assert load_config_from(self._corrupt_config(tmp_path)) is True

    def test_absent_config_is_not_a_load_failure(self, tmp_path, load_config_from):
        assert load_config_from(tmp_path / "never_configured.json") is False

    def test_corrupt_config_forbids_an_authenticated_edition_route(self, tmp_path, load_config_from):
        load_config_from(self._corrupt_config(tmp_path))
        client = _make_client(raise_server_exceptions=False)

        resp = client.post(
            _EDITION_ENDPOINT,
            json=_EDITION_BODY,
            headers={"Authorization": f"Bearer {create_access_token({'sub': '_legacy', 'role': 'user'})}"},
        )
        assert resp.status_code == 403

    def test_corrupt_config_rejects_an_anonymous_edition_route(self, tmp_path, load_config_from):
        load_config_from(self._corrupt_config(tmp_path))
        client = _make_client(raise_server_exceptions=False)

        resp = client.post(_EDITION_ENDPOINT, json=_EDITION_BODY)
        assert resp.status_code == 401

    def test_absent_config_keeps_the_open_install_open(self, tmp_path, load_config_from):
        """The same request, with the flag disarmed, reaches the handler: a 422
        on an incomplete body proves the edition gate was passed, without
        writing an album."""
        load_config_from(tmp_path / "never_configured.json")
        client = _make_client(raise_server_exceptions=False)

        resp = client.post(_EDITION_ENDPOINT, json=_INCOMPLETE_EDITION_BODY)
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Multi-user mode (HTTP)
# ---------------------------------------------------------------------------


class TestMultiUserMode:
    """Login in multi-user RBAC mode."""

    _USER_CFG = {
        "password_hash": hash_password("hunter2"),
        "role": "admin",
        "display_name": "Alice",
    }

    @pytest.fixture(autouse=True)
    def _patch(self):
        viewer_cfg = {"password": "", "edition_password": "", "features": {}}

        def _get_user(username):
            if username == "alice":
                return self._USER_CFG
            return None

        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", viewer_cfg),
            mock.patch("api.auth.VIEWER_CONFIG", viewer_cfg),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=True),
            mock.patch("api.auth.is_multi_user_enabled", return_value=True),
            mock.patch(f"{_AUTH_MODULE}.get_user_config", side_effect=_get_user),
            mock.patch(f"{_AUTH_MODULE}._login_limiter", _fresh_limiter()),
        ):
            yield

    @pytest.fixture()
    def client(self):
        return _make_client()

    def test_login_success(self, client):
        resp = client.post(
            "/api/auth/login",
            json={"username": "alice", "password": "hunter2"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert body["user"]["user_id"] == "alice"
        assert body["user"]["role"] == "admin"

    def test_login_wrong_password(self, client):
        resp = client.post(
            "/api/auth/login",
            json={"username": "alice", "password": "wrong"},
        )
        assert resp.status_code == 401

    def test_login_unknown_user(self, client):
        resp = client.post(
            "/api/auth/login",
            json={"username": "nobody", "password": "whatever"},
        )
        assert resp.status_code == 401

    def test_login_missing_username(self, client):
        resp = client.post(
            "/api/auth/login",
            json={"password": "hunter2"},
        )
        assert resp.status_code == 400

    def test_expired_bearer_stays_unauthenticated(self, client):
        """Multi-user has no open-install fallback, empty password or not."""
        resp = client.get(
            "/api/auth/status", headers=_expired_bearer(sub="alice", role="admin")
        )
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is False
