"""Searches are shown in the user's tab: the pure mappers and the relay through a scripted tab.

[REAL] ``agent_app`` (real auth chain, real lifespan) and a ``FakeTab`` on the real bridge.
"""

import asyncio
import json

import pytest

from api import config as api_config
from api.agent import show
from api.agent.tools_read import HIDE_DEFAULT_KEYS
from api.agent.internal_client import ok
from tests.conftest import AGENT_DIR, intercept_internal_call, visual_ranking

ROWS = [{"path": AGENT_DIR + f"show/{i}.jpg", "filename": f"{i}.jpg", "aggregate": 5.0 + i,
         "aesthetic": 4.0 + i, "caption": "a red sunset" if i == 0 else "a street"} for i in range(3)]
PREFIX = AGENT_DIR + "show/"


@pytest.fixture()
def photos(seed_photos_prefix):
    return seed_photos_prefix(PREFIX, ROWS)


def stub_semantic_search(monkeypatch, hits, seen=None):
    """Answer ``semantic_search`` with ``hits`` (row index, similarity or None); every other call goes through."""
    def handler(tool, kwargs):
        if tool != "semantic_search":
            return None
        if seen is not None:
            seen.append(kwargs["query"])
        return ok({"photos": [{"path": ROWS[i]["path"], "filename": f"{i}.jpg",
                               **({} if sim is None else {"similarity": sim})} for i, sim in hits],
                   "total": len(hits), "query": "q"})
    intercept_internal_call(monkeypatch, handler)


def reply_total(total=7):
    return lambda call: {"ok": True, "data": {"applied": list(call["args"]["patch"]), "total": total}}


def sort_pair():
    return show.effective_sort(None, None)


def hide_patch():
    defaults = api_config.VIEWER_CONFIG["defaults"]
    return {key: True for key in HIDE_DEFAULT_KEYS if defaults.get(key)}


class TestMappers:
    def test_search_patch_is_the_filters_plus_the_effective_sort(self):
        patch, reason = show.search_patch({"camera": "Canon", "min_aesthetic": 7.0, "hide_bursts": True},
                                          "date_taken", "asc")
        assert reason is None
        assert patch == {"camera": "Canon", "min_aesthetic": 7.0, "hide_bursts": True,
                         "sort": "date_taken", "sort_direction": "asc"}

    def test_sort_falls_back_to_the_viewer_default(self, monkeypatch):
        monkeypatch.setitem(api_config.VIEWER_CONFIG, "defaults", {"sort": "aesthetic", "sort_direction": "ASC"})
        assert show.effective_sort(None, None) == {"sort": "aesthetic", "sort_direction": "asc"}

    def test_unsupported_keys_are_listed_not_partially_applied(self):
        patch, reason = show.search_patch({"camera": "Canon", "min_rating": 3, "junk_kind": "blurry"}, None, None)
        assert patch == {}
        assert reason == {"applied": False, "reason": "unsupported_filters", "keys": ["junk_kind", "min_rating"]}

    def test_show_rejected_false_is_the_normal_listing_not_unsupported(self):
        patch, reason = show.search_patch({"show_rejected": False, "camera": "Canon"}, None, None)
        assert reason is None and "show_rejected" not in patch
        patch, reason = show.search_patch({"show_rejected": True}, None, None)
        assert reason is None and patch["show_rejected"] is True

    @pytest.mark.parametrize("ignored", [
        {"is_silhouette": False}, {"exclude_tags": ""}, {"require_tags": "  "},
        {"min_rating": 0}, {"min_rating": 6}, {"min_rating": "x"}])
    def test_a_value_the_route_ignores_is_not_unsupported(self, ignored):
        patch, reason = show.search_patch({**ignored, "camera": "X"}, None, None)
        assert reason is None and patch["camera"] == "X" and not set(ignored) & set(patch)

    def test_type_together_with_category_is_an_invalid_combination(self):
        assert show.search_patch({"type": "portrait", "category": "macro"}, None, None)[1]["reason"] == "invalid_combination"

    @pytest.mark.parametrize("mode,floor", [("visual", 0.40), ("color", 0.40), ("person", 0.0)])
    def test_similar_patch_sends_the_floor_the_route_used(self, mode, floor):
        patch = show.similar_patch("/a.jpg", mode, None, "aggregate", "desc")
        assert patch["min_similarity"] == floor and patch["similarity_mode"] == mode
        assert show.similar_patch("/a.jpg", mode, 0.8)["min_similarity"] == 0.8


