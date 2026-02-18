import time
from config import ScoringConfig
from viewer.config import VIEWER_CONFIG, _photo_types_cache
from viewer.top_picks import get_top_picks_score_sql
from viewer.db_helpers import HIDE_BLINKS_SQL, HIDE_BURSTS_SQL, HIDE_DUPLICATES_SQL


# --- SORT OPTIONS (loaded from config) ---
def _build_sort_options():
    """Build sort options from config - supports both flat and grouped formats."""
    sort_opts = VIEWER_CONFIG.get('sort_options', {})

    # Handle grouped format (dict of category -> options)
    if isinstance(sort_opts, dict):
        flat = []
        for category, options in sort_opts.items():
            for opt in options:
                flat.append((opt['column'], opt['label']))
        return flat, sort_opts

    # Handle legacy flat format (list of options)
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

# Build type definitions and filters from scoring_config.json categories (single ScoringConfig parse)
_scoring_config = ScoringConfig(validate=False)
_config_categories = _scoring_config.get_categories()


def _build_type_definitions():
    """Build type definitions from config categories."""
    pt = VIEWER_CONFIG['photo_types']
    threshold = pt.get('top_picks_min_score', 7)
    top_picks_expr = get_top_picks_score_sql()

    # Start with special types
    types = [
        ('top_picks', 'Top Picks', f"({top_picks_expr}) >= {threshold}"),
    ]

    # Add category-based types with display names
    category_labels = {
        'portrait': 'Portraits',
        'group_portrait': 'Group Portraits',
        'human_others': 'People in Scene',
        'silhouette': 'Silhouettes',
        'street': 'Street',
        'concert': 'Concerts',
        'art': 'Art & Statues',
        'macro': 'Macro',
        'astro': 'Astrophotography',
        'aerial': 'Aerial & Drone',
        'wildlife': 'Wildlife',
        'food': 'Food',
        'architecture': 'Architecture',
        'long_exposure': 'Long Exposure',
        'night': 'Night',
        'monochrome': 'Black & White',
        'others': 'Others',
    }

    for cat in _config_categories:
        cat_name = cat.get('name', '')
        if cat_name and cat_name in category_labels:
            label = category_labels[cat_name]
            types.append((cat_name, label, f"category = '{cat_name}'"))

    return types


TYPE_DEFINITIONS = _build_type_definitions()


# Map type to filter params - category-based types use 'category' filter
def _build_type_filters():
    """Build type filters from config categories."""
    filters = {
        'top_picks': {'top_picks_filter': '1'},
    }

    # Add category-based filters
    for cat in _config_categories:
        cat_name = cat.get('name', '')
        if cat_name:
            filters[cat_name] = {'category': cat_name}

    return filters


TYPE_FILTERS = _build_type_filters()
del _scoring_config, _config_categories  # Free references after startup

# Default sort for each photo type - list of (column, direction) tuples
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

# Mapping from viewer type to scoring category for comparison mode
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

# Type labels for filter chip display (without counts)
TYPE_LABELS = {type_id: label for type_id, label, _ in TYPE_DEFINITIONS}

QUALITY_MAP = VIEWER_CONFIG['quality_thresholds']


