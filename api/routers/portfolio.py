"""Static portfolio export endpoint (edition-gated).

``POST /api/albums/{album_id}/export-portfolio`` renders an album into a
self-contained static HTML gallery (see ``processing.portfolio_export``) inside a
caller-provided ``target_dir``. The destination is validated against the exact
same allow-list as the other copy/move export endpoints
(``_validate_target_dir_required`` from ``api.routers.export``), album access is
checked with the shared ``_check_album_access`` helper, and the work is bounded by
``portfolio.max_photos`` so a huge album cannot block the event loop.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import CurrentUser, require_edition
from api.config import VIEWER_CONFIG
from api.database import get_db
from api.db_helpers import get_visibility_clause
from api.path_validation import resolve_photo_disk_path
from api.routers.albums import _check_album_access
from api.routers.export import _validate_target_dir_required
from processing.portfolio_export import PortfolioOptions, export_portfolio

logger = logging.getLogger(__name__)

router = APIRouter(tags=["portfolio"])

_DEFAULT_MAX_PHOTOS = 500
_DEFAULT_MAX_EDGE = 2048
_DEFAULT_JPEG_QUALITY = 88
_MIN_EDGE = 256
_MAX_EDGE = 8000


class PortfolioExportRequest(BaseModel):
    target_dir: str = Field(..., min_length=1)
    title: Optional[str] = None
    max_edge: Optional[int] = None
    include_captions: bool = True


def _require_portfolio_enabled():
    if not VIEWER_CONFIG.get("features", {}).get("show_portfolio_export", True):
        raise HTTPException(status_code=404, detail="Portfolio export is disabled")


def _portfolio_config() -> dict:
    from api.config import _FULL_CONFIG

    return _FULL_CONFIG.get("portfolio", {}) or {}


def _album_photo_rows(conn, album_id, user_id):
    """Fetch ordered album rows carrying the fields the generator needs."""
    vis_sql, vis_params = get_visibility_clause(user_id)
    return conn.execute(
        "SELECT photos.path AS path, photos.caption AS caption, "
        "photos.date_taken AS date_taken, photos.thumbnail AS thumbnail "
        "FROM album_photos ap "
        "JOIN photos ON photos.path = ap.photo_path "
        f"WHERE ap.album_id = ? AND {vis_sql} "
        "ORDER BY ap.position ASC",
        [album_id] + vis_params,
    ).fetchall()


def _resolve_generator_row(row):
    """Build a generator row: resolved disk path (or None) + caption/date/thumbnail."""
    try:
        disk_path = resolve_photo_disk_path(row["path"])
    except HTTPException:
        disk_path = None
    return {
        "path": disk_path,
        "caption": row["caption"],
        "date": row["date_taken"],
        "thumbnail": row["thumbnail"],
    }


@router.post("/api/albums/{album_id}/export-portfolio")
def api_export_portfolio(
    album_id: int,
    body: PortfolioExportRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Export an album as a self-contained static HTML gallery into ``target_dir``."""
    _require_portfolio_enabled()
    safe_target = _validate_target_dir_required(body.target_dir)

    cfg = _portfolio_config()
    max_photos = int(cfg.get("max_photos", _DEFAULT_MAX_PHOTOS))
    config_edge = int(cfg.get("max_edge", _DEFAULT_MAX_EDGE))
    jpeg_quality = int(cfg.get("jpeg_quality", _DEFAULT_JPEG_QUALITY))
    max_edge = max(_MIN_EDGE, min(int(body.max_edge or config_edge), _MAX_EDGE))

    user_id = user.user_id
    with get_db() as conn:
        album = _check_album_access(conn, album_id, user_id)
        rows = _album_photo_rows(conn, album_id, user_id)
        if len(rows) > max_photos:
            raise HTTPException(
                status_code=400,
                detail=f"Album has {len(rows)} photos, over the {max_photos} portfolio limit",
            )
        generator_rows = [_resolve_generator_row(row) for row in rows]

    options = PortfolioOptions(
        title=(body.title or album["name"] or "Portfolio"),
        subtitle=(album["description"] or ""),
        max_edge=max_edge,
        jpeg_quality=jpeg_quality,
        include_captions=body.include_captions,
    )
    return export_portfolio(generator_rows, safe_target, options)
