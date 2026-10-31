"""Darkroom agent tools (``list_culling_groups`` ... ``confirm_culling_groups``) over /mcp.

Seeds a burst, a similar-free library slice and a bracket set under ``AGENT_DIR`` with
a unique capture-date window so ``date_from``/``date_to`` scope every call to them.
"""

import sqlite3

import pytest

from api.agent import nonce, tools_culling
from tests.conftest import _TEST_DB_FILE, AGENT_DIR

PREFIX = AGENT_DIR + "cull/"
DATE_FROM, DATE_TO = "1999:01:01 00:00:00", "1999:01:01 23:59:59"
SCOPE = {"date_from": DATE_FROM, "date_to": DATE_TO}


def _burst(name, second, score, gid, lead):
    return {"path": PREFIX + name, "filename": name, "date_taken": f"1999:01:01 10:00:{second:02d}",
            "aggregate": score, "aesthetic": score, "tech_sharpness": score,
            "burst_group_id": gid, "is_burst_lead": lead}


def _bracket(name, second, offset):
    return {"path": PREFIX + name, "filename": name, "date_taken": f"1999:01:01 15:00:{second:02d}",
            "aggregate": 6.0, "aesthetic": 6.0, "tech_sharpness": 6.0, "sequence_kind": "bracket",
            "sequence_group_id": 77, "sequence_ev_offset": offset}


ROWS = [
    _burst("b1.jpg", 1, 9.0, 4242, 1), _burst("b2.jpg", 2, 5.0, 4242, 0),
    _burst("b3.jpg", 3, 2.0, 4242, 0),
    _bracket("k1.jpg", 1, -2), _bracket("k2.jpg", 2, 0), _bracket("k3.jpg", 3, 2),
]
BURST_PATHS = [PREFIX + n for n in ("b1.jpg", "b2.jpg", "b3.jpg")]
BRACKET_PATHS = [PREFIX + n for n in ("k1.jpg", "k2.jpg", "k3.jpg")]


@pytest.fixture()
def photos(seed_photos_prefix):
    return seed_photos_prefix(PREFIX, ROWS)


@pytest.fixture()
def env_token(agent_app, photos):
    nonce.reset()
    env = agent_app("legacy")
    return env, env.token(env.login(edition=True), "edition")


def _rejected():
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        return {r[0] for r in conn.execute(
            "SELECT path FROM photos WHERE path LIKE ? AND COALESCE(is_rejected,0)=1", (PREFIX + "%",))}


def _counts():
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        return (conn.execute("SELECT COUNT(*) FROM comparisons").fetchone()[0],
                conn.execute("SELECT COUNT(*) FROM photos WHERE COALESCE(is_rejected,0)=1").fetchone()[0])


class TestGrant:
    def test_user_and_readonly_tokens_are_refused(self, agent_app, photos):
        env = agent_app("multi")
        headers = env.login("alice")
        for level in ("readonly", "user"):
            token = env.token(headers, level)
            for tool, args in (("list_culling_groups", {}), ("culling_profiles", {}),
                               ("auto_cull", {}), ("keeper_hints", {"paths": ["/x"]}),
                               ("confirm_culling_groups", {"groups": [
                                   {"type": "burst", "group_id": 1, "paths": ["/x"], "keep_paths": ["/x"]}]})):
                result = env.call(token, tool, args)
                assert result.get("error") == "forbidden_level", (level, tool, result)


class TestListGroups:
    def test_identity_pair_matches_the_router(self, env_token):
        env, token = env_token
        result = env.call(token, "list_culling_groups", {"group_by": "burst", **SCOPE})
        assert result["ok"], result
        direct = env.client.get("/api/culling-groups", params={"group_by": "burst", **SCOPE},
                                headers=env.login(edition=True)).json()
        assert [(g["type"], g["group_id"]) for g in result["data"]["rows"]] == \
            [(g["type"], g["group_id"]) for g in direct["groups"]]
        group = result["data"]["rows"][0]
        assert group["type"] == "burst" and group["photo_count"] == 3
        assert {p["path"] for p in group["photos"]} == set(BURST_PATHS)

    def test_default_group_by_all_lists_the_burst(self, env_token):
        env, token = env_token
        result = env.call(token, "list_culling_groups", SCOPE)
        assert result["ok"], result
        assert [g["type"] for g in result["data"]["rows"]] == ["burst"], result

    def test_bracket_set_carries_its_sequence_kind(self, env_token):
        env, token = env_token
        result = env.call(token, "list_culling_groups", {"group_by": "bracket", **SCOPE})
        group = result["data"]["rows"][0]
        assert (group["type"], group["sequence_kind"]) == ("bracket", "bracket")
        assert {p["path"] for p in group["photos"]} == set(BRACKET_PATHS)

    def test_a_page_over_the_byte_budget_sheds_members_not_groups(self):
        groups = [{"type": "scene", "group_id": g, "photos": [
            {"path": f"/p/{g}/{i}.jpg", "filename": "x" * 40, "date_taken": "1999:01:01 10:00:00"}
            for i in range(45)]} for g in range(20)]
        rows = tools_culling._fit_groups([tools_culling._compact_group(g) for g in groups], 20000)
        assert len(rows) == 20
        assert tools_culling.encoded_size({"rows": rows}) <= 20000
        assert all(row["photo_count"] == 45 for row in rows)
        assert all(row["photos_truncated"] is True for row in rows)
        assert any(len(row["photos"]) < tools_culling.GROUP_PHOTO_LIMIT for row in rows)

    def test_has_more_signals_further_pages(self, env_token):
        env, token = env_token
        result = env.call(token, "list_culling_groups", {"group_by": "burst", "per_page": 1, **SCOPE})
        assert result["data"]["has_more"] is False

    def test_has_more_is_true_on_a_page_with_more_behind_it(self, env_token, seed_photos_prefix):
        env, token = env_token
        window = {"date_from": "1998:01:01 00:00:00", "date_to": "1998:01:01 23:59:59"}
        rows = [{**_burst(f"p{gid}_{i}.jpg", i, 9.0 - i, gid, int(i == 0)),
                 "date_taken": f"1998:01:01 1{gid - 5000}:00:{i:02d}"} for gid in (5001, 5002) for i in range(3)]
        seed_photos_prefix(PREFIX + "pg/", [{**r, "path": PREFIX + "pg/" + r["filename"]} for r in rows])
        first = env.call(token, "list_culling_groups", {"group_by": "burst", "per_page": 1, **window})
        assert first["ok"] and len(first["data"]["rows"]) == 1 and first["data"]["has_more"] is True, first
        both = env.call(token, "list_culling_groups", {"group_by": "burst", "per_page": 2, **window})
        assert len(both["data"]["rows"]) == 2 and both["data"]["has_more"] is False

    def test_groups_seeded_after_a_first_call_are_visible_at_once(self, env_token, seed_photos_prefix):
        env, token = env_token
        window = {"date_from": "1997:01:01 00:00:00", "date_to": "1997:01:01 23:59:59"}
        assert env.call(token, "list_culling_groups", {"group_by": "burst", **window})["data"]["rows"] == []
        seed_photos_prefix(PREFIX + "late/", [
            {**_burst(f"l{i}.jpg", i, 9.0 - i, 6001, int(i == 0)), "path": PREFIX + f"late/l{i}.jpg",
             "date_taken": f"1997:01:01 10:00:{i:02d}"} for i in range(3)])
        rows = env.call(token, "list_culling_groups", {"group_by": "burst", **window})["data"]["rows"]
        assert [g["photo_count"] for g in rows] == [3]

    def test_rejecting_a_frame_through_the_gallery_route_refreshes_the_feed(self, env_token):
        env, token = env_token
        before = env.call(token, "list_culling_groups", {"group_by": "burst", **SCOPE})["data"]["rows"]
        assert [g["photo_count"] for g in before] == [3]
        resp = env.client.post("/api/photo/toggle_rejected", json={"photo_path": BURST_PATHS[2]},
                               headers=env.login(edition=True))
        assert resp.status_code == 200, resp.text
        after = env.call(token, "list_culling_groups", {"group_by": "burst", **SCOPE})["data"]["rows"]
        assert [g["photo_count"] for g in after] == [2]

    def test_bad_timestamp_is_invalid_input_before_any_call(self, env_token):
        env, token = env_token
        result = env.call(token, "list_culling_groups", {"date_from": "yesterday"})
        assert result["error"] == "invalid_input" and "YYYY-MM-DD" in result["message"]

    def test_iso_dates_are_accepted_and_scope_the_feed(self, env_token):
        env, token = env_token
        rows = env.call(token, "list_culling_groups", {
            "group_by": "burst", "date_from": "1999-01-01", "date_to": "1999-01-01"})["data"]["rows"]
        assert [g["photo_count"] for g in rows] == [3]
        none = env.call(token, "list_culling_groups", {
            "group_by": "burst", "date_from": "2001-01-01", "date_to": "2001-01-01"})
        assert none["ok"] and none["data"]["rows"] == []


