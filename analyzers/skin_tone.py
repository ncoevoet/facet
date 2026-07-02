"""Skin-tone naturalness from stored face crops (recompute-time, CPU, no model).

Samples cheek pixels from ``faces.face_thumbnail`` by re-projecting the stored
106-point landmarks into crop space: the padded crop box that
``utils.image_transforms.crop_face_with_padding`` produced is reconstructed
from the stored bbox (0-clamped origin, ``int(face_size * padding)`` pads) and
the scale is recovered from the decoded thumbnail's actual dimensions. Because
bbox, landmarks and pads all live in the same detection space, a uniform
source-space scale (e.g. the RAW embedded-thumbnail vs full-decode factor used
at refill time) cancels out; crops clamped at the far image edge break the
aspect check and are skipped as indeterminate.

The mean cheek color is compared in CIELAB (sRGB D65) against a sampled
natural skin locus — hue angle 35-55 degrees across a generous L*/chroma
envelope, the CIELAB image of the blackbody/CCT skin reflectance line — using
a pure-numpy CIEDE2000. The photo-level verdict is the worst (most deviant)
face; a cast direction (green/magenta/blue/yellow) is reported only when the
delta exceeds the configured threshold. Advisory only — never enters the
aggregate.
"""

import logging

import numpy as np

from analyzers.face import FaceAnalyzer

logger = logging.getLogger("facet.skin_tone")

# Cheek geometry: mid-cheek sits below each eye centre, part-way toward the
# mouth line; the patch radius scales with the inter-eye distance.
_CHEEK_DROP = 0.55
_PATCH_RADIUS_RATIO = 0.12
# Crops clamped at the far image edge distort the recovered scale; skip when
# the per-axis scales disagree by more than this.
_MAX_SCALE_MISMATCH = 0.08
_MIN_PATCH_PIXELS = 9

# Natural skin locus sampled in CIELAB: hue band 35-55 deg, chroma 8-40,
# L* 25-85 (very dark to very fair skin under near-neutral illumination).
_LOCUS_L = np.arange(25.0, 90.0, 5.0)
_LOCUS_C = np.arange(8.0, 42.0, 4.0)
_LOCUS_H = np.arange(35.0, 60.0, 5.0)


def srgb_to_lab(rgb):
    """CIELAB (D65) from an sRGB triplet in 0..255. Returns (L, a, b) floats."""
    c = np.asarray(rgb, dtype=np.float64) / 255.0
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    m = np.array([
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ])
    xyz = m @ lin
    f = xyz / np.array([0.95047, 1.0, 1.08883])
    delta = 6.0 / 29.0
    f = np.where(f > delta ** 3, np.cbrt(f), f / (3 * delta ** 2) + 4.0 / 29.0)
    return (float(116.0 * f[1] - 16.0),
            float(500.0 * (f[0] - f[1])),
            float(200.0 * (f[1] - f[2])))


