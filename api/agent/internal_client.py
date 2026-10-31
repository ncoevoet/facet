"""The only way an agent tool touches data: an in-process ASGI call to an ``/api`` route.

Every tool maps to one allow-listed ``(method, path template, minimum level)``.
There is no generic "call any API" tool, so the reachable surface is exactly this
table plus ``tools_culling.CULLING_ROUTES`` (the darkroom's own, same ``RouteSpec``
shape, passed to its own ``InternalClient``) -- admin, config, scan, share, proofing, frame, webdav and login routes are
not in it. Each call therefore runs the route's own auth, validation and guards;
there is no second SQL path.

Enforcement order, per call: (1) re-resolve the token against the live config;
(2) refuse when the EFFECTIVE level is below the route's, BEFORE any upstream
call; (3) mint a 60-second JWT whose role/edition MATCH the effective level.
"""

import asyncio
import inspect
import logging
from dataclasses import dataclass
from datetime import timedelta
from types import MappingProxyType
from typing import Any, Callable, Mapping, Optional
from urllib.parse import quote

import httpx
from pydantic import ValidationError

from api.agent import tokens
from api.agent.live_updates import LIVE_SINK_OVERRIDE
from api.auth import create_access_token

logger = logging.getLogger(__name__)

INTERNAL_BASE_URL = "http://facet.internal"
INTERNAL_JWT_SECONDS = 60


@dataclass(frozen=True)
class RouteSpec:
    method: str
    template: str
    min_level: str
    write: bool = False


