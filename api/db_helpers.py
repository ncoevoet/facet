"""
Database helper functions for the FastAPI API server.

"""

import hashlib
import logging
import math
import sqlite3
import struct
import time
from config import ScoringConfig

from api.config import (
    _existing_columns_cache, _existing_columns_lock,
    _photo_tags_available, _photo_tags_lock, PHOTO_TAGS_CACHE_TTL,
    _count_cache, _count_cache_lock, COUNT_CACHE_TTL,
    is_multi_user_enabled, get_user_directories, _FULL_CONFIG,
)
from api.database import get_db_connection

logger = logging.getLogger("facet.api.db_helpers")


def trigger_auto_retrain(db_path, user_id, added=1, conn=None):
    """Best-effort, non-blocking nudge to the personal-ranker auto-retrain.

    A culling confirm or rating change derives ``added`` new comparison pairs;
    once enough accumulate per user the personal ranker retrains in the
    background. Owns the ``added <= 0`` guard and the multi-user scope
    resolution so every caller (burst-culling confirm, similar-group confirm,
    rating sync) stays consistent. Isolated so a missing optimization dep
    (e.g. sklearn) or any failure never affects the write that already
    committed.

    Args:
        db_path: Path to the SQLite DB.
        user_id: Raw request user id; resolved to a per-user scope only when
            multi-user mode is enabled, else pooled into the global ranker.
        added: How many new comparisons this event contributed.
        conn: An already-open SQLite connection from the request that just
            committed; reused for the counter update so the hot culling-confirm
            path doesn't open a second connection. ``None`` (rating sync, CLI)
            opens a short-lived one.
    """
    if added <= 0:
        return
    try:
        from optimization.auto_retrain import maybe_retrain
        scope = user_id if (user_id and is_multi_user_enabled()) else None
        maybe_retrain(db_path, scope, added=added, conn=conn)
    except Exception:  # noqa: BLE001 — never let retrain bookkeeping break the request
        logger.debug("Auto-retrain trigger skipped", exc_info=True)


# --- DATE FORMATTING ---

def to_exif_date(iso_date: str) -> str:
    """Convert ISO date (2024-03-11) to EXIF format (2024:03:11)."""
    return iso_date.replace('-', ':')


def to_iso_date(exif_date: str) -> str:
    """Convert EXIF date prefix (2024:03:11...) to ISO (2024-03-11)."""
    return exif_date[:10].replace(':', '-')


def format_date(date_str):
    """Format EXIF date string (YYYY:MM:DD HH:MM:SS) to DD/MM/YYYY HH:MM."""
    if not date_str or not isinstance(date_str, str):
        return ''
    try:
        parts = date_str.split(' ')
        date_part = parts[0].replace(':', '/')
        date_components = date_part.split('/')
        if len(date_components) == 3:
            date_part = f"{date_components[2]}/{date_components[1]}/{date_components[0]}"
        time_part = parts[1][:5] if len(parts) > 1 else ''
        return f"{date_part} {time_part}".strip()
    except (IndexError, AttributeError):
        return str(date_str)


# --- SQL FRAGMENT CONSTANTS ---
HIDE_BLINKS_SQL = "(is_blink = 0 OR is_blink IS NULL)"
HIDE_BURSTS_SQL = "(is_burst_lead = 1 OR is_burst_lead IS NULL)"
HIDE_DUPLICATES_SQL = "(is_duplicate_lead = 1 OR is_duplicate_lead IS NULL OR duplicate_group_id IS NULL)"


DATE_FILTER_EXPR = "DATE(REPLACE(SUBSTR(date_taken,1,10),':','-'))"


def build_date_range_clauses(date_from, date_to):
    """Build WHERE clauses for date range filtering on EXIF date_taken."""
    clauses, params = [], []
    if date_from:
        clauses.append(f"{DATE_FILTER_EXPR} >= ?")
        params.append(date_from)
    if date_to:
        clauses.append(f"{DATE_FILTER_EXPR} <= ?")
        params.append(date_to)
    return clauses, params


