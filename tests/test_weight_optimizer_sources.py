"""Tests for source-aware weight optimization (optimization/weight_optimizer.py).

Verifies the refactored _fetch_comparison_data, source filtering, that the
source reliability weighting actually shifts the optimum when a noisy source
disagrees with explicit votes, the production-aligned feature space, the
config-key apply path, and the held-out gate on the apply decision.
"""

import json
import os
import shutil
import sqlite3
import stat
import subprocess
from pathlib import Path
from unittest import mock

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
            "iqa_extended": {"qrealign": True},
            "categories": [{"name": "portrait", "weights": {
                "aesthetic_percent": 50,
                "qrealign_percent": 10,      # enabled extended metric -> keep
                "bogus_metric_percent": 5,   # unknown -> strip
            }}],
        }))
        opt = WeightOptimizer("unused.db", str(cfg))
        opt.apply_optimized_weights(
            {"aesthetic": 0.6, "face_quality": 0.4}, category="portrait", backup=False
        )
        weights = json.loads(cfg.read_text())["categories"][0]["weights"]
        assert weights["qrealign_percent"] == 10      # preserved (tier enabled)
        assert "bogus_metric_percent" not in weights   # stripped (unknown)
        assert weights["aesthetic_percent"] == 60.0

    def test_apply_strips_extended_iqa_weight_when_disabled(self, tmp_path):
        # With the metric turned OFF, its *_percent key is just cruft. Explicit
        # false rather than the default, because qrealign's default is "auto"
        # and would follow whatever profile the box resolves to.
        cfg = tmp_path / "cfg.json"
        cfg.write_text(json.dumps({
            "iqa_extended": {"qrealign": False},
            "categories": [{"name": "portrait", "weights": {
                "aesthetic_percent": 90,
                "qrealign_percent": 10,   # metric disabled -> strip
            }}],
        }))
        opt = WeightOptimizer("unused.db", str(cfg))
        opt.apply_optimized_weights({"aesthetic": 1.0}, category="portrait", backup=False)
        weights = json.loads(cfg.read_text())["categories"][0]["weights"]
        assert "qrealign_percent" not in weights


class TestCVFoldsMatchDeployedObjective:
    """The held-out CV gate must score the SAME model optimize_weights_direct
    ships: L2-regularized toward the current config weights. Before the fix,
    each fold's fit was unregularized and started from a uniform prior, so the
    reported CV accuracy was gating a different model than the one applied.
    """

    def test_l2_regularization_defaults_match_direct_optimization(self):
        import inspect
        direct_default = inspect.signature(
            WeightOptimizer.optimize_weights_direct
        ).parameters['l2_regularization'].default
        cv_default = inspect.signature(
            WeightOptimizer.optimize_weights_with_cv
        ).parameters['l2_regularization'].default
        assert direct_default == cv_default

    def test_high_l2_pulls_every_fold_toward_current_weights(self, optimizer_db):
        db_path, aesthetics = optimizer_db
        _add_comparisons(db_path, aesthetics, 'vote', agree=True, count=80)
        optimizer = WeightOptimizer(db_path)

        old_weights = optimizer._load_current_weights(None)
        n = len(WeightOptimizer.SCORE_COMPONENTS)
        old_w = np.array([old_weights.get(c, 1.0 / n) for c in WeightOptimizer.SCORE_COMPONENTS])
        old_w = old_w / old_w.sum()

        # A huge L2 penalty should overwhelm the comparison-fit term in every
        # fold, so the averaged CV weights land right back on the current
        # config weights -- only possible if each fold is actually anchored to
        # old_w the way optimize_weights_direct is.
        result = optimizer.optimize_weights_with_cv(min_comparisons=30, l2_regularization=1e6)
        assert 'error' not in result
        new_w = np.array([result['new_weights'][c] for c in WeightOptimizer.SCORE_COMPONENTS])
        assert np.allclose(new_w, old_w, atol=0.02)

    def test_zero_l2_lets_folds_drift_from_current_weights(self, optimizer_db):
        """Sanity check that the l2_regularization param actually takes effect
        (rules out a no-op wiring that would make the test above pass by
        accident)."""
        db_path, aesthetics = optimizer_db
        _add_comparisons(db_path, aesthetics, 'vote', agree=True, count=80)
        optimizer = WeightOptimizer(db_path)

        old_weights = optimizer._load_current_weights(None)
        n = len(WeightOptimizer.SCORE_COMPONENTS)
        old_w = np.array([old_weights.get(c, 1.0 / n) for c in WeightOptimizer.SCORE_COMPONENTS])
        old_w = old_w / old_w.sum()

        result = optimizer.optimize_weights_with_cv(min_comparisons=30, l2_regularization=0.0)
        assert 'error' not in result
        new_w = np.array([result['new_weights'][c] for c in WeightOptimizer.SCORE_COMPONENTS])
        assert not np.allclose(new_w, old_w, atol=0.02)


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


