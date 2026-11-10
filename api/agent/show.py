"""Show a search in the user's open tab: the one relay every searching read tool shares.

A search tool applies its own query to the tab with ``replace`` semantics, so the user
sees what the agent found without being asked. The relay never fails the search: a
missing tab, an outdated one, a refusal or a timeout is reported in ``shown_in_tab``.

The mappers are pure (query in, patch out) so a test pins the exact frame; the relay
validates the patch through the same model as ``ui_set_gallery_filters``.
"""

import logging
from typing import Any, Callable, Optional, get_args

from pydantic import ValidationError

from api.agent.bridge import TabRegistry
from api.agent.internal_client import err
from api.agent.tokens import ResolvedGrant
from api.agent.tools_common import SortColumn
from api.agent.tools_ui import BRIDGE_DISABLED
from api.agent.ui_tools import (
    TAB_UNSUPPORTED_FILTER_KEYS, UiNavigate, UiSetGalleryFilters, UiShowPhotos, conflicting_rejected_filters,
)
from api.config import VIEWER_CONFIG

logger = logging.getLogger(__name__)

# The route's own per-mode floor when the caller gives none (``_MODE_DEFAULT_MIN_SIM``); the
# tab's own default ('70') differs, so the show always sends the value the route used.
SIMILAR_DEFAULT_MIN = {"visual": 0.40, "color": 0.40, "person": 0.0}


def not_shown(reason: str, **extra: Any) -> dict:
    return {"applied": False, "reason": reason, **extra}


def effective_sort(sort: Optional[str], sort_direction: Optional[str]) -> dict:
    """The sort the upstream query used: the caller's, else the viewer's configured default."""
    defaults = VIEWER_CONFIG.get("defaults", {}) or {}
    valid = get_args(SortColumn)
    column = sort or defaults.get("sort")
    direction = sort_direction or defaults.get("sort_direction")
    return {"sort": column if column in valid else "aggregate",
            "sort_direction": str(direction).lower() if str(direction).lower() in ("asc", "desc") else "desc"}


def _is_effective(key: str, value: Any) -> bool:
    """Whether the gallery route acts on ``value``; a value it ignores is the normal listing."""
    if key in ("show_rejected", "is_silhouette"):
        return value is True
    if key in ("exclude_tags", "require_tags"):
        return bool(str(value).strip())
    if key == "min_rating":
        try:
            return 1 <= int(value) <= 5
        except (TypeError, ValueError):
            return False
    return True


def search_patch(filters: dict, sort: Optional[str], sort_direction: Optional[str]) -> tuple[dict, Optional[dict]]:
    """``(patch, None)`` for a search the tab can express, else ``({}, <not_shown reason>)``."""
    effective = {k: v for k, v in filters.items() if v is not None and _is_effective(k, v)}
    keys = sorted(k for k in effective if k in TAB_UNSUPPORTED_FILTER_KEYS)
    if keys:
        return {}, not_shown("unsupported_filters", keys=keys)
    if conflicting_rejected_filters(effective):
        return {}, not_shown("invalid_combination", keys=["favorites_only", "show_rejected"])
    if "type" in effective and "category" in effective:
        return {}, not_shown("invalid_combination", keys=["type", "category"])
    return {**effective, **effective_sort(sort, sort_direction)}, None


def similar_patch(path: str, mode: str, min_similarity: Optional[float],
                  sort: Optional[str] = None, sort_direction: Optional[str] = None) -> dict:
    floor = min_similarity if min_similarity is not None else SIMILAR_DEFAULT_MIN.get(mode, 0.40)
    return {"similar_to": path, "similarity_mode": mode, "min_similarity": floor,
            "semantic_query": None, "semantic_threshold": None, **effective_sort(sort, sort_direction)}


async def call_tab(registry: TabRegistry, resolved: ResolvedGrant, settings: dict, tool: str,
                   payload: dict, tab_id: Optional[str], *, timeout: Optional[float] = None) -> dict:
    """Ask the user's tab to run ``tool``; the bridge's envelope, never a raise.

    The one tab relay every server-side tool shares (show, context, selection reads), with
    the same level and ``max_level`` reach rules as a ``ui_*`` call.
    """
    if not settings["bridge"]:
        return err("no_tab", BRIDGE_DISABLED)
    try:
        return await registry.call(
            resolved.principal, tool, payload, level=resolved.level, tab_id=tab_id,
            timeout=settings["call_timeout_s"] if timeout is None else timeout,
            max_level=resolved.minted_level)
    except Exception:
        logger.exception("Tab call %s crashed", tool)
        return err("upstream_error", "The tab call failed unexpectedly", crashed=True)


