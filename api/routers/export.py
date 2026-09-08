"""Export router — write Facet ratings/picks out to editors and export selects.

Three endpoints, all edition-gated:

* ``POST /api/photo/export_xmp``      — write one XMP sidecar.
* ``POST /api/export/sidecars``       — write sidecars for many photos
                                        (explicit ``paths`` or a gallery filter set).
* ``POST /api/albums/{id}/export``    — "basket" export: an album's photos either
                                        as in-place sidecars, or copied / symlinked
                                        into a target folder.

Effective (per-user-resolved) ratings are read via ``build_photo_select_columns``
+ ``get_photos_from_clause`` so multi-user star/favorite/reject overrides are
honored. Disk paths are resolved through ``resolve_photo_disk_path`` (scan-dir
allowlist) before any file is written. The original image files are never
modified — only ``.xmp`` sidecars are written, or copies/symlinks created.
"""

import logging
import os
import shutil
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError, model_validator

from api.auth import CurrentUser, require_edition
from api.config import VIEWER_CONFIG, cull_allow_trash, get_all_scan_directories
from api.database import get_db
from api.db_helpers import (
    PANORAMA_KINDS_SQL,
    get_photos_from_clause,
    get_preference_columns,
    get_visibility_clause,
)
from api.models.scan import CullApplyResponse
from api.path_validation import resolve_photo_disk_path
from api.raw_processing import find_companion_raw
from processing.xmp_export import (
    FaceRegion,
    XmpRating,
    person_names_from_regions,
    write_metadata,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["export"])

# Cap the placeholders in a single IN (...) query so a large selection (paths is
# bounded at 10000) can never exceed legacy SQLite's SQLITE_MAX_VARIABLE_NUMBER
# (999). Matches the chunked-fetch size used in gallery.py.
_PATH_QUERY_CHUNK = 500

# Cap on the photos one sidecar export may touch when the set comes from a
# filter instead of an explicit list. Matches ExportSidecarsRequest.paths'
# own max_length so both request forms are bounded identically -- the filter
# branch is the UI-reachable one now that the gallery can select a whole view
# without sending its paths. The work per photo is two exiftool processes
# (~0.13s measured), and the endpoint is a sync `def`, so it pins one FastAPI
# threadpool worker for the whole run: an uncapped library-wide export would
# hold that worker for hours. Refused rather than truncated -- half-exporting a
# selection the user believed was whole is worse than a clear refusal.
_SIDECAR_FILTER_MAX = 10000

# Same shape of problem, for POST /api/cull/apply's filter branch: `_selected_paths`
# was called with no cap there at all, so a whole-library filter set resolved to
# every path the library holds. Kept as its OWN constant rather than reusing
# _SIDECAR_FILTER_MAX, even though both are 10000 today: that value is shared
# only because both this field and ExportSidecarsRequest.paths cap their
# explicit-list branch at max_length=10000 via the common _PathsOrFiltersRequest
# base, so all four ways of naming a set on either endpoint end up bounded
# identically. The per-photo COST that motivates a cap is not the same one --
# sidecar export spawns two exiftool subprocesses per photo (~0.13s measured);
# cull does a single shutil.move/copy2 or send2trash call per photo, an order of
# magnitude cheaper -- so a future retune of either ceiling should not have to
# touch the other. Refused (412) rather than truncated, exactly like the sidecar
# cap, and applies to a dry run too: a preview must not be usable to do the
# unbounded work the real run would be refused for.
_CULL_FILTER_MAX = 10000


# --- Request models ---

class ExportXmpRequest(BaseModel):
    path: str
    overwrite: bool = False


class EmbedMetadataRequest(BaseModel):
    path: str


# The set a filter-scoped destructive request acts on: named paths, or the
# gallery view itself. Shared by sidecar export and cull so the two cannot
# disagree about how a selection is named -- and so the both-are-set rejection
# below is written once rather than per endpoint. No docstring: these fields
# are inlined into each endpoint's generated OpenAPI model, which carried no
# description before this base existed.
class _PathsOrFiltersRequest(BaseModel):
    paths: Optional[list[str]] = Field(default=None, max_length=10000)
    filters: Optional[dict] = None
    # Paths to drop from whichever target is sent. The client's "whole view
    # selected, minus these few" state, sent as the exceptions rather than as
    # the whole selection. Capped well below SQLITE_MAX_VARIABLE_NUMBER because
    # on the filter branch it binds one placeholder each into a single
    # NOT IN (...). Only ever narrows, so it can never widen a destructive
    # action.
    exclude: Optional[list[str]] = Field(
        default=None, max_length=1000,
        description="Paths to drop from whichever target is sent: subtracted from "
                    "`paths`, or bound out of the `filters` scope. Only ever narrows.",
    )

    @model_validator(mode='after')
    def _reject_both_targets(self):
        """``paths`` and ``filters`` name the same set two ways; never both.

        Sending both was silently resolved in ``paths``' favour:
        :func:`_selected_paths` returns the path list before ``filters`` is
        ever read, so a client that sent a whole-view filter set alongside a
        stale path list had its scope dropped without a word -- on endpoints
        that move and trash files. 422 like
        ``BatchPhotoRequest._exactly_one_target``, its twin in
        ``api/routers/faces.py``. (``exclude`` is no longer part of that
        failure: it narrows whichever target is sent, so it survives either
        branch.)

        The "neither" case stays a 400 in the handlers rather than joining this
        validator: that is the status this pair of endpoints has always
        returned for a request with no target at all.
        """
        if self.paths is not None and self.filters is not None:
            raise ValueError("paths and filters are mutually exclusive — send one, not both")
        return self


