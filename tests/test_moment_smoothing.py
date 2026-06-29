"""Tests for L2 temporal smoothing of narrative moments (models/moment_smoothing.py)."""

from datetime import datetime, timedelta

import numpy as np

from models.moment_smoothing import _segment_ranges, smooth

_ORDER = ['a', 'b', 'c']

# Shipped config (scoring_config.json): stay-heavy, no forward bias, partial weight.
_PROD = {'order': _ORDER, 'stay_prob': 0.7, 'forward_bias': 0.0, 'weight': 0.3}


def _peaked(n, peak, mass=0.9):
    p = np.full(n, (1.0 - mass) / (n - 1))
    p[peak] = mass
    return p / p.sum()


def _times(n, step_seconds=30):
    base = datetime(2024, 6, 15, 10, 0, 0)
    return [base + timedelta(seconds=step_seconds * i) for i in range(n)]


def test_corrects_single_misfire_in_a_run():
    # Seven frames clearly on 'b', with frame 3 misreading as 'a'.
    probs = [_peaked(3, 1) for _ in range(7)]
    probs[3] = _peaked(3, 0)
    transitions = {'order': _ORDER, 'stay_prob': 0.6, 'forward_bias': 0.3, 'weight': 1.0}
    out = smooth(probs, _times(7), transitions)
    labels = [o[0] for o in out]
    assert labels[3] == 1                      # the misfire is pulled back to 'b'
    assert all(label == 1 for label in labels)


def test_weight_zero_equals_raw_argmax():
    probs = [_peaked(3, i % 3) for i in range(6)]
    probs[2] = _peaked(3, 0)
    transitions = {'order': _ORDER, 'stay_prob': 0.6, 'forward_bias': 0.3, 'weight': 0.0}
    out = smooth(probs, _times(6), transitions)
    labels = [o[0] for o in out]
    assert labels == [int(np.argmax(p)) for p in probs]


def test_none_vectors_pass_through():
    out = smooth([None, None], [None, None], {'order': _ORDER, 'weight': 1.0})
    assert out == [(None, None), (None, None)]


def test_empty_order_is_noop():
    probs = [_peaked(3, 0)]
    out = smooth(probs, _times(1), {'order': [], 'weight': 1.0})
    assert out == [(None, None)]


def test_segment_ranges_splits_on_large_gap():
    base = datetime(2024, 6, 15, 10, 0, 0)
    times = [base, base + timedelta(seconds=30), base + timedelta(seconds=60),
             base + timedelta(hours=8), base + timedelta(hours=8, seconds=30)]
    assert _segment_ranges(times, 6 * 3600) == [(0, 3), (3, 5)]


def test_segment_ranges_single_when_no_large_gap():
    times = _times(4)
    assert _segment_ranges(times, 6 * 3600) == [(0, 4)]


def test_segment_ranges_never_splits_around_none_timestamp():
    base = datetime(2024, 6, 15, 10, 0, 0)
    times = [base, None, base + timedelta(hours=8)]
    assert _segment_ranges(times, 6 * 3600) == [(0, 3)]


def test_gap_isolates_segments_so_one_run_cant_bleed_into_another():
    # Segment 1 on 'a', segment 2 (>6h later) on 'c'. With the gap honoured each
    # is Viterbi-smoothed alone; merging them would let the transition matrix pull
    # the boundary frames together.
    probs = [_peaked(3, 0) for _ in range(4)] + [_peaked(3, 2) for _ in range(4)]
    base = datetime(2024, 6, 15, 10, 0, 0)
    times = [base + timedelta(seconds=30 * i) for i in range(4)]
    times += [base + timedelta(hours=8) + timedelta(seconds=30 * i) for i in range(4)]
    out = smooth(probs, times, _PROD)
    labels = [o[0] for o in out]
    assert labels[:4] == [0, 0, 0, 0]
    assert labels[4:] == [2, 2, 2, 2]


def test_corrected_frame_reports_posterior_not_raw_emission():
    # A confident misfire inside a strong 'b' run: Viterbi corrects the label,
    # and the forward-backward posterior reports HIGH confidence for the
    # corrected state — not the ~0.05 per-frame emission the context-blind model
    # gave 'b' at that frame (the F21 inversion fix).
    probs = [_peaked(3, 1, mass=0.9) for _ in range(7)]
    probs[3] = _peaked(3, 0, mass=0.9)            # confident misfire toward 'a'
    transitions = {'order': _ORDER, 'stay_prob': 0.7, 'forward_bias': 0.0, 'weight': 1.0}
    label, conf = smooth(probs, _times(7), transitions)[3]
    assert label == 1                              # corrected to the run's state 'b'
    assert conf > 0.5                              # posterior is high (context dominates)
    assert conf > probs[3][1]                      # strictly above the raw 'b' emission (0.05)


def test_weight_zero_confidence_equals_normalized_emission():
    # At weight=0 the posterior reduces to the normalized per-frame emission, so
    # confidence matches the chosen state's own probability mass.
    probs = [_peaked(3, i % 3) for i in range(4)]
    transitions = {'order': _ORDER, 'stay_prob': 0.6, 'forward_bias': 0.3, 'weight': 0.0}
    out = smooth(probs, _times(4), transitions)
    for (j, conf), p in zip(out, probs):
        assert abs(conf - p[j] / p.sum()) < 1e-6


def test_production_params_correct_borderline_misfire_but_not_a_confident_one():
    # Production weight (0.3) is a partial blend: a weak/borderline misfire is
    # pulled back into the surrounding run, but a confident one survives.
    borderline = [_peaked(3, 1) for _ in range(7)]
    borderline[3] = _peaked(3, 0, mass=0.45)
    assert smooth(borderline, _times(7), _PROD)[3][0] == 1

    confident = [_peaked(3, 1) for _ in range(7)]
    confident[3] = _peaked(3, 0, mass=0.95)
    assert smooth(confident, _times(7), _PROD)[3][0] == 0
