"""``ui_tools.py`` is canonical; the client's JSON is generated and must not drift."""

import json
import re

import pytest
from pathlib import Path

from api.agent.ui_tools import UI_TOOLS, render_client_json, tools_version

# Reads client, i18n or docs files: runs on every pull request (see ci.yml).
pytestmark = pytest.mark.cross_file

CLIENT_JSON = Path(__file__).resolve().parent.parent / "client/src/app/core/agent/ui-tools.schema.json"


def test_committed_json_matches_the_contract():
    assert CLIENT_JSON.read_text(encoding="utf-8") == render_client_json(), (
        "ui-tools.schema.json is stale: run `venv/bin/python scripts/dump_ui_tools.py`")


DOCS = Path(__file__).resolve().parent.parent / "docs"


@pytest.mark.parametrize("lang", ["", "fr", "de", "it", "es", "pt", "zh"])
def test_every_ui_tool_has_a_row_in_the_agents_doc_table(lang):
    text = (DOCS / lang / "AGENTS.md").read_text(encoding="utf-8")
    rows = {m.group(1) for m in re.finditer(r"^\| `(ui_[a-z_]+)` \|", text, re.MULTILINE)}
    assert rows == {tool.name for tool in UI_TOOLS}


def test_json_shape_for_the_client_checker():
    data = json.loads(render_client_json())
    assert data["version"] == tools_version() and re.fullmatch(r"[0-9a-f]{16}", data["version"])
    assert [t["name"] for t in data["tools"]] == [t.name for t in UI_TOOLS]
    for tool in data["tools"]:
        schema = tool["inputSchema"]
        assert schema["type"] == "object" and schema["additionalProperties"] is False
        assert "tab_id" not in schema["properties"]
        assert "$ref" not in json.dumps(schema) and "anyOf" not in json.dumps(schema)
        assert {"readOnlyHint", "destructiveHint", "untrustedContentHint"} <= set(tool["annotations"])


def test_json_carries_the_jobs_table_for_the_client():
    from api.agent.actions import ACTIONS, FACTS
    rows = json.loads(render_client_json())["actions"]
    assert [r["id"] for r in rows] == [a.id for a in ACTIONS]
    for row in rows:
        assert set(row) == {"id", "summary", "when", "tools"}
        assert set(row["when"]) <= FACTS
        assert all(set(t) == {"name", "required_level"} for t in row["tools"])


def test_version_changes_with_a_description():
    before = tools_version()
    original = UI_TOOLS[0]
    import api.agent.ui_tools as module
    from dataclasses import replace
    module.UI_TOOLS = (replace(original, description=original.description + "!"),) + UI_TOOLS[1:]
    try:
        assert tools_version() != before
    finally:
        module.UI_TOOLS = (original,) + module.UI_TOOLS[1:]
    assert tools_version() == before


def test_ui_get_context_describes_the_culling_block_and_its_activity_kinds():
    description = next(t for t in UI_TOOLS if t.name == "ui_get_context").description
    for term in ("culling", "plan_digest", "groups_total", "confirmed", "pending", "changed", "untouched",
                 "cull_confirm", "cull_skip", "review (a manual Keep or Reset: value kept or undecided)"):
        assert term in description, term
    for gone in ("review.applied", "groups_applied", "`review`"):
        assert gone not in description, gone