ROUTE_ALLOWLIST: Mapping[str, RouteSpec] = MappingProxyType({
    "search_photos": RouteSpec("GET", "/api/photos", "readonly"),
    "semantic_search": RouteSpec("GET", "/api/search", "readonly"),
    "get_photo": RouteSpec("GET", "/api/photo", "readonly"),
    "get_photo_stack": RouteSpec("GET", "/api/stacks/by-photo", "readonly"),
    "create_photo_stack": RouteSpec("POST", "/api/stacks", "edition", write=True),
    "update_photo_stack": RouteSpec("PUT", "/api/stacks/{stack_id}", "edition", write=True),
    "unstack_photos": RouteSpec("DELETE", "/api/stacks/{stack_id}", "edition", write=True),
    "undo_photo_stack": RouteSpec("POST", "/api/organization_history/{entry_id}/revert", "edition", write=True),
    "thumbnail": RouteSpec("GET", "/thumbnail", "readonly"),
    "possible_faces": RouteSpec("GET", "/api/person/{person_id}/possible_faces", "readonly"),
    "similar_photos": RouteSpec("GET", "/api/similar_photos/{path}", "readonly"),
    "filter_options.cameras": RouteSpec("GET", "/api/filter_options/cameras", "readonly"),
    "filter_options.lenses": RouteSpec("GET", "/api/filter_options/lenses", "readonly"),
    "filter_options.tags": RouteSpec("GET", "/api/filter_options/tags", "readonly"),
    "filter_options.persons": RouteSpec("GET", "/api/filter_options/persons", "readonly"),
    "filter_options.patterns": RouteSpec("GET", "/api/filter_options/patterns", "readonly"),
    "filter_options.categories": RouteSpec("GET", "/api/filter_options/categories", "readonly"),
    "filter_options.narrative_moments": RouteSpec(
        "GET", "/api/filter_options/narrative_moments", "readonly"),
    "filter_options.junk_kinds": RouteSpec("GET", "/api/filter_options/junk_kinds", "readonly"),
    "filter_options.metric_ranges": RouteSpec("GET", "/api/filter_options/metric_ranges", "readonly"),
    "list_persons": RouteSpec("GET", "/api/persons", "readonly"),
    "list_albums": RouteSpec("GET", "/api/albums", "readonly"),
    "library_stats.type_counts": RouteSpec("GET", "/api/type_counts", "readonly"),
    "library_stats.overview": RouteSpec("GET", "/api/stats/overview", "readonly"),
    "library_stats.score_distribution": RouteSpec("GET", "/api/stats/score_distribution", "readonly"),
    "library_stats.top_cameras": RouteSpec("GET", "/api/stats/top_cameras", "readonly"),
    "library_stats.categories": RouteSpec("GET", "/api/stats/categories", "readonly"),
    "library_stats.gear": RouteSpec("GET", "/api/stats/gear", "readonly"),
    "library_stats.timeline": RouteSpec("GET", "/api/stats/timeline", "readonly"),
    "library_stats.correlations": RouteSpec("GET", "/api/stats/correlations", "readonly"),
    "library_stats.category_breakdown": RouteSpec("GET", "/api/stats/categories/breakdown", "readonly"),
    "library_stats.category_weights": RouteSpec("GET", "/api/stats/categories/weights", "readonly"),
    "library_stats.category_correlations": RouteSpec("GET", "/api/stats/categories/correlations", "readonly"),
    "library_stats.category_overlap": RouteSpec("GET", "/api/stats/categories/overlap", "readonly"),
    "library_stats.stats_settings": RouteSpec("GET", "/api/stats/settings", "readonly"),
    "library_stats.timeline_dates": RouteSpec("GET", "/api/timeline/dates", "readonly"),
    "library_stats.timeline_years": RouteSpec("GET", "/api/timeline/years", "readonly"),
    "library_stats.timeline_months": RouteSpec("GET", "/api/timeline/months", "readonly"),
    "photos_count": RouteSpec("GET", "/api/photos/count", "readonly"),
    "photos_paths": RouteSpec("GET", "/api/photos/paths", "readonly"),
    "photos_by_paths": RouteSpec("POST", "/api/photos/by_paths", "readonly"),
    # Write routes. ``user`` = the per-photo require_auth routes a regular account
    # may call in the UI; ``edition`` = everything gated by require_edition.
    "set_rating": RouteSpec("POST", "/api/photo/set_rating", "user", write=True),
    "toggle_favorite": RouteSpec("POST", "/api/photo/toggle_favorite", "user", write=True),
    "toggle_rejected": RouteSpec("POST", "/api/photo/toggle_rejected", "user", write=True),
    "batch_favorite": RouteSpec("POST", "/api/photos/batch_favorite", "edition", write=True),
    "batch_reject": RouteSpec("POST", "/api/photos/batch_reject", "edition", write=True),
    "batch_rating": RouteSpec("POST", "/api/photos/batch_rating", "edition", write=True),
    "batch_manual_tags": RouteSpec("POST", "/api/photos/batch_manual_tags", "edition", write=True),
    "clear_junk": RouteSpec("POST", "/api/photo/clear_junk", "edition", write=True),
    "assign_faces": RouteSpec("POST", "/api/persons/{person_id}/assign_faces", "edition", write=True),
    "set_caption": RouteSpec("PUT", "/api/caption", "edition", write=True),
    "export_metadata": RouteSpec("POST", "/api/export/sidecars", "edition", write=True),
    "create_album": RouteSpec("POST", "/api/albums", "edition", write=True),
    "album_add_photos": RouteSpec("POST", "/api/albums/{album_id}/photos", "edition", write=True),
    "album_remove_photos": RouteSpec("DELETE", "/api/albums/{album_id}/photos", "edition", write=True),
    "cull_apply": RouteSpec("POST", "/api/cull/apply", "edition", write=True),
    "delete_photos": RouteSpec("POST", "/api/photo/delete", "edition", write=True),
    "override_sequence": RouteSpec("POST", "/api/culling-groups/override_sequence", "edition", write=True),
    "clear_sequence_override": RouteSpec("POST", "/api/culling-groups/clear_sequence_override", "edition", write=True),
    "group_faces": RouteSpec("POST", "/api/culling-group/faces", "readonly"),
    "group_subjects": RouteSpec("POST", "/api/culling-group/subjects", "readonly"),
    "override_category": RouteSpec("POST", "/api/comparison/override_category", "edition", write=True),
    "clear_category_override": RouteSpec("POST", "/api/comparison/clear_category_override", "edition", write=True),
    "scan_start": RouteSpec("POST", "/api/scan/start", "edition", write=True),
    # Read-only comparison reads. There is deliberately NO submit / reset / edit / delete entry: the answer to a
    # pair is the user's own click (tests/test_agent_comparison.py walks this table to keep it so).
    "comparison_stats": RouteSpec("GET", "/api/comparison/stats", "edition"),
    "comparison_coverage": RouteSpec("GET", "/api/comparison/coverage", "edition"),
    "scan_status": RouteSpec("GET", "/api/scan/status", "edition"),
    "scan_directories": RouteSpec("GET", "/api/scan/directories", "edition"),
    "scoring_contexts": RouteSpec("GET", "/api/config/scoring_contexts", "readonly"),
    # Scoring explanations and the weight preview: reads and a dry computation, nothing is stored. ``critique``
    # is always called with mode=rule (``POST /api/critique/vlm`` generates the VLM text and is not an agent route).
    "critique": RouteSpec("GET", "/api/critique", "readonly"),
    "category_weights": RouteSpec("GET", "/api/comparison/category_weights", "edition"),
    "preview_score": RouteSpec("POST", "/api/comparison/preview_score", "edition"),
    # Weight tuning. ``learned_weights`` / ``weight_confidence`` run the optimizer but store nothing. The two config
    # writers are the ONLY way an agent tool changes ``scoring_config.json``: each route owns CONFIG_WRITE_LOCK, the
    # automatic weight snapshot and ``write_user_config``. Deliberately absent: save_snapshot, snapshot delete,
    # /api/recalculate and /api/stats/categories/recompute (synchronous, up to 300 s).
    "learned_weights": RouteSpec("GET", "/api/comparison/learned_weights", "edition"),
    "weight_confidence": RouteSpec("GET", "/api/comparison/confidence", "edition"),
    "weight_snapshots": RouteSpec("GET", "/api/config/weight_snapshots", "edition"),
    "update_weights": RouteSpec("POST", "/api/config/update_weights", "edition", write=True),
    "restore_weights": RouteSpec("POST", "/api/config/restore_weights", "edition", write=True),
    # The background recompute: returns after the spawn, so a slow job can never read as outcome_unknown.
    "recompute_start": RouteSpec("POST", "/api/scan/recompute", "edition", write=True),
    "recompute_status": RouteSpec("GET", "/api/scan/recompute_status", "edition"),
    # The same two routes with ``dry_run=true``: nothing is written, so a timeout is a
    # plain upstream error rather than ``outcome_unknown``.
    "cull_apply.preview": RouteSpec("POST", "/api/cull/apply", "edition"),
    "delete_photos.preview": RouteSpec("POST", "/api/photo/delete", "edition"),
})


