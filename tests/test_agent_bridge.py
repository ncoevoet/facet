"""The tab bridge: WebSocket handshake, the registry, call forwarding and the ``ui_*`` tools.

[REAL] fixture throughout (``agent_app``): the real auth chain, the real lifespan, no
``dependency_overrides``. A browser tab is a scripted :class:`tests.conftest.FakeTab`.
"""

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone

import pytest
from starlette.websockets import WebSocketDisconnect

from api import config as api_config
from api.agent import bridge
from api.agent.ui_tools import UI_TOOLS, tools_version
from api.auth import SHARE_CLIENT_ROLE, create_access_token
from tests.conftest import serve_app


def jwt_of(headers):
    return headers["Authorization"].split(" ", 1)[1]


def connect(env, origin="http://testserver"):
    headers = {"origin": origin} if origin is not None else {}
    return env.client.websocket_connect("/api/mcp/bridge", headers=headers)


def refused_code(env, **kwargs):
    with connect(env, **kwargs) as ws:
        return closed_after(ws)


def auth_frame(token, tab_id="t1", **extra):
    return {"type": "auth", "token": token, "tab_id": tab_id, "route": "/", "focused": True,
            "tools": [t.name for t in UI_TOOLS], "tools_version": tools_version(), **extra}


def closed_after(ws):
    with pytest.raises(WebSocketDisconnect) as info:
        ws.receive_json()
    return info.value.code


class TestHandshake:
    def test_no_origin_is_4403(self, agent_app):
        env = agent_app("open")
        assert refused_code(env, origin=None) == bridge.CLOSE_FORBIDDEN_ORIGIN

    def test_foreign_origin_is_4403(self, agent_app):
        env = agent_app("open")
        assert refused_code(env, origin="http://evil.example") == 4403

    def test_flag_off_is_4404_before_accept(self, agent_app):
        env = agent_app("open", mcp_enabled=False)
        assert refused_code(env) == bridge.CLOSE_DISABLED

    def test_bridge_flag_off_is_4404(self, agent_app):
        env = agent_app("open", bridge=False)
        assert refused_code(env) == 4404

    def test_allowed_origins_lets_a_rewriting_proxy_through(self, agent_app):
        env = agent_app("open", allowed_origins=["https://photos.example"])
        with connect(env, origin="https://photos.example") as ws:
            ws.send_json(auth_frame(None))
            assert ws.receive_json()["type"] == "ready"

    def test_no_first_frame_is_4401(self, agent_app, monkeypatch):
        monkeypatch.setattr(bridge, "AUTH_TIMEOUT_S", 0.2)
        env = agent_app("open")
        with connect(env) as ws:
            assert closed_after(ws) == bridge.CLOSE_UNAUTHORIZED

    def test_bad_jwt_is_4401(self, agent_app):
        env = agent_app("legacy")
        with connect(env) as ws:
            ws.send_json(auth_frame("not.a.jwt"))
            assert closed_after(ws) == 4401

    def test_share_client_token_is_4401(self, agent_app):
        env = agent_app("legacy")
        token = create_access_token({"sub": "client", "role": SHARE_CLIENT_ROLE})
        with connect(env) as ws:
            ws.send_json(auth_frame(token))
            assert closed_after(ws) == 4401

    def test_agent_internal_jwt_is_4401(self, agent_app):
        env = agent_app("legacy")
        token = create_access_token({"sub": "_legacy", "role": "user", "mcp": True})
        with connect(env) as ws:
            ws.send_json(auth_frame(token))
            assert closed_after(ws) == 4401

    def test_query_string_token_is_ignored(self, agent_app):
        env = agent_app("legacy")
        token = jwt_of(env.login())
        with env.client.websocket_connect(f"/api/mcp/bridge?token={token}",
                                          headers={"origin": "http://testserver"}) as ws:
            ws.send_json({"type": "auth", "tab_id": "t1", "route": "/", "focused": True, "tools": []})
            assert closed_after(ws) == 4401

    def test_deeply_nested_preauth_frame_is_4400(self, agent_app):
        env = agent_app("open")
        with connect(env) as ws:
            ws.send_text("[" * 100000)
            assert closed_after(ws) == bridge.CLOSE_PROTOCOL

    def test_oversize_preauth_frame_is_rejected_unparsed(self, agent_app, monkeypatch):
        import json as json_module
        calls = []
        real = json_module.loads
        monkeypatch.setattr(json_module, "loads", lambda text, *a, **k: calls.append(len(text)) or real(text, *a, **k))
        env = agent_app("open")
        with connect(env) as ws:
            ws.send_text('{"type":"auth","pad":"' + "a" * (bridge.MAX_FRAME_BYTES + 10) + '"}')
            assert closed_after(ws) == bridge.CLOSE_PROTOCOL
        assert all(size <= bridge.MAX_FRAME_BYTES for size in calls)

    def test_deeply_nested_frame_after_auth_closes_4400(self, agent_app, fake_tab):
        env = agent_app("open")
        tab = fake_tab(env, None)
        tab.send_raw("[" * 100000)
        assert tab.wait_closed() == bridge.CLOSE_PROTOCOL

    def test_first_frame_must_be_auth(self, agent_app):
        env = agent_app("open")
        with connect(env) as ws:
            ws.send_json({"type": "state", "route": "/"})
            assert closed_after(ws) == 4401

    def test_malformed_auth_is_4400(self, agent_app):
        env = agent_app("open")
        with connect(env) as ws:
            ws.send_json(auth_frame(None, tab_id="bad id!"))
            assert closed_after(ws) == bridge.CLOSE_PROTOCOL

    def test_good_auth_is_ready(self, agent_app):
        env = agent_app("multi")
        with connect(env) as ws:
            ws.send_json(auth_frame(jwt_of(env.login("alice"))))
            ready = ws.receive_json()
        assert ready["type"] == "ready" and ready["user_id"] == "alice"
        assert ready["tools_version"] == tools_version() and ready["call_timeout_s"] == 30

    def test_open_install_accepts_null_token_as_anonymous(self, agent_app):
        env = agent_app("open")
        with connect(env) as ws:
            ws.send_json(auth_frame(None))
            ready = ws.receive_json()
        assert ready["user_id"] == "_anonymous"

    def test_password_install_rejects_null_token(self, agent_app):
        env = agent_app("legacy")
        with connect(env) as ws:
            ws.send_json(auth_frame(None))
            assert closed_after(ws) == 4401

    def test_expired_session_closes_4401(self, agent_app, fake_tab, monkeypatch):
        import jwt.api_jwt

        env = agent_app("legacy")
        token = create_access_token({"sub": "_legacy", "role": "user"},
                                    expires_delta=timedelta(seconds=2))
        # Read after minting: a clock frozen just before a second boundary would
        # precede the token's whole-second iat and fail the handshake instead.
        verification_time = datetime.now(timezone.utc)

        class VerificationClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return (verification_time.astimezone(tz) if tz is not None
                        else verification_time.replace(tzinfo=None))

        # A slow worker must not spend this token's lifetime before the
        # handshake. Keep the real JWT validation, then expire it only after
        # the actual socket has authenticated and sent its ready frame.
        monkeypatch.setattr(jwt.api_jwt, "datetime", VerificationClock)
        tab = fake_tab(env, token)
        assert tab.ready["type"] == "ready"
        verification_time += timedelta(seconds=3)
        assert tab.wait_closed() == bridge.CLOSE_UNAUTHORIZED

    def test_rotated_password_closes_4401(self, agent_app, fake_tab):
        from api import config as api_config
        env = agent_app("legacy")
        tab = fake_tab(env, jwt_of(env.login()))
        api_config.VIEWER_CONFIG["password"] = "rotated-pw"
        assert tab.wait_closed() == 4401

    def test_silent_tab_is_dropped(self, agent_app, fake_tab, monkeypatch):
        monkeypatch.setattr(bridge, "SILENCE_DROP_S", 0.3)
        env = agent_app("open")
        tab = fake_tab(env, None, answer_pings=False)
        assert tab.wait_closed() == bridge.CLOSE_SILENT

    def test_tab_cap_closes_the_oldest_with_4409(self, agent_app, fake_tab, monkeypatch):
        monkeypatch.setattr(bridge, "MAX_TABS_PER_USER", 2)
        env = agent_app("open")
        first = fake_tab(env, None, "tab-a")
        fake_tab(env, None, "tab-b")
        fake_tab(env, None, "tab-c")
        assert first.wait_closed() == bridge.CLOSE_SUPERSEDED

    def test_reconnect_with_the_same_tab_id_supersedes(self, agent_app, fake_tab):
        env = agent_app("open")
        old = fake_tab(env, None, "same")
        fake_tab(env, None, "same")
        assert old.wait_closed() == 4409
        assert len(env.app.state.tab_registry.tabs_for("_anonymous")) == 1