def tab_route(registry: TabRegistry, resolved: ResolvedGrant, tab_id: Optional[str]) -> Optional[str]:
    """The path the picked tab last reported (the registry tracks each tab's route), else None without a tab.

    No frame is sent: the route is the one the tab reported at its last event.
    """
    tabs = registry.tabs_for(resolved.principal, resolved.level, resolved.minted_level)
    conn, _ = registry.pick(tabs, tab_id)
    return None if conn is None else (conn.route.split("?")[0].split("#")[0].rstrip("/") or "/")


def comparison_open(registry: TabRegistry, resolved: ResolvedGrant, tab_id: Optional[str]) -> bool:
    """Whether a show would interrupt either comparison workspace.

    A show there would navigate away from a pair the user is judging, so it is skipped.
    """
    return tab_route(registry, resolved, tab_id) in {"/compare", "/photo-compare"}


async def _show(registry: TabRegistry, resolved: ResolvedGrant, settings: dict, tab_id: Optional[str],
                tool: str, label: str, build_args: Callable[[], dict], on_ok: Callable[[dict, dict], dict],
                *, timeout: float) -> dict:
    """The guards and refusal mapping every show shares; ``on_ok(data, tab)`` shapes the success."""
    if not settings["bridge"]:
        return not_shown("bridge_disabled")
    if comparison_open(registry, resolved, tab_id):
        return not_shown("comparison_open", note="The user is on the comparison page; nothing was changed.")
    try:
        args = build_args()
    except ValidationError as ex:
        logger.error("%s refused by the contract (%d issues)", label, ex.error_count())
        return not_shown("error")
    envelope = await call_tab(registry, resolved, settings, tool, args, tab_id, timeout=timeout)
    if envelope.get("crashed"):
        return not_shown("error")
    if envelope.get("ok"):
        return on_ok(envelope.get("data") or {}, envelope.get("tab") or {})
    code = str(envelope.get("error") or "error")
    if code == "tab_timeout":
        return not_shown(code, note="The tab may still apply it.")
    return not_shown("forbidden" if code == "forbidden_level" else code)


async def show_in_tab(registry: TabRegistry, resolved: ResolvedGrant, settings: dict,
                      tab_id: Optional[str], patch: dict, *, timeout: float) -> dict:
    """Apply ``patch`` (replace semantics) to the user's tab; describe the outcome, never raise."""
    return await _show(
        registry, resolved, settings, tab_id, "ui_set_gallery_filters", "Show patch",
        lambda: UiSetGalleryFilters.model_validate({"patch": patch, "replace": True}).forward(),
        lambda data, tab: {"applied": True, "tab_id": tab.get("tab_id"), "keys": data.get("applied"),
                           "total": data.get("total")},
        timeout=timeout)


async def show_paths_in_tab(registry: TabRegistry, resolved: ResolvedGrant, settings: dict,
                            tab_id: Optional[str], paths: list[str], *, timeout: float) -> dict:
    """Pin exactly ``paths`` (in order) as the user's gallery list; describe the outcome, never raise."""
    return await _show(
        registry, resolved, settings, tab_id, "ui_show_photos", "Show paths",
        lambda: UiShowPhotos.model_validate({"paths": paths}).forward(),
        lambda data, tab: {"applied": True, "tab_id": tab.get("tab_id"), "keys": None,
                           "total": data.get("total"), "missing": data.get("missing") or []},
        timeout=timeout)


async def show_route_in_tab(registry: TabRegistry, resolved: ResolvedGrant, settings: dict,
                            tab_id: Optional[str], route: str, query: dict, *, timeout: float) -> dict:
    """Open ``route`` with exactly ``query`` in the user's tab; describe the outcome, never raise.

    The page treats every query key as authoritative, so a key sent empty clears that page filter.
    """
    return await _show(
        registry, resolved, settings, tab_id, "ui_navigate", "Show route",
        lambda: UiNavigate.model_validate({"route": route, "query": query}).forward(),
        lambda data, tab: {"applied": True, "tab_id": tab.get("tab_id"), "route": route,
                           "keys": sorted(query)},
        timeout=timeout)
