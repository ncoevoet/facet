"""
Topic 3 steps 1, 5, 6 integration tests (CPU, no model downloads):
- config-gated extended IQA: _IQA_MODELS and build_metric_vector keys appear
  only when enabled; the weight-0 aggregate is byte-identical.
- SRCC harness ranks metrics against labels.
"""

import sqlite3

import pytest

from optimization.iqa_eval import spearman_srcc, evaluate_iqa_srcc
from processing.scorer import build_metric_vector
from config import ScoringConfig
from db.schema import init_database


# --- SRCC harness (step 6) ---

def test_spearman_perfect_and_inverse():
    assert spearman_srcc([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert spearman_srcc([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1.0)


def test_spearman_too_few_or_constant():
    assert spearman_srcc([1, 2], [1, 2]) is None          # < 3 pairs
    assert spearman_srcc([5, 5, 5], [1, 2, 3]) is None     # no variance -> undefined


def test_evaluate_iqa_srcc_over_db(tmp_path):
    db = str(tmp_path / "srcc.db")
    init_database(db)
    conn = sqlite3.connect(db)
    # aesthetic tracks the star rating exactly -> SRCC 1.0; topiq_score is reversed.
    for i, stars in enumerate([1, 2, 3, 4, 5]):
        conn.execute(
            "INSERT INTO photos (path, filename, star_rating, aesthetic, topiq_score) "
            "VALUES (?, ?, ?, ?, ?)",
            (f'/s/{i}.jpg', f'{i}.jpg', stars, float(stars), float(6 - stars)),
        )
    conn.commit()
    conn.close()
    res = evaluate_iqa_srcc(db)
    assert res['aesthetic']['srcc'] == pytest.approx(1.0)
    assert res['aesthetic']['n'] == 5
    assert res['topiq_score']['srcc'] == pytest.approx(-1.0)


# --- config-gated metric exposure (steps 1, 5) ---

def _photo_row():
    return {
        'aesthetic': 6.0, 'qalign_score': 8.0, 'aesthetic_v25': 7.0, 'deqa_score': 9.0,
    }


def test_extended_metrics_absent_when_disabled():
    cfg = ScoringConfig(validate=False)
    cfg.config['iqa_extended'] = {'qalign': False, 'aesthetic_v25': False, 'deqa': False}
    vec = build_metric_vector(_photo_row(), cfg, 'default', weights=cfg.get_weights('default'))
    assert 'qalign' not in vec
    assert 'aesthetic_v25' not in vec
    assert 'deqa' not in vec


def test_extended_metrics_present_when_enabled():
    cfg = ScoringConfig(validate=False)
    cfg.config['iqa_extended'] = {'qalign': True, 'aesthetic_v25': True, 'deqa': True}
    vec = build_metric_vector(_photo_row(), cfg, 'default', weights=cfg.get_weights('default'))
    assert vec['qalign'] == pytest.approx(8.0)
    assert vec['aesthetic_v25'] == pytest.approx(7.0)
    assert vec['deqa'] == pytest.approx(9.0)


def test_iqa_models_property_gated(tmp_path):
    from processing.scorer import Facet
    db = str(tmp_path / "f.db")
    init_database(db)
    f = Facet(db_path=db, lightweight=True)
    base = [m for m, _ in f._IQA_MODELS]
    assert 'qalign' not in base                 # OFF by default
    f.config.config['iqa_extended'] = {'qalign': True}
    enabled = dict(f._IQA_MODELS)
    assert enabled.get('qalign') == 'qalign_score'   # appears when enabled