class _ScriptedSocket:
    """The handler's side of a socket: the queued frames, then the client is gone."""

    def __init__(self, app, frames):
        self.app = app
        self.headers = {"origin": "http://testserver", "host": "testserver"}
        self._frames = list(frames)

    async def accept(self):
        pass

    async def receive(self):
        if self._frames:
            return {"type": "websocket.receive", "text": json.dumps(self._frames.pop(0))}
        return {"type": "websocket.disconnect", "code": 1000}

    async def send_json(self, frame):
        pass

    async def close(self, code=1000):
        pass


class TestHandlerCancellation:
    def test_cancel_during_cleanup_reraises_its_own_and_unregisters(self, agent_app, monkeypatch):
        """Starlette's TestClient cancels the app right after sending the disconnect, so the
        handler can be cancelled while it stops its pinger. That cancellation must stay the
        handler's own -- a child's untagged one escapes anyio's cancel scope and fails the
        session teardown -- and the tab must still leave the registry."""
        from api.routers import mcp_bridge
        env = agent_app("open")
        registry = env.app.state.tab_registry

        async def scenario():
            stopping, release = asyncio.Event(), asyncio.Event()

            async def keepalive_slow_to_stop(*_):
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    stopping.set()
                    await release.wait()
                    raise

            monkeypatch.setattr(mcp_bridge, "_keepalive", keepalive_slow_to_stop)
            handler = asyncio.ensure_future(mcp_bridge.tab_bridge(
                _ScriptedSocket(env.app, [auth_frame(None, tab_id="cancelled")])))
            await stopping.wait()
            handler.cancel("cancelled by the server")
            release.set()
            with pytest.raises(asyncio.CancelledError) as info:
                await handler
            return info.value

        cancelled = asyncio.run(scenario())
        assert cancelled.args == ("cancelled by the server",)
        assert registry.tabs_for("_anonymous") == []


