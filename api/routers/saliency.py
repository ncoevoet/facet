"""Saliency overlay + face-marker endpoints for the "why this score" view.

Both are read-only and feature-gated. The overlay recomputes the BiRefNet
saliency map on the stored 640px thumbnail on demand (the mask is never
persisted), colourises it as a translucent heatmap PNG, and caches the bytes
briefly. Face markers reconstruct boxes + eye centres from the stored 106-point
landmarks — no model needed.
"""

import io
import logging
from functools import lru_cache
from typing import Optional

import cv2
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from PIL import Image

from api.auth import CurrentUser, get_optional_user
from api.config import VIEWER_CONFIG
from api.database import get_db
from api.db_helpers import get_visibility_clause

logger = logging.getLogger(__name__)

router = APIRouter(tags=["saliency"])


def _require_overlay_enabled():
    if not VIEWER_CONFIG.get("features", {}).get("show_saliency_overlay", True):
        raise HTTPException(status_code=404, detail="Saliency overlay is disabled")


@lru_cache(maxsize=64)
def _render_overlay(thumbnail: bytes) -> bytes:
    """Render the heatmap PNG for a thumbnail, cached so repeated requests for
    the same photo don't re-run BiRefNet on the GPU. Keyed by the raw thumbnail
    bytes, so a re-scanned thumbnail naturally produces a fresh cache entry.
    """
    pil = Image.open(io.BytesIO(thumbnail)).convert("RGB")
    from api.model_cache import get_or_load_saliency_scorer

    scorer = get_or_load_saliency_scorer()
    soft = scorer.get_saliency_soft(pil)  # HxW float 0..1
    heat = (np.clip(soft, 0.0, 1.0) * 255).astype(np.uint8)
    colored = cv2.applyColorMap(heat, cv2.COLORMAP_JET)  # BGR
    bgra = np.dstack([colored, heat])  # alpha = saliency -> background transparent
    ok, buf = cv2.imencode(".png", bgra)
    if not ok:
        raise ValueError("Failed to encode heatmap")
    return buf.tobytes()


@router.get("/api/saliency_overlay")
def api_saliency_overlay(
    path: str = Query(...),
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Return a translucent saliency heatmap PNG for a photo's stored thumbnail.

    Alpha tracks saliency, so the background stays transparent and only the
    subject is tinted. 404s gracefully when the photo has no thumbnail (e.g. a
    profile that never ran the saliency pass).
    """
    _require_overlay_enabled()
    vis_sql, vis_params = get_visibility_clause(user.user_id if user else None)
    with get_db() as conn:
        row = conn.execute(
            f"SELECT thumbnail FROM photos WHERE path = ? AND {vis_sql}",
            [path] + vis_params,
        ).fetchone()
    if not row or row["thumbnail"] is None:
        raise HTTPException(status_code=404, detail="No thumbnail for this photo")

    try:
        png = _render_overlay(row["thumbnail"])
    except ValueError:
        raise HTTPException(status_code=500, detail="Failed to encode heatmap")
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "private, max-age=300"})


@router.get("/api/photo/face_markers")
def api_face_markers(
    path: str = Query(...),
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Per-face boxes + eye centres (normalised 0..1) and eyes-open score.

    Coordinates are normalised by the original image size so the client can
    scale them to whatever resolution it displays.
    """
    _require_overlay_enabled()
    vis_sql, vis_params = get_visibility_clause(user.user_id if user else None)
    with get_db() as conn:
        prow = conn.execute(
            f"SELECT image_width, image_height FROM photos WHERE path = ? AND {vis_sql}",
            [path] + vis_params,
        ).fetchone()
        if not prow:
            raise HTTPException(status_code=404, detail="Unknown photo")
        rows = conn.execute(
            "SELECT bbox_x1, bbox_y1, bbox_x2, bbox_y2, landmark_2d_106 "
            "FROM faces WHERE photo_path = ? ORDER BY face_index", (path,)
        ).fetchall()

    width = prow["image_width"] or 1
    height = prow["image_height"] or 1
    from analyzers.face import FaceAnalyzer

    faces = []
    for r in rows:
        eyes_score = None
        eye_points = []
        blob = r["landmark_2d_106"]
        if blob is not None:
            try:
                lm = np.frombuffer(blob, dtype=np.float32).reshape(106, 2)
                eyes_score = FaceAnalyzer.compute_eyes_open_score(lm)
                left = lm[FaceAnalyzer.LEFT_EYE_INDICES].mean(axis=0)
                right = lm[FaceAnalyzer.RIGHT_EYE_INDICES].mean(axis=0)
                eye_points = [
                    [float(left[0] / width), float(left[1] / height)],
                    [float(right[0] / width), float(right[1] / height)],
                ]
            except (ValueError, TypeError):
                pass
        bbox = None
        if None not in (r["bbox_x1"], r["bbox_y1"], r["bbox_x2"], r["bbox_y2"]):
            bbox = [r["bbox_x1"] / width, r["bbox_y1"] / height,
                    r["bbox_x2"] / width, r["bbox_y2"] / height]
        faces.append({
            "bbox": bbox,
            "eyes": eye_points,
            "eyes_open_score": eyes_score,
            "is_blink": eyes_score is not None and eyes_score <= FaceAnalyzer.EYES_CLOSED_MAX,
        })

    return {"faces": faces}