class ExportSidecarsRequest(_PathsOrFiltersRequest):
    overwrite: bool = False


class AlbumExportRequest(BaseModel):
    mode: Literal["sidecars", "copy", "symlink"] = "sidecars"
    target_dir: Optional[str] = None
    overwrite: bool = False


class CullApplyRequest(_PathsOrFiltersRequest):
    action: Literal["copy_keeps", "trash_rejects", "move_rejects"]
    target_dir: Optional[str] = None
    # Off by default: rejecting a derived JPEG must not silently trash/move its
    # untouched companion RAW or darktable .xmp. Opt in to keep a shot whole.
    include_companions: bool = False
    # Off by default too, for the same reason: a bracket/panorama sibling is a
    # separate photo row that the gallery hides by default, so silently
    # widening a destructive move/trash to cover it needs explicit consent.
    # Unlike include_companions this is DB-derived (sequence_kind +
    # sequence_group_id), not a same-stem disk lookup.
    include_sequence_siblings: bool = False
    dry_run: bool = True


# --- Helpers ---

def _fetch_rating_rows(conn, paths, user_id):
    """Fetch effective-rating rows (per-user resolved) for ``paths``.

    Returns a dict keyed by db photo path. Only paths visible to the user and
    present in the DB are returned. ``get_preference_columns`` resolves
    star_rating/is_favorite/is_rejected to the user_preferences COALESCE
    expressions in multi-user mode, so per-user overrides are honored.
    """
    if not paths:
        return {}
    pref_cols = get_preference_columns(user_id)
    from_clause, from_params = get_photos_from_clause(user_id)
    vis_sql, vis_params = get_visibility_clause(user_id)
    select = (
        "photos.path as path, photos.tags as tags, "
        "photos.caption as caption, photos.category as category, "
        "photos.aggregate as aggregate, "
        f"{pref_cols['star_rating']} as star_rating, "
        f"{pref_cols['is_favorite']} as is_favorite, "
        f"{pref_cols['is_rejected']} as is_rejected"
    )
    placeholders = ",".join("?" * len(paths))
    query = (
        f"SELECT {select} FROM {from_clause} "
        f"WHERE photos.path IN ({placeholders}) AND {vis_sql}"
    )
    rows = conn.execute(query, from_params + list(paths) + vis_params).fetchall()
    return {row["path"]: dict(row) for row in rows}


def _resolve_filter_paths(conn, filters, user_id, exclude=None, max_paths=None,
                          filter_label="this action"):
    """Resolve a gallery filter set to a list of photo paths.

    ``gallery_scope_sql`` is the gallery's own definition of "the current
    view", normalization included, so a filter set that renders one grid
    resolves here to exactly the rows that grid shows — ``exclude`` aside. It
    also applies the album access check, so a filter set naming an album this
    caller cannot open raises 403/404 here exactly as the gallery GET does.
    Parameterized: only the fixed from-clause and the generated placeholder run
    are interpolated, every user value stays a ``?`` bind.

    ``max_paths`` bounds the resolved set. The count is a ``COUNT(*)`` over the
    same scope, taken BEFORE the path list is materialised, so an oversized
    view is refused without ever building the list it would have exported.
    ``filter_label`` names the caller in the 412 (e.g. "sidecar export", "cull")
    since this resolver is shared by more than one capped endpoint.
    """
    from api.routers.gallery import gallery_scope_sql

    from_clause, where_str, params = gallery_scope_sql(conn, filters, user_id, exclude)
    if max_paths is not None:
        total = conn.execute(
            f"SELECT COUNT(*) FROM {from_clause}{where_str}", params
        ).fetchone()[0]
        if total > max_paths:
            raise HTTPException(
                status_code=412,
                detail=(
                    f"This view holds {total} photos and {filter_label} is capped at "
                    f"{max_paths}. Narrow the filters and try again."
                ),
            )
    rows = conn.execute(
        f"SELECT photos.path FROM {from_clause}{where_str}", params
    ).fetchall()
    return [row["path"] for row in rows]


