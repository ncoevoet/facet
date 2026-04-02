"""Capsules router — curated photo diaporamas grouped by theme."""

import logging
import re
import sqlite3
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth import CurrentUser, get_optional_user, require_edition
from api.config import _FULL_CONFIG
from api.database import get_db_connection
from api.db_helpers import (
    build_photo_select_columns,
    sanitize_float_values,
    get_visibility_clause,
    split_photo_tags,
    attach_person_data,
    format_date,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["capsules"])

# Per-(user, date_from, date_to) cache for full capsule list
_capsule_cache: dict[tuple, dict] = {}
_CACHE_TTL = _FULL_CONFIG.get("capsules", {}).get("freshness_hours", 24) * 3600
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _capsule_summary(capsule: dict) -> dict:
    """Return capsule metadata without paths."""
    return {
        "type": capsule["type"],
        "id": capsule["id"],
        "title": capsule["title"],
        "title_key": capsule.get("title_key", ""),
        "title_params": capsule.get("title_params", {}),
        "subtitle": capsule["subtitle"],
        "cover_photo_path": capsule["cover_photo_path"],
        "photo_count": capsule["photo_count"],
        "icon": capsule["icon"],
    }


def _cache_key(user_id, date_from="", date_to=""):
    """Build a cache key tuple from user_id and optional date range."""
    return (user_id, date_from or "", date_to or "")


def _get_cached_capsules(user_id, refresh=False, date_from="", date_to=""):
    """Return (full_capsules_list, from_cache). Generates if needed."""
    now = time.time()
    key = _cache_key(user_id, date_from, date_to)
    entry = _capsule_cache.get(key)

    if not refresh and entry and (now - entry["ts"]) < _CACHE_TTL:
        return entry["data"], True

    # Fall back to the startup precomputed cache (user_id=None, no date filters)
    # when no user-specific cache exists yet
    if not refresh and user_id is not None and not date_from and not date_to:
        fallback = _capsule_cache.get(_cache_key(None))
        if fallback and (now - fallback["ts"]) < _CACHE_TTL:
            return fallback["data"], True

    return None, False


def _set_cached_capsules(user_id, capsules, date_from="", date_to=""):
    """Store full capsule list in per-user cache, evicting expired entries."""
    now = time.time()
    # Evict expired entries to prevent unbounded growth
    expired = [k for k, v in _capsule_cache.items() if (now - v["ts"]) >= _CACHE_TTL]
    for k in expired:
        del _capsule_cache[k]
    key = _cache_key(user_id, date_from, date_to)
    _capsule_cache[key] = {"data": capsules, "ts": now}


def _validate_date(value: str) -> str:
    """Return validated date string or empty string if invalid."""
    if value and _DATE_RE.match(value):
        return value
    return ""


def _resolve_capsule(capsule_id: str, user_id, date_from="", date_to="") -> dict:
    """Find a capsule by ID from cache (generating if needed). Raises 404."""
    cached, hit = _get_cached_capsules(user_id, date_from=date_from, date_to=date_to)
    if not hit:
        conn = get_db_connection()
        try:
            from analyzers.capsule_generator import generate_all_capsules
            cached = generate_all_capsules(conn, config=_FULL_CONFIG, user_id=user_id,
                                           date_from=date_from, date_to=date_to)
            _set_cached_capsules(user_id, cached, date_from=date_from, date_to=date_to)
        finally:
            conn.close()

    for c in cached:
        if c["id"] == capsule_id:
            return c
    raise HTTPException(status_code=404, detail="Capsule not found")


