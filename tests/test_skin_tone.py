"""Tests for the skin-tone naturalness analyzer (analyzers/skin_tone.py).

Uses synthetic uniform-color face crops generated with the same
crop_face_with_padding helper the scan pipeline uses, with landmarks placed on
the uniform patch, so the landmark re-projection is exercised end to end.
CIEDE2000 is checked against published Sharma et al. (2005) reference pairs.
"""

import numpy as np
import pytest
from PIL import Image

from analyzers.skin_tone import (
    _cast_direction,
    ciede2000,
    compute_photo_skin_tone,
    measure_face_lab,
    skin_tone_delta,
    srgb_to_lab,
)
from analyzers.face import FaceAnalyzer
from utils.image_transforms import crop_face_with_padding

_NEUTRAL_SKIN = (198, 149, 120)
_GREEN_CAST = (150, 200, 120)
_BBOX = [150, 150, 250, 250]
_PADDING = 0.3


# ---------------------------------------------------------------------------
# CIEDE2000 reference values (Sharma, Wu & Dalal 2005 test data)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("lab1, lab2, expected", [
    ((50.0, 2.6772, -79.7751), (50.0, 0.0, -82.7485), 2.0425),
    ((50.0, 3.1571, -77.2803), (50.0, 0.0, -82.7485), 2.8615),
    ((50.0, 2.8361, -74.0200), (50.0, 0.0, -82.7485), 3.4412),
    ((50.0, 2.5, 0.0), (73.0, 25.0, -18.0), 27.1492),
    ((50.0, 2.5, 0.0), (61.0, -5.0, 29.0), 22.8977),
    ((60.2574, -34.0099, 36.2677), (60.4626, -34.1751, 39.4387), 1.2644),
    ((90.8027, -2.0831, 1.4410), (91.1528, -1.6435, 0.0447), 1.4441),
    ((2.0776, 0.0795, -1.1350), (0.9033, -0.0636, -0.5514), 0.9082),
])
def test_ciede2000_reference_pairs(lab1, lab2, expected):
    assert ciede2000(lab1, lab2) == pytest.approx(expected, abs=1e-3)


def test_ciede2000_vectorized_reference_set():
    refs = np.array([(50.0, 0.0, -82.7485), (73.0, 25.0, -18.0)])
    deltas = ciede2000((50.0, 2.6772, -79.7751), refs)
    assert deltas.shape == (2,)
    assert deltas[0] == pytest.approx(2.0425, abs=1e-3)


def test_srgb_to_lab_neutral_axis():
    L, a, b = srgb_to_lab((255, 255, 255))
    assert L == pytest.approx(100.0, abs=0.01)
    assert a == pytest.approx(0.0, abs=0.01)
    assert b == pytest.approx(0.0, abs=0.01)
    L, a, b = srgb_to_lab((119, 119, 119))
    assert L == pytest.approx(50.0, abs=0.2)
    assert abs(a) < 0.01 and abs(b) < 0.01


# ---------------------------------------------------------------------------
# Skin locus + cast direction
# ---------------------------------------------------------------------------


def test_natural_skin_sits_on_locus():
    delta, _, _ = skin_tone_delta(srgb_to_lab(_NEUTRAL_SKIN))
    assert delta < 5.0


def test_green_cast_is_far_from_locus():
    delta, da, db = skin_tone_delta(srgb_to_lab(_GREEN_CAST))
    assert delta > 12.0
    assert da < 0  # deviation pulls a* toward green


@pytest.mark.parametrize("da, db, expected", [
    (-9.0, 2.0, 'green'),
    (9.0, -2.0, 'magenta'),
    (2.0, -9.0, 'blue'),
    (2.0, 9.0, 'yellow'),
])
def test_cast_direction(da, db, expected):
    assert _cast_direction(da, db) == expected


# ---------------------------------------------------------------------------
# Face-crop re-projection + photo-level verdicts
# ---------------------------------------------------------------------------


def _landmarks():
    """106x2 landmarks with eye rings and mouth placed inside the bbox."""
    lm = np.zeros((106, 2), dtype=np.float32)
    lm[FaceAnalyzer.LEFT_EYE_INDICES] = (175.0, 190.0)
    lm[FaceAnalyzer.RIGHT_EYE_INDICES] = (225.0, 190.0)
    lm[FaceAnalyzer.MOUTH_INDICES] = (200.0, 235.0)
    return lm


def _face_row(color, bbox=None):
    """A synthetic faces row: uniform-color crop built by the shared crop helper."""
    bbox = bbox or _BBOX
    img = Image.new('RGB', (400, 400), color)
    thumb = crop_face_with_padding(img, bbox, padding=_PADDING, size=128, use_cv2=False)
    assert thumb is not None
    return {
        'bbox_x1': bbox[0], 'bbox_y1': bbox[1], 'bbox_x2': bbox[2], 'bbox_y2': bbox[3],
        'landmark_2d_106': _landmarks().tobytes(),
        'face_thumbnail': thumb,
    }


def test_measure_face_lab_recovers_patch_color():
    face = _face_row(_NEUTRAL_SKIN)
    lab = measure_face_lab(_BBOX, _landmarks(), face['face_thumbnail'], padding=_PADDING)
    assert lab is not None
    expected = srgb_to_lab(_NEUTRAL_SKIN)
    # JPEG round-trip of a uniform patch stays within ~1 dE of the source color
    assert ciede2000(lab, expected) < 1.5


def test_neutral_skin_verdict():
    delta, cast = compute_photo_skin_tone([_face_row(_NEUTRAL_SKIN)],
                                          padding=_PADDING, cast_threshold=12.0)
    assert delta is not None
    assert delta < 12.0
    assert cast is None


def test_green_cast_verdict():
    delta, cast = compute_photo_skin_tone([_face_row(_GREEN_CAST)],
                                          padding=_PADDING, cast_threshold=12.0)
    assert delta is not None
    assert delta > 12.0
    assert cast == 'green'


def test_worst_face_wins():
    faces = [_face_row(_NEUTRAL_SKIN), _face_row(_GREEN_CAST)]
    delta, cast = compute_photo_skin_tone(faces, padding=_PADDING, cast_threshold=12.0)
    assert cast == 'green'
    assert delta > 12.0


def test_unusable_faces_yield_none():
    face = _face_row(_NEUTRAL_SKIN)
    bad_landmarks = dict(face, landmark_2d_106=b'\x00' * 10)  # not 106x2 float32
    missing_bbox = dict(face, bbox_x1=None)
    delta, cast = compute_photo_skin_tone([bad_landmarks, missing_bbox],
                                          padding=_PADDING, cast_threshold=12.0)
    assert delta is None and cast is None


def test_edge_clamped_crop_is_skipped():
    # A face flush against the right image edge clamps the crop box on one
    # axis, breaking the reconstructed aspect ratio -> indeterminate, not a
    # wrong measurement.
    bbox = [300, 150, 398, 250]
    img = Image.new('RGB', (400, 400), _NEUTRAL_SKIN)
    thumb = crop_face_with_padding(img, bbox, padding=_PADDING, size=128, use_cv2=False)
    lm = np.zeros((106, 2), dtype=np.float32)
    lm[FaceAnalyzer.LEFT_EYE_INDICES] = (320.0, 175.0)
    lm[FaceAnalyzer.RIGHT_EYE_INDICES] = (370.0, 175.0)
    lm[FaceAnalyzer.MOUTH_INDICES] = (345.0, 225.0)
    assert measure_face_lab(bbox, lm, thumb, padding=_PADDING) is None