class TestAutoCull:
    def args(self, **extra):
        return {"group_by": "all", **SCOPE, **extra}

    def test_auto_cull_accepts_iso_date(self, env_token):
        env, token = env_token
        result = env.call(token, "auto_cull", {"group_by": "burst", "date_from": "1999-01-01",
                                               "date_to": "1999-01-01"})
        assert result["ok"], result
        assert {g["group_id"] for g in result["data"]["rows"]} == {4242}

    def test_auto_cull_bad_date_is_invalid_input_naming_the_forms(self, env_token):
        env, token = env_token
        result = env.call(token, "auto_cull", {"date_from": "1999-13-45"})
        assert result["error"] == "invalid_input" and "YYYY-MM-DD" in result["message"]

    @pytest.mark.parametrize("group_by,kinds", [("burst", []), ("similar", ["similar"]),
                                                ("scene", ["scene"]), ("all", ["similar"])])
    def test_auto_cull_scope_dependent_kinds(self, env_token, group_by, kinds):
        env, token = env_token
        result = env.call(token, "auto_cull", {"group_by": group_by, **SCOPE})
        assert result["ok"], result
        assert result["data"]["scope_dependent_kinds"] == kinds
        assert ("whole range in one call" in result.get("note", "")) == bool(kinds)

    def _tab(self, env, fake_tab, reply=None):
        headers = env.login(edition=True)
        tab = fake_tab(env, _jwt_of(headers), reply=reply or (
            lambda call: {"ok": True, "data": {"route": "/culling", "plan_digest": call["args"]["plan_digest"],
                                               "groups_total": 1}} if call["tool"] == "ui_show_culling_plan"
            else {"ok": True, "data": {"route": "/"}}))
        return tab, env.token(headers, "edition")

    def test_auto_cull_dry_run_opens_the_plan_in_the_tab(self, agent_app, photos, fake_tab):
        nonce.reset()
        env = agent_app("legacy")
        tab, token = self._tab(env, fake_tab)
        result = env.call(token, "auto_cull", {"group_by": "burst", **SCOPE, "strictness": 0})
        assert result["ok"], result
        assert [c["tool"] for c in tab.calls] == ["ui_show_culling_plan"]
        args = tab.calls[0]["args"]
        assert args["plan_digest"] == result["data"]["plan_digest"] and "focus" not in args
        assert args["request"]["group_by"] == "burst" and args["request"]["strictness"] == 0
        assert args["request"]["date_from"] == DATE_FROM and args["request"]["date_to"] == DATE_TO
        assert result["shown_in_tab"]["applied"] is True

    def test_the_shown_request_carries_the_overrides_the_digest_was_computed_with(self, agent_app, photos, fake_tab):
        nonce.reset()
        env = agent_app("legacy")
        tab, token = self._tab(env, fake_tab)
        overrides = {"keep_paths": [BURST_PATHS[2]], "remove_paths": [BURST_PATHS[1]]}
        result = env.call(token, "auto_cull", {"group_by": "burst", "strictness": 0, **SCOPE, **overrides})
        assert result["ok"], result
        request = tab.calls[0]["args"]["request"]
        assert request["keep_paths"] == overrides["keep_paths"] and request["remove_paths"] == overrides["remove_paths"]

    def test_auto_cull_show_failure_does_not_fail(self, agent_app, photos):
        nonce.reset()
        env = agent_app("legacy")
        result = env.call(env.token(env.login(edition=True), "edition"), "auto_cull",
                          {"group_by": "burst", **SCOPE})
        assert result["ok"] and result["shown_in_tab"]["applied"] is False and result["shown_in_tab"]["reason"] == "no_tab"
        assert result["confirm"]

    @pytest.mark.parametrize("code", ["unsaved_decisions", "plan_changed", "plan_load_failed", "stack_mode_active", "too_large"])
    def test_a_tab_refusal_becomes_the_reason(self, agent_app, photos, fake_tab, code):
        nonce.reset()
        env = agent_app("legacy")
        tab, token = self._tab(env, fake_tab, reply=lambda call: {"ok": False, "error": code, "message": "no"})
        result = env.call(token, "auto_cull", {"group_by": "burst", **SCOPE})
        assert result["ok"] and result["shown_in_tab"] == {"applied": False, "reason": code}
        assert result["confirm"]

    def test_a_request_too_big_for_the_bridge_is_not_sent(self, agent_app, photos, fake_tab):
        from api.agent import bridge
        nonce.reset()
        env = agent_app("legacy")
        tab, token = self._tab(env, fake_tab)
        stale = [f"/agent-seeded/old/{'x' * 300}/{i:04d}.jpg" for i in range(1000)]
        assert len("".join(stale)) > bridge.MAX_FRAME_BYTES
        result = env.call(token, "auto_cull", {"group_by": "burst", "strictness": 0, **SCOPE, "remove_paths": stale})
        assert result["ok"], result
        assert result["shown_in_tab"]["applied"] is False and result["shown_in_tab"]["reason"] == "too_large"
        assert [c["tool"] for c in tab.calls] == ["ui_get_context"] and result["confirm"]

    def test_auto_cull_show_false_skips(self, agent_app, photos, fake_tab):
        nonce.reset()
        env = agent_app("legacy")
        tab, token = self._tab(env, fake_tab)
        result = env.call(token, "auto_cull", {"group_by": "burst", **SCOPE, "show": False})
        assert result["ok"] and "ui_show_culling_plan" not in [c["tool"] for c in tab.calls]
        assert "shown_in_tab" not in result

    def test_auto_cull_apply_never_shows_and_reads_the_tab_once_for_the_pin(self, agent_app, photos, fake_tab):
        nonce.reset()
        env = agent_app("legacy")
        tab, token = self._tab(env, fake_tab)
        first = env.call(token, "auto_cull", {"group_by": "burst", **SCOPE})
        shown = len(tab.calls)
        result = env.call(token, "auto_cull", {"group_by": "burst", **SCOPE, "dry_run": False,
                                               "confirm": first["confirm"]})
        assert result["ok"], result
        assert shown == 2 and [c["tool"] for c in tab.calls[shown:]] == ["ui_get_context"]
        assert "ui_show_culling_plan" not in [c["tool"] for c in tab.calls[shown:]] and "shown_in_tab" not in result

    def test_auto_cull_description_says_one_call(self, env_token):
        env, token = env_token
        tools = env.rpc(token, "tools/list").json()["result"]["tools"]
        text = next(t["description"] for t in tools if t["name"] == "auto_cull")
        assert "ONE call" in text and "month" in text

    def test_preview_writes_nothing_and_issues_a_nonce(self, env_token):
        env, token = env_token
        before = _counts()
        result = env.call(token, "auto_cull", self.args())
        assert result["ok"] and result["data"]["dry_run"] is True and result["confirm"]
        assert _counts() == before and _rejected() == set()

    def test_apply_without_or_with_a_wrong_nonce_is_refused(self, env_token):
        env, token = env_token
        for confirm in (None, "bogus"):
            result = env.call(token, "auto_cull", self.args(dry_run=False, confirm=confirm))
            assert result["error"] == "confirmation_required"
        assert _rejected() == set()

    def test_apply_with_the_preview_nonce_rejects_and_keeps_the_bracket_whole(self, env_token):
        env, token = env_token
        preview = env.call(token, "auto_cull", self.args(strictness=0))
        planned = {p for g in preview["data"]["rows"] for p in g["reject_paths"]}
        assert planned and planned <= set(BURST_PATHS)
        assert not {p for g in preview["data"]["rows"] for p in g["keep_paths"] + g["reject_paths"]} \
            & set(BRACKET_PATHS)
        result = env.call(token, "auto_cull", self.args(strictness=0, dry_run=False,
                                                       confirm=preview["confirm"]))
        assert result["ok"], result
        assert _rejected() == planned
        assert not _rejected() & set(BRACKET_PATHS)

    def test_a_nonce_is_single_use(self, env_token):
        env, token = env_token
        preview = env.call(token, "auto_cull", self.args(strictness=0))
        args = self.args(strictness=0, dry_run=False, confirm=preview["confirm"])
        assert env.call(token, "auto_cull", args)["ok"]
        assert env.call(token, "auto_cull", args)["error"] == "confirmation_required"

    def test_a_plan_changed_since_the_preview_is_refused(self, env_token):
        env, token = env_token
        preview = env.call(token, "auto_cull", self.args(strictness=0))
        with sqlite3.connect(_TEST_DB_FILE.name) as conn:
            conn.execute("UPDATE photos SET aggregate = 9.5, aesthetic = 9.5, tech_sharpness = 9.5 "
                         "WHERE path = ?", (PREFIX + "b3.jpg",))
        result = env.call(token, "auto_cull", self.args(strictness=0, dry_run=False,
                                                       confirm=preview["confirm"]))
        assert result["error"] == "confirmation_required"
        assert _rejected() == set()

    def test_a_nonce_does_not_cross_options(self, env_token):
        env, token = env_token
        preview = env.call(token, "auto_cull", self.args(strictness=0))
        result = env.call(token, "auto_cull", self.args(strictness=100, dry_run=False,
                                                       confirm=preview["confirm"]))
        assert result["error"] == "confirmation_required"