def test_ui_show_culling_plan_takes_the_digest_the_shared_request_and_a_focus():
    from api.agent.ui_tools import UiShowCullingPlan, input_schema
    from api.models.culling import CullPlanRequest
    assert UiShowCullingPlan.model_fields["request"].annotation is CullPlanRequest
    args = UiShowCullingPlan(plan_digest="abc", request={"group_by": "burst", "strictness": 40}, focus=3)
    forwarded = args.forward()
    assert forwarded["plan_digest"] == "abc" and forwarded["focus"] == 3
    assert forwarded["request"]["group_by"] == "burst" and forwarded["request"]["strictness"] == 40
    assert "focus" not in UiShowCullingPlan(plan_digest="abc", request={}).forward()
    for bad in ({"plan_digest": "abc", "request": {}, "focus": 0}, {"request": {}},
                {"plan_digest": "abc"}, {"plan_digest": "abc", "request": {"group_by": "weird"}},
                {"plan_digest": "abc", "request": {}, "extra": 1}):
        with pytest.raises(ValueError):
            UiShowCullingPlan(**bad)
    schema = input_schema(next(t for t in UI_TOOLS if t.name == "ui_show_culling_plan"))
    text = json.dumps(schema)
    assert "$ref" not in text and "anyOf" not in text and schema["required"] == ["plan_digest", "request"]
    assert schema["properties"]["request"]["properties"]["keep_paths"]["maxItems"] == 1000


def test_ui_show_culling_plan_is_an_edition_write_free_tool():
    tool = next(t for t in UI_TOOLS if t.name == "ui_show_culling_plan")
    assert tool.read_only is False
    assert "/culling" in tool.description and "unsaved_decisions" in tool.description \
        and "plan_changed" in tool.description


def test_the_tab_may_report_the_plan_refusals():
    from api.agent.ui_tools import TAB_ERROR_CODES
    assert {"unsaved_decisions", "plan_changed", "plan_load_failed", "stack_mode_active", "navigation_refused"} <= TAB_ERROR_CODES


def test_the_navigating_tools_describe_the_leave_culling_refusal():
    from api.agent.ui_tools import UI_TOOLS
    by_name = {tool.name: tool for tool in UI_TOOLS}
    for name in ("ui_navigate", "ui_open_photo", "ui_open_album", "ui_show_photos", "ui_set_gallery_filters", "ui_show_comparison"):
        assert "unsaved_decisions" in by_name[name].description, name


def test_ui_show_photos_path_bound_is_in_the_contract_and_enforced():
    from api.agent.ui_tools import UiShowPhotos
    items = UiShowPhotos.model_json_schema()["properties"]["paths"]["items"]
    assert items["minLength"] == 1 and items["maxLength"] == 4096
    with pytest.raises(ValueError):
        UiShowPhotos(paths=["x" * 4097])
    with pytest.raises(ValueError):
        UiShowPhotos(paths=[""])


def test_ui_show_photos_takes_only_paths_and_rejects_the_removed_review_fields():
    from api.agent.ui_tools import UiShowPhotos
    assert UiShowPhotos(paths=["a", "b"]).forward() == {"paths": ["a", "b"]}
    assert set(UiShowPhotos.model_fields) == {"paths", "tab_id"}
    for name, value in (("groups", [1]), ("marks", ["keep"]), ("labels", [{"key": "burst"}]),
                        ("reasons", [{"key": "best"}]), ("kinds", ["burst"])):
        with pytest.raises(ValueError):
            UiShowPhotos(paths=["a"], **{name: value})


def test_ui_show_photos_schema_is_a_plain_paths_array():
    from api.agent.ui_tools import input_schema
    schema = input_schema(next(t for t in UI_TOOLS if t.name == "ui_show_photos"))
    text = json.dumps(schema)
    assert "$ref" not in text and "anyOf" not in text
    assert schema["additionalProperties"] is False
    assert list(schema["properties"]) == ["paths"]
    description = next(t for t in UI_TOOLS if t.name == "ui_show_photos").description
    assert "keep/remove" not in description and "section" not in description


def test_ui_get_context_takes_an_optional_activity_since():
    from api.agent.ui_tools import UiGetContext, input_schema
    assert UiGetContext().forward() == {}
    assert UiGetContext(activity_since=7).forward() == {"activity_since": 7}
    with pytest.raises(ValueError):
        UiGetContext(activity_since=-1)
    schema = input_schema(next(t for t in UI_TOOLS if t.name == "ui_get_context"))
    assert schema["properties"]["activity_since"]["type"] == "integer"
    text = next(t.description for t in UI_TOOLS if t.name == "ui_get_context")
    assert "activity_since" in text and "user_activity" in text


