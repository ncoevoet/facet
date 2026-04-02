"""
Filter options router — lazy-loaded dropdown options.

"""

import logging
import sqlite3
from typing import Optional
from fastapi import APIRouter, Depends

from api.auth import CurrentUser, get_optional_user
from api.config import VIEWER_CONFIG, is_multi_user_enabled
from api.database import get_db_connection
from api.db_helpers import is_photo_tags_available, get_visibility_clause

router = APIRouter(prefix="/api/filter_options", tags=["filter_options"])
logger = logging.getLogger(__name__)


def _vis_where(user: Optional[CurrentUser]):
    """Return (where_fragment, params) for visibility filtering."""
    if not user or not user.user_id:
        return '', []
    vis_sql, vis_params = get_visibility_clause(user.user_id)
    if vis_sql == '1=1':
        return '', []
    return f' AND {vis_sql}', vis_params


def _cached_filter_query(cache_key, result_key, query_fn):
    """Generic cache-then-query helper for filter option endpoints."""
    from db import get_cached_stat, DEFAULT_DB_PATH
    if not is_multi_user_enabled():
        data, is_fresh = get_cached_stat(DEFAULT_DB_PATH, cache_key, max_age_seconds=300)
        if data and is_fresh:
            return {result_key: data, 'cached': True}

    conn = get_db_connection()
    try:
        data = query_fn(conn)
    finally:
        conn.close()
    return {result_key: data, 'cached': False}


@router.get("/cameras")
def cameras(user: Optional[CurrentUser] = Depends(get_optional_user)):
    """Lazy-load camera options with counts."""
    vis, vp = _vis_where(user)
    def query(conn):
        rows = conn.execute(f"""
            SELECT camera_model, COUNT(*) as cnt FROM photos
            WHERE camera_model IS NOT NULL{vis}
            GROUP BY camera_model ORDER BY cnt DESC LIMIT ?
        """, vp + [VIEWER_CONFIG['dropdowns']['max_cameras']]).fetchall()
        return [(r[0], r[1]) for r in rows]
    return _cached_filter_query('cameras', 'cameras', query)


@router.get("/lenses")
def lenses(user: Optional[CurrentUser] = Depends(get_optional_user)):
    """Lazy-load lens options with counts."""
    vis, vp = _vis_where(user)
    def query(conn):
        rows = conn.execute(f"""
            SELECT lens_model, COUNT(*) as cnt FROM photos
            WHERE lens_model IS NOT NULL{vis}
            GROUP BY lens_model ORDER BY cnt DESC LIMIT ?
        """, vp + [VIEWER_CONFIG['dropdowns']['max_lenses']]).fetchall()
        return [(r[0], r[1]) for r in rows]
    return _cached_filter_query('lenses', 'lenses', query)


@router.get("/tags")
def tags(user: Optional[CurrentUser] = Depends(get_optional_user)):
    """Lazy-load tag options with counts."""
    from db import get_cached_stat, DEFAULT_DB_PATH

    max_tags = VIEWER_CONFIG['dropdowns']['max_tags']
    vis, vp = _vis_where(user)

    if not is_multi_user_enabled():
        data, is_fresh = get_cached_stat(DEFAULT_DB_PATH, 'tags', max_age_seconds=300)
        if data and is_fresh:
            return {'tags': data[:max_tags], 'cached': True}

    conn = get_db_connection()
    try:
        if is_photo_tags_available(conn):
            try:
                vis_sub = f' AND photo_path IN (SELECT path FROM photos WHERE 1=1{vis})' if vis else ''
                rows = conn.execute(f"""
                    SELECT tag, COUNT(*) as cnt
                    FROM photo_tags
                    WHERE 1=1{vis_sub}
                    GROUP BY tag
                    ORDER BY cnt DESC, tag ASC
                    LIMIT ?
                """, vp + [max_tags]).fetchall()
                return {'tags': [(r[0], r[1]) for r in rows], 'cached': False}
            except sqlite3.Error:
                logger.debug("photo_tags query failed, falling back to split", exc_info=True)

        tag_query = f"""
            WITH RECURSIVE split_tags(tag, rest) AS (
                SELECT '', tags || ',' FROM photos WHERE tags IS NOT NULL AND tags != ''{vis}
                UNION ALL
                SELECT TRIM(SUBSTR(rest, 1, INSTR(rest, ',') - 1)),
                       SUBSTR(rest, INSTR(rest, ',') + 1)
                FROM split_tags WHERE rest != ''
            )
            SELECT tag, COUNT(*) as cnt
            FROM split_tags
            WHERE tag != ''
            GROUP BY tag
            ORDER BY cnt DESC, tag ASC
            LIMIT ?
        """
        try:
            rows = conn.execute(tag_query, vp + [max_tags]).fetchall()
            return {'tags': [(r[0], r[1]) for r in rows], 'cached': False}
        except sqlite3.Error:
            logger.exception("Failed to query tags")
            return {'tags': [], 'cached': False}
    finally:
        conn.close()