def get_photo_types(hide_blinks=False, hide_bursts=False, hide_duplicates=False):
    """Build type list dynamically from database, showing only non-empty categories with counts.

    Args:
        hide_blinks: If True, exclude photos where is_blink = 1
        hide_bursts: If True, only include burst leads and standalone/unprocessed photos
        hide_duplicates: If True, only include duplicate leads and non-duplicate photos

    Optimized to use a single UNION ALL query instead of 17+ individual COUNT queries.
    """
    from viewer.db_helpers import get_db_connection, get_existing_columns, get_visibility_clause
    from viewer.auth import get_session_user_id

    user_id = get_session_user_id()

    # Check cache (keyed by filter combination + user)
    cache_key = (hide_blinks, hide_bursts, hide_duplicates, user_id or '')
    if time.time() < _photo_types_cache['expires'] and cache_key in _photo_types_cache['data']:
        return _photo_types_cache['data'][cache_key]

    conn = get_db_connection()
    existing_cols = get_existing_columns(conn)

    # Build base filter clauses for blink/burst settings
    base_filters = []
    sql_params = []
    if hide_blinks:
        base_filters.append(HIDE_BLINKS_SQL)
    if hide_bursts:
        base_filters.append(HIDE_BURSTS_SQL)
    if hide_duplicates:
        base_filters.append(HIDE_DUPLICATES_SQL)

    # Multi-user visibility
    if user_id:
        vis_sql, vis_params = get_visibility_clause(user_id)
        base_filters.append(vis_sql)
        sql_params.extend(vis_params)

    base_where = " AND ".join(base_filters) if base_filters else ""

    # Build list of valid type definitions with modified where clauses
    valid_types = []
    for type_id, label, where_clause in TYPE_DEFINITIONS:
        # Skip types that require columns not in the database
        if 'is_monochrome' in where_clause and 'is_monochrome' not in existing_cols:
            continue
        if 'mean_luminance' in where_clause and 'mean_luminance' not in existing_cols:
            continue
        if 'is_silhouette' in where_clause and 'is_silhouette' not in existing_cols:
            # Silhouettes can also be detected by tags, so modify query
            where_clause = "tags LIKE '%silhouette%'"
        if 'tags' in where_clause and 'tags' not in existing_cols:
            continue

        # Combine type filter with base filters
        if base_where:
            combined_where = f"({where_clause}) AND {base_where}"
        else:
            combined_where = where_clause

        valid_types.append((type_id, label, combined_where))

    # Build single UNION ALL query for all counts
    # Each sub-query needs its own copy of params
    all_params = []
    query_parts = []
    # Add "All Photos" count first
    if base_where:
        query_parts.append(f"SELECT '' as type_id, COUNT(*) as cnt FROM photos WHERE {base_where}")
        all_params.extend(sql_params)
    else:
        query_parts.append("SELECT '' as type_id, COUNT(*) as cnt FROM photos")

    # Add all type counts
    for type_id, label, combined_where in valid_types:
        query_parts.append(f"SELECT '{type_id}' as type_id, COUNT(*) as cnt FROM photos WHERE {combined_where}")
        all_params.extend(sql_params)

    # Execute single UNION ALL query
    union_query = " UNION ALL ".join(query_parts)
    try:
        results = conn.execute(union_query, all_params).fetchall()
    except Exception:
        # Fallback to individual queries if UNION fails
        conn.close()
        return _get_photo_types_fallback(hide_blinks, hide_bursts, hide_duplicates)

    conn.close()

    # Build type list from results
    types = []
    type_label_map = {type_id: label for type_id, label, _ in TYPE_DEFINITIONS}
    type_label_map[''] = 'All Photos'

    for row in results:
        type_id, count = row[0], row[1]
        if count > 0:
            label = type_label_map.get(type_id, type_id)
            types.append((type_id, f'{label} ({count})'))

    # Update cache (use configured TTL)
    _photo_types_cache['data'][cache_key] = types
    _photo_types_cache['expires'] = time.time() + VIEWER_CONFIG['cache_ttl_seconds']

    return types


def _get_photo_types_fallback(hide_blinks=False, hide_bursts=False, hide_duplicates=False):
    """Fallback method using individual queries if UNION ALL fails."""
    from viewer.db_helpers import get_db_connection, get_existing_columns

    conn = get_db_connection()
    existing_cols = get_existing_columns(conn)

    base_filters = []
    if hide_blinks:
        base_filters.append(HIDE_BLINKS_SQL)
    if hide_bursts:
        base_filters.append(HIDE_BURSTS_SQL)
    if hide_duplicates:
        base_filters.append(HIDE_DUPLICATES_SQL)

    base_where = " AND ".join(base_filters) if base_filters else ""

    total_query = "SELECT COUNT(*) FROM photos"
    if base_where:
        total_query += f" WHERE {base_where}"
    total = conn.execute(total_query).fetchone()[0]
    types = [('', f'All Photos ({total})')]

    for type_id, label, where_clause in TYPE_DEFINITIONS:
        # Skip types that require columns not in the database
        if 'is_monochrome' in where_clause and 'is_monochrome' not in existing_cols:
            continue
        if 'mean_luminance' in where_clause and 'mean_luminance' not in existing_cols:
            continue
        if 'is_silhouette' in where_clause and 'is_silhouette' not in existing_cols:
            # Silhouettes can also be detected by tags, so modify query
            where_clause = "tags LIKE '%silhouette%'"
        if 'tags' in where_clause and 'tags' not in existing_cols:
            continue

        # Combine type filter with base filters
        if base_where:
            combined_where = f"({where_clause}) AND {base_where}"
        else:
            combined_where = where_clause

        try:
            count = conn.execute(f"SELECT COUNT(*) FROM photos WHERE {combined_where}").fetchone()[0]
            if count > 0:
                types.append((type_id, f'{label} ({count})'))
        except Exception:
            # Skip types that fail due to missing columns or syntax issues
            pass

    conn.close()
    return types


def normalize_params(args):
    """Translate semantic params to legacy format while preserving originals."""
    result = {}

    # Copy all existing params
    for key in args:
        result[key] = args.get(key, '')

    # quality -> min_score (only if min_score not already set)
    quality = args.get('quality', '')
    if quality and quality in QUALITY_MAP and not args.get('min_score'):
        result['min_score'] = str(QUALITY_MAP[quality])

    # type -> filter params from TYPE_FILTERS dict
    photo_type = args.get('type', '')
    if photo_type in TYPE_FILTERS:
        for key, value in TYPE_FILTERS[photo_type].items():
            # Only set if not already explicitly set by user
            if not args.get(key):
                result[key] = value

    # Sort is handled by the configured default (viewer.defaults.sort)
    # and preserved when switching types - no auto-sort by type

    return result
