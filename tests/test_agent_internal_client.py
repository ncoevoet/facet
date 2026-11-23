"""The internal ASGI client: allowlist, grant enforcement, JWT, status mapping, caps."""

import asyncio
import dataclasses
import json
from datetime import timedelta
from types import MappingProxyType

import pytest
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.testclient import TestClient
from fastapi.responses import JSONResponse

from api import config as api_config
from api.agent import limits, tokens
from api.agent.internal_client import (
    ROUTE_ALLOWLIST, InternalClient, NotAllowedError, RouteSpec,
)
from api.auth import decode_access_token
from tests.conftest import AGENT_DIR

PHOTO = AGENT_DIR + "fav.jpg"
READ_ROUTE = RouteSpec("GET", "/api/photo", "readonly")
RATE_ROUTE = RouteSpec("POST", "/api/photo/toggle_favorite", "user", write=True)
# Deliberately mislabelled: an edition-only route declared as readonly, so the only
# thing standing between the token and the route is the JWT the client mints.
MISLABELLED_EDITION_ROUTE = RouteSpec("POST", "/api/photos/batch_reject", "readonly", write=True)


class CountingApp:
    """ASGI wrapper counting how many requests reached the app."""

    def __init__(self, app):
        self.app = app
        self.hits = 0

    async def __call__(self, scope, receive, send):
        self.hits += 1
        await self.app(scope, receive, send)


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def photo(seed_photos_prefix):
    seed_photos_prefix(AGENT_DIR, [{"path": PHOTO, "filename": "fav.jpg", "aggregate": 7.0}])
    return PHOTO


def _client(env, **allow):
    counting = CountingApp(env.app)
    return InternalClient(counting, allowlist={**allow}), counting


class TestLocalEditionGrant:
    """An open-install edition token that the /mcp boundary judged local (``trusted_local``)."""

    @staticmethod
    def _local_grant(env, trusted):
        api_config.VIEWER_CONFIG["trusted_local_editing"] = True
        _, plaintext = tokens.mint("_anonymous", "laptop", "edition", "edition")
        return dataclasses.replace(tokens.verify(plaintext), trusted_local=trusted)

    def test_local_edition_grant_reaches_edition_route(self, agent_app, photo):
        env = agent_app("open")
        client, counting = _client(env, rate=RATE_ROUTE)
        result = _run(client.call(self._local_grant(env, True), "rate", json={"photo_path": photo}))
        assert result["ok"] is True, result
        assert counting.hits == 1

    def test_send_takes_the_fact_from_the_grant_it_is_handed(self, agent_app, photo):
        # REGRESSION GUARD: the same token WITHOUT the fact stays readonly, the route is never reached.
        env = agent_app("open")
        client, counting = _client(env, rate=RATE_ROUTE)
        result = _run(client.call(self._local_grant(env, False), "rate", json={"photo_path": photo}))
        assert result["error"] == "forbidden_level" and counting.hits == 0

    def test_the_signed_claims_name_the_local_edition_grant_only(self, agent_app):
        env = agent_app("open")
        claims = self._local_grant(env, True).resolve().jwt_claims()
        assert claims is not None and "sub" not in claims and claims["edition"] is True
        assert claims["mcp"] is True and claims["mcp_local"] is True
        # REGRESSION GUARD: an untrusted edition token and a readonly one still send no credential.
        assert self._local_grant(env, False).resolve().jwt_claims() is None
        _, readonly = tokens.mint("_anonymous", "ro", "readonly", "edition")
        assert dataclasses.replace(tokens.verify(readonly), trusted_local=True).resolve().jwt_claims() is None

    def test_the_opt_in_going_off_inside_the_jwt_lifetime_refuses(self, agent_app, photo):
        env = agent_app("open")
        resolved_claims = self._local_grant(env, True).resolve().jwt_claims()
        assert resolved_claims is not None
        api_config.VIEWER_CONFIG["trusted_local_editing"] = False
        from api.auth import create_access_token
        jwt_str = create_access_token(resolved_claims, expires_delta=timedelta(seconds=60))
        probe = TestClient(env.app, base_url="http://facet.internal", client=("127.0.0.1", 0))
        refused = probe.post("/api/photo/toggle_favorite", json={"photo_path": photo},
                             headers={"Authorization": "Bearer " + jwt_str})
        assert refused.status_code == 403


