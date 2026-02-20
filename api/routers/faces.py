"""
Faces API router — face management, rating, favorites, rejected.

"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from api.auth import CurrentUser, require_edition, require_auth
from api.config import is_multi_user_enabled, _stats_cache
from api.database import get_db_connection
from api.db_helpers import update_person_face_count

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
    rating: int


class TogglePhotoRequest(BaseModel):
    photo_path: str


@router.get("/api/person/{person_id}/faces")
async def api_person_faces(
    person_id: int,
    user: CurrentUser = Depends(require_auth),
):
    """Get all faces belonging to a person."""
    conn = get_db_connection()
    try:
        faces = conn.execute("""
            SELECT f.id, f.photo_path, f.face_index, f.bbox_x1, f.bbox_y1, f.bbox_x2, f.bbox_y2
            FROM faces f
            LEFT JOIN photos p ON f.photo_path = p.path
            WHERE f.person_id = ?
            ORDER BY p.aggregate DESC
            LIMIT 36
        """, (person_id,)).fetchall()
        return {'faces': [dict(f) for f in faces]}
    finally:
        conn.close()


@router.post("/api/person/{person_id}/avatar")
async def api_set_person_avatar(
    person_id: int,
    body: AvatarRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Set a face as the representative avatar for a person."""
    conn = get_db_connection()
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
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail='Internal server error')
    finally:
        conn.close()


@router.get("/api/photo/faces")
async def api_photo_faces(
    path: str,
    user: CurrentUser = Depends(require_auth),
):
    """Get all faces in a photo with their current person assignment."""
    conn = get_db_connection()
    try:
        faces = conn.execute("""
            SELECT f.id, f.face_index, f.bbox_x1, f.bbox_y1, f.bbox_x2, f.bbox_y2,
                   f.person_id, p.name as person_name
            FROM faces f
            LEFT JOIN persons p ON f.person_id = p.id
            WHERE f.photo_path = ?
            ORDER BY f.face_index
        """, (path,)).fetchall()
        return {'faces': [dict(f) for f in faces]}
    finally:
        conn.close()


@router.post("/api/face/{face_id}/assign")
async def api_assign_face(
    face_id: int,
    body: AssignFaceRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Assign a face to a person."""
    conn = get_db_connection()
    try:
        face = conn.execute("SELECT person_id FROM faces WHERE id = ?", (face_id,)).fetchone()
        if not face:
            raise HTTPException(status_code=404, detail="Face not found")

        old_person_id = face['person_id']
        conn.execute("UPDATE faces SET person_id = ? WHERE id = ?", (body.person_id, face_id))

        if old_person_id:
            update_person_face_count(conn, old_person_id)
        update_person_face_count(conn, body.person_id)

        conn.commit()

        return {'success': True}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail='Internal server error')
    finally:
        conn.close()


@router.post("/api/photo/assign_all_faces")
async def api_assign_all_faces(
    body: AssignAllFacesRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Assign all unassigned faces in a photo to a person."""
    conn = get_db_connection()
    try:
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
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail='Internal server error')
    finally:
        conn.close()


@router.post("/api/photo/unassign_person")
async def api_unassign_person(
    body: UnassignPersonRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Unassign all faces of a specific person from a photo."""
    conn = get_db_connection()
    try:
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

        conn.commit()


        return {
            'success': True,
            'unassigned_count': len(faces),
            'person_deleted': person_deleted
        }
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail='Internal server error')
    finally:
        conn.close()


@router.post("/api/photo/set_rating")
async def api_set_rating(
    body: SetRatingRequest,
    user: CurrentUser = Depends(require_auth),
):
    """Set star rating (0-5) for a photo."""
    if body.rating < 0 or body.rating > 5:
        raise HTTPException(status_code=400, detail="rating must be integer 0-5")

    conn = get_db_connection()
    try:
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
        return {'success': True, 'rating': body.rating}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail='Internal server error')
    finally:
        conn.close()


@router.post("/api/photo/toggle_favorite")
async def api_toggle_favorite(
    body: TogglePhotoRequest,
    user: CurrentUser = Depends(require_auth),
):
    """Toggle favorite flag for a photo."""
    conn = get_db_connection()
    try:
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
            if not row:
                raise HTTPException(status_code=404, detail="Photo not found")
            new_value = 0 if row['is_favorite'] else 1
            if new_value == 1:
                conn.execute("UPDATE photos SET is_favorite = 1, is_rejected = 0 WHERE path = ?", (body.photo_path,))
            else:
                conn.execute("UPDATE photos SET is_favorite = 0 WHERE path = ?", (body.photo_path,))
        conn.commit()
        _stats_cache.clear()
        return {'success': True, 'is_favorite': new_value == 1, 'is_rejected': False if new_value == 1 else None}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail='Internal server error')
    finally:
        conn.close()


@router.post("/api/photo/toggle_rejected")
async def api_toggle_rejected(
    body: TogglePhotoRequest,
    user: CurrentUser = Depends(require_auth),
):
    """Toggle rejected flag for a photo."""
    conn = get_db_connection()
    try:
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
            if not row:
                raise HTTPException(status_code=404, detail="Photo not found")
            new_value = 0 if row['is_rejected'] else 1
            if new_value == 1:
                conn.execute("UPDATE photos SET is_rejected = 1, star_rating = 0, is_favorite = 0 WHERE path = ?", (body.photo_path,))
            else:
                conn.execute("UPDATE photos SET is_rejected = 0 WHERE path = ?", (body.photo_path,))
        conn.commit()
        _stats_cache.clear()
        return {'success': True, 'is_rejected': new_value == 1, 'star_rating': 0 if new_value == 1 else None, 'is_favorite': False if new_value == 1 else None}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail='Internal server error')
    finally:
        conn.close()