def _selected_paths(conn, body, user_id, max_filter_paths=None, filter_label="this action"):
    """The paths a ``paths``-or-``filters`` request acts on.

    Explicit paths win; otherwise the filter set is resolved through the
    gallery's own scope builder, which rejects a malformed filter set by
    raising — a 422 here, rather than the 500 an escaping ``ValidationError``
    would turn into. The two are mutually exclusive at validation
    (``_PathsOrFiltersRequest``), so "paths win" is now only the empty-list
    case rather than a silent preference.

    ``max_filter_paths`` bounds the FILTER branch only; the ``paths`` branch is
    already bounded by the field's own ``max_length``. ``filter_label`` is
    forwarded to :func:`_resolve_filter_paths` for its 412 message.

    ``exclude`` narrows WHICHEVER target is sent. On the filter branch the
    scope builder binds it into the query; on the paths branch it is subtracted
    here. It used to be read only on the filter branch, so a request naming
    ``paths`` alongside ``exclude`` moved or OS-trashed the very files it had
    listed as exceptions, without a word -- the same silent-drop failure
    ``_PathsOrFiltersRequest._reject_both_targets`` was written to close for the
    sibling pair. Subtraction preserves the caller's order and leaves an empty
    ``exclude`` a no-op; excluding every named path resolves to an empty set,
    which the handlers already treat as "nothing qualified" rather than as a
    missing target (the no-target 400 is decided on ``body.paths`` before this
    runs).
    """
    if body.paths:
        excluded = set(body.exclude or ())
        return [p for p in body.paths if p not in excluded]
    try:
        return _resolve_filter_paths(conn, body.filters, user_id, body.exclude,
                                     max_paths=max_filter_paths, filter_label=filter_label)
    except ValidationError as e:
        from api.routers.gallery import _raise_422_for_invalid_gallery_params
        _raise_422_for_invalid_gallery_params(e, logger, "Export filter validation failed: %s")


def _fetch_regions_map(conn, paths):
    """Map each path to its named-face regions (for MWG ``mwg-rs`` export).

    Only faces assigned to a named person with a valid bbox and known image
    dimensions are included. Returns ``{path: [FaceRegion, ...]}``.
    """
    if not paths:
        return {}
    placeholders = ",".join("?" * len(paths))
    rows = conn.execute(
        "SELECT f.photo_path AS path, pe.name AS name, "
        "f.bbox_x1, f.bbox_y1, f.bbox_x2, f.bbox_y2, "
        "ph.image_width AS w, ph.image_height AS h "
        "FROM faces f "
        "JOIN persons pe ON f.person_id = pe.id "
        "JOIN photos ph ON ph.path = f.photo_path "
        f"WHERE f.photo_path IN ({placeholders}) AND pe.name IS NOT NULL "
        "AND f.bbox_x1 IS NOT NULL AND ph.image_width > 0 AND ph.image_height > 0",
        list(paths),
    ).fetchall()
    regions: dict[str, list[FaceRegion]] = {}
    for row in rows:
        regions.setdefault(row["path"], []).append(
            FaceRegion.from_bbox(
                row["name"], row["bbox_x1"], row["bbox_y1"],
                row["bbox_x2"], row["bbox_y2"], row["w"], row["h"],
            )
        )
    return regions


def _rating_from(row, regions_map):
    """Build an ``XmpRating`` for a fetched row with its face regions attached.

    Person names are derived from the regions (deduped, order-preserving) rather
    than a comma-joined SQL aggregate, so names containing commas round-trip.
    """
    from api.config import get_xmp_export_config
    rating = XmpRating.from_row(row)
    rating.apply_score_mapping(get_xmp_export_config())
    rating.regions = regions_map.get(row["path"], [])
    rating.person_names = person_names_from_regions(rating.regions)
    return rating


def _write_sidecars_for_paths(conn, paths, user_id, overwrite):
    """Write metadata (embed + sidecar) for every visible path; return counts."""
    rating_rows = _fetch_rating_rows(conn, paths, user_id)
    regions_map = _fetch_regions_map(conn, list(rating_rows.keys()))
    written = 0
    skipped = 0
    errors = 0
    sidecars: list[str] = []
    for path in paths:
        row = rating_rows.get(path)
        if row is None:
            skipped += 1
            continue
        try:
            real_disk = resolve_photo_disk_path(path)
        except HTTPException:
            # Path escaped the allowlist or is missing on disk — skip it.
            skipped += 1
            continue
        try:
            result = write_metadata(real_disk, _rating_from(row, regions_map),
                                    overwrite=overwrite, embed_original=False)
            written += 1
            sidecars.append(result["sidecar"])
        except (OSError, RuntimeError):
            logger.exception("Failed to write metadata for %s", path)
            errors += 1
    return {
        "ok": True,
        "written": written,
        "skipped": skipped,
        "errors": errors,
        "sidecars": sidecars,
    }


