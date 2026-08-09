"""
Configuration loading for the FastAPI API server.

"""

import asyncio
import logging
import os
import json
import math
import shutil
import stat
import tempfile
import threading
import time
import secrets

logger = logging.getLogger(__name__)

# --- CONFIG & SHARE SECRET (single parse of scoring_config.json) ---
_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scoring_config.json')
CONFIG_WRITE_LOCK = threading.Lock()
FACET_SCRIPT = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'facet.py')

_TEMP_CONFIG_SUFFIX = '.json'
_WORLD_READ_WRITE_MODE = 0o666
_config_load_failed = False


def _umask_default_mode():
    """Return the permission bits a plain ``open(path, 'w')`` would have created.

    ``os.umask`` is both the setter and the only getter, so the current value
    is read by setting it and immediately restoring it. Only reached when the
    destination does not exist yet and there is no mode to preserve.
    """
    umask = os.umask(0)
    os.umask(umask)
    return _WORLD_READ_WRITE_MODE & ~umask


def _replacement_mode(path):
    """Permission bits an atomic replacement of ``path`` must end up with."""
    try:
        return stat.S_IMODE(os.stat(path).st_mode)
    except FileNotFoundError:
        return _umask_default_mode()


def _fsync_directory(directory):
    """Flush a rename in ``directory`` so the replacement survives a crash.

    The replacement's own bytes are already fsynced and not every platform
    allows opening a directory for reading, so a failure here is logged rather
    than raised.
    """
    try:
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        logger.debug("Could not fsync directory %s", directory, exc_info=True)


def _unlink_quietly(path):
    """Remove a temp file whose write failed, without masking the real error."""
    try:
        os.unlink(path)
    except OSError:
        logger.debug("Could not remove temp file %s", path, exc_info=True)


def atomic_write_json(path, data):
    """Replace ``path`` with ``data`` atomically, durably, and at its current mode.

    ``tempfile.mkstemp`` creates the replacement 0600, so the destination's own
    permissions are copied onto it before the rename — otherwise every config
    write would silently strip the group/other read access a co-deployed CLI
    needs. The payload is fsynced before the rename and the containing
    directory after it, so a crash leaves either the old file or the new one,
    never a truncated mix.

    Atomicity is per write, not per read-modify-write: every caller that reads
    scoring_config.json, edits part of it and writes it back MUST hold
    :data:`CONFIG_WRITE_LOCK` across the whole sequence, or one caller's update
    is lost wholesale under another's. That lock is the only one taken while a
    config write is in flight; ``reload_config`` may acquire it (through
    :func:`_load_and_ensure_share_secret`) while holding ``_config_lock``, so no
    writer may call ``reload_config`` without first releasing it.
    """
    directory = os.path.dirname(path) or '.'
    mode = _replacement_mode(path)
    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=_TEMP_CONFIG_SUFFIX)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, path)
    except Exception:
        _unlink_quietly(tmp_path)
        raise
    _fsync_directory(directory)


def config_load_failed():
    """True when scoring_config.json exists but could not be parsed.

    An unparseable config yields an EMPTY config — one carrying neither
    ``viewer.password`` nor ``viewer.edition_password`` — which is
    indistinguishable from a deliberately open install and would otherwise
    unlock every edition route. ``api.auth`` consults this flag to treat such
    an install as locked. A genuinely absent config is NOT a failure: a fresh,
    never-configured install is legitimately open.
    """
    return _config_load_failed


def _read_config():
    """Parse scoring_config.json, tracking whether an existing file failed to parse.

    Returns ``(config, parsed_ok)``. A missing file yields ``({}, False)``
    without arming :func:`config_load_failed`.
    """
    global _config_load_failed
    try:
        with open(_CONFIG_PATH) as f:
            config = json.load(f)
    except FileNotFoundError:
        logger.debug("No %s — running as a never-configured install", _CONFIG_PATH)
        return {}, False
    except Exception:
        _config_load_failed = True
        logger.error(
            "Could not parse %s — refusing the open-install auth path until it parses",
            _CONFIG_PATH, exc_info=True,
        )
        return {}, False
    _config_load_failed = False
    return config, True


