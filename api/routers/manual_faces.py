"""Draw a missed face in canonical analysis space without requiring a model."""
import base64
from datetime import timedelta
from io import BytesIO
import math
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Response
from PIL import Image

from api.auth import CurrentUser, create_access_token, decode_access_token, require_edition
from api.config import invalidate_stats_cache
from api.database import get_db
from api.db_helpers import assert_photo_visible, person_visibility_exists
from api.models.manual_faces import (ManualFaceCreate, ManualFaceDelete, ManualFaceFrame,
                                     ManualFaceRegion, ManualFacesResponse, ManualFaceWrite)
from api.path_validation import resolve_photo_disk_path
from db import manual_faces
from db.person_carry_over import refresh_person_counts
from utils.manual_face_frame import file_stamp, read_frame

router = APIRouter(tags=['manual faces'])
_PURPOSE = 'manual_face_frame'
_DECODER = 'upright-analysis-v1'


def _visible(conn, user, path):
    try:
        assert_photo_visible(conn, user.user_id, path)
    except LookupError as exc:
        raise HTTPException(404, 'Photo not found') from exc
    # The shared guard intentionally does nothing on single-user installs;
    # registration is still required before this API may read a local file.
    if conn.execute('SELECT 1 FROM photos WHERE path=?', (path,)).fetchone() is None:
        raise HTTPException(404, 'Photo not found')


def _current(path, stored):
    try:
        return manual_faces.is_current(resolve_photo_disk_path(path), stored)
    except Exception:
        return False


def _decode(path):
    # The token remains bound to the DB path, while every actual file access
    # follows the same mapping and containment contract as /image.
    disk_path = resolve_photo_disk_path(path)
    try:
        frame = read_frame(disk_path)
    except OSError as exc:
        raise HTTPException(409, 'Original image unavailable or changed') from exc
    # Canonical loader returns BGR; browser JPEG and crops must be RGB.
    return Image.fromarray(frame.pixels[:, :, ::-1]), frame.identity, frame.stamp


def _check_stamp(path, stamp):
    try:
        # Re-resolve mapping and containment too, rather than merely statting
        # the original target after its logical path has been repointed.
        current = file_stamp(resolve_photo_disk_path(path))
    except OSError as exc:
        raise HTTPException(409, 'Original image unavailable or changed') from exc
    if current != stamp:
        raise HTTPException(409, 'Image changed; reload the editor')


def _jpeg(image, edge):
    # Both callers give us an owned preview/crop, never the cached BGR array.
    # Resize that image directly instead of copying another full RAW frame.
    image.thumbnail((edge, edge), Image.Resampling.LANCZOS)
    output = BytesIO()
    image.save(output, format='JPEG', quality=90)
    return output.getvalue()


@router.get('/api/photo/manual-faces', response_model=ManualFacesResponse)
def list_manual_faces(path: str, response: Response, user: CurrentUser = Depends(require_edition)):
    response.headers['Cache-Control'] = 'no-store'
    with get_db() as conn:
        _visible(conn, user, path)
        rows = conn.execute(
            'SELECT f.*,p.name AS person_name FROM faces f LEFT JOIN persons p ON p.id=f.person_id '
            'WHERE f.photo_path=? AND f.is_manual=1 ORDER BY f.id', (path,)).fetchall()
    states = [_current(path, row['manual_source']) for row in rows]
    with get_db() as conn, conn:
        _visible(conn, user, path)
        manual_faces.apply_review_states(conn, {
            (row['id'], row['manual_source']): state for row, state in zip(rows, states)})
    return {'regions': [manual_faces.region_response(row, state) for row, state in zip(rows, states)]}


@router.get('/api/photo/manual-face-frame', response_model=ManualFaceFrame)
def manual_face_frame(path: str, response: Response, user: CurrentUser = Depends(require_edition)):
    response.headers['Cache-Control'] = 'no-store'
    with get_db() as conn:
        _visible(conn, user, path)
    image, identity, stamp = _decode(path)
    with get_db() as conn:
        _visible(conn, user, path)
    _check_stamp(path, stamp)
    w, h = image.size
    token = create_access_token({'sub': user.user_id or '_legacy', 'purpose': _PURPOSE,
                                 'path': path, 'width': w, 'height': h, 'source': identity,
                                 'decoder': _DECODER}, expires_delta=timedelta(minutes=15))
    return {'image_base64': base64.b64encode(_jpeg(image, 1600)).decode('ascii'),
            'width': w, 'height': h, 'frame_token': token}


def _person(conn, user, body, current_person=None):
    if body.person_id is None:
        # Retrying a PUT after losing its response must not create another
        # person. This checks only this mark's assigned identity, not names
        # across the library (different people may have the same name).
        if current_person is not None:
            current = conn.execute('SELECT name FROM persons WHERE id=?', (current_person,)).fetchone()
            if current and current['name'] == body.new_person_name:
                return current_person
        return conn.execute('INSERT INTO persons(name,auto_clustered,face_count) VALUES (?,0,0)',
                            (body.new_person_name,)).lastrowid
    vis, params = person_visibility_exists(user.user_id, 'p.id')
    row = conn.execute('SELECT 1 FROM persons p WHERE p.id=?' + (f' AND {vis}' if vis else ''),
                       [body.person_id, *params]).fetchone()
    if row is None:
        raise HTTPException(404, 'Person not found')
    return body.person_id