def _album_photo_paths(conn, album_id, user_id):
    """Fetch an album's photo paths (reusing the album_photos membership)."""
    album = conn.execute("SELECT * FROM albums WHERE id = ?", (album_id,)).fetchone()
    if not album:
        raise HTTPException(status_code=404, detail="Album not found")
    if album["user_id"] and album["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    vis_sql, vis_params = get_visibility_clause(user_id)
    rows = conn.execute(
        "SELECT ap.photo_path FROM album_photos ap "
        f"JOIN photos ON photos.path = ap.photo_path "
        f"WHERE ap.album_id = ? AND {vis_sql} "
        "ORDER BY ap.position ASC",
        [album_id] + vis_params,
    ).fetchall()
    return [row["photo_path"] for row in rows]


def _allowed_export_roots():
    """Real-path roots a copy/symlink export may write into.

    Configured ``viewer.export.allowed_target_dirs`` first, then the scan
    directories (so exporting within the photo tree works out of the box).
    """
    roots = []
    export_cfg = VIEWER_CONFIG.get("export", {}) or {}
    for d in (export_cfg.get("allowed_target_dirs") or []):
        if d:
            roots.append(os.path.realpath(d))
    for d in get_all_scan_directories():
        if d:
            roots.append(os.path.realpath(d))
    return roots


def _validate_target_dir(target_dir):
    """Canonicalize ``target_dir`` and require it under an allowed export root.

    Without this an edition user could copy/symlink album photos to an arbitrary
    host location (path traversal / symlink planting). Fail-closed: a target
    outside every configured root (including the case where none are
    configured at all) is refused rather than writing anywhere. The caller is
    already edition-authenticated, so the 403 names the config key and the
    resolved roots — a misconfiguration is otherwise unfixable from the UI.
    """
    real = os.path.realpath(target_dir)
    roots = _allowed_export_roots()
    # Two separate guards rather than any(...) or an or-condition: the direct
    # startswith true-branch is the containment shape static analysis credits
    # as a sanitizer, and the equality case returns the config-derived root
    # itself, so neither return path carries the request-provided string.
    for root in roots:
        if real == root:
            return root
        if real.startswith(root + os.sep):
            return real
    allowed = ", ".join(roots) if roots else "none configured"
    raise HTTPException(
        status_code=403,
        detail=(
            "target_dir is not an allowed export location. Configure "
            f"viewer.export.allowed_target_dirs to add one — allowed roots: {allowed}"
        ),
    )


def _contained_dest(target_dir, filename):
    """Join ``filename`` into ``target_dir`` and confirm it stays inside.

    ``filename`` is always a bare ``os.path.basename`` so it cannot contain a
    separator, but resolving with ``realpath`` and re-asserting containment
    against the (already validated) ``target_dir`` root makes the boundary
    explicit and rejects any residual escape (e.g. a symlinked target).
    """
    real_root = os.path.realpath(target_dir)
    dest = os.path.realpath(os.path.join(real_root, filename))
    if dest != real_root and not dest.startswith(real_root + os.sep):
        raise HTTPException(status_code=400, detail="export destination escapes target_dir")
    return dest


def _copy_or_link_into(paths, target_dir, mode):
    """Copy or symlink each resolved photo into ``target_dir``.

    Filenames that collide get a numeric suffix so selects aren't overwritten.
    ``target_dir`` must already be validated by ``_validate_target_dir``.
    """
    os.makedirs(target_dir, exist_ok=True)
    copied = 0
    skipped = 0
    errors = 0
    for path in paths:
        try:
            real_disk = resolve_photo_disk_path(path)
        except HTTPException:
            skipped += 1
            continue
        dest = _unique_dest(target_dir, os.path.basename(real_disk))
        try:
            if mode == "symlink":
                os.symlink(real_disk, dest)
            else:
                shutil.copy2(real_disk, dest)
            copied += 1
        except OSError:
            logger.exception("Failed to %s %s into %s", mode, path, target_dir)
            errors += 1
    return copied, skipped, errors


def _companion_files(disk_path):
    """Sibling files that belong with a shot: its companion RAW and .xmp sidecar.

    Keeps a "moved" shot whole rather than orphaning its RAW/metadata. Returns an
    ordered, de-duplicated list of existing paths (never the primary itself).
    """
    out = []
    raw = find_companion_raw(disk_path)
    if raw and raw != disk_path:
        out.append(raw)
    for sidecar in (disk_path + ".xmp", os.path.splitext(disk_path)[0] + ".xmp"):
        if os.path.exists(sidecar) and sidecar not in out:
            out.append(sidecar)
    return out


def _resolve_cull_files(paths, include_companions):
    """Resolve each db path to its on-disk files (+ companions), tracking skips.

    Returns ``(items, skipped)`` where items is a list of ``(db_path, [files])``
    and skipped is the db paths that did not resolve to a disk file.
    """
    items = []
    skipped = []
    for path in paths:
        try:
            real = resolve_photo_disk_path(path)
        except HTTPException:
            skipped.append(path)
            continue
        files = [real]
        if include_companions:
            files.extend(_companion_files(real))
        items.append((path, files))
    return items, skipped


def _chunked_path_rows(conn, paths, sql_fn, params_fn):
    """Run a ``path IN (...)`` query once per ``_PATH_QUERY_CHUNK``-sized chunk
    of ``paths`` and yield every row, so no caller has to re-derive its own
    chunk boundary or SQLite's placeholder limit.

    ``sql_fn(placeholders)`` builds the query text for a chunk's placeholder
    string; ``params_fn(chunk)`` builds that chunk's bound parameters (its own
    prefix/suffix params plus the chunk itself, in bind order).
    """
    paths = list(paths)
    for start in range(0, len(paths), _PATH_QUERY_CHUNK):
        chunk = paths[start:start + _PATH_QUERY_CHUNK]
        yield from conn.execute(sql_fn(",".join("?" * len(chunk))), params_fn(chunk)).fetchall()


def _sequence_group_keys(conn, paths, user_id):
    """Map each of ``paths`` with a sequence group to its ``(kind, group_id)``.

    Ungrouped photos (``sequence_kind IS NULL``) are simply absent from the
    map -- they have no siblings. Visibility-scoped like ``_reject_state_map``.
    """
    if not paths:
        return {}
    vis_sql, vis_params = get_visibility_clause(user_id)
    rows = _chunked_path_rows(
        conn, paths,
        sql_fn=lambda ph: (
            "SELECT path, sequence_kind, sequence_group_id FROM photos "
            f"WHERE path IN ({ph}) AND {vis_sql} "
            "AND sequence_kind IS NOT NULL AND sequence_group_id IS NOT NULL"
        ),
        params_fn=lambda chunk: chunk + vis_params,
    )
    return {r["path"]: (r["sequence_kind"], r["sequence_group_id"]) for r in rows}


def _sequence_siblings(conn, group_keys, exclude_paths, user_id):
    """Every visible sibling sharing a ``(sequence_kind, sequence_group_id)``
    found in ``group_keys``, excluding ``exclude_paths`` (the already-matched
    set) and de-duplicated across groups.

    A set's identity is the PAIR ``(sequence_kind, sequence_group_id)``: the
    bracket and panorama passes share ``sequence_group_id`` and each renumber
    their own groups from 1, so grouping by id alone would mix two unrelated
    sets that happen to share a number. Both columns are always bound
    together in the WHERE clause below so that can't happen.
    """
    if not group_keys:
        return []
    vis_sql, vis_params = get_visibility_clause(user_id)
    exclude = set(exclude_paths)
    seen = set()
    siblings = []
    for kind, group_id in set(group_keys.values()):
        rows = conn.execute(
            "SELECT path FROM photos WHERE sequence_kind = ? AND sequence_group_id = ? "
            f"AND {vis_sql}",
            [kind, group_id] + vis_params,
        ).fetchall()
        for r in rows:
            p = r["path"]
            if p in exclude or p in seen:
                continue
            seen.add(p)
            siblings.append(p)
    return siblings


def _reassign_dead_leads(conn, removed_db_paths, user_id):
    """Re-pick a surviving frame as lead for any panorama-kind sequence group
    whose lead was just moved/trashed.

    ``move_rejects``/``trash_rejects`` touch only the filesystem, so a removed
    panorama lead keeps satisfying ``HIDE_PANORAMAS_SQL`` -- and keeps serving
    its stored thumbnail -- until a rescan prunes the row, at which point every
    surviving frame has ``is_sequence_lead = 0`` and the whole set disappears
    from the default gallery. Scoped by the ``(sequence_kind,
    sequence_group_id)`` pair per the same invariant as ``_sequence_siblings``,
    and confined to the ``is_sequence_lead`` column -- nothing else about the
    row is touched. The demotion is guarded by ``if survivors:`` exactly like
    the promotion, so a whole group removed together (no surviving frame to
    promote) is a true no-op: demoting the dead lead's flag with nothing to
    promote in its place would leave the set with no lead at all, which is
    worse than leaving a stale flag for the next ``--detect-sequences`` run
    to clean up.

    Restricted to ``PANORAMA_KINDS`` (``panorama``/``hdr_panorama``): a
    bracket's representative is its ``sequence_ev_offset = 0`` frame -- a
    physical fact of the exposures, not a mark that can be moved -- so moving
    or trashing a bracket's base exposure leaves the rest of that set hidden
    once a rescan prunes the base row, and only re-running
    ``--detect-sequences`` restores it. This scoping also matters beyond
    panoramas: ``is_sequence_lead = 1`` is the one flag ``hide_bursts_sql``
    exempts from its own hide clause (``api/db_helpers.py``), so setting it on
    a bracket frame would grant that frame an unintended hide_bursts exemption.

    Fetches each dead lead's group members by the ``(sequence_kind,
    sequence_group_id)`` key and filters ``removed_db_paths`` out in Python,
    rather than binding the whole removed-path list into a ``NOT IN`` per dead
    lead -- O(D) group queries instead of O(D x R) binds, so the write
    transaction holding the DB lock stays short even when R (every path
    touched by this request) is large. Both queries are visibility-scoped
    like every sibling helper in this file, and the dead-lead lookup is
    chunked at ``_PATH_QUERY_CHUNK`` since ``removed_db_paths`` is unbounded.
    """
    if not removed_db_paths:
        return
    removed = set(removed_db_paths)
    vis_sql, vis_params = get_visibility_clause(user_id)
    dead_leads = list(_chunked_path_rows(
        conn, list(removed),
        sql_fn=lambda ph: (
            "SELECT path, sequence_kind, sequence_group_id FROM photos "
            f"WHERE path IN ({ph}) AND is_sequence_lead = 1 "
            f"AND sequence_kind IN {PANORAMA_KINDS_SQL} AND {vis_sql}"
        ),
        params_fn=lambda chunk: chunk + vis_params,
    ))
    for lead in dead_leads:
        members = conn.execute(
            "SELECT path FROM photos WHERE sequence_kind = ? AND sequence_group_id = ? "
            f"AND {vis_sql} ORDER BY date_taken, path",
            [lead["sequence_kind"], lead["sequence_group_id"]] + vis_params,
        ).fetchall()
        survivors = [m for m in members if m["path"] not in removed]
        if survivors:
            conn.execute("UPDATE photos SET is_sequence_lead = 0 WHERE path = ?", (lead["path"],))
            # The MIDDLE surviving frame in capture order, matching how the
            # detector chose in the first place (``utils/panorama.py``): a sweep
            # has no best frame, and the middle one is likeliest to hold the
            # subject. Promoting an edge frame would leave the set represented
            # in the gallery by its least representative tile.
            conn.execute(
                "UPDATE photos SET is_sequence_lead = 1 WHERE path = ?",
                (survivors[len(survivors) // 2]["path"],),
            )
    conn.commit()


def _reassign_dead_leads_after_removal(items, succeeded, user_id):
    """Re-pick a lead for any panorama group whose lead's PRIMARY file just
    moved/trashed successfully.

    ``items`` is the ``(db_path, [files])`` list ``_resolve_cull_files``
    built for the request; only the primary file (``fs[0]``, never a
    companion) determines whether the db row's own photo is actually gone.
    Shared by the move and trash branches of ``api_cull_apply`` so the
    "which files actually moved -> which db rows are gone -> reassign" chain
    exists in one place.
    """
    removed_db_paths = {db_path for db_path, fs in items if fs[0] in succeeded}
    with get_db() as reassign_conn:
        _reassign_dead_leads(reassign_conn, removed_db_paths, user_id)


def _reject_state_map(conn, paths, user_id):
    """Map each visible, in-DB path to its per-user ``is_rejected`` bool.

    Used to bound a destructive cull to the user's actual reject set: paths not
    visible / not in the DB are simply absent from the map.
    """
    if not paths:
        return {}
    pref_cols = get_preference_columns(user_id)
    from_clause, from_params = get_photos_from_clause(user_id)
    vis_sql, vis_params = get_visibility_clause(user_id)
    rows = _chunked_path_rows(
        conn, paths,
        sql_fn=lambda ph: (
            f"SELECT photos.path AS path, {pref_cols['is_rejected']} AS is_rejected "
            f"FROM {from_clause} WHERE photos.path IN ({ph}) AND {vis_sql}"
        ),
        params_fn=lambda chunk: from_params + chunk + vis_params,
    )
    return {r["path"]: bool(r["is_rejected"]) for r in rows}


def _move_into(files, target_dir):
    """Move each file into the (already validated) ``target_dir``.

    Returns ``(moved, errors, succeeded)`` where ``succeeded`` is the set of
    source paths that moved without error -- the caller uses it to tell which
    photos' primary file is actually gone from disk (for sequence-lead
    reassignment).
    """
    os.makedirs(target_dir, exist_ok=True)
    moved = errors = 0
    succeeded = set()
    for src in files:
        try:
            shutil.move(src, _unique_dest(target_dir, os.path.basename(src)))
            moved += 1
            succeeded.add(src)
        except (OSError, shutil.Error):
            logger.exception("Failed to move %s into %s", src, target_dir)
            errors += 1
    return moved, errors, succeeded


def _unique_dest(target_dir, filename):
    """Return a non-colliding destination path confined to ``target_dir``."""
    dest = _contained_dest(target_dir, filename)
    if not os.path.exists(dest):
        return dest
    stem, ext = os.path.splitext(filename)
    i = 1
    while True:
        candidate = _contained_dest(target_dir, f"{stem}_{i}{ext}")
        if not os.path.exists(candidate):
            return candidate
        i += 1


# --- Endpoints ---

@router.post("/api/photo/export_xmp")
def api_export_xmp(
    body: ExportXmpRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Write a single XMP sidecar next to a photo (the original is never touched).

    ``overwrite`` only governs the dependency-free fallback writer used when
    exiftool is absent (it diverts to ``.facet.xmp`` rather than clobbering a
    darktable sidecar). When exiftool is present the sidecar is merged
    non-destructively regardless, so ``overwrite`` has no effect on that path.
    """
    if not body.path:
        raise HTTPException(status_code=400, detail="path required")

    user_id = user.user_id
    with get_db() as conn:
        rating_rows = _fetch_rating_rows(conn, [body.path], user_id)
        regions_map = _fetch_regions_map(conn, list(rating_rows.keys()))

    row = rating_rows.get(body.path)
    if row is None:
        raise HTTPException(status_code=404, detail="File not found")

    real_disk = resolve_photo_disk_path(body.path)
    try:
        result = write_metadata(real_disk, _rating_from(row, regions_map),
                                overwrite=body.overwrite, embed_original=False)
    except (OSError, RuntimeError):
        logger.exception("Failed to write metadata for %s", body.path)
        raise HTTPException(status_code=500, detail="Failed to write metadata")
    return result


@router.post("/api/photo/embed_metadata")
def api_embed_metadata(
    body: EmbedMetadataRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Embed Facet metadata into the original photo file (and write the sidecar).

    Unlike ``/api/photo/export_xmp`` (sidecar-only), this rewrites the original
    image in-place for safe formats (JPEG/HEIC/TIFF/PNG/DNG) so the whole photo
    ecosystem sees the rating/keywords. Proprietary RAW is never modified.
    """
    if not body.path:
        raise HTTPException(status_code=400, detail="path required")

    user_id = user.user_id
    with get_db() as conn:
        rating_rows = _fetch_rating_rows(conn, [body.path], user_id)
        regions_map = _fetch_regions_map(conn, list(rating_rows.keys()))

    row = rating_rows.get(body.path)
    if row is None:
        raise HTTPException(status_code=404, detail="File not found")

    real_disk = resolve_photo_disk_path(body.path)
    try:
        result = write_metadata(real_disk, _rating_from(row, regions_map), embed_original=True)
    except (OSError, RuntimeError):
        logger.exception("Failed to embed metadata for %s", body.path)
        raise HTTPException(status_code=500, detail="Failed to embed metadata")
    return result


@router.post("/api/export/sidecars")
def api_export_sidecars(
    body: ExportSidecarsRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Write XMP sidecars for many photos (explicit paths or a filter set)."""
    # Kept a one-liner: FastAPI publishes this docstring as the operation
    # description, and the generated client types (client/src/app/core/api/
    # schema.d.ts) are diffed in CI, so prose here is a cross-project change.
    # Both ways of naming the set are bounded at _SIDECAR_FILTER_MAX; a larger
    # filter set is refused with 412 rather than truncated.
    if not body.paths and body.filters is None:
        raise HTTPException(status_code=400, detail="Either paths or filters is required")

    user_id = user.user_id
    with get_db() as conn:
        paths = _selected_paths(conn, body, user_id, max_filter_paths=_SIDECAR_FILTER_MAX,
                                 filter_label="sidecar export")
        return _write_sidecars_for_paths(conn, paths, user_id, body.overwrite)


@router.post("/api/cull/apply", response_model=CullApplyResponse, response_model_exclude_unset=True)
def api_cull_apply(
    body: CullApplyRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Physically act on a culling decision: copy keeps, or trash/move rejects.

    Defaults to ``dry_run`` (no I/O — returns the resolved file lists for a
    preview). Copy is purely additive; move/trash are destructive and require an
    explicit ``dry_run=false``. The op is bounded server-side to the action's
    actual set: ``copy_keeps`` acts only on non-rejected photos, ``move_rejects``
    /``trash_rejects`` only on rejected ones (per-user ``is_rejected``), so a
    buggy client can never move/trash a photo the user has not rejected — the
    excess is reported as ``excluded_by_state``. All file writes go through the
    same validated allow-list as album export, and trashing is OS-trash
    (recoverable) gated behind ``viewer.cull.allow_trash`` — never a permanent
    delete.

    Sequence siblings (bracket/panorama frames the gallery hides by default)
    are counted in ``sequence_siblings`` regardless of ``include_sequence_siblings``
    — the count is reported so the user can see a multi-frame set exists even
    when they decline to expand it — and only added to the acted-on files when
    the flag is set AND the sibling's own reject state matches the action,
    exactly like a path the caller named directly: a kept sibling of a
    rejected lead is never moved/trashed just because the flag is on, and a
    rejected sibling of a kept lead is never copied as a keep. A sibling whose
    own state doesn't match folds into ``excluded_by_state`` too. ``matched``
    is how many of the request's own paths matched this action's
    reject-state, so a response with ``matched == 0`` reads as "nothing here
    qualified" rather than a silent no-op. Moving/trashing a panorama's lead
    frame re-picks a surviving sibling as the new lead so the set stays
    visible under the default hide toggles.
    """
    # Kept unchanged above: FastAPI publishes this docstring as the operation
    # description, and the generated client types (client/src/app/core/api/
    # schema.d.ts) are diffed in CI, so prose here is a cross-project change.
    # Both ways of naming the set are bounded at _CULL_FILTER_MAX; a larger
    # filter set is refused with 412 rather than truncated, dry run included.
    if not body.paths and body.filters is None:
        raise HTTPException(status_code=400, detail="Either paths or filters is required")

    user_id = user.user_id
    # Bound the action to its semantic reject-state: keeps are non-rejected,
    # rejects are rejected. Photos in the selection that don't match are skipped.
    want_rejected = body.action != "copy_keeps"
    with get_db() as conn:
        paths = _selected_paths(conn, body, user_id, max_filter_paths=_CULL_FILTER_MAX,
                                 filter_label="cull")
        state = _reject_state_map(conn, paths, user_id)
        matching = [p for p in paths if state.get(p) == want_rejected]
        group_keys = _sequence_group_keys(conn, matching, user_id)
        sibling_paths = _sequence_siblings(conn, group_keys, matching, user_id)
        # Siblings are auto-added, not requested directly -- bound them to the
        # SAME reject-state check as `matching` (Finding 1, 2026-08-17 review)
        # rather than acting on a whole group regardless of each frame's own
        # state.
        sibling_state = _reject_state_map(conn, sibling_paths, user_id)
    sibling_matching = [p for p in sibling_paths if sibling_state.get(p) == want_rejected]
    excluded_by_state = sum(1 for p in paths if p in state and state[p] != want_rejected)
    if body.include_sequence_siblings:
        excluded_by_state += len(sibling_paths) - len(sibling_matching)
    # Not in state at all: invisible to this user, or not in the DB. Not acted
    # on either way, but distinct from excluded_by_state — surface it so the
    # totals (matching + excluded_by_state + not_visible) reconcile with len(paths).
    not_visible = sum(1 for p in paths if p not in state)
    matched = len(matching)
    sequence_siblings = len(sibling_paths)

    action_paths = matching + sibling_matching if body.include_sequence_siblings else matching
    items, skipped = _resolve_cull_files(action_paths, body.include_companions)
    files = [f for _, fs in items for f in fs]

    def respond(dry_run, errors, **verb):
        return {
            "action": body.action,
            "dry_run": dry_run,
            **verb,
            "skipped": skipped,
            "excluded_by_state": excluded_by_state,
            "not_visible": not_visible,
            "matched": matched,
            "sequence_siblings": sequence_siblings,
            "errors": errors,
        }

    if body.action == "copy_keeps":
        safe_target = _validate_target_dir_required(body.target_dir)
        if body.dry_run:
            return respond(True, [], would_copy=files)
        copied = errors = 0
        os.makedirs(safe_target, exist_ok=True)
        for src in files:
            try:
                shutil.copy2(src, _unique_dest(safe_target, os.path.basename(src)))
                copied += 1
            except OSError:
                logger.exception("Failed to copy %s into %s", src, safe_target)
                errors += 1
        return respond(False, errors, copied=copied)

    if body.action == "move_rejects":
        safe_target = _validate_target_dir_required(body.target_dir)
        if body.dry_run:
            return respond(True, [], would_move=files)
        moved, errors, succeeded = _move_into(files, safe_target)
        _reassign_dead_leads_after_removal(items, succeeded, user_id)
        return respond(False, errors, moved=moved)

    # trash_rejects
    if not cull_allow_trash(VIEWER_CONFIG):
        raise HTTPException(status_code=403,
                            detail="OS-trash is disabled — set viewer.cull.allow_trash to enable")
    try:
        import send2trash
    except ImportError:
        # This action's own import re-runs every request, so it recovers the
        # moment the package lands in the venv -- but GET /api/config's
        # trash_available flag (api/routers/gallery.py's HAS_SEND2TRASH) is a
        # module-scope constant set once at process start, so the UI keeps
        # hiding this action until the server restarts even though a retry
        # here would now succeed. Tell the operator both things.
        raise HTTPException(status_code=400,
                            detail="send2trash ships with Facet — upgrade the image or run pip install send2trash, "
                                    "then restart the server so the UI stops hiding this option")
    if body.dry_run:
        return respond(True, [], would_trash=files)
    trashed = errors = 0
    succeeded = set()
    for src in files:
        try:
            send2trash.send2trash(src)
            trashed += 1
            succeeded.add(src)
        except OSError:
            logger.exception("Failed to trash %s", src)
            errors += 1
    _reassign_dead_leads_after_removal(items, succeeded, user_id)
    return respond(False, errors, trashed=trashed)


def _validate_target_dir_required(target_dir):
    """Like _validate_target_dir but 400s on a missing target_dir first."""
    if not target_dir:
        raise HTTPException(status_code=400, detail="target_dir is required for this action")
    return _validate_target_dir(target_dir)


@router.post("/api/albums/{album_id}/export")
def api_album_export(
    album_id: int,
    body: AlbumExportRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Basket export: an album's photos as sidecars, or copied/symlinked out."""
    if body.mode in ("copy", "symlink") and not body.target_dir:
        raise HTTPException(status_code=400, detail="target_dir is required for copy/symlink mode")

    user_id = user.user_id
    with get_db() as conn:
        paths = _album_photo_paths(conn, album_id, user_id)
        if body.mode == "sidecars":
            result = _write_sidecars_for_paths(conn, paths, user_id, body.overwrite)
            result["mode"] = "sidecars"
            return result

    # copy / symlink: validate the destination, then do file ops outside the DB.
    safe_target = _validate_target_dir(body.target_dir)
    copied, skipped, errors = _copy_or_link_into(paths, safe_target, body.mode)
    return {
        "ok": True,
        "mode": body.mode,
        "target_dir": safe_target,
        "copied": copied,
        "skipped": skipped,
        "errors": errors,
    }
