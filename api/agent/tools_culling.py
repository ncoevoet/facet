"""Darkroom tools: culling groups, profiles, keeper hints, auto-cull and group confirm.

Every tool needs the ``edition`` level (the darkroom feeds, ``confirm`` and ``auto``
are edition-gated upstream) and reaches data through ``InternalClient`` over the
existing ``/api`` routes -- there is no second SQL path. A group's identity is the
PAIR ``(type, group_id)``: similar ids are offset when merged with bursts, and a
bracket / panorama / hdr_panorama set is always kept whole (the darkroom's rule).

The two writers are bounded server-side by a target-bound confirmation nonce:
``auto_cull`` apply needs the ``confirm`` value from a preview of the SAME resolved
plan, and ``confirm_culling_groups`` needs one whenever a group would reject every
frame it names.
"""

from dataclasses import dataclass
from typing import Annotated, Any, Literal, Optional

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import CallToolResult, ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field

from api.agent import limits, nonce
from api.agent import show as relay
from api.agent.bridge import MAX_FRAME_BYTES, TabRegistry
from api.agent.internal_client import InternalClient, RouteSpec, err, ok
from api.agent.live_updates import WriteSink
from api.agent.limits import encoded_size
from api.agent.runtime import run_tool
from api.agent.ui_tools import TAB_ID_PATTERN, UiShowCullingPlan
from api.agent.tools_common import DESTRUCTIVE_ANNOTATIONS, READ_ANNOTATIONS, register_tool
from api.db_helpers import to_second_granularity
from api.models.culling import CullPlanRequest

CULLING_ROUTES: dict[str, RouteSpec] = {
    "culling.groups": RouteSpec("GET", "/api/culling-groups", "edition"),
    "culling.profiles": RouteSpec("GET", "/api/culling/profiles", "edition"),
    "culling.suggest_profile": RouteSpec("GET", "/api/culling/suggest_profile", "edition"),
    "culling.keeper_hints": RouteSpec("POST", "/api/photos/keeper_hints", "edition"),
    "culling.auto": RouteSpec("POST", "/api/culling/auto", "edition", write=True),
    "culling.confirm": RouteSpec("POST", "/api/culling-groups/confirm", "edition", write=True),
}

# Every darkroom route is edition-gated upstream; the tools carry the same floor.
CULLING_LEVEL = "edition"

GroupType = Literal["burst", "similar", "scene", "bracket", "panorama", "hdr_panorama"]
KEEP_WHOLE_TYPES = ("bracket", "panorama", "hdr_panorama")
GROUP_PHOTO_LIMIT = 12
GROUP_PHOTO_KEYS = ("path", "filename", "date_taken", "aggregate", "aesthetic", "tech_sharpness",
                    "is_blink", "sequence_ev_offset", "keeper_prob")
SEE_GROUP = " Call ui_show_culling_group to show a group to the user."
AUTO_CULL_SHOW = (
    " A successful dry run with rows opens its plan on the user's /culling page in their open Facet tab "
    "(`show`, default true; never ask whether to show it): the same groups, keep/reject borders, loupe and "
    "compare as manual culling, with the plan's keepers pre-selected for the user to flip and confirm group "
    "by group. Report `shown_in_tab` (applied, or the reason it was not: `unsaved_decisions` when the user "
    "holds unconfirmed decisions on the page, `plan_changed` when the library moved since the preview, `plan_load_failed` when the tab could not "
    "load the plan for another reason, `navigation_refused` when the tab declined to open /culling, `comparison_open` when the user is on the comparison page, `modal_open` when a dialog, bottom sheet or slideshow is open in the tab, `stack_mode_active` when the page is in Suggested stacks mode, "
    "`too_large` when the overrides are too big to send). A page with `cursor` > 0 only moves the tab's focus "
    "to that page's first group. `ui_get_context` reports the user's progress as `culling` (confirmed groups, "
    "pending flips, and `culling.changed`: every group whose keepers differ from the plan, with its "
    "keep_paths and reject_paths). Their flips are NOT read back by the apply: pass the `changed` groups' "
    "paths as keep_paths / remove_paths on the next dry run and on the apply (explicit lists must be the SAME "
    "on both). Groups the user confirmed leave the plan, so the digest moves and the apply is refused until "
    "you preview again. The apply never shows; show=false skips it.")

