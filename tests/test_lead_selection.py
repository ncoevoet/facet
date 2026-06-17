"""
Tests for composite best-of lead selection (utils/selection.py), Topic 4 step 6.

aggregate dominates; eyes-open / expression / sharpness only break near-ties.
"""

from utils.selection import composite_lead_score, pick_lead


def _p(aggregate, **kw):
    return {'aggregate': aggregate, 'face_count': kw.pop('face_count', 1), **kw}


def test_equal_aggregate_open_eyes_wins():
    blinking = _p(7.0, eyes_open_score=1.0)
    open_eyes = _p(7.0, eyes_open_score=10.0)
    assert pick_lead([blinking, open_eyes]) is open_eyes


def test_equal_aggregate_better_expression_wins():
    yawning = _p(6.5, expression_score=0.0)
    composed = _p(6.5, expression_score=10.0)
    assert pick_lead([yawning, composed]) is composed


def test_aggregate_gap_not_overridden_by_eyes():
    # A 0.5 aggregate lead must survive even if the lower one has perfect eyes.
    strong = _p(7.5, eyes_open_score=1.0)
    weak_open = _p(7.0, eyes_open_score=10.0)
    assert pick_lead([strong, weak_open]) is strong


def test_no_face_ignores_eyes_expression():
    # face_count 0 -> eyes/expression terms skipped; sharpness still nudges.
    a = _p(7.0, face_count=0, eyes_open_score=10.0, expression_score=10.0, tech_sharpness=2.0)
    b = _p(7.0, face_count=0, eyes_open_score=0.0, expression_score=0.0, tech_sharpness=8.0)
    # b is sharper -> b wins despite a's (ignored) eyes/expression.
    assert pick_lead([a, b]) is b


def test_neutral_signals_equal_aggregate():
    # Both neutral (5.0) eyes/expression and equal sharpness -> scores equal to aggregate.
    a = _p(7.0, eyes_open_score=5.0, expression_score=5.0, tech_sharpness=5.0)
    assert composite_lead_score(a) == 7.0


def test_pick_lead_empty():
    assert pick_lead([]) is None


def test_missing_fields_fall_back_to_aggregate():
    a = {'aggregate': 8.0}
    b = {'aggregate': 6.0}
    assert pick_lead([a, b]) is a
