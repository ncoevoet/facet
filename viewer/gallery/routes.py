import math
import json
from flask import render_template, request, jsonify, session
from i18n import _ as translate
from viewer.filters import format_date
from viewer.gallery import gallery_bp
from viewer.config import VIEWER_CONFIG, load_viewer_config
from viewer.auth import is_edition_enabled, is_edition_authenticated, get_session_user_id
from viewer.config import is_multi_user_enabled
from viewer.db_helpers import (
    get_db_connection, get_existing_columns, get_filter_options,
    get_cached_count, _add_tag_filter, get_art_tags_from_config,
    HIDE_BLINKS_SQL, HIDE_BURSTS_SQL, HIDE_DUPLICATES_SQL,
    PHOTO_BASE_COLS, PHOTO_OPTIONAL_COLS,
    split_photo_tags, attach_person_data,
    get_visibility_clause, get_photos_from_clause, get_preference_columns
)
from viewer.top_picks import get_top_picks_score_sql, get_top_picks_threshold
from viewer.types import (
    SORT_OPTIONS, SORT_OPTIONS_GROUPED, VALID_SORT_COLS,
    QUALITY_LEVELS, TYPE_FILTERS, TYPE_LABELS,
    QUALITY_MAP, normalize_params, get_photo_types
)


def _build_gallery_where(params, conn=None, user_id=None):
    """Build WHERE clauses for gallery queries. Used by both index() and api_photos().

    Args:
        params: Filter parameters dict
        conn: Optional db connection
        user_id: Username for multi-user visibility filtering

    Returns (where_clauses, sql_params) lists.
    """
    where_clauses = []
    sql_params = []

    # Multi-user visibility filter
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

    # Equipment filters
    if params.get('camera'):
        where_clauses.append("camera_model = ?")
        sql_params.append(params['camera'])
    if params.get('lens'):
        clean_search = params['lens'].split('\ufffd')[0].strip()
        where_clauses.append("lens_model LIKE ?")
        sql_params.append(f"{clean_search}%")

    # Filename search
    if params.get('search'):
        where_clauses.append("filename LIKE ?")
        sql_params.append(f"%{params['search']}%")

    # Tag filters
    _add_tag_filter(
        where_clauses, sql_params,
        tag=params.get('tag'),
        require_tags=params.get('require_tags'),
        exclude_tags=params.get('exclude_tags'),
        exclude_art_tags=get_art_tags_from_config() if params.get('exclude_art') == '1' else None,
        conn=conn
    )

    # Composition pattern
    if params.get('composition_pattern'):
        where_clauses.append("composition_pattern = ?")
        sql_params.append(params['composition_pattern'])

    # Person filter (face recognition) - supports comma-separated IDs (AND logic: all must be present)
    if params.get('person'):
        person_ids = []
        for pid in params['person'].split(','):
            try:
                person_ids.append(int(pid.strip()))
            except ValueError:
                pass
        for pid in person_ids:
            where_clauses.append("EXISTS (SELECT 1 FROM faces WHERE photo_path = photos.path AND person_id = ?)")
            sql_params.append(pid)

    # B&W filter
    if params.get('is_monochrome') == '1':
        where_clauses.append("is_monochrome = 1")

    # Category filter
    if params.get('category'):
        where_clauses.append("category = ?")
        sql_params.append(params['category'])

    # Aggregate score filter (for top picks - legacy)
    if params.get('min_aggregate'):
        try:
            where_clauses.append("aggregate >= ?")
            sql_params.append(float(params['min_aggregate']))
        except ValueError:
            pass

    # Top picks filter (custom weighted score)
    if params.get('top_picks_filter') == '1':
        threshold = get_top_picks_threshold()
        top_picks_expr = get_top_picks_score_sql()
        where_clauses.append(f"({top_picks_expr}) >= ?")
        sql_params.append(threshold)

    # Luminance filter (for low light - max)
    if params.get('max_luminance'):
        try:
            where_clauses.append("mean_luminance < ?")
            sql_params.append(float(params['max_luminance']))
        except ValueError:
            pass

    # Silhouette filter
    if params.get('is_silhouette') == '1':
        where_clauses.append("is_silhouette = 1")

    # Toggle filters
    if params.get('hide_bursts') == '1' or params.get('burst_only') == '1':
        where_clauses.append(HIDE_BURSTS_SQL)
    if params.get('hide_blinks') == '1' or params.get('no_blink') == '1':
        where_clauses.append(HIDE_BLINKS_SQL)
    if params.get('hide_duplicates') == '1':
        where_clauses.append(HIDE_DUPLICATES_SQL)

    # Rating filters (use preference column expressions for multi-user support)
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
    elif params.get('hide_rejected') == '1':
        where_clauses.append(f"({pref_cols['is_rejected']} = 0 OR {pref_cols['is_rejected']} IS NULL)")

    # Range filters - scores
    add_range_filter("face_ratio", "min_face_ratio", "max_face_ratio")
    add_range_filter("aggregate", "min_score", "max_score")
    add_range_filter("aesthetic", "min_aesthetic", "max_aesthetic")
    add_range_filter("tech_sharpness", "min_sharpness", "max_sharpness")
    add_range_filter("exposure_score", "min_exposure", "max_exposure")
    add_range_filter("face_count", "min_face_count", "max_face_count", is_float=False)
    add_range_filter("face_quality", "min_face_quality", "max_face_quality")
    add_range_filter("eye_sharpness", "min_eye_sharpness", "max_eye_sharpness")

    # Range filters - technical settings
    add_range_filter("iso", "min_iso", "max_iso", is_float=False)
    add_range_filter("f_stop", "min_fstop", "max_fstop")
    add_range_filter("focal_length", "min_focal", "max_focal")

    # Range filters - metrics
    add_range_filter("dynamic_range_stops", "min_dynamic_range", "max_dynamic_range")
    add_range_filter("contrast_score", "min_contrast", "max_contrast")
    add_range_filter("noise_sigma", "min_noise", "max_noise")
    add_range_filter("color_score", "min_color", "max_color")
    add_range_filter("comp_score", "min_composition", "max_composition")
    add_range_filter("face_sharpness", "min_face_sharpness", "max_face_sharpness")
    add_range_filter("isolation_bonus", "min_isolation", "max_isolation")
    # Luminance min (separate from max_luminance handled above for low_light type)
    if params.get('min_luminance'):
        try:
            where_clauses.append("mean_luminance >= ?")
            sql_params.append(float(params['min_luminance']))
        except ValueError:
            pass
    add_range_filter("histogram_spread", "min_histogram_spread", "max_histogram_spread")
    add_range_filter("power_point_score", "min_power_point", "max_power_point")

    # Date range filters
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


