"""Live UI updates: which agent writes change photos, and the ``changed`` frame a tab refreshes from.

``InternalClient`` is the single choke point every agent write passes through, so it hands each
successful (or outcome-unknown) write route call to a sink. This module classifies the route, extracts
the photo paths the request named, and builds the frame ``{type: "changed", tool, paths, count}``.
``paths`` is ``None`` when the request did not name its photos (a filter-scoped write, a sibling-widened
move, a face assignment) or named more than ``MAX_LIVE_PATHS``: the tab then reloads its view.
``culling.auto`` frames also carry ``show_paths`` (the photos the apply rejected, for "Show photos"; ``None`` when
there are none or above the cap), and every frame written inside an agent tool call carries ``agent_tool`` and
``call_id`` naming that call.

The browser's own in-page agent route does not broadcast to its caller (the caller IS the tab and applies
the response); see ``api.agent.inpage``.
"""

import asyncio
import logging
from contextvars import ContextVar
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

MAX_LIVE_PATHS = 200
PATH_KEYS = ("photo_paths", "paths", "photo_path", "path")
# Response fields that count the photos a write changed, first match wins.
COUNT_KEYS = ("count", "affected", "moved", "trashed", "copied", "rejected", "cleared",
              "assigned_count")

# Every ``write=True`` route in ROUTE_ALLOWLIST and CULLING_ROUTES sits in exactly one of the two sets
# (tests/test_agent_live_updates.py walks both tables), so a new write route fails CI until classified.
PHOTO_EFFECT_TOOLS = frozenset({
    "create_photo_stack", "update_photo_stack", "unstack_photos", "undo_photo_stack",
    "set_rating", "toggle_favorite", "toggle_rejected", "batch_favorite", "batch_reject", "batch_rating",
    "batch_manual_tags", "clear_junk", "set_caption", "album_add_photos", "album_remove_photos",
    "cull_apply", "delete_photos", "override_sequence", "clear_sequence_override", "override_category",
    "clear_category_override", "assign_faces", "culling.auto", "culling.confirm",
})
NO_PHOTO_EFFECT_TOOLS = frozenset({"create_album", "export_metadata", "scan_start", "update_weights", "restore_weights",
                                   "recompute_start",
                                   # A new file plus a scan of it, like scan_start: no existing row changes.
                                   "import_ai_edit"})

# ``(principal, tool, request body, response body)``, sync or async.
WriteSink = Callable[[str, str, Any, Any], Any]

# Takes precedence over the client's own sink for the current context (the in-page route collects here).
LIVE_SINK_OVERRIDE: ContextVar[Optional[WriteSink]] = ContextVar("facet_live_sink_override", default=None)

# ``(assistant tool name, call id)`` of the MCP tool call running in this context, set by ``run_tool``.
# Every frame the call's writes produce carries both, so a tab can fold them into one activity entry.
CALL_CONTEXT: ContextVar[Optional[tuple[str, str]]] = ContextVar("facet_call_context", default=None)


def changed_paths(tool: str, body: Any) -> Optional[list[str]]:
    """The unique photo paths ``body`` names, in order, or ``None`` when the tab must reload instead."""
    # A row patch cannot repair representative paging/counts, and update bodies omit former members/covers.
    if tool in {"create_photo_stack", "update_photo_stack", "unstack_photos", "undo_photo_stack"}:
        return None
    if not isinstance(body, dict) or body.get("include_sequence_siblings") is True:
        return None
    seen: dict[str, None] = {}
    named = False
    for key in PATH_KEYS:
        value = body.get(key)
        if isinstance(value, str):
            named = True
            seen.setdefault(value)
        elif isinstance(value, list):
            named = True
            for item in value:
                if isinstance(item, str):
                    seen.setdefault(item)
    if not named or len(seen) > MAX_LIVE_PATHS:
        return None
    return list(seen)


def _response_count(response: Any) -> Optional[int]:
    if not isinstance(response, dict):
        return None
    for key in COUNT_KEYS:
        value = response.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    deleted = response.get("deleted")
    return len(deleted) if isinstance(deleted, list) else None


def _rejects_whole_burst(tool: str, body: Any) -> bool:
    """A burst confirm rejects every visible member of the group, not just the paths the body named."""
    return tool == "culling.confirm" and isinstance(body, dict) and body.get("type") == "burst"


def frame_for(tool: str, body: Any, response: Any) -> Optional[dict]:
    """The ``changed`` frame for one write, or ``None`` when it changed no photo (or only previewed)."""
    if tool not in PHOTO_EFFECT_TOOLS:
        return None
    if isinstance(body, dict) and body.get("dry_run") is True:
        return None
    paths = None if _rejects_whole_burst(tool, body) else changed_paths(tool, body)
    count = len(paths) if paths is not None else _response_count(response)
    frame = {"type": "changed", "tool": tool, "paths": paths, "count": count}
    if tool == "culling.auto":
        # The photos an auto-cull apply rejected, for the tab's "Show photos"; ``paths`` stays null so the tab
        # still reloads (an apply also moves burst leads and reviewed marks that no row patch covers).
        shown = response.get("rejected_paths") if isinstance(response, dict) else None
        frame["show_paths"] = shown if isinstance(shown, list) and shown else None
    if (call := CALL_CONTEXT.get()) is not None:
        frame["agent_tool"], frame["call_id"] = call
    return frame


def make_emitter(registry: Any) -> WriteSink:
    """A sink that broadcasts the frame to the writing principal's tabs without awaiting the sockets."""
    tasks: set[asyncio.Task] = set()

    def emit(principal: str, tool: str, body: Any, response: Any) -> None:
        frame = frame_for(tool, body, response)
        if frame is None:
            return
        task = asyncio.get_running_loop().create_task(registry.broadcast(principal, frame))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    return emit


class WriteCollector:
    """Collects the frames of the writes one in-page call made (nothing is broadcast to the caller)."""

    def __init__(self) -> None:
        self.principal: Optional[str] = None
        self.frames: list[dict] = []

    def __call__(self, principal: str, tool: str, body: Any, response: Any) -> None:
        frame = frame_for(tool, body, response)
        if frame is not None:
            self.principal = principal
            self.frames.append(frame)

    @property
    def wrote(self) -> bool:
        return bool(self.frames)

    def paths(self) -> Optional[list[str]]:
        """The union of the named paths, or ``None`` when any write was unscoped or the union is too big."""
        union: dict[str, None] = {}
        for frame in self.frames:
            if frame["paths"] is None:
                return None
            union.update(dict.fromkeys(frame["paths"]))
        return list(union) if len(union) <= MAX_LIVE_PATHS else None

    def show_paths(self) -> Optional[list[str]]:
        """The union of the frames' ``show_paths``, or ``None`` when no frame has any or one lacks its list."""
        union: dict[str, None] = {}
        for frame in self.frames:
            if "show_paths" not in frame:
                continue
            if frame["show_paths"] is None:
                return None
            union.update(dict.fromkeys(frame["show_paths"]))
        return list(union) if union and len(union) <= MAX_LIVE_PATHS else None

    @property
    def has_show_paths(self) -> bool:
        return any("show_paths" in frame for frame in self.frames)