BIG_PREFIX = PREFIX + "big/" + "d" * 70 + "/"
BIG_WINDOW = {"date_from": "1996-01-01", "date_to": "1996-01-01"}
BIG_GROUPS = 120


def _big_rows():
    return [{"path": f"{BIG_PREFIX}{'f' * 24}_{g:03d}_{i}.jpg", "filename": f"{g}_{i}.jpg",
             "date_taken": f"1996:01:01 {g // 60:02d}:{g % 60:02d}:{i:02d}",
             "aggregate": 9.0 - 3 * i, "aesthetic": 9.0 - 3 * i, "tech_sharpness": 9.0 - 3 * i,
             "burst_group_id": 7000 + g, "is_burst_lead": int(i == 0)}
            for g in range(BIG_GROUPS) for i in range(3)]


@pytest.fixture()
def big(env_token, seed_photos_prefix):
    seed_photos_prefix(BIG_PREFIX, _big_rows())
    return env_token


def _big_pages(env, token, **extra):
    pages, cursor, digest = [], 0, None
    while True:
        paging = {"cursor": cursor, "plan_digest": digest} if cursor else {}
        result = env.call(token, "auto_cull", {"group_by": "burst", "strictness": 100,
                                               **BIG_WINDOW, **paging, **extra})
        assert result["ok"], result
        pages.append(result)
        digest = result["data"]["plan_digest"]
        cursor = result["data"]["next_cursor"]
        if cursor is None:
            return pages
        assert len(pages) < 20


class TestAutoCullPaging:
    def test_a_page_fits_the_envelope_with_long_paths(self, big):
        env, token = big
        first = _big_pages(env, token)[0]
        photos = sum(len(r["keep_paths"]) + len(r["reject_paths"]) for r in first["data"]["rows"])
        assert 100 < photos <= 200 and len(first["data"]["rows"]) <= 100
        assert max(len(p) for r in first["data"]["rows"] for p in r["keep_paths"]) >= 120
        assert "truncated" not in first and "next_offset" not in first
        assert len(first["data"]["rows"]) == first["data"]["next_cursor"]
        assert tools_culling.encoded_size(first) <= 60000

    def test_auto_cull_large_plan_confirmable(self, big):
        env, token = big
        pages = _big_pages(env, token)
        assert len(pages) >= 2 and pages[0]["confirm"] and all("confirm" not in p for p in pages[1:])
        planned = {p for page in pages for g in page["data"]["rows"] for p in g["reject_paths"]}
        assert len(planned) == BIG_GROUPS * 2
        result = env.call(token, "auto_cull", {"group_by": "burst", "strictness": 100, "dry_run": False,
                                               "confirm": pages[0]["confirm"], **BIG_WINDOW})
        assert result["ok"], result
        assert {p for p in _rejected() if p.startswith(BIG_PREFIX)} == planned

    def test_the_apply_is_refused_when_the_plan_moved_after_the_nonce_check(self, big):
        env, token = big
        pages = _big_pages(env, token)
        with sqlite3.connect(_TEST_DB_FILE.name) as conn:
            conn.execute("UPDATE photos SET aggregate = 9.9, aesthetic = 9.9, tech_sharpness = 9.9 "
                         "WHERE path LIKE ? AND path LIKE '%\\_001\\_2.jpg' ESCAPE '\\'", (BIG_PREFIX + "%",))
        result = env.call(token, "auto_cull", {"group_by": "burst", "strictness": 100, "dry_run": False,
                                               "confirm": pages[0]["confirm"], **BIG_WINDOW})
        assert result["error"] == "confirmation_required"
        assert not {p for p in _rejected() if p.startswith(BIG_PREFIX)}


