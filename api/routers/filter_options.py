"""
Filter options router — lazy-loaded dropdown options.

"""

import logging
import sqlite3
from typing import Optional
from fastapi import APIRouter, Depends

from api.auth import CurrentUser, get_optional_user
from api.config import VIEWER_CONFIG, is_multi_user_enabled
from api.database import get_async_db, get_db
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


async def _cached_filter_query(cache_key, result_key, query_fn):
    """Generic cache-then-async-query helper for filter option endpoints.

    ``query_fn`` is an ``async def fn(conn)`` coroutine that returns the
    list of rows for the dropdown.
    """
    from db import get_cached_stat, DEFAULT_DB_PATH
    if not is_multi_user_enabled():
        data, is_fresh = get_cached_stat(DEFAULT_DB_PATH, cache_key, max_age_seconds=300)
        if data and is_fresh:
            return {result_key: data, 'cached': True}

    async with get_async_db() as conn:
        data = await query_fn(conn)
    return {result_key: data, 'cached': False}


async def _fetch_all(conn, sql: str, params=None):
    cursor = await conn.execute(sql, params or [])
    try:
        return await cursor.fetchall()
    finally:
        await cursor.close()


@router.get("/cameras")
async def cameras(user: Optional[CurrentUser] = Depends(get_optional_user)):
    """Lazy-load camera options with counts."""
    vis, vp = _vis_where(user)

    async def query(conn):
        rows = await _fetch_all(
            conn,
            f"""
            SELECT camera_model, COUNT(*) as cnt FROM photos
            WHERE camera_model IS NOT NULL{vis}
            GROUP BY camera_model ORDER BY cnt DESC LIMIT ?
            """,
            vp + [VIEWER_CONFIG['dropdowns']['max_cameras']],
        )
        return [(r[0], r[1]) for r in rows]

    return await _cached_filter_query('cameras', 'cameras', query)


@router.get("/lenses")
async def lenses(user: Optional[CurrentUser] = Depends(get_optional_user)):
    """Lazy-load lens options with counts."""
    vis, vp = _vis_where(user)

    async def query(conn):
        rows = await _fetch_all(
            conn,
            f"""
            SELECT lens_model, COUNT(*) as cnt FROM photos
            WHERE lens_model IS NOT NULL{vis}
            GROUP BY lens_model ORDER BY cnt DESC LIMIT ?
            """,
            vp + [VIEWER_CONFIG['dropdowns']['max_lenses']],
        )
        return [(r[0], r[1]) for r in rows]

    return await _cached_filter_query('lenses', 'lenses', query)


@router.get("/tags")
async def tags(user: Optional[CurrentUser] = Depends(get_optional_user)):
    """Lazy-load tag options with counts."""
    from db import get_cached_stat, DEFAULT_DB_PATH

    max_tags = VIEWER_CONFIG['dropdowns']['max_tags']
    vis, vp = _vis_where(user)

    if not is_multi_user_enabled():
        data, is_fresh = get_cached_stat(DEFAULT_DB_PATH, 'tags', max_age_seconds=300)
        if data and is_fresh:
            return {'tags': data[:max_tags], 'cached': True}

    async with get_async_db() as conn:
        # `is_photo_tags_available` runs a `SELECT name FROM sqlite_master`
        # under a sync connection; the result is stable per server lifetime
        # so the synchronous probe is fine here.
        photo_tags_ready = False
        with get_db() as sync_conn:
            photo_tags_ready = is_photo_tags_available(sync_conn)

        if photo_tags_ready:
            try:
                vis_sub = f' AND photo_path IN (SELECT path FROM photos WHERE 1=1{vis})' if vis else ''
                rows = await _fetch_all(
                    conn,
                    f"""
                    SELECT tag, COUNT(*) as cnt
                    FROM photo_tags
                    WHERE 1=1{vis_sub}
                    GROUP BY tag
                    ORDER BY cnt DESC, tag ASC
                    LIMIT ?
                    """,
                    vp + [max_tags],
                )
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
            rows = await _fetch_all(conn, tag_query, vp + [max_tags])
            return {'tags': [(r[0], r[1]) for r in rows], 'cached': False}
        except sqlite3.Error:
            logger.exception("Failed to query tags")
            return {'tags': [], 'cached': False}


