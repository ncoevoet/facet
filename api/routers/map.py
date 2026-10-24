"""
Map view router — GPS-based photo browsing with clustering at low zoom levels.

"""

import hashlib
import json
import logging
import re
import sqlite3
from typing import Iterator, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, ValidationError, model_validator

from api.auth import CurrentUser, get_optional_user, require_edition
from api import organization_history
from api.database import get_async_db, get_db
from api.db_helpers import get_existing_columns, get_visibility_clause, to_exif_date
from api.models.discovery import PhotoMapCountResponse, PhotoMapResponse
from api.path_validation import resolve_photo_disk_path
from api.routers.faces import BatchPhotoRequest, _batch_scope_sql
from api.routers.places import Latitude, Longitude, place_owner
from db import places
from exiftool.exiftool_batch import get_exif_batch

_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')

router = APIRouter(tags=["map"])
logger = logging.getLogger(__name__)


def _get_cluster_zoom_threshold():
    """Read map.cluster_zoom_threshold from scoring_config.json."""
    try:
        from api.config import _FULL_CONFIG
        return _FULL_CONFIG.get('map', {}).get('cluster_zoom_threshold', 10)
    except (KeyError, TypeError, ValueError):
        return 10


async def _get_clustered_photos(conn, zoom, date_from, date_to, user_id,
                                base_where, base_params, limit):
    """Return clustered photo locations grouped into grid cells for low zoom levels."""
    effective_zoom = max(zoom, 2)
    cell_size = 180.0 / (2 ** effective_zoom)

    # Build subquery filter for the representative photo (same bounds + dates + visibility)
    p2_vis_sql, p2_vis_params = get_visibility_clause(user_id, table_alias='p2')
    p2_where = f"p2.gps_latitude IS NOT NULL AND {p2_vis_sql}"
    p2_params = list(p2_vis_params)
    if date_from:
        p2_where += " AND p2.date_taken >= ?"
        p2_params.append(to_exif_date(date_from))
    if date_to:
        p2_where += " AND p2.date_taken <= ?"
        p2_params.append(to_exif_date(date_to) + " 23:59:59")

    cur = await conn.execute(
        f"SELECT "
        f"  AVG(gps_latitude) AS avg_lat, "
        f"  AVG(gps_longitude) AS avg_lng, "
        f"  COUNT(*) AS count, "
        f"  (SELECT p2.path FROM photos p2 "
        f"   WHERE {p2_where} "
        f"   AND ROUND(p2.gps_latitude / ?, 0) = ROUND(photos.gps_latitude / ?, 0) "
        f"   AND ROUND(p2.gps_longitude / ?, 0) = ROUND(photos.gps_longitude / ?, 0) "
        f"   ORDER BY p2.aggregate DESC, p2.path ASC LIMIT 1) AS representative_path "
        f"FROM photos "
        f"WHERE {base_where} "
        f"GROUP BY ROUND(gps_latitude / ?, 0), ROUND(gps_longitude / ?, 0) "
        f"ORDER BY count DESC "
        f"LIMIT ?",
        p2_params
        + [cell_size, cell_size, cell_size, cell_size]
        + base_params
        + [cell_size, cell_size, limit],
    )
    rows = await cur.fetchall()
    await cur.close()

    clusters = [
        {
            'lat': row['avg_lat'],
            'lng': row['avg_lng'],
            'count': row['count'],
            'representative_path': row['representative_path'],
        }
        for row in rows
    ]
    return {'clusters': clusters, 'photos': []}


async def _get_individual_photos(conn, base_where, base_params, limit):
    """Return individual photo locations for high zoom levels."""
    cur = await conn.execute(
        f"SELECT path, gps_latitude AS lat, gps_longitude AS lng, "
        f"  aggregate, filename, date_taken, category "
        f"FROM photos "
        f"WHERE {base_where} "
        f"ORDER BY aggregate DESC, path ASC "
        f"LIMIT ?",
        base_params + [limit],
    )
    rows = await cur.fetchall()
    await cur.close()

    photos = [
        {
            'path': row['path'],
            'lat': row['lat'],
            'lng': row['lng'],
            'aggregate': row['aggregate'],
            'filename': row['filename'],
            'date_taken': row['date_taken'],
            'category': row['category'],
        }
        for row in rows
    ]
    return {'clusters': [], 'photos': photos}