@pytest.fixture()
def big_env(agent_app, seed_photos_prefix):
    def make(**mcp):
        nonce.reset()
        seed_photos_prefix(BIG_PREFIX, _big_rows())
        env = agent_app("legacy", **mcp)
        return env, env.token(env.login(edition=True), "edition")
    return make


def _big_rejected():
    return {p for p in _rejected() if p.startswith(BIG_PREFIX)}


def _assert_every_group_once(pages):
    numbers = [row["number"] for page in pages for row in page["data"]["rows"]]
    assert numbers == list(range(1, BIG_GROUPS + 1))
    assert not any("truncated" in page or "returned" in page for page in pages)


class TestAutoCullPageBudget:
    def test_stale_overrides_do_not_make_the_envelope_drop_groups(self, big_env):
        env, token = big_env()
        stale = [f"/agent-seeded/old-session/{'x' * 90}/{i:04d}.jpg" for i in range(300)]
        pages = _big_pages(env, token, remove_paths=stale)
        _assert_every_group_once(pages)
        data = pages[0]["data"]
        assert len(data["ignored_overrides"]) == 20 and data["ignored_overrides_count"] == 300
        result = env.call(token, "auto_cull", {"group_by": "burst", "strictness": 100, "dry_run": False,
                                               "remove_paths": stale, "confirm": pages[0]["confirm"],
                                               **BIG_WINDOW})
        assert result["ok"], result
        assert _big_rejected() == {p for page in pages for r in page["data"]["rows"]
                                   for p in r["reject_paths"]}

    def test_a_small_operator_max_bytes_pages_by_whole_groups(self, big_env):
        env, token = big_env(max_bytes=30000)
        pages = _big_pages(env, token)
        _assert_every_group_once(pages)
        assert len(pages) > 2 and all(tools_culling.encoded_size(p) <= 30000 for p in pages)

    def test_the_apply_returns_counts_only(self, big_env):
        env, token = big_env(max_bytes=30000)
        first = env.call(token, "auto_cull", {"group_by": "burst", "strictness": 100, "show": False,
                                              **BIG_WINDOW})
        result = env.call(token, "auto_cull", {"group_by": "burst", "strictness": 100, "dry_run": False,
                                               "confirm": first["confirm"], **BIG_WINDOW})
        assert result["ok"], result
        assert set(result["data"]) <= {"groups_processed", "kept", "rejected", "highlights_added", "dry_run"}
        assert result["data"]["rejected"] == BIG_GROUPS * 2 and len(_big_rejected()) == BIG_GROUPS * 2

    def test_a_later_page_needs_the_plan_digest(self, big_env):
        env, token = big_env()
        first = env.call(token, "auto_cull", {"group_by": "burst", "strictness": 100, "show": False,
                                              **BIG_WINDOW})
        result = env.call(token, "auto_cull", {"group_by": "burst", "strictness": 100, "show": False,
                                               "cursor": first["data"]["next_cursor"], **BIG_WINDOW})
        assert result["error"] == "invalid_input" and "plan_digest" in result["message"]

    def test_a_plan_that_moves_between_pages_refuses_the_next_page(self, big_env):
        env, token = big_env()
        args = {"group_by": "burst", "strictness": 100, "show": False, **BIG_WINDOW}
        first = env.call(token, "auto_cull", args)
        with sqlite3.connect(_TEST_DB_FILE.name) as conn:
            conn.execute("UPDATE photos SET burst_reviewed = 1 WHERE burst_group_id = 7000 AND path LIKE ?",
                         (BIG_PREFIX + "%",))
        second = env.call(token, "auto_cull", {**args, "cursor": first["data"]["next_cursor"],
                                               "plan_digest": first["data"]["plan_digest"]})
        assert second["error"] == "confirmation_required" and "cursor 0" in second["message"]

    def test_only_the_first_page_issues_a_confirm_so_many_pages_keep_it_valid(self, big_env):
        env, token = big_env()
        first = env.call(token, "auto_cull", {"group_by": "burst", "strictness": 100, "show": False,
                                              **BIG_WINDOW})
        for _ in range(nonce.MAX_PENDING_PER_OWNER + 4):
            later = env.call(token, "auto_cull", {
                "group_by": "burst", "strictness": 100, "show": False, **BIG_WINDOW,
                "cursor": first["data"]["next_cursor"], "plan_digest": first["data"]["plan_digest"]})
            assert later["ok"] and "confirm" not in later
        result = env.call(token, "auto_cull", {"group_by": "burst", "strictness": 100, "dry_run": False,
                                               "confirm": first["confirm"], **BIG_WINDOW})
        assert result["ok"], result

    def test_the_plan_moving_after_the_nonce_check_is_refused_by_expected_digest(self, big_env, monkeypatch):
        from api.agent.internal_client import InternalClient
        env, token = big_env()
        first = env.call(token, "auto_cull", {"group_by": "burst", "strictness": 100, "show": False,
                                              **BIG_WINDOW})
        real = InternalClient.call

        async def call(self, grant, name, *a, **kw):
            body = kw.get("json")
            if name == "culling.auto" and isinstance(body, dict) and body.get("dry_run") is False:
                with sqlite3.connect(_TEST_DB_FILE.name) as conn:
                    conn.execute("UPDATE photos SET aggregate = 9.9, aesthetic = 9.9, tech_sharpness = 9.9 "
                                 "WHERE path LIKE ? AND path LIKE '%\\_001\\_2.jpg' ESCAPE '\\'",
                                 (BIG_PREFIX + "%",))
            return await real(self, grant, name, *a, **kw)
        monkeypatch.setattr(InternalClient, "call", call)
        result = env.call(token, "auto_cull", {"group_by": "burst", "strictness": 100, "dry_run": False,
                                               "confirm": first["confirm"], **BIG_WINDOW})
        assert result["error"] == "confirmation_required"
        assert not _big_rejected()

    def test_a_restated_removal_of_a_trimmed_bracket_rung_is_not_refused(self):
        from api.routers import burst_culling as bc
        photos = [{"path": "/b/k0.jpg", "sequence_ev_offset": 0},
                  {"path": "/b/k-2.jpg", "sequence_ev_offset": -2},
                  {"path": "/b/k+2.jpg", "sequence_ev_offset": 2}]
        plan = bc._plan_auto_cull_groups(
            [{"type": "bracket", "group_id": 9, "sequence_kind": "bracket", "photos": photos}], set(), 50, 1)
        assert "/b/k-2.jpg" in plan[0]["reject_paths"]
        effective, ignored = bc._apply_plan_overrides(plan, [], ["/b/k-2.jpg"])
        assert ignored == [] and effective == {"keep": [], "remove": []}
        with pytest.raises(bc.AutoCullOverrideError):
            bc._apply_plan_overrides(plan, [], ["/b/k0.jpg"])

    def test_trim_brackets_makes_bracket_scope_dependent(self, env_token):
        env, token = env_token
        result = env.call(token, "auto_cull", {"group_by": "burst", "trim_brackets": True, **SCOPE})
        assert result["ok"], result
        assert result["data"]["scope_dependent_kinds"] == ["bracket"]


