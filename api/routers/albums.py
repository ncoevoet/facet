"""
Albums router — user-curated photo collections and smart albums.

"""

import json
import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from api.auth import CurrentUser, get_optional_user, require_edition
from api.config import VIEWER_CONFIG
from api.database import get_db_connection
from api.db_helpers import (
    get_existing_columns, get_visibility_clause, get_photos_from_clause,
    get_preference_columns, PHOTO_BASE_COLS, PHOTO_OPTIONAL_COLS,
    split_photo_tags, attach_person_data, format_date,
)

router = APIRouter(tags=["albums"])


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
    return {
        'id': album['id'],
        'name': album['name'],
        'description': album['description'],
        'cover_photo_path': album['cover_photo_path'],
        'is_smart': bool(album['is_smart']),
        'smart_filter_json': album['smart_filter_json'],
        'created_at': album['created_at'],
        'updated_at': album['updated_at'],
    }


def _get_first_photo_path(conn, album_row, user_id=None):
    """Get the first photo path for an album (for cover display)."""
    if album_row['cover_photo_path']:
        return album_row['cover_photo_path']
    if album_row['is_smart'] and album_row['smart_filter_json']:
        try:
            from api.routers.gallery import _build_gallery_where
            saved_filters = json.loads(album_row['smart_filter_json'])
            where_clauses, sql_params = _build_gallery_where(saved_filters, conn, user_id=user_id)
            from_clause, from_params = get_photos_from_clause(user_id)
            all_params = from_params + sql_params
            where_str = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
            row = conn.execute(
                f"SELECT path FROM {from_clause}{where_str} ORDER BY aggregate DESC LIMIT 1",
                all_params
            ).fetchone()
            return row['path'] if row else None
        except Exception:
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
):
    """List all albums accessible to the current user."""
    conn = get_db_connection()
    try:
        user_id = _get_user_id(user)
        if user_id:
            rows = conn.execute(
                "SELECT * FROM albums WHERE user_id = ? OR user_id IS NULL ORDER BY updated_at DESC",
                (user_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM albums ORDER BY updated_at DESC"
            ).fetchall()

        albums = []
        for row in rows:
            album = _album_to_dict(row)
            album['photo_count'] = conn.execute(
                "SELECT COUNT(*) FROM album_photos WHERE album_id = ?", (row['id'],)
            ).fetchone()[0]
            # Get first photo path for cover display
            album['first_photo_path'] = _get_first_photo_path(conn, row, user_id)
            albums.append(album)

        return {'albums': albums}
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
        result['photo_count'] = conn.execute(
            "SELECT COUNT(*) FROM album_photos WHERE album_id = ?", (album_id,)
        ).fetchone()[0]
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
        result['photo_count'] = conn.execute(
            "SELECT COUNT(*) FROM album_photos WHERE album_id = ?", (album_id,)
        ).fetchone()[0]
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
    conn = get_db_connection()
    try:
        user_id = _get_user_id(user)
        _check_album_access(conn, album_id, user_id)

        # Get current max position
        max_pos = conn.execute(
            "SELECT COALESCE(MAX(position), -1) FROM album_photos WHERE album_id = ?",
            (album_id,)
        ).fetchone()[0]

        added = 0
        for i, path in enumerate(body.photo_paths):
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO album_photos (album_id, photo_path, position) VALUES (?, ?, ?)",
                    (album_id, path, max_pos + 1 + i)
                )
                added += conn.execute("SELECT changes()").fetchone()[0]
            except Exception:
                pass

        # Auto-set cover if not set
        album = conn.execute("SELECT cover_photo_path FROM albums WHERE id = ?", (album_id,)).fetchone()
        if not album['cover_photo_path'] and body.photo_paths:
            conn.execute(
                "UPDATE albums SET cover_photo_path = ?, updated_at = datetime('now') WHERE id = ?",
                (body.photo_paths[0], album_id)
            )

        conn.execute("UPDATE albums SET updated_at = datetime('now') WHERE id = ?", (album_id,))
        conn.commit()

        count = conn.execute(
            "SELECT COUNT(*) FROM album_photos WHERE album_id = ?", (album_id,)
        ).fetchone()[0]
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

        count = conn.execute(
            "SELECT COUNT(*) FROM album_photos WHERE album_id = ?", (album_id,)
        ).fetchone()[0]
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
        page = int(qp.get('page', 1))
        per_page = int(qp.get('per_page', VIEWER_CONFIG['pagination']['default_per_page']))
        sort = qp.get('sort', 'position')
        sort_dir = 'ASC' if qp.get('sort_direction', 'ASC') == 'ASC' else 'DESC'

        # Smart album: use saved filters
        if album['is_smart'] and album['smart_filter_json']:
            from api.routers.gallery import _build_gallery_where
            saved_filters = json.loads(album['smart_filter_json'])
            where_clauses, sql_params = _build_gallery_where(saved_filters, conn, user_id=user_id)
            from_clause, from_params = get_photos_from_clause(user_id)
            all_params = from_params + sql_params
            where_str = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

            total = conn.execute(
                f"SELECT COUNT(*) FROM {from_clause}{where_str}", all_params
            ).fetchone()[0]

            existing_cols = get_existing_columns(conn)
            pref_cols = get_preference_columns(user_id)
            pref_col_names = {'star_rating', 'is_favorite', 'is_rejected'}
            select_cols = list(PHOTO_BASE_COLS)
            for c in PHOTO_OPTIONAL_COLS:
                if c in existing_cols:
                    select_cols.append(f"{pref_cols[c]} as {c}" if c in pref_col_names else c)

            safe_sort = sort if sort in ('aggregate', 'aesthetic', 'date_taken', 'comp_score', 'tech_sharpness') else 'aggregate'
            rows = conn.execute(
                f"SELECT {', '.join(select_cols)} FROM {from_clause}{where_str} "
                f"ORDER BY {safe_sort} {sort_dir} LIMIT ? OFFSET ?",
                all_params + [per_page, (page - 1) * per_page]
            ).fetchall()
        else:
            # Regular album: join with album_photos
            vis_sql, vis_params = get_visibility_clause(user_id)
            from_clause, from_params = get_photos_from_clause(user_id)

            total = conn.execute(
                f"SELECT COUNT(*) FROM album_photos ap "
                f"JOIN {from_clause} ON photos.path = ap.photo_path "
                f"WHERE ap.album_id = ? AND {vis_sql}",
                from_params + [album_id] + vis_params
            ).fetchone()[0]

            existing_cols = get_existing_columns(conn)
            pref_cols = get_preference_columns(user_id)
            pref_col_names = {'star_rating', 'is_favorite', 'is_rejected'}
            select_cols = list(PHOTO_BASE_COLS)
            for c in PHOTO_OPTIONAL_COLS:
                if c in existing_cols:
                    select_cols.append(f"{pref_cols[c]} as {c}" if c in pref_col_names else c)

            safe_sort = sort if sort in ('aggregate', 'aesthetic', 'date_taken', 'comp_score', 'tech_sharpness', 'position') else 'ap.position'
            if sort == 'position':
                safe_sort = 'ap.position'

            rows = conn.execute(
                f"SELECT {', '.join(select_cols)} FROM album_photos ap "
                f"JOIN {from_clause} ON photos.path = ap.photo_path "
                f"WHERE ap.album_id = ? AND {vis_sql} "
                f"ORDER BY {safe_sort} {sort_dir} LIMIT ? OFFSET ?",
                from_params + [album_id] + vis_params + [per_page, (page - 1) * per_page]
            ).fetchall()

        tags_limit = VIEWER_CONFIG['display']['tags_per_photo']
        photos = split_photo_tags(rows, tags_limit)
        for photo in photos:
            photo['date_formatted'] = format_date(photo.get('date_taken'))
        attach_person_data(photos, conn)

        for photo in photos:
            for key, value in photo.items():
                if isinstance(value, float) and (math.isinf(value) or math.isnan(value)):
                    photo[key] = None

        total_pages = max(1, math.ceil(total / per_page))
        return {
            'photos': photos,
            'total': total,
            'page': page,
            'per_page': per_page,
            'total_pages': total_pages,
            'has_more': page < total_pages,
        }
    finally:
        conn.close()
