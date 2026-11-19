"""Photo-frame / kiosk endpoints (static frame-token auth, anonymous).

These endpoints let login-less kiosk devices — smart photo frames, Home
Assistant dashboards, ImmichFrame / Immich-Kiosk style displays — pull Facet's
best shots without a user session. Access is granted by a long-lived opaque
frame token configured in ``scoring_config.json`` (``frame.tokens``); an empty
token list disables the whole feature (404).

Responses never leak filesystem paths: photos are addressed by an opaque signed
identifier (the row's ``rowid`` signed with the server secret), so a token
holder cannot enumerate arbitrary rows and no library path is ever serialised.
"""

import hashlib
import hmac
import logging
from io import BytesIO
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response

from api.config import config_number, warn_bad_config_once
from api.database import get_db
from api.path_validation import resolve_photo_disk_path
from api.token_auth import TokenFailureLimiter, require_static_token_throttled
from api.types import JUNK_NOT_JUNK

logger = logging.getLogger(__name__)

router = APIRouter(tags=["frame"])

# Failed-token throttle per peer IP: a kiosk polls constantly, a guesser does not.
_token_limiter = TokenFailureLimiter()

_FEATURE = "Frame feature"

_DEFAULT_COUNT = 20
_DEFAULT_MAX_COUNT = 100
_DEFAULT_MIN_AGGREGATE = 7.0
_DEFAULT_MAX_EDGE = 1920
_DEFAULT_FAVORITES_ONLY = False

_JPEG_QUALITY = 88
_POOL_MULTIPLIER = 8
_SIG_LEN = 16
_ID_SEP = "."
_BEARER_SCHEME = "bearer"

_META_COLS = "rowid, caption, date_taken, image_width, image_height, preview_revision"
_RENDER_COLS = "rowid, path, thumbnail, image_width, image_height"

_IMMUTABLE_HEADERS = {"Cache-Control": "public, max-age=31536000, immutable"}
_NO_STORE_HEADERS = {"Cache-Control": "no-store"}


def _frame_config() -> dict:
    from api.config import _FULL_CONFIG

    return _FULL_CONFIG.get("frame", {}) or {}


def _secret() -> str:
    from api import config

    return config._server_secret


def _resolve_token(query_token: str, header_token: Optional[str],
                   authorization: Optional[str]) -> str:
    """Prefer a header-borne token over the ``?token=`` query param.

    Passing the long-lived frame token in a header (``X-Frame-Token`` or
    ``Authorization: Bearer <token>``) keeps it out of access logs and the
    Referer header. The query param stays supported so dumb ``<img>`` / kiosk
    clients that cannot set headers keep working.
    """
    if header_token:
        return header_token
    if authorization:
        scheme, _, param = authorization.partition(" ")
        if scheme.lower() == _BEARER_SCHEME and param.strip():
            return param.strip()
    return query_token