class TestAutoCullOverrides:
    def args(self, **extra):
        return {"group_by": "burst", "strictness": 0, **SCOPE, **extra}

    def test_description_documents_the_protocol(self, env_token):
        env, token = env_token
        tools = env.rpc(token, "tools/list").json()["result"]["tools"]
        text = next(t["description"] for t in tools if t["name"] == "auto_cull")
        for needle in ("keep_paths", "remove_paths", "ui_get_context", "SAME", "next_cursor", "300"):
            assert needle in text, needle

    def test_overrides_are_applied_under_the_same_confirm(self, env_token):
        env, token = env_token
        overrides = {"keep_paths": [BURST_PATHS[2]], "remove_paths": [BURST_PATHS[1]]}
        preview = env.call(token, "auto_cull", self.args(**overrides))
        assert preview["ok"], preview
        row = preview["data"]["rows"][0]
        assert row["reject_paths"] == [BURST_PATHS[1]] and BURST_PATHS[2] in row["keep_paths"]
        result = env.call(token, "auto_cull", self.args(dry_run=False, confirm=preview["confirm"], **overrides))
        assert result["ok"], result
        assert _rejected() == {BURST_PATHS[1]}

    def test_a_confirm_does_not_cover_different_overrides(self, env_token):
        env, token = env_token
        preview = env.call(token, "auto_cull", self.args(remove_paths=[BURST_PATHS[1]]))
        result = env.call(token, "auto_cull", self.args(dry_run=False, confirm=preview["confirm"]))
        assert result["error"] == "confirmation_required"
        assert _rejected() == set()

    def test_stale_paths_are_reported_not_applied(self, env_token):
        env, token = env_token
        result = env.call(token, "auto_cull", self.args(remove_paths=["/not/in/plan.jpg"]))
        assert result["ok"] and result["data"]["ignored_overrides"] == ["/not/in/plan.jpg"]

    def test_refusals_name_the_paths_and_groups(self, env_token):
        env, token = env_token
        both = env.call(token, "auto_cull", self.args(keep_paths=[BURST_PATHS[0]], remove_paths=[BURST_PATHS[0]]))
        assert both["error"] == "invalid_input" and BURST_PATHS[0] in both["message"]
        zero = env.call(token, "auto_cull", self.args(remove_paths=BURST_PATHS[:2]))
        assert zero["error"] == "invalid_input" and "4242" in zero["message"]

    def test_too_many_override_paths_are_invalid(self, env_token):
        env, token = env_token
        result = env.call(token, "auto_cull", self.args(remove_paths=[f"/p{i}" for i in range(1001)]))
        assert result["error"] == "invalid_input"


class TestConfirm:
    def group(self, type_, paths, keep):
        return {"type": type_, "group_id": 4242 if type_ == "burst" else 77, "paths": paths,
                "keep_paths": keep}

    def test_confirm_rejects_the_unkept_frames(self, env_token):
        env, token = env_token
        result = env.call(token, "confirm_culling_groups", {
            "groups": [self.group("burst", BURST_PATHS, BURST_PATHS[:1])]})
        assert result["ok"], result
        row = result["data"]["rows"][0]
        assert (row["type"], row["group_id"], row["ok"]) == ("burst", 4242, True)
        assert _rejected() == set(BURST_PATHS[1:])

    def test_empty_keep_needs_the_nonce_flow(self, env_token):
        env, token = env_token
        groups = [self.group("burst", BURST_PATHS, [])]
        first = env.call(token, "confirm_culling_groups", {"groups": groups})
        assert first["error"] == "confirmation_required" and first["confirm"]
        assert _rejected() == set()
        other = [self.group("burst", BURST_PATHS[:2], [])]
        assert env.call(token, "confirm_culling_groups", {
            "groups": other, "confirm": first["confirm"]})["error"] == "confirmation_required"
        again = env.call(token, "confirm_culling_groups", {"groups": groups})
        done = env.call(token, "confirm_culling_groups", {"groups": groups, "confirm": again["confirm"]})
        assert done["ok"] and _rejected() == set(BURST_PATHS)

    def test_partial_selection_of_a_bracket_is_refused(self, env_token):
        env, token = env_token
        result = env.call(token, "confirm_culling_groups", {
            "groups": [self.group("bracket", BRACKET_PATHS, BRACKET_PATHS[:1])]})
        assert result["error"] == "invalid_input"
        assert _rejected() == set()

    def test_keeping_a_whole_bracket_is_accepted(self, env_token):
        env, token = env_token
        result = env.call(token, "confirm_culling_groups", {
            "groups": [self.group("bracket", BRACKET_PATHS, BRACKET_PATHS)]})
        assert result["ok"] and _rejected() == set()

    def test_keep_outside_paths_is_invalid(self, env_token):
        env, token = env_token
        result = env.call(token, "confirm_culling_groups", {
            "groups": [self.group("burst", BURST_PATHS[:2], BURST_PATHS)]})
        assert result["error"] == "invalid_input"


class TestProfiles:
    def test_profiles_suggest_and_hints(self, env_token):
        env, token = env_token
        assert env.call(token, "culling_profiles")["data"]["profiles"]
        suggest = env.call(token, "suggest_culling_profile", SCOPE)
        assert suggest["ok"] and "confidence" in suggest["data"]
        assert env.call(token, "suggest_culling_profile", {"date_to": "x"})["error"] == "invalid_input"
        hints = env.call(token, "keeper_hints", {"paths": BURST_PATHS})
        assert hints["ok"] and isinstance(hints["data"]["rows"], list)


