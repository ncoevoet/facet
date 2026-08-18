"""
Faces API router — face management, rating, favorites, rejected.

"""

import logging
import os
import sqlite3
import threading

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import CurrentUser, require_edition, require_auth
from api.config import is_multi_user_enabled, _stats_cache
from api.database import get_async_db, get_db
from api.db_helpers import (
    update_person_face_count, trigger_auto_retrain, get_visibility_clause,
    assert_faces_visible, assert_photo_visible, repair_stale_representative,
    is_locked_error, retry_on_locked, select_in_chunks,
)
from api.types import JUNK_NOT_JUNK
from api.models.culling import (
    PersonFacesResponse, PhotoFacesResponse, ToggleFavoriteResponse, ToggleRejectedResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["faces"])


class AvatarRequest(BaseModel):
    face_id: int


class AssignFaceRequest(BaseModel):
    person_id: int


class AssignAllFacesRequest(BaseModel):
    photo_path: str
    person_id: int


class UnassignPersonRequest(BaseModel):
    photo_path: str
    person_id: int


class SetRatingRequest(BaseModel):
    photo_path: str
    rating: int = Field(ge=0, le=5)


class TogglePhotoRequest(BaseModel):
    photo_path: str


class BatchPhotoRequest(BaseModel):
    photo_paths: list[str] = Field(max_length=1000)


class BatchRatingRequest(BaseModel):
    photo_paths: list[str] = Field(max_length=1000)
    rating: int = Field(ge=0, le=5)


def _require_writable_photo(conn, user, photo_path):
    """404 unless ``photo_path`` exists AND this caller may write it.

    Both halves are load-bearing and neither replaces the other:

    * ``assert_photo_visible`` is a no-op outside multi-user mode, so on a
      single-user install it says nothing about existence — and an
      ``UPDATE photos ... WHERE path = ?`` against an unknown path matches zero
      rows, which the handlers would otherwise report as success.
    * a bare existence probe answers for every tenant's library, turning the
      404 into a per-path existence oracle — and lets the handler write a
      ``user_preferences`` row for a photo the caller cannot see.

    Both failure modes collapse onto the same 404, so "absent" and "not yours"
    stay indistinguishable.
    """
    try:
        assert_photo_visible(conn, user.user_id if user else None, photo_path)
    except LookupError:
        raise HTTPException(status_code=404, detail="Photo not found") from None
    if not conn.execute("SELECT 1 FROM photos WHERE path = ?", (photo_path,)).fetchone():
        raise HTTPException(status_code=404, detail="Photo not found")


def _writable_photo_paths(conn, user, photo_paths):
    """Return the subset of ``photo_paths`` that exists AND this caller may write.

    The batch twin of :func:`_require_writable_photo`, and it drops rather than
    raises: a batch cannot answer 404 for one bad path out of a thousand without
    discarding the 999 good ones, and answering differently per path is the same
    existence oracle the single-photo guard exists to close. Callers report the
    count actually written instead, so an unwritable path is indistinguishable
    from an absent one.

    One query does both halves. Existence alone is not enough — it writes
    ``user_preferences`` rows for other tenants' photos — and the visibility
    clause alone is not enough either, because it is ``1=1`` outside multi-user
    mode and so says nothing about whether the row is there.

    Duplicates are collapsed, so ``count`` cannot exceed the number of distinct
    photos the write touched.
    """
    if not photo_paths:
        return []
    vis_sql, vis_params = get_visibility_clause(user.user_id if user else None)
    writable = {
        row[0]
        for row in select_in_chunks(
            conn,
            f"SELECT path FROM photos WHERE path IN ({{placeholders}}) AND {vis_sql}",
            photo_paths,
            after=vis_params,
        )
    }
    return [path for path in dict.fromkeys(photo_paths) if path in writable]