class TestAllowlist:
    # Edition-only READS the allowlist carries on purpose (the routes themselves are edition-gated), and the
    # only /api/scan and /api/config routes it may name.
    EDITION_READS = ("/api/comparison/stats", "/api/comparison/coverage", "/api/scan/status", "/api/scan/directories",
                     # edition-gated reads of the scoring weights and the dry preview score (no write)
                     "/api/comparison/category_weights", "/api/comparison/preview_score",
                     # the optimizer's suggestion (stores nothing), the snapshot list and the recompute status
                     "/api/comparison/learned_weights", "/api/comparison/confidence", "/api/config/weight_snapshots",
                     "/api/scan/recompute_status", "/api/organization_history")
    ALLOWED_PREFIXED = ("/api/scan/start", "/api/scan/status", "/api/scan/directories", "/api/config/scoring_contexts",
                        "/api/config/weight_snapshots", "/api/config/update_weights", "/api/config/restore_weights",
                        "/api/scan/recompute", "/api/scan/recompute_status")

    def test_allowlist_is_frozen_and_only_writes_demand_a_level(self):
        assert isinstance(ROUTE_ALLOWLIST, MappingProxyType)
        assert all(spec.min_level == "readonly" or spec.write or spec.template.endswith("/api/cull/apply")
                   or spec.template.endswith("/api/photo/delete") or spec.template in self.EDITION_READS
                   for spec in ROUTE_ALLOWLIST.values())
        assert all(spec.min_level != "readonly" for spec in ROUTE_ALLOWLIST.values() if spec.write)
        assert not any(spec.template.startswith(("/api/admin", "/api/config", "/api/scan",
                                                 "/api/auth", "/dav", "/api/frame"))
                       and spec.template not in self.ALLOWED_PREFIXED
                       for spec in ROUTE_ALLOWLIST.values())

    def test_unknown_tool_raises_without_an_upstream_call(self, agent_app):
        env = agent_app("legacy")
        token = env.token(env.login())
        client, counting = _client(env, get_photo=READ_ROUTE)
        with pytest.raises(NotAllowedError):
            _run(client.call(tokens.verify(token), "scan_library"))
        assert counting.hits == 0


