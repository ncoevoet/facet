import json
import sqlite3

import numpy as np
import pytest

from calibrate import (
    METRIC_COLUMNS,
    build_metric_matrix,
    load_current_category_weights,
    log_run_to_db,
    optimize_modifiers,
    optimize_weights,
)
from db.schema import init_database


def test_build_metric_matrix_preserves_genuine_zero_scores():
    col = next(iter(METRIC_COLUMNS.keys()))
    rows = [{col: 0.0, 'mos': 5.0} for _ in range(10)]

    X, y, col_names = build_metric_matrix(rows)

    assert col in col_names
    idx = col_names.index(col)
    assert np.all(X[:, idx] == 0.0)


class TestLoadCurrentCategoryWeights:
    """Regression: the calibration baseline must be the live config weights,
    not a uniform strawman -- otherwise "before" SRCC and the persisted
    old_weights both compare against a vector nobody actually runs.
    """

    def _write_config(self, tmp_path, weights):
        cfg = tmp_path / "scoring_config.json"
        cfg.write_text(json.dumps({"categories": [{"name": "portrait", "weights": weights}]}))
        return str(cfg)

    def test_reads_and_normalizes_live_percent_weights(self, tmp_path):
        cfg_path = self._write_config(
            tmp_path, {"aesthetic_percent": 60, "composition_percent": 40},
        )
        w = load_current_category_weights(cfg_path, "portrait", ["aesthetic", "comp_score"])
        assert w == pytest.approx([0.6, 0.4])

    def test_unknown_category_falls_back_to_uniform(self, tmp_path):
        cfg_path = self._write_config(tmp_path, {"aesthetic_percent": 60})
        w = load_current_category_weights(cfg_path, "nonexistent", ["aesthetic", "comp_score"])
        assert w == pytest.approx([0.5, 0.5])

    def test_missing_config_file_falls_back_to_uniform(self, tmp_path):
        w = load_current_category_weights(
            str(tmp_path / "does_not_exist.json"), "portrait", ["aesthetic", "comp_score"],
        )
        assert w == pytest.approx([0.5, 0.5])

    def test_missing_metric_weight_defaults_to_zero_before_normalizing(self, tmp_path):
        # Only 'aesthetic' is configured; 'comp_score' -> composition_percent
        # is absent, so it contributes 0 rather than crashing.
        cfg_path = self._write_config(tmp_path, {"aesthetic_percent": 30})
        w = load_current_category_weights(cfg_path, "portrait", ["aesthetic", "comp_score"])
        assert w == pytest.approx([1.0, 0.0])


class TestOptimizeWeightsBaselineIsLiveConfig:
    def test_w_before_matches_config_not_uniform(self, tmp_path):
        cfg_path = tmp_path / "scoring_config.json"
        cfg_path.write_text(json.dumps({
            "categories": [{"name": "portrait",
                           "weights": {"aesthetic_percent": 70, "composition_percent": 30}}],
        }))
        rng = np.random.default_rng(0)
        rows = [
            {"aesthetic": float(rng.uniform(1, 9)), "comp_score": float(rng.uniform(1, 9)),
             "mos": float(rng.uniform(1, 9))}
            for _ in range(15)
        ]

        info, _ = optimize_weights(rows, "portrait", method="nelder-mead", config_path=str(cfg_path))

        assert set(info["col_names"]) == {"aesthetic", "comp_score"}
        idx = {c: i for i, c in enumerate(info["col_names"])}
        # Must reflect the configured 70/30 split, not a uniform 50/50 strawman.
        assert info["w_before"][idx["aesthetic"]] == pytest.approx(0.7)
        assert info["w_before"][idx["comp_score"]] == pytest.approx(0.3)


class TestLogRunToDbUsesRealBaseline:
    def test_uses_current_config_weights_when_given(self, tmp_path):
        db_path = str(tmp_path / "t.db")
        init_database(db_path)
        info = {
            "category": "portrait", "n_photos": 20,
            "srcc_before": 0.5, "srcc_after": 0.6,
            "col_names": ["aesthetic", "comp_score"],
            "w_before": [0.5, 0.5],  # deliberately different from the real config dict
            "w_after": [0.8, 0.2],
        }
        real_config_weights = {"aesthetic": 0.7, "comp_score": 0.3}

        log_run_to_db(db_path, info, {"aesthetic": 0.8, "comp_score": 0.2},
                      current_config_weights=real_config_weights)

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT old_weights FROM weight_optimization_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        assert json.loads(row[0]) == real_config_weights

    def test_falls_back_to_info_w_before_when_empty(self, tmp_path):
        db_path = str(tmp_path / "t.db")
        init_database(db_path)
        info = {
            "category": "portrait", "n_photos": 20,
            "srcc_before": 0.5, "srcc_after": 0.6,
            "col_names": ["aesthetic", "comp_score"],
            "w_before": [0.5, 0.5],
            "w_after": [0.8, 0.2],
        }

        log_run_to_db(db_path, info, {"aesthetic": 0.8, "comp_score": 0.2},
                      current_config_weights={})

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT old_weights FROM weight_optimization_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        assert json.loads(row[0]) == {"aesthetic": 0.5, "comp_score": 0.5}


class TestOptimizeModifiersReadsThePenaltiesBlock:
    """Regression: optimize_modifiers must read the shipped 'penalties' config
    block, not a 'penalty_settings' key that has never existed in any shipped
    config. Under the bug, config_data.get('penalty_settings', {}) is always
    {} regardless of what an install tunes 'penalties' to, so it silently
    falls back to hardcoded literals that happen to match the shipped values.
    """

    def _rows(self):
        # Oversaturation is the only active penalty (noise_sigma and
        # histogram_bimodality are 0 for every row). aesthetic=10 for every
        # row keeps the simulated score off the simulate() clip(0, 10) floor
        # after a penalty is subtracted. mean_saturation crosses the tuned
        # threshold (0.5) for half the rows but crosses the hardcoded
        # fallback (0.9) for only one -- so the two thresholds bucket the
        # rows differently and must produce different SRCCs.
        saturations = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
        mos_values = [10, 9, 8, 7, 6, 5, 4, 3, 2, 1]
        return [
            {
                "aesthetic": 10.0, "mos": mos, "mean_saturation": sat,
                "noise_sigma": 0.0, "histogram_bimodality": 0.0,
                "shadow_clipped": 0.0, "highlight_clipped": 0.0,
            }
            for sat, mos in zip(saturations, mos_values)
        ]

    def _write_config(self, tmp_path, name, penalties):
        cfg = tmp_path / name
        body = {"categories": [{
            "name": "test_cat",
            "weights": {"aesthetic_percent": 100},
            "modifiers": {},
        }]}
        if penalties is not None:
            body["penalties"] = penalties
        cfg.write_text(json.dumps(body))
        return str(cfg)

    def test_tuned_oversaturation_threshold_changes_srcc_before(self, tmp_path):
        rows = self._rows()
        default_cfg = self._write_config(tmp_path, "default.json", None)
        tuned_cfg = self._write_config(
            tmp_path, "tuned.json",
            {"oversaturation_threshold": 0.5, "oversaturation_penalty_points": 5.0},
        )

        default_result = optimize_modifiers(rows, "test_cat", default_cfg)
        tuned_result = optimize_modifiers(rows, "test_cat", tuned_cfg)

        assert default_result is not None
        assert tuned_result is not None
        assert tuned_result["srcc_before"] != pytest.approx(default_result["srcc_before"])
