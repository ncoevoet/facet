"""Tests for L2 temporal smoothing of narrative moments (models/moment_smoothing.py)."""

from datetime import datetime, timedelta

import numpy as np

from models.moment_smoothing import smooth

_ORDER = ['a', 'b', 'c']


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
