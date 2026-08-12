"""Saliency overlay, face-marker and key-subject endpoints for photo detail.

All three are read-only and normalise every box the same way (see
``KEY_SUBJECT_COORDINATE_SPACE``). The overlay recomputes the BiRefNet saliency
map on the stored 640px thumbnail on demand (the mask is never persisted),
colourises it as a translucent heatmap PNG, and caches the bytes briefly. Face
markers reconstruct boxes + eye centres from the stored 106-point landmarks —
no model needed.

The overlay and the markers are gated on ``features.show_saliency_overlay``
because the first needs BiRefNet at request time and the second only exists to
annotate it. The key-subject endpoints are deliberately NOT gated: they resolve
"what is this photo about" from persisted columns alone (faces, persons,
``photos.subject_bbox``), run no model, and drive ordinary UI (the darkroom's
zoom target and the key-person badge) rather than the overlay.
"""

import io
import logging
import math
from functools import lru_cache
from typing import Optional

import cv2
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from PIL import Image
from pydantic import BaseModel, Field

from api.auth import CurrentUser, get_optional_user, require_authenticated
from api.config import VIEWER_CONFIG
from api.database import get_db
from api.db_helpers import get_visibility_clause, select_in_chunks
from api.subject_bbox import parse_subject_bbox
from db.schema import person_not_hidden_clause

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
    user: CurrentUser = Depends(require_authenticated),
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
    except RuntimeError:
        logger.exception("Saliency model/inference failure for %s", path)
        raise HTTPException(status_code=503, detail="Saliency model unavailable")
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


# --- Key subject -----------------------------------------------------------
#
# "Who / what is this photo about", resolved on demand from columns that are
# already persisted. Nothing is stored: a rescan rewrites `photos` wholesale, so
# a cached answer would either be silently wiped or silently stale.

KIND_PERSON = "person"
KIND_SUBJECT = "subject"
KIND_NONE = "none"

# Every box this module returns is [x0, y0, x1, y1] in fractions of the frame,
# origin top-left, x before y. The frame is photos.image_width x image_height,
# which for faces is exactly the image the detector saw: one scoring pass hands
# the same `img_cv` array to analyze_faces() (whose boxes go to faces.bbox_*)
# and reads its shape into image_width/image_height, so the two cannot disagree
# whatever a RAW happened to decode to. `subject_bbox` is already persisted in
# this space. The client multiplies by whatever pixel size it displays.
KEY_SUBJECT_COORDINATE_SPACE = "normalized_frame_xyxy"

# Face ranking. `size` is a face's LINEAR size relative to the largest face in
# the frame (sqrt of the area ratio), so the weights are scale-free: they read
# the same on a portrait and on a group shot. Centrality is 1 at the frame
# centre and 0 in a corner.
#
# The three weights fix the "a named person beats a bigger stranger, within
# reason" bound exactly: at equal centrality a named face wins while
# 0.5 * size + 0.3 > 0.5, i.e. down to 0.4x the linear size (16% of the area)
# of the largest unnamed face — a named subject in the middle distance wins, a
# named speck in the background does not. Centrality's 0.2 is deliberately
# worth less than the named bonus (it only settles same-status faces) but more
# than a small size difference, so a centred face beats a marginally larger one
# at the edge.
FACE_SIZE_WEIGHT = 0.5
FACE_CENTRALITY_WEIGHT = 0.2
NAMED_PERSON_WEIGHT = 0.3

# How far outside the frame a face box may legitimately reach. InsightFace does
# not clip its boxes, so a face at the edge overhangs a little; a box beyond
# this is not an overhang but a coordinate-space mismatch — the giveaway that
# `backfill_image_dimensions()` filled the row's dimensions from its 640px
# thumbnail while the boxes are in original-image pixels. Such faces are
# dropped rather than clamped: clamping would pin the "key subject" to a frame
# edge and point the zoom at nothing.
FACE_FRAME_TOLERANCE = 1.25

