"""
Sort/type/filter definitions for the API server.

"""

import logging
import time

from config import ScoringConfig
from api.config import VIEWER_CONFIG, _photo_types_cache, _photo_types_lock
from api.top_picks import get_top_picks_score_sql
from api.db_helpers import build_hide_clauses

logger = logging.getLogger(__name__)


# --- SORT OPTIONS (loaded from config) ---
def _build_sort_options():
    """Build sort options from config - supports both flat and grouped formats."""
    sort_opts = VIEWER_CONFIG.get('sort_options', {})

    if isinstance(sort_opts, dict):
        flat = []
        for category, options in sort_opts.items():
            for opt in options:
                flat.append((opt['column'], opt['label']))
        return flat, sort_opts

    flat = [(opt['column'], opt['label']) for opt in sort_opts]
    return flat, None


SORT_OPTIONS, SORT_OPTIONS_GROUPED = _build_sort_options()
VALID_SORT_COLS = [opt[0] for opt in SORT_OPTIONS] + ['top_picks_score']


# --- SEMANTIC FILTER MAPPINGS ---
def _build_quality_levels():
    """Build quality levels from config."""
    qt = VIEWER_CONFIG['quality_thresholds']
    return [
        ('', 'All'),
        ('good', f"Good ({qt['good']}+)"),
        ('great', f"Great ({qt['great']}+)"),
        ('excellent', f"Excellent ({qt['excellent']}+)"),
        ('best', f"Best ({qt['best']}+)"),
    ]


QUALITY_LEVELS = _build_quality_levels()

# Build type definitions and filters from scoring_config.json categories
_scoring_config = ScoringConfig(validate=False)
_config_categories = _scoring_config.get_categories()


def _build_type_definitions():
    """Build type definitions from config categories."""
    pt = VIEWER_CONFIG['photo_types']
    threshold = pt.get('top_picks_min_score', 7)
    top_picks_expr = get_top_picks_score_sql()

    types = [
        ('top_picks', 'Top Picks', f"({top_picks_expr}) >= {threshold}", []),
    ]

    # Auto-include all categories from config (label resolved via i18n on frontend)
    for cat in _config_categories:
        cat_name = cat.get('name', '')
        if cat_name and cat_name != 'default':
            types.append((cat_name, cat_name, "category = ?", [cat_name]))

    return types


TYPE_DEFINITIONS = _build_type_definitions()


def _build_type_filters():
    """Build type filters from config categories."""
    filters = {
        'top_picks': {'top_picks_filter': '1'},
    }
    for cat in _config_categories:
        cat_name = cat.get('name', '')
        if cat_name:
            filters[cat_name] = {'category': cat_name}
    return filters


TYPE_FILTERS = _build_type_filters()
del _scoring_config, _config_categories

TYPE_DEFAULT_SORTS = {
    'top_picks': [('top_picks_score', 'DESC'), ('date_taken', 'DESC')],
    'portraits': [('face_quality', 'DESC'), ('eye_sharpness', 'DESC'), ('aesthetic', 'DESC')],
    'people': [('aggregate', 'DESC'), ('face_quality', 'DESC')],
    'landscapes': [('aesthetic', 'DESC'), ('tech_sharpness', 'DESC'), ('comp_score', 'DESC')],
    'architecture': [('aesthetic', 'DESC'), ('tech_sharpness', 'DESC'), ('comp_score', 'DESC')],
    'nature': [('aesthetic', 'DESC'), ('tech_sharpness', 'DESC'), ('color_score', 'DESC')],
    'animals': [('aesthetic', 'DESC'), ('tech_sharpness', 'DESC')],
    'art': [('aesthetic', 'DESC'), ('color_score', 'DESC')],
    'bw': [('histogram_spread', 'DESC'), ('contrast_score', 'DESC')],
    'low_light': [('exposure_score', 'DESC'), ('tech_sharpness', 'DESC')],
    'silhouettes': [('aesthetic', 'DESC'), ('histogram_spread', 'DESC')],
    'macro': [('tech_sharpness', 'DESC'), ('aesthetic', 'DESC'), ('isolation_bonus', 'DESC')],
    'astro': [('aesthetic', 'DESC'), ('comp_score', 'DESC')],
    'street': [('aesthetic', 'DESC'), ('comp_score', 'DESC'), ('face_quality', 'DESC')],
    'long_exposure': [('shutter_speed', 'DESC'), ('aesthetic', 'DESC'), ('comp_score', 'DESC')],
    'aerial': [('comp_score', 'DESC'), ('aesthetic', 'DESC'), ('color_score', 'DESC')],
    'concert': [('aesthetic', 'DESC'), ('comp_score', 'DESC'), ('exposure_score', 'DESC')],
}

