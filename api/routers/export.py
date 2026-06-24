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
from pydantic import BaseModel, Field

from api.auth import CurrentUser, require_edition
from api.config import VIEWER_CONFIG, get_all_scan_directories
from api.database import get_db
from api.db_helpers import (
    get_photos_from_clause,
    get_preference_columns,
    get_visibility_clause,
)
from api.path_validation import resolve_photo_disk_path
from processing.xmp_export import (
    FaceRegion,
    XmpRating,
    person_names_from_regions,
    write_metadata,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["export"])


# --- Request models ---

class ExportXmpRequest(BaseModel):
    path: str
    overwrite: bool = False


class EmbedMetadataRequest(BaseModel):
    path: str


class ExportSidecarsRequest(BaseModel):
    paths: Optional[list[str]] = Field(default=None, max_length=10000)
    filters: Optional[dict] = None
    overwrite: bool = False


class AlbumExportRequest(BaseModel):
    mode: Literal["sidecars", "copy", "symlink"] = "sidecars"
    target_dir: Optional[str] = None
    overwrite: bool = False


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


def _resolve_filter_paths(conn, filters, user_id):
    """Resolve a gallery filter set to a list of photo paths."""
    from api.routers.gallery import _build_gallery_where

    where_clauses, sql_params = _build_gallery_where(filters or {}, conn, user_id=user_id)
    from_clause, from_params = get_photos_from_clause(user_id)
    where_str = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    # Parameterized: from_clause is a fixed string and every where clause built by
    # _build_gallery_where carries only ? placeholders (all user values bound in
    # sql_params); no raw value or column name is ever interpolated. Same assembly
    # as the main gallery list endpoint (gallery.py).
    rows = conn.execute(
        f"SELECT photos.path FROM {from_clause}{where_str}",
        from_params + sql_params,
    ).fetchall()
    return [row["path"] for row in rows]


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
    host location (path traversal / symlink planting). Fail-closed: if no roots
    are configured, copy/symlink export is refused rather than writing anywhere.
    """
    real = os.path.realpath(target_dir)
    roots = _allowed_export_roots()
    if not roots:
        raise HTTPException(
            status_code=403,
            detail="Copy/symlink export is disabled — configure viewer.export.allowed_target_dirs",
        )
    if not any(real == r or real.startswith(r + os.sep) for r in roots):
        raise HTTPException(status_code=403, detail="target_dir is not an allowed export location")
    return real


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
    if not body.paths and body.filters is None:
        raise HTTPException(status_code=400, detail="Either paths or filters is required")

    user_id = user.user_id
    with get_db() as conn:
        if body.paths:
            paths = body.paths
        else:
            paths = _resolve_filter_paths(conn, body.filters, user_id)
        return _write_sidecars_for_paths(conn, paths, user_id, body.overwrite)


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
