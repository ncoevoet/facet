"""Preview and atomically correct capture walltimes without writing originals."""
import hashlib
import json
import os
import sqlite3
from typing import Any
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth import CurrentUser, require_edition
from api.config import invalidate_stats_cache
from api.database import get_db
from api.db_helpers import retry_on_locked
from api.models.capture_dates import CaptureDateApplyRequest, CaptureDatePreview, CaptureDateRequest, CaptureDateReset
from api.routers.faces import _batch_scope_sql, _require_writable_photo, _writable_photo_paths
from api.routers.map import resolve_photo_disk_path
from exiftool.exiftool_batch import get_exif_batch
from utils.capture_dates import format_capture_date, parse_capture_date

router = APIRouter(tags=['capture_dates'])


def _preview(conn: sqlite3.Connection, body: CaptureDateRequest, user: CurrentUser) -> tuple[dict[str, Any], list[dict[str, str]]]:
    if body.filters is not None:
        source, where, params = _batch_scope_sql(conn, body, user)
        rows = conn.execute(f'SELECT DISTINCT photos.path, photos.date_taken, photos.date_manually_set FROM {source}{where} ORDER BY photos.path LIMIT 1001', params).fetchall()
    else:
        excluded = set(body.exclude or ())
        paths = _writable_photo_paths(conn, user, [p for p in body.photo_paths or () if p not in excluded])
        rows = conn.execute(f"SELECT path, date_taken, date_manually_set FROM photos WHERE path IN ({','.join('?' * len(paths))}) ORDER BY path", paths).fetchall() if paths else []
    if len(rows) > 1000:
        raise HTTPException(422, 'Select at most 1000 photos')
    changes = []
    for row in rows:
        date = parse_capture_date(row['date_taken'])
        if date is None:
            continue
        try:
            shifted = date + timedelta(seconds=body.offset_seconds)
        except OverflowError:
            continue
        changes.append(dict(path=row['path'], old_date=row['date_taken'], new_date=format_capture_date(shifted)))
    token = hashlib.sha256(json.dumps([body.offset_seconds, [tuple(row) for row in rows]], ensure_ascii=True).encode()).hexdigest()
    return dict(changed=len(changes), skipped=len(rows) - len(changes), samples=changes[:20], preview_token=token), changes


def _invalidate(conn: sqlite3.Connection) -> None:
    conn.execute('DELETE FROM stats_cache')


def _after_commit() -> None:
    from api.routers.burst_culling import _invalidate_culling_groups_cache
    invalidate_stats_cache()
    _invalidate_culling_groups_cache()


@router.post('/api/photos/capture_date/preview', response_model=CaptureDatePreview)
def preview_dates(body: CaptureDateRequest, user: CurrentUser = Depends(require_edition)) -> dict[str, Any]:
    with get_db() as conn, conn:
        conn.execute('BEGIN')
        result, _ = _preview(conn, body, user)
        return result


@router.post('/api/photos/capture_date/apply', response_model=CaptureDatePreview)
@retry_on_locked()
def apply_dates(body: CaptureDateApplyRequest, user: CurrentUser = Depends(require_edition)) -> dict[str, Any]:
    with get_db() as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        result, changes = _preview(conn, body, user)
        if result['preview_token'] != body.preview_token:
            raise HTTPException(409, 'Photos changed; preview again')
        conn.executemany('UPDATE photos SET date_taken=?, date_manually_set=1 WHERE path=?', [(change['new_date'], change['path']) for change in changes])
        _invalidate(conn)
    _after_commit()
    return result


def _identity(path: str) -> tuple[int, int, int, int, int]:
    try:
        stat = os.stat(path)
        return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns
    except OSError as exc:
        raise HTTPException(404, 'File not readable') from exc


@router.delete('/api/photo/capture_date', response_model=CaptureDateReset)
def reset_date(path: str = Query(...), user: CurrentUser = Depends(require_edition)) -> dict[str, Any]:
    with get_db() as conn:
        _require_writable_photo(conn, user, path)
        before = tuple(conn.execute('SELECT date_taken, date_manually_set FROM photos WHERE path=?', (path,)).fetchone())
    disk_path = resolve_photo_disk_path(path)
    identity = _identity(disk_path)
    metadata = get_exif_batch([disk_path])
    if disk_path not in metadata:
        raise HTTPException(404, 'File not readable')
    raw = metadata[disk_path].get('date_taken')
    date = parse_capture_date(raw)
    if raw is not None and date is None:
        raise HTTPException(409, 'File date is unsupported; manual date was kept')
    restored = format_capture_date(date) if date else None
    with get_db() as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        _require_writable_photo(conn, user, path)
        current = tuple(conn.execute('SELECT date_taken, date_manually_set FROM photos WHERE path=?', (path,)).fetchone())
        if current != before or resolve_photo_disk_path(path) != disk_path or _identity(disk_path) != identity:
            raise HTTPException(409, 'Photo changed; try again')
        conn.execute('UPDATE photos SET date_taken=?, date_manually_set=0 WHERE path=?', (restored, path))
        _invalidate(conn)
    _after_commit()
    return dict(date_taken=restored, date_manually_set=0)
