"""``start_scan`` / ``scan_status`` over /mcp: the route's own gates, a directory pre-check and no free spawn.

[REAL] ``agent_app`` (real auth chain) and the real scan router. Only the OS boundary is replaced: the
router's ``Popen``, its output reader, its configured-directory list and its job-conflict probe. The
Popen recorder is what proves a refused call spawned nothing.
"""

import asyncio
import importlib
import subprocess
from collections import deque
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api import auth as api_auth
from api import config as api_config
from api.agent import requirements
from tests.conftest import AGENT_DIR

scan = importlib.import_module("api.routers.scan")
CONFIGURED = [AGENT_DIR + "scan-a/", AGENT_DIR + "scan-b/"]


def spawner(spawned):
    """A stand-in for the router's ``subprocess`` name only (patching the real module would leak)."""
    return SimpleNamespace(Popen=lambda cmd, **kw: (spawned.append(cmd), FakeProc())[1],
                           SubprocessError=subprocess.SubprocessError, PIPE=-1, STDOUT=-2)


class FakeProc:
    pid = 4242
    stdout = iter(())


@pytest.fixture()
def world(agent_app, monkeypatch):
    spawned = []
    monkeypatch.setattr(scan, "subprocess", spawner(spawned))
    monkeypatch.setattr(scan, "_read_scan_output", lambda proc, cleanup=None: None)
    monkeypatch.setattr(scan, "get_all_scan_directories", lambda: list(CONFIGURED))
    monkeypatch.setattr(scan, "_library_job_conflict_detail", lambda: None)
    for key, value in (("running", False), ("kind", None), ("process", None), ("started_at", None),
                       ("directories", []), ("exit_code", None), ("progress", None),
                       ("output_lines", deque(maxlen=500))):
        monkeypatch.setitem(scan._scan_state, key, value)
    monkeypatch.setitem(api_config.VIEWER_CONFIG.setdefault("features", {}), "show_scan_button", True)
    env = agent_app("legacy")
    yield env, env.token(env.login(edition=True), "edition"), spawned


def test_flag_off_refuses_and_hides_nothing_is_spawned(world, monkeypatch):
    env, token, spawned = world
    monkeypatch.setitem(api_config.VIEWER_CONFIG["features"], "show_scan_button", False)
    for tool, args in (("start_scan", {"directories": CONFIGURED[:1]}), ("scan_status", {})):
        refused = env.call(token, tool, args)
        assert refused["error"] == "feature_disabled" and "show_scan_button" in refused["message"]
    assert spawned == []


def test_flag_off_unlists_the_tools(world, monkeypatch):
    env, token, _ = world
    assert {"start_scan", "scan_status"} <= env.tool_names(token)
    monkeypatch.setitem(api_config.VIEWER_CONFIG["features"], "show_scan_button", False)
    assert not {"start_scan", "scan_status"} & env.tool_names(token)


def test_an_unconfigured_directory_is_refused_before_anything_spawns(world):
    env, token, spawned = world
    refused = env.call(token, "start_scan", {"directories": [CONFIGURED[0], "/etc/"]})
    assert refused["error"] == "invalid_input" and "/etc/" in refused["message"]
    assert refused["configured_directories"] == CONFIGURED and spawned == []


def test_a_configured_directory_spawns_exactly_the_validated_command(world):
    env, token, spawned = world
    done = env.call(token, "start_scan", {"directories": [CONFIGURED[1]]})
    assert done["ok"] and done["data"]["pid"] == 4242
    assert len(spawned) == 1 and spawned[0][-1:] == [CONFIGURED[1]] and spawned[0][1] == scan.FACET_SCRIPT


def test_a_running_scan_is_a_conflict_and_spawns_nothing(world, monkeypatch):
    env, token, spawned = world
    monkeypatch.setitem(scan._scan_state, "running", True)
    refused = env.call(token, "start_scan", {"directories": CONFIGURED[:1]})
    assert refused["error"] == "conflict" and spawned == []


def test_status_caps_the_returned_lines(world, monkeypatch):
    env, token, _ = world
    monkeypatch.setitem(scan._scan_state, "output_lines", deque((f"line {i}" for i in range(120)), maxlen=500))
    data = env.call(token, "scan_status", {"lines": 50})["data"]
    assert len(data["output"]) == 50 and data["output"][-1] == "line 119"
    assert data["configured_directories"] == CONFIGURED and data["running"] is False
    assert env.call(token, "scan_status", {"lines": 0})["data"]["output"] == []
    assert env.call(token, "scan_status", {"lines": 51})["ok"] is False


