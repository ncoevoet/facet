"""Read tools: search, detail, similarity, filter vocabularies, people, albums, stats.

Every tool reaches data through ``InternalClient`` (the existing ``/api`` routes),
declares ``readOnlyHint`` and carries the untrusted-content meta (captions, tags,
file names, paths and album/person names can all hold a prompt injection).
"""

import operator
from typing import Annotated, Any, Literal, Optional

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import CallToolResult
from pydantic import BaseModel, ConfigDict, Field, create_model

from api.agent import actions
from api.agent import show as relay
from api.agent.images import MAX_SHEET_PATHS, contact_sheet_result, thumbnail_result
from api.agent.bridge import TabRegistry
from api.agent.internal_client import InternalClient, err, ok
from api.agent.runtime import run_tool
from api.agent.target import SELECTION, resolve_selected_paths, with_target
from api.agent.tools_common import (
    MCP_FILTER_KEYS, READ_ANNOTATIONS, TOOL_LEVELS, FilterValue, SortColumn, hidden_tools, register_tool,
    unavailable_tools,
)
from api.agent.ui_tools import TAB_ID_PATTERN
from api.models.gallery import query_value
from api.routers.face_matches import FACE_SCAN_TIMEOUT_S
from api.config import CORRELATION_X_AXES, CORRELATION_Y_METRICS, VIEWER_CONFIG
from api.db_helpers import PHOTO_BASE_COLS, PHOTO_OPTIONAL_COLS, to_day_granularity

HIDE_DEFAULT_KEYS = ("hide_blinks", "hide_bursts", "hide_duplicates", "hide_brackets", "hide_panoramas",
                     "hide_rejected")

_FILTER_FIELDS: dict[str, Any] = {
    key: (Optional[FilterValue], Field(
        default=None, description=f"Gallery filter `{key}` (same meaning as in the viewer)."))
    for key in MCP_FILTER_KEYS
}
# Rejected-only is a boolean flag; reject unrelated values rather than silently
# treating them as the normal listing. An explicit review status takes precedence.
_FILTER_FIELDS["show_rejected"] = (Optional[bool], Field(
    default=None, description="true lists ONLY the rejected photos; false or omitted is the "
    "normal listing. Other values are refused."))
_FILTER_FIELDS["review_status"] = (Optional[Literal["", "undecided", "kept", "rejected"]], Field(
    default=None, description="Review decision: undecided, kept, or rejected; empty clears the filter."))
SearchFilters = create_model("SearchFilters", __config__=ConfigDict(extra="forbid"), **_FILTER_FIELDS)

# Every column the gallery routes serve is requestable, except the BLOBs (a guard: none is
# listed today) and the two keys whose trimmed form is already in every row.
BLOB_COLUMNS = frozenset({"thumbnail", "clip_embedding", "caption_embedding", "face_embedding",
                          "histogram_data"})
COMPACT_KEYS = ("path", "filename", "date_taken", "aggregate", "aesthetic", "comp_score",
                "face_quality", "category", "face_count", "is_favorite", "star_rating",
                "is_rejected", "sequence_kind", "is_monochrome", "camera_model", "lens_model",
                "focal_length", "f_stop", "shutter_speed", "iso")
TRIMMED_KEYS = ("tags", "caption")
# ``learned_score`` is served only under sort=learned_score (null otherwise).
PHOTO_FIELDS = tuple(dict.fromkeys(
    c for c in (*PHOTO_BASE_COLS, *PHOTO_OPTIONAL_COLS, "learned_score")
    if c not in COMPACT_KEYS and c not in TRIMMED_KEYS and c not in BLOB_COLUMNS))
# Row keys are accepted as no-ops so an agent that lists them is not refused.
ACCEPTED_FIELDS = (*PHOTO_FIELDS, *COMPACT_KEYS, *TRIMMED_KEYS)
MetricField: Any = operator.getitem(Literal, ACCEPTED_FIELDS)
SHOW_DESCRIPTION = ("true (default): after a successful first-page search, the same query is applied to "
                    "the user's open Facet tab. false only for intermediate probes and counts.")
SHOW_LIST_DESCRIPTION = ("false (default): true opens the page in the user's open Facet tab with exactly this "
                         "query (an empty query clears the page's search). Pass true when the user asks to see the list.")
READ_SELECTION_RULE = ('Or pass `target: "selection"` (and optionally `tab_id`) instead of {what}, to use exactly what '
                       "the user has selected in their open Facet tab ({how}). It reads the gallery selection from any page.")
SelectionTarget = Optional[Literal["selection"]]
FIELDS_DESCRIPTION = ("Extra photo columns to add to every row (any photo column except the image data). "
                      "Rows already carry camera, lens, aperture, shutter, ISO, focal length and "
                      "is_monochrome, so ask only for what is missing.")