def build_hide_clauses(hide_blinks: str, hide_bursts: str, hide_duplicates: str) -> list[str]:
    """Convert hide-toggle string params ('1'/'true') to SQL WHERE fragments."""
    clauses = []
    if hide_blinks in ('1', 'true'):
        clauses.append(HIDE_BLINKS_SQL)
    if hide_bursts in ('1', 'true'):
        clauses.append(HIDE_BURSTS_SQL)
    if hide_duplicates in ('1', 'true'):
        clauses.append(HIDE_DUPLICATES_SQL)
    return clauses

# Column lists shared by gallery and person viewer
PHOTO_BASE_COLS = [
    'path', 'filename', 'date_taken', 'camera_model', 'lens_model', 'iso',
    'f_stop', 'shutter_speed', 'focal_length', 'aesthetic', 'face_count', 'face_quality',
    'eye_sharpness', 'face_sharpness', 'face_ratio', 'tech_sharpness', 'color_score',
    'exposure_score', 'comp_score', 'isolation_bonus', 'is_blink', 'phash', 'is_burst_lead',
    'aggregate', 'category', 'image_width', 'image_height'
]
PHOTO_OPTIONAL_COLS = [
    'histogram_spread', 'mean_luminance', 'power_point_score',
    'shadow_clipped', 'highlight_clipped', 'is_silhouette', 'is_group_portrait', 'leading_lines_score',
    'face_confidence', 'is_monochrome', 'mean_saturation',
    'dynamic_range_stops', 'noise_sigma', 'contrast_score', 'tags',
    'composition_pattern', 'quality_score', 'topiq_score',
    'aesthetic_iaa', 'face_quality_iqa', 'liqe_score',
    'qalign_score', 'aesthetic_v25', 'deqa_score',
    'subject_sharpness', 'subject_prominence', 'subject_placement', 'bg_separation',
    'star_rating', 'is_favorite', 'is_rejected',
    'duplicate_group_id', 'is_duplicate_lead',
    'caption', 'caption_translated', 'gps_latitude', 'gps_longitude',
    'dominant_hue', 'color_temp',
]


def get_existing_columns(conn=None):
    """Get list of columns that exist in the photos table. Cached after first call."""
    global _existing_columns_cache
    with _existing_columns_lock:
        if _existing_columns_cache is not None:
            return _existing_columns_cache

    if conn is None:
        conn = get_db_connection()
        try:
            cursor = conn.execute('PRAGMA table_info(photos)')
            result = {row[1] for row in cursor.fetchall()}
        finally:
            conn.close()
    else:
        cursor = conn.execute('PRAGMA table_info(photos)')
        result = {row[1] for row in cursor.fetchall()}

    from api import config as _config_mod
    with _existing_columns_lock:
        _existing_columns_cache = result
        _config_mod._existing_columns_cache = result
    return _existing_columns_cache


def invalidate_existing_columns_cache():
    """Clear the existing-columns cache.

    Call after ``init_database()`` if it added columns (e.g. lifespan
    startup, or if a deploy hot-runs schema migrations). Without this,
    queries continue to use the stale PHOTO_OPTIONAL_COLS subset and
    miss newly-added columns until the API restarts.
    """
    global _existing_columns_cache
    from api import config as _config_mod
    with _existing_columns_lock:
        _existing_columns_cache = None
        _config_mod._existing_columns_cache = None