@router.get("/api/person/{person_id}/faces", response_model=PersonFacesResponse, response_model_exclude_unset=True)
async def api_person_faces(
    person_id: int,
    user: CurrentUser = Depends(require_auth),
):
    """Get all faces belonging to a person."""
    vis_sql, vis_params = get_visibility_clause(user.user_id if user else None, table_alias='p')
    async with get_async_db() as conn:
        cur = await conn.execute(f"""
            SELECT f.id, f.photo_path, f.face_index, f.bbox_x1, f.bbox_y1, f.bbox_x2, f.bbox_y2
            FROM faces f
            LEFT JOIN photos p ON f.photo_path = p.path
            WHERE f.person_id = ? AND {vis_sql}
            ORDER BY p.aggregate DESC
            LIMIT 36
        """, [person_id, *vis_params])
        faces = await cur.fetchall()
        await cur.close()
        return {'faces': [dict(f) for f in faces]}


@router.post("/api/person/{person_id}/avatar")
def api_set_person_avatar(
    person_id: int,
    body: AvatarRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Set a face as the representative avatar for a person."""
    with get_db() as conn:
        try:
            face = conn.execute("""
                SELECT id, face_thumbnail FROM faces WHERE id = ? AND person_id = ?
            """, (body.face_id, person_id)).fetchone()

            if not face:
                raise HTTPException(status_code=404, detail="Face not found or does not belong to this person")

            conn.execute("""
                UPDATE persons SET representative_face_id = ?, face_thumbnail = ?
                WHERE id = ?
            """, (body.face_id, face['face_thumbnail'], person_id))

            conn.commit()

            return {'success': True}
        except HTTPException:
            raise
        except sqlite3.Error:
            logger.exception("Database error setting person avatar %d", person_id)
            conn.rollback()
            raise HTTPException(status_code=500, detail='Internal server error')


@router.get("/api/photo/faces", response_model=PhotoFacesResponse, response_model_exclude_unset=True)
async def api_photo_faces(
    path: str,
    user: CurrentUser = Depends(require_auth),
):
    """Get all faces in a photo with their current person assignment."""
    vis_sql, vis_params = get_visibility_clause(user.user_id if user else None)
    async with get_async_db() as conn:
        cur = await conn.execute(
            f"SELECT 1 FROM photos WHERE path = ? AND {vis_sql}", [path, *vis_params]
        )
        visible = await cur.fetchone()
        await cur.close()
        if not visible:
            return {'faces': []}

        cur = await conn.execute("""
            SELECT f.id, f.face_index, f.bbox_x1, f.bbox_y1, f.bbox_x2, f.bbox_y2,
                   f.person_id, p.name as person_name
            FROM faces f
            LEFT JOIN persons p ON f.person_id = p.id
            WHERE f.photo_path = ?
            ORDER BY f.face_index
        """, (path,))
        faces = await cur.fetchall()
        await cur.close()
        return {'faces': [dict(f) for f in faces]}


@router.post("/api/face/{face_id}/assign")
def api_assign_face(
    face_id: int,
    body: AssignFaceRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Assign a face to a person."""
    with get_db() as conn:
        try:
            face = conn.execute("SELECT person_id FROM faces WHERE id = ?", (face_id,)).fetchone()
            if not face:
                raise HTTPException(status_code=404, detail="Face not found")

            assert_faces_visible(conn, user.user_id if user else None, [face_id])

            if not conn.execute("SELECT 1 FROM persons WHERE id = ?", (body.person_id,)).fetchone():
                raise HTTPException(status_code=404, detail="Target person not found")

            old_person_id = face['person_id']
            conn.execute("UPDATE faces SET person_id = ? WHERE id = ?", (body.person_id, face_id))

            if old_person_id:
                update_person_face_count(conn, old_person_id)
                repair_stale_representative(conn, old_person_id)
            update_person_face_count(conn, body.person_id)

            conn.commit()

            return {'success': True}
        except LookupError:
            conn.rollback()
            raise HTTPException(status_code=404, detail="Face not found")
        except HTTPException:
            raise
        except sqlite3.Error:
            logger.exception("Database error assigning face %d", face_id)
            conn.rollback()
            raise HTTPException(status_code=500, detail='Internal server error')


@router.post("/api/photo/assign_all_faces")
def api_assign_all_faces(
    body: AssignAllFacesRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Assign all unassigned faces in a photo to a person."""
    with get_db() as conn:
        try:
            assert_photo_visible(conn, user.user_id if user else None, body.photo_path)

            # faces.person_id has no FK, so a stale target id would strand the
            # faces on a dangling person. Validate the target exists first.
            if not conn.execute(
                "SELECT 1 FROM persons WHERE id = ?", (body.person_id,)
            ).fetchone():
                raise HTTPException(status_code=404, detail="Target person not found")

            faces = conn.execute("""
                SELECT id FROM faces WHERE photo_path = ? AND person_id IS NULL
            """, (body.photo_path,)).fetchall()

            if not faces:
                raise HTTPException(status_code=404, detail="No unassigned faces found")

            face_ids = [f['id'] for f in faces]
            placeholders = ','.join('?' * len(face_ids))
            conn.execute(f"""
                UPDATE faces SET person_id = ? WHERE id IN ({placeholders})
            """, [body.person_id] + face_ids)

            update_person_face_count(conn, body.person_id)

            conn.commit()

            return {'success': True, 'assigned_count': len(face_ids)}
        except LookupError:
            conn.rollback()
            raise HTTPException(status_code=404, detail="No unassigned faces found")
        except HTTPException:
            raise
        except sqlite3.Error:
            logger.exception("Database error assigning all faces for photo %s", body.photo_path)
            conn.rollback()
            raise HTTPException(status_code=500, detail='Internal server error')


@router.post("/api/photo/unassign_person")
def api_unassign_person(
    body: UnassignPersonRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Unassign all faces of a specific person from a photo."""
    with get_db() as conn:
        try:
            # A directory-scoped edition user must not detach faces on a photo
            # outside their directories (and thereby empty/delete a person the
            # global gallery still shows). Gate on photo visibility first.
            assert_photo_visible(conn, user.user_id if user else None, body.photo_path)

            faces = conn.execute("""
                SELECT id FROM faces
                WHERE photo_path = ? AND person_id = ?
            """, (body.photo_path, body.person_id)).fetchall()

            if not faces:
                raise HTTPException(status_code=404, detail="No faces found")

            conn.execute("""
                UPDATE faces SET person_id = NULL
                WHERE photo_path = ? AND person_id = ?
            """, (body.photo_path, body.person_id))

            update_person_face_count(conn, body.person_id)

            new_count = conn.execute(
                "SELECT face_count FROM persons WHERE id = ?",
                (body.person_id,)
            ).fetchone()

            person_deleted = False
            if new_count and new_count[0] == 0:
                conn.execute("DELETE FROM persons WHERE id = ?", (body.person_id,))
                person_deleted = True
            else:
                # The detached faces may have included this person's stored
                # representative; repoint it at a remaining face.
                repair_stale_representative(conn, body.person_id)

            conn.commit()

            return {
                'success': True,
                'unassigned_count': len(faces),
                'person_deleted': person_deleted
            }
        except LookupError:
            conn.rollback()
            raise HTTPException(status_code=404, detail="No faces found")
        except HTTPException:
            raise
        except sqlite3.Error:
            logger.exception("Database error unassigning person %d from photo %s", body.person_id, body.photo_path)
            conn.rollback()
            raise HTTPException(status_code=500, detail='Internal server error')


# --- Debounced rating-derived comparison sync ---------------------------------
# sync_label_comparisons rebuilds ALL source='rating' pairs from scratch (a full
# DELETE + regenerate over every labelled photo), so firing it on every click is
# O(all-labels) wasted work when a user rates a batch in quick succession. We
# coalesce: each rating change (re)schedules a single rebuild a short debounce
# after the last change, per user scope. Set FACET_RATING_SYNC_DEBOUNCE_S=0 to
# run inline (used by tests).
try:
    _RATING_SYNC_DEBOUNCE_S = float(os.environ.get("FACET_RATING_SYNC_DEBOUNCE_S", "3") or 0)
except ValueError:
    _RATING_SYNC_DEBOUNCE_S = 3.0
_rating_sync_lock = threading.Lock()
_rating_sync_timers = {}  # scope (user_id or None) -> (Timer, db_path)


def _run_rating_sync(db_path, scope):
    """Rebuild source='rating' pairs for one scope. Best-effort: never raises."""
    with _rating_sync_lock:
        _rating_sync_timers.pop(scope, None)
    try:
        from optimization.label_pairs import sync_label_comparisons
        sync_label_comparisons(db_path, user_id=scope)
    except (sqlite3.Error, ImportError):
        logger.warning("Failed to sync rating-derived comparisons", exc_info=True)


def _mint_rating_comparisons(user_id):
    """Schedule a debounced rebuild of source='rating' comparison pairs.

    Closes the label gap so star ratings / favorites / rejections become training
    signal for the weight optimizer and personal ranker (Topic 1 step 7) without a
    manual --sync-label-comparisons. Coalesces rapid clicks into one rebuild; the
    rating write has already succeeded and must never be rolled back by this.

    Also feeds the per-user auto-retrain counter: a rating change is one new
    comparison-worth of taste signal, so once enough accumulate the personal
    ranker retrains itself in the background (non-blocking, held-out gated).
    """
    from db import DEFAULT_DB_PATH
    scope = user_id if (user_id and is_multi_user_enabled()) else None
    db_path = DEFAULT_DB_PATH
    trigger_auto_retrain(db_path, user_id)
    if _RATING_SYNC_DEBOUNCE_S <= 0:
        _run_rating_sync(db_path, scope)
        return
    with _rating_sync_lock:
        existing = _rating_sync_timers.get(scope)
        if existing is not None:
            existing[0].cancel()
        timer = threading.Timer(_RATING_SYNC_DEBOUNCE_S, _run_rating_sync, args=(db_path, scope))
        timer.daemon = True
        _rating_sync_timers[scope] = (timer, db_path)
        timer.start()


def flush_rating_comparisons():
    """Run any pending debounced rating syncs immediately (tests / shutdown)."""
    with _rating_sync_lock:
        pending = list(_rating_sync_timers.items())
        _rating_sync_timers.clear()
    for scope, (timer, db_path) in pending:
        timer.cancel()
        _run_rating_sync(db_path, scope)


@router.post("/api/photo/set_rating")
@retry_on_locked()
def api_set_rating(
    body: SetRatingRequest,
    user: CurrentUser = Depends(require_auth),
):
    """Set star rating (0-5) for a photo."""
    with get_db() as conn:
        try:
            _require_writable_photo(conn, user, body.photo_path)
            if user.user_id and is_multi_user_enabled():
                conn.execute("""
                    INSERT INTO user_preferences (user_id, photo_path, star_rating)
                    VALUES (?, ?, ?)
                    ON CONFLICT(user_id, photo_path) DO UPDATE SET star_rating = excluded.star_rating
                """, (user.user_id, body.photo_path, body.rating))
            else:
                conn.execute("UPDATE photos SET star_rating = ? WHERE path = ?", (body.rating, body.photo_path))
            conn.commit()
            _stats_cache.clear()
            _mint_rating_comparisons(user.user_id)
            return {'success': True, 'rating': body.rating}
        except sqlite3.Error as ex:
            conn.rollback()
            if is_locked_error(ex):
                raise
            logger.exception("Database error setting rating for photo %s", body.photo_path)
            raise HTTPException(status_code=500, detail='Internal server error')


@router.post("/api/photo/toggle_favorite", response_model=ToggleFavoriteResponse, response_model_exclude_unset=True)
@retry_on_locked()
def api_toggle_favorite(
    body: TogglePhotoRequest,
    user: CurrentUser = Depends(require_auth),
):
    """Toggle favorite flag for a photo."""
    with get_db() as conn:
        try:
            _require_writable_photo(conn, user, body.photo_path)
            if user.user_id and is_multi_user_enabled():
                row = conn.execute(
                    "SELECT is_favorite FROM user_preferences WHERE user_id = ? AND photo_path = ?",
                    (user.user_id, body.photo_path)
                ).fetchone()
                current = row['is_favorite'] if row else 0
                new_value = 0 if current else 1
                if new_value == 1:
                    conn.execute("""
                        INSERT INTO user_preferences (user_id, photo_path, is_favorite, is_rejected)
                        VALUES (?, ?, 1, 0)
                        ON CONFLICT(user_id, photo_path) DO UPDATE SET is_favorite = 1, is_rejected = 0
                    """, (user.user_id, body.photo_path))
                else:
                    conn.execute("""
                        INSERT INTO user_preferences (user_id, photo_path, is_favorite)
                        VALUES (?, ?, 0)
                        ON CONFLICT(user_id, photo_path) DO UPDATE SET is_favorite = 0
                    """, (user.user_id, body.photo_path))
            else:
                row = conn.execute("SELECT is_favorite FROM photos WHERE path = ?", (body.photo_path,)).fetchone()
                new_value = 0 if row['is_favorite'] else 1
                if new_value == 1:
                    conn.execute("UPDATE photos SET is_favorite = 1, is_rejected = 0 WHERE path = ?", (body.photo_path,))
                else:
                    conn.execute("UPDATE photos SET is_favorite = 0 WHERE path = ?", (body.photo_path,))
            conn.commit()
            _stats_cache.clear()
            _mint_rating_comparisons(user.user_id)
            return {'success': True, 'is_favorite': new_value == 1, 'is_rejected': False if new_value == 1 else None}
        except HTTPException:
            raise
        except sqlite3.Error as ex:
            conn.rollback()
            if is_locked_error(ex):
                raise
            logger.exception("Database error toggling favorite for photo %s", body.photo_path)
            raise HTTPException(status_code=500, detail='Internal server error')


@router.post("/api/photo/toggle_rejected", response_model=ToggleRejectedResponse, response_model_exclude_unset=True)
@retry_on_locked()
def api_toggle_rejected(
    body: TogglePhotoRequest,
    user: CurrentUser = Depends(require_auth),
):
    """Toggle rejected flag for a photo."""
    with get_db() as conn:
        try:
            _require_writable_photo(conn, user, body.photo_path)
            if user.user_id and is_multi_user_enabled():
                row = conn.execute(
                    "SELECT is_rejected FROM user_preferences WHERE user_id = ? AND photo_path = ?",
                    (user.user_id, body.photo_path)
                ).fetchone()
                current = row['is_rejected'] if row else 0
                new_value = 0 if current else 1
                if new_value == 1:
                    conn.execute("""
                        INSERT INTO user_preferences (user_id, photo_path, is_rejected, star_rating, is_favorite)
                        VALUES (?, ?, 1, 0, 0)
                        ON CONFLICT(user_id, photo_path) DO UPDATE SET is_rejected = 1, star_rating = 0, is_favorite = 0
                    """, (user.user_id, body.photo_path))
                else:
                    conn.execute("""
                        INSERT INTO user_preferences (user_id, photo_path, is_rejected)
                        VALUES (?, ?, 0)
                        ON CONFLICT(user_id, photo_path) DO UPDATE SET is_rejected = 0
                    """, (user.user_id, body.photo_path))
            else:
                row = conn.execute("SELECT is_rejected FROM photos WHERE path = ?", (body.photo_path,)).fetchone()
                new_value = 0 if row['is_rejected'] else 1
                if new_value == 1:
                    conn.execute("UPDATE photos SET is_rejected = 1, star_rating = 0, is_favorite = 0 WHERE path = ?", (body.photo_path,))
                else:
                    conn.execute("UPDATE photos SET is_rejected = 0 WHERE path = ?", (body.photo_path,))
            conn.commit()
            _stats_cache.clear()
            _mint_rating_comparisons(user.user_id)
            return {'success': True, 'is_rejected': new_value == 1, 'star_rating': 0 if new_value == 1 else None, 'is_favorite': False if new_value == 1 else None}
        except HTTPException:
            raise
        except sqlite3.Error as ex:
            conn.rollback()
            if is_locked_error(ex):
                raise
            logger.exception("Database error toggling rejected for photo %s", body.photo_path)
            raise HTTPException(status_code=500, detail='Internal server error')


@router.post("/api/photo/clear_junk")
@retry_on_locked()
def api_clear_junk(
    body: TogglePhotoRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Keep a junk-sweep candidate: mark it evaluated-clean so it leaves the queue.

    Sets junk_kind to the 'not_junk' sentinel (not NULL) so --detect-junk does
    not re-flag it on the next run. junk_kind is a global column (not per-user),
    so this is edition-gated like the batch actions.
    """
    with get_db() as conn:
        try:
            _require_writable_photo(conn, user, body.photo_path)
            conn.execute("UPDATE photos SET junk_kind = ? WHERE path = ?", (JUNK_NOT_JUNK, body.photo_path))
            conn.commit()
            _stats_cache.clear()
            return {'success': True, 'junk_kind': None}
        except HTTPException:
            raise
        except sqlite3.Error as ex:
            conn.rollback()
            if is_locked_error(ex):
                raise
            logger.exception("Database error clearing junk for photo %s", body.photo_path)
            raise HTTPException(status_code=500, detail='Internal server error')


@retry_on_locked()
def _batch_update(
    photo_paths: list[str],
    user: CurrentUser,
    multi_user_sql: str,
    multi_user_row,
    single_user_sql: str,
    single_user_prefix: tuple = (),
) -> dict:
    """Execute a batch update on photos with transaction and cache invalidation.

    ``count`` is the number of photos actually written, not the number asked
    for: :func:`_writable_photo_paths` drops the paths that do not exist or that
    this caller may not see. Writing them was two defects at once — a stale path
    made ``executemany`` raise a FOREIGN KEY ``IntegrityError`` that surfaced as
    a 500 and lost the whole batch, and in multi-user mode nothing stopped a
    caller creating ``user_preferences`` rows for photos outside her own
    directories.

    ``multi_user_row`` builds one bind tuple per path and ``single_user_sql``
    carries a ``{placeholders}`` field, because both have to be built from the
    filtered list rather than from the request.
    """
    if not photo_paths:
        return {'success': True, 'count': 0}

    with get_db() as conn:
        try:
            paths = _writable_photo_paths(conn, user, photo_paths)
            if not paths:
                return {'success': True, 'count': 0}
            if user.user_id and is_multi_user_enabled():
                conn.executemany(multi_user_sql, [multi_user_row(path) for path in paths])
            else:
                placeholders = ','.join('?' * len(paths))
                conn.execute(
                    single_user_sql.format(placeholders=placeholders),
                    [*single_user_prefix, *paths],
                )
            conn.commit()
            _stats_cache.clear()
            return {'success': True, 'count': len(paths)}
        except HTTPException:
            raise
        except sqlite3.Error as ex:
            conn.rollback()
            if is_locked_error(ex):
                raise
            logger.exception("Database error in batch update")
            raise HTTPException(status_code=500, detail='Internal server error')


@router.post("/api/photos/batch_favorite")
def api_batch_favorite(
    body: BatchPhotoRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Mark multiple photos as favorite (clears rejected)."""
    return _batch_update(
        body.photo_paths, user,
        multi_user_sql="""
            INSERT INTO user_preferences (user_id, photo_path, is_favorite, is_rejected)
            VALUES (?, ?, 1, 0)
            ON CONFLICT(user_id, photo_path) DO UPDATE SET is_favorite = 1, is_rejected = 0
        """,
        multi_user_row=lambda path: (user.user_id, path),
        single_user_sql="UPDATE photos SET is_favorite = 1, is_rejected = 0 WHERE path IN ({placeholders})",
    )


@router.post("/api/photos/batch_reject")
def api_batch_reject(
    body: BatchPhotoRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Mark multiple photos as rejected (clears favorite and rating)."""
    return _batch_update(
        body.photo_paths, user,
        multi_user_sql="""
            INSERT INTO user_preferences (user_id, photo_path, is_rejected, star_rating, is_favorite)
            VALUES (?, ?, 1, 0, 0)
            ON CONFLICT(user_id, photo_path) DO UPDATE SET is_rejected = 1, star_rating = 0, is_favorite = 0
        """,
        multi_user_row=lambda path: (user.user_id, path),
        single_user_sql="UPDATE photos SET is_rejected = 1, star_rating = 0, is_favorite = 0 WHERE path IN ({placeholders})",
    )


@router.post("/api/photos/batch_rating")
def api_batch_rating(
    body: BatchRatingRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Set star rating for multiple photos."""
    return _batch_update(
        body.photo_paths, user,
        multi_user_sql="""
            INSERT INTO user_preferences (user_id, photo_path, star_rating)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, photo_path) DO UPDATE SET star_rating = excluded.star_rating
        """,
        multi_user_row=lambda path: (user.user_id, path, body.rating),
        single_user_sql="UPDATE photos SET star_rating = ? WHERE path IN ({placeholders})",
        single_user_prefix=(body.rating,),
    )
