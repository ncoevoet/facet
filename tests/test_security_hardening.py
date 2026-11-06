"""Tests for the security-hardening batch: body cap, static-token throttling,
docs gating and the Immich payload walk cap."""

from itertools import islice
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api import RequestBodyCapMiddleware, create_app
from api.token_auth import TokenFailureLimiter, require_static_token_throttled

_CAP = RequestBodyCapMiddleware.DEFAULT_MAX_BYTES
_TOO_LARGE = "Request body too large"


@pytest.fixture(scope="module")
def app_client():
    return TestClient(create_app())


# --- RequestBodyCapMiddleware ----------------------------------------------

def test_a_declared_body_over_the_cap_is_refused(app_client):
    resp = app_client.post("/api/auth/login", content=b"x" * (_CAP + 1))
    assert resp.status_code == 413
    assert resp.json()["detail"] == _TOO_LARGE


def test_a_chunked_body_over_the_cap_is_refused_while_it_streams(app_client):
    """No Content-Length: the cap is enforced on the bytes actually received."""
    def chunks():
        for _ in range(_CAP // (1024 * 1024) + 2):
            yield b"x" * (1024 * 1024)

    resp = app_client.post("/api/auth/login", content=chunks())
    assert resp.status_code == 413
    assert resp.json()["detail"] == _TOO_LARGE


def test_a_body_at_the_cap_reaches_the_handler(app_client):
    resp = app_client.post("/api/auth/login", content=b"x" * _CAP)
    assert resp.status_code != 413


@pytest.mark.parametrize("method, path", [
    ("PUT", "/dav/photo.cr3"),
    ("POST", "/api/photo/ai_edits/import"),
    ("POST", "/api/lightroom/import"),
])
def test_routes_with_their_own_streaming_cap_are_exempt(app_client, method, path):
    """WebDAV uploads, the AI-edit import and the Lightroom import allow more than
    10 MB and enforce it themselves; the global cap must not undercut them."""
    resp = app_client.request(method, path, content=b"x" * (_CAP + 1))
    assert not (resp.status_code == 413 and resp.json().get("detail") == _TOO_LARGE)


# --- static-token failure throttling ---------------------------------------

def _request(host="192.0.2.7"):
    return SimpleNamespace(client=SimpleNamespace(host=host))


def _status(limiter, provided, expected=("secret",), host="192.0.2.7"):
    try:
        require_static_token_throttled(_request(host), list(expected), provided, "Test feature", limiter=limiter)
    except HTTPException as ex:
        return ex.status_code, ex.headers
    return 200, None


def test_wrong_tokens_consume_the_budget_until_429():
    limiter = TokenFailureLimiter(max_failures=3, window_seconds=60)
    assert [_status(limiter, "wrong")[0] for _ in range(3)] == [403, 403, 403]
    status, headers = _status(limiter, "secret")
    assert status == 429
    assert headers["Retry-After"] == "60"


def test_successful_and_missing_tokens_never_consume_the_budget():
    limiter = TokenFailureLimiter(max_failures=3, window_seconds=60)
    assert {_status(limiter, "secret")[0] for _ in range(10)} == {200}
    assert {_status(limiter, "")[0] for _ in range(10)} == {401}
    assert _status(limiter, "secret")[0] == 200


def test_a_disabled_feature_answers_404_whatever_the_budget():
    limiter = TokenFailureLimiter(max_failures=2, window_seconds=60)
    for _ in range(2):
        _status(limiter, "wrong")
    assert _status(limiter, "wrong", expected=())[0] == 404


def test_peers_are_keyed_independently():
    limiter = TokenFailureLimiter(max_failures=2, window_seconds=60)
    for _ in range(2):
        _status(limiter, "wrong")
    assert _status(limiter, "secret")[0] == 429
    assert _status(limiter, "secret", host="192.0.2.8")[0] == 200


def test_the_budget_frees_once_the_window_passes():
    now = [0.0]
    limiter = TokenFailureLimiter(max_failures=1, window_seconds=60, clock=lambda: now[0])
    _status(limiter, "wrong")
    assert _status(limiter, "secret")[0] == 429
    now[0] += 61
    assert _status(limiter, "secret")[0] == 200


# --- Immich payload walk cap -----------------------------------------------

class _CountingList(list):
    pulled = 0

    def __iter__(self):
        for entry in super().__iter__():
            _CountingList.pulled += 1
            yield entry


def test_the_asset_walk_stops_pulling_entries_at_the_cap():
    """islice over the generator stops the walk itself, not just the result."""
    from api.routers.immich import _iter_assets
    _CountingList.pulled = 0
    payload = {"assets": _CountingList({"originalPath": f"/p{i}.jpg"} for i in range(500))}
    assert len(list(islice(_iter_assets(payload), 3))) == 3
    assert _CountingList.pulled == 3


# --- API docs gating --------------------------------------------------------

@pytest.mark.parametrize("value, served", [
    ("", False), ("0", False), ("false", False), ("off", False), ("no", False),
    ("1", True), ("true", True), ("yes", True), ("ON", True),
])
def test_the_interactive_docs_follow_the_env_flag(monkeypatch, value, served):
    """Off by default: the docs hand the complete route inventory to anyone who can
    reach the server. Only an explicit yes-value turns them on."""
    monkeypatch.setenv("FACET_ENABLE_API_DOCS", value)
    client = TestClient(create_app())
    expected = 200 if served else 404
    assert client.get("/api/openapi.json").status_code == expected
    assert client.get("/api/docs").status_code == expected
