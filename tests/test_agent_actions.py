"""The ONE jobs table: tied to the registered tools, their levels, the tab's state and the docs.

[REAL] ``agent_app`` (real auth chain and lifespan) and a ``FakeTab`` on the real bridge. The
drift tests in :class:`TestDrift` must stay green at every step that adds a tool: a new tool
needs an ``ACTIONS`` row and an entry in :data:`TOOL_ROUTES`.
"""

import json
import re
from pathlib import Path

import pytest

from api.agent import actions, tokens
from api.agent.actions import ACTIONS, FACTS, TOOL_STATE_NEEDS, evaluate, facts_for, render_client_actions
from api.agent.internal_client import ROUTE_ALLOWLIST
from api.agent.tools_common import TOOL_LEVELS
from api.agent.tools_culling import CULLING_ROUTES
from api.agent.tools_write import WRITE_TOOL_LEVELS
from api.agent.ui_tools import UI_TOOLS, render_client_json
from tests import test_agent_write

# Reads client, i18n or docs files: runs on every pull request (see ci.yml).
pytestmark = pytest.mark.cross_file

DOCS = Path(__file__).resolve().parent.parent / "docs"
ROUTES = {**ROUTE_ALLOWLIST, **CULLING_ROUTES}
LEVELS = ("readonly", "user", "edition")

# Literal in the TEST on purpose: the level of a tool is the max floor of the routes it calls,
# computed here independently of ``WRITE_TOOL_LEVELS`` so a hand-edited level cannot drift.
TOOL_ROUTES = {
    "get_photo_stack": ["get_photo_stack"], "create_photo_stack": ["create_photo_stack"],
    "update_photo_stack": ["update_photo_stack"], "unstack_photos": ["unstack_photos"],
    "undo_photo_stack": ["undo_photo_stack"], "import_ai_edit": ["import_ai_edit"],
    "search_photos": ["search_photos"], "semantic_search": ["semantic_search", "photos_by_paths"],
    "get_photo": ["get_photo", "photo_objects"], "possible_faces": ["possible_faces"], "assign_faces": ["assign_faces"],
    "set_caption": ["get_photo", "set_caption"], "export_metadata": ["export_metadata"], "get_thumbnail": ["thumbnail"], "contact_sheet": ["thumbnail"], "similar_photos": ["similar_photos"],
    "filter_options": ["filter_options.cameras"], "list_persons": ["list_persons"],
    "list_albums": ["list_albums"], "library_stats": ["library_stats.overview"],
    "status": [], "available_actions": [],
    "set_rating": ["get_photo", "set_rating"], "set_favorite": ["get_photo", "toggle_favorite"],
    "set_rejected": ["get_photo", "toggle_rejected"],
    "batch_set_rating": ["photos_count", "batch_rating"], "batch_set_favorite": ["photos_count", "batch_favorite"],
    "batch_set_rejected": ["photos_count", "batch_reject"],
    "create_album": ["create_album", "photos_count", "album_add_photos", "photos_paths"], "album_add_photos": ["album_add_photos", "photos_paths"],
    "album_remove_photos": ["album_remove_photos", "photos_paths"],
    "add_tags": ["photos_count", "batch_manual_tags"], "remove_tags": ["photos_count", "batch_manual_tags"],
    "junk_list": ["search_photos"], "junk_reject": ["batch_reject"], "junk_clear": ["clear_junk"],
    "cull_apply": ["cull_apply", "cull_apply.preview"],
    "delete_photos": ["delete_photos", "delete_photos.preview", "photos_paths"],
    "list_culling_groups": ["culling.groups"], "culling_profiles": ["culling.profiles"],
    "suggest_culling_profile": ["culling.suggest_profile"], "keeper_hints": ["culling.keeper_hints"],
    "auto_cull": ["culling.auto"], "confirm_culling_groups": ["culling.confirm"],
    "override_sequence": ["photos_by_paths", "override_sequence"],
    "clear_sequence_override": ["photos_by_paths", "clear_sequence_override"],
    "override_category": ["get_photo", "override_category"],
    "clear_category_override": ["get_photo", "clear_category_override"],
    "group_compare": ["photos_by_paths", "group_faces", "group_subjects"],
    "cull_report": ["photos_count", "search_photos"],
    "comparison_status": ["comparison_stats", "comparison_coverage"],
    "explain_score": ["critique"], "category_weights": ["category_weights"],
    "preview_weights": ["category_weights", "search_photos", "preview_score"],
    "apply_weights": ["category_weights", "weight_snapshots", "update_weights"],
    "list_weight_snapshots": ["weight_snapshots"],
    "restore_weight_snapshot": ["weight_snapshots", "category_weights", "restore_weights"],
    "recompute_scores": ["recompute_start"], "recompute_status": ["recompute_status"],
    "learned_weights": ["learned_weights", "weight_confidence"],
    "misassigned_categories": ["category_weights", "search_photos", "critique"],
    "override_categories": ["photos_by_paths", "override_category"],
    "start_scan": ["scan_directories", "scan_start"], "scan_status": ["scan_status", "scan_directories"],
    **{tool.name: [] for tool in UI_TOOLS},
}
CULLING_TOOLS = {"list_culling_groups", "culling_profiles", "suggest_culling_profile", "keeper_hints",
                 "auto_cull", "confirm_culling_groups"}
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
                "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
                "fifteen": 15, "sixteen": 16}