@router.get("/persons")
async def persons(ids: Optional[str] = None, user: Optional[CurrentUser] = Depends(get_optional_user)):
    """Lazy-load person options with photo counts. `ids` forces specific persons to be included."""
    vis, vp = _vis_where(user)
    forced_ids = [int(i) for i in ids.split(',') if i.strip().isdigit()] if ids else []

    async def query(conn):
        try:
            min_photos = VIEWER_CONFIG['dropdowns'].get('min_photos_for_person', 1)
            vis_join = f' AND f.photo_path IN (SELECT path FROM photos WHERE 1=1{vis})' if vis else ''
            rows = await _fetch_all(
                conn,
                f"""
                SELECT p.id, p.name, COUNT(DISTINCT f.photo_path) as photo_count
                FROM persons p
                JOIN faces f ON f.person_id = p.id
                WHERE 1=1{vis_join}
                GROUP BY p.id HAVING photo_count >= ?
                ORDER BY photo_count DESC LIMIT ?
                """,
                vp + [min_photos, VIEWER_CONFIG['dropdowns']['max_persons']],
            )
            result = [(r[0], r[1], r[2]) for r in rows]
            if forced_ids:
                present = {r[0] for r in result}
                missing = [i for i in forced_ids if i not in present]
                if missing:
                    placeholders = ','.join('?' * len(missing))
                    extra = await _fetch_all(
                        conn,
                        f"""
                        SELECT p.id, p.name, COUNT(DISTINCT f.photo_path) as photo_count
                        FROM persons p
                        JOIN faces f ON f.person_id = p.id
                        WHERE p.id IN ({placeholders}){vis_join}
                        GROUP BY p.id
                        """,
                        missing + vp,
                    )
                    result = [(r[0], r[1], r[2]) for r in extra] + result
            return result
        except sqlite3.Error:
            logger.exception("Failed to query persons")
            return []

    if forced_ids:
        async with get_async_db() as conn:
            data = await query(conn)
        return {'persons': data, 'cached': False}
    return await _cached_filter_query('persons', 'persons', query)


@router.get("/patterns")
async def patterns(user: Optional[CurrentUser] = Depends(get_optional_user)):
    """Lazy-load composition pattern options with counts."""
    vis, vp = _vis_where(user)

    async def query(conn):
        try:
            rows = await _fetch_all(
                conn,
                f"""
                SELECT composition_pattern, COUNT(*) as cnt FROM photos
                WHERE composition_pattern IS NOT NULL AND composition_pattern != ''{vis}
                GROUP BY composition_pattern ORDER BY cnt DESC
                """,
                vp,
            )
            return [(r[0], r[1]) for r in rows]
        except sqlite3.Error:
            logger.exception("Failed to query composition patterns")
            return []

    return await _cached_filter_query('composition_patterns', 'patterns', query)


@router.get("/apertures")
async def apertures(user: Optional[CurrentUser] = Depends(get_optional_user)):
    """Lazy-load distinct rounded aperture values with counts."""
    vis, vp = _vis_where(user)

    async def query(conn):
        try:
            rows = await _fetch_all(
                conn,
                f"""
                SELECT ROUND(f_stop, 1) as ap, COUNT(*) as cnt
                FROM photos
                WHERE f_stop IS NOT NULL AND f_stop > 0 AND f_stop < 1000{vis}
                GROUP BY ap ORDER BY ap ASC
                """,
                vp,
            )
            return [(r[0], r[1]) for r in rows]
        except sqlite3.Error:
            logger.exception("Failed to query apertures")
            return []

    return await _cached_filter_query('apertures', 'apertures', query)


@router.get("/focal_lengths")
async def focal_lengths(user: Optional[CurrentUser] = Depends(get_optional_user)):
    """Lazy-load distinct rounded focal length values with counts."""
    vis, vp = _vis_where(user)

    async def query(conn):
        try:
            rows = await _fetch_all(
                conn,
                f"""
                SELECT CAST(ROUND(focal_length) AS INTEGER) as fl, COUNT(*) as cnt
                FROM photos
                WHERE focal_length IS NOT NULL AND focal_length > 0{vis}
                GROUP BY fl ORDER BY fl ASC
                """,
                vp,
            )
            return [(r[0], r[1]) for r in rows]
        except sqlite3.Error:
            logger.exception("Failed to query focal lengths")
            return []

    return await _cached_filter_query('focal_lengths', 'focal_lengths', query)


