from flask import request, jsonify
from db import DEFAULT_DB_PATH
from viewer.filter_options import filter_options_bp
from viewer.config import VIEWER_CONFIG, is_multi_user_enabled
from viewer.db_helpers import get_db_connection, is_photo_tags_available, get_visibility_clause
from viewer.auth import get_session_user_id


# =============================================================================
# Lazy Filter Options API Endpoints (Performance Optimization)
# =============================================================================


def _vis_where():
    """Return (where_fragment, params) for visibility filtering in filter option queries."""
    user_id = get_session_user_id()
    if not user_id:
        return '', []
    vis_sql, vis_params = get_visibility_clause(user_id)
    if vis_sql == '1=1':
        return '', []
    return f' AND {vis_sql}', vis_params


def _cached_filter_query(cache_key, result_key, query_fn):
    """Generic cache-then-query helper for filter option endpoints.

    Args:
        cache_key: Stats cache key (e.g., 'cameras', 'lenses')
        result_key: JSON response key (e.g., 'cameras', 'lenses')
        query_fn: Function that takes a db connection and returns results list
    """
    from db import get_cached_stat
    # Only use global stats cache in single-user mode
    if not is_multi_user_enabled():
        data, is_fresh = get_cached_stat(DEFAULT_DB_PATH, cache_key, max_age_seconds=300)
        if data and is_fresh:
            return jsonify({result_key: data, 'cached': True})

    with get_db_connection() as conn:
        data = query_fn(conn)
    return jsonify({result_key: data, 'cached': False})


@filter_options_bp.route('/api/filter_options/cameras')
def api_filter_options_cameras():
    """Lazy-load camera options with counts."""
    vis, vp = _vis_where()
    def query(conn):
        rows = conn.execute(f"""
            SELECT camera_model, COUNT(*) as cnt FROM photos
            WHERE camera_model IS NOT NULL{vis}
            GROUP BY camera_model ORDER BY cnt DESC LIMIT ?
        """, vp + [VIEWER_CONFIG['dropdowns']['max_cameras']]).fetchall()
        return [(r[0], r[1]) for r in rows]
    return _cached_filter_query('cameras', 'cameras', query)


@filter_options_bp.route('/api/filter_options/lenses')
def api_filter_options_lenses():
    """Lazy-load lens options with counts."""
    vis, vp = _vis_where()
    def query(conn):
        rows = conn.execute(f"""
            SELECT lens_model, COUNT(*) as cnt FROM photos
            WHERE lens_model IS NOT NULL{vis}
            GROUP BY lens_model ORDER BY cnt DESC LIMIT ?
        """, vp + [VIEWER_CONFIG['dropdowns']['max_lenses']]).fetchall()
        return [(r[0], r[1]) for r in rows]
    return _cached_filter_query('lenses', 'lenses', query)


@filter_options_bp.route('/api/filter_options/tags')
def api_filter_options_tags():
    """API endpoint for lazy-loading tag options.

    Returns tags with counts, sorted by frequency.
    Uses stats_cache if available and fresh, with fast photo_tags query as fallback.
    """
    from db import get_cached_stat

    max_tags = VIEWER_CONFIG['dropdowns']['max_tags']
    vis, vp = _vis_where()

    # Try cached data first (only in single-user mode)
    if not is_multi_user_enabled():
        tags, is_fresh = get_cached_stat(DEFAULT_DB_PATH, 'tags', max_age_seconds=300)
        if tags and is_fresh:
            return jsonify({'tags': tags[:max_tags], 'cached': True})

    with get_db_connection() as conn:
        # Try fast photo_tags table first
        if is_photo_tags_available(conn):
            try:
                rows = conn.execute(f"""
                    SELECT tag, COUNT(*) as cnt
                    FROM photo_tags
                    WHERE 1=1{' AND photo_path IN (SELECT path FROM photos WHERE 1=1' + vis + ')' if vis else ''}
                    GROUP BY tag
                    ORDER BY cnt DESC, tag ASC
                    LIMIT ?
                """, vp + [max_tags]).fetchall()
                tags = [(r[0], r[1]) for r in rows]
                return jsonify({'tags': tags, 'cached': False})
            except Exception:
                pass

        # Fall back to recursive CTE (slow but works without photo_tags)
        tag_query = f"""
            WITH RECURSIVE split_tags(tag, rest) AS (
                SELECT '', tags || ',' FROM photos WHERE tags IS NOT NULL AND tags != ''{vis}
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
            rows = conn.execute(tag_query, vp + [max_tags]).fetchall()
            tags = [(r[0], r[1]) for r in rows]
        except Exception:
            tags = []

    return jsonify({'tags': tags, 'cached': False})


@filter_options_bp.route('/api/filter_options/persons')
def api_filter_options_persons():
    """Lazy-load person options with photo counts."""
    vis, vp = _vis_where()
    def query(conn):
        try:
            min_photos = VIEWER_CONFIG['dropdowns'].get('min_photos_for_person', 1)
            vis_join = f' AND f.photo_path IN (SELECT path FROM photos WHERE 1=1{vis})' if vis else ''
            rows = conn.execute(f"""
                SELECT p.id, p.name, COUNT(DISTINCT f.photo_path) as photo_count
                FROM persons p
                JOIN faces f ON f.person_id = p.id
                WHERE 1=1{vis_join}
                GROUP BY p.id HAVING photo_count >= ?
                ORDER BY photo_count DESC LIMIT ?
            """, vp + [min_photos, VIEWER_CONFIG['dropdowns']['max_persons']]).fetchall()
            return [(r[0], r[1], r[2]) for r in rows]
        except Exception:
            return []
    return _cached_filter_query('persons', 'persons', query)


@filter_options_bp.route('/api/filter_options/patterns')
def api_filter_options_patterns():
    """Lazy-load composition pattern options with counts."""
    vis, vp = _vis_where()
    def query(conn):
        try:
            rows = conn.execute(f"""
                SELECT composition_pattern, COUNT(*) as cnt FROM photos
                WHERE composition_pattern IS NOT NULL AND composition_pattern != ''{vis}
                GROUP BY composition_pattern ORDER BY cnt DESC
            """, vp).fetchall()
            return [(r[0], r[1]) for r in rows]
        except Exception:
            return []
    return _cached_filter_query('composition_patterns', 'patterns', query)


@filter_options_bp.route('/api/filter_options/categories')
def api_filter_options_categories():
    """Lazy-load category options with counts."""
    vis, vp = _vis_where()
    def query(conn):
        try:
            rows = conn.execute(f"""
                SELECT category, COUNT(*) as cnt FROM photos
                WHERE category IS NOT NULL{vis}
                GROUP BY category ORDER BY cnt DESC
            """, vp).fetchall()
            return [(r[0], r[1]) for r in rows]
        except Exception:
            return []
    return _cached_filter_query('categories', 'categories', query)