class NotAllowedError(Exception):
    """A tool name that is not in the allowlist. Raised before anything is sent."""


def ok(data: Any = None, **extra: Any) -> dict:
    return {"ok": True, "data": data, **extra}


def err(code: str, message: str, **extra: Any) -> dict:
    return {"ok": False, "error": code, "message": message, **extra}


def validation_issues(ex: ValidationError) -> list[dict]:
    """The agent-facing ``invalid_input`` issue list for a pydantic failure."""
    return [{"field": ".".join(str(part) for part in issue["loc"]), "message": issue["msg"]}
            for issue in ex.errors(include_url=False, include_context=False, include_input=False)]


CONFIG_REFUSAL_MARKERS = ("viewer.", "disabled", "not enabled")
# A 412 whose detail names a server cap ("... over the ceiling of N; narrow ...") is a size refusal.
TOO_LARGE_MARKER = "over the ceiling of"


def _is_config_refusal(message: str) -> bool:
    """A 403 whose detail names an operator's configuration ("OS-trash is disabled", "Scan feature
    not enabled", "set viewer.edition_password ...") is a switch that is off, not a missing right."""
    return any(marker in message for marker in CONFIG_REFUSAL_MARKERS)


def _status_to_error(status: int, detail: Any) -> dict:
    message = detail if isinstance(detail, str) else "Request refused"
    issues = detail if isinstance(detail, list) else None
    if status == 403 and _is_config_refusal(message):
        return err("feature_disabled", message)
    if status in (401, 403):
        return err("forbidden_level", message)
    if status == 409:
        return err("conflict", message)
    if status == 404:
        return err("not_found", message)
    if status == 413 or (status == 412 and TOO_LARGE_MARKER in message):
        return err("too_large", message)
    if status in (400, 412, 422):
        return err("invalid_input", message if issues is None else "Invalid input",
                   **({"issues": issues} if issues else {}))
    if status == 429:
        return err("rate_limited", message)
    if status == 503:
        return err("library_busy", "The library is busy; retry in a moment")
    logger.warning("Agent upstream call failed with HTTP %s: %s", status, detail)
    return err("upstream_error", "The server could not complete the request")