@gallery_bp.route('/')
def index():
    # 1. Get pagination parameters (configurable defaults)
    default_per_page = VIEWER_CONFIG['pagination']['default_per_page']
    per_page = request.args.get('per_page', default_per_page, type=int)
    page = request.args.get('page', 1, type=int)

    # Check if this is a fresh visit (no query params except page/per_page)
    filter_keys = set(request.args.keys()) - {'page', 'per_page'}
    is_fresh_visit = len(filter_keys) == 0

    # Get configurable defaults
    defaults_cfg = VIEWER_CONFIG['defaults']
    default_hide_blinks = '1' if defaults_cfg['hide_blinks'] else ''
    default_hide_bursts = '1' if defaults_cfg['hide_bursts'] else ''
    default_hide_duplicates = '1' if defaults_cfg.get('hide_duplicates', False) else ''
    default_hide_details = '1' if defaults_cfg.get('hide_details', False) else ''
    default_type = defaults_cfg.get('type', '')

    # 2. Build params dict with all filter values
    # Normalize semantic params first
    normalized = normalize_params(request.args)

    params = {
        'sort': normalized.get('sort') or request.args.get('sort', defaults_cfg['sort']),
        'dir': request.args.get('dir', defaults_cfg['sort_direction']),
        'camera': request.args.get('camera', ''),
        'lens': request.args.get('lens', ''),
        'per_page': per_page,
        # New semantic filters
        'quality': request.args.get('quality', ''),
        # Don't apply default type when filtering by person (show all photo types for that person)
        'type': request.args.get('type', '' if request.args.get('person') else default_type),
        # Display toggles - use configurable defaults on fresh visits
        'hide_blinks': request.args.get('hide_blinks', default_hide_blinks if is_fresh_visit else '0'),
        'hide_bursts': request.args.get('hide_bursts', default_hide_bursts if is_fresh_visit else '0'),
        'hide_duplicates': request.args.get('hide_duplicates', default_hide_duplicates if is_fresh_visit else '0'),
        'hide_details': request.args.get('hide_details', default_hide_details if is_fresh_visit else ''),
        # Legacy toggles (for backward compatibility)
        'burst_only': request.args.get('burst_only', ''),
        'no_blink': request.args.get('no_blink', ''),
        # Filename search
        'search': request.args.get('search', ''),
        # Tag filter
        'tag': request.args.get('tag', ''),
        # Person filter (face recognition)
        'person': request.args.get('person', ''),
        # Score ranges (may be set by normalize_params from semantic 'quality')
        'min_score': normalized.get('min_score', ''),
        'max_score': request.args.get('max_score', '', type=str),
        'min_aesthetic': request.args.get('min_aesthetic', '', type=str),
        'max_aesthetic': request.args.get('max_aesthetic', '', type=str),
        'min_sharpness': request.args.get('min_sharpness', '', type=str),
        'max_sharpness': request.args.get('max_sharpness', '', type=str),
        'min_exposure': request.args.get('min_exposure', '', type=str),
        'max_exposure': request.args.get('max_exposure', '', type=str),
        # Face filters (may be set by normalize_params from semantic 'type')
        'min_face_count': normalized.get('min_face_count', ''),
        'max_face_count': normalized.get('max_face_count', ''),
        'min_face_ratio': normalized.get('min_face_ratio', ''),
        'max_face_ratio': normalized.get('max_face_ratio', ''),
        'min_face_quality': request.args.get('min_face_quality', '', type=str),
        'max_face_quality': request.args.get('max_face_quality', '', type=str),
        'min_eye_sharpness': request.args.get('min_eye_sharpness', '', type=str),
        'max_eye_sharpness': request.args.get('max_eye_sharpness', '', type=str),
        # Technical settings
        'min_iso': request.args.get('min_iso', '', type=str),
        'max_iso': request.args.get('max_iso', '', type=str),
        'min_fstop': request.args.get('min_fstop', '', type=str),
        'max_fstop': request.args.get('max_fstop', '', type=str),
        'min_focal': request.args.get('min_focal', '', type=str),
        'max_focal': request.args.get('max_focal', '', type=str),
        # Date range
        'date_from': request.args.get('date_from', ''),
        'date_to': request.args.get('date_to', ''),
        # B&W filter (from normalized type=bw)
        'is_monochrome': normalized.get('is_monochrome', ''),
        # Category filter (from type selection)
        'category': normalized.get('category', ''),
        # Type-derived filters
        'min_aggregate': normalized.get('min_aggregate', ''),
        'max_luminance': normalized.get('max_luminance', ''),
        'is_silhouette': normalized.get('is_silhouette', ''),
        'require_tags': normalized.get('require_tags', ''),
        'exclude_tags': normalized.get('exclude_tags', ''),
        'exclude_art': normalized.get('exclude_art', ''),
        'top_picks_filter': normalized.get('top_picks_filter', ''),
        # Rating filters
        'min_rating': request.args.get('min_rating', ''),
        'favorites_only': request.args.get('favorites_only', ''),
        'hide_rejected': request.args.get('hide_rejected', '1' if defaults_cfg.get('hide_rejected', True) and is_fresh_visit else ''),
        'show_rejected': request.args.get('show_rejected', ''),
        # New metrics filters
        'min_dynamic_range': request.args.get('min_dynamic_range', '', type=str),
        'max_dynamic_range': request.args.get('max_dynamic_range', '', type=str),
        'min_contrast': request.args.get('min_contrast', '', type=str),
        'max_contrast': request.args.get('max_contrast', '', type=str),
        'min_noise': request.args.get('min_noise', '', type=str),
        'max_noise': request.args.get('max_noise', '', type=str),
        # Additional score filters
        'min_color': request.args.get('min_color', '', type=str),
        'max_color': request.args.get('max_color', '', type=str),
        'min_composition': request.args.get('min_composition', '', type=str),
        'max_composition': request.args.get('max_composition', '', type=str),
        'min_face_sharpness': request.args.get('min_face_sharpness', '', type=str),
        'max_face_sharpness': request.args.get('max_face_sharpness', '', type=str),
        'min_isolation': request.args.get('min_isolation', '', type=str),
        'max_isolation': request.args.get('max_isolation', '', type=str),
        'min_luminance': request.args.get('min_luminance', '', type=str),
        'min_histogram_spread': request.args.get('min_histogram_spread', '', type=str),
        'max_histogram_spread': request.args.get('max_histogram_spread', '', type=str),
        'min_power_point': request.args.get('min_power_point', '', type=str),
        'max_power_point': request.args.get('max_power_point', '', type=str),
        # Composition pattern filter (SAMP-Net)
        'composition_pattern': request.args.get('composition_pattern', ''),
    }

    # Apply type filters whenever a type is selected (from URL or default)
    # Only set filter values that aren't already explicitly set by user
    if params.get('type') in TYPE_FILTERS:
        for key, value in TYPE_FILTERS[params['type']].items():
            if not params.get(key):
                params[key] = value

    clean_args = {k: v for k, v in request.args.items() if k != 'page'}

    # 3. Build WHERE clauses using shared helper
    conn = get_db_connection()
    user_id = get_session_user_id()
    from_clause, from_params = get_photos_from_clause(user_id)
    where_clauses, sql_params = _build_gallery_where(params, conn, user_id=user_id)

    # Prepend FROM params (e.g., user_id for JOIN)
    all_params = from_params + sql_params

    # Build WHERE string
    where_str = ""
    if where_clauses:
        where_str = " WHERE " + " AND ".join(where_clauses)

    try:
        # 4. Calculate Pagination (use cached count to avoid repeated full-table scans)
        total_count = get_cached_count(conn, where_str, all_params, from_clause=from_clause)
        total_pages = max(1, math.ceil(total_count / per_page))

        # Sort validation - support multiple sort columns via sort_list
        if 'sort_list' in params:
            # Multi-column sort from TYPE_DEFAULT_SORTS
            order_parts = []
            for col, direction in params['sort_list']:
                if col in VALID_SORT_COLS:
                    dir_str = "ASC" if direction == "ASC" else "DESC"
                    order_parts.append(f"{col} {dir_str}")
            base_order = ", ".join(order_parts) if order_parts else "aggregate DESC"
            # Add path as tie-breaker for deterministic pagination (prevents duplicates in infinite scroll)
            order_by_clause = f"{base_order}, path ASC"
        else:
            # Single column sort (user-specified or default)
            sort_col = params['sort'] if params['sort'] in VALID_SORT_COLS else "aggregate"
            sort_dir = "ASC" if params['dir'] == "ASC" else "DESC"
            # Add path as tie-breaker for deterministic pagination (prevents duplicates in infinite scroll)
            order_by_clause = f"{sort_col} {sort_dir}, path ASC"

        # 5. Fetch Results (exclude BLOB columns to avoid bytes in template)
        offset = (page - 1) * per_page

        existing_cols = get_existing_columns(conn)
        # Build select cols, replacing preference columns with multi-user expressions
        pref_cols = get_preference_columns(user_id)
        pref_col_names = {'star_rating', 'is_favorite', 'is_rejected'}
        select_cols = list(PHOTO_BASE_COLS)
        for c in PHOTO_OPTIONAL_COLS:
            if c in existing_cols:
                if c in pref_col_names:
                    select_cols.append(f"{pref_cols[c]} as {c}")
                else:
                    select_cols.append(c)

        # Add computed top_picks_score column when needed for sorting or display
        needs_top_picks_score = (
            params.get('top_picks_filter') == '1' or
            'top_picks_score' in order_by_clause
        )
        if needs_top_picks_score:
            top_picks_expr = get_top_picks_score_sql()
            select_cols.append(f"({top_picks_expr}) as top_picks_score")

        query = f"SELECT {', '.join(select_cols)} FROM {from_clause}{where_str} ORDER BY {order_by_clause} LIMIT ? OFFSET ?"
        rows = conn.execute(query, all_params + [per_page, offset]).fetchall()

        # Convert to dicts and pre-split tags for template efficiency
        tags_limit = VIEWER_CONFIG['display']['tags_per_photo']
        photos = split_photo_tags(rows, tags_limit)

        # Batch fetch person associations and unassigned face counts
        attach_person_data(photos, conn)

    except Exception as e:
        print(f"Error executing query: {e}")
        return f"Database Error: {e}"
    finally:
        conn.close()

    # Count active filters (exclude display/sort params and internal params)
    # Sort/display params that shouldn't appear in chips
    sort_params = {'sort', 'dir', 'per_page', 'burst_only', 'no_blink'}
    # Toolbar params - visible in header, don't need chips (except person which can be truncated)
    toolbar_params = {'type', 'tag', 'search'}
    # Also exclude params that are derived from semantic params
    derived_params = set()
    if params.get('quality'):
        derived_params.add('min_score')  # Derived from quality
    if params.get('type'):
        # All params that can be derived from type selection
        derived_params.update(['min_face_count', 'max_face_count', 'min_face_ratio', 'max_face_ratio',
                               'is_monochrome', 'min_aggregate', 'max_luminance', 'is_silhouette',
                               'require_tags', 'exclude_tags', 'exclude_art', 'top_picks_filter', 'category'])

    # Params to exclude from chip removal URLs (only derived params - display params should be preserved)
    excluded_url_params = derived_params

    # Build person name lookup for filter chips
    filter_options = get_filter_options()
    person_names = {str(p[0]): (p[1] or f'Person {p[0]}') for p in filter_options.get('persons', [])}

    # Numeric filter params where "0" means "no filter"
    numeric_filter_params = {
        'min_score', 'max_score', 'min_aesthetic', 'max_aesthetic', 'min_sharpness', 'max_sharpness',
        'min_exposure', 'max_exposure', 'min_color', 'max_color', 'min_composition', 'max_composition',
        'min_face_count', 'max_face_count', 'min_face_quality', 'max_face_quality',
        'min_eye_sharpness', 'max_eye_sharpness', 'min_face_ratio', 'max_face_ratio',
        'min_face_sharpness', 'max_face_sharpness', 'min_iso', 'max_iso', 'min_fstop', 'max_fstop',
        'min_focal', 'max_focal', 'min_dynamic_range', 'max_dynamic_range', 'min_contrast', 'max_contrast',
        'min_noise', 'max_noise', 'min_isolation', 'max_isolation', 'min_luminance', 'max_luminance',
        'min_histogram_spread', 'max_histogram_spread', 'min_power_point', 'max_power_point'
    }

    active_filters = {}
    for k, v in params.items():
        if v and k not in sort_params and k not in toolbar_params and k not in derived_params:
            # Skip numeric filters with value "0" (means no filter)
            if k in numeric_filter_params and v == '0':
                continue
            # Toggle params: only show chip when enabled (value='1')
            if k in ('hide_blinks', 'hide_bursts', 'hide_duplicates', 'hide_details', 'hide_rejected', 'show_rejected', 'favorites_only'):
                if v == '1':
                    active_filters[k] = 'enabled'
                continue  # Skip if not '1'
            # Use semantic labels where applicable
            if k == 'quality':
                label = dict(QUALITY_LEVELS).get(v, v)
                active_filters[k] = label
            elif k == 'person':
                for pid in v.split(','):
                    pid = pid.strip()
                    if pid:
                        label = person_names.get(pid, f'Person {pid}')
                        active_filters[f'person:{pid}'] = label
                continue
            else:
                active_filters[k] = v

    active_filter_count = len(active_filters)

    # Build filter labels for chips (using translations)
    filter_labels = {
        # Basic filters (from filter_labels section)
        'quality': translate('filter_labels.quality'),
        'type': translate('filter_labels.type'),
        'camera': translate('filter_labels.camera'),
        'lens': translate('filter_labels.lens'),
        'search': translate('filter_labels.search'),
        'tag': translate('filter_labels.tag'),
        'person': translate('filter_labels.person'),
        'min_score': translate('filter_labels.min_score'),
        'max_score': translate('filter_labels.max_score'),
        'composition_pattern': translate('filter_labels.composition_pattern'),
        # Drawer fields
        'min_aesthetic': translate('drawer.fields.min_aesthetic'),
        'max_aesthetic': translate('drawer.fields.max_aesthetic'),
        'min_sharpness': translate('drawer.fields.min_sharpness'),
        'max_sharpness': translate('drawer.fields.max_sharpness'),
        'min_exposure': translate('drawer.fields.min_exposure'),
        'max_exposure': translate('drawer.fields.max_exposure'),
        'min_face_count': translate('drawer.fields.min_faces'),
        'max_face_count': translate('drawer.fields.max_faces'),
        'min_face_ratio': translate('drawer.fields.min_face_ratio'),
        'max_face_ratio': translate('drawer.fields.max_face_ratio'),
        'min_face_quality': translate('drawer.fields.min_face_quality'),
        'max_face_quality': translate('drawer.fields.max_face_quality'),
        'min_eye_sharpness': translate('drawer.fields.min_eye_sharpness'),
        'max_eye_sharpness': translate('drawer.fields.max_eye_sharpness'),
        'min_iso': translate('drawer.fields.min_iso'),
        'max_iso': translate('drawer.fields.max_iso'),
        'min_fstop': translate('drawer.fields.min_fstop'),
        'max_fstop': translate('drawer.fields.max_fstop'),
        'min_focal': translate('drawer.fields.min_focal'),
        'max_focal': translate('drawer.fields.max_focal'),
        'date_from': translate('drawer.fields.from_date'),
        'date_to': translate('drawer.fields.to_date'),
        'min_dynamic_range': translate('drawer.fields.min_dynamic_range'),
        'max_dynamic_range': translate('drawer.fields.max_dynamic_range'),
        'min_contrast': translate('drawer.fields.min_contrast'),
        'max_contrast': translate('drawer.fields.max_contrast'),
        'min_noise': translate('drawer.fields.min_noise'),
        'max_noise': translate('drawer.fields.max_noise'),
        'min_face_sharpness': translate('drawer.fields.min_face_sharpness'),
        'max_face_sharpness': translate('drawer.fields.max_face_sharpness'),
        'min_color': translate('drawer.fields.min_color'),
        'max_color': translate('drawer.fields.max_color'),
        'min_composition': translate('drawer.fields.min_composition'),
        'max_composition': translate('drawer.fields.max_composition'),
        'min_isolation': translate('drawer.fields.min_isolation'),
        'max_isolation': translate('drawer.fields.max_isolation'),
        'min_luminance': translate('drawer.fields.min_luminance'),
        'max_luminance': translate('drawer.fields.max_luminance'),
        'min_histogram_spread': translate('drawer.fields.min_hist_spread'),
        'max_histogram_spread': translate('drawer.fields.max_hist_spread'),
        'min_power_point': translate('drawer.fields.min_power_point'),
        'max_power_point': translate('drawer.fields.max_power_point'),
        # Rating filters
        'hide_rejected': translate('rating.hide_rejected'),
        'favorites_only': translate('rating.favorites_only'),
        'show_rejected': translate('rating.show_rejected'),
        'min_rating': translate('rating.min_rating'),
    }

    # Get sort column info for template
    sort_col = params['sort']
    sort_label = next((label for val, label in SORT_OPTIONS if val == sort_col), 'Score')

    return render_template(
        'gallery.html',
        photos=photos,
        params=params,
        options=filter_options,
        sort_options=SORT_OPTIONS,
        sort_options_grouped=SORT_OPTIONS_GROUPED,
        quality_levels=QUALITY_LEVELS,
        photo_types=get_photo_types(
            hide_blinks=(params['hide_blinks'] == '1'),
            hide_bursts=(params['hide_bursts'] == '1'),
            hide_duplicates=(params.get('hide_duplicates') == '1')
        ),
        page=page,
        total_pages=total_pages,
        total_count=total_count,
        clean_args=clean_args,
        active_filter_count=active_filter_count,
        active_filters=active_filters,
        filter_labels=filter_labels,
        excluded_url_params=excluded_url_params,
        sort_col=sort_col,
        editing_enabled=is_edition_enabled(),
        edition_authenticated=is_edition_authenticated(),
        sort_label=sort_label,
        viewer_config=VIEWER_CONFIG,
        # Multi-user template variables
        is_multi_user=is_multi_user_enabled(),
        user_display_name=session.get('user_display_name', ''),
        user_role=session.get('user_role', ''),
    )


