"""
Albums router — user-curated photo collections and smart albums.

"""

import hmac
import json
import logging
import math
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from api.auth import CurrentUser, get_optional_user, require_edition
from api.config import VIEWER_CONFIG
from api.database import get_db_connection
from api.db_helpers import (
    get_visibility_clause, get_photos_from_clause,
    build_photo_select_columns, sanitize_float_values,
    split_photo_tags, attach_person_data, format_date,
)
from api.types import VALID_SORT_COLS, SORT_OPTIONS_GROUPED, normalize_params

router = APIRouter(tags=["albums"])
logger = logging.getLogger(__name__)


# --- Request models ---

class CreateAlbumRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = ''
    is_smart: bool = False
    smart_filter_json: Optional[str] = None


class UpdateAlbumRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    cover_photo_path: Optional[str] = None
    is_smart: Optional[bool] = None
    smart_filter_json: Optional[str] = None


class AlbumPhotosRequest(BaseModel):
    photo_paths: list[str]


# --- Helpers ---

def _normalize_smart_filters(filters):
    """Normalize smart album filter keys to match _build_gallery_where() expectations.

    The Angular store saves person_id/type/quality, but the backend expects person/category/min_score.
    """
    result = dict(filters)
    if 'person_id' in result:
        result['person'] = result.pop('person_id')
    return normalize_params(result)


def _get_user_id(user):
    return user.user_id if user else None


def _check_album_access(conn, album_id, user_id):
    """Fetch album and verify ownership. Returns album row or raises 404/403."""
    album = conn.execute("SELECT * FROM albums WHERE id = ?", (album_id,)).fetchone()
    if not album:
        raise HTTPException(status_code=404, detail="Album not found")
    if album['user_id'] and album['user_id'] != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    return album


def _album_to_dict(album):
    """Convert album row to API response dict."""
    result = {
        'id': album['id'],
        'name': album['name'],
        'description': album['description'],
        'cover_photo_path': album['cover_photo_path'],
        'is_smart': bool(album['is_smart']),
        'smart_filter_json': album['smart_filter_json'],
        'created_at': album['created_at'],
        'updated_at': album['updated_at'],
    }
    try:
        result['is_shared'] = bool(album['share_token'])
    except (IndexError, KeyError):
        result['is_shared'] = False
    return result


def _fetch_album_photos(conn, album_row, user_id, page, per_page, sort_col, sort_dir, filters=None):
    """Fetch paginated photos for an album (smart or regular).

    Returns a dict with keys: photos, total, page, per_page, total_pages, has_more.
    ``filters`` is an optional dict of additional filter params (camera, lens, tag, date_from, etc.)
    applied via ``_build_gallery_where`` for regular albums.
    """
    # Smart album: use saved filters
    if album_row['is_smart'] and album_row['smart_filter_json']:
        from api.routers.gallery import _build_gallery_where
        saved_filters = json.loads(album_row['smart_filter_json'])
        saved_filters = _normalize_smart_filters(saved_filters)
        where_clauses, sql_params = _build_gallery_where(saved_filters, conn, user_id=user_id)
        from_clause, from_params = get_photos_from_clause(user_id)
        all_params = from_params + sql_params
        where_str = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        row = conn.execute(
            f"SELECT COUNT(*) FROM {from_clause}{where_str}", all_params
        ).fetchone()
        total = row[0] if row else 0

        select_cols = build_photo_select_columns(conn, user_id)

        safe_sort = sort_col if sort_col in VALID_SORT_COLS else 'aggregate'
        rows = conn.execute(
            f"SELECT {', '.join(select_cols)} FROM {from_clause}{where_str} "
            f"ORDER BY {safe_sort} {sort_dir} LIMIT ? OFFSET ?",
            all_params + [per_page, (page - 1) * per_page]
        ).fetchall()
    else:
        # Regular album: join with album_photos
        from_clause, from_params = get_photos_from_clause(user_id)
        base_where = ["ap.album_id = ?"]
        base_params = [album_row['id']]

        vis_sql, vis_params = get_visibility_clause(user_id)
        base_where.append(vis_sql)
        base_params.extend(vis_params)

        # Apply additional filters via _build_gallery_where
        if filters:
            from api.routers.gallery import _build_gallery_where
            extra_clauses, extra_params = _build_gallery_where(filters, conn)
            base_where.extend(extra_clauses)
            base_params.extend(extra_params)

        where_str = " AND ".join(base_where)

        row = conn.execute(
            f"SELECT COUNT(*) FROM album_photos ap "
            f"JOIN {from_clause} ON photos.path = ap.photo_path "
            f"WHERE {where_str}",
            from_params + base_params
        ).fetchone()
        total = row[0] if row else 0

        select_cols = build_photo_select_columns(conn, user_id)

        safe_sort = sort_col if sort_col in VALID_SORT_COLS else 'ap.position'
        if sort_col == 'position':
            safe_sort = 'ap.position'

        rows = conn.execute(
            f"SELECT {', '.join(select_cols)} FROM album_photos ap "
            f"JOIN {from_clause} ON photos.path = ap.photo_path "
            f"WHERE {where_str} "
            f"ORDER BY {safe_sort} {sort_dir} LIMIT ? OFFSET ?",
            from_params + base_params + [per_page, (page - 1) * per_page]
        ).fetchall()

    tags_limit = VIEWER_CONFIG['display']['tags_per_photo']
    photos = split_photo_tags(rows, tags_limit)
    for photo in photos:
        photo['date_formatted'] = format_date(photo.get('date_taken'))
    attach_person_data(photos, conn)

    sanitize_float_values(photos)

    total_pages = max(1, math.ceil(total / per_page))
    return {
        'photos': photos,
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': total_pages,
        'has_more': page < total_pages,
    }


