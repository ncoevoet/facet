"""
Faces API router — face management, rating, favorites, rejected.

"""

import logging
import os
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError, model_validator

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
    """The set a batch write acts on: named paths, or the gallery view itself.

    The gallery paginates at ``pagination.default_per_page`` with infinite
    scroll, so a path list could only ever name the pages the client had
    fetched. ``filters`` is the same query string the grid renders and the
    server derives the rows from it, so a whole-view write puts no path list on
    the wire at all; ``exclude`` carries the handful the user unticked.

    Exactly one of the two: neither is a write with no target and no way to say
    so, and both would leave which one wins undefined.
    """

    photo_paths: Optional[list[str]] = Field(default=None, max_length=1000)
    filters: Optional[dict] = None
    # Narrows whichever target is sent. Bounded well below
    # SQLITE_MAX_VARIABLE_NUMBER: on the filter branch each exclusion binds one
    # placeholder into a single NOT IN (...) alongside the filter's own binds.
    exclude: Optional[list[str]] = Field(
        default=None, max_length=1000,
        description="Paths to drop from whichever target is sent: subtracted from "
                    "`photo_paths`, or bound out of the `filters` scope. Only ever narrows.",
    )

    @model_validator(mode='after')
    def _exactly_one_target(self):
        if (self.photo_paths is None) == (self.filters is None):
            raise ValueError("exactly one of photo_paths or filters is required")
        return self


class BatchRatingRequest(BatchPhotoRequest):
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


def _batch_scope_sql(conn, body, user):
    """The gallery scope a filter-scoped batch write acts on.

    Imported inline, like the other cross-router helpers here, so this module
    keeps no import-time dependency on the gallery router.

    The scope carries the visibility clause as its FIRST where clause, which is
    why the filter branch needs no :func:`_writable_photo_paths` pass: a row
    another tenant owns is not in the set at all, rather than filtered out of a
    list after the fact.

    It also carries the album access check, so ``filters: {"album_id": N}``
    naming an album this caller cannot open raises the same 403/404 the gallery
    GET answers. That check used to live at the read call sites only, and this
    write path reached straight past it.
    """
    from api.routers.gallery import gallery_scope_sql, _raise_422_for_invalid_gallery_params

    try:
        return gallery_scope_sql(
            conn, body.filters, user.user_id if user else None, body.exclude
        )
    except ValidationError as ex:
        _raise_422_for_invalid_gallery_params(ex, logger, "Batch filter validation failed: %s")


@dataclass(frozen=True)
class BatchWriteSql:
    """The statements one batch endpoint needs, as a 2x2 matrix.

    Two ways to name the target set -- an explicit ``photo_paths`` list or a
    gallery ``filters`` set -- times two places the answer is stored: per-user
    rows in ``user_preferences``, or the global columns on ``photos``. Each
    cell needs its own statement because the four differ in shape, not only in
    text: the path forms bind one row per path, the filter forms carry a
    ``{scope}`` that takes the gallery's own FROM + WHERE, and the single-user
    path form carries ``{placeholders}``.

    Grouped into one object because they are one decision. As nine positional
    arguments the caller had to remember which of them pair up, and adding a
    fifth endpoint meant threading every one of them through again.
    """

    #: ``executemany``, one bind row per path, built by :attr:`multi_user_row`.
    multi_user: str
    multi_user_row: Callable[[str], tuple]
    #: Carries ``{placeholders}`` -- one ``?`` per surviving path.
    single_user: str
    #: Both carry ``{scope}``: the gallery FROM + WHERE, so the set is written
    #: without ever being materialised as a path list.
    filter_multi_user: str
    filter_single_user: str
    #: Bind values that precede the paths/scope params. ``single_user_prefix``
    #: is deliberately shared by BOTH single-user statements: they set the same
    #: columns and differ only in how they name the rows to set them on.
    single_user_prefix: tuple = ()
    filter_multi_user_prefix: tuple = ()


def _write_filter_scope(conn, body: BatchPhotoRequest, user: CurrentUser, sql: BatchWriteSql) -> int:
    """Write every row the filter set matches, in one statement.

    The set is never materialised as paths, so this holds however large the
    view is, and the count is the ``rowcount`` the statement reports. The scope
    already carries the visibility clause and the ``exclude`` list, so there is
    no separate writability pass here.
    """
    from_clause, where_str, scope_params = _batch_scope_sql(conn, body, user)
    scope = f"{from_clause}{where_str}"
    if user.user_id and is_multi_user_enabled():
        cursor = conn.execute(
            sql.filter_multi_user.format(scope=scope),
            [*sql.filter_multi_user_prefix, *scope_params],
        )
    else:
        cursor = conn.execute(
            sql.filter_single_user.format(scope=scope),
            [*sql.single_user_prefix, *scope_params],
        )
    return cursor.rowcount


def _write_paths(conn, paths: list, user: CurrentUser, sql: BatchWriteSql) -> int:
    """Write the named paths, which the caller has already filtered."""
    if user.user_id and is_multi_user_enabled():
        conn.executemany(sql.multi_user, [sql.multi_user_row(path) for path in paths])
    else:
        placeholders = ','.join('?' * len(paths))
        conn.execute(
            sql.single_user.format(placeholders=placeholders),
            [*sql.single_user_prefix, *paths],
        )
    return len(paths)