class TestForwarding:
    def test_call_roundtrip_and_envelope(self, agent_app, fake_tab):
        env = agent_app("multi")
        tab = fake_tab(env, jwt_of(env.login("alice")),
                       reply=lambda call: {"ok": True, "data": {"total": 7, "args": call["args"]}})
        token = env.token(env.login("alice"))
        result = env.call(token, "ui_get_gallery_view", {"limit": 10})
        assert result["ok"] is True and result["data"] == {"total": 7, "args": {"limit": 10}}
        assert result["tab"]["tab_id"] == "tab-1" and result["tab"]["tab_count"] == 1
        assert [c["tool"] for c in tab.calls] == ["ui_get_gallery_view"]
        assert "tab_id" not in tab.calls[0]["args"]

    def test_show_photos_sends_one_frame_and_bounds_the_list(self, agent_app, fake_tab):
        env = agent_app("open")
        tab = fake_tab(env, None, reply=lambda call: {"ok": True, "data": {"shown": 2, "missing": [], "total": 2}})
        token = env.token(env.login())
        paths = ["/a.jpg", "/b.jpg"]
        result = env.call(token, "ui_show_photos", {"paths": paths})
        assert result["ok"] is True and result["data"]["shown"] == 2
        assert [(c["tool"], c["args"]) for c in tab.calls] == [("ui_show_photos", {"paths": paths})]
        for bad in ([], [f"/p{n}.jpg" for n in range(201)], [""]):
            refused = env.call(token, "ui_show_photos", {"paths": bad})
            assert refused["ok"] is False and refused["error"] == "invalid_input"
        assert len(tab.calls) == 1

    def test_tab_error_codes_are_whitelisted_and_bounded(self, agent_app, fake_tab):
        env = agent_app("open")
        fake_tab(env, None, reply=lambda call: {"ok": False, "error": "rm -rf", "message": "x" * 5000})
        result = env.call(env.token(env.login()), "ui_next_page")
        assert result["ok"] is False and result["error"] == "upstream_error"
        assert len(result["message"]) == bridge.MAX_MESSAGE_CHARS

    def test_tab_reported_known_error_passes_through(self, agent_app, fake_tab):
        env = agent_app("open")
        fake_tab(env, None, reply=lambda call: {
            "ok": False, "error": "forbidden_level", "message": "Edition only"})
        result = env.call(env.token(env.login()), "ui_navigate", {"route": "/culling"})
        assert result["error"] == "forbidden_level" and result["message"] == "Edition only"

    def test_tab_data_is_bounded(self, agent_app, fake_tab):
        deep = leaf = {}
        for _ in range(9):
            leaf["n"] = {}
            leaf = leaf["n"]
        leaf["end"] = "bottom"
        payload = {"paths": ["p%d" % i for i in range(1500)], "long": "x" * 3000, "deep": deep}
        env = agent_app("open")
        fake_tab(env, None, reply=lambda call: {"ok": True, "data": payload})
        result = env.call(env.token(env.login()), "ui_get_selection")
        assert result["ok"] is True and result["truncated"] is True
        data = result["data"]
        assert len(data["paths"]) == bridge.MAX_LIST_ITEMS
        assert len(data["long"]) == bridge.MAX_STRING_CHARS
        node, depth = data["deep"], 0
        while isinstance(node, dict) and "n" in node:
            node, depth = node["n"], depth + 1
        assert node is None and depth < 9

    def test_oversize_result_frame_is_too_large(self, agent_app, fake_tab, monkeypatch):
        monkeypatch.setattr(bridge, "MAX_FRAME_BYTES", 2000)
        env = agent_app("open")
        fake_tab(env, None, reply=lambda call: {"ok": True, "data": "z" * 5000})
        result = env.call(env.token(env.login()), "ui_next_page")
        assert result["ok"] is False and result["error"] == "too_large"

    def test_no_tab_answers_immediately(self, agent_app):
        env = agent_app("open")
        started = time.monotonic()
        result = env.call(env.token(env.login()), "ui_get_selection")
        assert result["error"] == "no_tab" and time.monotonic() - started < 2

    def test_tab_timeout_and_no_pending_leak(self, agent_app, fake_tab):
        env = agent_app("open", call_timeout_s=1)
        fake_tab(env, None, reply=lambda call: None)
        result = env.call(env.token(env.login()), "ui_get_selection")
        assert result["error"] == "tab_timeout"
        (conn,) = env.app.state.tab_registry.tabs_for("_anonymous")
        assert conn.pending == {}

    def test_tab_closing_mid_call_is_no_tab(self, agent_app, fake_tab):
        env = agent_app("open")
        fake_tab(env, None, reply=lambda call: "close")
        result = env.call(env.token(env.login()), "ui_get_selection")
        assert result["error"] == "no_tab"

    def test_call_on_a_closed_conn_fails_fast(self, agent_app, fake_tab):
        env = agent_app("open")
        fake_tab(env, None)
        (conn,) = env.app.state.tab_registry.tabs_for("_anonymous")
        conn.closed = True
        started = time.monotonic()
        result = asyncio.run(env.app.state.tab_registry.call(
            "_anonymous", "ui_next_page", {}, level="readonly", tab_id=None, timeout=30))
        assert result["error"] == "no_tab" and time.monotonic() - started < 2
        assert conn.pending == {}

    def test_tab_missing_a_tool_is_outdated(self, agent_app, fake_tab):
        env = agent_app("open")
        tab = fake_tab(env, None, tools=["ui_navigate"])
        token = env.token(env.login())
        assert env.call(token, "ui_get_selection")["error"] == "tab_outdated"
        assert tab.calls == []

    def test_version_mismatch_is_outdated(self, agent_app, fake_tab):
        env = agent_app("open")
        tab = fake_tab(env, None, version="0000000000000000")
        assert env.call(env.token(env.login()), "ui_next_page")["error"] == "tab_outdated"
        assert tab.calls == []

    def test_state_frame_updates_tools_and_route(self, agent_app, fake_tab):
        env = agent_app("open")
        tab = fake_tab(env, None, tools=[])
        token = env.token(env.login())
        assert env.call(token, "ui_next_page")["error"] == "tab_outdated"
        tab.send_later({"type": "state", "route": "/albums", "focused": True,
                        "tools": [t.name for t in UI_TOOLS], "tools_version": tools_version()})
        deadline = time.monotonic() + 5
        result = {}
        while time.monotonic() < deadline:
            result = env.call(token, "ui_next_page")
            if result.get("ok"):
                break
            time.sleep(0.1)
        assert result["ok"] is True and result["tab"]["route"] == "/albums"

    def test_most_recently_focused_tab_wins_and_says_so(self, agent_app, fake_tab):
        env = agent_app("open")
        first = fake_tab(env, None, "tab-a", focused=True)
        second = fake_tab(env, None, "tab-b", focused=False)
        token = env.token(env.login())
        first.send_later({"type": "state", "route": "/", "focused": False})
        second.send_later({"type": "state", "route": "/stats", "focused": True})
        deadline = time.monotonic() + 5
        picked = {}
        while time.monotonic() < deadline:
            picked = env.call(token, "ui_get_selection")
            if picked.get("tab", {}).get("tab_id") == "tab-b":
                break
            time.sleep(0.1)
        assert picked["tab"]["tab_id"] == "tab-b" and picked["tab"]["selected_by"] == "focused"
        assert "2 tabs" in picked["tab"]["note"]
        assert env.call(token, "ui_get_selection", {"tab_id": "tab-a"})["tab"]["tab_id"] == "tab-a"
        assert env.call(token, "ui_get_selection", {"tab_id": "nope"})["error"] == "no_tab"

    def test_users_never_reach_each_others_tabs(self, agent_app, fake_tab):
        env = agent_app("multi")
        alice_tab = fake_tab(env, jwt_of(env.login("alice")), "alice-tab")
        bob_tab = fake_tab(env, jwt_of(env.login("bob")), "bob-tab")
        alice_token = env.token(env.login("alice"))
        bob_token = env.token(env.login("bob"))
        assert env.call(alice_token, "ui_get_selection")["tab"]["tab_id"] == "alice-tab"
        assert env.call(bob_token, "ui_get_selection")["tab"]["tab_id"] == "bob-tab"
        assert len(alice_tab.calls) == 1 and len(bob_tab.calls) == 1
        alice_tab.stop()
        deadline = time.monotonic() + 5
        result = {}
        while time.monotonic() < deadline and result.get("error") != "no_tab":
            result = env.call(alice_token, "ui_get_selection")
            time.sleep(0.1)
        assert result["error"] == "no_tab"
        assert len(bob_tab.calls) == 1

    def test_bridge_flag_off_makes_ui_tools_error_clearly(self, agent_app):
        env = agent_app("open", bridge=False)
        token = env.token(env.login())
        assert "ui_navigate" in env.tool_names(token)
        result = env.call(token, "ui_navigate", {"route": "/stats"})
        assert result["error"] == "no_tab" and "bridge" in result["message"]