# Built by subscripting at runtime: pydantic reads the enum from it, and mypy never has to
# accept a variable inside a type expression.
FIELDS_ANNOTATION: Any = operator.getitem(Annotated, (
    operator.getitem(Optional, list.__class_getitem__(MetricField)), Field(description=FIELDS_DESCRIPTION)))
SHOW_RULE = ("The result is shown automatically in the user's open Facet tab (`show`, default true): "
             "never ask whether to open or show it, and report `shown_in_tab` (applied, or the reason "
             "it was not). The last shown search is what the user sees; use show=false only for "
             "intermediate probes, counts, or a search that feeds `expected_count` of a write tool. "
             "Showing replaces the tab's filters, leaves /culling only when the user has no unconfirmed "
             "decisions there (otherwise it is refused: reason `unsaved_decisions`) and /photo, and resets a view-scope "
             "selection; on /compare it is refused (reason `comparison_open`) and while a dialog, bottom sheet or slideshow is open (reason `modal_open`). A page after the first and "
             "an empty result are not shown.")
STATS_KINDS = ("overview", "score_distribution", "top_cameras", "categories", "gear", "timeline",
               "correlations", "category_breakdown", "category_weights", "category_correlations",
               "category_overlap", "stats_settings", "timeline_dates", "timeline_years", "timeline_months")
StatsKind: Any = operator.getitem(Literal, STATS_KINDS)
_STATS_FILTERS = ("date_from", "date_to", "category")
# The parameters each kind forwards: exactly the ones its route declares.
STATS_KIND_PARAMS: dict[str, tuple[str, ...]] = {
    "overview": _STATS_FILTERS,
    "score_distribution": _STATS_FILTERS, "top_cameras": _STATS_FILTERS, "categories": _STATS_FILTERS,
    "gear": _STATS_FILTERS, "stats_settings": _STATS_FILTERS, "timeline": _STATS_FILTERS,
    "correlations": ("x", "y", "group_by", "min_samples", *_STATS_FILTERS),
    "category_breakdown": (), "category_weights": (), "category_correlations": (), "category_overlap": (),
    "timeline_dates": ("year", "month", "date_from", "date_to"),
    "timeline_years": ("date_from", "date_to"),
    "timeline_months": ("year", "date_from", "date_to"),
}
STATS_LIST_LIMIT = 50
FilterKind = Literal["cameras", "lenses", "tags", "persons", "patterns", "categories",
                     "narrative_moments", "junk_kinds", "metric_ranges"]

# The best semantic matches a filtered search narrows; the route's own cap is 200.
SEMANTIC_CANDIDATES = 200
CAPTION_LIMIT = 240
TAG_LIMIT = 5
FILTER_OPTION_LIMIT = 200


