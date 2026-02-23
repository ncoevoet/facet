"""
Gallery router — photo listing, type counts, similar photos.

"""

import math
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from api.auth import CurrentUser, get_optional_user, require_authenticated
from api.config import VIEWER_CONFIG, load_viewer_config
from api.database import get_db_connection
from api.db_helpers import (
    get_existing_columns, get_cached_count, _add_tag_filter,
    get_art_tags_from_config, HIDE_BLINKS_SQL, HIDE_BURSTS_SQL, HIDE_DUPLICATES_SQL,
    PHOTO_BASE_COLS, PHOTO_OPTIONAL_COLS,
    split_photo_tags, attach_person_data,
    get_visibility_clause, get_photos_from_clause, get_preference_columns
)
from api.top_picks import get_top_picks_score_sql, get_top_picks_threshold
from api.types import (
    VALID_SORT_COLS, TYPE_FILTERS, QUALITY_MAP, normalize_params, get_photo_types
)

router = APIRouter(tags=["gallery"])


def _format_date(date_str):
    """Format EXIF date string to DD/MM/YYYY HH:MM."""
    if not date_str or not isinstance(date_str, str):
        return ''
    try:
        parts = date_str.split(' ')
        date_part = parts[0].replace(':', '/')
        # Rearrange from YYYY/MM/DD to DD/MM/YYYY
        date_components = date_part.split('/')
        if len(date_components) == 3:
            date_part = f"{date_components[2]}/{date_components[1]}/{date_components[0]}"
        time_part = parts[1][:5] if len(parts) > 1 else ''
        return f"{date_part} {time_part}".strip()
    except (IndexError, AttributeError):
        return str(date_str)


def _build_gallery_where(params, conn=None, user_id=None):
    """Build WHERE clauses for gallery queries."""
    where_clauses = []
    sql_params = []

    if user_id:
        vis_sql, vis_params = get_visibility_clause(user_id)
        where_clauses.append(vis_sql)
        sql_params.extend(vis_params)

    def add_range_filter(column, min_key, max_key, is_float=True):
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

    if params.get('camera'):
        where_clauses.append("camera_model = ?")
        sql_params.append(params['camera'])
    if params.get('lens'):
        clean_search = params['lens'].split('\ufffd')[0].strip()
        where_clauses.append("lens_model LIKE ?")
        sql_params.append(f"{clean_search}%")

    if params.get('search'):
        where_clauses.append("filename LIKE ?")
        sql_params.append(f"%{params['search']}%")

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

    if params.get('is_silhouette') == '1':
        where_clauses.append("is_silhouette = 1")

    if params.get('hide_bursts') in ('1', 'true') or params.get('burst_only') in ('1', 'true'):
        where_clauses.append(HIDE_BURSTS_SQL)
    if params.get('hide_blinks') in ('1', 'true') or params.get('no_blink') in ('1', 'true'):
        where_clauses.append(HIDE_BLINKS_SQL)
    if params.get('hide_duplicates') in ('1', 'true'):
        where_clauses.append(HIDE_DUPLICATES_SQL)

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

    add_range_filter("aggregate", "min_score", "max_score")
    add_range_filter("aesthetic", "min_aesthetic", "max_aesthetic")
    add_range_filter("quality_score", "min_quality_score", "max_quality_score")
    add_range_filter("topiq_score", "min_topiq", "max_topiq")
    add_range_filter("tech_sharpness", "min_sharpness", "max_sharpness")
    add_range_filter("exposure_score", "min_exposure", "max_exposure")
    add_range_filter("color_score", "min_color", "max_color")
    add_range_filter("contrast_score", "min_contrast", "max_contrast")
    add_range_filter("noise_sigma", "min_noise", "max_noise")
    add_range_filter("mean_saturation", "min_saturation", "max_saturation")
    add_range_filter("mean_luminance", "min_luminance", "max_luminance")
    add_range_filter("histogram_spread", "min_histogram_spread", "max_histogram_spread")
    add_range_filter("dynamic_range_stops", "min_dynamic_range", "max_dynamic_range")
    add_range_filter("comp_score", "min_composition", "max_composition")
    add_range_filter("power_point_score", "min_power_point", "max_power_point")
    add_range_filter("leading_lines_score", "min_leading_lines", "max_leading_lines")
    add_range_filter("isolation_bonus", "min_isolation", "max_isolation")
    add_range_filter("face_count", "min_face_count", "max_face_count", is_float=False)
    add_range_filter("face_quality", "min_face_quality", "max_face_quality")
    add_range_filter("eye_sharpness", "min_eye_sharpness", "max_eye_sharpness")
    add_range_filter("face_sharpness", "min_face_sharpness", "max_face_sharpness")
    add_range_filter("face_ratio", "min_face_ratio", "max_face_ratio")
    add_range_filter("face_confidence", "min_face_confidence", "max_face_confidence")
    add_range_filter("star_rating", "min_star_rating", "max_star_rating", is_float=False)

    add_range_filter("aesthetic_iaa", "min_aesthetic_iaa", "max_aesthetic_iaa")
    add_range_filter("face_quality_iqa", "min_face_quality_iqa", "max_face_quality_iqa")
    add_range_filter("liqe_score", "min_liqe", "max_liqe")
    add_range_filter("subject_sharpness", "min_subject_sharpness", "max_subject_sharpness")
    add_range_filter("subject_prominence", "min_subject_prominence", "max_subject_prominence")
    add_range_filter("subject_placement", "min_subject_placement", "max_subject_placement")
    add_range_filter("bg_separation", "min_bg_separation", "max_bg_separation")

    add_range_filter("iso", "min_iso", "max_iso", is_float=False)
    add_range_filter("f_stop", "min_aperture", "max_aperture")
    add_range_filter("focal_length", "min_focal_length", "max_focal_length")

    if params.get('date_from'):
        try:
            date_from = params['date_from'].replace('-', ':')
            where_clauses.append("date_taken >= ?")
            sql_params.append(date_from)
        except (ValueError, AttributeError):
            pass
    if params.get('date_to'):
        try:
            date_to = params['date_to'].replace('-', ':') + " 23:59:59"
            where_clauses.append("date_taken <= ?")
            sql_params.append(date_to)
        except (ValueError, AttributeError):
            pass

    return where_clauses, sql_params


