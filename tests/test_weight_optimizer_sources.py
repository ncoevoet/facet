"""Tests for source-aware weight optimization (optimization/weight_optimizer.py).

Verifies the refactored _fetch_comparison_data, source filtering, that the
source reliability weighting actually shifts the optimum when a noisy source
disagrees with explicit votes, the production-aligned feature space, the
config-key apply path, and the held-out gate on the apply decision.
"""

import json
import shutil
import sqlite3
from pathlib import Path

import numpy as np
import pytest

from db.schema import init_database
from optimization.weight_optimizer import WeightOptimizer, run_weight_optimization

REPO_CONFIG = Path(__file__).resolve().parent.parent / 'scoring_config.json'


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


class TestFeatureSpaceAlignment:
    def test_components_are_config_metric_keys(self):
        keys = set(WeightOptimizer.SCORE_COMPONENTS)
        # Metrics the production scorer weights but the old optimizer omitted
        for k in ('liqe', 'aesthetic_iaa', 'face_quality_iqa',
                  'subject_sharpness', 'subject_prominence', 'subject_placement',
                  'bg_separation'):
            assert k in keys, f"{k} must be optimizable"
        # 'quality' is always 0 in scoring (redistributed into aesthetic)
        assert 'quality' not in keys
        # No stale DB-column names leaking in
        for stale in ('comp_score', 'color_score', 'noise_sigma', 'mean_saturation',
                      'dynamic_range_stops', 'isolation_bonus', 'quality_score'):
            assert stale not in keys

    def test_liqe_feature_tracks_liqe_score_column(self, tmp_path):
        db_path = str(tmp_path / "feat.db")
        init_database(db_path)
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO photos (path, filename, liqe_score) VALUES ('/p.jpg', 'p.jpg', 9.0)"
        )
        conn.commit()
        conn.close()
        opt = WeightOptimizer(db_path, str(REPO_CONFIG))
        from db import get_connection
        with get_connection(db_path) as conn:
            row = dict(conn.execute("SELECT * FROM photos WHERE path='/p.jpg'").fetchone())
        idx = opt.SCORE_COMPONENTS.index('liqe')
        vec = opt._metric_vector(row, category='portrait')
        assert vec[idx] == pytest.approx(9.0)


class TestApplyWritesConfigKeys:
    def test_apply_writes_metric_percent_keys(self, tmp_path):
        cfg = tmp_path / "cfg.json"
        cfg.write_text(json.dumps(
            {"categories": [{"name": "portrait", "weights": {"aesthetic_percent": 100}}]}
        ))
        opt = WeightOptimizer("unused.db", str(cfg))
        opt.apply_optimized_weights(
            {"liqe": 0.4, "subject_sharpness": 0.6}, category="portrait", backup=False
        )
        weights = json.loads(cfg.read_text())["categories"][0]["weights"]
        assert weights["liqe_percent"] == 40.0
        assert weights["subject_sharpness_percent"] == 60.0

    def test_apply_strips_stale_db_column_keys(self, tmp_path):
        # A pre-alignment apply could leave DB-column-named keys that the scorer
        # never reads but get_weights would still renormalize over, diluting the
        # real metrics. apply must remove them.
        cfg = tmp_path / "cfg.json"
        cfg.write_text(json.dumps({"categories": [{"name": "portrait", "weights": {
            "aesthetic_percent": 50,
            "noise_sigma_percent": 30,      # stale DB-column name
            "mean_saturation_percent": 20,  # stale DB-column name
        }}]}))
        opt = WeightOptimizer("unused.db", str(cfg))
        opt.apply_optimized_weights({"aesthetic": 0.5, "liqe": 0.5}, category="portrait", backup=False)
        weights = json.loads(cfg.read_text())["categories"][0]["weights"]
        assert "noise_sigma_percent" not in weights
        assert "mean_saturation_percent" not in weights
        # quality is a real (redistributed) metric key and must be preserved if present
        assert weights["liqe_percent"] == 50.0

    def test_apply_keeps_enabled_extended_iqa_weight(self, tmp_path):
        # When the extended-IQA tier is enabled, its weighted *_percent is a real
        # (config-gated) scoring metric and must survive the stale-key strip; a
        # genuinely-unknown key is still removed.
        cfg = tmp_path / "cfg.json"
        cfg.write_text(json.dumps({
            "iqa_extended": {"qalign": True},
            "categories": [{"name": "portrait", "weights": {
                "aesthetic_percent": 50,
                "qalign_percent": 10,        # enabled extended metric -> keep
                "bogus_metric_percent": 5,   # unknown -> strip
            }}],
        }))
        opt = WeightOptimizer("unused.db", str(cfg))
        opt.apply_optimized_weights(
            {"aesthetic": 0.6, "face_quality": 0.4}, category="portrait", backup=False
        )
        weights = json.loads(cfg.read_text())["categories"][0]["weights"]
        assert weights["qalign_percent"] == 10        # preserved (tier enabled)
        assert "bogus_metric_percent" not in weights   # stripped (unknown)
        assert weights["aesthetic_percent"] == 60.0

    def test_apply_strips_extended_iqa_weight_when_disabled(self, tmp_path):
        # With the tier OFF (default), an extended *_percent key is just cruft.
        cfg = tmp_path / "cfg.json"
        cfg.write_text(json.dumps({"categories": [{"name": "portrait", "weights": {
            "aesthetic_percent": 90,
            "qalign_percent": 10,   # tier disabled -> strip
        }}]}))
        opt = WeightOptimizer("unused.db", str(cfg))
        opt.apply_optimized_weights({"aesthetic": 1.0}, category="portrait", backup=False)
        weights = json.loads(cfg.read_text())["categories"][0]["weights"]
        assert "qalign_percent" not in weights


class TestHeldOutGate:
    def _setup(self, tmp_path):
        db_path = str(tmp_path / "gate.db")
        init_database(db_path)
        aesthetics = _seed(db_path)
        _add_comparisons(db_path, aesthetics, "vote", agree=True, count=80)
        # run_weight_optimization(category='default') filters by comparison
        # category, so tag the seeded votes accordingly
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE comparisons SET category = 'default'")
        conn.commit()
        conn.close()
        cfg = tmp_path / "cfg.json"
        shutil.copy(REPO_CONFIG, cfg)
        return db_path, str(cfg)

    def test_gate_blocks_apply_when_improvement_below_threshold(self, tmp_path):
        db_path, cfg = self._setup(tmp_path)
        before = Path(cfg).read_text()
        run_weight_optimization(
            db_path=db_path, config_path=cfg, category="default",
            min_comparisons=30, min_improvement=999.0,
        )
        assert Path(cfg).read_text() == before  # nothing written

    def test_force_applies_despite_gate(self, tmp_path):
        db_path, cfg = self._setup(tmp_path)
        before = Path(cfg).read_text()
        run_weight_optimization(
            db_path=db_path, config_path=cfg, category="default",
            min_comparisons=30, min_improvement=999.0, force=True,
        )
        assert Path(cfg).read_text() != before  # forced write
