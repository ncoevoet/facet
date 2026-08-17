"""
Albums router — user-curated photo collections and smart albums.

"""

import hashlib
import hmac
import json
import logging
import secrets
import sqlite3
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from api.auth import CurrentUser, get_optional_user, require_edition
from api.config import VIEWER_CONFIG
from api.database import get_async_db, get_db
from api.db_helpers import (
    get_visibility_clause, get_photos_from_clause,
    build_photo_select_columns, sanitize_float_values,
    split_photo_tags, attach_person_data_async, format_date, paginate,
    is_access_controlled_install,
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


class AlbumScoringContextRequest(BaseModel):
    scoring_context: str


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
    """Fetch album and verify ownership. Returns album row or raises 404/403.

    On a fully open single-user install (no multi-user, no viewer password) the
    library is world-readable, so album ownership must not deny access — legacy
    albums owned by ``_legacy`` stay reachable when ``get_optional_user`` yields
    no user. When the install IS access-controlled the ownership check is
    unchanged.
    """
    album = conn.execute("SELECT * FROM albums WHERE id = ?", (album_id,)).fetchone()
    if not album:
        raise HTTPException(status_code=404, detail="Album not found")
    if is_access_controlled_install() and album['user_id'] != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    return album


async def _check_album_access_async(conn, album_id, user_id):
    """Async variant of _check_album_access for aiosqlite paths."""
    cur = await conn.execute("SELECT * FROM albums WHERE id = ?", (album_id,))
    album = await cur.fetchone()
    await cur.close()
    if not album:
        raise HTTPException(status_code=404, detail="Album not found")
    if is_access_controlled_install() and album['user_id'] != user_id:
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
    try:
        result['scoring_context'] = album['scoring_context']
    except (IndexError, KeyError):
        result['scoring_context'] = None
    return result


async def _fetch_album_photos(conn, album_row, user_id, page, per_page, sort_col, sort_dir, filters=None):
    """Fetch paginated photos for an album (smart or regular). Async.

    ``conn`` must be an aiosqlite Connection. ``_build_gallery_where`` is
    called with this Connection — its internal helpers (is_photo_tags_
    available, get_existing_columns) are cache-warmed by lifespan startup,
    so they don't try to call ``.execute()`` on the async connection.

    Returns a dict with keys: photos, total, page, per_page, total_pages, has_more.
    """
    # build_photo_select_columns reads the lifespan-warmed
    # _existing_columns_cache and never touches conn — safe with aiosqlite.
    select_cols = build_photo_select_columns(conn=None, user_id=user_id)

    if album_row['is_smart'] and album_row['smart_filter_json']:
        # Smart album: evaluate the saved filter with the album OWNER's visibility,
        # not the viewer's. A shared smart album must stay scoped to the owner's
        # library regardless of who holds the share token, otherwise it leaks every
        # DB photo matching the filter (including other users' photos).
        owner_id = album_row['user_id']
        select_cols = build_photo_select_columns(conn=None, user_id=owner_id)
        from api.routers.gallery import _build_gallery_where
        saved_filters = json.loads(album_row['smart_filter_json'])
        saved_filters = _normalize_smart_filters(saved_filters)
        where_clauses, sql_params = _build_gallery_where(saved_filters, conn, user_id=owner_id)
        from_clause, from_params = get_photos_from_clause(owner_id)
        all_params = from_params + sql_params
        where_str = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        cur = await conn.execute(
            f"SELECT COUNT(*) FROM {from_clause}{where_str}", all_params
        )
        row = await cur.fetchone()
        await cur.close()
        total = row[0] if row else 0

        safe_sort = sort_col if sort_col in VALID_SORT_COLS else 'aggregate'
        cur = await conn.execute(
            f"SELECT {', '.join(select_cols)} FROM {from_clause}{where_str} "
            f"ORDER BY {safe_sort} {sort_dir} LIMIT ? OFFSET ?",
            all_params + [per_page, (page - 1) * per_page]
        )
        rows = await cur.fetchall()
        await cur.close()
    else:
        # Regular album: join with album_photos
        from_clause, from_params = get_photos_from_clause(user_id)
        base_where = ["ap.album_id = ?"]
        base_params = [album_row['id']]

        vis_sql, vis_params = get_visibility_clause(user_id)
        base_where.append(vis_sql)
        base_params.extend(vis_params)

        if filters:
            from api.routers.gallery import _build_gallery_where
            extra_clauses, extra_params = _build_gallery_where(filters, conn)
            base_where.extend(extra_clauses)
            base_params.extend(extra_params)

        where_str = " AND ".join(base_where)

        cur = await conn.execute(
            f"SELECT COUNT(*) FROM album_photos ap "
            f"JOIN {from_clause} ON photos.path = ap.photo_path "
            f"WHERE {where_str}",
            from_params + base_params
        )
        row = await cur.fetchone()
        await cur.close()
        total = row[0] if row else 0

        safe_sort = sort_col if sort_col in VALID_SORT_COLS else 'ap.position'
        if sort_col == 'position':
            safe_sort = 'ap.position'

        cur = await conn.execute(
            f"SELECT {', '.join(select_cols)} FROM album_photos ap "
            f"JOIN {from_clause} ON photos.path = ap.photo_path "
            f"WHERE {where_str} "
            f"ORDER BY {safe_sort} {sort_dir} LIMIT ? OFFSET ?",
            from_params + base_params + [per_page, (page - 1) * per_page]
        )
        rows = await cur.fetchall()
        await cur.close()

    tags_limit = VIEWER_CONFIG['display']['tags_per_photo']
    photos = split_photo_tags(rows, tags_limit)
    for photo in photos:
        photo['date_formatted'] = format_date(photo.get('date_taken'))
    await attach_person_data_async(photos, conn)

    sanitize_float_values(photos)

    total_pages, _ = paginate(total, page, per_page)
    return {
        'photos': photos,
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': total_pages,
        'has_more': page < total_pages,
    }


async def _get_album_filter_options(conn, album_id):
    """Return filter dropdown options scoped to a regular album's photos. Async."""
    base = (
        "SELECT {col}, COUNT(*) as cnt FROM album_photos ap "
        "JOIN photos ON photos.path = ap.photo_path "
        "WHERE ap.album_id = ? AND {col} IS NOT NULL "
        "GROUP BY {col} ORDER BY cnt DESC"
    )

    async def _all(query, params=()):
        cur = await conn.execute(query, params)
        rows = await cur.fetchall()
        await cur.close()
        return rows

    cameras = await _all(base.format(col='camera_model'), (album_id,))
    lenses = await _all(base.format(col='lens_model'), (album_id,))
    tags_rows = await _all(
        "SELECT pt.tag, COUNT(*) as cnt FROM album_photos ap "
        "JOIN photo_tags pt ON pt.photo_path = ap.photo_path "
        "WHERE ap.album_id = ? "
        "GROUP BY pt.tag ORDER BY cnt DESC",
        (album_id,),
    )
    patterns = await _all(
        "SELECT composition_pattern, COUNT(*) as cnt FROM album_photos ap "
        "JOIN photos ON photos.path = ap.photo_path "
        "WHERE ap.album_id = ? AND composition_pattern IS NOT NULL AND composition_pattern != '' "
        "GROUP BY composition_pattern ORDER BY cnt DESC",
        (album_id,),
    )
    categories = await _all(
        "SELECT category, COUNT(*) as cnt FROM album_photos ap "
        "JOIN photos ON photos.path = ap.photo_path "
        "WHERE ap.album_id = ? AND category IS NOT NULL AND category != '' "
        "GROUP BY category ORDER BY cnt DESC",
        (album_id,),
    )
    return {
        'cameras': [{'value': r[0], 'count': r[1]} for r in cameras],
        'lenses': [{'value': r[0], 'count': r[1]} for r in lenses],
        'tags': [{'value': r[0], 'count': r[1]} for r in tags_rows],
        'patterns': [{'value': r[0], 'count': r[1]} for r in patterns],
        'categories': [{'value': r[0], 'count': r[1]} for r in categories],
    }


_COVER_CACHE_TTL = 86400  # 24h — a smart album cover is just a thumbnail; staleness is fine


def _get_first_photo_path(conn, album_row):
    """Get the first photo path for an album (for cover display)."""
    if album_row['cover_photo_path']:
        return album_row['cover_photo_path']
    if album_row['is_smart'] and album_row['smart_filter_json']:
        return _smart_album_cover(conn, album_row)
    # Manual album: get first photo from album_photos
    row = conn.execute(
        "SELECT photo_path FROM album_photos WHERE album_id = ? ORDER BY position ASC LIMIT 1",
        (album_row['id'],)
    ).fetchone()
    return row['photo_path'] if row else None


def _cover_cache_key(album_row):
    """stats_cache key for a smart album's cover (id + filter/owner hash)."""
    digest = hashlib.md5(
        f"{album_row['smart_filter_json']}|{album_row['user_id']}".encode()).hexdigest()[:12]
    return f"album_cover_{album_row['id']}_{digest}"


def _smart_album_cover(conn, album_row):
    """Resolve a smart album's cover, caching the result in stats_cache.

    Picking a smart album's cover means running its full gallery filter + sort
    over the whole library — cheap once, but the albums list does it for every
    smart album on every page load. The cover is picked with the album OWNER's
    visibility (matching how ``_fetch_album_photos`` evaluates the album body),
    so it is stable across viewers and the ``--refresh-stats`` pre-warm actually
    hits. Cache the chosen path keyed by the album id plus a hash of its filter
    and owner, so a filter edit recomputes while an unchanged album is a single
    key lookup for ``_COVER_CACHE_TTL`` — turning the list from N full-library
    sorts into N key reads (see ``warm_smart_album_covers``).
    """
    owner_id = album_row['user_id']
    cache_key = _cover_cache_key(album_row)
    cached = conn.execute(
        "SELECT value, updated_at FROM stats_cache WHERE key = ?", (cache_key,)
    ).fetchone()
    if cached and (time.time() - cached['updated_at']) < _COVER_CACHE_TTL:
        return cached['value'] or None
    path = _compute_smart_album_cover(conn, album_row, owner_id)
    conn.execute(
        "INSERT OR REPLACE INTO stats_cache (key, value, updated_at) VALUES (?, ?, ?)",
        (cache_key, path or '', time.time()),
    )
    conn.commit()
    return path


def warm_smart_album_covers(db_path):
    """Precompute every smart album's cover into stats_cache (for --refresh-stats).

    Forces a fresh compute and store so the albums list never pays the per-album
    gallery sort on a cold cache. Albums with an explicit ``cover_photo_path`` are
    skipped (they never hit the sort). Returns the number of covers warmed.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM albums WHERE is_smart = 1 AND smart_filter_json IS NOT NULL "
            "AND (cover_photo_path IS NULL OR cover_photo_path = '')"
        ).fetchall()
        for row in rows:
            path = _compute_smart_album_cover(conn, row, row['user_id'])
            conn.execute(
                "INSERT OR REPLACE INTO stats_cache (key, value, updated_at) VALUES (?, ?, ?)",
                (_cover_cache_key(row), path or '', time.time()),
            )
        conn.commit()
        return len(rows)
    finally:
        conn.close()


def _compute_smart_album_cover(conn, album_row, user_id=None):
    """Run a smart album's filter + sort to pick its top photo as the cover."""
    try:
        from api.routers.gallery import _build_gallery_where
        saved_filters = json.loads(album_row['smart_filter_json'])
        saved_filters = _normalize_smart_filters(saved_filters)
        # Apply viewer defaults for hide filters (excluded from smart_filter_json but active by default)
        defaults = VIEWER_CONFIG.get('defaults', {})
        for key in ('hide_blinks', 'hide_bursts', 'hide_duplicates', 'hide_brackets',
                    'hide_panoramas', 'hide_rejected'):
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
    except (sqlite3.Error, json.JSONDecodeError, KeyError, TypeError):
        logger.debug("Failed to resolve smart album cover photo", exc_info=True)
        return None


# --- Endpoints ---

@router.get("/api/albums")
def list_albums(
    user: Optional[CurrentUser] = Depends(get_optional_user),
    page: int = Query(1, ge=1),
    per_page: int = Query(48, ge=1, le=200),
    search: str = Query(""),
    type: str = Query(""),
    sort: str = Query("updated_at"),
):
    """List all albums accessible to the current user with pagination."""
    with get_db() as conn:
        user_id = _get_user_id(user)

        where_clauses = []
        params: list = []
        if user_id:
            where_clauses.append("(user_id = ? OR user_id IS NULL)")
            params.append(user_id)
        elif is_access_controlled_install():
            # Anonymous on a locked/multi-user install must not enumerate every
            # album's names, paths and smart-filter JSON — fail closed.
            where_clauses.append("1=0")
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
        _SORT_MAP = {'updated_at': 'updated_at DESC', 'name': 'name ASC'}
        order_by = _SORT_MAP.get(sort, 'updated_at DESC')
        # photo_count has no column of its own — always resolved via this subquery,
        # never through _SORT_MAP, since album_photos rows are not cached on albums
        if sort == 'photo_count':
            order_by = '(SELECT COUNT(*) FROM album_photos WHERE album_id = albums.id) DESC'
        total_pages, offset = paginate(total, page, per_page)
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
            album['first_photo_path'] = _get_first_photo_path(conn, row)
            albums.append(album)
        return {
            'albums': albums,
            'total': total,
            'page': page,
            'per_page': per_page,
            'total_pages': total_pages,
            'has_more': page < total_pages,
        }


@router.post("/api/albums")
def create_album(
    body: CreateAlbumRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Create a new album."""
    with get_db() as conn:
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


@router.get("/api/albums/{album_id}")
def get_album(
    album_id: int,
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Get album details with photo count."""
    with get_db() as conn:
        user_id = _get_user_id(user)
        album = _check_album_access(conn, album_id, user_id)
        result = _album_to_dict(album)
        row = conn.execute(
            "SELECT COUNT(*) FROM album_photos WHERE album_id = ?", (album_id,)
        ).fetchone()
        result['photo_count'] = row[0] if row else 0
        return result


@router.put("/api/albums/{album_id}")
def update_album(
    album_id: int,
    body: UpdateAlbumRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Update album name, description, or cover photo."""
    with get_db() as conn:
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


@router.delete("/api/albums/{album_id}")
def delete_album(
    album_id: int,
    user: CurrentUser = Depends(require_edition),
):
    """Delete an album and its photo associations.

    ``photo_scoring_overrides`` has no FK to ``albums``, so deleting the
    album alone would leave every member permanently stamped with its
    scoring context. Clear only the overrides this album set (``source =
    'album:<id>'``) before dropping the album's own rows.
    """
    with get_db() as conn:
        user_id = _get_user_id(user)
        _check_album_access(conn, album_id, user_id)
        _clear_album_context_overrides(conn, album_id)
        conn.execute("DELETE FROM album_photos WHERE album_id = ?", (album_id,))
        conn.execute("DELETE FROM albums WHERE id = ?", (album_id,))
        conn.commit()
        return {'ok': True}


def _apply_album_scoring_context(conn, album_id, paths):
    """Materialize the album's declared scoring context onto ``paths``.

    A no-op when the album carries no context. Called from
    ``append_album_photos`` so photos added after ``PUT .../scoring_context``
    inherit it too, not just the members present at assignment time. A path
    already carrying a manual override is skipped — see
    ``set_album_scoring_context``.
    """
    row = conn.execute("SELECT scoring_context FROM albums WHERE id = ?", (album_id,)).fetchone()
    context = row['scoring_context'] if row else None
    if not context:
        return
    from db.scoring_overrides import set_photo_scoring_override
    existing_paths = _existing_photo_paths(conn, paths)
    manual_paths = _manual_override_paths(conn, existing_paths)
    for path in existing_paths:
        if path in manual_paths:
            continue
        set_photo_scoring_override(conn, path, scoring_context=context, source=f'album:{album_id}')


def _resolve_album_member_paths(conn, album_row):
    """Resolve an album's CURRENT member photo paths, sync.

    Smart albums carry no rows in ``album_photos`` — membership is computed
    at read time from ``smart_filter_json``. This mirrors the smart branch of
    ``_fetch_album_photos`` (owner-scoped visibility, saved filters via
    ``_build_gallery_where``) rather than reimplementing filter evaluation,
    just without pagination since callers here need every match. Regular
    albums read ``album_photos`` directly, unchanged.

    ``smart_filter_json`` carries only the filter the user actually chose
    (``sort``/``sort_direction``/``person``/etc.) — it deliberately does NOT
    include ``hide_blinks``/``hide_bursts``/``hide_duplicates``/
    ``hide_rejected``, which are global, runtime-toggleable gallery VIEW
    preferences (``viewer.defaults``), not part of the album's own
    definition. So this is the album's FILTER definition, not "whatever the
    gallery happened to be showing": the count returned here can legitimately
    exceed what the album's own gallery view displays with those hide-*
    toggles on, and that is intentional — a burst follower of the same scene
    is still a real member of e.g. an "action" smart album.

    Either way this is a snapshot of membership NOW: a caller that
    materializes something onto these paths (e.g. a scoring context) is
    stamping today's members, not subscribing to the filter — photos that
    start matching a smart filter later are not included.
    """
    if album_row['is_smart'] and album_row['smart_filter_json']:
        from api.routers.gallery import _build_gallery_where
        owner_id = album_row['user_id']
        saved_filters = _normalize_smart_filters(json.loads(album_row['smart_filter_json']))
        where_clauses, sql_params = _build_gallery_where(saved_filters, conn, user_id=owner_id)
        from_clause, from_params = get_photos_from_clause(owner_id)
        where_str = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        rows = conn.execute(
            f"SELECT path FROM {from_clause}{where_str}", from_params + sql_params
        ).fetchall()
        return [r['path'] for r in rows]

    rows = conn.execute(
        "SELECT photo_path FROM album_photos WHERE album_id = ?", (album_row['id'],)
    ).fetchall()
    return [r['photo_path'] for r in rows]


def _other_context_albums(conn, exclude_album_id):
    """Other albums (any type) that currently declare a non-null scoring context."""
    return conn.execute(
        "SELECT id, scoring_context, is_smart, smart_filter_json, user_id FROM albums "
        "WHERE scoring_context IS NOT NULL AND id != ?",
        (exclude_album_id,),
    ).fetchall()


def _photo_in_album(conn, album_row, path):
    """Whether ``path`` is currently a member of ``album_row`` (smart or manual)."""
    if album_row['is_smart'] and album_row['smart_filter_json']:
        from api.routers.gallery import _build_gallery_where
        owner_id = album_row['user_id']
        saved_filters = _normalize_smart_filters(json.loads(album_row['smart_filter_json']))
        where_clauses, sql_params = _build_gallery_where(saved_filters, conn, user_id=owner_id)
        from_clause, from_params = get_photos_from_clause(owner_id)
        where_str = f" WHERE {' AND '.join(list(where_clauses) + ['path = ?'])}"
        row = conn.execute(
            f"SELECT 1 FROM {from_clause}{where_str} LIMIT 1",
            from_params + sql_params + [path],
        ).fetchone()
        return row is not None
    row = conn.execute(
        "SELECT 1 FROM album_photos WHERE album_id = ? AND photo_path = ?", (album_row['id'], path)
    ).fetchone()
    return row is not None


def _clear_album_context_overrides(conn, album_id, paths=None):
    """Undo this album's scoring_context stamp on ``paths`` (or every member
    this album stamped, when ``paths`` is None).

    Scoped strictly to rows whose ``source`` is exactly this album's
    (``album:<id>``, written by ``set_album_scoring_context`` /
    ``_apply_album_scoring_context``) so a photo's own manual override, or a
    context a different album set, is never touched.

    A single ``source`` column cannot represent multi-album membership: when
    ``paths`` names a bounded set (a specific removal, e.g.
    ``remove_photos_from_album``), a path that is STILL a member of another
    album which itself declares a context is re-stamped with that other
    album's context instead of being left unscored — re-deriving from the
    albums that currently declare a context rather than the (unrecorded) set
    of albums that stamped this row historically. Full-album clears
    (``paths=None``, from ``delete_album`` / ``clear_album_scoring_context``)
    skip this re-derivation: testing every cleared photo against every other
    context-declaring album is unbounded for a smart album's full membership,
    and that photo's OWN album was just deleted/cleared, so there is no
    caller-scoped set to bound the check to.

    Returns the count cleared (re-stamped members are not counted as cleared).
    """
    from db.scoring_overrides import clear_photo_scoring_override, set_photo_scoring_override

    source = f'album:{album_id}'
    if paths is not None:
        if not paths:
            return 0
        from api.db_helpers import select_in_chunks
        rows = list(select_in_chunks(
            conn,
            "SELECT photo_path FROM photo_scoring_overrides "
            "WHERE source = ? AND scoring_context IS NOT NULL AND photo_path IN ({placeholders})",
            paths, before=[source],
        ))
    else:
        rows = conn.execute(
            "SELECT photo_path FROM photo_scoring_overrides WHERE source = ? AND scoring_context IS NOT NULL",
            (source,),
        ).fetchall()

    cleared_paths = [r['photo_path'] for r in rows]
    other_albums = _other_context_albums(conn, album_id) if paths is not None else []

    cleared = 0
    for path in cleared_paths:
        other = next((a for a in other_albums if _photo_in_album(conn, a, path)), None)
        if other is not None:
            set_photo_scoring_override(
                conn, path, scoring_context=other['scoring_context'], source=f"album:{other['id']}"
            )
        else:
            clear_photo_scoring_override(conn, path, field='scoring_context')
            cleared += 1
    return cleared


def _existing_photo_paths(conn, paths):
    """Keep only the paths that exist in ``photos``, preserving order.

    ``album_photos`` carries no foreign key, so a member can name a row that
    was never scanned or has since been cleaned up. ``photo_scoring_overrides``
    does have one, so writing an override for such a path raises IntegrityError
    and rolls back the whole assignment.
    """
    if not paths:
        return []
    from api.db_helpers import select_in_chunks
    known = {r[0] for r in select_in_chunks(
        conn, "SELECT path FROM photos WHERE path IN ({placeholders})", paths)}
    return [p for p in paths if p in known]


def _manual_override_paths(conn, paths):
    """Photo paths in ``paths`` whose scoring_context override was set manually.

    A manual override must never be silently converted into an album-sourced
    one, so callers that materialize an album's scoring context skip these
    paths entirely (both the value and the ``source`` provenance are left
    untouched).
    """
    if not paths:
        return set()
    from api.db_helpers import select_in_chunks
    rows = select_in_chunks(
        conn,
        "SELECT photo_path FROM photo_scoring_overrides "
        "WHERE source = 'manual' AND photo_path IN ({placeholders})",
        paths,
    )
    return {r['photo_path'] for r in rows}


def append_album_photos(conn, album_id, paths):
    """Append ``paths`` to an album at MAX(position)+1, idempotently.

    Shared by the add-photos endpoint and any feature that fills an album
    (e.g. auto-cull Highlights). ``INSERT OR IGNORE`` against
    ``UNIQUE(album_id, photo_path)`` keeps re-runs a no-op; a cover photo is
    set only when the album has none. Does NOT commit — the caller owns the
    transaction. Returns the number of rows actually inserted.
    """
    if not paths:
        return 0
    pos_row = conn.execute(
        "SELECT COALESCE(MAX(position), -1) FROM album_photos WHERE album_id = ?",
        (album_id,)
    ).fetchone()
    max_pos = pos_row[0] if pos_row else -1
    before = conn.total_changes
    conn.executemany(
        "INSERT OR IGNORE INTO album_photos (album_id, photo_path, position) VALUES (?, ?, ?)",
        [(album_id, path, max_pos + 1 + i) for i, path in enumerate(paths)],
    )
    added = conn.total_changes - before
    conn.execute(
        "UPDATE albums SET cover_photo_path = COALESCE(cover_photo_path, ?), "
        "updated_at = datetime('now') WHERE id = ?",
        (paths[0], album_id)
    )
    _apply_album_scoring_context(conn, album_id, paths)
    return added


@router.post("/api/albums/{album_id}/photos")
def add_photos_to_album(
    album_id: int,
    body: AlbumPhotosRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Add photos to an album (batch)."""
    if not body.photo_paths:
        raise HTTPException(status_code=400, detail="photo_paths must not be empty")
    with get_db() as conn:
        user_id = _get_user_id(user)
        _check_album_access(conn, album_id, user_id)
        added = append_album_photos(conn, album_id, body.photo_paths)
        conn.commit()

        row = conn.execute(
            "SELECT COUNT(*) FROM album_photos WHERE album_id = ?", (album_id,)
        ).fetchone()
        count = row[0] if row else 0
        return {'ok': True, 'added': added, 'photo_count': count}


@router.delete("/api/albums/{album_id}/photos")
def remove_photos_from_album(
    album_id: int,
    body: AlbumPhotosRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Remove photos from an album (batch).

    Also undoes this album's scoring_context stamp on exactly the removed
    photos (``source = 'album:<id>'`` only) — remaining members keep it, a
    photo's own manual override is never touched, and a path still a member
    of another context-declaring album is re-stamped with that album's
    context instead of being left unscored (see
    ``_clear_album_context_overrides``).

    A no-op for smart albums: ``album_photos`` carries no rows for them (their
    membership is resolved live from ``smart_filter_json``), so there is
    nothing to remove — and the removed photos would typically still be
    members, so clearing their scoring-context stamp here would be wrong.
    """
    if not body.photo_paths:
        raise HTTPException(status_code=400, detail="photo_paths must not be empty")
    with get_db() as conn:
        user_id = _get_user_id(user)
        album = _check_album_access(conn, album_id, user_id)

        if album['is_smart']:
            return {'ok': True, 'photo_count': 0}

        placeholders = ','.join(['?'] * len(body.photo_paths))
        conn.execute(
            f"DELETE FROM album_photos WHERE album_id = ? AND photo_path IN ({placeholders})",
            [album_id] + body.photo_paths
        )
        _clear_album_context_overrides(conn, album_id, paths=body.photo_paths)
        conn.execute("UPDATE albums SET updated_at = datetime('now') WHERE id = ?", (album_id,))
        conn.commit()

        row = conn.execute(
            "SELECT COUNT(*) FROM album_photos WHERE album_id = ?", (album_id,)
        ).fetchone()
        count = row[0] if row else 0
        return {'ok': True, 'photo_count': count}


@router.get("/api/albums/{album_id}/photos")
async def get_album_photos(
    request: Request,
    album_id: int,
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Get photos in an album with pagination and sorting (async)."""
    async with get_async_db() as conn:
        user_id = _get_user_id(user)
        album = await _check_album_access_async(conn, album_id, user_id)

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

        return await _fetch_album_photos(conn, album, user_id, page, per_page, sort, sort_dir)


@router.put("/api/albums/{album_id}/scoring_context")
def set_album_scoring_context(
    album_id: int,
    body: AlbumScoringContextRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Set the album's scoring context and materialize it onto CURRENT member photos.

    Membership is the album's FILTER definition (``_resolve_album_member_paths``
    — the same resolution the read endpoint uses), not "whatever the gallery
    happened to be showing": for a smart album it deliberately ignores the
    gallery's hide-blinks/hide-bursts/hide-duplicates/hide-rejected VIEW
    preferences (global, runtime-toggleable, and not part of
    ``smart_filter_json``), so ``updated`` can legitimately exceed the photo
    count the album's own gallery view displays with those toggles on.
    Membership is also captured NOW: photos that start matching a smart
    filter later do not retroactively inherit the context, and ``updated``
    reports the real number of photos actually written, which is 0 (flagged
    via ``warning``) when a smart album currently matches nothing.

    A member whose override was set manually (``source == 'manual'``) is
    skipped outright — never stamped with this album's context, and its
    ``source`` is never overwritten — so an album assignment can't silently
    convert a photo's own manual choice into an album-sourced one.
    ``manual_skipped`` reports how many were left alone this way.

    ``conflicts`` counts (non-manual) members whose scoring_context differed
    from the new value, read immediately before this call overwrites them —
    informational, not a dry-run preview: the change is already applied by
    the time the caller sees the count, since this endpoint has no separate
    commit step.
    """
    from config import ScoringConfig
    from db.scoring_overrides import get_photo_scoring_overrides, set_photo_scoring_override

    config = ScoringConfig(validate=False)
    if body.scoring_context not in config.get_scoring_contexts():
        raise HTTPException(status_code=400, detail=f'Unknown scoring context: {body.scoring_context}')

    with get_db() as conn:
        user_id = _get_user_id(user)
        album = _check_album_access(conn, album_id, user_id)

        conn.execute(
            "UPDATE albums SET scoring_context = ?, updated_at = datetime('now') WHERE id = ?",
            (body.scoring_context, album_id),
        )

        member_paths = _resolve_album_member_paths(conn, album)
        paths = _existing_photo_paths(conn, member_paths)
        manual_paths = _manual_override_paths(conn, paths)
        stampable = [p for p in paths if p not in manual_paths]

        existing = get_photo_scoring_overrides(conn, paths=stampable)
        conflicts = sum(
            1 for p in stampable
            if existing.get(p, {}).get('scoring_context') not in (None, body.scoring_context)
        )

        source = f'album:{album_id}'
        for path in stampable:
            set_photo_scoring_override(conn, path, scoring_context=body.scoring_context, source=source, created_by=user_id)

        conn.commit()

    result = {'updated': len(stampable), 'conflicts': conflicts, 'manual_skipped': len(manual_paths)}
    if bool(album['is_smart']) and not paths:
        result['warning'] = 'Smart album currently matches no photos; nothing was updated.'
    return result


@router.delete("/api/albums/{album_id}/scoring_context")
def clear_album_scoring_context(
    album_id: int,
    user: CurrentUser = Depends(require_edition),
):
    """Clear the album's scoring context and undo it on the members it set.

    A scoring context assigned via ``PUT .../scoring_context`` had no way to
    be unset: the album's own ``scoring_context`` stayed stamped forever
    (deleting the album or removing photos left ``photo_scoring_overrides``
    untouched, since that table carries no FK to ``albums``). Only overrides
    whose ``source`` is exactly this album's (``album:<id>``) are cleared, so
    a member's own manual override, or a context a different album set, is
    left untouched.
    """
    with get_db() as conn:
        user_id = _get_user_id(user)
        _check_album_access(conn, album_id, user_id)

        conn.execute(
            "UPDATE albums SET scoring_context = NULL, updated_at = datetime('now') WHERE id = ?",
            (album_id,),
        )
        cleared = _clear_album_context_overrides(conn, album_id)
        conn.commit()

    return {'ok': True, 'cleared': cleared}


@router.get("/api/albums/{album_id}/suggested_context")
def get_album_suggested_context(
    album_id: int,
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Suggest a scoring context from the album's dominant narrative moment.

    Membership is resolved the same way ``set_album_scoring_context`` resolves
    it (``_resolve_album_member_paths``) rather than reading ``album_photos``
    directly, which carries no rows for a smart album and would silently
    starve every suggestion for the album type this feature matters most for.

    Suggestion only — writes nothing; the caller confirms via
    ``PUT .../scoring_context``.
    """
    from config import ScoringConfig
    from api.db_helpers import select_in_chunks

    with get_db() as conn:
        user_id = _get_user_id(user)
        album = _check_album_access(conn, album_id, user_id)

        member_paths = _resolve_album_member_paths(conn, album)
        paths = _existing_photo_paths(conn, member_paths)

        counts: dict = {}
        for row in select_in_chunks(
            conn,
            "SELECT narrative_moment, COUNT(*) as cnt FROM photos "
            "WHERE path IN ({placeholders}) AND narrative_moment IS NOT NULL AND narrative_moment != '' "
            "GROUP BY narrative_moment",
            paths,
        ):
            counts[row['narrative_moment']] = counts.get(row['narrative_moment'], 0) + row['cnt']

    total = sum(counts.values())

    if not total:
        return {'suggested': None, 'moment': None, 'share': 0.0, 'counts': {}}

    dominant_moment, dominant_count = max(counts.items(), key=lambda kv: kv[1])
    share = dominant_count / total

    config = ScoringConfig(validate=False)
    suggested = next(
        (
            name for name, context_cfg in config.get_scoring_contexts().items()
            if dominant_moment in context_cfg.get('suggest_from_moments', [])
        ),
        None,
    )

    return {
        'suggested': suggested,
        'moment': dominant_moment,
        'share': round(share, 4),
        'counts': counts,
    }


# --- Sharing endpoints ---

@router.post("/api/albums/{album_id}/share")
def share_album(
    album_id: int,
    rotate: bool = Query(False),
    user: CurrentUser = Depends(require_edition),
):
    """Generate a share token for public album access.

    Reuses the album's existing token so repeated calls return a stable link.
    Pass ``?rotate=true`` to mint a fresh token, invalidating any link handed
    out earlier — the operation users expect when revoking a leaked link.
    """
    with get_db() as conn:
        user_id = _get_user_id(user)
        album = _check_album_access(conn, album_id, user_id)
        existing_token = None
        if not rotate:
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


@router.delete("/api/albums/{album_id}/share")
def unshare_album(
    album_id: int,
    user: CurrentUser = Depends(require_edition),
):
    """Revoke public sharing for an album."""
    with get_db() as conn:
        user_id = _get_user_id(user)
        _check_album_access(conn, album_id, user_id)
        conn.execute("UPDATE albums SET share_token = NULL WHERE id = ?", (album_id,))
        conn.commit()
        return {'ok': True}


@router.get("/api/shared/album/{album_id}")
async def get_shared_album(
    request: Request,
    album_id: int,
    token: str = Query(...),
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Public endpoint to view a shared album via token (async)."""
    async with get_async_db() as conn:
        cur = await conn.execute("SELECT * FROM albums WHERE id = ?", (album_id,))
        album = await cur.fetchone()
        await cur.close()
        if not album:
            raise HTTPException(status_code=404, detail="Album not found")

        # Verify token matches the stored share_token
        try:
            stored_token = album['share_token']
            if not stored_token or not hmac.compare_digest(
                stored_token.encode('utf-8'), token.encode('utf-8')
            ):
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
                # Color facet + on-the-fly quality tier
                'color_temp', 'hue_bucket', 'quality_tier',
                # Range filters (quality, face, composition, saliency, technical, exposure, ratings)
                'min_score', 'max_score', 'min_aesthetic', 'max_aesthetic',
                'min_quality_score', 'max_quality_score',
                'min_aesthetic_iaa', 'max_aesthetic_iaa',
                'min_face_quality_iqa', 'max_face_quality_iqa',
                'min_liqe', 'max_liqe',
                'min_qrealign', 'max_qrealign',
                'min_aesthetic_v25', 'max_aesthetic_v25',
                'min_deqa', 'max_deqa',
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

        result = await _fetch_album_photos(conn, album, user_id, page, per_page, sort, sort_dir, filters=filters)
        result['album'] = _album_to_dict(album)
        result['effective_sort'] = sort
        result['effective_sort_direction'] = sort_dir
        result['proofing_enabled'] = (
            bool(VIEWER_CONFIG.get('features', {}).get('show_proofing', False)) and is_manual
        )
        if SORT_OPTIONS_GROUPED:
            result['sort_options_grouped'] = SORT_OPTIONS_GROUPED

        # Include filter options for manual albums (first page only to avoid repeated work)
        if is_manual and page == 1:
            try:
                result['filter_options'] = await _get_album_filter_options(conn, album['id'])
            except sqlite3.Error:
                logger.debug("Failed to build album filter options", exc_info=True)

        return result