def test_ui_suggest_culling_bounds():
    from api.agent.ui_tools import UiSuggestCulling
    photo = {"path": "/a.jpg", "action": "reject", "reason": "blink"}
    assert UiSuggestCulling(photos=[photo], groups=[{"path": "/a.jpg", "note": "close call"}]).forward() == {
        "photos": [photo], "groups": [{"path": "/a.jpg", "note": "close call"}], "replace": False}
    assert UiSuggestCulling(replace=True).forward() == {"replace": True, "photos": [], "groups": []}
    for bad in ({}, {"photos": [dict(photo)] * 101}, {"groups": [{"path": "/a", "note": "n"}] * 51},
                {"photos": [{**photo, "reason": "x" * 201}]}, {"groups": [{"path": "/a", "note": "x" * 201}]},
                {"photos": [{**photo, "action": "maybe"}]}, {"photos": [{**photo, "why": "x"}]},
                {"groups": [{"path": "/a", "note": "n", "why": "x"}]}, {"photos": [{**photo, "reason": ""}]},
                {"photos": [{**photo, "path": ""}]}, {"photos": [photo], "extra": 1}):
        with pytest.raises(ValueError):
            UiSuggestCulling(**bad)


def test_ui_suggest_culling_is_an_edition_tool_not_read_only():
    tool = next(t for t in UI_TOOLS if t.name == "ui_suggest_culling")
    assert tool.read_only is False
    names = [t.name for t in UI_TOOLS]
    assert names.index("ui_suggest_culling") == names.index("ui_show_culling_plan") + 1
    for term in ("no_plan", "too_large", "replace", "tab_id", "plan_digest", "forbidden_level"):
        assert term in tool.description, term
    assert "no_plan" in json.loads(render_client_json())["error_codes"]
    context = next(t for t in UI_TOOLS if t.name == "ui_get_context").description
    for term in ("suggestions_open", "suggestions_accepted", "suggestions_total"):
        assert term in context, term


def test_json_carries_the_filter_key_tables_the_client_is_checked_against():
    from api.agent.ui_tools import CONTRACT_TO_CLIENT_KEY, SMART_ALBUM_EXCLUDE_KEYS
    data = json.loads(render_client_json())
    assert data["filter_key_map"] == CONTRACT_TO_CLIENT_KEY
    assert data["smart_album_exclude_keys"] == sorted(SMART_ALBUM_EXCLUDE_KEYS)


def test_ui_open_album_takes_a_bounded_positive_id_and_forwards_only_it():
    from api.agent.ui_tools import UiOpenAlbum
    assert UiOpenAlbum(album_id=3).forward() == {"album_id": 3}
    for bad in (0, -1, 2**31):
        with pytest.raises(ValueError):
            UiOpenAlbum(album_id=bad)


def test_ui_open_album_names_where_the_id_comes_from():
    tool = next(t for t in UI_TOOLS if t.name == "ui_open_album")
    assert "list_albums" in tool.description and "create_album" in tool.description
    assert "not_found" in tool.description


def test_ui_navigate_timeline_year_and_month():
    from api.agent.ui_tools import UiNavigate
    assert UiNavigate(route="/timeline", year=2024, month=3).forward() == {
        "route": "/timeline", "year": 2024, "month": 3}
    assert UiNavigate(route="/timeline", year=2024).forward() == {"route": "/timeline", "year": 2024}


@pytest.mark.parametrize("kwargs", [
    {"route": "/stats", "year": 2024},
    {"route": "/stats", "month": 3, "year": 2024},
    {"route": "/timeline", "month": 3},
    {"route": "/timeline", "year": 1899},
    {"route": "/timeline", "year": 2101},
    {"route": "/timeline", "year": 2024, "month": 13},
    {"route": "/timeline", "year": 2024, "month": 0},
    {"route": "/timeline", "year": 2024, "query": {"a": 1}},
])
def test_ui_navigate_rejects_a_bad_timeline_combination(kwargs):
    from api.agent.ui_tools import UiNavigate
    with pytest.raises(ValueError):
        UiNavigate(**kwargs)


