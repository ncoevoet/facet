"""
Gallery router — photo listing, type counts, similar photos.

"""

import logging
import math
import sqlite3
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from api.auth import CurrentUser, get_optional_user
from api.config import VIEWER_CONFIG, _FULL_CONFIG
from api.database import get_db_connection
from api.models.gallery import GalleryParams
from api.db_helpers import (
    get_existing_columns, get_cached_count, _add_tag_filter,
    get_art_tags_from_config, build_hide_clauses,
    PHOTO_BASE_COLS, PHOTO_OPTIONAL_COLS,
    split_photo_tags, attach_person_data, sanitize_float_values,
    get_visibility_clause, get_photos_from_clause, get_preference_columns,
    build_photo_select_columns,
    format_date, to_exif_date,
)
from api.top_picks import get_top_picks_score_sql, get_top_picks_threshold
from api.types import (
    VALID_SORT_COLS, TYPE_FILTERS, normalize_params, get_photo_types
)

router = APIRouter(tags=["gallery"])
logger = logging.getLogger(__name__)



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
        term = params['search']
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
            search_clauses.append("EXISTS (SELECT 1 FROM photo_tags WHERE photo_path = photos.path AND tag LIKE ? ESCAPE '\\')")
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

        search_clauses.append("EXISTS (SELECT 1 FROM faces f JOIN persons p ON f.person_id = p.id WHERE f.photo_path = photos.path AND p.name LIKE ? ESCAPE '\\')")
        search_params.append(f"%{escaped_term}%")

        where_clauses.append(f"({' OR '.join(search_clauses)})")
        sql_params.extend(search_params)

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


def _apply_score_range_filters(where_clauses, sql_params, params):
    """Apply all score/metric range filters."""
    rf = _add_range_filter
    rf(where_clauses, sql_params, params, "aggregate", "min_score", "max_score")
    rf(where_clauses, sql_params, params, "aesthetic", "min_aesthetic", "max_aesthetic")
    rf(where_clauses, sql_params, params, "quality_score", "min_quality_score", "max_quality_score")
    rf(where_clauses, sql_params, params, "topiq_score", "min_topiq", "max_topiq")
    rf(where_clauses, sql_params, params, "tech_sharpness", "min_sharpness", "max_sharpness")
    rf(where_clauses, sql_params, params, "exposure_score", "min_exposure", "max_exposure")
    rf(where_clauses, sql_params, params, "color_score", "min_color", "max_color")
    rf(where_clauses, sql_params, params, "contrast_score", "min_contrast", "max_contrast")
    rf(where_clauses, sql_params, params, "noise_sigma", "min_noise", "max_noise")
    rf(where_clauses, sql_params, params, "mean_saturation", "min_saturation", "max_saturation")
    rf(where_clauses, sql_params, params, "mean_luminance", "min_luminance", "max_luminance")
    rf(where_clauses, sql_params, params, "histogram_spread", "min_histogram_spread", "max_histogram_spread")
    rf(where_clauses, sql_params, params, "dynamic_range_stops", "min_dynamic_range", "max_dynamic_range")
    rf(where_clauses, sql_params, params, "comp_score", "min_composition", "max_composition")
    rf(where_clauses, sql_params, params, "power_point_score", "min_power_point", "max_power_point")
    rf(where_clauses, sql_params, params, "leading_lines_score", "min_leading_lines", "max_leading_lines")
    rf(where_clauses, sql_params, params, "isolation_bonus", "min_isolation", "max_isolation")
    rf(where_clauses, sql_params, params, "face_count", "min_face_count", "max_face_count", is_float=False)
    rf(where_clauses, sql_params, params, "face_quality", "min_face_quality", "max_face_quality")
    rf(where_clauses, sql_params, params, "eye_sharpness", "min_eye_sharpness", "max_eye_sharpness")
    rf(where_clauses, sql_params, params, "face_sharpness", "min_face_sharpness", "max_face_sharpness")
    rf(where_clauses, sql_params, params, "face_ratio", "min_face_ratio", "max_face_ratio")
    rf(where_clauses, sql_params, params, "face_confidence", "min_face_confidence", "max_face_confidence")
    rf(where_clauses, sql_params, params, "star_rating", "min_star_rating", "max_star_rating", is_float=False)
    rf(where_clauses, sql_params, params, "aesthetic_iaa", "min_aesthetic_iaa", "max_aesthetic_iaa")
    rf(where_clauses, sql_params, params, "face_quality_iqa", "min_face_quality_iqa", "max_face_quality_iqa")
    rf(where_clauses, sql_params, params, "liqe_score", "min_liqe", "max_liqe")
    rf(where_clauses, sql_params, params, "subject_sharpness", "min_subject_sharpness", "max_subject_sharpness")
    rf(where_clauses, sql_params, params, "subject_prominence", "min_subject_prominence", "max_subject_prominence")
    rf(where_clauses, sql_params, params, "subject_placement", "min_subject_placement", "max_subject_placement")
    rf(where_clauses, sql_params, params, "bg_separation", "min_bg_separation", "max_bg_separation")


