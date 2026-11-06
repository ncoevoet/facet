"""
Filter options router — lazy-loaded dropdown options.

"""

import asyncio
import json
import logging
import math
import sqlite3
import threading
import time
from typing import Optional
from fastapi import APIRouter, Depends

from api.auth import CurrentUser, get_optional_user, require_authenticated
from api.config import VIEWER_CONFIG, is_multi_user_enabled
from api.database import get_async_db, get_db
from api.db_helpers import is_manual_tags_available, is_photo_tags_available, get_visibility_clause
from api.types import JUNK_NOT_JUNK
from api.models.media import (
    MediaFilterOptionCamerasResponse,
    MediaFilterOptionJunkKindsResponse,
    MediaFilterOptionLensesResponse,
    MediaFilterOptionPersonsResponse,
    MediaFilterOptionTagsResponse,
    MediaLocationNameResponse,
)
from db import person_not_hidden_clause
from db.stats_cache import METRIC_RANGES_KEY, cache_stat_if_unchanged, cache_stats_best_effort

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


async def _cached_filter_query(cache_key, result_key, query_fn, vis):
    """Generic cache-then-async-query helper for filter option endpoints.

    ``query_fn`` is an ``async def fn(conn)`` coroutine that returns the
    list of rows for the dropdown.

    ``vis`` is the fragment ``_vis_where`` resolved for this caller. The cached
    payload is whole-library — ``database.py --refresh-stats`` builds it with no
    user in scope — so it may only answer a caller under no restriction at all.
    A non-empty fragment means this request must not see everything, and the
    cache is skipped so the clause inside ``query_fn`` actually runs. Resolving
    the clause is not the same as applying it: returning here first is how the
    whole-library answer reached a caller the clause was meant to stop.
    """
    from db import get_cached_stat, DEFAULT_DB_PATH
    if not vis and not is_multi_user_enabled():
        data, is_fresh = await asyncio.to_thread(
            get_cached_stat, DEFAULT_DB_PATH, cache_key, max_age_seconds=300)
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


@router.get("/cameras", response_model=MediaFilterOptionCamerasResponse, response_model_exclude_unset=True)
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

    return await _cached_filter_query('cameras', 'cameras', query, vis)


@router.get("/lenses", response_model=MediaFilterOptionLensesResponse, response_model_exclude_unset=True)
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

    return await _cached_filter_query('lenses', 'lenses', query, vis)


def _tag_tables_ready():
    """(photo_tags has rows, photo_manual_tags exists), on one sync connection."""
    with get_db() as sync_conn:
        return is_photo_tags_available(sync_conn), is_manual_tags_available(sync_conn)