class TestSearchRelay:
    def test_the_tab_gets_one_replace_frame_with_the_exact_patch(self, agent_app, fake_tab, photos):
        env = agent_app("open")
        assert hide_patch(), "the shipped defaults hide sets; the hide toggles must reach the patch"
        tab = fake_tab(env, None, reply=reply_total(7))
        result = env.call(env.token(env.login()), "search_photos", {
            "filters": {"min_aesthetic": 4.0, "path_prefix": PREFIX}})
        assert result["ok"] is True and len(tab.calls) == 1
        assert tab.calls[0]["tool"] == "ui_set_gallery_filters"
        assert tab.calls[0]["args"] == {
            "patch": {"min_aesthetic": 4.0, "path_prefix": PREFIX, **hide_patch(), **sort_pair()},
            "replace": True}
        shown = result["shown_in_tab"]
        assert shown["applied"] is True and shown["tab_id"] == "tab-1" and shown["total"] == 7
        assert "min_aesthetic" in shown["keys"] and "filters" not in shown

    def test_rejected_search_reaches_the_tab_with_the_same_positive_filter(self, agent_app, fake_tab, seed_photos_prefix):
        seed_photos_prefix(PREFIX, [{**row, "is_rejected": int(i == 1)} for i, row in enumerate(ROWS)])
        env = agent_app("open")
        tab = fake_tab(env, None, reply=reply_total(1))
        result = env.call(env.token(env.login()), "search_photos", {
            "filters": {"path_prefix": PREFIX, "show_rejected": True}})
        assert result["ok"] is True
        assert [photo["path"] for photo in result["data"]["rows"]] == [ROWS[1]["path"]]
        assert result["shown_in_tab"]["applied"] is True
        assert len(tab.calls) == 1
        assert tab.calls[0]["tool"] == "ui_set_gallery_filters"
        assert tab.calls[0]["args"]["patch"]["show_rejected"] is True
        assert tab.calls[0]["args"]["replace"] is True

    def test_favorite_reject_intersection_is_not_broadened_in_the_tab(self, agent_app, fake_tab, seed_photos_prefix):
        seed_photos_prefix(PREFIX, [{**row, "is_rejected": int(i > 0), "is_favorite": int(i == 1)}
                                   for i, row in enumerate(ROWS)])
        env = agent_app("open")
        tab = fake_tab(env, None, reply=reply_total(1))
        result = env.call(env.token(env.login()), "search_photos", {"filters": {
            "path_prefix": PREFIX, "show_rejected": True, "favorites_only": True}})
        assert result["ok"] is True
        assert [row["path"] for row in result["data"]["rows"]] == [ROWS[1]["path"]]
        assert result["shown_in_tab"]["reason"] == "invalid_combination"
        assert tab.calls == []

    @pytest.mark.parametrize("route", ["/compare", "/photo-compare", "/photo-compare?layout=two"])
    def test_a_tab_on_the_comparison_page_is_left_alone(self, agent_app, fake_tab, photos, route):
        env = agent_app("open")
        tab = fake_tab(env, None, reply=reply_total(7), route=route)
        result = env.call(env.token(env.login()), "search_photos", {"filters": {"path_prefix": PREFIX}})
        assert result["ok"] is True and tab.calls == []
        assert result["shown_in_tab"]["applied"] is False
        assert result["shown_in_tab"]["reason"] == "comparison_open"

    def test_show_false_sends_nothing(self, agent_app, fake_tab, photos):
        env = agent_app("open")
        tab = fake_tab(env, None, reply=reply_total())
        token = env.token(env.login())
        args = {"filters": {"path_prefix": PREFIX}}
        assert "shown_in_tab" in env.call(token, "search_photos", args)
        assert len(tab.calls) == 1
        quiet = env.call(token, "search_photos", {**args, "show": False})
        assert quiet["ok"] is True and "shown_in_tab" not in quiet
        assert len(tab.calls) == 1

    def test_a_later_page_is_not_reapplied(self, agent_app, fake_tab, photos):
        env = agent_app("open")
        tab = fake_tab(env, None, reply=reply_total())
        result = env.call(env.token(env.login()), "search_photos", {
            "filters": {"path_prefix": PREFIX}, "per_page": 1, "page": 2})
        assert result["ok"] is True
        assert result["shown_in_tab"] == {"applied": False, "reason": "page_not_first"}
        assert tab.calls == []

    def test_an_empty_result_keeps_the_users_view(self, agent_app, fake_tab, photos):
        env = agent_app("open")
        tab = fake_tab(env, None, reply=reply_total())
        result = env.call(env.token(env.login()), "search_photos", {"filters": {"path_prefix": "/nowhere/"}})
        assert result["ok"] is True and result["shown_in_tab"]["reason"] == "empty_result"
        assert tab.calls == []

    def test_unsupported_filters_skip_the_whole_show(self, agent_app, fake_tab, photos):
        env = agent_app("open")
        tab = fake_tab(env, None, reply=reply_total())
        result = env.call(env.token(env.login()), "search_photos", {
            "filters": {"path_prefix": PREFIX, "exclude_tags": "zzz"}})
        assert result["ok"] is True
        assert result["shown_in_tab"] == {"applied": False, "reason": "unsupported_filters", "keys": ["exclude_tags"]}
        assert tab.calls == []

    def test_no_tab_never_fails_the_search(self, agent_app, photos):
        env = agent_app("open")
        result = env.call(env.token(env.login()), "search_photos", {"filters": {"path_prefix": PREFIX}})
        assert result["ok"] is True and len(result["data"]["rows"]) == 3
        assert result["shown_in_tab"]["applied"] is False and result["shown_in_tab"]["reason"] == "no_tab"

    def test_bridge_off_reports_it(self, agent_app, photos):
        env = agent_app("open", bridge=False)
        result = env.call(env.token(env.login()), "search_photos", {"filters": {"path_prefix": PREFIX}})
        assert result["ok"] is True and result["shown_in_tab"]["reason"] == "bridge_disabled"

    def test_an_outdated_tab_is_reported(self, agent_app, fake_tab, photos):
        env = agent_app("open")
        fake_tab(env, None, version="old")
        result = env.call(env.token(env.login()), "search_photos", {"filters": {"path_prefix": PREFIX}})
        assert result["ok"] is True and result["shown_in_tab"]["reason"] == "tab_outdated"

    def test_a_tab_refusal_is_reported_faithfully(self, agent_app, fake_tab, photos):
        env = agent_app("open")
        fake_tab(env, None, reply=lambda call: {"ok": False, "error": "forbidden_level", "message": "no"})
        result = env.call(env.token(env.login()), "search_photos", {"filters": {"path_prefix": PREFIX}})
        assert result["ok"] is True and result["shown_in_tab"] == {"applied": False, "reason": "forbidden"}

    @pytest.mark.parametrize("code", ["unsaved_decisions", "navigation_refused", "modal_open"])
    def test_a_navigation_refusal_keeps_its_own_reason(self, agent_app, fake_tab, photos, code):
        env = agent_app("open")
        fake_tab(env, None, reply=lambda call: {"ok": False, "error": code, "message": "no"})
        result = env.call(env.token(env.login()), "search_photos", {"filters": {"path_prefix": PREFIX}})
        assert result["ok"] is True and result["shown_in_tab"] == {"applied": False, "reason": code}

    def test_a_silent_tab_times_out_but_the_search_stands(self, agent_app, fake_tab, photos):
        env = agent_app("open", call_timeout_s=1)
        fake_tab(env, None, reply=lambda call: None)
        result = env.call(env.token(env.login()), "search_photos", {"filters": {"path_prefix": PREFIX}})
        assert result["ok"] is True
        assert result["shown_in_tab"]["reason"] == "tab_timeout" and "may still apply" in result["shown_in_tab"]["note"]

    def test_tab_id_routes_to_that_tab(self, agent_app, fake_tab, photos):
        env = agent_app("open")
        first = fake_tab(env, None, "tab-a", reply=reply_total())
        second = fake_tab(env, None, "tab-b", reply=reply_total())
        result = env.call(env.token(env.login()), "search_photos", {
            "filters": {"path_prefix": PREFIX}, "tab_id": "tab-a"})
        assert result["shown_in_tab"]["tab_id"] == "tab-a"
        assert len(first.calls) == 1 and second.calls == []

    def test_a_bad_tab_id_is_invalid_input(self, agent_app, photos):
        env = agent_app("open")
        result = env.call(env.token(env.login()), "search_photos", {"tab_id": "bad id!"})
        assert result["ok"] is False and result["error"] == "invalid_input"


