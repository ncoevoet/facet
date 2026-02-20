"""
Stats router — gear, settings, timeline, correlations, category analysis.

"""

import json
import math
import os
import shutil
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.auth import CurrentUser, get_optional_user, require_edition
from api.config import (
    VIEWER_CONFIG, CORRELATION_X_AXES, CORRELATION_Y_METRICS,
    _get_stats_cached, _stats_cache, _FULL_CONFIG, _CONFIG_PATH, reload_config,
)
from api.database import get_db_connection
from api.db_helpers import get_visibility_clause

_FACET_SCRIPT = os.path.join(os.path.dirname(__file__), '..', '..', 'facet.py')

router = APIRouter(tags=["stats"])

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
}


# --- Visibility helper ---

def _vis_where(user: Optional[CurrentUser]):
    """Return (where_clause_with_AND_prefix, params) for visibility filtering.

    Returns ('', []) in legacy mode. In multi-user mode returns
    (' AND <visibility>', [params...]) suitable for appending to an existing WHERE.
    """
    user_id = user.user_id if user else None
    if not user_id:
        return '', []
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
        params.append(date_from)
    if date_to:
        clause += ' AND date_taken <= ?'
        params.append(date_to + ' 23:59:59')
    if category:
        clause += ' AND category = ?'
        params.append(category)
    return clause, params


# --- Endpoints ---

@router.get('/api/stats/overview')
def api_stats_overview(
    user: Optional[CurrentUser] = Depends(get_optional_user),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
):
    """Aggregate overview stats for the Angular stats page."""
    vis, vp = _stats_filter_where(user, date_from, date_to, category)

    def compute():
        conn = get_db_connection()
        try:
            cur = conn.cursor()

            cur.execute(f'''SELECT COUNT(*) as total,
                           ROUND(AVG(aggregate), 2) as avg_agg,
                           ROUND(AVG(aesthetic), 2) as avg_aes,
                           ROUND(AVG(comp_score), 2) as avg_comp,
                           MIN(date_taken) as date_start,
                           MAX(date_taken) as date_end
                           FROM photos WHERE 1=1{vis}''', vp)
            row = cur.fetchone()

            # Total faces
            try:
                faces_row = cur.execute(f'''SELECT COUNT(*) FROM faces
                    WHERE photo_path IN (SELECT path FROM photos WHERE 1=1{vis})''', vp).fetchone()
                total_faces = faces_row[0] if faces_row else 0
            except Exception:
                total_faces = 0

            # Total persons
            try:
                persons_row = cur.execute('SELECT COUNT(*) FROM persons').fetchone()
                total_persons = persons_row[0] if persons_row else 0
            except Exception:
                total_persons = 0

            # Total distinct tags
            try:
                from api.db_helpers import is_photo_tags_available
                if is_photo_tags_available(conn):
                    tags_row = cur.execute('SELECT COUNT(DISTINCT tag) FROM photo_tags').fetchone()
                else:
                    tags_row = (0,)
                total_tags = tags_row[0] if tags_row else 0
            except Exception:
                total_tags = 0
        finally:
            conn.close()

        # Format dates
        date_start = ''
        date_end = ''
        if row[4]:
            date_start = row[4][:10].replace(':', '-')
        if row[5]:
            date_end = row[5][:10].replace(':', '-')

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
    return _get_stats_cached(cache_key, compute)


@router.get('/api/stats/score_distribution')
def api_stats_score_distribution(
    user: Optional[CurrentUser] = Depends(get_optional_user),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
):
    """Score distribution histogram for the Angular stats page."""
    vis, vp = _stats_filter_where(user, date_from, date_to, category)

    def compute():
        conn = get_db_connection()
        try:
            cur = conn.cursor()

            # 0.5-point buckets
            cur.execute(f'''SELECT ROUND(aggregate * 2) / 2.0 AS bucket, COUNT(*) as cnt
                           FROM photos WHERE aggregate IS NOT NULL{vis}
                           GROUP BY bucket ORDER BY bucket''', vp)
            rows = cur.fetchall()
            total = sum(r[1] for r in rows) or 1
        finally:
            conn.close()

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
    return _get_stats_cached(cache_key, compute)


