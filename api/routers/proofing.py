"""
Proofing router — client picks on shared albums.

A photographer shares an album link; the client (no account) marks picks with
an optional comment, and the owner reads them back. Picks live in the
dedicated ``album_client_picks`` table and are FULLY isolated from the owner's
ratings: proofing never writes ``photos.is_favorite`` / ``user_preferences``
and never mints comparison rows (those would train the owner's "My Taste"
ranker).

Write auth: the client exchanges the album share token (plus the optional
``viewer.proofing.pin``) for a short-lived JWT scoped to that one album
(``require_share_client``), so writes hold regardless of the server's auth
mode. Every write is additionally bounded server-side to the album's own
photo set.
"""

import hmac
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from api.auth import (
    CurrentUser, RateLimiter, create_share_client_token, require_edition,
    require_share_client,
)
from api.config import VIEWER_CONFIG
from api.database import get_db
from api.routers.albums import _check_album_access, _get_user_id

router = APIRouter(tags=["proofing"])
logger = logging.getLogger(__name__)

# Brute-force guard on the share-session PIN, mirroring the login limiter.
_session_limiter = RateLimiter(max_attempts=5, window_seconds=60)


def _load_album_share_token(conn, album_id):
    """Return the album row and its share_token, or (None, None) if absent.

    A share_token of NULL means the album is not (or no longer) shared, so any
    proofing session minted earlier must stop working — this is the revocation
    check the picks routes re-run on every request.
    """
    album = conn.execute(
        "SELECT id, is_smart, share_token FROM albums WHERE id = ?", (album_id,)
    ).fetchone()
    if not album:
        return None, None
    return album, album['share_token']


# --- Request models ---

class ShareSessionRequest(BaseModel):
    token: str
    pin: str = ''
    client_name: str = Field('', max_length=100)


class PickRequest(BaseModel):
    path: str
    picked: bool = True
    comment: Optional[str] = Field(None, max_length=2000)


# --- Helpers ---

def _proofing_config() -> dict:
    return VIEWER_CONFIG.get('proofing', {}) or {}


def _proofing_enabled() -> bool:
    return bool(VIEWER_CONFIG.get('features', {}).get('show_proofing', False))


def _pick_rows(conn, album_id):
    return conn.execute(
        "SELECT photo_path, picked, comment, client_name, updated_at "
        "FROM album_client_picks WHERE album_id = ? ORDER BY updated_at DESC",
        (album_id,)
    ).fetchall()


def _picks_response(rows):
    picks = [
        {
            'path': row['photo_path'],
            'picked': bool(row['picked']),
            'comment': row['comment'],
            'client_name': row['client_name'],
            'updated_at': row['updated_at'],
        }
        for row in rows
    ]
    return {'picks': picks, 'count': sum(1 for p in picks if p['picked'])}


# --- Client endpoints (share-token / share-session auth) ---

def _tokens_match(stored: Optional[str], provided: str) -> bool:
    """Constant-time compare of two secrets as UTF-8 bytes.

    ``hmac.compare_digest`` raises TypeError on non-ASCII ``str`` inputs, so a
    unicode token/PIN would surface as a 500 instead of a clean rejection.
    """
    if not stored:
        return False
    return hmac.compare_digest(stored.encode('utf-8'), provided.encode('utf-8'))


@router.post("/api/shared/album/{album_id}/session")
def create_share_session(album_id: int, body: ShareSessionRequest, request: Request):
    """Exchange a valid share token (+ optional PIN) for a proofing session JWT."""
    if not _proofing_enabled():
        raise HTTPException(status_code=403, detail="Proofing disabled")
    client_ip = request.client.host if request.client else "unknown"
    if not _session_limiter.is_allowed(f"{client_ip}:{album_id}"):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")
    with get_db() as conn:
        album, stored_token = _load_album_share_token(conn, album_id)
    if not album:
        raise HTTPException(status_code=404, detail="Album not found")
    if not _tokens_match(stored_token, body.token):
        raise HTTPException(status_code=403, detail="Invalid share token")
    pin = str(_proofing_config().get('pin', '') or '')
    if pin:
        if not body.pin:
            raise HTTPException(status_code=403, detail="pin_required")
        if not _tokens_match(pin, body.pin):
            raise HTTPException(status_code=403, detail="pin_invalid")
    client_name = body.client_name.strip()
    return {
        'session_token': create_share_client_token(album_id, client_name),
        'client_name': client_name,
    }


@router.put("/api/shared/album/{album_id}/picks")
def upsert_pick(
    album_id: int,
    body: PickRequest,
    session: dict = Depends(require_share_client),
):
    """Upsert a client pick, bounded server-side to the album's photo set.

    A ``None`` comment leaves any existing comment untouched (pick toggles
    don't wipe comments); an explicit empty string clears it.
    """
    with get_db() as conn:
        album, stored_token = _load_album_share_token(conn, album_id)
        if not album:
            raise HTTPException(status_code=404, detail="Album not found")
        if not _proofing_enabled() or not stored_token:
            raise HTTPException(status_code=403, detail="Share session revoked")
        if album['is_smart']:
            raise HTTPException(
                status_code=400,
                detail="Proofing picks are not supported on smart albums",
            )
        member = conn.execute(
            "SELECT 1 FROM album_photos WHERE album_id = ? AND photo_path = ?",
            (album_id, body.path)
        ).fetchone()
        if not member:
            raise HTTPException(status_code=400, detail="Photo is not part of this album")
        conn.execute(
            """INSERT INTO album_client_picks
                   (album_id, photo_path, picked, comment, client_name, updated_at)
               VALUES (?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(album_id, photo_path) DO UPDATE SET
                   picked = excluded.picked,
                   comment = COALESCE(excluded.comment, album_client_picks.comment),
                   client_name = excluded.client_name,
                   updated_at = datetime('now')""",
            (album_id, body.path, 1 if body.picked else 0, body.comment,
             session.get('client_name', '')),
        )
        conn.commit()
        return {'ok': True, 'path': body.path, 'picked': body.picked}


@router.get("/api/shared/album/{album_id}/picks")
def get_share_picks(
    album_id: int,
    session: dict = Depends(require_share_client),
):
    """Current picks for the shared album, for client-side re-hydration."""
    with get_db() as conn:
        album, stored_token = _load_album_share_token(conn, album_id)
        if not album or not _proofing_enabled() or not stored_token:
            raise HTTPException(status_code=403, detail="Share session revoked")
        rows = _pick_rows(conn, album_id)
    return _picks_response(rows)


# --- Owner endpoint (edition auth) ---

@router.get("/api/albums/{album_id}/picks")
def get_owner_picks(
    album_id: int,
    user: CurrentUser = Depends(require_edition),
):
    """Full client-picks list for the album owner (edition-gated)."""
    with get_db() as conn:
        _check_album_access(conn, album_id, _get_user_id(user))
        rows = _pick_rows(conn, album_id)
    return _picks_response(rows)
