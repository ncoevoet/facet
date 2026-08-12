"""
Filter options router — lazy-loaded dropdown options.

"""

import json
import logging
import math
import sqlite3
import time
from typing import Optional
from fastapi import APIRouter, Depends

from api.auth import CurrentUser, get_optional_user, require_authenticated
from api.config import VIEWER_CONFIG, is_multi_user_enabled
from api.database import get_async_db, get_db
from api.db_helpers import is_photo_tags_available, get_visibility_clause
from db import person_not_hidden_clause

router = APIRouter(prefix="/api/filter_options", tags=["filter_options"])
logger = logging.getLogger(__name__)


def _vis_where(user: Optional[CurrentUser]):
    """Return (where_fragment, params) for visibility filtering.

    Returns ('', []) on a fully open install. On an access-controlled deployment
    (multi-user, or a single-user viewer password) an unauthenticated request
    resolves to (' AND 0=1', []) so it sees nothing; ``get_visibility_clause``
    owns that carve-out, so this must never short-circuit before calling it.
    """
    user_id = user.user_id if user else None
    vis_sql, vis_params = get_visibility_clause(user_id)
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
                WHERE {person_not_hidden_clause('p')}{vis_join}
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


async def _store_color_cache(conn, temps, hue_buckets):
    """Persist the colour facets into ``stats_cache`` (best-effort).

    Lets repeated dropdown opens skip the full ``dominant_hue`` scan. Failures
    (e.g. a missing table before init) are swallowed so a cache miss never
    breaks the actual response.
    """
    now = time.time()
    try:
        await conn.execute(
            "INSERT OR REPLACE INTO stats_cache (key, value, updated_at) VALUES (?, ?, ?)",
            ('color_temps', json.dumps(temps), now),
        )
        await conn.execute(
            "INSERT OR REPLACE INTO stats_cache (key, value, updated_at) VALUES (?, ?, ?)",
            ('color_hue_buckets', json.dumps(hue_buckets), now),
        )
        await conn.commit()
    except sqlite3.Error:
        logger.debug("Failed to cache color facets", exc_info=True)


@router.get("/colors")
async def colors(user: Optional[CurrentUser] = Depends(get_optional_user)):
    """Lazy-load colour facets: warm/cool/neutral temps and hue buckets with counts.

    Returns ``{'temps': [(temp, count)], 'hue_buckets': [(bucket, count)]}``.
    Both lists are empty until ``--recompute-colors`` has populated the
    ``color_temp`` / ``dominant_hue`` columns.

    Cached in ``stats_cache`` (300s TTL) like the sibling dropdowns so the full
    column scan runs at most once per window; bypassed in multi-user mode where
    the counts are visibility-scoped per user.
    """
    from api.routers.gallery import HUE_BUCKETS, bucket_for_hue
    from db import get_cached_stat, DEFAULT_DB_PATH
    vis, vp = _vis_where(user)
    use_cache = not is_multi_user_enabled()

    if use_cache:
        temps_cached, temps_fresh = get_cached_stat(DEFAULT_DB_PATH, 'color_temps', max_age_seconds=300)
        hues_cached, hues_fresh = get_cached_stat(DEFAULT_DB_PATH, 'color_hue_buckets', max_age_seconds=300)
        if temps_fresh and hues_fresh and temps_cached is not None and hues_cached is not None:
            return {'temps': temps_cached, 'hue_buckets': hues_cached, 'cached': True}

    async def query(conn):
        try:
            temp_rows = await _fetch_all(
                conn,
                f"""
                SELECT color_temp, COUNT(*) as cnt FROM photos
                WHERE color_temp IS NOT NULL{vis}
                GROUP BY color_temp ORDER BY cnt DESC
                """,
                vp,
            )
            temps = [(r[0], r[1]) for r in temp_rows]

            # One grouped scan over hue ranges; bucket in Python to avoid a
            # CASE-per-bucket SQL expression that the planner can't index.
            hue_rows = await _fetch_all(
                conn,
                f"""
                SELECT dominant_hue FROM photos
                WHERE dominant_hue IS NOT NULL{vis}
                """,
                vp,
            )
            counts = {name: 0 for name in HUE_BUCKETS}
            for (hue,) in hue_rows:
                name = bucket_for_hue(hue)
                if name is not None:
                    counts[name] += 1
            hue_buckets = [(name, counts[name]) for name in HUE_BUCKETS if counts[name]]
            if use_cache:
                await _store_color_cache(conn, temps, hue_buckets)
            return {'temps': temps, 'hue_buckets': hue_buckets}
        except sqlite3.Error:
            logger.exception("Failed to query colors")
            return {'temps': [], 'hue_buckets': []}

    async with get_async_db() as conn:
        data = await query(conn)
    return {**data, 'cached': False}


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


