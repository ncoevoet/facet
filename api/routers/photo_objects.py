"""User-marked objects: a labelled box on a photo ("cake", "red car").

Objects live in the ``photo_objects`` side table and are never faces: face
detection, clustering and persons never read it. Labels follow the manual-tag
rules (trimmed, lowercased) so the gallery search matches them the same way.
Reads follow photo visibility; writes are edition-gated like every other write.
"""

from fastapi import APIRouter, Depends, HTTPException

from api.auth import CurrentUser, require_authenticated, require_edition
from api.config import is_multi_user_enabled
from api.database import get_async_db, get_db
from api.db_helpers import get_visibility_clause, retry_on_locked
from api.models.photo_objects import (PhotoObject, PhotoObjectCreate, PhotoObjectDelete,
                                      PhotoObjectsResponse)
from api.routers.faces import _require_writable_photo
from db.manual_tags import ManualTagError, normalize_manual_tag

router = APIRouter(tags=['photo objects'])

# Enough for a busy scene; a cap keeps one photo from collecting thousands of rows.
MAX_OBJECTS_PER_PHOTO = 50


def _row(row) -> PhotoObject:
    return PhotoObject(id=row['id'], label=row['label'],
                       box=[row['x1'], row['y1'], row['x2'], row['y2']])


@router.get('/api/photo/objects', response_model=PhotoObjectsResponse)
async def list_photo_objects(path: str, user: CurrentUser = Depends(require_authenticated)):
    """The objects marked on one photo; empty for a photo the caller cannot see."""
    vis_sql, vis_params = get_visibility_clause(user.user_id if user else None)
    async with get_async_db() as conn:
        cur = await conn.execute(f'SELECT 1 FROM photos WHERE path = ? AND {vis_sql}', [path, *vis_params])
        visible = await cur.fetchone()
        await cur.close()
        if not visible:
            return {'objects': []}
        cur = await conn.execute(
            'SELECT id, label, x1, y1, x2, y2 FROM photo_objects WHERE photo_path = ? ORDER BY id', (path,))
        rows = await cur.fetchall()
        await cur.close()
    return {'objects': [_row(r) for r in rows]}


@router.post('/api/photo/objects', response_model=PhotoObject, status_code=201)
@retry_on_locked()
def create_photo_object(body: PhotoObjectCreate, user: CurrentUser = Depends(require_edition)):
    """Mark one object on a photo."""
    try:
        label = normalize_manual_tag(body.label)
    except ManualTagError as ex:
        raise HTTPException(status_code=422, detail=str(ex)) from None
    x1, y1, x2, y2 = body.box
    with get_db() as conn:
        _require_writable_photo(conn, user, body.path)
        count = conn.execute('SELECT COUNT(*) FROM photo_objects WHERE photo_path = ?', (body.path,)).fetchone()[0]
        if count >= MAX_OBJECTS_PER_PHOTO:
            raise HTTPException(status_code=409, detail=f'At most {MAX_OBJECTS_PER_PHOTO} objects per photo')
        created_by = user.user_id if user and is_multi_user_enabled() else None
        cur = conn.execute(
            'INSERT INTO photo_objects (photo_path, label, x1, y1, x2, y2, created_by) VALUES (?, ?, ?, ?, ?, ?, ?)',
            (body.path, label, x1, y1, x2, y2, created_by))
        conn.commit()
        return PhotoObject(id=cur.lastrowid, label=label, box=[x1, y1, x2, y2])


@router.delete('/api/photo/objects/{object_id}', response_model=PhotoObjectDelete)
@retry_on_locked()
def delete_photo_object(object_id: int, user: CurrentUser = Depends(require_edition)):
    """Remove one marked object."""
    with get_db() as conn:
        row = conn.execute('SELECT photo_path FROM photo_objects WHERE id = ?', (object_id,)).fetchone()
        if row is None:
            return {'success': True, 'removed': False}
        _require_writable_photo(conn, user, row['photo_path'])
        conn.execute('DELETE FROM photo_objects WHERE id = ?', (object_id,))
        conn.commit()
    return {'success': True, 'removed': True}