class TestApplyPreservesConfigPermissions:
    """--optimize-weights --apply rewrites the config that holds the install's
    plaintext secrets (viewer.password, users.*.password_hash, upload.password,
    frame.tokens, immich.api_key). docker-entrypoint.sh seeds it 0600 and
    docker-compose.yml promises the mode survives every later write, so the
    replacement must land at the destination's mode and must stage through a
    name no `git add -A` can pick up.
    """

    REPO_ROOT = Path(__file__).resolve().parent.parent

    @staticmethod
    def _config(tmp_path, mode):
        cfg = tmp_path / "scoring_config.json"
        cfg.write_text(json.dumps(
            {"viewer": {"password": "plaintext-secret"},
             "categories": [{"name": "portrait", "weights": {"aesthetic_percent": 100}}]}
        ))
        os.chmod(cfg, mode)
        return cfg

    def test_apply_preserves_owner_only_mode(self, tmp_path):
        cfg = self._config(tmp_path, 0o600)
        WeightOptimizer("unused.db", str(cfg)).apply_optimized_weights(
            {"aesthetic": 0.5, "liqe": 0.5}, category="portrait", backup=False
        )
        assert json.loads(cfg.read_text())["viewer"]["password"] == "plaintext-secret"
        assert stat.S_IMODE(os.stat(cfg).st_mode) == 0o600

    def test_apply_preserves_a_group_readable_mode(self, tmp_path):
        # The mode is copied, not forced to 0600: a co-deployed CLI reading the
        # config through its group must not lose access on an optimizer run.
        cfg = self._config(tmp_path, 0o640)
        WeightOptimizer("unused.db", str(cfg)).apply_optimized_weights(
            {"aesthetic": 1.0}, category="portrait", backup=False
        )
        assert stat.S_IMODE(os.stat(cfg).st_mode) == 0o640

    def test_scratch_file_name_is_gitignored(self, tmp_path, monkeypatch):
        # A SIGKILL between the write and the rename leaves the scratch file —
        # a COMPLETE copy of the config — behind. On a native install that is
        # the repository root, so the name must match a .gitignore rule.
        staged = []
        real_replace = os.replace

        def spy(src, dst, *a, **kw):
            staged.append(os.path.basename(src))
            return real_replace(src, dst, *a, **kw)

        monkeypatch.setattr(os, "replace", spy)
        cfg = self._config(tmp_path, 0o600)
        WeightOptimizer("unused.db", str(cfg)).apply_optimized_weights(
            {"aesthetic": 1.0}, category="portrait", backup=False
        )
        assert staged, "apply did not stage the config through a scratch file"
        for name in staged:
            ignored = subprocess.run(
                ["git", "check-ignore", "-q", name],
                cwd=self.REPO_ROOT, capture_output=True,
            )
            assert ignored.returncode == 0, f"scratch name {name!r} is stageable"

    def test_apply_leaves_no_scratch_file_behind(self, tmp_path):
        cfg = self._config(tmp_path, 0o600)
        WeightOptimizer("unused.db", str(cfg)).apply_optimized_weights(
            {"aesthetic": 1.0}, category="portrait", backup=False
        )
        assert [p.name for p in tmp_path.iterdir()] == ["scoring_config.json"]


class TestApplyHoldsTheConfigWriteLock:
    """scoring_config.json is read, edited and written back here, and
    ``atomic_write_json`` is atomic per WRITE, not per read-modify-write. Any
    concurrent writer that lands between this read and this write has its
    update overwritten wholesale, so the lock must span both -- not just the
    write. CLAUDE.md makes that lock the single one every config writer shares.
    """

    @staticmethod
    def _config(tmp_path):
        cfg = tmp_path / "scoring_config.json"
        cfg.write_text(json.dumps(
            {"categories": [{"name": "portrait", "weights": {"aesthetic_percent": 100}}]}
        ))
        return cfg

    def test_the_lock_is_held_when_the_replacement_is_written(self, tmp_path):
        from api.config import CONFIG_WRITE_LOCK
        import api.config as api_config

        held = []
        real_write = api_config.atomic_write_json

        def watching_write(path, data):
            held.append(CONFIG_WRITE_LOCK.locked())
            return real_write(path, data)

        cfg = self._config(tmp_path)
        with mock.patch.object(api_config, "atomic_write_json", watching_write):
            WeightOptimizer("unused.db", str(cfg)).apply_optimized_weights(
                {"aesthetic": 0.5, "liqe": 0.5}, category="portrait", backup=False
            )

        assert held == [True], "config was rewritten without CONFIG_WRITE_LOCK held"

    def test_the_lock_spans_the_read_not_only_the_write(self, tmp_path):
        """A lock taken just before the write would still lose an update made
        after the read, so prove it is already held while the snapshot runs --
        which happens between the read and the write.
        """
        from api.config import CONFIG_WRITE_LOCK

        held = []

        def watching_snapshot(*args, **kwargs):
            held.append(CONFIG_WRITE_LOCK.locked())
            return 1

        cfg = self._config(tmp_path)
        with mock.patch("db.record_weight_snapshot", watching_snapshot):
            WeightOptimizer("unused.db", str(cfg)).apply_optimized_weights(
                {"aesthetic": 0.5, "liqe": 0.5}, category="portrait", backup=True
            )

        assert held == [True], "the lock was not held across the whole read-modify-write"

    def test_the_lock_is_released_afterwards(self, tmp_path):
        from api.config import CONFIG_WRITE_LOCK

        cfg = self._config(tmp_path)
        WeightOptimizer("unused.db", str(cfg)).apply_optimized_weights(
            {"aesthetic": 0.5, "liqe": 0.5}, category="portrait", backup=False
        )

        assert not CONFIG_WRITE_LOCK.locked()
