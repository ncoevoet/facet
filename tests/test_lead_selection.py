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


def test_learned_score_influences_when_present():
    # Equal aggregate; the higher learned_score wins (Topic 4 step 7).
    low = _p(7.0, face_count=0, learned_score=2.0)
    high = _p(7.0, face_count=0, learned_score=9.0)
    assert pick_lead([low, high]) is high


def test_learned_score_inert_when_absent():
    # No learned_score key -> identical to the eyes/expression-only behavior.
    a = {'aggregate': 7.0, 'face_count': 1, 'eyes_open_score': 10.0}
    b = {'aggregate': 7.0, 'face_count': 1, 'eyes_open_score': 1.0}
    assert pick_lead([a, b]) is a
    # And a None learned_score must not change the score.
    assert composite_lead_score({'aggregate': 7.0, 'learned_score': None}) == 7.0


def test_process_bursts_uses_composite_tiebreak(tmp_path):
    """Integration guard for the LIVE burst path (processing.scorer.process_bursts).

    The composite tie-break was once wired only into an unused alternative burst
    processor, while process_bursts still picked the lead via raw max(aggregate)
    and never loaded the eyes/expression columns. This test puts a
    blink frame with a *slightly higher* aggregate in the same burst as an open-eyes
    frame and asserts the open-eyes frame wins — it FAILS on the old max(aggregate).
    """
    import os
    import sqlite3
    from db.schema import init_database
    from processing.scorer import process_bursts

    db_path = str(tmp_path / "burst.db")
    init_database(db_path)

    phash = "ffff0000ffff0000"          # identical -> Hamming 0, always co-bursts
    when = "2024:01:01 12:00:00"        # identical timestamps -> within any window
    rows = [
        # (path, filename, aggregate, eyes_open_score) — blink leads on aggregate
        ("/blink.jpg", "blink.jpg", 7.05, 1.0),
        ("/open.jpg", "open.jpg", 7.00, 10.0),
    ]
    conn = sqlite3.connect(db_path)
    for path, filename, agg, eyes in rows:
        conn.execute(
            "INSERT INTO photos (path, filename, date_taken, aggregate, phash, "
            "face_count, eyes_open_score, expression_score, tech_sharpness) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (path, filename, when, agg, phash, 1, eyes, 5.0, 5.0),
        )
    conn.commit()
    conn.close()

    config_path = os.path.join(os.path.dirname(__file__), "..", "scoring_config.json")
    process_bursts(db_path, config_path=config_path)

    conn = sqlite3.connect(db_path)
    leads = dict(conn.execute("SELECT path, is_burst_lead FROM photos").fetchall())
    groups = dict(conn.execute("SELECT path, burst_group_id FROM photos").fetchall())
    conn.close()

    # Both frames landed in one burst group, and the open-eyes frame is the lead
    # despite the blink frame's higher aggregate.
    assert groups["/open.jpg"] is not None
    assert groups["/open.jpg"] == groups["/blink.jpg"]
    assert leads["/open.jpg"] == 1
    assert leads["/blink.jpg"] == 0