@router.get('/api/stats/top_cameras')
def api_stats_top_cameras(
    user: Optional[CurrentUser] = Depends(get_optional_user),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
):
    """Top cameras ranked by average aggregate score."""
    vis, vp = _stats_filter_where(user, date_from, date_to, category)

    def compute():
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute(f'''SELECT camera_model, COUNT(*) as cnt,
                           ROUND(AVG(aggregate), 2) as avg_agg,
                           ROUND(AVG(aesthetic), 2) as avg_aes
                           FROM photos WHERE camera_model IS NOT NULL AND camera_model != ''{vis}
                           GROUP BY camera_model HAVING cnt >= 10
                           ORDER BY avg_agg DESC LIMIT 20''', vp)
            cameras = [{'name': r[0], 'count': r[1], 'avg_score': r[2], 'avg_aesthetic': r[3]} for r in cur.fetchall()]
        finally:
            conn.close()
        return cameras

    user_id = user.user_id if user else None
    cache_key = f'top_cameras:{user_id or ""}:{date_from or ""}:{date_to or ""}:{category or ""}'
    return _get_stats_cached(cache_key, compute)


@router.get('/api/stats/categories')
def api_stats_categories(
    user: Optional[CurrentUser] = Depends(get_optional_user),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
):
    """Category stats in the format the Angular component expects (CategoryStat[])."""
    vis, vp = _stats_filter_where(user, date_from, date_to, category)

    def compute():
        conn = get_db_connection()
        try:
            cur = conn.cursor()

            cur.execute(f'''SELECT category, COUNT(*) as cnt, ROUND(AVG(aggregate), 2) as avg_agg
                           FROM photos WHERE 1=1{vis}
                           GROUP BY category ORDER BY cnt DESC''', vp)
            rows = cur.fetchall()
            total = sum(r[1] for r in rows) or 1
        finally:
            conn.close()

        return [
            {
                'category': r[0] or '(uncategorized)',
                'count': r[1],
                'percentage': r[1] / total,
                'avg_score': r[2] or 0,
            }
            for r in rows
        ]

    user_id = user.user_id if user else None
    cache_key = f'categories_stats:{user_id or ""}:{date_from or ""}:{date_to or ""}:{category or ""}'
    return _get_stats_cached(cache_key, compute)


@router.get('/api/stats/gear')
def api_stats_gear(
    user: Optional[CurrentUser] = Depends(get_optional_user),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
):
    vis, vp = _stats_filter_where(user, date_from, date_to, category)

    def compute():
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            # Camera bodies
            cur.execute(f'''SELECT camera_model, COUNT(*) as cnt, ROUND(AVG(aggregate),2), ROUND(AVG(aesthetic),2)
                           FROM photos WHERE camera_model IS NOT NULL AND camera_model != ''{vis}
                           GROUP BY camera_model ORDER BY cnt DESC LIMIT 20''', vp)
            cameras = [{'name': r[0], 'count': r[1], 'avg_aggregate': r[2], 'avg_aesthetic': r[3]} for r in cur.fetchall()]

            # Lenses
            cur.execute(f'''SELECT lens_model, COUNT(*) as cnt, ROUND(AVG(aggregate),2), ROUND(AVG(aesthetic),2)
                           FROM photos WHERE lens_model IS NOT NULL AND lens_model != ''{vis}
                           GROUP BY lens_model ORDER BY cnt DESC LIMIT 20''', vp)
            lenses = [{'name': r[0], 'count': r[1], 'avg_aggregate': r[2], 'avg_aesthetic': r[3]} for r in cur.fetchall()]

            # Combos
            cur.execute(f'''SELECT camera_model || ' + ' || lens_model as combo, COUNT(*) as cnt, ROUND(AVG(aggregate),2)
                           FROM photos WHERE camera_model IS NOT NULL AND camera_model != '' AND lens_model IS NOT NULL AND lens_model != ''{vis}
                           GROUP BY camera_model, lens_model ORDER BY cnt DESC LIMIT 20''', vp)
            combos = [{'name': r[0], 'count': r[1], 'avg_aggregate': r[2]} for r in cur.fetchall()]

            # Category distribution
            cur.execute(f'''SELECT category, COUNT(*) as cnt
                           FROM photos WHERE category IS NOT NULL AND category != ''{vis}
                           GROUP BY category ORDER BY cnt DESC''', vp)
            categories = [{'name': r[0], 'count': r[1]} for r in cur.fetchall()]
        finally:
            conn.close()
        return {'cameras': cameras, 'lenses': lenses, 'combos': combos, 'categories': categories}

    user_id = user.user_id if user else None
    cache_key = f'gear:{user_id or ""}:{date_from or ""}:{date_to or ""}:{category or ""}'
    return _get_stats_cached(cache_key, compute)