class TestSemanticAndSimilarRelay:
    def test_semantic_search_pins_exactly_the_returned_rows(self, agent_app, fake_tab, photos, monkeypatch):
        stub_semantic_search(monkeypatch, [(0, None)])
        env = agent_app("open")
        tab = fake_tab(env, None, reply=lambda call: {"ok": True, "data": {"total": 1}})
        result = env.call(env.token(env.login()), "semantic_search", {"query": "red sunset", "threshold": 0.2})
        assert result["ok"] is True and result["shown_in_tab"]["applied"] is True
        assert result["shown_in_tab"]["mode"] == "paths"
        assert [(c["tool"], c["args"]) for c in tab.calls] == [("ui_show_photos", {"paths": [ROWS[0]["path"]]})]

    def test_text_scope_is_pinned_like_any_other_semantic_search(self, agent_app, fake_tab, photos, monkeypatch):
        stub_semantic_search(monkeypatch, [(1, None)])
        env = agent_app("open")
        tab = fake_tab(env, None, reply=lambda call: {"ok": True, "data": {"total": 1}})
        result = env.call(env.token(env.login()), "semantic_search", {"query": "sunset", "scope": "text"})
        assert result["ok"] is True and result["shown_in_tab"]["mode"] == "paths"
        assert [c["tool"] for c in tab.calls] == ["ui_show_photos"]

    def test_similar_photos_shows_with_the_floor_the_route_used(self, agent_app, fake_tab, photos, monkeypatch):
        from api.routers import gallery
        seen = []

        def find(conn, source, path, min_similarity, *rest):
            seen.append(min_similarity)
            return [{"path": ROWS[1]["path"], "filename": "1.jpg", "similarity": 0.9}], 1, None

        monkeypatch.setattr(gallery, "_find_similar_visual", find)
        env = agent_app("open")
        tab = fake_tab(env, None, reply=reply_total(1))
        token = env.token(env.login())
        result = env.call(token, "similar_photos", {"path": ROWS[0]["path"]})
        assert result["ok"] is True and result["shown_in_tab"]["applied"] is True
        assert seen == [0.4]
        assert tab.calls[0]["args"] == {"patch": {
            "similar_to": ROWS[0]["path"], "similarity_mode": "visual", "min_similarity": 0.4,
            "semantic_query": None, "semantic_threshold": None, **sort_pair()}, "replace": True}
        env.call(token, "similar_photos", {"path": ROWS[0]["path"], "min_similarity": 0.8})
        assert seen == [0.4, 0.8] and tab.calls[1]["args"]["patch"]["min_similarity"] == 0.8

    def test_similar_photos_rows_carry_the_default_keys(self, agent_app, photos, seed_photos_prefix, monkeypatch):
        from api.routers import gallery
        seed_photos_prefix(AGENT_DIR + "simkeys/", [{
            "path": AGENT_DIR + "simkeys/h.jpg", "filename": "h.jpg", "camera_model": "X100", "iso": 200}])
        monkeypatch.setattr(gallery, "_find_similar_visual", visual_ranking(
            [{"path": AGENT_DIR + "simkeys/h.jpg", "filename": "h.jpg", "similarity": 0.9}]))
        env = agent_app("open")
        row = env.call(env.token(env.login()), "similar_photos", {
            "path": ROWS[0]["path"], "show": False})["data"]["rows"][0]
        assert row["camera_model"] == "X100" and row["iso"] == 200 and row["similarity"] == 0.9

    def test_a_later_similar_page_is_not_reapplied(self, agent_app, fake_tab, photos, monkeypatch):
        from api.routers import gallery
        monkeypatch.setattr(gallery, "_find_similar_visual", visual_ranking(
            [{"path": ROWS[1]["path"], "filename": "1.jpg", "similarity": 0.9},
             {"path": ROWS[2]["path"], "filename": "2.jpg", "similarity": 0.8}]))
        env = agent_app("open")
        tab = fake_tab(env, None, reply=reply_total())
        result = env.call(env.token(env.login()), "similar_photos", {
            "path": ROWS[0]["path"], "limit": 1, "offset": 1})
        assert result["shown_in_tab"]["reason"] == "page_not_first" and tab.calls == []