@router.get("/narrative_moments")
async def narrative_moments(user: Optional[CurrentUser] = Depends(get_optional_user)):
    """Lazy-load narrative-moment options with counts."""
    vis, vp = _vis_where(user)

    async def query(conn):
        try:
            rows = await _fetch_all(
                conn,
                f"""
                SELECT narrative_moment, COUNT(*) as cnt FROM photos
                WHERE narrative_moment IS NOT NULL{vis}
                GROUP BY narrative_moment ORDER BY cnt DESC
                """,
                vp,
            )
            return [(r[0], r[1]) for r in rows]
        except sqlite3.Error:
            logger.exception("Failed to query narrative_moments")
            return []

    return await _cached_filter_query('narrative_moments', 'narrative_moments', query)


@router.get("/junk_kinds")
async def junk_kinds(user: Optional[CurrentUser] = Depends(get_optional_user)):
    """Lazy-load junk-kind options with counts (excludes the 'not_junk' sentinel)."""
    from api.types import JUNK_NOT_JUNK
    vis, vp = _vis_where(user)

    async def query(conn):
        try:
            rows = await _fetch_all(
                conn,
                f"""
                SELECT junk_kind, COUNT(*) as cnt FROM photos
                WHERE junk_kind IS NOT NULL AND junk_kind != ?{vis}
                GROUP BY junk_kind ORDER BY cnt DESC
                """,
                [JUNK_NOT_JUNK, *vp],
            )
            return [(r[0], r[1]) for r in rows]
        except sqlite3.Error:
            logger.exception("Failed to query junk_kinds")
            return []

    return await _cached_filter_query('junk_kinds', 'junk_kinds', query)


@router.get("/location_name")
def location_name(
    lat: float, lng: float,
    user: CurrentUser = Depends(require_authenticated),
):
    """Reverse geocode coordinates to a place name, using location_names cache.

    Stays sync — the underlying ``geocode_grid`` helper is sync and the
    endpoint is per-photo (low concurrency), so async migration would only
    add complexity for no measurable gain.
    """
    from analyzers.capsule_generator import geocode_grid

    with get_db() as conn:
        name = geocode_grid(conn, lat, lng)
        return {"display_name": name}


# Sparkline resolution for the metric histograms in the filter sidebar.
_METRIC_RANGE_BINS = 20
# Key and freshness of the persisted result. Matches the in-process stats TTL
# and the scenes cache (api/routers/scenes.py), so the DB row only exists to
# carry the work across a restart.
_METRIC_RANGES_KEY = 'metric_ranges'
_METRIC_RANGES_TTL_SECONDS = 3600


def _metric_bounds(conn, column):
    """Exact observed ``(min, max)`` for one metric column, ``None`` if all NULL.

    Each aggregate is its own statement so SQLite applies the MIN/MAX
    optimization over that column's covering index. Asking for all 38 metrics in
    a single aggregate leaves the planner one index to pick, so it scans
    ``photos`` instead — and with thumbnails stored inline that drags every BLOB
    overflow page through the cache (55+ minutes on a 120k-photo library).
    """
    v_min = conn.execute(f"SELECT MIN({column}) FROM photos").fetchone()[0]
    v_max = conn.execute(f"SELECT MAX({column}) FROM photos").fetchone()[0]
    if v_min is None or v_max is None:
        return None
    v_min, v_max = float(v_min), float(v_max)
    if math.isfinite(v_min) and math.isfinite(v_max):
        return v_min, v_max
    # A stored infinity (e.g. an unparsable EXIF aperture) would collapse every
    # bucket onto one edge, so re-read the bounds over the finite values only.
    row = conn.execute(
        f"SELECT MIN({column}), MAX({column}) FROM photos "
        f"WHERE {column} > ? AND {column} < ?",
        (float('-inf'), float('inf')),
    ).fetchone()
    return (float(row[0]), float(row[1])) if row[0] is not None else None


