"""The in-page agent: ``/api/mcp/inpage_tools`` and ``/api/mcp/call`` run the SAME tools as ``/mcp``.

[REAL] ``agent_app`` (the production auth chain and lifespan, no ``dependency_overrides``), real
``create_access_token`` JWTs from the real login routes on a LOCKED install, the real tool registry and
the real write routes against seeded rows. The session grant is exercised through ``tokens.session_grant``
directly where the claims themselves are the subject.
"""

import os
import sqlite3

import pytest

from api import config as api_config
from api.agent import nonce, tokens
from api.agent.tools_common import CORE_TOOLS, TOOL_LEVELS
from api.agent.tools_write import WRITE_TOOL_LEVELS
from api.auth import CurrentUser, create_access_token, decode_access_token
from tests import test_agent_taste_isolation as taste
from tests import test_agent_write as write_tests
from tests.conftest import _TEST_DB_FILE, AGENT_DIR, intercept_internal_call

P, ROWS, ARGS = write_tests.P, write_tests.ROWS, write_tests.TestGrantMatrix.ARGS
photo_col, pref, wipe_prefs = write_tests.photo_col, write_tests.pref, write_tests.wipe_prefs
SESSION_HEADER = "X-Facet-Agent-Session"
IMAGE_AND_ACTION_TOOLS = {"get_thumbnail", "contact_sheet", "available_actions"}
LEVELS = ("readonly", "user", "edition")


@pytest.fixture()
def photos(seed_photos_prefix):
    wipe_prefs()
    yield seed_photos_prefix(AGENT_DIR, ROWS)
    wipe_prefs()


def post(env, headers, tool, arguments=None, sid="tab-a", snapshot=None, extra=None):
    body = {"tool": tool, "arguments": arguments or {}}
    if snapshot is not None:
        body["selection_snapshot"] = snapshot
    return env.client.post("/api/mcp/call", json=body, headers={**headers, **({SESSION_HEADER: sid} if sid else {}),
                                                                **(extra or {})})


def call(env, headers, tool, arguments=None, **kw):
    resp = post(env, headers, tool, arguments, **kw)
    assert resp.status_code == 200, resp.text
    return resp.json()


