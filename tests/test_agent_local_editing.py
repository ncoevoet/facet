"""``viewer.trusted_local_editing`` through the agent layer: a Full-editing token on a password-less install.

[REAL] ``agent_app`` (real auth chain, real lifespan, real routes). The "local" client is the same
app addressed as a browser on the machine would (loopback peer, ``Host: localhost``); the "remote"
client is the same app addressed from the LAN. Only the scan subprocess boundary is replaced.

Tests marked REGRESSION GUARD pass before and after the change; they pin a refusal that must stay.
"""

import importlib
import subprocess
import time
from collections import deque
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api import config as api_config
from api.agent import tokens
from tests.conftest import AGENT_DIR, AgentEnv, agent_db

scan = importlib.import_module("api.routers.scan")
CONFIGURED = [AGENT_DIR + "scan-a/"]
PHOTO = AGENT_DIR + "local-edit.jpg"
LOCAL = {"base_url": "http://localhost", "client": ("127.0.0.1", 5000)}
FORWARDED = {"X-Forwarded-For": "203.0.113.9"}
LOCAL_ONLY = ("Agent tokens on an open install can only be managed from the computer running Facet; "
              "set viewer.password to manage them from another machine")


class FakeProc:
    pid = 4242
    stdout = iter(())


class HostClient(TestClient):
    """A ``TestClient`` whose WebSocket handshakes carry the base URL's Host (the stock one sends ``testserver``)."""

    ws_headers: dict = {}

    def websocket_connect(self, url, subprotocols=None, **kwargs):
        kwargs["headers"] = {"host": self.base_url.netloc.decode(), **self.ws_headers, **kwargs.get("headers", {})}
        return super().websocket_connect(url, subprotocols, **kwargs)


@pytest.fixture()
def build(agent_app):
    """``build(opt_in=True, **mcp)`` -> ``(local, remote)`` AgentEnvs on one open-install app."""
    def make(opt_in=True, **mcp):
        env = agent_app("open", **mcp)
        api_config.VIEWER_CONFIG["trusted_local_editing"] = opt_in
        api_config.VIEWER_CONFIG.setdefault("features", {}).pop("show_scan_button", None)
        local = AgentEnv(HostClient(env.app, **LOCAL), "open")
        remote = AgentEnv(HostClient(env.app, base_url="http://nas.lan", client=("192.0.2.7", 5000)), "open")
        return local, remote
    return make


@pytest.fixture()
def photo(seed_photos_prefix):
    seed_photos_prefix(AGENT_DIR, [{"path": PHOTO, "filename": "local-edit.jpg", "star_rating": 0,
                                    "is_favorite": 0, "is_rejected": 0}])
    agent_db("DELETE FROM user_preferences WHERE photo_path LIKE ?", AGENT_DIR + "%")
    yield PHOTO
    agent_db("DELETE FROM user_preferences WHERE photo_path LIKE ?", AGENT_DIR + "%")


@pytest.fixture()
def spawned(monkeypatch):
    calls = []
    monkeypatch.setattr(scan, "subprocess", SimpleNamespace(
        Popen=lambda cmd, **kw: (calls.append(cmd), FakeProc())[1],
        SubprocessError=subprocess.SubprocessError, PIPE=-1, STDOUT=-2))
    monkeypatch.setattr(scan, "_read_scan_output", lambda proc: None)
    monkeypatch.setattr(scan, "get_all_scan_directories", lambda: list(CONFIGURED))
    monkeypatch.setattr(scan, "_library_job_conflict_detail", lambda: None)
    for key, value in (("running", False), ("kind", None), ("process", None), ("started_at", None),
                       ("directories", []), ("exit_code", None), ("progress", None),
                       ("output_lines", deque(maxlen=500))):
        monkeypatch.setitem(scan._scan_state, key, value)
    return calls


def edition_token(local):
    return local.token(local.login(), "edition")


def test_mint_edition_on_open_install_requires_trusted_local(build):
    local, remote = build()
    assert local.mint(local.login(), "edition").json()["level"] == "edition"
    refused = remote.mint(remote.login(), "edition")
    assert refused.status_code == 403 and refused.json()["detail"] == LOCAL_ONLY
    assert len(tokens.list_tokens("_anonymous")) == 1
    assert local.mint(local.login(), "edition").status_code == 200


