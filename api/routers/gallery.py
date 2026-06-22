"""
Gallery router — photo listing, type counts, similar photos.

"""

import asyncio
import logging
import math
import sqlite3
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import ValidationError

from api.auth import CurrentUser, get_optional_user
from api.config import VIEWER_CONFIG, _FULL_CONFIG
from api.database import get_async_db, get_db
from api.models.gallery import GalleryParams
from api.db_helpers import (
    get_existing_columns, get_cached_count_async, _add_tag_filter,
    get_art_tags_from_config, build_hide_clauses,
    split_photo_tags, attach_person_data_async, sanitize_float_values,
    get_visibility_clause, get_photos_from_clause, get_preference_columns,
    build_photo_select_columns,
    format_date, to_exif_date, paginate,
)
from api.top_picks import get_top_picks_score_sql, get_top_picks_threshold
from api.types import (
    VALID_SORT_COLS, TYPE_FILTERS, normalize_params, get_photo_types
)

router = APIRouter(tags=["gallery"])
logger = logging.getLogger(__name__)



_FTS_TOKEN_CHARS = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
)

# Hue-bucket name -> [start_deg, end_deg) half-open ranges over dominant_hue (0-360).
# Eight perceptual buckets; 'red' wraps the 0/360 boundary so it is matched with OR.
HUE_BUCKETS = {
    'red': [(0.0, 15.0), (345.0, 360.0)],
    'orange': [(15.0, 45.0)],
    'yellow': [(45.0, 70.0)],
    'green': [(70.0, 165.0)],
    'cyan': [(165.0, 195.0)],
    'blue': [(195.0, 255.0)],
    'purple': [(255.0, 300.0)],
    'magenta': [(300.0, 345.0)],
}


def bucket_for_hue(hue):
    """Return the hue-bucket name containing ``hue`` (degrees), or ``None``.

    Single source of truth for hue-bucket membership (half-open ranges
    ``[lo, hi)``) shared by the gallery colour filter and the ``/colors`` facet
    counts, so the two can never disagree on a boundary.
    """
    for name, ranges in HUE_BUCKETS.items():
        if any(lo <= hue < hi for lo, hi in ranges):
            return name
    return None


_VALID_COLOR_TEMPS = {'warm', 'cool', 'neutral'}

# Quality tiers map a fraction of the aggregate (0-10) scale onto the configured
# quality_thresholds (good/great/excellent/best). Bands are computed on the fly
# in SQL, so no new column is needed.
_QUALITY_TIER_KEYS = {'excellent', 'good', 'fair', 'poor'}


def _fts5_query_from(term: str) -> Optional[str]:
    """Convert free-text user input into an FTS5 query string.

    Splits on whitespace, strips FTS5 syntax characters from each token,
    quotes the survivor and adds a `*` prefix-match wildcard, then ANDs
    the tokens together (FTS5 default behaviour). Returns ``None`` if no
    safe token remains, which short-circuits the search to "match nothing"
    rather than risking an injected FTS5 expression.
    """
    tokens = []
    for raw in term.split():
        cleaned = ''.join(ch for ch in raw if ch in _FTS_TOKEN_CHARS)
        if cleaned:
            tokens.append(f'"{cleaned}"*')
    return ' '.join(tokens) if tokens else None


def _apply_search_filter(where_clauses, sql_params, term: str, conn):
    """Apply the gallery free-text search filter.

    Prefers a single ``photos_fts MATCH`` query over the covering FTS5
    schema (filename + caption + caption_translated + tags + camera_model +
    lens_model + category), OR'd with a person-name LIKE so face-tagged
    person searches still work. Falls back to the legacy LIKE OR-chain if
    the FTS5 table is missing (older DB without rebuild).
    """
    from db.fts import has_fts_table

    fts_query = _fts5_query_from(term)

    if fts_query and has_fts_table(conn):
        person_like = "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        # IN-subquery rather than EXISTS per row: the persons.name LIKE
        # scan runs once on the small persons table (a few thousand rows)
        # instead of N times against the photos table. On a no-match query
        # this collapses the worst-case from ~580 ms to ~2 ms.
        where_clauses.append(
            "("
            "photos.rowid IN (SELECT rowid FROM photos_fts WHERE photos_fts MATCH ?)"
            " OR photos.path IN ("
            "SELECT f.photo_path FROM faces f JOIN persons p ON f.person_id = p.id"
            " WHERE p.name LIKE ? ESCAPE '\\')"
            ")"
        )
        sql_params.extend([fts_query, person_like])
        return

    escaped_term = term.replace('%', '\\%').replace('_', '\\_')
    search_clauses = [
        "filename LIKE ? ESCAPE '\\'",
        "camera_model LIKE ? ESCAPE '\\'",
        "lens_model LIKE ? ESCAPE '\\'",
        "category LIKE ? ESCAPE '\\'",
    ]
    search_params = [f"%{escaped_term}%"] * 4

    from api.db_helpers import is_photo_tags_available
    if is_photo_tags_available(conn):
        search_clauses.append(
            "EXISTS (SELECT 1 FROM photo_tags WHERE photo_path = photos.path "
            "AND tag LIKE ? ESCAPE '\\')"
        )
    else:
        search_clauses.append("tags LIKE ? ESCAPE '\\'")
    search_params.append(f"%{escaped_term}%")

    existing_cols = get_existing_columns(conn)
    if 'caption' in existing_cols:
        search_clauses.append("caption LIKE ? ESCAPE '\\'")
        search_params.append(f"%{escaped_term}%")
    if 'caption_translated' in existing_cols:
        search_clauses.append("caption_translated LIKE ? ESCAPE '\\'")
        search_params.append(f"%{escaped_term}%")

    search_clauses.append(
        "EXISTS (SELECT 1 FROM faces f JOIN persons p ON f.person_id = p.id "
        "WHERE f.photo_path = photos.path AND p.name LIKE ? ESCAPE '\\')"
    )
    search_params.append(f"%{escaped_term}%")

    where_clauses.append(f"({' OR '.join(search_clauses)})")
    sql_params.extend(search_params)