class TestSemanticTimeout:
    def test_the_semantic_show_waits_on_semantic_timeout_not_call_timeout(self, agent_app, fake_tab, photos, monkeypatch):
        import time

        stub_semantic_search(monkeypatch, [(0, None)])
        env = agent_app("open", call_timeout_s=1, semantic_timeout_s=10)

        def slow(call):
            time.sleep(1.6)
            return {"ok": True, "data": {"applied": [], "total": 1}}

        fake_tab(env, None, reply=slow)
        result = env.call(env.token(env.login()), "semantic_search", {"query": "sunset"})
        assert result["ok"] is True and result["shown_in_tab"]["applied"] is True


class TestSemanticFilters:
    """semantic_search(filters): narrow the best matches through by_paths, keep similarity order."""

    HITS = [(2, 0.9), (0, 0.8), (1, 0.7)]

    def test_filtered_rows_keep_similarity_order_and_scores(self, agent_app, fake_tab, photos, monkeypatch):
        seen = []
        stub_semantic_search(monkeypatch, self.HITS, seen)
        env = agent_app("open")
        fake_tab(env, None, reply=lambda call: {"ok": True, "data": {"shown": 2, "missing": [], "total": 2}})
        result = env.call(env.token(env.login()), "semantic_search",
                          {"query": "q", "limit": 5, "filters": {"min_aggregate": 5.5}})
        assert result["ok"] is True, result
        # 0.jpg (aggregate 5.0) is filtered out; by_paths order is the search order, not 1,2.
        assert [(r["filename"], r["similarity"]) for r in result["data"]["rows"]] == [("2.jpg", 0.9), ("1.jpg", 0.7)]
        assert result["data"]["candidates"] == 3 and result["data"]["filtered_out"] == 1
        assert "note" not in result["data"]
        assert seen[0]["limit"] == 200

    def test_filtered_show_is_one_ui_show_photos_frame_with_the_final_paths(self, agent_app, fake_tab, photos, monkeypatch):
        stub_semantic_search(monkeypatch, self.HITS)
        env = agent_app("open")
        tab = fake_tab(env, None, reply=lambda call: {"ok": True, "data": {"shown": 2, "missing": [], "total": 2}})
        result = env.call(env.token(env.login()), "semantic_search",
                          {"query": "q", "filters": {"min_aggregate": 5.5}})
        assert [(c["tool"], c["args"]) for c in tab.calls] == [
            ("ui_show_photos", {"paths": [ROWS[2]["path"], ROWS[1]["path"]]})]
        assert result["shown_in_tab"]["applied"] is True and result["shown_in_tab"]["mode"] == "paths"

    def test_show_false_and_empty_results_send_no_frame(self, agent_app, fake_tab, photos, monkeypatch):
        stub_semantic_search(monkeypatch, self.HITS)
        env = agent_app("open")
        tab = fake_tab(env, None, reply=lambda call: {"ok": True, "data": {}})
        token = env.token(env.login())
        env.call(token, "semantic_search", {"query": "q", "show": False, "filters": {"min_aggregate": 5.5}})
        empty = env.call(token, "semantic_search", {"query": "q", "filters": {"min_aggregate": 99}})
        assert tab.calls == []
        assert empty["data"]["rows"] == [] and empty["shown_in_tab"]["reason"] == "empty_result"

    def test_unfiltered_search_pins_the_rows_in_similarity_order_and_keeps_scores(self, agent_app, fake_tab, photos, monkeypatch):
        stub_semantic_search(monkeypatch, self.HITS)
        env = agent_app("open")
        tab = fake_tab(env, None, reply=lambda call: {"ok": True, "data": {"total": 3}})
        result = env.call(env.token(env.login()), "semantic_search", {"query": "q"})
        assert [(c["tool"], c["args"]) for c in tab.calls] == [
            ("ui_show_photos", {"paths": [ROWS[i]["path"] for i in (2, 0, 1)]})]
        assert result["shown_in_tab"]["mode"] == "paths"
        assert [r["similarity"] for r in result["data"]["rows"]] == [0.9, 0.8, 0.7]
        assert "candidates" not in result["data"]

    def test_a_saturated_candidate_list_adds_a_note(self, agent_app, fake_tab, photos, monkeypatch):
        from api.agent import tools_read
        monkeypatch.setattr(tools_read, "SEMANTIC_CANDIDATES", 3)
        stub_semantic_search(monkeypatch, self.HITS)
        env = agent_app("open")
        fake_tab(env, None, reply=lambda call: {"ok": True, "data": {}})
        result = env.call(env.token(env.login()), "semantic_search",
                          {"query": "q", "limit": 10, "show": False, "filters": {"min_aggregate": 5.5}})
        assert "note" in result["data"]