def test_mint_edition_is_readonly_when_the_opt_in_is_off(build):
    # REGRESSION GUARD: passes before and after.
    local, _ = build(opt_in=False)
    assert local.mint(local.login(), "edition").json()["level"] == "readonly"


def test_mint_edition_from_a_forwarded_local_request_is_refused(build):
    local, _ = build()
    headers = {**local.login(), **FORWARDED}
    refused = local.mint(headers, "edition")
    assert refused.status_code == 403 and refused.json()["detail"] == LOCAL_ONLY
    assert tokens.list_tokens("_anonymous") == []


def test_a_local_edition_token_writes_and_the_row_changes(build, photo):
    local, _ = build()
    token = edition_token(local)
    result = local.call(token, "set_rating", {"paths": [photo], "rating": 4})
    assert result["ok"], result
    assert agent_db("SELECT star_rating FROM photos WHERE path = ?", photo) == [(4,)] or agent_db(
        "SELECT rating FROM user_preferences WHERE photo_path = ?", photo) == [(4,)]


def test_the_same_token_with_a_forwarding_header_is_readonly(build, photo):
    # REGRESSION GUARD: passes before and after.
    local, _ = build()
    token = edition_token(local)
    refused = local.rpc(token, "tools/call", {"name": "set_rating", "arguments": {"paths": [photo], "rating": 4}},
                        headers=FORWARDED).json()["result"]["content"][0]["text"]
    assert "forbidden_level" in refused


def test_the_same_token_from_a_remote_peer_is_readonly(build, photo):
    # REGRESSION GUARD: passes before and after.
    local, remote = build()
    token = edition_token(local)
    assert remote.call(token, "set_rating", {"paths": [photo], "rating": 4})["error"] == "forbidden_level"


def test_a_token_less_post_stays_401(build):
    # REGRESSION GUARD: passes before and after.
    local, _ = build()
    assert local.rpc(None, "tools/list").status_code == 401


def test_the_opt_in_going_off_makes_the_very_next_call_readonly(build, photo):
    local, _ = build()
    token = edition_token(local)
    assert local.call(token, "set_rating", {"paths": [photo], "rating": 4})["ok"]
    api_config.VIEWER_CONFIG["trusted_local_editing"] = False
    assert local.call(token, "set_rating", {"paths": [photo], "rating": 4})["error"] == "forbidden_level"


def test_any_password_lowers_the_token_and_clearing_it_revives_it(build, photo):
    local, _ = build()
    token = edition_token(local)
    row = tokens.list_tokens("_anonymous")[0]
    cfg = api_config.VIEWER_CONFIG
    cfg["edition_password"] = "ed-pw"
    assert local.call(token, "set_rating", {"paths": [photo], "rating": 4})["error"] == "forbidden_level"
    cfg["edition_password"] = ""
    cfg["password"] = "view-pw"
    assert local.rpc(token, "tools/list").status_code == 401
    cfg["password"] = ""
    assert local.call(token, "set_rating", {"paths": [photo], "rating": 4})["ok"]
    after = tokens.list_tokens("_anonymous")[0]
    assert {k: v for k, v in after.items() if k != "last_used_at"} == {k: v for k, v in row.items() if k != "last_used_at"}


def test_list_albums_through_the_local_agent_matches_the_browser(build):
    # PARITY GUARD: the agent's signed claim carries no ``sub`` so ``user_id`` is None, like the
    # token-less open-install browser, and it must see the browser's albums. Passes before (the
    # call was anonymous) and after (it is signed).
    local, _ = build()
    created = local.client.post("/api/albums", json={"name": "Parity"})
    assert created.status_code == 200, created.text
    try:
        browser = [a["name"] for a in local.client.get("/api/albums").json()["albums"]]
        agent = local.call(edition_token(local), "list_albums")
        assert agent["ok"] and "Parity" in browser
        assert [a["name"] for a in agent["data"]["rows"]] == browser
    finally:
        local.client.delete(f"/api/albums/{created.json()['id']}")