@router.get("/tags", response_model=MediaFilterOptionTagsResponse, response_model_exclude_unset=True)
async def tags(user: Optional[CurrentUser] = Depends(get_optional_user)):
    """Lazy-load tag options with counts.

    Owns a private cache branch instead of ``_cached_filter_query`` because the
    payload is trimmed to ``max_tags`` on the way out, but it is gated on the
    same rule: the cached list is whole-library, so a caller with a non-empty
    ``vis`` fragment must miss it and run the clause.
    """
    from db import get_cached_stat, DEFAULT_DB_PATH

    max_tags = VIEWER_CONFIG['dropdowns']['max_tags']
    vis, vp = _vis_where(user)

    if not vis and not is_multi_user_enabled():
        data, is_fresh = await asyncio.to_thread(
            get_cached_stat, DEFAULT_DB_PATH, 'tags', max_age_seconds=300)
        if data and is_fresh:
            return {'tags': data[:max_tags], 'cached': True}

    async with get_async_db() as conn:
        # Both probes are cached, but a cache miss opens a sync connection and
        # queries it: run them on a worker thread so a miss never stalls the event
        # loop (and with it every other request in flight).
        photo_tags_ready, manual_ready = await asyncio.to_thread(_tag_tables_ready)

        if photo_tags_ready:
            try:
                if vis:
                    # The visibility filter needs the (photo, tag) pair rows, so this
                    # branch keeps the pair-level UNION. UNION (not UNION ALL) de-dupes
                    # (photo, tag): a manual tag equal to an AI tag counts that photo once.
                    vis_sub = f' AND photo_path IN (SELECT path FROM photos WHERE 1=1{vis})'
                    tag_pairs = "SELECT photo_path, tag FROM photo_tags"
                    if manual_ready:
                        tag_pairs += " UNION SELECT photo_path, tag FROM photo_manual_tags"
                    rows = await _fetch_all(
                        conn,
                        f"""
                        SELECT tag, COUNT(*) as cnt
                        FROM ({tag_pairs})
                        WHERE 1=1{vis_sub}
                        GROUP BY tag
                        ORDER BY cnt DESC, tag ASC
                        LIMIT ?
                        """,
                        vp + [max_tags],
                    )
                else:
                    # Whole library: count the AI pairs with an index-only GROUP BY on
                    # idx_photo_tags_tag, then add the manual pairs the AI side does not
                    # already hold (the anti-join is the same (photo, tag) de-dupe the
                    # UNION did, without building a temp b-tree over every pair).
                    manual_half = (
                        " UNION ALL SELECT m.tag, COUNT(*) FROM photo_manual_tags m"
                        " WHERE NOT EXISTS (SELECT 1 FROM photo_tags t"
                        " WHERE t.photo_path = m.photo_path AND t.tag = m.tag)"
                        " GROUP BY m.tag"
                        if manual_ready else ""
                    )
                    rows = await _fetch_all(
                        conn,
                        f"""
                        SELECT tag, SUM(n) AS cnt
                        FROM (SELECT tag, COUNT(*) AS n FROM photo_tags GROUP BY tag{manual_half})
                        GROUP BY tag
                        ORDER BY cnt DESC, tag ASC
                        LIMIT ?
                        """,
                        [max_tags],
                    )
                return {'tags': [(r[0], r[1]) for r in rows], 'cached': False}
            except sqlite3.Error:
                logger.debug("photo_tags query failed, falling back to split", exc_info=True)

        manual_seed = (
            f" UNION SELECT '', path, tag || ',' FROM photos JOIN photo_manual_tags m"
            f" ON m.photo_path = photos.path WHERE 1=1{vis}"
            if manual_ready else ""
        )
        tag_query = f"""
            WITH RECURSIVE split_tags(tag, path, rest) AS (
                SELECT '', path, tags || ',' FROM photos WHERE tags IS NOT NULL AND tags != ''{vis}
                {manual_seed}
                UNION ALL
                SELECT TRIM(SUBSTR(rest, 1, INSTR(rest, ',') - 1)), path,
                       SUBSTR(rest, INSTR(rest, ',') + 1)
                FROM split_tags WHERE rest != ''
            )
            SELECT tag, COUNT(DISTINCT path) as cnt
            FROM split_tags
            WHERE tag != ''
            GROUP BY tag
            ORDER BY cnt DESC, tag ASC
            LIMIT ?
        """
        try:
            rows = await _fetch_all(conn, tag_query, vp + (vp if manual_ready else []) + [max_tags])
            return {'tags': [(r[0], r[1]) for r in rows], 'cached': False}
        except sqlite3.Error:
            logger.exception("Failed to query tags")
            return {'tags': [], 'cached': False}


@router.get("/persons", response_model=MediaFilterOptionPersonsResponse, response_model_exclude_unset=True)
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
    return await _cached_filter_query('persons', 'persons', query, vis)


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

    return await _cached_filter_query('composition_patterns', 'patterns', query, vis)


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

    return await _cached_filter_query('apertures', 'apertures', query, vis)


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

    return await _cached_filter_query('focal_lengths', 'focal_lengths', query, vis)


def _store_color_cache_sync(temps, hue_buckets):
    with get_db() as conn:
        cache_stats_best_effort(conn, [
            ('color_temps', json.dumps(temps)),
            ('color_hue_buckets', json.dumps(hue_buckets)),
        ])


async def _store_color_cache(temps, hue_buckets):
    """Persist the colour facets into ``stats_cache`` (best-effort).

    Lets repeated dropdown opens skip the full ``dominant_hue`` scan. Failures
    (e.g. a missing table before init) are swallowed so a cache miss never
    breaks the actual response, and the write is skipped while the gallery index
    build or another writer holds the lock (``cache_stats_best_effort``). It runs
    on its own short-lived connection in a worker thread, so its lock wait never
    blocks the event loop.
    """
    try:
        await asyncio.to_thread(_store_color_cache_sync, temps, hue_buckets)
    except sqlite3.Error:
        logger.debug("Failed to cache color facets", exc_info=True)


