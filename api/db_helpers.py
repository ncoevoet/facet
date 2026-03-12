"""
Database helper functions for the FastAPI API server.

"""

import hashlib
import logging
import struct
import time
from config import ScoringConfig

logger = logging.getLogger("facet.api.db_helpers")
from api.config import (
    _existing_columns_cache,
    _photo_tags_available, _count_cache, COUNT_CACHE_TTL,
    is_multi_user_enabled, get_user_directories
)
from api.database import get_db_connection

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
    'subject_sharpness', 'subject_prominence', 'subject_placement', 'bg_separation',
    'star_rating', 'is_favorite', 'is_rejected',
    'duplicate_group_id', 'is_duplicate_lead'
]


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


def get_cached_count(conn, where_str, sql_params, from_clause="photos"):
    """Cache COUNT results to avoid repeated full-table scans."""
    cache_key = hashlib.sha256(f"{from_clause}:{where_str}:{tuple(sql_params)}".encode()).hexdigest()

    now = time.time()
    if cache_key in _count_cache:
        count, ts = _count_cache[cache_key]
        if now - ts < COUNT_CACHE_TTL:
            return count

    count = conn.execute(f"SELECT COUNT(*) FROM {from_clause}{where_str}", sql_params).fetchone()[0]
    _count_cache[cache_key] = (count, now)

    if len(_count_cache) > 100:
        expired = [k for k, (_, ts) in _count_cache.items() if now - ts > COUNT_CACHE_TTL * 2]
        for k in expired:
            del _count_cache[k]

    return count



def update_person_face_count(conn, person_id):
    """Update a person's face_count from the faces table."""
    conn.execute("""
        UPDATE persons SET face_count = (
            SELECT COUNT(*) FROM faces WHERE person_id = ?
        ) WHERE id = ?
    """, (person_id, person_id))


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


def attach_person_data(photos, conn):
    """Batch-fetch person associations and unassigned face counts for photos."""
    if not photos:
        return
    try:
        photo_paths = [p['path'] for p in photos]
        placeholders = ','.join(['?'] * len(photo_paths))
        person_rows = conn.execute(f"""
            SELECT DISTINCT f.photo_path, f.person_id, p.name
            FROM faces f
            JOIN persons p ON p.id = f.person_id
            WHERE f.photo_path IN ({placeholders})
              AND f.person_id IS NOT NULL
        """, photo_paths).fetchall()

        path_to_persons = {}
        for row in person_rows:
            path = row['photo_path']
            if path not in path_to_persons:
                path_to_persons[path] = []
            path_to_persons[path].append({
                'id': row['person_id'],
                'name': row['name'] or f"Person {row['person_id']}"
            })

        unassigned_rows = conn.execute(f"""
            SELECT photo_path, COUNT(*) as unassigned_count
            FROM faces
            WHERE photo_path IN ({placeholders})
              AND person_id IS NULL
            GROUP BY photo_path
        """, photo_paths).fetchall()
        path_to_unassigned = {row['photo_path']: row['unassigned_count'] for row in unassigned_rows}

        for photo in photos:
            photo['persons'] = path_to_persons.get(photo['path'], [])
            photo['unassigned_faces'] = path_to_unassigned.get(photo['path'], 0)
    except Exception:
        for photo in photos:
            photo['persons'] = []
            photo['unassigned_faces'] = 0


# --- MULTI-USER VISIBILITY & PREFERENCES ---

def get_visibility_clause(user_id):
    """Returns (sql_fragment, params) for photo visibility in multi-user mode."""
    if not user_id or not is_multi_user_enabled():
        return '1=1', []

    all_dirs = get_user_directories(user_id)
    if not all_dirs:
        return '0=1', []

    conditions = []
    params = []
    for d in all_dirs:
        prefix = d.rstrip('/\\') + '/'
        conditions.append("photos.path LIKE ?")
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
        null_count = conn.execute(
            "SELECT COUNT(*) FROM photos WHERE image_width IS NULL OR image_height IS NULL"
        ).fetchone()[0]
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