def _load_and_ensure_share_secret():
    """Load scoring_config.json once, ensure share_secret exists. Returns (config_dict, secret).

    Holds :data:`CONFIG_WRITE_LOCK` — the one lock every writer of this file
    takes — across its read-modify-write, so a concurrent weights, priority,
    context or password-upgrade write can neither lose this secret nor be lost
    under it. Writes atomically via temp file + rename to avoid partial writes.

    A config that exists but does not parse gets an ephemeral in-memory secret
    and is never rewritten: persisting a share_secret-only stub over a partial
    or corrupt file would destroy the whole config (and its .backup with it).
    """
    config, _ = _read_config()
    if 'share_secret' not in config or not config['share_secret']:
        with CONFIG_WRITE_LOCK:
            config, parsed_ok = _read_config()
            if 'share_secret' not in config or not config['share_secret']:
                config['share_secret'] = secrets.token_hex(32)
                if parsed_ok:
                    shutil.copy2(_CONFIG_PATH, f"{_CONFIG_PATH}.backup")
                    atomic_write_json(_CONFIG_PATH, config)
    return config, config['share_secret']


_FULL_CONFIG, _share_secret = _load_and_ensure_share_secret()

# JWT secret — derived from share_secret for consistency
JWT_SECRET = _share_secret
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 48  # 2 days