def context_reply(route="/", selection=0, scope="paths", pinned=False, gallery=True):
    """A scripted ``ui_get_context`` answer for the tab."""
    body = {"route": route, "selection": {"scope": scope, "count": selection},
            "gallery": {"total": 5, "loaded": 5, "has_more": False, "pinned": pinned} if gallery else None,
            "mounted_actions": [], "level": "edition", "actions": []}
    return lambda call: {"ok": True, "data": body}


def jwt_of(headers):
    return headers["Authorization"].split(" ", 1)[1]


def listed(env, token, **args):
    result = env.call(token, "available_actions", args)
    assert result["ok"] is True, result
    return result["data"]


def tool_rows(data):
    return {row["id"]: {t["name"]: t for t in row["tools"]} for row in data["actions"]}


class TestDrift:
    def test_actions_and_registered_tools_name_the_same_set(self, agent_app):
        agent_app("open")
        registered = set(TOOL_LEVELS)
        in_actions = {name for action in ACTIONS for name in action.tools}
        assert in_actions == registered
        assert set(TOOL_LEVELS) == registered

    def test_tool_routes_cover_every_registered_tool(self, agent_app):
        agent_app("open")
        assert set(TOOL_ROUTES) == set(TOOL_LEVELS)

    def test_levels_match_route_gate(self, agent_app):
        agent_app("open")
        for tool, routes in TOOL_ROUTES.items():
            expected = max((ROUTES[r].min_level for r in routes), default="readonly", key=LEVELS.index)
            assert TOOL_LEVELS[tool] == expected, tool

    def test_write_levels_table_is_what_registration_recorded(self, agent_app):
        agent_app("open")
        for tool, level in WRITE_TOOL_LEVELS.items():
            assert TOOL_LEVELS[tool] == level

    def test_every_action_names_known_facts_and_unique_tools(self):
        assert len({a.id for a in ACTIONS}) == len(ACTIONS)
        for action in ACTIONS:
            assert action.when and action.when <= FACTS, action.id
            assert len(set(action.tools)) == len(action.tools), action.id
        assert set(TOOL_STATE_NEEDS.values()) <= FACTS

    def test_client_json_carries_the_same_table(self):
        rows = json.loads(render_client_json())["actions"]
        assert [r["id"] for r in rows] == [a.id for a in ACTIONS]
        levels = actions.tool_levels()
        for row, action in zip(rows, ACTIONS):
            assert row["when"] == sorted(action.when)
            assert row["tools"] == [{"name": n, "required_level": levels[n]} for n in action.tools]
        assert rows == render_client_actions()

    def test_docs_tool_counts_follow_the_registered_tools(self, agent_app):
        agent_app("open")
        registered = set(TOOL_LEVELS)
        ui = {t.name for t in UI_TOOLS}
        reads = registered - ui - set(WRITE_TOOL_LEVELS) - CULLING_TOOLS
        text = (DOCS / "AGENTS.md").read_text(encoding="utf-8")
        intro = re.search(r"exposes (\w+) read tools .*? and (\w+) `ui_\*` tools", text)
        assert intro, "the intro sentence of docs/AGENTS.md changed shape"
        assert (NUMBER_WORDS[intro.group(1)], NUMBER_WORDS[intro.group(2)]) == (len(reads), len(ui))
        data_tools = re.search(r"The (\w+) data tools are read-only", text)
        assert data_tools and NUMBER_WORDS[data_tools.group(1)] == len(reads)
        ui_tools = re.search(r"always lists (\w+) `ui_\*` tools", text)
        assert ui_tools and NUMBER_WORDS[ui_tools.group(1)] == len(ui)