class TestGrantEnforcement:
    def test_readonly_token_of_an_admin_is_refused_before_any_upstream_call(self, agent_app, photo):
        env = agent_app("multi")
        token = env.token(env.login("root"), "readonly")
        client, counting = _client(env, rate=RATE_ROUTE)
        result = _run(client.call(tokens.verify(token), "rate", json={"photo_path": photo}))
        assert result["ok"] is False and result["error"] == "forbidden_level"
        assert counting.hits == 0

    def test_user_token_cannot_reach_an_edition_route(self, agent_app, photo):
        env = agent_app("multi")
        token = env.token(env.login("alice"), "user")
        edition_route = RouteSpec("POST", "/api/photos/batch_reject", "edition", write=True)
        client, counting = _client(env, reject=edition_route)
        result = _run(client.call(tokens.verify(token), "reject", json={"photo_paths": [photo]}))
        assert result["error"] == "forbidden_level" and counting.hits == 0

    def test_user_token_reaches_a_user_route(self, agent_app, photo):
        env = agent_app("multi")
        token = env.token(env.login("alice"), "user")
        client, counting = _client(env, rate=RATE_ROUTE)
        result = _run(client.call(tokens.verify(token), "rate", json={"photo_path": photo}))
        assert result["ok"] is True, result
        assert counting.hits == 1

    def test_jwt_of_a_readonly_admin_token_carries_no_admin_rights(self, agent_app):
        env = agent_app("multi")
        token = env.token(env.login("root"), "readonly")
        claims = tokens.verify(token).resolve().jwt_claims()
        assert claims["role"] == "user" and claims["edition"] is False and claims["mcp"] is True
        assert claims["sub"] == "root"

    def test_jwt_of_an_edition_admin_token_keeps_the_live_role(self, agent_app):
        env = agent_app("multi")
        token = env.token(env.login("root"), "edition")
        claims = tokens.verify(token).resolve().jwt_claims()
        assert claims["role"] == "admin" and claims["edition"] is True

    def test_jwt_is_short_lived_and_decodes_against_current_generations(self, agent_app):
        env = agent_app("legacy")
        token = env.token(env.login(edition=True), "edition")
        resolved = tokens.verify(token).resolve()
        from api.auth import create_access_token
        jwt_str = create_access_token(resolved.jwt_claims(), expires_delta=timedelta(seconds=60))
        payload = decode_access_token(jwt_str)
        assert payload["mcp"] is True and payload["mcp_token_id"] == resolved.token_id
        assert payload["exp"] - payload["iat"] <= 60
        assert payload["edition"] is True

    def test_admin_readonly_token_is_refused_by_the_route_itself(self, agent_app, photo):
        """Defence in depth: even a mislabelled route is closed by the role-matching JWT."""
        env = agent_app("multi")
        token = env.token(env.login("root"), "readonly")
        client, counting = _client(env, reject=MISLABELLED_EDITION_ROUTE)
        result = _run(client.call(tokens.verify(token), "reject", json={"photo_paths": [photo]}))
        assert counting.hits == 1
        assert result["ok"] is False and result["error"] == "forbidden_level"

    def test_legacy_readonly_token_cannot_ride_a_rating_route(self, agent_app, photo):
        env = agent_app("legacy")
        token = env.token(env.login(), "readonly")
        client, counting = _client(env, rate=RATE_ROUTE)
        result = _run(client.call(tokens.verify(token), "rate", json={"photo_path": photo}))
        assert result["error"] == "forbidden_level" and counting.hits == 0

    def test_open_install_sends_no_authorization_header(self, agent_app):
        env = agent_app("open")
        token = env.token(env.login(), "readonly")
        assert tokens.verify(token).resolve().jwt_claims() is None

    def test_dead_token_is_forbidden_at_call_time(self, agent_app):
        env = agent_app("legacy")
        token = env.token(env.login(), "readonly")
        grant = tokens.verify(token)
        api_config.VIEWER_CONFIG["password"] = "rotated"
        client, counting = _client(env, get=READ_ROUTE)
        result = _run(client.call(grant, "get", query={"path": "x"}))
        assert result["error"] == "forbidden_level" and counting.hits == 0


def _fake_app():
    app = FastAPI()

    @app.get("/s/{code}")
    async def status(code: int):
        if code == 503:
            return JSONResponse({"detail": "library busy"}, status_code=503)
        raise HTTPException(status_code=code, detail=f"detail {code}")

    @app.get("/config403/{detail}")
    async def config_refusal(detail: str):
        raise HTTPException(status_code=403, detail=detail)

    @app.get("/slow")
    async def slow():
        await asyncio.sleep(2)
        return {}

    @app.post("/slow")
    async def slow_write():
        await asyncio.sleep(2)
        return {}

    @app.get("/big")
    async def big():
        return {"rows": [{"path": f"/p/{i}", "caption": "x" * 200} for i in range(500)], "total": 500}

    return app


