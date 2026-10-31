"""An open install with ``viewer.edition_password`` set: a Full-editing token for a local assistant (#387).

[REAL] ``agent_app`` (real auth chain, real lifespan, real routes), set to an open install (no
``viewer.password``) carrying an edition password. The "local" client is the app addressed as a
browser on the machine would; the "remote" client is the same app from the LAN. Only the scan
subprocess boundary is replaced.

Tests marked REGRESSION GUARD pass before and after the change; they pin a refusal that must stay.
"""

import importlib
import subprocess
from collections import deque
from dataclasses import replace
from types import SimpleNamespace

import pytest

from api import config as api_config
from api.agent import tokens
from api.auth import EDITION_PASSWORD_KEY, password_generation
from tests.conftest import AGENT_DIR, AgentEnv, agent_db
from tests.test_agent_local_editing import FORWARDED, LOCAL, FakeProc, HostClient

scan = importlib.import_module("api.routers.scan")
CONFIGURED = [AGENT_DIR + "scan-a/"]
PHOTO = AGENT_DIR + "open-edition.jpg"
EDITION_PW = "open-edition-pw"


@pytest.fixture()
def build(agent_app):
    """``build(**mcp)`` -> ``(local, remote)`` AgentEnvs on one open install with an edition password."""
    def make(**mcp):
        env = agent_app("open", **mcp)
        cfg = api_config.VIEWER_CONFIG
        cfg["edition_password"] = EDITION_PW
        cfg["trusted_local_editing"] = False
        cfg.setdefault("features", {}).pop("show_scan_button", None)
        local = AgentEnv(HostClient(env.app, **LOCAL), "open")
        remote = AgentEnv(HostClient(env.app, base_url="http://nas.lan", client=("192.0.2.7", 5000)), "open")
        return local, remote
    return make


