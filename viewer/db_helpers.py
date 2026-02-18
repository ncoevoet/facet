import sqlite3
import hashlib
import time
from db import DEFAULT_DB_PATH, apply_pragmas
from config import ScoringConfig
from viewer.config import VIEWER_CONFIG, _filter_options_cache, _existing_columns_cache, _photo_tags_available, _count_cache, COUNT_CACHE_TTL, is_multi_user_enabled, get_user_directories

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
    'aggregate', 'category'
]
PHOTO_OPTIONAL_COLS = [
    'histogram_spread', 'mean_luminance', 'power_point_score',
    'shadow_clipped', 'highlight_clipped', 'is_silhouette', 'is_group_portrait', 'leading_lines_score',
    'face_confidence', 'is_monochrome', 'mean_saturation',
    'dynamic_range_stops', 'noise_sigma', 'contrast_score', 'tags',
    'composition_pattern', 'quality_score',
    'star_rating', 'is_favorite', 'is_rejected',
    'duplicate_group_id', 'is_duplicate_lead'
]


# --- DATABASE HELPERS ---
_viewer_perf = VIEWER_CONFIG.get('performance', {})


def get_db_connection():
    """Get database connection with WAL mode and row factory.

    Uses viewer.performance overrides if configured, otherwise falls back
    to global performance settings from scoring_config.json.
    Returns a plain connection (caller must close).
    """
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


def get_cached_count(conn, where_str, sql_params, from_clause="photos"):
    """Cache COUNT results to avoid repeated full-table scans.

    Uses a short TTL (30s) to balance performance with freshness.
    Cache key is based on the WHERE clause, parameters, and FROM clause.
    """
    # Build cache key from query components
    cache_key = hashlib.md5(f"{from_clause}:{where_str}:{tuple(sql_params)}".encode()).hexdigest()

    now = time.time()
    if cache_key in _count_cache:
        count, ts = _count_cache[cache_key]
        if now - ts < COUNT_CACHE_TTL:
            return count

    # Execute count query
    count = conn.execute(f"SELECT COUNT(*) FROM {from_clause}{where_str}", sql_params).fetchone()[0]

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

        # Get tags with counts, ordered by frequency
        try:
            max_tags = VIEWER_CONFIG['dropdowns']['max_tags']
            tag_query = """
                WITH RECURSIVE split_tags(tag, rest) AS (
                    SELECT '', tags || ',' FROM photos WHERE tags IS NOT NULL AND tags != ''
                    UNION ALL
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

        # Get composition patterns with counts
        try:
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
    """Returns (sql_fragment, params) for photo visibility in multi-user mode.

    Each user can see photos from their configured directories + shared directories.
    Uses LIKE 'prefix%' which leverages the PRIMARY KEY B-tree index on photos.path.
    """
    if not user_id or not is_multi_user_enabled():
        return '1=1', []

    all_dirs = get_user_directories(user_id)
    if not all_dirs:
        return '0=1', []  # No directories = no access

    conditions = []
    params = []
    for d in all_dirs:
        prefix = d.rstrip('/\\') + '/'
        conditions.append("photos.path LIKE ?")
        params.append(prefix + '%')

    return f"({' OR '.join(conditions)})", params


def get_photos_from_clause(user_id=None):
    """Build FROM clause for gallery queries.

    In multi-user mode, LEFT JOINs user_preferences to get per-user ratings.
    Returns (from_sql, extra_params).
    """
    if user_id and is_multi_user_enabled():
        return ("photos LEFT JOIN user_preferences up "
                "ON up.photo_path = photos.path AND up.user_id = ?"), [user_id]
    return "photos", []


def get_preference_columns(user_id=None):
    """Get SQL column expressions for user-preference columns.

    In multi-user mode, reads from user_preferences JOIN.
    In legacy mode, reads from photos table directly.
    Returns dict mapping column name to SQL expression.
    """
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