@router.get("/api/type_counts")
async def api_type_counts(
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
    """Gallery photo listing with filtering, sorting, and pagination."""
    qp = dict(request.query_params)
    defaults_cfg = VIEWER_CONFIG['defaults']
    default_per_page = VIEWER_CONFIG['pagination']['default_per_page']

    try:
        page = int(qp.get('page', 1))
    except (ValueError, TypeError):
        page = 1
    try:
        per_page = int(qp.get('per_page', default_per_page))
    except (ValueError, TypeError):
        per_page = default_per_page

    default_type = defaults_cfg.get('type', '')
    normalized = normalize_params(qp)

    params = {
        'sort': normalized.get('sort') or qp.get('sort', defaults_cfg['sort']),
        'dir': qp.get('sort_direction') or qp.get('dir', defaults_cfg['sort_direction']),
        'camera': qp.get('camera', ''),
        'lens': qp.get('lens', ''),
        'per_page': per_page,
        'quality': qp.get('quality', ''),
        'type': qp.get('type', '' if (qp.get('person') or qp.get('person_id')) else default_type),
        'hide_blinks': qp.get('hide_blinks', '0'),
        'hide_bursts': qp.get('hide_bursts', '0'),
        'hide_duplicates': qp.get('hide_duplicates', '0'),
        'burst_only': qp.get('burst_only', ''),
        'no_blink': qp.get('no_blink', ''),
        'search': qp.get('search', ''),
        'tag': qp.get('tag', ''),
        'person': qp.get('person') or qp.get('person_id', ''),
        'min_score': normalized.get('min_score', ''),
        'max_score': qp.get('max_score', ''),
        'min_aesthetic': qp.get('min_aesthetic', ''),
        'max_aesthetic': qp.get('max_aesthetic', ''),
        'min_sharpness': qp.get('min_sharpness', ''),
        'max_sharpness': qp.get('max_sharpness', ''),
        'min_exposure': qp.get('min_exposure', ''),
        'max_exposure': qp.get('max_exposure', ''),
        'min_face_count': normalized.get('min_face_count', ''),
        'max_face_count': normalized.get('max_face_count', ''),
        'min_face_ratio': normalized.get('min_face_ratio', ''),
        'max_face_ratio': normalized.get('max_face_ratio', ''),
        'min_face_quality': qp.get('min_face_quality', ''),
        'max_face_quality': qp.get('max_face_quality', ''),
        'min_eye_sharpness': qp.get('min_eye_sharpness', ''),
        'max_eye_sharpness': qp.get('max_eye_sharpness', ''),
        'min_iso': qp.get('min_iso', ''),
        'max_iso': qp.get('max_iso', ''),
        'min_aperture': qp.get('min_aperture', ''),
        'max_aperture': qp.get('max_aperture', ''),
        'min_focal_length': qp.get('min_focal_length', ''),
        'max_focal_length': qp.get('max_focal_length', ''),
        'date_from': qp.get('date_from', ''),
        'date_to': qp.get('date_to', ''),
        'is_monochrome': normalized.get('is_monochrome', ''),
        'category': normalized.get('category', ''),
        'min_aggregate': normalized.get('min_aggregate', ''),
        'max_luminance': normalized.get('max_luminance', ''),
        'is_silhouette': normalized.get('is_silhouette', ''),
        'require_tags': normalized.get('require_tags', ''),
        'exclude_tags': normalized.get('exclude_tags', ''),
        'exclude_art': normalized.get('exclude_art', ''),
        'top_picks_filter': normalized.get('top_picks_filter', ''),
        'min_rating': qp.get('min_rating', ''),
        'favorites_only': qp.get('favorites_only', ''),
        'hide_rejected': qp.get('hide_rejected', ''),
        'show_rejected': qp.get('show_rejected', ''),
        'min_dynamic_range': qp.get('min_dynamic_range', ''),
        'max_dynamic_range': qp.get('max_dynamic_range', ''),
        'min_contrast': qp.get('min_contrast', ''),
        'max_contrast': qp.get('max_contrast', ''),
        'min_noise': qp.get('min_noise', ''),
        'max_noise': qp.get('max_noise', ''),
        'min_color': qp.get('min_color', ''),
        'max_color': qp.get('max_color', ''),
        'min_composition': qp.get('min_composition', ''),
        'max_composition': qp.get('max_composition', ''),
        'min_face_sharpness': qp.get('min_face_sharpness', ''),
        'max_face_sharpness': qp.get('max_face_sharpness', ''),
        'min_isolation': qp.get('min_isolation', ''),
        'max_isolation': qp.get('max_isolation', ''),
        'min_luminance': qp.get('min_luminance', ''),
        'min_histogram_spread': qp.get('min_histogram_spread', ''),
        'max_histogram_spread': qp.get('max_histogram_spread', ''),
        'min_power_point': qp.get('min_power_point', ''),
        'max_power_point': qp.get('max_power_point', ''),
        'min_leading_lines': qp.get('min_leading_lines', ''),
        'max_leading_lines': qp.get('max_leading_lines', ''),
        'min_quality_score': qp.get('min_quality_score', ''),
        'max_quality_score': qp.get('max_quality_score', ''),
        'min_saturation': qp.get('min_saturation', ''),
        'max_saturation': qp.get('max_saturation', ''),
        'min_face_confidence': qp.get('min_face_confidence', ''),
        'max_face_confidence': qp.get('max_face_confidence', ''),
        'min_star_rating': qp.get('min_star_rating', ''),
        'max_star_rating': qp.get('max_star_rating', ''),
        'min_topiq': qp.get('min_topiq', ''),
        'max_topiq': qp.get('max_topiq', ''),
        'composition_pattern': qp.get('composition_pattern', ''),
        'min_aesthetic_iaa': qp.get('min_aesthetic_iaa', ''),
        'max_aesthetic_iaa': qp.get('max_aesthetic_iaa', ''),
        'min_face_quality_iqa': qp.get('min_face_quality_iqa', ''),
        'max_face_quality_iqa': qp.get('max_face_quality_iqa', ''),
        'min_liqe': qp.get('min_liqe', ''),
        'max_liqe': qp.get('max_liqe', ''),
        'min_subject_sharpness': qp.get('min_subject_sharpness', ''),
        'max_subject_sharpness': qp.get('max_subject_sharpness', ''),
        'min_subject_prominence': qp.get('min_subject_prominence', ''),
        'max_subject_prominence': qp.get('max_subject_prominence', ''),
        'min_subject_placement': qp.get('min_subject_placement', ''),
        'max_subject_placement': qp.get('max_subject_placement', ''),
        'min_bg_separation': qp.get('min_bg_separation', ''),
        'max_bg_separation': qp.get('max_bg_separation', ''),
    }

    if params.get('type') in TYPE_FILTERS:
        for key, value in TYPE_FILTERS[params['type']].items():
            if not params.get(key):
                params[key] = value

    conn = get_db_connection()
    user_id = user.user_id if user else None
    from_clause, from_params = get_photos_from_clause(user_id)
    where_clauses, sql_params = _build_gallery_where(params, conn, user_id=user_id)
    all_params = from_params + sql_params
    where_str = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    sort_col = params['sort'] if params['sort'] in VALID_SORT_COLS else 'aggregate'
    sort_dir = 'ASC' if params['dir'] == 'ASC' else 'DESC'
    order_by_clause = f"{sort_col} {sort_dir}, path ASC"

    try:
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
            photo['date_formatted'] = _format_date(photo.get('date_taken'))

        attach_person_data(photos, conn)

    except Exception:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail='Internal server error')
    finally:
        conn.close()

    for photo in photos:
        for key, value in photo.items():
            if isinstance(value, float) and (math.isinf(value) or math.isnan(value)):
                photo[key] = None

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
    path_to_photo = {p['path']: p for p in photos}
    ordered = []
    for path in paths:
        if path in path_to_photo:
            p = path_to_photo[path]
            p['similarity'] = sim_map[path]
            ordered.append(p)
    return ordered