_KEY_SUBJECT_PHOTO_COLS = (
    "path, image_width, image_height, subject_bbox, subject_sharpness, "
    "subject_prominence, subject_placement, bg_separation"
)
# A hidden person is dropped by the join, so `person_id` and `person_name` both
# come from `persons`: a cluster the user hid can never be badged as the key
# person, it competes as an unnamed face instead. An unnamed (auto-clustered)
# person still reports its id — only its missing name costs it the bonus.
_KEY_SUBJECT_FACE_SELECT = (
    "SELECT f.photo_path, f.id, f.face_index, f.bbox_x1, f.bbox_y1, f.bbox_x2, f.bbox_y2, "
    "p.id AS person_id, p.name AS person_name "
    "FROM faces f LEFT JOIN persons p "
    f"ON p.id = f.person_id AND {person_not_hidden_clause('p')} "
)


class KeySubjectsBody(BaseModel):
    paths: list[str] = Field(max_length=1000)


def _normalized_face_box(x1, y1, x2, y2, width, height):
    """Normalise a pixel face box to the frame, or None when it can't be trusted.

    Returns None for a missing/degenerate box, for a photo with no stored
    dimensions, and for a box that overshoots the frame past
    ``FACE_FRAME_TOLERANCE`` (see the constant: that means the stored dimensions
    are not the detection frame). A legitimate overhang is clamped to the frame.
    """
    if None in (x1, y1, x2, y2) or not width or not height:
        return None
    if width <= 0 or height <= 0 or x2 <= x1 or y2 <= y1:
        return None
    overhang = FACE_FRAME_TOLERANCE - 1.0
    if (x2 > width * FACE_FRAME_TOLERANCE or y2 > height * FACE_FRAME_TOLERANCE
            or x1 < -width * overhang or y1 < -height * overhang):
        return None
    box = [
        max(0.0, min(1.0, x1 / width)), max(0.0, min(1.0, y1 / height)),
        max(0.0, min(1.0, x2 / width)), max(0.0, min(1.0, y2 / height)),
    ]
    if box[2] <= box[0] or box[3] <= box[1]:
        return None
    return box


def _box_centre(box):
    return [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2]


def _centrality(box):
    """1.0 for a box centred in the frame, 0.0 for one centred in a corner."""
    cx, cy = _box_centre(box)
    distance = math.hypot((cx - 0.5) / 0.5, (cy - 0.5) / 0.5) / math.sqrt(2)
    return max(0.0, 1.0 - distance)


def _best_face(faces, width, height):
    """Rank a photo's faces and return the winner's geometry, or None."""
    candidates = []
    for row in faces:
        box = _normalized_face_box(
            row["bbox_x1"], row["bbox_y1"], row["bbox_x2"], row["bbox_y2"], width, height
        )
        if box is None:
            continue
        candidates.append({
            "row": row,
            "box": box,
            "area": (box[2] - box[0]) * (box[3] - box[1]),
            "centrality": _centrality(box),
            "name": (row["person_name"] or "").strip(),
        })
    if not candidates:
        return None

    largest = max(c["area"] for c in candidates)
    for candidate in candidates:
        size = math.sqrt(candidate["area"] / largest) if largest > 0 else 0.0
        candidate["score"] = (
            FACE_SIZE_WEIGHT * size
            + FACE_CENTRALITY_WEIGHT * candidate["centrality"]
            + (NAMED_PERSON_WEIGHT if candidate["name"] else 0.0)
        )
    # Ties break on the earliest face_index so the answer is stable across calls.
    return max(candidates, key=lambda c: (c["score"], -(c["row"]["face_index"] or 0)))


def _empty_key_subject(path, width, height):
    """The full response shape with nothing resolved — every key always present."""
    return {
        "path": path,
        "kind": KIND_NONE,
        "coordinate_space": KEY_SUBJECT_COORDINATE_SPACE,
        "image_width": width,
        "image_height": height,
        "bbox": None,
        "center": None,
        "area_ratio": None,
        "centrality": None,
        "score": None,
        "face_id": None,
        "face_index": None,
        "person_id": None,
        "person_name": None,
        "subject_sharpness": None,
        "subject_prominence": None,
        "subject_placement": None,
        "bg_separation": None,
    }


