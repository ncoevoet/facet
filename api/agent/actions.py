"""What an assistant can do right now: ONE declarative table, evaluated for a tab's state.

``ACTIONS`` is the only place that says which tools belong to which job and when the job
applies. A tool's level is NOT here: it comes from ``tools_common.TOOL_LEVELS``, which
registration fills from the same sources ``run_tool`` enforces, so a hand-kept second list
cannot drift from the gate. A drift test ties the table to the registered tools.

Advertising follows rights: a tool above the caller's effective level is omitted from its
action (and an action left with no tool is omitted entirely). ``allowed`` is kept only for
state-dependent unavailability (a tool that needs the gallery open, or a selection).

The same table is rendered into ``ui-tools.schema.json`` (``render_client_actions``) so an
in-page agent gets the list from ``ui_get_context`` without a server round trip; the
closed ``when`` facts are evaluated by the client with the same rules as ``facts_for``.
"""

from dataclasses import dataclass
from typing import Any, Mapping

from api.agent import tokens

# The closed set of facts an action's ``when`` may name. An action applies when ``any`` is
# named or at least one of its facts holds.
FACTS = frozenset({"any", "gallery", "detail", "selection", "culling", "persons", "albums", "pinned"})


@dataclass(frozen=True)
class Action:
    id: str
    summary: str
    tools: tuple[str, ...]
    when: frozenset[str]


def _when(*facts: str) -> frozenset[str]:
    return frozenset(facts)


ANY = _when("any")

ACTIONS: tuple[Action, ...] = (
    Action("check_access", "See who you act as, what the token may do and what the open tab shows",
           ("status", "available_actions", "ui_get_context"), ANY),
    Action("search_library", "Find photos by filters, by meaning or by look-alike",
           ("search_photos", "semantic_search", "similar_photos", "filter_options"), ANY),
    Action("browse_library", "Read one photo, the people, the albums and the library statistics (the lists open their page with show=true)",
           ("get_photo", "list_persons", "list_albums", "library_stats"), ANY),
    Action("look_at_photos", "See a photo or a numbered contact sheet of up to 16 photos, or the ones the user selected",
           ("get_thumbnail", "contact_sheet"), _when("gallery", "detail")),
    Action("match_faces", "Find faces that look like a recognised person",
           ("possible_faces", "assign_faces"), _when("persons")),
    Action("drive_tab", "Move the user's tab to another page, an album or a timeline month, or open a photo",
           ("ui_navigate", "ui_open_photo", "ui_open_album"), ANY),
    Action("steer_gallery", "Change what the gallery shows and read it back",
           ("ui_set_gallery_filters", "ui_show_photos", "ui_get_gallery_view", "ui_next_page"), _when("gallery")),
    Action("select_photos", "Select photos in the tab and read the selection back",
           ("ui_select_photos", "ui_get_selection", "ui_clear_selection"), _when("gallery")),
    Action("rate_photos", "Rate, favourite or reject a few photos",
           ("set_rating", "set_favorite", "set_rejected"), _when("gallery", "detail")),
    Action("edit_many", "Rate, flag or tag many photos at once",
           ("batch_set_rating", "batch_set_favorite", "batch_set_rejected", "add_tags", "remove_tags"),
           _when("gallery", "selection")),
    Action("manage_albums", "Create an album and add photos to it or remove them",
           ("create_album", "album_add_photos", "album_remove_photos"),
           _when("gallery", "detail", "albums", "selection")),
    Action("manage_stacks", "Read or organize an owner-private local photo stack without changing files or review decisions",
           ("get_photo_stack", "create_photo_stack", "update_photo_stack", "unstack_photos", "undo_photo_stack"),
           _when("gallery", "detail", "selection")),
    Action("import_ai_edits", "Bring an AI-edited copy of a photo into the library, linked to its original",
           ("import_ai_edit",), _when("detail", "gallery", "selection")),
    Action("write_metadata", "Set a photo's caption or write XMP sidecars next to the files",
           ("set_caption", "export_metadata"), _when("detail", "gallery", "selection")),
    Action("junk_sweep", "Review junk-sweep candidates (shown on the junk page with show=true) and reject or keep them",
           ("junk_list", "junk_reject", "junk_clear"), ANY),
    Action("teach_preferences", "Open the comparison page so the user can teach Facet their taste",
           ("ui_show_comparison", "comparison_status"), ANY),
    Action("fix_sequence_set", "Tell Facet what a set of frames really is (panorama, bracket, not a set)",
           ("override_sequence", "clear_sequence_override"), _when("culling", "selection")),
    Action("recategorize", "Pin or release one photo's category",
           ("override_category", "clear_category_override"), _when("detail", "selection")),
    Action("explain_scores", "Read why a photo scored what it did, metric by metric",
           ("explain_score",), _when("detail", "gallery", "selection")),
    Action("tune_weights", "Read a category's scoring weights, preview a change, apply it once the user agrees and undo it",
           ("category_weights", "preview_weights", "learned_weights", "apply_weights", "list_weight_snapshots",
            "restore_weight_snapshot"), ANY),
    Action("recompute_scores", "Re-score the library (or one category) with the current weights and follow the job",
           ("recompute_scores", "recompute_status"), ANY),
    Action("fix_categories", "Find photos filed in the wrong category and pin several to the right one",
           ("misassigned_categories", "override_categories"), ANY),
    Action("compare_in_group", "Compare the faces or the subject sharpness of a group's frames",
           ("group_compare",), _when("culling")),
    Action("cull_summary", "Summarise a scope before culling it", ("cull_report",), ANY),
    Action("start_scan", "Start a scan of a configured directory and follow it",
           ("start_scan", "scan_status"), ANY),
    Action("cull_or_delete", "Copy the keepers, move or trash the rejects, or delete photos",
           ("cull_apply", "delete_photos"), _when("gallery", "selection")),
    Action("work_darkroom", "Work through culling groups and confirm what to keep",
           ("list_culling_groups", "culling_profiles", "suggest_culling_profile", "keeper_hints",
            "auto_cull", "confirm_culling_groups", "ui_show_culling_group", "ui_show_culling_plan",
            "ui_suggest_culling"),
           _when("culling")),
)

