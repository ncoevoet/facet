"""
Synthetic-landmark tests for the eyes-open / expression scorers
(FaceAnalyzer.compute_eyes_open_score / compute_expression_score), Topic 4 step 4.

We synthesize 106-point landmark arrays placing only the indices the scorers
read, so the geometry (EAR, mouth extent) is exactly controlled.
"""

import numpy as np

from analyzers.face import FaceAnalyzer as FA


def _base():
    return np.zeros((106, 2), dtype=np.float32)


def _set_eye(lm, indices, h, ear):
    """Place one eye: outer/inner span `h`, vertical opening `ear*h`."""
    outer, inner, up1, up2, lo1, lo2 = indices
    v = ear * h
    lm[outer] = (0.0, 0.0)
    lm[inner] = (h, 0.0)
    lm[up1] = (0.3 * h, v / 2)
    lm[lo1] = (0.3 * h, -v / 2)
    lm[up2] = (0.6 * h, v / 2)
    lm[lo2] = (0.6 * h, -v / 2)


def _set_mouth(lm, w, h, x0=50.0, y0=50.0):
    """Spread the mouth block (52-71) over a w x h rectangle."""
    idx = FA.MOUTH_INDICES
    n = len(idx)
    for k, i in enumerate(idx):
        # alternate top/bottom rows so both x and y extents are realized
        lm[i] = (x0 + (k / (n - 1)) * w, y0 + (h if k % 2 else 0.0))


def _face(eye_h_l=10.0, eye_h_r=10.0, ear_l=0.28, ear_r=0.28, mouth_w=10.0, mouth_h=2.0):
    lm = _base()
    _set_eye(lm, FA.LEFT_EYE_INDICES, eye_h_l, ear_l)
    _set_eye(lm, FA.RIGHT_EYE_INDICES, eye_h_r, ear_r)
    _set_mouth(lm, mouth_w, mouth_h)
    return lm


# --- eyes-open ---

def test_open_eyes_high():
    score = FA.compute_eyes_open_score(_face(ear_l=0.30, ear_r=0.30))
    assert score is not None and score >= 9.0


def test_closed_eyes_low():
    score = FA.compute_eyes_open_score(_face(ear_l=0.08, ear_r=0.08))
    assert score is not None and score <= 1.0


def test_half_open_mid():
    # EAR 0.20 sits between EAR_CLOSED (0.12) and EAR_OPEN (0.28) -> ~5.
    score = FA.compute_eyes_open_score(_face(ear_l=0.20, ear_r=0.20))
    assert 3.5 <= score <= 6.5


def test_turned_head_neutral_via_landmarks():
    # Right eye foreshortened to 30% of left width -> ratio < 0.45 -> neutral.
    assert FA.compute_eyes_open_score(_face(eye_h_l=10.0, eye_h_r=3.0)) is None


def test_turned_head_neutral_via_pose():
    score = FA.compute_eyes_open_score(_face(ear_l=0.30, ear_r=0.30), pose=[50.0, 0.0, 0.0])
    assert score is None


def test_pose_within_gate_not_neutral():
    score = FA.compute_eyes_open_score(_face(ear_l=0.30, ear_r=0.30), pose=[10.0, 5.0, 0.0])
    assert score is not None and score >= 9.0


# --- expression ---

def test_composed_mouth_high():
    # Flat mouth (closed / slight): open_ratio ~0.1, below open_lo (0.36) -> high.
    score = FA.compute_expression_score(_face(mouth_w=20.0, mouth_h=2.0))
    assert score is not None and score >= 9.0


def test_wide_open_mouth_low():
    # Tall mouth box: open_ratio ~0.9, above open_hi (0.84) -> low.
    score = FA.compute_expression_score(_face(mouth_w=20.0, mouth_h=18.0))
    assert score is not None and score <= 1.0


def test_typical_mouth_mid():
    # open_ratio ~0.5 (near the real median) -> mid-range, not saturated.
    score = FA.compute_expression_score(_face(mouth_w=20.0, mouth_h=10.0))
    assert 4.0 <= score <= 8.0


def test_degenerate_mouth_none():
    lm = _base()  # all-zero mouth -> width 0 -> None
    assert FA.compute_expression_score(lm) is None


# --- aggregation ---

def test_aggregate_eyes_open_is_min():
    assert FA.aggregate_eyes_open([9.0, 2.0, None, 7.0]) == 2.0
    assert FA.aggregate_eyes_open([None, None]) is None


def test_aggregate_expression_is_mean():
    assert FA.aggregate_expression([6.0, 8.0, None]) == 7.0
    assert FA.aggregate_expression([]) is None