class TestAutoCullRowsCarryReasons:
    def test_rows_have_a_group_reason_key_reject_only_reasons_and_a_kind(self, env_token):
        env, token = env_token
        result = env.call(token, "auto_cull", {"group_by": "burst", "strictness": 0, "show": False, **SCOPE})
        assert result["ok"], result
        row = result["data"]["rows"][0]
        assert row["group_reason"]["key"] in ("burst", "burst_seconds") and isinstance(row["group_reason"]["params"], dict)
        assert set(row["reasons"]) == set(row["reject_paths"]) and row["reject_paths"]
        assert all(set(r) == {"key", "value"} and r["key"] != "best" for r in row["reasons"].values())
        assert row["kind"] == "burst"


def test_group_reason_keys_for_every_plan_builder_string():
    from api.routers.burst_culling import _group_reason
    cases = [
        ({"type": "burst", "reason": "burst"}, "burst", {}),
        ({"type": "burst", "reason": "1.5s burst"}, "burst_seconds", {"seconds": 1.5}),
        ({"type": "burst", "reason": "2.5m burst"}, "burst_minutes", {"minutes": 2.5}),
        ({"type": "similar", "reason": "85% similar"}, "similar_percent", {"percent": 85}),
        ({"type": "scene", "reason": "12 photos"}, "photo_count", {"n": 12}),
        ({"type": "scene", "reason": "golden hour"}, "moment", {"moment": "golden hour"}),
        ({"type": "bracket", "reason": "4 frames, 1.3 EV span"}, "bracket_span", {"frames": 4, "ev_span": 1.3}),
        ({"type": "panorama", "reason": "9 frames"}, "frame_count", {"frames": 9}),
    ]
    for group, key, params in cases:
        assert _group_reason(group) == {"key": key, "params": params}, group
    assert _group_reason({"type": "burst"}) is None
    assert len(_group_reason({"type": "scene", "reason": "x" * 200})["params"]["moment"]) == 80


class TestAutoCullOversizedGroup:
    def test_a_single_group_over_the_budget_is_clipped_not_dropped(self, agent_app, seed_photos_prefix):
        nonce.reset()
        prefix = PREFIX + "huge/"
        rows = [{"path": f"{prefix}{'h' * 120}_{i:04d}.jpg", "filename": f"h{i}.jpg",
                 "date_taken": f"1997:02:02 00:{i // 60:02d}:{i % 60:02d}",
                 "aggregate": 5.0, "aesthetic": 5.0, "tech_sharpness": 5.0,
                 "burst_group_id": 9000, "is_burst_lead": int(i == 0)} for i in range(800)]
        rows += [{"path": f"{prefix}small_{i}.jpg", "filename": f"s{i}.jpg",
                  "date_taken": f"1997:02:02 05:00:{i:02d}", "aggregate": 9.0 - 3 * i,
                  "aesthetic": 9.0 - 3 * i, "tech_sharpness": 9.0 - 3 * i,
                  "burst_group_id": 9001, "is_burst_lead": int(i == 0)} for i in range(3)]
        seed_photos_prefix(prefix, rows)
        env = agent_app("legacy")
        token = env.token(env.login(edition=True), "edition")
        result = env.call(token, "auto_cull", {"group_by": "burst", "strictness": 100, "show": False,
                                               "date_from": "1997-02-02", "date_to": "1997-02-02"})
        assert result["ok"], result
        got = result["data"]["rows"]
        assert len(got) == 1 and got[0]["paths_clipped"] is True
        assert got[0]["keep_count"] + got[0]["reject_count"] == 800
        assert len(got[0]["keep_paths"]) + len(got[0]["reject_paths"]) < 800
        assert result["data"]["next_cursor"] == got[0]["number"]
        assert "truncated" not in result


def _jwt_of(headers):
    return headers["Authorization"].split(" ", 1)[1]


def _rate(path, **columns):
    sets = ", ".join(f"{k} = ?" for k in columns)
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        conn.execute(f"UPDATE photos SET {sets} WHERE path = ?", [*columns.values(), path])




class TestAutoCullPlanPaging:
    def test_a_later_page_only_moves_the_focus_to_its_first_group(self, big_env, fake_tab):
        env, token_unused = big_env()
        headers = env.login(edition=True)
        tab = fake_tab(env, _jwt_of(headers), reply=lambda call: {"ok": True, "data": {"route": "/culling"}})
        token = env.token(headers, "edition")
        base = {"group_by": "burst", "strictness": 100, **BIG_WINDOW}
        first = env.call(token, "auto_cull", base)
        assert first["ok"] and "focus" not in tab.calls[0]["args"]
        second = env.call(token, "auto_cull", {**base, "cursor": first["data"]["next_cursor"],
                                               "plan_digest": first["data"]["plan_digest"]})
        assert second["ok"], second
        args = tab.calls[1]["args"]
        assert args["focus"] == second["data"]["rows"][0]["number"] == first["data"]["next_cursor"] + 1
        assert args["plan_digest"] == first["data"]["plan_digest"] and args["request"] == tab.calls[0]["args"]["request"]


class TestAutoCullDescriptionTeachesThePlanPage:
    def test_the_description_names_the_culling_page_and_the_changed_groups(self, env_token):
        env, token = env_token
        tools = env.rpc(token, "tools/list").json()["result"]["tools"]
        text = next(t["description"] for t in tools if t["name"] == "auto_cull")
        for needle in ("/culling", "culling.changed", "keep_paths", "remove_paths", "shown_in_tab"):
            assert needle in text, needle
        assert "`review`" not in text and "read from their open tab" not in text