class TestTabLevels:
    def test_viewer_only_tab_never_serves_an_edition_token(self, agent_app, fake_tab):
        env = agent_app("legacy")
        fake_tab(env, jwt_of(env.login()), "viewer-tab")
        edition_token = env.token(env.login(edition=True), "edition")
        result = env.call(edition_token, "ui_get_selection")
        assert result["error"] == "no_tab"
        assert "edition" in result["message"]
        fake_tab(env, jwt_of(env.login(edition=True)), "edition-tab")
        assert env.call(edition_token, "ui_get_selection")["tab"]["tab_id"] == "edition-tab"

    def test_viewer_only_tab_cannot_steal_focus_from_an_edition_tab(self, agent_app, fake_tab):
        env = agent_app("legacy")
        fake_tab(env, jwt_of(env.login(edition=True)), "edition-tab", focused=False)
        fake_tab(env, jwt_of(env.login()), "rogue-tab", focused=True)
        edition_token = env.token(env.login(edition=True), "edition")
        assert env.call(edition_token, "ui_get_selection")["tab"]["tab_id"] == "edition-tab"

    def test_readonly_token_may_drive_an_edition_tab(self, agent_app, fake_tab):
        env = agent_app("legacy")
        fake_tab(env, jwt_of(env.login(edition=True)), "edition-tab")
        token = env.token(env.login(edition=True), "readonly")
        assert env.call(token, "ui_get_selection")["tab"]["tab_id"] == "edition-tab"

    def test_viewer_minted_readonly_token_cannot_reach_an_edition_tab(self, agent_app, fake_tab):
        env = agent_app("legacy")
        fake_tab(env, jwt_of(env.login(edition=True)), "edition-tab")
        token = env.token(env.login(), "readonly")
        result = env.call(token, "ui_get_selection")
        assert result["error"] == "no_tab" and "viewer-only session" in result["message"]
        status = env.call(token, "status")["data"]
        assert status["tabs"] == [] and status["out_of_reach_tabs"] == 1
        fake_tab(env, jwt_of(env.login()), "viewer-tab")
        assert env.call(token, "ui_get_selection")["tab"]["tab_id"] == "viewer-tab"
        status = env.call(token, "status")["data"]
        assert [t["tab_id"] for t in status["tabs"]] == ["viewer-tab"] and status["out_of_reach_tabs"] == 1

    def test_open_install_token_cannot_reach_an_edition_tab_of_the_shared_principal(self, agent_app, fake_tab):
        env = agent_app("open")
        api_config.VIEWER_CONFIG["edition_password"] = "ed-pw"
        resp = env.client.post("/api/auth/edition/login", json={"password": "ed-pw"})
        assert resp.status_code == 200, resp.text
        env.client.cookies.clear()
        fake_tab(env, resp.json()["access_token"], "edition-tab")
        assert [t.level for t in env.app.state.tab_registry.tabs_for("_anonymous")] == ["edition"]
        token = env.token(env.login(), "readonly")
        result = env.call(token, "ui_get_selection")
        assert result["error"] == "no_tab"
        status = env.call(token, "status")["data"]
        assert status["tabs"] == [] and status["out_of_reach_tabs"] == 1

    def test_null_minted_level_row_counts_as_readonly(self, agent_app, fake_tab):
        from api.database import get_db
        env = agent_app("legacy")
        fake_tab(env, jwt_of(env.login(edition=True)), "edition-tab")
        token = env.token(env.login(edition=True), "readonly")
        with get_db() as conn:
            conn.execute("UPDATE mcp_tokens SET minted_level = NULL")
            conn.commit()
        assert env.call(token, "ui_get_selection")["error"] == "no_tab"

    def test_null_minted_level_edition_row_is_capped_at_its_own_level(self, agent_app, fake_tab):
        from api.database import get_db
        env = agent_app("legacy")
        fake_tab(env, jwt_of(env.login(edition=True)), "edition-tab")
        token = env.token(env.login(edition=True), "edition")
        with get_db() as conn:
            conn.execute("UPDATE mcp_tokens SET minted_level = NULL")
            conn.commit()
        assert env.call(token, "ui_get_selection")["tab"]["tab_id"] == "edition-tab"
        assert [t["tab_id"] for t in env.call(token, "status")["data"]["tabs"]] == ["edition-tab"]

    def test_viewer_session_cannot_evict_an_edition_tab_by_reusing_its_id(self, agent_app, fake_tab):
        env = agent_app("legacy")
        edition_tab = fake_tab(env, jwt_of(env.login(edition=True)), "shared-id")
        rogue = fake_tab(env, jwt_of(env.login()), "shared-id", wait=False)
        assert rogue.wait_closed() == bridge.CLOSE_SUPERSEDED
        token = env.token(env.login(edition=True), "edition")
        assert env.call(token, "ui_get_selection")["tab"]["tab_id"] == "shared-id"
        assert edition_tab.close_code is None

    def test_full_registry_never_evicts_a_higher_tab_for_a_lower_newcomer(self, agent_app, fake_tab, monkeypatch):
        monkeypatch.setattr(bridge, "MAX_TABS_PER_USER", 2)
        env = agent_app("legacy")
        edition_jwt = jwt_of(env.login(edition=True))
        fake_tab(env, edition_jwt, "e1")
        fake_tab(env, edition_jwt, "e2")
        rogue = fake_tab(env, jwt_of(env.login()), "v1", wait=False)
        assert rogue.wait_closed() == bridge.CLOSE_SUPERSEDED
        token = env.token(env.login(edition=True), "readonly")
        assert {t["tab_id"] for t in env.call(token, "status")["data"]["tabs"]} == {"e1", "e2"}

    def test_full_registry_evicts_the_lowest_level_first(self, agent_app, fake_tab, monkeypatch):
        monkeypatch.setattr(bridge, "MAX_TABS_PER_USER", 2)
        env = agent_app("legacy")
        edition_jwt = jwt_of(env.login(edition=True))
        fake_tab(env, edition_jwt, "e1")
        viewer = fake_tab(env, jwt_of(env.login()), "v1")
        fake_tab(env, edition_jwt, "e2")
        assert viewer.wait_closed() == bridge.CLOSE_SUPERSEDED

    def test_multi_user_token_reaches_its_own_role_tab(self, agent_app, fake_tab):
        env = agent_app("multi")
        fake_tab(env, jwt_of(env.login("alice")), "alice-tab")
        assert env.call(env.token(env.login("alice"), "user"), "ui_get_selection")["tab"]["tab_id"] == "alice-tab"
        fake_tab(env, jwt_of(env.login("root")), "root-tab")
        assert env.call(env.token(env.login("root"), "edition"), "ui_get_selection")["tab"]["tab_id"] == "root-tab"

    def test_multi_user_floor_message_does_not_mention_unlocking_edition(self, agent_app, fake_tab):
        env = agent_app("multi")
        stale = {"Authorization": "Bearer " + create_access_token({"sub": "root", "role": "user"})}
        fake_tab(env, jwt_of(stale), "root-stale-tab")
        result = env.call(env.token(env.login("root"), "edition"), "ui_get_selection")
        assert result["error"] == "no_tab" and "account role is below edition rights" in result["message"]
        assert "unlock" not in result["message"]

    def test_tab_id_of_an_out_of_reach_tab_is_not_reported_as_disconnected(self, agent_app, fake_tab):
        env = agent_app("legacy")
        fake_tab(env, jwt_of(env.login()), "viewer-tab")
        fake_tab(env, jwt_of(env.login(edition=True)), "edition-tab")
        token = env.token(env.login(edition=True), "edition")
        result = env.call(token, "ui_get_selection", {"tab_id": "viewer-tab"})
        assert result["error"] == "no_tab" and "not connected" not in result["message"]
        assert "viewer-tab is open but outside this token's reach" in result["message"]
        assert "only higher-rights" not in result["message"] and "less than" not in result["message"]
        assert "not connected" in env.call(token, "ui_get_selection", {"tab_id": "ghost"})["message"]

    def test_status_for_an_edition_token_with_only_a_viewer_tab_is_empty(self, agent_app, fake_tab):
        env = agent_app("legacy")
        fake_tab(env, jwt_of(env.login()), "viewer-tab")
        status = env.call(env.token(env.login(edition=True), "edition"), "status")["data"]
        assert status["tabs"] == [] and status["out_of_reach_tabs"] == 1

    def test_clearing_the_edition_password_mid_socket_drops_the_tab_level(self, agent_app, fake_tab):
        from api import config as api_config
        env = agent_app("legacy")
        fake_tab(env, jwt_of(env.login(edition=True)), "edition-tab")
        token = env.token(env.login(edition=True), "edition")
        assert env.call(token, "ui_get_selection")["tab"]["tab_id"] == "edition-tab"
        api_config.VIEWER_CONFIG["edition_password"] = ""
        time.sleep(0.5)
        registry = env.client.app.state.tab_registry
        assert [t.level for t in registry.tabs_for("_legacy")] == ["readonly"]
        # the token degrades with the password too, so it follows the tab down rather than losing it
        assert env.call(token, "ui_get_selection")["tab"]["tab_id"] == "edition-tab"