def is_photo_tags_available(conn=None):
    """Check if the photo_tags lookup table exists and has data.

    Result is TTL-cached (5 min by default; see ``PHOTO_TAGS_CACHE_TTL``).
    Without a TTL the cache stayed permanently False on a fresh DB even
    after the operator ran ``database.py --migrate-tags`` while the API
    was up — the lookup table would be populated but the API would
    continue using the slow LIKE fallback until restart.

    Cache-warm path (within TTL) returns instantly without touching
    ``conn`` — safe to call from an async context with an aiosqlite
    Connection as long as the lifespan startup or a prior call warmed it.
    """
    global _photo_tags_available
    from api import config as _config_mod
    import time
    now = time.monotonic()
    with _photo_tags_lock:
        if (_photo_tags_available is not None
                and (now - _config_mod._photo_tags_checked_at) < PHOTO_TAGS_CACHE_TTL):
            return _photo_tags_available

    # Cold path / TTL expired: only fire if a sync sqlite3.Connection was
    # provided, or open a fresh one. Passing an aiosqlite Connection here
    # would be a programmer error — refuse rather than emit a
    # coroutine-never-awaited warning.
    if conn is not None and not isinstance(conn, sqlite3.Connection):
        # Fall through to open our own sync connection.
        conn = None

    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    try:
        row = conn.execute("SELECT COUNT(*) FROM photo_tags").fetchone()
        result = row[0] > 0 if row else False
    except sqlite3.OperationalError:
        logger.debug("photo_tags table not available", exc_info=True)
        result = False

    if close_conn:
        conn.close()

    with _photo_tags_lock:
        _photo_tags_available = result
        _config_mod._photo_tags_available = result
        _config_mod._photo_tags_checked_at = now
    return _photo_tags_available


_art_tags_cache = None


def _add_tag_filter(where_clauses, sql_params, tag=None, require_tags=None, exclude_tags=None, exclude_art_tags=None, conn=None):
    """Build tag-related WHERE clauses using photo_tags table when available."""
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
    """Get list of art tags from scoring config (cached)."""
    global _art_tags_cache
    if _art_tags_cache is not None:
        return _art_tags_cache

    config = ScoringConfig()
    art_config = config.get_category_config('art')
    if art_config:
        filters = art_config.get('filters', {})
        required_tags = filters.get('required_tags', [])
        if required_tags:
            _art_tags_cache = list(required_tags)
            return _art_tags_cache
        tags = art_config.get('tags', {})
        if isinstance(tags, dict):
            _art_tags_cache = list(tags.keys())
            return _art_tags_cache

    _art_tags_cache = ['painting', 'statue', 'mural', 'drawing', 'cartoon', 'anime']
    return _art_tags_cache


def _count_cache_lookup(cache_key):
    """Return cached count if fresh, else None."""
    now = time.time()
    with _count_cache_lock:
        if cache_key in _count_cache:
            count, ts = _count_cache[cache_key]
            if now - ts < COUNT_CACHE_TTL:
                return count
    return None


def _count_cache_store(cache_key, count):
    now = time.time()
    with _count_cache_lock:
        _count_cache[cache_key] = (count, now)
        if len(_count_cache) > 100:
            expired = [k for k, (_, ts) in _count_cache.items() if now - ts > COUNT_CACHE_TTL * 2]
            for k in expired:
                del _count_cache[k]


def get_cached_count(conn, where_str, sql_params, from_clause="photos"):
    """Cache COUNT results to avoid repeated full-table scans."""
    cache_key = hashlib.sha256(f"{from_clause}:{where_str}:{tuple(sql_params)}".encode()).hexdigest()
    cached = _count_cache_lookup(cache_key)
    if cached is not None:
        return cached

    row = conn.execute(f"SELECT COUNT(*) FROM {from_clause}{where_str}", sql_params).fetchone()
    count = row[0] if row else 0
    _count_cache_store(cache_key, count)
    return count


async def get_cached_count_async(conn, where_str, sql_params, from_clause="photos"):
    """Async variant of get_cached_count for aiosqlite paths."""
    cache_key = hashlib.sha256(f"{from_clause}:{where_str}:{tuple(sql_params)}".encode()).hexdigest()
    cached = _count_cache_lookup(cache_key)
    if cached is not None:
        return cached

    cursor = await conn.execute(f"SELECT COUNT(*) FROM {from_clause}{where_str}", sql_params)
    row = await cursor.fetchone()
    await cursor.close()
    count = row[0] if row else 0
    _count_cache_store(cache_key, count)
    return count