def test_local_agent_request_can_start_a_scan_without_flag(build, spawned):
    local, _ = build()
    token = edition_token(local)
    assert {"start_scan", "scan_status"} <= local.tool_names(token)
    done = local.call(token, "start_scan", {"directories": CONFIGURED})
    assert done["ok"], done
    assert len(spawned) == 1


def test_scan_tools_are_listed_only_to_a_local_edition_grant(build):
    local, remote = build()
    token = edition_token(local)
    assert {"start_scan", "scan_status"} <= local.tool_names(token)
    # REGRESSION GUARD half: the same token from the LAN, and a readonly token, never see them.
    assert not {"start_scan", "scan_status"} & remote.tool_names(token)
    assert not {"start_scan", "scan_status"} & local.tool_names(local.token(local.login(), "readonly"))


def test_a_forwarded_scan_call_is_refused_and_spawns_nothing(build, spawned):
    # REGRESSION GUARD: passes before and after.
    local, remote = build()
    token = edition_token(local)
    assert remote.call(token, "start_scan", {"directories": CONFIGURED})["error"] in ("forbidden_level", "feature_disabled")
    assert spawned == []


def test_the_opt_in_off_refuses_the_scan_tool(build, spawned):
    # REGRESSION GUARD: passes before and after.
    local, _ = build(opt_in=False)
    token = local.token(local.login(), "edition")
    assert local.call(token, "start_scan", {"directories": CONFIGURED})["error"] in ("forbidden_level", "feature_disabled")
    assert spawned == []


def test_delete_tools_stay_behind_allow_destructive(build):
    # REGRESSION GUARD: passes before and after.
    local, _ = build()
    assert "delete_photos" not in local.tool_names(edition_token(local))


def test_the_trusted_local_human_scan_status_is_allowed_and_a_forwarded_one_is_not(build):
    local, remote = build()
    headers = local.login()
    assert local.client.get("/api/scan/status", headers=headers).status_code == 200
    assert local.client.get("/api/scan/status", headers={**headers, **FORWARDED}).status_code == 403
    assert remote.client.get("/api/scan/status", headers=remote.login()).status_code == 403


# ---------------------------------------------------------------- bridge

def _level_of_tabs(env):
    registry = env.app.state.tab_registry
    return [t.level for t in registry.tabs_for("_anonymous")]


