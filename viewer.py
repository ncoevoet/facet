import os
import sys

# Ensure the script's directory is in Python path for local imports
# This allows running the script from any directory
_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)

from flask import Flask, render_template_string, send_file, request, redirect, make_response, jsonify, session, abort
import sqlite3
import math
import time
import json
import hashlib
import hmac
import secrets
import re
from functools import lru_cache
from datetime import datetime
from io import BytesIO
import zipfile
from db import get_connection, DEFAULT_DB_PATH
from config import ScoringConfig
from person_viewer import person_bp
from i18n import init_i18n, _ as translate

app = Flask(__name__)

# --- CONFIG & SHARE SECRET (single parse of scoring_config.json) ---
_CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'scoring_config.json')

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
app.secret_key = _share_secret


def generate_person_share_token(person_id):
    """Generate an HMAC token for sharing a person page."""
    return hmac.new(_share_secret.encode(), str(person_id).encode(), 'sha256').hexdigest()


def verify_person_share_token(person_id, token):
    """Verify an HMAC share token for a person page."""
    expected = generate_person_share_token(person_id)
    return hmac.compare_digest(token, expected)


# --- PASSWORD AUTHENTICATION ---
def _get_viewer_password():
    """Get password from viewer config, returns empty string if not set."""
    config_path = os.path.join(os.path.dirname(__file__), 'scoring_config.json')
    try:
        with open(config_path) as f:
            config = json.load(f)
        return config.get('viewer', {}).get('password', '')
    except Exception:
        return ''


def _is_authenticated():
    """Check if current session is authenticated."""
    password = _get_viewer_password()
    if not password:
        return True  # No password required
    return session.get('authenticated', False)


LOGIN_PAGE_TEMPLATE = '''
<!DOCTYPE html>
<html class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Login - Facet</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {
            darkMode: 'class',
            theme: {
                extend: {
                    colors: {
                        'photo-dark': '#0b0b0b',
                        'photo-card': '#151515',
                        'photo-accent': '#4CAF50'
                    }
                }
            }
        }
    </script>
</head>
<body class="bg-neutral-950 text-neutral-200 min-h-screen flex items-center justify-center">
    <div class="bg-neutral-900 border border-neutral-800 rounded-lg p-8 w-full max-w-sm">
        <h1 class="text-2xl font-bold text-white mb-6 text-center">Facet</h1>
        {% if error %}
        <div class="bg-red-900 border border-red-700 text-red-200 px-4 py-2 rounded mb-4 text-sm">
            {{ error }}
        </div>
        {% endif %}
        <form method="POST" action="/login">
            <input type="hidden" name="next" value="{{ next_url }}">
            <div class="mb-4">
                <label for="password" class="block text-neutral-400 text-sm mb-2">Password</label>
                <input type="password" name="password" id="password"
                       class="w-full bg-neutral-800 text-white border border-neutral-700 rounded px-3 py-2 focus:border-green-500 focus:outline-none focus:ring-1 focus:ring-green-500"
                       placeholder="Enter password" autofocus>
            </div>
            <button type="submit"
                    class="w-full bg-green-600 hover:bg-green-500 text-white font-medium py-2 px-4 rounded transition-colors">
                Login
            </button>
        </form>
    </div>
</body>
</html>
'''


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Handle login form display and submission."""
    password = _get_viewer_password()
    if not password:
        return redirect('/')

    next_url = request.args.get('next', '/')

    if request.method == 'POST':
        if request.form.get('password') == password:
            session['authenticated'] = True
            next_url = request.form.get('next', '/')
            return redirect(next_url)
        return render_template_string(LOGIN_PAGE_TEMPLATE, error='Invalid password', next_url=next_url)

    return render_template_string(LOGIN_PAGE_TEMPLATE, error=None, next_url=next_url)


@app.route('/api/edition/login', methods=['POST'])
def api_edition_login():
    """Authenticate for edition mode."""
    data = request.get_json() or {}
    password = data.get('password', '')
    edition_password = _get_edition_password()
    if edition_password and password == edition_password:
        session['edition_authenticated'] = True
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Invalid password'}), 401


@app.route('/api/edition/logout', methods=['POST'])
def api_edition_logout():
    """Log out of edition mode."""
    session.pop('edition_authenticated', None)
    return jsonify({'success': True})


@app.route('/api/person/<int:person_id>/share-token')
def api_person_share_token(person_id):
    """Generate a share URL token for a person page. Only available to local (non-shared) users."""
    if session.get('shared_person_id') is not None:
        abort(403)
    token = generate_person_share_token(person_id)
    return jsonify({'token': token})


@app.before_request
def check_access():
    """Check authentication and gate shared visitors."""
    # Allow login route without authentication
    if request.path == '/login':
        return None

    # Allow static assets without authentication
    if request.path.startswith('/static/'):
        return None

    # Check if incoming request has a share token on a person page
    match = re.match(r'^/person/(\d+)', request.path)
    if match and request.args.get('token'):
        person_id = int(match.group(1))
        token = request.args.get('token')
        if verify_person_share_token(person_id, token):
            session['shared_person_id'] = person_id
            # Redirect to strip the token from the URL
            from urllib.parse import urlencode
            args = {k: v for k, v in request.args.items() if k != 'token'}
            clean_url = request.path
            if args:
                clean_url += '?' + urlencode(args)
            return redirect(clean_url)
        else:
            abort(403)

    # If session marks this visitor as a shared visitor, restrict routes
    shared_pid = session.get('shared_person_id')
    if shared_pid is not None:
        allowed_prefixes = [
            f'/person/{shared_pid}',
            '/thumbnail',
            f'/person_thumbnail/{shared_pid}',
            '/api/download-selected',
            '/api/download',
            '/static/',
        ]
        if not any(request.path.startswith(p) for p in allowed_prefixes):
            # Clear shared session and let normal auth flow handle it
            session.pop('shared_person_id', None)
            # Fall through to password authentication check below

    # Check password authentication for all other routes
    if not _is_authenticated():
        # For API routes, return 401
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Authentication required'}), 401
        # For regular routes, redirect to login
        from urllib.parse import urlencode
        next_url = request.path
        if request.query_string:
            next_url += '?' + request.query_string.decode('utf-8')
        return redirect(f'/login?next={next_url}')

# Initialize i18n support (must be before any route definitions)
init_i18n(app)

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

def _get_edition_password():
    """Get edition password from config."""
    return VIEWER_CONFIG.get('edition_password', '')


def is_edition_enabled():
    """Check if edition mode is available (password is configured)."""
    return bool(_get_edition_password())


def is_edition_authenticated():
    """Check if current session has unlocked edition mode."""
    edition_password = _get_edition_password()
    if not edition_password:
        return False  # No password = edition disabled
    return session.get('edition_authenticated', False)

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

# --- TOP PICKS SCORE COMPUTATION ---
def get_top_picks_score_sql():
    """Build SQL expression for top_picks_score based on config weights.

    When face_ratio >= min_face_ratio: uses configured weights including face_quality
    Otherwise: redistributes face_quality weight equally to aesthetic and composition
    """
    pt = VIEWER_CONFIG['photo_types']
    weights = pt.get('top_picks_weights', {
        'aggregate_percent': 20,
        'aesthetic_percent': 32,
        'composition_percent': 24,
        'face_quality_percent': 24
    })

    # Minimum face ratio to use face_quality weight (default 20%)
    min_face_ratio = pt.get('top_picks_min_face_ratio', 0.20)

    # Convert percentages to decimals
    agg_w = weights.get('aggregate_percent', 20) / 100.0
    aesthetic_w = weights.get('aesthetic_percent', 32) / 100.0
    comp_w = weights.get('composition_percent', 24) / 100.0
    face_w = weights.get('face_quality_percent', 24) / 100.0

    # For photos without significant faces, redistribute face_quality weight equally
    no_face_aesthetic_w = aesthetic_w + (face_w / 2.0)
    no_face_comp_w = comp_w + (face_w / 2.0)

    return f"""CASE
        WHEN COALESCE(face_ratio, 0) >= {min_face_ratio} THEN
            (COALESCE(aggregate, 0) * {agg_w:.2f} + COALESCE(aesthetic, 0) * {aesthetic_w:.2f} + COALESCE(comp_score, 0) * {comp_w:.2f} + COALESCE(face_quality, 0) * {face_w:.2f})
        ELSE
            (COALESCE(aggregate, 0) * {agg_w:.2f} + COALESCE(aesthetic, 0) * {no_face_aesthetic_w:.2f} + COALESCE(comp_score, 0) * {no_face_comp_w:.2f})
    END"""


def get_top_picks_threshold():
    """Get the minimum score threshold for top picks."""
    return VIEWER_CONFIG['photo_types'].get('top_picks_min_score', 7)


# Simple TTL cache for filter options
_filter_options_cache = {'data': None, 'expires': 0}

# Cache for existing columns (loaded once at startup, rarely changes)
_existing_columns_cache = None

# Cache for photo type counts (keyed by hide_blinks/hide_bursts/hide_duplicates combination)
_photo_types_cache = {'data': {}, 'expires': 0}

# Cache for COUNT query results (avoids repeated full-table scans)
_count_cache = {}
COUNT_CACHE_TTL = 300  # seconds - 5 minute TTL for performance on large databases

# Track if photo_tags lookup table is available (checked once at startup)
_photo_tags_available = None

# Face thumbnail cache is now managed by @lru_cache decorator (see _get_face_thumbnail_data)

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

# --- TEMPLATE FILTERS ---
@app.template_filter('format_date')
def format_date(value):
    if not value: return ""
    try:
        dt = datetime.strptime(value[:19], '%Y:%m:%d %H:%M:%S')
        return dt.strftime('%d/%m/%Y %H:%M')
    except (ValueError, TypeError):
        return value.split(' ')[0].replace(':', '/')

@app.template_filter('cleanup')
def cleanup(value, rnd):
    # Convert local absolute path to an SMB-friendly file URL
    if not rnd: return ""
    formatted_path = rnd[21:]
    return 'Z:' + formatted_path

@app.template_filter('safe_float')
def safe_float(value, decimals=2):
    """Safely format a value as float, handling None and bytes."""
    if value is None:
        return "0.00" if decimals == 2 else "0.0"
    if isinstance(value, bytes):
        return "N/A"
    try:
        fmt = f"%.{decimals}f"
        return fmt % float(value)
    except (ValueError, TypeError):
        return "N/A"

@app.template_filter('format_shutter')
def format_shutter(value):
    """Format shutter speed as fraction (e.g., 0.01 -> 1/100)."""
    if not value or value == 0:
        return "?"
    try:
        val = float(value)
        if val >= 1:
            return f"{val:.1f}s"
        else:
            return f"1/{int(round(1/val))}"
    except (ValueError, TypeError, ZeroDivisionError):
        return "?"

@app.template_filter('urlencode_without')
def urlencode_without(params, keys):
    """Encode params excluding specific key(s). Accepts string or list."""
    from urllib.parse import urlencode
    if isinstance(keys, str):
        keys = [keys]
    keys_set = set(keys)
    filtered = {k: v for k, v in params.items() if k not in keys_set and v}
    return urlencode(filtered)

@app.template_filter('urlencode_with')
def urlencode_with(params, key, value):
    """Encode params with a specific key set."""
    from urllib.parse import urlencode
    updated = dict(params)
    updated[key] = value
    return urlencode({k: v for k, v in updated.items() if v or k == key})

@app.template_filter('js_escape')
def js_escape(s):
    """Escape a string for safe embedding inside a JavaScript string literal."""
    if s is None:
        return ''
    return s.replace('\\', '\\\\').replace("'", "\\'").replace('"', '\\"')

# --- DATABASE HELPERS ---
_viewer_perf = VIEWER_CONFIG.get('performance', {})

def get_db_connection():
    """Get database connection with WAL mode and row factory.

    Uses viewer.performance overrides if configured, otherwise falls back
    to global performance settings from scoring_config.json.
    Returns a plain connection (caller must close).
    """
    from db import apply_pragmas
    conn = sqlite3.connect(DEFAULT_DB_PATH)
    apply_pragmas(conn,
        mmap_size_mb=_viewer_perf.get('mmap_size_mb'),
        cache_size_mb=_viewer_perf.get('cache_size_mb'))
    conn.row_factory = sqlite3.Row
    return conn

def get_existing_columns(conn=None):
    """Get list of columns that exist in the photos table. Cached after first call."""
    global _existing_columns_cache
    if _existing_columns_cache is not None:
        return _existing_columns_cache

    if conn is None:
        conn = get_db_connection()
        cursor = conn.execute('PRAGMA table_info(photos)')
        _existing_columns_cache = {row[1] for row in cursor.fetchall()}
        conn.close()
    else:
        cursor = conn.execute('PRAGMA table_info(photos)')
        _existing_columns_cache = {row[1] for row in cursor.fetchall()}

    return _existing_columns_cache


def is_photo_tags_available(conn=None):
    """Check if the photo_tags lookup table exists and has data."""
    global _photo_tags_available
    if _photo_tags_available is not None:
        return _photo_tags_available

    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    try:
        count = conn.execute("SELECT COUNT(*) FROM photo_tags").fetchone()[0]
        _photo_tags_available = count > 0
    except Exception:
        _photo_tags_available = False

    if close_conn:
        conn.close()

    return _photo_tags_available


# Cache for art tags from config
_art_tags_cache = None


def _add_tag_filter(where_clauses, sql_params, tag=None, require_tags=None, exclude_tags=None, exclude_art_tags=None, conn=None):
    """Build tag-related WHERE clauses using photo_tags table when available.

    Args:
        where_clauses: List to append WHERE conditions to
        sql_params: List to append SQL parameters to
        tag: Single tag to filter (exact match)
        require_tags: Comma-separated tags (any match)
        exclude_tags: Comma-separated tags to exclude
        exclude_art_tags: List of art tag names to exclude
        conn: Optional db connection for is_photo_tags_available check
    """
    use_photo_tags = is_photo_tags_available(conn)

    if tag:
        if use_photo_tags:
            where_clauses.append("EXISTS (SELECT 1 FROM photo_tags WHERE photo_path = photos.path AND tag = ?)")
            sql_params.append(tag)
        else:
            where_clauses.append("tags LIKE ?")
            sql_params.append(f"%{tag}%")

    if require_tags:
        tag_list = [t.strip() for t in require_tags.split(',')]
        if use_photo_tags:
            placeholders = ','.join(['?' for _ in tag_list])
            where_clauses.append(f"EXISTS (SELECT 1 FROM photo_tags WHERE photo_path = photos.path AND tag IN ({placeholders}))")
            sql_params.extend(tag_list)
        else:
            tag_conditions = ' OR '.join(['tags LIKE ?' for _ in tag_list])
            where_clauses.append(f"({tag_conditions})")
            sql_params.extend([f"%{tag}%" for tag in tag_list])

    if exclude_tags:
        tag_list = [t.strip() for t in exclude_tags.split(',')]
        for tag_name in tag_list:
            if use_photo_tags:
                where_clauses.append("NOT EXISTS (SELECT 1 FROM photo_tags WHERE photo_path = photos.path AND tag = ?)")
                sql_params.append(tag_name)
            else:
                where_clauses.append("(tags IS NULL OR tags NOT LIKE ?)")
                sql_params.append(f"%{tag_name}%")

    if exclude_art_tags:
        if use_photo_tags:
            placeholders = ','.join(['?' for _ in exclude_art_tags])
            where_clauses.append(f"NOT EXISTS (SELECT 1 FROM photo_tags WHERE photo_path = photos.path AND tag IN ({placeholders}))")
            sql_params.extend(exclude_art_tags)
        else:
            art_exclusions = ' AND '.join(['(tags IS NULL OR tags NOT LIKE ?)' for _ in exclude_art_tags])
            where_clauses.append(f"({art_exclusions})")
            sql_params.extend([f"%{tag}%" for tag in exclude_art_tags])


def get_art_tags_from_config():
    """Get list of art tags from scoring config (cached).

    Returns the required_tags from the 'art' category filter config,
    or falls back to tag keys from the art category tags dict.
    """
    global _art_tags_cache
    if _art_tags_cache is not None:
        return _art_tags_cache

    config = ScoringConfig()
    art_config = config.get_category_config('art')
    if art_config:
        # First try required_tags from filters
        filters = art_config.get('filters', {})
        required_tags = filters.get('required_tags', [])
        if required_tags:
            _art_tags_cache = list(required_tags)
            return _art_tags_cache

        # Fall back to tag keys from tags dict
        tags = art_config.get('tags', {})
        if isinstance(tags, dict):
            _art_tags_cache = list(tags.keys())
            return _art_tags_cache

    # Ultimate fallback (should not happen with proper config)
    _art_tags_cache = ['painting', 'statue', 'mural', 'drawing', 'cartoon', 'anime']
    return _art_tags_cache


def get_cached_count(conn, where_str, sql_params):
    """Cache COUNT results to avoid repeated full-table scans.

    Uses a short TTL (30s) to balance performance with freshness.
    Cache key is based on the WHERE clause and parameters.
    """
    global _count_cache

    # Build cache key from query components
    cache_key = hashlib.md5(f"{where_str}:{tuple(sql_params)}".encode()).hexdigest()

    now = time.time()
    if cache_key in _count_cache:
        count, ts = _count_cache[cache_key]
        if now - ts < COUNT_CACHE_TTL:
            return count

    # Execute count query
    count = conn.execute(f"SELECT COUNT(*) FROM photos{where_str}", sql_params).fetchone()[0]

    # Store in cache
    _count_cache[cache_key] = (count, now)

    # Prune old entries periodically (keep cache from growing unbounded)
    if len(_count_cache) > 100:
        expired = [k for k, (_, ts) in _count_cache.items() if now - ts > COUNT_CACHE_TTL * 2]
        for k in expired:
            del _count_cache[k]

    return count


def get_filter_options():
    """Fetch unique values for dropdowns directly from the data.

    Uses a 60-second TTL cache to reduce database queries.
    """
    global _filter_options_cache

    # Check cache
    if _filter_options_cache['data'] and time.time() < _filter_options_cache['expires']:
        return _filter_options_cache['data']

    with get_db_connection() as conn:
        # Combined query for cameras and lenses (reduces 2 queries to 1)
        options = {'cameras': [], 'lenses': []}
        for row in conn.execute("""
            SELECT DISTINCT camera_model, lens_model FROM photos
            WHERE camera_model IS NOT NULL OR lens_model IS NOT NULL
        """).fetchall():
            if row[0] and row[0] not in options['cameras']:
                options['cameras'].append(row[0])
            if row[1] and row[1] not in options['lenses']:
                options['lenses'].append(row[1])
        options['cameras'].sort()
        options['lenses'].sort()

        # Get tags with counts, ordered by frequency (use SQL recursive CTE for efficiency)
        # Tags are stored as comma-separated strings, split and count directly in SQL
        try:
            max_tags = VIEWER_CONFIG['dropdowns']['max_tags']
            # Recursive CTE to split comma-separated tags and aggregate counts
            tag_query = """
                WITH RECURSIVE split_tags(tag, rest) AS (
                    -- Base case: start with empty tag and the full tags string + trailing comma
                    SELECT '', tags || ',' FROM photos WHERE tags IS NOT NULL AND tags != ''
                    UNION ALL
                    -- Recursive case: extract tag before comma, keep rest after comma
                    SELECT
                        TRIM(SUBSTR(rest, 1, INSTR(rest, ',') - 1)),
                        SUBSTR(rest, INSTR(rest, ',') + 1)
                    FROM split_tags
                    WHERE rest != ''
                )
                SELECT tag, COUNT(*) as cnt
                FROM split_tags
                WHERE tag != ''
                GROUP BY tag
                ORDER BY cnt DESC, tag ASC
                LIMIT ?
            """
            rows = conn.execute(tag_query, (max_tags,)).fetchall()
            options['tags'] = [(row[0], row[1]) for row in rows]
        except (sqlite3.Error, AttributeError):
            options['tags'] = []

        # Get persons with photo counts for face recognition filter
        try:
            # Check if persons table exists
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='persons'")
            if cursor.fetchone():
                min_photos = VIEWER_CONFIG['dropdowns'].get('min_photos_for_person', 1)
                persons = conn.execute("""
                    SELECT p.id, p.name, p.representative_face_id,
                           COUNT(DISTINCT f.photo_path) as photo_count
                    FROM persons p
                    JOIN faces f ON f.person_id = p.id
                    GROUP BY p.id
                    HAVING photo_count >= ?
                    ORDER BY photo_count DESC
                """, (min_photos,)).fetchall()
                options['persons'] = [(r[0], r[1], r[2], r[3]) for r in persons]
            else:
                options['persons'] = []
        except sqlite3.Error:
            options['persons'] = []

        # Get composition patterns with counts (from SAMP-Net scoring)
        try:
            # Check if composition_pattern column exists
            existing_cols = get_existing_columns(conn)
            if 'composition_pattern' in existing_cols:
                rows = conn.execute("""
                    SELECT composition_pattern, COUNT(*) as count
                    FROM photos
                    WHERE composition_pattern IS NOT NULL AND composition_pattern != ''
                    GROUP BY composition_pattern
                    ORDER BY count DESC
                """).fetchall()
                options['composition_patterns'] = [(r[0], r[1]) for r in rows]
            else:
                options['composition_patterns'] = []
        except sqlite3.Error:
            options['composition_patterns'] = []

    # Update cache (configurable TTL)
    _filter_options_cache['data'] = options
    _filter_options_cache['expires'] = time.time() + VIEWER_CONFIG['cache_ttl_seconds']

    return options

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
    global _photo_types_cache

    # Check cache (keyed by filter combination)
    cache_key = (hide_blinks, hide_bursts, hide_duplicates)
    if time.time() < _photo_types_cache['expires'] and cache_key in _photo_types_cache['data']:
        return _photo_types_cache['data'][cache_key]

    conn = get_db_connection()
    existing_cols = get_existing_columns(conn)

    # Build base filter clauses for blink/burst settings
    base_filters = []
    if hide_blinks:
        base_filters.append("(is_blink = 0 OR is_blink IS NULL)")
    if hide_bursts:
        base_filters.append("(is_burst_lead = 1 OR is_burst_lead IS NULL)")
    if hide_duplicates:
        base_filters.append("(is_duplicate_lead = 1 OR is_duplicate_lead IS NULL OR duplicate_group_id IS NULL)")

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
    query_parts = []
    # Add "All Photos" count first
    if base_where:
        query_parts.append(f"SELECT '' as type_id, COUNT(*) as cnt FROM photos WHERE {base_where}")
    else:
        query_parts.append("SELECT '' as type_id, COUNT(*) as cnt FROM photos")

    # Add all type counts
    for type_id, label, combined_where in valid_types:
        query_parts.append(f"SELECT '{type_id}' as type_id, COUNT(*) as cnt FROM photos WHERE {combined_where}")

    # Execute single UNION ALL query
    union_query = " UNION ALL ".join(query_parts)
    try:
        results = conn.execute(union_query).fetchall()
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
    conn = get_db_connection()
    existing_cols = get_existing_columns(conn)

    base_filters = []
    if hide_blinks:
        base_filters.append("(is_blink = 0 OR is_blink IS NULL)")
    if hide_bursts:
        base_filters.append("(is_burst_lead = 1 OR is_burst_lead IS NULL)")
    if hide_duplicates:
        base_filters.append("(is_duplicate_lead = 1 OR is_duplicate_lead IS NULL OR duplicate_group_id IS NULL)")

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

# --- THE HTML TEMPLATE ---
HTML_TEMPLATE = r'''
<!DOCTYPE html>
<html class="dark">
<head>
    <title>Facet</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {
            darkMode: 'class',
            theme: {
                extend: {
                    colors: {
                        'photo-dark': '#0b0b0b',
                        'photo-card': '#151515',
                        'photo-accent': '#4CAF50'
                    }
                }
            }
        }
    </script>
    <style type="text/tailwindcss">
        @layer utilities {
            .filter-input {
                @apply bg-neutral-800 text-white border border-neutral-600 px-3 py-2 rounded-md text-sm focus:border-green-500 focus:outline-none focus:ring-1 focus:ring-green-500 w-full;
            }
            .filter-label {
                @apply text-neutral-400 uppercase text-xs font-bold tracking-wide mb-1;
            }
            .filter-chip {
                @apply inline-flex items-center gap-1.5 px-2.5 py-1 bg-neutral-800 border border-neutral-700 rounded-full text-xs text-neutral-300 cursor-pointer no-underline hover:border-red-400 hover:text-red-300 transition-colors;
            }
            .filter-chip-remove {
                @apply text-neutral-500 font-bold;
            }
            .filter-chip:hover .filter-chip-remove {
                @apply text-red-400;
            }
        }
        /* Hover preview styles */
        #hover-preview {
            position: fixed;
            z-index: 100;
            pointer-events: none;
            opacity: 0;
            transition: opacity 0.15s ease-out;
        }
        #hover-preview.visible {
            opacity: 1;
        }
        #hover-preview img {
            object-fit: contain;
            border-radius: 8px;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.8);
            border: 2px solid #404040;
        }
        /* Hide hover preview on mobile */
        @media (max-width: 640px) {
            #hover-preview, #person-hover-preview, #photo-hover-preview { display: none !important; }
        }
        /* Responsive card sizing */
        @media (max-width: 639px) {
            #photo-grid { gap: 2px !important; }
            #photo-grid-wrapper { padding: 0 !important; }
            .photo-card { padding: 0 !important; gap: 0 !important; border: none !important; border-radius: 0 !important; background: transparent !important; }
            .photo-thumb { object-fit: contain !important; width: 100% !important; height: auto !important; border-radius: 0 !important; aspect-ratio: auto !important; }
        }
        @media (min-width: 640px) {
            .photo-card { width: var(--card-width) !important; }
            .photo-card img.photo-thumb { width: var(--image-width) !important; }
        }
        /* Hide details: compact cards with uniform square thumbnails */
        body.details-hidden .photo-card { padding: 0 !important; gap: 0 !important; }
        body.details-hidden .photo-thumb { aspect-ratio: 1; width: 100% !important; }
        /* Photo hover preview with details */
        #photo-hover-preview {
            position: fixed;
            z-index: 100;
            pointer-events: none;
            opacity: 0;
            transition: opacity 0.15s ease-out;
            display: flex;
            align-items: start;
            gap: 12px;
            background: rgba(23, 23, 23, 0.97);
            padding: 10px;
            border-radius: 10px;
            border: 1px solid #404040;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.8);
        }
        #photo-hover-preview.landscape {
            flex-direction: column;
            gap: 8px;
        }
        #photo-hover-preview.visible {
            opacity: 1;
        }
        #photo-hover-preview img {
            object-fit: contain;
            border-radius: 6px;
        }
        #photo-hover-preview.landscape img {
            width: 100%;
        }
        #photo-hover-preview .preview-details {
            max-width: 260px;
            font-size: 12px;
            line-height: 1.6;
            color: #e5e5e5;
        }
        #photo-hover-preview.landscape .preview-details {
            max-width: none;
            width: 100%;
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 0 16px;
        }
        #photo-hover-preview.landscape .preview-details .preview-filename,
        #photo-hover-preview.landscape .preview-details .preview-date,
        #photo-hover-preview.landscape .preview-details .category {
            grid-column: 1 / -1;
        }
        #photo-hover-preview .preview-details .preview-filename {
            font-weight: 600;
            color: #e5e5e5;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        #photo-hover-preview .preview-details .preview-date {
            color: #737373;
            font-size: 11px;
            margin-bottom: 4px;
        }
        #photo-hover-preview .preview-details .category {
            font-weight: 600;
            color: #22c55e;
            margin-bottom: 6px;
        }
        #photo-hover-preview .preview-details .score-section {
            margin-top: 8px;
            padding-top: 6px;
            border-top: 1px solid #404040;
        }
        #photo-hover-preview .preview-details .score-section-title {
            font-size: 10px;
            color: #737373;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 4px;
        }
        #photo-hover-preview .preview-details .score-row {
            display: flex;
            justify-content: space-between;
        }
        #photo-hover-preview .preview-details .score-label {
            color: #a3a3a3;
        }
        #photo-hover-preview .preview-details .score-value {
            color: #22c55e;
            font-weight: 500;
        }
        /* Person hover preview styles */
        #person-hover-preview {
            position: fixed;
            z-index: 100;
            pointer-events: none;
            opacity: 0;
            transition: opacity 0.15s ease-out;
        }
        #person-hover-preview.visible {
            opacity: 1;
        }
        #person-hover-preview img {
            width: 160px;
            height: 160px;
            object-fit: cover;
            border-radius: 50%;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.8);
            border: 3px solid #22c55e;
        }
        #person-hover-preview .person-name {
            text-align: center;
            margin-top: 8px;
            font-size: 14px;
            color: #e5e5e5;
            text-shadow: 0 2px 4px rgba(0, 0, 0, 0.8);
        }
    </style>
</head>
<body class="bg-neutral-950 text-neutral-200 min-h-screen{% if params.hide_details == '1' %} details-hidden{% endif %}">
    <!-- Hover Preview (simple large image) -->
    <div id="hover-preview"><img src="" alt="Preview"></div>
    <!-- Person Hover Preview -->
    <div id="person-hover-preview"><img src="" alt="Person Preview"><div class="person-name"></div></div>
    <!-- Photo Hover Preview with Details -->
    <div id="photo-hover-preview">
        <img src="" alt="Photo Preview">
        <div class="preview-details"></div>
    </div>

    <!-- Compact Header Toolbar -->
    <header class="bg-neutral-900 border-b border-neutral-800 px-3 sm:px-6 py-2 sm:sticky sm:top-0 z-40">
        <!-- Responsive: stacked rows on mobile/tablet, single row on lg+ -->
        <div class="flex flex-col lg:flex-row lg:items-center gap-2">
            <!-- Primary Filters Form -->
            <form id="primaryFilters" method="GET" class="contents">
                <!-- Preserve sort params and toggle states -->
                <input type="hidden" name="sort" value="{{ params.sort }}">
                <input type="hidden" name="dir" value="{{ params.dir }}">
                {% if params.person %}<input type="hidden" name="person" value="{{ params.person }}">{% endif %}
                {% if params.hide_blinks == '1' %}<input type="hidden" name="hide_blinks" value="1">{% endif %}
                {% if params.hide_bursts == '1' %}<input type="hidden" name="hide_bursts" value="1">{% endif %}
                {% if params.hide_duplicates == '1' %}<input type="hidden" name="hide_duplicates" value="1">{% endif %}
                {% if params.hide_details == '1' %}<input type="hidden" name="hide_details" value="1">{% endif %}

                <!-- Row 1 on mobile: Type + Person (single row on lg+) -->
                <div class="flex flex-col sm:flex-row lg:contents gap-2">
                    <!-- Photo Type -->
                    <select name="type" onchange="this.form.elements['sort'].disabled=true; this.form.submit()" class="w-full sm:basis-1/2 lg:w-auto bg-neutral-800 text-white text-sm px-2 py-1.5 rounded border border-neutral-700 focus:border-green-500 focus:outline-none">
                        {% for value, label in photo_types %}
                        <option value="{{ value }}" {% if params.type == value %}selected{% endif %}>{{ label }}</option>
                        {% endfor %}
                    </select>

                    <!-- Person Filter + Edit -->
                    {% if options.persons %}
                    <div class="w-full sm:basis-1/2 lg:w-auto flex gap-1">
                        <div class="person-dropdown relative flex-1 lg:flex-none">
                            <button type="button" class="person-dropdown-btn w-full lg:w-auto bg-neutral-800 text-white text-sm px-2 py-1.5 rounded border border-neutral-700 hover:border-neutral-600 focus:border-green-500 focus:outline-none flex items-center gap-2">
                                {% if params.person %}
                                    {% for id, name, face_id, count in options.persons if id|string == params.person %}
                                    <img src="/person_thumbnail/{{ id }}" class="w-12 h-12 rounded-full object-cover flex-shrink-0" alt="">
                                    <span class="truncate max-w-[120px]">{{ name or 'Person ' ~ id }}</span>
                                    {% endfor %}
                                {% else %}
                                    <span class="truncate">{{ _('ui.filters.all_people') }}</span>
                                {% endif %}
                                <svg class="w-4 h-4 ml-auto flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
                            </button>
                            <div class="person-dropdown-menu hidden absolute top-full left-0 mt-1 bg-neutral-800 border border-neutral-700 rounded shadow-lg z-50 max-h-64 overflow-y-auto min-w-[200px]">
                                <a href="?{{ params|urlencode_without('person') }}" class="flex items-center gap-2 px-3 py-2 hover:bg-neutral-700 text-white text-sm">
                                    <span class="w-12 h-12"></span>
                                    <span>{{ _('ui.filters.all_people') }}</span>
                                </a>
                                {% for id, name, face_id, count in options.persons %}
                                {% set person_params = params|urlencode_without(['type', 'person']) %}
                                <a href="?{{ person_params ~ ('&' if person_params else '') }}person={{ id }}" class="flex items-center gap-2 px-3 py-2 hover:bg-neutral-700 text-white text-sm {% if params.person == id|string %}bg-neutral-700{% endif %}">
                                    <img src="/person_thumbnail/{{ id }}" class="w-12 h-12 rounded-full object-cover" alt="" loading="lazy">
                                    <span class="truncate">{{ name or 'Person ' ~ id }}</span>
                                    <span class="text-neutral-500 ml-auto">({{ count }})</span>
                                </a>
                                {% endfor %}
                                {% if edition_authenticated %}
                                <a href="/manage_persons" class="flex items-center gap-2 px-3 py-2 hover:bg-neutral-700 text-green-500 text-sm border-t border-neutral-700">
                                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/>
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>
                                    </svg>
                                    <span>{{ _('manage_persons.title') }}</span>
                                </a>
                                {% endif %}
                            </div>
                        </div>
                        {% if params.person and edition_authenticated %}
                        {% for id, name, face_id, count in options.persons if id|string == params.person %}
                        <button type="button" onclick="renamePerson({{ id }}, '{{ (name or 'Person ' ~ id)|e }}')" class="flex-shrink-0 bg-neutral-800 text-neutral-400 hover:text-white p-1.5 rounded border border-neutral-700 hover:border-neutral-600" title="Rename person">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"/></svg>
                        </button>
                        {% endfor %}
                        {% endif %}
                    </div>
                    {% endif %}
                </div>

                <!-- Row 2 on mobile: Tag + Search (single row on lg+) -->
                <div class="flex lg:contents gap-2">
                    <!-- Tag Filter -->
                    {% if options.tags %}
                    <select name="tag" onchange="this.form.submit()" class="basis-1/2 lg:basis-auto lg:w-auto bg-neutral-800 text-white text-sm px-2 py-1.5 rounded border border-neutral-700 focus:border-green-500 focus:outline-none">
                        <option value="">{{ _('ui.filters.tag') }}: {{ _('ui.filters.all') }}</option>
                        {% for tag, count in options.tags %}
                        <option value="{{ tag }}" {% if params.tag == tag %}selected{% endif %}>{{ tag }} ({{ count }})</option>
                        {% endfor %}
                    </select>
                    {% endif %}

                    <!-- Filename Search -->
                    <div class="basis-1/2 lg:basis-auto lg:flex-1 lg:max-w-xs relative">
                        <input type="text" name="search" value="{{ params.search or '' }}" placeholder="{{ _('ui.filters.search') }}..."
                               class="w-full bg-neutral-800 text-white text-sm pl-8 pr-2 py-1.5 rounded border border-neutral-700 focus:border-green-500 focus:outline-none"
                               onkeydown="if(event.key==='Enter'){this.form.submit();}">
                        <svg class="absolute left-2 top-1/2 -translate-y-1/2 w-4 h-4 text-neutral-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
                        </svg>
                    </div>
                </div>
            </form>

            <!-- Row 3 on mobile: Sort + Buttons (single row on lg+) -->
            <div class="flex lg:contents gap-2 items-center">
                <!-- Sort Controls -->
                <form id="sortForm" method="GET" class="flex-1 lg:flex-none flex items-center gap-1 min-w-0">
                    {% for key, val in params.items() if key not in ['sort', 'dir'] and val %}
                    <input type="hidden" name="{{ key }}" value="{{ val }}">
                    {% endfor %}

                    <select name="sort" onchange="document.getElementById('sortForm').submit()" class="flex-1 lg:flex-none lg:w-auto min-w-0 bg-neutral-800 text-white text-sm px-2 py-1.5 rounded border border-neutral-700 focus:border-green-500 focus:outline-none">
                        {% if sort_options_grouped %}
                            {% for category, options in sort_options_grouped.items() %}
                            <optgroup label="{{ category }}">
                                {% for opt in options %}
                                <option value="{{ opt.column }}" {% if params.sort == opt.column %}selected{% endif %}>{{ opt.label }}</option>
                                {% endfor %}
                            </optgroup>
                            {% endfor %}
                        {% else %}
                            {% for value, label in sort_options %}
                            <option value="{{ value }}" {% if params.sort == value %}selected{% endif %}>{{ label }}</option>
                            {% endfor %}
                        {% endif %}
                    </select>

                    <button type="button" onclick="toggleSortDir()" class="flex-shrink-0 bg-neutral-800 text-white px-2 py-1.5 rounded border border-neutral-700 hover:border-green-500 text-sm" title="{{ _('ui.sort.toggle_direction') }}">
                        {% if params.dir == 'ASC' %}&#8593;{% else %}&#8595;{% endif %}
                    </button>
                    <input type="hidden" name="dir" id="sortDir" value="{{ params.dir }}">
                </form>

                <!-- Filter Toggle Button with Badge -->
                <button onclick="toggleDrawer()" class="flex-shrink-0 relative bg-neutral-800 text-white px-3 py-1.5 rounded border border-neutral-700 hover:border-green-500 flex items-center gap-2 text-sm">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z"></path>
                    </svg>
                    <span class="hidden sm:inline">{{ _('ui.buttons.filters') }}</span>
                    {% if active_filter_count > 0 %}
                    <span class="absolute -top-1.5 -right-1.5 bg-green-500 text-white text-xs w-5 h-5 rounded-full flex items-center justify-center font-bold">{{ active_filter_count }}</span>
                    {% endif %}
                </button>

                {% if editing_enabled and not edition_authenticated %}
                <!-- Edition Mode Unlock Button -->
                <button onclick="showEditionLoginModal()" class="flex-shrink-0 bg-neutral-800 text-neutral-400 hover:text-yellow-400 px-3 py-1.5 rounded border border-neutral-700 hover:border-yellow-500 flex items-center gap-2 text-sm" title="Unlock edition mode">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"/>
                    </svg>
                </button>
                {% elif edition_authenticated %}
                <!-- Edition Mode Active Indicator / Logout Button -->
                <button onclick="editionLogout()" class="flex-shrink-0 bg-yellow-600 hover:bg-yellow-500 text-white px-3 py-1.5 rounded border border-yellow-500 flex items-center gap-2 text-sm" title="Edition mode active - click to lock">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 11V7a4 4 0 118 0m-4 8v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2z"/>
                    </svg>
                </button>
                {% endif %}

                {% if options.persons and edition_authenticated %}
                <!-- Manage Persons Button -->
                <a href="/manage_persons" class="flex-shrink-0 bg-green-700 hover:bg-green-600 text-white px-3 py-1.5 rounded border border-green-600 flex items-center gap-2 text-sm">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197m13.5-9a2.5 2.5 0 11-5 0 2.5 2.5 0 015 0z"/>
                    </svg>
                    <span class="hidden sm:inline">{{ _('manage_persons.title') }}</span>
                </a>
                {% endif %}

                {% if edition_authenticated and params.type %}
                <!-- Compare Photos Button -->
                <a href="/compare?type={{ params.type }}" class="flex-shrink-0 bg-purple-700 hover:bg-purple-600 text-white px-3 py-1.5 rounded border border-purple-600 flex items-center gap-2 text-sm">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"></path>
                    </svg>
                    <span class="hidden sm:inline">{{ _('ui.buttons.compare') }}</span>
                </a>
                {% endif %}

                <!-- Stats Button -->
                <a href="/stats" class="flex-shrink-0 relative bg-neutral-800 text-white px-3 py-1.5 rounded border border-neutral-700 hover:border-green-500 flex items-center gap-2 text-sm" title="{{ _('stats.title') }}">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/>
                    </svg>
                </a>
            </div>
        </div>
    </header>

    <!-- Active Filter Chips (drawer filters, toggles, and person only) -->
    {% if active_filter_count > 0 %}
    <div class="px-3 sm:px-6 py-2 flex flex-wrap gap-2 bg-neutral-900/50 border-b border-neutral-800">
        {% for key, val in active_filters.items() %}
        <a href="?{% for k, v in params.items() if k != key and v and k not in excluded_url_params %}{{ k }}={{ v }}&{% endfor %}" class="filter-chip">
            {% if key == 'hide_blinks' %}
            {{ _('ui.toggles.hide_blinks') }}
            {% elif key == 'hide_bursts' %}
            {{ _('ui.toggles.best_of_burst') }}
            {% elif key == 'hide_duplicates' %}
            {{ _('ui.toggles.hide_duplicates') }}
            {% elif key == 'hide_details' %}
            {{ _('ui.toggles.hide_details') }}
            {% elif key in ['hide_rejected', 'favorites_only', 'show_rejected'] %}
            {{ filter_labels.get(key, key) }}
            {% else %}
            {{ filter_labels.get(key, key) }}: {{ val }}
            {% endif %}
            <span class="filter-chip-remove">&times;</span>
        </a>
        {% endfor %}
        <a href="/" class="text-red-400 text-xs hover:text-red-300 ml-2 self-center">{{ _('ui.buttons.clear_all') }}</a>
    </div>
    {% endif %}

    <!-- Filter Drawer (hidden by default) - Advanced Filters Only -->
    <div id="filter-drawer" class="fixed left-0 top-0 h-full w-80 bg-neutral-900 border-r border-neutral-800 transform -translate-x-full transition-transform duration-300 z-50 overflow-y-auto">
        <form method="GET" class="h-full flex flex-col">
            <!-- Preserve primary filter params -->
            <input type="hidden" name="sort" value="{{ params.sort }}">
            <input type="hidden" name="dir" value="{{ params.dir }}">
            <input type="hidden" name="type" value="{{ params.type }}">
            {% if params.tag %}<input type="hidden" name="tag" value="{{ params.tag }}">{% endif %}
            {% if params.search %}<input type="hidden" name="search" value="{{ params.search }}">{% endif %}
            {% if params.person %}<input type="hidden" name="person" value="{{ params.person }}">{% endif %}

            <!-- Drawer Header -->
            <div class="flex justify-between items-center p-4 border-b border-neutral-800 sticky top-0 bg-neutral-900">
                <h2 class="text-lg font-semibold text-white">{{ _('drawer.title') }}</h2>
                <button type="button" onclick="toggleDrawer()" class="text-neutral-400 hover:text-white text-2xl leading-none">&times;</button>
            </div>

            <div class="p-4 space-y-4 flex-1 overflow-y-auto">
                <!-- Display Options Section -->
                <details open class="group">
                    <summary class="flex items-center justify-between cursor-pointer text-sm font-semibold text-neutral-300 uppercase tracking-wide py-2">
                        {{ _('drawer.sections.display_options') }}
                        <svg class="w-4 h-4 transform group-open:rotate-180 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path>
                        </svg>
                    </summary>
                    <div class="mt-3 space-y-3">
                        <label class="flex items-center gap-2 text-sm text-neutral-400 cursor-pointer hover:text-neutral-300">
                            <input type="checkbox" name="hide_blinks" value="1" {% if params.hide_blinks == '1' %}checked{% endif %} class="w-4 h-4 rounded bg-neutral-800 border-neutral-600 text-green-500 focus:ring-green-500 focus:ring-offset-neutral-900">
                            <span>{{ _('ui.toggles.hide_blinks') }}</span>
                        </label>
                        <label class="flex items-center gap-2 text-sm text-neutral-400 cursor-pointer hover:text-neutral-300">
                            <input type="checkbox" name="hide_bursts" value="1" {% if params.hide_bursts == '1' %}checked{% endif %} class="w-4 h-4 rounded bg-neutral-800 border-neutral-600 text-green-500 focus:ring-green-500 focus:ring-offset-neutral-900">
                            <span>{{ _('ui.toggles.best_of_burst') }}</span>
                        </label>
                        <label class="flex items-center gap-2 text-sm text-neutral-400 cursor-pointer hover:text-neutral-300">
                            <input type="checkbox" name="hide_duplicates" value="1" {% if params.hide_duplicates == '1' %}checked{% endif %} class="w-4 h-4 rounded bg-neutral-800 border-neutral-600 text-green-500 focus:ring-green-500 focus:ring-offset-neutral-900">
                            <span>{{ _('ui.toggles.hide_duplicates') }}</span>
                        </label>
                        <label class="flex items-center gap-2 text-sm text-neutral-400 cursor-pointer hover:text-neutral-300">
                            <input type="checkbox" name="hide_details" value="1" {% if params.hide_details == '1' %}checked{% endif %} class="w-4 h-4 rounded bg-neutral-800 border-neutral-600 text-green-500 focus:ring-green-500 focus:ring-offset-neutral-900">
                            <span>{{ _('ui.toggles.hide_details') }}</span>
                        </label>
                        <label class="flex items-center gap-2 text-sm text-neutral-400 cursor-pointer hover:text-neutral-300">
                            <input type="checkbox" name="hide_rejected" value="1" {% if params.hide_rejected == '1' %}checked{% endif %} class="w-4 h-4 rounded bg-neutral-800 border-neutral-600 text-green-500 focus:ring-green-500 focus:ring-offset-neutral-900" onchange="if(this.checked) document.querySelector('input[name=show_rejected]').checked=false">
                            <span>{{ _('rating.hide_rejected') }}</span>
                        </label>
                        <label class="flex items-center gap-2 text-sm text-neutral-400 cursor-pointer hover:text-neutral-300">
                            <input type="checkbox" name="favorites_only" value="1" {% if params.favorites_only == '1' %}checked{% endif %} class="w-4 h-4 rounded bg-neutral-800 border-neutral-600 text-green-500 focus:ring-green-500 focus:ring-offset-neutral-900">
                            <span>{{ _('rating.favorites_only') }}</span>
                        </label>
                        <label class="flex items-center gap-2 text-sm text-neutral-400 cursor-pointer hover:text-neutral-300">
                            <input type="checkbox" name="show_rejected" value="1" {% if params.show_rejected == '1' %}checked{% endif %} class="w-4 h-4 rounded bg-neutral-800 border-neutral-600 text-green-500 focus:ring-green-500 focus:ring-offset-neutral-900" onchange="if(this.checked) document.querySelector('input[name=hide_rejected]').checked=false">
                            <span>{{ _('rating.show_rejected') }}</span>
                        </label>
                        <!-- Min rating dropdown -->
                        <div>
                            <label class="filter-label">{{ _('rating.min_rating') }}</label>
                            <select name="min_rating" class="filter-input">
                                <option value="">{{ _('drawer.placeholder') }}</option>
                                <option value="1" {% if params.min_rating == '1' %}selected{% endif %}>★ (1+)</option>
                                <option value="2" {% if params.min_rating == '2' %}selected{% endif %}>★★ (2+)</option>
                                <option value="3" {% if params.min_rating == '3' %}selected{% endif %}>★★★ (3+)</option>
                                <option value="4" {% if params.min_rating == '4' %}selected{% endif %}>★★★★ (4+)</option>
                                <option value="5" {% if params.min_rating == '5' %}selected{% endif %}>★★★★★ (5)</option>
                            </select>
                        </div>
                    </div>
                </details>

                <!-- Date Range Section -->
                <details class="group">
                    <summary class="flex items-center justify-between cursor-pointer text-sm font-semibold text-neutral-300 uppercase tracking-wide py-2 border-t border-neutral-800 pt-4">
                        {{ _('drawer.sections.date_range') }}
                        <svg class="w-4 h-4 transform group-open:rotate-180 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path>
                        </svg>
                    </summary>
                    <div class="mt-3 space-y-3">
                        <div>
                            <label class="filter-label">{{ _('drawer.fields.from_date') }}</label>
                            <input type="date" name="date_from" class="filter-input" value="{{ params.date_from or '' }}">
                        </div>
                        <div>
                            <label class="filter-label">{{ _('drawer.fields.to_date') }}</label>
                            <input type="date" name="date_to" class="filter-input" value="{{ params.date_to or '' }}">
                        </div>
                    </div>
                </details>

                <!-- Score Ranges Section -->
                <details class="group">
                    <summary class="flex items-center justify-between cursor-pointer text-sm font-semibold text-neutral-300 uppercase tracking-wide py-2 border-t border-neutral-800 pt-4">
                        {{ _('drawer.sections.score_ranges') }}
                        <svg class="w-4 h-4 transform group-open:rotate-180 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path>
                        </svg>
                    </summary>
                    <div class="mt-3 space-y-3">
                        <div class="grid grid-cols-2 gap-2">
                            <div>
                                <label class="filter-label">Min Aggregate</label>
                                <input type="number" step="0.1" name="min_score" class="filter-input" value="{{ params.min_score or '' }}" placeholder="0">
                            </div>
                            <div>
                                <label class="filter-label">Max Aggregate</label>
                                <input type="number" step="0.1" name="max_score" class="filter-input" value="{{ params.max_score or '' }}" placeholder="10">
                            </div>
                        </div>
                        <div class="grid grid-cols-2 gap-2">
                            <div>
                                <label class="filter-label">Min Aesthetic</label>
                                <input type="number" step="0.1" name="min_aesthetic" class="filter-input" value="{{ params.min_aesthetic or '' }}" placeholder="Any">
                            </div>
                            <div>
                                <label class="filter-label">Max Aesthetic</label>
                                <input type="number" step="0.1" name="max_aesthetic" class="filter-input" value="{{ params.max_aesthetic or '' }}" placeholder="Any">
                            </div>
                        </div>
                        <div class="grid grid-cols-2 gap-2">
                            <div>
                                <label class="filter-label">Min Sharpness</label>
                                <input type="number" step="0.1" name="min_sharpness" class="filter-input" value="{{ params.min_sharpness or '' }}" placeholder="Any">
                            </div>
                            <div>
                                <label class="filter-label">Max Sharpness</label>
                                <input type="number" step="0.1" name="max_sharpness" class="filter-input" value="{{ params.max_sharpness or '' }}" placeholder="Any">
                            </div>
                        </div>
                        <div class="grid grid-cols-2 gap-2">
                            <div>
                                <label class="filter-label">Min Exposure</label>
                                <input type="number" step="0.1" name="min_exposure" class="filter-input" value="{{ params.min_exposure or '' }}" placeholder="Any">
                            </div>
                            <div>
                                <label class="filter-label">Max Exposure</label>
                                <input type="number" step="0.1" name="max_exposure" class="filter-input" value="{{ params.max_exposure or '' }}" placeholder="Any">
                            </div>
                        </div>
                        <div class="grid grid-cols-2 gap-2">
                            <div>
                                <label class="filter-label">Min Color</label>
                                <input type="number" step="0.1" name="min_color" class="filter-input" value="{{ params.min_color or '' }}" placeholder="Any">
                            </div>
                            <div>
                                <label class="filter-label">Max Color</label>
                                <input type="number" step="0.1" name="max_color" class="filter-input" value="{{ params.max_color or '' }}" placeholder="Any">
                            </div>
                        </div>
                        <div class="grid grid-cols-2 gap-2">
                            <div>
                                <label class="filter-label">Min Composition</label>
                                <input type="number" step="0.1" name="min_composition" class="filter-input" value="{{ params.min_composition or '' }}" placeholder="Any">
                            </div>
                            <div>
                                <label class="filter-label">Max Composition</label>
                                <input type="number" step="0.1" name="max_composition" class="filter-input" value="{{ params.max_composition or '' }}" placeholder="Any">
                            </div>
                        </div>
                        <!-- Composition Pattern Filter (SAMP-Net) -->
                        {% if options.composition_patterns %}
                        <div class="mt-3">
                            <label class="filter-label">Composition Pattern</label>
                            <select name="composition_pattern" class="filter-input w-full">
                                <option value="">All Patterns</option>
                                {% for pattern, count in options.composition_patterns %}
                                <option value="{{ pattern }}" {% if params.composition_pattern == pattern %}selected{% endif %}>{{ pattern|replace('_', ' ')|title }} ({{ count }})</option>
                                {% endfor %}
                            </select>
                        </div>
                        {% endif %}
                    </div>
                </details>

                <!-- Face Metrics Section -->
                <details class="group">
                    <summary class="flex items-center justify-between cursor-pointer text-sm font-semibold text-neutral-300 uppercase tracking-wide py-2 border-t border-neutral-800 pt-4">
                        {{ _('drawer.sections.face_metrics') }}
                        <svg class="w-4 h-4 transform group-open:rotate-180 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path>
                        </svg>
                    </summary>
                    <div class="mt-3 space-y-3">
                        <div class="grid grid-cols-2 gap-2">
                            <div>
                                <label class="filter-label">Min Faces</label>
                                <input type="number" name="min_face_count" class="filter-input" value="{{ params.min_face_count or '' }}" placeholder="Any">
                            </div>
                            <div>
                                <label class="filter-label">Max Faces</label>
                                <input type="number" name="max_face_count" class="filter-input" value="{{ params.max_face_count or '' }}" placeholder="Any">
                            </div>
                        </div>
                        <div class="grid grid-cols-2 gap-2">
                            <div>
                                <label class="filter-label">Min Face Quality</label>
                                <input type="number" step="0.1" name="min_face_quality" class="filter-input" value="{{ params.min_face_quality or '' }}" placeholder="Any">
                            </div>
                            <div>
                                <label class="filter-label">Max Face Quality</label>
                                <input type="number" step="0.1" name="max_face_quality" class="filter-input" value="{{ params.max_face_quality or '' }}" placeholder="Any">
                            </div>
                        </div>
                        <div class="grid grid-cols-2 gap-2">
                            <div>
                                <label class="filter-label">Min Eye Sharpness</label>
                                <input type="number" step="0.1" name="min_eye_sharpness" class="filter-input" value="{{ params.min_eye_sharpness or '' }}" placeholder="Any">
                            </div>
                            <div>
                                <label class="filter-label">Max Eye Sharpness</label>
                                <input type="number" step="0.1" name="max_eye_sharpness" class="filter-input" value="{{ params.max_eye_sharpness or '' }}" placeholder="Any">
                            </div>
                        </div>
                        <div class="grid grid-cols-2 gap-2">
                            <div>
                                <label class="filter-label">Min Face Ratio</label>
                                <input type="number" step="0.01" name="min_face_ratio" class="filter-input" value="{{ params.min_face_ratio or '' }}" placeholder="Any">
                            </div>
                            <div>
                                <label class="filter-label">Max Face Ratio</label>
                                <input type="number" step="0.01" name="max_face_ratio" class="filter-input" value="{{ params.max_face_ratio or '' }}" placeholder="Any">
                            </div>
                        </div>
                        <div class="grid grid-cols-2 gap-2">
                            <div>
                                <label class="filter-label">Min Face Sharpness</label>
                                <input type="number" step="0.1" name="min_face_sharpness" class="filter-input" value="{{ params.min_face_sharpness or '' }}" placeholder="Any">
                            </div>
                            <div>
                                <label class="filter-label">Max Face Sharpness</label>
                                <input type="number" step="0.1" name="max_face_sharpness" class="filter-input" value="{{ params.max_face_sharpness or '' }}" placeholder="Any">
                            </div>
                        </div>
                    </div>
                </details>

                <!-- New Metrics Section -->
                <details class="group">
                    <summary class="flex items-center justify-between cursor-pointer text-sm font-semibold text-neutral-300 uppercase tracking-wide py-2 border-t border-neutral-800 pt-4">
                        {{ _('drawer.sections.image_metrics') }}
                        <svg class="w-4 h-4 transform group-open:rotate-180 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path>
                        </svg>
                    </summary>
                    <div class="mt-3 space-y-3">
                        <div class="grid grid-cols-2 gap-2">
                            <div>
                                <label class="filter-label">Min Dynamic Range</label>
                                <input type="number" step="0.1" name="min_dynamic_range" class="filter-input" value="{{ params.min_dynamic_range or '' }}" placeholder="Any">
                            </div>
                            <div>
                                <label class="filter-label">Max Dynamic Range</label>
                                <input type="number" step="0.1" name="max_dynamic_range" class="filter-input" value="{{ params.max_dynamic_range or '' }}" placeholder="Any">
                            </div>
                        </div>
                        <div class="grid grid-cols-2 gap-2">
                            <div>
                                <label class="filter-label">Min Contrast</label>
                                <input type="number" step="0.1" name="min_contrast" class="filter-input" value="{{ params.min_contrast or '' }}" placeholder="Any">
                            </div>
                            <div>
                                <label class="filter-label">Max Contrast</label>
                                <input type="number" step="0.1" name="max_contrast" class="filter-input" value="{{ params.max_contrast or '' }}" placeholder="Any">
                            </div>
                        </div>
                        <div class="grid grid-cols-2 gap-2">
                            <div>
                                <label class="filter-label">Min Noise</label>
                                <input type="number" step="0.1" name="min_noise" class="filter-input" value="{{ params.min_noise or '' }}" placeholder="Any">
                            </div>
                            <div>
                                <label class="filter-label">Max Noise</label>
                                <input type="number" step="0.1" name="max_noise" class="filter-input" value="{{ params.max_noise or '' }}" placeholder="Any">
                            </div>
                        </div>
                        <div class="grid grid-cols-2 gap-2">
                            <div>
                                <label class="filter-label">Min Isolation</label>
                                <input type="number" step="0.1" name="min_isolation" class="filter-input" value="{{ params.min_isolation or '' }}" placeholder="Any">
                            </div>
                            <div>
                                <label class="filter-label">Max Isolation</label>
                                <input type="number" step="0.1" name="max_isolation" class="filter-input" value="{{ params.max_isolation or '' }}" placeholder="Any">
                            </div>
                        </div>
                        <div class="grid grid-cols-2 gap-2">
                            <div>
                                <label class="filter-label">Min Luminance</label>
                                <input type="number" step="0.01" name="min_luminance" class="filter-input" value="{{ params.min_luminance or '' }}" placeholder="Any">
                            </div>
                            <div>
                                <label class="filter-label">Max Luminance</label>
                                <input type="number" step="0.01" name="max_luminance" class="filter-input" value="{{ params.max_luminance or '' }}" placeholder="Any">
                            </div>
                        </div>
                        <div class="grid grid-cols-2 gap-2">
                            <div>
                                <label class="filter-label">Min Hist Spread</label>
                                <input type="number" step="0.01" name="min_histogram_spread" class="filter-input" value="{{ params.min_histogram_spread or '' }}" placeholder="Any">
                            </div>
                            <div>
                                <label class="filter-label">Max Hist Spread</label>
                                <input type="number" step="0.01" name="max_histogram_spread" class="filter-input" value="{{ params.max_histogram_spread or '' }}" placeholder="Any">
                            </div>
                        </div>
                        <div class="grid grid-cols-2 gap-2">
                            <div>
                                <label class="filter-label">Min Power Point</label>
                                <input type="number" step="0.1" name="min_power_point" class="filter-input" value="{{ params.min_power_point or '' }}" placeholder="Any">
                            </div>
                            <div>
                                <label class="filter-label">Max Power Point</label>
                                <input type="number" step="0.1" name="max_power_point" class="filter-input" value="{{ params.max_power_point or '' }}" placeholder="Any">
                            </div>
                        </div>
                    </div>
                </details>

                <!-- Camera Settings Section -->
                <details class="group">
                    <summary class="flex items-center justify-between cursor-pointer text-sm font-semibold text-neutral-300 uppercase tracking-wide py-2 border-t border-neutral-800 pt-4">
                        {{ _('drawer.sections.camera_settings') }}
                        <svg class="w-4 h-4 transform group-open:rotate-180 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path>
                        </svg>
                    </summary>
                    <div class="mt-3 space-y-3">
                        <div>
                            <label class="filter-label">Camera</label>
                            <select name="camera" class="filter-input">
                                <option value="">All Cameras</option>
                                {% for cam in options.cameras %}
                                <option value="{{ cam }}" {% if params.camera == cam %}selected{% endif %}>{{ cam }}</option>
                                {% endfor %}
                            </select>
                        </div>
                        <div>
                            <label class="filter-label">Lens</label>
                            <select name="lens" class="filter-input">
                                <option value="">All Lenses</option>
                                {% for l in options.lenses %}
                                <option value="{{ l }}" {% if params.lens == l %}selected{% endif %}>{{ l }}</option>
                                {% endfor %}
                            </select>
                        </div>
                        <div class="grid grid-cols-2 gap-2">
                            <div>
                                <label class="filter-label">Min ISO</label>
                                <input type="number" name="min_iso" class="filter-input" value="{{ params.min_iso or '' }}" placeholder="Any">
                            </div>
                            <div>
                                <label class="filter-label">Max ISO</label>
                                <input type="number" name="max_iso" class="filter-input" value="{{ params.max_iso or '' }}" placeholder="Any">
                            </div>
                        </div>
                        <div class="grid grid-cols-2 gap-2">
                            <div>
                                <label class="filter-label">Min F-Stop</label>
                                <input type="number" step="0.1" name="min_fstop" class="filter-input" value="{{ params.min_fstop or '' }}" placeholder="Any">
                            </div>
                            <div>
                                <label class="filter-label">Max F-Stop</label>
                                <input type="number" step="0.1" name="max_fstop" class="filter-input" value="{{ params.max_fstop or '' }}" placeholder="Any">
                            </div>
                        </div>
                        <div class="grid grid-cols-2 gap-2">
                            <div>
                                <label class="filter-label">Min Focal (mm)</label>
                                <input type="number" name="min_focal" class="filter-input" value="{{ params.min_focal or '' }}" placeholder="Any">
                            </div>
                            <div>
                                <label class="filter-label">Max Focal (mm)</label>
                                <input type="number" name="max_focal" class="filter-input" value="{{ params.max_focal or '' }}" placeholder="Any">
                            </div>
                        </div>
                    </div>
                </details>
            </div>

            <!-- Drawer Footer Actions (sticky) -->
            <div class="p-4 border-t border-neutral-800 bg-neutral-900 sticky bottom-0 flex gap-3">
                <button type="submit" class="flex-1 bg-green-600 hover:bg-green-500 text-white px-4 py-2.5 rounded-lg font-semibold transition-colors">
                    {{ _('ui.buttons.apply') }}
                </button>
                <a href="/" class="flex-1 bg-neutral-700 hover:bg-neutral-600 text-white px-4 py-2.5 rounded-lg font-semibold transition-colors text-center">
                    {{ _('ui.buttons.reset_all') }}
                </a>
            </div>
        </form>
    </div>

    <!-- Drawer Overlay -->
    <div id="drawer-overlay" class="hidden fixed inset-0 bg-black/50 z-40" onclick="toggleDrawer()"></div>

    <!-- Photo Grid - Tight Layout -->
    <div id="photo-grid-wrapper" class="px-2 py-3">
        <div id="photo-grid" class="flex flex-wrap justify-center gap-2" data-page="{{ page }}" data-total-pages="{{ total_pages }}" data-sort-col="{{ sort_col }}">
            {% for p in photos %}
            <div class="photo-card group bg-neutral-900 flex flex-col gap-1 rounded border border-neutral-800 p-1.5 hover:border-green-500 transition-all w-full sm:w-auto" style="--card-width: {{ viewer_config.display.card_width_px }}px; --image-width: {{ viewer_config.display.image_width_px }}px" data-path="{{ p['path'] | urlencode }}">
                <!-- Thumbnail -->
                <div class="photo-thumb-container flex-initial relative" onclick="toggleSelection(this, '{{ p['filename'] | js_escape }}', '{{ p['path'] | js_escape }}')" data-tooltip="{{ p['filename'] }}&#10;{{ p['date_taken'] | format_date }}&#10;[{{ p['category'] | default('others') | title }}] Aggregate: {{ p['aggregate'] | safe_float(1) }}&#10;&#10;── Quality ──&#10;Aesthetic: {{ p['aesthetic'] | safe_float(1) }}{% if p['quality_score'] %}&#10;Quality: {{ p['quality_score'] | safe_float(1) }}{% endif %}{% if p['face_count'] > 0 %}&#10;Face Quality: {{ p['face_quality'] | safe_float(1) }}&#10;Face Sharpness: {{ p['face_sharpness'] | safe_float(1) }}&#10;Eye Sharpness: {{ p['eye_sharpness'] | safe_float(1) }}{% endif %}&#10;Tech Sharpness: {{ p['tech_sharpness'] | safe_float(1) }}&#10;&#10;── Composition ──&#10;Composition: {{ p['comp_score'] | safe_float(1) }}{% if p['composition_pattern'] %}&#10;Pattern: {{ p['composition_pattern'] | replace('_', ' ') | title }}{% endif %}{% if p['power_point_score'] %}&#10;Power Points: {{ p['power_point_score'] | safe_float(1) }}{% endif %}{% if p['leading_lines_score'] %}&#10;Leading Lines: {{ p['leading_lines_score'] | safe_float(1) }}{% endif %}&#10;&#10;── Technical ──&#10;Exposure: {{ p['exposure_score'] | safe_float(1) }}&#10;Color: {{ p['color_score'] | safe_float(1) }}{% if p['contrast_score'] %}&#10;Contrast: {{ p['contrast_score'] | safe_float(1) }}{% endif %}{% if p['dynamic_range_stops'] %}&#10;Dynamic Range: {{ p['dynamic_range_stops'] | safe_float(1) }}{% endif %}{% if p['mean_saturation'] %}&#10;Saturation: {{ p['mean_saturation'] | safe_float(1) }}{% endif %}{% if p['noise_sigma'] %}&#10;Noise: {{ p['noise_sigma'] | safe_float(1) }}{% endif %}&#10;&#10;── EXIF ──{% if p['camera_model'] %}&#10;Camera: {{ p['camera_model'] }}{% endif %}{% if p['lens_model'] %}&#10;Lens: {{ p['lens_model'] }}{% endif %}&#10;Focal: {{ p['focal_length'] or '?' }}mm&#10;Shutter: {{ p['shutter_speed'] | format_shutter }}&#10;ISO: {{ p['iso'] or '?' }}{% if p['isolation_bonus'] and p['isolation_bonus'] > 1.0 %}&#10;&#10;── Bonus ──&#10;Isolation: {{ p['isolation_bonus'] | safe_float(1) }}{% endif %}">
                    <img
                        src="/thumbnail?path={{ p['path'] | urlencode }}&size=640"
                        loading="lazy"
                        class="photo-thumb rounded object-cover cursor-pointer w-full sm:w-auto"
                    >
                    <div class="selection-check hidden absolute top-1 right-1 w-6 h-6 bg-green-500 rounded-full flex items-center justify-center">
                        <svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"></path>
                        </svg>
                    </div>
                    {% if viewer_config.features.show_rating_badge and (p['is_favorite'] or (p['star_rating'] and p['star_rating'] > 0)) %}
                    <div class="rating-badge absolute top-8 right-1 bg-black/70 rounded px-1 py-0.5 text-xs font-medium z-10" data-path="{{ p['path'] | js_escape }}">
                        {% if p['is_favorite'] %}<span class="text-red-400">❤</span>{% elif p['star_rating'] > 0 %}<span class="text-yellow-400">★{{ p['star_rating'] }}</span>{% endif %}
                    </div>
                    {% endif %}
                    {% if edition_authenticated and p['face_count'] > 0 and not params.person %}
                    <button onclick="event.stopPropagation(); showAssignFaceModal('{{ p['path'] | js_escape }}')"
                            class="assign-face-btn opacity-0 group-hover:opacity-100 absolute top-1 left-1 w-6 h-6 bg-blue-600 hover:bg-blue-500 rounded-full flex items-center justify-center text-white transition-opacity z-10"
                            title="Assign face to person">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6v6m0 0v6m0-6h6m-6 0H6"/>
                        </svg>
                    </button>
                    {% endif %}
                    {% if viewer_config.features.show_similar_button %}
                    <!-- Find Similar Button -->
                    <button onclick="event.stopPropagation(); showSimilarPhotosModal('{{ p['path'] | js_escape }}')"
                            class="similar-btn opacity-0 group-hover:opacity-100 absolute bottom-1 left-1 w-6 h-6 bg-purple-600 hover:bg-purple-500 rounded-full flex items-center justify-center text-white transition-opacity z-10"
                            title="{{ _('similar.find_similar') }}">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
                        </svg>
                    </button>
                    {% endif %}
                    {% if edition_authenticated and viewer_config.features.show_rating_controls %}
                    <!-- Rating controls (edition mode only) -->
                    <div class="rating-controls opacity-0 group-hover:opacity-100 absolute bottom-1 right-1 flex items-center gap-1 bg-black/70 rounded px-1 py-0.5 transition-opacity z-10">
                        <!-- Star rating -->
                        <div class="star-rating flex" data-path="{{ p['path'] | js_escape }}" data-current="{{ p['star_rating'] or 0 }}">
                            {% for i in range(1, 6) %}
                            <button onclick="event.stopPropagation(); setRating('{{ p['path'] | js_escape }}', {{ i }}, this.parentElement)"
                                    class="star-btn text-sm {% if p['star_rating'] and p['star_rating'] >= i %}text-yellow-400{% else %}text-neutral-500 hover:text-yellow-400{% endif %} transition-colors"
                                    title="{{ i }} star{% if i > 1 %}s{% endif %}">★</button>
                            {% endfor %}
                        </div>
                        <!-- Favorite toggle -->
                        <button onclick="event.stopPropagation(); toggleFavorite('{{ p['path'] | js_escape }}', this)"
                                class="favorite-btn text-sm {% if p['is_favorite'] %}text-red-400{% else %}text-neutral-500 hover:text-red-400{% endif %} transition-colors"
                                title="{{ _('rating.favorite') }}"
                                data-favorite="{{ '1' if p['is_favorite'] else '0' }}">❤</button>
                        <!-- Rejected toggle -->
                        <button onclick="event.stopPropagation(); toggleRejected('{{ p['path'] | js_escape }}', this)"
                                class="rejected-btn text-sm {% if p['is_rejected'] %}text-red-600{% else %}text-neutral-500 hover:text-red-600{% endif %} transition-colors"
                                title="{{ _('rating.rejected') }}"
                                data-rejected="{{ '1' if p['is_rejected'] else '0' }}">✕</button>
                    </div>
                    {% endif %}
                </div>

                <!-- Details (stacked below photo) -->
                {% if params.hide_details != '1' %}
                <div class="mt-1.5 text-left">
                    <!-- Always visible: filename + aggregate score -->
                    <div class="flex justify-between text-[12px] items-center">
                        <div class="text-neutral-300 truncate font-medium">{{ p['filename'] }}</div>
                        <span class="text-green-400 font-medium">{{ p['aggregate'] | safe_float(1) }}</span>
                    </div>
                    <!-- Hidden on mobile, visible on sm+ -->
                    <div class="hidden sm:block">
                        <div class="flex justify-between items-center">
                            {% if sort_col == 'date_taken' or sort_col == 'aggregate' %}
                            <span class="text-green-400 font-bold text-base">{{ p['aggregate'] | safe_float(1) }}</span>
                            {% elif sort_col == 'shutter_speed' %}
                            <span class="text-green-400 font-bold text-base">{{ p[sort_col] | format_shutter }}</span>
                            {% elif sort_col == 'composition_pattern' %}
                            <span class="text-green-400 font-bold text-base">{{ (p[sort_col] or 'N/A') | replace('_', ' ') | title }}</span>
                            {% else %}
                            <span class="text-green-400 font-bold text-base">{{ p[sort_col] | safe_float(1) }}</span>
                            {% endif %}
                            <span>{% if p['is_favorite'] %}<span class="text-[10px] font-medium text-red-400 mr-0.5" title="{{ _('rating.favorite') }}">❤</span>{% endif %}{% if p['is_rejected'] %}<span class="text-[10px] font-medium bg-red-900 text-red-400 px-1 rounded mr-0.5">REJ</span>{% endif %}{% if p['star_rating'] and p['star_rating'] > 0 %}<span class="text-[10px] font-medium text-yellow-400 mr-0.5">{% for _ in range(p['star_rating']) %}★{% endfor %}</span>{% endif %}{% if p['is_burst_lead'] %}<span class="text-[10px] font-medium bg-green-900 text-green-400 px-1 rounded">{{ _('ui.badges.best') }}</span>{% endif %}{% if p['is_blink'] %} <span class="text-[10px] font-medium bg-amber-900 text-amber-400 px-1 rounded">{{ _('ui.badges.blink') }}</span>{% endif %}{% if p['is_monochrome'] %} <span class="text-[10px] font-medium bg-neutral-700 text-neutral-400 px-1 rounded">{{ _('ui.badges.bw') }}</span>{% endif %}</span>
                        </div>
                        {% if sort_col not in ['aggregate', 'date_taken'] %}
                        <div class="text-[10px] text-neutral-500 -mt-0.5">{{ sort_label }}</div>
                        {% endif %}
                        <div class="flex justify-between text-neutral-400 text-[12px]">
                            <span>{{ p['date_taken'] | format_date }}</span>
                        </div>
                        <div class="flex justify-between text-[12px] text-neutral-500">
                            <span>{{ p['focal_length'] or '?' }}mm f/{{ p['f_stop'] or '?' }}</span>
                            <span>{{ p['shutter_speed'] | format_shutter }} ISO {{ p['iso'] or '?' }}</span>
                        </div>
                        {% if p['tags_list'] %}
                        <div class="flex flex-wrap gap-1 mt-1">
                            {% for tag in p['tags_list'] %}
                            <a href="?tag={{ tag }}" class="text-[10px] px-1.5 py-0.5 bg-neutral-800 text-neutral-400 rounded hover:bg-green-600 hover:text-white transition-colors">{{ tag }}</a>
                            {% endfor %}
                        </div>
                        {% endif %}
                    </div>
                    {% if p['persons'] or (edition_authenticated and params.person) %}
                    <div class="flex flex-wrap gap-1 mt-1 items-center">
                        {% if p['persons'] %}
                        {% for person in p['persons'] if person.id|string != params.person %}
                        <a href="?{{ params|urlencode_with('person', person.id) }}" title="{{ person.name }}" class="block">
                            <img src="/person_thumbnail/{{ person.id }}"
                                 alt="{{ person.name }}"
                                 class="w-8 h-8 rounded-full object-cover border border-neutral-700 hover:border-green-500 transition-colors"
                                 loading="lazy">
                        </a>
                        {% endfor %}
                        {% endif %}
                        {% if edition_authenticated and params.person %}
                        <button onclick="event.stopPropagation(); removePersonFromPhoto('{{ p['path'] | js_escape }}', {{ params.person }})"
                                class="remove-person-btn w-8 h-8 rounded-full bg-red-600 hover:bg-red-500 flex items-center justify-center text-white"
                                title="Remove person from this photo">
                            <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M6 18L18 6M6 6l12 12"/>
                            </svg>
                        </button>
                        {% endif %}
                    </div>
                    {% endif %}
                </div>
                {% endif %}
            </div>
            {% endfor %}
        </div>
    </div>

    <!-- Infinite Scroll Loading Indicator -->
    <div id="scroll-loader" class="flex justify-center items-center gap-4 py-8 border-t border-neutral-800 {% if page >= total_pages %}hidden{% endif %}">
        <div id="scroll-spinner" class="hidden">
            <svg class="animate-spin h-6 w-6 text-green-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
        </div>
        <span id="scroll-status" class="text-neutral-400">
            {{ _('pagination.scroll_for_more') }} &middot; <span id="current-count">{{ photos|length }}</span> {{ _('ui.labels.of') }} {{ total_count }} {{ _('ui.labels.photos') }}
        </span>
    </div>
    <div id="scroll-end" class="{% if page < total_pages %}hidden{% endif %} flex justify-center items-center py-8 border-t border-neutral-800">
        <span class="text-neutral-500">{{ _('pagination.end_of_results') }} &middot; {{ total_count }} {{ _('ui.labels.photos') }}</span>
    </div>

    <!-- Footer with Language Switcher -->
    <footer class="bg-neutral-900 border-t border-neutral-800 py-4 mt-8">
        <div class="flex justify-center items-center gap-2">
            {% for code in supported_languages %}
            <a href="?{{ request.query_string.decode('utf-8') }}&lang={{ code }}"
               class="text-xs px-3 py-1.5 rounded transition-colors {% if lang == code %}bg-green-600 text-white{% else %}bg-neutral-800 text-neutral-400 hover:text-white hover:bg-neutral-700{% endif %}">
                {{ _('language.' ~ code) }}
            </a>
            {% endfor %}
        </div>
    </footer>

    <!-- Selection Toolbar -->
    <div id="selection-toolbar" class="fixed bottom-4 left-1/2 transform -translate-x-1/2 translate-y-20 opacity-0 transition-all duration-300 z-50 bg-neutral-800 border border-neutral-700 rounded-lg shadow-xl px-2 sm:px-4 py-2 sm:py-3 flex items-center gap-2 sm:gap-4">
        <span class="text-neutral-300 hidden sm:inline"><span id="selection-count" class="text-green-400 font-bold">0</span> {{ _('ui.labels.selected') }}</span>
        <span class="text-green-400 font-bold sm:hidden" id="selection-count-mobile">0</span>
        <button onclick="copySelected()" class="hidden sm:flex bg-green-600 hover:bg-green-500 text-white px-4 py-1.5 rounded font-medium transition-colors items-center gap-2">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2v-1M8 5a2 2 0 002 2h2a2 2 0 002-2M8 5a2 2 0 012-2h2a2 2 0 012 2m0 0h2a2 2 0 012 2v3m2 4H10m0 0l3-3m-3 3l3 3"></path>
            </svg>
            <span>{{ _('ui.buttons.copy') }}</span>
        </button>
        <button onclick="downloadSelected()" class="bg-green-600 hover:bg-green-500 text-white px-2 sm:px-4 py-1 sm:py-1.5 rounded font-medium transition-colors flex items-center gap-1 sm:gap-2">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path>
            </svg>
            <span>{{ _('ui.buttons.download') }}</span>
        </button>
        <button onclick="clearSelection()" class="text-neutral-400 hover:text-white px-1 sm:px-2 py-1 sm:py-1.5 transition-colors">
            <span class="hidden sm:inline">{{ _('ui.buttons.clear') }}</span>
            <svg class="w-4 h-4 sm:hidden" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
            </svg>
        </button>
    </div>

    <!-- Copy Notification -->
    <div id="copy-notification" class="fixed bottom-4 right-4 bg-green-600 text-white px-4 py-2 rounded-lg shadow-lg transform translate-y-20 opacity-0 transition-all duration-300 z-50">
        <span id="copy-notification-text">Copied!</span>
    </div>

    <!-- Fixed loading spinner (bottom-right) -->
    <div id="loading-spinner-fixed" class="hidden fixed bottom-6 right-6 z-50
         bg-neutral-800/90 rounded-full p-3 shadow-lg border border-neutral-700">
        <svg class="animate-spin h-6 w-6 text-green-500" xmlns="http://www.w3.org/2000/svg"
             fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10"
                    stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
    </div>

    <!-- Face Selection Modal (for selecting which face to assign) -->
    <div id="select-face-modal" class="hidden fixed inset-0 bg-black/80 flex items-center justify-center z-50">
        <div class="bg-neutral-900 rounded-lg p-6 max-w-2xl w-full mx-4 border border-neutral-700">
            <h3 class="text-lg font-semibold mb-4">{{ _('manage_persons.select_face') or 'Select face to assign' }}</h3>
            <div id="select-face-grid" class="grid grid-cols-4 gap-3 mb-4 max-h-80 overflow-y-auto">
                <!-- Dynamically populated with face thumbnails -->
            </div>
            <button onclick="closeSelectFaceModal()" class="w-full bg-neutral-700 hover:bg-neutral-600 py-2 rounded transition-colors">
                {{ _('ui.buttons.cancel') }}
            </button>
        </div>
    </div>

    <!-- Person Selection Modal (for face assignment) -->
    <div id="select-person-modal" class="hidden fixed inset-0 bg-black/80 flex items-center justify-center z-50">
        <div class="bg-neutral-900 rounded-lg p-6 max-w-2xl w-full mx-4 border border-neutral-700">
            <h3 class="text-lg font-semibold mb-4">{{ _('manage_persons.select_person') }}</h3>
            <input type="text" id="person-search" placeholder="{{ _('manage_persons.search_persons') }}" class="w-full bg-neutral-800 text-white px-3 py-2 rounded border border-neutral-700 mb-4 focus:border-green-500 focus:outline-none">
            <div id="select-person-grid" class="grid grid-cols-6 gap-3 mb-4 max-h-80 overflow-y-auto">
                <!-- Dynamically populated -->
            </div>
            <button onclick="closeSelectPersonModal()" class="w-full bg-neutral-700 hover:bg-neutral-600 py-2 rounded transition-colors">
                {{ _('ui.buttons.cancel') }}
            </button>
        </div>
    </div>

    <!-- Similar Photos Modal -->
    <div id="similar-photos-modal" class="hidden fixed inset-0 bg-black/80 flex items-center justify-center z-50" onclick="if(event.target === this) closeSimilarPhotosModal()">
        <div class="bg-neutral-900 rounded-lg p-6 max-w-4xl w-full mx-4 border border-neutral-700 max-h-[90vh] flex flex-col">
            <div class="flex justify-between items-center mb-4">
                <h3 class="text-lg font-semibold">{{ _('similar.title') }}</h3>
                <button onclick="closeSimilarPhotosModal()" class="text-neutral-400 hover:text-white transition-colors">
                    <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                    </svg>
                </button>
            </div>
            <div id="similar-photos-loading" class="hidden py-8 text-center text-neutral-400">
                <svg class="animate-spin h-8 w-8 mx-auto mb-2 text-purple-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                {{ _('similar.loading') }}
            </div>
            <div id="similar-photos-empty" class="hidden py-8 text-center text-neutral-500">
                {{ _('similar.no_results') }}
            </div>
            <div id="similar-photos-grid" class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 auto-rows-max gap-4 overflow-y-auto min-h-0 flex-1 p-1">
                <!-- Dynamically populated -->
            </div>
        </div>
    </div>

    {% if editing_enabled and not edition_authenticated %}
    <!-- Edition Login Modal -->
    <div id="edition-login-modal" class="hidden fixed inset-0 bg-black/80 flex items-center justify-center z-50">
        <div class="bg-neutral-900 rounded-lg p-6 max-w-sm w-full mx-4 border border-neutral-700">
            <h3 class="text-lg font-semibold mb-2">Unlock Edition Mode</h3>
            <p class="text-sm text-neutral-400 mb-4">Enter the edition password to enable editing features.</p>
            <form onsubmit="return submitEditionLogin(event)">
                <input type="password" id="edition-password" placeholder="Edition password"
                       class="w-full bg-neutral-800 text-white px-3 py-2 rounded border border-neutral-700 mb-3 focus:border-yellow-500 focus:outline-none"
                       autocomplete="current-password">
                <div id="edition-login-error" class="hidden text-red-400 text-sm mb-3"></div>
                <div class="flex gap-2">
                    <button type="button" onclick="closeEditionLoginModal()" class="flex-1 bg-neutral-700 hover:bg-neutral-600 py-2 rounded transition-colors">
                        {{ _('ui.buttons.cancel') }}
                    </button>
                    <button type="submit" class="flex-1 bg-yellow-600 hover:bg-yellow-500 py-2 rounded transition-colors font-medium">
                        Unlock
                    </button>
                </div>
            </form>
        </div>
    </div>
    {% endif %}

    <!-- JavaScript -->
    <script>
        // i18n translations
        const I18N = {{ js_translations(['manage_persons', 'notifications', 'ui', 'similar', 'rating']) | tojson | safe }};
        const FEATURES = {{ viewer_config.features | tojson | safe }};
        const EDITION_AUTHENTICATED = {{ edition_authenticated | tojson }};
        const currentPersonFilter = {{ params.person|tojson if params.person else 'null' }};
        function t(key, vars={}) {
            const keys = key.split('.');
            let value = I18N;
            for (const k of keys) {
                if (value && typeof value === 'object' && k in value) {
                    value = value[k];
                } else {
                    return key;
                }
            }
            if (typeof value === 'string' && Object.keys(vars).length > 0) {
                return value.replace(/\{(\w+)\}/g, (m, k) => vars[k] !== undefined ? vars[k] : m);
            }
            return value || key;
        }

        // Global helper: format number with decimals
        function safeFloat(val, decimals) {
            if (val === null || val === undefined || val === '') return '?';
            return parseFloat(val).toFixed(decimals);
        }

        // Selection state
        const selectedPhotos = new Map(); // filename -> {element, path}

        function toggleDrawer() {
            const drawer = document.getElementById('filter-drawer');
            const overlay = document.getElementById('drawer-overlay');
            const isOpen = !drawer.classList.contains('-translate-x-full');

            if (isOpen) {
                // Close drawer - explicit state to prevent desync
                drawer.classList.add('-translate-x-full');
                overlay.classList.add('hidden');
                document.body.classList.remove('overflow-hidden');
            } else {
                // Open drawer
                drawer.classList.remove('-translate-x-full');
                overlay.classList.remove('hidden');
                document.body.classList.add('overflow-hidden');
            }
        }

        function toggleSortDir() {
            const dirInput = document.getElementById('sortDir');
            dirInput.value = dirInput.value === 'ASC' ? 'DESC' : 'ASC';
            document.getElementById('sortForm').submit();
        }

        // Edition mode login
        function showEditionLoginModal() {
            const modal = document.getElementById('edition-login-modal');
            if (modal) {
                modal.classList.remove('hidden');
                document.getElementById('edition-password').focus();
            }
        }

        function closeEditionLoginModal() {
            const modal = document.getElementById('edition-login-modal');
            if (modal) {
                modal.classList.add('hidden');
                document.getElementById('edition-password').value = '';
                document.getElementById('edition-login-error').classList.add('hidden');
            }
        }

        function submitEditionLogin(event) {
            event.preventDefault();
            const password = document.getElementById('edition-password').value;
            const errorEl = document.getElementById('edition-login-error');

            fetch('/api/edition/login', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: JSON.stringify({ password: password })
            })
            .then(response => response.json().then(data => ({ ok: response.ok, data })))
            .then(({ ok, data }) => {
                if (ok && data.success) {
                    // Reload page to show edition features
                    window.location.reload();
                } else {
                    errorEl.textContent = data.error || 'Invalid password';
                    errorEl.classList.remove('hidden');
                }
            })
            .catch(err => {
                errorEl.textContent = 'Connection error';
                errorEl.classList.remove('hidden');
            });

            return false;
        }

        function editionLogout() {
            fetch('/api/edition/logout', {
                method: 'POST',
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            })
            .then(() => window.location.reload())
            .catch(() => window.location.reload());
        }

        // Person dropdown toggle
        document.querySelectorAll('.person-dropdown').forEach(dropdown => {
            const btn = dropdown.querySelector('.person-dropdown-btn');
            const menu = dropdown.querySelector('.person-dropdown-menu');

            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                menu.classList.toggle('hidden');
            });
        });

        // Rename person function
        function renamePerson(personId, currentName) {
            const newName = prompt('Enter new name for this person:', currentName);
            if (newName !== null && newName.trim() !== currentName) {
                const formData = new FormData();
                formData.append('name', newName.trim());
                fetch('/rename_person/' + personId, {
                    method: 'POST',
                    body: formData,
                    headers: { 'X-Requested-With': 'XMLHttpRequest' }
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        showNotification('Person renamed to "' + data.name + '"');
                        location.reload();
                    } else {
                        showNotification('Failed to rename person');
                    }
                })
                .catch(() => showNotification('Failed to rename person'));
            }
        }

        // Close dropdown when clicking outside
        document.addEventListener('click', () => {
            document.querySelectorAll('.person-dropdown-menu').forEach(menu => {
                menu.classList.add('hidden');
            });
        });

        // Close drawer on Escape key, clear selection on Escape
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') {
                const drawer = document.getElementById('filter-drawer');
                if (!drawer.classList.contains('-translate-x-full')) {
                    toggleDrawer();
                } else if (selectedPhotos.size > 0) {
                    clearSelection();
                }
            }
        });

        // Toggle photo selection
        function toggleSelection(element, filename, path) {
            const checkmark = element.querySelector('.selection-check');
            const card = element.closest('.bg-neutral-900');

            if (selectedPhotos.has(filename)) {
                // Deselect
                selectedPhotos.delete(filename);
                checkmark.classList.add('hidden');
                card.classList.remove('border-green-500', 'ring-2', 'ring-green-500');
                card.classList.add('border-neutral-800');
            } else {
                // Select
                selectedPhotos.set(filename, {element: element, path: path});
                checkmark.classList.remove('hidden');
                card.classList.remove('border-neutral-800');
                card.classList.add('border-green-500', 'ring-2', 'ring-green-500');
            }

            updateToolbar();
        }

        // Update selection toolbar visibility and count
        function updateToolbar() {
            const toolbar = document.getElementById('selection-toolbar');
            const countEl = document.getElementById('selection-count');
            const countElMobile = document.getElementById('selection-count-mobile');
            countEl.textContent = selectedPhotos.size;
            countElMobile.textContent = selectedPhotos.size;

            if (selectedPhotos.size > 0) {
                toolbar.classList.remove('translate-y-20', 'opacity-0');
                toolbar.classList.add('translate-y-0', 'opacity-100');
            } else {
                toolbar.classList.remove('translate-y-0', 'opacity-100');
                toolbar.classList.add('translate-y-20', 'opacity-0');
            }
        }

        // Copy selected filenames to clipboard
        function copySelected() {
            if (selectedPhotos.size === 0) return;

            const filenames = Array.from(selectedPhotos.keys()).join('\\n');
            navigator.clipboard.writeText(filenames).then(function() {
                const count = selectedPhotos.size;
                showNotification('Copied ' + count + ' filename' + (count > 1 ? 's' : ''));
            }).catch(function(err) {
                console.error('Failed to copy: ', err);
            });
        }

        // Download selected photos as ZIP
        function downloadSelected() {
            if (selectedPhotos.size === 0) return;

            const paths = Array.from(selectedPhotos.values()).map(function(d) { return d.path; });
            const count = paths.length;
            showNotification('Downloading ' + count + ' photo' + (count > 1 ? 's' : '') + '...');

            // Download files sequentially with small delay to avoid browser blocking
            let index = 0;
            function downloadNext() {
                if (index >= paths.length) {
                    showNotification('Downloaded ' + count + ' photo' + (count > 1 ? 's' : ''));
                    return;
                }
                const path = paths[index];
                const a = document.createElement('a');
                a.href = '/api/download?path=' + encodeURIComponent(path);
                a.download = '';
                a.style.display = 'none';
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                index++;
                if (index < paths.length) {
                    setTimeout(downloadNext, 300);
                } else {
                    showNotification('Downloaded ' + count + ' photo' + (count > 1 ? 's' : ''));
                }
            }
            downloadNext();
        }

        // Clear all selections
        function clearSelection() {
            selectedPhotos.forEach(function(data, filename) {
                const checkmark = data.element.querySelector('.selection-check');
                const card = data.element.closest('.bg-neutral-900');
                checkmark.classList.add('hidden');
                card.classList.remove('border-green-500', 'ring-2', 'ring-green-500');
                card.classList.add('border-neutral-800');
            });
            selectedPhotos.clear();
            updateToolbar();
        }

        function showNotification(message) {
            const notification = document.getElementById('copy-notification');
            const text = document.getElementById('copy-notification-text');
            text.textContent = message;

            // Show notification
            notification.classList.remove('translate-y-20', 'opacity-0');
            notification.classList.add('translate-y-0', 'opacity-100');

            // Hide after configurable duration
            setTimeout(function() {
                notification.classList.remove('translate-y-0', 'opacity-100');
                notification.classList.add('translate-y-20', 'opacity-0');
            }, {{ viewer_config.notification_duration_ms }});
        }

        // Infinite Scroll
        (function() {
            const photoGrid = document.getElementById('photo-grid');
            const scrollLoader = document.getElementById('scroll-loader');
            const scrollSpinner = document.getElementById('scroll-spinner');
            const loadingSpinnerFixed = document.getElementById('loading-spinner-fixed');
            const scrollStatus = document.getElementById('scroll-status');
            const scrollEnd = document.getElementById('scroll-end');
            const currentCountEl = document.getElementById('current-count');
            const cardWidth = {{ viewer_config.display.card_width_px }};
            const imageWidth = {{ viewer_config.display.image_width_px }};

            let currentPage = parseInt(photoGrid.dataset.page);
            let totalPages = parseInt(photoGrid.dataset.totalPages);
            let sortCol = photoGrid.dataset.sortCol;
            let isLoading = false;
            let loadedCount = parseInt(currentCountEl.textContent);
            const hideDetails = document.body.classList.contains('details-hidden');

            // Track loaded photo paths to prevent duplicates during infinite scroll
            const loadedPaths = new Set();
            // Populate with initial photos from server render
            document.querySelectorAll('.photo-card[data-path]').forEach(card => {
                loadedPaths.add(decodeURIComponent(card.dataset.path));
            });

            // Get current URL params for API calls
            function getQueryParams() {
                return window.location.search;
            }

            // Format number with 1 decimal
            function safeFloat(val, decimals) {
                if (val === null || val === undefined || val === '') return '?';
                return parseFloat(val).toFixed(decimals);
            }

            // Format shutter speed as fraction
            function formatShutter(val) {
                if (!val || val === 0) return '?';
                const v = parseFloat(val);
                if (v >= 1) return v.toFixed(1) + 's';
                return '1/' + Math.round(1/v);
            }

            // Format date
            function formatDate(val) {
                if (!val) return '';
                try {
                    const parts = val.substring(0, 19).split(' ');
                    const dateParts = parts[0].split(':');
                    const timeParts = parts[1] ? parts[1].split(':') : ['00', '00'];
                    return `${dateParts[2]}/${dateParts[1]}/${dateParts[0]} ${timeParts[0]}:${timeParts[1]}`;
                } catch (e) {
                    return val.split(' ')[0].replace(/:/g, '/');
                }
            }

            // Format shutter speed
            function formatShutter(val) {
                if (!val) return '?';
                if (val >= 1) return val.toFixed(1) + 's';
                return '1/' + Math.round(1/val);
            }

            // Create photo card HTML
            function createPhotoCard(p) {
                const tags = (p.tags_list || []).map(tag =>
                    `<a href="?tag=${encodeURIComponent(tag)}" class="text-[10px] px-1.5 py-0.5 bg-neutral-800 text-neutral-400 rounded hover:bg-green-600 hover:text-white transition-colors">${tag}</a>`
                ).join('');

                const escapedFilename = p.filename.replace(/\\/g, '\\\\').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
                const escapedPath = p.path.replace(/\\/g, '\\\\').replace(/"/g, '&quot;').replace(/'/g, '&#39;');

                // Build person avatars (hide only on person_viewer page, exclude current person filter)
                const isPersonViewer = window.location.pathname.startsWith('/person/');
                const currentPersonFilter = new URLSearchParams(window.location.search).get('person');
                const filteredPersons = (p.persons || []).filter(person => String(person.id) !== currentPersonFilter);
                const removePersonBtn = EDITION_AUTHENTICATED && currentPersonFilter ? `
                    <button onclick="event.stopPropagation(); removePersonFromPhoto('${escapedPath}', ${currentPersonFilter})"
                            class="remove-person-btn w-8 h-8 rounded-full bg-red-600 hover:bg-red-500 flex items-center justify-center text-white"
                            title="Remove person from this photo">
                        <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M6 18L18 6M6 6l12 12"/>
                        </svg>
                    </button>` : '';
                const hasPersonContent = (!isPersonViewer && filteredPersons.length > 0) || removePersonBtn;
                const personsInner = (!isPersonViewer ? filteredPersons.map(person => {
                        const url = new URLSearchParams(window.location.search);
                        url.set('person', person.id);
                        return `<a href="?${url.toString()}" title="${person.name}" class="block">
                            <img src="/person_thumbnail/${person.id}"
                                 alt="${person.name}"
                                 class="w-8 h-8 rounded-full object-cover border border-neutral-700 hover:border-green-500 transition-colors"
                                 loading="lazy">
                        </a>`;
                    }).join('') : '') + removePersonBtn;
                const persons = hasPersonContent
                    ? `<div class="flex flex-wrap gap-1 mt-1 items-center">${personsInner}</div>`
                    : '';

                // Rating badges
                const starRating = p.star_rating || 0;
                const starBadge = starRating > 0 ? `<span class="text-[10px] font-medium text-yellow-400 mr-0.5">${'★'.repeat(starRating)}</span>` : '';
                const favBadge = p.is_favorite ? `<span class="text-[10px] font-medium text-red-400 mr-0.5" title="${t('rating.favorite')}">❤</span>` : '';
                const rejBadge = p.is_rejected ? '<span class="text-[10px] font-medium bg-red-900 text-red-400 px-1 rounded mr-0.5">REJ</span>' : '';

                const badges = [
                    favBadge,
                    rejBadge,
                    starBadge,
                    p.is_burst_lead ? '<span class="text-[10px] font-medium bg-green-900 text-green-400 px-1 rounded">BEST</span>' : '',
                    p.is_blink ? '<span class="text-[10px] font-medium bg-amber-900 text-amber-400 px-1 rounded">BLINK</span>' : '',
                    (p.duplicate_group_id && !p.is_duplicate_lead) ? `<span class="text-[10px] font-medium bg-purple-900 text-purple-400 px-1 rounded">${t('ui.badges.dup')}</span>` : '',
                    p.is_monochrome ? '<span class="text-[10px] font-medium bg-neutral-700 text-neutral-400 px-1 rounded">B&W</span>' : ''
                ].filter(b => b).join(' ');

                // Build tooltip with all scoring properties
                const category = (p.category || 'others').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
                let tooltip = `${p.filename}&#10;${p.date_formatted || ''}&#10;[${category}] Aggregate: ${safeFloat(p.aggregate, 1)}&#10;&#10;── Quality ──&#10;Aesthetic: ${safeFloat(p.aesthetic, 1)}`;
                if (p.quality_score) tooltip += `&#10;Quality: ${safeFloat(p.quality_score, 1)}`;
                if (p.face_count > 0) {
                    tooltip += `&#10;Face Quality: ${safeFloat(p.face_quality, 1)}`;
                    tooltip += `&#10;Face Sharpness: ${safeFloat(p.face_sharpness, 1)}`;
                    tooltip += `&#10;Eye Sharpness: ${safeFloat(p.eye_sharpness, 1)}`;
                }
                tooltip += `&#10;Tech Sharpness: ${safeFloat(p.tech_sharpness, 1)}`;
                tooltip += `&#10;&#10;── Composition ──&#10;Composition: ${safeFloat(p.comp_score, 1)}`;
                if (p.composition_pattern) tooltip += `&#10;Pattern: ${p.composition_pattern.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}`;
                if (p.power_point_score) tooltip += `&#10;Power Points: ${safeFloat(p.power_point_score, 1)}`;
                if (p.leading_lines_score) tooltip += `&#10;Leading Lines: ${safeFloat(p.leading_lines_score, 1)}`;
                tooltip += `&#10;&#10;── Technical ──&#10;Exposure: ${safeFloat(p.exposure_score, 1)}&#10;Color: ${safeFloat(p.color_score, 1)}`;
                if (p.contrast_score) tooltip += `&#10;Contrast: ${safeFloat(p.contrast_score, 1)}`;
                if (p.dynamic_range_stops) tooltip += `&#10;Dynamic Range: ${safeFloat(p.dynamic_range_stops, 1)}`;
                if (p.mean_saturation) tooltip += `&#10;Saturation: ${safeFloat(p.mean_saturation, 1)}`;
                if (p.noise_sigma) tooltip += `&#10;Noise: ${safeFloat(p.noise_sigma, 1)}`;
                tooltip += `&#10;&#10;── EXIF ──`;
                if (p.camera_model) tooltip += `&#10;Camera: ${p.camera_model}`;
                if (p.lens_model) tooltip += `&#10;Lens: ${p.lens_model}`;
                tooltip += `&#10;Focal: ${p.focal_length || '?'}mm&#10;Shutter: ${formatShutter(p.shutter_speed)}&#10;ISO: ${p.iso || '?'}`;
                if (p.isolation_bonus && p.isolation_bonus > 1.0) tooltip += `&#10;&#10;── Bonus ──&#10;Isolation: ${safeFloat(p.isolation_bonus, 1)}`;

                // Sort value display
                let sortValue;
                if (sortCol === 'date_taken' || sortCol === 'aggregate') {
                    sortValue = `<span class="text-green-400 font-bold text-base">${safeFloat(p.aggregate, 1)}</span>`;
                } else if (sortCol === 'shutter_speed') {
                    sortValue = `<span class="text-green-400 font-bold text-base" title="Shutter">${formatShutter(p[sortCol])}</span>`;
                } else if (sortCol === 'composition_pattern') {
                    const pattern = p[sortCol] || 'N/A';
                    sortValue = `<span class="text-green-400 font-bold text-base" title="Composition">${pattern.replace(/_/g, ' ')}</span>`;
                } else {
                    sortValue = `<span class="text-green-400 font-bold text-base">${safeFloat(p[sortCol], 1)}</span>`;
                }

                // Details: hidden entirely when hideDetails is on
                const detailsHtml = hideDetails ? '' : `
                        <div class="flex justify-between text-[12px] items-center">
                            <div class="text-neutral-300 truncate font-medium">${p.filename}</div>
                            <span class="text-green-400 font-medium">${safeFloat(p.aggregate, 1)}</span>
                        </div>
                        <div class="hidden sm:block">
                            <div class="flex justify-between items-center">
                                ${sortValue}
                                <span>${badges}</span>
                            </div>
                            <div class="flex justify-between text-neutral-400 text-[12px]">
                                <span>${p.date_formatted || ''}</span>
                            </div>
                            <div class="flex justify-between text-[12px] text-neutral-500">
                                <span>${p.focal_length || '?'}mm f/${p.f_stop || '?'}</span>
                                <span>${formatShutter(p.shutter_speed)} ISO ${p.iso || '?'}</span>
                            </div>
                            ${tags ? `<div class="flex flex-wrap gap-1 mt-1">${tags}</div>` : ''}
                        </div>`;
                const personsHtml = hideDetails ? '' : persons;

                return `
                <div class="photo-card group bg-neutral-900 flex flex-col gap-1 rounded border border-neutral-800 p-1.5 hover:border-green-500 transition-all w-full sm:w-auto" style="--card-width: ${cardWidth}px; --image-width: ${imageWidth}px" data-path="${encodeURIComponent(p.path)}">
                    <div class="photo-thumb-container flex-initial relative" onclick="toggleSelection(this, '${escapedFilename}', '${escapedPath}')" data-tooltip="${tooltip}">
                        <img src="/thumbnail?path=${encodeURIComponent(p.path)}&size=640" loading="lazy" class="photo-thumb rounded object-cover cursor-pointer w-full sm:w-auto">
                        <div class="selection-check hidden absolute top-1 right-1 w-6 h-6 bg-green-500 rounded-full flex items-center justify-center">
                            <svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"></path>
                            </svg>
                        </div>
                        ${FEATURES.show_rating_badge && (p.is_favorite || (p.star_rating && p.star_rating > 0)) ? `
                        <div class="rating-badge absolute top-8 right-1 bg-black/70 rounded px-1 py-0.5 text-xs font-medium z-10" data-path="${escapedPath}">
                            ${p.is_favorite ? '<span class="text-red-400">❤</span>' : `<span class="text-yellow-400">★${p.star_rating}</span>`}
                        </div>` : ''}
                        ${EDITION_AUTHENTICATED && (p.face_count || 0) > 0 && !currentPersonFilter ? `
                        <button onclick="event.stopPropagation(); showAssignFaceModal('${escapedPath}')"
                                class="assign-face-btn opacity-0 group-hover:opacity-100 absolute top-1 left-1 w-6 h-6 bg-blue-600 hover:bg-blue-500 rounded-full flex items-center justify-center text-white transition-opacity z-10"
                                title="Assign face to person">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6v6m0 0v6m0-6h6m-6 0H6"/>
                            </svg>
                        </button>` : ''}
                        ${FEATURES.show_similar_button ? `<button onclick="event.stopPropagation(); showSimilarPhotosModal('${escapedPath}')"
                                class="similar-btn opacity-0 group-hover:opacity-100 absolute bottom-1 left-1 w-6 h-6 bg-purple-600 hover:bg-purple-500 rounded-full flex items-center justify-center text-white transition-opacity z-10"
                                title="${t('similar.find_similar')}">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
                            </svg>
                        </button>` : ''}
                    </div>
                    ${!hideDetails ? `<div class="mt-1.5 text-left">
                        ${detailsHtml}
                        ${personsHtml}
                    </div>` : ''}
                </div>`;
            }

            // Load more photos
            async function loadMorePhotos() {
                if (isLoading || currentPage >= totalPages) return;

                isLoading = true;
                scrollSpinner.classList.remove('hidden');
                if (loadingSpinnerFixed) loadingSpinnerFixed.classList.remove('hidden');

                try {
                    const nextPage = currentPage + 1;
                    const params = new URLSearchParams(window.location.search);
                    params.set('page', nextPage);

                    const response = await fetch('/api/photos?' + params.toString());

                    // Check response status before parsing JSON
                    if (!response.ok) {
                        console.error('API request failed:', response.status, response.statusText);
                        return;
                    }

                    let data;
                    try {
                        data = await response.json();
                    } catch (jsonErr) {
                        console.error('Failed to parse API response:', jsonErr);
                        return;
                    }

                    if (data.error) {
                        console.error('API error:', data.error);
                        return;
                    }

                    // Append new photos (skip duplicates)
                    let addedCount = 0;
                    data.photos.forEach(photo => {
                        if (!loadedPaths.has(photo.path)) {
                            loadedPaths.add(photo.path);
                            photoGrid.insertAdjacentHTML('beforeend', createPhotoCard(photo));
                            addedCount++;
                        }
                    });

                    currentPage = data.page;
                    totalPages = data.total_pages;
                    loadedCount += addedCount;
                    currentCountEl.textContent = loadedCount;

                    // Update/hide loader if no more pages
                    if (!data.has_more) {
                        scrollLoader.classList.add('hidden');
                        scrollEnd.classList.remove('hidden');
                    }
                } catch (err) {
                    console.error('Failed to load photos:', err);
                } finally {
                    isLoading = false;
                    scrollSpinner.classList.add('hidden');
                    if (loadingSpinnerFixed) loadingSpinnerFixed.classList.add('hidden');

                    // Check if we need to load more (loader still visible after load)
                    requestAnimationFrame(() => {
                        if (currentPage < totalPages && isElementInViewport(scrollLoader)) {
                            loadMorePhotos();
                        }
                    });
                }
            }

            // Check if element is in viewport
            function isElementInViewport(el) {
                const rect = el.getBoundingClientRect();
                return rect.top < window.innerHeight + 500 && rect.bottom > 0;
            }

            // Scroll detection using IntersectionObserver (more reliable than scroll events)
            function checkScroll() {
                if (isLoading || currentPage >= totalPages) return;

                const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
                const windowHeight = window.innerHeight;
                const docHeight = document.documentElement.scrollHeight;

                // Load more when within 500px of bottom (increased threshold)
                if (scrollTop + windowHeight >= docHeight - 500) {
                    loadMorePhotos();
                }
            }

            // Use IntersectionObserver for reliable scroll detection
            if ('IntersectionObserver' in window) {
                const observer = new IntersectionObserver(function(entries) {
                    entries.forEach(function(entry) {
                        if (entry.isIntersecting && !isLoading && currentPage < totalPages) {
                            loadMorePhotos();
                        }
                    });
                }, {
                    rootMargin: '500px 0px',  // Trigger 500px before visible
                    threshold: 0
                });
                observer.observe(scrollLoader);
            } else {
                // Fallback: Throttle scroll events for browsers without IntersectionObserver
                let scrollTimeout;
                window.addEventListener('scroll', function() {
                    if (scrollTimeout) return;
                    scrollTimeout = setTimeout(function() {
                        scrollTimeout = null;
                        checkScroll();
                    }, 100);
                });
            }

            // Also check on initial load in case page is short
            setTimeout(checkScroll, 500);

            // Debug: Log scroll state for troubleshooting
            console.log('Infinite scroll initialized:', {
                currentPage: currentPage,
                totalPages: totalPages,
                loadedCount: loadedCount,
                isLoading: isLoading
            });
        })();

        // Hover preview functionality
        (function() {
            const preview = document.getElementById('hover-preview');
            const previewImg = preview.querySelector('img');
            const personPreview = document.getElementById('person-hover-preview');
            const personPreviewImg = personPreview.querySelector('img');
            const personPreviewName = personPreview.querySelector('.person-name');
            const photoPreview = document.getElementById('photo-hover-preview');
            const photoPreviewImg = photoPreview.querySelector('img');
            const photoPreviewDetails = photoPreview.querySelector('.preview-details');
            const hideDetails = document.body.classList.contains('details-hidden');
            let hoverTimeout = null;

            function isPhotoThumbnail(img) {
                return img.src && img.src.includes('/thumbnail?');
            }

            function isPersonThumbnail(img) {
                return img.src && img.src.includes('/person_thumbnail/');
            }

            function parseTooltipData(tooltipStr) {
                // Parse the tooltip string into structured data
                const lines = tooltipStr.split(/&#10;|\n/).filter(l => l.trim());
                const data = { sections: [], filename: '', date: '' };
                let currentSection = null;
                let headerLines = [];

                for (const line of lines) {
                    if (line.startsWith('[')) {
                        // Category and aggregate line — preceding lines are filename/date
                        if (headerLines.length >= 1) data.filename = headerLines[0];
                        if (headerLines.length >= 2) data.date = headerLines[1];
                        const match = line.match(/\[([^\]]+)\]\s*Aggregate:\s*([\d.]+)/);
                        if (match) {
                            data.category = match[1];
                            data.aggregate = match[2];
                        }
                    } else if (line.startsWith('──')) {
                        // Section header
                        const title = line.replace(/──/g, '').trim();
                        currentSection = { title, scores: [] };
                        data.sections.push(currentSection);
                    } else if (line.includes(':') && currentSection) {
                        // Score line
                        const [label, value] = line.split(':').map(s => s.trim());
                        if (label && value) {
                            currentSection.scores.push({ label, value });
                        }
                    } else if (!data.category) {
                        // Lines before category = filename, date
                        headerLines.push(line);
                    }
                }
                return data;
            }

            function buildDetailsHtml(data) {
                let html = '';
                if (data.filename) html += `<div class="preview-filename">${data.filename}</div>`;
                if (data.date) html += `<div class="preview-date">${data.date}</div>`;
                html += `<div class="category">[${data.category}] ${data.aggregate}</div>`;
                for (const section of data.sections) {
                    html += `<div class="score-section">`;
                    html += `<div class="score-section-title">${section.title}</div>`;
                    for (const score of section.scores) {
                        html += `<div class="score-row"><span class="score-label">${score.label}</span><span class="score-value">${score.value}</span></div>`;
                    }
                    html += `</div>`;
                }
                return html;
            }

            function getPreviewSizes(isLandscape) {
                const vh = window.innerHeight;
                const vw = window.innerWidth;
                const simple = Math.round(Math.min(Math.max(Math.min(vh, vw) * 0.4, 200), 640));
                if (isLandscape) {
                    // Landscape: photo on top, 2-col details below
                    const imgW = Math.round(Math.min(Math.max(vw * 0.25, 250), 450));
                    return { detailImg: imgW, detailWidth: imgW + 20, detailHeight: Math.round(vh * 0.5), simple };
                } else {
                    // Portrait: side-by-side, image takes full height
                    const imgH = Math.round(Math.min(vh * 0.55, 500));
                    return { detailImg: imgH, detailWidth: imgH + 280, detailHeight: imgH + 20, simple };
                }
            }

            function showPreview(e) {
                const img = e.target;
                if (!isPhotoThumbnail(img)) return;

                if (hoverTimeout) {
                    clearTimeout(hoverTimeout);
                    hoverTimeout = null;
                }

                // Check if we should show details
                const container = img.closest('.photo-thumb-container');
                const tooltipData = container?.getAttribute('data-tooltip');

                // Detect aspect ratio from the grid thumbnail
                const isLandscape = img.naturalWidth > img.naturalHeight;
                const sizes = getPreviewSizes(isLandscape);

                if (tooltipData) {
                    // Toggle layout class based on orientation
                    photoPreview.classList.toggle('landscape', isLandscape);
                    // Show photo preview with details
                    photoPreviewImg.src = img.src.replace('size=320', 'size=640');
                    if (isLandscape) {
                        photoPreviewImg.style.width = sizes.detailImg + 'px';
                        photoPreviewImg.style.height = 'auto';
                    } else {
                        photoPreviewImg.style.height = sizes.detailImg + 'px';
                        photoPreviewImg.style.width = 'auto';
                    }
                    const data = parseTooltipData(tooltipData);
                    photoPreviewDetails.innerHTML = buildDetailsHtml(data);
                    positionPreview(e, photoPreview, sizes.detailWidth, sizes.detailHeight);
                    photoPreview.classList.add('visible');
                } else {
                    // Show simple large preview
                    previewImg.src = img.src.replace('size=320', 'size=480');
                    previewImg.style.maxWidth = sizes.simple + 'px';
                    previewImg.style.maxHeight = sizes.simple + 'px';
                    positionPreview(e, preview, sizes.simple, sizes.simple);
                    preview.classList.add('visible');
                }
            }

            function showPersonPreview(e) {
                const img = e.target;
                if (!isPersonThumbnail(img)) return;

                if (hoverTimeout) {
                    clearTimeout(hoverTimeout);
                    hoverTimeout = null;
                }

                personPreviewImg.src = img.src;
                personPreviewName.textContent = img.alt || img.closest('a')?.title || '';
                positionPreview(e, personPreview, 160, 200);
                personPreview.classList.add('visible');
            }

            function hidePreview() {
                hoverTimeout = setTimeout(() => {
                    preview.classList.remove('visible');
                    personPreview.classList.remove('visible');
                    photoPreview.classList.remove('visible');
                }, 50);
            }

            function positionPreview(e, previewEl, previewWidth, previewHeight) {
                const padding = 20;

                let x = e.clientX + padding;
                let y = e.clientY - previewHeight / 2;

                if (x + previewWidth > window.innerWidth - padding) {
                    x = e.clientX - previewWidth - padding;
                }

                if (y < padding) {
                    y = padding;
                } else if (y + previewHeight > window.innerHeight - padding) {
                    y = window.innerHeight - previewHeight - padding;
                }

                previewEl.style.left = x + 'px';
                previewEl.style.top = y + 'px';
            }

            document.getElementById('photo-grid').addEventListener('mouseenter', function(e) {
                if (e.target.tagName === 'IMG') {
                    if (isPhotoThumbnail(e.target)) {
                        showPreview(e);
                    } else if (isPersonThumbnail(e.target)) {
                        showPersonPreview(e);
                    }
                }
            }, true);

            document.getElementById('photo-grid').addEventListener('mouseleave', function(e) {
                if (e.target.tagName === 'IMG' && (isPhotoThumbnail(e.target) || isPersonThumbnail(e.target))) {
                    hidePreview();
                }
            }, true);

            document.getElementById('photo-grid').addEventListener('mousemove', function(e) {
                if (e.target.tagName === 'IMG') {
                    if (isPhotoThumbnail(e.target)) {
                        const isLandscape = photoPreview.classList.contains('landscape');
                        const sizes = getPreviewSizes(isLandscape);
                        if (photoPreview.classList.contains('visible')) {
                            positionPreview(e, photoPreview, sizes.detailWidth, sizes.detailHeight);
                        } else if (preview.classList.contains('visible')) {
                            positionPreview(e, preview, sizes.simple, sizes.simple);
                        }
                    } else if (isPersonThumbnail(e.target) && personPreview.classList.contains('visible')) {
                        positionPreview(e, personPreview, 160, 200);
                    }
                }
            }, true);
        })();

        // Face assignment functionality - allows assigning individual faces to persons
        let assignPhotoPath = null;
        let assignFaceId = null;  // Track which specific face to assign (null = all unassigned)
        let allPersons = [];

        async function showAssignFaceModal(photoPath) {
            assignPhotoPath = photoPath;
            assignFaceId = null;

            // Fetch faces in this photo to check if we need face selection
            try {
                const response = await fetch(`/api/photo/faces?path=${encodeURIComponent(photoPath)}`);
                const data = await response.json();
                const faces = data.faces || [];

                if (faces.length === 0) {
                    alert('No faces found in this photo');
                    return;
                }

                if (faces.length === 1) {
                    // Single face - assign directly
                    assignFaceId = faces[0].id;
                    showSelectPersonModal();
                } else {
                    // Multiple faces - show face selection modal
                    showSelectFaceModal(faces);
                }
            } catch (err) {
                console.error('Error fetching faces:', err);
                alert('Error loading faces');
            }
        }

        function showSelectFaceModal(faces) {
            const grid = document.getElementById('select-face-grid');
            grid.innerHTML = '';

            for (const face of faces) {
                const el = document.createElement('div');
                el.className = 'cursor-pointer bg-neutral-800 hover:bg-blue-600 rounded-lg p-2 text-center transition-colors';
                el.onclick = () => selectFaceForAssignment(face.id);

                const assignedInfo = face.person_name
                    ? `<div class="text-xs text-green-400 truncate">&rarr; ${face.person_name}</div>`
                    : `<div class="text-xs text-neutral-500">Unassigned</div>`;

                el.innerHTML = `
                    <img src="/face_thumbnail/${face.id}" class="w-full aspect-square rounded object-cover mb-2" loading="lazy">
                    <div class="text-xs text-neutral-300">Face ${face.face_index + 1}</div>
                    ${assignedInfo}
                `;
                grid.appendChild(el);
            }

            document.getElementById('select-face-modal').classList.remove('hidden');
        }

        function selectFaceForAssignment(faceId) {
            assignFaceId = faceId;
            closeSelectFaceModal();
            showSelectPersonModal();
        }

        function closeSelectFaceModal() {
            document.getElementById('select-face-modal').classList.add('hidden');
        }

        async function showSelectPersonModal() {
            const grid = document.getElementById('select-person-grid');
            grid.innerHTML = '<div class="col-span-6 text-center text-neutral-500">Loading...</div>';
            document.getElementById('select-person-modal').classList.remove('hidden');

            try {
                const response = await fetch('/api/filter_options/persons');
                const data = await response.json();
                // Only show named persons (filter out auto-clustered "Person 123")
                allPersons = (data.persons || []).filter(([id, name]) => name);
                renderPersonGrid(allPersons);
            } catch (err) {
                grid.innerHTML = `<div class="col-span-6 text-center text-red-500">${t('manage_persons.error_loading_persons')}</div>`;
            }
        }

        function renderPersonGrid(persons) {
            const grid = document.getElementById('select-person-grid');
            grid.innerHTML = '';
            for (const [id, name, count] of persons) {
                const el = document.createElement('div');
                el.className = 'cursor-pointer bg-neutral-800 hover:bg-blue-600 rounded-lg p-2 text-center transition-colors';
                el.onclick = () => assignAllFacesToPerson(id);
                el.innerHTML = `
                    <img src="/person_thumbnail/${id}" class="w-full aspect-square rounded-full object-cover mb-2" loading="lazy">
                    <div class="text-xs text-neutral-300 truncate">${name}</div>
                    <div class="text-xs text-neutral-500">${count} photos</div>
                `;
                grid.appendChild(el);
            }
            if (persons.length === 0) {
                grid.innerHTML = `<div class="col-span-6 text-center text-neutral-500">${t('manage_persons.no_named_persons')}</div>`;
            }
        }

        document.getElementById('person-search').addEventListener('input', function(e) {
            const query = e.target.value.toLowerCase();
            const filtered = allPersons.filter(([id, name]) =>
                (name || 'Person ' + id).toLowerCase().includes(query)
            );
            renderPersonGrid(filtered);
        });

        function closeSelectPersonModal() {
            document.getElementById('select-person-modal').classList.add('hidden');
            document.getElementById('person-search').value = '';
            assignPhotoPath = null;
        }

        // Similar photos modal functions
        async function showSimilarPhotosModal(photoPath) {
            const modal = document.getElementById('similar-photos-modal');
            const grid = document.getElementById('similar-photos-grid');
            const loading = document.getElementById('similar-photos-loading');
            const empty = document.getElementById('similar-photos-empty');

            modal.classList.remove('hidden');
            grid.innerHTML = '';
            loading.classList.remove('hidden');
            empty.classList.add('hidden');

            try {
                const response = await fetch(`/api/similar_photos/${encodeURIComponent(photoPath)}?limit=20`);
                const data = await response.json();

                loading.classList.add('hidden');

                if (data.error) {
                    empty.textContent = data.error;
                    empty.classList.remove('hidden');
                    return;
                }

                if (!data.similar || data.similar.length === 0) {
                    empty.classList.remove('hidden');
                    return;
                }

                // Render similar photos
                data.similar.forEach(photo => {
                    const simPercent = Math.round(photo.similarity * 100);
                    const breakdown = photo.breakdown || {};

                    // Build breakdown tooltip
                    let breakdownText = [];
                    if (breakdown.clip !== undefined) breakdownText.push(`${t('similar.visual')}: ${Math.round(breakdown.clip * 100)}%`);
                    if (breakdown.persons !== undefined) breakdownText.push(`${t('similar.persons')}: ${Math.round(breakdown.persons * 100)}%`);
                    if (breakdown.date !== undefined) breakdownText.push(`${t('similar.date')}: ${Math.round(breakdown.date * 100)}%`);
                    if (breakdown.score !== undefined) breakdownText.push(`${t('similar.score')}: ${Math.round(breakdown.score * 100)}%`);

                    const card = document.createElement('div');
                    card.className = 'similar-photo-card cursor-pointer hover:ring-2 hover:ring-purple-500 rounded-lg overflow-hidden bg-neutral-800';
                    card.title = breakdownText.join('\\n');
                    const filename = photo.filename;
                    card.innerHTML = `
                        <div class="relative w-full aspect-square">
                            <img src="/thumbnail?path=${encodeURIComponent(photo.path)}&size=320" class="absolute inset-0 w-full h-full object-cover" loading="lazy">
                            <div class="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/90 to-transparent p-2">
                                <div class="text-white text-sm font-medium">${simPercent}% ${t('similar.similarity')}</div>
                                <div class="text-neutral-300 text-xs">${safeFloat(photo.aggregate, 1)} score</div>
                            </div>
                        </div>
                        <div class="p-2">
                            <div class="text-xs text-neutral-400 truncate" title="${filename}">${filename}</div>
                        </div>
                    `;
                    card.onclick = () => {
                        closeSimilarPhotosModal();
                        // Navigate to photo - find card and scroll to it, or search by filename with filters reset
                        const photoCard = document.querySelector(`.photo-card[data-path="${encodeURIComponent(photo.path)}"]`);
                        if (photoCard) {
                            photoCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
                            photoCard.classList.add('ring-2', 'ring-purple-500');
                            setTimeout(() => photoCard.classList.remove('ring-2', 'ring-purple-500'), 2000);
                        } else {
                            // Photo not on current page - search by filename with all filters reset
                            window.location.href = `/?search=${encodeURIComponent(filename)}&type=&hide_blinks=0&hide_bursts=0&hide_duplicates=0&hide_rejected=0`;
                        }
                    };
                    grid.appendChild(card);
                });
            } catch (err) {
                loading.classList.add('hidden');
                empty.textContent = 'Error: ' + err.message;
                empty.classList.remove('hidden');
            }
        }

        function closeSimilarPhotosModal() {
            document.getElementById('similar-photos-modal').classList.add('hidden');
        }

        async function assignAllFacesToPerson(personId) {
            if (!assignPhotoPath) return;

            try {
                let response, data;

                if (assignFaceId) {
                    // Assign specific face
                    response = await fetch(`/api/face/${assignFaceId}/assign`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-Requested-With': 'XMLHttpRequest'
                        },
                        body: JSON.stringify({ person_id: personId })
                    });
                } else {
                    // Assign all unassigned faces
                    response = await fetch('/api/photo/assign_all_faces', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-Requested-With': 'XMLHttpRequest'
                        },
                        body: JSON.stringify({ photo_path: assignPhotoPath, person_id: personId })
                    });
                }

                data = await response.json();

                if (data.success) {
                    closeSelectPersonModal();
                    showNotification(t('notifications.faces_assigned') || 'Face assigned');
                } else {
                    alert('Error assigning faces: ' + (data.error || 'Unknown error'));
                }
            } catch (err) {
                alert('Error assigning faces: ' + err.message);
            }
        }

        async function removePersonFromPhoto(photoPath, personId) {
            if (!confirm('Remove this person from this photo?')) return;
            try {
                const response = await fetch('/api/photo/unassign_person', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
                    body: JSON.stringify({ photo_path: photoPath, person_id: personId })
                });
                const data = await response.json();
                if (response.ok) {
                    // Remove the photo card from view
                    const card = document.querySelector(`[data-path="${CSS.escape(encodeURIComponent(photoPath))}"]`);
                    if (card) card.remove();
                } else {
                    alert('Error: ' + (data.error || 'Unknown error'));
                }
            } catch (err) {
                alert('Error: ' + err.message);
            }
        }

        // Close modals on escape key
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') {
                closeSelectPersonModal();
                closeSimilarPhotosModal();
                if (typeof closeEditionLoginModal === 'function') closeEditionLoginModal();
            }
        });

        // Close modals on backdrop click
        document.getElementById('select-person-modal').addEventListener('click', function(e) {
            if (e.target.id === 'select-person-modal') closeSelectPersonModal();
        });

        // Edition login modal backdrop click
        const editionModal = document.getElementById('edition-login-modal');
        if (editionModal) {
            editionModal.addEventListener('click', function(e) {
                if (e.target.id === 'edition-login-modal') closeEditionLoginModal();
            });
        }

        // Rating functions (edition mode)
        async function setRating(photoPath, rating, starContainer) {
            try {
                const response = await fetch('/api/photo/set_rating', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
                    body: JSON.stringify({ photo_path: photoPath, rating: rating })
                });
                const data = await response.json();
                if (data.success) {
                    // Update star display
                    const stars = starContainer.querySelectorAll('.star-btn');
                    stars.forEach((star, i) => {
                        if (i < rating) {
                            star.classList.add('text-yellow-400');
                            star.classList.remove('text-neutral-500');
                        } else {
                            star.classList.remove('text-yellow-400');
                            star.classList.add('text-neutral-500');
                        }
                    });
                    starContainer.dataset.current = rating;
                    // Update rating badge (check if favorited first - heart takes priority)
                    const favoriteBtn = starContainer.closest('.rating-controls')?.querySelector('[data-favorite]');
                    const isFavorite = favoriteBtn?.dataset.favorite === '1';
                    updateRatingBadge(photoPath, rating, isFavorite);
                    showNotification(t('rating.set_rating') + ': ' + rating + ' ★');
                } else {
                    showNotification('Error: ' + (data.error || 'Unknown'), true);
                }
            } catch (err) {
                showNotification('Error: ' + err.message, true);
            }
        }

        async function toggleFavorite(photoPath, btn) {
            try {
                const response = await fetch('/api/photo/toggle_favorite', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
                    body: JSON.stringify({ photo_path: photoPath })
                });
                const data = await response.json();
                if (data.success) {
                    if (data.is_favorite) {
                        btn.classList.add('text-red-400');
                        btn.classList.remove('text-neutral-500');
                        btn.dataset.favorite = '1';
                        // When marking favorite, also clear rejected (mutually exclusive)
                        const rejectedBtn = btn.closest('.rating-controls')?.querySelector('.rejected-btn');
                        if (rejectedBtn) {
                            rejectedBtn.classList.remove('text-red-600');
                            rejectedBtn.classList.add('text-neutral-500');
                            rejectedBtn.dataset.rejected = '0';
                        }
                    } else {
                        btn.classList.remove('text-red-400');
                        btn.classList.add('text-neutral-500');
                        btn.dataset.favorite = '0';
                    }
                    // Update rating badge (get current star rating to show if not favorite)
                    const starContainer = btn.closest('.rating-controls')?.querySelector('.star-rating');
                    const starRating = parseInt(starContainer?.dataset.current || '0', 10);
                    updateRatingBadge(photoPath, starRating, data.is_favorite);
                    showNotification(data.is_favorite ? t('rating.add_favorite') : t('rating.remove_favorite'));
                } else {
                    showNotification('Error: ' + (data.error || 'Unknown'), true);
                }
            } catch (err) {
                showNotification('Error: ' + err.message, true);
            }
        }

        async function toggleRejected(photoPath, btn) {
            try {
                const response = await fetch('/api/photo/toggle_rejected', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
                    body: JSON.stringify({ photo_path: photoPath })
                });
                const data = await response.json();
                if (data.success) {
                    if (data.is_rejected) {
                        btn.classList.add('text-red-600');
                        btn.classList.remove('text-neutral-500');
                        btn.dataset.rejected = '1';
                        // When rejecting, also reset star rating to 0 and clear favorite
                        const starContainer = btn.closest('.rating-controls').querySelector('.star-rating');
                        if (starContainer) {
                            starContainer.dataset.current = '0';
                            starContainer.querySelectorAll('.star-btn').forEach(s => {
                                s.classList.remove('text-yellow-400');
                                s.classList.add('text-neutral-500');
                            });
                        }
                        // Clear favorite (mutually exclusive)
                        const favoriteBtn = btn.closest('.rating-controls')?.querySelector('.favorite-btn');
                        if (favoriteBtn) {
                            favoriteBtn.classList.remove('text-red-400');
                            favoriteBtn.classList.add('text-neutral-500');
                            favoriteBtn.dataset.favorite = '0';
                        }
                        // Update rating badge (remove)
                        updateRatingBadge(photoPath, 0, false);
                    } else {
                        btn.classList.remove('text-red-600');
                        btn.classList.add('text-neutral-500');
                        btn.dataset.rejected = '0';
                    }
                    showNotification(data.is_rejected ? t('rating.mark_rejected') : t('rating.unmark_rejected'));
                } else {
                    showNotification('Error: ' + (data.error || 'Unknown'), true);
                }
            } catch (err) {
                showNotification('Error: ' + err.message, true);
            }
        }

        // Helper function to update rating badge on photo thumbnail
        function updateRatingBadge(photoPath, starRating, isFavorite) {
            const escapedPath = photoPath.replace(/'/g, "\\'");
            const badge = document.querySelector(`.rating-badge[data-path="${escapedPath}"]`);
            const container = document.querySelector(`.photo-thumb-container[onclick*="${escapedPath}"]`) ||
                             document.querySelector(`[data-path="${encodeURIComponent(photoPath)}"] .photo-thumb-container`);

            if (isFavorite) {
                // Show heart
                if (badge) {
                    badge.innerHTML = '<span class="text-red-400">❤</span>';
                } else if (container) {
                    const newBadge = document.createElement('div');
                    newBadge.className = 'rating-badge absolute top-8 right-1 bg-black/70 rounded px-1 py-0.5 text-xs font-medium z-10';
                    newBadge.dataset.path = photoPath;
                    newBadge.innerHTML = '<span class="text-red-400">❤</span>';
                    container.appendChild(newBadge);
                }
            } else if (starRating > 0) {
                // Show star count
                if (badge) {
                    badge.innerHTML = `<span class="text-yellow-400">★${starRating}</span>`;
                } else if (container) {
                    const newBadge = document.createElement('div');
                    newBadge.className = 'rating-badge absolute top-8 right-1 bg-black/70 rounded px-1 py-0.5 text-xs font-medium z-10';
                    newBadge.dataset.path = photoPath;
                    newBadge.innerHTML = `<span class="text-yellow-400">★${starRating}</span>`;
                    container.appendChild(newBadge);
                }
            } else {
                // Remove badge
                if (badge) {
                    badge.remove();
                }
            }
        }
    </script>
</body>
</html>
'''

_thumbnail_cache_size = _viewer_perf.get('thumbnail_cache_size', 2000)

@lru_cache(maxsize=_thumbnail_cache_size)
def _resize_thumbnail(thumbnail_bytes, size):
    """Resize a thumbnail to the given max dimension. Returns JPEG bytes."""
    from PIL import Image
    img = Image.open(BytesIO(thumbnail_bytes))
    if max(img.size) <= size:
        return thumbnail_bytes
    img.thumbnail((size, size), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, format='JPEG', quality=80)
    return buf.getvalue()


@app.route('/thumbnail')
def get_thumbnail():
    photo_path = request.args.get('path')
    size = request.args.get('size', type=int)
    conn = get_db_connection()
    row = conn.execute("SELECT thumbnail FROM photos WHERE path = ?", (photo_path,)).fetchone()
    conn.close()

    if row and row['thumbnail']:
        thumb_bytes = row['thumbnail']

        # Resize if requested and smaller than stored 640px
        if size and 0 < size < 640:
            thumb_bytes = _resize_thumbnail(thumb_bytes, size)

        # Generate ETag from content hash (includes size variant)
        etag = hashlib.md5(thumb_bytes).hexdigest()

        # Check If-None-Match header for conditional request
        if request.headers.get('If-None-Match') == etag:
            return '', 304

        response = make_response(send_file(BytesIO(thumb_bytes), mimetype='image/jpeg'))
        response.headers['Cache-Control'] = 'public, max-age=31536000'  # 1 year
        response.headers['ETag'] = etag
        return response
    return "Thumbnail not found", 404


_face_cache_size = _viewer_perf.get('face_cache_size', 500)

@lru_cache(maxsize=_face_cache_size)
def _get_face_thumbnail_data(face_id):
    """Get face thumbnail bytes with LRU caching. Returns (face_bytes, etag) or (None, None) on error.

    First checks for pre-stored face_thumbnail (generated during --batch scanning).
    Falls back to on-demand generation from photo thumbnail for legacy data.
    """
    from PIL import Image

    conn = get_db_connection()
    face = conn.execute("""
        SELECT f.photo_path, f.bbox_x1, f.bbox_y1, f.bbox_x2, f.bbox_y2,
               f.face_thumbnail, p.thumbnail
        FROM faces f
        JOIN photos p ON p.path = f.photo_path
        WHERE f.id = ?
    """, (face_id,)).fetchone()
    conn.close()

    if not face:
        return None, None

    # Check for pre-stored face thumbnail first (faster path)
    if face['face_thumbnail']:
        etag = hashlib.md5(face['face_thumbnail']).hexdigest()
        return face['face_thumbnail'], etag

    # Fall back to on-demand generation from photo thumbnail (legacy data)
    if not face['thumbnail']:
        return None, None

    try:
        # Get bbox coordinates (these are from original full-size image)
        bbox_x1, bbox_y1, bbox_x2, bbox_y2 = face['bbox_x1'], face['bbox_y1'], face['bbox_x2'], face['bbox_y2']

        if bbox_x1 is None or bbox_x2 is None:
            return None, None

        # Generate ETag for caching
        etag = hashlib.md5(f"{face_id}:{bbox_x1}:{bbox_y1}:{bbox_x2}:{bbox_y2}".encode()).hexdigest()

        # Load the photo thumbnail
        thumb_img = Image.open(BytesIO(face['thumbnail']))
        thumb_w, thumb_h = thumb_img.size

        # Estimate original dimensions from bbox (bbox must fit within original)
        if thumb_w >= thumb_h:
            estimated_orig_longest = max(bbox_x2, bbox_y2 * thumb_w / thumb_h)
        else:
            estimated_orig_longest = max(bbox_y2, bbox_x2 * thumb_h / thumb_w)

        # Add small margin and calculate uniform scale
        estimated_orig_longest = max(estimated_orig_longest * 1.05, 100)
        scale = max(thumb_w, thumb_h) / estimated_orig_longest

        # Scale bbox to thumbnail coordinates (uniform scale)
        x1 = max(0, int(bbox_x1 * scale))
        y1 = max(0, int(bbox_y1 * scale))
        x2 = min(thumb_w, int(bbox_x2 * scale))
        y2 = min(thumb_h, int(bbox_y2 * scale))

        # Add padding (configurable)
        padding_ratio = VIEWER_CONFIG['face_thumbnails']['crop_padding_ratio']
        pad_x = int((x2 - x1) * padding_ratio)
        pad_y = int((y2 - y1) * padding_ratio)
        x1 = max(0, x1 - pad_x)
        y1 = max(0, y1 - pad_y)
        x2 = min(thumb_w, x2 + pad_x)
        y2 = min(thumb_h, y2 + pad_y)

        # Ensure minimum size (configurable)
        min_size = VIEWER_CONFIG['face_thumbnails']['min_crop_size_px']
        if x2 - x1 < min_size or y2 - y1 < min_size:
            # Fallback: return center crop
            cx, cy = thumb_w // 2, thumb_h // 2
            size = min(thumb_w, thumb_h) // 2
            x1, y1 = cx - size, cy - size
            x2, y2 = cx + size, cy + size

        # Crop face region
        face_crop = thumb_img.crop((x1, y1, x2, y2))

        # Resize to consistent size (configurable)
        output_size = VIEWER_CONFIG['face_thumbnails']['output_size_px']
        face_crop.thumbnail((output_size, output_size), Image.Resampling.LANCZOS)

        # Save to buffer (configurable quality)
        buf = BytesIO()
        face_crop.save(buf, format="JPEG", quality=VIEWER_CONFIG['face_thumbnails']['jpeg_quality'])
        return buf.getvalue(), etag
    except Exception:
        return None, None


@app.route('/face_thumbnail/<int:face_id>')
def face_thumbnail(face_id):
    """Return cropped face thumbnail from photo with LRU caching."""
    face_bytes, etag = _get_face_thumbnail_data(face_id)

    if face_bytes is None:
        return "Face not found", 404

    # Check If-None-Match header for conditional request
    if request.headers.get('If-None-Match') == etag:
        return '', 304

    response = make_response(send_file(BytesIO(face_bytes), mimetype='image/jpeg'))
    response.headers['Cache-Control'] = 'public, max-age=31536000'
    response.headers['ETag'] = etag
    return response


@app.route('/person_thumbnail/<int:person_id>')
def person_thumbnail(person_id):
    """Return stored face thumbnail for a person, with fallback to face_thumbnail."""
    conn = get_db_connection()
    person = conn.execute("""
        SELECT face_thumbnail, representative_face_id FROM persons WHERE id = ?
    """, (person_id,)).fetchone()
    conn.close()

    if person and person['face_thumbnail']:
        # Add caching headers
        etag = hashlib.md5(person['face_thumbnail']).hexdigest()
        if request.headers.get('If-None-Match') == etag:
            return '', 304

        response = make_response(send_file(BytesIO(person['face_thumbnail']), mimetype='image/jpeg'))
        response.headers['Cache-Control'] = 'public, max-age=31536000'
        response.headers['ETag'] = etag
        return response

    # Fallback: use face_thumbnail endpoint if no stored thumbnail
    if person and person['representative_face_id']:
        return face_thumbnail(person['representative_face_id'])

    return "Person thumbnail not found", 404


@app.route('/rename_person/<int:person_id>', methods=['POST'])
def rename_person(person_id):
    """Rename a person (set or update their name)."""
    if not is_edition_authenticated():
        return jsonify({'error': 'Edition disabled'}), 403
    global _filter_options_cache
    name = request.form.get('name', '').strip()
    conn = get_db_connection()
    conn.execute("UPDATE persons SET name = ? WHERE id = ?", (name or None, person_id))
    conn.commit()
    conn.close()
    _filter_options_cache['data'] = None  # Invalidate cache so new name appears
    # Return JSON for AJAX requests
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return {'success': True, 'name': name or f'Person {person_id}'}
    return redirect(request.referrer or '/')


@app.route('/')
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

    # 3. Build WHERE clauses
    where_clauses = []
    sql_params = []

    # Helper to add range filters
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
    if params['camera']:
        where_clauses.append("camera_model = ?")
        sql_params.append(params['camera'])

    if params['lens']:
        clean_search = params['lens'].split('\ufffd')[0].strip()
        where_clauses.append("lens_model LIKE ?")
        sql_params.append(f"{clean_search}%")

    # Filename search filter
    if params.get('search'):
        where_clauses.append("filename LIKE ?")
        sql_params.append(f"%{params['search']}%")

    # Tag filters (single tag, require_tags, exclude_tags, exclude_art)
    conn = get_db_connection()
    _add_tag_filter(
        where_clauses, sql_params,
        tag=params.get('tag'),
        require_tags=params.get('require_tags'),
        exclude_tags=params.get('exclude_tags'),
        exclude_art_tags=get_art_tags_from_config() if params.get('exclude_art') == '1' else None,
        conn=conn
    )

    # Composition pattern filter (SAMP-Net)
    if params.get('composition_pattern'):
        where_clauses.append("composition_pattern = ?")
        sql_params.append(params['composition_pattern'])

    # Person filter (face recognition) - uses EXISTS for better performance
    if params.get('person'):
        try:
            person_id = int(params['person'])
            where_clauses.append("EXISTS (SELECT 1 FROM faces WHERE photo_path = photos.path AND person_id = ?)")
            sql_params.append(person_id)
        except ValueError:
            pass

    # B&W filter
    if params.get('is_monochrome') == '1':
        where_clauses.append("is_monochrome = 1")

    # Category filter (from type selection)
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

    # Luminance filter (for low light)
    if params.get('max_luminance'):
        try:
            where_clauses.append("mean_luminance < ?")
            sql_params.append(float(params['max_luminance']))
        except ValueError:
            pass

    # Silhouette filter (uses indexed column only)
    if params.get('is_silhouette') == '1':
        where_clauses.append("is_silhouette = 1")

    # Toggle filters - support both new and legacy params
    # New: hide_bursts=1 shows only burst leads; Legacy: burst_only=1
    # Include burst leads AND standalone/unprocessed photos (is_burst_lead IS NULL)
    if params['hide_bursts'] == '1' or params['burst_only'] == '1':
        where_clauses.append("(is_burst_lead = 1 OR is_burst_lead IS NULL)")

    # New: hide_blinks=1 excludes blinks; Legacy: no_blink=1
    if params['hide_blinks'] == '1' or params['no_blink'] == '1':
        where_clauses.append("(is_blink = 0 OR is_blink IS NULL)")

    # Hide non-lead duplicates
    if params.get('hide_duplicates') == '1':
        where_clauses.append("(is_duplicate_lead = 1 OR is_duplicate_lead IS NULL OR duplicate_group_id IS NULL)")

    # Rating filters
    if params.get('min_rating'):
        try:
            min_rating = int(params['min_rating'])
            if 1 <= min_rating <= 5:
                where_clauses.append("star_rating >= ?")
                sql_params.append(min_rating)
        except ValueError:
            pass
    if params.get('favorites_only') == '1':
        where_clauses.append("is_favorite = 1")
    if params.get('show_rejected') == '1':
        where_clauses.append("is_rejected = 1")
    elif params.get('hide_rejected') == '1':
        where_clauses.append("(is_rejected = 0 OR is_rejected IS NULL)")

    # Face ratio filters (for "portraits" and "people in scene" types)
    # Note: Art exclusion is now handled separately via exclude_art parameter
    add_range_filter("face_ratio", "min_face_ratio", "max_face_ratio")

    # Score range filters
    add_range_filter("aggregate", "min_score", "max_score")
    add_range_filter("aesthetic", "min_aesthetic", "max_aesthetic")
    add_range_filter("tech_sharpness", "min_sharpness", "max_sharpness")
    add_range_filter("exposure_score", "min_exposure", "max_exposure")

    # Face filters
    add_range_filter("face_count", "min_face_count", "max_face_count", is_float=False)
    add_range_filter("face_quality", "min_face_quality", "max_face_quality")
    add_range_filter("eye_sharpness", "min_eye_sharpness", "max_eye_sharpness")

    # Technical setting filters
    add_range_filter("iso", "min_iso", "max_iso", is_float=False)
    add_range_filter("f_stop", "min_fstop", "max_fstop")
    add_range_filter("focal_length", "min_focal", "max_focal")

    # New metrics filters
    add_range_filter("dynamic_range_stops", "min_dynamic_range", "max_dynamic_range")
    add_range_filter("contrast_score", "min_contrast", "max_contrast")
    add_range_filter("noise_sigma", "min_noise", "max_noise")

    # Additional score filters
    add_range_filter("color_score", "min_color", "max_color")
    add_range_filter("comp_score", "min_composition", "max_composition")
    add_range_filter("face_sharpness", "min_face_sharpness", "max_face_sharpness")
    add_range_filter("isolation_bonus", "min_isolation", "max_isolation")
    # Note: max_luminance is handled separately above (line ~1412) for low_light type filter
    if params.get('min_luminance'):
        try:
            where_clauses.append("mean_luminance >= ?")
            sql_params.append(float(params['min_luminance']))
        except ValueError:
            pass
    add_range_filter("histogram_spread", "min_histogram_spread", "max_histogram_spread")
    add_range_filter("power_point_score", "min_power_point", "max_power_point")

    # Date range filters
    if params['date_from']:
        # Convert YYYY-MM-DD to YYYY:MM:DD format used in EXIF
        try:
            date_from = params['date_from'].replace('-', ':')
            where_clauses.append("date_taken >= ?")
            sql_params.append(date_from)
        except (ValueError, AttributeError):
            pass  # Invalid date format, skip filter

    if params['date_to']:
        try:
            date_to = params['date_to'].replace('-', ':') + " 23:59:59"
            where_clauses.append("date_taken <= ?")
            sql_params.append(date_to)
        except (ValueError, AttributeError):
            pass  # Invalid date format, skip filter

    # Build WHERE string
    where_str = ""
    if where_clauses:
        where_str = " WHERE " + " AND ".join(where_clauses)

    try:
        # 4. Calculate Pagination (use cached count to avoid repeated full-table scans)
        total_count = get_cached_count(conn, where_str, sql_params)
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

        # Base columns that always exist
        base_cols = [
            'path', 'filename', 'date_taken', 'camera_model', 'lens_model', 'iso',
            'f_stop', 'shutter_speed', 'focal_length', 'aesthetic', 'face_count', 'face_quality',
            'eye_sharpness', 'face_sharpness', 'face_ratio', 'tech_sharpness', 'color_score',
            'exposure_score', 'comp_score', 'isolation_bonus', 'is_blink', 'phash', 'is_burst_lead',
            'aggregate', 'category'
        ]
        # Optional columns that may not exist in older databases
        optional_cols = [
            'histogram_spread', 'mean_luminance', 'power_point_score',
            'shadow_clipped', 'highlight_clipped', 'is_silhouette', 'is_group_portrait', 'leading_lines_score',
            'face_confidence', 'is_monochrome', 'mean_saturation',
            'dynamic_range_stops', 'noise_sigma', 'contrast_score', 'tags',
            'composition_pattern', 'quality_score',
            'star_rating', 'is_favorite', 'is_rejected',
            'duplicate_group_id', 'is_duplicate_lead'
        ]

        existing_cols = get_existing_columns(conn)
        select_cols = base_cols + [c for c in optional_cols if c in existing_cols]

        # Add computed top_picks_score column when needed for sorting or display
        needs_top_picks_score = (
            params.get('top_picks_filter') == '1' or
            'top_picks_score' in order_by_clause
        )
        if needs_top_picks_score:
            top_picks_expr = get_top_picks_score_sql()
            select_cols.append(f"({top_picks_expr}) as top_picks_score")

        query = f"SELECT {', '.join(select_cols)} FROM photos{where_str} ORDER BY {order_by_clause} LIMIT ? OFFSET ?"
        rows = conn.execute(query, sql_params + [per_page, offset]).fetchall()

        # Convert to dicts and pre-split tags for template efficiency
        tags_limit = VIEWER_CONFIG['display']['tags_per_photo']
        photos = []
        for row in rows:
            photo = dict(row)
            if photo.get('tags'):
                photo['tags_list'] = [t.strip() for t in photo['tags'].split(',')[:tags_limit]]
            else:
                photo['tags_list'] = []
            photos.append(photo)

        # Batch fetch person associations and unassigned face counts for all photos
        if photos:
            try:
                photo_paths = [p['path'] for p in photos]
                placeholders = ','.join(['?'] * len(photo_paths))
                person_query = f"""
                    SELECT DISTINCT f.photo_path, f.person_id, p.name
                    FROM faces f
                    JOIN persons p ON p.id = f.person_id
                    WHERE f.photo_path IN ({placeholders})
                      AND f.person_id IS NOT NULL
                """
                person_rows = conn.execute(person_query, photo_paths).fetchall()

                path_to_persons = {}
                for row in person_rows:
                    path = row['photo_path']
                    if path not in path_to_persons:
                        path_to_persons[path] = []
                    path_to_persons[path].append({
                        'id': row['person_id'],
                        'name': row['name'] or f"Person {row['person_id']}"
                    })

                # Count unassigned faces per photo
                unassigned_query = f"""
                    SELECT photo_path, COUNT(*) as unassigned_count
                    FROM faces
                    WHERE photo_path IN ({placeholders})
                      AND person_id IS NULL
                    GROUP BY photo_path
                """
                unassigned_rows = conn.execute(unassigned_query, photo_paths).fetchall()
                path_to_unassigned = {row['photo_path']: row['unassigned_count'] for row in unassigned_rows}

                for photo in photos:
                    photo['persons'] = path_to_persons.get(photo['path'], [])
                    photo['unassigned_faces'] = path_to_unassigned.get(photo['path'], 0)
            except Exception:
                for photo in photos:
                    photo['persons'] = []
                    photo['unassigned_faces'] = 0
        else:
            for photo in photos:
                photo['persons'] = []
                photo['unassigned_faces'] = 0

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
                label = person_names.get(v, f'Person {v}')
                active_filters[k] = label
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

    return render_template_string(
        HTML_TEMPLATE,
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
    )


@app.route('/api/type_counts')
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


# =============================================================================
# Lazy Filter Options API Endpoints (Performance Optimization)
# =============================================================================


def _cached_filter_query(cache_key, result_key, query_fn):
    """Generic cache-then-query helper for filter option endpoints.

    Args:
        cache_key: Stats cache key (e.g., 'cameras', 'lenses')
        result_key: JSON response key (e.g., 'cameras', 'lenses')
        query_fn: Function that takes a db connection and returns results list
    """
    from db import get_cached_stat
    data, is_fresh = get_cached_stat(DEFAULT_DB_PATH, cache_key, max_age_seconds=300)
    if data and is_fresh:
        return jsonify({result_key: data, 'cached': True})

    with get_db_connection() as conn:
        data = query_fn(conn)
    return jsonify({result_key: data, 'cached': False})


@app.route('/api/filter_options/cameras')
def api_filter_options_cameras():
    """Lazy-load camera options with counts."""
    def query(conn):
        rows = conn.execute("""
            SELECT camera_model, COUNT(*) as cnt FROM photos
            WHERE camera_model IS NOT NULL
            GROUP BY camera_model ORDER BY cnt DESC LIMIT ?
        """, (VIEWER_CONFIG['dropdowns']['max_cameras'],)).fetchall()
        return [(r[0], r[1]) for r in rows]
    return _cached_filter_query('cameras', 'cameras', query)


@app.route('/api/filter_options/lenses')
def api_filter_options_lenses():
    """Lazy-load lens options with counts."""
    def query(conn):
        rows = conn.execute("""
            SELECT lens_model, COUNT(*) as cnt FROM photos
            WHERE lens_model IS NOT NULL
            GROUP BY lens_model ORDER BY cnt DESC LIMIT ?
        """, (VIEWER_CONFIG['dropdowns']['max_lenses'],)).fetchall()
        return [(r[0], r[1]) for r in rows]
    return _cached_filter_query('lenses', 'lenses', query)


@app.route('/api/filter_options/tags')
def api_filter_options_tags():
    """API endpoint for lazy-loading tag options.

    Returns tags with counts, sorted by frequency.
    Uses stats_cache if available and fresh, with fast photo_tags query as fallback.
    """
    from db import get_cached_stat

    max_tags = VIEWER_CONFIG['dropdowns']['max_tags']

    # Try cached data first
    tags, is_fresh = get_cached_stat(DEFAULT_DB_PATH, 'tags', max_age_seconds=300)
    if tags and is_fresh:
        # Return cached data (already sorted by count desc)
        return jsonify({'tags': tags[:max_tags], 'cached': True})

    with get_db_connection() as conn:
        # Try fast photo_tags table first
        if is_photo_tags_available(conn):
            try:
                rows = conn.execute("""
                    SELECT tag, COUNT(*) as cnt
                    FROM photo_tags
                    GROUP BY tag
                    ORDER BY cnt DESC, tag ASC
                    LIMIT ?
                """, (max_tags,)).fetchall()
                tags = [(r[0], r[1]) for r in rows]
                return jsonify({'tags': tags, 'cached': False})
            except Exception:
                pass

        # Fall back to recursive CTE (slow but works without photo_tags)
        tag_query = """
            WITH RECURSIVE split_tags(tag, rest) AS (
                SELECT '', tags || ',' FROM photos WHERE tags IS NOT NULL AND tags != ''
                UNION ALL
                SELECT TRIM(SUBSTR(rest, 1, INSTR(rest, ',') - 1)),
                       SUBSTR(rest, INSTR(rest, ',') + 1)
                FROM split_tags WHERE rest != ''
            )
            SELECT tag, COUNT(*) as cnt
            FROM split_tags
            WHERE tag != ''
            GROUP BY tag
            ORDER BY cnt DESC, tag ASC
            LIMIT ?
        """
        try:
            rows = conn.execute(tag_query, (max_tags,)).fetchall()
            tags = [(r[0], r[1]) for r in rows]
        except Exception:
            tags = []

    return jsonify({'tags': tags, 'cached': False})


@app.route('/api/filter_options/persons')
def api_filter_options_persons():
    """Lazy-load person options with photo counts."""
    def query(conn):
        try:
            min_photos = VIEWER_CONFIG['dropdowns'].get('min_photos_for_person', 1)
            rows = conn.execute("""
                SELECT p.id, p.name, COUNT(DISTINCT f.photo_path) as photo_count
                FROM persons p
                JOIN faces f ON f.person_id = p.id
                GROUP BY p.id HAVING photo_count >= ?
                ORDER BY photo_count DESC LIMIT ?
            """, (min_photos, VIEWER_CONFIG['dropdowns']['max_persons'])).fetchall()
            return [(r[0], r[1], r[2]) for r in rows]
        except Exception:
            return []
    return _cached_filter_query('persons', 'persons', query)


@app.route('/api/filter_options/patterns')
def api_filter_options_patterns():
    """Lazy-load composition pattern options with counts."""
    def query(conn):
        try:
            rows = conn.execute("""
                SELECT composition_pattern, COUNT(*) as cnt FROM photos
                WHERE composition_pattern IS NOT NULL AND composition_pattern != ''
                GROUP BY composition_pattern ORDER BY cnt DESC
            """).fetchall()
            return [(r[0], r[1]) for r in rows]
        except Exception:
            return []
    return _cached_filter_query('composition_patterns', 'patterns', query)


@app.route('/api/filter_options/categories')
def api_filter_options_categories():
    """Lazy-load category options with counts."""
    def query(conn):
        try:
            rows = conn.execute("""
                SELECT category, COUNT(*) as cnt FROM photos
                WHERE category IS NOT NULL
                GROUP BY category ORDER BY cnt DESC
            """).fetchall()
            return [(r[0], r[1]) for r in rows]
        except Exception:
            return []
    return _cached_filter_query('categories', 'categories', query)


@app.route('/api/person/<int:person_id>/faces')
def api_person_faces(person_id):
    """Get all faces belonging to a person."""
    conn = get_db_connection()
    try:
        faces = conn.execute("""
            SELECT f.id, f.photo_path, f.face_index, f.bbox_x1, f.bbox_y1, f.bbox_x2, f.bbox_y2
            FROM faces f
            LEFT JOIN photos p ON f.photo_path = p.path
            WHERE f.person_id = ?
            ORDER BY p.aggregate DESC
            LIMIT 36
        """, (person_id,)).fetchall()
        return jsonify({
            'faces': [dict(f) for f in faces]
        })
    finally:
        conn.close()


@app.route('/api/person/<int:person_id>/avatar', methods=['POST'])
def api_set_person_avatar(person_id):
    """Set a face as the representative avatar for a person."""
    if not is_edition_authenticated():
        return jsonify({'error': 'Edition disabled'}), 403
    global _filter_options_cache
    data = request.get_json()
    face_id = data.get('face_id')

    if not face_id:
        return jsonify({'error': 'face_id required'}), 400

    conn = get_db_connection()
    try:
        # Verify face belongs to this person
        face = conn.execute("""
            SELECT id, face_thumbnail FROM faces WHERE id = ? AND person_id = ?
        """, (face_id, person_id)).fetchone()

        if not face:
            return jsonify({'error': 'Face not found or does not belong to this person'}), 404

        # Update person's representative face and copy thumbnail
        conn.execute("""
            UPDATE persons SET representative_face_id = ?, face_thumbnail = ?
            WHERE id = ?
        """, (face_id, face['face_thumbnail'], person_id))

        conn.commit()
        _filter_options_cache['data'] = None  # Invalidate cache
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/photo/faces')
def api_photo_faces():
    """Get all faces in a photo with their current person assignment."""
    photo_path = request.args.get('path')
    if not photo_path:
        return jsonify({'error': 'path required'}), 400

    conn = get_db_connection()
    try:
        faces = conn.execute("""
            SELECT f.id, f.face_index, f.bbox_x1, f.bbox_y1, f.bbox_x2, f.bbox_y2,
                   f.person_id, p.name as person_name
            FROM faces f
            LEFT JOIN persons p ON f.person_id = p.id
            WHERE f.photo_path = ?
            ORDER BY f.face_index
        """, (photo_path,)).fetchall()
        return jsonify({
            'faces': [dict(f) for f in faces]
        })
    finally:
        conn.close()


@app.route('/api/face/<int:face_id>/assign', methods=['POST'])
def api_assign_face(face_id):
    """Assign a face to a person."""
    if not is_edition_authenticated():
        return jsonify({'error': 'Edition disabled'}), 403
    global _filter_options_cache
    data = request.get_json()
    person_id = data.get('person_id')

    if person_id is None:
        return jsonify({'error': 'person_id required'}), 400

    conn = get_db_connection()
    try:
        # Get current person_id for the face
        face = conn.execute("SELECT person_id FROM faces WHERE id = ?", (face_id,)).fetchone()
        if not face:
            return jsonify({'error': 'Face not found'}), 404

        old_person_id = face['person_id']

        # Update face assignment
        conn.execute("UPDATE faces SET person_id = ? WHERE id = ?", (person_id, face_id))

        # Update face counts
        if old_person_id:
            conn.execute("""
                UPDATE persons SET face_count = (
                    SELECT COUNT(*) FROM faces WHERE person_id = ?
                ) WHERE id = ?
            """, (old_person_id, old_person_id))

        conn.execute("""
            UPDATE persons SET face_count = (
                SELECT COUNT(*) FROM faces WHERE person_id = ?
            ) WHERE id = ?
        """, (person_id, person_id))

        conn.commit()
        _filter_options_cache['data'] = None  # Invalidate cache
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/photo/assign_all_faces', methods=['POST'])
def api_assign_all_faces():
    """Assign all unassigned faces in a photo to a person."""
    if not is_edition_authenticated():
        return jsonify({'error': 'Edition disabled'}), 403
    global _filter_options_cache
    data = request.get_json()
    photo_path = data.get('photo_path')
    person_id = data.get('person_id')

    if not photo_path or person_id is None:
        return jsonify({'error': 'photo_path and person_id required'}), 400

    conn = get_db_connection()
    try:
        # Get all unassigned faces in this photo
        faces = conn.execute("""
            SELECT id FROM faces WHERE photo_path = ? AND person_id IS NULL
        """, (photo_path,)).fetchall()

        if not faces:
            return jsonify({'error': 'No unassigned faces found'}), 404

        face_ids = [f['id'] for f in faces]

        # Assign all faces to the person
        placeholders = ','.join('?' * len(face_ids))
        conn.execute(f"""
            UPDATE faces SET person_id = ? WHERE id IN ({placeholders})
        """, [person_id] + face_ids)

        # Update person face count
        conn.execute("""
            UPDATE persons SET face_count = (
                SELECT COUNT(*) FROM faces WHERE person_id = ?
            ) WHERE id = ?
        """, (person_id, person_id))

        conn.commit()
        _filter_options_cache['data'] = None  # Invalidate cache
        return jsonify({'success': True, 'assigned_count': len(face_ids)})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/photo/unassign_person', methods=['POST'])
def api_unassign_person():
    """Unassign all faces of a specific person from a photo."""
    if not is_edition_authenticated():
        return jsonify({'error': 'Edition disabled'}), 403

    global _filter_options_cache
    data = request.get_json()
    photo_path = data.get('photo_path')
    person_id = data.get('person_id')

    if not photo_path or not person_id:
        return jsonify({'error': 'Missing photo_path or person_id'}), 400

    conn = get_db_connection()
    try:
        # Get faces to unassign
        faces = conn.execute("""
            SELECT id FROM faces
            WHERE photo_path = ? AND person_id = ?
        """, (photo_path, person_id)).fetchall()

        if not faces:
            return jsonify({'error': 'No faces found'}), 404

        # Unassign faces
        conn.execute("""
            UPDATE faces SET person_id = NULL
            WHERE photo_path = ? AND person_id = ?
        """, (photo_path, person_id))

        # Update person's face count
        conn.execute("""
            UPDATE persons SET face_count = (
                SELECT COUNT(*) FROM faces WHERE person_id = ?
            ) WHERE id = ?
        """, (person_id, person_id))

        # Check if person now has zero faces and should be deleted
        new_count = conn.execute(
            "SELECT face_count FROM persons WHERE id = ?",
            (person_id,)
        ).fetchone()

        person_deleted = False
        if new_count and new_count[0] == 0:
            conn.execute("DELETE FROM persons WHERE id = ?", (person_id,))
            person_deleted = True

        conn.commit()
        _filter_options_cache['data'] = None  # Invalidate cache

        return jsonify({
            'success': True,
            'unassigned_count': len(faces),
            'person_deleted': person_deleted
        })
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/photo/set_rating', methods=['POST'])
def api_set_rating():
    """Set star rating (0-5) for a photo."""
    if not is_edition_authenticated():
        return jsonify({'error': 'Edition disabled'}), 403

    data = request.get_json()
    photo_path = data.get('photo_path')
    rating = data.get('rating')

    if not photo_path:
        return jsonify({'error': 'photo_path required'}), 400
    if rating is None or not isinstance(rating, int) or rating < 0 or rating > 5:
        return jsonify({'error': 'rating must be integer 0-5'}), 400

    conn = get_db_connection()
    try:
        conn.execute("UPDATE photos SET star_rating = ? WHERE path = ?", (rating, photo_path))
        conn.commit()
        return jsonify({'success': True, 'rating': rating})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/photo/toggle_favorite', methods=['POST'])
def api_toggle_favorite():
    """Toggle favorite flag for a photo."""
    if not is_edition_authenticated():
        return jsonify({'error': 'Edition disabled'}), 403

    data = request.get_json()
    photo_path = data.get('photo_path')

    if not photo_path:
        return jsonify({'error': 'photo_path required'}), 400

    conn = get_db_connection()
    try:
        # Get current state and toggle
        row = conn.execute("SELECT is_favorite FROM photos WHERE path = ?", (photo_path,)).fetchone()
        if not row:
            return jsonify({'error': 'Photo not found'}), 404

        new_value = 0 if row['is_favorite'] else 1
        if new_value == 1:
            # When marking as favorite, also unmark rejected (mutually exclusive)
            conn.execute("UPDATE photos SET is_favorite = 1, is_rejected = 0 WHERE path = ?", (photo_path,))
        else:
            conn.execute("UPDATE photos SET is_favorite = 0 WHERE path = ?", (photo_path,))
        conn.commit()
        return jsonify({'success': True, 'is_favorite': new_value == 1, 'is_rejected': False if new_value == 1 else None})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/photo/toggle_rejected', methods=['POST'])
def api_toggle_rejected():
    """Toggle rejected flag for a photo."""
    if not is_edition_authenticated():
        return jsonify({'error': 'Edition disabled'}), 403

    data = request.get_json()
    photo_path = data.get('photo_path')

    if not photo_path:
        return jsonify({'error': 'photo_path required'}), 400

    conn = get_db_connection()
    try:
        # Get current state and toggle
        row = conn.execute("SELECT is_rejected FROM photos WHERE path = ?", (photo_path,)).fetchone()
        if not row:
            return jsonify({'error': 'Photo not found'}), 404

        new_value = 0 if row['is_rejected'] else 1
        if new_value == 1:
            # When rejecting, also set star_rating to 0 and unmark favorite (mutually exclusive)
            conn.execute("UPDATE photos SET is_rejected = 1, star_rating = 0, is_favorite = 0 WHERE path = ?", (photo_path,))
        else:
            conn.execute("UPDATE photos SET is_rejected = 0 WHERE path = ?", (photo_path,))
        conn.commit()
        return jsonify({'success': True, 'is_rejected': new_value == 1, 'star_rating': 0 if new_value == 1 else None, 'is_favorite': False if new_value == 1 else None})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/photos')
def api_photos():
    """API endpoint for infinite scroll - returns JSON with photo data."""
    # Reuse the same query logic as index()
    default_per_page = VIEWER_CONFIG['pagination']['default_per_page']
    per_page = request.args.get('per_page', default_per_page, type=int)
    page = request.args.get('page', 1, type=int)

    # Get configurable defaults
    defaults_cfg = VIEWER_CONFIG['defaults']
    default_type = defaults_cfg.get('type', '')

    # Build params dict with all filter values
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
        'tag': request.args.get('tag', ''),
        'person': request.args.get('person', ''),
        'search': request.args.get('search', ''),
        'min_score': normalized.get('min_score') or request.args.get('min_score', ''),
        'max_score': request.args.get('max_score', ''),
        'min_aesthetic': request.args.get('min_aesthetic', ''),
        'max_aesthetic': request.args.get('max_aesthetic', ''),
        'min_sharpness': request.args.get('min_sharpness', ''),
        'max_sharpness': request.args.get('max_sharpness', ''),
        'min_exposure': request.args.get('min_exposure', ''),
        'max_exposure': request.args.get('max_exposure', ''),
        'min_face_count': normalized.get('min_face_count') or request.args.get('min_face_count', ''),
        'max_face_count': normalized.get('max_face_count') or request.args.get('max_face_count', ''),
        'min_face_ratio': normalized.get('min_face_ratio') or request.args.get('min_face_ratio', ''),
        'max_face_ratio': normalized.get('max_face_ratio') or request.args.get('max_face_ratio', ''),
        'is_monochrome': normalized.get('is_monochrome') or request.args.get('is_monochrome', ''),
        'is_silhouette': normalized.get('is_silhouette') or request.args.get('is_silhouette', ''),
        'category': normalized.get('category') or request.args.get('category', ''),
        'require_tags': normalized.get('require_tags') or request.args.get('require_tags', ''),
        'exclude_tags': normalized.get('exclude_tags') or request.args.get('exclude_tags', ''),
        'exclude_art': normalized.get('exclude_art') or request.args.get('exclude_art', ''),
        'top_picks_filter': normalized.get('top_picks_filter') or request.args.get('top_picks_filter', ''),
        # Rating filters
        'min_rating': request.args.get('min_rating', ''),
        'favorites_only': request.args.get('favorites_only', ''),
        'hide_rejected': request.args.get('hide_rejected', ''),
        'show_rejected': request.args.get('show_rejected', ''),
    }

    # Apply type filters (same as index())
    if params.get('type') in TYPE_FILTERS:
        for key, value in TYPE_FILTERS[params['type']].items():
            if not params.get(key):
                params[key] = value

    # Build WHERE clauses
    where_clauses = []
    sql_params = []

    if params['camera']:
        where_clauses.append("camera_model = ?")
        sql_params.append(params['camera'])
    if params['lens']:
        where_clauses.append("lens_model = ?")
        sql_params.append(params['lens'])
    # Tag and person/search filters
    _add_tag_filter(
        where_clauses, sql_params,
        tag=params.get('tag'),
        require_tags=params.get('require_tags'),
        exclude_tags=params.get('exclude_tags'),
        exclude_art_tags=get_art_tags_from_config() if params.get('exclude_art') == '1' else None
    )
    if params['person']:
        try:
            person_id = int(params['person'])
            where_clauses.append("EXISTS (SELECT 1 FROM faces WHERE photo_path = photos.path AND person_id = ?)")
            sql_params.append(person_id)
        except ValueError:
            pass
    if params['search']:
        where_clauses.append("filename LIKE ?")
        sql_params.append(f"%{params['search']}%")

    # Score filters
    for param, col, op in [
        ('min_score', 'aggregate', '>='), ('max_score', 'aggregate', '<='),
        ('min_aesthetic', 'aesthetic', '>='), ('max_aesthetic', 'aesthetic', '<='),
        ('min_sharpness', 'tech_sharpness', '>='), ('max_sharpness', 'tech_sharpness', '<='),
        ('min_exposure', 'exposure_score', '>='), ('max_exposure', 'exposure_score', '<='),
        ('min_face_count', 'face_count', '>='), ('max_face_count', 'face_count', '<='),
        ('min_face_ratio', 'face_ratio', '>='), ('max_face_ratio', 'face_ratio', '<='),
    ]:
        if params.get(param):
            where_clauses.append(f"{col} {op} ?")
            sql_params.append(float(params[param]))

    # Boolean filters
    if params.get('is_monochrome') == '1':
        where_clauses.append("is_monochrome = 1")
    if params.get('is_silhouette') == '1':
        where_clauses.append("is_silhouette = 1")
    if params.get('category'):
        where_clauses.append("category = ?")
        sql_params.append(params['category'])

    # Top picks filter (custom weighted score)
    if params.get('top_picks_filter') == '1':
        threshold = get_top_picks_threshold()
        top_picks_expr = get_top_picks_score_sql()
        where_clauses.append(f"({top_picks_expr}) >= ?")
        sql_params.append(threshold)

    # Rating filters
    if params.get('min_rating'):
        try:
            min_rating = int(params['min_rating'])
            if 1 <= min_rating <= 5:
                where_clauses.append("star_rating >= ?")
                sql_params.append(min_rating)
        except ValueError:
            pass
    if params.get('favorites_only') == '1':
        where_clauses.append("is_favorite = 1")
    if params.get('show_rejected') == '1':
        where_clauses.append("is_rejected = 1")
    elif params.get('hide_rejected') == '1':
        where_clauses.append("(is_rejected = 0 OR is_rejected IS NULL)")

    # Blink/burst filters
    if params['hide_blinks'] == '1':
        where_clauses.append("(is_blink = 0 OR is_blink IS NULL)")
    if params['hide_bursts'] == '1':
        where_clauses.append("(is_burst_lead = 1 OR is_burst_lead IS NULL)")
    if params.get('hide_duplicates') == '1':
        where_clauses.append("(is_duplicate_lead = 1 OR is_duplicate_lead IS NULL OR duplicate_group_id IS NULL)")
    if params['burst_only'] == '1':
        where_clauses.append("is_burst_lead = 1")
    if params['no_blink'] == '1':
        where_clauses.append("is_blink = 0")

    where_str = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    # Build ORDER BY
    sort_col = params['sort'] if params['sort'] in VALID_SORT_COLS else 'aggregate'
    sort_dir = 'ASC' if params['dir'] == 'ASC' else 'DESC'
    # Add path as tie-breaker for deterministic pagination (prevents duplicates in infinite scroll)
    order_by_clause = f"{sort_col} {sort_dir}, path ASC"

    conn = get_db_connection()
    try:
        # Get total count (use cached count to avoid repeated full-table scans)
        total_count = get_cached_count(conn, where_str, sql_params)
        total_pages = max(1, math.ceil(total_count / per_page))
        offset = (page - 1) * per_page

        # Query photos - include all fields needed for tooltip display
        base_cols = ['path', 'filename', 'date_taken', 'camera_model', 'lens_model',
                     'iso', 'f_stop', 'shutter_speed', 'focal_length', 'aesthetic',
                     'face_count', 'face_quality', 'eye_sharpness', 'face_sharpness', 'face_ratio',
                     'tech_sharpness', 'color_score', 'exposure_score', 'comp_score',
                     'is_blink', 'aggregate', 'is_burst_lead', 'tags', 'category']
        optional_cols = ['is_monochrome', 'isolation_bonus', 'contrast_score', 'dynamic_range_stops',
                         'composition_pattern', 'power_point_score', 'leading_lines_score',
                         'mean_saturation', 'noise_sigma', 'quality_score',
                         'star_rating', 'is_favorite', 'is_rejected',
                         'duplicate_group_id', 'is_duplicate_lead']

        existing_cols = get_existing_columns(conn)
        select_cols = base_cols + [c for c in optional_cols if c in existing_cols]

        # Add computed top_picks_score column when needed for sorting or display
        needs_top_picks_score = (
            params.get('top_picks_filter') == '1' or
            'top_picks_score' in order_by_clause
        )
        if needs_top_picks_score:
            top_picks_expr = get_top_picks_score_sql()
            select_cols.append(f"({top_picks_expr}) as top_picks_score")

        query = f"SELECT {', '.join(select_cols)} FROM photos{where_str} ORDER BY {order_by_clause} LIMIT ? OFFSET ?"
        rows = conn.execute(query, sql_params + [per_page, offset]).fetchall()

        # Convert to list of dicts for JSON
        tags_limit = VIEWER_CONFIG['display']['tags_per_photo']
        photos = []
        for row in rows:
            photo = dict(row)
            # Pre-split tags
            if photo.get('tags'):
                photo['tags_list'] = [t.strip() for t in photo['tags'].split(',')[:tags_limit]]
            else:
                photo['tags_list'] = []
            # Format values for display
            photo['date_formatted'] = format_date(photo.get('date_taken'))
            photos.append(photo)

        # Batch fetch person associations and unassigned face counts for all photos
        if photos:
            try:
                photo_paths = [p['path'] for p in photos]
                placeholders = ','.join(['?'] * len(photo_paths))
                person_query = f"""
                    SELECT DISTINCT f.photo_path, f.person_id, p.name
                    FROM faces f
                    JOIN persons p ON p.id = f.person_id
                    WHERE f.photo_path IN ({placeholders})
                      AND f.person_id IS NOT NULL
                """
                person_rows = conn.execute(person_query, photo_paths).fetchall()

                path_to_persons = {}
                for prow in person_rows:
                    path = prow['photo_path']
                    if path not in path_to_persons:
                        path_to_persons[path] = []
                    path_to_persons[path].append({
                        'id': prow['person_id'],
                        'name': prow['name'] or f"Person {prow['person_id']}"
                    })

                # Count unassigned faces per photo
                unassigned_query = f"""
                    SELECT photo_path, COUNT(*) as unassigned_count
                    FROM faces
                    WHERE photo_path IN ({placeholders})
                      AND person_id IS NULL
                    GROUP BY photo_path
                """
                unassigned_rows = conn.execute(unassigned_query, photo_paths).fetchall()
                path_to_unassigned = {row['photo_path']: row['unassigned_count'] for row in unassigned_rows}

                for photo in photos:
                    photo['persons'] = path_to_persons.get(photo['path'], [])
                    photo['unassigned_faces'] = path_to_unassigned.get(photo['path'], 0)
            except Exception:
                for photo in photos:
                    photo['persons'] = []
                    photo['unassigned_faces'] = 0
        else:
            for photo in photos:
                photo['persons'] = []
                photo['unassigned_faces'] = 0

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


@app.route('/api/similar_photos/<path:photo_path>')
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


@app.route('/image')
def image():
    return send_file(request.args.get('path'))


@app.route('/manage_persons')
def manage_persons_page():
    """Display a page to manage persons (merge or delete)."""
    if not is_edition_authenticated():
        return redirect('/')
    sort_by = request.args.get('sort', 'count_desc')

    conn = get_db_connection()
    try:
        if sort_by == 'count_asc':
            order_clause = "ORDER BY p.face_count ASC, p.id"
        elif sort_by == 'quality_asc':
            order_clause = "ORDER BY rep_quality ASC, p.id"
        elif sort_by == 'quality_desc':
            order_clause = "ORDER BY rep_quality DESC, p.id"
        else:  # count_desc (default)
            order_clause = "ORDER BY p.face_count DESC, p.id"

        # Normalize eye_sharpness (0-10) and face_quality (6.5-9.5) to 0-1 scale
        # Weight eye_sharpness 70% since it's the primary blur indicator
        persons = conn.execute(f"""
            SELECT p.id, p.name, p.representative_face_id, p.face_count,
                   (COALESCE(photos.eye_sharpness, 0) / 10.0 * 0.7 +
                    (COALESCE(photos.face_quality, 6.5) - 6.5) / 3.0 * 0.3) as rep_quality
            FROM persons p
            LEFT JOIN faces f ON p.representative_face_id = f.id
            LEFT JOIN photos ON f.photo_path = photos.path
            {order_clause}
        """).fetchall()
        persons = [dict(row) for row in persons]
    finally:
        conn.close()

    return render_template_string(r'''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ _('manage_persons.title') }} - Facet</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        .person-card { transition: all 0.2s; }
        .person-card.selected { border-color: #3b82f6; box-shadow: 0 0 0 2px #3b82f6; }
        .person-card:hover:not(.selected) { border-color: #525252; }
        .person-card .delete-btn, .person-card .avatar-btn { opacity: 0; }
        .person-card:hover .delete-btn, .person-card:hover .avatar-btn { opacity: 1; }
    </style>
</head>
<body class="bg-neutral-950 text-white min-h-screen">
    <header class="bg-neutral-900 border-b border-neutral-800 px-6 py-3 sticky top-0 z-40">
        <div class="flex items-center justify-between">
            <div class="flex items-center gap-4">
                <a href="/" class="text-neutral-400 hover:text-white">
                    <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 19l-7-7m0 0l7-7m-7 7h18"/>
                    </svg>
                </a>
                <h1 class="text-xl font-semibold">{{ _('manage_persons.title') }}</h1>
                <select onchange="window.location='?sort=' + this.value" class="bg-neutral-800 text-white text-sm px-2 py-1.5 rounded border border-neutral-700 focus:border-green-500 focus:outline-none">
                    <option value="count_desc" {% if sort_by == 'count_desc' %}selected{% endif %}>{{ _('manage_persons.sort.count_desc') }}</option>
                    <option value="count_asc" {% if sort_by == 'count_asc' %}selected{% endif %}>{{ _('manage_persons.sort.count_asc') }}</option>
                    <option value="quality_asc" {% if sort_by == 'quality_asc' %}selected{% endif %}>{{ _('manage_persons.sort.quality_asc') }}</option>
                    <option value="quality_desc" {% if sort_by == 'quality_desc' %}selected{% endif %}>{{ _('manage_persons.sort.quality_desc') }}</option>
                </select>
                {% if edition_authenticated and viewer_config.features.show_merge_suggestions %}
                <a href="/suggest_merges" class="text-sm text-neutral-400 hover:text-white px-3 py-1.5 bg-neutral-800 rounded border border-neutral-700 hover:border-neutral-600 transition-colors">
                    {{ _('manage_persons.suggest_merges') }}
                </a>
                {% endif %}
            </div>
            {% if edition_authenticated %}
            <div class="flex items-center gap-3">
                <div id="selection-status" class="text-sm text-neutral-500"></div>
                <button id="clear-btn" onclick="clearSelection()" class="hidden px-3 py-1.5 bg-neutral-700 hover:bg-neutral-600 text-white text-sm rounded transition-colors">
                    {{ _('ui.buttons.clear') }}
                </button>
                <button id="delete-btn" onclick="deleteSelected()" class="hidden px-3 py-1.5 bg-red-600 hover:bg-red-500 text-white text-sm rounded font-medium transition-colors">
                    {{ _('ui.buttons.delete') }}
                </button>
                <button id="merge-btn" onclick="startMerge()" class="hidden px-3 py-1.5 bg-blue-600 hover:bg-blue-500 text-white text-sm rounded font-medium transition-colors">
                    {{ _('ui.buttons.merge') }}
                </button>
            </div>
            {% endif %}
        </div>
    </header>

    <main class="p-6">
        <!-- Persons Grid -->
        <div class="grid grid-cols-4 sm:grid-cols-6 md:grid-cols-8 lg:grid-cols-10 xl:grid-cols-12 gap-3">
            {% for person in persons %}
            <div class="person-card group relative bg-neutral-900 border border-neutral-800 rounded-lg p-2 {% if edition_authenticated %}cursor-pointer{% endif %} text-center"
                 data-id="{{ person.id }}"
                 data-name="{{ person.name or 'Person ' ~ person.id }}"
                 data-count="{{ person.face_count }}"
                 {% if edition_authenticated %}onclick="toggleSelection(this)"{% endif %}>
                {% if edition_authenticated %}
                <button onclick="event.stopPropagation(); deletePerson({{ person.id }}, '{{ (person.name or 'Person ' ~ person.id)|e }}', {{ person.face_count }})"
                        class="delete-btn absolute -top-1 -right-1 w-5 h-5 bg-red-600 hover:bg-red-500 rounded-full flex items-center justify-center text-white transition-opacity z-10"
                        title="Delete person">
                    <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                    </svg>
                </button>
                <button onclick="event.stopPropagation(); showFacesModal({{ person.id }}, '{{ (person.name or 'Person ' ~ person.id)|e }}')"
                        class="avatar-btn absolute -top-1 -left-1 w-5 h-5 bg-green-600 hover:bg-green-500 rounded-full flex items-center justify-center text-white transition-opacity z-10"
                        title="{{ _('manage_persons.change_avatar') }}">
                    <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"/>
                    </svg>
                </button>
                {% endif %}
                <img src="/person_thumbnail/{{ person.id }}"
                     class="w-full aspect-square rounded-full object-cover mb-2"
                     loading="lazy" alt="">
                <div class="text-xs text-neutral-300 truncate">{{ person.name or 'Person ' ~ person.id }}</div>
                <div class="text-xs text-neutral-500 mb-1">{{ person.face_count }} photos</div>
                <div class="flex gap-1 justify-center">
                    <a href="/?person={{ person.id }}"
                       onclick="event.stopPropagation()"
                       class="text-[10px] px-2 py-0.5 bg-neutral-700 hover:bg-green-600 text-neutral-300 hover:text-white rounded transition-colors">
                        {{ _('ui.buttons.view') }}
                    </a>
                    {% if edition_authenticated %}
                    <button onclick="event.stopPropagation(); renamePerson({{ person.id }}, '{{ (person.name or 'Person ' ~ person.id)|e }}')"
                            class="text-[10px] px-2 py-0.5 bg-neutral-700 hover:bg-yellow-600 text-neutral-300 hover:text-white rounded transition-colors"
                            title="{{ _('ui.buttons.rename') }}">
                        <svg class="w-3 h-3 inline" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"/>
                        </svg>
                    </button>
                    {% endif %}
                    <button onclick="event.stopPropagation(); copyPersonUrl({{ person.id }})"
                            class="text-[10px] px-2 py-0.5 bg-neutral-700 hover:bg-blue-600 text-neutral-300 hover:text-white rounded transition-colors"
                            title="{{ _('ui.buttons.share') }}">
                        <svg class="w-3 h-3 inline" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.684 13.342C8.886 12.938 9 12.482 9 12c0-.482-.114-.938-.316-1.342m0 2.684a3 3 0 110-2.684m0 2.684l6.632 3.316m-6.632-6l6.632-3.316m0 0a3 3 0 105.367-2.684 3 3 0 00-5.367 2.684zm0 9.316a3 3 0 105.368 2.684 3 3 0 00-5.368-2.684z"/>
                        </svg>
                    </button>
                </div>
            </div>
            {% endfor %}
        </div>
    </main>

    <!-- Copy Notification -->
    <div id="copy-notification" class="fixed bottom-4 right-4 bg-green-600 text-white px-4 py-2 rounded-lg shadow-lg transform translate-y-20 opacity-0 transition-all duration-300 z-50">
        <span id="copy-notification-text">Copied!</span>
    </div>

    <!-- Target Selection Modal -->
    <div id="target-modal" class="hidden fixed inset-0 bg-black/80 flex items-center justify-center z-50">
        <div class="bg-neutral-900 rounded-lg p-6 max-w-lg w-full mx-4 border border-neutral-700">
            <h3 class="text-lg font-semibold mb-2">{{ _('manage_persons.select_target') }}</h3>
            <p class="text-neutral-400 text-sm mb-4">{{ _('manage_persons.merge_explanation') }}</p>
            <div id="target-options" class="grid grid-cols-4 gap-3 mb-4 max-h-64 overflow-y-auto">
                <!-- Dynamically populated with selected persons -->
            </div>
            <button onclick="closeModal()" class="w-full bg-neutral-700 hover:bg-neutral-600 py-2 rounded transition-colors">
                {{ _('ui.buttons.cancel') }}
            </button>
        </div>
    </div>

    <!-- Faces Modal for Avatar Selection -->
    <div id="faces-modal" class="hidden fixed inset-0 bg-black/80 flex items-center justify-center z-50">
        <div class="bg-neutral-900 rounded-lg p-6 max-w-2xl w-full mx-4 border border-neutral-700">
            <h3 class="text-lg font-semibold mb-2">{{ _('manage_persons.select_avatar') }}</h3>
            <p id="faces-modal-person-name" class="text-neutral-400 text-sm mb-4"></p>
            <div id="faces-grid" class="grid grid-cols-6 gap-2 mb-4 max-h-80 overflow-y-auto">
                <!-- Dynamically populated with faces -->
            </div>
            <button onclick="closeFacesModal()" class="w-full bg-neutral-700 hover:bg-neutral-600 py-2 rounded transition-colors">
                {{ _('ui.buttons.cancel') }}
            </button>
        </div>
    </div>

    <script>
        // i18n translations
        const I18N = {{ js_translations(['manage_persons', 'notifications', 'ui', 'similar', 'rating']) | tojson | safe }};
        function t(key, vars={}) {
            const keys = key.split('.');
            let value = I18N;
            for (const k of keys) {
                if (value && typeof value === 'object' && k in value) {
                    value = value[k];
                } else {
                    return key;
                }
            }
            if (typeof value === 'string' && Object.keys(vars).length > 0) {
                return value.replace(/\{(\w+)\}/g, (m, k) => vars[k] !== undefined ? vars[k] : m);
            }
            return value || key;
        }

        // Multi-select using a Set of selected IDs
        let selectedIds = new Set();

        function toggleSelection(el) {
            const id = parseInt(el.dataset.id);

            if (selectedIds.has(id)) {
                selectedIds.delete(id);
                el.classList.remove('selected');
            } else {
                selectedIds.add(id);
                el.classList.add('selected');
            }
            updateUI();
        }

        function updateUI() {
            const count = selectedIds.size;
            const mergeBtn = document.getElementById('merge-btn');
            const clearBtn = document.getElementById('clear-btn');
            const deleteBtn = document.getElementById('delete-btn');
            const statusEl = document.getElementById('selection-status');

            if (count === 0) {
                mergeBtn.classList.add('hidden');
                deleteBtn.classList.add('hidden');
                clearBtn.classList.add('hidden');
                statusEl.textContent = '';
            } else if (count === 1) {
                mergeBtn.classList.add('hidden');
                deleteBtn.classList.remove('hidden');
                clearBtn.classList.remove('hidden');
                statusEl.textContent = `1 ${t('ui.labels.selected')}`;
                statusEl.classList.remove('text-blue-400');
                statusEl.classList.add('text-neutral-400');
            } else {
                mergeBtn.classList.remove('hidden');
                deleteBtn.classList.remove('hidden');
                clearBtn.classList.remove('hidden');
                statusEl.textContent = `${count} ${t('ui.labels.selected')}`;
                statusEl.classList.remove('text-neutral-400');
                statusEl.classList.add('text-blue-400');
            }
        }

        function clearSelection() {
            document.querySelectorAll('.person-card').forEach(el => {
                el.classList.remove('selected');
            });
            selectedIds.clear();
            updateUI();
        }

        function showNotification(message) {
            const notification = document.getElementById('copy-notification');
            const text = document.getElementById('copy-notification-text');
            text.textContent = message;

            notification.classList.remove('translate-y-20', 'opacity-0');
            notification.classList.add('translate-y-0', 'opacity-100');

            setTimeout(() => {
                notification.classList.remove('translate-y-0', 'opacity-100');
                notification.classList.add('translate-y-20', 'opacity-0');
            }, 2000);
        }

        async function copyPersonUrl(personId) {
            try {
                const response = await fetch(`/api/person/${personId}/share-token`);
                if (!response.ok) {
                    throw new Error(`API error: ${response.status}`);
                }
                const data = await response.json();
                const url = `${window.location.origin}/person/${personId}?token=${data.token}`;

                // Try modern clipboard API first, fall back to execCommand
                if (navigator.clipboard && window.isSecureContext) {
                    await navigator.clipboard.writeText(url);
                } else {
                    // Fallback for non-secure contexts (HTTP)
                    const textArea = document.createElement('textarea');
                    textArea.value = url;
                    textArea.style.position = 'fixed';
                    textArea.style.left = '-9999px';
                    document.body.appendChild(textArea);
                    textArea.select();
                    document.execCommand('copy');
                    document.body.removeChild(textArea);
                }
                showNotification(t('notifications.link_copied') || 'Link copied to clipboard');
            } catch (err) {
                console.error('Failed to generate share URL:', err);
                showNotification(t('notifications.copy_failed') || 'Failed to copy link');
            }
        }

        function startMerge() {
            if (selectedIds.size < 2) return;

            // Populate the modal with selected persons
            const optionsContainer = document.getElementById('target-options');
            optionsContainer.innerHTML = '';

            selectedIds.forEach(id => {
                const card = document.querySelector(`[data-id="${id}"]`);
                const name = card.dataset.name;
                const count = card.dataset.count;

                const option = document.createElement('div');
                option.className = 'cursor-pointer bg-neutral-800 hover:bg-blue-600 rounded-lg p-2 text-center transition-colors';
                option.onclick = () => executeBatchMerge(id);
                option.innerHTML = `
                    <img src="/person_thumbnail/${id}" class="w-full aspect-square rounded-full object-cover mb-2">
                    <div class="text-xs text-neutral-300 truncate">${name}</div>
                    <div class="text-xs text-neutral-500">${count} photos</div>
                `;
                optionsContainer.appendChild(option);
            });

            document.getElementById('target-modal').classList.remove('hidden');
        }

        function closeModal() {
            document.getElementById('target-modal').classList.add('hidden');
        }

        async function executeBatchMerge(targetId) {
            const sourceIds = Array.from(selectedIds).filter(id => id !== targetId);

            if (sourceIds.length === 0) {
                alert('Cannot merge a person into itself');
                return;
            }

            try {
                const response = await fetch('/merge_persons_batch', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest'
                    },
                    body: JSON.stringify({ source_ids: sourceIds, target_id: targetId })
                });
                const data = await response.json();

                if (data.success) {
                    closeModal();
                    // Remove merged person cards from DOM
                    sourceIds.forEach(id => {
                        const card = document.querySelector(`[data-id="${id}"]`);
                        if (card) card.remove();
                    });
                    // Update target card's count
                    const targetCard = document.querySelector(`[data-id="${targetId}"]`);
                    if (targetCard && data.new_count !== undefined) {
                        targetCard.dataset.count = data.new_count;
                        targetCard.querySelector('.text-neutral-500').textContent = data.new_count + ' photos';
                    }
                    // Clear selection
                    clearSelection();
                } else {
                    alert(t('notifications.error_merging') + ': ' + (data.error || 'Unknown error'));
                }
            } catch (err) {
                alert(t('notifications.error_merging') + ': ' + err.message);
            }
        }

        async function deletePerson(personId, personName, photoCount) {
            try {
                const response = await fetch(`/delete_person/${personId}`, {
                    method: 'POST',
                    headers: {'X-Requested-With': 'XMLHttpRequest'}
                });
                const data = await response.json();

                if (data.success) {
                    const card = document.querySelector(`[data-id="${personId}"]`);
                    if (card) card.remove();
                    selectedIds.delete(personId);
                    updateUI();
                } else {
                    alert(t('notifications.error_deleting') + ': ' + (data.error || 'Unknown error'));
                }
            } catch (err) {
                alert(t('notifications.error_deleting') + ': ' + err.message);
            }
        }

        function renamePerson(personId, currentName) {
            const newName = prompt(t('manage_persons.enter_new_name'), currentName);
            if (newName !== null && newName.trim() !== currentName) {
                const formData = new FormData();
                formData.append('name', newName.trim());
                fetch('/rename_person/' + personId, {
                    method: 'POST',
                    body: formData,
                    headers: { 'X-Requested-With': 'XMLHttpRequest' }
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        // Update card name without reload
                        const card = document.querySelector(`[data-id="${personId}"]`);
                        if (card) {
                            card.dataset.name = data.name;
                            card.querySelector('.text-neutral-300').textContent = data.name;
                        }
                    } else {
                        alert(t('notifications.failed_rename'));
                    }
                })
                .catch(() => alert(t('notifications.failed_rename')));
            }
        }

        async function deleteSelected() {
            const idsToDelete = Array.from(selectedIds);
            if (idsToDelete.length === 0) return;

            try {
                const response = await fetch('/delete_persons_batch', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest'
                    },
                    body: JSON.stringify({ person_ids: idsToDelete })
                });
                const data = await response.json();

                if (data.success) {
                    idsToDelete.forEach(personId => {
                        const card = document.querySelector(`[data-id="${personId}"]`);
                        if (card) card.remove();
                    });
                    selectedIds.clear();
                    updateUI();
                } else {
                    alert(t('notifications.error_deleting') + ': ' + (data.error || 'Unknown error'));
                }
            } catch (err) {
                alert(t('notifications.error_deleting') + ': ' + err.message);
            }
        }

        // Close modal on escape key
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                closeModal();
                closeFacesModal();
            }
        });

        // Close modal on backdrop click
        document.getElementById('target-modal').addEventListener('click', (e) => {
            if (e.target.id === 'target-modal') closeModal();
        });

        document.getElementById('faces-modal').addEventListener('click', (e) => {
            if (e.target.id === 'faces-modal') closeFacesModal();
        });

        // Avatar selection
        let currentPersonIdForAvatar = null;

        async function showFacesModal(personId, personName) {
            currentPersonIdForAvatar = personId;
            document.getElementById('faces-modal-person-name').textContent = personName;

            const grid = document.getElementById('faces-grid');
            grid.innerHTML = '<div class="col-span-6 text-center text-neutral-500">Loading...</div>';

            document.getElementById('faces-modal').classList.remove('hidden');

            try {
                const response = await fetch(`/api/person/${personId}/faces`);
                const data = await response.json();

                grid.innerHTML = '';
                for (const face of data.faces) {
                    const el = document.createElement('div');
                    el.className = 'cursor-pointer rounded-lg overflow-hidden hover:ring-2 hover:ring-green-500 transition-all';
                    el.onclick = () => selectAvatar(face.id);
                    el.innerHTML = `<img src="/face_thumbnail/${face.id}" class="w-full aspect-square object-cover" loading="lazy">`;
                    grid.appendChild(el);
                }

                if (data.faces.length === 0) {
                    grid.innerHTML = '<div class="col-span-6 text-center text-neutral-500">No faces found</div>';
                }
            } catch (err) {
                grid.innerHTML = '<div class="col-span-6 text-center text-red-500">Error loading faces</div>';
            }
        }

        function closeFacesModal() {
            document.getElementById('faces-modal').classList.add('hidden');
            currentPersonIdForAvatar = null;
        }

        async function selectAvatar(faceId) {
            if (!currentPersonIdForAvatar) return;

            try {
                const response = await fetch(`/api/person/${currentPersonIdForAvatar}/avatar`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest'
                    },
                    body: JSON.stringify({ face_id: faceId })
                });
                const data = await response.json();

                if (data.success) {
                    window.location.reload();
                } else {
                    alert('Error setting avatar: ' + (data.error || 'Unknown error'));
                }
            } catch (err) {
                alert('Error setting avatar: ' + err.message);
            }
        }
    </script>
</body>
</html>
    ''', persons=persons, sort_by=sort_by, editing_enabled=is_edition_enabled(), edition_authenticated=is_edition_authenticated(), viewer_config=load_viewer_config())


@app.route('/merge_persons/<int:source_id>/<int:target_id>', methods=['POST'])
def merge_persons(source_id, target_id):
    """Merge source person into target person."""
    if not is_edition_authenticated():
        return jsonify({'error': 'Edition disabled'}), 403
    global _filter_options_cache

    if source_id == target_id:
        return jsonify({'error': 'Cannot merge a person into itself'}), 400

    conn = get_db_connection()
    try:
        # 1. Move all faces from source to target
        conn.execute("UPDATE faces SET person_id = ? WHERE person_id = ?",
                     (target_id, source_id))

        # 2. Update target face_count
        count = conn.execute("SELECT COUNT(*) FROM faces WHERE person_id = ?",
                            (target_id,)).fetchone()[0]
        conn.execute("UPDATE persons SET face_count = ? WHERE id = ?",
                     (count, target_id))

        # 3. Delete source person
        conn.execute("DELETE FROM persons WHERE id = ?", (source_id,))

        conn.commit()
        _filter_options_cache['data'] = None  # Invalidate cache so person list updates
        return jsonify({'success': True, 'new_count': count})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/merge_persons_batch', methods=['POST'])
def merge_persons_batch():
    """Merge multiple persons into a target person."""
    if not is_edition_authenticated():
        return jsonify({'error': 'Edition disabled'}), 403
    global _filter_options_cache

    data = request.get_json()
    source_ids = data.get('source_ids', [])
    target_id = data.get('target_id')

    if not source_ids or not target_id:
        return jsonify({'success': False, 'error': 'Missing source_ids or target_id'}), 400
    if target_id in source_ids:
        return jsonify({'success': False, 'error': 'Target cannot be in source list'}), 400

    conn = get_db_connection()
    try:
        # Move all faces from sources to target
        placeholders = ','.join('?' * len(source_ids))
        conn.execute(f'UPDATE faces SET person_id = ? WHERE person_id IN ({placeholders})',
                     [target_id] + source_ids)

        # Update target face_count
        new_count = conn.execute('SELECT COUNT(*) FROM faces WHERE person_id = ?',
                                 (target_id,)).fetchone()[0]
        conn.execute('UPDATE persons SET face_count = ? WHERE id = ?', (new_count, target_id))

        # Delete source persons
        conn.execute(f'DELETE FROM persons WHERE id IN ({placeholders})', source_ids)
        conn.commit()

        _filter_options_cache['data'] = None  # Invalidate cache so person list updates
        return jsonify({'success': True, 'target_id': target_id, 'merged_count': len(source_ids), 'new_count': new_count})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/delete_person/<int:person_id>', methods=['POST'])
def delete_person(person_id):
    """Delete a person and unassign all their faces."""
    if not is_edition_authenticated():
        return jsonify({'error': 'Edition disabled'}), 403
    global _filter_options_cache

    conn = get_db_connection()
    try:
        # 1. Unassign all faces from this person (set person_id to NULL)
        conn.execute("UPDATE faces SET person_id = NULL WHERE person_id = ?", (person_id,))

        # 2. Delete the person
        conn.execute("DELETE FROM persons WHERE id = ?", (person_id,))

        conn.commit()
        _filter_options_cache['data'] = None  # Invalidate cache so person list updates
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/delete_persons_batch', methods=['POST'])
def delete_persons_batch():
    """Delete multiple persons and unassign all their faces."""
    if not is_edition_authenticated():
        return jsonify({'error': 'Edition disabled'}), 403
    global _filter_options_cache

    data = request.get_json()
    person_ids = data.get('person_ids', [])

    if not person_ids:
        return jsonify({'success': False, 'error': 'No person_ids provided'}), 400

    conn = get_db_connection()
    try:
        placeholders = ','.join('?' * len(person_ids))
        # 1. Unassign all faces from these persons
        conn.execute(f"UPDATE faces SET person_id = NULL WHERE person_id IN ({placeholders})", person_ids)

        # 2. Delete the persons
        conn.execute(f"DELETE FROM persons WHERE id IN ({placeholders})", person_ids)

        conn.commit()
        _filter_options_cache['data'] = None
        return jsonify({'success': True, 'deleted_count': len(person_ids)})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conn.close()


# Register person page blueprint
app.register_blueprint(person_bp)


# ============================================
# MERGE SUGGESTIONS ROUTES
# ============================================

@app.route('/api/merge_groups')
def api_merge_groups():
    """Return merge groups as JSON for the suggest_merges page."""
    if not is_edition_authenticated():
        return jsonify({'error': 'Edition disabled'}), 403

    # Check if feature is enabled
    viewer_config = load_viewer_config()
    if not viewer_config.get('features', {}).get('show_merge_suggestions', True):
        return jsonify({'error': 'Merge suggestions feature is disabled'}), 403

    threshold = float(request.args.get('threshold', 0.6))
    # Lazy import only when feature is used
    from faces import get_merge_groups
    groups = get_merge_groups(DEFAULT_DB_PATH, threshold)
    return jsonify({'groups': groups, 'threshold': threshold})


@app.route('/suggest_merges')
def suggest_merges_page():
    """Display a page showing merge suggestions grouped by similarity."""
    if not is_edition_authenticated():
        return redirect('/')

    # Check if feature is enabled
    viewer_config = load_viewer_config()
    if not viewer_config.get('features', {}).get('show_merge_suggestions', True):
        return redirect('/')

    threshold = float(request.args.get('threshold', 0.6))

    return render_template_string(r'''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ _('merge_suggestions.title') }} - Facet</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        .group-card { transition: all 0.3s; }
        .group-card.merged { opacity: 0; transform: translateX(100%); height: 0; padding: 0; margin: 0; overflow: hidden; }
        .person-item:hover { border-color: #3b82f6; }
        .toast { animation: slideIn 0.3s ease-out; }
        @keyframes slideIn { from { transform: translateY(100%); opacity: 0; } to { transform: translateY(0); opacity: 1; } }
    </style>
</head>
<body class="bg-neutral-950 text-white min-h-screen">
    <header class="bg-neutral-900 border-b border-neutral-800 px-6 py-3 sticky top-0 z-40">
        <div class="flex items-center justify-between">
            <div class="flex items-center gap-4">
                <a href="/manage_persons" class="text-neutral-400 hover:text-white">
                    <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 19l-7-7m0 0l7-7m-7 7h18"/>
                    </svg>
                </a>
                <h1 class="text-xl font-semibold">{{ _('merge_suggestions.title') }}</h1>
            </div>
            <div class="flex items-center gap-3">
                <span class="text-sm text-neutral-400">{{ _('merge_suggestions.threshold') }}:</span>
                <select id="threshold-select" onchange="changeThreshold(this.value)" class="bg-neutral-800 text-white text-sm px-2 py-1.5 rounded border border-neutral-700 focus:border-blue-500 focus:outline-none">
                    {% for pct in range(45, 96) %}
                    <option value="0.{{ '%02d' % pct }}" {% if (threshold * 100) | round | int == pct %}selected{% endif %}>{{ pct }}%</option>
                    {% endfor %}
                </select>
            </div>
        </div>
    </header>

    <main class="p-6 mx-auto">
        <div id="subtitle" class="text-neutral-400 mb-6"></div>

        <div id="loading-state" class="text-center py-16">
            <svg class="animate-spin w-12 h-12 mx-auto text-blue-500 mb-4" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            <p class="text-neutral-400 text-lg">{{ _('merge_suggestions.loading') }}</p>
        </div>

        <div id="groups-container" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4 items-start hidden">
            <!-- Groups loaded via JS -->
        </div>

        <div id="empty-state" class="hidden text-center py-16">
            <svg class="w-16 h-16 mx-auto text-neutral-600 mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
            </svg>
            <p class="text-neutral-400 text-lg">{{ _('merge_suggestions.no_suggestions') }}</p>
        </div>

        <div id="all-done-state" class="hidden text-center py-16">
            <svg class="w-16 h-16 mx-auto text-green-500 mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
            </svg>
            <p class="text-green-400 text-lg">{{ _('merge_suggestions.all_reviewed') }}</p>
        </div>
    </main>

    <!-- Toast notification -->
    <div id="toast" class="hidden fixed bottom-6 right-6 bg-green-600 text-white px-4 py-3 rounded-lg shadow-lg z-50 toast">
        <span id="toast-message"></span>
    </div>

    <!-- Hover preview (positioned by JS) -->
    <div id="hover-preview" class="hidden fixed z-[100] pointer-events-none">
        <img id="hover-preview-img" class="w-32 h-32 rounded-full object-cover border-2 border-blue-500 shadow-lg shadow-blue-500/20" src="" alt="">
        <div id="hover-preview-name" class="text-xs text-center text-neutral-300 mt-1 bg-neutral-900 px-2 py-1 rounded"></div>
    </div>

    <script>
        // i18n translations
        const I18N = {{ js_translations(['merge_suggestions', 'manage_persons', 'notifications', 'ui']) | tojson | safe }};
        function t(key, vars={}) {
            const keys = key.split('.');
            let value = I18N;
            for (const k of keys) {
                if (value && typeof value === 'object' && k in value) {
                    value = value[k];
                } else {
                    return key;
                }
            }
            if (typeof value === 'string' && Object.keys(vars).length > 0) {
                return value.replace(/\{(\w+)\}/g, (m, k) => vars[k] !== undefined ? vars[k] : m);
            }
            return value || key;
        }

        let currentGroups = [];
        const threshold = {{ threshold }};

        async function loadGroups() {
            const loadingState = document.getElementById('loading-state');
            const groupsContainer = document.getElementById('groups-container');
            try {
                const response = await fetch(`/api/merge_groups?threshold=${threshold}`);
                const data = await response.json();
                currentGroups = data.groups;
                // Sort by number of persons per group (descending)
                currentGroups.sort((a, b) => b.persons.length - a.persons.length);
                loadingState.classList.add('hidden');
                groupsContainer.classList.remove('hidden');
                renderGroups();
            } catch (err) {
                console.error('Failed to load groups:', err);
                loadingState.innerHTML = `
                    <svg class="w-12 h-12 mx-auto text-red-500 mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
                    </svg>
                    <p class="text-red-400 text-lg">${t('merge_suggestions.load_error')}</p>
                `;
            }
        }

        function renderGroups() {
            const container = document.getElementById('groups-container');
            const emptyState = document.getElementById('empty-state');
            const subtitle = document.getElementById('subtitle');

            if (currentGroups.length === 0) {
                container.innerHTML = '';
                emptyState.classList.remove('hidden');
                subtitle.textContent = '';
                return;
            }

            emptyState.classList.add('hidden');
            subtitle.textContent = t('merge_suggestions.subtitle', {count: currentGroups.length});

            container.innerHTML = currentGroups.map((group, idx) => `
                <div class="group-card bg-neutral-900 border border-neutral-800 rounded-lg p-3" data-group-index="${idx}">
                    <div class="flex items-center justify-between mb-2">
                        <div class="flex items-center gap-2">
                            <span class="text-neutral-400 text-xs font-medium">${t('merge_suggestions.group_label', {n: idx + 1})}</span>
                            <span class="text-[10px] text-neutral-500">(${group.persons.length})</span>
                        </div>
                        <div class="flex items-center gap-2">
                            <span class="text-[10px] px-1.5 py-0.5 rounded bg-blue-600/20 text-blue-400">
                                ${(group.avg_similarity * 100).toFixed(0)}%
                            </span>
                            <button onclick="dismissGroup(${idx})" class="w-5 h-5 flex items-center justify-center text-neutral-500 hover:text-red-400 transition-colors" title="${t('ui.buttons.dismiss')}">
                                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                                </svg>
                            </button>
                        </div>
                    </div>
                    <div class="flex flex-wrap gap-2 justify-center">
                        ${group.persons.map(p => `
                            <div class="person-item relative flex flex-col items-center bg-neutral-800 border border-neutral-700 rounded-lg p-1.5 hover:border-blue-500 transition-colors"
                                 data-person-id="${p.id}" data-person-name="${(p.name || 'Person ' + p.id).replace(/"/g, '&quot;')}">
                                <button onclick="removePersonFromGroup(${idx}, ${p.id})" class="absolute -top-1.5 -right-1.5 w-4 h-4 bg-red-600 hover:bg-red-500 rounded-full flex items-center justify-center text-white transition-colors z-10" title="${t('ui.buttons.remove')}">
                                    <svg class="w-2.5 h-2.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M6 18L18 6M6 6l12 12"/>
                                    </svg>
                                </button>
                                <a href="/?person=${p.id}" target="_blank">
                                    <img src="/person_thumbnail/${p.id}" class="w-12 h-12 rounded-full object-cover" loading="lazy" alt="">
                                </a>
                                <div class="text-[10px] text-neutral-300 truncate max-w-[60px] mt-1">${p.name || 'Person ' + p.id}</div>
                                <button onclick="mergeInto(${idx}, ${p.id})" ${group.persons.length < 2 ? 'disabled' : ''} class="mt-1 px-2 py-0.5 ${group.persons.length < 2 ? 'bg-neutral-600 cursor-not-allowed' : 'bg-blue-600 hover:bg-blue-500'} text-white text-[10px] rounded transition-colors">
                                    ${t('ui.buttons.merge')}
                                </button>
                            </div>
                        `).join('')}
                    </div>
                </div>
            `).join('');
        }

        function dismissGroup(groupIndex) {
            currentGroups.splice(groupIndex, 1);
            renderGroups();

            const subtitle = document.getElementById('subtitle');
            if (currentGroups.length > 0) {
                subtitle.textContent = t('merge_suggestions.subtitle', {count: currentGroups.length});
            } else {
                subtitle.textContent = '';
                document.getElementById('empty-state').classList.remove('hidden');
            }
        }

        function removePersonFromGroup(groupIndex, personId) {
            const group = currentGroups[groupIndex];
            group.persons = group.persons.filter(p => p.id !== personId);

            // If only 1 person left, remove the entire group
            if (group.persons.length < 2) {
                currentGroups.splice(groupIndex, 1);
            }

            // Re-render
            renderGroups();

            // Update subtitle
            const subtitle = document.getElementById('subtitle');
            if (currentGroups.length > 0) {
                subtitle.textContent = t('merge_suggestions.subtitle', {count: currentGroups.length});
            } else {
                subtitle.textContent = '';
                document.getElementById('empty-state').classList.remove('hidden');
            }
        }

        async function mergeInto(groupIndex, targetId) {
            const group = currentGroups[groupIndex];
            const sourceIds = group.persons.filter(p => p.id !== targetId).map(p => p.id);
            const targetPerson = group.persons.find(p => p.id === targetId);

            if (sourceIds.length === 0) {
                alert('Cannot merge a person into itself');
                return;
            }

            try {
                const response = await fetch('/merge_persons_batch', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest'
                    },
                    body: JSON.stringify({ source_ids: sourceIds, target_id: targetId })
                });
                const data = await response.json();

                if (data.success) {
                    // Animate and remove the group card
                    const card = document.querySelector(`[data-group-index="${groupIndex}"]`);
                    if (card) {
                        card.classList.add('merged');
                        setTimeout(() => card.remove(), 300);
                    }

                    // Remove from array
                    currentGroups.splice(groupIndex, 1);

                    // Update subtitle
                    const subtitle = document.getElementById('subtitle');
                    if (currentGroups.length > 0) {
                        subtitle.textContent = t('merge_suggestions.subtitle', {count: currentGroups.length});
                        // Re-render to fix group indices
                        setTimeout(renderGroups, 350);
                    } else {
                        subtitle.textContent = '';
                        document.getElementById('all-done-state').classList.remove('hidden');
                    }

                    // Show toast
                    showToast(t('merge_suggestions.merged_success', {
                        count: sourceIds.length,
                        name: targetPerson.name || 'Person ' + targetId
                    }));
                } else {
                    alert(t('notifications.error_merging') + ': ' + (data.error || 'Unknown error'));
                }
            } catch (err) {
                alert(t('notifications.error_merging') + ': ' + err.message);
            }
        }

        function showToast(message) {
            const toast = document.getElementById('toast');
            const toastMessage = document.getElementById('toast-message');
            toastMessage.textContent = message;
            toast.classList.remove('hidden');
            setTimeout(() => toast.classList.add('hidden'), 3000);
        }

        function changeThreshold(newThreshold) {
            window.location.href = `/suggest_merges?threshold=${newThreshold}`;
        }

        // Hover preview handling
        const hoverPreview = document.getElementById('hover-preview');
        const hoverPreviewImg = document.getElementById('hover-preview-img');
        const hoverPreviewName = document.getElementById('hover-preview-name');

        document.getElementById('groups-container').addEventListener('mouseenter', (e) => {
            const personItem = e.target.closest('.person-item');
            if (!personItem) return;

            const personId = personItem.dataset.personId;
            const personName = personItem.dataset.personName;

            hoverPreviewImg.src = `/person_thumbnail/${personId}`;
            hoverPreviewName.textContent = personName;

            const rect = personItem.getBoundingClientRect();
            let top = rect.top - 160;
            let left = rect.left + (rect.width / 2) - 64;

            // Keep preview within viewport
            if (top < 10) top = rect.bottom + 10;
            if (left < 10) left = 10;
            if (left + 128 > window.innerWidth - 10) left = window.innerWidth - 138;

            hoverPreview.style.top = top + 'px';
            hoverPreview.style.left = left + 'px';
            hoverPreview.classList.remove('hidden');
        }, true);

        document.getElementById('groups-container').addEventListener('mouseleave', (e) => {
            const personItem = e.target.closest('.person-item');
            if (!personItem) return;
            hoverPreview.classList.add('hidden');
        }, true);

        // Load groups on page load
        loadGroups();
    </script>
</body>
</html>
''', threshold=threshold)


# ============================================
# COMPARISON MODE ROUTES
# ============================================

COMPARISON_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Compare Photos - Facet</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        .photo-card { transition: all 0.15s; cursor: pointer; }
        .photo-card:hover { transform: scale(1.02); box-shadow: 0 0 20px rgba(147, 51, 234, 0.3); }
        .photo-card.selected { box-shadow: 0 0 0 4px #22c55e; }
        .keyboard-hint { font-family: monospace; background: #404040; padding: 2px 8px; border-radius: 4px; }
        .progress-bar { transition: width 0.3s; }
        /* Slider styling */
        .slider-input::-webkit-slider-thumb {
            appearance: none;
            width: 14px;
            height: 14px;
            background: #a855f7;
            border-radius: 50%;
            cursor: pointer;
            margin-top: -3px;
        }
        .slider-input::-moz-range-thumb {
            width: 14px;
            height: 14px;
            background: #a855f7;
            border-radius: 50%;
            cursor: pointer;
            border: none;
        }
        .slider-row:hover { background: rgba(255,255,255,0.03); }
    </style>
</head>
<body class="bg-neutral-950 text-white min-h-screen">
    <header class="bg-neutral-900 border-b border-neutral-800 px-6 py-4">
        <div class="flex items-center justify-between">
            <div class="flex items-center gap-4">
                <a href="/" class="text-neutral-400 hover:text-white">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 19l-7-7m0 0l7-7m-7 7h18"/>
                    </svg>
                </a>
                <h1 class="text-xl font-bold">Compare Photos</h1>
            </div>
            <div class="flex items-center gap-4">
                <div class="text-sm text-neutral-400">
                    <span id="comparison-count">{{ stats.total_comparisons }}</span> / {{ min_comparisons }} comparisons
                </div>
                <div class="w-48 bg-neutral-800 rounded-full h-2">
                    <div class="progress-bar bg-purple-600 h-2 rounded-full" style="width: {{ progress_pct }}%"></div>
                </div>
            </div>
        </div>
    </header>

    <main class="p-6">
        <div class="max-w-6xl mx-auto">
            <!-- Category & Strategy Selector -->
            <div class="mb-6 flex items-center gap-4 flex-wrap">
                <label class="text-neutral-400 text-sm">Category:</label>
                <select id="category-filter" class="bg-neutral-800 text-white text-sm px-3 py-2 rounded border border-neutral-700 border-purple-500">
                    {% for cat in categories %}
                    <option value="{{ cat }}" {{ 'selected' if cat == selected_category else '' }}>{{ cat }}</option>
                    {% endfor %}
                </select>
                <label class="text-neutral-400 text-sm ml-4">Strategy:</label>
                <select id="strategy" class="bg-neutral-800 text-white text-sm px-3 py-2 rounded border border-neutral-700">
                    <option value="uncertainty" {{ 'selected' if strategy == 'uncertainty' else '' }}>Uncertainty (similar scores)</option>
                    <option value="boundary" {{ 'selected' if strategy == 'boundary' else '' }}>Boundary (6-8 range)</option>
                    <option value="active" {{ 'selected' if strategy == 'active' else '' }}>Active Learning (low counts)</option>
                    <option value="random" {{ 'selected' if strategy == 'random' else '' }}>Random</option>
                </select>
                <button id="strategy-help-btn" class="text-neutral-400 hover:text-white" title="Strategy info">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
                    </svg>
                </button>
                <span class="text-neutral-500 text-sm ml-auto">Keyboard: <span class="keyboard-hint">A</span> left wins, <span class="keyboard-hint">B</span> right wins, <span class="keyboard-hint">T</span> equal, <span class="keyboard-hint">S</span> skip</span>
            </div>

            <!-- Strategy Help Panel (hidden by default) -->
            <div id="strategy-help-panel" class="hidden mb-6 p-4 bg-neutral-800 rounded-lg text-sm border border-neutral-700">
                <h4 class="font-bold text-white mb-3">Comparison Strategies</h4>
                <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div class="p-3 bg-neutral-900 rounded">
                        <strong class="text-purple-400">Uncertainty (Similar Scores)</strong>
                        <p class="text-neutral-300 mt-1">Selects pairs with nearly identical aggregate scores. Best for calibrating weights - your preference reveals which metrics matter when the algorithm can't tell the difference.</p>
                    </div>
                    <div class="p-3 bg-neutral-900 rounded">
                        <strong class="text-purple-400">Boundary (Quality Threshold)</strong>
                        <p class="text-neutral-300 mt-1">Focuses on photos scoring 5.5-8.5, the "gray zone" between good and mediocre. Helps refine the threshold between acceptable and rejects.</p>
                    </div>
                    <div class="p-3 bg-neutral-900 rounded">
                        <strong class="text-purple-400">Active Learning (Underrepresented)</strong>
                        <p class="text-neutral-300 mt-1">Prioritizes photos that have been compared fewer times. Ensures all photos contribute to the learned scores and improves overall coverage.</p>
                    </div>
                    <div class="p-3 bg-neutral-900 rounded">
                        <strong class="text-purple-400">Random Sampling</strong>
                        <p class="text-neutral-300 mt-1">Selects completely random pairs. Good for getting unbiased coverage and avoiding strategy-specific biases in your comparisons.</p>
                    </div>
                </div>
            </div>

            <!-- Photo Comparison Area -->
            <div id="comparison-area" class="grid grid-cols-2 gap-8">
                <div id="photo-a" class="photo-card bg-neutral-900 rounded-lg overflow-hidden border-2 border-neutral-700" onclick="selectWinner('a')">
                    <div class="aspect-[4/3] bg-neutral-800 flex items-center justify-center">
                        <img id="img-a" src="" class="max-w-full max-h-full object-contain hidden">
                        <span id="loading-a" class="text-neutral-500">Loading...</span>
                    </div>
                    <div class="p-4">
                        <div class="flex items-center justify-between mb-1">
                            <div class="text-lg font-bold text-purple-400">Photo A</div>
                            <div class="flex items-center gap-2" onclick="event.stopPropagation()">
                                <span id="category-a" class="text-xs text-neutral-500 bg-neutral-800 px-2 py-1 rounded">-</span>
                                <button onclick="openCategoryOverride('a')" class="text-xs text-neutral-400 hover:text-white" title="Change category">
                                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/>
                                    </svg>
                                </button>
                            </div>
                        </div>
                        <div id="info-a" class="text-sm text-neutral-400"></div>
                        {% if show_scores %}
                        <div id="score-a" class="text-xs text-neutral-500 mt-2"></div>
                        {% endif %}
                    </div>
                </div>

                <div id="photo-b" class="photo-card bg-neutral-900 rounded-lg overflow-hidden border-2 border-neutral-700" onclick="selectWinner('b')">
                    <div class="aspect-[4/3] bg-neutral-800 flex items-center justify-center">
                        <img id="img-b" src="" class="max-w-full max-h-full object-contain hidden">
                        <span id="loading-b" class="text-neutral-500">Loading...</span>
                    </div>
                    <div class="p-4">
                        <div class="flex items-center justify-between mb-1">
                            <div class="text-lg font-bold text-purple-400">Photo B</div>
                            <div class="flex items-center gap-2" onclick="event.stopPropagation()">
                                <span id="category-b" class="text-xs text-neutral-500 bg-neutral-800 px-2 py-1 rounded">-</span>
                                <button onclick="openCategoryOverride('b')" class="text-xs text-neutral-400 hover:text-white" title="Change category">
                                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/>
                                    </svg>
                                </button>
                            </div>
                        </div>
                        <div id="info-b" class="text-sm text-neutral-400"></div>
                        {% if show_scores %}
                        <div id="score-b" class="text-xs text-neutral-500 mt-2"></div>
                        {% endif %}
                    </div>
                </div>
            </div>

            <!-- Category Override Modal -->
            <div id="category-modal" class="fixed inset-0 bg-black bg-opacity-75 z-50 hidden flex items-center justify-center">
                <div class="bg-neutral-900 rounded-lg p-6 max-w-xl w-full mx-4 max-h-[80vh] overflow-y-auto">
                    <div class="flex items-center justify-between mb-4">
                        <h3 class="text-lg font-bold">Change Category</h3>
                        <button onclick="closeCategoryModal()" class="text-neutral-400 hover:text-white">
                            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                            </svg>
                        </button>
                    </div>

                    <div class="mb-4">
                        <label class="text-sm text-neutral-400">Photo: <span id="modal-photo-name" class="text-white">-</span></label>
                        <div class="flex items-center gap-2 mt-2">
                            <span class="text-sm">Current:</span>
                            <span id="modal-current-category" class="text-purple-400 font-bold">-</span>
                        </div>
                    </div>

                    <div class="mb-4">
                        <label class="text-sm text-neutral-400 block mb-2">Select new category:</label>
                        <select id="modal-target-category" class="w-full bg-neutral-800 text-white px-3 py-2 rounded border border-neutral-700">
                            {% for cat in categories %}
                            <option value="{{ cat }}">{{ cat }}</option>
                            {% endfor %}
                        </select>
                    </div>

                    <button onclick="analyzeFilterConflicts()" class="w-full bg-purple-600 hover:bg-purple-700 text-white py-2 rounded mb-4">
                        Analyze Filter Conflicts
                    </button>

                    <!-- Filter Analysis Results -->
                    <div id="filter-analysis" class="hidden">
                        <div id="no-conflicts" class="hidden p-4 bg-green-900/30 border border-green-700 rounded mb-4">
                            <div class="flex items-center gap-2 text-green-400">
                                <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
                                </svg>
                                <span>Photo already matches target category filters</span>
                            </div>
                        </div>

                        <div id="conflicts-section" class="hidden mb-4">
                            <h4 class="text-sm font-bold text-red-400 mb-2">Filter Conflicts</h4>
                            <div id="conflicts-list" class="space-y-2 text-sm"></div>
                        </div>

                        <div id="suggestions-section" class="hidden mb-4">
                            <h4 class="text-sm font-bold text-yellow-400 mb-2">Suggested Filter Changes</h4>
                            <div id="suggestions-list" class="space-y-2 text-sm"></div>
                        </div>

                        <div id="photo-values-section" class="mb-4">
                            <h4 class="text-sm font-bold text-neutral-400 mb-2">Photo Values</h4>
                            <div id="photo-values-grid" class="grid grid-cols-2 gap-2 text-xs bg-neutral-800 p-3 rounded"></div>
                        </div>
                    </div>

                    <div class="flex gap-2 mt-4">
                        <button onclick="applyOverride()" class="flex-1 bg-green-600 hover:bg-green-700 text-white py-2 rounded">
                            Apply Override
                        </button>
                        <button onclick="closeCategoryModal()" class="flex-1 bg-neutral-700 hover:bg-neutral-600 text-white py-2 rounded">
                            Cancel
                        </button>
                    </div>
                </div>
            </div>

            <!-- Action Buttons -->
            <div class="mt-6 flex justify-center gap-4">
                <button onclick="selectWinner('tie')" class="bg-neutral-700 hover:bg-neutral-600 text-white px-6 py-2 rounded" title="Both photos are equally good (or equally bad)">
                    Equal Quality (T)
                </button>
                <button onclick="selectWinner('skip')" class="bg-neutral-800 hover:bg-neutral-700 text-neutral-400 px-6 py-2 rounded" title="Can't decide or photos are too different to compare">
                    Can't Compare (S)
                </button>
            </div>

            <!-- Action Bar -->
            <div class="mt-4 flex justify-center gap-4">
                <button id="suggest-weights"
                        class="bg-green-700 hover:bg-green-600 text-white px-6 py-2 rounded"
                        title="Suggest optimal weights based on your comparisons">
                    Suggest Weights
                </button>
                <button id="apply-weights"
                        class="bg-purple-700 hover:bg-purple-600 text-white px-6 py-2 rounded"
                        title="Save suggested weights to config file">
                    Apply Config
                </button>
                <button id="recalculate-btn" onclick="recalculateScores()"
                        class="bg-blue-700 hover:bg-blue-600 text-white px-6 py-2 rounded"
                        title="Recalculate all categories and aggregate scores using current config">
                    Recalculate
                </button>
                <button id="reset-weights"
                        class="bg-neutral-700 hover:bg-neutral-600 text-white px-6 py-2 rounded"
                        title="Reset weight sliders to original values">
                    Reset Weights
                </button>
                <button onclick="resetComparisons()"
                        class="bg-red-700 hover:bg-red-600 text-white px-6 py-2 rounded"
                        title="Clear all comparison data and start fresh">
                    Reset All
                </button>
            </div>

            <!-- Session Stats (Compact) -->
            <div class="mt-8 p-3 bg-neutral-900 rounded-lg">
                <div class="flex items-center gap-6 text-sm">
                    <button id="stats-toggle" onclick="toggleStats()" class="text-neutral-400 hover:text-white flex items-center gap-1">
                        <svg id="stats-chevron" class="w-4 h-4 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/>
                        </svg>
                        <span class="font-bold">Stats</span>
                    </button>
                    <span class="text-neutral-400">Total: <span id="stat-total" class="text-white font-bold">{{ stats.total_comparisons }}</span></span>
                    <span class="text-neutral-400">A: <span id="stat-a" class="text-purple-400 font-bold">{{ stats.winner_breakdown.get('a', 0) }}</span></span>
                    <span class="text-neutral-400">B: <span id="stat-b" class="text-purple-400 font-bold">{{ stats.winner_breakdown.get('b', 0) }}</span></span>
                    <span class="text-neutral-400">Ties: <span id="stat-tie" class="text-neutral-300 font-bold">{{ stats.winner_breakdown.get('tie', 0) }}</span></span>
                </div>
                <!-- Expanded stats (hidden by default) -->
                <div id="stats-expanded" class="hidden mt-3 pt-3 border-t border-neutral-800">
                    <div class="grid grid-cols-4 gap-4 text-sm">
                        <div>
                            <div class="text-neutral-500">Total Comparisons</div>
                            <div id="stat-total-expanded" class="text-xl font-bold">{{ stats.total_comparisons }}</div>
                        </div>
                        <div>
                            <div class="text-neutral-500">A Wins</div>
                            <div id="stat-a-expanded" class="text-xl font-bold text-purple-400">{{ stats.winner_breakdown.get('a', 0) }}</div>
                        </div>
                        <div>
                            <div class="text-neutral-500">B Wins</div>
                            <div id="stat-b-expanded" class="text-xl font-bold text-purple-400">{{ stats.winner_breakdown.get('b', 0) }}</div>
                        </div>
                        <div>
                            <div class="text-neutral-500">Ties</div>
                            <div id="stat-tie-expanded" class="text-xl font-bold text-neutral-400">{{ stats.winner_breakdown.get('tie', 0) }}</div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Weight Preview Panel (always visible) -->
            <div id="weight-panel" class="mt-6 p-4 bg-neutral-900 rounded-lg">
                <div class="flex items-center gap-2 mb-4">
                    <h3 class="text-lg font-bold">Weight Preview</h3>
                    <button id="weight-help-btn" class="text-neutral-400 hover:text-white" title="How it works">
                        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
                        </svg>
                    </button>
                </div>

                <!-- How It Works (hidden by default) -->
                <div id="weight-help-panel" class="hidden mb-4 p-4 bg-neutral-800 rounded-lg text-sm border border-neutral-700">
                    <h4 class="font-bold text-white mb-3">How Weight Learning Works</h4>
                    <div class="space-y-3 text-neutral-300">
                        <div>
                            <strong class="text-purple-400">1. Your comparisons teach the system</strong>
                            <p class="mt-1">Each time you pick a winner, the system learns your preferences using the Bradley-Terry model, which calculates a "true quality score" for each photo based on win/loss patterns.</p>
                        </div>
                        <div>
                            <strong class="text-purple-400">2. Suggest Weights optimizes the weight combination</strong>
                            <p class="mt-1">The algorithm finds the best <em>ratio</em> of weights that makes the combined score match your preferences. It uses mathematical optimization (SLSQP) to maximize how well the weighted sum predicts your choices.</p>
                        </div>
                        <div>
                            <strong class="text-purple-400">3. Rank correlation measures accuracy</strong>
                            <p class="mt-1">
                                <span class="text-green-400">Positive correlation (+0.5 to +1.0)</span> = weights rank photos similar to your preferences<br>
                                <span class="text-yellow-400">Near zero (-0.2 to +0.2)</span> = not enough data or mixed signals<br>
                                <span class="text-red-400">Negative correlation</span> = weights rank opposite to your preferences
                            </p>
                        </div>
                        <div>
                            <strong class="text-purple-400">4. Apply to save, Recalculate to update</strong>
                            <p class="mt-1">Click "Apply to Config" to save weights, then "Recalculate Scores" to update all photo scores in the database.</p>
                        </div>
                    </div>
                    <div class="mt-3 p-2 bg-neutral-900 rounded text-xs text-neutral-400">
                        <strong>Tip:</strong> Do 30+ comparisons per category for suggestions (50+ recommended for accuracy). Mix strategies for best coverage. Ties are now included in optimization.
                    </div>
                </div>

                <!-- Suggestion Info (hidden by default) -->
                <div id="suggestion-info" class="mb-4 p-3 bg-neutral-800 rounded hidden">
                    <div class="flex items-center justify-between flex-wrap gap-2">
                        <span class="text-sm text-neutral-400">
                            Learned from <span id="suggestion-comparisons">0</span> comparisons
                            <span id="suggestion-ties" class="text-neutral-500">(incl. <span id="suggestion-ties-count">0</span> ties)</span>
                        </span>
                        <span class="text-sm">
                            Prediction accuracy: <span id="suggestion-acc-before" class="text-neutral-400">0%</span>
                            &rarr; <span id="suggestion-acc-after" class="text-green-400 font-bold">0%</span>
                            (<span id="suggestion-improvement" class="font-bold">+0%</span>)
                        </span>
                    </div>
                    <div id="suggestion-mispredicted" class="mt-2 text-xs text-neutral-500 hidden">
                        <span id="suggestion-mispredicted-count">0</span> comparisons predicted incorrectly
                    </div>
                    <div id="suggestion-warning" class="mt-2 text-xs text-yellow-500 hidden">
                        Current weights already achieve good accuracy - changes not recommended.
                    </div>
                    <!-- Weight changes delta -->
                    <div id="suggestion-deltas" class="mt-3 pt-3 border-t border-neutral-700">
                        <div class="text-xs text-neutral-400 mb-2">Weight changes:</div>
                        <div id="suggestion-deltas-list" class="flex flex-wrap gap-2 text-xs"></div>
                    </div>
                </div>
                <!-- Unified Score Preview & Weight Grid -->
                <div class="bg-neutral-800 p-4 rounded">
                    <!-- Compact Score Preview Header -->
                    <div class="flex items-center justify-between mb-3">
                        <h4 class="font-bold">Score Preview</h4>
                        <span class="text-sm">Category: <span id="category-name" class="text-purple-400">-</span></span>
                    </div>
                    <div class="grid grid-cols-2 gap-4 text-sm mb-4 pb-3 border-b border-neutral-700">
                        <div class="flex items-center gap-2">
                            <span class="text-neutral-400">Photo A:</span>
                            <span id="preview-a-current" class="text-purple-400">-</span>
                            <span class="text-neutral-500">&rarr;</span>
                            <span id="preview-a-new" class="text-green-400">-</span>
                            <span id="preview-a-delta" class="text-xs">(Δ-)</span>
                        </div>
                        <div class="flex items-center gap-2">
                            <span class="text-neutral-400">Photo B:</span>
                            <span id="preview-b-current" class="text-purple-400">-</span>
                            <span class="text-neutral-500">&rarr;</span>
                            <span id="preview-b-new" class="text-green-400">-</span>
                            <span id="preview-b-delta" class="text-xs">(Δ-)</span>
                        </div>
                    </div>
                    <!-- Column headers for unified grid -->
                    <div class="flex items-center gap-2 text-xs text-neutral-500 mb-2 px-1">
                        <span class="w-24">Property</span>
                        <span class="w-12 text-right">A</span>
                        <span class="w-12 text-right">B</span>
                        <span class="flex-1 text-center">Weight</span>
                        <span class="w-8 text-right">%</span>
                        <span class="w-6"></span>
                        <span class="w-12"></span>
                    </div>
                    <!-- Unified Property Grid -->
                    <div id="weight-sliders" class="space-y-1 text-sm max-h-[32rem] overflow-y-auto pr-2">
                        <!-- Sliders with A/B values inserted dynamically -->
                    </div>
                </div>
            </div>
        </div>
    </main>

    <script>
        let currentPair = null;
        const showScores = {{ 'true' if show_scores else 'false' }};

        async function loadNextPair() {
            const strategy = document.getElementById('strategy').value;
            const category = document.getElementById('category-filter').value;
            document.getElementById('loading-a').classList.remove('hidden');
            document.getElementById('loading-b').classList.remove('hidden');
            document.getElementById('img-a').classList.add('hidden');
            document.getElementById('img-b').classList.add('hidden');

            try {
                let url = `/api/comparison/next_pair?strategy=${strategy}`;
                if (category) {
                    url += `&category=${encodeURIComponent(category)}`;
                }
                const response = await fetch(url);
                const data = await response.json();

                if (data.error) {
                    alert(data.error);
                    return;
                }

                currentPair = data;

                // Load thumbnails (embedded in database for fast loading)
                document.getElementById('img-a').src = `/thumbnail?path=${encodeURIComponent(data.a)}`;
                document.getElementById('img-b').src = `/thumbnail?path=${encodeURIComponent(data.b)}`;

                document.getElementById('img-a').onload = () => {
                    document.getElementById('loading-a').classList.add('hidden');
                    document.getElementById('img-a').classList.remove('hidden');
                };
                document.getElementById('img-a').onerror = () => {
                    document.getElementById('loading-a').textContent = 'Failed to load';
                    console.error('Failed to load thumbnail for:', data.a);
                };
                document.getElementById('img-b').onload = () => {
                    document.getElementById('loading-b').classList.add('hidden');
                    document.getElementById('img-b').classList.remove('hidden');
                };
                document.getElementById('img-b').onerror = () => {
                    document.getElementById('loading-b').textContent = 'Failed to load';
                    console.error('Failed to load thumbnail for:', data.b);
                };

                // Show file info
                document.getElementById('info-a').textContent = data.a.split('/').pop();
                document.getElementById('info-b').textContent = data.b.split('/').pop();

                if (showScores) {
                    document.getElementById('score-a').textContent = `Score: ${data.score_a?.toFixed(2) || 'N/A'}`;
                    document.getElementById('score-b').textContent = `Score: ${data.score_b?.toFixed(2) || 'N/A'}`;
                }

                // Reset selection state
                document.getElementById('photo-a').classList.remove('selected');
                document.getElementById('photo-b').classList.remove('selected');
            } catch (err) {
                console.error('Error loading pair:', err);
                alert('Failed to load next pair');
            }
        }

        async function selectWinner(winner) {
            if (!currentPair) return;

            // Visual feedback
            if (winner === 'a') {
                document.getElementById('photo-a').classList.add('selected');
            } else if (winner === 'b') {
                document.getElementById('photo-b').classList.add('selected');
            }

            try {
                const category = document.getElementById('category-filter').value;
                const response = await fetch('/api/comparison/submit', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        photo_a: currentPair.a,
                        photo_b: currentPair.b,
                        winner: winner,
                        category: category || null
                    })
                });

                const data = await response.json();
                if (data.success) {
                    // Update stats (compact and expanded)
                    updateAllStats(data.stats);
                    document.getElementById('comparison-count').textContent = data.stats.total_comparisons;

                    // Update progress bar
                    const pct = Math.min(100, (data.stats.total_comparisons / {{ min_comparisons }}) * 100);
                    document.querySelector('.progress-bar').style.width = pct + '%';

                    // Load next pair
                    setTimeout(loadNextPair, 300);
                }
            } catch (err) {
                console.error('Error submitting:', err);
            }
        }

        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {
            if (e.target.tagName === 'INPUT') return; // Don't trigger on input fields
            if (e.key.toLowerCase() === 'a') selectWinner('a');
            else if (e.key.toLowerCase() === 'b') selectWinner('b');
            else if (e.key.toLowerCase() === 't') selectWinner('tie');
            else if (e.key.toLowerCase() === 's') selectWinner('skip');
        });

        // Toggle stats expansion
        function toggleStats() {
            const expanded = document.getElementById('stats-expanded');
            const chevron = document.getElementById('stats-chevron');
            expanded.classList.toggle('hidden');
            chevron.classList.toggle('rotate-90');
        }

        // Update all stat displays (compact + expanded)
        function updateAllStats(stats) {
            document.getElementById('stat-total').textContent = stats.total_comparisons;
            document.getElementById('stat-a').textContent = stats.winner_breakdown.a || 0;
            document.getElementById('stat-b').textContent = stats.winner_breakdown.b || 0;
            document.getElementById('stat-tie').textContent = stats.winner_breakdown.tie || 0;
            // Also update expanded versions
            const expandedTotal = document.getElementById('stat-total-expanded');
            if (expandedTotal) expandedTotal.textContent = stats.total_comparisons;
            const expandedA = document.getElementById('stat-a-expanded');
            if (expandedA) expandedA.textContent = stats.winner_breakdown.a || 0;
            const expandedB = document.getElementById('stat-b-expanded');
            if (expandedB) expandedB.textContent = stats.winner_breakdown.b || 0;
            const expandedTie = document.getElementById('stat-tie-expanded');
            if (expandedTie) expandedTie.textContent = stats.winner_breakdown.tie || 0;
        }

        // Reset all comparisons
        async function resetComparisons() {
            const totalComparisons = document.getElementById('stat-total').textContent;
            const confirmMsg = `RESET ALL COMPARISON DATA

This will permanently delete:
- ${totalComparisons} pairwise comparisons
- All learned weight suggestions
- All session statistics

This cannot be undone. Continue?`;
            if (!confirm(confirmMsg)) {
                return;
            }
            try {
                const response = await fetch('/api/comparison/reset', { method: 'POST' });
                const data = await response.json();
                if (data.success) {
                    // Reset UI
                    updateAllStats({total_comparisons: 0, winner_breakdown: {a: 0, b: 0, tie: 0}});
                    document.getElementById('comparison-count').textContent = '0';
                    document.querySelector('.progress-bar').style.width = '0%';
                    document.getElementById('suggestion-info').classList.add('hidden');
                    alert('Comparison data has been reset.');
                    loadNextPair();
                } else {
                    alert('Error resetting data: ' + (data.error || 'Unknown error'));
                }
            } catch (err) {
                console.error('Error resetting comparisons:', err);
                alert('Error resetting comparison data');
            }
        }

        // Recalculate all scores
        async function recalculateScores() {
            const category = document.getElementById('category-filter').value;
            const confirmMsg = `RECALCULATE ALL PHOTO SCORES

This will:
- Re-determine categories for all photos based on config filters
- Recalculate aggregate scores using current category weights
- Update the database with new scores

Category weights from: ${category || 'current config'}

This may take several minutes for large databases. Continue?`;
            if (!confirm(confirmMsg)) {
                return;
            }

            const btn = document.getElementById('recalculate-btn');
            const originalText = btn.textContent;
            btn.textContent = 'Recalculating...';
            btn.disabled = true;
            btn.classList.add('opacity-50', 'cursor-not-allowed');

            try {
                const response = await fetch('/api/recalculate', { method: 'POST' });
                const data = await response.json();

                if (data.success) {
                    alert('Recalculation complete! Categories and scores have been updated.');
                    // Reload the current pair to show updated scores
                    loadNextPair();
                } else {
                    alert('Error: ' + (data.error || 'Unknown error'));
                }
            } catch (err) {
                console.error('Error recalculating:', err);
                alert('Error recalculating scores. Check console for details.');
            } finally {
                btn.textContent = originalText;
                btn.disabled = false;
                btn.classList.remove('opacity-50', 'cursor-not-allowed');
            }
        }

        // Strategy change
        document.getElementById('strategy').addEventListener('change', loadNextPair);

        // Strategy help toggle
        document.getElementById('strategy-help-btn').addEventListener('click', () => {
            const panel = document.getElementById('strategy-help-panel');
            panel.classList.toggle('hidden');
        });

        // Weight help toggle
        document.getElementById('weight-help-btn').addEventListener('click', () => {
            const panel = document.getElementById('weight-help-panel');
            panel.classList.toggle('hidden');
        });

        // Category filter change
        document.getElementById('category-filter').addEventListener('change', () => {
            loadNextPair();
            if (weightPanelVisible) loadCategoryWeights();
        });

        // Weight preview panel state (always visible now)
        let weightPanelVisible = true;
        let currentWeights = {};
        let originalWeights = {};
        let photoMetrics = {};

        // Reset weights button
        document.getElementById('reset-weights').addEventListener('click', () => {
            currentWeights = {...originalWeights};
            renderWeightSliders();
            updateScorePreview();
            document.getElementById('suggestion-info').classList.add('hidden');
        });

        // Apply weights to config button
        document.getElementById('apply-weights').addEventListener('click', async () => {
            const category = document.getElementById('category-filter').value;
            if (!category) {
                alert('Please select a category first to apply weights.');
                return;
            }

            // Check if weights have changed
            const hasChanges = Object.keys(currentWeights).some(k => currentWeights[k] !== originalWeights[k]);
            if (!hasChanges) {
                alert('No weight changes to apply.');
                return;
            }

            // Build weight changes summary
            const changes = [];
            for (const key of Object.keys(currentWeights)) {
                const oldVal = originalWeights[key] || 0;
                const newVal = currentWeights[key] || 0;
                if (Math.abs(newVal - oldVal) >= 1) {
                    const name = key.replace(/_percent$/, '').replace(/_/g, ' ');
                    changes.push(`  ${name}: ${Math.round(oldVal)}% -> ${Math.round(newVal)}%`);
                }
            }

            const confirmMsg = `APPLY WEIGHTS TO CONFIG

Category: ${category}

Weight changes:
${changes.join('\\n')}

This will:
- Update scoring_config.json with new weights
- Create a backup of the current config
- NOT recalculate existing scores (use "Recalculate Scores" after)

Save these weights?`;
            if (!confirm(confirmMsg)) {
                return;
            }

            const btn = document.getElementById('apply-weights');
            const originalText = btn.textContent;
            btn.textContent = 'Saving...';
            btn.disabled = true;

            try {
                const response = await fetch('/api/config/update_weights', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        category: category,
                        weights: currentWeights,
                        recalculate: false  // User can manually recalculate
                    })
                });

                const data = await response.json();
                if (data.success) {
                    originalWeights = {...currentWeights};
                    alert(`Weights saved for "${category}"!\\n\\nBackup created: ${data.backup}\\n\\nClick "Recalculate Scores" to apply to all photos.`);
                } else {
                    alert('Error: ' + (data.error || 'Unknown error'));
                }
            } catch (err) {
                console.error('Error saving weights:', err);
                alert('Error saving weights');
            } finally {
                btn.textContent = originalText;
                btn.disabled = false;
            }
        });

        // Suggest weights button
        document.getElementById('suggest-weights').addEventListener('click', async () => {
            const category = document.getElementById('category-filter').value || null;
            const btn = document.getElementById('suggest-weights');
            btn.disabled = true;
            btn.textContent = 'Loading...';

            try {
                const url = category
                    ? `/api/comparison/learned_weights?category=${category}`
                    : '/api/comparison/learned_weights';
                const response = await fetch(url);
                const data = await response.json();

                if (data.available) {
                    // Store old weights before applying suggestions
                    const oldWeights = {...currentWeights};

                    // Merge suggested weights with original (keeps any weights not in optimizer)
                    currentWeights = {...originalWeights, ...data.suggested_weights};
                    renderWeightSliders();
                    updateScorePreview();

                    // Show suggestion info with accuracy metrics
                    document.getElementById('suggestion-comparisons').textContent = data.comparisons_used;

                    // Show ties count if available
                    const tiesEl = document.getElementById('suggestion-ties');
                    const tiesCountEl = document.getElementById('suggestion-ties-count');
                    if (data.ties_included && data.ties_included > 0) {
                        tiesCountEl.textContent = data.ties_included;
                        tiesEl.classList.remove('hidden');
                    } else {
                        tiesEl.classList.add('hidden');
                    }

                    // Show accuracy before/after
                    document.getElementById('suggestion-acc-before').textContent = (data.accuracy_before || 0).toFixed(1) + '%';
                    document.getElementById('suggestion-acc-after').textContent = (data.accuracy_after || 0).toFixed(1) + '%';

                    // Show improvement
                    const improvement = data.improvement || 0;
                    const improvementEl = document.getElementById('suggestion-improvement');
                    improvementEl.textContent = (improvement >= 0 ? '+' : '') + improvement.toFixed(1) + '%';
                    improvementEl.className = improvement >= 0 ? 'font-bold text-green-400' : 'font-bold text-red-400';

                    // Show mispredicted count if any
                    const mispredEl = document.getElementById('suggestion-mispredicted');
                    const mispredCountEl = document.getElementById('suggestion-mispredicted-count');
                    if (data.mispredicted_count && data.mispredicted_count > 0) {
                        mispredCountEl.textContent = data.mispredicted_count;
                        mispredEl.classList.remove('hidden');
                    } else {
                        mispredEl.classList.add('hidden');
                    }

                    // Show warning if changes not recommended
                    const warningEl = document.getElementById('suggestion-warning');
                    if (data.suggest_changes === false) {
                        warningEl.classList.remove('hidden');
                    } else {
                        warningEl.classList.add('hidden');
                    }

                    // Build weight deltas display
                    // Note: weights are already in percentage format (0-100)
                    const deltasList = document.getElementById('suggestion-deltas-list');
                    deltasList.innerHTML = '';
                    const allKeys = new Set([...Object.keys(oldWeights), ...Object.keys(currentWeights)]);
                    const deltas = [];
                    for (const key of allKeys) {
                        const oldVal = oldWeights[key] || 0;
                        const newVal = currentWeights[key] || 0;
                        const delta = newVal - oldVal;
                        if (Math.abs(delta) >= 1) {  // Only show changes >= 1%
                            deltas.push({ key, oldVal, newVal, delta });
                        }
                    }
                    // Sort by absolute delta descending
                    deltas.sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta));

                    if (deltas.length === 0) {
                        deltasList.innerHTML = '<span class="text-neutral-500">No significant changes</span>';
                    } else {
                        for (const { key, oldVal, newVal, delta } of deltas) {
                            const colorClass = delta > 0 ? 'text-green-400' : 'text-red-400';
                            const arrow = delta > 0 ? '↑' : '↓';
                            // Clean up key name: remove _percent suffix and replace underscores
                            const displayName = key.replace(/_percent$/, '').replace(/_/g, ' ');
                            const chip = document.createElement('span');
                            chip.className = 'inline-flex items-center gap-1 px-2 py-1 bg-neutral-700 rounded';
                            chip.innerHTML = `<span class="text-neutral-300">${displayName}</span>` +
                                `<span class="text-neutral-500">${Math.round(oldVal)}%</span>` +
                                `<span class="text-neutral-500">&rarr;</span>` +
                                `<span class="${colorClass} font-medium">${Math.round(newVal)}%</span>` +
                                `<span class="${colorClass}">${arrow}${Math.abs(Math.round(delta))}</span>`;
                            deltasList.appendChild(chip);
                        }
                    }

                    document.getElementById('suggestion-info').classList.remove('hidden');
                } else {
                    alert(data.message || 'Could not generate suggestions');
                    document.getElementById('suggestion-info').classList.add('hidden');
                }
            } catch (err) {
                console.error('Error fetching suggestions:', err);
                alert('Error fetching weight suggestions');
            } finally {
                btn.disabled = false;
                btn.textContent = 'Suggest Weights';
            }
        });

        // Load category weights from API
        async function loadCategoryWeights() {
            const category = document.getElementById('category-filter').value || 'portrait';
            try {
                const response = await fetch(`/api/comparison/category_weights?category=${category}`);
                const data = await response.json();
                if (data.weights) {
                    originalWeights = {...data.weights};
                    currentWeights = {...data.weights};
                    document.getElementById('category-name').textContent = category;
                    renderWeightSliders();
                }
            } catch (err) {
                console.error('Error loading weights:', err);
            }
        }

        // Render weight sliders - shows ALL scoring components with A/B values inline
        function renderWeightSliders() {
            const container = document.getElementById('weight-sliders');
            container.innerHTML = '';

            // Get photo metrics for A/B values
            const metricsA = currentPair ? (photoMetrics[currentPair.a] || {}) : {};
            const metricsB = currentPair ? (photoMetrics[currentPair.b] || {}) : {};

            // All possible scoring components with labels and metric keys (grouped)
            const allComponents = [
                // Primary quality metrics
                { key: 'aesthetic_percent', label: 'Aesthetic', metricKey: 'aesthetic', group: 'Quality' },
                { key: 'quality_percent', label: 'Quality Score', metricKey: 'quality_score', group: 'Quality' },
                { key: 'face_quality_percent', label: 'Face Quality', metricKey: 'face_quality', group: 'Quality' },
                { key: 'face_sharpness_percent', label: 'Face Sharpness', metricKey: 'face_sharpness', group: 'Quality' },
                { key: 'eye_sharpness_percent', label: 'Eye Sharpness', metricKey: 'eye_sharpness', group: 'Quality' },
                { key: 'tech_sharpness_percent', label: 'Tech Sharpness', metricKey: 'tech_sharpness', group: 'Quality' },
                // Composition metrics
                { key: 'composition_percent', label: 'Composition', metricKey: 'comp_score', group: 'Composition' },
                { key: 'power_point_percent', label: 'Power Points', metricKey: 'power_point_score', group: 'Composition' },
                { key: 'leading_lines_percent', label: 'Leading Lines', metricKey: 'leading_lines_score', group: 'Composition' },
                // Technical metrics
                { key: 'exposure_percent', label: 'Exposure', metricKey: 'exposure_score', group: 'Technical' },
                { key: 'color_percent', label: 'Color', metricKey: 'color_score', group: 'Technical' },
                { key: 'contrast_percent', label: 'Contrast', metricKey: 'contrast_score', group: 'Technical' },
                { key: 'dynamic_range_percent', label: 'Dynamic Range', metricKey: 'dynamic_range_stops', group: 'Technical' },
                { key: 'saturation_percent', label: 'Saturation', metricKey: 'mean_saturation', group: 'Technical' },
                { key: 'noise_percent', label: 'Noise (inv)', metricKey: 'noise_sigma', group: 'Technical', inverse: true },
                // Bonuses
                { key: 'isolation_percent', label: 'Isolation', metricKey: 'isolation_bonus', group: 'Bonus' },
            ];

            // Group components by category
            const groups = {};
            for (const comp of allComponents) {
                if (!groups[comp.group]) {
                    groups[comp.group] = [];
                }
                groups[comp.group].push(comp);
            }

            // Helper to get color class for A/B value comparison
            function getCompareClass(valA, valB, inverse = false) {
                if (valA == null || valB == null || valA === valB) return ['text-neutral-300', 'text-neutral-300'];
                if (inverse) {
                    // Lower is better (e.g., noise)
                    return [
                        valA < valB ? 'text-green-400' : 'text-red-400',
                        valB < valA ? 'text-green-400' : 'text-red-400'
                    ];
                } else {
                    // Higher is better
                    return [
                        valA > valB ? 'text-green-400' : 'text-red-400',
                        valB > valA ? 'text-green-400' : 'text-red-400'
                    ];
                }
            }

            // Render each group with header
            for (const [groupName, components] of Object.entries(groups)) {
                // Add group header
                container.insertAdjacentHTML('beforeend', `
                    <div class="text-xs text-purple-400 uppercase tracking-wide mt-3 mb-1 first:mt-0">${groupName}</div>
                `);

                for (const {key, label, metricKey, inverse} of components) {
                    // Default to 0 if not in currentWeights
                    const value = currentWeights[key] || 0;
                    const origValue = originalWeights[key] || 0;
                    // Ensure currentWeights has all keys for preview calculation
                    if (!(key in currentWeights)) {
                        currentWeights[key] = 0;
                    }
                    const isZero = value === 0;
                    const delta = value - origValue;
                    const deltaClass = delta > 0 ? 'text-green-400' : (delta < 0 ? 'text-red-400' : 'text-neutral-500');
                    const deltaText = delta !== 0 ? (delta > 0 ? '+' + delta : delta) : '';
                    const origMarkerPos = origValue + '%';

                    // Get A/B metric values
                    const valA = metricsA[metricKey];
                    const valB = metricsB[metricKey];
                    const fmtA = valA != null ? (typeof valA === 'number' ? valA.toFixed(2) : valA) : '-';
                    const fmtB = valB != null ? (typeof valB === 'number' ? valB.toFixed(2) : valB) : '-';
                    const [classA, classB] = getCompareClass(valA, valB, inverse);

                    const html = `
                        <div class="flex items-center gap-2 slider-row ${isZero && origValue === 0 ? 'opacity-50' : ''}" data-key="${key}">
                            <span class="w-24 text-neutral-400 text-xs truncate" title="${label}">${label}</span>
                            <span class="w-12 text-right text-xs font-mono ${classA}" data-metric-a="${metricKey}">${fmtA}</span>
                            <span class="w-12 text-right text-xs font-mono ${classB}" data-metric-b="${metricKey}">${fmtB}</span>
                            <div class="flex-1 relative">
                                <input type="range" min="0" max="100" value="${value}"
                                       class="w-full h-2 bg-neutral-700 rounded appearance-none cursor-pointer slider-input"
                                       data-key="${key}" data-orig="${origValue}" oninput="onWeightChange(this)">
                                <div class="absolute top-0 h-2 w-0.5 bg-yellow-500 pointer-events-none" style="left: ${origMarkerPos}; transform: translateX(-50%);" title="Original: ${origValue}%"></div>
                            </div>
                            <span class="w-8 text-right text-xs font-mono" id="val-${key}">${value}</span>
                            <span class="w-6 text-right text-xs font-mono ${deltaClass}" id="delta-${key}">${deltaText}</span>
                            <div class="flex gap-0.5">
                                <button onclick="adjustWeight('${key}', -5)" class="w-5 h-5 text-xs bg-neutral-700 hover:bg-neutral-600 rounded" title="-5%">-</button>
                                <button onclick="adjustWeight('${key}', 5)" class="w-5 h-5 text-xs bg-neutral-700 hover:bg-neutral-600 rounded" title="+5%">+</button>
                            </div>
                        </div>
                    `;
                    container.insertAdjacentHTML('beforeend', html);
                }
            }
        }

        // Handle weight slider change
        function onWeightChange(slider) {
            const key = slider.dataset.key;
            const value = parseInt(slider.value);
            const origValue = parseInt(slider.dataset.orig) || 0;
            currentWeights[key] = value;

            const valEl = document.getElementById(`val-${key}`);
            valEl.textContent = value;

            // Update delta display
            const delta = value - origValue;
            const deltaEl = document.getElementById(`delta-${key}`);
            if (deltaEl) {
                deltaEl.textContent = delta !== 0 ? (delta > 0 ? '+' + delta : delta) : '';
                deltaEl.className = 'w-6 text-right text-xs font-mono ' +
                    (delta > 0 ? 'text-green-400' : (delta < 0 ? 'text-red-400' : 'text-neutral-500'));
            }

            // Update row styling
            const row = slider.closest('.slider-row');
            if (row) {
                if (value === 0 && origValue === 0) {
                    row.classList.add('opacity-50');
                } else {
                    row.classList.remove('opacity-50');
                }
            }

            debounce(updateScorePreview, 100)();
        }

        // Adjust weight by step amount
        function adjustWeight(key, step) {
            const slider = document.querySelector(`input[data-key="${key}"]`);
            if (!slider) return;
            const newValue = Math.max(0, Math.min(100, parseInt(slider.value) + step));
            slider.value = newValue;
            onWeightChange(slider);
        }

        // Debounce helper
        let debounceTimer;
        function debounce(fn, delay) {
            return function() {
                clearTimeout(debounceTimer);
                debounceTimer = setTimeout(fn, delay);
            };
        }

        // Load photo metrics
        async function loadPhotoMetrics() {
            if (!currentPair) return;
            try {
                const paths = encodeURIComponent(`${currentPair.a},${currentPair.b}`);
                const response = await fetch(`/api/comparison/photo_metrics?paths=${paths}`);
                photoMetrics = await response.json();
                updateScorePreview();
            } catch (err) {
                console.error('Error loading metrics:', err);
            }
        }

        // Update score preview (client-side calculation)
        async function updateScorePreview() {
            if (!currentPair || Object.keys(photoMetrics).length === 0) return;

            const category = document.getElementById('category-filter').value || 'portrait';

            // Preview for Photo A
            try {
                const respA = await fetch('/api/comparison/preview_score', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({path: currentPair.a, weights: currentWeights})
                });
                const dataA = await respA.json();
                document.getElementById('preview-a-current').textContent = (photoMetrics[currentPair.a]?.aggregate || 0).toFixed(2);
                document.getElementById('preview-a-new').textContent = dataA.preview_score?.toFixed(2) || '-';
                const deltaA = dataA.delta || 0;
                document.getElementById('preview-a-delta').textContent = (deltaA >= 0 ? '+' : '') + deltaA.toFixed(2);
                document.getElementById('preview-a-delta').className = deltaA >= 0 ? 'text-green-400' : 'text-red-400';
            } catch (err) {
                console.error('Error previewing A:', err);
            }

            // Preview for Photo B
            try {
                const respB = await fetch('/api/comparison/preview_score', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({path: currentPair.b, weights: currentWeights})
                });
                const dataB = await respB.json();
                document.getElementById('preview-b-current').textContent = (photoMetrics[currentPair.b]?.aggregate || 0).toFixed(2);
                document.getElementById('preview-b-new').textContent = dataB.preview_score?.toFixed(2) || '-';
                const deltaB = dataB.delta || 0;
                document.getElementById('preview-b-delta').textContent = (deltaB >= 0 ? '+' : '') + deltaB.toFixed(2);
                document.getElementById('preview-b-delta').className = deltaB >= 0 ? 'text-green-400' : 'text-red-400';
            } catch (err) {
                console.error('Error previewing B:', err);
            }

            // Re-render sliders to update A/B values with new metrics
            renderWeightSliders();
        }

        // Reload metrics when pair changes
        const originalLoadNextPair = loadNextPair;
        loadNextPair = async function() {
            await originalLoadNextPair();
            // Always load metrics to display category badges
            if (currentPair) {
                await loadPhotoMetrics();
                // Update category display after metrics load
                document.getElementById('category-a').textContent = photoMetrics[currentPair.a]?.category || '-';
                document.getElementById('category-b').textContent = photoMetrics[currentPair.b]?.category || '-';
            }
        };

        // Category Override Modal State
        let currentOverridePhoto = null;  // 'a' or 'b'

        function openCategoryOverride(photo) {
            currentOverridePhoto = photo;
            const path = photo === 'a' ? currentPair.a : currentPair.b;
            const metrics = photoMetrics[path] || {};

            document.getElementById('modal-photo-name').textContent = path.split('/').pop();
            document.getElementById('modal-current-category').textContent = metrics.category || '-';
            document.getElementById('modal-target-category').value = metrics.category || 'others';

            // Reset analysis state
            document.getElementById('filter-analysis').classList.add('hidden');
            document.getElementById('no-conflicts').classList.add('hidden');
            document.getElementById('conflicts-section').classList.add('hidden');
            document.getElementById('suggestions-section').classList.add('hidden');

            document.getElementById('category-modal').classList.remove('hidden');
        }

        function closeCategoryModal() {
            document.getElementById('category-modal').classList.add('hidden');
            currentOverridePhoto = null;
        }

        async function analyzeFilterConflicts() {
            if (!currentOverridePhoto || !currentPair) return;

            const path = currentOverridePhoto === 'a' ? currentPair.a : currentPair.b;
            const targetCategory = document.getElementById('modal-target-category').value;

            try {
                const response = await fetch('/api/comparison/suggest_filters', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({path: path, target_category: targetCategory})
                });
                const data = await response.json();

                // Show analysis section
                document.getElementById('filter-analysis').classList.remove('hidden');

                // Handle no conflicts case
                if (data.no_conflicts || data.conflicts.length === 0) {
                    document.getElementById('no-conflicts').classList.remove('hidden');
                    document.getElementById('conflicts-section').classList.add('hidden');
                    document.getElementById('suggestions-section').classList.add('hidden');
                } else {
                    document.getElementById('no-conflicts').classList.add('hidden');

                    // Show conflicts
                    const conflictsHtml = data.conflicts.map(c => `
                        <div class="p-2 bg-red-900/30 border border-red-700 rounded">
                            <span class="text-red-400">${c.message}</span>
                        </div>
                    `).join('');
                    document.getElementById('conflicts-list').innerHTML = conflictsHtml;
                    document.getElementById('conflicts-section').classList.remove('hidden');

                    // Show suggestions
                    if (data.suggestions && data.suggestions.length > 0) {
                        const suggestionsHtml = data.suggestions.map(s => `
                            <div class="p-2 bg-yellow-900/30 border border-yellow-700 rounded flex items-start gap-2">
                                <svg class="w-4 h-4 text-yellow-400 mt-0.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
                                </svg>
                                <span class="text-yellow-200">${s.message}</span>
                            </div>
                        `).join('');
                        document.getElementById('suggestions-list').innerHTML = suggestionsHtml;
                        document.getElementById('suggestions-section').classList.remove('hidden');
                    } else {
                        document.getElementById('suggestions-section').classList.add('hidden');
                    }
                }

                // Show photo values
                const values = data.photo_values || {};
                const valuesHtml = Object.entries(values).map(([key, val]) => {
                    const displayVal = val === null ? '-' : (typeof val === 'boolean' ? (val ? 'Yes' : 'No') : val);
                    return `<div><span class="text-neutral-500">${key}:</span> <span class="text-white">${displayVal}</span></div>`;
                }).join('');
                document.getElementById('photo-values-grid').innerHTML = valuesHtml;

            } catch (err) {
                console.error('Error analyzing conflicts:', err);
                alert('Error analyzing filter conflicts');
            }
        }

        async function applyOverride() {
            if (!currentOverridePhoto || !currentPair) return;

            const path = currentOverridePhoto === 'a' ? currentPair.a : currentPair.b;
            const newCategory = document.getElementById('modal-target-category').value;

            try {
                const response = await fetch('/api/comparison/override_category', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({path: path, category: newCategory})
                });
                const data = await response.json();

                if (data.success) {
                    // Update the displayed category
                    const categoryEl = document.getElementById(`category-${currentOverridePhoto}`);
                    categoryEl.textContent = newCategory;

                    // Update photoMetrics cache
                    if (photoMetrics[path]) {
                        photoMetrics[path].category = newCategory;
                    }

                    closeCategoryModal();

                    // Show brief notification
                    const notification = document.createElement('div');
                    notification.className = 'fixed bottom-4 right-4 bg-green-600 text-white px-4 py-2 rounded shadow-lg z-50';
                    notification.textContent = `Category changed to ${newCategory}`;
                    document.body.appendChild(notification);
                    setTimeout(() => notification.remove(), 2000);
                } else {
                    alert(data.error || 'Failed to change category');
                }
            } catch (err) {
                console.error('Error applying override:', err);
                alert('Error applying category override');
            }
        }

        // Close modal on Escape key
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && !document.getElementById('category-modal').classList.contains('hidden')) {
                closeCategoryModal();
            }
        });

        // Initial load
        async function initPage() {
            await loadNextPair();
            // Weight panel is always visible, load weights for selected category
            loadCategoryWeights();
        }
        initPage();
    </script>
</body>
</html>
'''


@app.route('/compare')
def compare_page():
    """Comparison mode page for pairwise photo ranking."""
    if not is_edition_authenticated():
        return redirect('/')

    settings = get_comparison_mode_settings()
    min_comparisons = settings['min_comparisons_for_optimization']

    # Get current stats
    from comparison import ComparisonManager
    manager = ComparisonManager(DEFAULT_DB_PATH)
    stats = manager.get_statistics()

    progress_pct = min(100, (stats['total_comparisons'] / min_comparisons) * 100)

    # Get category list for filter dropdown
    from config import ScoringConfig
    config = ScoringConfig(validate=False)
    categories = config.get_all_category_names()

    # Get type parameter and map to category for auto-selection
    type_param = request.args.get('type', '')
    selected_category = TYPE_TO_CATEGORY.get(type_param, categories[0] if categories else 'portrait')
    if selected_category not in categories:
        selected_category = categories[0] if categories else 'portrait'

    return render_template_string(
        COMPARISON_TEMPLATE,
        stats=stats,
        min_comparisons=min_comparisons,
        progress_pct=progress_pct,
        strategy=settings['pair_selection_strategy'],
        show_scores=settings['show_current_scores'],
        categories=categories,
        selected_category=selected_category,
    )


@app.route('/api/comparison/next_pair')
def api_comparison_next_pair():
    """API endpoint to get the next pair of photos for comparison."""
    if not is_edition_authenticated():
        return jsonify({'error': 'Comparison mode is disabled'}), 403

    from comparison import PairSelector

    strategy = request.args.get('strategy', 'uncertainty')
    category = request.args.get('category', None)

    selector = PairSelector(DEFAULT_DB_PATH)
    pair = selector.get_next_pair(strategy=strategy, category=category)

    if not pair:
        return jsonify({'error': 'No more pairs available for comparison'})

    return jsonify(pair)


@app.route('/api/download')
def api_download_single():
    """Download a single photo file (validated against database).

    RAW files (CR2/CR3) are converted to full-resolution JPEG on-the-fly.
    """
    photo_path = request.args.get('path')
    if not photo_path:
        return jsonify({'error': 'path required'}), 400

    # Validate path exists in the database (prevents path traversal)
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT path FROM photos WHERE path = ?", (photo_path,)
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return jsonify({'error': 'File not found'}), 404

    # Map database path to local disk path
    disk_path = map_disk_path(photo_path)

    if not os.path.isfile(disk_path):
        return jsonify({'error': 'File not found on disk'}), 404

    # Convert RAW files to JPEG for download
    if disk_path.lower().endswith(('.cr2', '.cr3')):
        import rawpy
        from io import BytesIO
        from PIL import Image

        with rawpy.imread(disk_path) as raw:
            rgb = raw.postprocess(
                use_camera_wb=True,
                no_auto_bright=False,
                output_color=rawpy.ColorSpace.sRGB,
                output_bps=8
            )

        pil_img = Image.fromarray(rgb)
        buffer = BytesIO()
        pil_img.save(buffer, format='JPEG', quality=95)
        buffer.seek(0)

        download_name = os.path.splitext(os.path.basename(photo_path))[0] + '.jpg'

        return send_file(
            buffer,
            mimetype='image/jpeg',
            as_attachment=True,
            download_name=download_name
        )

    return send_file(
        disk_path,
        as_attachment=True,
        download_name=os.path.basename(disk_path)
    )


@app.route('/api/download-selected', methods=['POST'])
def api_download_selected():
    """Download selected photos as a ZIP archive."""
    data = request.get_json()
    paths = data.get('paths', [])
    if not paths:
        return jsonify({'error': 'No paths provided'}), 400

    # Validate all paths exist in the database
    conn = get_db_connection()
    try:
        placeholders = ','.join('?' for _ in paths)
        rows = conn.execute(
            f"SELECT path FROM photos WHERE path IN ({placeholders})", paths
        ).fetchall()
        valid_paths = {row[0] for row in rows}
    finally:
        conn.close()

    if not valid_paths:
        return jsonify({'error': 'No valid paths found'}), 404

    # Build ZIP in memory
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_STORED) as zf:
        for path in paths:
            if path not in valid_paths:
                continue
            disk_path = map_disk_path(path)
            if os.path.isfile(disk_path):
                zf.write(disk_path, os.path.basename(disk_path))

    buffer.seek(0)
    from datetime import datetime as _dt
    timestamp = _dt.now().strftime('%Y%m%d_%H%M%S')
    return send_file(
        buffer,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f'photos_{timestamp}.zip'
    )


@app.route('/api/comparison/submit', methods=['POST'])
def api_comparison_submit():
    """API endpoint to submit a comparison result."""
    if not is_edition_authenticated():
        return jsonify({'error': 'Comparison mode is disabled'}), 403

    from comparison import ComparisonManager

    data = request.get_json()
    photo_a = data.get('photo_a')
    photo_b = data.get('photo_b')
    winner = data.get('winner')
    category = data.get('category')

    if not photo_a or not photo_b or not winner:
        return jsonify({'error': 'Missing required fields'}), 400

    manager = ComparisonManager(DEFAULT_DB_PATH)
    success = manager.submit_comparison(photo_a, photo_b, winner, category)

    if success:
        stats = manager.get_statistics()
        return jsonify({'success': True, 'stats': stats})
    else:
        return jsonify({'error': 'Failed to save comparison'}), 500


@app.route('/api/comparison/reset', methods=['POST'])
def api_comparison_reset():
    """API endpoint to reset all comparison data."""
    if not is_edition_authenticated():
        return jsonify({'error': 'Comparison mode is disabled'}), 403

    try:
        with get_db_connection() as conn:
            conn.execute("DELETE FROM comparisons")
            conn.execute("DELETE FROM learned_scores")
            conn.execute("DELETE FROM weight_optimization_runs")
            conn.commit()
        return jsonify({'success': True, 'message': 'All comparison data has been reset'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/recalculate', methods=['POST'])
def api_recalculate():
    """API endpoint to recalculate all categories and aggregate scores.

    This runs the same logic as `python photos.py --recompute-average`:
    - Re-determines category for each photo based on current config
    - Recalculates aggregate scores using current weights
    - Updates burst processing

    Note: This runs synchronously and may take a while for large databases.
    """
    try:
        import subprocess
        import sys

        # Get config path from current config if available
        config_path = 'scoring_config.json'

        # Run recalculate as subprocess to avoid blocking
        # Using the same Python interpreter as the viewer
        result = subprocess.run(
            [sys.executable, 'photos.py', '--recompute-average', '--config', config_path],
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout
        )

        if result.returncode == 0:
            return jsonify({
                'success': True,
                'message': 'Recalculation complete',
                'output': result.stdout
            })
        else:
            return jsonify({
                'success': False,
                'error': f'Recalculation failed: {result.stderr or result.stdout}'
            }), 500

    except subprocess.TimeoutExpired:
        return jsonify({
            'success': False,
            'error': 'Recalculation timed out (>5 minutes). Run manually with: python photos.py --recompute-average'
        }), 500
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/config/update_weights', methods=['POST'])
def api_update_weights():
    """API endpoint to update category weights in scoring_config.json.

    Request body:
        {
            "category": "portrait",
            "weights": {
                "aesthetic_percent": 30,
                "face_quality_percent": 25,
                ...
            },
            "recalculate": true  // optional: trigger recalculation after saving
        }

    Returns success/error status.
    """
    try:
        import json
        from datetime import datetime

        data = request.get_json()
        category = data.get('category')
        weights = data.get('weights', {})
        should_recalculate = data.get('recalculate', False)

        if not category:
            return jsonify({'success': False, 'error': 'Missing category'}), 400

        if not weights:
            return jsonify({'success': False, 'error': 'Missing weights'}), 400

        config_path = 'scoring_config.json'

        # Read current config
        with open(config_path, 'r') as f:
            config = json.load(f)

        # Create backup
        backup_path = f"{config_path}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        with open(backup_path, 'w') as f:
            json.dump(config, f, indent=2)

        # Update weights in v4 config format (categories is a list)
        categories = config.get('categories', [])
        found = False
        for cat in categories:
            if cat.get('name') == category:
                # Update weights in the category
                if 'weights' not in cat:
                    cat['weights'] = {}
                cat['weights'].update(weights)
                found = True
                break
        if not found:
            return jsonify({'success': False, 'error': f'Category "{category}" not found in config'}), 404

        # Save updated config
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)

        result = {
            'success': True,
            'message': f'Weights updated for category "{category}"',
            'backup': backup_path
        }

        # Optionally trigger recalculation
        if should_recalculate:
            import subprocess
            import sys
            try:
                recalc_result = subprocess.run(
                    [sys.executable, 'photos.py', '--recompute-average', '--config', config_path],
                    capture_output=True,
                    text=True,
                    timeout=300
                )
                if recalc_result.returncode == 0:
                    result['recalculated'] = True
                    result['message'] += ' and scores recalculated'
                else:
                    result['recalculated'] = False
                    result['recalculate_error'] = recalc_result.stderr or recalc_result.stdout
            except subprocess.TimeoutExpired:
                result['recalculated'] = False
                result['recalculate_error'] = 'Recalculation timed out'

        return jsonify(result)

    except FileNotFoundError:
        return jsonify({'success': False, 'error': 'Config file not found'}), 404
    except json.JSONDecodeError as e:
        return jsonify({'success': False, 'error': f'Invalid JSON in config: {e}'}), 500
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/comparison/stats')
def api_comparison_stats():
    """API endpoint to get comparison statistics."""
    if not is_edition_authenticated():
        return jsonify({'error': 'Comparison mode is disabled'}), 403

    from comparison import ComparisonManager
    manager = ComparisonManager(DEFAULT_DB_PATH)
    stats = manager.get_statistics()
    return jsonify(stats)


@app.route('/api/comparison/photo_metrics')
def api_comparison_photo_metrics():
    """API endpoint to get raw metrics for photos (for client-side score preview).

    Query params:
        paths: Comma-separated list of photo paths (max 2)

    Returns:
        Dict mapping path to metrics dict with all scoring columns
    """
    paths_param = request.args.get('paths', '')
    if not paths_param:
        return jsonify({'error': 'Missing paths parameter'}), 400

    paths = [p.strip() for p in paths_param.split(',') if p.strip()]
    if len(paths) > 2:
        return jsonify({'error': 'Maximum 2 paths allowed'}), 400

    # Columns needed for score calculation
    metric_columns = [
        'path', 'category', 'aggregate',
        'aesthetic', 'face_quality', 'eye_sharpness', 'tech_sharpness',
        'color_score', 'exposure_score', 'comp_score', 'isolation_bonus',
        'quality_score', 'contrast_score', 'dynamic_range_stops',
        'noise_sigma', 'histogram_bimodality', 'mean_saturation',
        'is_blink', 'is_silhouette', 'face_ratio', 'face_count',
        'scoring_model', 'tags', 'is_monochrome', 'leading_lines_score',
        'power_point_score', 'histogram_spread', 'mean_luminance'
    ]

    with get_connection(DEFAULT_DB_PATH) as conn:
        placeholders = ','.join(['?' for _ in paths])
        cols = ', '.join(metric_columns)
        query = f"SELECT {cols} FROM photos WHERE path IN ({placeholders})"
        rows = conn.execute(query, paths).fetchall()

    result = {}
    for row in rows:
        row_dict = dict(row)
        path = row_dict['path']
        result[path] = row_dict

    return jsonify(result)


@app.route('/api/comparison/category_weights')
def api_comparison_category_weights():
    """API endpoint to get weights for a category (or all categories).

    Query params:
        category: Optional category name. If omitted, returns all categories.

    Returns:
        Dict with category weights as percentages (for UI sliders)
    """
    from config import ScoringConfig

    category = request.args.get('category')
    config = ScoringConfig(validate=False)

    if category:
        # Return weights for specific category
        for cat in config.get_categories():
            if cat['name'] == category:
                return jsonify({
                    'category': category,
                    'weights': cat.get('weights', {}),
                    'modifiers': cat.get('modifiers', {}),
                    'filters': cat.get('filters', {}),
                    'priority': cat.get('priority', 100)
                })
        return jsonify({'error': f'Category not found: {category}'}), 404
    else:
        # Return all categories with their weights
        categories = []
        for cat in config.get_categories():
            categories.append({
                'name': cat['name'],
                'priority': cat.get('priority', 100),
                'weights': cat.get('weights', {}),
                'modifiers': cat.get('modifiers', {}),
                'filters': cat.get('filters', {})
            })
        return jsonify({'categories': categories})


@app.route('/api/comparison/learned_weights')
def api_comparison_learned_weights():
    """API endpoint to get suggested weights based on comparison outcomes.

    Uses Direct Preference Optimization to maximize comparison prediction accuracy.

    Query params:
        category: Optional category name
        include_ties: Include tie comparisons (default: true)
        use_cv: Use cross-validation for robustness (default: false)

    Returns:
        Dict with current_weights, suggested_weights, accuracy metrics, etc.
    """
    if not is_edition_authenticated():
        return jsonify({'error': 'Comparison mode is disabled'}), 403

    category = request.args.get('category')
    include_ties = request.args.get('include_ties', 'true').lower() == 'true'
    use_cv = request.args.get('use_cv', 'false').lower() == 'true'

    from optimization import WeightOptimizer

    optimizer = WeightOptimizer(DEFAULT_DB_PATH)

    # Check if we have enough comparisons (lower threshold with direct optimization)
    with get_connection(DEFAULT_DB_PATH) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM comparisons WHERE winner IN ('a', 'b', 'tie')"
        ).fetchone()[0]

    settings = get_comparison_mode_settings()
    # Direct optimization needs fewer comparisons (30 vs 50)
    min_comparisons = settings.get('min_comparisons_for_optimization', 30)

    if count < min_comparisons:
        return jsonify({
            'available': False,
            'message': f'Need at least {min_comparisons} comparisons (have {count})',
            'comparisons': count,
            'min_required': min_comparisons
        })

    # Use new direct preference optimization
    try:
        if use_cv:
            result = optimizer.optimize_weights_with_cv(
                category=category,
                min_comparisons=min_comparisons,
                include_ties=include_ties
            )
        else:
            result = optimizer.optimize_weights_direct(
                category=category,
                min_comparisons=min_comparisons,
                include_ties=include_ties
            )

        if 'error' in result:
            return jsonify({
                'available': False,
                'message': result['error'],
                'comparisons': count
            })

        # Map optimizer column names to config weight names
        name_mapping = {
            # Primary quality
            'aesthetic': 'aesthetic',
            'quality_score': 'quality',
            'face_quality': 'face_quality',
            'face_sharpness': 'face_sharpness',
            'eye_sharpness': 'eye_sharpness',
            'tech_sharpness': 'tech_sharpness',
            # Composition
            'comp_score': 'composition',
            'power_point_score': 'power_point',
            'leading_lines_score': 'leading_lines',
            # Technical
            'exposure_score': 'exposure',
            'color_score': 'color',
            'contrast_score': 'contrast',
            'dynamic_range_stops': 'dynamic_range',
            'mean_saturation': 'saturation',
            'noise_sigma': 'noise',
            # Bonuses
            'isolation_bonus': 'isolation',
        }

        # All scoring components (for showing all in UI, even if 0)
        all_components = list(name_mapping.keys())

        # Convert weights to percent format for UI with correct names
        current_weights = {}
        suggested_weights = {}

        # Include ALL components, defaulting to 0 if not present
        for db_key in all_components:
            mapped_key = name_mapping.get(db_key, db_key)
            current_val = result.get('old_weights', {}).get(db_key, 0.0)
            suggested_val = result.get('new_weights', {}).get(db_key, 0.0)
            current_weights[f'{mapped_key}_percent'] = round(current_val * 100)
            suggested_weights[f'{mapped_key}_percent'] = round(suggested_val * 100)

        # Count mispredicted comparisons for display
        per_comparison = result.get('per_comparison', [])
        mispredicted = [c for c in per_comparison if not c.get('predicted_correct', True)]

        response = {
            'available': True,
            'current_weights': current_weights,
            'suggested_weights': suggested_weights,
            'accuracy_before': result.get('accuracy_before', 0),
            'accuracy_after': result.get('accuracy_after', 0),
            'improvement': result.get('improvement', 0),
            'suggest_changes': result.get('suggest_changes', False),
            'comparisons_used': result.get('comparisons_used', 0),
            'ties_included': result.get('ties_included', 0),
            'mispredicted_count': len(mispredicted),
            'category': category,
            'method': result.get('method', 'direct_preference_optimization'),
        }

        # Add CV-specific metrics if available
        if use_cv:
            response['cv_accuracy'] = result.get('cv_accuracy', 0)
            response['cv_std'] = result.get('cv_std', 0)
            response['fold_results'] = result.get('fold_results', [])

        return jsonify(response)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'available': False,
            'message': f'Optimization error: {str(e)}',
            'comparisons': count
        })


@app.route('/api/comparison/preview_score', methods=['POST'])
def api_comparison_preview_score():
    """API endpoint to preview score with custom weights.

    Request body:
        path: Photo path
        weights: Dict of weight overrides (as percentages, e.g., {"aesthetic_percent": 40})

    Returns:
        Dict with original and preview scores
    """
    from config import ScoringConfig
    from processing.scorer import Facet

    data = request.get_json()
    path = data.get('path')
    custom_weights = data.get('weights', {})

    if not path:
        return jsonify({'error': 'Missing path parameter'}), 400

    # Get photo metrics
    with get_connection(DEFAULT_DB_PATH) as conn:
        row = conn.execute("SELECT * FROM photos WHERE path = ?", (path,)).fetchone()

    if not row:
        return jsonify({'error': 'Photo not found'}), 404

    metrics = dict(row)
    original_score = metrics.get('aggregate', 0)
    category = metrics.get('category', 'others')

    # Create scorer with custom weights for preview
    # We'll calculate using the standard logic but with modified weights
    config = ScoringConfig(validate=False)

    # Build photo_data for determine_category
    photo_data = {
        'tags': metrics.get('tags', '') or '',
        'face_count': metrics.get('face_count', 0) or 0,
        'face_ratio': metrics.get('face_ratio', 0) or 0,
        'is_silhouette': metrics.get('is_silhouette', 0),
        'is_group_portrait': metrics.get('is_group_portrait', 0),
        'is_monochrome': metrics.get('is_monochrome', 0),
        'mean_luminance': metrics.get('mean_luminance', 0.5),
    }

    # Calculate preview score using simplified weighted sum
    weights = config.get_weights(category)

    # Override with custom weights (convert from percent to decimal)
    for key, value in custom_weights.items():
        if key.endswith('_percent'):
            base_key = key[:-8]
            weights[base_key] = value / 100
        else:
            weights[base_key if key.endswith('_percent') else key] = value / 100

    # Simple weighted sum calculation
    preview_score = 0.0
    weight_map = {
        'aesthetic': 'aesthetic',
        'face_quality': 'face_quality',
        'eye_sharpness': 'eye_sharpness',
        'tech_sharpness': 'tech_sharpness',
        'exposure': 'exposure_score',
        'composition': 'comp_score',
        'color': 'color_score',
        'contrast': 'contrast_score',
        'quality': 'quality_score',
        'dynamic_range': 'dynamic_range_stops',
        'isolation': 'isolation_bonus',
        'leading_lines': 'leading_lines_score',
    }

    for weight_key, metric_key in weight_map.items():
        weight = weights.get(weight_key, 0)
        if weight > 0:
            value = metrics.get(metric_key) or 0
            # Special handling for isolation_bonus (scale 1-3 to 0-10)
            if metric_key == 'isolation_bonus' and value:
                value = min(10, (value - 1) * 5)
            # Special handling for dynamic_range (scale to 0-10)
            if metric_key == 'dynamic_range_stops' and value:
                value = min(10, value / 0.6)  # Assuming 6 stops = 10
            preview_score += value * weight

    # Add bonus if present
    bonus = weights.get('bonus', 0)
    preview_score = min(10, preview_score + bonus)

    return jsonify({
        'path': path,
        'category': category,
        'original_score': original_score,
        'preview_score': round(preview_score, 2),
        'delta': round(preview_score - (original_score or 0), 2)
    })


@app.route('/api/comparison/suggest_filters', methods=['POST'])
def api_comparison_suggest_filters():
    """API endpoint to suggest filter changes when moving a photo to another category.

    When a user wants to re-categorize a photo during comparison, this endpoint
    analyzes why the photo doesn't match the target category and suggests filter
    modifications that would make similar photos automatically categorized correctly.

    Request body:
        path: Photo path
        target_category: Category to move the photo to

    Returns:
        Dict with:
            - current_category: Current category of the photo
            - target_category: Requested target category
            - conflicts: List of filter conflicts (why it doesn't match)
            - suggestions: List of suggested filter changes
            - photo_values: Actual metric values for the photo
    """
    from config import ScoringConfig, CategoryFilter

    data = request.get_json()
    path = data.get('path')
    target_category = data.get('target_category')

    if not path or not target_category:
        return jsonify({'error': 'Missing path or target_category'}), 400

    # Get photo metrics
    with get_connection(DEFAULT_DB_PATH) as conn:
        row = conn.execute("SELECT * FROM photos WHERE path = ?", (path,)).fetchone()

    if not row:
        return jsonify({'error': 'Photo not found'}), 404

    metrics = dict(row)
    current_category = metrics.get('category', 'others')

    if current_category == target_category:
        return jsonify({
            'current_category': current_category,
            'target_category': target_category,
            'conflicts': [],
            'suggestions': [],
            'message': 'Photo is already in the target category'
        })

    config = ScoringConfig(validate=False)

    # Build photo_data dict for filter evaluation
    photo_data = {
        'tags': metrics.get('tags', '') or '',
        'face_count': metrics.get('face_count', 0) or 0,
        'face_ratio': metrics.get('face_ratio', 0) or 0,
        'is_silhouette': metrics.get('is_silhouette', 0),
        'is_group_portrait': metrics.get('is_group_portrait', 0),
        'is_monochrome': metrics.get('is_monochrome', 0),
        'mean_luminance': metrics.get('mean_luminance', 0.5),
        'iso': metrics.get('ISO'),
        'shutter_speed': metrics.get('shutter_speed'),
        'focal_length': metrics.get('focal_length'),
        'f_stop': metrics.get('f_stop'),
    }

    # Get target category config
    target_config = None
    for cat in config.get_categories():
        if cat['name'] == target_category:
            target_config = cat
            break

    if not target_config:
        return jsonify({'error': f'Category not found: {target_category}'}), 404

    # Analyze conflicts between photo values and target category filters
    target_filters = target_config.get('filters', {})
    conflicts = []
    suggestions = []

    # Numeric filter analysis
    numeric_mappings = {
        'face_ratio': ('face_ratio', 'Face ratio'),
        'face_count': ('face_count', 'Face count'),
        'iso': ('iso', 'ISO'),
        'shutter_speed': ('shutter_speed', 'Shutter speed'),
        'luminance': ('mean_luminance', 'Luminance'),
        'focal_length': ('focal_length', 'Focal length'),
        'f_stop': ('f_stop', 'F-stop'),
    }

    for filter_key, (data_key, label) in numeric_mappings.items():
        min_val = target_filters.get(f'{filter_key}_min')
        max_val = target_filters.get(f'{filter_key}_max')
        actual = photo_data.get(data_key)

        if min_val is not None:
            if actual is None:
                conflicts.append({
                    'type': 'missing_value',
                    'filter': f'{filter_key}_min',
                    'required': min_val,
                    'actual': None,
                    'message': f'{label} is required but missing'
                })
            elif actual < min_val:
                conflicts.append({
                    'type': 'below_minimum',
                    'filter': f'{filter_key}_min',
                    'required': min_val,
                    'actual': actual,
                    'message': f'{label} ({actual:.3f}) is below minimum ({min_val})'
                })
                suggestions.append({
                    'type': 'lower_minimum',
                    'filter': f'{filter_key}_min',
                    'current': min_val,
                    'suggested': round(actual * 0.9, 4),  # 10% margin
                    'message': f'Lower {filter_key}_min from {min_val} to {round(actual * 0.9, 4)}'
                })

        if max_val is not None:
            if actual is None:
                conflicts.append({
                    'type': 'missing_value',
                    'filter': f'{filter_key}_max',
                    'required': max_val,
                    'actual': None,
                    'message': f'{label} is required but missing'
                })
            elif actual > max_val:
                conflicts.append({
                    'type': 'above_maximum',
                    'filter': f'{filter_key}_max',
                    'required': max_val,
                    'actual': actual,
                    'message': f'{label} ({actual:.3f}) is above maximum ({max_val})'
                })
                suggestions.append({
                    'type': 'raise_maximum',
                    'filter': f'{filter_key}_max',
                    'current': max_val,
                    'suggested': round(actual * 1.1, 4),  # 10% margin
                    'message': f'Raise {filter_key}_max from {max_val} to {round(actual * 1.1, 4)}'
                })

    # Boolean filter analysis
    bool_mappings = {
        'has_face': ('Has face', lambda pd: (pd.get('face_count') or 0) > 0),
        'is_monochrome': ('Monochrome', lambda pd: bool(pd.get('is_monochrome', 0))),
        'is_silhouette': ('Silhouette', lambda pd: bool(pd.get('is_silhouette', 0))),
        'is_group_portrait': ('Group portrait', lambda pd: bool(pd.get('is_group_portrait', 0))),
    }

    for filter_key, (label, getter) in bool_mappings.items():
        required = target_filters.get(filter_key)
        if required is not None:
            actual = getter(photo_data)
            if actual != required:
                conflicts.append({
                    'type': 'boolean_mismatch',
                    'filter': filter_key,
                    'required': required,
                    'actual': actual,
                    'message': f'{label} is {actual}, but category requires {required}'
                })
                suggestions.append({
                    'type': 'change_boolean',
                    'filter': filter_key,
                    'current': required,
                    'suggested': actual,
                    'message': f'Change {filter_key} from {required} to {actual}'
                })

    # Tag filter analysis
    required_tags = target_filters.get('required_tags', [])
    excluded_tags = target_filters.get('excluded_tags', [])
    match_mode = target_filters.get('tag_match_mode', 'any')

    if required_tags:
        tags_str = photo_data.get('tags') or ''
        photo_tags = [t.strip().lower() for t in tags_str.split(',') if t.strip()]
        required_lower = [t.lower() for t in required_tags]

        if match_mode == 'any':
            if not any(tag in photo_tags for tag in required_lower):
                conflicts.append({
                    'type': 'missing_tags',
                    'filter': 'required_tags',
                    'required': required_tags,
                    'actual': photo_tags,
                    'message': f'Photo needs at least one of: {", ".join(required_tags)}'
                })
                suggestions.append({
                    'type': 'remove_tag_requirement',
                    'filter': 'required_tags',
                    'message': 'Remove or modify required_tags filter'
                })
        else:  # all
            missing = [t for t in required_lower if t not in photo_tags]
            if missing:
                conflicts.append({
                    'type': 'missing_tags',
                    'filter': 'required_tags',
                    'required': required_tags,
                    'actual': photo_tags,
                    'missing': missing,
                    'message': f'Photo is missing required tags: {", ".join(missing)}'
                })

    if excluded_tags:
        tags_str = photo_data.get('tags') or ''
        photo_tags = [t.strip().lower() for t in tags_str.split(',') if t.strip()]
        excluded_lower = [t.lower() for t in excluded_tags]
        found_excluded = [t for t in excluded_lower if t in photo_tags]

        if found_excluded:
            conflicts.append({
                'type': 'excluded_tags_present',
                'filter': 'excluded_tags',
                'excluded': excluded_tags,
                'found': found_excluded,
                'message': f'Photo has excluded tags: {", ".join(found_excluded)}'
            })
            suggestions.append({
                'type': 'modify_excluded_tags',
                'filter': 'excluded_tags',
                'current': excluded_tags,
                'to_remove': found_excluded,
                'message': f'Remove from excluded_tags: {", ".join(found_excluded)}'
            })

    # Format photo values for display
    photo_values = {
        'face_ratio': round(photo_data.get('face_ratio', 0), 4),
        'face_count': photo_data.get('face_count', 0),
        'is_monochrome': bool(photo_data.get('is_monochrome', 0)),
        'is_silhouette': bool(photo_data.get('is_silhouette', 0)),
        'is_group_portrait': bool(photo_data.get('is_group_portrait', 0)),
        'mean_luminance': round(photo_data.get('mean_luminance', 0), 4),
        'iso': photo_data.get('iso'),
        'shutter_speed': photo_data.get('shutter_speed'),
        'focal_length': photo_data.get('focal_length'),
        'f_stop': photo_data.get('f_stop'),
        'tags': photo_data.get('tags', ''),
    }

    return jsonify({
        'current_category': current_category,
        'target_category': target_category,
        'target_filters': target_filters,
        'conflicts': conflicts,
        'suggestions': suggestions,
        'photo_values': photo_values,
        'no_conflicts': len(conflicts) == 0
    })


@app.route('/api/comparison/override_category', methods=['POST'])
def api_comparison_override_category():
    """API endpoint to manually override a photo's category.

    This stores the category override for learning purposes.

    Request body:
        path: Photo path
        category: New category to assign

    Returns:
        Dict with success status and updated category
    """
    data = request.get_json()
    path = data.get('path')
    category = data.get('category')

    if not path or not category:
        return jsonify({'error': 'Missing path or category'}), 400

    # Verify photo exists
    with get_connection(DEFAULT_DB_PATH) as conn:
        row = conn.execute("SELECT category FROM photos WHERE path = ?", (path,)).fetchone()
        if not row:
            return jsonify({'error': 'Photo not found'}), 404

        old_category = row[0]

        # Update the category
        conn.execute("UPDATE photos SET category = ? WHERE path = ?", (category, path))
        conn.commit()

    return jsonify({
        'success': True,
        'path': path,
        'old_category': old_category,
        'new_category': category
    })


@app.route('/api/comparison/history')
def api_comparison_history():
    """API endpoint to get paginated comparison history with filters.

    Query params:
        limit: Max results (default 50)
        offset: Skip results (default 0)
        category: Filter by category
        winner: Filter by winner ('a', 'b', 'tie', 'skip')
        start_date: Filter by start date (ISO format)
        end_date: Filter by end date (ISO format)

    Returns:
        Dict with comparisons, total, has_more
    """
    if not is_edition_authenticated():
        return jsonify({'error': 'Comparison mode is disabled'}), 403

    from comparison import ComparisonManager

    manager = ComparisonManager(DEFAULT_DB_PATH)

    try:
        result = manager.get_comparison_history_filtered(
            limit=int(request.args.get('limit', 50)),
            offset=int(request.args.get('offset', 0)),
            category=request.args.get('category'),
            winner=request.args.get('winner'),
            start_date=request.args.get('start_date'),
            end_date=request.args.get('end_date'),
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/comparison/edit', methods=['POST'])
def api_comparison_edit():
    """API endpoint to edit a past comparison.

    Request body:
        id: Comparison ID
        winner: New winner value ('a', 'b', 'tie', 'skip')

    Returns:
        Dict with success status
    """
    if not is_edition_authenticated():
        return jsonify({'error': 'Comparison mode is disabled'}), 403

    from comparison import ComparisonManager

    data = request.get_json()
    comparison_id = data.get('id')
    new_winner = data.get('winner')

    if not comparison_id or not new_winner:
        return jsonify({'error': 'Missing id or winner'}), 400

    manager = ComparisonManager(DEFAULT_DB_PATH)

    try:
        success = manager.edit_comparison(int(comparison_id), new_winner)
        if success:
            return jsonify({'success': True})
        else:
            return jsonify({'error': 'Comparison not found'}), 404
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/comparison/delete', methods=['POST'])
def api_comparison_delete():
    """API endpoint to delete a comparison.

    Request body:
        id: Comparison ID

    Returns:
        Dict with success status
    """
    if not is_edition_authenticated():
        return jsonify({'error': 'Comparison mode is disabled'}), 403

    from comparison import ComparisonManager

    data = request.get_json()
    comparison_id = data.get('id')

    if not comparison_id:
        return jsonify({'error': 'Missing id'}), 400

    manager = ComparisonManager(DEFAULT_DB_PATH)

    try:
        success = manager.delete_comparison(int(comparison_id))
        if success:
            return jsonify({'success': True})
        else:
            return jsonify({'error': 'Comparison not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/comparison/coverage')
def api_comparison_coverage():
    """API endpoint to get comparison coverage statistics.

    Shows score distribution coverage and optimization readiness.

    Query params:
        category: Optional category filter

    Returns:
        Dict with coverage metrics and recommendations
    """
    if not is_edition_authenticated():
        return jsonify({'error': 'Comparison mode is disabled'}), 403

    from comparison import ComparisonManager

    manager = ComparisonManager(DEFAULT_DB_PATH)
    category = request.args.get('category')

    try:
        result = manager.get_comparison_coverage(category=category)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/comparison/confidence')
def api_comparison_confidence():
    """API endpoint to get bootstrap confidence intervals for weights.

    Query params:
        category: Optional category filter
        n_bootstrap: Number of bootstrap samples (default 100)

    Returns:
        Dict with weight confidence intervals
    """
    if not is_edition_authenticated():
        return jsonify({'error': 'Comparison mode is disabled'}), 403

    from optimization import WeightOptimizer

    optimizer = WeightOptimizer(DEFAULT_DB_PATH)
    category = request.args.get('category')
    n_bootstrap = int(request.args.get('n_bootstrap', 100))

    try:
        result = optimizer.compute_weight_confidence(
            category=category,
            n_bootstrap=n_bootstrap
        )

        if 'error' in result:
            return jsonify({
                'available': False,
                'message': result['error']
            })

        # Map names for UI
        name_mapping = {
            # Primary quality
            'aesthetic': 'aesthetic',
            'quality_score': 'quality',
            'face_quality': 'face_quality',
            'face_sharpness': 'face_sharpness',
            'eye_sharpness': 'eye_sharpness',
            'tech_sharpness': 'tech_sharpness',
            # Composition
            'comp_score': 'composition',
            'power_point_score': 'power_point',
            'leading_lines_score': 'leading_lines',
            # Technical
            'exposure_score': 'exposure',
            'color_score': 'color',
            'contrast_score': 'contrast',
            'dynamic_range_stops': 'dynamic_range',
            'mean_saturation': 'saturation',
            'noise_sigma': 'noise',
            # Bonuses
            'isolation_bonus': 'isolation',
        }

        # Convert to UI format
        weights_ui = {}
        lower_ui = {}
        upper_ui = {}
        ci_ui = {}

        for db_key, mapped_key in name_mapping.items():
            ui_key = f'{mapped_key}_percent'
            weights_ui[ui_key] = round(result['weights'].get(db_key, 0) * 100)
            lower_ui[ui_key] = round(result['lower_bounds'].get(db_key, 0) * 100)
            upper_ui[ui_key] = round(result['upper_bounds'].get(db_key, 0) * 100)
            ci_ui[ui_key] = round(result['confidence_intervals'].get(db_key, 0) * 100)

        return jsonify({
            'available': True,
            'weights': weights_ui,
            'lower_bounds': lower_ui,
            'upper_bounds': upper_ui,
            'confidence_intervals': ci_ui,
            'stable_components': result.get('stable_components', []),
            'n_bootstrap': result.get('n_bootstrap', 0),
            'comparisons_used': result.get('comparisons_used', 0),
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/weight_snapshots')
def api_weight_snapshots():
    """API endpoint to list weight configuration snapshots.

    Query params:
        category: Optional category filter
        limit: Max results (default 20)

    Returns:
        List of snapshots with metadata
    """
    category = request.args.get('category')
    limit = int(request.args.get('limit', 20))

    try:
        with get_connection(DEFAULT_DB_PATH) as conn:
            if category:
                cursor = conn.execute("""
                    SELECT * FROM weight_config_snapshots
                    WHERE category = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (category, limit))
            else:
                cursor = conn.execute("""
                    SELECT * FROM weight_config_snapshots
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (limit,))

            snapshots = []
            for row in cursor:
                snapshot = dict(row)
                # Parse weights JSON
                import json
                if snapshot.get('weights'):
                    snapshot['weights'] = json.loads(snapshot['weights'])
                snapshots.append(snapshot)

            return jsonify({'snapshots': snapshots})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/save_snapshot', methods=['POST'])
def api_save_weight_snapshot():
    """API endpoint to save current weights as a snapshot.

    Request body:
        category: Category to snapshot
        description: Optional description
        accuracy_before: Optional accuracy metric
        accuracy_after: Optional accuracy metric after applying

    Returns:
        Dict with snapshot ID
    """
    import json as json_module
    from config import ScoringConfig

    data = request.get_json()
    category = data.get('category', 'others')
    description = data.get('description', '')
    accuracy_before = data.get('accuracy_before')
    accuracy_after = data.get('accuracy_after')
    comparisons_used = data.get('comparisons_used')
    created_by = data.get('created_by', 'manual')

    try:
        # Get current weights
        config = ScoringConfig(validate=False)
        weights = config.get_weights(category)

        with get_connection(DEFAULT_DB_PATH, row_factory=False) as conn:
            cursor = conn.execute("""
                INSERT INTO weight_config_snapshots
                (category, weights, description, accuracy_before, accuracy_after,
                 comparisons_used, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                category,
                json_module.dumps(weights),
                description,
                accuracy_before,
                accuracy_after,
                comparisons_used,
                created_by
            ))
            conn.commit()
            snapshot_id = cursor.lastrowid

        return jsonify({'success': True, 'snapshot_id': snapshot_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/restore_weights', methods=['POST'])
def api_restore_weights():
    """API endpoint to restore weights from a snapshot.

    Request body:
        snapshot_id: ID of snapshot to restore

    Returns:
        Dict with success status and restored weights
    """
    import json as json_module
    import shutil
    from datetime import datetime

    data = request.get_json()
    snapshot_id = data.get('snapshot_id')

    if not snapshot_id:
        return jsonify({'error': 'Missing snapshot_id'}), 400

    try:
        # Get snapshot
        with get_connection(DEFAULT_DB_PATH) as conn:
            row = conn.execute("""
                SELECT * FROM weight_config_snapshots WHERE id = ?
            """, (snapshot_id,)).fetchone()

            if not row:
                return jsonify({'error': 'Snapshot not found'}), 404

            snapshot = dict(row)
            weights = json_module.loads(snapshot['weights'])
            category = snapshot['category']

        # Load and update config
        config_path = 'scoring_config.json'

        # Create backup first
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = f"{config_path}.backup.{timestamp}"
        shutil.copy2(config_path, backup_path)

        with open(config_path) as f:
            config = json_module.load(f)

        # Update weights in v4 config format
        categories = config.get('categories', [])
        found = False
        for cat in categories:
            if cat.get('name') == category:
                cat['weights'] = weights
                found = True
                break

        if not found:
            return jsonify({'error': f'Category "{category}" not found in config'}), 404

        with open(config_path, 'w') as f:
            json_module.dump(config, f, indent=2)

        return jsonify({
            'success': True,
            'restored_weights': weights,
            'category': category,
            'backup_path': backup_path
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# --- STATS DASHBOARD ---

STATS_TEMPLATE = r'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ _('stats.title') }} - Facet</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
    <style>
        body { background: #0a0a0a; }
        .tab-btn { border-bottom: 2px solid transparent; }
        .tab-btn.active { border-bottom-color: #22c55e; color: #22c55e; }
        .chart-card { background: #171717; border: 1px solid #262626; border-radius: 0.5rem; padding: 1rem; }
        .loading-spinner { display: inline-block; width: 1.5rem; height: 1.5rem; border: 2px solid #404040; border-top-color: #22c55e; border-radius: 50%; animation: spin 0.8s linear infinite; }
        @keyframes spin { to { transform: rotate(360deg); } }
    </style>
</head>
<body class="text-neutral-200 min-h-screen">
    <!-- Header -->
    <header class="bg-neutral-900 border-b border-neutral-800 px-4 py-3 flex items-center gap-4">
        <a href="/" class="text-neutral-400 hover:text-white">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"/>
            </svg>
        </a>
        <h1 class="text-lg font-semibold">{{ _('stats.title') }}</h1>
    </header>

    <!-- Tabs -->
    <nav class="bg-neutral-900 border-b border-neutral-800 px-4 flex gap-1">
        <button class="tab-btn active px-4 py-3 text-sm font-medium text-neutral-400 hover:text-white transition-colors" data-tab="gear">{{ _('stats.tabs.gear') }}</button>
        <button class="tab-btn px-4 py-3 text-sm font-medium text-neutral-400 hover:text-white transition-colors" data-tab="settings">{{ _('stats.tabs.settings') }}</button>
        <button class="tab-btn px-4 py-3 text-sm font-medium text-neutral-400 hover:text-white transition-colors" data-tab="timeline">{{ _('stats.tabs.timeline') }}</button>
        <button class="tab-btn px-4 py-3 text-sm font-medium text-neutral-400 hover:text-white transition-colors" data-tab="correlations">{{ _('stats.tabs.correlations') }}</button>
    </nav>

    <!-- Tab Panels -->
    <main class="p-4 mx-auto">
        <!-- Gear Tab -->
        <div id="panel-gear" class="tab-panel">
            <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <div class="chart-card"><h3 class="text-sm font-medium text-neutral-300 mb-3" id="title-cameras"></h3><canvas id="chart-cameras"></canvas></div>
                <div class="chart-card"><h3 class="text-sm font-medium text-neutral-300 mb-3" id="title-lenses"></h3><canvas id="chart-lenses"></canvas></div>
                <div class="chart-card"><h3 class="text-sm font-medium text-neutral-300 mb-3" id="title-combos"></h3><canvas id="chart-combos"></canvas></div>
                <div class="chart-card"><h3 class="text-sm font-medium text-neutral-300 mb-3" id="title-categories"></h3><canvas id="chart-categories"></canvas></div>
            </div>
        </div>

        <!-- Settings Tab -->
        <div id="panel-settings" class="tab-panel hidden">
            <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <div class="chart-card"><h3 class="text-sm font-medium text-neutral-300 mb-3" id="title-iso"></h3><canvas id="chart-iso"></canvas></div>
                <div class="chart-card"><h3 class="text-sm font-medium text-neutral-300 mb-3" id="title-aperture"></h3><canvas id="chart-aperture"></canvas></div>
                <div class="chart-card"><h3 class="text-sm font-medium text-neutral-300 mb-3" id="title-focal"></h3><canvas id="chart-focal"></canvas></div>
                <div class="chart-card"><h3 class="text-sm font-medium text-neutral-300 mb-3" id="title-shutter"></h3><canvas id="chart-shutter"></canvas></div>
                <div class="chart-card lg:col-span-2"><h3 class="text-sm font-medium text-neutral-300 mb-3" id="title-score-dist"></h3><canvas id="chart-score-dist"></canvas></div>
            </div>
        </div>

        <!-- Timeline Tab -->
        <div id="panel-timeline" class="tab-panel hidden">
            <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <div class="chart-card lg:col-span-2"><h3 class="text-sm font-medium text-neutral-300 mb-3" id="title-monthly"></h3><canvas id="chart-monthly"></canvas></div>
                <div class="chart-card"><h3 class="text-sm font-medium text-neutral-300 mb-3" id="title-yearly"></h3><canvas id="chart-yearly"></canvas></div>
                <div class="chart-card"><h3 class="text-sm font-medium text-neutral-300 mb-3" id="title-heatmap"></h3><canvas id="chart-heatmap"></canvas></div>
                <div class="chart-card"><h3 class="text-sm font-medium text-neutral-300 mb-3" id="title-top-days"></h3><canvas id="chart-top-days"></canvas></div>
            </div>
        </div>

        <!-- Correlations Tab -->
        <div id="panel-correlations" class="tab-panel hidden">
            <!-- Controls -->
            <div class="chart-card mb-4">
                <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 mb-4">
                    <div>
                        <label class="block text-xs text-neutral-400 mb-1">{{ _('stats.correlations.x_axis') }}</label>
                        <select id="corr-x" class="w-full bg-neutral-800 border border-neutral-700 text-neutral-200 rounded px-2 py-1.5 text-sm">
                            {% for key in ['iso','f_stop','focal_length','camera_model','lens_model','date_month','date_year','composition_pattern','category','aggregate','aesthetic','tech_sharpness','comp_score','face_quality','color_score','exposure_score'] %}
                            <option value="{{ key }}">{{ _('stats.correlations.dimensions.' + key) }}</option>
                            {% endfor %}
                        </select>
                    </div>
                    <div>
                        <label class="block text-xs text-neutral-400 mb-1">{{ _('stats.correlations.group_by') }}</label>
                        <select id="corr-group" class="w-full bg-neutral-800 border border-neutral-700 text-neutral-200 rounded px-2 py-1.5 text-sm">
                            <option value="">{{ _('stats.correlations.none') }}</option>
                            {% for key in ['iso','f_stop','focal_length','camera_model','lens_model','date_month','date_year','composition_pattern','category','aggregate','aesthetic','tech_sharpness','comp_score','face_quality','color_score','exposure_score'] %}
                            <option value="{{ key }}">{{ _('stats.correlations.dimensions.' + key) }}</option>
                            {% endfor %}
                        </select>
                    </div>
                    <div>
                        <label class="block text-xs text-neutral-400 mb-1">{{ _('stats.correlations.chart_type') }}</label>
                        <select id="corr-chart-type" class="w-full bg-neutral-800 border border-neutral-700 text-neutral-200 rounded px-2 py-1.5 text-sm">
                            <option value="line">{{ _('stats.correlations.chart_types.line') }}</option>
                            <option value="area">{{ _('stats.correlations.chart_types.area') }}</option>
                            <option value="bar">{{ _('stats.correlations.chart_types.bar') }}</option>
                            <option value="horizontalBar">{{ _('stats.correlations.chart_types.horizontalBar') }}</option>
                            <option value="radar">{{ _('stats.correlations.chart_types.radar') }}</option>
                            <option value="scatter">{{ _('stats.correlations.chart_types.scatter') }}</option>
                        </select>
                    </div>
                    <div>
                        <label class="block text-xs text-neutral-400 mb-1">{{ _('stats.correlations.min_samples') }}</label>
                        <input type="number" id="corr-min-samples" value="3" min="1" max="100"
                               class="w-full bg-neutral-800 border border-neutral-700 text-neutral-200 rounded px-2 py-1.5 text-sm">
                    </div>
                    <div>
                        <label class="block text-xs text-neutral-400 mb-1">{{ _('drawer.fields.from_date') }}</label>
                        <input type="date" id="corr-date-from"
                               class="w-full bg-neutral-800 border border-neutral-700 text-neutral-200 rounded px-2 py-1.5 text-sm">
                    </div>
                    <div>
                        <label class="block text-xs text-neutral-400 mb-1">{{ _('drawer.fields.to_date') }}</label>
                        <input type="date" id="corr-date-to"
                               class="w-full bg-neutral-800 border border-neutral-700 text-neutral-200 rounded px-2 py-1.5 text-sm">
                    </div>
                </div>
                <div>
                    <label class="block text-xs text-neutral-400 mb-2">{{ _('stats.correlations.y_metrics') }}</label>
                    <div id="corr-metrics-select" class="relative">
                        <div id="corr-metrics-trigger" class="w-full bg-neutral-800 border border-neutral-700 text-neutral-200 rounded px-2 py-1.5 text-sm cursor-pointer flex items-center justify-between min-h-[34px]">
                            <div id="corr-metrics-chips" class="flex flex-wrap gap-1 flex-1"></div>
                            <svg class="w-4 h-4 ml-2 shrink-0 text-neutral-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
                        </div>
                        <div id="corr-metrics-dropdown" class="hidden absolute z-50 mt-1 w-full bg-neutral-800 border border-neutral-700 rounded shadow-lg max-h-60 overflow-y-auto"></div>
                    </div>
                </div>
            </div>
            <!-- Chart -->
            <div class="chart-card" id="corr-chart-card" style="min-height:640px; display:flex; flex-direction:column;">
                <div id="corr-status" class="text-xs text-neutral-500 mb-2"></div>
                <div style="flex:1; position:relative; min-height:0;">
                    <canvas id="chart-correlations"></canvas>
                </div>
            </div>
        </div>

        <!-- Loading overlay -->
        <div id="loading-overlay" class="fixed inset-0 bg-black/50 flex items-center justify-center z-50 hidden">
            <div class="bg-neutral-900 rounded-lg p-6 flex items-center gap-3">
                <div class="loading-spinner"></div>
                <span id="loading-text"></span>
            </div>
        </div>
    </main>

    <script>
    const I18N = {{ js_translations(['stats']) | tojson | safe }};
    function t(key) {
        const parts = key.split('.');
        let val = I18N;
        for (const p of parts) { val = val && val[p]; }
        return val || key;
    }

    // Chart.js dark theme defaults
    Chart.defaults.color = '#a3a3a3';
    Chart.defaults.borderColor = '#262626';
    Chart.defaults.plugins.legend.labels.color = '#a3a3a3';

    const COLORS = ['#22c55e', '#3b82f6', '#a855f7', '#f59e0b', '#ef4444', '#06b6d4', '#ec4899', '#84cc16'];
    const tabsLoaded = {};
    const charts = {};

    // Tab switching
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-panel').forEach(p => p.classList.add('hidden'));
            btn.classList.add('active');
            const tab = btn.dataset.tab;
            document.getElementById('panel-' + tab).classList.remove('hidden');
            if (tab === 'correlations') {
                if (!tabsLoaded[tab]) { initCorrelationControls(); fetchCorrelations(); }
            } else if (!tabsLoaded[tab]) {
                loadTab(tab);
            }
        });
    });

    function showLoading(show) {
        document.getElementById('loading-overlay').classList.toggle('hidden', !show);
        document.getElementById('loading-text').textContent = t('stats.loading');
    }

    function makeChart(canvasId, config) {
        if (charts[canvasId]) charts[canvasId].destroy();
        const ctx = document.getElementById(canvasId);
        if (!ctx) return;
        charts[canvasId] = new Chart(ctx, config);
    }

    function horizontalBar(canvasId, labels, data, label, color) {
        const canvas = document.getElementById(canvasId);
        if (!canvas) return;
        const minH = Math.max(200, labels.length * 28);
        canvas.parentElement.style.position = 'relative';
        canvas.parentElement.style.height = minH + 'px';
        makeChart(canvasId, {
            type: 'bar',
            data: { labels, datasets: [{ label, data, backgroundColor: color || COLORS[0], borderRadius: 3 }] },
            options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } },
                scales: { x: { grid: { color: '#262626' }, ticks: { color: '#a3a3a3' } }, y: { grid: { display: false }, ticks: { color: '#d4d4d4', autoSkip: false, font: { size: 11 } } } } }
        });
    }

    function verticalBar(canvasId, labels, datasets, xLabel, yLabel) {
        makeChart(canvasId, {
            type: 'bar',
            data: { labels, datasets },
            options: { responsive: true, plugins: { legend: { display: datasets.length > 1, labels: { color: '#a3a3a3' } } },
                scales: { x: { grid: { color: '#262626' }, title: { display: !!xLabel, text: xLabel, color: '#a3a3a3' }, ticks: { color: '#a3a3a3', maxRotation: 45, minRotation: 45, autoSkip: false, font: { size: 10 } } },
                         y: { grid: { color: '#262626' }, title: { display: !!yLabel, text: yLabel, color: '#a3a3a3' }, ticks: { color: '#a3a3a3' } } } }
        });
    }

    function lineChart(canvasId, labels, datasets, xLabel, yLabel) {
        makeChart(canvasId, {
            type: 'line',
            data: { labels, datasets },
            options: { responsive: true, interaction: { mode: 'index', intersect: false },
                plugins: { legend: { display: datasets.length > 1, labels: { color: '#a3a3a3' } } },
                scales: { x: { grid: { color: '#262626' }, title: { display: !!xLabel, text: xLabel, color: '#a3a3a3' }, ticks: { color: '#a3a3a3' } },
                         y: { grid: { color: '#262626' }, title: { display: !!yLabel, text: yLabel, color: '#a3a3a3' }, ticks: { color: '#a3a3a3' } } } }
        });
    }

    async function loadTab(tab) {
        showLoading(true);
        try {
            const resp = await fetch('/api/stats/' + tab);
            const data = await resp.json();
            tabsLoaded[tab] = true;
            renderTab(tab, data);
        } catch (e) {
            console.error('Failed to load stats:', e);
        } finally {
            showLoading(false);
        }
    }

    function renderTab(tab, data) {
        switch(tab) {
            case 'gear': renderGear(data); break;
            case 'settings': renderSettings(data); break;
            case 'timeline': renderTimeline(data); break;
            case 'correlations': break; // handled by initCorrelationControls
        }
    }

    function renderGear(d) {
        document.getElementById('title-cameras').textContent = t('stats.charts.camera_bodies');
        document.getElementById('title-lenses').textContent = t('stats.charts.lenses');
        document.getElementById('title-combos').textContent = t('stats.charts.camera_lens_combos');
        document.getElementById('title-categories').textContent = t('stats.charts.category_distribution');
        if (d.cameras && d.cameras.length) {
            horizontalBar('chart-cameras', d.cameras.map(r=>r.name), d.cameras.map(r=>r.count), t('stats.axes.photos'));
        }
        if (d.lenses && d.lenses.length) {
            horizontalBar('chart-lenses', d.lenses.map(r=>r.name), d.lenses.map(r=>r.count), t('stats.axes.photos'), COLORS[1]);
        }
        if (d.combos && d.combos.length) {
            horizontalBar('chart-combos', d.combos.map(r=>r.name), d.combos.map(r=>r.count), t('stats.axes.photos'), COLORS[2]);
        }
        if (d.categories && d.categories.length) {
            horizontalBar('chart-categories', d.categories.map(r=>r.name), d.categories.map(r=>r.count), t('stats.axes.photos'), COLORS[3]);
        }
    }

    function renderSettings(d) {
        document.getElementById('title-iso').textContent = t('stats.charts.iso_distribution');
        document.getElementById('title-aperture').textContent = t('stats.charts.aperture_usage');
        document.getElementById('title-focal').textContent = t('stats.charts.focal_length') + ' (eq. 35mm)';
        document.getElementById('title-shutter').textContent = t('stats.charts.shutter_speed');
        document.getElementById('title-score-dist').textContent = t('stats.charts.score_distribution');

        if (d.iso && d.iso.length) {
            verticalBar('chart-iso', d.iso.map(r=>r.label), [
                { label: t('stats.axes.photos'), data: d.iso.map(r=>r.count), backgroundColor: COLORS[0], borderRadius: 3 }
            ], t('stats.axes.iso'), t('stats.axes.count'));
        }
        if (d.aperture && d.aperture.length) {
            horizontalBar('chart-aperture', d.aperture.map(r=>'f/'+r.value), d.aperture.map(r=>r.count), t('stats.axes.photos'), COLORS[1]);
        }
        if (d.focal_length && d.focal_length.length) {
            verticalBar('chart-focal', d.focal_length.map(r=>r.label), [
                { label: t('stats.axes.photos'), data: d.focal_length.map(r=>r.count), backgroundColor: COLORS[2], borderRadius: 3 }
            ], t('stats.axes.focal_length'), t('stats.axes.count'));
        }
        if (d.shutter_speed && d.shutter_speed.length) {
            verticalBar('chart-shutter', d.shutter_speed.map(r=>r.label), [
                { label: t('stats.axes.photos'), data: d.shutter_speed.map(r=>r.count), backgroundColor: COLORS[3], borderRadius: 3 }
            ], t('stats.axes.shutter_speed'), t('stats.axes.count'));
        }
        if (d.score_distribution && d.score_distribution.length) {
            verticalBar('chart-score-dist', d.score_distribution.map(r=>r.label), [
                { label: t('stats.axes.photos'), data: d.score_distribution.map(r=>r.count), backgroundColor: COLORS[4], borderRadius: 3 }
            ], t('stats.axes.score'), t('stats.axes.count'));
        }
    }

    function renderTimeline(d) {
        document.getElementById('title-monthly').textContent = t('stats.charts.photos_per_month');
        document.getElementById('title-yearly').textContent = t('stats.charts.photos_per_year');
        document.getElementById('title-heatmap').textContent = t('stats.charts.hours_heatmap');
        document.getElementById('title-top-days').textContent = t('stats.charts.top_days');

        if (d.monthly && d.monthly.length) {
            lineChart('chart-monthly', d.monthly.map(r=>r.month), [
                { label: t('stats.axes.photos'), data: d.monthly.map(r=>r.count), borderColor: COLORS[0], backgroundColor: 'rgba(34,197,94,0.1)', fill: true, tension: 0.3, pointRadius: 1 }
            ], t('stats.axes.month'), t('stats.axes.photos'));
        }
        if (d.yearly && d.yearly.length) {
            verticalBar('chart-yearly', d.yearly.map(r=>r.year), [
                { label: t('stats.axes.photos'), data: d.yearly.map(r=>r.count), backgroundColor: COLORS[0], borderRadius: 3 }
            ], t('stats.axes.year'), t('stats.axes.photos'));
        }
        if (d.heatmap && d.heatmap.length) {
            const dayLabels = [t('stats.days.sun'), t('stats.days.mon'), t('stats.days.tue'), t('stats.days.wed'), t('stats.days.thu'), t('stats.days.fri'), t('stats.days.sat')];
            const maxCount = Math.max(...d.heatmap.map(p => p.count), 1);
            makeChart('chart-heatmap', {
                type: 'bubble',
                data: { datasets: [{
                    label: t('stats.axes.photos'),
                    data: d.heatmap.map(p => ({ x: p.hour, y: p.day, r: Math.max(2, (p.count / maxCount) * 20) })),
                    backgroundColor: 'rgba(34,197,94,0.6)'
                }]},
                options: { responsive: true, plugins: { legend: { display: false }, tooltip: {
                    callbacks: { label: ctx => { const p = d.heatmap[ctx.dataIndex]; return dayLabels[p.day] + ' ' + p.hour + 'h: ' + p.count + ' ' + t('stats.axes.photos').toLowerCase(); } }
                }},
                scales: {
                    x: { min: -0.5, max: 23.5, grid: { color: '#262626' }, title: { display: true, text: t('stats.axes.hour'), color: '#a3a3a3' }, ticks: { color: '#a3a3a3', stepSize: 1 } },
                    y: { min: -0.5, max: 6.5, reverse: true, grid: { color: '#262626' }, title: { display: true, text: t('stats.axes.day_of_week'), color: '#a3a3a3' },
                        ticks: { color: '#a3a3a3', callback: v => dayLabels[v] || '' } }
                }}
            });
        }
        if (d.top_days && d.top_days.length) {
            horizontalBar('chart-top-days', d.top_days.map(r=>r.date), d.top_days.map(r=>r.count), t('stats.axes.photos'), COLORS[3]);
        }
    }

    const CORR_METRICS = ['aggregate','aesthetic','tech_sharpness','noise_sigma','comp_score',
        'face_quality','color_score','exposure_score','contrast_score',
        'dynamic_range_stops','mean_saturation','isolation_bonus','quality_score',
        'power_point_score','leading_lines_score'];
    const CORR_DEFAULTS = ['aggregate','aesthetic'];
    let corrInitialized = false;

    function initCorrelationControls() {
        if (corrInitialized) return;
        corrInitialized = true;
        const dropdown = document.getElementById('corr-metrics-dropdown');
        const trigger = document.getElementById('corr-metrics-trigger');
        CORR_METRICS.forEach(m => {
            const label = document.createElement('label');
            label.className = 'flex items-center gap-2 px-3 py-1.5 text-sm text-neutral-300 cursor-pointer hover:bg-neutral-700';
            const cb = document.createElement('input');
            cb.type = 'checkbox'; cb.value = m;
            cb.className = 'accent-green-500 corr-metric-cb';
            if (CORR_DEFAULTS.includes(m)) cb.checked = true;
            cb.addEventListener('change', () => { updateMetricChips(); fetchCorrelations(); });
            label.appendChild(cb);
            label.appendChild(document.createTextNode(' ' + t('stats.correlations.metrics.' + m)));
            dropdown.appendChild(label);
        });
        trigger.addEventListener('click', (e) => {
            if (e.target.closest('.corr-chip-remove')) return;
            dropdown.classList.toggle('hidden');
        });
        document.addEventListener('click', (e) => {
            if (!e.target.closest('#corr-metrics-select')) dropdown.classList.add('hidden');
        });
        updateMetricAvailability();
        updateMetricChips();
        document.getElementById('corr-x').addEventListener('change', () => { updateMetricAvailability(); fetchCorrelations(); });
        document.getElementById('corr-group').addEventListener('change', () => { updateMetricAvailability(); fetchCorrelations(); });
        document.getElementById('corr-chart-type').addEventListener('change', fetchCorrelations);
        document.getElementById('corr-min-samples').addEventListener('change', fetchCorrelations);
        document.getElementById('corr-date-from').addEventListener('change', fetchCorrelations);
        document.getElementById('corr-date-to').addEventListener('change', fetchCorrelations);

    }

    function updateMetricAvailability() {
        const xVal = document.getElementById('corr-x').value;
        const gVal = document.getElementById('corr-group').value;
        const excluded = new Set([xVal, gVal].filter(Boolean));
        document.querySelectorAll('.corr-metric-cb').forEach(cb => {
            const disabled = excluded.has(cb.value);
            cb.disabled = disabled;
            const label = cb.closest('label');
            if (disabled) {
                cb.checked = false;
                label.classList.add('opacity-40', 'pointer-events-none');
            } else {
                label.classList.remove('opacity-40', 'pointer-events-none');
            }
        });
        updateMetricChips();
    }

    function updateMetricChips() {
        const chips = document.getElementById('corr-metrics-chips');
        chips.innerHTML = '';
        document.querySelectorAll('.corr-metric-cb:checked').forEach(cb => {
            const chip = document.createElement('span');
            chip.className = 'inline-flex items-center gap-1 bg-neutral-700 text-neutral-200 text-xs rounded px-2 py-0.5';
            chip.textContent = t('stats.correlations.metrics.' + cb.value);
            const rm = document.createElement('button');
            rm.type = 'button';
            rm.className = 'corr-chip-remove text-neutral-400 hover:text-white ml-0.5';
            rm.innerHTML = '&times;';
            rm.addEventListener('click', (e) => { e.stopPropagation(); cb.checked = false; updateMetricChips(); fetchCorrelations(); });
            chip.appendChild(rm);
            chips.appendChild(chip);
        });
        if (!chips.children.length) {
            const placeholder = document.createElement('span');
            placeholder.className = 'text-neutral-500 text-sm';
            placeholder.textContent = t('stats.correlations.y_metrics');
            chips.appendChild(placeholder);
        }
    }

    async function fetchCorrelations() {
        const x = document.getElementById('corr-x').value;
        const groupBy = document.getElementById('corr-group').value;
        const minSamples = document.getElementById('corr-min-samples').value || '3';
        const checked = [...document.querySelectorAll('.corr-metric-cb:checked')].map(c => c.value);
        const status = document.getElementById('corr-status');

        if (!checked.length) {
            status.textContent = t('stats.correlations.select_metric');
            if (charts['chart-correlations']) { charts['chart-correlations'].destroy(); delete charts['chart-correlations']; }
            return;
        }

        status.textContent = t('stats.loading');
        try {
            const params = new URLSearchParams({ x, y: checked.join(','), min_samples: minSamples });
            if (groupBy) params.set('group_by', groupBy);
            const dateFrom = document.getElementById('corr-date-from').value;
            const dateTo = document.getElementById('corr-date-to').value;
            if (dateFrom) params.set('date_from', dateFrom);
            if (dateTo) params.set('date_to', dateTo);
            const resp = await fetch('/api/stats/correlations?' + params);
            const data = await resp.json();
            if (data.error) { status.textContent = data.error; return; }
            tabsLoaded['correlations'] = true;
            renderCorrelationChart(data);
            const bucketCount = data.labels ? data.labels.length : 0;
            status.textContent = bucketCount + ' ' + t('stats.correlations.buckets');
        } catch(e) {
            status.textContent = t('stats.correlations.error');
            console.error(e);
        }
    }

    function renderCorrelationChart(data) {
        const chartType = document.getElementById('corr-chart-type').value;
        const isHorizontal = chartType === 'horizontalBar';
        const isArea = chartType === 'area';
        const isRadar = chartType === 'radar';
        const isScatter = chartType === 'scatter';
        const type = isHorizontal ? 'bar' : isArea ? 'line' : isScatter ? 'scatter' : chartType;
        const labels = data.labels || [];
        const datasets = [];
        let ci = 0;

        function makeDs(label, values, color) {
            if (isArea) {
                return { label, data: values, borderColor: color, backgroundColor: color + '33', tension: 0.3, pointRadius: 2, fill: true, spanGaps: true };
            } else if (type === 'line') {
                return { label, data: values, borderColor: color, backgroundColor: color + '33', tension: 0.3, pointRadius: 3, spanGaps: true };
            } else if (isScatter) {
                const points = values.map((v, i) => v != null ? { x: i, y: v } : null).filter(Boolean);
                return { label, data: points, backgroundColor: color, pointRadius: 4 };
            } else if (isRadar) {
                return { label, data: values, borderColor: color, backgroundColor: color + '33', pointBackgroundColor: color, pointRadius: 3 };
            } else {
                return { label, data: values, backgroundColor: color, borderRadius: 3 };
            }
        }

        if (data.group_by && data.groups) {
            const groups = Object.keys(data.groups);
            const metrics = data.metrics || [];
            groups.forEach(grp => {
                metrics.forEach(m => {
                    const metricLabel = t('stats.correlations.metrics.' + m);
                    const dsLabel = metrics.length > 1 ? grp + ' - ' + metricLabel : grp;
                    const values = labels.map(lbl => {
                        const bucket = data.groups[grp] && data.groups[grp][lbl];
                        return bucket ? bucket[m] : null;
                    });
                    datasets.push(makeDs(dsLabel, values, COLORS[ci++ % COLORS.length]));
                });
            });
        } else if (data.metrics) {
            const metricKeys = Object.keys(data.metrics);
            metricKeys.forEach(m => {
                const metricLabel = t('stats.correlations.metrics.' + m);
                datasets.push(makeDs(metricLabel, data.metrics[m], COLORS[ci++ % COLORS.length]));
            });
        }

        const xDimLabel = t('stats.correlations.dimensions.' + (data.x_axis || ''));
        // Build Y axis label from selected metrics
        const yMetricKeys = data.group_by && data.groups ? (data.metrics || []) : Object.keys(data.metrics || {});
        const yLabel = yMetricKeys.map(m => t('stats.correlations.metrics.' + m)).join(', ');
        const scalesConfig = isRadar ? {
            r: { grid: { color: '#262626' }, ticks: { color: '#a3a3a3', backdropColor: 'transparent' }, pointLabels: { color: '#d4d4d4' } }
        } : {
            x: { grid: { color: '#262626' },
                 title: { display: !isHorizontal, text: isHorizontal ? yLabel : xDimLabel, color: '#a3a3a3' },
                 ticks: { color: '#a3a3a3', callback: isScatter ? (v => labels[v] || v) : undefined } },
            y: { grid: { color: '#262626' },
                 title: { display: true, text: isHorizontal ? xDimLabel : yLabel, color: '#a3a3a3' },
                 ticks: { color: '#a3a3a3' } }
        };
        // Size chart card to fill remaining viewport (min 640px)
        const card = document.getElementById('corr-chart-card');
        const rect = card.getBoundingClientRect();
        const availH = Math.max(640, window.innerHeight - rect.top - 24);
        card.style.height = availH + 'px';

        makeChart('chart-correlations', {
            type,
            data: { labels: isScatter ? undefined : labels, datasets },
            options: {
                indexAxis: isHorizontal ? 'y' : 'x',
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: isScatter ? 'nearest' : 'index', intersect: false },
                plugins: { legend: { display: datasets.length > 1, position: 'bottom', align: 'center', labels: { color: '#a3a3a3', padding: 16, usePointStyle: true, pointStyle: 'circle' } },
                    tooltip: {
                        callbacks: {
                            afterTitle: ctx => {
                                if (isScatter && ctx[0]) {
                                    const idx = ctx[0].raw.x;
                                    const lbl = labels[idx] || '';
                                    return lbl + (data.counts ? ' (' + data.counts[idx] + ' ' + t('stats.axes.photos').toLowerCase() + ')' : '');
                                }
                                if (data.counts && ctx[0]) return data.counts[ctx[0].dataIndex] + ' ' + t('stats.axes.photos').toLowerCase();
                                return '';
                            }
                        }
                    }
                },
                scales: scalesConfig
            }
        });
    }

    // Load gear tab on page load
    loadTab('gear');
    </script>
</body>
</html>'''


@app.route('/stats')
def stats_page():
    if not _is_authenticated():
        return redirect('/login?next=/stats')
    return render_template_string(STATS_TEMPLATE)


@app.route('/api/stats/gear')
def api_stats_gear():
    if not _is_authenticated():
        return jsonify({'error': 'unauthorized'}), 401

    def compute():
        conn = get_db_connection()
        cur = conn.cursor()
        # Camera bodies
        cur.execute('''SELECT camera_model, COUNT(*) as cnt, ROUND(AVG(aggregate),2), ROUND(AVG(aesthetic),2)
                       FROM photos WHERE camera_model IS NOT NULL AND camera_model != ''
                       GROUP BY camera_model ORDER BY cnt DESC LIMIT 20''')
        cameras = [{'name': r[0], 'count': r[1], 'avg_aggregate': r[2], 'avg_aesthetic': r[3]} for r in cur.fetchall()]

        # Lenses
        cur.execute('''SELECT lens_model, COUNT(*) as cnt
                       FROM photos WHERE lens_model IS NOT NULL AND lens_model != ''
                       GROUP BY lens_model ORDER BY cnt DESC LIMIT 20''')
        lenses = [{'name': r[0], 'count': r[1]} for r in cur.fetchall()]

        # Combos
        cur.execute('''SELECT camera_model || ' + ' || lens_model as combo, COUNT(*) as cnt, ROUND(AVG(aggregate),2)
                       FROM photos WHERE camera_model IS NOT NULL AND camera_model != '' AND lens_model IS NOT NULL AND lens_model != ''
                       GROUP BY camera_model, lens_model ORDER BY cnt DESC LIMIT 20''')
        combos = [{'name': r[0], 'count': r[1], 'avg_aggregate': r[2]} for r in cur.fetchall()]

        # Category distribution
        cur.execute('''SELECT category, COUNT(*) as cnt
                       FROM photos WHERE category IS NOT NULL AND category != ''
                       GROUP BY category ORDER BY cnt DESC''')
        categories = [{'name': r[0], 'count': r[1]} for r in cur.fetchall()]

        conn.close()
        return {'cameras': cameras, 'lenses': lenses, 'combos': combos, 'categories': categories}

    return jsonify(_get_stats_cached('gear', compute))


@app.route('/api/stats/settings')
def api_stats_settings():
    if not _is_authenticated():
        return jsonify({'error': 'unauthorized'}), 401

    def compute():
        conn = get_db_connection()
        cur = conn.cursor()

        # ISO distribution with buckets
        cur.execute('''SELECT
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
            FROM photos WHERE ISO IS NOT NULL AND ISO > 0
            GROUP BY iso_bucket ORDER BY sort_key''')
        iso = [{'label': r[0], 'count': r[1]} for r in cur.fetchall()]

        # Aperture usage
        cur.execute('''SELECT ROUND(f_stop, 1) as ap, COUNT(*) as cnt
                       FROM photos WHERE f_stop IS NOT NULL AND f_stop > 0
                       GROUP BY ap ORDER BY ap''')
        aperture = [{'value': r[0], 'count': r[1]} for r in cur.fetchall()]

        # Focal length distribution (prefer 35mm equivalent)
        cur.execute('''SELECT
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
            FROM photos WHERE COALESCE(focal_length_35mm, focal_length) IS NOT NULL AND COALESCE(focal_length_35mm, focal_length) > 0
            GROUP BY focal_bucket ORDER BY sort_key''')
        focal = [{'label': r[0], 'count': r[1]} for r in cur.fetchall()]

        # Shutter speed distribution with SQL binning
        # Parse TEXT shutter_speed: "1/250" -> fraction, "0.5" -> float
        cur.execute('''SELECT
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
                WHERE shutter_speed IS NOT NULL AND shutter_speed != ''
            ) WHERE ss IS NOT NULL AND ss > 0
            GROUP BY shutter_bucket ORDER BY sort_key''')
        shutter = [{'label': r[0], 'count': r[1]} for r in cur.fetchall()]

        # Score distribution in 0.5-point buckets
        cur.execute('''SELECT ROUND(aggregate * 2) / 2.0 AS bucket, COUNT(*) as cnt
                       FROM photos WHERE aggregate IS NOT NULL
                       GROUP BY bucket ORDER BY bucket''')
        score_dist = [{'label': str(r[0]), 'count': r[1]} for r in cur.fetchall()]
        conn.close()

        return {'iso': iso, 'aperture': aperture, 'focal_length': focal, 'shutter_speed': shutter, 'score_distribution': score_dist}

    return jsonify(_get_stats_cached('settings', compute))


@app.route('/api/stats/timeline')
def api_stats_timeline():
    if not _is_authenticated():
        return jsonify({'error': 'unauthorized'}), 401

    def compute():
        conn = get_db_connection()
        cur = conn.cursor()

        # Monthly
        cur.execute('''SELECT SUBSTR(date_taken, 1, 7) as month, COUNT(*) as cnt
                       FROM photos WHERE date_taken IS NOT NULL AND date_taken != ''
                       GROUP BY month ORDER BY month''')
        monthly = [{'month': r[0].replace(':', '-'), 'count': r[1]} for r in cur.fetchall()]

        # Yearly
        cur.execute('''SELECT SUBSTR(date_taken, 1, 4) as year, COUNT(*) as cnt
                       FROM photos WHERE date_taken IS NOT NULL AND date_taken != ''
                       GROUP BY year ORDER BY year''')
        yearly = [{'year': r[0], 'count': r[1]} for r in cur.fetchall()]

        # Heatmap (day of week x hour)
        cur.execute('''SELECT
            CAST(STRFTIME('%w', REPLACE(SUBSTR(date_taken,1,10),':','-')) AS INTEGER) as dow,
            CAST(SUBSTR(date_taken, 12, 2) AS INTEGER) as hour,
            COUNT(*) as cnt
            FROM photos WHERE date_taken IS NOT NULL AND LENGTH(date_taken) >= 13
            GROUP BY dow, hour''')
        heatmap = [{'day': r[0], 'hour': r[1], 'count': r[2]} for r in cur.fetchall()]

        # Top days
        cur.execute('''SELECT REPLACE(SUBSTR(date_taken, 1, 10), ':', '-') as day, COUNT(*) as cnt
                       FROM photos WHERE date_taken IS NOT NULL AND date_taken != ''
                       GROUP BY day ORDER BY cnt DESC LIMIT 10''')
        top_days = [{'date': r[0], 'count': r[1]} for r in cur.fetchall()]

        conn.close()
        return {'monthly': monthly, 'yearly': yearly, 'heatmap': heatmap, 'top_days': top_days}

    return jsonify(_get_stats_cached('timeline', compute))


@app.route('/api/stats/correlations')
def api_stats_correlations():
    if not _is_authenticated():
        return jsonify({'error': 'unauthorized'}), 401

    # Validate parameters against whitelists
    x = request.args.get('x', 'iso')
    if x not in CORRELATION_X_AXES:
        return jsonify({'error': 'invalid x axis'}), 400

    y_raw = request.args.get('y', 'aggregate')
    y_metrics = [m for m in y_raw.split(',') if m in CORRELATION_Y_METRICS]
    if not y_metrics:
        return jsonify({'error': 'no valid metrics'}), 400

    group_by = request.args.get('group_by', '')
    if group_by and group_by not in CORRELATION_X_AXES:
        return jsonify({'error': 'invalid group_by'}), 400

    try:
        min_samples = max(1, int(request.args.get('min_samples', '3')))
    except ValueError:
        min_samples = 3

    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')

    cache_key = f"corr:{x}:{','.join(sorted(y_metrics))}:{group_by}:{min_samples}:{date_from}:{date_to}"

    def compute():
        conn = get_db_connection()
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
        date_filter = (' AND '.join(date_clauses)) if date_clauses else '1=1'

        # Build metric AVG expressions
        metric_cols = ', '.join(f'ROUND(AVG({m}), 3)' for m in y_metrics)

        if group_by:
            g_def = CORRELATION_X_AXES[group_by]
            g_sql = g_def['sql']
            g_filter = g_def['filter']
            top_n = g_def['top_n']

            # Find top N groups by count
            cur.execute(f"SELECT {g_sql}, COUNT(*) as cnt FROM photos WHERE {g_filter} AND {x_filter} AND {date_filter} GROUP BY {g_sql} ORDER BY cnt DESC LIMIT ?", date_params + [top_n])
            top_groups = [r[0] for r in cur.fetchall()]
            if not top_groups:
                conn.close()
                return {'labels': [], 'groups': {}, 'metrics': y_metrics, 'x_axis': x, 'group_by': group_by}

            placeholders = ','.join('?' for _ in top_groups)
            sql = f"""SELECT {x_sql} AS x_bucket, {g_sql} AS group_val, {metric_cols}, COUNT(*) AS cnt
                      FROM photos
                      WHERE {x_filter} AND {g_filter} AND {date_filter} AND {g_sql} IN ({placeholders})
                      GROUP BY x_bucket, group_val
                      HAVING cnt >= ?
                      ORDER BY {x_sort}"""
            cur.execute(sql, date_params + top_groups + [min_samples])
            rows = cur.fetchall()
            conn.close()

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
            sql = f"""SELECT {x_sql} AS x_bucket, {metric_cols}, COUNT(*) AS cnt
                      FROM photos
                      WHERE {x_filter} AND {date_filter}
                      GROUP BY x_bucket
                      HAVING cnt >= ?
                      ORDER BY {x_sort}"""
            cur.execute(sql, date_params + [min_samples])
            rows = cur.fetchall()
            conn.close()

            labels = [str(r[0]) for r in rows]
            metrics = {}
            for i, m in enumerate(y_metrics):
                metrics[m] = [r[1 + i] for r in rows]
            counts = [r[1 + len(y_metrics)] for r in rows]

            return {'labels': labels, 'metrics': metrics, 'counts': counts, 'x_axis': x, 'group_by': ''}

    return jsonify(_get_stats_cached(cache_key, compute))


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