def test_show_paths_in_tab_forwards_only_the_paths(monkeypatch):
    sent = {}

    async def fake_call_tab(registry, resolved, settings, tool, args, tab_id, *, timeout):
        sent.update(tool=tool, args=args)
        return {"ok": True, "data": {"total": 2}, "tab": {"tab_id": "t"}}

    monkeypatch.setattr(show, "call_tab", fake_call_tab)
    monkeypatch.setattr(show, "comparison_open", lambda *a: False)
    result = asyncio.run(show.show_paths_in_tab(None, None, {"bridge": True}, None, ["a", "b"], timeout=1.0))
    assert result["applied"] is True
    assert sent["tool"] == "ui_show_photos"
    assert sent["args"] == {"paths": ["a", "b"]}


def test_the_agent_tool_refuses_the_removed_review_fields_as_invalid_input(agent_app, fake_tab):
    env = agent_app("open")
    tab = fake_tab(env, None, reply=lambda call: {"ok": True, "data": {"total": 2}})
    refused = env.call(env.token(env.login()), "ui_show_photos", {
        "paths": ["/a.jpg", "/b.jpg"], "reasons": [{"key": "best"}, {"key": "soft"}]})
    assert refused["ok"] is False and refused["error"] == "invalid_input" and not tab.calls