TYPE_TO_CATEGORY = {
    'portraits': 'portrait',
    'people': 'human_others',
    'landscapes': 'others',
    'architecture': 'architecture',
    'nature': 'macro',
    'animals': 'wildlife',
    'art': 'art',
    'bw': 'monochrome',
    'low_light': 'night',
    'silhouettes': 'silhouette',
    'macro': 'macro',
    'astro': 'astro',
    'street': 'street',
    'long_exposure': 'long_exposure',
    'aerial': 'aerial',
    'concert': 'concert',
    'top_picks': 'portrait',
}

TYPE_LABELS = {type_id: label for type_id, label, *_ in TYPE_DEFINITIONS}
QUALITY_MAP = VIEWER_CONFIG['quality_thresholds']


def get_photo_types(hide_blinks=False, hide_bursts=False, hide_duplicates=False, user_id=None):
    """Build type list dynamically from database, showing only non-empty categories with counts."""
    from api.db_helpers import get_db_connection, get_existing_columns, get_visibility_clause

    cache_key = (hide_blinks, hide_bursts, hide_duplicates, user_id or '')
    with _photo_types_lock:
        if time.time() < _photo_types_cache['expires'] and cache_key in _photo_types_cache['data']:
            return _photo_types_cache['data'][cache_key]

    conn = get_db_connection()
    try:
        existing_cols = get_existing_columns(conn)

        base_filters = build_hide_clauses(
            '1' if hide_blinks else '0',
            '1' if hide_bursts else '0',
            '1' if hide_duplicates else '0',
        )
        sql_params = []

        if user_id:
            vis_sql, vis_params = get_visibility_clause(user_id)
            base_filters.append(vis_sql)
            sql_params.extend(vis_params)

        base_where = " AND ".join(base_filters) if base_filters else ""

        valid_types = []
        for type_id, label, where_clause, type_params in TYPE_DEFINITIONS:
            if 'is_monochrome' in where_clause and 'is_monochrome' not in existing_cols:
                continue
            if 'mean_luminance' in where_clause and 'mean_luminance' not in existing_cols:
                continue
            if 'is_silhouette' in where_clause and 'is_silhouette' not in existing_cols:
                where_clause = "tags LIKE '%silhouette%'"
            if 'tags' in where_clause and 'tags' not in existing_cols:
                continue

            if base_where:
                combined_where = f"({where_clause}) AND {base_where}"
            else:
                combined_where = where_clause

            valid_types.append((type_id, label, combined_where, type_params))

        all_params = []
        query_parts = []
        if base_where:
            query_parts.append(f"SELECT '' as type_id, COUNT(*) as cnt FROM photos WHERE {base_where}")
            all_params.extend(sql_params)
        else:
            query_parts.append("SELECT '' as type_id, COUNT(*) as cnt FROM photos")

        for type_id, label, combined_where, type_params in valid_types:
            query_parts.append(f"SELECT ? as type_id, COUNT(*) as cnt FROM photos WHERE {combined_where}")
            all_params.append(type_id)
            all_params.extend(type_params)
            all_params.extend(sql_params)

        union_query = " UNION ALL ".join(query_parts)
        results = conn.execute(union_query, all_params).fetchall()
    except Exception:
        logger.exception("Failed to compute photo type counts")
        return []
    finally:
        conn.close()

    types = []
    type_label_map = {type_id: label for type_id, label, *_ in TYPE_DEFINITIONS}
    type_label_map[''] = 'All Photos'

    for row in results:
        type_id, count = row[0], row[1]
        if count > 0:
            label = type_label_map.get(type_id, type_id)
            types.append({'id': type_id, 'label': label, 'count': count})

    with _photo_types_lock:
        _photo_types_cache['data'][cache_key] = types
        _photo_types_cache['expires'] = time.time() + VIEWER_CONFIG['cache_ttl_seconds']

    return types


def normalize_params(params):
    """Translate semantic params to legacy format while preserving originals."""
    result = dict(params)

    quality = params.get('quality', '')
    if quality and quality in QUALITY_MAP and not params.get('min_score'):
        result['min_score'] = str(QUALITY_MAP[quality])

    photo_type = params.get('type', '')
    if photo_type in TYPE_FILTERS:
        for key, value in TYPE_FILTERS[photo_type].items():
            if not params.get(key):
                result[key] = value

    return result
