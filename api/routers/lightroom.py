"""Lightroom round-trip router — manifest download + reverse-sync import.

Two endpoints, both edition-gated:

* ``POST /api/lightroom/manifest`` — build and return the same JSON manifest
  ``facet.py --export-manifest`` writes, scoped by the SAME ``paths`` /
  ``filters`` + ``exclude`` shape the export-editor dialog's sidecar export
  uses (``api.routers.export._selected_paths`` / ``_PathsOrFiltersRequest``),
  resolved the same way (reuses that resolver, same cap). A ``GET`` cannot
  carry ``filters``/``exclude`` cleanly, so this is a ``POST`` like the
  sidecar-export endpoint it mirrors.
* ``POST /api/lightroom/import`` — accept the plug-in's exported Lightroom-
  state JSON as a plain body (no multipart — see Step 10's B6 resolution)
  and fold it into Facet via ``processing.lightroom_sync.import_lightroom_state``.

Both use the caller's own session-resolved user — never a raw request field —
for multi-user scoping (per-user ``user_preferences`` rows / manifest ratings).
"""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api.auth import CurrentUser, require_edition
from api.config import get_xmp_export_config, invalidate_stats_cache
from api.database import get_db
from api.db_helpers import get_visibility_clause, select_in_chunks
from api.routers.export import (
    _PathsOrFiltersRequest,
    _selected_paths,
    _sequence_siblings,
    _visible_photo_paths,
)
from db import DEFAULT_DB_PATH
from processing.lightroom_sync import (
    InvalidLightroomStateFile,
    import_lightroom_state,
    validate_lightroom_state,
)
from processing.xmp_export import build_manifest

logger = logging.getLogger(__name__)

router = APIRouter(tags=["lightroom"])

# Cap for resolving the manifest's initial selection (explicit paths or a
# filters+exclude view), BEFORE burst/sequence expansion. Its own constant --
# not a reuse of api.routers.export's _SIDECAR_FILTER_MAX / _CULL_FILTER_MAX --
# per that module's own rationale (api/routers/export.py:68-76): the value is
# 10000 today only because every explicit-``paths`` list on either endpoint is
# separately bounded to max_length=10000 by the shared _PathsOrFiltersRequest
# base, not because the per-photo COST is the same. A manifest row is a single
# SQL SELECT (no subprocess), unlike sidecar export's two exiftool calls or
# cull's per-photo move -- coupling the caps would make one endpoint's cost
# model silently gate the other's cap.
_MANIFEST_FILTER_MAX = 10000

# Caps for the reverse-sync upload: a JSON body with no multipart size limit
# could otherwise pin a worker thread parsing an unbounded request. Refused
# (400/413) before any DB write, never truncated.
_IMPORT_MAX_BODY_BYTES = 20 * 1024 * 1024
_IMPORT_MAX_PHOTOS = 50000

# Cap on the manifest AFTER burst/sequence expansion -- the round trip's other
# half of _IMPORT_MAX_PHOTOS: any manifest the plug-in can build here must
# stay small enough that its later POST /api/lightroom/import upload (capped
# at _IMPORT_MAX_PHOTOS) can accept it back. Deliberately its own constant
# rather than _MANIFEST_FILTER_MAX, which only bounds the PRE-expansion
# selection -- expanding to full burst/sequence sets can grow a selection well
# past that cap (see _expand_to_full_sets), and the two caps bound different
# things.
_MANIFEST_EXPANDED_MAX = _IMPORT_MAX_PHOTOS


_SQLITE_VAR_LIMIT = 900