# A tool that cannot run until the tab is in a given state: ``allowed`` is false until then.
TOOL_STATE_NEEDS: Mapping[str, str] = {
    "ui_get_gallery_view": "gallery",
    "ui_next_page": "gallery",
    "ui_clear_selection": "selection",
}
STATE_HINTS: Mapping[str, str] = {
    "gallery": "open the gallery first (ui_navigate to /)",
    "selection": "select photos in the tab first",
}


def facts_for(route: str, selection_count: int, pinned: bool) -> frozenset[str]:
    """The facts that hold for a tab, from its route, selection size and pinned-list state."""
    path = route.split("?")[0].split("#")[0] or "/"
    facts = {"any"}
    if path == "/" or path.startswith("/album/"):
        facts.add("gallery")
    if path == "/photo":
        facts.add("detail")
    if path == "/culling":
        facts.add("culling")
    if path in ("/persons", "/merge-suggestions"):
        facts.add("persons")
    if path == "/albums" or path.startswith("/album/"):
        facts.add("albums")
    if selection_count > 0:
        facts.add("selection")
    if pinned:
        facts.add("pinned")
    return frozenset(facts)


def facts_from_context(data: dict) -> tuple[frozenset[str], str, int, bool]:
    """``(facts, route, selection_count, pinned)`` from a tab's ``ui_get_context`` data."""
    raw_gallery, raw_selection = data.get("gallery"), data.get("selection")
    gallery: dict = raw_gallery if isinstance(raw_gallery, dict) else {}
    selection: dict = raw_selection if isinstance(raw_selection, dict) else {}
    raw_count = selection.get("count")
    count = raw_count if isinstance(raw_count, int) else 0
    route = str(data.get("route") or "/")
    pinned = bool(gallery.get("pinned"))
    return facts_for(route, count, pinned), route, count, pinned


def applies(action: Action, facts: frozenset[str]) -> bool:
    return "any" in action.when or bool(action.when & facts)


def evaluate(level: str, facts: frozenset[str], levels: Mapping[str, str],
             switched_off: frozenset[str] = frozenset()) -> tuple[list[dict], int]:
    """``(actions, hidden)`` for a caller at ``level`` and a tab in state ``facts``.

    ``hidden`` counts the actions that do not apply to the tab's state; actions dropped for
    rights are not counted (the caller cannot use them anyway). Tools in ``switched_off`` (an
    operator's switch, e.g. ``viewer.mcp.allow_destructive``) are dropped from their action the same way.
    """
    rank = tokens.level_rank(level)
    rows: list[dict] = []
    hidden = 0
    for action in ACTIONS:
        if not applies(action, facts):
            hidden += 1
            continue
        listed: list[dict[str, Any]] = []
        for name in action.tools:
            floor = tokens.effective_requirement(levels[name])
            if tokens.level_rank(floor) > rank or name in switched_off:
                continue
            need = TOOL_STATE_NEEDS.get(name)
            listed.append({"name": name, "required_level": floor, "allowed": need is None or need in facts})
        if not listed:
            continue
        row: dict = {"id": action.id, "summary": action.summary, "tools": listed}
        blocked = sorted({TOOL_STATE_NEEDS[t["name"]] for t in listed if not t["allowed"]})
        if blocked:
            row["hint"] = "; ".join(STATE_HINTS[fact] for fact in blocked)
        rows.append(row)
    return rows, hidden


def tool_levels() -> Mapping[str, str]:
    """``TOOL_LEVELS``, filled by registration; built from a throwaway server when nothing has registered yet."""
    from api.agent.server import fill_tool_levels
    return fill_tool_levels(tuple(name for action in ACTIONS for name in action.tools))


def render_client_actions() -> list[dict]:
    """The table as the client JSON carries it: ``{id, summary, when, tools: [{name, required_level}]}``."""
    levels = tool_levels()
    return [{"id": a.id, "summary": a.summary, "when": sorted(a.when),
             "tools": [{"name": name, "required_level": levels[name]} for name in a.tools]}
            for a in ACTIONS]