def resolve_key_subject(row, faces):
    """Resolve one photo's key subject from its own row + its face rows.

    Faces win over saliency whenever a usable face box exists — a photo with a
    person in it is about that person even when BiRefNet locked onto something
    larger. Within the faces, the best mix of relative size, centrality and
    named-person status wins (see the weight constants). With no usable face the
    persisted BiRefNet box takes over, and with neither the answer is ``none``
    rather than a guessed centre crop.

    ``area_ratio`` and ``centrality`` always describe the returned ``bbox``;
    ``score`` is the face ranking score and is null for a saliency subject. The
    ``subject_*`` fields are only filled for ``kind == "subject"`` — they grade
    the saliency box, not the face.
    """
    result = _empty_key_subject(row["path"], row["image_width"], row["image_height"])
    best = _best_face(faces, row["image_width"] or 0, row["image_height"] or 0)
    if best is not None:
        box = best["box"]
        result.update({
            "kind": KIND_PERSON,
            "bbox": [round(v, 4) for v in box],
            "center": [round(v, 4) for v in _box_centre(box)],
            "area_ratio": round(best["area"], 4),
            "centrality": round(best["centrality"], 4),
            "score": round(best["score"], 4),
            "face_id": best["row"]["id"],
            "face_index": best["row"]["face_index"],
            "person_id": best["row"]["person_id"],
            "person_name": best["name"] or None,
        })
        return result

    box = parse_subject_bbox(row["subject_bbox"])
    if box is not None:
        result.update({
            "kind": KIND_SUBJECT,
            "bbox": [round(v, 4) for v in box],
            "center": [round(v, 4) for v in _box_centre(box)],
            "area_ratio": round((box[2] - box[0]) * (box[3] - box[1]), 4),
            "centrality": round(_centrality(box), 4),
            "subject_sharpness": row["subject_sharpness"],
            "subject_prominence": row["subject_prominence"],
            "subject_placement": row["subject_placement"],
            "bg_separation": row["bg_separation"],
        })
    return result


@router.get("/api/photo/key_subject")
def api_key_subject(
    path: str = Query(...),
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """The photo's key subject: the key person's face, else the saliency subject.

    Computed per request from stored columns — no model loads, nothing cached —
    so it always reflects the current face/person assignments. Boxes are in
    ``coordinate_space`` (see ``KEY_SUBJECT_COORDINATE_SPACE``). 404s for an
    unknown photo, and for any photo the caller may not see.
    """
    vis_sql, vis_params = get_visibility_clause(user.user_id if user else None)
    with get_db() as conn:
        row = conn.execute(
            f"SELECT {_KEY_SUBJECT_PHOTO_COLS} FROM photos WHERE path = ? AND {vis_sql}",
            [path] + vis_params,
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Unknown photo")
        faces = conn.execute(
            _KEY_SUBJECT_FACE_SELECT + "WHERE f.photo_path = ? ORDER BY f.face_index",
            (row["path"],),
        ).fetchall()
    return resolve_key_subject(row, faces)


@router.post("/api/photos/key_subjects")
def api_key_subjects(
    body: KeySubjectsBody,
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Key subjects for a set of photos in one call, keyed by path.

    The batch twin of ``/api/photo/key_subject``, for surfaces that need one
    answer per frame of a whole set (the darkroom strip) — the same reason
    ``/api/culling-group/faces`` replaced the per-photo face fan-out. Every
    requested path is present in the response; one the caller may not see (or
    that no longer exists) comes back as ``kind: "none"`` rather than missing,
    so the client never has to distinguish absent from unresolved.
    """
    paths = [p for p in (body.paths or []) if p]
    results = {p: _empty_key_subject(p, None, None) for p in paths}
    if not paths:
        return {"key_subjects_by_path": results}

    vis_sql, vis_params = get_visibility_clause(user.user_id if user else None)
    with get_db() as conn:
        rows = list(select_in_chunks(
            conn,
            f"SELECT {_KEY_SUBJECT_PHOTO_COLS} FROM photos "
            f"WHERE path IN ({{placeholders}}) AND {vis_sql}",
            paths, after=vis_params,
        ))
        visible = [row["path"] for row in rows]
        faces_by_path: dict[str, list] = {p: [] for p in visible}
        for face in select_in_chunks(
            conn,
            _KEY_SUBJECT_FACE_SELECT + "WHERE f.photo_path IN ({placeholders}) "
            "ORDER BY f.photo_path, f.face_index",
            visible,
        ):
            faces_by_path[face["photo_path"]].append(face)

    for row in rows:
        results[row["path"]] = resolve_key_subject(row, faces_by_path[row["path"]])
    return {"key_subjects_by_path": results}