class InternalClient:
    """Calls allow-listed routes of ``app`` in-process, as the token's owner."""

    def __init__(self, app: Any, allowlist: Mapping[str, RouteSpec] = ROUTE_ALLOWLIST,
                 peer_ip: str = "127.0.0.1", on_write: Optional[Callable[[str, str, Any, Any], Any]] = None):
        self._app = app
        self._allowlist = allowlist
        self._peer_ip = peer_ip
        self._on_write = on_write

    async def _notify_write(self, resolved: Optional[tokens.ResolvedGrant], tool: str, body: Any,
                            response: Any) -> None:
        """Hand a write that landed (or may have) to the live-update sink; it never changes the result."""
        sink = LIVE_SINK_OVERRIDE.get() or self._on_write
        if sink is None or resolved is None:
            return
        try:
            outcome = sink(resolved.principal, tool, body, response)
            if inspect.isawaitable(outcome):
                await outcome
        except Exception as ex:
            logger.warning("Live-update sink failed for %s: %r", tool, ex)

    async def _send(self, grant: tokens.TokenGrant, tool: str, query: Optional[Mapping[str, Any]],
                    path_args: Optional[Mapping[str, Any]], json: Any, timeout: float):
        """The allow-list, level and path checks, then the in-process request.

        Returns ``(error_envelope, None, resolved)`` or ``(None, response, resolved)``; ``resolved`` is
        None until the grant resolved.
        """
        spec = self._allowlist.get(tool)
        if spec is None:
            raise NotAllowedError(tool)
        resolved = await asyncio.to_thread(grant.resolve)
        if resolved is None:
            return err("forbidden_level", "This token is no longer valid"), None, None
        if tokens.level_rank(resolved.level) < tokens.level_rank(spec.min_level):
            return err("forbidden_level",
                       f"This token's level is {resolved.level}; {tool} needs "
                       f"{tokens.effective_requirement(spec.min_level)}"), None, resolved
        for value in (path_args or {}).values():
            text = str(value)
            if not text or any(part in (".", "..") for part in text.split("/")):
                return err("invalid_input",
                           "A path argument may not be empty or contain '.' or '..' segments"), None, resolved
        headers = {}
        claims = resolved.jwt_claims()
        if claims is not None:
            jwt_token = create_access_token(claims, expires_delta=timedelta(seconds=INTERNAL_JWT_SECONDS))
            headers["Authorization"] = "Bearer " + jwt_token
        path = spec.template.format(
            **{key: quote(str(value), safe="") for key, value in (path_args or {}).items()})
        params = {k: v for k, v in (query or {}).items() if v is not None}
        transport = httpx.ASGITransport(
            app=self._app, raise_app_exceptions=False, client=(self._peer_ip, 0))
        try:
            async with httpx.AsyncClient(transport=transport, base_url=INTERNAL_BASE_URL) as client:
                response = await asyncio.wait_for(client.request(
                    spec.method, path, params=params or None, json=json, headers=headers), timeout)
        except asyncio.TimeoutError:
            return self._timed_out(spec, tool), None, resolved
        except (httpx.HTTPError, OSError) as ex:
            logger.warning("Agent upstream call %s failed: %r", tool, ex)
            return self._timed_out(spec, tool), None, resolved
        return None, response, resolved

    async def call(
        self,
        grant: tokens.TokenGrant,
        tool: str,
        *,
        query: Optional[Mapping[str, Any]] = None,
        path_args: Optional[Mapping[str, Any]] = None,
        json: Any = None,
        timeout: float = 30.0,
    ) -> dict:
        failure, response, resolved = await self._send(grant, tool, query, path_args, json, timeout)
        if response is None:
            if failure and failure.get("error") == "outcome_unknown":
                await self._notify_write(resolved, tool, json, None)
            return failure
        try:
            body = response.json() if response.content else None
        except ValueError:
            body = None
        if response.status_code >= 400:
            detail = body.get("detail") if isinstance(body, dict) else None
            return _status_to_error(response.status_code, detail)
        if self._allowlist[tool].write:
            await self._notify_write(resolved, tool, json, body)
        return ok(body)

    async def call_bytes(
        self,
        grant: tokens.TokenGrant,
        tool: str,
        *,
        query: Optional[Mapping[str, Any]] = None,
        timeout: float = 30.0,
    ) -> dict:
        """Like ``call`` for a route that answers image bytes: ``ok({"bytes", "mime"})``."""
        failure, response, _ = await self._send(grant, tool, query, None, None, timeout)
        if response is None:
            return failure
        if response.status_code >= 400:
            try:
                body = response.json()
            except ValueError:
                body = None
            detail = body.get("detail") if isinstance(body, dict) else None
            return _status_to_error(response.status_code, detail)
        return ok({"bytes": response.content,
                   "mime": response.headers.get("content-type", "image/jpeg").split(";")[0]})

    @staticmethod
    def _timed_out(spec: RouteSpec, tool: str) -> dict:
        if spec.write:
            return err("outcome_unknown",
                       f"{tool} timed out or the connection dropped: outcome unknown, "
                       "do not blindly retry; re-read state")
        return err("upstream_error", f"{tool} did not answer in time")