def _context(activity=None):
    body = {"route": "/", "query_path": None, "selection": {"scope": "paths", "count": 0},
            "gallery": {"total": 200, "loaded": 200, "has_more": False, "pinned": True},
            "mounted_actions": [], "level": "readonly", "actions": []}
    if activity is not None:
        body["user_activity"] = activity
    return body


def _activity(items, path_len=100, paths=3):
    return {"items": [{"seq": i, "kind": "rating", "paths": ["/p" + "x" * path_len + str(j) for j in range(paths)],
                       "truncated": False, "value": 5, "at": 1} for i in range(1, items + 1)],
            "until": items, "truncated": False}


class TestUserActivityInTheContext:
    def test_a_small_activity_is_left_whole(self, agent_app, fake_tab):
        env = agent_app("open")
        activity = _activity(3)
        fake_tab(env, None, reply=lambda call: {"ok": True, "data": _context(activity)})
        data = env.call(env.token(env.login()), "ui_get_context")["data"]
        assert data["user_activity"] == activity

    @pytest.mark.parametrize("decision", ["kept", "undecided"])
    def test_manual_review_activity_survives_the_agent_context(self, agent_app, fake_tab, decision):
        env = agent_app("open")
        activity = {"items": [{"seq": 1, "kind": "review", "paths": ["/a.jpg"],
                               "truncated": False, "value": decision, "at": 1}],
                    "until": 1, "truncated": False}
        fake_tab(env, None, reply=lambda call: {"ok": True, "data": _context(activity)})
        data = env.call(env.token(env.login()), "ui_get_context")["data"]
        assert data["user_activity"] == activity

    def test_an_oversized_activity_is_trimmed_to_fit_and_flagged(self, agent_app, fake_tab):
        env = agent_app("open")
        fake_tab(env, None, reply=lambda call: {"ok": True, "data": _context(_activity(50, 90, 20))})
        result = env.call(env.token(env.login()), "ui_get_context")
        assert result["ok"], result
        assert len(json.dumps(result, separators=(",", ":"))) <= 60000
        got = result["data"]
        assert got["user_activity"]["truncated"] is True and 0 < len(got["user_activity"]["items"]) < 50
        assert got["user_activity"]["until"] == 50 and got["route"] == "/"

    def test_activity_is_capped_at_fifty_items_of_twenty_paths(self):
        from api.agent.tools_ui import fit_culling
        result = {"ok": True, "data": _context(_activity(60, 5, 30))}
        fit_culling(result, 10 ** 7)
        activity = result["data"]["user_activity"]
        assert len(activity["items"]) == 50 and activity["truncated"] is True
        assert activity["items"][0]["seq"] == 11 and activity["items"][-1]["seq"] == 60
        assert all(len(i["paths"]) == 20 and i["truncated"] is True for i in activity["items"])

    def test_the_activity_argument_reaches_the_tab_and_a_bare_call_sends_none(self, agent_app, fake_tab):
        env = agent_app("open")
        tab = fake_tab(env, None, reply=lambda call: {"ok": True, "data": _context()})
        token = env.token(env.login())
        env.call(token, "ui_get_context")
        env.call(token, "ui_get_context", {"activity_since": 12})
        assert [c["args"] for c in tab.calls] == [{}, {"activity_since": 12}]