def _apply_exif_range_filters(where_clauses, sql_params, params):
    """Apply ISO, aperture, and focal length range filters."""
    rf = _add_range_filter
    rf(where_clauses, sql_params, params, "iso", "min_iso", "max_iso", is_float=False)
    rf(where_clauses, sql_params, params, "f_stop", "min_aperture", "max_aperture")
    rf(where_clauses, sql_params, params, "focal_length", "min_focal_length", "max_focal_length")


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
    _apply_date_album_geo_filters(where_clauses, sql_params, params)
    return where_clauses, sql_params


@router.get("/api/photo")
def api_photo(
    path: str = Query(...),
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Get a single photo by path (same shape as gallery items)."""
    conn = get_db_connection()
    try:
        user_id = user.user_id if user else None
        from_clause, from_params = get_photos_from_clause(user_id)
        vis_sql, vis_params = get_visibility_clause(user_id)

        select_cols = build_photo_select_columns(conn, user_id)

        query = f"SELECT {', '.join(select_cols)} FROM {from_clause} WHERE photos.path = ? AND {vis_sql}"
        row = conn.execute(query, from_params + [path] + vis_params).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Photo not found")

        photos = split_photo_tags([row], VIEWER_CONFIG['display']['tags_per_photo'])
        photo = photos[0]
        photo['date_formatted'] = format_date(photo.get('date_taken'))
        attach_person_data([photo], conn)

        sanitize_float_values([photo])

        return photo
    except HTTPException:
        raise
    except sqlite3.Error:
        logger.exception("Failed to fetch photo details")
        raise HTTPException(status_code=500, detail='Internal server error')
    finally:
        conn.close()


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
def api_photos(
    request: Request,
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Gallery photo listing with filtering, sorting, and pagination."""
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

    gallery_params = GalleryParams.model_validate(merged)
    page = max(1, gallery_params.page)
    per_page = gallery_params.per_page
    params = gallery_params.model_dump()

    if params.get('type') in TYPE_FILTERS:
        for key, value in TYPE_FILTERS[params['type']].items():
            if not params.get(key):
                params[key] = value

    sort_col = params['sort'] if params['sort'] in VALID_SORT_COLS else 'aggregate'
    sort_dir = 'ASC' if params['dir'] == 'ASC' else 'DESC'
    order_by_clause = f"{sort_col} {sort_dir}, path ASC"

    conn = get_db_connection()
    try:
        user_id = user.user_id if user else None
        from_clause, from_params = get_photos_from_clause(user_id)
        where_clauses, sql_params = _build_gallery_where(params, conn, user_id=user_id)
        all_params = from_params + sql_params
        where_str = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        total_count = get_cached_count(conn, where_str, all_params, from_clause=from_clause)
        total_pages = max(1, math.ceil(total_count / per_page))
        offset = (page - 1) * per_page

        existing_cols = get_existing_columns(conn)
        pref_cols = get_preference_columns(user_id)
        pref_col_names = {'star_rating', 'is_favorite', 'is_rejected'}
        select_cols = list(PHOTO_BASE_COLS)
        for c in PHOTO_OPTIONAL_COLS:
            if c in existing_cols:
                if c in pref_col_names:
                    select_cols.append(f"{pref_cols[c]} as {c}")
                else:
                    select_cols.append(c)

        needs_top_picks_score = (
            params.get('top_picks_filter') == '1' or
            'top_picks_score' in order_by_clause
        )
        if needs_top_picks_score:
            top_picks_expr = get_top_picks_score_sql()
            select_cols.append(f"({top_picks_expr}) as top_picks_score")

        query = f"SELECT {', '.join(select_cols)} FROM {from_clause}{where_str} ORDER BY {order_by_clause} LIMIT ? OFFSET ?"
        rows = conn.execute(query, all_params + [per_page, offset]).fetchall()

        tags_limit = VIEWER_CONFIG['display']['tags_per_photo']
        photos = split_photo_tags(rows, tags_limit)

        for photo in photos:
            photo['date_formatted'] = format_date(photo.get('date_taken'))

        attach_person_data(photos, conn)

    except sqlite3.Error:
        logger.exception("Failed to fetch gallery photos")
        raise HTTPException(status_code=500, detail='Internal server error')
    finally:
        conn.close()

    sanitize_float_values(photos)

    return {
        'photos': photos,
        'page': page,
        'total': total_count,
        'per_page': per_page,
        'total_pages': total_pages,
        'has_more': page < total_pages,
        'sort_col': sort_col,
    }


def _enrich_similar_with_full_rows(page_results, conn, user_id):
    """Replace basic similar-photo dicts with full photo rows, preserving similarity order."""
    if not page_results:
        return page_results
    sim_map = {r['path']: r['similarity'] for r in page_results}
    paths = [r['path'] for r in page_results]
    existing_cols = get_existing_columns(conn)
    pref_cols = get_preference_columns(user_id)
    pref_col_names = {'star_rating', 'is_favorite', 'is_rejected'}
    select_cols = list(PHOTO_BASE_COLS)
    for c in PHOTO_OPTIONAL_COLS:
        if c in existing_cols:
            if c in pref_col_names:
                select_cols.append(f"{pref_cols[c]} as {c}")
            else:
                select_cols.append(c)
    placeholders = ','.join(['?'] * len(paths))
    vis_sql, vis_params = get_visibility_clause(user_id)
    rows = conn.execute(
        f"SELECT {', '.join(select_cols)} FROM photos WHERE path IN ({placeholders}) AND {vis_sql}",
        paths + vis_params,
    ).fetchall()
    photos = split_photo_tags(rows, VIEWER_CONFIG['display']['tags_per_photo'])
    attach_person_data(photos, conn)
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
def api_similar_photos(
    photo_path: str,
    mode: str = Query("visual"),
    limit: int = Query(20),
    offset: int = Query(0),
    min_similarity: Optional[float] = Query(None),
    full: int = Query(0),
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Find similar photos using different similarity modes.

    Modes:
      - visual: pHash hamming distance (70%) + CLIP cosine (30%)
      - color: histogram intersection + saturation/luminance distance
      - person: same person_id or face embedding cosine similarity
    """
    if not VIEWER_CONFIG.get('features', {}).get('show_similar_button', True):
        raise HTTPException(status_code=503, detail='Similar photos feature is disabled')

    if mode not in _MODE_DEFAULT_MIN_SIM:
        mode = 'visual'

    effective_min_sim = min_similarity if min_similarity is not None else _MODE_DEFAULT_MIN_SIM[mode]

    conn = get_db_connection()
    try:
        user_id = user.user_id if user else None
        vis_sql, vis_params = get_visibility_clause(user_id)

        # Load source photo with all columns needed across modes
        source = conn.execute(f"""
            SELECT path, phash, clip_embedding, histogram_data, mean_saturation,
                   mean_luminance, is_monochrome,
                   aggregate, aesthetic, date_taken
            FROM photos WHERE path = ? AND {vis_sql}
        """, [photo_path] + vis_params).fetchone()

        if not source:
            raise HTTPException(status_code=404, detail='Photo not found')

        source = dict(source)
        message = None

        if mode == 'visual':
            results, message = _find_similar_visual(conn, source, photo_path, effective_min_sim, vis_sql, vis_params)
        elif mode == 'color':
            results, message = _find_similar_color(conn, source, photo_path, effective_min_sim, vis_sql, vis_params)
        elif mode == 'person':
            results, message = _find_similar_person(conn, source, photo_path, effective_min_sim, vis_sql, vis_params, user_id=user_id)
        else:
            results, message = [], None

        total_count = len(results)
        page_results = results[offset:offset + limit]

        if full:
            page_results = _enrich_similar_with_full_rows(page_results, conn, user_id)

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

    except sqlite3.Error:
        logger.exception("Failed to find similar photos")
        raise HTTPException(status_code=500, detail='Internal server error')
    finally:
        conn.close()


@router.get("/api/config")
def api_config(user: Optional[CurrentUser] = Depends(get_optional_user)):
    """Get viewer configuration for Angular client initialization."""
    from api.config import is_multi_user_enabled
    from api.auth import is_edition_enabled, is_edition_authenticated
    from api.types import SORT_OPTIONS, SORT_OPTIONS_GROUPED, QUALITY_LEVELS, TYPE_LABELS

    features = dict(VIEWER_CONFIG.get('features', {}))
    conn = get_db_connection()
    try:
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
    finally:
        conn.close()

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
