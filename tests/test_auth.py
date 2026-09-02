"""Tests for authentication: JWT tokens, password hashing, rate limiting, and login endpoints."""

import json
import logging
import os
import shutil
import stat
import sys
from datetime import timedelta
from pathlib import Path
from unittest import mock

import jwt
import pytest
from fastapi.testclient import TestClient

from api import create_app
from api.auth import (
    AUTH_COOKIE_NAME,
    EDITION_GENERATION_CLAIM,
    VIEWER_GENERATION_CLAIM,
    create_access_token,
    decode_access_token,
    hash_password,
    password_generation,
    upgrade_legacy_password,
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

    def test_token_carries_both_password_generations(self):
        decoded = decode_access_token(create_access_token({"sub": "alice"}))
        assert decoded[VIEWER_GENERATION_CLAIM] == password_generation("password")
        assert decoded[EDITION_GENERATION_CLAIM] == password_generation("edition_password")

    @pytest.mark.parametrize("claim", [VIEWER_GENERATION_CLAIM, EDITION_GENERATION_CLAIM])
    def test_token_without_a_generation_claim_is_stale(self, claim):
        """No shim for claim-less tokens: accepting them would be exactly the
        hole the claims close."""
        payload = decode_access_token(create_access_token({"sub": "alice"}))
        del payload[claim]
        from api.auth import JWT_ALGORITHM
        from api.config import JWT_SECRET

        assert decode_access_token(jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)) is None

    def test_encode_and_decode_pick_up_a_rotated_secret_without_reimport(self):
        """DEBT A6#8: api.auth used to bind JWT_SECRET at import time, so a
        rotated api.config.JWT_SECRET (what reload_config() actually mutates)
        never took effect for this process -- both signing and verification
        kept using the stale value forever. They must read it through the
        module fresh on every call, like frame._secret() does."""
        import api.config as api_config

        original_secret = api_config.JWT_SECRET
        try:
            token_under_old_secret = create_access_token({"sub": "u1"})
            assert decode_access_token(token_under_old_secret) is not None

            api_config.JWT_SECRET = "rotated-secret-does-not-match-original"

            # A token signed before rotation must fail verification now...
            assert decode_access_token(token_under_old_secret) is None

            # ...and a token minted after rotation must both sign AND verify
            # under the new secret.
            token_under_new_secret = create_access_token({"sub": "u1"})
            payload = decode_access_token(token_under_new_secret)
            assert payload is not None
            assert payload["sub"] == "u1"
        finally:
            api_config.JWT_SECRET = original_secret


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
# Password rotation ages tokens out (FINDING 32)
# ---------------------------------------------------------------------------


_REPO_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "scoring_config.default.json"

_VIEWER_PASSWORD = "viewer-pw"
_EDITION_PASSWORD = "ed-pw"
_ROTATED_PASSWORD = "rotated-pw"