def _expand_to_full_sets(conn, paths: list[str], user_id) -> list[str]:
    """Expand a resolved selection to every frame of any burst/set it touches.

    Under the default ``hide_bursts`` / ``hide_brackets`` / ``hide_panoramas``
    (all ``true``), the gallery-scoped selection ``_selected_paths`` returns
    contains only each set's lead, so a whole-view manifest would otherwise
    carry groups of size 1 -- the plug-in's ``buildGroupIndex`` never fires
    pick/reject or set collections, and ``fullyInScope`` gets computed against
    a truncated group (I8). Filters by ``sequence_kind`` before grouping by
    ``sequence_group_id``, per CLAUDE.md's shared-column invariant.

    Every widening query is ANDed with ``get_visibility_clause(user_id)`` --
    mirroring ``api/routers/export.py``'s ``_bracket_lead_paths`` /
    ``_reassign_dead_leads`` -- so a burst/sequence sibling outside the
    caller's visible directories is never pulled into the expansion, even
    though ``paths`` itself is expected to already be visibility-filtered by
    the caller. Uses the shared ``select_in_chunks`` / ``_sequence_siblings``
    helpers rather than hand-rolled chunk loops.
    """
    if not paths:
        return paths
    vis_sql, vis_params = get_visibility_clause(user_id)

    burst_ids: set = set()
    sequence_pairs: set = set()
    for row in select_in_chunks(
        conn,
        "SELECT burst_group_id, sequence_kind, sequence_group_id FROM photos "
        "WHERE path IN ({placeholders}) AND " + vis_sql,
        paths, after=vis_params, chunk=_SQLITE_VAR_LIMIT,
    ):
        if row["burst_group_id"] is not None:
            burst_ids.add(row["burst_group_id"])
        if row["sequence_kind"] is not None and row["sequence_group_id"] is not None:
            sequence_pairs.add((row["sequence_kind"], row["sequence_group_id"]))

    expanded = set(paths)
    if burst_ids:
        for row in select_in_chunks(
            conn,
            "SELECT path FROM photos WHERE burst_group_id IN ({placeholders}) AND " + vis_sql,
            burst_ids, after=vis_params, chunk=_SQLITE_VAR_LIMIT,
        ):
            expanded.add(row["path"])

    if sequence_pairs:
        group_keys = {str(i): pair for i, pair in enumerate(sequence_pairs)}
        expanded.update(_sequence_siblings(conn, group_keys, exclude_paths=(), user_id=user_id))

    return sorted(expanded)


class LightroomManifestRequest(_PathsOrFiltersRequest):
    """Same scope shape as the sidecar export's request -- ``paths`` /
    ``filters`` + ``exclude`` -- reused rather than redefined so the two
    endpoints cannot silently drift apart on what a "selection" means.
    Subclasses ``_PathsOrFiltersRequest`` directly rather than
    ``ExportSidecarsRequest``: the manifest download has no "overwrite
    existing files" concept, so inheriting that field would put a meaningless
    ``overwrite`` in the OpenAPI schema and ``schema.d.ts`` (M7)."""


class LightroomImportResponse(BaseModel):
    matched: int
    unmatched: int
    changed: int


class LightroomManifest(BaseModel):
    """The v2 manifest shape ``build_manifest`` returns -- see its docstring.

    ``photos`` entries carry a large, growing set of per-photo fields (path,
    scores, tags, sequence columns, ...); typing that fully here would just
    duplicate ``build_manifest``'s own dict-building code with no extra
    safety, so entries stay ``dict`` while the top-level contract (what the
    export-editor dialog actually branches on: ``version``,
    ``pending_corrections``) is declared.
    """
    version: int
    generated_at: str
    photos: list[dict]
    pending_corrections: int