def _get_album_filter_options(conn, album_id):
    """Return filter dropdown options scoped to a regular album's photos."""
    base = (
        "SELECT {col}, COUNT(*) as cnt FROM album_photos ap "
        "JOIN photos ON photos.path = ap.photo_path "
        "WHERE ap.album_id = ? AND {col} IS NOT NULL "
        "GROUP BY {col} ORDER BY cnt DESC"
    )
    cameras = conn.execute(base.format(col='camera_model'), (album_id,)).fetchall()
    lenses = conn.execute(base.format(col='lens_model'), (album_id,)).fetchall()
    tags_rows = conn.execute(
        "SELECT pt.tag, COUNT(*) as cnt FROM album_photos ap "
        "JOIN photo_tags pt ON pt.photo_path = ap.photo_path "
        "WHERE ap.album_id = ? "
        "GROUP BY pt.tag ORDER BY cnt DESC",
        (album_id,),
    ).fetchall()
    patterns = conn.execute(
        "SELECT composition_pattern, COUNT(*) as cnt FROM album_photos ap "
        "JOIN photos ON photos.path = ap.photo_path "
        "WHERE ap.album_id = ? AND composition_pattern IS NOT NULL AND composition_pattern != '' "
        "GROUP BY composition_pattern ORDER BY cnt DESC",
        (album_id,),
    ).fetchall()
    categories = conn.execute(
        "SELECT category, COUNT(*) as cnt FROM album_photos ap "
        "JOIN photos ON photos.path = ap.photo_path "
        "WHERE ap.album_id = ? AND category IS NOT NULL AND category != '' "
        "GROUP BY category ORDER BY cnt DESC",
        (album_id,),
    ).fetchall()
    return {
        'cameras': [{'value': r[0], 'count': r[1]} for r in cameras],
        'lenses': [{'value': r[0], 'count': r[1]} for r in lenses],
        'tags': [{'value': r[0], 'count': r[1]} for r in tags_rows],
        'patterns': [{'value': r[0], 'count': r[1]} for r in patterns],
        'categories': [{'value': r[0], 'count': r[1]} for r in categories],
    }