class TestPasswordRotationRevokesTokens:
    """A JWT is bound to the passwords stored when it was minted.

    Reproduces the reported probe end to end against the real app: nothing
    invalidates a token server-side, so before this binding a token kept
    performing edition writes for its full 48h across a logout, an edition
    logout, and an edition-password change. Each test drives a real login over
    HTTP, rewrites the stored password on disk, reloads, and re-issues the SAME
    bearer against a route that actually mutates state.
    """

    @pytest.fixture()
    def locked_install(self, tmp_path):
        """A real, locked config (seeded from the shipped defaults) this process reads and reloads.

        Passwords are stored pre-hashed so ``upgrade_legacy_password`` stays
        inert and the file changes only when a test rotates it.
        """
        import api.config as api_config

        config_path = tmp_path / "scoring_config.json"
        shutil.copy2(_REPO_CONFIG_PATH, config_path)

        def rotate(**passwords):
            config = json.loads(config_path.read_text())
            for key, value in passwords.items():
                config['viewer'][key] = hash_password(value)
            config_path.write_text(json.dumps(config))
            api_config.reload_config()

        with (
            mock.patch.object(api_config, "_CONFIG_PATH", str(config_path)),
            mock.patch(f"{_AUTH_MODULE}._login_limiter", _fresh_limiter()),
        ):
            rotate(password=_VIEWER_PASSWORD, edition_password=_EDITION_PASSWORD)
            yield rotate
        api_config.reload_config()

    def _edition_bearer(self, client):
        resp = client.post("/api/auth/edition/login", json={"password": _EDITION_PASSWORD})
        assert resp.status_code == 200
        return _bearer(resp.json()["access_token"])

    def test_edition_write_works_before_any_rotation(self, locked_install):
        client = _make_client(raise_server_exceptions=False)
        headers = self._edition_bearer(client)

        resp = client.post(_EDITION_ENDPOINT, json=_EDITION_BODY, headers=headers)
        assert resp.status_code == 200

    def test_rotating_the_edition_password_kills_edition_writes(self, locked_install):
        client = _make_client(raise_server_exceptions=False)
        headers = self._edition_bearer(client)
        before = client.post(_EDITION_ENDPOINT, json=_EDITION_BODY, headers=headers)

        locked_install(edition_password=_ROTATED_PASSWORD)
        after = client.post(_EDITION_ENDPOINT, json=_EDITION_BODY, headers=headers)

        assert (before.status_code, after.status_code) == (200, 403)

    def test_rotating_the_edition_password_keeps_the_session(self, locked_install):
        """Edition rights are revoked everywhere without logging anyone out."""
        client = _make_client(raise_server_exceptions=False)
        headers = self._edition_bearer(client)

        locked_install(edition_password=_ROTATED_PASSWORD)
        resp = client.get("/api/auth/status", headers=headers)

        assert resp.status_code == 200
        assert resp.json()["authenticated"] is True
        assert resp.json()["edition_authenticated"] is False

    def test_rotating_the_viewer_password_ends_the_session(self, locked_install):
        client = _make_client(raise_server_exceptions=False)
        resp = client.post("/api/auth/login", json={"password": _VIEWER_PASSWORD})
        assert resp.status_code == 200
        headers = _bearer(resp.json()["access_token"])
        before = client.get("/api/auth/status", headers=headers)

        locked_install(password=_ROTATED_PASSWORD)
        after = client.get("/api/auth/status", headers=headers)

        assert (before.json()["authenticated"], after.json()["authenticated"]) == (True, False)

    def test_rotating_the_viewer_password_kills_edition_writes(self, locked_install):
        client = _make_client(raise_server_exceptions=False)
        headers = self._edition_bearer(client)
        before = client.post(_EDITION_ENDPOINT, json=_EDITION_BODY, headers=headers)

        locked_install(password=_ROTATED_PASSWORD)
        after = client.post(_EDITION_ENDPOINT, json=_EDITION_BODY, headers=headers)

        assert (before.status_code, after.status_code) == (200, 401)

    def test_cookie_session_dies_with_the_viewer_password(self, locked_install):
        """The cookie mirrors the same JWT, so it must age out with it."""
        client = _make_client(raise_server_exceptions=False)
        assert client.post("/api/auth/login", json={"password": _VIEWER_PASSWORD}).status_code == 200
        before = client.get("/api/auth/status")

        locked_install(password=_ROTATED_PASSWORD)
        after = client.get("/api/auth/status")

        assert (before.json()["authenticated"], after.json()["authenticated"]) == (True, False)

    def test_logout_does_not_revoke_the_bearer(self, locked_install):
        """Out of scope by design: individual revocation needs server-side
        session state. The docstrings and the client say so; this pins it."""
        client = _make_client(raise_server_exceptions=False)
        headers = self._edition_bearer(client)

        assert client.post("/api/auth/logout", headers=headers).status_code == 200
        resp = client.post(_EDITION_ENDPOINT, json=_EDITION_BODY, headers=headers)

        assert resp.status_code == 200


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