@router.get('/api/stats/settings')
def api_stats_settings(
    user: Optional[CurrentUser] = Depends(get_optional_user),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
):
    vis, vp = _stats_filter_where(user, date_from, date_to, category)

    def compute():
        conn = get_db_connection()
        try:
            cur = conn.cursor()

            # ISO distribution with buckets
            cur.execute(f'''SELECT
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
            iso = [{'label': r[0], 'count': r[1]} for r in cur.fetchall()]

            # Aperture usage
            cur.execute(f'''SELECT ROUND(f_stop, 1) as ap, COUNT(*) as cnt
                           FROM photos WHERE f_stop IS NOT NULL AND f_stop > 0{vis}
                           GROUP BY ap ORDER BY ap''', vp)
            aperture = [{'value': r[0], 'count': r[1]} for r in cur.fetchall()]

            # Focal length distribution (prefer 35mm equivalent)
            cur.execute(f'''SELECT
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
            focal = [{'label': r[0], 'count': r[1]} for r in cur.fetchall()]

            # Shutter speed distribution with SQL binning
            cur.execute(f'''SELECT
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
                    SELECT CASE
                        WHEN INSTR(shutter_speed, '/') > 0
                        THEN CAST(SUBSTR(shutter_speed, 1, INSTR(shutter_speed, '/') - 1) AS REAL)
                             / CAST(SUBSTR(shutter_speed, INSTR(shutter_speed, '/') + 1) AS REAL)
                        ELSE CAST(shutter_speed AS REAL)
                    END as ss
                    FROM photos
                    WHERE shutter_speed IS NOT NULL AND shutter_speed != ''{vis}
                ) WHERE ss IS NOT NULL AND ss > 0
                GROUP BY shutter_bucket ORDER BY sort_key''', vp)
            shutter = [{'label': r[0], 'count': r[1]} for r in cur.fetchall()]

            # Score distribution in 0.5-point buckets
            cur.execute(f'''SELECT ROUND(aggregate * 2) / 2.0 AS bucket, COUNT(*) as cnt
                           FROM photos WHERE aggregate IS NOT NULL{vis}
                           GROUP BY bucket ORDER BY bucket''', vp)
            score_dist = [{'label': str(r[0]), 'count': r[1]} for r in cur.fetchall()]
        finally:
            conn.close()

        return {'iso': iso, 'aperture': aperture, 'focal_length': focal, 'shutter_speed': shutter, 'score_distribution': score_dist}

    user_id = user.user_id if user else None
    cache_key = f'settings:{user_id or ""}:{date_from or ""}:{date_to or ""}:{category or ""}'
    return _get_stats_cached(cache_key, compute)


@router.get('/api/stats/timeline')
def api_stats_timeline(
    user: Optional[CurrentUser] = Depends(get_optional_user),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
):
    vis, vp = _stats_filter_where(user, date_from, date_to, category)

    def compute():
        conn = get_db_connection()
        try:
            cur = conn.cursor()

            # Monthly
            cur.execute(f'''SELECT SUBSTR(date_taken, 1, 7) as month, COUNT(*) as cnt, ROUND(AVG(aggregate), 2) as avg_agg
                           FROM photos WHERE date_taken IS NOT NULL AND date_taken != ''{vis}
                           GROUP BY month ORDER BY month''', vp)
            monthly = [{'month': r[0].replace(':', '-'), 'count': r[1], 'avg_score': r[2] or 0} for r in cur.fetchall()]

            # Yearly
            cur.execute(f'''SELECT SUBSTR(date_taken, 1, 4) as year, COUNT(*) as cnt
                           FROM photos WHERE date_taken IS NOT NULL AND date_taken != ''{vis}
                           GROUP BY year ORDER BY year''', vp)
            yearly = [{'year': r[0], 'count': r[1]} for r in cur.fetchall()]

            # Heatmap (day of week x hour)
            cur.execute(f'''SELECT
                CAST(STRFTIME('%w', REPLACE(SUBSTR(date_taken,1,10),':','-')) AS INTEGER) as dow,
                CAST(SUBSTR(date_taken, 12, 2) AS INTEGER) as hour,
                COUNT(*) as cnt
                FROM photos WHERE date_taken IS NOT NULL AND LENGTH(date_taken) >= 13{vis}
                GROUP BY dow, hour''', vp)
            heatmap = [{'day': r[0], 'hour': r[1], 'count': r[2]} for r in cur.fetchall()]

            # Top days
            cur.execute(f'''SELECT REPLACE(SUBSTR(date_taken, 1, 10), ':', '-') as day, COUNT(*) as cnt
                           FROM photos WHERE date_taken IS NOT NULL AND date_taken != ''{vis}
                           GROUP BY day ORDER BY cnt DESC LIMIT 10''', vp)
            top_days = [{'date': r[0], 'count': r[1]} for r in cur.fetchall()]
        finally:
            conn.close()
        return {'monthly': monthly, 'yearly': yearly, 'heatmap': heatmap, 'top_days': top_days}

    user_id = user.user_id if user else None
    cache_key = f'timeline:{user_id or ""}:{date_from or ""}:{date_to or ""}:{category or ""}'
    return _get_stats_cached(cache_key, compute)


@router.get('/api/stats/correlations')
def api_stats_correlations(
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

    def compute():
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            x_def = CORRELATION_X_AXES[x]
            x_sql = x_def['sql']
            x_filter = x_def['filter']
            x_sort = x_def['sort']

            # Build date filter clause
            date_clauses = []
            date_params = []
            if date_from:
                date_clauses.append("date_taken >= ?")
                date_params.append(date_from.replace('-', ':'))
            if date_to:
                date_clauses.append("date_taken <= ?")
                date_params.append(date_to.replace('-', ':') + " 23:59:59")
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
                cur.execute(f"SELECT {g_sql}, COUNT(*) as cnt FROM photos WHERE {g_filter} AND {x_filter} AND {date_filter} AND {vis_filter} GROUP BY {g_sql} ORDER BY cnt DESC LIMIT ?", date_params + vp + [top_n])
                top_groups = [r[0] for r in cur.fetchall()]
                if not top_groups:
                    return {'labels': [], 'groups': {}, 'metrics': y_metrics, 'x_axis': x, 'group_by': group_by}

                placeholders = ','.join('?' for _ in top_groups)
                sql = f"""SELECT {x_sql} AS x_bucket, {g_sql} AS group_val, {metric_cols}, COUNT(*) AS cnt
                          FROM photos
                          WHERE {x_filter} AND {g_filter} AND {date_filter} AND {vis_filter} AND {g_sql} IN ({placeholders})
                          GROUP BY x_bucket, group_val
                          HAVING cnt >= ?
                          ORDER BY {x_sort}"""
                cur.execute(sql, date_params + vp + top_groups + [min_samples])
                rows = cur.fetchall()
            else:
                sql = f"""SELECT {x_sql} AS x_bucket, {metric_cols}, COUNT(*) AS cnt
                          FROM photos
                          WHERE {x_filter} AND {date_filter} AND {vis_filter}
                          GROUP BY x_bucket
                          HAVING cnt >= ?
                          ORDER BY {x_sort}"""
                cur.execute(sql, date_params + vp + [min_samples])
                rows = cur.fetchall()
        finally:
            conn.close()

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

    return _get_stats_cached(cache_key, compute)


# --- Categories tab endpoints ---

@router.get('/api/stats/categories/breakdown')
def api_stats_categories_breakdown(user: Optional[CurrentUser] = Depends(get_optional_user)):
    vis, vp = _vis_where(user)

    def compute():
        conn = get_db_connection()
        try:
            cur = conn.cursor()

            # Per-category counts and averages
            cur.execute(f'''
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

            categories = []
            total = 0
            uncategorized = 0
            for r in cur.fetchall():
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
            cur.execute(f'''
                SELECT category, ROUND(aggregate * 2) / 2.0 AS bucket, COUNT(*) as cnt
                FROM photos WHERE aggregate IS NOT NULL{vis}
                GROUP BY category, bucket ORDER BY category, bucket
            ''', vp)

            distributions = {}
            for r in cur.fetchall():
                cat = r[0] or '(uncategorized)'
                if cat not in distributions:
                    distributions[cat] = []
                distributions[cat].append({'bucket': r[1], 'count': r[2]})
        finally:
            conn.close()
        return {
            'categories': categories,
            'distributions': distributions,
            'total': total,
            'uncategorized': uncategorized,
        }

    user_id = user.user_id if user else None
    cache_key = f'cat_breakdown:{user_id or ""}'
    return _get_stats_cached(cache_key, compute)


@router.get('/api/stats/categories/weights')
def api_stats_categories_weights(user: Optional[CurrentUser] = Depends(get_optional_user)):
    from config import ScoringConfig

    config = ScoringConfig(validate=False)
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


@router.get('/api/stats/categories/correlations')
def api_stats_categories_correlations(user: Optional[CurrentUser] = Depends(get_optional_user)):
    vis, vp = _vis_where(user)

    def compute():
        conn = get_db_connection()
        try:
            cur = conn.cursor()

            # For each category, compute Pearson r between each weight dimension and aggregate
            # Using: r = (N*SUM(xy) - SUM(x)*SUM(y)) / sqrt((N*SUM(x^2) - SUM(x)^2) * (N*SUM(y^2) - SUM(y)^2))
            results = {}
            for weight_key, col in _WEIGHT_COLUMNS.items():
                cur.execute(f'''
                    SELECT category,
                        COUNT(*) as n,
                        SUM(CAST({col} AS REAL)) as sx,
                        SUM(CAST(aggregate AS REAL)) as sy,
                        SUM(CAST({col} AS REAL) * CAST(aggregate AS REAL)) as sxy,
                        SUM(CAST({col} AS REAL) * CAST({col} AS REAL)) as sx2,
                        SUM(CAST(aggregate AS REAL) * CAST(aggregate AS REAL)) as sy2
                    FROM photos
                    WHERE {col} IS NOT NULL AND aggregate IS NOT NULL
                        AND category IS NOT NULL AND category != ''{vis}
                    GROUP BY category
                    HAVING COUNT(*) >= 10
                ''', vp)

                for r in cur.fetchall():
                    cat = r[0]
                    n, sx, sy, sxy, sx2, sy2 = r[1], r[2], r[3], r[4], r[5], r[6]
                    denom = math.sqrt((n * sx2 - sx * sx) * (n * sy2 - sy * sy))
                    pearson_r = (n * sxy - sx * sy) / denom if denom > 0 else 0

                    if cat not in results:
                        results[cat] = {}
                    results[cat][weight_key] = round(pearson_r, 3)
        finally:
            conn.close()

        # Also include configured weight percentages for comparison
        from config import ScoringConfig
        config = ScoringConfig(validate=False)
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
    return _get_stats_cached(cache_key, compute)


@router.get('/api/stats/categories/metrics')
def api_stats_categories_metrics(
    category: str = Query(...),
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Return raw metric values for photos in a category (for client-side preview)."""
    if not category:
        raise HTTPException(status_code=400, detail='Missing category')

    vis, vp = _vis_where(user)

    def compute():
        cols = list(_WEIGHT_COLUMNS.values())
        col_sql = ', '.join(cols)

        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                f'SELECT {col_sql}, aggregate FROM photos WHERE category = ?{vis} LIMIT 5000',
                [category] + vp,
            )

            metrics = {k: [] for k in _WEIGHT_COLUMNS}
            current_aggregate = []
            for row in cur.fetchall():
                for i, key in enumerate(_WEIGHT_COLUMNS):
                    metrics[key].append(row[i] if row[i] is not None else 0)
                current_aggregate.append(row[len(cols)] if row[len(cols)] is not None else 0)
        finally:
            conn.close()

        return {
            'category': category,
            'count': len(current_aggregate),
            'metrics': metrics,
            'current_aggregate': current_aggregate,
        }

    user_id = user.user_id if user else None
    cache_key = f'cat_metrics:{category}:{user_id or ""}'
    return _get_stats_cached(cache_key, compute)


@router.get('/api/stats/categories/overlap')
def api_stats_categories_overlap(user: Optional[CurrentUser] = Depends(get_optional_user)):
    vis, vp = _vis_where(user)

    def compute():
        from config import ScoringConfig
        from config.category_filter import CategoryFilter

        config = ScoringConfig(validate=False)
        cat_configs = config.get_categories()

        # Build filters for each category
        cat_filters = []
        for cat_cfg in cat_configs:
            cat_filters.append({
                'name': cat_cfg['name'],
                'priority': cat_cfg.get('priority', 100),
                'filter': CategoryFilter(cat_cfg.get('filters', {})),
            })

        # Fetch photo data needed for filter evaluation
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute(f'''
                SELECT tags, face_count, face_ratio, is_silhouette, is_group_portrait,
                       is_monochrome, mean_luminance, ISO, shutter_speed, focal_length,
                       f_stop, category
                FROM photos WHERE 1=1{vis}
            ''', vp)

            columns = ['tags', 'face_count', 'face_ratio', 'is_silhouette', 'is_group_portrait',
                        'is_monochrome', 'mean_luminance', 'iso', 'shutter_speed', 'focal_length',
                        'f_stop', 'category']

            # Count overlaps
            overlap_pairs = defaultdict(int)
            match_counts = defaultdict(int)  # how many photos match each filter
            assigned_counts = defaultdict(int)  # how many are actually assigned
            uncategorized = 0
            total = 0

            for row in cur.fetchall():
                total += 1
                photo_data = dict(zip(columns, row))

                # Parse shutter_speed from string to float
                ss = photo_data.get('shutter_speed')
                if ss and isinstance(ss, str) and '/' in ss:
                    try:
                        parts = ss.split('/')
                        photo_data['shutter_speed'] = float(parts[0]) / float(parts[1])
                    except (ValueError, ZeroDivisionError):
                        photo_data['shutter_speed'] = None
                elif ss:
                    try:
                        photo_data['shutter_speed'] = float(ss)
                    except (ValueError, TypeError):
                        photo_data['shutter_speed'] = None

                assigned_cat = photo_data.get('category') or ''
                if assigned_cat:
                    assigned_counts[assigned_cat] += 1
                else:
                    uncategorized += 1

                # Test all filters
                matched = []
                for cf in cat_filters:
                    if cf['filter'].matches(photo_data):
                        matched.append(cf['name'])
                        match_counts[cf['name']] += 1

                # Record overlap pairs
                for i in range(len(matched)):
                    for j in range(i + 1, len(matched)):
                        pair = tuple(sorted([matched[i], matched[j]]))
                        overlap_pairs[pair] += 1
        finally:
            conn.close()

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
    return _get_stats_cached(cache_key, compute)


@router.post('/api/stats/categories/update')
def api_stats_categories_update(
    body: CategoryUpdateRequest,
    user: CurrentUser = Depends(require_edition),
):
    if not body.category:
        raise HTTPException(status_code=400, detail='Missing category')

    # Read current config
    with open(_CONFIG_PATH) as f:
        config = json.load(f)

    # Create backup
    backup_path = f"{_CONFIG_PATH}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(_CONFIG_PATH, backup_path)

    # Find and update category
    categories = config.get('categories', [])
    found = False
    for cat in categories:
        if cat.get('name') == body.category:
            if body.weights is not None:
                cat['weights'] = body.weights
            if body.modifiers is not None:
                cat['modifiers'] = body.modifiers
            found = True
            break

    if not found:
        raise HTTPException(status_code=404, detail=f'Category "{body.category}" not found')

    # Write back
    with open(_CONFIG_PATH, 'w') as f:
        json.dump(config, f, indent=2)

    # Reload config and clear stats cache
    reload_config()
    _stats_cache.clear()

    return {
        'success': True,
        'message': f'Category "{body.category}" updated',
        'backup': backup_path,
    }


@router.post('/api/stats/categories/recompute')
def api_stats_categories_recompute(
    body: CategoryRecomputeRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Recompute aggregate scores for a single category.

    Runs ``python facet.py --recompute-category <name>`` as a subprocess.
    """
    if not body.category:
        raise HTTPException(status_code=400, detail='Missing category')

    try:
        config_path = str(_CONFIG_PATH)
        result = subprocess.run(
            [sys.executable, _FACET_SCRIPT, '--recompute-category', body.category,
             '--config', config_path],
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode == 0:
            _stats_cache.clear()
            return {
                'success': True,
                'message': f'Scores recomputed for "{body.category}"',
                'output': result.stdout,
            }
        else:
            raise HTTPException(
                status_code=500,
                detail=result.stderr or result.stdout,
            )

    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=500,
            detail=f'Recomputation timed out (>5 min). Run manually: python facet.py --recompute-category {body.category}',
        )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail='Recomputation failed')
