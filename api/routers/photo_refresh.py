"""Refresh selected indexed previews and available source EXIF without scoring."""
import logging
import sqlite3
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from api.auth import CurrentUser, require_edition
from api.database import get_db
from api.db_helpers import after_commit, is_locked_error
from api.path_validation import resolve_photo_disk_path
from api.raw_processing import load_viewer_image
from api.routers.capture_dates import _identity
from api.routers.faces import _require_writable_photo
from api.routers.thumbnails import _image_render_budget
from db.maintenance import evict_derived_stats_cache
from db.manual_faces import apply_review_states, is_current
from db.render_version import render_version_for
from exiftool.exiftool_batch import EXIF_META_COLUMNS, get_exif_batch
from utils.capture_dates import format_capture_date, parse_capture_date
from utils.image_loading import RAW_EXTENSIONS, load_image_from_path
from utils.image_transforms import generate_photo_thumbnail, thumbnail_has_signal
from utils.manual_face_frame import invalidate_path

logger = logging.getLogger(__name__)
router = APIRouter(tags=['photo_refresh'])


MAX_REFRESH_PATHS = 100
_MAX_PATH_LENGTH = 4096


class PhotoRefreshRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    paths: list[str] = Field(min_length=1, max_length=MAX_REFRESH_PATHS)


class PhotoRefreshFailure(BaseModel):
    path: str
    reason: Literal['unavailable', 'changed', 'busy', 'failed']


class PhotoRefreshResponse(BaseModel):
    refreshed: list[str]
    failed: list[PhotoRefreshFailure]


_METADATA_FIELDS = ('camera_model', 'lens_model', 'iso', 'f_stop', 'shutter_speed',
                    'focal_length', 'focal_length_35mm', *EXIF_META_COLUMNS)


def _refresh(path, user):
    with get_db() as conn, conn:
        conn.execute('BEGIN')
        _require_writable_photo(conn, user, path)
        before = conn.execute('SELECT thumbnail, preview_revision, sequence_kind FROM photos WHERE path=?', (path,)).fetchone()
        if before is None:
            raise HTTPException(404, 'Photo unavailable')
        before = tuple(before)
        marks = conn.execute('SELECT id,manual_source FROM faces WHERE photo_path=? AND is_manual=1', (path,)).fetchall()
    disk = resolve_photo_disk_path(path)
    identity = _identity(disk)
    with _image_render_budget(disk):
        if Path(disk).suffix.lower() in RAW_EXTENSIONS:
            # DB face coordinates belong to the metrics frame, never the camera
            # preview or a bracket's gain-free display buffer. Close it before
            # decoding the display frame so only one full plane remains alive.
            metrics, metrics_bgr = load_image_from_path(disk)
            if metrics is None:
                raise ValueError('Source frame unavailable')
            del metrics_bgr
            try:
                width, height = metrics.size
            finally:
                metrics.close()
            image = load_viewer_image(disk, before[2], max_edge=640)
        else:
            # Upright full frame: JPEG draft dimensions must not be stored.
            image = load_viewer_image(disk, before[2])
            width, height = image.size
        try:
            thumbnail = generate_photo_thumbnail(image)
        finally:
            image.close()
        if not thumbnail_has_signal(thumbnail):
            raise ValueError('No usable preview')
        invalidate_path(disk)
        review_states = {(row['id'], row['manual_source']): is_current(disk, row['manual_source'], verify_pixels=True) for row in marks}
    # Outside the render slot: an exiftool subprocess holds no pixel plane.
    # Without exiftool (or a readable tag block) the preview still refreshes
    # and every stored metadata value is kept.
    values = get_exif_batch([disk]).get(disk)
    if values is None:
        logger.warning('Photo refresh read no source metadata for %s; keeping stored values', disk)
        values = {}
    updates = {key: values[key] for key in _METADATA_FIELDS if values.get(key) is not None}
    source_date = values.get('date_taken')
    date = parse_capture_date(source_date) if isinstance(source_date, str) else None
    with get_db() as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        _require_writable_photo(conn, user, path)
        current = conn.execute('SELECT thumbnail,preview_revision,sequence_kind FROM photos WHERE path=?', (path,)).fetchone()
        if tuple(current) != before or resolve_photo_disk_path(path) != disk or _identity(disk) != identity:
            raise HTTPException(409, 'Photo changed')
        assignments = [f'{key}=?' for key in updates]
        params = list(updates.values())
        if date:
            assignments.append('date_taken=CASE WHEN date_manually_set=1 THEN date_taken ELSE ? END')
            params.append(format_capture_date(date))
        latitude, longitude = values.get('gps_latitude'), values.get('gps_longitude')
        if latitude is not None and longitude is not None and -90 <= latitude <= 90 and -180 <= longitude <= 180:
            assignments += ['gps_latitude=CASE WHEN gps_manually_set=1 THEN gps_latitude ELSE ? END',
                            'gps_longitude=CASE WHEN gps_manually_set=1 THEN gps_longitude ELSE ? END']
            params += [latitude, longitude]
        # The photos_preview_revision trigger only fires when the thumbnail
        # bytes change; an identical re-render must still bust warm caches.
        assignments += ['thumbnail=?', 'image_width=?', 'image_height=?', 'render_version=?', 'histogram_data=NULL', 'preview_revision=lower(hex(randomblob(16)))']
        params += [thumbnail, width, height, render_version_for(before[2]), path]
        conn.execute('UPDATE photos SET '+','.join(assignments)+' WHERE path=?', params)
        apply_review_states(conn, review_states)
        conn.execute('DELETE FROM iqa_declined WHERE photo_path=?', (path,))
        evict_derived_stats_cache(conn)
    after_commit()


@router.post('/api/photos/refresh', response_model=PhotoRefreshResponse)
def refresh_photos(body: PhotoRefreshRequest, user: CurrentUser = Depends(require_edition)):
    paths = list(dict.fromkeys(body.paths))
    if any(not path or '\x00' in path or len(path) > _MAX_PATH_LENGTH for path in paths):
        raise HTTPException(422, 'Choose explicit photo paths')
    # An unauthorized target refuses the whole request before any source read or write.
    with get_db() as conn:
        for path in paths:
            _require_writable_photo(conn, user, path)
    from facet import LibraryLock, LibraryLockError, LibraryLockUnusableError
    with get_db() as conn:
        db_path = conn.execute('PRAGMA database_list').fetchone()[2]
    lock = LibraryLock(db_path, 'photo-refresh', origin='viewer')
    try:
        lock.acquire()
    except LibraryLockUnusableError as exc:
        logger.exception('Photo refresh library lock unavailable')
        raise HTTPException(503, 'Library storage is unavailable; check server logs') from exc
    except LibraryLockError as exc:
        raise HTTPException(503, 'Another library job is running; retry after it finishes', headers={'Retry-After': '5'}) from exc
    try:
        refreshed, failed = [], []
        for path in paths:
            try:
                _refresh(path, user)
                refreshed.append(path)
            except HTTPException as exc:
                failed.append(dict(path=path, reason='changed' if exc.status_code == 409 else 'unavailable'))
            except sqlite3.Error as exc:
                logger.exception('Photo refresh database failure')
                failed.append(dict(path=path, reason='busy' if is_locked_error(exc) else 'failed'))
            except (OSError, ValueError, RuntimeError):
                logger.exception('Photo refresh decode or metadata failure')
                failed.append(dict(path=path, reason='failed'))
        return dict(refreshed=refreshed, failed=failed)
    finally:
        lock.release()
