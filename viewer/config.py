import os
import json
import math
import time
import secrets

# --- CONFIG & SHARE SECRET (single parse of scoring_config.json) ---
_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scoring_config.json')


def _load_and_ensure_share_secret():
    """Load scoring_config.json once, ensure share_secret exists. Returns (config_dict, secret)."""
    try:
        with open(_CONFIG_PATH) as f:
            config = json.load(f)
    except Exception:
        config = {}
    if 'share_secret' not in config or not config['share_secret']:
        config['share_secret'] = secrets.token_hex(32)
        with open(_CONFIG_PATH, 'w') as f:
            json.dump(config, f, indent=2)
    return config, config['share_secret']


_FULL_CONFIG, _share_secret = _load_and_ensure_share_secret()


# --- VIEWER CONFIG ---
def load_viewer_config(config=None):
    """Load viewer settings, merging defaults with config.

    Args:
        config: Already-parsed scoring_config.json dict. If None, reads from disk.
    """
    defaults = {
        'sort_options': {
            'General': [
                {'column': 'aggregate', 'label': 'Aggregate Score'},
                {'column': 'aesthetic', 'label': 'Aesthetic'},
                {'column': 'date_taken', 'label': 'Date Taken'}
            ],
            'Face Metrics': [
                {'column': 'face_quality', 'label': 'Face Quality'},
                {'column': 'eye_sharpness', 'label': 'Eye Sharpness'},
                {'column': 'face_sharpness', 'label': 'Face Sharpness'},
                {'column': 'face_ratio', 'label': 'Face Ratio'},
                {'column': 'face_count', 'label': 'Face Count'}
            ],
            'Technical': [
                {'column': 'tech_sharpness', 'label': 'Tech Sharpness'},
                {'column': 'contrast_score', 'label': 'Contrast'},
                {'column': 'noise_sigma', 'label': 'Noise Level'}
            ],
            'Color': [
                {'column': 'color_score', 'label': 'Color Score'},
                {'column': 'mean_saturation', 'label': 'Saturation'}
            ],
            'Exposure': [
                {'column': 'exposure_score', 'label': 'Exposure Score'},
                {'column': 'mean_luminance', 'label': 'Mean Luminance'},
                {'column': 'histogram_spread', 'label': 'Histogram Spread'},
                {'column': 'dynamic_range_stops', 'label': 'Dynamic Range'}
            ],
            'Composition': [
                {'column': 'comp_score', 'label': 'Composition Score'},
                {'column': 'power_point_score', 'label': 'Power Point Score'},
                {'column': 'leading_lines_score', 'label': 'Leading Lines'},
                {'column': 'isolation_bonus', 'label': 'Isolation Bonus'}
            ],
            'Camera': [
                {'column': 'f_stop', 'label': 'F-Stop'},
                {'column': 'focal_length', 'label': 'Focal Length'},
                {'column': 'shutter_speed', 'label': 'Shutter Speed'}
            ]
        },
        'pagination': {'default_per_page': 50},
        'dropdowns': {'max_cameras': 50, 'max_lenses': 50, 'max_persons': 50, 'max_tags': 20},
        'display': {'tags_per_photo': 3, 'card_width_px': 168, 'image_width_px': 160},
        'face_thumbnails': {'output_size_px': 64, 'jpeg_quality': 80, 'crop_padding_ratio': 0.2, 'min_crop_size_px': 20},
        'quality_thresholds': {'good': 6, 'great': 7, 'excellent': 8, 'best': 9},
        'photo_types': {'top_picks_min_score': 7, 'low_light_max_luminance': 0.2},
        'defaults': {'hide_blinks': True, 'hide_bursts': True, 'hide_duplicates': True, 'hide_details': True, 'hide_rejected': True, 'sort': 'aggregate', 'sort_direction': 'DESC'},
        'features': {'show_similar_button': True, 'show_merge_suggestions': True, 'show_rating_controls': True, 'show_rating_badge': True},
        'cache_ttl_seconds': 3600,
        'notification_duration_ms': 2000
    }
    if config is None:
        try:
            with open(_CONFIG_PATH) as f:
                config = json.load(f)
        except Exception:
            return defaults
    viewer = config.get('viewer', {})
    # Merge with defaults
    for key, value in defaults.items():
        if key not in viewer:
            viewer[key] = value
        elif isinstance(value, dict):
            for k, v in value.items():
                if k not in viewer[key]:
                    viewer[key][k] = v
    return viewer