@retry_on_locked()
def _batch_update(body: BatchPhotoRequest, user: CurrentUser, sql: BatchWriteSql) -> dict:
    """Execute a batch update on photos with transaction and cache invalidation.

    Which statement of :class:`BatchWriteSql` runs is decided here; the two
    branches are :func:`_write_filter_scope` and :func:`_write_paths`.

    With ``photo_paths``, ``count`` is the number of photos actually written,
    not the number asked for: :func:`_writable_photo_paths` drops the paths that
    do not exist or that this caller may not see. Writing them was two defects
    at once — a stale path made ``executemany`` raise a FOREIGN KEY
    ``IntegrityError`` that surfaced as a 500 and lost the whole batch, and in
    multi-user mode nothing stopped a caller creating ``user_preferences`` rows
    for photos outside her own directories. An empty survivor list returns
    before the commit, so a batch naming only unwritable paths is not a write.
    """
    if body.filters is None and not body.photo_paths:
        return {'success': True, 'count': 0}

    with get_db() as conn:
        try:
            if body.filters is not None:
                count = _write_filter_scope(conn, body, user, sql)
            else:
                # `exclude` narrows WHICHEVER target is sent. On the filter
                # branch `_batch_scope_sql` binds it into the query; here it is
                # subtracted before the writability pass, so the excluded rows
                # are never written and never counted. It used to be read only
                # on the filter branch, so `{photo_paths, exclude}` cleared
                # star_rating and is_favorite on the very rows the caller asked
                # to skip. Order-preserving; an empty `exclude` is a no-op.
                excluded = set(body.exclude or ())
                named = [p for p in body.photo_paths if p not in excluded]
                paths = _writable_photo_paths(conn, user, named)
                if not paths:
                    return {'success': True, 'count': 0}
                count = _write_paths(conn, paths, user, sql)
            conn.commit()
            _stats_cache.clear()
            return {'success': True, 'count': count}
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
    return _batch_update(body, user, BatchWriteSql(
        multi_user="""
            INSERT INTO user_preferences (user_id, photo_path, is_favorite, is_rejected)
            VALUES (?, ?, 1, 0)
            ON CONFLICT(user_id, photo_path) DO UPDATE SET is_favorite = 1, is_rejected = 0
        """,
        multi_user_row=lambda path: (user.user_id, path),
        single_user="UPDATE photos SET is_favorite = 1, is_rejected = 0 WHERE path IN ({placeholders})",
        filter_multi_user="""
            INSERT INTO user_preferences (user_id, photo_path, is_favorite, is_rejected)
            SELECT ?, photos.path, 1, 0 FROM {scope}
            ON CONFLICT(user_id, photo_path) DO UPDATE SET is_favorite = 1, is_rejected = 0
        """,
        filter_multi_user_prefix=(user.user_id,),
        filter_single_user=(
            "UPDATE photos SET is_favorite = 1, is_rejected = 0 "
            "WHERE path IN (SELECT photos.path FROM {scope})"
        ),
    ))


@router.post("/api/photos/batch_reject")
def api_batch_reject(
    body: BatchPhotoRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Mark multiple photos as rejected (clears favorite and rating)."""
    return _batch_update(body, user, BatchWriteSql(
        multi_user="""
            INSERT INTO user_preferences (user_id, photo_path, is_rejected, star_rating, is_favorite)
            VALUES (?, ?, 1, 0, 0)
            ON CONFLICT(user_id, photo_path) DO UPDATE SET is_rejected = 1, star_rating = 0, is_favorite = 0
        """,
        multi_user_row=lambda path: (user.user_id, path),
        single_user="UPDATE photos SET is_rejected = 1, star_rating = 0, is_favorite = 0 WHERE path IN ({placeholders})",
        filter_multi_user="""
            INSERT INTO user_preferences (user_id, photo_path, is_rejected, star_rating, is_favorite)
            SELECT ?, photos.path, 1, 0, 0 FROM {scope}
            ON CONFLICT(user_id, photo_path) DO UPDATE SET is_rejected = 1, star_rating = 0, is_favorite = 0
        """,
        filter_multi_user_prefix=(user.user_id,),
        filter_single_user=(
            "UPDATE photos SET is_rejected = 1, star_rating = 0, is_favorite = 0 "
            "WHERE path IN (SELECT photos.path FROM {scope})"
        ),
    ))


@router.post("/api/photos/batch_rating")
def api_batch_rating(
    body: BatchRatingRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Set star rating for multiple photos."""
    return _batch_update(body, user, BatchWriteSql(
        multi_user="""
            INSERT INTO user_preferences (user_id, photo_path, star_rating)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, photo_path) DO UPDATE SET star_rating = excluded.star_rating
        """,
        multi_user_row=lambda path: (user.user_id, path, body.rating),
        single_user="UPDATE photos SET star_rating = ? WHERE path IN ({placeholders})",
        single_user_prefix=(body.rating,),
        filter_multi_user="""
            INSERT INTO user_preferences (user_id, photo_path, star_rating)
            SELECT ?, photos.path, ? FROM {scope}
            ON CONFLICT(user_id, photo_path) DO UPDATE SET star_rating = excluded.star_rating
        """,
        filter_multi_user_prefix=(user.user_id, body.rating),
        filter_single_user=(
            "UPDATE photos SET star_rating = ? "
            "WHERE path IN (SELECT photos.path FROM {scope})"
        ),
    ))