def _write(body, user, face_id=None):
    key = str(body.client_id) if isinstance(body, ManualFaceCreate) else None
    previous = None
    with get_db() as conn:
        _visible(conn, user, body.path)
        if key:
            old = manual_faces.get_region(conn, body.path, manual_key=key)
            previous = old
        if face_id is not None and manual_faces.get_region(conn, body.path, face_id=face_id) is None:
            raise HTTPException(404, 'Manual face not found')
    if previous is not None:
        state = _current(body.path, previous['manual_source'])
        with get_db() as conn:
            _visible(conn, user, body.path)
            current = manual_faces.get_region(conn, body.path, manual_key=key)
            if current is None:
                raise HTTPException(409, 'Manual face changed while retrying')
        return manual_faces.region_response(current, state)
    claims = decode_access_token(body.frame_token)
    if not claims or claims.get('purpose') != _PURPOSE or claims.get('decoder') != _DECODER:
        raise HTTPException(409, 'Invalid or expired editor frame; reload the editor')
    if claims.get('sub') != (user.user_id or '_legacy') or claims.get('path') != body.path:
        raise HTTPException(409, 'Editor frame belongs to another photo or user')
    image, identity, stamp = _decode(body.path)
    w, h = image.size
    if (not manual_faces.same_image(claims.get('source'), identity) or
            (claims.get('width'), claims.get('height')) != (w, h)):
        raise HTTPException(409, 'Image changed; reload the editor')
    x1, y1, x2, y2 = body.bbox
    if (x2 - x1) * w < 4 - 1e-9 or (y2 - y1) * h < 4 - 1e-9:
        raise HTTPException(422, 'Rectangle must cover at least 4 by 4 source pixels')
    box = (math.floor(x1 * w), math.floor(y1 * h), math.ceil(x2 * w), math.ceil(y2 * h))
    crop = _jpeg(image.crop(box), 160)
    with get_db() as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        _visible(conn, user, body.path)
        _check_stamp(body.path, stamp)
        old = manual_faces.get_region(conn, body.path, face_id=face_id) if face_id is not None else None
        if face_id is not None and old is None:
            raise HTTPException(404, 'Manual face not found')
        if key:
            retry = manual_faces.get_region(conn, body.path, manual_key=key)
            if retry:
                return manual_faces.region_response(retry, True)
            if conn.execute('SELECT 1 FROM faces WHERE manual_key=?', (key,)).fetchone():
                raise HTTPException(409, 'Request identifier already used')
            if conn.execute('SELECT 1 FROM manual_face_deletions WHERE manual_key=?', (key,)).fetchone():
                raise HTTPException(409, 'Request identifier already used')
        if not old and conn.execute('SELECT COUNT(*) FROM faces WHERE photo_path=? AND is_manual=1',
                                    (body.path,)).fetchone()[0] >= 100:
            raise HTTPException(409, 'Manual face limit reached')
        if manual_faces.detected_overlap(conn, body.path, box):
            raise HTTPException(409, {'code': 'detected_face_overlap'})
        person_id = _person(conn, user, body, old['person_id'] if old else None)
        fields = (*box, person_id, crop, identity, w, h)
        if old:
            conn.execute('UPDATE faces SET bbox_x1=?,bbox_y1=?,bbox_x2=?,bbox_y2=?,person_id=?, '
                         'face_thumbnail=?,manual_source=?,manual_width=?,manual_height=?,manual_review_required=0 WHERE id=?',
                         (*fields, face_id))
        else:
            index = conn.execute('SELECT MIN(COALESCE(face_index,0)) FROM faces WHERE photo_path=?',
                                 (body.path,)).fetchone()[0]
            index = min(index or 0, 0) - 1
            face_id = conn.execute(
                "INSERT INTO faces(photo_path,face_index,embedding,is_manual,manual_key,embedding_model,"
                'bbox_x1,bbox_y1,bbox_x2,bbox_y2,person_id,face_thumbnail,manual_source,manual_width,manual_height) '
                "VALUES (?, ?, X'', 1, ?, 'manual', ?,?,?,?,?,?,?,?,?)",
                (body.path, index, key, *fields)).lastrowid
        affected = {person_id, old['person_id'] if old else None} - {None}
        refresh_person_counts(conn, affected)
        # A still-valid representative ID does not make its old crop current.
        conn.execute('UPDATE persons SET face_thumbnail=? WHERE representative_face_id=?', (crop, face_id))
        result = manual_faces.region_response(
            manual_faces.get_region(conn, body.path, face_id=face_id), True)
        _check_stamp(body.path, stamp)
    invalidate_stats_cache()
    return result


@router.post('/api/photo/manual-faces', response_model=ManualFaceRegion, status_code=201)
def create_manual_face(body: ManualFaceCreate, user: CurrentUser = Depends(require_edition)):
    try:
        return _write(body, user)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, 'Manual face conflicts with a concurrent change') from exc


@router.put('/api/photo/manual-faces/{face_id}', response_model=ManualFaceRegion)
def update_manual_face(face_id: int, body: ManualFaceWrite, user: CurrentUser = Depends(require_edition)):
    return _write(body, user, face_id)


@router.delete('/api/photo/manual-faces/{face_id}', response_model=ManualFaceDelete)
def delete_manual_face(face_id: int, path: str, user: CurrentUser = Depends(require_edition)):
    with get_db() as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        _visible(conn, user, path)
        old = manual_faces.get_region(conn, path, face_id=face_id)
        if old is None:
            raise HTTPException(404, 'Manual face not found')
        conn.execute('INSERT OR IGNORE INTO manual_face_deletions(manual_key) VALUES (?)', (old['manual_key'],))
        conn.execute('DELETE FROM faces WHERE id=?', (face_id,))
        if old['person_id'] is not None:
            refresh_person_counts(conn, {old['person_id']})
    invalidate_stats_cache()
    return {'success': True}