@router.get("/colors")
async def colors(user: Optional[CurrentUser] = Depends(get_optional_user)):
    """Lazy-load colour facets: warm/cool/neutral temps and hue buckets with counts.

    Returns ``{'temps': [(temp, count)], 'hue_buckets': [(bucket, count)]}``.
    Both lists are empty until ``--recompute-colors`` has populated the
    ``color_temp`` / ``dominant_hue`` columns.

    Cached in ``stats_cache`` (300s TTL) like the sibling dropdowns so the full
    column scan runs at most once per window. ``use_cache`` gates the read AND
    the write, so a restricted caller neither reads the whole-library facets nor
    persists its own ``AND 0=1`` result over them — writing back would blank the
    real user's colour filter for a whole TTL.
    """
    from api.routers.gallery import HUE_BUCKETS, bucket_for_hue
    from db import get_cached_stat, DEFAULT_DB_PATH
    vis, vp = _vis_where(user)
    use_cache = not vis and not is_multi_user_enabled()

    if use_cache:
        def read_cached():
            return (get_cached_stat(DEFAULT_DB_PATH, 'color_temps', max_age_seconds=300),
                    get_cached_stat(DEFAULT_DB_PATH, 'color_hue_buckets', max_age_seconds=300))

        (temps_cached, temps_fresh), (hues_cached, hues_fresh) = await asyncio.to_thread(read_cached)
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
                await _store_color_cache(temps, hue_buckets)
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

    return await _cached_filter_query('categories', 'categories', query, vis)


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

    return await _cached_filter_query('narrative_moments', 'narrative_moments', query, vis)


@router.get("/junk_kinds", response_model=MediaFilterOptionJunkKindsResponse, response_model_exclude_unset=True)
async def junk_kinds(user: Optional[CurrentUser] = Depends(get_optional_user)):
    """Count remaining Junk Sweep candidates using this reader's review state."""
    from api.logical_collection import enabled_async
    from api.routers.gallery import gallery_scope_sql_async

    user_id = user.user_id if user else None
    # Match the queue's explicit filters; the shared builder also preserves
    # configured sequence hiding and logical-primary/review authority.
    filters = {
        'type': '', 'hide_rejected': '1',
        'hide_blinks': '0', 'hide_bursts': '0', 'hide_duplicates': '0',
        'collapse_stacks': '0',
    }

    async def query(conn):
        try:
            # `not_junk` sits on nearly every evaluated photo, so a `!= not_junk`
            # range would row-fetch the whole library to read the review state.
            # List the real kinds from the index alone, then count each by
            # equality so only genuine candidates are ever looked up.
            kinds = await _fetch_all(
                conn,
                "SELECT DISTINCT junk_kind FROM photos WHERE junk_kind IS NOT NULL AND junk_kind != ?",
                [JUNK_NOT_JUNK],
            )
            counts = []
            for (kind,) in kinds:
                from_clause, where, params = await gallery_scope_sql_async(
                    conn, {**filters, 'junk_kind': kind}, user_id, logical=await enabled_async(conn))
                rows = await _fetch_all(
                    conn, f"SELECT COUNT(*) FROM {from_clause} {where}", params)
                if rows[0][0]:
                    counts.append((kind, rows[0][0]))
            return sorted(counts, key=lambda item: item[1], reverse=True)
        except sqlite3.Error:
            logger.exception("Failed to query junk_kinds")
            return []

    # The offline junk_kinds cache includes rejected rows and has no reader's
    # preference scope. Decisions must be reflected on the next menu read.
    async with get_async_db() as conn:
        await conn.execute('BEGIN')
        data = await query(conn)
    return {'junk_kinds': data, 'cached': False}