@pytest.fixture()
def photo(seed_photos_prefix):
    seed_photos_prefix(AGENT_DIR, [{"path": PHOTO, "filename": "open-edition.jpg", "star_rating": 0,
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


def peer(env, base_url, address):
    """The same app as ``env``, reached at ``base_url`` from the TCP peer ``address``."""
    return AgentEnv(HostClient(env.app, base_url=base_url, client=(address, 5000)), "open")


def edition_session(env):
    """Bearer headers for a session that has logged in with the edition password."""
    env.client.post("/api/auth/login", json={"password": ""})
    resp = env.client.post("/api/auth/edition/login", json={"password": EDITION_PW})
    assert resp.status_code == 200, resp.text
    env.client.cookies.clear()
    return {"Authorization": "Bearer " + resp.json()["access_token"]}


def edition_token(env):
    return env.token(edition_session(env), "edition")


def rate(env, token, photo):
    return env.call(token, "set_rating", {"paths": [photo], "rating": 4})


# ---------------------------------------------------------------- minting

def test_an_edition_session_mints_an_edition_token(build):
    local, remote = build()
    assert local.mint(edition_session(local), "edition").json()["level"] == "edition"
    # The session is what grants it, not the machine: an edition login on the LAN may mint too.
    assert remote.mint(edition_session(remote), "edition").json()["level"] == "edition"


def test_a_viewer_session_still_mints_readonly(build):
    # REGRESSION GUARD: passes before and after.
    local, _ = build()
    assert local.mint(local.login(), "edition").json()["level"] == "readonly"


def test_a_password_less_install_still_mints_readonly(build):
    # REGRESSION GUARD: open with no passwords and the opt-in off.
    local, _ = build()
    api_config.VIEWER_CONFIG["edition_password"] = ""
    assert local.mint(local.login(), "edition").json()["level"] == "readonly"


# ---------------------------------------------------------------- /mcp locality

def test_a_local_edition_token_writes(build, photo):
    local, _ = build()
    result = rate(local, edition_token(local), photo)
    assert result["ok"], result
    assert agent_db("SELECT star_rating FROM photos WHERE path = ?", photo) == [(4,)]


def test_the_token_minted_on_the_lan_writes_when_used_locally(build, photo):
    local, remote = build()
    assert rate(local, edition_token(remote), photo)["ok"]


def test_the_same_token_from_a_lan_peer_is_readonly(build, photo):
    local, remote = build()
    token = edition_token(local)
    assert rate(remote, token, photo)["error"] == "forbidden_level"
    assert agent_db("SELECT star_rating FROM photos WHERE path = ?", photo) == [(0,)]


def test_the_same_token_through_a_proxy_is_readonly(build, photo):
    local, _ = build()
    token = edition_token(local)
    refused = local.rpc(token, "tools/call", {"name": "set_rating", "arguments": {"paths": [photo], "rating": 4}},
                        headers=FORWARDED).json()["result"]["content"][0]["text"]
    assert "forbidden_level" in refused


def test_a_readonly_token_stays_readonly_locally(build, photo):
    # REGRESSION GUARD: passes before and after.
    local, _ = build()
    token = local.token(edition_session(local), "readonly")
    assert rate(local, token, photo)["error"] == "forbidden_level"


# ---------------------------------------------------------------- password lifecycle

def test_changing_the_edition_password_lowers_the_token_for_good(build, photo):
    local, _ = build()
    token = edition_token(local)
    assert rate(local, token, photo)["ok"]
    api_config.VIEWER_CONFIG["edition_password"] = "rotated-pw"
    assert rate(local, token, photo)["error"] == "forbidden_level"
    # A fresh edition token under the new password works; the old one stays dead.
    api_config.VIEWER_CONFIG["edition_password"] = EDITION_PW
    fresh = edition_token(local)
    api_config.VIEWER_CONFIG["edition_password"] = "rotated-pw"
    assert rate(local, fresh, photo)["error"] == "forbidden_level"


def test_restoring_the_same_stored_password_revives_the_token(build, photo):
    local, _ = build()
    token = edition_token(local)
    stored = api_config.VIEWER_CONFIG["edition_password"]
    api_config.VIEWER_CONFIG["edition_password"] = "rotated-pw"
    assert rate(local, token, photo)["error"] == "forbidden_level"
    # The generation is a digest of the stored value, so only the very same stored value matches.
    api_config.VIEWER_CONFIG["edition_password"] = stored
    assert rate(local, token, photo)["ok"]


def test_removing_the_edition_password_lowers_the_token(build, photo):
    local, _ = build()
    token = edition_token(local)
    api_config.VIEWER_CONFIG["edition_password"] = ""
    assert rate(local, token, photo)["error"] == "forbidden_level"


def test_setting_a_viewer_password_kills_the_token(build):
    local, _ = build()
    token = edition_token(local)
    api_config.VIEWER_CONFIG["password"] = "view-pw"
    assert local.rpc(token, "tools/list").status_code == 401


def test_the_token_row_pins_the_edition_generation(build):
    local, _ = build()
    edition_token(local)
    row = agent_db("SELECT edition_gen, minted_level FROM mcp_tokens WHERE user_id = ?", tokens.OPEN_PRINCIPAL)
    assert row == [(password_generation(EDITION_PASSWORD_KEY), "edition")]


# ---------------------------------------------------------------- scanning

def test_scan_tools_still_need_show_scan_button(build, spawned):
    local, _ = build()
    token = edition_token(local)
    assert not {"start_scan", "scan_status"} & local.tool_names(token)
    assert local.call(token, "start_scan", {"directories": CONFIGURED})["error"] == "feature_disabled"
    assert spawned == []


def test_scan_tools_work_locally_with_show_scan_button(build, spawned):
    local, remote = build()
    api_config.VIEWER_CONFIG["features"]["show_scan_button"] = True
    token = edition_token(local)
    assert {"start_scan", "scan_status"} <= local.tool_names(token)
    assert not {"start_scan", "scan_status"} & remote.tool_names(token)
    done = local.call(token, "start_scan", {"directories": CONFIGURED})
    assert done["ok"], done
    assert len(spawned) == 1


# ---------------------------------------------------------------- tabs

def _tab_levels(env):
    return [t.level for t in env.app.state.tab_registry.tabs_for(tokens.OPEN_PRINCIPAL)]


def test_a_local_edition_token_drives_the_edition_tab(build, fake_tab):
    local, _ = build()
    session = edition_session(local)
    fake_tab(local, session["Authorization"].removeprefix("Bearer "), origin="http://localhost")
    assert _tab_levels(local) == ["edition"]
    result = local.call(local.token(session, "edition"), "ui_get_context")
    assert result.get("error") != "no_tab", result


def test_a_lan_use_of_the_token_never_reaches_the_edition_tab(build, fake_tab):
    local, remote = build()
    session = edition_session(local)
    fake_tab(local, session["Authorization"].removeprefix("Bearer "), origin="http://localhost")
    result = remote.call(local.token(session, "edition"), "ui_get_context")
    assert result["ok"] is False and result["error"] == "no_tab", result


# ---------------------------------------------------------------- the same-machine boundary itself
# The "remote" client above is refused by its Host alone; these pin each other half of the check.

def test_a_lan_peer_forging_a_local_host_is_readonly(build, photo, fake_tab):
    local, _ = build()
    forged = peer(local, "http://localhost", "192.0.2.7")
    session = edition_session(local)
    token = local.token(session, "edition")
    assert rate(forged, token, photo)["error"] == "forbidden_level"
    assert agent_db("SELECT star_rating FROM photos WHERE path = ?", photo) == [(0,)]
    fake_tab(local, session["Authorization"].removeprefix("Bearer "), origin="http://localhost")
    assert forged.call(token, "ui_get_context")["error"] == "no_tab"


def test_a_loopback_peer_with_a_foreign_origin_is_refused(build, photo):
    # A browser page on the same machine: the /mcp gate refuses any cross-origin request outright.
    local, _ = build()
    resp = local.rpc(edition_token(local), "tools/call",
                     {"name": "set_rating", "arguments": {"paths": [photo], "rating": 4}},
                     headers={"Origin": "http://evil.example"})
    assert resp.status_code == 403
    assert agent_db("SELECT star_rating FROM photos WHERE path = ?", photo) == [(0,)]


def test_a_loopback_peer_forwarding_for_loopback_is_readonly(build, photo):
    local, _ = build()
    refused = local.rpc(edition_token(local), "tools/call",
                        {"name": "set_rating", "arguments": {"paths": [photo], "rating": 4}},
                        headers={"X-Forwarded-For": "127.0.0.1"}).json()["result"]["content"][0]["text"]
    assert "forbidden_level" in refused
    assert agent_db("SELECT star_rating FROM photos WHERE path = ?", photo) == [(0,)]


def test_an_ipv4_mapped_loopback_peer_writes(build, photo):
    local, _ = build()
    mapped = peer(local, "http://localhost", "::ffff:127.0.0.1")
    assert rate(mapped, edition_token(local), photo)["ok"]


# ---------------------------------------------------------------- who may mint edition

def test_a_lan_viewer_session_never_mints_edition(build):
    _, remote = build()
    resp = remote.client.post("/api/mcp/tokens", json={"name": "test", "level": "edition"},
                              headers=remote.login())
    assert resp.status_code != 200 or resp.json()["level"] == "readonly", resp.text


def test_a_session_whose_edition_claim_went_stale_mints_readonly(build):
    local, _ = build()
    session = edition_session(local)
    api_config.VIEWER_CONFIG["edition_password"] = "rotated-pw"
    assert local.mint(session, "edition").json()["level"] == "readonly"


def test_a_token_minted_under_trusted_local_editing_stays_readonly_once_an_edition_password_is_set(build, photo):
    local, _ = build()
    api_config.VIEWER_CONFIG["edition_password"] = ""
    api_config.VIEWER_CONFIG["trusted_local_editing"] = True
    token = local.token(local.login(), "edition")
    assert rate(local, token, photo)["ok"]
    api_config.VIEWER_CONFIG["trusted_local_editing"] = False
    api_config.VIEWER_CONFIG["edition_password"] = EDITION_PW
    assert rate(local, token, photo)["error"] == "forbidden_level"


def test_a_row_minted_before_edition_generations_were_pinned_stays_readonly(build, photo):
    local, _ = build()
    token = edition_token(local)
    agent_db("UPDATE mcp_tokens SET edition_gen = '' WHERE user_id = ?", tokens.OPEN_PRINCIPAL)
    assert rate(local, token, photo)["error"] == "forbidden_level"


# ---------------------------------------------------------------- identity

def test_the_local_edition_grant_acts_as_the_edition_session(build):
    local, _ = build()
    token = edition_token(local)
    grant = tokens.verify(token)
    claims = replace(grant, local=True).resolve().jwt_claims()
    # The edition browser session signs ``_legacy``: sharing it keeps the undo history and
    # sidecar jobs, which are keyed by owner, in one list for the user and the assistant.
    assert claims["sub"] == tokens.LEGACY_PRINCIPAL and claims["edition"] is True
    assert "mcp_local" not in claims
    assert grant.edition_gen == password_generation(EDITION_PASSWORD_KEY)
