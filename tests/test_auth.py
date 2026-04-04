"""Tests for authentication: JWT tokens, password hashing, rate limiting, and login endpoints."""

from datetime import timedelta
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from api import create_app
from api.auth import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
    verify_legacy_password,
    _is_hashed,
    RateLimiter,
)

_AUTH_MODULE = "api.routers.auth"


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


def _make_client():
    return TestClient(create_app())


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

    def test_edition_login_rejected_in_multi_user(self, client):
        with mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=True):
            resp = client.post(
                "/api/auth/edition/login", json={"password": "ed-pw"}
            )
            assert resp.status_code == 400


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