def test_more_than_twenty_directories_are_refused(world):
    env, token, spawned = world
    refused = env.call(token, "start_scan", {"directories": [f"/d{i}/" for i in range(21)]})
    assert refused["ok"] is False and refused["error"] in ("too_large", "invalid_input")
    assert spawned == []


def test_a_readonly_key_cannot_see_or_call_the_scan_tools(world):
    env, _, spawned = world
    readonly = env.token(env.login(), "readonly")
    assert not {"start_scan", "scan_status"} & env.tool_names(readonly)
    assert env.call(readonly, "start_scan", {"directories": CONFIGURED[:1]})["error"] == "forbidden_level"
    assert spawned == []


def test_an_open_install_cannot_start_a_scan(agent_app, monkeypatch):
    spawned = []
    monkeypatch.setattr(scan, "subprocess", spawner(spawned))
    monkeypatch.setattr(scan, "get_all_scan_directories", lambda: list(CONFIGURED))
    monkeypatch.setitem(api_config.VIEWER_CONFIG.setdefault("features", {}), "show_scan_button", True)
    env = agent_app("open")
    token = env.token(env.login(), "readonly")
    assert env.call(token, "start_scan", {"directories": CONFIGURED[:1]})["error"] == "forbidden_level"
    assert spawned == []


def test_multi_user_needs_a_superadmin_not_just_an_admin(agent_app, monkeypatch):
    spawned = []
    monkeypatch.setattr(scan, "subprocess", spawner(spawned))
    monkeypatch.setattr(scan, "_read_scan_output", lambda proc, cleanup=None: None)
    monkeypatch.setattr(scan, "get_all_scan_directories", lambda: list(CONFIGURED))
    monkeypatch.setattr(scan, "_library_job_conflict_detail", lambda: None)
    monkeypatch.setitem(scan._scan_state, "running", False)
    monkeypatch.setitem(api_config.VIEWER_CONFIG.setdefault("features", {}), "show_scan_button", True)
    env = agent_app("multi")
    admin = env.token(env.login("root"), "edition")
    assert env.call(admin, "start_scan", {"directories": CONFIGURED[:1]})["error"] == "forbidden_level"
    assert "start_scan" not in env.tool_names(admin) and spawned == []
    api_config._FULL_CONFIG["users"]["root"]["role"] = "superadmin"
    superadmin = env.token(env.login("root"), "edition")
    assert "start_scan" in env.tool_names(superadmin)
    assert env.call(superadmin, "start_scan", {"directories": CONFIGURED[:1]})["ok"]
    assert len(spawned) == 1


@pytest.mark.parametrize("multi", [False, True])
@pytest.mark.parametrize("superadmin", [False, True])
@pytest.mark.parametrize("edition", [False, True])
@pytest.mark.parametrize("open_install", [False, True])
@pytest.mark.parametrize("flag", [False, True])
@pytest.mark.parametrize("trusted_local", [False, True])
def test_the_tool_gate_and_the_route_gate_are_one_rule(
        monkeypatch, multi, superadmin, edition, open_install, flag, trusted_local):
    monkeypatch.setitem(api_config.VIEWER_CONFIG.setdefault("features", {}), "show_scan_button", flag)
    for module in (requirements, api_auth):
        monkeypatch.setattr(module, "is_multi_user_enabled", lambda: multi, raising=False)
        monkeypatch.setattr(module, "_is_open_install", lambda key: open_install)
    resolved = SimpleNamespace(role="superadmin" if superadmin else "user", level="edition" if edition else "readonly",
                               trusted_local=trusted_local)
    user = SimpleNamespace(is_superadmin=superadmin, is_edition=edition, trusted_local_editing=trusted_local)
    tool_refusal = requirements.scan_available(resolved, {})
    try:
        asyncio.run(api_auth.require_scan_access(user))
        route_status = 403 if scan.scan_feature_refusal(user) is not None else None
    except HTTPException as ex:
        route_status = ex.status_code
    assert (tool_refusal is None) == (route_status is None)
    assert route_status in (None, 403) and (
        tool_refusal is None or tool_refusal[0] in ("forbidden_level", "feature_disabled"))
