"""
Map view router — GPS-based photo browsing with clustering at low zoom levels.

"""

import logging
import re
import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.auth import CurrentUser, get_optional_user, require_edition
from api.database import get_db_connection
from api.db_helpers import get_existing_columns, get_visibility_clause

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


def _get_clustered_photos(conn, bounds, zoom, vis_sql, vis_params, existing_cols,
                          date_from, date_to, user_id, base_where, base_params, limit):
    """Return clustered photo locations grouped into grid cells for low zoom levels."""
    effective_zoom = max(zoom, 2)
    cell_size = 180.0 / (2 ** effective_zoom)

    # Build subquery filter for the representative photo (same bounds + dates + visibility)
    p2_vis_sql, p2_vis_params = get_visibility_clause(user_id, table_alias='p2')
    p2_where = f"p2.gps_latitude IS NOT NULL AND {p2_vis_sql}"
    p2_params = list(p2_vis_params)
    if date_from:
        p2_where += " AND p2.date_taken >= ?"
        p2_params.append(date_from)
    if date_to:
        p2_where += " AND p2.date_taken <= ?"
        p2_params.append(date_to + " 23:59:59")

    rows = conn.execute(
        f"SELECT "
        f"  AVG(gps_latitude) AS avg_lat, "
        f"  AVG(gps_longitude) AS avg_lng, "
        f"  COUNT(*) AS count, "
        f"  (SELECT p2.path FROM photos p2 "
        f"   WHERE {p2_where} "
        f"   AND ROUND(p2.gps_latitude / ?, 0) = ROUND(photos.gps_latitude / ?, 0) "
        f"   AND ROUND(p2.gps_longitude / ?, 0) = ROUND(photos.gps_longitude / ?, 0) "
        f"   ORDER BY p2.aggregate DESC LIMIT 1) AS representative_path "
        f"FROM photos "
        f"WHERE {base_where} "
        f"GROUP BY ROUND(gps_latitude / ?, 0), ROUND(gps_longitude / ?, 0) "
        f"ORDER BY count DESC "
        f"LIMIT ?",
        p2_params
        + [cell_size, cell_size, cell_size, cell_size]
        + base_params
        + [cell_size, cell_size, limit],
    ).fetchall()

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


def _get_individual_photos(conn, bounds, vis_sql, vis_params, existing_cols,
                           base_where, base_params, limit):
    """Return individual photo locations for high zoom levels."""
    rows = conn.execute(
        f"SELECT path, gps_latitude AS lat, gps_longitude AS lng, "
        f"  aggregate, filename, date_taken, category "
        f"FROM photos "
        f"WHERE {base_where} "
        f"ORDER BY aggregate DESC "
        f"LIMIT ?",
        base_params + [limit],
    ).fetchall()

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


@router.get("/api/photos/map")
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

    conn = get_db_connection()
    try:
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
            base_params.append(date_from)
        if date_to:
            if not _DATE_RE.match(date_to):
                raise HTTPException(status_code=400, detail='Invalid date_to format. Expected: YYYY-MM-DD')
            base_where += " AND date_taken <= ?"
            base_params.append(date_to + " 23:59:59")

        if zoom < _get_cluster_zoom_threshold():
            return _get_clustered_photos(
                conn, bounds, zoom, vis_sql, vis_params, existing_cols,
                date_from, date_to, user_id, base_where, base_params, limit,
            )
        else:
            return _get_individual_photos(
                conn, bounds, vis_sql, vis_params, existing_cols,
                base_where, base_params, limit,
            )

    finally:
        conn.close()


@router.get("/api/photos/map/count")
async def api_photos_map_count(
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Return count of photos with GPS data, for nav badge visibility."""
    existing_cols = get_existing_columns()
    if 'gps_latitude' not in existing_cols or 'gps_longitude' not in existing_cols:
        return {'count': 0}

    conn = get_db_connection()
    try:
        user_id = user.user_id if user else None
        vis_sql, vis_params = get_visibility_clause(user_id)

        row = conn.execute(
            f"SELECT COUNT(*) AS cnt FROM photos "
            f"WHERE gps_latitude IS NOT NULL AND gps_longitude IS NOT NULL AND {vis_sql}",
            vis_params,
        ).fetchone()

        return {'count': row['cnt']}
    finally:
        conn.close()


class GpsUpdateRequest(BaseModel):
    path: str
    gps_latitude: Optional[float] = None
    gps_longitude: Optional[float] = None


@router.put("/api/photo/gps")
async def api_update_gps(
    body: GpsUpdateRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Update GPS coordinates for a photo (edition mode required)."""
    existing_cols = get_existing_columns()
    if 'gps_latitude' not in existing_cols or 'gps_longitude' not in existing_cols:
        raise HTTPException(status_code=400, detail="GPS columns not available")

    if (body.gps_latitude is None) != (body.gps_longitude is None):
        raise HTTPException(status_code=400, detail="Both latitude and longitude must be set or both must be null")

    conn = get_db_connection()
    try:
        user_id = user.user_id if user else None
        vis_sql, vis_params = get_visibility_clause(user_id)

        row = conn.execute(
            f"SELECT path FROM photos WHERE path = ? AND {vis_sql}",
            [body.path] + vis_params,
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Photo not found")

        conn.execute(
            f"UPDATE photos SET gps_latitude = ?, gps_longitude = ? WHERE path = ? AND {vis_sql}",
            [body.gps_latitude, body.gps_longitude, body.path] + vis_params,
        )
        conn.commit()
        return {'gps_latitude': body.gps_latitude, 'gps_longitude': body.gps_longitude}
    except sqlite3.Error:
        logger.exception("Database error updating GPS for photo %s", body.path)
        conn.rollback()
        raise HTTPException(status_code=500, detail='Internal server error')
    finally:
        conn.close()