@router.get("/api/photos/map", response_model=PhotoMapResponse, response_model_exclude_unset=True)
async def api_photos_map(
    bounds: str = Query(..., description="sw_lat,sw_lng,ne_lat,ne_lng"),
    zoom: int = Query(10, ge=0, le=22),
    limit: int = Query(500, ge=1, le=2000),
    date_from: str = Query(None, description="Filter photos from this date (YYYY-MM-DD)"),
    date_to: str = Query(None, description="Filter photos to this date (YYYY-MM-DD)"),
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Return photo locations within bounds, clustered at low zoom or individual at high zoom."""
    existing_cols = get_existing_columns()
    if 'gps_latitude' not in existing_cols or 'gps_longitude' not in existing_cols:
        return {'photos': [], 'clusters': []}

    # Parse bounds
    try:
        parts = [float(x) for x in bounds.split(',')]
        if len(parts) != 4:
            raise ValueError
        sw_lat, sw_lng, ne_lat, ne_lng = parts
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail='Invalid bounds format. Expected: sw_lat,sw_lng,ne_lat,ne_lng')

    async with get_async_db() as conn:
        user_id = user.user_id if user else None
        vis_sql, vis_params = get_visibility_clause(user_id)

        # Handle antimeridian wrap-around: when sw_lng > ne_lng, the bounds
        # cross the antimeridian so we use OR instead of BETWEEN for longitude.
        if sw_lng > ne_lng:
            lng_clause = "(gps_longitude >= ? OR gps_longitude <= ?)"
        else:
            lng_clause = "gps_longitude BETWEEN ? AND ?"

        base_where = (
            f"gps_latitude IS NOT NULL AND gps_longitude IS NOT NULL "
            f"AND gps_latitude BETWEEN ? AND ? "
            f"AND {lng_clause} "
            f"AND {vis_sql}"
        )
        base_params = [sw_lat, ne_lat, sw_lng, ne_lng] + vis_params

        if date_from:
            if not _DATE_RE.match(date_from):
                raise HTTPException(status_code=400, detail='Invalid date_from format. Expected: YYYY-MM-DD')
            base_where += " AND date_taken >= ?"
            base_params.append(to_exif_date(date_from))
        if date_to:
            if not _DATE_RE.match(date_to):
                raise HTTPException(status_code=400, detail='Invalid date_to format. Expected: YYYY-MM-DD')
            base_where += " AND date_taken <= ?"
            base_params.append(to_exif_date(date_to) + " 23:59:59")

        if zoom < _get_cluster_zoom_threshold():
            return await _get_clustered_photos(
                conn, zoom, date_from, date_to, user_id,
                base_where, base_params, limit,
            )
        else:
            return await _get_individual_photos(
                conn, base_where, base_params, limit,
            )


@router.get("/api/photos/map/count", response_model=PhotoMapCountResponse, response_model_exclude_unset=True)
async def api_photos_map_count(
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Return count of photos with GPS data, for nav badge visibility."""
    existing_cols = get_existing_columns()
    if 'gps_latitude' not in existing_cols or 'gps_longitude' not in existing_cols:
        return {'count': 0}

    async with get_async_db() as conn:
        user_id = user.user_id if user else None
        vis_sql, vis_params = get_visibility_clause(user_id)

        cur = await conn.execute(
            f"SELECT COUNT(*) AS cnt FROM photos "
            f"WHERE gps_latitude IS NOT NULL AND gps_longitude IS NOT NULL AND {vis_sql}",
            vis_params,
        )
        row = await cur.fetchone()
        await cur.close()

        return {'count': row['cnt']}


class GpsUpdateRequest(BaseModel):
    path: str
    gps_latitude: Latitude | None = None
    gps_longitude: Longitude | None = None
    saved_place_id: int | None = None

    @model_validator(mode='after')
    def paired_coordinates(self):
        if (self.gps_latitude is None) != (self.gps_longitude is None):
            raise ValueError('Both coordinates must be set or both null')
        return self


class GpsUpdateResponse(BaseModel):
    gps_latitude: float | None
    gps_longitude: float | None


class BatchGpsRequest(BatchPhotoRequest):
    gps_latitude: Latitude
    gps_longitude: Longitude
    saved_place_id: int | None = None
    only_missing: bool = True
    preview: bool = False
    preview_token: str | None = Field(default=None, max_length=64)


class BatchGpsResponse(BaseModel):
    changed: int
    skipped: int
    preview_token: str


def _gps_batch_scopes(conn: sqlite3.Connection, body: BatchGpsRequest, user: CurrentUser) -> Iterator[tuple[str, list]]:
    """Reuse gallery visibility/album checks; keep explicit SQL binds bounded."""
    if body.filters is not None:
        from_clause, where, params = _batch_scope_sql(conn, body, user)
        yield f"SELECT DISTINCT photos.path FROM {from_clause}{where} LIMIT 1001", params
    else:
        excluded = set(body.exclude or ())
        paths = list(dict.fromkeys(p for p in body.photo_paths or () if p not in excluded))
        vis_sql, vis_params = get_visibility_clause(user.user_id if user else None)
        for start in range(0, len(paths), 400):
            chunk = paths[start:start + 400]
            marks = ','.join('?' for _ in chunk)
            yield f"SELECT path FROM photos WHERE path IN ({marks}) AND {vis_sql}", [*chunk, *vis_params]


@router.post("/api/photos/batch_gps", response_model=BatchGpsResponse)
def api_batch_gps(body: BatchGpsRequest, user: CurrentUser = Depends(require_edition)) -> dict:
    """Preview or assign one location to a visible selection, without file writes.

    The preview snapshot, visibility, missing coordinates and saved-place
    ownership are checked again under the apply transaction's write lock.
    Equal coordinates are skipped rather than pinning an unchanged file location.
    The deterministic token guards against stale inputs; it is not authorization
    or proof that a preview was requested. Edition access remains required.
    """
    if not {'gps_latitude', 'gps_longitude', 'gps_manually_set'} <= get_existing_columns():
        raise HTTPException(status_code=400, detail="GPS columns not available")
    owner = place_owner(user)
    with get_db() as conn, conn:
        try:
            conn.execute("BEGIN" if body.preview else "BEGIN IMMEDIATE")
            if body.saved_place_id is not None:
                saved = places.get_place(conn, owner, body.saved_place_id)
                if (saved['latitude'], saved['longitude']) != (body.gps_latitude, body.gps_longitude):
                    raise places.PlaceError(409, 'Saved place coordinates changed')
            rows = []
            for scope, params in _gps_batch_scopes(conn, body, user):
                rows.extend(conn.execute(
                    f"SELECT path, gps_latitude, gps_longitude, gps_manually_set FROM photos WHERE path IN ({scope}) ORDER BY path LIMIT 1001",
                    params,
                ).fetchall())
                if len(rows) > 1000:
                    raise HTTPException(status_code=412, detail="Select at most 1000 photos for location assignment")
            rows.sort(key=lambda row: row['path'])
            coordinates = [body.gps_latitude, body.gps_longitude]
            token = hashlib.sha256(json.dumps(
                [owner, [tuple(row) for row in rows], coordinates, body.only_missing, body.saved_place_id],
                ensure_ascii=True, separators=(',', ':'),
            ).encode()).hexdigest()
            if not body.preview and body.preview_token != token:
                raise HTTPException(status_code=409, detail="Selection changed; preview again before applying")
            changed_paths = [row['path'] for row in rows
                             if (row['gps_latitude'], row['gps_longitude']) != tuple(coordinates)
                             and (not body.only_missing or row['gps_latitude'] is None or row['gps_longitude'] is None)]
            if not body.preview:
                history_before = organization_history.begin(conn, user.user_id, 'gps', changed_paths)
                for start in range(0, len(changed_paths), 400):
                    chunk = changed_paths[start:start + 400]
                    marks = ','.join('?' for _ in chunk)
                    conn.execute(
                        f"UPDATE photos SET gps_latitude=?, gps_longitude=?, gps_manually_set=1 WHERE path IN ({marks})",
                        [*coordinates, *chunk],
                    )
                organization_history.finish(conn, user.user_id, 'gps', history_before)
                if changed_paths:
                    # One user action, regardless of the size of the selection.
                    places.record_assignment(conn, owner, body.gps_latitude, body.gps_longitude, body.saved_place_id)
            conn.commit()
            return {'changed': len(changed_paths), 'skipped': len(rows) - len(changed_paths), 'preview_token': token}
        except places.PlaceError as exc:
            raise HTTPException(status_code=exc.status, detail=exc.detail) from exc
        except sqlite3.Error as exc:
            logger.exception("Database error assigning batch GPS")
            raise HTTPException(status_code=500, detail='Internal server error') from exc


@router.put("/api/photo/gps", response_model=GpsUpdateResponse)
def api_update_gps(
    body: GpsUpdateRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Update GPS coordinates for a photo (edition mode required)."""
    existing_cols = get_existing_columns()
    if 'gps_latitude' not in existing_cols or 'gps_longitude' not in existing_cols:
        raise HTTPException(status_code=400, detail="GPS columns not available")

    owner = place_owner(user)

    with get_db() as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            user_id = user.user_id if user else None
            vis_sql, vis_params = get_visibility_clause(user_id)

            row = conn.execute(
                f"SELECT path FROM photos WHERE path = ? AND {vis_sql}",
                [body.path] + vis_params,
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Photo not found")

            if body.saved_place_id is not None:
                saved = places.get_place(conn, owner, body.saved_place_id)
                if (saved['latitude'], saved['longitude']) != (body.gps_latitude, body.gps_longitude):
                    raise places.PlaceError(409, 'Saved place coordinates changed')
            history_before = organization_history.begin(conn, user.user_id, 'gps', [body.path])
            conn.execute(
                f"UPDATE photos SET gps_latitude = ?, gps_longitude = ?, gps_manually_set = 1 WHERE path = ? AND {vis_sql}",
                [body.gps_latitude, body.gps_longitude, body.path] + vis_params,
            )
            organization_history.finish(conn, user.user_id, 'gps', history_before)
            places.record_assignment(conn, owner, body.gps_latitude, body.gps_longitude, body.saved_place_id)
            result = dict(conn.execute(
                'SELECT gps_latitude, gps_longitude FROM photos WHERE path=?', (body.path,)
            ).fetchone())
            conn.commit()
            return result
        except places.PlaceError as exc:
            conn.rollback()
            raise HTTPException(status_code=exc.status, detail=exc.detail) from exc
        except sqlite3.Error:
            logger.exception("Database error updating GPS for photo %s", body.path)
            conn.rollback()
            raise HTTPException(status_code=500, detail='Internal server error')


@router.delete("/api/photo/gps", response_model=GpsUpdateResponse)
def api_reset_gps(
    path: str = Query(...),
    user: CurrentUser = Depends(require_edition),
):
    """Drop a photo's hand-set location and re-read the file's own GPS (edition mode required)."""
    existing_cols = get_existing_columns()
    if 'gps_latitude' not in existing_cols or 'gps_longitude' not in existing_cols or 'gps_manually_set' not in existing_cols:
        raise HTTPException(status_code=400, detail="GPS columns not available")
    user_id = user.user_id if user else None
    vis_sql, vis_params = get_visibility_clause(user_id)
    with get_db() as conn:
        row = conn.execute(
            f"SELECT path FROM photos WHERE path = ? AND {vis_sql}",
            [path] + vis_params,
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Photo not found")
    # Read the file outside the write transaction: exiftool can take seconds.
    exif_by_path = get_exif_batch([resolve_photo_disk_path(path)])
    if not exif_by_path:
        raise HTTPException(status_code=404, detail="File not readable")
    exif = next(iter(exif_by_path.values()))
    lat, lng = exif.get('gps_latitude'), exif.get('gps_longitude')
    if lat is None or lng is None:
        lat = lng = None
    try:
        restored = GpsUpdateRequest(path=path, gps_latitude=lat, gps_longitude=lng)
    except ValidationError as exc:
        raise HTTPException(status_code=409, detail="File GPS is invalid; the manual location was kept") from exc
    lat, lng = restored.gps_latitude, restored.gps_longitude
    with get_db() as conn, conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            # ExifTool runs outside the lock. Access or the photo itself may
            # have disappeared since the initial read; never reuse that scope.
            vis_sql, vis_params = get_visibility_clause(user_id)
            row = conn.execute(
                f"SELECT 1 FROM photos WHERE path = ? AND {vis_sql}",
                [path] + vis_params,
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Photo not found")
            history_before = organization_history.begin(conn, user.user_id, 'gps', [path])
            cursor = conn.execute(
                f"UPDATE photos SET gps_latitude = ?, gps_longitude = ?, gps_manually_set = 0 WHERE path = ? AND {vis_sql}",
                [lat, lng, path] + vis_params,
            )
            if cursor.rowcount != 1:
                raise HTTPException(status_code=404, detail="Photo not found")
            organization_history.finish(conn, user.user_id, 'gps', history_before)
            conn.commit()
        except sqlite3.Error:
            logger.exception("Database error resetting GPS for photo %s", path)
            conn.rollback()
            raise HTTPException(status_code=500, detail='Internal server error')
    return {'gps_latitude': lat, 'gps_longitude': lng}
