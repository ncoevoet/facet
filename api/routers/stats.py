"""
Stats router — gear, settings, timeline, correlations, category analysis.

"""

import asyncio
import logging
import math
import sqlite3
import sys
from collections import defaultdict
from typing import Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.auth import CurrentUser, get_optional_user, require_edition, require_authenticated
from api.config import (
    child_process_env,
    CORRELATION_X_AXES, CORRELATION_Y_METRICS, FACET_SCRIPT,
    _get_stats_cached, _get_stats_cached_async, _stats_cache,
    _CONFIG_PATH, reload_config, server_scoring_config,
)
from api.database import get_async_db, get_db
from api.db_helpers import (
    get_visibility_clause, library_lock_held_error, refuse_while_gallery_index_build_runs,
    to_exif_date, to_iso_date,
)
from api.config_writes import update_category_weights
from api.exposure import exposure_seconds_sql
from api.models.stats import (
    MetricDistributionResponse,
    StatsCategoryCorrelationsResponse, StatsCategoryOverlapResponse,
    StatsCategoryRecomputeResponse, StatsCategoryStat,
    StatsCorrelationsGroupedResponse, StatsCorrelationsUngroupedResponse,
    StatsGearResponse, StatsOverviewResponse, StatsScoreDistributionBin,
    StatsTopCamera,
)

router = APIRouter(tags=["stats"])
logger = logging.getLogger(__name__)


# Pre-built SQL fragments keyed by metric name (server-origin constants, not user strings)
_METRIC_SQL: dict[str, str] = {m: f'ROUND(AVG({m}), 3)' for m in CORRELATION_Y_METRICS}


# --- Pydantic request bodies ---

class CategoryUpdateRequest(BaseModel):
    category: str
    weights: Optional[dict] = None
    modifiers: Optional[dict] = None


class CategoryRecomputeRequest(BaseModel):
    category: str


# --- Weight dimensions: config key -> DB column ---

_WEIGHT_COLUMNS = {
    'aesthetic': 'aesthetic',
    'composition': 'comp_score',
    'face_quality': 'face_quality',
    'eye_sharpness': 'eye_sharpness',
    'tech_sharpness': 'tech_sharpness',
    'exposure': 'exposure_score',
    'color': 'color_score',
    'quality': 'quality_score',
    'contrast': 'contrast_score',
    'dynamic_range': 'dynamic_range_stops',
    'isolation': 'isolation_bonus',
    'leading_lines': 'leading_lines_score',
    # Supplementary PyIQA
    'aesthetic_iaa': 'aesthetic_iaa',
    'face_quality_iqa': 'face_quality_iqa',
    'liqe': 'liqe_score',
    # Subject saliency
    'subject_sharpness': 'subject_sharpness',
    'subject_prominence': 'subject_prominence',
    'subject_placement': 'subject_placement',
    'bg_separation': 'bg_separation',
}


# --- Visibility helper ---

