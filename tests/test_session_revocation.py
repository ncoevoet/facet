"""Real login/auth routes revoke multi-user sessions when their account changes."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from api import config
from api.agent.tokens import session_grant
from api.auth import ACCOUNT_GENERATION_CLAIM, CurrentUser, create_access_token, decode_access_token, hash_password
from api.routers.scan import SCAN_STREAM_PURPOSE


@pytest.mark.parametrize("change", ["password", "demote", "delete", "recreate", "remove_users"])
def test_account_change_revokes_bearer_cookie_refresh_and_held_grant(agent_app, change):
    env = agent_app("multi")
    config.VIEWER_CONFIG["features"]["show_scan_button"] = True
    config._FULL_CONFIG["users"]["root"]["role"] = "superadmin"
    headers = env.login("root")
    token = headers["Authorization"].removeprefix("Bearer ")
    claims = decode_access_token(token)
    grant = session_grant(CurrentUser.from_payload(claims), claims)
    assert grant.resolve().level == "edition"
    assert env.client.get("/api/auth/status", headers=headers).json()["user_role"] == "superadmin"
    assert env.client.get("/api/scan/directories", headers=headers).status_code == 200
    # Short-lived purpose tokens and internal MCP calls share the same account boundary.
    stream_response = env.client.get("/api/scan/stream_token", headers=headers)
    assert stream_response.status_code == 200
    stream = stream_response.json()["token"]
    assert decode_access_token(stream)["purpose"] == SCAN_STREAM_PURPOSE
    internal = create_access_token({"sub": "root", "role": "user", "mcp": True})
    assert CurrentUser.from_payload(decode_access_token(internal)).role == "user"
    if change == "password":
        config._FULL_CONFIG["users"]["root"]["password_hash"] = hash_password("new-password")
    elif change == "demote":
        config._FULL_CONFIG["users"]["root"]["role"] = "user"
    elif change == "delete":
        del config._FULL_CONFIG["users"]["root"]
    elif change == "recreate":
        previous = config._FULL_CONFIG["users"].pop("root")
        config._FULL_CONFIG["users"]["root"] = {**previous, "password_hash": hash_password("root-pw")}
    else:
        config._FULL_CONFIG.pop("users")
    assert decode_access_token(token) is None
    assert decode_access_token(stream) is None
    assert decode_access_token(internal) is None
    assert grant.resolve() is None
    # A stale admin JWT must not renew itself by dropping edition mode.
    refresh = env.client.post("/api/auth/edition/logout", headers=headers)
    if change != "remove_users":
        assert env.client.get("/api/scan/directories", headers=headers).status_code == 401
        assert env.client.get("/api/scan/stream", params={"token": stream}).status_code == 403
        assert refresh.status_code == 401
        for _ in range(2):
            assert env.client.post("/api/auth/edition/logout", headers=headers).status_code == 401
        assert env.client.get("/api/auth/status", headers=headers).json()["authenticated"] is False
        env.client.cookies.set("facet_auth", token)
        assert env.client.get("/api/auth/status").json()["authenticated"] is False
        from tests.test_agent_bridge import auth_frame, closed_after, connect
        with connect(env) as ws:
            ws.send_json(auth_frame(token))
            assert closed_after(ws) == 4401
    else:
        # An open install may issue a new anonymous session, never preserve admin.
        assert refresh.status_code == 200
        renewed = decode_access_token(refresh.json()["access_token"])
        assert renewed["role"] == "user" and ACCOUNT_GENERATION_CLAIM not in renewed
        assert env.client.get("/api/scan/directories", headers=headers).status_code == 403
        assert env.client.get("/api/scan/stream", params={"token": stream}).status_code == 403
        status = env.client.get("/api/auth/status", headers=headers).json()
        assert status["user_id"] is None and status["user_role"] == "user"
        assert status["edition_authenticated"] is False
        # The refresh above set its own anonymous cookie; send only the stale admin one.
        env.client.cookies.clear()
        env.client.cookies.set("facet_auth", token)
        assert list(env.client.cookies.values()) == [token]
        cookie_status = env.client.get("/api/auth/status").json()
        assert cookie_status["user_id"] is None and cookie_status["edition_authenticated"] is False
        from tests.test_agent_bridge import auth_frame, closed_after, connect
        with connect(env) as ws:
            ws.send_json(auth_frame(token))
            assert closed_after(ws) == 4401


def test_changed_account_can_log_in_again_and_public_share_proof_remains_valid(agent_app):
    from api.auth import create_share_client_token

    env = agent_app("multi")
    stale = env.login("root")
    share = create_share_client_token(42, "Guest")
    config._FULL_CONFIG["users"]["root"]["role"] = "user"
    fresh = env.login("root")
    assert env.client.get("/api/scan/directories", headers=fresh).status_code == 403
    assert env.client.get("/api/auth/status", headers=fresh).json()["user_role"] == "user"
    renewed = env.client.post("/api/auth/edition/logout", headers=fresh)
    assert renewed.status_code == 400, "role-based sessions cannot drop edition or renew through this legacy route"
    assert decode_access_token(stale["Authorization"].split(" ", 1)[1]) is None
    assert decode_access_token(share)["role"] == "share_client"


def test_held_multiuser_grant_also_checks_global_password_generation(agent_app):
    env = agent_app("multi")
    token = env.login("root")["Authorization"].split(" ", 1)[1]
    claims = decode_access_token(token)
    user = CurrentUser.from_payload(claims)
    grant = session_grant(user, claims)
    config.VIEWER_CONFIG["password"] = hash_password("rotated-global")
    assert grant.resolve() is None
    del config._FULL_CONFIG["users"]["root"]
    assert session_grant(user) is None


def test_revocation_survives_process_restart_with_the_same_signing_secret(agent_app, tmp_path):
    env = agent_app("multi")
    token = env.login("root")["Authorization"].split(" ", 1)[1]
    config_file = tmp_path / "config.json"
    subprocess_env = {**os.environ, "FACET_CONFIG": str(config_file),
                      "FACET_JWT_SECRET": config.JWT_SECRET,
                      "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    script = ("import json,sys; from api.auth import decode_access_token; "
              "data=json.load(sys.stdin); "
              "assert (decode_access_token(data['token']) is not None) == data['valid']")
    for valid in (True, False):
        if not valid:
            del config._FULL_CONFIG["users"]["root"]
        config_file.write_text(json.dumps({"users": config._FULL_CONFIG["users"]}), encoding="utf-8")
        result = subprocess.run([sys.executable, "-c", script], input=json.dumps({"token": token, "valid": valid}),
                                text=True, capture_output=True, cwd=tmp_path, env=subprocess_env, timeout=30)
        assert result.returncode == 0, result.stderr


def test_cookie_reconciliation_reuses_only_an_explicit_live_human_token(agent_app):
    from api.auth import create_share_client_token

    env = agent_app("multi")
    alice = env.login("alice")
    alice_token = alice["Authorization"].split(" ", 1)[1]
    bob = env.login("bob")
    bob_token = bob["Authorization"].split(" ", 1)[1]
    env.client.cookies.set("facet_auth", alice_token)
    assert env.client.get("/api/auth/status").json()["user_id"] == "alice"
    response = env.client.post("/api/auth/cookie", headers=bob)
    assert response.status_code == 204 and response.content == b""
    assert response.headers["cache-control"] == "no-store"
    assert response.cookies["facet_auth"] == bob_token, "reconciliation must not mint or extend a JWT"
    env.client.cookies.clear()
    env.client.cookies.update(response.cookies)
    assert env.client.get("/api/auth/status").json()["user_id"] == "bob"
    assert env.client.post("/api/auth/cookie").status_code == 401, "an image cookie is not a credential for mutations"
    refused_tokens = [
        create_share_client_token(42, "Guest"),
        create_access_token({"sub": "bob", "purpose": SCAN_STREAM_PURPOSE}),
        create_access_token({"sub": "bob", "role": "user", "mcp": True}),
    ]
    for token in refused_tokens:
        refused = env.client.post("/api/auth/cookie", headers={"Authorization": "Bearer " + token})
        assert refused.status_code in (401, 403)
        assert "set-cookie" not in refused.headers
    config._FULL_CONFIG["users"]["bob"]["password_hash"] = hash_password("new")
    revoked = env.client.post("/api/auth/cookie", headers=bob)
    assert revoked.status_code == 401 and "set-cookie" not in revoked.headers


def test_open_install_cookie_reconciliation_still_requires_a_valid_explicit_token(agent_app):
    env = agent_app("open")
    assert env.client.post("/api/auth/cookie").status_code == 401
    assert env.client.post("/api/auth/cookie", headers={"Authorization": "Bearer invalid"}).status_code == 401
    assert env.client.post("/api/auth/cookie", headers=env.login()).status_code == 204


def test_account_revocation_closes_an_existing_scan_stream(agent_app, monkeypatch):
    from collections import deque

    import httpx
    from api.routers import scan
    from tests.conftest import serve_app

    env = agent_app("multi")
    config._FULL_CONFIG["users"]["root"]["role"] = "superadmin"
    config.VIEWER_CONFIG["features"]["show_scan_button"] = True
    token = env.client.get("/api/scan/stream_token", headers=env.login("root")).json()["token"]
    # Own the complete job state: subprocess tests may leave mocked exit/progress
    # values behind, which are not a real serializable scan snapshot.
    monkeypatch.setattr(scan, "_scan_state", {
        "running": True, "kind": scan.JOB_KIND_SCAN, "process": None,
        "output_lines": deque(["authorized snapshot"], maxlen=500),
        "started_at": None, "directories": ["/authorized-library"],
        "exit_code": None, "progress": None, "scope": None,
    })
    with serve_app(env.app, access_log=False) as port:
        with httpx.stream("GET", f"http://127.0.0.1:{port}/api/scan/stream", params={"token": token}, timeout=5) as response:
            assert response.status_code == 200
            lines = response.iter_lines()
            first = next(lines)
            assert first.startswith("data: ")
            snapshot = json.loads(first.removeprefix("data: "))
            assert snapshot["running"] is True
            assert snapshot["output"] == ["authorized snapshot"]
            assert snapshot["directories"] == ["/authorized-library"]
            assert next(lines) == ""
            del config._FULL_CONFIG["users"]["root"]
            assert list(lines) == [], "the authorized connection must close before emitting any further snapshots"


def _single_user_scan_stream(agent_app, monkeypatch, running):
    from collections import deque

    from api.routers import scan
    from tests.conftest import AGENT_EDITION_PASSWORD

    env = agent_app("legacy")
    config.VIEWER_CONFIG["features"]["show_scan_button"] = True
    login = env.client.post("/api/auth/edition/login", json={"password": AGENT_EDITION_PASSWORD})
    assert login.status_code == 200, login.text
    headers = {"Authorization": "Bearer " + login.json()["access_token"]}
    token = env.client.get("/api/scan/stream_token", headers=headers).json()["token"]
    monkeypatch.setattr(scan, "_scan_state", {
        "running": running, "kind": scan.JOB_KIND_SCAN, "process": None,
        "output_lines": deque(["edition-only scan log line"], maxlen=500),
        "started_at": None, "directories": ["/edition-only-dir"],
        "exit_code": None if running else 0, "progress": None, "scope": None,
    })
    return env, token


def test_unrotated_single_user_stream_token_still_opens(agent_app, monkeypatch):
    env, token = _single_user_scan_stream(agent_app, monkeypatch, running=False)
    opened = env.client.get("/api/scan/stream", params={"token": token})
    assert opened.status_code == 200
    assert "edition-only scan log line" in opened.text


def test_edition_password_rotation_refuses_a_held_stream_token(agent_app, monkeypatch):
    env, token = _single_user_scan_stream(agent_app, monkeypatch, running=False)
    config.VIEWER_CONFIG["edition_password"] = hash_password("rotated-edition")
    refused = env.client.get("/api/scan/stream", params={"token": token})
    assert refused.status_code == 403
    assert "edition-only scan log line" not in refused.text


def test_edition_password_rotation_closes_an_open_single_user_stream(agent_app, monkeypatch):
    import httpx
    from tests.conftest import serve_app

    env, token = _single_user_scan_stream(agent_app, monkeypatch, running=True)
    with serve_app(env.app, access_log=False) as port:
        with httpx.stream("GET", f"http://127.0.0.1:{port}/api/scan/stream", params={"token": token}, timeout=5) as response:
            assert response.status_code == 200
            lines = response.iter_lines()
            assert json.loads(next(lines).removeprefix("data: "))["output"] == ["edition-only scan log line"]
            assert next(lines) == ""
            config.VIEWER_CONFIG["edition_password"] = hash_password("rotated-edition")
            assert list(lines) == [], "rotation must close the stream before any further snapshot"