def _add_range_filter(where_clauses, sql_params, params, column, min_key, max_key, is_float=True):
    """Add min/max range filter for a numeric column."""
    min_val = params.get(min_key, '')
    max_val = params.get(max_key, '')
    if min_val:
        try:
            val = float(min_val) if is_float else int(min_val)
            where_clauses.append(f"{column} >= ?")
            sql_params.append(val)
        except ValueError:
            pass
    if max_val:
        try:
            val = float(max_val) if is_float else int(max_val)
            where_clauses.append(f"{column} <= ?")
            sql_params.append(val)
        except ValueError:
            pass


def _apply_text_filters(where_clauses, sql_params, params, conn):
    """Apply camera, lens, search, tag, composition, person, category filters."""
    if params.get('camera'):
        where_clauses.append("camera_model = ?")
        sql_params.append(params['camera'])
    if params.get('lens'):
        clean_search = params['lens'].split('\ufffd')[0].strip()
        where_clauses.append("lens_model LIKE ?")
        sql_params.append(f"{clean_search}%")

    if params.get('search'):
        _apply_search_filter(where_clauses, sql_params, params['search'], conn)

    _add_tag_filter(
        where_clauses, sql_params,
        tag=params.get('tag'),
        require_tags=params.get('require_tags'),
        exclude_tags=params.get('exclude_tags'),
        exclude_art_tags=get_art_tags_from_config() if params.get('exclude_art') == '1' else None,
        conn=conn
    )

    if params.get('composition_pattern'):
        where_clauses.append("composition_pattern = ?")
        sql_params.append(params['composition_pattern'])

    if params.get('person'):
        for pid_str in params['person'].split(','):
            try:
                pid = int(pid_str.strip())
                where_clauses.append("EXISTS (SELECT 1 FROM faces WHERE photo_path = photos.path AND person_id = ?)")
                sql_params.append(pid)
            except ValueError:
                pass

    if params.get('is_monochrome') == '1':
        where_clauses.append("is_monochrome = 1")

    if params.get('category'):
        where_clauses.append("category = ?")
        sql_params.append(params['category'])

    if params.get('is_silhouette') == '1':
        where_clauses.append("is_silhouette = 1")


def _quality_tier_bounds(tier):
    """Return (min, max) aggregate bounds for a quality tier, or None if invalid.

    Tiers are derived from the configured ``quality_thresholds`` block
    (good/great/excellent/best) on the 0-10 aggregate scale:
      excellent: aggregate >= excellent
      good:      great <= aggregate < excellent
      fair:      good  <= aggregate < great
      poor:      aggregate < good
    A bound of None means "open" on that side.
    """
    if tier not in _QUALITY_TIER_KEYS:
        return None
    thresholds = VIEWER_CONFIG.get('quality_thresholds', {}) or {}
    good = float(thresholds.get('good', 6))
    great = float(thresholds.get('great', 7))
    excellent = float(thresholds.get('excellent', 8))
    if tier == 'excellent':
        return (excellent, None)
    if tier == 'good':
        return (great, excellent)
    if tier == 'fair':
        return (good, great)
    return (None, good)  # poor


def _apply_color_quality_filters(where_clauses, sql_params, params):
    """Apply colour-temperature, hue-bucket, and quality-tier filters."""
    temp = params.get('color_temp')
    if temp in _VALID_COLOR_TEMPS:
        where_clauses.append("color_temp = ?")
        sql_params.append(temp)

    bucket = params.get('hue_bucket')
    if bucket in HUE_BUCKETS:
        ranges = HUE_BUCKETS[bucket]
        sub = " OR ".join("(dominant_hue >= ? AND dominant_hue < ?)" for _ in ranges)
        where_clauses.append(f"(dominant_hue IS NOT NULL AND ({sub}))")
        for lo, hi in ranges:
            sql_params.extend([lo, hi])

    bounds = _quality_tier_bounds(params.get('quality_tier'))
    if bounds is not None:
        lo, hi = bounds
        if lo is not None:
            where_clauses.append("aggregate >= ?")
            sql_params.append(lo)
        if hi is not None:
            where_clauses.append("aggregate < ?")
            sql_params.append(hi)


def _apply_visibility_and_hide_filters(where_clauses, sql_params, params, user_id):
    """Apply visibility, top picks, aggregate minimum, and hide blinks/bursts/duplicates."""
    if user_id:
        vis_sql, vis_params = get_visibility_clause(user_id)
        where_clauses.append(vis_sql)
        sql_params.extend(vis_params)

    if params.get('min_aggregate'):
        try:
            where_clauses.append("aggregate >= ?")
            sql_params.append(float(params['min_aggregate']))
        except ValueError:
            pass

    if params.get('top_picks_filter') == '1':
        threshold = get_top_picks_threshold()
        top_picks_expr = get_top_picks_score_sql()
        where_clauses.append(f"({top_picks_expr}) >= ?")
        sql_params.append(threshold)

    hb = params.get('hide_blinks', '')
    hide_blinks_val = hb if hb in ('1', 'true') else params.get('no_blink', '')
    hbr = params.get('hide_bursts', '')
    hide_bursts_val = hbr if hbr in ('1', 'true') else params.get('burst_only', '')
    hide_duplicates_val = params.get('hide_duplicates', '')
    where_clauses.extend(build_hide_clauses(hide_blinks_val, hide_bursts_val, hide_duplicates_val))