VIEWER_CONFIG = load_viewer_config(_FULL_CONFIG)


# --- MULTI-USER SUPPORT ---

def is_multi_user_enabled():
    """Check if multi-user mode is configured.

    Returns True if scoring_config.json has a 'users' key with at least one user entry
    (keys other than 'shared_directories').
    """
    users = _FULL_CONFIG.get('users', {})
    return any(k != 'shared_directories' for k in users)


def get_user_config(username):
    """Get config dict for a specific user. Returns None if user not found."""
    users = _FULL_CONFIG.get('users', {})
    user = users.get(username)
    if user is None or not isinstance(user, dict):
        return None
    return user


def get_user_directories(username):
    """Get list of all directories a user can access (own + shared).

    Returns empty list if user not found.
    """
    users = _FULL_CONFIG.get('users', {})
    user = users.get(username)
    if user is None or not isinstance(user, dict):
        return []
    user_dirs = list(user.get('directories', []))
    shared_dirs = list(users.get('shared_directories', []))
    return user_dirs + shared_dirs


def get_all_scan_directories():
    """Get all configured directories (all users + shared). For scan UI."""
    users = _FULL_CONFIG.get('users', {})
    dirs = set()
    for key, val in users.items():
        if key == 'shared_directories':
            dirs.update(val)
        elif isinstance(val, dict):
            dirs.update(val.get('directories', []))
    return sorted(dirs)


def reload_config():
    """Reload scoring_config.json from disk. Used after --add-user modifies it."""
    global _FULL_CONFIG, _share_secret, VIEWER_CONFIG
    _FULL_CONFIG, _share_secret = _load_and_ensure_share_secret()
    VIEWER_CONFIG = load_viewer_config(_FULL_CONFIG)


def map_disk_path(db_path):
    """Map a database path to a local disk path using viewer.path_mapping config.

    Applies prefix replacements and normalizes path separators for the current OS.
    Config keys can use forward slashes for readability (backslashes are normalized).
    Example config: {"//NAS/share/Photos": "/volume1/Photos"}
    """
    path_mapping = VIEWER_CONFIG.get('path_mapping', {})
    for prefix_from, prefix_to in path_mapping.items():
        if db_path.startswith(prefix_from):
            db_path = prefix_to + db_path[len(prefix_from):]
            break
        # Also try with normalized separators (Windows -> Unix)
        normalized = db_path.replace('\\', '/')
        prefix_normalized = prefix_from.replace('\\', '/')
        if normalized.startswith(prefix_normalized):
            db_path = prefix_to + normalized[len(prefix_normalized):]
            break
    # Normalize separators for current OS
    return db_path.replace('\\', os.sep).replace('/', os.sep)


def get_comparison_mode_settings():
    """Get comparison mode settings from config."""
    defaults = {
        'min_comparisons_for_optimization': 30,
        'pair_selection_strategy': 'uncertainty',
        'show_current_scores': False
    }
    settings = _FULL_CONFIG.get('viewer', {}).get('comparison_mode', {})
    for key, value in defaults.items():
        if key not in settings:
            settings[key] = value
    return settings


# --- CACHES ---

# Simple TTL cache for filter options
_filter_options_cache = {'data': None, 'expires': 0}


def invalidate_filter_cache():
    """Invalidate filter options cache so new data appears on next request."""
    _filter_options_cache['data'] = None