# --- VIEWER CONFIG ---
def load_viewer_config(config=None):
    """Load viewer settings, merging defaults with config."""
    defaults = {
        'sort_options': {
            'General': [
                {'column': 'aggregate', 'label': 'Aggregate Score'},
                {'column': 'aesthetic', 'label': 'Aesthetic'},
                {'column': 'topiq_score', 'label': 'TOPIQ Score'},
                {'column': 'date_taken', 'label': 'Date Taken'},
                {'column': 'is_favorite', 'label': 'Favorites'},
                {'column': 'is_rejected', 'label': 'Rejected'}
            ],
            'Face Metrics': [
                {'column': 'face_quality', 'label': 'Face Quality'},
                {'column': 'eye_sharpness', 'label': 'Eye Sharpness'},
                {'column': 'face_sharpness', 'label': 'Face Sharpness'},
                {'column': 'face_ratio', 'label': 'Face Ratio'},
                {'column': 'face_count', 'label': 'Face Count'},
                {'column': 'face_confidence', 'label': 'Face Confidence'}
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
        'raw_processor': {
            'darktable': {
                'executable': 'darktable-cli',
                'profiles': [],
                'cull_styles': [],
                'preview_max_edge': 1440,
                'preview_timeout_seconds': 60,
            },
        },
        'display': {'tags_per_photo': 3, 'card_width_px': 168, 'image_width_px': 160, 'image_jpeg_quality': 96},
        'face_thumbnails': {'output_size_px': 64, 'jpeg_quality': 80, 'crop_padding_ratio': 0.2, 'min_crop_size_px': 20},
        'quality_thresholds': {'good': 6, 'great': 7, 'excellent': 8, 'best': 9},
        'photo_types': {'top_picks_min_score': 7, 'low_light_max_luminance': 0.2},
        'defaults': {'hide_blinks': True, 'hide_bursts': True, 'hide_duplicates': True, 'hide_details': True, 'hide_rejected': True, 'sort': 'aggregate', 'sort_direction': 'DESC'},
        'features': {'show_similar_button': True, 'show_merge_suggestions': True, 'show_rating_controls': True, 'show_rating_badge': True, 'show_semantic_search': True, 'show_albums': True, 'show_critique': True, 'show_vlm_critique': False, 'show_embed_metadata': True, 'show_memories': True, 'show_captions': True, 'show_timeline': True, 'show_map': False, 'show_capsules': True, 'show_my_taste': True, 'show_scenes': True, 'show_junk_sweep': True, 'show_proofing': False},
        'proofing': {'pin': '', 'session_minutes': 1440},
        'cache_ttl_seconds': 3600,
        'notification_duration_ms': 2000
    }
    if config is None:
        config, _ = _read_config()
    viewer = config.get('viewer', {})
    for key, value in defaults.items():
        if key not in viewer:
            viewer[key] = value
        elif isinstance(value, dict):
            for k, v in value.items():
                if k not in viewer[key]:
                    viewer[key][k] = v
    return viewer


VIEWER_CONFIG = load_viewer_config(_FULL_CONFIG)


def get_xmp_export_config():
    """Return the ``xmp_export`` config block (score-to-stars mapping etc.)."""
    return _FULL_CONFIG.get('xmp_export', {})


# --- MULTI-USER SUPPORT ---

def is_multi_user_enabled():
    """Check if multi-user mode is configured."""
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
    """Get list of all directories a user can access (own + shared)."""
    users = _FULL_CONFIG.get('users', {})
    user = users.get(username)
    if user is None or not isinstance(user, dict):
        return []
    user_dirs = list(user.get('directories', []))
    shared_dirs = list(users.get('shared_directories', []))
    return user_dirs + shared_dirs


def get_all_scan_directories():
    """Get all configured directories (all users + shared + path_mapping targets)."""
    users = _FULL_CONFIG.get('users', {})
    dirs = set()
    for key, val in users.items():
        if key == 'shared_directories':
            dirs.update(val)
        elif isinstance(val, dict):
            dirs.update(val.get('directories', []))
    # Include path_mapping target directories so mapped paths pass the allowlist
    for target in VIEWER_CONFIG.get('path_mapping', {}).values():
        dirs.add(target)
    # Include standalone scan directories (single-user / Docker installs that
    # have no per-user directories configured still get a pickable target)
    dirs.update(VIEWER_CONFIG.get('scan_directories', []))
    return sorted(dirs)


_config_lock = threading.Lock()


def reload_config():
    """Reload scoring_config.json from disk.

    ``VIEWER_CONFIG`` is refilled in place rather than rebound: every consumer
    does ``from api.config import VIEWER_CONFIG`` at import time and holds that
    dict forever, so rebinding this module's name would leave them all reading
    the pre-reload values. ``api.auth`` derives each token's password generation
    from it, which makes a stale copy a security question and not just a
    freshness one.
    """
    global _FULL_CONFIG, _share_secret, JWT_SECRET
    with _config_lock:
        _FULL_CONFIG, _share_secret = _load_and_ensure_share_secret()
        VIEWER_CONFIG.clear()
        VIEWER_CONFIG.update(load_viewer_config(_FULL_CONFIG))
        JWT_SECRET = _share_secret


def map_disk_path(db_path):
    """Map a database path to a local disk path using viewer.path_mapping config."""
    path_mapping = VIEWER_CONFIG.get('path_mapping', {})
    for prefix_from, prefix_to in path_mapping.items():
        if db_path.startswith(prefix_from):
            db_path = prefix_to + db_path[len(prefix_from):]
            break
        normalized = db_path.replace('\\', '/')
        prefix_normalized = prefix_from.replace('\\', '/')
        if normalized.startswith(prefix_normalized):
            db_path = prefix_to + normalized[len(prefix_normalized):]
            break
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

# Cache for existing columns (loaded once at startup, rarely changes)
_existing_columns_cache = None
_existing_columns_lock = threading.Lock()

# Cache for photo type counts (keyed by hide_blinks/hide_bursts/hide_duplicates combination)
_photo_types_cache = {'data': {}, 'expires': 0}
_photo_types_lock = threading.Lock()

# Cache for COUNT query results (avoids repeated full-table scans)
_count_cache = {}
_count_cache_lock = threading.Lock()
COUNT_CACHE_TTL = 300  # seconds

# Track if photo_tags lookup table is available.
# TTL-cached so `database.py --migrate-tags` running while the API is up
# eventually flips the cache without requiring an API restart.
_photo_tags_available = None
_photo_tags_checked_at = 0.0
_photo_tags_lock = threading.Lock()
PHOTO_TAGS_CACHE_TTL = 300  # seconds — recheck every 5 min

# Cache for stats API responses
_stats_cache = {}  # key -> {'data': ..., 'expires': float}
_stats_cache_lock = threading.Lock()
_stats_inflight = {}  # key -> _StatsFlight, shared by the sync and async surfaces
_stats_cache_generation = 0
_STATS_FLIGHT_POLL_SECONDS = 0.02


def _sanitize_stats(obj):
    """Replace NaN/Infinity floats with None for JSON serialization."""
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize_stats(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_stats(v) for v in obj]
    return obj


class _StatsFlight:
    """One in-flight ``compute_fn`` run, shared by every caller of its key.

    ``done`` is a :class:`threading.Event` rather than an ``asyncio`` one so a
    leader on either surface can release waiters on the other: the sync path
    blocks on it from a threadpool thread, the async path polls ``is_set()``
    between ``asyncio.sleep`` calls and never blocks the event loop.
    """

    __slots__ = ('done', 'data', 'error', 'generation')

    def __init__(self, generation):
        self.done = threading.Event()
        self.data = None
        self.error = None
        self.generation = generation


def _lookup_or_claim_stats(cache_key):
    """Resolve a key against the stats cache and the single-flight registry.

    Returns one of ``('hit', data)`` for a live entry, ``('stale', data)`` when
    a computation is already running and an expired entry can be served
    without waiting, ``('lead', flight)`` when the caller must run
    ``compute_fn`` itself, or ``('wait', flight)`` when it must wait for
    another caller's run because nothing is cached.

    ``_stats_cache_lock`` is only held for these dict operations — never
    across a compute or a wait — so this can never deadlock.
    """
    with _stats_cache_lock:
        cached = _stats_cache.get(cache_key)
        if cached and time.time() < cached['expires']:
            return 'hit', cached['data']
        flight = _stats_inflight.get(cache_key)
        if flight is None:
            flight = _StatsFlight(_stats_cache_generation)
            _stats_inflight[cache_key] = flight
            return 'lead', flight
        if cached is not None:
            return 'stale', cached['data']
        return 'wait', flight


def _finish_stats_flight(cache_key, flight, data, error):
    """Publish a leader's outcome: store it, deregister the flight, wake waiters.

    A result computed across an :func:`invalidate_stats_cache` call is handed
    to the waiters but not stored — its generation no longer matches, so the
    next caller recomputes instead of serving pre-invalidation data for a
    whole TTL.
    """
    with _stats_cache_lock:
        if error is None and flight.generation == _stats_cache_generation:
            _stats_cache[cache_key] = {
                'data': data,
                'expires': time.time() + VIEWER_CONFIG['cache_ttl_seconds'],
            }
        if _stats_inflight.get(cache_key) is flight:
            del _stats_inflight[cache_key]
    flight.data = data
    flight.error = error
    flight.done.set()


def _run_stats_flight(cache_key, flight, compute_fn):
    """Run ``compute_fn`` as the leader of ``flight`` and publish the outcome."""
    try:
        data = _sanitize_stats(compute_fn())
    except BaseException as ex:
        _finish_stats_flight(cache_key, flight, None, ex)
        raise
    _finish_stats_flight(cache_key, flight, data, None)
    return data


def _get_stats_cached(cache_key, compute_fn):
    """Return cached stats for ``cache_key``, computing them at most once.

    Concurrent callers of a cold key elect a single leader to run
    ``compute_fn``; the rest either serve an expired entry immediately or
    block on the leader. A waiter whose leader failed retries once — it then
    becomes the new leader or joins a fresh flight, so one cancelled request
    does not fail every other waiter. The sync surface runs in FastAPI's
    threadpool, so blocking on the event is safe here.
    """
    flight = None
    for _ in range(2):
        state, payload = _lookup_or_claim_stats(cache_key)
        if state in ('hit', 'stale'):
            return payload
        if state == 'lead':
            return _run_stats_flight(cache_key, payload, compute_fn)
        flight = payload
        flight.done.wait()
        if flight.error is None:
            return flight.data
    raise flight.error


async def _await_stats_flight(flight):
    """Wait for another caller's computation without blocking the event loop."""
    while not flight.done.is_set():
        await asyncio.sleep(_STATS_FLIGHT_POLL_SECONDS)


async def _get_stats_cached_async(cache_key, compute_fn):
    """Async sibling of :func:`_get_stats_cached`.

    ``compute_fn`` is an ``async`` callable (it awaits an aiosqlite connection
    for its DB reads). The cache dict, lock, TTL, single-flight registry and
    NaN/Inf sanitization are shared with the sync path, so a key written by
    either surface is readable by the other and a leader on one surface
    releases waiters on both.
    """
    flight = None
    for _ in range(2):
        state, payload = _lookup_or_claim_stats(cache_key)
        if state in ('hit', 'stale'):
            return payload
        if state == 'lead':
            try:
                data = _sanitize_stats(await compute_fn())
            except BaseException as ex:
                _finish_stats_flight(cache_key, payload, None, ex)
                raise
            _finish_stats_flight(cache_key, payload, data, None)
            return data
        flight = payload
        await _await_stats_flight(flight)
        if flight.error is None:
            return flight.data
    raise flight.error


def invalidate_stats_cache():
    """Clear the in-memory stats cache under the lock.

    Use this helper from mutation endpoints instead of touching
    ``_stats_cache.clear()`` directly — the module's discipline is "always
    under the lock," and bare ``.clear()`` calls mix locked-readers with
    unlocked-writers. dict.clear() is GIL-atomic so there's no corruption
    today, but the consistency matters if anyone later adds iteration.

    In-flight computations are left running (dropping them would let the next
    caller start a duplicate scan) but are bumped out of the current
    generation, so their results are delivered to their waiters without being
    cached.
    """
    global _stats_cache_generation
    with _stats_cache_lock:
        _stats_cache.clear()
        _stats_cache_generation += 1

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
    'noise_sigma': {
        'sql': "CASE WHEN noise_sigma<2 THEN '<2' WHEN noise_sigma<4 THEN '2-4' "
               "WHEN noise_sigma<6 THEN '4-6' WHEN noise_sigma<8 THEN '6-8' "
               "WHEN noise_sigma<10 THEN '8-10' ELSE '10+' END",
        'sort': 'MIN(noise_sigma)', 'filter': 'noise_sigma IS NOT NULL', 'top_n': 6},
    'contrast_score': {
        'sql': "CASE WHEN contrast_score<4 THEN '<4' WHEN contrast_score<6 THEN '4-6' "
               "WHEN contrast_score<7 THEN '6-7' WHEN contrast_score<8 THEN '7-8' "
               "WHEN contrast_score<9 THEN '8-9' ELSE '9-10' END",
        'sort': 'MIN(contrast_score)', 'filter': 'contrast_score IS NOT NULL', 'top_n': 6},
    'mean_saturation': {
        'sql': "CASE WHEN mean_saturation<0.2 THEN '<20%' WHEN mean_saturation<0.4 THEN '20-40%' "
               "WHEN mean_saturation<0.6 THEN '40-60%' WHEN mean_saturation<0.8 THEN '60-80%' "
               "ELSE '80-100%' END",
        'sort': 'MIN(mean_saturation)', 'filter': 'mean_saturation IS NOT NULL', 'top_n': 5},
    'face_ratio': {
        'sql': "CASE WHEN face_ratio<0.05 THEN '<5%' WHEN face_ratio<0.1 THEN '5-10%' "
               "WHEN face_ratio<0.2 THEN '10-20%' WHEN face_ratio<0.4 THEN '20-40%' "
               "ELSE '40%+' END",
        'sort': 'MIN(face_ratio)', 'filter': 'face_ratio IS NOT NULL AND face_ratio > 0', 'top_n': 5},
    'star_rating': {
        'sql': "CAST(star_rating AS TEXT)", 'sort': 'x_bucket',
        'filter': 'star_rating IS NOT NULL AND star_rating > 0', 'top_n': 5},
}
CORRELATION_Y_METRICS = {
    'aggregate', 'aesthetic', 'tech_sharpness', 'noise_sigma', 'comp_score',
    'face_quality', 'color_score', 'exposure_score', 'contrast_score',
    'dynamic_range_stops', 'mean_saturation', 'isolation_bonus', 'quality_score',
    'power_point_score', 'leading_lines_score',
    'eye_sharpness', 'face_sharpness', 'face_ratio', 'face_confidence',
    'histogram_spread', 'mean_luminance', 'star_rating', 'topiq_score',
    # Supplementary PyIQA
    'aesthetic_iaa', 'face_quality_iqa', 'liqe_score',
    # Subject saliency
    'subject_sharpness', 'subject_prominence', 'subject_placement', 'bg_separation',
}
