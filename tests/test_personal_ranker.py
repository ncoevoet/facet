"""
Tests for the personal ranker (optimization/personal_ranker.py), Topic 1 steps 1-4.

Pure-function tests verify the RankNet/BT head separates a clean signal
(~100% train, held-out > 0.8). Integration tests verify the CV gate, the
<30-comparison guard, and that a passing gate writes learned_scores.
"""

import sqlite3

import numpy as np
import pytest

from db.schema import init_database
from optimization import personal_ranker as pr


# --- pure-function tests (step 2 verify) ---

def test_fit_separates_single_feature():
    """One feature decides the winner -> ~100% train accuracy, CV > 0.8."""
    rng = np.random.default_rng(0)
    n, f = 200, 6
    a = rng.normal(size=(n, f))
    b = rng.normal(size=(n, f))
    diff = a - b
    # Feature 0 alone decides: a wins iff diff[:,0] > 0.
    y = (diff[:, 0] > 0).astype(np.int64)
    weights = np.ones(n)
    w = pr._fit_logistic(diff, y, weights, C=1.0)
    assert pr._pairwise_accuracy(w, diff, y) >= 0.99
    assert pr._cv_accuracy(diff, y, weights, C=1.0, n_folds=5) > 0.8
    # The decisive feature has the largest-magnitude weight.
    assert abs(w[0]) == pytest.approx(np.abs(w).max())


def test_baseline_accuracy():
    agg_a = np.array([8.0, 3.0, 5.0])
    agg_b = np.array([4.0, 6.0, 5.0])
    y = np.array([1, 1, 0])   # a, a(wrong-by-agg), b
    # pred = agg_a>agg_b -> [True, False, False]; correct vs y -> [T, F, T] = 2/3
    assert pr._baseline_accuracy(agg_a, agg_b, y) == pytest.approx(2 / 3)


# --- integration fixtures ---

_METRIC_COLS = (
    "aesthetic, quality_score, face_quality, face_sharpness, eye_sharpness, "
    "tech_sharpness, comp_score, power_point_score, leading_lines_score, "
    "exposure_score, color_score, contrast_score, dynamic_range_stops, "
    "mean_saturation, noise_sigma, isolation_bonus"
)
_METRIC_VALS = "5, 5, 5, 50, 5, 5, 5, 5, 5, 5, 5, 5, 7, 0.5, 1, 5"


def _emb_bytes(signal, dim=16, rng=None):
    """Embedding whose component 0 carries the preference signal."""
    v = np.full(dim, 0.1, dtype=np.float32)
    v[0] = signal
    if rng is not None:
        v[1:] += rng.normal(scale=0.01, size=dim - 1).astype(np.float32)
    return v.tobytes()


def _seed_photos(db_path, n=40, seed=3, aggregate="signal"):
    """Insert n photos; component-0 of the embedding is the preference signal.

    aggregate="signal" makes aggregate track the signal (baseline strong);
    aggregate="noise" makes it uninformative (baseline ~50%).
    """
    rng = np.random.default_rng(seed)
    conn = sqlite3.connect(db_path)
    signals = {}
    for i in range(n):
        s = float(rng.uniform(0.2, 2.0))
        path = f'/r/p{i:03d}.jpg'
        signals[path] = s
        agg = s * 5.0 if aggregate == "signal" else float(rng.uniform(1, 9))
        conn.execute(
            f"INSERT INTO photos (path, filename, clip_embedding, aggregate, {_METRIC_COLS}) "
            f"VALUES (?, ?, ?, ?, {_METRIC_VALS})",
            (path, f'p{i:03d}.jpg', _emb_bytes(s, rng=rng), agg),
        )
    conn.commit()
    conn.close()
    return signals


def _add_comparisons(db_path, signals, count=60, seed=11, by="signal"):
    """Pairs whose winner is decided by the embedding signal (or by aggregate)."""
    rng = np.random.default_rng(seed)
    paths = list(signals)
    conn = sqlite3.connect(db_path)
    added = 0
    while added < count:
        ia, ib = rng.choice(len(paths), size=2, replace=False)
        pa, pb = paths[ia], paths[ib]
        winner_path = pa if signals[pa] > signals[pb] else pb
        winner = 'a' if winner_path == pa else 'b'
        cur = conn.execute(
            "INSERT OR IGNORE INTO comparisons (photo_a_path, photo_b_path, winner, source) "
            "VALUES (?, ?, ?, 'vote')",
            (pa, pb, winner),
        )
        added += cur.rowcount
    conn.commit()
    conn.close()


@pytest.fixture()
def ranker_db(tmp_path):
    db_path = str(tmp_path / "ranker.db")
    init_database(db_path)
    return db_path


def _learned_count(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM learned_scores WHERE learned_score IS NOT NULL"
        ).fetchone()[0]
    finally:
        conn.close()


# --- integration tests (steps 3-4) ---

def test_too_few_comparisons_returns_error(ranker_db):
    signals = _seed_photos(ranker_db, n=20, aggregate="noise")
    _add_comparisons(ranker_db, signals, count=10)
    result = pr.train_ranker(ranker_db)
    assert 'error' in result
    assert result['n_pairs'] < pr.MIN_COMPARISONS
    assert _learned_count(ranker_db) == 0


def test_embedding_signal_beats_baseline_and_writes(ranker_db):
    # Winner decided by embedding signal; aggregate is uninformative (~50% baseline).
    signals = _seed_photos(ranker_db, n=40, aggregate="noise")
    _add_comparisons(ranker_db, signals, count=80)
    result = pr.train_ranker(ranker_db, min_improvement_pp=2.0)
    assert 'error' not in result
    assert result['cv_accuracy'] > 80.0
    assert result['cv_accuracy'] - result['baseline_accuracy'] >= 2.0
    assert result['gated'] is False
    assert result['written'] > 0
    assert _learned_count(ranker_db) == result['written']


def test_gate_blocks_when_no_improvement_over_aggregate(ranker_db):
    # Winner perfectly tracks aggregate -> baseline ~100%, ranker can't beat it -> gated.
    signals = _seed_photos(ranker_db, n=40, aggregate="signal")
    _add_comparisons(ranker_db, signals, count=80)
    result = pr.train_ranker(ranker_db, min_improvement_pp=2.0)
    assert result.get('gated') is True
    assert result['written'] == 0
    assert _learned_count(ranker_db) == 0


def test_force_writes_despite_gate(ranker_db):
    signals = _seed_photos(ranker_db, n=40, aggregate="signal")
    _add_comparisons(ranker_db, signals, count=80)
    result = pr.train_ranker(ranker_db, min_improvement_pp=2.0, force=True)
    assert result['gated'] is False
    assert result['written'] > 0
    assert _learned_count(ranker_db) > 0
