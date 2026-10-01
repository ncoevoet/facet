"""Manual (user-authored) photo tags: write endpoints.

Tags live in the ``photo_manual_tags`` side table (never on ``photos``, which a
rescan rewrites). Edition-gated like every other write; tags are global in
multi-user mode, ``created_by`` only records who wrote them. Readers UNION this
table with the AI tags at read time, so a write only has to drop the cached tag
dropdown (both cache layers).
"""

import logging
import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from api.auth import CurrentUser, require_edition
from api.config import invalidate_stats_cache, is_multi_user_enabled
from api.database import get_db
from api.db_helpers import is_locked_error, retry_on_locked
from api.models.manual_tags import (
    BatchManualTagRequest, BatchManualTagResponse, ManualTagDeleteResponse,
    ManualTagRequest, ManualTagResponse,
)
from api.routers.faces import _batch_scope_sql, _require_writable_photo, _writable_photo_paths
from db.manual_tags import (
    MAX_TAGS_PER_PHOTO, SOURCE_USER, ManualTagError, ai_tag_absent_sql,
    delete_manual_tag, insert_manual_tag, is_ai_tag,
    normalize_manual_tag,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["manual_tags"])


def _normalized(tag):
    try:
        return normalize_manual_tag(tag)
    except ManualTagError as ex:
        raise HTTPException(status_code=422, detail=str(ex)) from None


def _created_by(user):
    return user.user_id if user and is_multi_user_enabled() else None


def _drop_tag_caches(conn):
    """Clear the DB-persisted tag dropdown row, then the in-process stats cache."""
    conn.execute("DELETE FROM stats_cache WHERE key = 'tags'")


def _after_commit():
    invalidate_stats_cache()


@router.put("/api/photo/manual_tags", response_model=ManualTagResponse)
@retry_on_locked()
def api_add_manual_tag(
    body: ManualTagRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Add one manual tag to a photo (no-op when it equals an existing AI tag)."""
    tag = _normalized(body.tag)
    with get_db() as conn:
        try:
            _require_writable_photo(conn, user, body.path)
            ai_tags = conn.execute(
                "SELECT tags FROM photos WHERE path = ?", (body.path,)
            ).fetchone()[0]
            if is_ai_tag(ai_tags, tag):
                return {"success": True, "tag": tag, "skipped_existing": True}
            if not insert_manual_tag(conn, body.path, tag, SOURCE_USER, _created_by(user)):
                # Not written: either the photo already has the tag (idempotent
                # success) or it is at the cap.
                if conn.execute(
                    "SELECT 1 FROM photo_manual_tags WHERE photo_path = ? AND tag = ?",
                    (body.path, tag),
                ).fetchone():
                    return {"success": True, "tag": tag, "skipped_existing": False}
                raise HTTPException(
                    status_code=422,
                    detail=f"a photo can carry at most {MAX_TAGS_PER_PHOTO} manual tags",
                )
            _drop_tag_caches(conn)
            conn.commit()
        except HTTPException:
            raise
        except sqlite3.Error as ex:
            conn.rollback()
            if is_locked_error(ex):
                raise
            logger.exception("Database error adding manual tag")
            raise HTTPException(status_code=500, detail='Internal server error')
    _after_commit()
    return {"success": True, "tag": tag, "skipped_existing": False}


@router.delete("/api/photo/manual_tags", response_model=ManualTagDeleteResponse)
@retry_on_locked()
def api_delete_manual_tag(
    body: ManualTagRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Remove one manual tag from a photo, whichever import wrote it."""
    tag = _normalized(body.tag)
    with get_db() as conn:
        try:
            _require_writable_photo(conn, user, body.path)
            removed = delete_manual_tag(conn, body.path, tag)
            if removed:
                _drop_tag_caches(conn)
            conn.commit()
        except HTTPException:
            raise
        except sqlite3.Error as ex:
            conn.rollback()
            if is_locked_error(ex):
                raise
            logger.exception("Database error deleting manual tag")
            raise HTTPException(status_code=500, detail='Internal server error')
    if removed:
        _after_commit()
    return {"success": True, "tag": tag, "removed": removed}


@router.post("/api/photos/batch_manual_tags", response_model=BatchManualTagResponse)
@retry_on_locked()
def api_batch_manual_tags(
    body: BatchManualTagRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Add or remove one manual tag across named paths or a gallery view.

    ``count`` is the rows actually written or removed: unwritable paths are
    dropped, an at-cap photo and a photo whose AI tags already hold the tag are
    skipped inside the INSERT, and a photo that already has the tag is not
    counted.
    """
    tag = _normalized(body.tag)
    if body.filters is None and not body.photo_paths:
        return {"success": True, "count": 0}
    with get_db() as conn:
        try:
            if body.filters is not None:
                from_clause, where_str, scope_params = _batch_scope_sql(conn, body, user)
                scope = f"{from_clause}{where_str}"
            else:
                excluded = set(body.exclude or ())
                paths = _writable_photo_paths(
                    conn, user, [p for p in body.photo_paths if p not in excluded]
                )
                if not paths:
                    return {"success": True, "count": 0}
                scope = f"photos WHERE photos.path IN ({','.join('?' * len(paths))})"
                scope_params = paths
            if body.action == 'add':
                absent_sql, absent_params = ai_tag_absent_sql(tag)
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO photo_manual_tags "
                    "(photo_path, tag, source, created_by, created_at) "
                    f"SELECT photos.path, ?, ?, ?, datetime('now') FROM {scope} "
                    f"AND {absent_sql} "
                    "AND (SELECT COUNT(*) FROM photo_manual_tags pmt "
                    "WHERE pmt.photo_path = photos.path) < ?",
                    [tag, SOURCE_USER, _created_by(user), *scope_params,
                     *absent_params, MAX_TAGS_PER_PHOTO],
                )
            else:
                cursor = conn.execute(
                    "DELETE FROM photo_manual_tags WHERE tag = ? AND photo_path IN "
                    f"(SELECT photos.path FROM {scope})",
                    [tag, *scope_params],
                )
            count = cursor.rowcount
            _drop_tag_caches(conn)
            conn.commit()
        except HTTPException:
            raise
        except sqlite3.Error as ex:
            conn.rollback()
            if is_locked_error(ex):
                raise
            logger.exception("Database error in batch manual tags")
            raise HTTPException(status_code=500, detail='Internal server error')
    _after_commit()
    return {"success": True, "count": count}