def test_drive_tab_includes_the_album_tool():
    from api.agent.actions import ACTIONS
    drive = next(a for a in ACTIONS if a.id == "drive_tab")
    assert "ui_open_album" in drive.tools


def test_modal_open_is_a_tab_error_code_and_in_the_client_json():
    from api.agent.ui_tools import TAB_ERROR_CODES
    assert "modal_open" in TAB_ERROR_CODES
    assert "modal_open" in json.loads(render_client_json())["error_codes"]


def test_only_the_non_read_only_tools_carry_the_modal_refusal_sentence():
    from api.agent.ui_tools import MODAL_REFUSAL, tool_descriptors
    by_name = {d["name"]: d for d in tool_descriptors()}
    for tool in UI_TOOLS:
        assert (MODAL_REFUSAL in by_name[tool.name]["description"]) is (not tool.read_only), tool.name
    assert "modal_open" in MODAL_REFUSAL and "read-only" in MODAL_REFUSAL


def test_the_mcp_registration_carries_the_same_sentence():
    from api.agent.tools_ui import register_ui_tools
    from api.agent.ui_tools import MODAL_REFUSAL

    class Recorder:
        def __init__(self):
            self.descriptions = {}

        def add_tool(self, fn, *, name, description, **kwargs):
            self.descriptions[name] = description

    recorder = Recorder()
    register_ui_tools(recorder, None)
    assert set(recorder.descriptions) == {tool.name for tool in UI_TOOLS}
    for tool in UI_TOOLS:
        assert (MODAL_REFUSAL in recorder.descriptions[tool.name]) is (not tool.read_only), tool.name


@pytest.mark.parametrize("lang", ["", "fr", "de", "it", "es", "pt", "zh"])
def test_every_agents_doc_lists_the_same_error_codes_and_modal_open(lang):
    def codes(path):
        line = next(row for row in path.read_text(encoding="utf-8").splitlines() if re.search(r"^- \*\*[^*]+[:：]\*\* `forbidden_level`", row))
        return set(re.findall(r"`([a-z_]+)`", line))
    english = codes(DOCS / "AGENTS.md")
    assert "modal_open" in english
    assert codes(DOCS / lang / "AGENTS.md") == english
    reasons = next(row for row in (DOCS / lang / "AGENTS.md").read_text(encoding="utf-8").splitlines() if '{"applied": false, "reason"}' in row)
    assert "modal_open" in reasons


def test_rejected_only_patch_preserves_explicit_review_status():
    from api.agent.ui_tools import UiSetGalleryFilters
    assert UiSetGalleryFilters.model_validate({"patch": {
        "show_rejected": True, "review_status": "kept"}}).forward() == {
            "patch": {"show_rejected": True, "review_status": "kept"}, "replace": False}


def test_registered_search_guidance_supports_rejected_only_tab_filters():
    from api.agent.tools_read import register_read_tools
    from api.agent.ui_tools import TAB_UNSUPPORTED_FILTER_KEYS

    class Recorder:
        def __init__(self):
            self.descriptions = {}

        def add_tool(self, fn, *, name, description, **kwargs):
            self.descriptions[name] = description

    recorder = Recorder()
    register_read_tools(recorder, None, None, None)
    description = recorder.descriptions["search_photos"]
    unsupported = description.split("Filters the gallery sidebar has no field for (", 1)[1].split(")", 1)[0]
    assert set(unsupported.split(", ")) == TAB_UNSUPPORTED_FILTER_KEYS
    assert "`show_rejected` can be shown in the tab" in description


def test_rejected_only_and_favorites_patch_is_refused_atomically():
    from api.agent.ui_tools import UiSetGalleryFilters
    with pytest.raises(ValueError, match="cannot be combined"):
        UiSetGalleryFilters.model_validate({"patch": {"show_rejected": True, "favorites_only": True}})