SUMMARY_PATHS = 20
CONFIRM_WIDTH = 40
APPLY_KEYS = ("groups_processed", "kept", "rejected", "highlights_added", "dry_run",
              "skipped_user_changed", "skipped_user_changed_count", "skipped_user_changed_groups",
              "state_guard")
MAX_REMEMBERED = 64


@dataclass(frozen=True)
class _Preview:
    """What a dry run issued a ``confirm`` for: the plan digest it was computed from, until ``expires``."""
    digest: str
    expires: float
    knobs: Optional[dict] = None
    tab_pin: Optional[str] = None
    tab_id: Optional[str] = None


_previews: dict[tuple, _Preview] = {}


def reset_preview_memory() -> None:
    _previews.clear()


def _remember(key: tuple, value: _Preview) -> None:
    """Insert into ``_previews``, shedding expired entries first and then the oldest past ``MAX_REMEMBERED``."""
    current = limits.now()
    for stale in [k for k, v in _previews.items() if v.expires <= current]:
        del _previews[stale]
    _previews[key] = value
    while len(_previews) > MAX_REMEMBERED:
        del _previews[next(iter(_previews))]


def _recall(key: tuple) -> Optional[_Preview]:
    value = _previews.get(key)
    if value is None or value.expires <= limits.now():
        _previews.pop(key, None)
        return None
    return value


# Room kept for what the tool adds after the page is fitted (`shown_in_tab`).
SHOWN_RESERVE = 4096