class TestAutoCullTabDefaults:
    """With neither strictness nor profile, auto_cull uses what the tab's /culling page would start at."""

    @pytest.fixture()
    def rig(self, agent_app, photos, fake_tab, monkeypatch):
        from tests.conftest import intercept_internal_call
        nonce.reset()
        tools_culling.reset_preview_memory()
        sent = []
        intercept_internal_call(monkeypatch, lambda tool, kw: sent.append(kw["json"]) if tool == "culling.auto" else None)
        env = agent_app("legacy")
        headers = env.login(edition=True)

        def build(defaults):
            def reply(call):
                if call["tool"] == "ui_get_context":
                    return {"ok": True, "data": {"route": "/", "culling_defaults": defaults}}
                return {"ok": True, "data": {"route": "/culling", "plan_digest": call["args"]["plan_digest"],
                                             "groups_total": 1}}
            tab = fake_tab(env, _jwt_of(headers), reply=reply)
            return type("Rig", (), {"env": env, "token": env.token(headers, "edition"), "tab": tab, "sent": sent})
        build.env, build.headers, build.sent = env, headers, sent
        return build

    @staticmethod
    def args(**extra):
        return {"group_by": "burst", **SCOPE, **extra}

    def test_the_tabs_stored_profile_is_used(self, rig):
        r = rig({"profile": "sports", "strictness": None})
        result = r.env.call(r.token, "auto_cull", self.args())
        assert result["ok"], result
        assert r.sent[0]["profile"] == "sports" and r.sent[0]["strictness"] is None
        assert result["data"]["knobs_from_tab"] == {"profile": "sports"}

    def test_a_stored_profile_and_strictness_are_both_used(self, rig):
        r = rig({"profile": "sports", "strictness": 40})
        result = r.env.call(r.token, "auto_cull", self.args())
        assert result["ok"], result
        assert r.sent[0]["profile"] == "sports" and r.sent[0]["strictness"] == 40
        assert result["data"]["knobs_from_tab"] == {"profile": "sports", "strictness": 40}

    def test_without_a_profile_the_page_default_strictness_is_used(self, rig):
        r = rig({"profile": None, "strictness": 100})
        result = r.env.call(r.token, "auto_cull", self.args())
        assert r.sent[0]["strictness"] == 100 and r.sent[0]["profile"] is None
        assert result["data"]["knobs_from_tab"] == {"strictness": 100}

    def test_an_unknown_stored_profile_falls_back_to_strictness(self, rig):
        r = rig({"profile": "nope", "strictness": 100})
        result = r.env.call(r.token, "auto_cull", self.args())
        assert r.sent[0]["strictness"] == 100 and r.sent[0]["profile"] is None
        assert result["data"]["knobs_from_tab"] == {"strictness": 100}

    @pytest.mark.parametrize("extra", [{"strictness": 30}, {"profile": "wedding"}])
    def test_an_explicit_knob_reads_the_tab_only_for_its_pin(self, rig, extra):
        r = rig({"profile": "sports", "strictness": 100})
        result = r.env.call(r.token, "auto_cull", self.args(show=False, **extra))
        assert result["ok"], result
        assert [c["tool"] for c in r.tab.calls] == ["ui_get_context"]
        assert "knobs_from_tab" not in result["data"] and r.sent[0]["profile"] == extra.get("profile")

    def test_no_tab_keeps_the_server_default(self, agent_app, photos, monkeypatch):
        from tests.conftest import intercept_internal_call
        nonce.reset()
        sent = []
        intercept_internal_call(monkeypatch, lambda tool, kw: sent.append(kw["json"]) if tool == "culling.auto" else None)
        env = agent_app("legacy")
        token = env.token(env.login(edition=True), "edition")
        result = env.call(token, "auto_cull", self.args())
        assert result["ok"], result
        assert sent[0]["strictness"] is None and sent[0]["profile"] is None
        assert "knobs_from_tab" not in result["data"]

    def test_the_shown_request_and_the_apply_carry_the_resolved_knobs(self, rig):
        r = rig({"profile": "sports", "strictness": 100})
        first = r.env.call(r.token, "auto_cull", self.args())
        shown = [c for c in r.tab.calls if c["tool"] == "ui_show_culling_plan"]
        assert shown[0]["args"]["request"]["profile"] == "sports"
        assert [c["tool"] for c in r.tab.calls].count("ui_get_context") == 1
        r.env.call(r.token, "auto_cull", self.args(dry_run=False, confirm=first["confirm"], show=False))
        assert r.sent[-1]["profile"] == "sports" and r.sent[-1]["dry_run"] is False

    def test_an_apply_with_explicit_overrides_uses_the_previews_knobs_and_not_the_tabs_defaults(self, rig):
        r = rig({"profile": "sports", "strictness": 100})
        over = {"keep_paths": [BURST_PATHS[1]]}
        first = r.env.call(r.token, "auto_cull", self.args(**over))
        assert first["ok"] and first.get("confirm"), first
        r.tab.reply = lambda call: {"ok": True, "data": {"culling_defaults": {"profile": None, "strictness": 100}}}
        before = [c["tool"] for c in r.tab.calls].count("ui_get_context")
        result = r.env.call(r.token, "auto_cull",
                            self.args(dry_run=False, confirm=first["confirm"], show=False, **over))
        assert result["ok"], result
        assert [c["tool"] for c in r.tab.calls].count("ui_get_context") == before + 1
        assert r.sent[-1]["profile"] == "sports" and r.sent[-1]["dry_run"] is False

    def test_a_changed_tab_default_refuses_the_apply(self, rig):
        r = rig({"profile": "sports", "strictness": 100})
        first = r.env.call(r.token, "auto_cull", self.args())
        tools_culling.reset_preview_memory()
        r.tab.reply = lambda call: {"ok": True, "data": {"culling_defaults": {"profile": "wedding", "strictness": 100}}}
        result = r.env.call(r.token, "auto_cull", self.args(dry_run=False, confirm=first["confirm"]))
        assert not result["ok"] and result["error"] == "confirmation_required"

    def test_the_description_states_the_rule(self, env_token):
        env, token = env_token
        tools = env.rpc(token, "tools/list").json()["result"]["tools"]
        text = next(t for t in tools if t["name"] == "auto_cull")["description"]
        assert "/culling defaults" in text
        assert "never reads the tab" not in text and "slider's stored" in text


