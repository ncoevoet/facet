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
from api.database import get_db
from api.db_helpers import (
    get_photos_from_clause,
    get_preference_columns,
    get_visibility_clause,
)
from api.path_validation import resolve_photo_disk_path
from processing.xmp_export import XmpRating, write_sidecar

logger = logging.getLogger(__name__)

router = APIRouter(tags=["export"])


# --- Request models ---

class ExportXmpRequest(BaseModel):
    path: str
    overwrite: bool = False


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
    rows = conn.execute(
        f"SELECT photos.path FROM {from_clause}{where_str}",
        from_params + sql_params,
    ).fetchall()
    return [row["path"] for row in rows]


def _write_sidecars_for_paths(conn, paths, user_id, overwrite):
    """Write sidecars for every visible path; return a counts dict."""
    rating_rows = _fetch_rating_rows(conn, paths, user_id)
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
            result = write_sidecar(real_disk, XmpRating.from_row(row), overwrite=overwrite)
            written += 1
            sidecars.append(result["sidecar"])
        except OSError:
            logger.exception("Failed to write XMP sidecar for %s", path)
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


def _copy_or_link_into(paths, target_dir, mode):
    """Copy or symlink each resolved photo into ``target_dir``.

    Filenames that collide get a numeric suffix so selects aren't overwritten.
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
    """Return a non-colliding destination path inside ``target_dir``."""
    dest = os.path.join(target_dir, filename)
    if not os.path.exists(dest):
        return dest
    stem, ext = os.path.splitext(filename)
    i = 1
    while True:
        candidate = os.path.join(target_dir, f"{stem}_{i}{ext}")
        if not os.path.exists(candidate):
            return candidate
        i += 1


# --- Endpoints ---

@router.post("/api/photo/export_xmp")
def api_export_xmp(
    body: ExportXmpRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Write a single XMP sidecar next to a photo."""
    if not body.path:
        raise HTTPException(status_code=400, detail="path required")

    user_id = user.user_id
    with get_db() as conn:
        rating_rows = _fetch_rating_rows(conn, [body.path], user_id)

    row = rating_rows.get(body.path)
    if row is None:
        raise HTTPException(status_code=404, detail="File not found")

    real_disk = resolve_photo_disk_path(body.path)
    try:
        result = write_sidecar(real_disk, XmpRating.from_row(row), overwrite=body.overwrite)
    except OSError:
        logger.exception("Failed to write XMP sidecar for %s", body.path)
        raise HTTPException(status_code=500, detail="Failed to write sidecar")
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

    # copy / symlink: file ops happen outside the DB connection.
    copied, skipped, errors = _copy_or_link_into(paths, body.target_dir, body.mode)
    return {
        "ok": True,
        "mode": body.mode,
        "target_dir": body.target_dir,
        "copied": copied,
        "skipped": skipped,
        "errors": errors,
    }