def _get_first_photo_path(conn, album_row, user_id=None):
    """Get the first photo path for an album (for cover display)."""
    if album_row['cover_photo_path']:
        return album_row['cover_photo_path']
    if album_row['is_smart'] and album_row['smart_filter_json']:
        try:
            from api.routers.gallery import _build_gallery_where
            saved_filters = json.loads(album_row['smart_filter_json'])
            saved_filters = _normalize_smart_filters(saved_filters)
            # Apply viewer defaults for hide filters (excluded from smart_filter_json but active by default)
            defaults = VIEWER_CONFIG.get('defaults', {})
            for key in ('hide_blinks', 'hide_bursts', 'hide_duplicates', 'hide_rejected'):
                if key not in saved_filters:
                    saved_filters[key] = '1' if defaults.get(key, False) else '0'
            where_clauses, sql_params = _build_gallery_where(saved_filters, conn, user_id=user_id)
            from_clause, from_params = get_photos_from_clause(user_id)
            all_params = from_params + sql_params
            where_str = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
            sort_col = saved_filters.get('sort', 'aggregate')
            if sort_col not in VALID_SORT_COLS:
                sort_col = 'aggregate'
            if sort_col == 'top_picks_score':
                from api.top_picks import get_top_picks_score_sql
                sort_col = f"({get_top_picks_score_sql()})"
            sort_dir = 'ASC' if saved_filters.get('sort_direction') == 'ASC' else 'DESC'
            row = conn.execute(
                f"SELECT path FROM {from_clause}{where_str} ORDER BY {sort_col} {sort_dir}, path ASC LIMIT 1",
                all_params
            ).fetchone()
            return row['path'] if row else None
        except Exception:
            logger.debug("Failed to resolve smart album cover photo", exc_info=True)
            return None
    # Manual album: get first photo from album_photos
    row = conn.execute(
        "SELECT photo_path FROM album_photos WHERE album_id = ? ORDER BY position ASC LIMIT 1",
        (album_row['id'],)
    ).fetchone()
    return row['photo_path'] if row else None


# --- Endpoints ---

@router.get("/api/albums")
async def list_albums(
    user: Optional[CurrentUser] = Depends(get_optional_user),
    page: int = Query(1, ge=1),
    per_page: int = Query(48, ge=1, le=200),
    search: str = Query(""),
    type: str = Query(""),
    sort: str = Query("updated_at"),
):
    """List all albums accessible to the current user with pagination."""
    conn = get_db_connection()
    try:
        user_id = _get_user_id(user)

        where_clauses = []
        params: list = []
        if user_id:
            where_clauses.append("(user_id = ? OR user_id IS NULL)")
            params.append(user_id)
        if search.strip():
            where_clauses.append("(name LIKE ? OR description LIKE ?)")
            params.extend([f"%{search.strip()}%", f"%{search.strip()}%"])
        if type == 'smart':
            where_clauses.append("is_smart = 1")
        elif type == 'manual':
            where_clauses.append("(is_smart = 0 OR is_smart IS NULL)")

        where_str = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        # Total count
        row = conn.execute(f"SELECT COUNT(*) FROM albums{where_str}", params).fetchone()
        total = row[0] if row else 0

        # Paginated fetch
        _SORT_MAP = {'updated_at': 'updated_at DESC', 'name': 'name ASC', 'photo_count': 'photo_count_cache DESC'}
        order_by = _SORT_MAP.get(sort, 'updated_at DESC')
        # photo_count sort needs a subquery since it's not a column
        if sort == 'photo_count':
            order_by = '(SELECT COUNT(*) FROM album_photos WHERE album_id = albums.id) DESC'
        offset = (page - 1) * per_page
        rows = conn.execute(
            f"SELECT * FROM albums{where_str} ORDER BY {order_by} LIMIT ? OFFSET ?",
            params + [per_page, offset]
        ).fetchall()

        # Batch-fetch photo counts for this page's albums (avoids N+1 queries)
        album_ids = [row['id'] for row in rows]
        count_map = {}
        if album_ids:
            placeholders = ','.join(['?'] * len(album_ids))
            count_rows = conn.execute(
                f"SELECT album_id, COUNT(*) as cnt FROM album_photos WHERE album_id IN ({placeholders}) GROUP BY album_id",
                album_ids
            ).fetchall()
            count_map = {r['album_id']: r['cnt'] for r in count_rows}

        albums = []
        for row in rows:
            album = _album_to_dict(row)
            album['photo_count'] = count_map.get(row['id'], 0)
            album['first_photo_path'] = _get_first_photo_path(conn, row, user_id)
            albums.append(album)

        total_pages = max(1, math.ceil(total / per_page))
        return {
            'albums': albums,
            'total': total,
            'page': page,
            'per_page': per_page,
            'total_pages': total_pages,
            'has_more': page < total_pages,
        }
    finally:
        conn.close()


