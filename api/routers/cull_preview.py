"""Edited-look cull-preview endpoint.

``GET /api/photo/cull_preview`` renders a photo's original through a named
darktable style so the user culls on the developed look rather than the flat
preview. It reuses the download path's darktable-cli machinery
(``api.raw_processing``) and caches rendered JPEGs on disk keyed by the source
file's mtime, style and max edge, so a repeat request never re-runs the CLI.
"""

import hashlib
import logging
import os
import subprocess
import tempfile

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response

from api.auth import CurrentUser, require_edition
from api.config import VIEWER_CONFIG
from api.database import get_db
from api.db_helpers import get_visibility_clause
from api.path_validation import resolve_photo_disk_path
from api.raw_processing import (
    DEFAULT_CULL_PREVIEW_MAX_EDGE,
    DEFAULT_CULL_PREVIEW_TIMEOUT_SECONDS,
    get_cull_style_names,
    is_darktable_available,
    render_cull_preview,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["cull_preview"])

CACHE_SUBDIR = os.path.join(".facet_cache", "cull_previews")
_CACHE_CONTROL = "private, max-age=3600"

_CULL_CACHE_MAX_BYTES = 500 * 1024 * 1024
_CULL_CACHE_MAX_AGE_SECONDS = 30 * 24 * 3600


def _get_darktable_config() -> dict:
    return (VIEWER_CONFIG.get("raw_processor", {}) or {}).get("darktable", {}) or {}


def _cull_cache_dir() -> str:
    """Cache directory alongside the database (``<db_dir>/.facet_cache/cull_previews``)."""
    from db.connection import DEFAULT_DB_PATH

    base = os.path.dirname(os.path.abspath(DEFAULT_DB_PATH))
    return os.path.join(base, CACHE_SUBDIR)


def _cache_path(disk_path: str, mtime: float, style: str, max_edge: int) -> str:
    raw = f"{disk_path}\x00{mtime}\x00{style}\x00{max_edge}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return os.path.join(_cull_cache_dir(), digest + ".jpg")


def _trim_cache(cache_dir: str) -> None:
    """Evict expired then over-budget entries (mtime-LRU) after a cache write.

    Mirrors the companion-RAW cache bounds in ``api.raw_processing``: drop
    files older than ``_CULL_CACHE_MAX_AGE_SECONDS``, then remove the oldest
    until the total is under ``_CULL_CACHE_MAX_BYTES``. Files that vanish
    mid-scan (a concurrent request) are skipped.
    """
    import time

    try:
        names = os.listdir(cache_dir)
    except OSError:
        return

    now = time.time()
    entries = []
    for name in names:
        if not name.endswith(".jpg"):
            continue
        fpath = os.path.join(cache_dir, name)
        try:
            stat = os.stat(fpath)
        except OSError:
            continue
        if now - stat.st_mtime > _CULL_CACHE_MAX_AGE_SECONDS:
            try:
                os.unlink(fpath)
            except OSError:
                pass
            continue
        entries.append((stat.st_mtime, stat.st_size, fpath))

    total = sum(size for _mtime, size, _fpath in entries)
    if total <= _CULL_CACHE_MAX_BYTES:
        return

    entries.sort(key=lambda entry: entry[0])
    for _mtime, size, fpath in entries:
        if total <= _CULL_CACHE_MAX_BYTES:
            break
        try:
            os.unlink(fpath)
            total -= size
        except OSError:
            pass


def _write_cache(cache_path: str, data: bytes) -> bool:
    """Write ``data`` to ``cache_path`` atomically; return ``False`` on any I/O error."""
    try:
        cache_dir = os.path.dirname(cache_path)
        os.makedirs(cache_dir, exist_ok=True)
        fd, tmp = tempfile.mkstemp(suffix=".jpg", dir=cache_dir)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, cache_path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        _trim_cache(cache_dir)
        return True
    except OSError:
        logger.warning("Failed to write cull-preview cache at %s", cache_path, exc_info=True)
        return False


@router.get("/api/photo/cull_preview")
def api_cull_preview(
    path: str = Query(...),
    style: str = Query(...),
    user: CurrentUser = Depends(require_edition),
):
    """Render a photo's original through a configured darktable style (cached JPEG).

    ``style`` must be one of the configured ``cull_styles`` (400 otherwise). The
    original is resolved through the same DB-visibility + scan-dir allowlist as
    sibling photo endpoints. Failure mapping: darktable-cli missing -> 503,
    unreadable original -> 404, CLI timeout/error -> 502.
    """
    if not style or style not in get_cull_style_names():
        raise HTTPException(status_code=400, detail="Unknown cull style")
    if not is_darktable_available():
        raise HTTPException(status_code=503, detail="darktable-cli is not available")

    vis_sql, vis_params = get_visibility_clause(user.user_id if user else None)
    with get_db() as conn:
        row = conn.execute(
            f"SELECT path FROM photos WHERE path = ? AND {vis_sql}",
            [path] + vis_params,
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="File not found")

    real_disk = resolve_photo_disk_path(row["path"])

    dt_cfg = _get_darktable_config()
    max_edge = int(dt_cfg.get("preview_max_edge", DEFAULT_CULL_PREVIEW_MAX_EDGE))
    timeout = int(dt_cfg.get("preview_timeout_seconds", DEFAULT_CULL_PREVIEW_TIMEOUT_SECONDS))
    quality = int(VIEWER_CONFIG.get("display", {}).get("image_jpeg_quality", 96))

    try:
        mtime = os.path.getmtime(real_disk)
    except OSError:
        raise HTTPException(status_code=404, detail="File not found on disk")

    cache_path = _cache_path(real_disk, mtime, style, max_edge)
    if os.path.isfile(cache_path) and os.path.getsize(cache_path) > 0:
        return FileResponse(cache_path, media_type="image/jpeg",
                            headers={"Cache-Control": _CACHE_CONTROL})

    try:
        jpeg = render_cull_preview(real_disk, style, max_edge, quality, timeout)
    except subprocess.TimeoutExpired:
        logger.warning("Cull preview timed out for %s (style=%s)", real_disk, style)
        raise HTTPException(status_code=502, detail="darktable render timed out")
    except RuntimeError as ex:
        summary = str(ex).replace(real_disk, os.path.basename(real_disk))[:300]
        logger.warning("Cull preview render failed for %s: %s", real_disk, ex)
        raise HTTPException(status_code=502, detail=f"darktable render failed: {summary}")

    if _write_cache(cache_path, jpeg):
        return FileResponse(cache_path, media_type="image/jpeg",
                            headers={"Cache-Control": _CACHE_CONTROL})
    return Response(content=jpeg, media_type="image/jpeg",
                    headers={"Cache-Control": _CACHE_CONTROL})