def stub_lists(monkeypatch, persons=1, albums=1, junk=1):
    """Answer the three list routes with that many rows; every other call goes through."""
    bodies = {
        "list_persons": {"persons": [{"id": i + 1, "name": f"P{i}", "face_count": 3} for i in range(persons)],
                         "total": persons},
        "list_albums": {"albums": [{"id": i + 1, "name": f"A{i}", "description": None, "is_smart": 0,
                                    "photo_count": 2} for i in range(albums)], "total": albums},
        "search_photos": {"photos": [{"path": ROWS[i]["path"], "filename": f"{i}.jpg"} for i in range(junk)],
                          "total": junk, "page": 1, "per_page": 50},
    }
    intercept_internal_call(monkeypatch, lambda tool, kwargs: ok(bodies[tool]) if tool in bodies else None)


def navigate_reply(call):
    return {"ok": True, "data": {"route": call["args"]["route"]}}


class TestListShow:
    @pytest.mark.parametrize("tool, args, route, query", [
        ("list_persons", {"query": "anna"}, "/persons", {"search": "anna"}),
        ("list_albums", {"query": "trip"}, "/albums", {"search": "trip"}),
        ("junk_list", {"kind": "blurry"}, "/junk", {"kind": "blurry"}),
    ])
    def test_show_true_sends_exactly_one_navigate_frame(self, agent_app, fake_tab, monkeypatch, tool, args, route, query):
        stub_lists(monkeypatch)
        env = agent_app("open")
        tab = fake_tab(env, None, reply=navigate_reply)
        result = env.call(env.token(env.login()), tool, {**args, "show": True})
        assert result["ok"] is True and len(result["data"]["rows"]) == 1
        assert [c["tool"] for c in tab.calls] == ["ui_navigate"]
        assert tab.calls[0]["args"] == {"route": route, "query": query}
        shown = result["shown_in_tab"]
        assert shown["applied"] is True and shown["tab_id"] == "tab-1" and shown["route"] == route
        assert shown["mode"] == "route"

    @pytest.mark.parametrize("tool, route, query", [
        ("list_persons", "/persons", {"search": ""}), ("list_albums", "/albums", {"search": ""}),
        ("junk_list", "/junk", {"kind": "any"})])
    def test_an_empty_query_is_sent_so_the_page_clears(self, agent_app, fake_tab, monkeypatch, tool, route, query):
        stub_lists(monkeypatch)
        env = agent_app("open")
        tab = fake_tab(env, None, reply=navigate_reply)
        env.call(env.token(env.login()), tool, {"show": True})
        assert tab.calls[0]["args"] == {"route": route, "query": query}

    @pytest.mark.parametrize("tool", ["list_persons", "list_albums", "junk_list"])
    def test_the_default_sends_nothing(self, agent_app, fake_tab, monkeypatch, tool):
        stub_lists(monkeypatch)
        env = agent_app("open")
        tab = fake_tab(env, None, reply=navigate_reply)
        result = env.call(env.token(env.login()), tool, {})
        assert result["ok"] is True and "shown_in_tab" not in result and tab.calls == []

    @pytest.mark.parametrize("tool", ["list_persons", "list_albums", "junk_list"])
    def test_an_empty_list_is_not_shown(self, agent_app, fake_tab, monkeypatch, tool):
        stub_lists(monkeypatch, persons=0, albums=0, junk=0)
        env = agent_app("open")
        tab = fake_tab(env, None, reply=navigate_reply)
        result = env.call(env.token(env.login()), tool, {"show": True})
        assert result["shown_in_tab"] == {"applied": False, "reason": "empty_result"} and tab.calls == []

    def test_a_later_junk_page_is_not_shown(self, agent_app, fake_tab, monkeypatch):
        stub_lists(monkeypatch)
        env = agent_app("open")
        tab = fake_tab(env, None, reply=navigate_reply)
        result = env.call(env.token(env.login()), "junk_list", {"show": True, "page": 2})
        assert result["ok"] is True
        assert result["shown_in_tab"] == {"applied": False, "reason": "page_not_first"} and tab.calls == []

    @pytest.mark.parametrize("route", ["/compare", "/photo-compare", "/photo-compare?layout=two"])
    def test_a_tab_on_the_comparison_page_is_left_alone(self, agent_app, fake_tab, monkeypatch, route):
        stub_lists(monkeypatch)
        env = agent_app("open")
        tab = fake_tab(env, None, reply=navigate_reply, route=route)
        result = env.call(env.token(env.login()), "list_persons", {"show": True})
        assert result["shown_in_tab"]["reason"] == "comparison_open" and tab.calls == []

    @pytest.mark.parametrize("code", ["modal_open", "unsaved_decisions", "navigation_refused"])
    def test_a_navigation_refusal_keeps_its_own_reason(self, agent_app, fake_tab, monkeypatch, code):
        stub_lists(monkeypatch)
        env = agent_app("open")
        fake_tab(env, None, reply=lambda call: {"ok": False, "error": code, "message": "no"})
        result = env.call(env.token(env.login()), "list_albums", {"show": True})
        assert result["ok"] is True and result["shown_in_tab"] == {"applied": False, "reason": code}

    def test_a_forbidden_tab_is_reported_as_forbidden(self, agent_app, fake_tab, monkeypatch):
        stub_lists(monkeypatch)
        env = agent_app("open")
        fake_tab(env, None, reply=lambda call: {"ok": False, "error": "forbidden_level", "message": "no"})
        result = env.call(env.token(env.login()), "junk_list", {"show": True})
        assert result["shown_in_tab"] == {"applied": False, "reason": "forbidden"}

    def test_no_tab_never_fails_the_list(self, agent_app, monkeypatch):
        stub_lists(monkeypatch)
        env = agent_app("open")
        result = env.call(env.token(env.login()), "list_persons", {"show": True})
        assert result["ok"] is True and result["shown_in_tab"]["reason"] == "no_tab"