@router.get("/categories")
async def categories(user: Optional[CurrentUser] = Depends(get_optional_user)):
    """Lazy-load category options with counts."""
    vis, vp = _vis_where(user)

    async def query(conn):
        try:
            rows = await _fetch_all(
                conn,
                f"""
                SELECT category, COUNT(*) as cnt FROM photos
                WHERE category IS NOT NULL{vis}
                GROUP BY category ORDER BY cnt DESC
                """,
                vp,
            )
            return [(r[0], r[1]) for r in rows]
        except sqlite3.Error:
            logger.exception("Failed to query categories")
            return []

    return await _cached_filter_query('categories', 'categories', query)


@router.get("/location_name")
def location_name(lat: float, lng: float):
    """Reverse geocode coordinates to a place name, using location_names cache.

    Stays sync — the underlying ``geocode_grid`` helper is sync and the
    endpoint is per-photo (low concurrency), so async migration would only
    add complexity for no measurable gain.
    """
    from analyzers.capsule_generator import geocode_grid

    with get_db() as conn:
        name = geocode_grid(conn, lat, lng)
        return {"display_name": name}


# Max rows materialized for the metric histograms (exact min/max come from SQL,
# so this only bounds the sparkline sample, never the slider bounds).
_METRIC_RANGE_SAMPLE_CAP = 50000


def _compute_metric_ranges():
    """Observed min/max and a value histogram per numeric metric column.

    Powers data-driven slider bounds (clamping) and the distribution sparkline
    in the gallery filter sidebar. Bounds are exact (SQL MIN/MAX); the histogram
    is from a bounded sample. Cached; values are global (not visibility-filtered)
    since they are only a UI hint.
    """
    import numpy as np
    from api.routers.gallery import SCORE_RANGE_COLUMNS, EXIF_RANGE_COLUMNS

    metrics = SCORE_RANGE_COLUMNS + EXIF_RANGE_COLUMNS
    columns = [m[0] for m in metrics]  # hardcoded column names — safe to interpolate
    n_bins = 20
    # Histograms are sparkline hints, so a bounded, evenly-spaced sample is enough.
    # Exact min/max still come from a SQL aggregate (cheap, no row materialization),
    # so slider bounds stay precise while memory stays O(sample), not O(table).
    sample_cap = _METRIC_RANGE_SAMPLE_CAP
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
        if not total:
            return {}
        agg_select = ', '.join(f"MIN({c}), MAX({c})" for c in columns)
        agg = conn.execute(f"SELECT {agg_select} FROM photos").fetchone()
        stride = max(1, -(-total // sample_cap))  # ceil(total / sample_cap)
        if stride > 1:
            cur = conn.execute(
                f"SELECT {', '.join(columns)} FROM photos WHERE rowid % {stride} = 0"
            )
        else:
            cur = conn.execute(f"SELECT {', '.join(columns)} FROM photos")
        rows = cur.fetchall()

    if not rows:
        return {}
    # NULL -> nan; slice per column instead of re-iterating rows per metric.
    matrix = np.array(rows, dtype=float)

    result = {}
    for idx, (_column, min_key, _max_key, _is_float) in enumerate(metrics):
        v_min, v_max = agg[idx * 2], agg[idx * 2 + 1]
        if v_min is None or v_max is None:
            continue
        v_min, v_max = float(v_min), float(v_max)
        values = matrix[:, idx]
        values = values[np.isfinite(values)]
        if v_max <= v_min:
            buckets = [int(values.size)]
        else:
            counts, _edges = np.histogram(values, bins=n_bins, range=(v_min, v_max))
            buckets = [int(c) for c in counts]
        result[min_key] = {'min': v_min, 'max': v_max, 'buckets': buckets}
    return result


@router.get("/metric_ranges")
def metric_ranges():
    """Per-metric observed range and distribution for slider clamping + histograms."""
    from api.config import _get_stats_cached
    return {'ranges': _get_stats_cached('metric_ranges', _compute_metric_ranges)}