class TestStatusMapping:
    @pytest.mark.parametrize("code,expected", [
        (401, "forbidden_level"), (403, "forbidden_level"), (404, "not_found"),
        (400, "invalid_input"), (412, "invalid_input"), (422, "invalid_input"),
        (409, "conflict"), (429, "rate_limited"), (503, "library_busy"), (500, "upstream_error"),
    ])
    def test_error_codes(self, agent_app, code, expected):
        env = agent_app("open")
        token = env.token(env.login(), "readonly")
        client = InternalClient(_fake_app(), allowlist={"s": RouteSpec("GET", "/s/{code}", "readonly")})
        result = _run(client.call(tokens.verify(token), "s", path_args={"code": code}))
        assert result["ok"] is False and result["error"] == expected

    @pytest.mark.parametrize("detail,expected", [
        ("Scan feature not enabled", "feature_disabled"), ("OS-trash is disabled", "feature_disabled"),
        ("Set viewer.edition_password to enable the scan trigger", "feature_disabled"),
        ("Edition access required", "forbidden_level"),
    ])
    def test_a_403_that_names_a_config_switch_is_feature_disabled(self, agent_app, detail, expected):
        env = agent_app("open")
        token = env.token(env.login(), "readonly")
        client = InternalClient(_fake_app(), allowlist={"c": RouteSpec("GET", "/config403/{detail}", "readonly")})
        result = _run(client.call(tokens.verify(token), "c", path_args={"detail": detail}))
        assert result["error"] == expected

    def test_read_timeout_is_upstream_error(self, agent_app):
        env = agent_app("open")
        token = env.token(env.login(), "readonly")
        client = InternalClient(_fake_app(), allowlist={"slow": RouteSpec("GET", "/slow", "readonly")})
        result = _run(client.call(tokens.verify(token), "slow", timeout=0.05))
        assert result["error"] == "upstream_error"

    def test_timeout_does_not_need_asyncio_timeout_python_3_11(self, agent_app, monkeypatch):
        monkeypatch.delattr(asyncio, "timeout")
        env = agent_app("open")
        token = env.token(env.login(), "readonly")
        client = InternalClient(_fake_app(), allowlist={"slow": RouteSpec("GET", "/slow", "readonly")})
        result = _run(client.call(tokens.verify(token), "slow", timeout=0.05))
        assert result["error"] == "upstream_error"
        assert "did not answer in time" in result["message"]

    def test_write_timeout_is_outcome_unknown(self, agent_app):
        env = agent_app("legacy")
        token = env.token(env.login(edition=True), "edition")
        client = InternalClient(_fake_app(), allowlist={
            "slow": RouteSpec("POST", "/slow", "edition", write=True)})
        result = _run(client.call(tokens.verify(token), "slow", timeout=0.05, json={}))
        assert result["error"] == "outcome_unknown"
        assert "do not blindly retry" in result["message"]

    def test_success_returns_the_parsed_body(self, agent_app):
        env = agent_app("open")
        token = env.token(env.login(), "readonly")
        client = InternalClient(_fake_app(), allowlist={"big": RouteSpec("GET", "/big", "readonly")})
        result = _run(client.call(tokens.verify(token), "big"))
        assert result["ok"] is True and result["data"]["total"] == 500


@pytest.mark.parametrize("kind,probes", [
    ("cameras", True), ("lenses", True), ("tags", True), ("persons", True), ("categories", False),
])
def test_filter_options_probes_only_filtered_dropdowns(agent_app, kind, probes):
    header = "X-Facet-Filter-Options-Overflow"
    app = FastAPI()

    @app.get("/api/filter_options/{route_kind}")
    async def report_probe(route_kind: str, request: Request, response: Response):
        probe = request.headers.get(header)
        if probe == "1":
            response.headers[header] = "1"
        return {"kind": route_kind, "probe": probe}

    env = agent_app("open")
    grant = tokens.verify(env.token(env.login(), "readonly"))
    client = InternalClient(app)
    for query in (None, {"query": ""}, {"query": "sun"}):
        expected = "1" if probes and query and query["query"] else None
        result = _run(client.call(grant, f"filter_options.{kind}", query=query))
        assert result["ok"] is True, result
        assert result["data"] == {"kind": kind, "probe": expected}
        if expected:
            assert result["truncated"] is True
        else:
            assert "truncated" not in result