def _vis_where(user: Optional[CurrentUser]):
    """Return (where_clause_with_AND_prefix, params) for visibility filtering.

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


def _stats_filter_where(user: Optional[CurrentUser],
                        date_from: Optional[str] = None,
                        date_to: Optional[str] = None,
                        category: Optional[str] = None):
    """Build combined WHERE clause for stats endpoints with date range and category filters.

    Returns (AND_clause, params) just like _vis_where but including date/category filters.
    """
    vis, vp = _vis_where(user)
    clause = vis
    params = list(vp)
    if date_from:
        clause += ' AND date_taken >= ?'
        params.append(to_exif_date(date_from))
    if date_to:
        clause += ' AND date_taken <= ?'
        params.append(to_exif_date(date_to) + ' 23:59:59')
    if category:
        clause += ' AND category = ?'
        params.append(category)
    return clause, params


# --- Endpoints ---

@router.get('/api/stats/overview', response_model=StatsOverviewResponse,
            response_model_exclude_unset=True)
async def api_stats_overview(
    user: Optional[CurrentUser] = Depends(get_optional_user),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
):
    """Aggregate overview stats for the Angular stats page."""
    vis, vp = _stats_filter_where(user, date_from, date_to, category)

    async def compute():
        async with get_async_db() as conn:
            cur = await conn.execute(f'''SELECT COUNT(*) as total,
                           ROUND(AVG(aggregate), 2) as avg_agg,
                           ROUND(AVG(aesthetic), 2) as avg_aes,
                           ROUND(AVG(comp_score), 2) as avg_comp,
                           MIN(date_taken) as date_start,
                           MAX(date_taken) as date_end
                           FROM photos WHERE 1=1{vis}''', vp)
            row = await cur.fetchone()
            await cur.close()

            # Total faces
            try:
                cur = await conn.execute(f'''SELECT COUNT(*) FROM faces
                    WHERE photo_path IN (SELECT path FROM photos WHERE 1=1{vis})''', vp)
                faces_row = await cur.fetchone()
                await cur.close()
                total_faces = faces_row[0] if faces_row else 0
            except sqlite3.OperationalError:
                total_faces = 0

            # Total persons
            try:
                cur = await conn.execute('SELECT COUNT(*) FROM persons')
                persons_row = await cur.fetchone()
                await cur.close()
                total_persons = persons_row[0] if persons_row else 0
            except sqlite3.OperationalError:
                total_persons = 0

            # Total distinct tags
            try:
                from api.db_helpers import is_manual_tags_available, is_photo_tags_available
                # Distinct union of AI and manual tags: a manual tag equal to an AI
                # tag is one tag, and a manual-only library still counts its tags.
                # Cached probes whose miss queries a sync connection: off the event loop.
                photo_tags_ready, manual_ready = await asyncio.to_thread(
                    lambda: (is_photo_tags_available(), is_manual_tags_available()))
                tag_sources = []
                if photo_tags_ready:
                    tag_sources.append('SELECT tag FROM photo_tags')
                if manual_ready:
                    tag_sources.append('SELECT tag FROM photo_manual_tags')
                if tag_sources:
                    cur = await conn.execute(
                        f"SELECT COUNT(DISTINCT tag) FROM ({' UNION ALL '.join(tag_sources)})"
                    )
                    tags_row = await cur.fetchone()
                    await cur.close()
                else:
                    tags_row = (0,)
                total_tags = tags_row[0] if tags_row else 0
            except sqlite3.OperationalError:
                total_tags = 0

        # Format dates
        date_start = ''
        date_end = ''
        if row[4]:
            date_start = to_iso_date(row[4])
        if row[5]:
            date_end = to_iso_date(row[5])

        return {
            'total_photos': row[0] or 0,
            'total_persons': total_persons,
            'avg_score': row[1] or 0,
            'avg_aesthetic': row[2] or 0,
            'avg_composition': row[3] or 0,
            'total_faces': total_faces,
            'total_tags': total_tags,
            'date_range_start': date_start,
            'date_range_end': date_end,
        }

    user_id = user.user_id if user else None
    cache_key = f'overview:{user_id or ""}:{date_from or ""}:{date_to or ""}:{category or ""}'
    return await _get_stats_cached_async(cache_key, compute)


@router.get('/api/stats/score_distribution', response_model=list[StatsScoreDistributionBin],
            response_model_exclude_unset=True)
async def api_stats_score_distribution(
    user: Optional[CurrentUser] = Depends(get_optional_user),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
):
    """Score distribution histogram for the Angular stats page."""
    vis, vp = _stats_filter_where(user, date_from, date_to, category)

    async def compute():
        async with get_async_db() as conn:
            # 0.5-point buckets
            cur = await conn.execute(f'''SELECT ROUND(aggregate * 2) / 2.0 AS bucket, COUNT(*) as cnt
                           FROM photos WHERE aggregate IS NOT NULL{vis}
                           GROUP BY bucket ORDER BY bucket''', vp)
            rows = await cur.fetchall()
            await cur.close()
            total = sum(r[1] for r in rows) or 1

        bins = []
        for r in rows:
            bucket = r[0]
            count = r[1]
            bins.append({
                'range': str(bucket),
                'min': bucket,
                'max': bucket + 0.5,
                'count': count,
                'percentage': count / total,
            })
        return bins

    user_id = user.user_id if user else None
    cache_key = f'score_dist:{user_id or ""}:{date_from or ""}:{date_to or ""}:{category or ""}'
    return await _get_stats_cached_async(cache_key, compute)


@router.get('/api/stats/top_cameras', response_model=list[StatsTopCamera],
            response_model_exclude_unset=True)
async def api_stats_top_cameras(
    user: Optional[CurrentUser] = Depends(get_optional_user),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
):
    """Top cameras ranked by average aggregate score."""
    vis, vp = _stats_filter_where(user, date_from, date_to, category)

    async def compute():
        async with get_async_db() as conn:
            cur = await conn.execute(f'''SELECT camera_model, COUNT(*) as cnt,
                           ROUND(AVG(aggregate), 2) as avg_agg,
                           ROUND(AVG(aesthetic), 2) as avg_aes
                           FROM photos WHERE camera_model IS NOT NULL AND camera_model != ''{vis}
                           GROUP BY camera_model HAVING cnt >= 10
                           ORDER BY avg_agg DESC LIMIT 20''', vp)
            rows = await cur.fetchall()
            await cur.close()
            cameras = [{'name': r[0], 'count': r[1], 'avg_score': r[2], 'avg_aesthetic': r[3]} for r in rows]
        return cameras

    user_id = user.user_id if user else None
    cache_key = f'top_cameras:{user_id or ""}:{date_from or ""}:{date_to or ""}:{category or ""}'
    return await _get_stats_cached_async(cache_key, compute)


# Mean f-stop over the finite values only. Older EXIF writers stored +Inf in
# ``f_stop``; ``AVG`` over such a row is +Inf, ``_sanitize_stats`` turns that into
# None, and ``avg_f_stop: Union[int, float]`` rejects None -- a 500 raised after the
# (minutes-long) compute. A group without a non-finite row averages exactly as
# ``AVG(f_stop)`` does; an all-non-finite group yields NULL, which the callers'
# ``or 0`` turns into 0. Reads only ``f_stop``, so it stays inside
# ``idx_stats_categories``.
_FINITE_AVG_F_STOP = 'ROUND(AVG(CASE WHEN f_stop BETWEEN -1e308 AND 1e308 THEN f_stop END), 1)'

# The categories averages statement, with a ``{vis}`` placeholder for the
# ``_stats_filter_where`` clause. A module constant so the plan test reads the real text.
CATEGORY_AVERAGES_SQL = f'''
                SELECT category, COUNT(*) as cnt,
                       ROUND(AVG(aggregate), 2),
                       ROUND(AVG(aesthetic), 2),
                       ROUND(AVG(comp_score), 2),
                       ROUND(AVG(tech_sharpness), 2),
                       ROUND(AVG(color_score), 2),
                       ROUND(AVG(exposure_score), 2),
                       ROUND(AVG(ISO), 0),
                       {_FINITE_AVG_F_STOP},
                       ROUND(AVG(COALESCE(focal_length_35mm, focal_length)), 0),
                       ROUND(AVG(face_quality), 2),
                       ROUND(AVG(contrast_score), 2)
                FROM photos WHERE 1=1{{vis}}
                GROUP BY category ORDER BY cnt DESC
            '''


@router.get('/api/stats/categories', response_model=list[StatsCategoryStat],
            response_model_exclude_unset=True)
async def api_stats_categories(
    user: Optional[CurrentUser] = Depends(get_optional_user),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
):
    """Category stats in the format the Angular component expects (CategoryStat[])."""
    vis, vp = _stats_filter_where(user, date_from, date_to, category)

    async def compute():
        async with get_async_db() as conn:
            cur = await conn.execute(CATEGORY_AVERAGES_SQL.format(vis=vis), vp)
            rows = await cur.fetchall()
            await cur.close()
            total = sum(r[1] for r in rows) or 1

            # Top camera per category
            cur = await conn.execute(f'''
                SELECT category, camera_model FROM (
                    SELECT category, camera_model, COUNT(*) as cnt,
                           ROW_NUMBER() OVER (PARTITION BY category
                                              ORDER BY COUNT(*) DESC, camera_model) as rn
                    FROM photos
                    WHERE camera_model IS NOT NULL AND camera_model != ''{vis}
                    GROUP BY category, camera_model
                ) WHERE rn = 1
            ''', vp)
            top_cameras = {r[0]: r[1] for r in await cur.fetchall()}
            await cur.close()

            # Top lens per category
            cur = await conn.execute(f'''
                SELECT category, lens_model FROM (
                    SELECT category, lens_model, COUNT(*) as cnt,
                           ROW_NUMBER() OVER (PARTITION BY category
                                              ORDER BY COUNT(*) DESC, lens_model) as rn
                    FROM photos
                    WHERE lens_model IS NOT NULL AND lens_model != ''{vis}
                    GROUP BY category, lens_model
                ) WHERE rn = 1
            ''', vp)
            top_lenses = {r[0]: r[1] for r in await cur.fetchall()}
            await cur.close()

        return [
            {
                'category': r[0] or '(uncategorized)',
                'count': r[1],
                'percentage': r[1] / total,
                'avg_score': r[2] or 0,
                'avg_aesthetic': r[3] or 0,
                'avg_composition': r[4] or 0,
                'avg_sharpness': r[5] or 0,
                'avg_color': r[6] or 0,
                'avg_exposure': r[7] or 0,
                'avg_iso': r[8] or 0,
                'avg_f_stop': r[9] or 0,
                'avg_focal_length': r[10] or 0,
                'avg_face_quality': r[11] or 0,
                'avg_contrast': r[12] or 0,
                'top_camera': top_cameras.get(r[0]),
                'top_lens': top_lenses.get(r[0]),
            }
            for r in rows
        ]

    user_id = user.user_id if user else None
    cache_key = f'categories_stats:{user_id or ""}:{date_from or ""}:{date_to or ""}:{category or ""}'
    return await _get_stats_cached_async(cache_key, compute)


# The twelve averages every gear breakdown reports, aliased so the rows are read
# by key. They were read as r[2]..r[13] off three separate copies of this SELECT,
# where inserting a column silently shifted every field after it onto the wrong
# key -- a wrong number the UI cannot distinguish from a real one.
_GEAR_AGGREGATES = f"""COUNT(*) AS cnt,
                   ROUND(AVG(aggregate),2) AS avg_aggregate,
                   ROUND(AVG(aesthetic),2) AS avg_aesthetic,
                   ROUND(AVG(tech_sharpness),2) AS avg_sharpness,
                   ROUND(AVG(comp_score),2) AS avg_composition,
                   ROUND(AVG(exposure_score),2) AS avg_exposure,
                   ROUND(AVG(color_score),2) AS avg_color,
                   ROUND(AVG(ISO),0) AS avg_iso,
                   {_FINITE_AVG_F_STOP} AS avg_f_stop,
                   ROUND(AVG(COALESCE(focal_length_35mm, focal_length)),0) AS avg_focal_length,
                   ROUND(AVG(face_count),2) AS avg_face_count,
                   ROUND(AVG(is_monochrome),3) AS avg_monochrome,
                   ROUND(AVG(dynamic_range_stops),2) AS avg_dynamic_range"""

# The score averages serve NULL through as JSON null; the shooting-parameter
# averages fall back to 0. The split is deliberate and predates this helper --
# a camera with no scored photo reports no score, while one with no recorded ISO
# reports 0 -- so both halves are listed rather than folded into one rule.
_GEAR_SCORE_FIELDS = ('avg_aggregate', 'avg_aesthetic', 'avg_sharpness',
                      'avg_composition', 'avg_exposure', 'avg_color')
_GEAR_ZERO_FILLED_FIELDS = ('avg_iso', 'avg_f_stop', 'avg_focal_length',
                            'avg_face_count', 'avg_monochrome', 'avg_dynamic_range')


async def _gear_rows(conn, name_expr, where_sql, params, group_by):
    """The top 20 gear items for one grouping, keyed as the client reads them.

    ``name_expr``/``group_by`` are server-origin SQL literals, and ``where_sql``
    carries ``_stats_filter_where``'s already-bound placeholders -- no user
    string is interpolated here.
    """
    cur = await conn.execute(
        f'SELECT {name_expr} AS name, {_GEAR_AGGREGATES} FROM photos '
        f'WHERE {where_sql} GROUP BY {group_by} ORDER BY cnt DESC LIMIT 20', params)
    rows = await cur.fetchall()
    await cur.close()
    return [{'name': r['name'], 'count': r['cnt'],
             **{f: r[f] for f in _GEAR_SCORE_FIELDS},
             **{f: r[f] or 0 for f in _GEAR_ZERO_FILLED_FIELDS},
             'history': []} for r in rows]


@router.get('/api/stats/gear', response_model=StatsGearResponse,
            response_model_exclude_unset=True)
async def api_stats_gear(
    user: Optional[CurrentUser] = Depends(get_optional_user),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
):
    vis, vp = _stats_filter_where(user, date_from, date_to, category)

    async def compute():
        async with get_async_db() as conn:
            cameras = await _gear_rows(
                conn, 'camera_model', f"camera_model IS NOT NULL AND camera_model != ''{vis}",
                vp, 'camera_model')
            lenses = await _gear_rows(
                conn, 'lens_model', f"lens_model IS NOT NULL AND lens_model != ''{vis}",
                vp, 'lens_model')
            combos = await _gear_rows(
                conn, "camera_model || ' + ' || lens_model",
                f"camera_model IS NOT NULL AND camera_model != '' "
                f"AND lens_model IS NOT NULL AND lens_model != ''{vis}",
                vp, 'camera_model, lens_model')

            # Category distribution
            cur = await conn.execute(f'''SELECT category, COUNT(*) as cnt
                           FROM photos WHERE category IS NOT NULL AND category != ''{vis}
                           GROUP BY category ORDER BY cnt DESC''', vp)
            categories = [{'name': r[0], 'count': r[1]} for r in await cur.fetchall()]
            await cur.close()

            # Timelines (monthly usage)
            cur = await conn.execute(f'''SELECT camera_model, lens_model, SUBSTR(date_taken,1,7) as month, COUNT(*) as cnt
                           FROM photos WHERE date_taken IS NOT NULL {vis}
                           GROUP BY camera_model, lens_model, month''', vp)
            tl_rows = await cur.fetchall()
            await cur.close()

            cam_tl, len_tl, com_tl = {}, {}, {}
            for cam, lens, month, count in tl_rows:
                if not month:
                    continue
                month = to_iso_date(month)
                # Cameras
                if cam:
                    if cam not in cam_tl:
                        cam_tl[cam] = []
                    cam_tl[cam].append((month, count))
                # Lenses
                if lens:
                    if lens not in len_tl:
                        len_tl[lens] = []
                    len_tl[lens].append((month, count))
                # Combos
                if cam and lens:
                    combo = f"{cam} + {lens}"
                    if combo not in com_tl:
                        com_tl[combo] = []
                    com_tl[combo].append((month, count))

            # Helper to consolidate histories (since the above is grouped by camera AND lens, we need to sum for individual cameras/lenses)
            from collections import defaultdict
            def consolidate_history(tl_dict, item_list):
                for item in item_list:
                    raw_data = tl_dict.get(item['name'], [])
                    month_sums = defaultdict(int)
                    for m, c in raw_data:
                        month_sums[m] += c
                    item['history'] = [{'date': m, 'count': c} for m, c in sorted(month_sums.items())]

            consolidate_history(cam_tl, cameras)
            consolidate_history(len_tl, lenses)
            consolidate_history(com_tl, combos)

        return {'cameras': cameras, 'lenses': lenses, 'combos': combos, 'categories': categories}

    user_id = user.user_id if user else None
    cache_key = f'gear:{user_id or ""}:{date_from or ""}:{date_to or ""}:{category or ""}'
    return await _get_stats_cached_async(cache_key, compute)


@router.get('/api/stats/settings')
async def api_stats_settings(
    user: Optional[CurrentUser] = Depends(get_optional_user),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
):
    vis, vp = _stats_filter_where(user, date_from, date_to, category)

    async def compute():
        async with get_async_db() as conn:
            # ISO distribution with buckets
            cur = await conn.execute(f'''SELECT
                CASE
                    WHEN ISO <= 100 THEN '100'
                    WHEN ISO <= 200 THEN '200'
                    WHEN ISO <= 400 THEN '400'
                    WHEN ISO <= 800 THEN '800'
                    WHEN ISO <= 1600 THEN '1600'
                    WHEN ISO <= 3200 THEN '3200'
                    WHEN ISO <= 6400 THEN '6400'
                    WHEN ISO <= 12800 THEN '12800'
                    ELSE '25600+'
                END as iso_bucket,
                COUNT(*) as cnt,
                MIN(ISO) as sort_key
                FROM photos WHERE ISO IS NOT NULL AND ISO > 0{vis}
                GROUP BY iso_bucket ORDER BY sort_key''', vp)
            iso = [{'label': r[0], 'count': r[1]} for r in await cur.fetchall()]
            await cur.close()

            # Aperture usage
            cur = await conn.execute(f'''SELECT ROUND(f_stop, 1) as ap, COUNT(*) as cnt
                           FROM photos WHERE f_stop IS NOT NULL AND f_stop > 0 AND f_stop < 1e308{vis}
                           GROUP BY ap ORDER BY ap''', vp)
            aperture = [{'value': r[0], 'count': r[1]} for r in await cur.fetchall()]
            await cur.close()

            # Focal length distribution (prefer 35mm equivalent)
            cur = await conn.execute(f'''SELECT
                CASE
                    WHEN COALESCE(focal_length_35mm, focal_length) < 20 THEN '<20mm'
                    WHEN COALESCE(focal_length_35mm, focal_length) < 35 THEN '20-34mm'
                    WHEN COALESCE(focal_length_35mm, focal_length) < 50 THEN '35-49mm'
                    WHEN COALESCE(focal_length_35mm, focal_length) < 85 THEN '50-84mm'
                    WHEN COALESCE(focal_length_35mm, focal_length) < 135 THEN '85-134mm'
                    WHEN COALESCE(focal_length_35mm, focal_length) < 200 THEN '135-199mm'
                    WHEN COALESCE(focal_length_35mm, focal_length) < 400 THEN '200-399mm'
                    ELSE '400mm+'
                END as focal_bucket,
                COUNT(*) as cnt,
                MIN(COALESCE(focal_length_35mm, focal_length)) as sort_key
                FROM photos WHERE COALESCE(focal_length_35mm, focal_length) IS NOT NULL AND COALESCE(focal_length_35mm, focal_length) > 0{vis}
                GROUP BY focal_bucket ORDER BY sort_key''', vp)
            focal = [{'label': r[0], 'count': r[1]} for r in await cur.fetchall()]
            await cur.close()

            # Shutter speed distribution with SQL binning
            cur = await conn.execute(f'''SELECT
                CASE
                    WHEN ss < 0.00025 THEN '1/8000-1/4000'
                    WHEN ss < 0.0005  THEN '1/4000-1/2000'
                    WHEN ss < 0.001   THEN '1/2000-1/1000'
                    WHEN ss < 0.002   THEN '1/1000-1/500'
                    WHEN ss < 0.004   THEN '1/500-1/250'
                    WHEN ss < 0.008   THEN '1/250-1/125'
                    WHEN ss < 0.0167  THEN '1/125-1/60'
                    WHEN ss < 0.0333  THEN '1/60-1/30'
                    WHEN ss < 0.25    THEN '1/30-1/4'
                    ELSE '1/4s+'
                END as shutter_bucket,
                COUNT(*) as cnt,
                MIN(ss) as sort_key
                FROM (
                    SELECT {exposure_seconds_sql()} as ss
                    FROM photos
                    WHERE shutter_speed IS NOT NULL AND shutter_speed != ''{vis}
                ) WHERE ss IS NOT NULL AND ss > 0
                GROUP BY shutter_bucket ORDER BY sort_key''', vp)
            shutter = [{'label': r[0], 'count': r[1]} for r in await cur.fetchall()]
            await cur.close()

            # Score distribution in 0.5-point buckets
            cur = await conn.execute(f'''SELECT ROUND(aggregate * 2) / 2.0 AS bucket, COUNT(*) as cnt
                           FROM photos WHERE aggregate IS NOT NULL{vis}
                           GROUP BY bucket ORDER BY bucket''', vp)
            score_dist = [{'label': str(r[0]), 'count': r[1]} for r in await cur.fetchall()]
            await cur.close()

        return {'iso': iso, 'aperture': aperture, 'focal_length': focal, 'shutter_speed': shutter, 'score_distribution': score_dist}

    user_id = user.user_id if user else None
    cache_key = f'settings:{user_id or ""}:{date_from or ""}:{date_to or ""}:{category or ""}'
    return await _get_stats_cached_async(cache_key, compute)


@router.get('/api/stats/timeline')
async def api_stats_timeline(
    user: Optional[CurrentUser] = Depends(get_optional_user),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
):
    vis, vp = _stats_filter_where(user, date_from, date_to, category)

    async def compute():
        async with get_async_db() as conn:
            # Monthly
            cur = await conn.execute(f'''SELECT SUBSTR(date_taken, 1, 7) as month, COUNT(*) as cnt, ROUND(AVG(aggregate), 2) as avg_agg
                           FROM photos WHERE date_taken IS NOT NULL AND date_taken != ''{vis}
                           GROUP BY month ORDER BY month''', vp)
            monthly = [{'month': to_iso_date(r[0]), 'count': r[1], 'avg_score': r[2] or 0} for r in await cur.fetchall()]
            await cur.close()

            # Yearly
            cur = await conn.execute(f'''SELECT SUBSTR(date_taken, 1, 4) as year, COUNT(*) as cnt
                           FROM photos WHERE date_taken IS NOT NULL AND date_taken != ''{vis}
                           GROUP BY year ORDER BY year''', vp)
            yearly = [{'year': r[0], 'count': r[1]} for r in await cur.fetchall()]
            await cur.close()

            # Heatmap (day of week x hour)
            cur = await conn.execute(f'''SELECT
                CAST(STRFTIME('%w', REPLACE(SUBSTR(date_taken,1,10),':','-')) AS INTEGER) as dow,
                CAST(SUBSTR(date_taken, 12, 2) AS INTEGER) as hour,
                COUNT(*) as cnt
                FROM photos WHERE date_taken IS NOT NULL AND LENGTH(date_taken) >= 13{vis}
                GROUP BY dow, hour''', vp)
            heatmap = [{'day': r[0], 'hour': r[1], 'count': r[2]} for r in await cur.fetchall()]
            await cur.close()

            # Top days
            cur = await conn.execute(f'''SELECT REPLACE(SUBSTR(date_taken, 1, 10), ':', '-') as day, COUNT(*) as cnt
                           FROM photos WHERE date_taken IS NOT NULL AND date_taken != ''{vis}
                           GROUP BY day ORDER BY cnt DESC LIMIT 10''', vp)
            top_days = [{'date': r[0], 'count': r[1]} for r in await cur.fetchall()]
            await cur.close()
        return {'monthly': monthly, 'yearly': yearly, 'heatmap': heatmap, 'top_days': top_days}

    user_id = user.user_id if user else None
    cache_key = f'timeline:{user_id or ""}:{date_from or ""}:{date_to or ""}:{category or ""}'
    return await _get_stats_cached_async(cache_key, compute)


@router.get('/api/stats/correlations',
            response_model=Union[StatsCorrelationsGroupedResponse, StatsCorrelationsUngroupedResponse],
            response_model_exclude_unset=True)
async def api_stats_correlations(
    x: str = Query('iso'),
    y: str = Query('aggregate'),
    group_by: str = Query(''),
    min_samples: int = Query(3, ge=1),
    date_from: str = Query(''),
    date_to: str = Query(''),
    category: str = Query(''),
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    # Validate parameters against whitelists
    if x not in CORRELATION_X_AXES:
        raise HTTPException(status_code=400, detail='invalid x axis')

    y_metrics = [m for m in y.split(',') if m in CORRELATION_Y_METRICS]
    if not y_metrics:
        raise HTTPException(status_code=400, detail='no valid metrics')

    if group_by and group_by not in CORRELATION_X_AXES:
        raise HTTPException(status_code=400, detail='invalid group_by')

    vis, vp = _vis_where(user)
    user_id = user.user_id if user else None
    cache_key = f"corr:{x}:{','.join(sorted(y_metrics))}:{group_by}:{min_samples}:{date_from}:{date_to}:{category}:{user_id or ''}"

    async def compute():
        async with get_async_db() as conn:
            x_def = CORRELATION_X_AXES[x]
            x_sql = x_def['sql']
            x_filter = x_def['filter']
            x_sort = x_def['sort']

            # Build date filter clause
            date_clauses = []
            date_params = []
            if date_from:
                date_clauses.append("date_taken >= ?")
                date_params.append(to_exif_date(date_from))
            if date_to:
                date_clauses.append("date_taken <= ?")
                date_params.append(to_exif_date(date_to) + " 23:59:59")
            if category:
                date_clauses.append("category = ?")
                date_params.append(category)
            date_filter = (' AND '.join(date_clauses)) if date_clauses else '1=1'

            # Build metric AVG expressions from pre-built constant dict (not from user strings)
            metric_cols = ', '.join(_METRIC_SQL[m] for m in y_metrics)

            # Visibility filter for correlation queries
            vis_filter = vis.removeprefix(' AND ') if vis else '1=1'

            if group_by:
                g_def = CORRELATION_X_AXES[group_by]
                g_sql = g_def['sql']
                g_filter = g_def['filter']
                top_n = g_def['top_n']

                # Find top N groups by count
                cur = await conn.execute(f"SELECT {g_sql}, COUNT(*) as cnt FROM photos WHERE {g_filter} AND {x_filter} AND {date_filter} AND {vis_filter} GROUP BY {g_sql} ORDER BY cnt DESC LIMIT ?", date_params + vp + [top_n])
                top_groups = [r[0] for r in await cur.fetchall()]
                await cur.close()
                if not top_groups:
                    return {'labels': [], 'groups': {}, 'metrics': y_metrics, 'x_axis': x, 'group_by': group_by}

                placeholders = ','.join('?' for _ in top_groups)
                sql = f"""SELECT {x_sql} AS x_bucket, {g_sql} AS group_val, {metric_cols}, COUNT(*) AS cnt
                          FROM photos
                          WHERE {x_filter} AND {g_filter} AND {date_filter} AND {vis_filter} AND {g_sql} IN ({placeholders})
                          GROUP BY x_bucket, group_val
                          HAVING cnt >= ?
                          ORDER BY {x_sort}"""
                cur = await conn.execute(sql, date_params + vp + top_groups + [min_samples])
                rows = await cur.fetchall()
                await cur.close()
            else:
                sql = f"""SELECT {x_sql} AS x_bucket, {metric_cols}, COUNT(*) AS cnt
                          FROM photos
                          WHERE {x_filter} AND {date_filter} AND {vis_filter}
                          GROUP BY x_bucket
                          HAVING cnt >= ?
                          ORDER BY {x_sort}"""
                cur = await conn.execute(sql, date_params + vp + [min_samples])
                rows = await cur.fetchall()
                await cur.close()

        # The aggregation below is pure CPU work over the already-loaded rows
        # (no further DB access). For large result sets it can build wide
        # group/metric matrices, so offload it from the event loop.
        def _aggregate():
            if group_by:
                # Build ordered labels from all x_buckets
                seen = {}
                labels = []
                for r in rows:
                    if r[0] not in seen:
                        seen[r[0]] = True
                        labels.append(str(r[0]))

                # Build groups dict: {group_name: {label: {metric: value, count: N}}}
                groups = {}
                for r in rows:
                    lbl = str(r[0])
                    grp = str(r[1])
                    if grp not in groups:
                        groups[grp] = {}
                    bucket = {}
                    for i, m in enumerate(y_metrics):
                        bucket[m] = r[2 + i]
                    bucket['count'] = r[2 + len(y_metrics)]
                    groups[grp][lbl] = bucket

                return {'labels': labels, 'groups': groups, 'metrics': y_metrics, 'x_axis': x, 'group_by': group_by}
            else:
                labels = [str(r[0]) for r in rows]
                metrics = {}
                for i, m in enumerate(y_metrics):
                    metrics[m] = [r[1 + i] for r in rows]
                counts = [r[1 + len(y_metrics)] for r in rows]

                return {'labels': labels, 'metrics': metrics, 'counts': counts, 'x_axis': x, 'group_by': ''}

        return await asyncio.to_thread(_aggregate)

    return await _get_stats_cached_async(cache_key, compute)


# --- Categories tab endpoints ---

@router.get('/api/stats/categories/breakdown')
async def api_stats_categories_breakdown(user: Optional[CurrentUser] = Depends(get_optional_user)):
    vis, vp = _vis_where(user)

    async def compute():
        async with get_async_db() as conn:
            # Per-category counts and averages
            cur = await conn.execute(f'''
                SELECT category, COUNT(*) as cnt,
                       ROUND(AVG(aggregate), 2) as avg_agg,
                       ROUND(AVG(aesthetic), 2) as avg_aes,
                       ROUND(AVG(comp_score), 2) as avg_comp,
                       ROUND(AVG(face_quality), 2) as avg_face,
                       ROUND(AVG(tech_sharpness), 2) as avg_sharp,
                       ROUND(AVG(exposure_score), 2) as avg_exp,
                       ROUND(AVG(color_score), 2) as avg_color
                FROM photos WHERE 1=1{vis}
                GROUP BY category ORDER BY cnt DESC
            ''', vp)
            cat_rows = await cur.fetchall()
            await cur.close()

            categories = []
            total = 0
            uncategorized = 0
            for r in cat_rows:
                cat = r[0] or ''
                cnt = r[1]
                total += cnt
                entry = {
                    'name': cat or '(uncategorized)',
                    'count': cnt,
                    'avg_aggregate': r[2],
                    'avg_aesthetic': r[3],
                    'avg_composition': r[4],
                    'avg_face_quality': r[5],
                    'avg_sharpness': r[6],
                    'avg_exposure': r[7],
                    'avg_color': r[8],
                }
                if not cat:
                    uncategorized = cnt
                categories.append(entry)

            # Score distribution per category (0.5-point buckets)
            cur = await conn.execute(f'''
                SELECT category, ROUND(aggregate * 2) / 2.0 AS bucket, COUNT(*) as cnt
                FROM photos WHERE aggregate IS NOT NULL{vis}
                GROUP BY category, bucket ORDER BY category, bucket
            ''', vp)
            dist_rows = await cur.fetchall()
            await cur.close()

            distributions = {}
            for r in dist_rows:
                cat = r[0] or '(uncategorized)'
                if cat not in distributions:
                    distributions[cat] = []
                distributions[cat].append({'bucket': r[1], 'count': r[2]})
        return {
            'categories': categories,
            'distributions': distributions,
            'total': total,
            'uncategorized': uncategorized,
        }

    user_id = user.user_id if user else None
    cache_key = f'cat_breakdown:{user_id or ""}'
    return await _get_stats_cached_async(cache_key, compute)


@router.get('/api/stats/categories/weights')
def api_stats_categories_weights(user: Optional[CurrentUser] = Depends(get_optional_user)):

    config = server_scoring_config()
    categories = []
    for cat in config.get_categories():
        categories.append({
            'name': cat['name'],
            'priority': cat.get('priority', 100),
            'weights': cat.get('weights', {}),
            'modifiers': cat.get('modifiers', {}),
            'filters': cat.get('filters', {}),
        })
    from api.auth import is_edition_authenticated
    return {
        'categories': categories,
        'edition_authenticated': is_edition_authenticated(user),
    }


# --- Category overlap: precompiled filters over streamed rows ---

# Column indices of the overlap scan (SELECT order above).
_OVERLAP_IDX = {'tags': 0, 'face_count': 1, 'face_ratio': 2, 'is_silhouette': 3,
                'is_group_portrait': 4, 'is_monochrome': 5, 'mean_luminance': 6,
                'iso': 7, 'shutter_speed': 8, 'focal_length': 9, 'f_stop': 10,
                'category': 11}
# Columns with_face_defaults coalesces NULL to 0 before filter evaluation.
_FACE_DEFAULT_IDX = (_OVERLAP_IDX['face_count'], _OVERLAP_IDX['face_ratio'],
                     _OVERLAP_IDX['is_group_portrait'])
# Numeric filter field -> scan column; the check set mirrors
# config.category_filter.CategoryFilter._check_numeric exactly.
_NUMERIC_FIELD_IDX = {'face_ratio': 2, 'face_count': 1, 'iso': 7,
                      'shutter_speed': 8, 'luminance': 6, 'focal_length': 9,
                      'f_stop': 10}


def _shutter_float(ss):
    """Parse the shutter_speed column the way the overlap evaluator always has."""
    if ss and isinstance(ss, str) and '/' in ss:
        try:
            parts = ss.split('/')
            return float(parts[0]) / float(parts[1])
        except (ValueError, ZeroDivisionError):
            return None
    elif ss:
        try:
            return float(ss)
        except (ValueError, TypeError):
            return None
    return ss


def _compile_category_filter(filters: dict):
    """Precompile one category's filter dict against the scan column indices.

    Returns ``(numeric_checks, bool_checks, tag_spec)`` — a conjunction with the
    same shape and order of outcomes as ``CategoryFilter.matches`` over
    ``with_face_defaults``-ed rows, minus the per-row dict building.
    """
    numeric = []
    for field, idx in _NUMERIC_FIELD_IDX.items():
        mn = filters.get(f'{field}_min')
        mx = filters.get(f'{field}_max')
        if mn is not None or mx is not None:
            numeric.append((idx, mn, mx))
    bools = []
    for key, idx in (('has_face', 1), ('is_monochrome', 5),
                     ('is_silhouette', 3), ('is_group_portrait', 4)):
        required = filters.get(key)
        if required is not None:
            bools.append((idx, required))
    required_tags = [t.lower() for t in filters.get('required_tags', [])]
    excluded_tags = [t.lower() for t in filters.get('excluded_tags', [])]
    tag_spec = None
    if required_tags or excluded_tags:
        tag_spec = (required_tags, excluded_tags, filters.get('tag_match_mode', 'any'))
    return numeric, bools, tag_spec


def _evaluate_overlap_chunk(rows, compiled, names):
    """Evaluate every category filter over one chunk of photo rows.

    The per-row semantics are exactly ``CategoryFilter.matches`` over
    ``with_face_defaults``-ed photo dicts: face NULLs coalesce to 0, shutter
    strings parse to fractional floats, numeric mismatches fail closed on
    unparseable values, and tags compare as the lowercased, end-stripped,
    comma-split set.
    """
    from config.category_filter import _to_float

    overlap_pairs = defaultdict(int)
    match_counts = defaultdict(int)
    assigned_counts = defaultdict(int)
    uncategorized = 0
    total = 0
    tags_needed = any(spec is not None for _, _, spec in compiled)

    for row in rows:
        total += 1
        values = list(row)
        for idx in _FACE_DEFAULT_IDX:
            if values[idx] is None:
                values[idx] = 0
        values[8] = _shutter_float(values[8])

        assigned_cat = row[11] or ''
        if assigned_cat:
            assigned_counts[assigned_cat] += 1
        else:
            uncategorized += 1

        photo_tags = None
        if tags_needed:
            raw = row[0] or ''
            photo_tags = {t.strip().lower() for t in raw.split(',') if t.strip()}

        matched = []
        for (numeric, bools, tag_spec), name in zip(compiled, names):
            ok = True
            for idx, mn, mx in numeric:
                num = _to_float(values[idx])
                if mn is not None:
                    if num is None or num < mn:
                        ok = False
                        break
                if mx is not None:
                    if num is None or num > mx:
                        ok = False
                        break
            if ok:
                for idx, required in bools:
                    actual = bool(values[idx] or 0) if idx != 1 else values[idx] > 0
                    if actual != required:
                        ok = False
                        break
            if ok and tag_spec is not None:
                required_tags, excluded_tags, mode = tag_spec
                if required_tags:
                    if mode == 'any':
                        if not any(tag in photo_tags for tag in required_tags):
                            ok = False
                    else:
                        if not all(tag in photo_tags for tag in required_tags):
                            ok = False
                if ok and excluded_tags:
                    if any(tag in photo_tags for tag in excluded_tags):
                        ok = False
            if ok:
                matched.append(name)
                match_counts[name] += 1

        for i in range(len(matched)):
            for j in range(i + 1, len(matched)):
                pair = tuple(sorted([matched[i], matched[j]]))
                overlap_pairs[pair] += 1

    return total, uncategorized, assigned_counts, match_counts, overlap_pairs


@router.get('/api/stats/categories/correlations', response_model=StatsCategoryCorrelationsResponse,
            response_model_exclude_unset=True)
async def api_stats_categories_correlations(user: Optional[CurrentUser] = Depends(get_optional_user)):
    vis, vp = _vis_where(user)

    async def compute():
        async with get_async_db() as conn:
            # For each category, compute Pearson r between each weight dimension and aggregate
            # Using: r = (N*SUM(xy) - SUM(x)*SUM(y)) / sqrt((N*SUM(x^2) - SUM(x)^2) * (N*SUM(y^2) - SUM(y)^2))
            # One scan for every weight column: each column's own NULL filters
            # (col IS NOT NULL AND aggregate IS NOT NULL) fold into conditional
            # SUMs, which reproduce the per-column WHERE + GROUP BY exactly.
            per_col = []
            for weight_key, col in _WEIGHT_COLUMNS.items():
                cond = f'{col} IS NOT NULL AND aggregate IS NOT NULL'
                per_col.append(f'''
                    SUM(CASE WHEN {cond} THEN 1 ELSE 0 END) AS n__{weight_key},
                    SUM(CASE WHEN {cond} THEN CAST({col} AS REAL) ELSE 0 END) AS sx__{weight_key},
                    SUM(CASE WHEN {cond} THEN CAST(aggregate AS REAL) ELSE 0 END) AS sy__{weight_key},
                    SUM(CASE WHEN {cond} THEN CAST({col} AS REAL) * CAST(aggregate AS REAL) ELSE 0 END) AS sxy__{weight_key},
                    SUM(CASE WHEN {cond} THEN CAST({col} AS REAL) * CAST({col} AS REAL) ELSE 0 END) AS sx2__{weight_key},
                    SUM(CASE WHEN {cond} THEN CAST(aggregate AS REAL) * CAST(aggregate AS REAL) ELSE 0 END) AS sy2__{weight_key}''')
            cur = await conn.execute(f'''
                SELECT category, {', '.join(per_col)}
                FROM photos
                WHERE aggregate IS NOT NULL
                    AND category IS NOT NULL AND category != ''{vis}
                GROUP BY category
            ''', vp)
            corr_rows = await cur.fetchall()
            await cur.close()

            results = {}
            for r in corr_rows:
                cat = r[0]
                for weight_key in _WEIGHT_COLUMNS:
                    n, sx, sy, sxy, sx2, sy2 = (
                        r[f'n__{weight_key}'], r[f'sx__{weight_key}'], r[f'sy__{weight_key}'],
                        r[f'sxy__{weight_key}'], r[f'sx2__{weight_key}'], r[f'sy2__{weight_key}'])
                    # The old HAVING COUNT(*) >= 10 was per column+category.
                    if n < 10:
                        continue
                    denom = math.sqrt((n * sx2 - sx * sx) * (n * sy2 - sy * sy))
                    pearson_r = (n * sxy - sx * sy) / denom if denom > 0 else 0

                    if cat not in results:
                        results[cat] = {}
                    results[cat][weight_key] = round(pearson_r, 3)

        # Also include configured weight percentages for comparison
        config = server_scoring_config()
        configured = {}
        for cat_cfg in config.get_categories():
            name = cat_cfg['name']
            weights = cat_cfg.get('weights', {})
            configured[name] = {}
            for wk in _WEIGHT_COLUMNS:
                configured[name][wk] = weights.get(f'{wk}_percent', 0)

        return {
            'correlations': results,
            'configured_weights': configured,
            'dimensions': list(_WEIGHT_COLUMNS.keys()),
        }

    user_id = user.user_id if user else None
    cache_key = f'cat_correlations:{user_id or ""}'
    return await _get_stats_cached_async(cache_key, compute)


@router.get('/api/stats/categories/overlap', response_model=StatsCategoryOverlapResponse,
            response_model_exclude_unset=True)
async def api_stats_categories_overlap(user: Optional[CurrentUser] = Depends(get_optional_user)):
    vis, vp = _vis_where(user)

    async def compute():
        from config.category_filter import CategoryFilter

        config = server_scoring_config()
        cat_configs = config.get_categories()

        # Build filters for each category
        cat_filters = []
        for cat_cfg in cat_configs:
            cat_filters.append({
                'name': cat_cfg['name'],
                'priority': cat_cfg.get('priority', 100),
                'filter': CategoryFilter(cat_cfg.get('filters', {})),
            })

        overlap_pairs = defaultdict(int)
        match_counts = defaultdict(int)  # how many photos match each filter
        assigned_counts = defaultdict(int)  # how many are actually assigned
        uncategorized = 0
        total = 0

        # The per-row filter evaluation is CPU-bound over the whole library, so
        # the scan streams in chunks: fetchmany hops the event loop once per
        # chunk, the chunk's evaluation runs in a worker thread, and memory
        # stays bounded instead of materialising every row as a dict.
        compiled = [_compile_category_filter(cf['filter'].filters) for cf in cat_filters]
        names = [cf['name'] for cf in cat_filters]
        async with get_async_db() as conn:
            cur = await conn.execute(f'''
                SELECT tags, face_count, face_ratio, is_silhouette, is_group_portrait,
                       is_monochrome, mean_luminance, ISO, shutter_speed, focal_length,
                       f_stop, category
                FROM photos WHERE 1=1{vis}
            ''', vp)
            while True:
                rows = await cur.fetchmany(2000)
                if not rows:
                    break
                chunk = await asyncio.to_thread(
                    _evaluate_overlap_chunk, rows, compiled, names)
                total += chunk[0]
                uncategorized += chunk[1]
                for name, n in chunk[2].items():
                    assigned_counts[name] += n
                for name, n in chunk[3].items():
                    match_counts[name] += n
                for pair, n in chunk[4].items():
                    overlap_pairs[pair] += n
            await cur.close()

        # Build overlap list sorted by count
        overlaps = [
            {'pair': list(pair), 'count': count}
            for pair, count in sorted(overlap_pairs.items(), key=lambda x: -x[1])
            if count > 0
        ]

        # Per-category summary
        per_category = []
        for cf in cat_filters:
            name = cf['name']
            assigned = assigned_counts.get(name, 0)
            matched = match_counts.get(name, 0)
            per_category.append({
                'name': name,
                'priority': cf['priority'],
                'assigned': assigned,
                'matched': matched,
                'captured_by_higher': matched - assigned if matched > assigned else 0,
            })

        return {
            'overlaps': overlaps[:50],  # top 50 pairs
            'per_category': per_category,
            'uncategorized': uncategorized,
            'total': total,
        }

    user_id = user.user_id if user else None
    cache_key = f'cat_overlap:{user_id or ""}'
    return await _get_stats_cached_async(cache_key, compute)


@router.post('/api/stats/categories/update')
def api_stats_categories_update(
    body: CategoryUpdateRequest,
    user: CurrentUser = Depends(require_edition),
):
    if not body.category:
        raise HTTPException(status_code=400, detail='Missing category')

    # A loose full-config backup is only needed when non-weight config (modifiers)
    # changes -- the snapshot table is weights-only.
    backup_path = update_category_weights(
        _CONFIG_PATH, body.category, 'auto:cat_edit', get_db,
        not_found_detail=f'Category "{body.category}" not found',
        weights=body.weights,
        replace_weights=True,
        modifiers=body.modifiers,
        backup=body.modifiers is not None,
    )

    # Reload config and clear stats cache
    reload_config()
    _stats_cache.clear()

    return {
        'success': True,
        'message': f'Category "{body.category}" updated',
        'backup': backup_path,
    }


@router.post('/api/stats/categories/recompute', response_model=StatsCategoryRecomputeResponse,
             response_model_exclude_unset=True)
async def api_stats_categories_recompute(
    body: CategoryRecomputeRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Recompute aggregate scores for a single category.

    Runs ``python facet.py --recompute-category <name>`` as an async subprocess.
    """
    if not body.category:
        raise HTTPException(status_code=400, detail='Missing category')

    refuse_while_gallery_index_build_runs()
    try:
        config_path = str(_CONFIG_PATH)
        proc = await asyncio.create_subprocess_exec(
            sys.executable, FACET_SCRIPT, '--recompute-category', body.category,
            '--config', config_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=child_process_env(),
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=300)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise HTTPException(
                status_code=500,
                detail=f'Recomputation timed out (>5 min). Run manually: python facet.py --recompute-category {body.category}',
            )

        stdout = stdout_bytes.decode(errors='replace')
        stderr = stderr_bytes.decode(errors='replace')

        if proc.returncode == 0:
            _stats_cache.clear()
            return {
                'success': True,
                'message': f'Scores recomputed for "{body.category}"',
                'output': stdout,
            }
        else:
            raise HTTPException(
                status_code=500,
                detail=stderr or stdout,
            ) from library_lock_held_error(proc.returncode)

    except HTTPException:
        raise
    except Exception:
        logger.exception("Category recomputation failed for %s", body.category)
        raise HTTPException(status_code=500, detail='Recomputation failed')