@router.post("/api/lightroom/manifest", response_model=LightroomManifest)
def api_lightroom_manifest(
    body: LightroomManifestRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Build the Lightroom manifest for the dialog's resolved scope.

    Scope resolution is the SAME SHAPE as ``POST /api/export/sidecars``:
    explicit ``paths``, or a ``filters`` + ``exclude`` gallery view. The
    pre-expansion selection is capped at ``_MANIFEST_FILTER_MAX``; the cap is
    its OWN constant, not shared with the sidecar/cull endpoints' caps, since
    a manifest row costs one SQL SELECT rather than a subprocess or a file
    move (see that constant's own comment). Ratings in the returned manifest
    are the caller's own (multi-user resolved via ``rating_columns``, exactly
    like the CLI's ``--user``).

    The explicit-``paths`` branch of ``_selected_paths`` is NOT itself
    visibility-scoped (it returns the caller's list verbatim), so the
    resolved selection is re-intersected with the caller's visible paths
    before expansion; the expansion queries are themselves visibility-scoped
    too, so a burst/sequence sibling outside scope can never be pulled in
    either. ``exclude`` is re-applied AFTER expansion (and the selection is
    re-checked after expansion against ``_MANIFEST_EXPANDED_MAX`` -- the
    round trip's other half of ``_IMPORT_MAX_PHOTOS``) since expanding to
    full sets can otherwise re-add a path the caller explicitly excluded, or
    grow the selection past what a later import of this same manifest could
    accept back.
    """
    if not body.paths and body.filters is None:
        raise HTTPException(status_code=400, detail="Either paths or filters is required")

    user_id = user.user_id
    with get_db() as conn:
        paths = _selected_paths(conn, body, user_id, max_filter_paths=_MANIFEST_FILTER_MAX,
                                 filter_label="manifest download")
        paths = sorted(_visible_photo_paths(conn, paths, user_id))
        # Expand the resolved selection to every frame of any burst/set it
        # touches -- otherwise a whole-view manifest under the default hide
        # toggles carries only each set's lead (I8).
        paths = _expand_to_full_sets(conn, paths, user_id)

    excluded = set(body.exclude or ())
    paths = [p for p in paths if p not in excluded]

    if len(paths) > _MANIFEST_EXPANDED_MAX:
        raise HTTPException(
            status_code=412,
            detail=(
                f"Expanding the selection to full burst/sequence sets grew it to "
                f"{len(paths)} photos, which exceeds the manifest cap of "
                f"{_MANIFEST_EXPANDED_MAX}. Narrow the selection and try again."
            ),
        )

    score_to_rating = get_xmp_export_config().get("score_to_rating")
    manifest = build_manifest(DEFAULT_DB_PATH, paths=paths, score_to_rating=score_to_rating,
                               user=user_id)
    return JSONResponse(
        content=manifest,
        headers={"Content-Disposition": 'attachment; filename="facet_manifest.json"'},
    )


@router.post(
    "/api/lightroom/import",
    response_model=LightroomImportResponse,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "description": (
                            "The plug-in's exported Lightroom-state file "
                            "(facet-lightroom-state format)."
                        ),
                        "required": ["format", "version", "photos"],
                        "properties": {
                            "format": {"type": "string", "const": "facet-lightroom-state"},
                            "version": {"type": "integer", "const": 1},
                            "photos": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "required": ["path"],
                                    "properties": {
                                        "path": {"type": "string"},
                                        "rating": {"type": "integer", "minimum": 0, "maximum": 5},
                                        "pick": {"type": "integer", "enum": [-1, 0, 1]},
                                    },
                                },
                            },
                        },
                    },
                },
            },
        },
        "responses": {
            "400": {"description": "Body is not valid JSON, or fails the state-file shape"},
            "413": {"description": "Body or photo count exceeds the import cap"},
        },
    },
)
async def api_lightroom_import(
    request: Request,
    user: CurrentUser = Depends(require_edition),
):
    """Import the plug-in's exported Lightroom-state JSON (Lightroom wins).

    Plain JSON body, no multipart (B6): the client reads the file itself and
    POSTs its parsed contents. Validated (format/version discriminator, then
    per-record shape) BEFORE any DB write; an oversized body or photo count is
    refused (413/400) before parsing/validating the records at all.

    The body is read from ``request.stream()`` with a running byte count
    rather than ``request.body()`` (which buffers the ENTIRE stream before any
    length check runs, per Starlette's own source) -- a chunked upload with no
    ``Content-Length`` header is refused as soon as it crosses the cap instead
    of being held fully in memory first, mirroring ``api/routers/webdav.py``'s
    ``dav_put``.
    """
    content_length = request.headers.get("content-length")
    if content_length is not None and int(content_length) > _IMPORT_MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Lightroom state file is too large")

    written = 0
    chunks: list[bytes] = []
    async for chunk in request.stream():
        written += len(chunk)
        if written > _IMPORT_MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="Lightroom state file is too large")
        chunks.append(chunk)
    raw = b"".join(chunks)

    try:
        data = json.loads(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Body is not valid JSON")

    if isinstance(data, dict) and isinstance(data.get("photos"), list) \
            and len(data["photos"]) > _IMPORT_MAX_PHOTOS:
        raise HTTPException(
            status_code=413,
            detail=f"Lightroom state file holds more than {_IMPORT_MAX_PHOTOS} photos",
        )

    try:
        records = validate_lightroom_state(data)
    except InvalidLightroomStateFile as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # import_lightroom_state (and the label-pair resync it triggers) is
    # synchronous SQLite work; running it inline on this coroutine would
    # block the whole event loop for the duration of the import -- up to
    # several minutes on a large, mostly-unmatched upload (I5). Offload to
    # the threadpool like every other blocking-DB route.
    #
    # visibility restricts which DB rows a record may match to the caller's
    # own session-resolved directories (I2): a directory-scoped user must
    # never be able to use matched/unmatched counts as an existence oracle
    # for, or write ratings against, a photo outside their visible
    # directories.
    visibility = get_visibility_clause(user.user_id)
    result = await run_in_threadpool(
        import_lightroom_state, DEFAULT_DB_PATH, records, user_id=user.user_id,
        visibility=visibility,
    )

    if result.changed > 0:
        invalidate_stats_cache()

    return LightroomImportResponse(
        matched=result.matched, unmatched=result.unmatched, changed=result.changed,
    )