_PLAINTEXT_PASSWORD = "legacy-plaintext-pw"
_CONFIG_GROUP_MODE = 0o664
_BACKUP_OWNER_ONLY_MODE = 0o600


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits do not apply on Windows")
class TestPasswordUpgradeBackupIsOwnerOnly:
    """The pre-upgrade backup is the single most sensitive file this project writes.

    It is taken while the config still holds the PLAINTEXT password, seconds
    after a successful login, and it survives as long as the operator keeps it.
    ``shutil.copy2`` put those bytes on disk at the config's own mode first —
    0664 under a default umask — and only tightened them with a following
    ``chmod``, so every local account had a window to read the password. The
    upgrade now goes through the shared owner-only backup primitive, which
    creates the destination at 0600 and re-modes a reused name while it is
    still empty.
    """

    def _plaintext_install(self, tmp_path):
        config_path = tmp_path / "scoring_config.json"
        config_path.write_text(json.dumps({"viewer": {"password": _PLAINTEXT_PASSWORD}}))
        os.chmod(config_path, _CONFIG_GROUP_MODE)
        return config_path

    def _upgrade(self, config_path):
        import api.config as api_config

        with (
            mock.patch.object(api_config, "_CONFIG_PATH", str(config_path)),
            mock.patch.object(api_config, "reload_config", lambda: None),
        ):
            upgrade_legacy_password("password", _PLAINTEXT_PASSWORD)

    def test_the_backup_holding_the_plaintext_is_owner_only(self, tmp_path):
        config_path = self._plaintext_install(tmp_path)

        self._upgrade(config_path)

        backup = Path(f"{config_path}.backup")
        assert _PLAINTEXT_PASSWORD in backup.read_text(), "this IS the sensitive copy"
        assert _is_hashed(json.loads(config_path.read_text())["viewer"]["password"])
        assert stat.S_IMODE(os.stat(backup).st_mode) == _BACKUP_OWNER_ONLY_MODE

    def test_the_config_keeps_its_own_mode(self, tmp_path):
        """Only the backup is restricted: a co-deployed CLI still reads the config."""
        config_path = self._plaintext_install(tmp_path)

        self._upgrade(config_path)

        assert stat.S_IMODE(os.stat(config_path).st_mode) == _CONFIG_GROUP_MODE

    def test_the_plaintext_never_lands_at_a_looser_mode_first(self, tmp_path):
        """The window ``copy2`` + ``chmod`` left, pinned at the moment of the copy.

        The backup name already exists at 0664 here — every install upgraded
        from an older Facet has exactly that — so the creation mode alone would
        not help: the mode is asserted as the first byte is written.
        """
        config_path = self._plaintext_install(tmp_path)
        backup_path = Path(f"{config_path}.backup")
        backup_path.write_text("stale")
        os.chmod(backup_path, _CONFIG_GROUP_MODE)
        modes_while_writing = []
        real_copyfileobj = shutil.copyfileobj

        def _recording_copyfileobj(source_file, destination_file, *args, **kwargs):
            modes_while_writing.append(stat.S_IMODE(os.stat(backup_path).st_mode))
            return real_copyfileobj(source_file, destination_file, *args, **kwargs)

        with mock.patch("api.config_writes.shutil.copyfileobj", _recording_copyfileobj):
            self._upgrade(config_path)

        assert modes_while_writing == [_BACKUP_OWNER_ONLY_MODE]
        assert _PLAINTEXT_PASSWORD in backup_path.read_text()