def ciede2000(lab1, lab2):
    """CIEDE2000 color difference (Sharma et al. 2005 formulation).

    ``lab1`` is a single (L, a, b); ``lab2`` may be a single triplet or an
    (N, 3) array. Returns a float for a single reference, else an (N,) array.
    """
    L1, a1, b1 = (float(v) for v in lab1)
    ref = np.atleast_2d(np.asarray(lab2, dtype=np.float64))
    L2, a2, b2 = ref[:, 0], ref[:, 1], ref[:, 2]
    C1 = np.hypot(a1, b1)
    C2 = np.hypot(a2, b2)
    cbar7 = ((C1 + C2) / 2.0) ** 7
    G = 0.5 * (1.0 - np.sqrt(cbar7 / (cbar7 + 25.0 ** 7)))
    a1p = (1.0 + G) * a1
    a2p = (1.0 + G) * a2
    C1p = np.hypot(a1p, b1)
    C2p = np.hypot(a2p, b2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360.0
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360.0
    dLp = L2 - L1
    dCp = C2p - C1p
    dh = h2p - h1p
    dh = np.where(dh > 180.0, dh - 360.0, dh)
    dh = np.where(dh < -180.0, dh + 360.0, dh)
    dh = np.where(C1p * C2p == 0.0, 0.0, dh)
    dHp = 2.0 * np.sqrt(C1p * C2p) * np.sin(np.radians(dh) / 2.0)
    Lbp = (L1 + L2) / 2.0
    Cbp = (C1p + C2p) / 2.0
    hsum = h1p + h2p
    hbp = np.where(np.abs(h1p - h2p) <= 180.0, hsum / 2.0,
                   np.where(hsum < 360.0, (hsum + 360.0) / 2.0, (hsum - 360.0) / 2.0))
    hbp = np.where(C1p * C2p == 0.0, hsum, hbp)
    T = (1.0 - 0.17 * np.cos(np.radians(hbp - 30.0))
         + 0.24 * np.cos(np.radians(2.0 * hbp))
         + 0.32 * np.cos(np.radians(3.0 * hbp + 6.0))
         - 0.20 * np.cos(np.radians(4.0 * hbp - 63.0)))
    dtheta = 30.0 * np.exp(-(((hbp - 275.0) / 25.0) ** 2))
    cbp7 = Cbp ** 7
    RC = 2.0 * np.sqrt(cbp7 / (cbp7 + 25.0 ** 7))
    SL = 1.0 + 0.015 * (Lbp - 50.0) ** 2 / np.sqrt(20.0 + (Lbp - 50.0) ** 2)
    SC = 1.0 + 0.045 * Cbp
    SH = 1.0 + 0.015 * Cbp * T
    RT = -np.sin(np.radians(2.0 * dtheta)) * RC
    dE = np.sqrt((dLp / SL) ** 2 + (dCp / SC) ** 2 + (dHp / SH) ** 2
                 + RT * (dCp / SC) * (dHp / SH))
    return float(dE[0]) if dE.shape[0] == 1 else dE


_LOCUS_CACHE = None


def _skin_locus():
    """Sampled skin-locus points in CIELAB as an (N, 3) array (module-cached)."""
    global _LOCUS_CACHE
    if _LOCUS_CACHE is None:
        h = np.radians(_LOCUS_H)
        _LOCUS_CACHE = np.asarray([
            (L, C * np.cos(hr), C * np.sin(hr))
            for L in _LOCUS_L for C in _LOCUS_C for hr in h
        ], dtype=np.float64)
    return _LOCUS_CACHE


def _cast_direction(da, db):
    """Dominant deviation axis vs the nearest locus point -> cast label."""
    if abs(da) >= abs(db):
        return 'green' if da < 0 else 'magenta'
    return 'blue' if db < 0 else 'yellow'


def skin_tone_delta(lab):
    """(min CIEDE2000 to the skin locus, delta_a, delta_b vs the nearest point)."""
    locus = _skin_locus()
    deltas = ciede2000(lab, locus)
    i = int(np.argmin(deltas))
    return float(deltas[i]), lab[1] - locus[i][1], lab[2] - locus[i][2]


def measure_face_lab(bbox, landmarks, thumbnail_bytes, padding=0.3):
    """Mean cheek color of one face in CIELAB, or None when indeterminate.

    ``bbox`` and ``landmarks`` are in the stored detection space; the crop box
    of ``thumbnail_bytes`` is reconstructed from them (see module docstring).
    """
    import io

    from PIL import Image

    try:
        img = np.asarray(Image.open(io.BytesIO(thumbnail_bytes)).convert('RGB'), dtype=np.float64)
    except Exception:
        return None
    th, tw = img.shape[:2]
    x1, y1, x2, y2 = (float(v) for v in bbox)
    face_w, face_h = x2 - x1, y2 - y1
    if face_w <= 0 or face_h <= 0:
        return None
    pad_x, pad_y = int(face_w * padding), int(face_h * padding)
    cx1, cy1 = max(0.0, x1 - pad_x), max(0.0, y1 - pad_y)
    crop_w, crop_h = (x2 + pad_x) - cx1, (y2 + pad_y) - cy1
    scale_x, scale_y = tw / crop_w, th / crop_h
    if abs(scale_x - scale_y) > _MAX_SCALE_MISMATCH * max(scale_x, scale_y):
        return None
    left_eye = landmarks[FaceAnalyzer.LEFT_EYE_INDICES].mean(axis=0)
    right_eye = landmarks[FaceAnalyzer.RIGHT_EYE_INDICES].mean(axis=0)
    mouth = landmarks[FaceAnalyzer.MOUTH_INDICES].mean(axis=0)
    eye_dist = float(np.linalg.norm(right_eye - left_eye))
    radius = _PATCH_RADIUS_RATIO * eye_dist * (scale_x + scale_y) / 2.0
    if radius <= 0:
        return None
    r = max(1, int(round(radius)))
    pixels = []
    for eye in (left_eye, right_eye):
        cheek_x = float(eye[0])
        cheek_y = float(eye[1]) + _CHEEK_DROP * (float(mouth[1]) - float(eye[1]))
        px = int(round((cheek_x - cx1) * scale_x))
        py = int(round((cheek_y - cy1) * scale_y))
        px1, px2 = max(0, px - r), min(tw, px + r + 1)
        py1, py2 = max(0, py - r), min(th, py + r + 1)
        if px2 > px1 and py2 > py1:
            pixels.append(img[py1:py2, px1:px2].reshape(-1, 3))
    if not pixels:
        return None
    pixels = np.concatenate(pixels)
    if pixels.shape[0] < _MIN_PATCH_PIXELS:
        return None
    return srgb_to_lab(pixels.mean(axis=0))


def compute_photo_skin_tone(faces, padding=0.3, cast_threshold=12.0):
    """Worst-face (delta, cast) over a photo's faces rows, or (None, None).

    ``faces`` is an iterable of mappings/sqlite rows with ``bbox_x1..bbox_y2``,
    ``landmark_2d_106`` and ``face_thumbnail``. ``cast`` is None when the worst
    delta stays at or below ``cast_threshold`` (natural / indeterminate).
    """
    worst = None
    for face in faces:
        bbox = (face['bbox_x1'], face['bbox_y1'], face['bbox_x2'], face['bbox_y2'])
        blob = face['landmark_2d_106']
        thumb = face['face_thumbnail']
        if None in bbox or not blob or not thumb:
            continue
        try:
            landmarks = np.frombuffer(blob, dtype=np.float32).reshape(106, 2)
        except ValueError:
            continue
        lab = measure_face_lab(bbox, landmarks, thumb, padding=padding)
        if lab is None:
            continue
        delta, da, db = skin_tone_delta(lab)
        if worst is None or delta > worst[0]:
            worst = (delta, da, db)
    if worst is None:
        return None, None
    delta, da, db = worst
    cast = _cast_direction(da, db) if delta > cast_threshold else None
    return delta, cast