class TestRealBrowserCloseCodes:
    """The refusals must reach a real WebSocket client as close frames, not an HTTP 403 (a
    browser reports that as 1006 and the tab would retry forever)."""

    @staticmethod
    def _close_code(port, origin):
        from websockets.exceptions import ConnectionClosed
        from websockets.sync.client import connect as ws_connect
        with ws_connect(f"ws://127.0.0.1:{port}/api/mcp/bridge", origin=origin, open_timeout=5) as ws:
            with pytest.raises(ConnectionClosed) as info:
                ws.recv(timeout=5)
        return info.value.rcvd.code

    @pytest.mark.parametrize("bridge_on,origin,code", [
        (False, "http://127.0.0.1:{port}", 4404),
        (True, "http://evil.example", 4403),
    ])
    def test_refusal_is_a_close_frame(self, agent_app, bridge_on, origin, code):
        env = agent_app("open", bridge=bridge_on)
        with serve_app(env.app, log_level="error") as port:
            assert self._close_code(port, origin.format(port=port)) == code


class TestUiTools:
    def test_list_is_static_and_annotated(self, agent_app):
        env = agent_app("open")
        token = env.token(env.login())
        tools = {t["name"]: t for t in env.rpc(token, "tools/list").json()["result"]["tools"]}
        read_only = {"ui_get_gallery_view", "ui_get_selection", "ui_get_context"}
        for tool in UI_TOOLS:
            listed = tools[tool.name]
            assert listed["annotations"]["readOnlyHint"] is (tool.name in read_only), tool.name
            assert listed["annotations"]["destructiveHint"] is False
            assert listed["_meta"]["facet/untrusted_content"] is True, tool.name
            assert tool.name == tool.name.lower() and len(tool.name) < 40
            assert "tab_id" in listed["inputSchema"]["properties"]
        assert "ui_show_culling_group" in tools and "ui_show_culling_plan" in tools

    @pytest.mark.parametrize("tool,args", [
        ("ui_navigate", {"route": "/admin"}),
        ("ui_navigate", {"route": "/stats", "extra": 1}),
        ("ui_set_gallery_filters", {"patch": {"not_a_filter": 1}}),
        ("ui_set_gallery_filters", {"patch": {"sort": "nope"}}),
        ("ui_set_gallery_filters", {"patch": {"show_rejected": True, "favorites_only": True}}),
        ("ui_get_gallery_view", {"limit": 500}),
        ("ui_select_photos", {}),
        ("ui_select_photos", {"paths": ["a"], "select_view": True}),
        ("ui_select_photos", {"select_view": True, "mode": "remove"}),
        ("ui_show_culling_group", {"type": "weird", "group_id": 1}),
        ("ui_show_culling_group", {"type": "burst", "group_id": -1}),
        ("ui_show_culling_plan", {"request": {}}),
        ("ui_show_culling_plan", {"plan_digest": "abc"}),
        ("ui_show_culling_plan", {"plan_digest": "abc", "request": {}, "focus": 0}),
        ("ui_show_culling_plan", {"plan_digest": "abc", "request": {"group_by": "weird"}}),
        ("ui_suggest_culling", {}),
        ("ui_suggest_culling", {"photos": [{"path": "a", "action": "maybe", "reason": "x"}]}),
    ])
    def test_invalid_args_never_reach_the_tab(self, agent_app, fake_tab, tool, args):
        env = agent_app("open")
        tab = fake_tab(env, None)
        result = env.call(env.token(env.login()), tool, args)
        assert result["ok"] is False and result["error"] == "invalid_input"
        assert tab.calls == []

    def test_set_filters_forwards_only_set_keys_and_null_clears(self, agent_app, fake_tab):
        env = agent_app("open")
        tab = fake_tab(env, None)
        result = env.call(env.token(env.login()), "ui_set_gallery_filters", {
            "patch": {"min_aesthetic": 8, "camera": None, "sort": "aesthetic"}})
        assert result["ok"] is True
        assert tab.calls[0]["args"] == {
            "patch": {"min_aesthetic": 8, "camera": None, "sort": "aesthetic"}, "replace": False}

    def test_select_view_and_paths_forwarding(self, agent_app, fake_tab):
        env = agent_app("open")
        tab = fake_tab(env, None)
        token = env.token(env.login())
        assert env.call(token, "ui_select_photos", {"select_view": True})["ok"] is True
        assert env.call(token, "ui_select_photos", {"paths": ["/a.jpg"], "mode": "add"})["ok"] is True
        assert [c["args"] for c in tab.calls] == [
            {"select_view": True, "mode": "replace"}, {"paths": ["/a.jpg"], "select_view": False, "mode": "add"}]

    def test_show_culling_group_forwards_type_and_id(self, agent_app, fake_tab):
        env = agent_app("open")
        tab = fake_tab(env, None)
        result = env.call(env.token(env.login()), "ui_show_culling_group", {"type": "bracket", "group_id": 4})
        assert result["ok"] is True and tab.calls[0]["args"] == {"type": "bracket", "group_id": 4}

    def test_a_huge_culling_block_is_cut_with_true_counts_and_flagged(self):
        from api.agent.limits import encoded_size
        from api.agent.tools_ui import fit_culling
        changed = [{"type": "burst", "group_id": n, "number": n, "keep_paths": [f"/k/{n}/{'a' * 80}.jpg"],
                    "reject_paths": [f"/r/{n}/{'b' * 80}.jpg" for _ in range(5)]} for n in range(1, 301)]
        culling = {"plan_digest": "d", "groups_total": 400, "confirmed": list(range(1, 50)),
                   "pending": list(range(50, 90)), "changed": changed, "untouched": 260, "truncated": False}
        result = {"ok": True, "data": {"route": "/culling", "culling": culling}}
        fit_culling(result, 20000)
        assert encoded_size(result) <= 20000
        assert culling["truncated"] is True and culling["groups_total"] == 400 and culling["untouched"] == 260
        assert culling["changed_count"] == 300 and culling["confirmed_count"] == 49 and culling["pending_count"] == 40
        assert 0 < len(culling["changed"]) < 300 and culling["changed"] == changed[:len(culling["changed"])]
        small = {"ok": True, "data": {"culling": {"plan_digest": "d", "confirmed": [1], "changed": [], "truncated": False}}}
        fit_culling(small, 20000)
        assert small["data"]["culling"]["truncated"] is False and "changed_count" not in small["data"]["culling"]

    def test_a_huge_suggestions_list_is_halved_and_counted(self):
        from api.agent.limits import encoded_size
        from api.agent.tools_ui import fit_culling
        opened = [{"path": f"/p/{n}/{'a' * 120}.jpg", "action": "reject"} for n in range(300)]
        culling = {"plan_digest": "d", "groups_total": 4, "confirmed": [], "pending": [], "changed": [],
                   "suggestions_open": opened, "suggestions_accepted": 2, "suggestions_total": 300,
                   "truncated": False}
        result = {"ok": True, "data": {"culling": culling}}
        fit_culling(result, 8000)
        assert encoded_size(result) <= 8000
        assert culling["truncated"] is True and culling["suggestions_open_count"] == 300
        assert 0 < len(culling["suggestions_open"]) < 300 and culling["suggestions_total"] == 300
        assert culling["suggestions_open"] == opened[:len(culling["suggestions_open"])]

    def test_the_capped_plan_flag_is_never_confused_with_a_cut_list(self):
        from api.agent.tools_ui import fit_culling
        from api.agent.ui_tools import UI_TOOLS
        capped = {"ok": True, "data": {"culling": {"plan_digest": "d", "confirmed": [1], "changed": [],
                                                   "plan_truncated": True}}}
        fit_culling(capped, 20000)
        culling = capped["data"]["culling"]
        assert culling["plan_truncated"] is True and "truncated" not in culling
        text = next(t.description for t in UI_TOOLS if t.name == "ui_get_context")
        assert "plan_truncated" in text and "{plan_digest, groups_total, confirmed, pending, changed, untouched, plan_truncated}" in text

    def test_show_culling_plan_forwards_digest_request_and_focus(self, agent_app, fake_tab):
        env = agent_app("open")
        tab = fake_tab(env, None)
        request = {"group_by": "burst", "strictness": 40, "keep_paths": ["/a.jpg"]}
        result = env.call(env.token(env.login()), "ui_show_culling_plan",
                          {"plan_digest": "abc", "request": request, "focus": 2})
        assert result["ok"] is True
        sent = tab.calls[0]["args"]
        assert sent["plan_digest"] == "abc" and sent["focus"] == 2
        assert sent["request"]["group_by"] == "burst" and sent["request"]["keep_paths"] == ["/a.jpg"]

    def test_suggest_culling_forwards_suggestions_and_notes(self, agent_app, fake_tab):
        env = agent_app("open")
        tab = fake_tab(env, None)
        photo = {"path": "/a.jpg", "action": "keep", "reason": "sharper eyes"}
        result = env.call(env.token(env.login()), "ui_suggest_culling",
                          {"photos": [photo], "groups": [{"path": "/a.jpg", "note": "tight call"}], "replace": True})
        assert result["ok"] is True
        assert tab.calls[0]["args"] == {"photos": [photo], "groups": [{"path": "/a.jpg", "note": "tight call"}],
                                        "replace": True}

    def test_tab_plan_refusals_pass_through(self, agent_app, fake_tab):
        env = agent_app("open")
        for code in ("unsaved_decisions", "plan_changed", "plan_load_failed", "stack_mode_active", "navigation_refused"):
            fake_tab(env, None, tab_id=f"t-{code}", reply=lambda call, code=code: {
                "ok": False, "error": code, "message": "no"})
            result = env.call(env.token(env.login()), "ui_show_culling_plan",
                              {"plan_digest": "abc", "request": {}, "tab_id": f"t-{code}"})
            assert result["error"] == code

    def test_get_context_is_one_empty_frame_and_the_tab_answer_passes_through(self, agent_app, fake_tab):
        env = agent_app("open")
        body = {"route": "/photo", "query_path": "a.jpg", "selection": {"scope": "paths", "count": 0},
                "gallery": None, "mounted_actions": [], "level": "readonly", "actions": []}
        tab = fake_tab(env, None, reply=lambda call: {"ok": True, "data": body})
        result = env.call(env.token(env.login()), "ui_get_context")
        assert result["ok"] is True
        data = result["data"]
        assert {k: v for k, v in data.items() if k not in ("actions", "level")} == \
            {k: v for k, v in body.items() if k not in ("actions", "level")}
        assert data["level"] == "readonly" and data["actions"] and all(row["tools"] for row in data["actions"])
        assert [(c["tool"], c["args"]) for c in tab.calls] == [("ui_get_context", {})]

    def test_ui_tools_need_only_readonly(self, agent_app, fake_tab):
        env = agent_app("legacy")
        fake_tab(env, jwt_of(env.login()))
        token = env.token(env.login())
        assert env.call(token, "ui_open_photo", {"path": "/a.jpg"})["ok"] is True

    def test_status_lists_tabs(self, agent_app, fake_tab):
        env = agent_app("multi")
        token = env.token(env.login("alice"))
        assert env.call(token, "status")["data"]["tabs"] == []
        fake_tab(env, jwt_of(env.login("alice")), "alice-tab", route="/albums")
        fake_tab(env, jwt_of(env.login("bob")), "bob-tab")
        data = env.call(token, "status")["data"]
        assert [t["tab_id"] for t in data["tabs"]] == ["alice-tab"]
        assert data["tabs"][0]["route"] == "/albums" and data["tabs"][0]["tools_current"] is True
        assert data["ui_tools_version"] == tools_version()