def _metric_buckets(conn, column, v_min, v_max):
    """Value histogram for one metric column, bucketed by SQL over its index.

    Counting in SQL keeps the scan on the covering index; materializing the
    values in Python instead pulls whole ``photos`` rows, thumbnail BLOB
    included. Bucket edges are approximate by design — the sparkline is a UI
    hint, while the bounds above stay exact. Values outside ``[v_min, v_max]``
    (a stored infinity) clamp onto the end buckets instead of being dropped.
    """
    if v_max <= v_min:
        total = conn.execute(
            f"SELECT COUNT(*) FROM photos WHERE {column} IS NOT NULL"
        ).fetchone()[0]
        return [int(total)]
    rows = conn.execute(
        f"""
        SELECT MAX(0, MIN(?, CAST(({column} - ?) * ? / ? AS INTEGER))) AS bucket,
               COUNT(*)
        FROM photos WHERE {column} IS NOT NULL
        GROUP BY bucket
        """,
        (_METRIC_RANGE_BINS - 1, v_min, _METRIC_RANGE_BINS, v_max - v_min),
    ).fetchall()
    buckets = [0] * _METRIC_RANGE_BINS
    for bucket, count in rows:
        buckets[int(bucket)] = int(count)
    return buckets


def compute_metric_ranges(conn):
    """Observed min/max and a value histogram per numeric metric column.

    Powers data-driven slider bounds (clamping) and the distribution sparkline
    in the gallery filter sidebar. Values are global (not visibility-filtered)
    since they are only a UI hint. Every statement is scoped to a single column
    so it rides that column's covering index and never touches row data; also
    called offline by ``database.py --refresh-stats``.
    """
    from api.routers.gallery import SCORE_RANGE_COLUMNS, EXIF_RANGE_COLUMNS

    result = {}
    # Column names come from the hardcoded registry — safe to interpolate.
    for column, min_key, _max_key, _is_float in SCORE_RANGE_COLUMNS + EXIF_RANGE_COLUMNS:
        bounds = _metric_bounds(conn, column)
        if bounds is None:
            continue
        v_min, v_max = bounds
        result[min_key] = {
            'min': v_min,
            'max': v_max,
            'buckets': _metric_buckets(conn, column, v_min, v_max),
        }
    return result


def _compute_metric_ranges():
    """Serve the metric ranges from ``stats_cache``, recomputing when stale.

    The persisted row backs the in-process cache so a restart does not re-walk
    every metric index; ``database.py --refresh-stats`` writes the same row
    offline.
    """
    with get_db() as conn:
        cached = conn.execute(
            "SELECT value, updated_at FROM stats_cache WHERE key = ?",
            (_METRIC_RANGES_KEY,),
        ).fetchone()
        if cached and (time.time() - cached[1]) < _METRIC_RANGES_TTL_SECONDS:
            try:
                return json.loads(cached[0])
            except (json.JSONDecodeError, TypeError):
                pass
        ranges = compute_metric_ranges(conn)
        # An unscanned library has nothing worth persisting, and pinning the
        # empty result would keep the sidebar blank for a whole TTL after the
        # first scan lands.
        if ranges:
            conn.execute(
                "INSERT OR REPLACE INTO stats_cache (key, value, updated_at) VALUES (?, ?, ?)",
                (_METRIC_RANGES_KEY, json.dumps(ranges), time.time()),
            )
            conn.commit()
        return ranges


@router.get("/metric_ranges")
def metric_ranges(user: CurrentUser = Depends(require_authenticated)):
    """Per-metric observed range and distribution for slider clamping + histograms."""
    from api.config import _get_stats_cached
    return {'ranges': _get_stats_cached(_METRIC_RANGES_KEY, _compute_metric_ranges)}
