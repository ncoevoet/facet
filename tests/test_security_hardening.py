"""Tests for the security-hardening batch: body cap, static-token throttling,
docs gating and the Immich payload walk cap."""

import asyncio
import os
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api import create_app
from api.token_auth import TokenFailureLimiter, require_static_token_throttled


# --- RequestBodyCapMiddleware (B62) ----------------------------------------

def _dispatch(path, content_length, method="POST"):
    from api import RequestBodyCapMiddleware
    from starlette.responses import PlainTextResponse

    reached = {"n": 0}

    async def call_next(request):
        reached["n"] += 1
        return PlainTextResponse("downstream")

    request = SimpleNamespace(
        method=method, url=SimpleNamespace(path=path),
        headers={"content-length": str(content_length)} if content_length is not None else {},
    )
    middleware = RequestBodyCapMiddleware(app=None, max_bytes=10 * 1024 * 1024)
    # asyncio.run: the test env has no ambient event loop (xdist workers and
    # fresh threads never do), and get_event_loop() would raise there.
    response = asyncio.run(middleware.dispatch(request, call_next))
    return response, reached["n"]


def test_oversized_declared_body_is_refused_before_the_handler():
    response, reached = _dispatch("/api/auth/login", 500 * 1024 * 1024)
    assert response.status_code == 413
    assert reached == 0  # the body is never read


def test_webdav_uploads_are_exempt_from_the_cap():
    response, reached = _dispatch("/webdav/inbox/photo.jpg", 500 * 1024 * 1024)
    assert reached == 1  # the upload streams against its own cap
    assert response.status_code == 200


def test_a_body_without_content_length_passes_the_precheck():
    response, reached = _dispatch("/api/auth/login", None)
    assert reached == 1


def test_get_requests_are_never_capped():
    response, reached = _dispatch("/api/stats", 500 * 1024 * 1024, method="GET")
    assert reached == 1


# --- static-token failure throttling (B63) ---------------------------------

def _request():
    return SimpleNamespace(client=SimpleNamespace(host="192.0.2.7"))


def test_failures_consume_budget_until_the_cap():
    limiter = TokenFailureLimiter(max_failures=3, window_seconds=60)
    with pytest.raises(Exception):
        require_static_token_throttled(_request(), ["secret"], "wrong", "Test feature", limiter=limiter)
    with pytest.raises(Exception):
        require_static_token_throttled(_request(), ["secret"], "wrong", "Test feature", limiter=limiter)
    with pytest.raises(Exception):
        require_static_token_throttled(_request(), ["secret"], "wrong", "Test feature", limiter=limiter)
    # Budget exhausted: the 429 answers before the token check runs.
    with pytest.raises(Exception) as blocked:
        require_static_token_throttled(_request(), ["secret"], "wrong", "Test feature", limiter=limiter)
    assert "Too many token failures" in str(blocked.value)


def test_successful_tokens_never_consume_the_failure_budget():
    limiter = TokenFailureLimiter(max_failures=3, window_seconds=60)
    for _ in range(10):
        require_static_token_throttled(_request(), ["secret"], "secret", "Test feature", limiter=limiter)
    # A legit kiosk polling every photo cannot lock itself out.


def test_peers_are_keyed_independently():
    limiter = TokenFailureLimiter(max_failures=2, window_seconds=60)
    other = SimpleNamespace(client=SimpleNamespace(host="192.0.2.8"))
    for _ in range(3):
        with pytest.raises(Exception):
            require_static_token_throttled(_request(), ["secret"], "wrong", "Test feature", limiter=limiter)
    # The exhausted peer is blocked; the other peer is unaffected.
    with pytest.raises(Exception) as blocked:
        require_static_token_throttled(_request(), ["secret"], "wrong", "Test feature", limiter=limiter)
    assert "Too many token failures" in str(blocked.value)
    require_static_token_throttled(other, ["secret"], "secret", "Test feature", limiter=limiter)


# --- Immich payload walk cap (B65) -----------------------------------------

def test_iter_assets_stops_at_the_limit():
    from api.routers.immich import _iter_assets
    payload = {"assets": [{"originalPath": f"/p{i}.jpg"} for i in range(500)]}
    assets = list(_iter_assets(payload, limit=3))
    assert len(assets) == 3


def test_iter_assets_uncapped_yields_everything():
    from api.routers.immich import _iter_assets
    payload = {"assets": [{"originalPath": f"/p{i}.jpg"} for i in range(7)]}
    assert len(list(_iter_assets(payload))) == 7


def test_router_delivery_over_the_cap_is_logged_and_truncated():
    """The observability warning survives the walk cap: a delivery one past the
    cap is distinguishable from one exactly at it."""
    from api.routers import immich
    payload = {"assets": [{"originalPath": f"/p{i}.jpg"} for i in range(immich._MAX_ASSETS_PER_DELIVERY + 3)]}
    assets = list(immich._iter_assets(payload, limit=immich._MAX_ASSETS_PER_DELIVERY + 1))
    assert len(assets) == immich._MAX_ASSETS_PER_DELIVERY + 1


# --- API docs gating (B64) --------------------------------------------------

def _client(enable_docs):
    env = {"FACET_ENABLE_API_DOCS": "1" if enable_docs else ""}
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        app = create_app()
        return TestClient(app)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_the_interactive_docs_are_off_by_default():
    """The docs hand the complete route inventory to anyone who can reach the
    server; on a password-protected install that contradicts the disabled-
    feature-404 posture."""
    client = _client(enable_docs=False)
    assert client.get("/api/docs").status_code == 404
    assert client.get("/api/openapi.json").status_code == 404


def test_the_interactive_docs_can_be_enabled_for_development():
    client = _client(enable_docs=True)
    assert client.get("/api/openapi.json").status_code == 200
