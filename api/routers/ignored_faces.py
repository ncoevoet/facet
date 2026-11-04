"""Per-detection corrections for advertisements and false face detections."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import CurrentUser, require_edition
from api.config import invalidate_stats_cache
from api.database import get_db
from api.db_helpers import assert_photo_visible

router = APIRouter(tags=['faces'])


class FaceCorrectionRequest(BaseModel):
    photo_path: str


class IgnoreFaceResponse(BaseModel):
    ignore_id: UUID


class RestoreFaceResponse(BaseModel):
    success: bool


def _face_correction_frame(path):
    from api.path_validation import resolve_photo_disk_path
    from utils.manual_face_frame import read_frame
    try:
        disk_path = resolve_photo_disk_path(path)
        return disk_path, read_frame(disk_path)
    except OSError as exc:
        raise HTTPException(409, 'Original image unavailable or changed') from exc


def _check_face_correction_frame(path, disk_path, frame):
    from api.path_validation import resolve_photo_disk_path
    from utils.manual_face_frame import file_stamp
    try:
        if resolve_photo_disk_path(path) == disk_path and file_stamp(disk_path) == frame.stamp:
            return
    except OSError:
        pass
    raise HTTPException(409, 'Original image changed; reload the photo')


@router.post('/api/face/{face_id}/ignore', response_model=IgnoreFaceResponse)
def api_ignore_face(face_id: int, body: FaceCorrectionRequest, user: CurrentUser = Depends(require_edition)):
    """Ignore one automatic detection, retaining a durable correction for Undo."""
    from db.ignored_faces import detection_source, ignore_detection, source_is_current
    with get_db() as conn:
        try:
            assert_photo_visible(conn, user.user_id, body.photo_path)
        except LookupError as exc:
            raise HTTPException(404, 'Face not found') from exc
        row = conn.execute('SELECT * FROM faces WHERE id=? AND photo_path=?',
                           (face_id, body.photo_path)).fetchone()
        if row is None:
            # A lost response may be retried after the face has been removed.
            # Scope by photo and retain the original correction's Undo handle.
            previous = conn.execute('SELECT ignore_id,source FROM ignored_face_detections '
                                    'WHERE face_id=? AND photo_path=? AND active=1',
                                    (face_id, body.photo_path)).fetchone()
            if previous is not None:
                disk_path, frame = _face_correction_frame(body.photo_path)
                if not source_is_current(disk_path, previous['source'], frame):
                    raise HTTPException(409, 'Original image changed; reload the photo')
                _check_face_correction_frame(body.photo_path, disk_path, frame)
                return {'ignore_id': previous['ignore_id']}
            raise HTTPException(404, 'Face not found')
        observed = dict(row)
    # Decode outside the write transaction and off the async request loop.
    disk_path, frame = _face_correction_frame(body.photo_path)
    with get_db() as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        try:
            assert_photo_visible(conn, user.user_id, body.photo_path)
        except LookupError as exc:
            raise HTTPException(404, 'Face not found') from exc
        row = conn.execute('SELECT * FROM faces WHERE id=? AND photo_path=?',
                           (face_id, body.photo_path)).fetchone()
        if row is None:
            previous = conn.execute('SELECT ignore_id,source FROM ignored_face_detections '
                                    'WHERE face_id=? AND photo_path=? AND active=1',
                                    (face_id, body.photo_path)).fetchone()
            if previous is not None and source_is_current(disk_path, previous['source'], frame):
                _check_face_correction_frame(body.photo_path, disk_path, frame)
                return {'ignore_id': previous['ignore_id']}
        if row is None or dict(row) != observed:
            raise HTTPException(409, 'Face changed; reload the photo')
        if conn.execute('SELECT COUNT(*) FROM ignored_face_detections WHERE photo_path=? AND active=1',
                        (body.photo_path,)).fetchone()[0] >= 100:
            raise HTTPException(409, 'Ignored detection limit reached')
        _check_face_correction_frame(body.photo_path, disk_path, frame)
        try:
            ignore_id = ignore_detection(conn, row, detection_source(frame))
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        _check_face_correction_frame(body.photo_path, disk_path, frame)
    invalidate_stats_cache()
    return {'ignore_id': ignore_id}


@router.post('/api/ignored-face/{ignore_id}/restore', response_model=RestoreFaceResponse)
def api_restore_ignored_face(ignore_id: UUID, body: FaceCorrectionRequest,
                             user: CurrentUser = Depends(require_edition)):
    """Restore a correction only while its original image is still current."""
    from db.ignored_faces import restore_detection, source_is_current
    with get_db() as conn:
        try:
            assert_photo_visible(conn, user.user_id, body.photo_path)
        except LookupError as exc:
            raise HTTPException(404, 'Face not found') from exc
        row = conn.execute('SELECT * FROM ignored_face_detections WHERE ignore_id=? AND photo_path=?',
                           (str(ignore_id), body.photo_path)).fetchone()
        if row is None:
            raise HTTPException(404, 'Face not found')
        observed = dict(row)
    disk_path, frame = _face_correction_frame(body.photo_path)
    if not source_is_current(disk_path, observed['source'], frame):
        raise HTTPException(409, 'Original image changed; reload the photo')
    with get_db() as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        try:
            assert_photo_visible(conn, user.user_id, body.photo_path)
        except LookupError as exc:
            raise HTTPException(404, 'Face not found') from exc
        row = conn.execute('SELECT * FROM ignored_face_detections WHERE ignore_id=? AND photo_path=?',
                           (str(ignore_id), body.photo_path)).fetchone()
        if row is None or dict(row) != observed:
            raise HTTPException(409, 'Face changed; reload the photo')
        _check_face_correction_frame(body.photo_path, disk_path, frame)
        try:
            restore_detection(conn, row)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        _check_face_correction_frame(body.photo_path, disk_path, frame)
    invalidate_stats_cache()
    return {'success': True}