class TestEvaluator:
    def test_facts_from_the_route_selection_and_pin(self):
        assert facts_for("/", 0, False) == {"any", "gallery"}
        assert facts_for("/album/3", 2, True) == {"any", "gallery", "albums", "selection", "pinned"}
        assert facts_for("/photo?path=a.jpg", 0, False) == {"any", "detail"}
        assert facts_for("/culling", 0, False) == {"any", "culling"}
        assert facts_for("/persons", 0, False) == {"any", "persons"}
        assert facts_for("/stats", 0, False) == {"any"}

    def test_no_tab_lists_only_the_page_independent_jobs(self):
        rows, hidden = evaluate("edition", frozenset({"any"}), TOOL_LEVELS_FULL())
        assert rows and all("any" in a.when for a in ACTIONS if a.id in {r["id"] for r in rows})
        assert hidden == sum(1 for a in ACTIONS if "any" not in a.when)

    def test_a_job_with_only_tools_above_the_level_is_omitted_not_hidden(self):
        rows, hidden = evaluate("readonly", facts_for("/", 0, False), TOOL_LEVELS_FULL())
        assert "cull_or_delete" not in {r["id"] for r in rows}
        assert hidden == sum(1 for a in ACTIONS if "any" not in a.when and "gallery" not in a.when)


def TOOL_LEVELS_FULL():
    return actions.tool_levels()


class TestAvailableActions:
    def test_without_a_tab_only_the_any_jobs(self, agent_app):
        env = agent_app("open")
        data = listed(env, env.token(env.login()))
        assert data["tab"] is None and data["level"] == "readonly"
        ids = {r["id"] for r in data["actions"]}
        assert ids and ids <= {a.id for a in ACTIONS if "any" in a.when}
        assert data["hidden"] == sum(1 for a in ACTIONS if "any" not in a.when)

    def test_bridge_off_is_the_same_as_no_tab(self, agent_app):
        env = agent_app("open", bridge=False)
        assert listed(env, env.token(env.login()))["tab"] is None

    def test_culling_context_lists_the_confirm_tools_and_not_the_selection_jobs(self, agent_app, fake_tab):
        env = agent_app("legacy")
        fake_tab(env, jwt_of(env.login(edition=True)), route="/culling", reply=context_reply("/culling", gallery=False))
        data = listed(env, env.token(env.login(edition=True), "edition"))
        rows = tool_rows(data)
        assert data["tab"]["route"] == "/culling"
        assert "confirm_culling_groups" in rows["work_darkroom"]
        assert "ui_show_culling_plan" in rows["work_darkroom"]
        assert "edit_many" not in rows and "batch_set_rating" not in {n for r in rows.values() for n in r}

    def test_a_selection_in_the_gallery_lists_the_editing_jobs(self, agent_app, fake_tab):
        env = agent_app("legacy")
        fake_tab(env, jwt_of(env.login(edition=True)), reply=context_reply("/", selection=3))
        data = listed(env, env.token(env.login(edition=True), "edition"))
        assert data["tab"]["selection_count"] == 3
        assert {"batch_set_rating", "add_tags"} <= set(tool_rows(data)["edit_many"])

    def test_mixed_state_reports_allowed_per_tool_in_the_same_job(self, agent_app, fake_tab):
        env = agent_app("legacy")
        fake_tab(env, jwt_of(env.login(edition=True)), reply=context_reply("/", selection=0))
        data = listed(env, env.token(env.login(edition=True), "edition"))
        row = tool_rows(data)["select_photos"]
        assert row["ui_select_photos"]["allowed"] is True
        assert row["ui_clear_selection"]["allowed"] is False
        job = next(r for r in data["actions"] if r["id"] == "select_photos")
        assert "select photos" in job["hint"]

    def test_a_readonly_key_does_not_see_the_tools_above_it(self, agent_app, fake_tab):
        env = agent_app("legacy")
        viewer, editor = env.login(), env.login(edition=True)
        fake_tab(env, jwt_of(viewer), "viewer-tab", reply=context_reply("/", selection=2))
        fake_tab(env, jwt_of(editor), "edition-tab", reply=context_reply("/", selection=2))
        readonly = listed(env, env.token(viewer, "readonly"), tab_id="viewer-tab")
        names = {n for r in tool_rows(readonly).values() for n in r}
        assert "ui_select_photos" in names and "search_photos" in names
        assert not names & {"batch_set_rating", "cull_apply", "delete_photos", "set_rating"}
        assert all(t["required_level"] == "readonly" for r in readonly["actions"] for t in r["tools"])
        edition = listed(env, env.token(editor, "edition"), tab_id="edition-tab")
        assert {"batch_set_rating", "cull_apply"} <= {n for r in tool_rows(edition).values() for n in r}

    def test_get_context_rewrites_the_tab_actions_for_the_tokens_level(self, agent_app, fake_tab):
        env = agent_app("legacy")
        editor = env.login(edition=True)
        body = {"route": "/", "selection": {"scope": "paths", "count": 2}, "gallery": None, "mounted_actions": [],
                "level": "edition", "actions": [
                    {"id": "cull_or_delete", "summary": "x", "tools": ["cull_apply", "delete_photos"]}]}
        fake_tab(env, jwt_of(editor), "edition-tab", reply=lambda call: {"ok": True, "data": dict(body)})
        readonly = env.call(env.token(editor, "readonly"), "ui_get_context", {"tab_id": "edition-tab"})
        assert readonly["ok"] is True and readonly["data"]["level"] == "readonly", readonly
        shown = {n for row in readonly["data"]["actions"] for n in row["tools"]}
        assert "search_photos" in shown and not shown & {"cull_apply", "delete_photos", "batch_set_rating"}
        edition = env.call(env.token(editor, "edition"), "ui_get_context", {"tab_id": "edition-tab"})
        assert {"cull_apply", "delete_photos"} <= {n for row in edition["data"]["actions"] for n in row["tools"]}

    def test_a_single_password_install_reports_user_tools_at_the_edition_level(self, agent_app, fake_tab):
        env = agent_app("legacy")
        editor = env.login(edition=True)
        fake_tab(env, jwt_of(editor), reply=context_reply("/", selection=1))
        data = listed(env, env.token(editor, "edition"))
        rate = tool_rows(data)["rate_photos"]["set_rating"]
        assert rate["required_level"] == "edition"

    def test_user_tools_appear_for_a_user_token_only_in_multi_user(self, agent_app, fake_tab):
        env = agent_app("multi")
        fake_tab(env, jwt_of(env.login("alice")), reply=context_reply("/", selection=1))
        user = listed(env, env.token(env.login("alice"), "user"))
        names = {n for r in tool_rows(user).values() for n in r}
        assert {"set_rating", "set_favorite", "set_rejected"} <= names
        assert "batch_set_rating" not in names
        readonly = listed(env, env.token(env.login("alice"), "readonly"))
        assert "set_rating" not in {n for r in tool_rows(readonly).values() for n in r}

    def test_an_unreachable_tab_answers_like_no_tab(self, agent_app):
        env = agent_app("open")
        data = listed(env, env.token(env.login()), tab_id="nope")
        assert data["tab"] is None and data["hidden"] > 0

    def test_a_malformed_context_falls_back_to_the_any_jobs(self, agent_app, fake_tab):
        env = agent_app("open")
        fake_tab(env, None, reply=lambda call: {"ok": True, "data": {"route": 5, "selection": "x", "gallery": 7}})
        data = listed(env, env.token(env.login()))
        assert {r["id"] for r in data["actions"]} <= {a.id for a in ACTIONS if "any" in a.when | {"gallery"}}