@router.post("/api/albums")
async def create_album(
    body: CreateAlbumRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Create a new album."""
    conn = get_db_connection()
    try:
        user_id = _get_user_id(user)
        cursor = conn.execute(
            """INSERT INTO albums (user_id, name, description, is_smart, smart_filter_json)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, body.name, body.description, 1 if body.is_smart else 0,
             body.smart_filter_json)
        )
        conn.commit()
        album = conn.execute("SELECT * FROM albums WHERE id = ?", (cursor.lastrowid,)).fetchone()
        result = _album_to_dict(album)
        result['photo_count'] = 0
        return result
    finally:
        conn.close()


@router.get("/api/albums/{album_id}")
async def get_album(
    album_id: int,
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Get album details with photo count."""
    conn = get_db_connection()
    try:
        user_id = _get_user_id(user)
        album = _check_album_access(conn, album_id, user_id)
        result = _album_to_dict(album)
        row = conn.execute(
            "SELECT COUNT(*) FROM album_photos WHERE album_id = ?", (album_id,)
        ).fetchone()
        result['photo_count'] = row[0] if row else 0
        return result
    finally:
        conn.close()


@router.put("/api/albums/{album_id}")
async def update_album(
    album_id: int,
    body: UpdateAlbumRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Update album name, description, or cover photo."""
    conn = get_db_connection()
    try:
        user_id = _get_user_id(user)
        _check_album_access(conn, album_id, user_id)

        updates = []
        params = []
        if body.name is not None:
            updates.append("name = ?")
            params.append(body.name)
        if body.description is not None:
            updates.append("description = ?")
            params.append(body.description)
        if body.cover_photo_path is not None:
            updates.append("cover_photo_path = ?")
            params.append(body.cover_photo_path)
        if body.is_smart is not None:
            updates.append("is_smart = ?")
            params.append(1 if body.is_smart else 0)
        if body.smart_filter_json is not None:
            updates.append("smart_filter_json = ?")
            params.append(body.smart_filter_json)

        if updates:
            updates.append("updated_at = datetime('now')")
            params.append(album_id)
            conn.execute(f"UPDATE albums SET {', '.join(updates)} WHERE id = ?", params)
            conn.commit()

        album = conn.execute("SELECT * FROM albums WHERE id = ?", (album_id,)).fetchone()
        result = _album_to_dict(album)
        row = conn.execute(
            "SELECT COUNT(*) FROM album_photos WHERE album_id = ?", (album_id,)
        ).fetchone()
        result['photo_count'] = row[0] if row else 0
        return result
    finally:
        conn.close()


@router.delete("/api/albums/{album_id}")
async def delete_album(
    album_id: int,
    user: CurrentUser = Depends(require_edition),
):
    """Delete an album and its photo associations."""
    conn = get_db_connection()
    try:
        user_id = _get_user_id(user)
        _check_album_access(conn, album_id, user_id)
        conn.execute("DELETE FROM album_photos WHERE album_id = ?", (album_id,))
        conn.execute("DELETE FROM albums WHERE id = ?", (album_id,))
        conn.commit()
        return {'ok': True}
    finally:
        conn.close()


@router.post("/api/albums/{album_id}/photos")
async def add_photos_to_album(
    album_id: int,
    body: AlbumPhotosRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Add photos to an album (batch)."""
    if not body.photo_paths:
        raise HTTPException(status_code=400, detail="photo_paths must not be empty")
    conn = get_db_connection()
    try:
        user_id = _get_user_id(user)
        _check_album_access(conn, album_id, user_id)

        # Get current max position
        row = conn.execute(
            "SELECT COALESCE(MAX(position), -1) FROM album_photos WHERE album_id = ?",
            (album_id,)
        ).fetchone()
        max_pos = row[0] if row else -1

        added = 0
        for i, path in enumerate(body.photo_paths):
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO album_photos (album_id, photo_path, position) VALUES (?, ?, ?)",
                    (album_id, path, max_pos + 1 + i)
                )
                row = conn.execute("SELECT changes()").fetchone()
                added += row[0] if row else 0
            except Exception:
                logger.debug("Failed to add photo %s to album %s", path, album_id, exc_info=True)

        # Auto-set cover if not set
        album = conn.execute("SELECT cover_photo_path FROM albums WHERE id = ?", (album_id,)).fetchone()
        if not album['cover_photo_path'] and body.photo_paths:
            conn.execute(
                "UPDATE albums SET cover_photo_path = ?, updated_at = datetime('now') WHERE id = ?",
                (body.photo_paths[0], album_id)
            )

        conn.execute("UPDATE albums SET updated_at = datetime('now') WHERE id = ?", (album_id,))
        conn.commit()

        row = conn.execute(
            "SELECT COUNT(*) FROM album_photos WHERE album_id = ?", (album_id,)
        ).fetchone()
        count = row[0] if row else 0
        return {'ok': True, 'added': added, 'photo_count': count}
    finally:
        conn.close()


@router.delete("/api/albums/{album_id}/photos")
async def remove_photos_from_album(
    album_id: int,
    body: AlbumPhotosRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Remove photos from an album (batch)."""
    if not body.photo_paths:
        raise HTTPException(status_code=400, detail="photo_paths must not be empty")
    conn = get_db_connection()
    try:
        user_id = _get_user_id(user)
        _check_album_access(conn, album_id, user_id)

        placeholders = ','.join(['?'] * len(body.photo_paths))
        conn.execute(
            f"DELETE FROM album_photos WHERE album_id = ? AND photo_path IN ({placeholders})",
            [album_id] + body.photo_paths
        )
        conn.execute("UPDATE albums SET updated_at = datetime('now') WHERE id = ?", (album_id,))
        conn.commit()

        row = conn.execute(
            "SELECT COUNT(*) FROM album_photos WHERE album_id = ?", (album_id,)
        ).fetchone()
        count = row[0] if row else 0
        return {'ok': True, 'photo_count': count}
    finally:
        conn.close()


@router.get("/api/albums/{album_id}/photos")
async def get_album_photos(
    request: Request,
    album_id: int,
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Get photos in an album with pagination and sorting."""
    conn = get_db_connection()
    try:
        user_id = _get_user_id(user)
        album = _check_album_access(conn, album_id, user_id)

        qp = dict(request.query_params)
        try:
            page = max(1, int(qp.get('page', 1)))
        except (ValueError, TypeError):
            page = 1
        try:
            per_page = min(max(1, int(qp.get('per_page', VIEWER_CONFIG['pagination']['default_per_page']))), 200)
        except (ValueError, TypeError):
            per_page = VIEWER_CONFIG['pagination']['default_per_page']
        sort = qp.get('sort', 'position')
        sort_dir = 'ASC' if qp.get('sort_direction', 'ASC') == 'ASC' else 'DESC'

        return _fetch_album_photos(conn, album, user_id, page, per_page, sort, sort_dir)
    finally:
        conn.close()


# --- Sharing endpoints ---

@router.post("/api/albums/{album_id}/share")
async def share_album(
    album_id: int,
    user: CurrentUser = Depends(require_edition),
):
    """Generate a share token for public album access."""
    conn = get_db_connection()
    try:
        user_id = _get_user_id(user)
        album = _check_album_access(conn, album_id, user_id)
        # Reuse existing token if already shared, otherwise generate a new random one
        try:
            existing_token = album['share_token']
        except (IndexError, KeyError):
            existing_token = None
        token = existing_token or secrets.token_urlsafe(32)
        conn.execute("UPDATE albums SET share_token = ? WHERE id = ?", (token, album_id))
        conn.commit()
        return {
            'share_url': f"/shared/album/{album_id}?token={token}",
            'share_token': token,
        }
    finally:
        conn.close()


@router.delete("/api/albums/{album_id}/share")
async def unshare_album(
    album_id: int,
    user: CurrentUser = Depends(require_edition),
):
    """Revoke public sharing for an album."""
    conn = get_db_connection()
    try:
        user_id = _get_user_id(user)
        _check_album_access(conn, album_id, user_id)
        conn.execute("UPDATE albums SET share_token = NULL WHERE id = ?", (album_id,))
        conn.commit()
        return {'ok': True}
    finally:
        conn.close()


@router.get("/api/shared/album/{album_id}")
async def get_shared_album(
    request: Request,
    album_id: int,
    token: str = Query(...),
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Public endpoint to view a shared album via token."""
    conn = get_db_connection()
    try:
        album = conn.execute("SELECT * FROM albums WHERE id = ?", (album_id,)).fetchone()
        if not album:
            raise HTTPException(status_code=404, detail="Album not found")

        # Verify token matches the stored share_token
        try:
            stored_token = album['share_token']
            if not stored_token or not hmac.compare_digest(stored_token, token):
                raise HTTPException(status_code=403, detail="Invalid share token")
        except (IndexError, KeyError):
            raise HTTPException(status_code=403, detail="Sharing not available")

        user_id = _get_user_id(user)
        qp = dict(request.query_params)
        try:
            page = max(1, int(qp.get('page', 1)))
        except (ValueError, TypeError):
            page = 1
        try:
            per_page = min(max(1, int(qp.get('per_page', VIEWER_CONFIG['pagination']['default_per_page']))), 200)
        except (ValueError, TypeError):
            per_page = VIEWER_CONFIG['pagination']['default_per_page']

        explicit_sort = qp.get('sort')
        explicit_sort_dir = qp.get('sort_direction')

        # For smart albums with no explicit sort, use saved sort from smart_filter_json
        is_manual = not album['is_smart']
        saved_sort = None
        saved_sort_dir = None
        if not is_manual and album['smart_filter_json']:
            try:
                smart_filters = json.loads(album['smart_filter_json'])
                saved_sort = smart_filters.get('sort')
                saved_sort_dir = smart_filters.get('sort_direction')
            except (ValueError, TypeError):
                pass

        sort = explicit_sort or saved_sort or 'aggregate'
        if sort not in VALID_SORT_COLS:
            sort = 'aggregate'
        effective_sort_dir = explicit_sort_dir or saved_sort_dir or 'DESC'
        sort_dir = 'ASC' if effective_sort_dir == 'ASC' else 'DESC'

        # Build filters dict from query params (for regular albums)
        filters = None
        if is_manual:
            _FILTER_KEYS = (
                'camera', 'lens', 'tag', 'date_from', 'date_to',
                'hide_blinks', 'hide_bursts', 'hide_duplicates',
                'composition_pattern', 'category', 'is_monochrome',
                # Range filters (quality, face, composition, saliency, technical, exposure, ratings)
                'min_score', 'max_score', 'min_aesthetic', 'max_aesthetic',
                'min_quality_score', 'max_quality_score',
                'min_aesthetic_iaa', 'max_aesthetic_iaa',
                'min_face_quality_iqa', 'max_face_quality_iqa',
                'min_liqe', 'max_liqe',
                'min_face_count', 'max_face_count',
                'min_face_quality', 'max_face_quality',
                'min_eye_sharpness', 'max_eye_sharpness',
                'min_face_sharpness', 'max_face_sharpness',
                'min_face_ratio', 'max_face_ratio',
                'min_face_confidence', 'max_face_confidence',
                'min_composition', 'max_composition',
                'min_power_point', 'max_power_point',
                'min_leading_lines', 'max_leading_lines',
                'min_isolation', 'max_isolation',
                'min_subject_sharpness', 'max_subject_sharpness',
                'min_subject_prominence', 'max_subject_prominence',
                'min_subject_placement', 'max_subject_placement',
                'min_bg_separation', 'max_bg_separation',
                'min_sharpness', 'max_sharpness',
                'min_exposure', 'max_exposure',
                'min_color', 'max_color',
                'min_contrast', 'max_contrast',
                'min_saturation', 'max_saturation',
                'min_noise', 'max_noise',
                'min_dynamic_range', 'max_dynamic_range',
                'min_luminance', 'max_luminance',
                'min_histogram_spread', 'max_histogram_spread',
                'min_iso', 'max_iso',
                'min_aperture', 'max_aperture',
                'min_focal_length', 'max_focal_length',
                'min_star_rating', 'max_star_rating',
            )
            filters = {k: qp[k] for k in _FILTER_KEYS if qp.get(k)}

        result = _fetch_album_photos(conn, album, user_id, page, per_page, sort, sort_dir, filters=filters)
        result['album'] = _album_to_dict(album)
        result['effective_sort'] = sort
        result['effective_sort_direction'] = sort_dir
        if SORT_OPTIONS_GROUPED:
            result['sort_options_grouped'] = SORT_OPTIONS_GROUPED

        # Include filter options for manual albums (first page only to avoid repeated work)
        if is_manual and page == 1:
            try:
                result['filter_options'] = _get_album_filter_options(conn, album['id'])
            except Exception:
                logger.debug("Failed to build album filter options", exc_info=True)

        return result
    finally:
        conn.close()