class TestApplyRefusedWhenThePageReplanned:
    """The apply reads the tab's pinned plan digest: a re-plan on the page supersedes the previewed plan."""

    @pytest.fixture()
    def rig(self, agent_app, photos, fake_tab, monkeypatch):
        from tests.conftest import intercept_internal_call
        nonce.reset()
        tools_culling.reset_preview_memory()
        sent = []
        intercept_internal_call(monkeypatch, lambda tool, kw: sent.append(kw["json"]) if tool == "culling.auto" else None)
        env = agent_app("legacy")
        headers = env.login(edition=True)
        state = {"pin": None, "show": "ok"}

        def reply(call):
            if call["tool"] == "ui_get_context":
                culling = {"plan_digest": state["pin"]} if state["pin"] else None
                return {"ok": True, "data": {"route": "/culling", "culling": culling,
                                             "culling_defaults": {"profile": None, "strictness": 100}}}
            if state["show"] != "ok":
                return {"ok": False, "error": state["show"], "message": "no"}
            state["pin"] = call["args"]["plan_digest"]
            return {"ok": True, "data": {"route": "/culling", "plan_digest": state["pin"], "groups_total": 1}}
        tab = fake_tab(env, _jwt_of(headers), reply=reply)
        return type("Rig", (), {"env": env, "token": env.token(headers, "edition"), "tab": tab,
                                "sent": sent, "state": state, "jwt": _jwt_of(headers)})

    @staticmethod
    def args(**extra):
        return {"group_by": "burst", "strictness": 0, **SCOPE, **extra}

    @staticmethod
    def applied(r):
        return [c for c in r.sent if c.get("dry_run") is False]

    def test_an_unchanged_pin_lets_the_apply_through(self, rig):
        r = rig
        first = r.env.call(r.token, "auto_cull", self.args())
        assert first["shown_in_tab"]["applied"] is True
        result = r.env.call(r.token, "auto_cull", self.args(dry_run=False, confirm=first["confirm"]))
        assert result["ok"], result
        assert len(self.applied(r)) == 1

    def test_a_replanned_page_refuses_the_apply(self, rig):
        r = rig
        first = r.env.call(r.token, "auto_cull", self.args())
        r.state["pin"] = "f" * 64
        result = r.env.call(r.token, "auto_cull", self.args(dry_run=False, confirm=first["confirm"]))
        assert not result["ok"] and result["error"] == "confirmation_required"
        assert "re-planned" in result["message"]
        assert self.applied(r) == []

    def test_an_unreachable_tab_lets_the_apply_through(self, rig):
        r = rig
        first = r.env.call(r.token, "auto_cull", self.args())
        r.tab.reply = lambda call: {"ok": False, "error": "tab_error", "message": "gone"}
        result = r.env.call(r.token, "auto_cull", self.args(dry_run=False, confirm=first["confirm"]))
        assert result["ok"], result
        assert len(self.applied(r)) == 1

    def test_an_apply_without_tab_id_reads_the_tab_the_preview_targeted(self, rig, fake_tab):
        r = rig
        first = r.env.call(r.token, "auto_cull", self.args(tab_id="tab-1"))
        assert first["shown_in_tab"]["tab_id"] == "tab-1"
        other = fake_tab(r.env, r.jwt, tab_id="tab-2", reply=lambda call: {
            "ok": True, "data": {"route": "/culling", "culling": {"plan_digest": "e" * 64}}})
        before = [c["tool"] for c in r.tab.calls].count("ui_get_context")
        result = r.env.call(r.token, "auto_cull", self.args(dry_run=False, confirm=first["confirm"]))
        assert result["ok"], result
        assert [c["tool"] for c in r.tab.calls].count("ui_get_context") == before + 1
        assert [c["tool"] for c in other.calls] == []
        assert len(self.applied(r)) == 1

    def test_an_apply_reads_the_tab_the_plan_was_shown_in_when_the_preview_named_none(self, rig, fake_tab):
        r = rig
        first = r.env.call(r.token, "auto_cull", self.args())
        assert first["shown_in_tab"]["tab_id"] == "tab-1"
        other = fake_tab(r.env, r.jwt, tab_id="tab-2", reply=lambda call: {
            "ok": True, "data": {"route": "/culling", "culling": {"plan_digest": "e" * 64}}})
        before = [c["tool"] for c in r.tab.calls].count("ui_get_context")
        result = r.env.call(r.token, "auto_cull", self.args(dry_run=False, confirm=first["confirm"]))
        assert result["ok"], result
        assert [c["tool"] for c in r.tab.calls].count("ui_get_context") == before + 1
        assert [c["tool"] for c in other.calls] == []
        assert len(self.applied(r)) == 1

    def test_an_unshown_preview_records_the_tabs_existing_pin(self, rig):
        r = rig
        r.state["pin"] = "a" * 64
        r.state["show"] = "unsaved_decisions"
        first = r.env.call(r.token, "auto_cull", self.args())
        assert first["shown_in_tab"] == {"applied": False, "reason": "unsaved_decisions"}
        result = r.env.call(r.token, "auto_cull", self.args(dry_run=False, confirm=first["confirm"]))
        assert result["ok"], result
        assert len(self.applied(r)) == 1

    def test_an_unshown_preview_is_refused_once_the_pin_moved(self, rig):
        r = rig
        r.state["pin"] = "a" * 64
        r.state["show"] = "unsaved_decisions"
        first = r.env.call(r.token, "auto_cull", self.args())
        r.state["pin"] = "b" * 64
        result = r.env.call(r.token, "auto_cull", self.args(dry_run=False, confirm=first["confirm"]))
        assert not result["ok"] and result["error"] == "confirmation_required"
        assert self.applied(r) == []


class TestAutoCullStateGuardThroughTheTool:
    """The tool binds the apply to the ORIGINAL preview and the route skips what the user touched."""

    @pytest.fixture()
    def rig(self, agent_app, photos, monkeypatch):
        from tests.conftest import intercept_internal_call
        nonce.reset()
        tools_culling.reset_preview_memory()
        state = {"upstream": []}
        env = agent_app("legacy")
        headers = env.login(edition=True)
        intercept_internal_call(monkeypatch, lambda tool, kw: state["upstream"].append((tool, kw)) and None)
        token = env.token(headers, "edition")
        yield type("Rig", (), {"env": env, "token": token, "state": state})
        for path in BURST_PATHS:
            _rate(path, star_rating=0, is_favorite=0, is_rejected=0)

    @staticmethod
    def args(**extra):
        return {"group_by": "burst", "strictness": 0, "show": False, **SCOPE, **extra}

    def apply(self, rig, preview, **extra):
        return rig.env.call(rig.token, "auto_cull", self.args(dry_run=False, confirm=preview["confirm"], **extra))

    def auto_calls(self, rig):
        return [kw["json"] for tool, kw in rig.state["upstream"] if tool == "culling.auto"]

    def test_a_rating_after_the_preview_is_skipped_and_listed(self, rig):
        preview = rig.env.call(rig.token, "auto_cull", self.args())
        assert {p for r in preview["data"]["rows"] for p in r["reject_paths"]} == {BURST_PATHS[2]}
        _rate(BURST_PATHS[2], star_rating=5)
        result = self.apply(rig, preview)
        assert result["ok"], result
        assert _rejected() == set()
        assert result["data"]["skipped_user_changed"] == [BURST_PATHS[2]]
        assert result["data"]["skipped_user_changed_count"] == 1

    def test_a_manual_reject_after_the_preview_is_listed(self, rig):
        preview = rig.env.call(rig.token, "auto_cull", self.args())
        _rate(BURST_PATHS[2], is_rejected=1)
        result = self.apply(rig, preview)
        assert result["ok"], result
        assert _rejected() == {BURST_PATHS[2]}
        assert result["data"]["skipped_user_changed"] == [BURST_PATHS[2]]

    def test_the_apply_does_not_re_run_a_dry_run_that_would_overwrite_the_snapshot(self, rig):
        preview = rig.env.call(rig.token, "auto_cull", self.args())
        _rate(BURST_PATHS[2], star_rating=5)
        self.apply(rig, preview)
        sent = self.auto_calls(rig)
        assert [c["dry_run"] for c in sent] == [True, False]
        assert sent[1]["expected_digest"] == preview["data"]["plan_digest"]

    def test_the_apply_sends_only_the_plan_request_and_its_guards(self, rig):
        from api.routers.burst_culling import AutoCullBody
        preview = rig.env.call(rig.token, "auto_cull", self.args())
        self.apply(rig, preview)
        for sent in self.auto_calls(rig):
            assert set(sent) <= set(AutoCullBody.model_fields)

    def test_without_memory_of_the_confirm_the_apply_keeps_todays_path(self, rig):
        preview = rig.env.call(rig.token, "auto_cull", self.args())
        tools_culling.reset_preview_memory()
        result = self.apply(rig, preview)
        assert result["ok"], result
        assert [c["dry_run"] for c in self.auto_calls(rig)] == [True, True, False]
        assert _rejected() == {BURST_PATHS[2]}

    def test_a_confirm_is_single_use(self, rig):
        preview = rig.env.call(rig.token, "auto_cull", self.args())
        assert self.apply(rig, preview)["ok"]
        assert self.apply(rig, preview)["error"] == "confirmation_required"