@router.get("/api/stats/metric_distribution", response_model=MetricDistributionResponse)
def metric_distribution(column: str = Query("aggregate", max_length=80),
                        category: Optional[str] = Query(None, max_length=200),
                        user: CurrentUser = Depends(require_authenticated)):
    """One metric in the caller's visible library, optionally within a category.

    Cached in the stats cache per metric, category and visibility scope: the form
    metrics have no index, so an uncached read walks every photo's overflow pages.
    Identifiers come exclusively from the registry.
    """
    from api.routers.gallery import SCORE_RANGE_COLUMNS, EXIF_RANGE_COLUMNS
    from metric_columns import FORM_METRIC_COLUMNS
    # Manual ratings have account-specific authority; this endpoint describes computed metrics.
    columns = {name: name for name in
               ({row[0] for row in SCORE_RANGE_COLUMNS + EXIF_RANGE_COLUMNS} | set(FORM_METRIC_COLUMNS))
               if name != 'star_rating'}
    # Interpolate the registry value, never the request's identifier.
    sql_column = columns.get(column)
    if sql_column is None:
        raise HTTPException(422, 'Unknown metric')
    visibility, params = get_visibility_clause(user.user_id if user else None)
    where = f"{visibility} AND {sql_column} > ? AND {sql_column} < ?"
    params = [*params, float('-inf'), float('inf')]
    if category is not None:
        where += ' AND category = ?'
        params.append(category)
    def compute():
        with get_db() as conn:
            conn.execute('BEGIN')
            row = conn.execute(f'SELECT MIN({sql_column}),MAX({sql_column}),COUNT(*) FROM photos WHERE {where}', params).fetchone()
            if not row[2]:
                return {'distribution': None, 'count': 0}
            lo, hi, count = float(row[0]), float(row[1]), row[2]
            buckets = [count]
            if hi > lo:
                buckets = [0] * 32
                scale = max(abs(lo), abs(hi), 1.0)
                normalized_lo = lo / scale
                span = hi / scale - normalized_lo
                for bucket, total in conn.execute(
                        f'SELECT MAX(0,MIN(31,CAST((({sql_column}/?-?)/?)*32 AS INTEGER))),COUNT(*) '
                        f'FROM photos WHERE {where} GROUP BY 1', [scale, normalized_lo, span, *params]):
                    buckets[int(bucket)] = total
        return {'distribution': {'column': sql_column, 'min': lo, 'max': hi, 'buckets': buckets}, 'count': count}
    # The visibility fragment and its parameters already encode the reader's scope.
    return _get_stats_cached(f'metric_distribution:{sql_column}:{category}:{where}:{params}', compute)
