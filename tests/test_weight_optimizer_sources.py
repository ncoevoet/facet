"""Tests for source-aware weight optimization (optimization/weight_optimizer.py).

Verifies the refactored _fetch_comparison_data, source filtering, and that
the source reliability weighting actually shifts the optimum when a noisy
source disagrees with explicit votes.
"""

import sqlite3

import numpy as np
import pytest

from db.schema import init_database
from optimization.weight_optimizer import WeightOptimizer


def _seed(db_path, n_photos=40, seed=3):
    """Photos where 'aesthetic' is the only informative metric."""
    rng = np.random.default_rng(seed)
    conn = sqlite3.connect(db_path)
    photos = []
    for i in range(n_photos):
        aesthetic = float(rng.uniform(1, 9))
        photos.append((f'/w/p{i:03d}.jpg', f'p{i:03d}.jpg', aesthetic))
    conn.executemany(
        """INSERT INTO photos (path, filename, aesthetic, quality_score, face_quality,
               face_sharpness, eye_sharpness, tech_sharpness, comp_score,
               power_point_score, leading_lines_score, exposure_score, color_score,
               contrast_score, dynamic_range_stops, mean_saturation, noise_sigma,
               isolation_bonus, aggregate)
           VALUES (?, ?, ?, 5, 5, 50, 5, 5, 5, 5, 5, 5, 5, 5, 7, 0.5, 1, 5, 5)""",
        photos,
    )
    conn.commit()
    conn.close()
    return {path: aesthetic for path, _, aesthetic in photos}


def _add_comparisons(db_path, aesthetics, source, agree=True, count=60, seed=11):
    """Pairs whose winner agrees (or disagrees) with the aesthetic ordering."""
    rng = np.random.default_rng(seed)
    paths = list(aesthetics)
    conn = sqlite3.connect(db_path)
    added = 0
    while added < count:
        a, b = rng.choice(len(paths), size=2, replace=False)
        pa, pb = sorted((paths[a], paths[b]))
        better = pa if aesthetics[pa] > aesthetics[pb] else pb
        winner_path = better if agree else (pa if better == pb else pb)
        winner = 'a' if winner_path == pa else 'b'
        cur = conn.execute(
            "INSERT OR IGNORE INTO comparisons "
            "(photo_a_path, photo_b_path, winner, source) VALUES (?, ?, ?, ?)",
            (pa, pb, winner, source),
        )
        added += cur.rowcount
    conn.commit()
    conn.close()


@pytest.fixture()
def optimizer_db(tmp_path):
    db_path = str(tmp_path / "opt.db")
    init_database(db_path)
    aesthetics = _seed(db_path)
    return db_path, aesthetics


class TestFetchComparisonData:
    def test_returns_sources_and_row_weights(self, optimizer_db):
        db_path, aesthetics = optimizer_db
        _add_comparisons(db_path, aesthetics, 'vote', count=10)
        _add_comparisons(db_path, aesthetics, 'culling', count=10, seed=22)
        optimizer = WeightOptimizer(db_path)
        from db import get_connection
        with get_connection(db_path) as conn:
            comps, X_a, X_b, winners, rw = optimizer._fetch_comparison_data(conn)
        assert len(comps) == len(winners) == len(rw) == X_a.shape[0]
        sources = {c['source'] for c in comps}
        assert sources == {'vote', 'culling'}
        weight_by_source = {c['source']: w for c, w in zip(comps, rw)}
        assert weight_by_source['vote'] == 1.0
        assert weight_by_source['culling'] == 0.5

    def test_source_filter(self, optimizer_db):
        db_path, aesthetics = optimizer_db
        _add_comparisons(db_path, aesthetics, 'vote', count=10)
        _add_comparisons(db_path, aesthetics, 'rating', count=10, seed=22)
        optimizer = WeightOptimizer(db_path)
        from db import get_connection
        with get_connection(db_path) as conn:
            comps, *_ = optimizer._fetch_comparison_data(conn, sources=['vote'])
        assert {c['source'] for c in comps} == {'vote'}

    def test_empty_result_shape(self, optimizer_db):
        db_path, _ = optimizer_db
        optimizer = WeightOptimizer(db_path)
        from db import get_connection
        with get_connection(db_path) as conn:
            comps, X_a, X_b, winners, rw = optimizer._fetch_comparison_data(conn)
        assert comps == []
        assert X_a.shape == (0, len(WeightOptimizer.SCORE_COMPONENTS))


class TestOptimizationRecoversPlantedSignal:
    def test_aesthetic_dominates_when_votes_track_it(self, optimizer_db):
        db_path, aesthetics = optimizer_db
        _add_comparisons(db_path, aesthetics, 'vote', agree=True, count=80)
        optimizer = WeightOptimizer(db_path)
        result = optimizer.optimize_weights_direct(min_comparisons=30)
        assert 'error' not in result
        new_weights = result['new_weights']
        top_metric = max(new_weights, key=new_weights.get)
        assert top_metric == 'aesthetic'
        assert result['accuracy_after'] >= 90.0
        assert result['source_counts'] == {'vote': 80}

    def test_sources_vote_excludes_synthetic_rows(self, optimizer_db):
        db_path, aesthetics = optimizer_db
        _add_comparisons(db_path, aesthetics, 'vote', agree=True, count=60)
        _add_comparisons(db_path, aesthetics, 'rating', agree=False, count=60, seed=33)
        optimizer = WeightOptimizer(db_path)
        result = optimizer.optimize_weights_direct(min_comparisons=30, sources=['vote'])
        assert result['comparisons_used'] == 60
        assert result['source_counts'] == {'vote': 60}

    def test_noisy_low_weight_source_degrades_accuracy_less(self, optimizer_db):
        """A disagreeing 'culling' source (weight 0.5) must hurt the optimum
        less than the same rows would as full-weight votes."""
        db_path, aesthetics = optimizer_db
        _add_comparisons(db_path, aesthetics, 'vote', agree=True, count=60)
        _add_comparisons(db_path, aesthetics, 'culling', agree=False, count=40, seed=33)
        optimizer = WeightOptimizer(db_path)
        weighted = optimizer.optimize_weights_direct(min_comparisons=30)

        # Same data, but poison rows promoted to full-weight votes
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE comparisons SET source = 'vote' WHERE source = 'culling'")
        conn.commit()
        conn.close()
        unweighted = optimizer.optimize_weights_direct(min_comparisons=30)

        # With down-weighting, the optimizer should track the clean votes better
        assert weighted['new_weights']['aesthetic'] >= unweighted['new_weights']['aesthetic']