def _day_window(date_from: Optional[str], date_to: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Both bounds as ``YYYY-MM-DD`` (the stats and face routes compare whole days); ``ValueError`` on a time."""
    return (to_day_granularity(date_from) if date_from is not None else None,
            to_day_granularity(date_to) if date_to is not None else None)


def compact_photo(photo: dict, extra_fields: tuple = ()) -> dict:
    """A fixed, small key set -- never the raw ``/api/photos`` row."""
    row = {key: photo.get(key) for key in COMPACT_KEYS}
    tags = photo.get("tags_list")
    if tags is None:
        raw = photo.get("tags")
        tags = [t.strip() for t in raw.split(",")] if isinstance(raw, str) and raw else []
    row["tags"] = list(tags)[:TAG_LIMIT]
    caption = photo.get("caption")
    row["caption"] = caption[:CAPTION_LIMIT] if isinstance(caption, str) else caption
    for field in extra_fields:
        row.setdefault(field, photo.get(field))
    return row


def _list_result(upstream: dict, extra_fields: tuple = ()) -> dict:
    """Reshape a ``{photos, total, ...}`` route body into ``{rows, ...}``."""
    if not upstream["ok"]:
        return upstream
    body = upstream["data"] or {}
    data = {
        "rows": [compact_photo(p, extra_fields) for p in body.get("photos", [])],
        "total": body.get("total", 0),
    }
    for key in ("photo_total", "page", "per_page", "has_more", "hidden_summary", "query"):
        if key in body:
            data[key] = body[key]
    if body.get("error"):
        return err("upstream_error", str(body["error"]))
    return ok(data)


def _attach_similarity(rows: list[dict], similarity: dict) -> None:
    """Re-attach the search score to compact rows, which carry no score of their own."""
    for row in rows:
        row["similarity"] = similarity.get(row["path"])


def _tag_mode(result: dict, mode: str) -> None:
    shown = result.get("shown_in_tab")
    if isinstance(shown, dict) and shown.get("applied"):
        shown["mode"] = mode


async def show_list(registry: TabRegistry, result: dict, resolved, settings, tab_id: Optional[str], route: str,
                    query: dict, *, first_page: bool = True) -> None:
    """Attach ``shown_in_tab`` to a successful list: open ``route`` with exactly ``query``; never fails the list."""
    if not result["ok"]:
        return
    if not first_page:
        shown = relay.not_shown("page_not_first")
    elif not (result["data"] or {}).get("rows"):
        shown = relay.not_shown("empty_result")
    else:
        shown = await relay.show_route_in_tab(registry, resolved, settings, tab_id, route, query,
                                              timeout=settings["call_timeout_s"])
    result["shown_in_tab"] = shown
    _tag_mode(result, "route")


def _hide_defaults(filters: dict) -> dict:
    """Start from what the viewer shows: ``viewer.defaults.hide_*`` unless the caller set it."""
    defaults = VIEWER_CONFIG.get("defaults", {}) or {}
    merged = dict(filters)
    for key in HIDE_DEFAULT_KEYS:
        if key not in merged and defaults.get(key):
            merged[key] = True
    if merged.get("show_rejected") or merged.get("favorites_only"):
        merged.pop("hide_rejected", None)
    return merged


def register_read_tools(server: MCPServer, client: InternalClient, status_extra,
                        registry: TabRegistry) -> None:
    """Register the read tools on ``server``. ``status_extra`` supplies status-only fields."""

    def add(fn, name: str, description: str) -> None:
        register_tool(server, fn, name, description, READ_ANNOTATIONS)

    async def show_result(result: dict, resolved, settings, tab_id: Optional[str], *, first_page: bool,
                          patch_or_reason: Any, timeout: float) -> None:
        """Attach ``shown_in_tab`` to a successful search; a failed show never fails the search."""
        if not result["ok"]:
            return
        patch, reason = patch_or_reason
        if not first_page:
            shown = relay.not_shown("page_not_first")
        elif not (result["data"] or {}).get("total"):
            shown = relay.not_shown("empty_result")
        elif reason is not None:
            shown = reason
        else:
            shown = await relay.show_in_tab(registry, resolved, settings, tab_id, patch, timeout=timeout)
        result["shown_in_tab"] = shown

    async def search_photos(
        ctx: Context,
        filters: Optional[BaseModel] = None,
        sort: Optional[SortColumn] = None,
        sort_direction: Optional[Literal["asc", "desc"]] = None,
        page: Annotated[int, Field(ge=1)] = 1,
        per_page: Annotated[int, Field(ge=1, le=100)] = 50,
        fields: Optional[list[str]] = None,
        show: Annotated[bool, Field(description=SHOW_DESCRIPTION)] = True,
        tab_id: Optional[str] = None,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            merged = _hide_defaults(
                filters.model_dump(exclude_none=True) if filters is not None else {})
            query = {key: query_value(value) for key, value in merged.items()}
            query.update(page=page, per_page=per_page)
            if sort:
                query["sort"] = sort
            if sort_direction:
                query["sort_direction"] = sort_direction.upper()
            upstream = await client.call(grant, "search_photos", query=query,
                                         timeout=settings["call_timeout_s"])
            result = _list_result(upstream, tuple(fields or ()))
            if show:
                await show_result(result, resolved, settings, tab_id, first_page=page == 1,
                                  patch_or_reason=relay.search_patch(merged, sort, sort_direction),
                                  timeout=settings["call_timeout_s"])
            return result
        return await run_tool(ctx, "search_photos", handler)

    search_photos.__annotations__["filters"] = Optional[SearchFilters]
    search_photos.__annotations__["fields"] = FIELDS_ANNOTATION
    search_photos.__annotations__["tab_id"] = Annotated[Optional[str], Field(pattern=TAB_ID_PATTERN)]

    async def show_rows(result: dict, paths: list[str], resolved, settings, tab_id: Optional[str],
                        timeout: float) -> None:
        """Pin exactly ``paths`` (the rows the tool returned, in order) as the user's list.

        The tab's own semantic view is hide-filtered and sort-ordered, so it would differ from the rows.
        """
        if paths:
            result["shown_in_tab"] = await relay.show_paths_in_tab(
                registry, resolved, settings, tab_id, paths, timeout=timeout)
        else:
            result["shown_in_tab"] = relay.not_shown("empty_result")
        _tag_mode(result, "paths")

    async def semantic_search(
        ctx: Context,
        query: Annotated[str, Field(min_length=1, max_length=500)],
        limit: Annotated[int, Field(ge=1, le=50)] = 20,
        threshold: Annotated[Optional[float], Field(ge=0.0, le=1.0)] = None,
        scope: Optional[Literal["text"]] = None,
        filters: Optional[BaseModel] = None,
        fields: Optional[list[str]] = None,
        show: Annotated[bool, Field(description=SHOW_DESCRIPTION)] = True,
        tab_id: Optional[str] = None,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            timeout = settings["semantic_timeout_s"]
            upstream = await client.call(
                grant, "semantic_search",
                query={"q": query, "limit": SEMANTIC_CANDIDATES if filters is not None else limit,
                       "threshold": threshold, "scope": scope}, timeout=timeout)
            if not upstream["ok"]:
                return upstream
            body = upstream["data"] or {}
            if body.get("error"):
                return err("upstream_error", str(body["error"]))
            hits = body.get("photos", [])
            similarity = {p["path"]: p.get("similarity") for p in hits}
            candidates = len(hits)
            if filters is None:
                result = _list_result(upstream, tuple(fields or ()))
                _attach_similarity(result["data"]["rows"], similarity)
                if show:
                    await show_rows(result, [p["path"] for p in hits], resolved, settings, tab_id, timeout)
                return result
            kept = hits
            if hits:
                narrowed = await client.call(
                    grant, "photos_by_paths",
                    json={"paths": [p["path"] for p in hits],
                          "filters": {key: query_value(value)
                                      for key, value in filters.model_dump(exclude_none=True).items()}},
                    timeout=timeout)
                if not narrowed["ok"]:
                    return narrowed
                kept = (narrowed["data"] or {}).get("photos", [])
            # by_paths answers in the requested order, which is the search's similarity order.
            cut = kept[:limit]
            result = _list_result(ok({"photos": cut, "total": len(kept), "query": body.get("query", query)}),
                                  tuple(fields or ()))
            _attach_similarity(result["data"]["rows"], similarity)
            result["data"]["candidates"] = candidates
            result["data"]["filtered_out"] = candidates - len(kept)
            if candidates >= SEMANTIC_CANDIDATES and len(kept) < limit:
                result["data"]["note"] = (
                    f"Only the {SEMANTIC_CANDIDATES} best semantic matches were filtered; more matching "
                    "photos may exist beyond them. Loosen the query or the filters.")
            if show:
                await show_rows(result, [row["path"] for row in cut], resolved, settings, tab_id, timeout)
            return result
        return await run_tool(ctx, "semantic_search", handler)

    semantic_search.__annotations__["filters"] = Optional[SearchFilters]
    semantic_search.__annotations__["fields"] = FIELDS_ANNOTATION
    semantic_search.__annotations__["tab_id"] = Annotated[Optional[str], Field(pattern=TAB_ID_PATTERN)]

    async def selected_or_given(grant, resolved, settings, given: Optional[list[str]], target: SelectionTarget,
                                tab_id: Optional[str], *, cap: int, exact_one: bool,
                                ) -> tuple[Optional[dict], list[str], Optional[dict]]:
        """``(error, paths, target_meta)``: exactly one of the given paths or the tab's selection."""
        if (given is None) == (target is None):
            return err("invalid_input", f"Give exactly one of the path(s) or `target: \"{SELECTION}\"`"), [], None
        if target is None:
            return None, list(given or ()), None
        return await resolve_selected_paths(client, grant, registry, resolved, settings, tab_id=tab_id,
                                            cap=cap, exact_one=exact_one)

    async def get_photo(
        ctx: Context, path: Annotated[Optional[str], Field(min_length=1)] = None,
        target: SelectionTarget = None, tab_id: Optional[str] = None,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            refusal, chosen, meta = await selected_or_given(
                grant, resolved, settings, None if path is None else [path], target, tab_id,
                cap=1, exact_one=True)
            if refusal is not None:
                return refusal
            upstream = await client.call(grant, "get_photo", query={"path": chosen[0]},
                                         timeout=settings["call_timeout_s"])
            if upstream["ok"] and isinstance(upstream["data"], dict):
                upstream["data"].pop("histogram_data", None)
            return with_target(upstream, meta)
        return await run_tool(ctx, "get_photo", handler)

    get_photo.__annotations__["tab_id"] = Annotated[Optional[str], Field(pattern=TAB_ID_PATTERN)]

    async def possible_faces(
        ctx: Context,
        person_id: Annotated[int, Field(ge=1)],
        scope: Literal["unassigned", "unnamed", "other_persons", "all"] = "unassigned",
        min_similarity: Annotated[float, Field(ge=0.0, le=1.0)] = 0.30,
        limit: Annotated[int, Field(ge=1, le=100)] = 30,
        path_prefix: Annotated[Optional[str], Field(max_length=4096)] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        show: Annotated[bool, Field(description=SHOW_DESCRIPTION)] = True,
        tab_id: Optional[str] = None,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            try:
                since, until = _day_window(date_from, date_to)
            except ValueError as ex:
                return err("invalid_input", f"date_from/date_to: {ex}")
            upstream = await client.call(
                grant, "possible_faces", path_args={"person_id": person_id},
                query={"scope": scope, "min_similarity": min_similarity, "limit": limit,
                       "path_prefix": path_prefix, "date_from": since, "date_to": until},
                timeout=FACE_SCAN_TIMEOUT_S)
            if not upstream["ok"]:
                return upstream
            body = upstream["data"] or {}
            faces = body.get("faces") or []
            result = ok({"rows": faces, "total": len(faces), "faces_scanned": body.get("faces_scanned"),
                         "candidates": body.get("candidates")})
            if show:
                paths = list(dict.fromkeys(face["photo_path"] for face in faces))
                result["shown_in_tab"] = (
                    await relay.show_paths_in_tab(registry, resolved, settings, tab_id, paths,
                                                  timeout=settings["call_timeout_s"])
                    if paths else relay.not_shown("empty_result"))
                _tag_mode(result, "paths")
            return result
        return await run_tool(ctx, "possible_faces", handler)

    possible_faces.__annotations__["tab_id"] = Annotated[Optional[str], Field(pattern=TAB_ID_PATTERN)]

    async def similar_photos(
        ctx: Context,
        path: Annotated[str, Field(min_length=1)],
        limit: Annotated[int, Field(ge=1, le=50)] = 20,
        offset: Annotated[int, Field(ge=0)] = 0,
        mode: Literal["visual", "color"] = "visual",
        min_similarity: Annotated[Optional[float], Field(ge=0.0, le=1.0)] = None,
        fields: Optional[list[str]] = None,
        show: Annotated[bool, Field(description=SHOW_DESCRIPTION)] = True,
        tab_id: Optional[str] = None,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            upstream = await client.call(
                grant, "similar_photos", path_args={"path": path},
                query={"limit": limit, "offset": offset, "mode": mode, "full": 1,
                       "min_similarity": min_similarity}, timeout=settings["call_timeout_s"])
            if not upstream["ok"]:
                return upstream
            body = upstream["data"] or {}
            photos = body.get("similar") or []
            extra = tuple(fields or ())
            result = ok({"rows": [compact_photo(p, extra) | {"similarity": p.get("similarity")} for p in photos],
                         "total": body.get("total", len(photos)), "offset": offset,
                         "has_more": bool(body.get("has_more"))})
            if show:
                await show_result(result, resolved, settings, tab_id, first_page=offset == 0,
                                  patch_or_reason=(relay.similar_patch(path, mode, min_similarity), None),
                                  timeout=settings["call_timeout_s"])
            return result
        return await run_tool(ctx, "similar_photos", handler)

    similar_photos.__annotations__["fields"] = FIELDS_ANNOTATION
    similar_photos.__annotations__["tab_id"] = Annotated[Optional[str], Field(pattern=TAB_ID_PATTERN)]

    async def filter_options(
        ctx: Context,
        kind: FilterKind,
        query: Annotated[Optional[str], Field(max_length=100)] = None,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            upstream = await client.call(grant, f"filter_options.{kind}",
                                         timeout=settings["call_timeout_s"])
            if not upstream["ok"]:
                return upstream
            data, truncated = _trim_options(upstream["data"], query)
            return ok(data, **({"truncated": True} if truncated else {}))
        return await run_tool(ctx, "filter_options", handler)

    async def list_persons(
        ctx: Context,
        query: Annotated[Optional[str], Field(max_length=100)] = None,
        limit: Annotated[int, Field(ge=1, le=100)] = 48,
        show: Annotated[bool, Field(description=SHOW_LIST_DESCRIPTION)] = False,
        tab_id: Optional[str] = None,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            upstream = await client.call(grant, "list_persons", query={
                "search": query or "", "per_page": limit}, timeout=settings["call_timeout_s"])
            if not upstream["ok"]:
                return upstream
            body = upstream["data"] or {}
            rows = [{k: p.get(k) for k in ("id", "name", "face_count")}
                    for p in body.get("persons", [])]
            result = ok({"rows": rows, "total": body.get("total", len(rows))})
            if show:
                await show_list(registry, result, resolved, settings, tab_id, "/persons", {"search": query or ""})
            return result
        return await run_tool(ctx, "list_persons", handler)

    list_persons.__annotations__["tab_id"] = Annotated[Optional[str], Field(pattern=TAB_ID_PATTERN)]

    async def list_albums(
        ctx: Context, query: Annotated[Optional[str], Field(max_length=100)] = None,
        show: Annotated[bool, Field(description=SHOW_LIST_DESCRIPTION)] = False,
        tab_id: Optional[str] = None,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            upstream = await client.call(grant, "list_albums", query={
                "search": query or "", "per_page": 100}, timeout=settings["call_timeout_s"])
            if not upstream["ok"]:
                return upstream
            body = upstream["data"] or {}
            rows = [{k: a.get(k) for k in ("id", "name", "description", "is_smart", "photo_count")}
                    for a in body.get("albums", [])]
            result = ok({"rows": rows, "total": body.get("total", len(rows))})
            if show:
                await show_list(registry, result, resolved, settings, tab_id, "/albums", {"search": query or ""})
            return result
        return await run_tool(ctx, "list_albums", handler)

    list_albums.__annotations__["tab_id"] = Annotated[Optional[str], Field(pattern=TAB_ID_PATTERN)]

    async def library_stats(
        ctx: Context,
        kind: str = "overview",
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        category: Optional[str] = None,
        year: Annotated[Optional[int], Field(ge=1900, le=2100)] = None,
        month: Annotated[Optional[int], Field(ge=1, le=12)] = None,
        x: Optional[str] = None,
        y: Optional[str] = None,
        group_by: Optional[str] = None,
        min_samples: Annotated[Optional[int], Field(ge=1)] = None,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            timeout = settings["call_timeout_s"]
            given = {"date_from": date_from, "date_to": date_to, "category": category, "year": year,
                     "month": month, "x": x, "y": y, "group_by": group_by, "min_samples": min_samples}
            refused = [key for key, value in given.items()
                       if value is not None and key not in STATS_KIND_PARAMS[kind]]
            try:
                given["date_from"], given["date_to"] = _day_window(date_from, date_to)
            except ValueError as ex:
                return err("invalid_input", f"date_from/date_to: {ex}")
            if refused:
                return err("invalid_input", f"kind={kind} does not take {', '.join(refused)}",
                           issues=[{"field": key, "message": f"not a parameter of kind={kind}"}
                                   for key in refused])
            if kind == "overview":
                counts = await client.call(grant, "library_stats.type_counts", timeout=timeout)
                overview = await client.call(
                    grant, "library_stats.overview", timeout=timeout,
                    query={key: given[key] for key in STATS_KIND_PARAMS["overview"]})
                if not counts["ok"]:
                    return counts
                if not overview["ok"]:
                    return overview
                basis = {"total_photos": "photos you can see within date_from/date_to and category (every date and category when none is given); hide toggles ignored, rejected photos included",
                         "type_counts": "hide toggles applied (rejected, bursts ... hidden); date_from/date_to "
                                        "and category are ignored"}
                return ok({"type_counts": counts["data"], "overview": {**overview["data"], "basis": basis}})
            bad = _stats_params_error(kind, year, x, y, group_by)
            if bad is not None:
                return bad
            query = {key: given[key] for key in STATS_KIND_PARAMS[kind]}
            upstream = await client.call(grant, f"library_stats.{kind}", query=query, timeout=timeout)
            if not upstream["ok"]:
                return upstream
            return _stats_result(upstream["data"])
        return await run_tool(ctx, "library_stats", handler)

    library_stats.__annotations__["kind"] = StatsKind

    async def status(ctx: Context) -> CallToolResult:
        async def handler(grant, resolved, settings):
            return ok({
                "owner": resolved.principal,
                "level": resolved.level,
                "token_level": grant.level,
                "tool_profile": settings["tool_profile"],
                "hidden_tools": hidden_tools(resolved, settings),
                "mcp": {"enabled": settings["enabled"], "bridge": settings["bridge"]},
                **status_extra(resolved),
            })
        return await run_tool(ctx, "status", handler)

    async def available_actions(
        ctx: Context, tab_id: Annotated[Optional[str], Field(pattern=TAB_ID_PATTERN)] = None,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            tab = None
            facts = frozenset({"any"})
            if settings["bridge"]:
                context = await relay.call_tab(registry, resolved, settings, "ui_get_context", {}, tab_id)
                if context.get("ok") and isinstance(context.get("data"), dict):
                    facts, route, count, pinned = actions.facts_from_context(context["data"])
                    tab = {"tab_id": (context.get("tab") or {}).get("tab_id"), "route": route,
                           "selection_count": count, "pinned": pinned}
            rows, hidden = actions.evaluate(resolved.level, facts, TOOL_LEVELS, unavailable_tools(resolved, settings))
            return ok({"tab": tab, "level": resolved.level, "actions": rows, "hidden": hidden})
        return await run_tool(ctx, "available_actions", handler)

    async def get_thumbnail(
        ctx: Context,
        path: Annotated[Optional[str], Field(min_length=1, max_length=4096)] = None,
        size: Literal[160, 256, 384, 512, 640] = 512,
        target: SelectionTarget = None,
        tab_id: Optional[str] = None,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            refusal, chosen, meta = await selected_or_given(
                grant, resolved, settings, None if path is None else [path], target, tab_id,
                cap=1, exact_one=True)
            if refusal is not None:
                return refusal
            return with_target(await thumbnail_result(client, grant, chosen[0], size, settings), meta)
        return await run_tool(ctx, "get_thumbnail", handler)

    get_thumbnail.__annotations__["tab_id"] = Annotated[Optional[str], Field(pattern=TAB_ID_PATTERN)]

    async def contact_sheet(
        ctx: Context,
        paths: Annotated[Optional[list[Annotated[str, Field(min_length=1, max_length=4096)]]],
                         Field(min_length=1, max_length=MAX_SHEET_PATHS)] = None,
        columns: Annotated[int, Field(ge=2, le=4)] = 4,
        target: SelectionTarget = None,
        tab_id: Optional[str] = None,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            refusal, chosen, meta = await selected_or_given(
                grant, resolved, settings, paths, target, tab_id, cap=MAX_SHEET_PATHS, exact_one=False)
            if refusal is not None:
                return refusal
            return with_target(await contact_sheet_result(client, grant, chosen, columns, settings), meta)
        return await run_tool(ctx, "contact_sheet", handler)

    contact_sheet.__annotations__["tab_id"] = Annotated[Optional[str], Field(pattern=TAB_ID_PATTERN)]

    add(search_photos, "search_photos",
        "Search and filter the photo library like the viewer gallery. Applies the viewer's "
        "stack collapse: `total` counts displayed items; `photo_total` counts matching originals, including "
        "folded stack members. Use `photo_total` as a filter-scoped write's expected_count. Exact pinned lists "
        "keep the requested photos. Applies the viewer's "
        "default hide toggles (bursts, duplicates, brackets, panoramas, blinks) unless the filter "
        "sets them, and reports `hidden_summary` so you can say how many more are hidden. " + SHOW_RULE +
        " Filters the gallery sidebar has no field for (exclude_tags, require_tags, is_silhouette, "
        "junk_kind, narrative_moment, min_rating, min_aggregate) make the show report "
        "`unsupported_filters`: drop those keys to show the search, or tell the user. `fields` adds "
        "any photo column to the rows. `show_rejected` can be shown in the tab; an explicit "
        "`review_status` determines the review decision. Combining `show_rejected` with `favorites_only` "
        "still returns their intersection, but `shown_in_tab` reports `invalid_combination` and leaves "
        "the tab unchanged because its controls cannot represent both.")
    add(semantic_search, "semantic_search",
        "Find photos by meaning (text-to-image) or, with scope='text', by words in captions/OCR. "
        "Rows carry their `similarity`. `filters` (the `search_photos` filters, no hide defaults) narrows "
        "the best 200 matches and keeps similarity order; the result adds `candidates` and "
        "`filtered_out`, and a `note` when the 200 limit may have hidden more. "
        + SHOW_RULE + " The exact rows returned (similarity order, at most `limit`) are shown as an "
        "assistant-chosen list (`shown_in_tab.mode` 'paths'), with or without `filters`.")
    add(get_photo, "get_photo",
        "Full detail of one photo by its path. " + READ_SELECTION_RULE.format(
            what="`path`", how="exactly one photo must be selected"))
    add(get_thumbnail, "get_thumbnail",
        "Look at one photo: its thumbnail as an image (size 160 to 640, default 512; a smaller size is "
        "used when the JPEG would exceed the byte cap). A photo the token cannot see answers not_found. "
        + READ_SELECTION_RULE.format(what="`path`", how="exactly one photo must be selected"))
    add(contact_sheet, "contact_sheet",
        "Look at up to 16 photos at once as one numbered grid image (columns 2 to 4, longest edge 1024). "
        "The text part's `legend` maps each tile number to its path, in request order; `unavailable` "
        "lists tiles left blank because the photo is missing or not visible. "
        + READ_SELECTION_RULE.format(what="`paths`", how=f"at most {MAX_SHEET_PATHS} photos"))
    add(possible_faces, "possible_faces",
        "Faces that look like one recognised person (cosine similarity to the person's centroid, best "
        "first; same embedding model only). `scope` is unassigned (default), unnamed (faces in no group or in a "
        "group nobody has named), other_persons or all; `min_similarity` defaults to 0.30; `limit` max 100. "
        "Rows carry face_id, photo_path, person_id/person_name (current owner), owner (ungrouped, "
        "unnamed_group or named), similarity and distance. A scan over 192000 faces is "
        "refused with too_large: narrow it with scope, path_prefix, date_from or date_to. "
        "`candidates` is the count of faces in scope you can see, before the embedding-dimension "
        "check; `faces_scanned` is the number of rows actually scored. "
        + SHOW_RULE + " The distinct photos are shown as an assistant-chosen list. A person with no "
        "centroid yet answers invalid_input.")
    add(similar_photos, "similar_photos",
        "Photos similar to one photo (visual or colour); pass `offset` to page when has_more is true. "
        "`min_similarity` (0 to 1) sets the floor the route and the shown view both use. " + SHOW_RULE)
    add(filter_options, "filter_options",
        "List the vocabulary a filter accepts (cameras, lenses, tags, persons, patterns, "
        "categories, narrative_moments, junk_kinds, metric_ranges).")
    add(list_persons, "list_persons",
        "Recognised people, optionally filtered by name. With show=true (default false) the /persons page opens "
        "in the user's tab with exactly this name search (empty clears it); `shown_in_tab` reports the outcome.")
    add(list_albums, "list_albums",
        "Albums the token's owner can see. With show=true (default false) the /albums page opens in the user's "
        "tab with exactly this name search (empty clears it); `shown_in_tab` reports the outcome. To open one "
        "album, use ui_open_album.")
    add(library_stats, "library_stats",
        "Library statistics, read-only. kind='overview' (default) is the size, type counts and score "
        "overview; the other kinds are the Stats page's data: " + ", ".join(STATS_KINDS[1:]) + ". "
        "`timeline_dates` and `timeline_months` need `year`; `correlations` takes x, y (comma list), "
        "group_by and min_samples. Long lists are cut and `truncated` is set.")
    add(status, "status", "Who this token is, its effective level and the server flags.")
    add(available_actions, "available_actions",
        "The jobs that apply to the user's open tab and this token right now, each with its tools "
        "(`required_level`, and `allowed: false` when the tab is not in the state the tool needs, "
        "with a `hint`). Tools above this token's level are not listed; `hidden` counts the jobs "
        "that do not apply to the tab's page. Without a tab only the page-independent jobs are listed.")


def _trim_options(data: Any, query: Optional[str]) -> tuple[Any, bool]:
    """Filter list values by ``query`` and cap each at 200; report whether any were cut."""
    needle = (query or "").lower()
    cut = False

    def trim(items: list) -> list:
        nonlocal cut
        kept = [item for item in items if not needle or needle in str(item).lower()]
        if len(kept) > FILTER_OPTION_LIMIT:
            cut = True
        return kept[:FILTER_OPTION_LIMIT]

    if isinstance(data, list):
        return trim(data), cut
    if isinstance(data, dict):
        return {key: trim(value) if isinstance(value, list) else value
                for key, value in data.items()}, cut
    return data, cut


def _stats_params_error(kind: str, year: Optional[int], x: Optional[str], y: Optional[str],
                        group_by: Optional[str]) -> Optional[dict]:
    """``invalid_input`` for a kind whose required parameter is missing or unknown."""
    if kind in ("timeline_dates", "timeline_months") and year is None:
        return err("invalid_input", f"kind={kind} needs `year`",
                   issues=[{"field": "year", "message": "required for this kind"}])
    if kind == "correlations":
        if x is not None and x not in CORRELATION_X_AXES:
            return err("invalid_input", f"x must be one of {', '.join(sorted(CORRELATION_X_AXES))}")
        wrong = [m for m in (y or "").split(",") if m and m not in CORRELATION_Y_METRICS]
        if wrong:
            return err("invalid_input", f"y has unknown metrics: {', '.join(wrong)}")
        if group_by and group_by not in CORRELATION_X_AXES:
            return err("invalid_input", f"group_by must be one of {', '.join(sorted(CORRELATION_X_AXES))}")
    return None


def _cut_lists(value: Any, depth: int = 0) -> tuple[Any, bool]:
    """Cap every list at ``STATS_LIST_LIMIT`` (recursively); report whether any was cut."""
    cut = False
    if isinstance(value, list):
        cut = len(value) > STATS_LIST_LIMIT
        out = []
        for item in value[:STATS_LIST_LIMIT]:
            trimmed, inner = _cut_lists(item, depth + 1) if depth < 6 else (item, False)
            out.append(trimmed)
            cut = cut or inner
        return out, cut
    if isinstance(value, dict) and depth < 6:
        out_dict = {}
        for key, item in value.items():
            out_dict[key], inner = _cut_lists(item, depth + 1)
            cut = cut or inner
        return out_dict, cut
    return value, False


def _stats_result(data: Any) -> dict:
    """A list body becomes ``rows`` (the row cap applies); a dict body has its lists cut."""
    if isinstance(data, list):
        return ok({"rows": data, "total": len(data)})
    trimmed, cut = _cut_lists(data)
    return ok(trimmed, **({"truncated": True} if cut else {}))