def _fit_page(data: dict, extra: dict, settings: dict) -> None:
    """Drop whole rows from the end of ``data['rows']`` until the envelope fits the runtime caps.

    The tool owns the page budget: ``fit_envelope`` would otherwise cut rows while the route's
    ``next_cursor`` still points past them. Rows dropped here move ``next_cursor`` back to the last
    returned row's ``number`` (the next group's 0-based plan index). At least one row stays; if that
    one row alone is still over budget its path lists are clipped (``keep_count`` / ``reject_count``
    carry the full sizes, ``paths_clipped`` is true) so the group is never silently dropped.
    """
    rows = data["rows"]
    budget = max(settings["max_bytes"] - SHOWN_RESERVE, settings["max_bytes"] // 2)
    shown = len(rows)
    while shown > 1 and (shown > settings["max_rows"]
                         or encoded_size(ok({**data, "rows": rows[:shown]}, **extra)) > budget):
        shown -= 1
    if shown < len(rows):
        data["rows"] = rows[:shown]
        data["next_cursor"] = rows[shown - 1]["number"]
    if shown == 1 and encoded_size(ok(data, **extra)) > budget:
        _clip_row(data, extra, budget)


def _clip_row(data: dict, extra: dict, budget: int) -> None:
    """Clip the only row's path lists to the longest prefix that fits ``budget``."""
    row = dict(data["rows"][0])
    keep, reject = row.get("keep_paths") or [], row.get("reject_paths") or []
    row.update(keep_count=len(keep), reject_count=len(reject), paths_clipped=True)
    reasons = row.get("reasons") or {}

    def fits(n: int) -> bool:
        trial = {**row, "keep_paths": keep[:n], "reject_paths": reject[:n],
                 "reasons": {p: reasons[p] for p in reject[:n] if p in reasons}}
        return encoded_size(ok({**data, "rows": [trial]}, **extra)) <= budget

    low, high = 0, max(len(keep), len(reject))
    while low < high:
        mid = (low + high + 1) // 2
        low, high = (mid, high) if fits(mid) else (low, mid - 1)
    row.update(keep_paths=keep[:low], reject_paths=reject[:low],
               reasons={p: reasons[p] for p in reject[:low] if p in reasons})
    data["rows"] = [row]


class ConfirmGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: GroupType
    group_id: int
    paths: Annotated[list[str], Field(min_length=1, max_length=1000)]
    keep_paths: Annotated[list[str], Field(max_length=1000)]


def _compact_group(group: dict) -> dict:
    photos = group.get("photos") or []
    kind = group.get("sequence_kind")
    if kind is None:
        kind = next((p.get("sequence_kind") for p in photos if p.get("sequence_kind")), None)
    return {
        "type": group.get("type"),
        "group_id": group.get("group_id"),
        "sequence_kind": kind,
        "reason": group.get("reason"),
        "keeper_best_path": group.get("keeper_best_path"),
        "photo_count": len(photos),
        "photos": [{key: p.get(key) for key in GROUP_PHOTO_KEYS}
                   for p in photos[:GROUP_PHOTO_LIMIT]],
    }


def _fit_groups(rows: list[dict], budget: int) -> list[dict]:
    """Shed group members (never groups) until the page fits ``budget`` serialized bytes.

    A scene page is ~20 groups of up to ``GROUP_PHOTO_LIMIT`` photos; halving every group's
    member list keeps each group visible. ``photo_count`` stays the true size and
    ``photos_truncated`` marks a group whose list was cut.
    """
    shown = GROUP_PHOTO_LIMIT
    while shown > 1 and encoded_size({"rows": rows}) > budget:
        shown = max(1, shown // 2)
        for row in rows:
            if len(row["photos"]) > shown:
                row["photos"] = row["photos"][:shown]
    for row in rows:
        row["photos_truncated"] = len(row["photos"]) < row["photo_count"]
    return rows


PLAN_CHANGED = "The plan changed since it was previewed"
def _confirm_digest(groups: list[ConfirmGroup]) -> str:
    tagged = [f"{g.type}:{g.group_id}:{side}:{path}" for g in groups
              for side, paths in (("all", g.paths), ("keep", g.keep_paths)) for path in paths]
    return nonce.digest(tagged, "confirm_culling_groups")


def normalise_window(date_from: Optional[str], date_to: Optional[str]) -> tuple[Optional[str], Optional[str], Optional[dict]]:
    """``(date_from, date_to, error)``: the darkroom routes' ``YYYY:MM:DD HH:MM:SS`` form.

    Accepts ISO dates, ISO datetimes and EXIF forms; a date-only ``date_to`` becomes 23:59:59.
    """
    try:
        return (to_second_granularity(date_from) if date_from is not None else None,
                to_second_granularity(date_to, end_of_day=True) if date_to is not None else None, None)
    except ValueError as ex:
        return None, None, err("invalid_input", f"date_from/date_to: {ex}")


def _validate_confirm(groups: list[ConfirmGroup]) -> Optional[dict]:
    seen = set()
    for g in groups:
        if (g.type, g.group_id) in seen:
            return err("invalid_input", f"Group ({g.type}, {g.group_id}) is listed twice")
        seen.add((g.type, g.group_id))
        if not set(g.keep_paths) <= set(g.paths):
            return err("invalid_input",
                       f"keep_paths of ({g.type}, {g.group_id}) must be a subset of its paths")
        if g.type in KEEP_WHOLE_TYPES and set(g.keep_paths) != set(g.paths):
            return err("invalid_input",
                       f"A {g.type} set is kept whole: keep_paths must equal paths for "
                       f"({g.type}, {g.group_id})")
    return None


def register_culling_tools(server: MCPServer, app: Any, registry: TabRegistry,
                           on_write: Optional[WriteSink] = None) -> None:
    """Register the darkroom tools. ``app`` is the FastAPI app the routes live on."""
    client = InternalClient(app, CULLING_ROUTES, on_write=on_write)

    def add(fn, name: str, description: str, annotations: ToolAnnotations = READ_ANNOTATIONS) -> None:
        register_tool(server, fn, name, description, annotations, CULLING_LEVEL)

    async def list_culling_groups(
        ctx: Context,
        group_by: Literal["all", "burst", "similar", "scene", "bracket", "panorama",
                          "hdr_panorama"] = "all",
        page: Annotated[int, Field(ge=1)] = 1,
        per_page: Annotated[int, Field(ge=1, le=50)] = 20,
        sort: Literal["easiest", "redundant", "best", "recent", "needs_comparisons",
                      "chronological"] = "easiest",
        direction: Literal["", "asc", "desc"] = "",
        exclude_rejected: bool = True,
        album_id: Optional[int] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            since, until, bad = normalise_window(date_from, date_to)
            if bad:
                return bad
            upstream = await client.call(
                grant, "culling.groups", timeout=settings["call_timeout_s"],
                query={"group_by": group_by, "page": page, "per_page": per_page, "sort": sort,
                       "direction": direction, "exclude_rejected": "1" if exclude_rejected else "0",
                       "album_id": album_id, "date_from": since, "date_to": until})
            if not upstream["ok"]:
                return upstream
            body = upstream["data"] or {}
            rows = _fit_groups([_compact_group(g) for g in body.get("groups", [])],
                               settings["max_bytes"] // 2)
            return ok({"rows": rows,
                       "total": body.get("total_groups", 0), "page": body.get("page", page),
                       "per_page": body.get("per_page", per_page),
                       "total_pages": body.get("total_pages", 0),
                       "has_more": body.get("page", page) < body.get("total_pages", 0)})
        return await run_tool(ctx, "list_culling_groups", handler)

    async def culling_profiles(ctx: Context) -> CallToolResult:
        async def handler(grant, resolved, settings):
            return await client.call(grant, "culling.profiles", timeout=settings["call_timeout_s"])
        return await run_tool(ctx, "culling_profiles", handler)

    async def suggest_culling_profile(
        ctx: Context, album_id: Optional[int] = None,
        date_from: Optional[str] = None, date_to: Optional[str] = None,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            since, until, bad = normalise_window(date_from, date_to)
            if bad:
                return bad
            return await client.call(
                grant, "culling.suggest_profile", timeout=settings["call_timeout_s"],
                query={"album_id": album_id, "date_from": since, "date_to": until})
        return await run_tool(ctx, "suggest_culling_profile", handler)

    async def keeper_hints(
        ctx: Context, paths: Annotated[list[str], Field(min_length=1, max_length=100)],
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            upstream = await client.call(grant, "culling.keeper_hints", json={"paths": paths},
                                         timeout=settings["call_timeout_s"])
            if not upstream["ok"]:
                return upstream
            hints = upstream["data"] or {}
            return ok({"rows": [{"path": path, **hint} for path, hint in hints.items()],
                       "trained": bool(hints)})
        return await run_tool(ctx, "keeper_hints", handler)

    async def auto_cull(
        ctx: Context,
        group_by: Literal["all", "burst", "similar", "scene"] = "all",
        album_id: Optional[int] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        strictness: Annotated[Optional[int], Field(ge=0, le=100)] = None,
        min_keep_per_group: Annotated[Optional[int], Field(ge=1)] = None,
        profile: Optional[str] = None,
        trim_brackets: bool = False,
        highlights_album: Annotated[str, Field(max_length=200)] = "",
        dry_run: bool = True,
        confirm: Optional[str] = None,
        cursor: Annotated[int, Field(ge=0)] = 0,
        plan_digest: Optional[str] = None,
        keep_paths: Annotated[Optional[list[str]], Field(max_length=1000)] = None,
        remove_paths: Annotated[Optional[list[str]], Field(max_length=1000)] = None,
        show: bool = True,
        tab_id: Annotated[Optional[str], Field(pattern=TAB_ID_PATTERN)] = None,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            since, until, bad = normalise_window(date_from, date_to)
            if bad:
                return bad
            timeout = settings["call_timeout_s"]
            owner = grant.nonce_owner
            if dry_run and cursor > 0 and not plan_digest:
                return err("invalid_input", "plan_digest is required when cursor > 0: pass the "
                           "`plan_digest` of the cursor-0 page, so every page comes from the same plan")
            memory = None if dry_run or not confirm else _recall((owner, confirm))
            knobs = None
            use_strictness, use_profile = strictness, profile
            if strictness is None and profile is None:
                if memory is not None:
                    knobs = memory.knobs
                else:
                    knobs = await _tab_knobs(grant, resolved, settings, tab_id, timeout)
                if knobs:
                    use_strictness, use_profile = knobs.get("strictness"), knobs.get("profile")
            options = {"group_by": group_by, "album_id": album_id, "date_from": since,
                       "date_to": until, "strictness": use_strictness,
                       "min_keep_per_group": min_keep_per_group, "profile": use_profile,
                       "trim_brackets": trim_brackets, "highlights_album": highlights_album,
                       "keep_paths": keep_paths or [], "remove_paths": remove_paths or []}
            page_call = {**options, "dry_run": True, "cursor": cursor if dry_run else 0}
            if dry_run and plan_digest:
                page_call["expected_digest"] = plan_digest
            if memory is not None:
                return await apply_preview(grant, memory, options, confirm, timeout, resolved, settings, tab_id)
            preview = await client.call(grant, "culling.auto", json=page_call, timeout=timeout)
            if not preview["ok"] and PLAN_CHANGED in preview.get("message", ""):
                return err("confirmation_required",
                           "The plan changed since the first page; nothing was written. Restart the "
                           "preview from cursor 0 (without plan_digest) and use its new `confirm`")
            if not preview["ok"] or dry_run:
                result = _preview_result(grant, preview, settings, cursor)
                if knobs and result["ok"]:
                    result["data"]["knobs_from_tab"] = knobs
                if show and dry_run and result["ok"]:
                    result["shown_in_tab"] = await _show_plan(
                        result["data"], options, cursor, resolved, settings, tab_id, timeout)
                if result["ok"]:
                    digest = (result.get("data") or {}).get("plan_digest")
                    if digest and result.get("confirm"):
                        if (result.get("shown_in_tab") or {}).get("applied"):
                            pin = digest
                        else:
                            pin = await _tab_plan_digest(resolved, settings, tab_id, timeout)
                        shown_tab = (result.get("shown_in_tab") or {}).get("tab_id") or tab_id
                        _remember((owner, result["confirm"]),
                                  _Preview(digest, limits.now() + nonce.TTL_SECONDS, knobs, pin, shown_tab))
                return result
            digest = (preview["data"] or {}).get("plan_digest")
            if not digest or not _left_to_reject(preview["data"] or {}) \
                    or not nonce.check(grant.nonce_owner, "auto_cull", digest, confirm):
                return err("confirmation_required",
                           "Preview with dry_run=true first and pass its `confirm` value, with the "
                           "same overrides; the plan must be unchanged since that preview")
            return await send_apply(grant, options, digest, timeout)
        return await run_tool(ctx, "auto_cull", handler, write=not dry_run)

    async def _tab_plan_digest(resolved, settings, tab_id: Optional[str], timeout: float) -> Optional[str]:
        """The digest of the plan the tab's /culling page has pinned now; None with no tab, no plan or a failed read."""
        context = await relay.call_tab(registry, resolved, settings, "ui_get_context", {}, tab_id, timeout=timeout)
        culling = (context.get("data") or {}).get("culling") if context.get("ok") else None
        digest = culling.get("plan_digest") if isinstance(culling, dict) else None
        return digest if isinstance(digest, str) and digest else None

    async def _tab_knobs(grant, resolved, settings, tab_id: Optional[str], timeout: float) -> Optional[dict]:
        """The knobs the tab's /culling page would start at: the slider's stored strictness and the stored profile.

        Both when the tab reports both (the page keeps a profile while the slider moves in plan mode and
        re-plans with both; the route lets the explicit strictness win and the profile supply its other
        settings, such as ``keep_min_per_group``); otherwise whichever one is usable. The slider's value is
        stored on every change and is the live one; showing a plan moves it to the plan's strictness.

        None on any failure or an unusable answer: the server default then applies.
        """
        context = await relay.call_tab(registry, resolved, settings, "ui_get_context", {}, tab_id, timeout=timeout)
        defaults = (context.get("data") or {}).get("culling_defaults") if context.get("ok") else None
        if not isinstance(defaults, dict):
            return None
        knobs: dict = {}
        stored = defaults.get("profile")
        if isinstance(stored, str) and stored:
            known = await client.call(grant, "culling.profiles", timeout=timeout)
            ids = {row.get("id") for row in ((known.get("data") or {}).get("profiles") or [])} if known["ok"] else set()
            if stored in ids:
                knobs["profile"] = stored
        strictness = defaults.get("strictness")
        if isinstance(strictness, int) and not isinstance(strictness, bool) and 0 <= strictness <= 100:
            knobs["strictness"] = strictness
        return knobs or None

    async def send_apply(grant, options: dict, digest: str, timeout: float) -> dict:
        applied = await client.call(
            grant, "culling.auto", json={**options, "dry_run": False, "expected_digest": digest},
            timeout=timeout)
        if not applied["ok"]:
            if PLAN_CHANGED in applied.get("message", ""):
                return err("confirmation_required", applied["message"])
            return applied
        body = applied["data"] or {}
        return ok({key: body.get(key) for key in APPLY_KEYS if key in body})

    async def apply_preview(grant, memory: _Preview, options: dict, confirm: Optional[str], timeout: float,
                            resolved, settings, tab_id: Optional[str]) -> dict:
        """Apply the plan the user was shown: the ORIGINAL preview's digest.

        No dry run is re-run (it would hand the route a new digest and, for a plan the user's own edit
        moved, a nonce that cannot match); the route compares the plan with its preview-time snapshot.
        When the preview recorded the plan pinned on the user's /culling page, the tab the preview targeted
        (else the apply's own ``tab_id``) is read once: a pin
        that now differs means the page re-planned or replaced it, and the apply is refused. No tab or no
        plan on screen is not checked.
        """
        if memory.tab_pin:
            now = await _tab_plan_digest(resolved, settings, memory.tab_id or tab_id, timeout)
            if now and now != memory.tab_pin:
                return err("confirmation_required",
                           "the plan on the user's /culling page changed since your preview: it was re-planned "
                           "or replaced. Read ui_get_context and preview again")
        if not nonce.check(grant.nonce_owner, "auto_cull", memory.digest, confirm):
            return err("confirmation_required",
                       "Preview with dry_run=true first and pass its `confirm` value, with the "
                       "same overrides; the plan must be unchanged since that preview")
        return await send_apply(grant, options, memory.digest, timeout)

    async def _show_plan(data: dict, options: dict, page_cursor: int, resolved, settings, tab_id: Optional[str],
                         timeout: float) -> dict:
        """Open the dry run's plan on the user's /culling page; the first page pins it, a later one moves the focus."""
        rows = data.get("rows") or []
        digest = data.get("plan_digest")
        if not rows or not digest:
            return relay.not_shown("empty_result")
        request = CullPlanRequest.model_validate({key: options[key] for key in CullPlanRequest.model_fields})
        payload = {"plan_digest": digest, "request": request.model_dump(mode="json"),
                   **({"focus": rows[0]["number"]} if page_cursor > 0 else {})}
        if encoded_size(payload) > MAX_FRAME_BYTES:
            return relay.not_shown("too_large", note="The overrides are too large to send to the tab; "
                                                       "the plan was not shown.")
        return await relay._show(
            registry, resolved, settings, tab_id, "ui_show_culling_plan", "Show culling plan",
            lambda: UiShowCullingPlan.model_validate(payload).forward(),
            lambda reply, tab: {"applied": True, "tab_id": tab.get("tab_id"), "route": reply.get("route"),
                                "groups_total": reply.get("groups_total")},
            timeout=timeout)

    def _left_to_reject(body: dict) -> int:
        """The frames the plan would reject."""
        return body.get("rejected") or 0

    def _preview_result(grant, upstream: dict, settings: dict, cursor: int) -> dict:
        if not upstream["ok"]:
            return upstream
        body = upstream["data"] or {}
        data = {**body, "rows": list(body.get("preview", []))}
        data.pop("preview", None)
        data.pop("effective_overrides", None)
        left = _left_to_reject(body)
        ignored = body.get("ignored_overrides") or []
        if len(ignored) > SUMMARY_PATHS:
            data["ignored_overrides"] = ignored[:SUMMARY_PATHS]
        if ignored:
            data["ignored_overrides_count"] = len(ignored)
        kinds = body.get("scope_dependent_kinds")
        notes = []
        if not left:
            notes.append("Nothing to apply")
        if kinds:
            notes.append(f"Groups of kind {', '.join(kinds)} depend on the date range / candidate pool: "
                         "cull the whole range in one call.")
        extra = {"note": " ".join(notes)} if notes else {}
        issues = bool(left) and cursor == 0
        if issues:
            extra["confirm"] = "x" * CONFIRM_WIDTH
        _fit_page(data, extra, settings)
        if issues:
            extra["confirm"] = nonce.issue(grant.nonce_owner, "auto_cull", body["plan_digest"])
        return ok(data, **extra)

    async def confirm_culling_groups(
        ctx: Context,
        groups: Annotated[list[ConfirmGroup], Field(min_length=1, max_length=20)],
        confirm: Optional[str] = None,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            bad = _validate_confirm(groups)
            if bad:
                return bad
            if any(not g.keep_paths for g in groups):
                digest = _confirm_digest(groups)
                if not nonce.check(grant.nonce_owner, "confirm_culling_groups", digest, confirm):
                    return err("confirmation_required",
                               "A group with empty keep_paths rejects every frame it names. Show "
                               "the user, then repeat this call with `confirm` set to this value.",
                               confirm=nonce.issue(grant.nonce_owner, "confirm_culling_groups", digest))
            rows = []
            for g in groups:
                upstream = await client.call(
                    grant, "culling.confirm", json=g.model_dump(), timeout=settings["call_timeout_s"])
                head = {"type": g.type, "group_id": g.group_id}
                if upstream["ok"]:
                    body = upstream["data"] or {}
                    rows.append({**head, "ok": True, "kept": body.get("kept"),
                                 "rejected": body.get("rejected"), "skipped": body.get("skipped")})
                elif upstream["error"] in ("forbidden_level", "library_busy", "rate_limited"):
                    stopped = upstream if not rows else ok({"rows": rows + [
                        {**head, "ok": False, "error": upstream["error"]}]})
                    return stopped
                else:
                    rows.append({**head, "ok": False, "error": upstream["error"],
                                 "message": upstream["message"]})
            return ok({"rows": rows})
        return await run_tool(ctx, "confirm_culling_groups", handler, write=True)

    add(list_culling_groups, "list_culling_groups",
        "List the darkroom's culling groups (burst, similar, scene, bracket, panorama, "
        "hdr_panorama), each with its photos and scores. A group is identified by the PAIR "
        "(type, group_id); bracket/panorama/hdr_panorama sets are kept whole by design, never "
        "culled frame by frame. The list takes no `show`: the /culling page cannot apply this query." + SEE_GROUP)
    add(culling_profiles, "culling_profiles", "The genre-aware culling presets and the default one.")
    add(suggest_culling_profile, "suggest_culling_profile",
        "Name the preset that fits an album or capture-time window. date_from/date_to accept "
        "'YYYY-MM-DD', 'YYYY-MM-DD HH:MM:SS' or the EXIF 'YYYY:MM:DD HH:MM:SS'; a date-only "
        "date_to covers the whole day.")
    add(keeper_hints, "keeper_hints",
        "Per-photo 'a better shot exists in this burst' hints for up to 100 paths. Empty when no "
        "keeper head is trained.")
    add(auto_cull, "auto_cull",
        "Auto-cull a scope under a keeper budget. With neither `strictness` nor `profile` and a Facet tab "
        "open, the plan uses that tab's /culling defaults (the slider's stored strictness, 100 when never "
        "moved, plus the stored profile when set, which supplies its other settings such as the minimum keepers per group), reported as `knobs_from_tab`; with no tab the server default (50) "
        "applies. Showing a plan moves the slider to the plan's strictness. The apply reads the tab once: it is "
        "refused (confirmation_required) when the plan pinned on the /culling page is no longer the one the "
        "preview was shown as or against (the user re-planned with the slider), so preview again. "
        "dry_run=true (default) only previews the split "
        "and returns a `confirm` value; show the user the counts, then call again with "
        "dry_run=false and that `confirm` to reject the planned frames. The apply leaves out the photos "
        "the user rated, favourited or rejected since the preview (`skipped_user_changed`, with "
        "`skipped_user_changed_count`) and is refused when the plan changed for any other reason. The preview is paged by whole groups: repeat the call "
        "with `cursor` set to the result's `next_cursor` and `plan_digest` set to the cursor-0 "
        "page's `plan_digest` (required when cursor > 0; a changed plan is refused, restart from "
        "cursor 0) until next_cursor is null; a page is cut by whole groups to fit the result size (a single group too big for it has its "
        "path lists clipped: `paths_clipped`, with `keep_count` / `reject_count`). "
        "`kept` and `rejected` cover the full plan, "
        "and ONE confirm, issued on the cursor-0 page only and only when something is left to reject, covers all "
        "of it (valid 300 s, single use). The apply returns counts only. The user's own Keep/Remove flips "
        "are not read back: to honour them pass explicit lists (up to 1000 each; `ui_get_context` `culling.changed` "
        "gives the paths), which replace the plan's decisions, never merged: paths outside the plan come back as "
        "`ignored_overrides` (the first 20, "
        "with `ignored_overrides_count`), and removing a frame of a bracket or panorama, emptying a group of "
        "keepers or listing a path in both is refused. Explicit lists must be the SAME on the dry run that "
        "issues the confirm and on the apply. "
        "Brackets and panoramas are kept whole. date_from/date_to "
        "accept 'YYYY-MM-DD' (date_to covers the whole day) or 'YYYY-MM-DD HH:MM:SS'. Cull a whole "
        "range in ONE call: do not split it by month, because similar and scene groups depend on "
        "the date range (see `scope_dependent_kinds` in the result)." + AUTO_CULL_SHOW + SEE_GROUP,
        DESTRUCTIVE_ANNOTATIONS)
    add(confirm_culling_groups, "confirm_culling_groups",
        "Confirm up to 20 groups, each keyed by (type, group_id) with the group's `paths` and the "
        "`keep_paths` to keep; the rest are rejected. bracket/panorama/hdr_panorama groups must "
        "keep every path. A group with empty keep_paths (reject all) first answers "
        "confirmation_required with a `confirm` value to repeat the call with." + SEE_GROUP,
        DESTRUCTIVE_ANNOTATIONS)