def _sign_rowid(rowid: int, revision: Optional[str] = None,
                edge: Optional[int] = None) -> str:
    """Signed opaque id for a photo row.

    Cache-key ingredients ride along so a display's ``immutable`` id changes
    whenever the pixels it addresses would change: the content revision
    (``preview_revision``, bumped by photo refresh, which keeps the rowid) and
    the frame's configured ``max_edge`` cap (bumped by a config edit, which
    keeps everything else). Old-format ids keep resolving — and keep honouring
    their ``?max_edge=`` query — until the display's next poll delivers ids
    that carry the edge.
    """
    payload = str(rowid)
    if edge is not None:
        # Always the full three-ingredient shape: a bare "rowid.edge" would be
        # indistinguishable from a legacy "rowid.revision".
        payload += f"{_ID_SEP}{revision if revision is not None else ''}{_ID_SEP}{edge}"
    elif revision is not None:
        payload += f"{_ID_SEP}{revision}"
    sig = hmac.new(
        _secret().encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()[:_SIG_LEN]
    return f"{payload}{_ID_SEP}{sig}"


def _resolve_id(photo_id: str) -> Optional[tuple]:
    """Return ``(rowid, edge)`` for a valid signed id, or None for a forged one.

    ``rowid``, ``rowid.revision``, ``rowid.revision.edge`` and ``rowid..edge``
    payloads all resolve: the trailing ingredients exist to change the cache
    key, not the identity, so any authentic combination serves the row's
    current image. The edge is set only by ids minted after the config's
    ``max_edge`` joined the payload; it caps the rendering together with the
    current config, and a ``?max_edge=`` query can only lower it further.
    """
    if not photo_id or _ID_SEP not in photo_id:
        return None
    parts = photo_id.split(_ID_SEP)
    if len(parts) < 2:
        return None
    payload = _ID_SEP.join(parts[:-1])
    sig = parts[-1]
    if not parts[0].isdigit():
        return None
    expected = hmac.new(
        _secret().encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()[:_SIG_LEN]
    if not hmac.compare_digest(expected.encode("utf-8"), sig.encode("utf-8")):
        return None
    edge = None
    if len(parts) >= 4 and parts[-2].isdigit():
        # The edge is the ingredient before the signature, present only in ids
        # minted after it joined the payload (parts: rowid[.revision].edge.sig).
        edge = int(parts[-2])
    return int(parts[0]), edge


def _clamp_count(count: Optional[int], cfg: dict) -> int:
    default = int(config_number(cfg, "count", default=_DEFAULT_COUNT, name="frame.count"))
    max_count = int(config_number(cfg, "max_count", default=_DEFAULT_MAX_COUNT, name="frame.max_count"))
    requested = default if count is None else count
    return max(1, min(requested, max_count))


def _edge_cap(cfg: dict) -> int:
    """``frame.max_edge``, falling back to the default on a value ``int()`` refuses."""
    raw = cfg.get("max_edge", _DEFAULT_MAX_EDGE)
    try:
        return max(1, int(raw))
    except (TypeError, ValueError, OverflowError):
        warn_bad_config_once("frame.max_edge", raw, f"{_DEFAULT_MAX_EDGE} px")
        return _DEFAULT_MAX_EDGE


def _clamp_edge(max_edge: Optional[int], cap: int) -> int:
    requested = cap if max_edge is None else max_edge
    return max(1, min(requested, cap))


def _curation_clause(cfg: dict):
    """Build the WHERE fragment + params for the curated candidate set."""
    clauses = [
        "(is_rejected IS NULL OR is_rejected = 0)",
        "(junk_kind IS NULL OR junk_kind = ?)",
        "(is_blink IS NULL OR is_blink = 0)",
        "aggregate IS NOT NULL",
        "aggregate >= ?",
    ]
    params = [JUNK_NOT_JUNK, config_number(cfg, "min_aggregate", default=_DEFAULT_MIN_AGGREGATE, name="frame.min_aggregate")]
    if cfg.get("favorites_only", _DEFAULT_FAVORITES_ONLY):
        clauses.append("is_favorite = 1")
    categories = [c for c in (cfg.get("categories") or []) if isinstance(c, str) and c]
    if categories:
        placeholders = ",".join("?" for _ in categories)
        clauses.append(f"category IN ({placeholders})")
        params.extend(categories)
    return " AND ".join(clauses), params


def _sample(cfg: dict, count: int, columns: str):
    """Score-weighted random sample: shuffle a top-by-score candidate pool.

    The inner query walks ``idx_aggregate`` (aggregate DESC) to collect the best
    ``count * _POOL_MULTIPLIER`` curated rows without a full-table sort, then the
    outer ``ORDER BY RANDOM()`` picks ``count`` of them — biased toward the
    highest scores while staying index-friendly on 100k+ libraries.
    """
    where, params = _curation_clause(cfg)
    pool = max(count, count * _POOL_MULTIPLIER)
    sql = (
        f"SELECT {columns} FROM ("
        f" SELECT {columns} FROM photos WHERE {where}"
        f" ORDER BY aggregate DESC LIMIT ?"
        f") ORDER BY RANDOM() LIMIT ?"
    )
    with get_db() as conn:
        return conn.execute(sql, [*params, pool, count]).fetchall()


def _encode_jpeg(pil, max_edge: int) -> bytes:
    from PIL import Image

    if pil.mode != "RGB":
        pil = pil.convert("RGB")
    width, height = pil.size
    longest = max(width, height)
    if longest > max_edge:
        scale = max_edge / float(longest)
        pil = pil.resize(
            (max(1, int(width * scale)), max(1, int(height * scale))), Image.Resampling.LANCZOS
        )
    buf = BytesIO()
    pil.save(buf, format="JPEG", quality=_JPEG_QUALITY)
    return buf.getvalue()


def _render_jpeg(path: str, thumbnail: Optional[bytes], max_edge: int) -> Optional[bytes]:
    """Downscaled JPEG of the on-disk original, falling back to the stored thumbnail."""
    from PIL import Image
    from utils.image_loading import load_image_from_path

    pil = None
    try:
        real_disk = resolve_photo_disk_path(path)
        pil, _ = load_image_from_path(real_disk)
    except (HTTPException, OSError, ValueError):
        pil = None
    if pil is None and thumbnail:
        try:
            pil = Image.open(BytesIO(thumbnail))
        except (OSError, ValueError):
            pil = None
    if pil is None:
        return None
    return _encode_jpeg(pil, max_edge)


@router.get("/api/frame/photos")
def frame_photos(
    request: Request,
    token: str = Query(""),
    count: Optional[int] = Query(None),
    x_frame_token: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
):
    """Return a curated batch of photos as opaque ids + display metadata."""
    cfg = _frame_config()
    require_static_token_throttled(request, cfg.get("tokens"),
                                   _resolve_token(token, x_frame_token, authorization), _FEATURE,
                                   limiter=_token_limiter)
    rows = _sample(cfg, _clamp_count(count, cfg), _META_COLS)
    photos = []
    edge = _edge_cap(cfg)
    for row in rows:
        entry = {
            "id": _sign_rowid(row["rowid"], row["preview_revision"], edge=edge),
            "width": row["image_width"],
            "height": row["image_height"],
        }
        if row["caption"]:
            entry["caption"] = row["caption"]
        if row["date_taken"]:
            entry["date_taken"] = row["date_taken"]
        photos.append(entry)
    return {"photos": photos}


@router.get("/api/frame/image/{photo_id}")
def frame_image(
    request: Request,
    photo_id: str,
    token: str = Query(""),
    max_edge: Optional[int] = Query(None),
    x_frame_token: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
):
    """Serve a single curated photo JPEG addressed by its opaque signed id."""
    cfg = _frame_config()
    require_static_token_throttled(request, cfg.get("tokens"),
                                   _resolve_token(token, x_frame_token, authorization), _FEATURE,
                                   limiter=_token_limiter)
    resolved = _resolve_id(photo_id)
    if resolved is None:
        raise HTTPException(status_code=404, detail="Unknown photo")
    rowid, signed_edge = resolved
    where, params = _curation_clause(cfg)
    with get_db() as conn:
        row = conn.execute(
            f"SELECT path, thumbnail FROM photos WHERE rowid = ? AND {where}",
            (rowid, *params),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Unknown photo")
    # The id carries the cap it was minted with, so raising the config cap
    # reaches a display on its next poll (new ids, new immutable cache keys)
    # rather than by changing the pixels behind a live id. Lowering it binds at
    # once: ids never expire, and an old one must not keep fetching the larger
    # rendering. The query can only lower the edge further.
    cap = _edge_cap(cfg)
    if signed_edge is not None:
        cap = min(signed_edge, cap)
    data = _render_jpeg(row["path"], row["thumbnail"], _clamp_edge(max_edge, cap))
    if data is None:
        raise HTTPException(status_code=404, detail="Image unavailable")
    return Response(content=data, media_type="image/jpeg", headers=_IMMUTABLE_HEADERS)


@router.get("/api/frame/next")
def frame_next(
    request: Request,
    token: str = Query(""),
    max_edge: Optional[int] = Query(None),
    x_frame_token: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
):
    """Serve one random curated photo JPEG (dumb-frame / HA generic-camera case)."""
    cfg = _frame_config()
    require_static_token_throttled(request, cfg.get("tokens"),
                                   _resolve_token(token, x_frame_token, authorization), _FEATURE,
                                   limiter=_token_limiter)
    rows = _sample(cfg, 1, _RENDER_COLS)
    if not rows:
        raise HTTPException(status_code=404, detail="No photos available")
    row = rows[0]
    data = _render_jpeg(row["path"], row["thumbnail"], _clamp_edge(max_edge, _edge_cap(cfg)))
    if data is None:
        raise HTTPException(status_code=404, detail="Image unavailable")
    return Response(content=data, media_type="image/jpeg", headers=_NO_STORE_HEADERS)