class TestCaps:
    def test_over_cap_envelope_is_truncated_and_valid_json(self):
        envelope = {"ok": True, "data": {"rows": [{"path": f"/p/{i}", "caption": "x" * 200}
                                                  for i in range(500)], "total": 500}}
        capped = limits.fit_envelope(envelope, max_rows=100, max_bytes=20000)
        encoded = json.dumps(capped, separators=(",", ":"))
        assert len(encoded.encode()) <= 20000
        assert capped["truncated"] is True and len(capped["data"]["rows"]) < 100
        assert capped["data"]["total"] == 500
        assert json.loads(encoded) == capped

    def test_under_cap_envelope_is_untouched(self):
        envelope = {"ok": True, "data": {"rows": [{"path": "/a"}], "total": 1}}
        assert limits.fit_envelope(envelope, max_rows=100, max_bytes=20000) == envelope

    def test_row_cap_alone_truncates(self):
        envelope = {"ok": True, "data": {"rows": [{"p": i} for i in range(150)]}}
        capped = limits.fit_envelope(envelope, max_rows=100, max_bytes=500000)
        assert capped["truncated"] is True and len(capped["data"]["rows"]) == 100


class TestPathArgs:
    @pytest.mark.parametrize("value", ["..", ".", "", "../x", "a/../b", "./x"])
    def test_dot_segments_and_empty_path_args_are_refused_before_any_upstream_call(self, agent_app, value):
        env = agent_app("open")
        grant = tokens.verify(env.token(env.login(), "readonly"))
        counting = CountingApp(FastAPI())
        client = InternalClient(counting, allowlist=MappingProxyType(
            {"sim": RouteSpec("GET", "/api/similar_photos/{path}", "readonly")}))
        result = _run(client.call(grant, "sim", path_args={"path": value}))
        assert result["ok"] is False and result["error"] == "invalid_input" and counting.hits == 0

    def test_similar_photos_tool_refuses_dot_dot(self, agent_app):
        env = agent_app("open")
        token = env.token(env.login())
        result = env.call(token, "similar_photos", {"path": ".."})
        assert result["ok"] is False and result["error"] == "invalid_input"


def _write_app():
    app = FastAPI()

    @app.post("/w/{code}")
    async def write(code: int, body: dict):
        if code >= 400:
            raise HTTPException(status_code=code, detail=f"detail {code}")
        return {"count": 2, "echo": body}

    @app.get("/r")
    async def read():
        return {"ok": 1}

    @app.post("/slowwrite")
    async def slow_write():
        await asyncio.sleep(2)
        return {}

    return app


WRITE_SPEC = RouteSpec("POST", "/w/{code}", "edition", write=True)