def _apply_preference_filters(where_clauses, sql_params, params, user_id):
    """Apply star rating, favorites, and rejected filters."""
    pref_cols = get_preference_columns(user_id)
    if params.get('min_rating'):
        try:
            min_rating = int(params['min_rating'])
            if 1 <= min_rating <= 5:
                where_clauses.append(f"{pref_cols['star_rating']} >= ?")
                sql_params.append(min_rating)
        except ValueError:
            pass
    if params.get('favorites_only') == '1':
        where_clauses.append(f"{pref_cols['is_favorite']} = 1")
    if params.get('show_rejected') == '1':
        where_clauses.append(f"{pref_cols['is_rejected']} = 1")
    elif params.get('hide_rejected') in ('1', 'true'):
        where_clauses.append(f"({pref_cols['is_rejected']} = 0 OR {pref_cols['is_rejected']} IS NULL)")


# Single source of truth for numeric range filters: (column, min_key, max_key, is_float).
# Drives both the WHERE-clause builders below and the /filter_options/metric_ranges endpoint.
SCORE_RANGE_COLUMNS = [
    ("aggregate", "min_score", "max_score", True),
    ("aesthetic", "min_aesthetic", "max_aesthetic", True),
    ("quality_score", "min_quality_score", "max_quality_score", True),
    ("topiq_score", "min_topiq", "max_topiq", True),
    ("tech_sharpness", "min_sharpness", "max_sharpness", True),
    ("exposure_score", "min_exposure", "max_exposure", True),
    ("color_score", "min_color", "max_color", True),
    ("contrast_score", "min_contrast", "max_contrast", True),
    ("noise_sigma", "min_noise", "max_noise", True),
    ("mean_saturation", "min_saturation", "max_saturation", True),
    ("mean_luminance", "min_luminance", "max_luminance", True),
    ("histogram_spread", "min_histogram_spread", "max_histogram_spread", True),
    ("dynamic_range_stops", "min_dynamic_range", "max_dynamic_range", True),
    ("comp_score", "min_composition", "max_composition", True),
    ("power_point_score", "min_power_point", "max_power_point", True),
    ("leading_lines_score", "min_leading_lines", "max_leading_lines", True),
    ("isolation_bonus", "min_isolation", "max_isolation", True),
    ("face_count", "min_face_count", "max_face_count", False),
    ("face_quality", "min_face_quality", "max_face_quality", True),
    ("eye_sharpness", "min_eye_sharpness", "max_eye_sharpness", True),
    ("face_sharpness", "min_face_sharpness", "max_face_sharpness", True),
    ("face_ratio", "min_face_ratio", "max_face_ratio", True),
    ("face_confidence", "min_face_confidence", "max_face_confidence", True),
    ("star_rating", "min_star_rating", "max_star_rating", False),
    ("aesthetic_iaa", "min_aesthetic_iaa", "max_aesthetic_iaa", True),
    ("face_quality_iqa", "min_face_quality_iqa", "max_face_quality_iqa", True),
    ("liqe_score", "min_liqe", "max_liqe", True),
    ("qalign_score", "min_qalign", "max_qalign", True),
    ("aesthetic_v25", "min_aesthetic_v25", "max_aesthetic_v25", True),
    ("deqa_score", "min_deqa", "max_deqa", True),
    ("subject_sharpness", "min_subject_sharpness", "max_subject_sharpness", True),
    ("subject_prominence", "min_subject_prominence", "max_subject_prominence", True),
    ("subject_placement", "min_subject_placement", "max_subject_placement", True),
    ("bg_separation", "min_bg_separation", "max_bg_separation", True),
]

EXIF_RANGE_COLUMNS = [
    ("iso", "min_iso", "max_iso", False),
    ("f_stop", "min_aperture", "max_aperture", True),
    ("focal_length", "min_focal_length", "max_focal_length", True),
]


def _apply_score_range_filters(where_clauses, sql_params, params):
    """Apply all score/metric range filters."""
    for column, min_key, max_key, is_float in SCORE_RANGE_COLUMNS:
        _add_range_filter(where_clauses, sql_params, params, column, min_key, max_key, is_float=is_float)


def _apply_exif_range_filters(where_clauses, sql_params, params):
    """Apply ISO, aperture, and focal length range filters."""
    for column, min_key, max_key, is_float in EXIF_RANGE_COLUMNS:
        _add_range_filter(where_clauses, sql_params, params, column, min_key, max_key, is_float=is_float)


def _apply_date_album_geo_filters(where_clauses, sql_params, params):
    """Apply date range, album membership, GPS radius, and path prefix filters."""
    if params.get('date_from'):
        try:
            date_from = to_exif_date(params['date_from'])
            where_clauses.append("date_taken >= ?")
            sql_params.append(date_from)
        except (ValueError, AttributeError):
            pass
    if params.get('date_to'):
        try:
            date_to = to_exif_date(params['date_to']) + " 23:59:59"
            where_clauses.append("date_taken <= ?")
            sql_params.append(date_to)
        except (ValueError, AttributeError):
            pass

    if params.get('album_id'):
        try:
            album_id = int(params['album_id'])
            where_clauses.append(
                "photos.path IN (SELECT photo_path FROM album_photos WHERE album_id = ?)"
            )
            sql_params.append(album_id)
        except ValueError:
            pass

    if params.get('gps_lat') and params.get('gps_lng') and params.get('gps_radius_km'):
        try:
            lat = float(params['gps_lat'])
            lng = float(params['gps_lng'])
            radius_km = float(params['gps_radius_km'])
            lat_delta = radius_km / 111.0
            lng_delta = radius_km / (111.0 * max(abs(math.cos(math.radians(lat))), 0.01))
            where_clauses.append("gps_latitude BETWEEN ? AND ?")
            sql_params.extend([lat - lat_delta, lat + lat_delta])
            where_clauses.append("gps_longitude BETWEEN ? AND ?")
            sql_params.extend([lng - lng_delta, lng + lng_delta])
        except (ValueError, TypeError):
            pass

    if params.get('path_prefix'):
        norm_prefix = params['path_prefix'].replace('\\', '/').rstrip('/') + '/'
        escaped = norm_prefix.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        where_clauses.append("REPLACE(photos.path, '\\', '/') LIKE ? ESCAPE '\\'")
        sql_params.append(escaped + '%')