class TestUnparseableConfigStaysLocked:
    """An unparseable config must not become an open install via the viewer defaults.

    ``_read_config`` returns ``{}`` for a config that exists but cannot be
    parsed, and ``load_viewer_config`` backfills that from the SHIPPED defaults
    -- which carry an empty ``viewer.edition_password``, the value that means
    "no lock". The gate that keeps this safe is ``config_load_failed()``, which
    ``_is_open_install`` short-circuits on, so it is the thing to pin: while the
    backfill was a stale hardcoded dict this happened to be belt-and-braces, and
    it stopped being so the moment the defaults became the real ones.
    """

    def _run(self, tmp_path, config_text):
        import subprocess
        cfg = tmp_path / "scoring_config.json"
        cfg.write_text(config_text)
        code = (
            "import api.config as ac, api.auth as auth;"
            "print(ac.config_load_failed(),"
            " repr(ac.VIEWER_CONFIG.get('edition_password', '<missing>')),"
            " auth._is_open_install(auth.EDITION_PASSWORD_KEY),"
            " auth.CurrentUser().is_edition)"
        )
        env = {
            **os.environ,
            "FACET_CONFIG": str(cfg),
            "PYTHONPATH": str(Path(__file__).resolve().parent.parent),
            "FACET_JWT_SECRET": "x" * 40,
        }
        res = subprocess.run([sys.executable, "-c", code], env=env,
                             capture_output=True, text=True)
        assert res.returncode == 0, res.stderr[-2000:]
        return res.stdout.split()

    def test_an_unparseable_config_grants_no_edition_rights(self, tmp_path):
        failed, password, open_install, is_edition = self._run(tmp_path, "{ not json")
        assert failed == "True", "an unparseable config must be recorded as failed"
        # The backfill legitimately supplies the shipped empty password...
        assert password == "''"
        # ...and it must NOT be read as "this install has no lock".
        assert open_install == "False"
        assert is_edition == "False"

    def test_a_valid_empty_override_still_reads_the_shipped_defaults(self, tmp_path):
        """The contrast case: {} is a healthy install, not a failed one."""
        failed, _password, _open_install, _is_edition = self._run(tmp_path, "{}")
        assert failed == "False"