class TestAdvertisedMatchesEnforced:
    """A tool above the key is neither advertised nor callable; one at or below it is never refused."""

    ARGS = {
        **test_agent_write.TestGrantMatrix.ARGS,
        "list_culling_groups": {}, "culling_profiles": {}, "suggest_culling_profile": {},
        "keeper_hints": {"paths": ["/x.jpg"]}, "auto_cull": {}, "confirm_culling_groups": {
            "groups": [{"type": "burst", "group_id": 1, "paths": ["/x.jpg"], "keep_paths": ["/x.jpg"]}]},
    }

    @pytest.mark.parametrize("mode,user,token_level", [
        ("legacy", None, "readonly"), ("multi", "alice", "user"), ("multi", "root", "edition")])
    def test_above_grant_tools_are_omitted_and_refused(self, agent_app, fake_tab, mode, user, token_level):
        env = agent_app(mode)
        headers = env.login(user) if mode == "multi" else env.login()
        fake_tab(env, jwt_of(headers), reply=context_reply("/", selection=1))
        token = env.token(headers, token_level)
        advertised = {n for r in tool_rows(listed(env, token)).values() for n in r}
        rank = tokens.level_rank
        for tool, args in self.ARGS.items():
            if rank(TOOL_LEVELS[tool]) > rank(token_level):
                assert tool not in advertised, (token_level, tool)
                result = env.call(token, tool, args)
                assert result.get("error") == "forbidden_level", (token_level, tool, result)
            elif TOOL_LEVELS[tool] == "readonly" and tool in advertised:
                assert env.call(token, tool, args).get("error") != "forbidden_level", tool


def test_an_unregistered_tool_has_no_default_floor():
    import asyncio
    from api.agent.runtime import run_tool

    async def handler(grant, resolved, settings):
        raise AssertionError("must not run")

    with pytest.raises(KeyError):
        asyncio.run(run_tool(None, "no_such_tool", handler))