@router.get("/persons")
def persons(ids: Optional[str] = None, user: Optional[CurrentUser] = Depends(get_optional_user)):
    """Lazy-load person options with photo counts. `ids` forces specific persons to be included."""
    vis, vp = _vis_where(user)
    forced_ids = [int(i) for i in ids.split(',') if i.strip().isdigit()] if ids else []

    def query(conn):
        try:
            min_photos = VIEWER_CONFIG['dropdowns'].get('min_photos_for_person', 1)
            vis_join = f' AND f.photo_path IN (SELECT path FROM photos WHERE 1=1{vis})' if vis else ''
            rows = conn.execute(f"""
                SELECT p.id, p.name, COUNT(DISTINCT f.photo_path) as photo_count
                FROM persons p
                JOIN faces f ON f.person_id = p.id
                WHERE 1=1{vis_join}
                GROUP BY p.id HAVING photo_count >= ?
                ORDER BY photo_count DESC LIMIT ?
            """, vp + [min_photos, VIEWER_CONFIG['dropdowns']['max_persons']]).fetchall()
            result = [(r[0], r[1], r[2]) for r in rows]
            if forced_ids:
                present = {r[0] for r in result}
                missing = [i for i in forced_ids if i not in present]
                if missing:
                    placeholders = ','.join('?' * len(missing))
                    extra = conn.execute(f"""
                        SELECT p.id, p.name, COUNT(DISTINCT f.photo_path) as photo_count
                        FROM persons p
                        JOIN faces f ON f.person_id = p.id
                        WHERE p.id IN ({placeholders}){vis_join}
                        GROUP BY p.id
                    """, missing + vp).fetchall()
                    result = [(r[0], r[1], r[2]) for r in extra] + result
            return result
        except sqlite3.Error:
            logger.exception("Failed to query persons")
            return []

    if forced_ids:
        # Bypass cache when forced IDs are requested to always include them
        conn = get_db_connection()
        try:
            data = query(conn)
        finally:
            conn.close()
        return {'persons': data, 'cached': False}
    return _cached_filter_query('persons', 'persons', query)


@router.get("/patterns")
def patterns(user: Optional[CurrentUser] = Depends(get_optional_user)):
    """Lazy-load composition pattern options with counts."""
    vis, vp = _vis_where(user)
    def query(conn):
        try:
            rows = conn.execute(f"""
                SELECT composition_pattern, COUNT(*) as cnt FROM photos
                WHERE composition_pattern IS NOT NULL AND composition_pattern != ''{vis}
                GROUP BY composition_pattern ORDER BY cnt DESC
            """, vp).fetchall()
            return [(r[0], r[1]) for r in rows]
        except sqlite3.Error:
            logger.exception("Failed to query composition patterns")
            return []
    return _cached_filter_query('composition_patterns', 'patterns', query)


@router.get("/apertures")
def apertures(user: Optional[CurrentUser] = Depends(get_optional_user)):
    """Lazy-load distinct rounded aperture values with counts."""
    vis, vp = _vis_where(user)
    def query(conn):
        try:
            rows = conn.execute(f"""
                SELECT ROUND(f_stop, 1) as ap, COUNT(*) as cnt
                FROM photos
                WHERE f_stop IS NOT NULL AND f_stop > 0 AND f_stop < 1000{vis}
                GROUP BY ap ORDER BY ap ASC
            """, vp).fetchall()
            return [(r[0], r[1]) for r in rows]
        except sqlite3.Error:
            logger.exception("Failed to query apertures")
            return []
    return _cached_filter_query('apertures', 'apertures', query)


@router.get("/focal_lengths")
def focal_lengths(user: Optional[CurrentUser] = Depends(get_optional_user)):
    """Lazy-load distinct rounded focal length values with counts."""
    vis, vp = _vis_where(user)
    def query(conn):
        try:
            rows = conn.execute(f"""
                SELECT CAST(ROUND(focal_length) AS INTEGER) as fl, COUNT(*) as cnt
                FROM photos
                WHERE focal_length IS NOT NULL AND focal_length > 0{vis}
                GROUP BY fl ORDER BY fl ASC
            """, vp).fetchall()
            return [(r[0], r[1]) for r in rows]
        except sqlite3.Error:
            logger.exception("Failed to query focal lengths")
            return []
    return _cached_filter_query('focal_lengths', 'focal_lengths', query)


@router.get("/categories")
def categories(user: Optional[CurrentUser] = Depends(get_optional_user)):
    """Lazy-load category options with counts."""
    vis, vp = _vis_where(user)
    def query(conn):
        try:
            rows = conn.execute(f"""
                SELECT category, COUNT(*) as cnt FROM photos
                WHERE category IS NOT NULL{vis}
                GROUP BY category ORDER BY cnt DESC
            """, vp).fetchall()
            return [(r[0], r[1]) for r in rows]
        except sqlite3.Error:
            logger.exception("Failed to query categories")
            return []
    return _cached_filter_query('categories', 'categories', query)


@router.get("/location_name")
def location_name(lat: float, lng: float):
    """Reverse geocode coordinates to a place name, using location_names cache."""
    from analyzers.capsule_generator import geocode_grid

    conn = get_db_connection()
    try:
        name = geocode_grid(conn, lat, lng)
        return {"display_name": name}
    finally:
        conn.close()