class TestLiveSdkClient:
    """Real MCP client -> /mcp -> bridge -> a fake WebSocket tab, all under uvicorn."""

    def test_sdk_client_drives_a_websocket_tab(self, agent_app):
        import httpx2
        import websockets
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        env = agent_app("legacy")
        jwt = jwt_of(env.login())
        token = env.token(env.login())
        with serve_app(env.app, log_level="warning", ws="auto") as port:
            seen = []

            async def tab(ready):
                async with websockets.connect(f"ws://127.0.0.1:{port}/api/mcp/bridge",
                                              origin=f"http://127.0.0.1:{port}") as ws:
                    await ws.send(json.dumps(auth_frame(jwt)))
                    assert json.loads(await ws.recv())["type"] == "ready"
                    ready.set()
                    async for raw in ws:
                        frame = json.loads(raw)
                        if frame["type"] == "call":
                            seen.append(frame)
                            await ws.send(json.dumps({"type": "result", "id": frame["id"], "ok": True,
                                                      "data": {"total": 3}}))
                            return

            async def drive():
                ready = asyncio.Event()
                tab_task = asyncio.create_task(tab(ready))
                await asyncio.wait_for(ready.wait(), 10)
                async with httpx2.AsyncClient(headers={"Authorization": "Bearer " + token}) as http:
                    async with streamable_http_client(f"http://127.0.0.1:{port}/mcp", http_client=http) as streams:
                        async with ClientSession(streams[0], streams[1]) as session:
                            await session.initialize()
                            called = await session.call_tool("ui_get_gallery_view", {"limit": 5})
                await asyncio.wait_for(tab_task, 10)
                return json.loads(called.content[0].text)

            envelope = asyncio.run(drive())
        assert envelope["ok"] is True and envelope["data"] == {"total": 3}
        assert seen[0]["tool"] == "ui_get_gallery_view" and seen[0]["args"] == {"limit": 5}