def paginate(total: int, page: int, per_page: int) -> tuple[int, int]:
    """Calculate pagination values.

    Returns (total_pages, offset).
    """
    total_pages = max(1, math.ceil(total / per_page))
    offset = (page - 1) * per_page
    return total_pages, offset


def sanitize_float_values(data):
    """Replace NaN/Infinity with None in a list of dicts."""
    for item in data:
        for key, value in item.items():
            if isinstance(value, float) and (math.isinf(value) or math.isnan(value)):
                item[key] = None
    return data


def build_photo_select_columns(conn, user_id=None):
    """Build the SELECT column list for photo queries.

    Resolves existing columns, applies user-preference overrides for
    star_rating / is_favorite / is_rejected, and returns a list of SQL
    column expressions ready to join into a SELECT clause.
    """
    existing_cols = get_existing_columns(conn)
    pref_cols = get_preference_columns(user_id)
    pref_col_names = {'star_rating', 'is_favorite', 'is_rejected'}

    # Skip caption_translated when translation is disabled (target_language empty or "en")
    target_lang = _FULL_CONFIG.get('translation', {}).get('target_language', '')
    skip_cols = set()
    if not target_lang or target_lang == 'en':
        skip_cols.add('caption_translated')

    select_cols = list(PHOTO_BASE_COLS)
    for c in PHOTO_OPTIONAL_COLS:
        if c in existing_cols and c not in skip_cols:
            if c in pref_col_names:
                select_cols.append(f"{pref_cols[c]} as {c}")
            else:
                select_cols.append(c)
    return select_cols


def update_person_face_count(conn, person_id):
    """Update a person's face_count from the faces table."""
    conn.execute("""
        UPDATE persons SET face_count = (
            SELECT COUNT(*) FROM faces WHERE person_id = ?
        ) WHERE id = ?
    """, (person_id, person_id))


def reassign_faces_to_person(conn, person_id, face_ids):
    """Reassign a set of faces to ``person_id``; auto-delete emptied old persons.

    Validates that every face_id exists, moves them to the new person, refreshes
    face_count on both old and new persons, and deletes any old person whose
    face_count drops to zero.

    Returns a dict with: ``assigned_count``, ``face_count`` (final count on
    ``person_id``), and ``deleted_persons`` (list of auto-deleted old IDs).
    Raises ``LookupError`` if any face_id is unknown.
    """
    if not face_ids:
        return {"assigned_count": 0, "face_count": 0, "deleted_persons": []}

    # Dedup face_ids so the existence check below isn't tripped up by duplicates
    # collapsing in SQL's IN-set semantics (SELECT IN (5,5,6) returns one row for 5,
    # producing a false-negative len-mismatch even though both IDs exist).
    face_ids = list(dict.fromkeys(face_ids))

    placeholders = ",".join("?" * len(face_ids))
    existing = conn.execute(
        f"SELECT id, person_id FROM faces WHERE id IN ({placeholders})",
        face_ids,
    ).fetchall()
    if len(existing) != len(face_ids):
        raise LookupError("One or more face_ids not found")

    old_person_ids = {
        row["person_id"] for row in existing
        if row["person_id"] is not None and row["person_id"] != person_id
    }

    conn.execute(
        f"UPDATE faces SET person_id = ? WHERE id IN ({placeholders})",
        [person_id] + list(face_ids),
    )

    update_person_face_count(conn, person_id)
    deleted_persons = []
    for old_id in old_person_ids:
        update_person_face_count(conn, old_id)
        row = conn.execute(
            "SELECT face_count FROM persons WHERE id = ?", (old_id,)
        ).fetchone()
        if row and row[0] == 0:
            conn.execute("DELETE FROM persons WHERE id = ?", (old_id,))
            deleted_persons.append(old_id)

    row = conn.execute(
        "SELECT face_count FROM persons WHERE id = ?", (person_id,)
    ).fetchone()
    return {
        "assigned_count": len(face_ids),
        "face_count": row[0] if row else 0,
        "deleted_persons": deleted_persons,
    }