class TestConfigFailureStaysLocked:
    """A config Facet cannot read must not present as an install with no lock.

    Three ways this went wrong, each reproduced before it was fixed:
    the login endpoint read the password VALUE instead of asking
    ``_is_open_install``; ``reload_config`` cleared ``VIEWER_CONFIG`` before
    rebuilding it, so a raising rebuild left an empty dict that reads as "no
    password"; and a ``viewer`` block of the wrong TYPE degraded to "no viewer
    settings", which backfills the shipped defaults and their empty passwords.
    """

    def _probe(self, tmp_path, corrupt_to, script):
        import subprocess
        cfg = tmp_path / "scoring_config.json"
        cfg.write_text(json.dumps(
            {"viewer": {"password": "PW", "edition_password": "EDITION-PW"}}))
        preamble = (
            "import json, api.config as ac, api.auth as auth\n"
            f"open(ac._CONFIG_PATH, 'w').write({corrupt_to!r})\n"
        )
        env = {
            **os.environ,
            "FACET_CONFIG": str(cfg),
            "PYTHONPATH": str(Path(__file__).resolve().parent.parent),
            "FACET_JWT_SECRET": "q" * 40,
        }
        res = subprocess.run([sys.executable, "-c", preamble + script], env=env,
                             capture_output=True, text=True)
        assert res.returncode == 0, res.stderr[-2000:]
        return res.stdout.split()

    def test_a_reload_onto_a_broken_config_does_not_open_the_install(self, tmp_path):
        out = self._probe(tmp_path, "[1, 2, 3]", (
            "ac.reload_config()\n"
            "print(auth._is_open_install(auth.VIEWER_PASSWORD_KEY),"
            " auth._is_open_install(auth.EDITION_PASSWORD_KEY),"
            " auth.CurrentUser().is_edition, bool(ac.VIEWER_CONFIG))\n"
        ))
        assert out[:3] == ["False", "False", "False"], out
        # and the dict is never left empty, which is what read as "no password"
        assert out[3] == "True"

    def test_a_viewer_block_of_the_wrong_type_is_a_load_failure(self, tmp_path):
        """It carries the passwords, so it cannot degrade to "no settings"."""
        out = self._probe(tmp_path, '{"viewer": []}', (
            "ac.reload_config()\n"
            "print(ac.config_load_failed(),"
            " auth._is_open_install(auth.VIEWER_PASSWORD_KEY),"
            " auth._is_open_install(auth.EDITION_PASSWORD_KEY))\n"
        ))
        assert out == ["True", "False", "False"], out

    def test_login_with_an_empty_password_is_refused_when_the_config_failed(self, tmp_path):
        """The app boots healthy and the config breaks under it — the reachable
        shape, since a config already broken at boot stops import instead."""
        import subprocess
        cfg = tmp_path / "scoring_config.json"
        cfg.write_text(json.dumps({"viewer": {"password": "PW"}}))
        script = (
            "import json, api.config as ac\n"
            "from fastapi.testclient import TestClient\n"
            "from api import create_app\n"
            "c = TestClient(create_app())\n"
            "before = c.post('/api/auth/login', json={'password': ''}).status_code\n"
            "json.dump([1, 2, 3], open(ac._CONFIG_PATH, 'w'))\n"
            "ac.reload_config()\n"
            "after = c.post('/api/auth/login', json={'password': ''}).status_code\n"
            "print(before, after)\n"
        )
        env = {
            **os.environ,
            "FACET_CONFIG": str(cfg),
            "PYTHONPATH": str(Path(__file__).resolve().parent.parent),
            "FACET_JWT_SECRET": "q" * 40,
        }
        res = subprocess.run([sys.executable, "-c", script], env=env,
                             capture_output=True, text=True)
        assert res.returncode == 0, res.stderr[-2000:]
        before, after = res.stdout.split()
        assert before == "401", "a locked install must reject an empty password"
        # It used to mint a session here (200 + a usable JWT for sub=_anonymous).
        assert after == "503", f"empty password must not mint a session, got {after}"

    def test_features_fail_closed_when_the_config_could_not_be_read(self, tmp_path):
        """Auth is not the only gate VIEWER_CONFIG feeds."""
        out = self._probe(tmp_path, "[1, 2, 3]", (
            "ac.reload_config()\n"
            "f = ac.VIEWER_CONFIG.get('features', {})\n"
            "print(bool(f), any(f.values()))\n"
        ))
        assert out == ["True", "False"], f"no feature may be enabled, got {out}"

    def test_a_raising_rebuild_never_leaves_viewer_config_empty(self, tmp_path):
        """Directly exercises the build-before-swap in ``reload_config``.

        The other tests here cover the OUTCOME (the install stays locked) but no
        longer reach this mechanism: the ``viewer``-block validation means
        ``load_viewer_config`` cannot raise on a malformed config any more. So
        force it to raise, which is what the ordering has to survive — an empty
        ``VIEWER_CONFIG`` reads as "no password" to ``_is_open_install``.
        """
        import subprocess
        cfg = tmp_path / "scoring_config.json"
        cfg.write_text(json.dumps({"viewer": {"password": "PW",
                                              "edition_password": "EDITION-PW"}}))
        script = (
            "import api.config as ac, api.auth as auth\n"
            "def boom(*a, **k):\n"
            "    raise RuntimeError('rebuild failed')\n"
            "ac.load_viewer_config = boom\n"
            "try:\n"
            "    ac.reload_config()\n"
            "except RuntimeError:\n"
            "    pass\n"
            "print(bool(ac.VIEWER_CONFIG),"
            " auth._is_open_install(auth.VIEWER_PASSWORD_KEY),"
            " auth._is_open_install(auth.EDITION_PASSWORD_KEY))\n"
        )
        env = {
            **os.environ,
            "FACET_CONFIG": str(cfg),
            "PYTHONPATH": str(Path(__file__).resolve().parent.parent),
            "FACET_JWT_SECRET": "q" * 40,
        }
        res = subprocess.run([sys.executable, "-c", script], env=env,
                             capture_output=True, text=True)
        assert res.returncode == 0, res.stderr[-2000:]
        populated, open_pw, open_edition = res.stdout.split()
        assert populated == "True", "a raising rebuild must not empty VIEWER_CONFIG"
        assert open_pw == "False" and open_edition == "False"