class TestOnWriteSink:
    @staticmethod
    def _setup(agent_app, sink, **allow):
        env = agent_app("legacy")
        grant = tokens.verify(env.token(env.login(edition=True), "edition"))
        return grant, InternalClient(_write_app(), allowlist={**allow}, on_write=sink)

    def test_a_successful_write_calls_the_sink_once_with_principal_tool_body_and_response(self, agent_app):
        seen = []
        grant, client = self._setup(agent_app, lambda *args: seen.append(args), w=WRITE_SPEC)
        result = _run(client.call(grant, "w", path_args={"code": 200}, json={"photo_path": "/a"}))
        assert result["ok"] is True
        assert seen == [("_legacy", "w", {"photo_path": "/a"}, {"count": 2, "echo": {"photo_path": "/a"}})]

    def test_a_read_never_calls_the_sink(self, agent_app):
        seen = []
        grant, client = self._setup(agent_app, lambda *args: seen.append(args),
                                    r=RouteSpec("GET", "/r", "readonly"))
        assert _run(client.call(grant, "r"))["ok"] is True
        assert seen == []

    @pytest.mark.parametrize("code", [403, 404, 422, 500])
    def test_a_refused_write_never_calls_the_sink(self, agent_app, code):
        seen = []
        grant, client = self._setup(agent_app, lambda *args: seen.append(args), w=WRITE_SPEC)
        result = _run(client.call(grant, "w", path_args={"code": code}, json={}))
        assert result["ok"] is False and seen == []

    def test_a_write_timeout_calls_the_sink_with_the_body_and_no_response(self, agent_app):
        seen = []
        grant, client = self._setup(agent_app, lambda *args: seen.append(args),
                                    slow=RouteSpec("POST", "/slowwrite", "edition", write=True))
        result = _run(client.call(grant, "slow", json={"paths": ["/a"]}, timeout=0.05))
        assert result["error"] == "outcome_unknown"
        assert seen == [("_legacy", "slow", {"paths": ["/a"]}, None)]

    def test_a_transport_error_on_a_write_calls_the_sink_and_on_a_read_does_not(self, agent_app, monkeypatch):
        import httpx

        async def boom(self, *args, **kwargs):
            raise httpx.ConnectError("down")

        monkeypatch.setattr(httpx.AsyncClient, "request", boom)
        seen = []
        grant, client = self._setup(agent_app, lambda *args: seen.append(args), w=WRITE_SPEC,
                                    r=RouteSpec("GET", "/r", "readonly"))
        assert _run(client.call(grant, "w", path_args={"code": 200}, json={"paths": ["/a"]}))["error"] == "outcome_unknown"
        assert len(seen) == 1
        assert _run(client.call(grant, "r"))["error"] == "upstream_error"
        assert len(seen) == 1

    def test_a_read_timeout_never_calls_the_sink(self, agent_app):
        seen = []
        grant, client = self._setup(agent_app, lambda *args: seen.append(args),
                                    slow=RouteSpec("GET", "/slowwrite", "readonly"))
        _run(client.call(grant, "slow", timeout=0.05))
        assert seen == []

    def test_a_raising_sink_never_changes_the_result(self, agent_app):
        def sink(*args):
            raise RuntimeError("tab exploded")

        grant, client = self._setup(agent_app, sink, w=WRITE_SPEC)
        assert _run(client.call(grant, "w", path_args={"code": 200}, json={}))["ok"] is True

    def test_an_async_sink_is_awaited(self, agent_app):
        seen = []

        async def sink(*args):
            seen.append(args)

        grant, client = self._setup(agent_app, sink, w=WRITE_SPEC)
        _run(client.call(grant, "w", path_args={"code": 200}, json={}))
        assert len(seen) == 1

    def test_a_non_write_spec_never_calls_the_sink(self, agent_app):
        seen = []
        grant, client = self._setup(agent_app, lambda *args: seen.append(args),
                                    preview=RouteSpec("POST", "/w/{code}", "edition"))
        assert _run(client.call(grant, "preview", path_args={"code": 200}, json={}))["ok"] is True
        assert seen == []

    def test_the_context_override_takes_precedence(self, agent_app):
        from api.agent.live_updates import LIVE_SINK_OVERRIDE
        own, override = [], []
        grant, client = self._setup(agent_app, lambda *args: own.append(args), w=WRITE_SPEC)
        marker = LIVE_SINK_OVERRIDE.set(lambda *args: override.append(args))
        try:
            _run(client.call(grant, "w", path_args={"code": 200}, json={}))
        finally:
            LIVE_SINK_OVERRIDE.reset(marker)
        assert own == [] and len(override) == 1

    def test_no_sink_is_the_default(self, agent_app):
        env = agent_app("legacy")
        grant = tokens.verify(env.token(env.login(edition=True), "edition"))
        client = InternalClient(_write_app(), allowlist={"w": WRITE_SPEC})
        assert _run(client.call(grant, "w", path_args={"code": 200}, json={}))["ok"] is True