def listed(env, headers):
    resp = env.client.get("/api/mcp/inpage_tools", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def names(env, headers):
    return {t["name"] for t in listed(env, headers)["tools"]}


def floor_set(level):
    """The in-page set computed from TOOL_LEVELS alone (the contract), independent of ``tool_visible``."""
    rank = LEVELS.index(level)
    return {n for n, floor in TOOL_LEVELS.items()
            if LEVELS.index(tokens.effective_requirement(floor)) <= rank
            and not n.startswith("ui_") and n not in IMAGE_AND_ACTION_TOOLS}


def session_of(env, headers):
    jwt = headers["Authorization"].split(" ", 1)[1]
    claims = decode_access_token(jwt)
    return tokens.session_grant(CurrentUser.from_payload(claims), claims)


class TestSessionGrant:
    @pytest.mark.parametrize("mode,who,edition,level", [
        ("legacy", None, False, "readonly"), ("legacy", None, True, "edition"),
        ("multi", "alice", False, "user"), ("multi", "root", False, "edition"),
        ("open", None, False, "readonly")])
    def test_session_grant_round_trips_real_level(self, agent_app, mode, who, edition, level):
        env = agent_app(mode)
        grant = session_of(env, env.login(who, edition=edition))
        resolved = grant.resolve()
        assert resolved.level == level and resolved.token_id is None
        claims = resolved.jwt_claims()
        if mode == "open":
            assert claims is None, "an open install's internal call is anonymous, exactly as a human's"
            return
        payload = decode_access_token(create_access_token(claims))
        user = CurrentUser.from_payload(payload)
        assert user.is_edition is (level == "edition"), claims
        assert payload["mcp"] is True and payload["sub"] == resolved.principal

    def test_resolve_is_min_of_jwt_and_live(self, agent_app):
        env = agent_app("legacy")
        grant = session_of(env, env.login(edition=True))
        assert grant.resolve().level == "edition"
        api_config.VIEWER_CONFIG["edition_password"] = "rotated-edition"
        assert grant.resolve().level == "readonly", "rotating the edition password lowers the very next call"
        api_config.VIEWER_CONFIG["password"] = "rotated-viewer"
        assert grant.resolve() is None, "a rotated viewer password ends the session"
        env = agent_app("multi")
        grant = session_of(env, env.login("root"))
        assert grant.resolve().level == "edition"
        api_config._FULL_CONFIG["users"]["root"]["role"] = "user"
        assert grant.resolve().level == "user"

    def test_session_level_never_exceeds_jwt(self, agent_app):
        env = agent_app("multi")
        grant = session_of(env, env.login("alice"))
        api_config._FULL_CONFIG["users"]["alice"]["role"] = "admin"
        assert grant.resolve().level == "user", "a promotion cannot raise a session past its own JWT"

    def test_unknown_user_and_unreadable_config_resolve_none(self, agent_app, monkeypatch):
        env = agent_app("multi")
        headers = env.login("alice")
        grant = session_of(env, headers)
        del api_config._FULL_CONFIG["users"]["alice"]
        assert grant.resolve() is None and session_of(env, headers) is None
        assert env.client.get("/api/mcp/inpage_tools", headers=headers).status_code == 401
        env = agent_app("legacy")
        grant = session_of(env, env.login(edition=True))
        monkeypatch.setattr(tokens, "install_mode", lambda: "unreadable")
        assert grant.resolve() is None

    def test_forbidden_hint_wording_inpage_vs_token(self, agent_app, photos):
        env = agent_app("legacy")
        session = call(env, env.login(), "batch_set_rating", {"paths": [P[0]], "rating": 3})
        assert session["error"] == "forbidden_level" and "unlock edition in Facet" in session["message"]
        assert "mint" not in session["message"] and "token" not in session["message"]
        token = env.call(env.token(env.login(), "readonly"), "batch_set_rating", {"paths": [P[0]], "rating": 3})
        assert token["error"] == "forbidden_level" and "token's level" in token["message"]
        status = call(env, env.login(), "status")["data"]["hidden_tools"]
        assert "unlock edition in Facet" in status["hint"] and "mint" not in status["hint"]

    def test_nonce_owner_int_never_equals_str(self):
        nonce.reset()
        mine = tokens.SessionGrant("u", "u", "edition", "admin", "", "", "", session_id="a")
        other = tokens.SessionGrant("u", "u", "edition", "admin", "", "", "", session_id="b")
        issued = nonce.issue(mine.nonce_owner, "delete_photos", "h")
        assert not nonce.check(other.nonce_owner, "delete_photos", "h", issued)
        assert not nonce.check(7, "delete_photos", "h", issued)
        assert nonce.check(mine.nonce_owner, "delete_photos", "h", issued)
        assert mine.rate_key == other.rate_key == "inpage:u" and mine.nonce_owner != other.nonce_owner


class TestExposure:
    def test_endpoints_404_when_mcp_disabled(self, agent_app):
        env = agent_app("legacy", mcp_enabled=False)
        headers = env.login()
        assert env.client.get("/api/mcp/inpage_tools", headers=headers).status_code == 404
        assert post(env, headers, "status").status_code == 404
        assert env.client.get("/api/auth/status").json()["features"]["mcp_inpage"] is False

    def test_endpoints_404_when_inpage_tools_off(self, agent_app):
        env = agent_app("legacy", inpage_tools=False)
        headers = env.login()
        assert env.client.get("/api/mcp/inpage_tools", headers=headers).status_code == 404
        assert post(env, headers, "status").status_code == 404
        features = env.client.get("/api/auth/status").json()["features"]
        assert features["mcp_inpage"] is False and features["mcp"] is True
        assert env.rpc(env.token(headers, "readonly"), "tools/list").status_code == 200, "/mcp is unaffected"

    def test_flag_on_by_default_and_reported(self, agent_app):
        assert api_config.MCP_SETTINGS_DEFAULTS["inpage_tools"] is True
        env = agent_app("legacy")
        assert env.client.get("/api/auth/status").json()["features"]["mcp_inpage"] is True

    @pytest.mark.parametrize("mode,who,edition,level", [
        ("legacy", None, False, "readonly"), ("multi", "alice", False, "user"), ("legacy", None, True, "edition")])
    def test_listed_set_equals_visible_tools_per_level(self, agent_app, mode, who, edition, level):
        env = agent_app(mode, allow_destructive=True)
        api_config.VIEWER_CONFIG.setdefault("features", {})["show_scan_button"] = True
        headers = env.login(who, edition=edition)
        body = listed(env, headers)
        assert body["level"] == level
        assert {t["name"] for t in body["tools"]} == floor_set(level)
        for tool in body["tools"]:
            assert tool["required_level"] == tokens.effective_requirement(TOOL_LEVELS[tool["name"]])
            assert not {"show", "tab_id"} & set(tool["inputSchema"].get("properties", {}))
            assert not {"show", "tab_id"} & set(tool["inputSchema"].get("required", []))
            assert tool["annotations"]["untrustedContentHint"] is True
            assert tool["annotations"]["consequentialHint"] is (not tool["annotations"]["readOnlyHint"])

    def test_listed_set_under_core_profile(self, agent_app):
        env = agent_app("legacy", tool_profile="core")
        headers = env.login(edition=True)
        assert names(env, headers) == floor_set("edition") & CORE_TOOLS

    def test_edition_tools_vanish_on_lock_and_demotion(self, agent_app):
        env = agent_app("legacy")
        headers = env.login(edition=True)
        assert "batch_set_rating" in names(env, headers)
        api_config.VIEWER_CONFIG["edition_password"] = "rotated"
        after = listed(env, headers)
        assert after["level"] == "readonly" and "batch_set_rating" not in {t["name"] for t in after["tools"]}
        env = agent_app("multi")
        headers = env.login("root")
        assert "override_sequence" in names(env, headers)
        api_config._FULL_CONFIG["users"]["root"]["role"] = "user"
        assert "override_sequence" not in names(env, headers) and "set_rating" in names(env, headers)

    def test_image_tools_and_ui_tools_absent_and_refused(self, agent_app):
        env = agent_app("legacy")
        headers = env.login(edition=True)
        listing = names(env, headers)
        assert not IMAGE_AND_ACTION_TOOLS & listing and not any(n.startswith("ui_") for n in listing)
        for tool in IMAGE_AND_ACTION_TOOLS | {"ui_get_context"}:
            result = call(env, headers, tool, {})
            assert result["error"] == "invalid_input" and "in-page" in result["message"], tool

    @pytest.mark.parametrize("mode,who,edition", [("legacy", None, False), ("multi", "alice", False),
                                                    ("legacy", None, True)])
    def test_call_matrix_allowed_equals_listed(self, agent_app, photos, monkeypatch, mode, who, edition):
        counting = []
        intercept_internal_call(monkeypatch, lambda tool, kw: counting.append(tool))
        env = agent_app(mode, allow_destructive=True)
        headers = env.login(who, edition=edition)
        listing = names(env, headers)
        for tool in WRITE_TOOL_LEVELS:
            counting.clear()
            result = call(env, headers, tool, ARGS[tool])
            refused = result.get("error") in ("forbidden_level", "feature_disabled") and any(
                m in result["message"] for m in ("session's level", "allow_destructive", "show_scan_button"))
            assert (tool in listing) is (not refused), (mode, edition, tool, result)
            if refused:
                assert counting == [], (tool, counting)
                if result["error"] == "forbidden_level":
                    assert "unlock edition in Facet" in result["message"] or "needs user" in result["message"]

    def test_allow_destructive_false_hides_and_refuses_delete_cull_and_reassign(self, agent_app, photos):
        env = agent_app("legacy")
        headers = env.login(edition=True)
        assert "delete_photos" not in names(env, headers)
        deleted = call(env, headers, "delete_photos", {"paths": [P[0]]})
        assert deleted["error"] == "feature_disabled" and "allow_destructive" in deleted["message"]
        trashed = call(env, headers, "cull_apply", {"action": "trash_rejects", "paths": [P[0]]})
        assert trashed["error"] == "feature_disabled" and "allow_destructive" in trashed["message"]
        reassign = call(env, headers, "assign_faces", {"person_id": 1, "face_ids": [1], "allow_reassign": True})
        assert reassign["error"] == "feature_disabled" and "allow_destructive" in reassign["message"]
        env = agent_app("legacy", allow_destructive=True)
        assert "delete_photos" in names(env, env.login(edition=True))


class TestAuthSurface:
    def test_cookie_only_post_401(self, agent_app, photos):
        env = agent_app("legacy")
        login = env.client.post("/api/auth/login", json={"password": "view-pw"})
        assert login.status_code == 200 and env.client.cookies
        resp = env.client.post("/api/mcp/call", json={"tool": "status", "arguments": {}},
                               headers={SESSION_HEADER: "tab-a"})
        assert resp.status_code == 401
        env.client.cookies.clear()

    def test_anonymous_401_on_a_locked_install(self, agent_app):
        env = agent_app("legacy")
        assert env.client.get("/api/mcp/inpage_tools").status_code == 401
        assert post(env, {}, "status").status_code == 401

    def test_foreign_origin_403_same_origin_ok(self, agent_app):
        env = agent_app("legacy")
        headers = env.login()
        assert post(env, headers, "status", extra={"Origin": "http://evil.example"}).status_code == 403
        assert env.client.get("/api/mcp/inpage_tools", headers={**headers, "Origin": "http://evil.example"}
                              ).status_code == 403
        assert post(env, headers, "status", extra={"Origin": "http://testserver"}).status_code == 200

    def test_mcp_claim_jwt_403(self, agent_app):
        env = agent_app("legacy")
        jwt = create_access_token({"sub": "_legacy", "role": "user", "edition": True, "mcp": True})
        headers = {"Authorization": "Bearer " + jwt}
        assert post(env, headers, "status").status_code == 403
        assert env.client.get("/api/mcp/inpage_tools", headers=headers).status_code == 403

    def test_agent_token_403(self, agent_app):
        env = agent_app("legacy")
        token = env.token(env.login(), "readonly")
        assert post(env, {"Authorization": "Bearer " + token}, "status").status_code == 403

    def test_rotated_viewer_password_401(self, agent_app):
        env = agent_app("legacy")
        headers = env.login()
        assert post(env, headers, "status").status_code == 200
        api_config.VIEWER_CONFIG["password"] = "rotated-viewer"
        assert post(env, headers, "status").status_code == 401
        assert env.client.get("/api/mcp/inpage_tools", headers=headers).status_code == 401

    @pytest.mark.parametrize("sid", [None, "", "has space", "x" * 65, "bad/slash"])
    def test_session_header_is_validated(self, agent_app, sid):
        env = agent_app("legacy")
        resp = post(env, env.login(), "status", sid=sid)
        assert resp.status_code == 400

    def test_unexpected_tool_error_is_an_envelope_not_a_500(self, agent_app, monkeypatch):
        from mcp.server.mcpserver.exceptions import UnexpectedToolError
        env = agent_app("legacy")

        async def boom(*args, **kw):
            raise UnexpectedToolError("x")
        monkeypatch.setattr(env.app.state.mcp_server, "call_tool", boom)
        resp = post(env, env.login(), "status")
        assert resp.status_code == 200 and resp.json()["error"] == "upstream_error"

    def test_unknown_tool_and_arguments_are_invalid_input_envelopes(self, agent_app):
        env = agent_app("legacy")
        headers = env.login()
        assert call(env, headers, "no_such_tool")["error"] == "invalid_input"
        assert call(env, headers, "status", {"bogus": 1})["error"] == "invalid_input"
        assert call(env, headers, "search_photos", {"tab_id": "t1"})["error"] == "invalid_input"

    def test_no_touch_for_session_actors(self, agent_app, monkeypatch):
        touched = []
        monkeypatch.setattr(tokens, "touch", lambda token_id: touched.append(token_id))
        env = agent_app("legacy")
        headers = env.login()
        assert call(env, headers, "status")["ok"]
        assert touched == []
        assert env.call(env.token(headers, "readonly"), "status")["ok"] and len(touched) == 1


class TestSameToolSameWrapper:
    def test_rate_bucket_shared_across_sids(self, agent_app):
        env = agent_app("legacy", rate_per_min=2)
        headers = env.login()
        assert call(env, headers, "status", sid="tab-a")["ok"]
        assert call(env, headers, "status", sid="tab-b")["ok"]
        third = call(env, headers, "status", sid="tab-c")
        assert third["error"] == "rate_limited", "more tabs must not multiply a user's budget"

    def test_envelope_caps_match_mcp(self, agent_app, photos):
        env = agent_app("legacy", max_rows=2)
        headers = env.login()
        args = {"filters": {"path_prefix": AGENT_DIR}, "per_page": 5}
        inpage = call(env, headers, "search_photos", args)
        over_mcp = env.call(env.token(headers, "readonly"), "search_photos", {**args, "show": False})
        assert inpage["truncated"] is True and len(inpage["data"]["rows"]) == 2
        assert {k: inpage[k] for k in ("truncated", "returned")} == {k: over_mcp[k] for k in ("truncated", "returned")}

    def test_show_is_forced_off(self, agent_app, photos):
        env = agent_app("legacy")
        result = call(env, env.login(), "search_photos", {"filters": {"path_prefix": AGENT_DIR}, "show": True})
        assert result["ok"] and "shown_in_tab" not in result

    def test_write_inpage_same_db_row_and_envelope_as_mcp(self, agent_app, photos):
        env = agent_app("legacy")
        headers = env.login(edition=True)
        via_mcp = env.call(env.token(headers, "edition"), "set_rating", {"paths": [P[0]], "rating": 4})
        via_page = call(env, headers, "set_rating", {"paths": [P[1]], "rating": 4})
        assert photo_col(P[0], "star_rating") == photo_col(P[1], "star_rating") == 4

        def shape(envelope):
            data = dict(envelope["data"])
            data["results"] = [r["outcome"] for r in data["results"]]
            return envelope["ok"], data
        assert shape(via_mcp) == shape(via_page)
        assert via_page["changed"] == 1
        assert "changed" not in via_mcp and "batch_id" not in via_page

    def test_inpage_status_has_no_tab_extras(self, agent_app):
        env = agent_app("legacy")
        headers = env.login()
        inpage = call(env, headers, "status")["data"]
        over_mcp = env.call(env.token(headers, "readonly"), "status")["data"]
        assert "tabs" in over_mcp and "out_of_reach_tabs" in over_mcp
        assert "tabs" not in inpage and "out_of_reach_tabs" not in inpage
        assert inpage["owner"] == "_legacy" and inpage["level"] == "readonly"

    def test_per_user_rating_lands_in_the_right_row(self, agent_app, photos):
        env = agent_app("multi")
        result = call(env, env.login("alice"), "set_rating", {"paths": [P[0]], "rating": 5})
        assert result["ok"] and result["changed"] == 1
        assert pref("alice", P[0])[0] == 5 and pref("bob", P[0]) is None and pref("root", P[0]) is None


class TestTargetSelection:
    def test_two_tabs_selection_isolated(self, agent_app, photos):
        env = agent_app("legacy")
        headers = env.login(edition=True)
        x = {"scope": "paths", "count": 2, "paths": [P[0], P[1]]}
        y = {"scope": "paths", "count": 1, "paths": [P[2]]}
        before = [photo_col(p, "star_rating") for p in P]
        result = call(env, headers, "batch_set_rating", {"target": "selection", "rating": 5}, sid="tab-x", snapshot=x)
        assert result["ok"], result
        assert result["data"]["affected"] == 2
        assert [photo_col(p, "star_rating") for p in P[:3]] == [5, 5, before[2]], "tab Y's rows must not move"
        result = call(env, headers, "batch_set_rating", {"target": "selection", "rating": 2}, sid="tab-y", snapshot=y)
        assert result["ok"] and [photo_col(p, "star_rating") for p in P[:3]] == [5, 5, 2]

    def test_selection_without_a_snapshot_is_refused_not_bridged(self, agent_app, photos):
        env = agent_app("legacy")
        result = call(env, env.login(edition=True), "batch_set_rating", {"target": "selection", "rating": 5})
        assert result["error"] == "invalid_input" and "selection" in result["message"]
        assert photo_col(P[0], "star_rating") == 1

    def test_snapshot_is_validated_like_the_bridge_reply(self, agent_app, photos):
        env = agent_app("legacy")
        headers = env.login(edition=True)
        liar = {"scope": "paths", "count": 3, "paths": [P[0]]}
        refused = call(env, headers, "batch_set_rating", {"target": "selection", "rating": 5}, snapshot=liar)
        assert refused["error"] == "invalid_input"
        truncated = {"scope": "paths", "count": 1, "paths": [P[0]], "truncated": True}
        assert call(env, headers, "batch_set_rating", {"target": "selection", "rating": 5},
                    snapshot=truncated)["error"] == "too_large"
        assert photo_col(P[0], "star_rating") == 1


@pytest.fixture()
def trash_library(agent_app, tmp_path, seed_photos_prefix, monkeypatch):
    env = agent_app("legacy", allow_destructive=True)
    root = os.path.realpath(tmp_path)
    src = os.path.join(root, "src")
    os.makedirs(src)
    rows = []
    for name in ("d1", "d2"):
        with open(os.path.join(src, name + ".jpg"), "wb") as handle:
            handle.write(b"JPG")
        rows.append({"path": os.path.join(src, name + ".jpg"), "filename": name + ".jpg"})
    seed_photos_prefix(src + os.sep, rows)
    monkeypatch.setitem(api_config.VIEWER_CONFIG, "cull", {"allow_trash": True})
    monkeypatch.setattr("send2trash.send2trash", os.remove)
    return env, [r["path"] for r in rows]


class TestNonceIsolation:
    def test_dry_run_reports_no_change(self, trash_library):
        env, paths = trash_library
        dry = call(env, env.login(edition=True), "delete_photos", {"paths": paths})
        assert dry["ok"] is True and dry["data"]["confirm"] and not dry.get("changed")
        assert all(os.path.exists(p) for p in paths)

    def test_cross_session_and_token_nonce_isolation(self, trash_library):
        env, paths = trash_library
        headers_a, headers_b = env.login(edition=True), env.login(edition=True)
        token = env.token(headers_a, "edition")
        dry = call(env, headers_a, "delete_photos", {"paths": paths}, sid="tab-a")
        confirm = dry["data"]["confirm"]
        real = {"paths": paths, "dry_run": False, "confirm": confirm}
        assert call(env, headers_b, "delete_photos", real, sid="tab-b")["error"] == "confirmation_required"
        assert env.call(token, "delete_photos", real)["error"] == "confirmation_required"
        assert all(os.path.exists(p) for p in paths), "neither stranger burned or spent the nonce"
        done = call(env, headers_a, "delete_photos", real, sid="tab-a")
        assert done["ok"] is True and not any(os.path.exists(p) for p in paths)

    def test_same_user_second_tab_cannot_spend_the_first_tabs_nonce(self, trash_library):
        env, paths = trash_library
        headers = env.login(edition=True)
        confirm = call(env, headers, "delete_photos", {"paths": paths}, sid="tab-a")["data"]["confirm"]
        real = {"paths": paths, "dry_run": False, "confirm": confirm}
        assert call(env, headers, "delete_photos", real, sid="tab-b")["error"] == "confirmation_required"
        assert call(env, headers, "delete_photos", real, sid="tab-a")["ok"] is True

    def test_a_session_nonce_is_not_a_token_nonce_the_other_way_round(self, trash_library):
        env, paths = trash_library
        headers = env.login(edition=True)
        token = env.token(headers, "edition")
        confirm = env.call(token, "delete_photos", {"paths": paths})["data"]["confirm"]
        real = {"paths": paths, "dry_run": False, "confirm": confirm}
        assert call(env, headers, "delete_photos", real)["error"] == "confirmation_required"
        assert env.call(token, "delete_photos", real)["ok"] is True


def provenance(user, path):
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        return conn.execute("SELECT star_rating FROM rating_provenance WHERE user_id = ? AND photo_path = ?",
                            (user, path)).fetchall()


class TestProvenance:
    def test_inpage_write_is_marked_and_a_person_rerating_clears_the_mark(self, agent_app, photos):
        env = agent_app("multi")
        alice = env.login("alice")
        assert call(env, alice, "set_rating", {"paths": [P[0]], "rating": 5}, sid="tab-j")["changed"] == 1
        assert provenance("alice", P[0]) == [(5,)]
        assert provenance("bob", P[0]) == []
        resp = env.client.post("/api/photo/set_rating", json={"photo_path": P[0], "rating": 2}, headers=alice)
        assert resp.status_code == 200
        assert provenance("alice", P[0]) == []


@pytest.fixture()
def taste_world(agent_app, seed_photos_prefix, monkeypatch):
    from api import db_helpers
    from api.routers import faces
    rows = [{**row, "star_rating": 3} for row in taste.ROWS]
    seed_photos_prefix(taste.PREFIX, rows)
    nudges, mints = [], []
    real_nudge, real_mint = db_helpers.trigger_auto_retrain, faces._mint_rating_comparisons
    monkeypatch.setattr(db_helpers, "trigger_auto_retrain",
                        lambda *a, **k: (nudges.append(a), real_nudge(*a, **k))[1])
    monkeypatch.setattr(faces, "_mint_rating_comparisons", lambda *a, **k: (mints.append(a), real_mint(*a, **k))[1])
    env = agent_app("legacy")
    yield env, env.login(edition=True), nudges, mints
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        conn.execute("DELETE FROM comparisons WHERE photo_a_path LIKE ? OR photo_b_path LIKE ?",
                     (taste.PREFIX + "%", taste.PREFIX + "%"))


class TestTasteModel:
    def test_agent_write_does_not_train_taste(self, taste_world):
        env, headers, nudges, mints = taste_world
        before = taste.comparisons()
        assert call(env, headers, "set_rating", {"paths": taste.PATHS[:1], "rating": 5})["changed"] == 1
        assert call(env, headers, "set_rejected", {"paths": taste.PATHS[1:2], "value": True})["changed"] == 1
        assert mints == [] and nudges == [] and taste.comparisons() == before
        resp = env.client.post("/api/photo/set_rating", json={"photo_path": taste.PATHS[2], "rating": 5},
                               headers=headers)
        assert resp.status_code == 200 and len(mints) == 1, "a person's own rating still trains"


def post_json(env, headers, tool, arguments=None, tab_id=None, sid="tab-a"):
    body = {"tool": tool, "arguments": arguments or {}}
    if tab_id is not None:
        body["tab_id"] = tab_id
    resp = env.client.post("/api/mcp/call", json=body, headers={**headers, SESSION_HEADER: sid})
    assert resp.status_code == 200, resp.text
    return resp.json()


def changed_frames(tab):
    return [m for m in tab.inbox if m.get("type") == "changed"]


def frames_within(tab, count, timeout=5.0):
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and len(changed_frames(tab)) < count:
        time.sleep(0.05)
    return changed_frames(tab)


class TestChangedPaths:
    """``changed_paths`` on ``/api/mcp/call``: present iff a write ran; the caller tab is never broadcast to."""

    @pytest.fixture()
    def edition_session(self, agent_app, photos):
        env = agent_app("legacy", allow_destructive=True)
        return env, env.login(edition=True)

    def test_a_batch_write_carries_changed_paths(self, edition_session):
        env, headers = edition_session
        out = post_json(env, headers, "batch_set_rejected", {"paths": P[:2]})
        assert out["ok"] and out["changed_paths"] == P[:2] and out["changed"] == 2

    def test_a_write_whose_envelope_has_no_affected_still_carries_the_key(self, edition_session):
        env, headers = edition_session
        out = post_json(env, headers, "set_caption", {"path": P[0], "caption": "inpage live caption"})
        assert out["ok"], out
        assert "changed" not in out and out["changed_paths"] == [P[0]]

    def test_a_filter_scoped_write_has_the_key_with_null(self, edition_session):
        env, headers = edition_session
        out = post_json(env, headers, "batch_set_rejected",
                        {"filters": {"path_prefix": AGENT_DIR}, "expected_count": len(P)})
        assert out["ok"], out
        assert "changed_paths" in out and out["changed_paths"] is None

    def test_a_read_has_no_key(self, edition_session):
        env, headers = edition_session
        out = post_json(env, headers, "search_photos", {})
        assert out["ok"] and "changed_paths" not in out

    def test_a_preview_has_no_key(self, edition_session):
        env, headers = edition_session
        out = post_json(env, headers, "delete_photos", {"paths": P[:1]})
        assert "changed_paths" not in out, out

    def test_a_refused_write_has_no_key(self, agent_app, photos):
        env = agent_app("legacy")
        headers = env.login()
        out = post_json(env, headers, "set_caption", {"path": P[0], "caption": "x"})
        assert not out["ok"] and "changed_paths" not in out

    def test_an_outcome_unknown_write_still_carries_the_key(self, edition_session, monkeypatch):
        import httpx
        original = httpx.AsyncClient.request

        async def flaky(self, method, url, *args, **kwargs):
            if str(url).endswith("/api/photos/batch_reject"):
                raise httpx.ConnectError("dropped")
            return await original(self, method, url, *args, **kwargs)

        monkeypatch.setattr(httpx.AsyncClient, "request", flaky)
        env, headers = edition_session
        out = post_json(env, headers, "batch_set_rejected", {"paths": P[:2]})
        assert out["ok"] is False and out["error"] == "outcome_unknown"
        assert out["changed_paths"] == P[:2]

    def test_other_tabs_get_the_frame_and_the_caller_tab_does_not(self, edition_session, fake_tab):
        env, headers = edition_session
        jwt = headers["Authorization"].split(" ", 1)[1]
        caller, other = fake_tab(env, jwt, "tab-caller"), fake_tab(env, jwt, "tab-other")
        out = post_json(env, headers, "batch_set_rejected", {"paths": P[:2]}, tab_id="tab-caller")
        assert out["changed_paths"] == P[:2]
        frames = frames_within(other, 1)
        assert frames[0].pop("call_id")
        assert frames == [{"type": "changed", "tool": "batch_reject", "paths": P[:2], "count": 2,
                           "agent_tool": "batch_set_rejected"}]
        import time
        time.sleep(0.5)
        assert changed_frames(caller) == []

    def test_a_two_photo_write_shares_one_call_id_across_other_tabs_frames(self, edition_session, fake_tab):
        env, headers = edition_session
        jwt = headers["Authorization"].split(" ", 1)[1]
        other = fake_tab(env, jwt, "tab-other")
        out = post_json(env, headers, "set_rejected", {"paths": P[:2], "value": True}, tab_id="tab-caller")
        assert out["changed_paths"] == P[:2]
        frames = frames_within(other, 2)
        assert len(frames) == 2
        assert {f["agent_tool"] for f in frames} == {"set_rejected"}
        assert len({f["call_id"] for f in frames}) == 1 and frames[0]["call_id"]

    def test_an_auto_cull_apply_carries_show_paths_and_a_null_changed_paths(self, agent_app, seed_photos_prefix):
        from tests import test_agent_culling as culling
        seed_photos_prefix(culling.PREFIX, culling.ROWS)
        nonce.reset()
        env = agent_app("legacy")
        headers = env.login(edition=True)
        args = {"group_by": "burst", "strictness": 0, **culling.SCOPE}
        preview = call(env, headers, "auto_cull", args)
        assert preview["ok"] and preview["confirm"], preview
        assert "show_paths" not in preview
        applied = call(env, headers, "auto_cull", {**args, "dry_run": False, "confirm": preview["confirm"]})
        assert applied["ok"], applied
        assert applied["changed_paths"] is None
        assert applied["show_paths"] == [culling.BURST_PATHS[2]]

    def test_an_unexpected_error_after_a_write_still_carries_the_paths_and_broadcasts(
            self, edition_session, fake_tab, monkeypatch):
        from mcp.server.mcpserver.exceptions import UnexpectedToolError
        from api.agent.live_updates import LIVE_SINK_OVERRIDE
        env, headers = edition_session
        jwt = headers["Authorization"].split(" ", 1)[1]
        other = fake_tab(env, jwt, "tab-other")

        async def write_then_boom(*args, **kw):
            LIVE_SINK_OVERRIDE.get()("_legacy", "batch_reject", {"photo_paths": P[:2]}, {"count": 2})
            raise UnexpectedToolError("x")
        monkeypatch.setattr(env.app.state.mcp_server, "call_tool", write_then_boom)
        out = post_json(env, headers, "batch_set_rejected", {"paths": P[:2]}, tab_id="tab-caller")
        assert out["error"] == "upstream_error" and out["changed_paths"] == P[:2]
        assert frames_within(other, 1) == [{"type": "changed", "tool": "batch_reject", "paths": P[:2], "count": 2}]

    def test_an_unexpected_error_without_a_write_has_no_key(self, edition_session, monkeypatch):
        from mcp.server.mcpserver.exceptions import UnexpectedToolError
        env, headers = edition_session

        async def boom(*args, **kw):
            raise UnexpectedToolError("x")
        monkeypatch.setattr(env.app.state.mcp_server, "call_tool", boom)
        out = post_json(env, headers, "batch_set_rejected", {"paths": P[:2]})
        assert out["error"] == "upstream_error" and "changed_paths" not in out

    def test_a_dry_run_broadcasts_nothing(self, edition_session, fake_tab):
        env, headers = edition_session
        jwt = headers["Authorization"].split(" ", 1)[1]
        other = fake_tab(env, jwt, "tab-other")
        post_json(env, headers, "delete_photos", {"paths": P[:1]}, tab_id="tab-caller")
        import time
        time.sleep(0.5)
        assert changed_frames(other) == []

    def test_no_tab_id_broadcasts_to_nobody(self, edition_session, fake_tab):
        env, headers = edition_session
        jwt = headers["Authorization"].split(" ", 1)[1]
        other = fake_tab(env, jwt, "tab-other")
        out = post_json(env, headers, "batch_set_rejected", {"paths": P[:1]})
        assert out["changed_paths"] == P[:1]
        import time
        time.sleep(0.5)
        assert changed_frames(other) == []

    def test_a_malformed_tab_id_is_a_422(self, edition_session):
        env, headers = edition_session
        resp = env.client.post("/api/mcp/call", json={"tool": "search_photos", "tab_id": "bad id!"},
                               headers={**headers, SESSION_HEADER: "tab-a"})
        assert resp.status_code == 422


class TestAutoCullReadsNothingFromTheTab:
    """In-page: auto_cull reads no review state back from the caller tab, and the call body has no field to carry one."""

    def test_an_in_page_auto_cull_makes_no_bridge_read(self, agent_app, fake_tab, seed_photos_prefix,
                                                                    monkeypatch):
        from tests import test_agent_culling as culling
        seed_photos_prefix(culling.PREFIX, culling.ROWS)
        nonce.reset()
        env = agent_app("legacy")
        headers = env.login(edition=True)
        tab = fake_tab(env, headers["Authorization"].split(" ", 1)[1])
        result = call(env, headers, "auto_cull", {"group_by": "burst", "strictness": 0, **culling.SCOPE})
        assert result["ok"], result
        # The one read is the plan digest the tab has pinned, kept so an apply can check the tab still shows
        # this plan; nothing it returns feeds the plan, and no review state is read back.
        assert [c["tool"] for c in tab.calls] == ["ui_get_context"]

    def test_the_request_body_carries_only_the_call_and_the_selection(self):
        from pydantic import ValidationError
        from api.models.mcp_inpage import McpCallRequest
        assert set(McpCallRequest.model_fields) == {"tool", "arguments", "selection_snapshot", "tab_id"}
        with pytest.raises(ValidationError):
            McpCallRequest.model_validate({"tool": "auto_cull", "review": {"keep": []}})
