"""Saliency-aware social-export crop endpoints (edition-gated).

``GET /api/photo/social_crop`` decodes the original photo, crops it to a
configured social aspect preset framed on the detected subject, and returns the
cropped full-resolution JPEG as a download. ``GET /api/photo/social_crop/preview``
returns just the crop rectangle (normalized) and its source without decoding the
original, so the client can draw an overlay cheaply.

Subject framing follows a fallback chain: the persisted BiRefNet subject box
(``photos.subject_bbox``) → the union of detected face boxes → a center crop.
The response surfaces which source drove the crop.
"""

import io
import json
import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from api.auth import CurrentUser, require_edition
from api.config import VIEWER_CONFIG
from api.database import get_db
from api.db_helpers import get_visibility_clause
from api.path_validation import resolve_photo_disk_path
from processing.social_crop import compute_crop_rect, parse_aspect

logger = logging.getLogger(__name__)

router = APIRouter(tags=["social_crop"])

SOURCE_SALIENCY = "saliency"
SOURCE_FACES = "faces"
SOURCE_CENTER = "center"


def _require_social_export_enabled():
    if not VIEWER_CONFIG.get("features", {}).get("show_social_export", True):
        raise HTTPException(status_code=404, detail="Social export is disabled")


def _social_export_config() -> dict:
    from api.config import _FULL_CONFIG

    return _FULL_CONFIG.get("social_export", {}) or {}


def _preset_aspect(preset: str):
    presets = _social_export_config().get("presets", {}) or {}
    entry = presets.get(preset)
    if not entry:
        raise HTTPException(status_code=400, detail=f"Unknown preset: {preset}")
    try:
        return parse_aspect(entry["aspect"])
    except (KeyError, ValueError):
        raise HTTPException(status_code=400, detail=f"Invalid preset: {preset}") from None


def _margin_frac() -> float:
    return float(_social_export_config().get("subject_margin_percent", 8)) / 100.0


def _lookup_photo(path: str, user: Optional[CurrentUser]):
    """Fetch a visible photo row (subject box + dimensions) or raise 404."""
    if not path:
        raise HTTPException(status_code=400, detail="path required")
    vis_sql, vis_params = get_visibility_clause(user.user_id if user else None)
    with get_db() as conn:
        row = conn.execute(
            f"SELECT path, subject_bbox, image_width, image_height "
            f"FROM photos WHERE path = ? AND {vis_sql}",
            [path] + vis_params,
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="File not found")
        faces = conn.execute(
            "SELECT bbox_x1, bbox_y1, bbox_x2, bbox_y2 FROM faces WHERE photo_path = ?",
            (row["path"],),
        ).fetchall()
    return row, faces


def _resolve_subject(row, faces):
    """Return ``(subject_norm, source)`` from the saliency box, faces, or None.

    ``subject_norm`` is a normalized ``[x0, y0, x1, y1]`` box, or None for the
    center-crop fallback.
    """
    raw = row["subject_bbox"]
    if raw:
        try:
            box = json.loads(raw)
            if isinstance(box, (list, tuple)) and len(box) == 4:
                return [float(v) for v in box], SOURCE_SALIENCY
        except (ValueError, TypeError):
            pass

    width = row["image_width"] or 0
    height = row["image_height"] or 0
    if faces and width > 0 and height > 0:
        xs0 = [f["bbox_x1"] for f in faces if f["bbox_x1"] is not None]
        ys0 = [f["bbox_y1"] for f in faces if f["bbox_y1"] is not None]
        xs1 = [f["bbox_x2"] for f in faces if f["bbox_x2"] is not None]
        ys1 = [f["bbox_y2"] for f in faces if f["bbox_y2"] is not None]
        if xs0 and ys0 and xs1 and ys1:
            box = [
                min(xs0) / width,
                min(ys0) / height,
                max(xs1) / width,
                max(ys1) / height,
            ]
            box = [max(0.0, min(1.0, v)) for v in box]
            return box, SOURCE_FACES

    return None, SOURCE_CENTER


@router.get("/api/photo/social_crop/preview")
def api_social_crop_preview(
    path: str = Query(...),
    preset: str = Query(...),
    user: CurrentUser = Depends(require_edition),
):
    """Return the normalized crop rectangle and its source without decoding."""
    _require_social_export_enabled()
    aspect_w, aspect_h = _preset_aspect(preset)
    row, faces = _lookup_photo(path, user)

    width = row["image_width"] or 0
    height = row["image_height"] or 0
    if width <= 0 or height <= 0:
        raise HTTPException(status_code=422, detail="Photo has no stored dimensions")

    subject_norm, source = _resolve_subject(row, faces)
    x0, y0, x1, y1 = compute_crop_rect(
        width, height, aspect_w, aspect_h, subject_norm, _margin_frac()
    )
    return {
        "preset": preset,
        "aspect": f"{aspect_w:g}:{aspect_h:g}",
        "source": source,
        "rect": {
            "x0": round(x0 / width, 4),
            "y0": round(y0 / height, 4),
            "x1": round(x1 / width, 4),
            "y1": round(y1 / height, 4),
        },
    }


@router.get("/api/photo/social_crop")
def api_social_crop(
    path: str = Query(...),
    preset: str = Query(...),
    user: CurrentUser = Depends(require_edition),
):
    """Return the cropped full-resolution JPEG for a social aspect preset."""
    _require_social_export_enabled()
    aspect_w, aspect_h = _preset_aspect(preset)
    row, faces = _lookup_photo(path, user)
    real_disk = resolve_photo_disk_path(row["path"])

    from utils.image_loading import load_image_from_path

    pil_img, _ = load_image_from_path(real_disk)
    if pil_img is None:
        raise HTTPException(status_code=500, detail="Failed to decode image")
    if pil_img.mode != "RGB":
        pil_img = pil_img.convert("RGB")

    width, height = pil_img.size
    subject_norm, _source = _resolve_subject(row, faces)
    x0, y0, x1, y1 = compute_crop_rect(
        width, height, aspect_w, aspect_h, subject_norm, _margin_frac()
    )
    cropped = pil_img.crop((x0, y0, x1, y1))

    quality = int(_social_export_config().get("jpeg_quality", 92))
    buf = io.BytesIO()
    cropped.save(buf, format="JPEG", quality=quality)
    buf.seek(0)

    stem = os.path.splitext(os.path.basename(row["path"]))[0]
    download_name = f"{stem}_{preset}.jpg"
    return StreamingResponse(
        buf,
        media_type="image/jpeg",
        headers={"Content-Disposition": f'attachment; filename="{download_name}"'},
    )