def split_photo_tags(rows, tags_limit):
    """Convert DB rows to dicts with pre-split tags_list."""
    photos = []
    for row in rows:
        photo = dict(row)
        if photo.get('tags'):
            photo['tags_list'] = [t.strip() for t in photo['tags'].split(',')[:tags_limit]]
        else:
            photo['tags_list'] = []
        photos.append(photo)
    return photos


_PERSONS_FOR_PATHS_TMPL = """
    SELECT DISTINCT f.photo_path, f.person_id, p.name
    FROM faces f
    JOIN persons p ON p.id = f.person_id
    WHERE f.photo_path IN ({placeholders})
      AND f.person_id IS NOT NULL
"""

_UNASSIGNED_FOR_PATHS_TMPL = """
    SELECT photo_path, COUNT(*) as unassigned_count
    FROM faces
    WHERE photo_path IN ({placeholders})
      AND person_id IS NULL
    GROUP BY photo_path
"""


def _apply_person_data(photos, person_rows, unassigned_rows):
    """Mutate ``photos`` in place from the two query result sets.

    Extracted from ``attach_person_data_async`` so the post-query mapping
    logic is pure (no DB access) and unit-testable.
    """
    path_to_persons: dict[str, list[dict]] = {}
    for row in person_rows:
        path = row['photo_path']
        path_to_persons.setdefault(path, []).append({
            'id': row['person_id'],
            'name': row['name'] or f"Person {row['person_id']}",
        })
    path_to_unassigned = {row['photo_path']: row['unassigned_count'] for row in unassigned_rows}
    for photo in photos:
        photo['persons'] = path_to_persons.get(photo['path'], [])
        photo['unassigned_faces'] = path_to_unassigned.get(photo['path'], 0)


async def attach_person_data_async(photos, conn):
    """Async variant: same shape, awaits aiosqlite cursors."""
    if not photos:
        return
    try:
        photo_paths = [p['path'] for p in photos]
        placeholders = ','.join(['?'] * len(photo_paths))
        cursor = await conn.execute(
            _PERSONS_FOR_PATHS_TMPL.format(placeholders=placeholders),
            photo_paths,
        )
        person_rows = await cursor.fetchall()
        await cursor.close()
        cursor = await conn.execute(
            _UNASSIGNED_FOR_PATHS_TMPL.format(placeholders=placeholders),
            photo_paths,
        )
        unassigned_rows = await cursor.fetchall()
        await cursor.close()
        _apply_person_data(photos, person_rows, unassigned_rows)
    except Exception:
        logger.exception("Failed to attach person data (async)")
        for photo in photos:
            photo['persons'] = []
            photo['unassigned_faces'] = 0


# --- MULTI-USER VISIBILITY & PREFERENCES ---

def get_visibility_clause(user_id, table_alias='photos'):
    """Returns (sql_fragment, params) for photo visibility in multi-user mode.

    Args:
        user_id: The current user ID (or None).
        table_alias: Table name or alias to qualify the path column (default: 'photos').
    """
    if not user_id or not is_multi_user_enabled():
        return '1=1', []

    all_dirs = get_user_directories(user_id)
    if not all_dirs:
        return '0=1', []

    conditions = []
    params = []
    for d in all_dirs:
        prefix = d.rstrip('/\\') + '/'
        conditions.append(f"{table_alias}.path LIKE ?")
        params.append(prefix + '%')

    return f"({' OR '.join(conditions)})", params


def get_photos_from_clause(user_id=None):
    """Build FROM clause for gallery queries."""
    if user_id and is_multi_user_enabled():
        return ("photos LEFT JOIN user_preferences up "
                "ON up.photo_path = photos.path AND up.user_id = ?"), [user_id]
    return "photos", []


