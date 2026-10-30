"""The weight optimizer's training objective (optimization/weight_optimizer.py).

One penalised Bradley-Terry objective serves the direct fit, the CV folds and
the bootstrap: a tie counts as half a win plus half a loss (the curvature of a
decisive pair, not the old 25x quadratic), and ``l2_regularization`` is a prior
toward the current weights that actually binds at its default.
"""

from pathlib import Path

import numpy as np
import pytest

from optimization.weight_optimizer import WeightOptimizer
from tests.test_weight_optimizer_gate import build_db

REPO_CONFIG = Path(__file__).resolve().parent.parent / 'config' / 'scoring_config.default.json'


def _softplus(x):
    return np.logaddexp(0.0, x)


def _loss_at(d, y):
    """The objective for ONE pair whose weighted score difference is ``d``."""
    from optimization.weight_optimizer import _pairwise_objective
    k = 4
    u = np.full(k, 1.0 / k)
    D = np.full((1, k), float(d))  # D @ u == d
    loss, _ = _pairwise_objective(u, D, np.array([y]), np.ones(1), u, 0.0)
    return loss


class TestTieLoss:
    @pytest.mark.parametrize('d', [-3.0, -0.4, 0.0, 0.7, 5.0])
    def test_tie_is_half_a_win_plus_half_a_loss(self, d):
        assert _loss_at(d, 0) == pytest.approx(0.5 * _softplus(d) + 0.5 * _softplus(-d))

    def test_tie_curvature_at_zero_equals_a_decisive_pair(self):
        h = 1e-3
        for y in (0, 1):
            curvature = (_loss_at(h, y) + _loss_at(-h, y) - 2 * _loss_at(0.0, y)) / h ** 2
            assert curvature == pytest.approx(0.25, abs=1e-3), f'y={y}'

    def test_gradient_matches_finite_differences(self):
        from optimization.weight_optimizer import _pairwise_objective
        rng = np.random.default_rng(0)
        D = rng.normal(size=(30, 6))
        y = rng.choice([-1, 0, 1], size=30)
        rw = rng.uniform(0.5, 1.0, size=30)
        w0 = np.full(6, 1 / 6)
        w = rng.dirichlet(np.ones(6))
        _, grad = _pairwise_objective(w, D, y, rw, w0, 3.0)
        eps = 1e-6
        for i in range(6):
            e = np.zeros(6)
            e[i] = eps
            up, _ = _pairwise_objective(w + e, D, y, rw, w0, 3.0)
            down, _ = _pairwise_objective(w - e, D, y, rw, w0, 3.0)
            assert grad[i] == pytest.approx((up - down) / (2 * eps), rel=1e-4, abs=1e-6)

    def test_ties_do_not_cost_decisive_accuracy(self, tmp_path):
        # 100 decisive pairs ranked by aesthetic + 43 ties (30%) between photos with
        # independent random metrics, over 10 seeds. A tie is half a win plus half a
        # loss, so it still pulls the fit (it is evidence the pair scores alike) but
        # must not drag it off the decisive signal: the mean gap to the ties-excluded
        # fit stays within 1.5 pp (the old 25x quadratic tie: 7.5 pp mean, 13 max).
        gaps = []
        for seed in range(10):
            db = build_db(str(tmp_path / f'ties{seed}.db'), n_decisive=100, n_ties=43,
                          seed=seed, agree=1.0)
            opt = WeightOptimizer(db, str(REPO_CONFIG))
            with_ties = opt.optimize_weights_direct(category='portrait', include_ties=True)
            without = opt.optimize_weights_direct(category='portrait', include_ties=False)
            assert with_ties['ties_included'] == 43
            assert without['ties_included'] == 0
            gaps.append(abs(with_ties['accuracy_after'] - without['accuracy_after']))
        assert np.mean(gaps) <= 1.5, gaps


class TestPriorBinds:
    @staticmethod
    def _fit(db, **kwargs):
        opt = WeightOptimizer(db, str(REPO_CONFIG))
        result = opt.optimize_weights_direct(category='portrait', **kwargs)
        keys = WeightOptimizer.SCORE_COMPONENTS
        old = np.array([result['old_weights'][k] for k in keys])
        new = np.array([result['new_weights'][k] for k in keys])
        return opt, old / old.sum(), new

    def test_movement_shrinks_as_the_prior_strengthens(self, tmp_path):
        db = build_db(str(tmp_path / 'p.db'), n_decisive=150, seed=7, agree=0.85)
        moves = []
        for lam in (0.0, 100.0, 1e4):
            _, w0, w = self._fit(db, l2_regularization=lam)
            moves.append(float(np.abs(w - w0).sum()))
        assert moves[0] > moves[1] > moves[2], moves

    def test_default_prior_is_not_negligible_against_the_data(self, tmp_path):
        db = build_db(str(tmp_path / 'p.db'), n_decisive=150, seed=7, agree=0.85)
        opt, w0, w = self._fit(db)  # default l2_regularization
        from db import get_connection
        with get_connection(db) as conn:
            _, X_a, X_b, y, rw = opt._fetch_comparison_data(conn, category='portrait', mask_missing=True)
        from optimization.weight_optimizer import _pair_difference
        d = _pair_difference(np.stack((X_a, X_b), axis=1), w)
        data_term = float((rw * _softplus(-y * d)).sum())  # decisive pairs only in this set
        import inspect
        lam = inspect.signature(WeightOptimizer.optimize_weights_direct).parameters[
            'l2_regularization'].default
        penalty = lam * float(((w - w0) ** 2).sum())
        assert penalty >= 0.01 * data_term, (penalty, data_term)


class TestBootstrapSharesTheObjective:
    def test_huge_prior_pins_the_bootstrap_to_the_current_weights(self, tmp_path):
        db = build_db(str(tmp_path / 'b.db'), n_decisive=80, seed=7, agree=0.85)
        opt = WeightOptimizer(db, str(REPO_CONFIG))
        result = opt.compute_weight_confidence(
            category='portrait', n_bootstrap=12, min_comparisons=30, l2_regularization=1e6)
        assert 'error' not in result
        keys = WeightOptimizer.SCORE_COMPONENTS
        current = opt._load_current_weights('portrait')
        w0 = np.array([current[k] for k in keys])
        w0 = w0 / w0.sum()
        got = np.array([result['weights'][k] for k in keys])
        assert np.allclose(got, w0, atol=0.01)