def _wait(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def test_trusted_local_tab_registers_at_edition(build, fake_tab):
    local, _ = build()
    fake_tab(local, None, origin="http://localhost")
    assert _level_of_tabs(local) == ["edition"]
    registry = local.app.state.tab_registry
    assert len(registry.tabs_for("_anonymous", "edition")) == 1


def test_a_tab_is_demoted_on_the_first_ping_after_the_opt_in_goes_off(build, fake_tab):
    local, _ = build()
    fake_tab(local, None, origin="http://localhost")
    assert _level_of_tabs(local) == ["edition"]
    api_config.VIEWER_CONFIG["trusted_local_editing"] = False
    assert _wait(lambda: _level_of_tabs(local) == ["readonly"])


@pytest.mark.parametrize("via", ["lan", "forwarded"])
def test_untrusted_anonymous_tab_stays_readonly_and_unreachable(build, fake_tab, via):
    local, remote = build()
    if via == "lan":
        tab_env, origin = remote, "http://nas.lan"
    else:
        tab_env, origin = local, "http://localhost"
        local.client.ws_headers = FORWARDED
    fake_tab(tab_env, None, origin=origin)
    assert _level_of_tabs(tab_env) == ["readonly"]
    registry = tab_env.app.state.tab_registry
    assert registry.tabs_for("_anonymous", "edition") == []
    reach, out_of_reach = registry.reach_counts("_anonymous", "edition", "edition")
    assert reach == [] and out_of_reach == 1
    # The edition token a local agent holds reaches no tab: a UI tool finds none.
    unreached = local.call(edition_token(local), "ui_get_context")
    assert unreached["ok"] is False and unreached["error"] == "no_tab", unreached


def test_a_readonly_token_minted_before_the_opt_in_reaches_the_local_edition_tab(build, fake_tab):
    local, _ = build(opt_in=False)
    readonly = local.token(local.login(), "readonly")
    api_config.VIEWER_CONFIG["trusted_local_editing"] = True
    fake_tab(local, None, origin="http://localhost")
    assert _level_of_tabs(local) == ["edition"]
    result = local.call(readonly, "ui_get_context")
    assert result.get("error") != "no_tab", result


def test_guard_a_lan_readonly_token_never_reaches_the_local_edition_tab(build, fake_tab):
    local, remote = build()
    fake_tab(local, None, origin="http://localhost")
    result = remote.call(local.token(local.login(), "readonly"), "ui_get_context")
    assert result["ok"] is False and result["error"] == "no_tab"
    assert "higher level" in result["message"] and "non-local" in result["message"], result


@pytest.mark.parametrize("claims", [
    {"mcp": True, "mcp_local": True, "edition": True, "sub": "_anonymous"},
    {"mcp": True, "mcp_local": True, "edition": False},
    {"mcp": True, "mcp_local": "true", "edition": True},
    {"mcp": True, "edition": True},
    {"mcp_local": True, "edition": True},
])
def test_from_payload_only_honours_the_exact_signed_shape(build, claims):
    local, remote = build()
    from api import auth
    tok = auth.create_access_token({"role": "user", **claims})
    response = remote.client.get("/api/scan/status", headers={"Authorization": "Bearer " + tok})
    assert response.status_code == 403


def test_a_lan_replay_of_a_local_stream_token_is_refused(build, monkeypatch):
    for key, value in (("running", False), ("directories", []), ("exit_code", None), ("progress", None),
                       ("started_at", None), ("output_lines", deque(maxlen=500))):
        monkeypatch.setitem(scan._scan_state, key, value)
    local, remote = build()
    token = local.client.get("/api/scan/stream_token").json()["token"]
    assert local.client.get("/api/scan/stream", params={"token": token, "lines": 1}).status_code == 200
    assert remote.client.get("/api/scan/stream", params={"token": token, "lines": 1}).status_code == 403


def test_a_lan_replay_of_a_local_stream_token_is_refused_with_the_scan_button_on(build, monkeypatch):
    for key, value in (("running", False), ("directories", ["/local-only-dir"]), ("exit_code", None),
                       ("progress", None), ("started_at", None), ("output_lines", deque(["local-only line"], maxlen=500))):
        monkeypatch.setitem(scan._scan_state, key, value)
    local, remote = build()
    token = local.client.get("/api/scan/stream_token").json()["token"]
    api_config.VIEWER_CONFIG["features"]["show_scan_button"] = True
    replay = remote.client.get("/api/scan/stream", params={"token": token, "lines": 1})
    assert replay.status_code == 403
    assert "local-only line" not in replay.text
    assert local.client.get("/api/scan/stream", params={"token": token, "lines": 1}).status_code == 200


def test_setting_a_password_closes_an_open_trusted_local_stream(build, monkeypatch):
    import json

    import httpx
    from api.auth import hash_password
    from tests.conftest import serve_app

    for key, value in (("running", True), ("directories", ["/local-only-dir"]), ("exit_code", None),
                       ("progress", None), ("started_at", None), ("output_lines", deque(["local-only line"], maxlen=500))):
        monkeypatch.setitem(scan._scan_state, key, value)
    local, _ = build()
    token = local.client.get("/api/scan/stream_token").json()["token"]
    with serve_app(local.client.app, access_log=False) as port:
        with httpx.stream("GET", f"http://127.0.0.1:{port}/api/scan/stream", params={"token": token}, timeout=5) as response:
            assert response.status_code == 200
            lines = response.iter_lines()
            assert json.loads(next(lines).removeprefix("data: "))["output"] == ["local-only line"]
            assert next(lines) == ""
            api_config.VIEWER_CONFIG["edition_password"] = hash_password("now-protected")
            assert list(lines) == [], "a password ends the trusted-local boundary, so the stream must close"