def get_preference_columns(user_id=None):
    """Get SQL column expressions for user-preference columns."""
    if user_id and is_multi_user_enabled():
        return {
            'star_rating': 'COALESCE(up.star_rating, 0)',
            'is_favorite': 'COALESCE(up.is_favorite, 0)',
            'is_rejected': 'COALESCE(up.is_rejected, 0)',
        }
    return {
        'star_rating': 'photos.star_rating',
        'is_favorite': 'photos.is_favorite',
        'is_rejected': 'photos.is_rejected',
    }


def set_photos_rejected(conn, paths, user_id):
    """Mark photos as rejected, honoring multi-user per-user preferences and visibility.

    Resolves the caller's visible subset of ``paths`` first, then records the
    rejection per-user in ``user_preferences`` (multi-user mode) or in the global
    ``photos`` table (single-user). This keeps bulk culling/scene rejects consistent
    with the per-user read path (``get_preference_columns``) and the single-photo
    toggle in ``api/routers/faces.py``. Returns the number of photos affected.
    """
    if not paths:
        return 0
    vis_sql, vis_params = get_visibility_clause(user_id)
    placeholders = ','.join('?' * len(paths))
    visible = [r[0] for r in conn.execute(
        f"SELECT path FROM photos WHERE path IN ({placeholders}) AND {vis_sql}",
        list(paths) + vis_params,
    ).fetchall()]
    if not visible:
        return 0
    if user_id and is_multi_user_enabled():
        conn.executemany(
            "INSERT INTO user_preferences (user_id, photo_path, is_rejected) "
            "VALUES (?, ?, 1) "
            "ON CONFLICT(user_id, photo_path) DO UPDATE SET is_rejected = 1",
            [(user_id, p) for p in visible],
        )
    else:
        ph = ','.join('?' * len(visible))
        conn.execute(f"UPDATE photos SET is_rejected = 1 WHERE path IN ({ph})", visible)
    return len(visible)


def _jpeg_dimensions(blob):
    """Extract width/height from a JPEG blob by parsing SOF markers."""
    data = bytes(blob)
    i = 0
    if data[0:2] != b'\xff\xd8':
        return None, None
    i = 2
    while i < len(data) - 1:
        if data[i] != 0xFF:
            break
        marker = data[i + 1]
        if marker == 0xD9:  # EOI
            break
        if marker in (0xD0, 0xD1, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0x01):
            i += 2
            continue
        if i + 3 >= len(data):
            break
        length = struct.unpack('>H', data[i + 2:i + 4])[0]
        # SOF markers: C0-C3, C5-C7, C9-CB, CD-CF
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                      0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            if i + 9 <= len(data):
                height = struct.unpack('>H', data[i + 5:i + 7])[0]
                width = struct.unpack('>H', data[i + 7:i + 9])[0]
                return width, height
        i += 2 + length
    return None, None


def backfill_image_dimensions():
    """Backfill image_width/image_height from thumbnail BLOBs for NULL rows."""
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM photos WHERE image_width IS NULL OR image_height IS NULL"
        ).fetchone()
        null_count = row[0] if row else 0
        if null_count == 0:
            return

        cursor = conn.execute(
            "SELECT path, thumbnail FROM photos "
            "WHERE (image_width IS NULL OR image_height IS NULL) AND thumbnail IS NOT NULL"
        )

        updated = 0
        for row in cursor:
            w, h = _jpeg_dimensions(row['thumbnail'])
            if w and h:
                conn.execute(
                    "UPDATE photos SET image_width = ?, image_height = ? WHERE path = ?",
                    (w, h, row['path'])
                )
                updated += 1

        if updated:
            conn.commit()
            logger.info("Backfilled image dimensions for %d/%d photos from thumbnails", updated, null_count)
    finally:
        conn.close()