@router.get("/location_name", response_model=MediaLocationNameResponse, response_model_exclude_unset=True)
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
# Freshness of the persisted result (its key is db.stats_cache.METRIC_RANGES_KEY),
# the same as the scenes cache (api/routers/scenes.py). The row is the only cache:
# nothing is kept in process memory, so a writer that invalidates it is seen on
# the next request.
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
            # The photo field this range describes, so a client can place one photo's value in it.
            'column': column,
            'min': v_min,
            'max': v_max,
            'buckets': _metric_buckets(conn, column, v_min, v_max),
        }
    return result


class _MetricRangesFlight:
    """One in-flight metric-ranges read, shared by the requests that arrive during it."""

    __slots__ = ('done', 'ranges', 'failed', 'lost')

    def __init__(self):
        self.done = threading.Event()
        self.ranges = None
        self.failed = False
        self.lost = False


_metric_ranges_flight_lock = threading.Lock()
_metric_ranges_flight = None


def _load_or_compute_metric_ranges():
    """Serve the persisted ranges, or compute and persist them: ``(ranges, lost)``.

    The cache row, the bounds and the buckets are read in ONE snapshot, so a
    result never mixes values from before and after a concurrent score update.
    That read transaction is ended before the write, which is a compare-and-set
    against the row as read (``cache_stat_if_unchanged``): a writer that
    invalidated the ranges meanwhile wins, while a commit to anything else -- a
    rating save, a scan batch -- does not stop the result from landing. ``lost``
    is True when the write did not land -- the row had changed, or the write was
    skipped as busy -- i.e. the result may predate an invalidation.
    """
    with get_db() as conn:
        conn.execute("BEGIN")
        try:
            row = conn.execute(
                "SELECT value, updated_at FROM stats_cache WHERE key = ?",
                (METRIC_RANGES_KEY,),
            ).fetchone()
            # A NULL value is an eviction tombstone (invalidate_metric_ranges): a miss.
            if (row is not None and row[0] is not None
                    and (time.time() - row[1]) < _METRIC_RANGES_TTL_SECONDS):
                try:
                    cached = json.loads(row[0])
                except (json.JSONDecodeError, TypeError):
                    cached = None
                # A row cached before each range named its column cannot place a photo: a miss.
                if isinstance(cached, dict) and all('column' in r for r in cached.values()):
                    return cached, False
            ranges = compute_metric_ranges(conn)
        finally:
            conn.rollback()
        # An unscanned library has nothing worth persisting, and pinning the
        # empty result would keep the sidebar blank for a whole TTL after the
        # first scan lands.
        if not ranges:
            return ranges, False
        seen = None if row is None else (row[0], row[1])
        landed = cache_stat_if_unchanged(conn, METRIC_RANGES_KEY, json.dumps(ranges), seen)
        return ranges, landed is not True


def _compute_metric_ranges():
    """Metric ranges from ``stats_cache``, computed at most once at a time per process.

    Requests arriving while another one computes wait for it and take its
    result instead of walking every metric index again -- unless that result
    lost its write (compare-and-set failed or was skipped as busy), or the
    leader failed: it may then predate an invalidation, so they go round again,
    leading or joining a newer flight, and surface their own exception rather
    than a shared one. After two rounds they compute un-coalesced. Nothing
    outlives the in-flight computation.
    """
    global _metric_ranges_flight
    for _ in range(2):
        with _metric_ranges_flight_lock:
            flight = _metric_ranges_flight
            lead = flight is None
            if lead:
                flight = _metric_ranges_flight = _MetricRangesFlight()
        if lead:
            flight.failed = True
            try:
                flight.ranges, flight.lost = _load_or_compute_metric_ranges()
                flight.failed = False
            finally:
                with _metric_ranges_flight_lock:
                    _metric_ranges_flight = None
                flight.done.set()
            return flight.ranges
        flight.done.wait()
        if not flight.failed and not flight.lost:
            return flight.ranges
    return _load_or_compute_metric_ranges()[0]


@router.get("/metric_ranges")
def metric_ranges(user: CurrentUser = Depends(require_authenticated)):
    """Per-metric observed range and distribution for slider clamping + histograms."""
    from api.config import _sanitize_stats
    # No process-local TTL here: score publishers invalidate the persisted row,
    # and a cached copy in memory would hide that until its own expiry.
    return {'ranges': _sanitize_stats(_compute_metric_ranges())}