@router.get("/api/capsules")
def get_capsules(
    user: Optional[CurrentUser] = Depends(get_optional_user),
    refresh: bool = Query(False),
    page: int = Query(1, ge=1),
    per_page: int = Query(24, ge=1, le=200),
    date_from: str = Query(""),
    date_to: str = Query(""),
):
    """Return available capsules (cached 1h, paginated)."""
    user_id = user.user_id if user else None
    date_from = _validate_date(date_from)
    date_to = _validate_date(date_to)

    cached, hit = _get_cached_capsules(user_id, refresh, date_from=date_from, date_to=date_to)
    if not hit:
        conn = get_db_connection()
        try:
            from analyzers.capsule_generator import generate_all_capsules

            cached = generate_all_capsules(conn, config=_FULL_CONFIG, user_id=user_id,
                                           date_from=date_from, date_to=date_to,
                                           shuffle=refresh)
            _set_cached_capsules(user_id, cached, date_from=date_from, date_to=date_to)
        except (sqlite3.Error, ValueError, TypeError, KeyError):
            logger.exception("Failed to generate capsules")
            raise HTTPException(status_code=500, detail="Failed to generate capsules")
        finally:
            conn.close()

    total = len(cached)
    start = (page - 1) * per_page
    end = start + per_page
    page_capsules = cached[start:end]

    return {
        "capsules": [_capsule_summary(c) for c in page_capsules],
        "total": total,
        "page": page,
        "per_page": per_page,
        "has_more": end < total,
    }


@router.get("/api/capsules/{capsule_id}/photos")
def get_capsule_photos(
    capsule_id: str,
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Return the curated photo list for a specific capsule."""
    user_id = user.user_id if user else None
    capsule = _resolve_capsule(capsule_id, user_id)

    paths = capsule["params"].get("paths", [])
    if not paths:
        return {"photos": [], "capsule": _capsule_summary(capsule)}

    conn = get_db_connection()
    try:
        # Fetch full photo data for these paths
        select_cols = build_photo_select_columns(conn, user_id)
        inner_cols = ", ".join(select_cols)

        vis_sql, vis_params = get_visibility_clause(user_id)

        placeholders = ",".join(["?"] * len(paths))
        query = f"""
            SELECT {inner_cols}
            FROM photos
            WHERE path IN ({placeholders})
              AND {vis_sql}
        """
        rows = conn.execute(query, paths + vis_params).fetchall()

        from api.config import VIEWER_CONFIG

        tags_limit = VIEWER_CONFIG.get("display", {}).get("tags_per_photo", 10)
        photos = split_photo_tags(rows, tags_limit)

        for photo in photos:
            photo["date_formatted"] = format_date(photo.get("date_taken"))

        attach_person_data(photos, conn)
        sanitize_float_values(photos)

        # Preserve the original path ordering
        path_order = {p: i for i, p in enumerate(paths)}
        photos.sort(key=lambda p: path_order.get(p.get("path"), 999999))

        return {
            "photos": photos,
            "capsule": _capsule_summary(capsule),
        }

    except HTTPException:
        raise
    except sqlite3.Error:
        logger.exception("Failed to fetch capsule photos for %s", capsule_id)
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        conn.close()


@router.post("/api/capsules/{capsule_id}/save-album")
def save_capsule_as_album(
    capsule_id: str,
    user: CurrentUser = Depends(require_edition),
):
    """Save a capsule as a new album."""
    user_id = user.user_id if user else None
    capsule = _resolve_capsule(capsule_id, user_id)

    paths = capsule["params"].get("paths", [])
    if not paths:
        raise HTTPException(status_code=400, detail="Capsule has no photos")

    name = capsule["title"]
    description = capsule.get("subtitle", "")
    cover_path = capsule.get("cover_photo_path")

    conn = get_db_connection()
    try:
        cursor = conn.execute(
            """INSERT INTO albums (user_id, name, description, is_smart, cover_photo_path)
               VALUES (?, ?, ?, 0, ?)""",
            (user_id, name, description, cover_path),
        )
        album_id = cursor.lastrowid
        conn.executemany(
            "INSERT OR IGNORE INTO album_photos (album_id, photo_path, position) VALUES (?, ?, ?)",
            [(album_id, path, i) for i, path in enumerate(paths)],
        )
        conn.commit()
        return {"album_id": album_id, "name": name}
    except sqlite3.Error:
        logger.exception("Failed to save capsule %s as album", capsule_id)
        raise HTTPException(status_code=500, detail="Failed to save album")
    finally:
        conn.close()