def _build_gallery_where(params, conn=None, user_id=None):
    """Build WHERE clauses for gallery queries."""
    where_clauses = []
    sql_params = []
    _apply_visibility_and_hide_filters(where_clauses, sql_params, params, user_id)
    _apply_text_filters(where_clauses, sql_params, params, conn)
    _apply_preference_filters(where_clauses, sql_params, params, user_id)
    _apply_score_range_filters(where_clauses, sql_params, params)
    _apply_exif_range_filters(where_clauses, sql_params, params)
    _apply_color_quality_filters(where_clauses, sql_params, params)
    _apply_date_album_geo_filters(where_clauses, sql_params, params)
    return where_clauses, sql_params


@router.get("/api/photo")
async def api_photo(
    path: str = Query(...),
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Get a single photo by path (same shape as gallery items). Async."""
    try:
        async with get_async_db() as conn:
            user_id = user.user_id if user else None
            from_clause, from_params = get_photos_from_clause(user_id)
            vis_sql, vis_params = get_visibility_clause(user_id)

            select_cols = build_photo_select_columns(conn=None, user_id=user_id)

            query = f"SELECT {', '.join(select_cols)} FROM {from_clause} WHERE photos.path = ? AND {vis_sql}"
            cur = await conn.execute(query, from_params + [path] + vis_params)
            row = await cur.fetchone()
            await cur.close()
            if not row:
                raise HTTPException(status_code=404, detail="Photo not found")

            photos = split_photo_tags([row], VIEWER_CONFIG['display']['tags_per_photo'])
            photo = photos[0]
            photo['date_formatted'] = format_date(photo.get('date_taken'))
            await attach_person_data_async([photo], conn)

            sanitize_float_values([photo])

            return photo
    except HTTPException:
        raise
    except sqlite3.Error:
        logger.exception("Failed to fetch photo details")
        raise HTTPException(status_code=500, detail='Internal server error')


@router.get("/api/type_counts")
def api_type_counts(
    hide_blinks: str = Query('0'),
    hide_bursts: str = Query('0'),
    hide_duplicates: str = Query('0'),
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Get photo type counts for sidebar."""
    user_id = user.user_id if user else None
    types = get_photo_types(
        hide_blinks in ('1', 'true'), hide_bursts in ('1', 'true'), hide_duplicates in ('1', 'true'),
        user_id=user_id
    )
    return {'types': types}


@router.get("/api/photos")
async def api_photos(
    request: Request,
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Gallery photo listing with filtering, sorting, and pagination (async).

    Migrated to aiosqlite. _build_gallery_where() still accepts a Connection
    because its internal helpers (is_photo_tags_available, get_existing_columns)
    are cache-warmed at lifespan startup and never touch conn after the first
    hit. get_cached_count_async / attach_person_data_async cover the awaited
    DB paths.
    """
    qp = dict(request.query_params)
    defaults_cfg = VIEWER_CONFIG['defaults']
    default_per_page = VIEWER_CONFIG['pagination']['default_per_page']

    # Normalize semantic params (quality→min_score, type→filter overrides)
    normalized = normalize_params(qp)

    # Merge query params with normalized values and defaults
    default_type = defaults_cfg.get('type', '')
    merged = {
        **qp,
        **{k: v for k, v in normalized.items() if v},
        'sort': normalized.get('sort') or qp.get('sort', defaults_cfg['sort']),
        'dir': qp.get('sort_direction') or qp.get('dir', defaults_cfg['sort_direction']),
        'person': qp.get('person') or qp.get('person_id', ''),
        'type': qp.get('type', '' if (qp.get('person') or qp.get('person_id')) else default_type),
        'per_page': qp.get('per_page', str(default_per_page)),
    }

    try:
        gallery_params = GalleryParams.model_validate(merged)
    except ValidationError as e:
        # Log the structured detail server-side; return a clean message rather
        # than leaking Pydantic internals (loc/type/ctx/url) to the client.
        logger.warning("Gallery parameter validation failed: %s", e.errors())
        raise HTTPException(status_code=422, detail="Invalid gallery parameters") from e
    page = max(1, gallery_params.page)
    per_page = gallery_params.per_page
    params = gallery_params.model_dump()

    if params.get('type') in TYPE_FILTERS:
        for key, value in TYPE_FILTERS[params['type']].items():
            if not params.get(key):
                params[key] = value

    sort_col = params['sort'] if params['sort'] in VALID_SORT_COLS else 'aggregate'
    sort_dir = 'ASC' if params['dir'] == 'ASC' else 'DESC'
    if sort_col == 'learned_score':
        # Personal-ranker sort: untrained photos (NULL learned_score) always sink,
        # regardless of direction, so the gallery degrades gracefully to a stable
        # path order on an untrained DB.
        order_by_clause = f"(learned_score IS NULL) ASC, learned_score {sort_dir}, path ASC"
    else:
        order_by_clause = f"{sort_col} {sort_dir}, path ASC"

    try:
        async with get_async_db() as conn:
            user_id = user.user_id if user else None
            from_clause, from_params = get_photos_from_clause(user_id)
            where_clauses, sql_params = _build_gallery_where(params, conn, user_id=user_id)
            all_params = from_params + sql_params
            where_str = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

            total_count = await get_cached_count_async(conn, where_str, all_params, from_clause=from_clause)
            total_pages, offset = paginate(total_count, page, per_page)

            any_hide_active = any(
                params.get(k) in ('1', 'true')
                for k in ('hide_blinks', 'hide_bursts', 'hide_duplicates', 'no_blink', 'burst_only')
            )
            if any_hide_active:
                params_no_hide = dict(params)
                for k in ('hide_blinks', 'hide_bursts', 'hide_duplicates', 'no_blink', 'burst_only'):
                    params_no_hide[k] = ''
                where_no_hide, params_no_hide_sql = _build_gallery_where(
                    params_no_hide, conn, user_id=user_id,
                )
                all_params_no_hide = from_params + params_no_hide_sql
                where_str_no_hide = (
                    f" WHERE {' AND '.join(where_no_hide)}" if where_no_hide else ""
                )
                cur = await conn.execute(
                    "SELECT "
                    "COUNT(*) AS unhidden, "
                    "SUM(CASE WHEN is_blink = 1 THEN 1 ELSE 0 END) AS blinks, "
                    "SUM(CASE WHEN is_burst_lead = 0 THEN 1 ELSE 0 END) AS bursts, "
                    "SUM(CASE WHEN is_duplicate_lead = 0 AND duplicate_group_id IS NOT NULL "
                    "THEN 1 ELSE 0 END) AS duplicates "
                    f"FROM {from_clause}{where_str_no_hide}",
                    all_params_no_hide,
                )
                row = await cur.fetchone()
                await cur.close()
                unhidden_total = row['unhidden'] if row else total_count
                hidden_summary = {
                    'total': max(0, unhidden_total - total_count),
                    'blinks': int(row['blinks'] or 0) if row else 0,
                    'bursts': int(row['bursts'] or 0) if row else 0,
                    'duplicates': int(row['duplicates'] or 0) if row else 0,
                }
            else:
                hidden_summary = {'total': 0, 'blinks': 0, 'bursts': 0, 'duplicates': 0}

            # cache hit, no PRAGMA — same select-cols logic as other endpoints
            select_cols = build_photo_select_columns(conn=None, user_id=user_id)

            needs_top_picks_score = (
                params.get('top_picks_filter') == '1' or
                'top_picks_score' in order_by_clause
            )
            if needs_top_picks_score:
                top_picks_expr = get_top_picks_score_sql()
                select_cols.append(f"({top_picks_expr}) as top_picks_score")

            if sort_col == 'learned_score':
                # Opt-in alternate sort from the personal ranker. Correlated
                # subquery (not a JOIN) avoids ambiguity with photos.category /
                # photos.user_id; scoped to the global pooled ranker (category
                # NULL, user_id NULL). NULL when untrained -> sorts last.
                select_cols.append(
                    "(SELECT ls.learned_score FROM learned_scores ls "
                    "WHERE ls.photo_path = photos.path AND ls.user_id IS NULL "
                    "AND ls.category IS NULL) AS learned_score"
                )

            if total_count:
                query = f"SELECT {', '.join(select_cols)} FROM {from_clause}{where_str} ORDER BY {order_by_clause} LIMIT ? OFFSET ?"
                cur = await conn.execute(query, all_params + [per_page, offset])
                rows = await cur.fetchall()
                await cur.close()
            else:
                rows = []

            tags_limit = VIEWER_CONFIG['display']['tags_per_photo']
            photos = split_photo_tags(rows, tags_limit)

            for photo in photos:
                photo['date_formatted'] = format_date(photo.get('date_taken'))

            await attach_person_data_async(photos, conn)

    except sqlite3.Error:
        logger.exception("Failed to fetch gallery photos")
        raise HTTPException(status_code=500, detail='Internal server error')

    sanitize_float_values(photos)

    return {
        'photos': photos,
        'page': page,
        'total': total_count,
        'per_page': per_page,
        'total_pages': total_pages,
        'has_more': page < total_pages,
        'sort_col': sort_col,
        'hidden_summary': hidden_summary,
    }


async def _enrich_similar_with_full_rows_async(page_results, conn, user_id):
    """Async variant: replace basic similar-photo dicts with full photo rows, preserving similarity order."""
    if not page_results:
        return page_results
    sim_map = {r['path']: r['similarity'] for r in page_results}
    paths = [r['path'] for r in page_results]
    select_cols = build_photo_select_columns(conn=None, user_id=user_id)
    placeholders = ','.join(['?'] * len(paths))
    vis_sql, vis_params = get_visibility_clause(user_id)
    cur = await conn.execute(
        f"SELECT {', '.join(select_cols)} FROM photos WHERE path IN ({placeholders}) AND {vis_sql}",
        paths + vis_params,
    )
    rows = await cur.fetchall()
    await cur.close()
    photos = split_photo_tags(rows, VIEWER_CONFIG['display']['tags_per_photo'])
    await attach_person_data_async(photos, conn)
    sanitize_float_values(photos)
    path_to_photo = {p['path']: p for p in photos}
    ordered = []
    for path in paths:
        if path in path_to_photo:
            p = path_to_photo[path]
            p['similarity'] = sim_map[path]
            ordered.append(p)
    return ordered


def _similar_result(row, similarity):
    """Build a standard similar-photo result dict."""
    return {
        'path': row['path'],
        'filename': row['filename'],
        'similarity': round(similarity, 4),
        'aggregate': row.get('aggregate'),
        'aesthetic': row.get('aesthetic'),
        'date_taken': row.get('date_taken'),
    }


def _vec_knn_similar(conn, source_embedding, photo_path, min_similarity, vis_sql, vis_params):
    """CLIP-only similar search via sqlite-vec vec0 KNN (sync, runs inside to_thread).

    Replaces the brute-force full-table NumPy cosine scan in the no-pHash-candidate
    branch of ``_find_similar_visual`` with an indexed vec0 KNN against ``photos_vec``.
    ``distance_metric=cosine`` makes ``1 - distance`` the cosine similarity, matching
    the NumPy dot product of L2-normalized embeddings — so top-K ordering is identical.

    Returns the result list (``[:500]``) on success, or ``None`` to signal the caller
    to fall back to the NumPy scan (sqlite-vec unavailable, ``photos_vec`` missing/empty,
    or no source embedding). An empty match set returns ``[]`` (a valid result), not
    ``None`` — that is a successful query that found nothing.
    """
    import numpy as np
    from db.connection import HAS_SQLITE_VEC

    if not HAS_SQLITE_VEC or source_embedding is None:
        return None

    # Availability guard (plan Topic 2 step 2): photos_vec may be absent or empty.
    # Catch OperationalError (table missing / extension not loaded) → NumPy fallback.
    try:
        if conn.execute("SELECT 1 FROM photos_vec LIMIT 1").fetchone() is None:
            return None
    except sqlite3.OperationalError:
        return None

    # vec0 MATCH cannot carry a WHERE clause, so over-fetch (k large) then post-filter
    # by visibility/self. k≥2000 keeps the top-500 most-similar even after filtering.
    k = 2000
    query_bytes = np.asarray(source_embedding, dtype=np.float32).tobytes()
    try:
        knn_rows = conn.execute(
            "SELECT path, distance FROM photos_vec WHERE embedding MATCH ? AND k = ?",
            [query_bytes, k],
        ).fetchall()
    except sqlite3.OperationalError:
        return None

    if not knn_rows:
        return []

    dist_by_path = {}
    ordered_paths = []
    for r in knn_rows:
        p = r['path']
        if p == photo_path or p in dist_by_path:
            continue
        dist_by_path[p] = r['distance']
        ordered_paths.append(p)

    if not ordered_paths:
        return []

    # Fetch display columns + apply visibility in one pass, chunked to stay under
    # SQLite's variable limit on older builds.
    meta_by_path = {}
    for start in range(0, len(ordered_paths), 500):
        chunk = ordered_paths[start:start + 500]
        placeholders = ','.join('?' * len(chunk))
        meta_rows = conn.execute(
            f"""SELECT path, filename, date_taken, aggregate, aesthetic
                FROM photos WHERE path IN ({placeholders}) AND {vis_sql}""",
            chunk + vis_params,
        ).fetchall()
        for mr in meta_rows:
            meta_by_path[mr['path']] = dict(mr)

    results = []
    for p in ordered_paths:
        row = meta_by_path.get(p)
        if row is None:
            continue
        sim = max(0.0, 1.0 - dist_by_path[p])
        if sim >= min_similarity:
            results.append(_similar_result(row, sim))

    results.sort(key=lambda x: x['similarity'], reverse=True)
    return results[:500]


def _find_similar_visual(conn, source, photo_path, min_similarity, vis_sql, vis_params):
    """Find visually similar photos using pHash hamming distance (primary) + CLIP cosine (secondary)."""
    import numpy as np
    from utils.duplicate import _POPCOUNT_TABLE
    from utils.embedding import bytes_to_normalized_embedding
    PHASH_W = 0.7
    CLIP_W = 0.3

    source_phash = np.uint64(int(source['phash'], 16)) if source.get('phash') else None

    source_embedding = bytes_to_normalized_embedding(source.get('clip_embedding'))

    if source_phash is None and source_embedding is None:
        return [], None

    rows = conn.execute(f"""
        SELECT path, filename, phash, date_taken, aggregate, aesthetic
        FROM photos
        WHERE path != ? AND phash IS NOT NULL AND {vis_sql}
    """, [photo_path] + vis_params).fetchall()
    rows = [dict(r) for r in rows]

    if not rows:
        # CLIP-only fallback (no pHash candidates). Prefer the indexed vec0 KNN
        # path; _vec_knn_similar returns None when sqlite-vec is unavailable, in
        # which case we keep the original brute-force NumPy scan below unchanged.
        vec_results = _vec_knn_similar(conn, source_embedding, photo_path, min_similarity, vis_sql, vis_params)
        if vec_results is not None:
            return vec_results, None
        clip_rows = conn.execute(f"""
            SELECT path, filename, clip_embedding, date_taken, aggregate, aesthetic
            FROM photos
            WHERE path != ? AND clip_embedding IS NOT NULL AND {vis_sql}
            LIMIT 5000
        """, [photo_path] + vis_params).fetchall()
        rows = [dict(r) for r in clip_rows]
        if not rows or source_embedding is None:
            return [], None
        results = []
        for r in rows:
            e = bytes_to_normalized_embedding(r['clip_embedding'])
            if e is None:
                continue
            sim = max(0.0, float(np.dot(source_embedding, e)))
            if sim >= min_similarity:
                results.append(_similar_result(r, sim))
        results.sort(key=lambda x: x['similarity'], reverse=True)
        return results[:500], None

    hashes = np.array([int(r['phash'], 16) for r in rows], dtype=np.uint64)
    xor = np.bitwise_xor(hashes, source_phash)
    hamming = np.zeros(len(rows), dtype=np.int32)
    for byte_idx in range(8):
        shift = np.uint64(byte_idx * 8)
        byte_vals = ((xor >> shift) & np.uint64(0xFF)).astype(np.int32)
        hamming += _POPCOUNT_TABLE[byte_vals]
    phash_sims = 1.0 - hamming / 64.0

    if source_embedding is not None:
        phash_floor = max(0.0, (min_similarity - CLIP_W) / PHASH_W)
    else:
        phash_floor = min_similarity
    candidate_indices = np.where(phash_sims >= phash_floor)[0]

    clip_by_path: dict = {}
    if source_embedding is not None and len(candidate_indices) > 0:
        cand_paths = [rows[i]['path'] for i in candidate_indices]
        for start in range(0, len(cand_paths), 500):
            chunk = cand_paths[start:start + 500]
            placeholders = ','.join('?' * len(chunk))
            clip_rows = conn.execute(
                f"SELECT path, clip_embedding FROM photos "
                f"WHERE path IN ({placeholders}) AND clip_embedding IS NOT NULL",
                chunk,
            ).fetchall()
            for cr in clip_rows:
                e = bytes_to_normalized_embedding(cr['clip_embedding'])
                if e is not None:
                    clip_by_path[cr['path']] = e

    results = []
    for i in candidate_indices:
        row = rows[i]
        phash_sim = float(phash_sims[i])
        cand_clip = clip_by_path.get(row['path'])
        if source_embedding is not None and cand_clip is not None:
            clip_sim = max(0.0, float(np.dot(source_embedding, cand_clip)))
            sim = phash_sim * PHASH_W + clip_sim * CLIP_W
        else:
            sim = phash_sim * PHASH_W
        if sim >= min_similarity:
            results.append(_similar_result(row, sim))

    results.sort(key=lambda x: x['similarity'], reverse=True)
    return results[:500], None


def _find_similar_color(conn, source, photo_path, min_similarity, vis_sql, vis_params):
    """Find photos with similar color palette using histogram intersection + saturation/luminance."""
    import numpy as np

    src_hist_blob = source.get('histogram_data')
    if not src_hist_blob:
        return [], 'no_histogram'

    src_mono = source.get('is_monochrome', 0)
    src_sat = source.get('mean_saturation', 0) or 0
    src_lum = source.get('mean_luminance', 0) or 0

    # Decode source histogram (256 float32 = 1024 bytes)
    src_hist = np.frombuffer(src_hist_blob, dtype=np.float32).copy()
    src_norm = src_hist.sum()
    if src_norm > 0:
        src_hist = src_hist / src_norm

    # Pre-filter: match monochrome flag, limit saturation distance
    rows = conn.execute(f"""
        SELECT path, filename, histogram_data, mean_saturation, mean_luminance,
               is_monochrome, date_taken, aggregate, aesthetic
        FROM photos
        WHERE path != ? AND histogram_data IS NOT NULL
              AND is_monochrome = ?
              AND ABS(COALESCE(mean_saturation, 0) - ?) <= 3.0
              AND {vis_sql}
    """, [photo_path, src_mono, src_sat] + vis_params).fetchall()

    results = []
    for r in rows:
        r = dict(r)
        cand_hist = np.frombuffer(r['histogram_data'], dtype=np.float32).copy()
        cand_norm = cand_hist.sum()
        if cand_norm > 0:
            cand_hist = cand_hist / cand_norm

        # Histogram intersection (0..1)
        hist_sim = float(np.minimum(src_hist, cand_hist).sum())

        # Saturation distance (0..1, inverted)
        cand_sat = r.get('mean_saturation', 0) or 0
        sat_sim = max(0.0, 1.0 - abs(src_sat - cand_sat) / 10.0)

        # Luminance distance (0..1, inverted)
        cand_lum = r.get('mean_luminance', 0) or 0
        lum_sim = max(0.0, 1.0 - abs(src_lum - cand_lum) / 10.0)

        # Monochrome bonus
        mono_bonus = 1.0 if (src_mono and r.get('is_monochrome')) else 0.0

        sim = hist_sim * 0.7 + sat_sim * 0.1 + lum_sim * 0.1 + mono_bonus * 0.1
        if sim >= min_similarity:
            results.append(_similar_result(r, sim))

    results.sort(key=lambda x: x['similarity'], reverse=True)
    return results[:500], None


def _find_similar_person(conn, source, photo_path, min_similarity, vis_sql, vis_params, user_id=None):
    """Find photos containing the same person(s) via person_id or face embedding cosine."""
    import numpy as np
    from utils.embedding import bytes_to_normalized_embedding

    # Get faces for source photo
    faces = conn.execute(
        "SELECT id, person_id, embedding FROM faces WHERE photo_path = ?",
        [photo_path],
    ).fetchall()

    if not faces:
        return [], 'no_faces'

    # Build visibility clause with 'p' alias for JOIN queries
    p_vis_sql, p_vis_params = get_visibility_clause(user_id, table_alias='p')

    person_ids = [f['person_id'] for f in faces if f['person_id']]

    if person_ids:
        # Fast path: find all photos sharing these person_ids
        placeholders = ','.join('?' * len(person_ids))
        rows = conn.execute(f"""
            SELECT DISTINCT f.photo_path as path, p.filename, p.date_taken, p.aggregate, p.aesthetic
            FROM faces f
            JOIN photos p ON p.path = f.photo_path
            WHERE f.person_id IN ({placeholders})
              AND f.photo_path != ?
              AND {p_vis_sql}
        """, person_ids + [photo_path] + p_vis_params).fetchall()

        results = [_similar_result(dict(r), 1.0) for r in rows]
        results.sort(key=lambda x: x.get('date_taken') or '', reverse=True)
        return results[:500], None

    # Slow path: cosine similarity on face embeddings
    src_embeddings = []
    for f in faces:
        e = bytes_to_normalized_embedding(f['embedding'])
        if e is not None:
            src_embeddings.append(e)

    if not src_embeddings:
        return [], 'no_faces'

    all_faces = conn.execute(f"""
        SELECT f.photo_path as path, f.embedding, p.filename, p.date_taken, p.aggregate, p.aesthetic
        FROM faces f
        JOIN photos p ON p.path = f.photo_path
        WHERE f.photo_path != ? AND f.embedding IS NOT NULL AND {p_vis_sql}
        LIMIT 50000
    """, [photo_path] + p_vis_params).fetchall()

    # Group best similarity per photo
    photo_sims: dict = {}
    for r in all_faces:
        r = dict(r)
        cand_emb = bytes_to_normalized_embedding(r['embedding'])
        if cand_emb is None:
            continue
        best = max(float(np.dot(src_e, cand_emb)) for src_e in src_embeddings)
        best = max(0.0, best)
        path = r['path']
        if path not in photo_sims or best > photo_sims[path]['similarity']:
            photo_sims[path] = _similar_result(r, best)

    results = [v for v in photo_sims.values() if v['similarity'] >= min_similarity]
    results.sort(key=lambda x: x['similarity'], reverse=True)
    return results[:500], None


# Mode-specific default min_similarity values
_MODE_DEFAULT_MIN_SIM = {
    'visual': 0.40,
    'color': 0.40,
    'person': 0.0,
}


@router.get("/api/similar_photos/{photo_path:path}")
async def api_similar_photos(
    photo_path: str,
    mode: str = Query("visual"),
    limit: int = Query(20),
    offset: int = Query(0),
    min_similarity: Optional[float] = Query(None),
    full: int = Query(0),
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Find similar photos using different similarity modes (async).

    Modes:
      - visual: pHash hamming distance (70%) + CLIP cosine (30%)
      - color: histogram intersection + saturation/luminance distance
      - person: same person_id or face embedding cosine similarity

    The heavy numpy + DB scan inside _find_similar_* runs in a worker thread via
    asyncio.to_thread, keeping the event loop free.  Source loading and result
    enrichment run on the async connection.
    """
    if not VIEWER_CONFIG.get('features', {}).get('show_similar_button', True):
        raise HTTPException(status_code=503, detail='Similar photos feature is disabled')

    if mode not in _MODE_DEFAULT_MIN_SIM:
        mode = 'visual'

    effective_min_sim = min_similarity if min_similarity is not None else _MODE_DEFAULT_MIN_SIM[mode]
    user_id = user.user_id if user else None
    vis_sql, vis_params = get_visibility_clause(user_id)

    try:
        async with get_async_db() as conn:
            cur = await conn.execute(f"""
                SELECT path, phash, clip_embedding, histogram_data, mean_saturation,
                       mean_luminance, is_monochrome,
                       aggregate, aesthetic, date_taken
                FROM photos WHERE path = ? AND {vis_sql}
            """, [photo_path] + vis_params)
            source_row = await cur.fetchone()
            await cur.close()

            if not source_row:
                raise HTTPException(status_code=404, detail='Photo not found')
            source = dict(source_row)

            def _run_similarity():
                with get_db() as sync_conn:
                    if mode == 'visual':
                        return _find_similar_visual(sync_conn, source, photo_path, effective_min_sim, vis_sql, vis_params)
                    if mode == 'color':
                        return _find_similar_color(sync_conn, source, photo_path, effective_min_sim, vis_sql, vis_params)
                    if mode == 'person':
                        return _find_similar_person(sync_conn, source, photo_path, effective_min_sim, vis_sql, vis_params, user_id=user_id)
                    return [], None

            results, message = await asyncio.to_thread(_run_similarity)

            total_count = len(results)
            page_results = results[offset:offset + limit]

            if full:
                page_results = await _enrich_similar_with_full_rows_async(page_results, conn, user_id)

            response = {
                'source': photo_path,
                'mode': mode,
                'similar': page_results,
                'total': total_count,
                'has_more': (offset + limit) < total_count,
            }
            if message:
                response['message'] = message
            return response

    except HTTPException:
        raise
    except sqlite3.Error:
        logger.exception("Failed to find similar photos")
        raise HTTPException(status_code=500, detail='Internal server error')


@router.get("/api/config")
def api_config(user: Optional[CurrentUser] = Depends(get_optional_user)):
    """Get viewer configuration for Angular client initialization."""
    from api.config import is_multi_user_enabled
    from api.auth import is_edition_enabled, is_edition_authenticated
    from api.types import SORT_OPTIONS, SORT_OPTIONS_GROUPED, QUALITY_LEVELS, TYPE_LABELS

    features = dict(VIEWER_CONFIG.get('features', {}))
    with get_db() as conn:
        has_embeddings = conn.execute(
            "SELECT 1 FROM photos WHERE clip_embedding IS NOT NULL LIMIT 1"
        ).fetchone() is not None
        if not has_embeddings:
            features['show_similar_button'] = False
            features['show_semantic_search'] = False
        else:
            features.setdefault('show_semantic_search', True)
        features.setdefault('show_albums', True)
        features.setdefault('show_critique', True)
        features.setdefault('show_vlm_critique', False)
        features.setdefault('show_folders', True)

        # Check if albums table exists
        try:
            conn.execute("SELECT 1 FROM albums LIMIT 0")
        except sqlite3.OperationalError:
            features['show_albums'] = False

    return {
        'sort_options': SORT_OPTIONS,
        'sort_options_grouped': SORT_OPTIONS_GROUPED,
        'quality_levels': QUALITY_LEVELS,
        'type_labels': TYPE_LABELS,
        'defaults': VIEWER_CONFIG['defaults'],
        'pagination': VIEWER_CONFIG['pagination'],
        'display': VIEWER_CONFIG['display'],
        'features': features,
        'quality_thresholds': VIEWER_CONFIG['quality_thresholds'],
        'notification_duration_ms': VIEWER_CONFIG.get('notification_duration_ms', 2000),
        'translation_target_language': _FULL_CONFIG.get('translation', {}).get('target_language', ''),
        'is_multi_user': is_multi_user_enabled(),
        'edition_enabled': is_edition_enabled(),
        'edition_authenticated': is_edition_authenticated(user),
    }