@gallery_bp.route('/api/type_counts')
def api_type_counts():
    """API endpoint for lazy-loading photo type counts.

    Returns type counts as JSON for async loading in the sidebar.
    This avoids blocking the initial page render with expensive COUNT queries.
    """
    hide_blinks = request.args.get('hide_blinks', '0') == '1'
    hide_bursts = request.args.get('hide_bursts', '0') == '1'
    hide_duplicates = request.args.get('hide_duplicates', '0') == '1'
    types = get_photo_types(hide_blinks, hide_bursts, hide_duplicates)
    return jsonify({
        'types': [{'id': type_id, 'label': label} for type_id, label in types]
    })



@gallery_bp.route('/api/photos')
def api_photos():
    """API endpoint for infinite scroll - returns JSON with photo data.

    Uses the same filter logic as index() via shared _build_gallery_where().
    """
    default_per_page = VIEWER_CONFIG['pagination']['default_per_page']
    per_page = request.args.get('per_page', default_per_page, type=int)
    page = request.args.get('page', 1, type=int)

    # Get configurable defaults
    defaults_cfg = VIEWER_CONFIG['defaults']
    default_type = defaults_cfg.get('type', '')

    # Build params dict with ALL filter values (must match index() exactly)
    normalized = normalize_params(request.args)

    params = {
        'sort': normalized.get('sort') or request.args.get('sort', defaults_cfg['sort']),
        'dir': request.args.get('dir', defaults_cfg['sort_direction']),
        'camera': request.args.get('camera', ''),
        'lens': request.args.get('lens', ''),
        'per_page': per_page,
        'quality': request.args.get('quality', ''),
        # Don't apply default type when filtering by person (show all photo types for that person)
        'type': request.args.get('type', '' if request.args.get('person') else default_type),
        'hide_blinks': request.args.get('hide_blinks', '0'),
        'hide_bursts': request.args.get('hide_bursts', '0'),
        'hide_duplicates': request.args.get('hide_duplicates', '0'),
        'burst_only': request.args.get('burst_only', ''),
        'no_blink': request.args.get('no_blink', ''),
        'search': request.args.get('search', ''),
        'tag': request.args.get('tag', ''),
        'person': request.args.get('person', ''),
        'min_score': normalized.get('min_score', ''),
        'max_score': request.args.get('max_score', '', type=str),
        'min_aesthetic': request.args.get('min_aesthetic', '', type=str),
        'max_aesthetic': request.args.get('max_aesthetic', '', type=str),
        'min_sharpness': request.args.get('min_sharpness', '', type=str),
        'max_sharpness': request.args.get('max_sharpness', '', type=str),
        'min_exposure': request.args.get('min_exposure', '', type=str),
        'max_exposure': request.args.get('max_exposure', '', type=str),
        'min_face_count': normalized.get('min_face_count', ''),
        'max_face_count': normalized.get('max_face_count', ''),
        'min_face_ratio': normalized.get('min_face_ratio', ''),
        'max_face_ratio': normalized.get('max_face_ratio', ''),
        'min_face_quality': request.args.get('min_face_quality', '', type=str),
        'max_face_quality': request.args.get('max_face_quality', '', type=str),
        'min_eye_sharpness': request.args.get('min_eye_sharpness', '', type=str),
        'max_eye_sharpness': request.args.get('max_eye_sharpness', '', type=str),
        'min_iso': request.args.get('min_iso', '', type=str),
        'max_iso': request.args.get('max_iso', '', type=str),
        'min_fstop': request.args.get('min_fstop', '', type=str),
        'max_fstop': request.args.get('max_fstop', '', type=str),
        'min_focal': request.args.get('min_focal', '', type=str),
        'max_focal': request.args.get('max_focal', '', type=str),
        'date_from': request.args.get('date_from', ''),
        'date_to': request.args.get('date_to', ''),
        'is_monochrome': normalized.get('is_monochrome', ''),
        'category': normalized.get('category', ''),
        'min_aggregate': normalized.get('min_aggregate', ''),
        'max_luminance': normalized.get('max_luminance', ''),
        'is_silhouette': normalized.get('is_silhouette', ''),
        'require_tags': normalized.get('require_tags', ''),
        'exclude_tags': normalized.get('exclude_tags', ''),
        'exclude_art': normalized.get('exclude_art', ''),
        'top_picks_filter': normalized.get('top_picks_filter', ''),
        'min_rating': request.args.get('min_rating', ''),
        'favorites_only': request.args.get('favorites_only', ''),
        'hide_rejected': request.args.get('hide_rejected', ''),
        'show_rejected': request.args.get('show_rejected', ''),
        'min_dynamic_range': request.args.get('min_dynamic_range', '', type=str),
        'max_dynamic_range': request.args.get('max_dynamic_range', '', type=str),
        'min_contrast': request.args.get('min_contrast', '', type=str),
        'max_contrast': request.args.get('max_contrast', '', type=str),
        'min_noise': request.args.get('min_noise', '', type=str),
        'max_noise': request.args.get('max_noise', '', type=str),
        'min_color': request.args.get('min_color', '', type=str),
        'max_color': request.args.get('max_color', '', type=str),
        'min_composition': request.args.get('min_composition', '', type=str),
        'max_composition': request.args.get('max_composition', '', type=str),
        'min_face_sharpness': request.args.get('min_face_sharpness', '', type=str),
        'max_face_sharpness': request.args.get('max_face_sharpness', '', type=str),
        'min_isolation': request.args.get('min_isolation', '', type=str),
        'max_isolation': request.args.get('max_isolation', '', type=str),
        'min_luminance': request.args.get('min_luminance', '', type=str),
        'min_histogram_spread': request.args.get('min_histogram_spread', '', type=str),
        'max_histogram_spread': request.args.get('max_histogram_spread', '', type=str),
        'min_power_point': request.args.get('min_power_point', '', type=str),
        'max_power_point': request.args.get('max_power_point', '', type=str),
        'composition_pattern': request.args.get('composition_pattern', ''),
    }

    # Apply type filters (same as index())
    if params.get('type') in TYPE_FILTERS:
        for key, value in TYPE_FILTERS[params['type']].items():
            if not params.get(key):
                params[key] = value

    # Build WHERE clauses using shared helper (identical to index())
    conn = get_db_connection()
    user_id = get_session_user_id()
    from_clause, from_params = get_photos_from_clause(user_id)
    where_clauses, sql_params = _build_gallery_where(params, conn, user_id=user_id)
    all_params = from_params + sql_params
    where_str = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    # Build ORDER BY
    sort_col = params['sort'] if params['sort'] in VALID_SORT_COLS else 'aggregate'
    sort_dir = 'ASC' if params['dir'] == 'ASC' else 'DESC'
    order_by_clause = f"{sort_col} {sort_dir}, path ASC"

    try:
        total_count = get_cached_count(conn, where_str, all_params, from_clause=from_clause)
        total_pages = max(1, math.ceil(total_count / per_page))
        offset = (page - 1) * per_page

        # Use shared column lists (same as index())
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

        # Add computed top_picks_score column when needed
        needs_top_picks_score = (
            params.get('top_picks_filter') == '1' or
            'top_picks_score' in order_by_clause
        )
        if needs_top_picks_score:
            top_picks_expr = get_top_picks_score_sql()
            select_cols.append(f"({top_picks_expr}) as top_picks_score")

        query = f"SELECT {', '.join(select_cols)} FROM {from_clause}{where_str} ORDER BY {order_by_clause} LIMIT ? OFFSET ?"
        rows = conn.execute(query, all_params + [per_page, offset]).fetchall()

        # Use shared helpers for tag splitting and person data
        tags_limit = VIEWER_CONFIG['display']['tags_per_photo']
        photos = split_photo_tags(rows, tags_limit)

        # Add formatted date for API consumers
        for photo in photos:
            photo['date_formatted'] = format_date(photo.get('date_taken'))

        attach_person_data(photos, conn)

    except Exception as e:
        import traceback
        print(f"API photos error: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

    # Sanitize data for JSON (handle Infinity/NaN which are not valid JSON)
    for photo in photos:
        for key, value in photo.items():
            if isinstance(value, float) and (math.isinf(value) or math.isnan(value)):
                photo[key] = None

    return jsonify({
        'photos': photos,
        'page': page,
        'total_pages': total_pages,
        'total_count': total_count,
        'has_more': page < total_pages,
        'sort_col': sort_col,
    })




@gallery_bp.route('/api/similar_photos/<path:photo_path>')
def api_similar_photos(photo_path):
    """Find photos similar to the given photo using multiple factors.

    Query params:
        limit: Max number of results (default: 20)
        clip_weight: Weight for CLIP embedding similarity (default: 0.4)
        person_weight: Weight for shared persons (default: 0.3)
        date_weight: Weight for date proximity (default: 0.2)
        score_weight: Weight for score similarity (default: 0.1)

    Returns JSON with similar photos ranked by combined similarity score.
    """
    # Check if feature is enabled
    viewer_config = load_viewer_config()
    if not viewer_config.get('features', {}).get('show_similar_button', True):
        return jsonify({'error': 'Similar photos feature is disabled'}), 403

    # Lazy import numpy only when feature is used
    import numpy as np

    limit = request.args.get('limit', 20, type=int)
    clip_weight = request.args.get('clip_weight', 0.4, type=float)
    person_weight = request.args.get('person_weight', 0.3, type=float)
    date_weight = request.args.get('date_weight', 0.2, type=float)
    score_weight = request.args.get('score_weight', 0.1, type=float)

    conn = get_db_connection()
    try:
        # Get source photo data
        source = conn.execute("""
            SELECT path, clip_embedding, date_taken, aggregate, aesthetic, comp_score
            FROM photos WHERE path = ?
        """, (photo_path,)).fetchone()

        if not source:
            return jsonify({'error': 'Photo not found'}), 404

        source = dict(source)
        source_embedding = None
        if source.get('clip_embedding'):
            source_embedding = np.frombuffer(source['clip_embedding'], dtype=np.float32)

        # Get persons in source photo
        source_persons = set()
        person_rows = conn.execute("""
            SELECT person_id FROM faces WHERE photo_path = ? AND person_id IS NOT NULL
        """, (photo_path,)).fetchall()
        for row in person_rows:
            source_persons.add(row[0])

        # Get all other photos with embeddings
        candidates = conn.execute("""
            SELECT path, filename, clip_embedding, date_taken, aggregate, aesthetic, comp_score, thumbnail
            FROM photos
            WHERE path != ? AND clip_embedding IS NOT NULL
        """, (photo_path,)).fetchall()

        results = []
        for cand in candidates:
            cand_dict = dict(cand)
            cand_path = cand_dict['path']
            similarity_breakdown = {}
            total_similarity = 0

            # 1. CLIP embedding similarity (cosine)
            if source_embedding is not None and cand_dict.get('clip_embedding'):
                cand_embedding = np.frombuffer(cand_dict['clip_embedding'], dtype=np.float32)
                cosine_sim = float(np.dot(source_embedding, cand_embedding) /
                                  (np.linalg.norm(source_embedding) * np.linalg.norm(cand_embedding) + 1e-10))
                # Normalize to 0-1 range (cosine is -1 to 1)
                clip_sim = (cosine_sim + 1) / 2
                similarity_breakdown['clip'] = round(clip_sim, 3)
                total_similarity += clip_sim * clip_weight

            # 2. Shared persons
            if source_persons:
                cand_persons = set()
                cp_rows = conn.execute("""
                    SELECT person_id FROM faces WHERE photo_path = ? AND person_id IS NOT NULL
                """, (cand_path,)).fetchall()
                for row in cp_rows:
                    cand_persons.add(row[0])

                if cand_persons:
                    shared = len(source_persons & cand_persons)
                    person_sim = shared / max(len(source_persons), len(cand_persons))
                    similarity_breakdown['persons'] = round(person_sim, 3)
                    total_similarity += person_sim * person_weight

            # 3. Date proximity (same day = 1, same week = 0.5, same month = 0.2)
            if source.get('date_taken') and cand_dict.get('date_taken'):
                try:
                    from datetime import datetime
                    src_date = datetime.strptime(source['date_taken'][:19], '%Y:%m:%d %H:%M:%S')
                    cand_date = datetime.strptime(cand_dict['date_taken'][:19], '%Y:%m:%d %H:%M:%S')
                    days_diff = abs((src_date - cand_date).days)
                    if days_diff == 0:
                        date_sim = 1.0
                    elif days_diff <= 7:
                        date_sim = 0.5
                    elif days_diff <= 30:
                        date_sim = 0.2
                    else:
                        date_sim = max(0, 1 - days_diff / 365)  # Decay over a year
                    similarity_breakdown['date'] = round(date_sim, 3)
                    total_similarity += date_sim * date_weight
                except Exception:
                    pass

            # 4. Score similarity (how close are aggregate scores)
            if source.get('aggregate') and cand_dict.get('aggregate'):
                score_diff = abs(source['aggregate'] - cand_dict['aggregate'])
                score_sim = max(0, 1 - score_diff / 10)  # 10-point scale
                similarity_breakdown['score'] = round(score_sim, 3)
                total_similarity += score_sim * score_weight

            if total_similarity > 0:
                results.append({
                    'path': cand_path,
                    'filename': cand_dict.get('filename'),
                    'similarity': round(total_similarity, 4),
                    'breakdown': similarity_breakdown,
                    'aggregate': cand_dict.get('aggregate'),
                    'aesthetic': cand_dict.get('aesthetic'),
                    'date_taken': cand_dict.get('date_taken'),
                })

        # Sort by similarity and limit
        results.sort(key=lambda x: x['similarity'], reverse=True)
        results = results[:limit]

        return jsonify({
            'source': photo_path,
            'weights': {
                'clip': clip_weight,
                'person': person_weight,
                'date': date_weight,
                'score': score_weight
            },
            'similar': results
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()