class TestBroadcast:
    @staticmethod
    def _frames(tab):
        return [m for m in tab.inbox if m.get("type") == "changed"]

    @staticmethod
    def _wait(tab, count, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and len(TestBroadcast._frames(tab)) < count:
            time.sleep(0.05)
        return TestBroadcast._frames(tab)

    FRAME = {"type": "changed", "tool": "batch_reject", "paths": ["/a"], "count": 1}

    def test_every_tab_of_the_user_gets_the_frame(self, agent_app, fake_tab):
        env = agent_app("open")
        jwt = jwt_of(env.login())
        first, second = fake_tab(env, jwt, "tab-a"), fake_tab(env, jwt, "tab-b")
        asyncio.run(env.app.state.tab_registry.broadcast("_anonymous", self.FRAME))
        assert self._wait(first, 1) == [self.FRAME] and self._wait(second, 1) == [self.FRAME]

    def test_exclude_tab_id_skips_only_that_tab(self, agent_app, fake_tab):
        env = agent_app("open")
        jwt = jwt_of(env.login())
        caller, other = fake_tab(env, jwt, "tab-a"), fake_tab(env, jwt, "tab-b")
        asyncio.run(env.app.state.tab_registry.broadcast("_anonymous", self.FRAME, exclude_tab_id="tab-a"))
        assert self._wait(other, 1) == [self.FRAME]
        time.sleep(0.4)
        assert self._frames(caller) == []

    def test_a_broken_connection_never_raises_or_blocks_the_others(self, agent_app, fake_tab):
        env = agent_app("open")
        jwt = jwt_of(env.login())
        broken, healthy = fake_tab(env, jwt, "tab-a"), fake_tab(env, jwt, "tab-b")
        registry = env.app.state.tab_registry
        conn = next(c for c in registry.tabs_for("_anonymous") if c.tab_id == "tab-a")

        original = conn.send

        async def explode(frame):
            if frame.get("type") == "changed":
                raise RuntimeError("socket gone")
            await original(frame)

        conn.send = explode
        asyncio.run(registry.broadcast("_anonymous", self.FRAME))
        assert self._wait(healthy, 1) == [self.FRAME]
        assert self._frames(broken) == []

    def test_no_tabs_is_a_no_op(self, agent_app):
        env = agent_app("open")
        asyncio.run(env.app.state.tab_registry.broadcast("nobody", self.FRAME))