# Cache for existing columns (loaded once at startup, rarely changes)
_existing_columns_cache = None

# Cache for photo type counts (keyed by hide_blinks/hide_bursts/hide_duplicates combination)
_photo_types_cache = {'data': {}, 'expires': 0}

# Cache for COUNT query results (avoids repeated full-table scans)
_count_cache = {}
COUNT_CACHE_TTL = 300  # seconds - 5 minute TTL for performance on large databases

# Track if photo_tags lookup table is available (checked once at startup)
_photo_tags_available = None

# Cache for stats API responses
_stats_cache = {}  # key -> {'data': ..., 'expires': float}


def _sanitize_stats(obj):
    """Replace NaN/Infinity floats with None for JSON serialization."""
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize_stats(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_stats(v) for v in obj]
    return obj


def _get_stats_cached(cache_key, compute_fn):
    now = time.time()
    cached = _stats_cache.get(cache_key)
    if cached and now < cached['expires']:
        return cached['data']
    data = _sanitize_stats(compute_fn())
    _stats_cache[cache_key] = {'data': data, 'expires': now + VIEWER_CONFIG['cache_ttl_seconds']}
    return data

# --- CORRELATION QUERY WHITELISTS ---
CORRELATION_X_AXES = {
    'iso': {
        'sql': "CASE WHEN ISO<=100 THEN '100' WHEN ISO<=200 THEN '200' WHEN ISO<=400 THEN '400' "
               "WHEN ISO<=800 THEN '800' WHEN ISO<=1600 THEN '1600' WHEN ISO<=3200 THEN '3200' "
               "WHEN ISO<=6400 THEN '6400' WHEN ISO<=12800 THEN '12800' ELSE '25600+' END",
        'sort': 'MIN(ISO)', 'filter': 'ISO IS NOT NULL AND ISO > 0', 'top_n': 10},
    'f_stop': {
        'sql': 'ROUND(f_stop,1)', 'sort': 'x_bucket',
        'filter': 'f_stop IS NOT NULL AND f_stop > 0', 'top_n': 15},
    'focal_length': {
        'sql': "CASE WHEN COALESCE(focal_length_35mm, focal_length)<24 THEN '<24' WHEN COALESCE(focal_length_35mm, focal_length)<=35 THEN '24-35' "
               "WHEN COALESCE(focal_length_35mm, focal_length)<=50 THEN '36-50' WHEN COALESCE(focal_length_35mm, focal_length)<=85 THEN '51-85' "
               "WHEN COALESCE(focal_length_35mm, focal_length)<=135 THEN '86-135' WHEN COALESCE(focal_length_35mm, focal_length)<=200 THEN '136-200' "
               "ELSE '200+' END",
        'sort': 'MIN(COALESCE(focal_length_35mm, focal_length))', 'filter': 'COALESCE(focal_length_35mm, focal_length) IS NOT NULL AND COALESCE(focal_length_35mm, focal_length) > 0', 'top_n': 8},
    'camera_model': {
        'sql': 'camera_model', 'sort': 'COUNT(*) DESC',
        'filter': "camera_model IS NOT NULL AND camera_model != ''", 'top_n': 5},
    'lens_model': {
        'sql': 'lens_model', 'sort': 'COUNT(*) DESC',
        'filter': "lens_model IS NOT NULL AND lens_model != ''", 'top_n': 5},
    'date_month': {
        'sql': "SUBSTR(REPLACE(date_taken,':','-'),1,7)", 'sort': 'x_bucket',
        'filter': "date_taken IS NOT NULL AND date_taken != ''", 'top_n': 24},
    'date_year': {
        'sql': "SUBSTR(date_taken,1,4)", 'sort': 'x_bucket',
        'filter': "date_taken IS NOT NULL AND date_taken != ''", 'top_n': 10},
    'composition_pattern': {
        'sql': 'composition_pattern', 'sort': 'COUNT(*) DESC',
        'filter': "composition_pattern IS NOT NULL AND composition_pattern != ''", 'top_n': 10},
    'category': {
        'sql': 'category', 'sort': 'COUNT(*) DESC',
        'filter': "category IS NOT NULL AND category != ''", 'top_n': 10},
    'aggregate': {
        'sql': "CASE WHEN aggregate<4 THEN '<4' WHEN aggregate<6 THEN '4-6' "
               "WHEN aggregate<7 THEN '6-7' WHEN aggregate<8 THEN '7-8' "
               "WHEN aggregate<9 THEN '8-9' ELSE '9-10' END",
        'sort': 'MIN(aggregate)', 'filter': 'aggregate IS NOT NULL', 'top_n': 6},
    'aesthetic': {
        'sql': "CASE WHEN aesthetic<4 THEN '<4' WHEN aesthetic<6 THEN '4-6' "
               "WHEN aesthetic<7 THEN '6-7' WHEN aesthetic<8 THEN '7-8' "
               "WHEN aesthetic<9 THEN '8-9' ELSE '9-10' END",
        'sort': 'MIN(aesthetic)', 'filter': 'aesthetic IS NOT NULL', 'top_n': 6},
    'tech_sharpness': {
        'sql': "CASE WHEN tech_sharpness<4 THEN '<4' WHEN tech_sharpness<6 THEN '4-6' "
               "WHEN tech_sharpness<7 THEN '6-7' WHEN tech_sharpness<8 THEN '7-8' "
               "WHEN tech_sharpness<9 THEN '8-9' ELSE '9-10' END",
        'sort': 'MIN(tech_sharpness)', 'filter': 'tech_sharpness IS NOT NULL', 'top_n': 6},
    'comp_score': {
        'sql': "CASE WHEN comp_score<4 THEN '<4' WHEN comp_score<6 THEN '4-6' "
               "WHEN comp_score<7 THEN '6-7' WHEN comp_score<8 THEN '7-8' "
               "WHEN comp_score<9 THEN '8-9' ELSE '9-10' END",
        'sort': 'MIN(comp_score)', 'filter': 'comp_score IS NOT NULL', 'top_n': 6},
    'face_quality': {
        'sql': "CASE WHEN face_quality<4 THEN '<4' WHEN face_quality<6 THEN '4-6' "
               "WHEN face_quality<7 THEN '6-7' WHEN face_quality<8 THEN '7-8' "
               "WHEN face_quality<9 THEN '8-9' ELSE '9-10' END",
        'sort': 'MIN(face_quality)', 'filter': 'face_quality IS NOT NULL', 'top_n': 6},
    'color_score': {
        'sql': "CASE WHEN color_score<4 THEN '<4' WHEN color_score<6 THEN '4-6' "
               "WHEN color_score<7 THEN '6-7' WHEN color_score<8 THEN '7-8' "
               "WHEN color_score<9 THEN '8-9' ELSE '9-10' END",
        'sort': 'MIN(color_score)', 'filter': 'color_score IS NOT NULL', 'top_n': 6},
    'exposure_score': {
        'sql': "CASE WHEN exposure_score<4 THEN '<4' WHEN exposure_score<6 THEN '4-6' "
               "WHEN exposure_score<7 THEN '6-7' WHEN exposure_score<8 THEN '7-8' "
               "WHEN exposure_score<9 THEN '8-9' ELSE '9-10' END",
        'sort': 'MIN(exposure_score)', 'filter': 'exposure_score IS NOT NULL', 'top_n': 6},
}
CORRELATION_Y_METRICS = {
    'aggregate', 'aesthetic', 'tech_sharpness', 'noise_sigma', 'comp_score',
    'face_quality', 'color_score', 'exposure_score', 'contrast_score',
    'dynamic_range_stops', 'mean_saturation', 'isolation_bonus', 'quality_score',
    'power_point_score', 'leading_lines_score',
}