@router.get("/api/similar_photos/{photo_path:path}")
async def api_similar_photos(
    photo_path: str,
    limit: int = Query(20),
    offset: int = Query(0),
    min_similarity: float = Query(0.40),
    full: int = Query(0),
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Find visually similar photos using pHash hamming distance (primary) + CLIP cosine (secondary).

    Two-pass algorithm:
      Pass 1 — load all pHashes (no BLOBs), compute vectorized hamming distances, prune via
               mathematical floor: a candidate can only pass if phash_sim >= (min_sim - 0.3) / 0.7.
      Pass 2 — fetch CLIP embeddings for survivors, compute blended score:
               similarity = phash_sim * 0.7 + clip_cosine * 0.3
    Falls back to CLIP-only (raw cosine, clamped to 0) when the source has no pHash.
    """
    viewer_config = load_viewer_config()
    if not viewer_config.get('features', {}).get('show_similar_button', True):
        return {'error': 'Similar photos feature is disabled'}

    import numpy as np

    # Precomputed byte popcount table (same technique as duplicate.py)
    _POPCOUNT = np.array([bin(i).count('1') for i in range(256)], dtype=np.int32)
    PHASH_W = 0.7
    CLIP_W = 0.3

    conn = get_db_connection()
    try:
        user_id = user.user_id if user else None
        vis_sql, vis_params = get_visibility_clause(user_id)

        source = conn.execute(f"""
            SELECT path, phash, clip_embedding, aggregate, aesthetic, date_taken
            FROM photos WHERE path = ? AND {vis_sql}
        """, [photo_path] + vis_params).fetchone()

        if not source:
            return {'error': 'Photo not found'}

        source = dict(source)

        # Parse source pHash
        source_phash = np.uint64(int(source['phash'], 16)) if source.get('phash') else None

        # Parse + normalize source CLIP embedding
        source_embedding = None
        if source.get('clip_embedding'):
            e = np.frombuffer(source['clip_embedding'], dtype=np.float32).copy()
            norm = np.linalg.norm(e)
            if norm > 0:
                source_embedding = e / norm

        if source_phash is None and source_embedding is None:
            return {'similar': [], 'total': 0, 'has_more': False}

        # ── Pass 1: load all pHashes (no CLIP BLOBs) ─────────────────────────
        rows = conn.execute(f"""
            SELECT path, filename, phash, date_taken, aggregate, aesthetic
            FROM photos
            WHERE path != ? AND phash IS NOT NULL AND {vis_sql}
        """, [photo_path] + vis_params).fetchall()
        rows = [dict(r) for r in rows]

        if not rows:
            # No phash candidates — CLIP-only fallback handled below
            clip_rows = conn.execute(f"""
                SELECT path, filename, clip_embedding, date_taken, aggregate, aesthetic
                FROM photos
                WHERE path != ? AND clip_embedding IS NOT NULL AND {vis_sql}
                LIMIT 5000
            """, [photo_path] + vis_params).fetchall()
            rows = [dict(r) for r in clip_rows]
            if not rows or source_embedding is None:
                return {'similar': [], 'total': 0, 'has_more': False}
            results = []
            for r in rows:
                e = np.frombuffer(r['clip_embedding'], dtype=np.float32).copy()
                n = np.linalg.norm(e)
                if n == 0:
                    continue
                sim = max(0.0, float(np.dot(source_embedding, e / n)))
                if sim >= min_similarity:
                    results.append({
                        'path': r['path'], 'filename': r['filename'],
                        'similarity': round(sim, 4),
                        'aggregate': r.get('aggregate'), 'aesthetic': r.get('aesthetic'),
                        'date_taken': r.get('date_taken'),
                    })
            results.sort(key=lambda x: x['similarity'], reverse=True)
            results = results[:500]
            page_slice = results[offset:offset + limit]
            total_clip = len(results)
            if full:
                page_slice = _enrich_similar_with_full_rows(page_slice, conn, user_id)
            return {'source': photo_path, 'similar': page_slice,
                    'total': total_clip, 'has_more': (offset + limit) < total_clip}

        # ── Vectorized pHash hamming distance ─────────────────────────────────
        hashes = np.array([int(r['phash'], 16) for r in rows], dtype=np.uint64)
        xor = np.bitwise_xor(hashes, source_phash)
        hamming = np.zeros(len(rows), dtype=np.int32)
        for byte_idx in range(8):
            shift = np.uint64(byte_idx * 8)
            byte_vals = ((xor >> shift) & np.uint64(0xFF)).astype(np.int32)
            hamming += _POPCOUNT[byte_vals]
        phash_sims = 1.0 - hamming / 64.0

        # Prune: lowest possible score = phash_sim * PHASH_W + 0 * CLIP_W
        # Highest possible score = phash_sim * PHASH_W + 1.0 * CLIP_W
        # Skip if even perfect CLIP can't push it over min_similarity
        if source_embedding is not None:
            phash_floor = max(0.0, (min_similarity - CLIP_W) / PHASH_W)
        else:
            phash_floor = min_similarity  # no CLIP available: phash alone must clear threshold
        candidate_indices = np.where(phash_sims >= phash_floor)[0]

        # ── Pass 2: load CLIP embeddings for survivors ────────────────────────
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
                    e = np.frombuffer(cr['clip_embedding'], dtype=np.float32).copy()
                    n = np.linalg.norm(e)
                    if n > 0:
                        clip_by_path[cr['path']] = e / n

        # ── Score, filter, paginate ───────────────────────────────────────────
        results = []
        for i in candidate_indices:
            row = rows[i]
            phash_sim = float(phash_sims[i])
            cand_clip = clip_by_path.get(row['path'])
            if source_embedding is not None and cand_clip is not None:
                clip_sim = max(0.0, float(np.dot(source_embedding, cand_clip)))
                sim = phash_sim * PHASH_W + clip_sim * CLIP_W
            else:
                sim = phash_sim * PHASH_W  # no CLIP: candidate only earns its phash share
            if sim >= min_similarity:
                results.append({
                    'path': row['path'],
                    'filename': row['filename'],
                    'similarity': round(sim, 4),
                    'aggregate': row.get('aggregate'),
                    'aesthetic': row.get('aesthetic'),
                    'date_taken': row.get('date_taken'),
                })

        results.sort(key=lambda x: x['similarity'], reverse=True)
        results = results[:500]
        total_count = len(results)
        page_results = results[offset:offset + limit]

        if full:
            page_results = _enrich_similar_with_full_rows(page_results, conn, user_id)

        return {
            'source': photo_path,
            'similar': page_results,
            'total': total_count,
            'has_more': (offset + limit) < total_count,
        }

    except Exception:
        import traceback
        traceback.print_exc()
        return {'error': 'Internal server error'}
    finally:
        conn.close()


@router.get("/api/config")
async def api_config(user: Optional[CurrentUser] = Depends(get_optional_user)):
    """Get viewer configuration for Angular client initialization."""
    from api.config import is_multi_user_enabled
    from api.auth import is_edition_enabled, is_edition_authenticated
    from api.types import SORT_OPTIONS, SORT_OPTIONS_GROUPED, QUALITY_LEVELS, TYPE_LABELS

    features = dict(VIEWER_CONFIG.get('features', {}))
    if features.get('show_similar_button'):
        conn = get_db_connection()
        try:
            has_embeddings = conn.execute(
                "SELECT 1 FROM photos WHERE clip_embedding IS NOT NULL LIMIT 1"
            ).fetchone() is not None
            if not has_embeddings:
                features['show_similar_button'] = False
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
        'is_multi_user': is_multi_user_enabled(),
        'edition_enabled': is_edition_enabled(),
        'edition_authenticated': is_edition_authenticated(user),
    }