class TestEditionLoginReportsAnUnreadableConfig:
    """An empty ``edition_password`` means two different things here too.

    ``/api/auth/login`` was taught to answer 503 rather than "invalid password"
    when the config could not be read; ``/api/auth/edition/login`` was not, so
    it answered 401 in the same state — and the client maps only 5xx to
    'unavailable', leaving the edition dialog saying the password was wrong.
    """

    def test_an_unreadable_config_answers_503(self):
        import api.auth as api_auth

        with mock.patch.object(api_auth, "config_load_failed", lambda: True), \
             mock.patch.dict(api_auth.VIEWER_CONFIG, {"edition_password": ""}), \
             mock.patch.object(api_auth, "is_multi_user_enabled", lambda: False):
            client = TestClient(create_app())
            res = client.post("/api/auth/edition/login", json={"password": "anything"})

        assert res.status_code == 503
        assert "Configuration could not be read" in res.json()["detail"]

    def test_a_deliberately_open_install_still_answers_401(self):
        """The other half: no edition gate configured is not a server fault."""
        import api.auth as api_auth

        with mock.patch.object(api_auth, "config_load_failed", lambda: False), \
             mock.patch.dict(api_auth.VIEWER_CONFIG, {"edition_password": ""}), \
             mock.patch.object(api_auth, "is_multi_user_enabled", lambda: False):
            client = TestClient(create_app())
            res = client.post("/api/auth/edition/login", json={"password": "anything"})

        assert res.status_code == 401


class TestAPublishedPasswordNeverAuthenticates:
    """`user` and `admin` shipped in this project's own tracked config.

    scoring_config.json carried ``viewer.password`` = ``user`` and
    ``viewer.edition_password`` = ``admin`` in 24 commits between 2026-02-14
    and 2026-03-16. Every clone taken in that window got them, and an install
    that never changed them is guarded by a value anyone can read out of the
    public history -- so accepting it authenticates the whole internet.

    The share secrets of that same era are already refused by
    ``_BURNED_SECRET_DIGESTS``; the passwords sitting beside them in the same
    file had no equivalent check. They stay a SEPARATE list because the two are
    handled oppositely: a burned secret is silently regenerated, which a
    password cannot be.
    """

    def test_the_published_viewer_password_is_refused(self):
        from api.auth import verify_legacy_password

        assert verify_legacy_password("user", "user") is False

    def test_the_published_edition_password_is_refused(self):
        from api.auth import verify_legacy_password

        assert verify_legacy_password("admin", "admin") is False

    def test_an_ordinary_plaintext_password_still_works(self):
        """The refusal must be the two published values, not plaintext at all --
        hashing on first login is the documented upgrade path."""
        from api.auth import verify_legacy_password

        assert verify_legacy_password("hunter2", "hunter2") is True
        assert verify_legacy_password("wrong", "hunter2") is False

    def test_typing_a_published_value_against_another_password_just_fails(self):
        """Only the STORED side is checked. Someone typing "admin" at an install
        whose password is something else must fail the ordinary way."""
        from api.auth import verify_legacy_password

        assert verify_legacy_password("admin", "hunter2") is False

    def test_a_hashed_password_is_never_treated_as_published(self):
        from api.auth import hash_password, verify_legacy_password

        stored = hash_password("admin")
        assert verify_legacy_password("admin", stored) is True

    def test_the_startup_check_reports_it_as_an_error_not_a_reassurance(self, caplog):
        """"will be hashed on next successful login" is wrong twice over here:
        there will be no successful login, and hashing a published value would
        not have protected anything."""
        from api.auth import check_legacy_password_warnings

        with mock.patch.dict("api.auth.VIEWER_CONFIG", {"password": "user", "edition_password": ""}):
            with caplog.at_level(logging.ERROR, logger="api.auth"):
                check_legacy_password_warnings()

        assert any("public git history" in r.getMessage() for r in caplog.records)
        assert not any("will be hashed" in r.getMessage() for r in caplog.records)
