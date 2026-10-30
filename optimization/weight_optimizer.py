"""
Weight Optimizer for Pairwise Comparison Feedback System.

Directly optimizes weights to maximize the likelihood that the weighted
component scores correctly predict comparison outcomes. Uses the
Bradley-Terry probability model; a tie counts as half a win plus half a
loss, and a Gaussian prior (``l2_regularization``) pulls the fit toward the
current weights. One objective (:func:`_pairwise_objective`) serves the
direct fit, the cross-validation folds and the bootstrap.

Whether a fit may be applied is decided by one held-out gate,
:meth:`WeightOptimizer.optimize_weights_with_cv`: photo-grouped folds, pooled
held-out predictions over the decisive pairs, and a one-sided exact McNemar
test on the pairs the fitted and the current weights disagree about.

Usage::

    optimizer = WeightOptimizer(db_path)

    # Single-shot direct optimization (suggest_changes = the held-out gate)
    result = optimizer.optimize_weights_direct(category='portrait')

    # The held-out gate on its own
    result = optimizer.optimize_weights_with_cv(category='portrait')

    # Apply optimized weights to config
    optimizer.apply_optimized_weights(result['new_weights'], category='portrait')

CLI::

    python facet.py --optimize-weights
"""

import json
import logging
import os
import sqlite3
import time
from typing import Dict, List, Optional, Sequence, Tuple
import numpy as np
from scipy.optimize import minimize
from scipy.special import expit
from scipy.stats import binom
from db import DEFAULT_DB_PATH, get_connection
from config import ScoringConfig
from config.percentile_normalizer import PercentileNormalizer
from config.scoring_config import resolve_scoring_config_path
from config_resolve import load_resolved
from optimization.learning_policy import deferred_if_external
from db.scoring_overrides import get_photo_scoring_overrides
from processing.scorer import (
    Facet, SCORING_METRIC_KEYS, SERVED_ROW_COLUMNS, build_metric_vector,
    fold_quality_weight, unavailable_for_config, NULLABLE_SCORING_METRICS,
)

logger = logging.getLogger("facet.optimizer")

# Strength of the Gaussian prior toward the current weights, shared by every fit
# (direct, CV folds, bootstrap) so the gate scores the model that ships. Fixed
# and independent of the number of pairs: with a per-pair curvature of 0.25 it
# is worth ~0.23 per pair on a 400-pair category, so it binds hardest on small
# categories, where an unconstrained fit is least trustworthy.
DEFAULT_L2_REGULARIZATION = 100.0

# Every weight is bounded so no single metric can take the whole aggregate.
_WEIGHT_UPPER_BOUND = 0.60

# One-sided significance level of the held-out McNemar test.
_GATE_ALPHA = 0.05

# How long the percentile snapshot an optimizer instance read stays current. A
# per-request optimizer never reaches it; the long-lived one the burst-culling
# router keeps would otherwise score on the snapshot of its first call forever.
_NORMALIZER_TTL_SECONDS = 300.0

# Range the viewer accepts for a category's ``modifiers.bonus``.
_BONUS_MIN, _BONUS_MAX = -5.0, 5.0


def _row_scores_and_gradient(X, w):
    """Score rows: NaN is optional NULL, -inf is a licence exclusion.

    Exclusions score zero when nothing remains; optional NULLs retain the
    neutral 5.0 fallback. Neither sentinel enters arithmetic on metric values.
    """
    present = np.isfinite(X)
    values = np.where(present, X, 0.0)
    denominator = present @ w
    numerator = values @ w
    scores = np.where(np.isnan(X) @ w > 0, 5.0, 0.0)
    gradient = np.zeros_like(X)
    valid = denominator > 0
    scores[valid] = numerator[valid] / denominator[valid]
    gradient[valid] = (values[valid] - scores[valid, None] * present[valid]) / denominator[valid, None]
    return scores, gradient


def _pair_difference(D, w):
    if D.ndim == 2:
        return D @ w
    return _row_scores_and_gradient(D[:, 0], w)[0] - _row_scores_and_gradient(D[:, 1], w)[0]


def _pairwise_objective(w, D, y, rw, w0, lam):
    """Penalised Bradley-Terry negative log-likelihood and its gradient.

    ``D`` holds one row ``X_a - X_b`` per pair, ``y`` is +1 when A won, -1 when
    B won and 0 for a tie, ``rw`` is each pair's likelihood weight (see
    ``WeightOptimizer.SOURCE_WEIGHTS``), ``w0`` the prior's centre (the current
    weights) and ``lam`` its strength::

        loss = sum_i rw_i * l_i(D_i @ u) + lam * ||w - w0||^2,   u = w / sum(w)

    A decisive pair costs ``softplus(-y * d)``. A tie costs half a win plus
    half a loss, ``(softplus(d) + softplus(-d)) / 2``: minimal at ``d = 0``
    with the curvature of a decisive pair (0.25) and only linear growth, so a
    tie between two very different photos cannot outweigh the decisive votes.

    Returns ``(loss, grad)`` for ``scipy.optimize.minimize(..., jac=True)``.
    """
    k = len(w)
    s = w.sum()
    u = w / s if s > 1e-8 else np.full(k, 1.0 / k)
    if D.ndim == 3:
        a, ga = _row_scores_and_gradient(D[:, 0], u)
        b, gb = _row_scores_and_gradient(D[:, 1], u)
        d, jacobian = a - b, ga - gb
    else:
        d, jacobian = D @ u, D
    decisive = y != 0
    yd = y * d
    loss_i = np.where(decisive, np.logaddexp(0.0, -yd),
                      0.5 * (np.logaddexp(0.0, d) + np.logaddexp(0.0, -d)))
    dloss_dd = np.where(decisive, -y * expit(-yd), expit(d) - 0.5)
    delta = w - w0
    loss = float(rw @ loss_i) + lam * float(delta @ delta)
    g_u = (rw * dloss_dd) @ jacobian
    g_w = (g_u - g_u @ u) / s if s > 1e-8 else np.zeros(k)
    return loss, g_w + 2.0 * lam * delta


def _active_columns(D) -> np.ndarray:
    """Columns with at least one finite value in ``D`` (all of them for 2-D ``D``).

    Compute it once on the full comparison set: a fold or bootstrap subset can
    lack a column the full set has, and that must not change which weights the
    fit is allowed to move.
    """
    k = D.shape[-1]
    return np.any(np.isfinite(D), axis=(0, 1)) if D.ndim == 3 else np.ones(k, dtype=bool)


def _fit_weights(D, y, rw, w0, lam, starts, maxiter, ftol=1e-6, active=None) -> Tuple[np.ndarray, float]:
    """Minimise :func:`_pairwise_objective` from each start; keep the best.

    Bounds ``[0, 0.6]`` per weight, weights summing to 1, SLSQP. Returns the
    normalised weights and the objective at them (``w0`` when every start
    fails). A column with no finite value in the comparison set (``active``
    False) carries no evidence, so it is held at its prior ``w0`` and the
    active columns share what remains.
    """
    k = D.shape[-1]
    if active is None:
        active = _active_columns(D)
    if not active.any():
        return w0.copy(), _pairwise_objective(w0, D, y, rw, w0, lam)[0]
    held = np.where(active, 0.0, w0)
    rest = 1.0 - held.sum()
    if rest <= 1e-9:
        return w0.copy(), _pairwise_objective(w0, D, y, rw, w0, lam)[0]

    def on_active(vec):
        vec = np.where(active, vec, 0.0)
        return vec / vec.sum() * rest if vec.sum() else active / active.sum() * rest

    w0_fit = held + on_active(w0)
    starts = [held + on_active(start) for start in starts]
    upper = max(_WEIGHT_UPPER_BOUND, rest / active.sum())
    bounds = [(0.0, upper) if enabled else (w0[i], w0[i]) for i, enabled in enumerate(active)]
    w0 = w0_fit
    constraint = {'type': 'eq', 'fun': lambda w: w.sum() - 1.0, 'jac': lambda w: np.ones_like(w)}
    best, best_loss = None, float('inf')
    for start in starts:
        try:
            result = minimize(
                _pairwise_objective, start, args=(D, y, rw, w0, lam), jac=True,
                method='SLSQP', bounds=bounds, constraints=constraint,
                options={'maxiter': maxiter, 'ftol': ftol},
            )
        except (ValueError, ArithmeticError, np.linalg.LinAlgError):
            continue
        if result.fun < best_loss:
            best_loss, best = float(result.fun), result.x.copy()
    if best is None:
        best = w0.copy()
        best_loss = _pairwise_objective(best, D, y, rw, w0, lam)[0]
    w = np.maximum(best, 0.0)
    w = w / w.sum() if w.sum() > 0 else np.full(k, 1.0 / k)
    w = np.where(active, w, w0)
    return w, best_loss


def _decisive_correct(w, D, y) -> np.ndarray:
    """Per decisive pair: does ``w`` score the winner strictly higher?"""
    m = y != 0
    d = _pair_difference(D[m], w)
    return np.where(y[m] == 1, d > 0, d < 0)


def _decisive_accuracy(w, D, y) -> float:
    """Percentage of decisive pairs ``w`` ranks right (ties do not count)."""
    correct = _decisive_correct(w, D, y)
    return float(correct.mean() * 100) if correct.size else 0.0


def _photo_folds(
    photo_a: Sequence, photo_b: Sequence, n_folds: int,
) -> Tuple[np.ndarray, np.ndarray, int]:
    """Assign both photos of every pair to folds so no photo straddles a split.

    Pairs are grouped into photo-connected components (union-find over
    ``photo_a``/``photo_b``); the components, in sorted order, are permuted
    with ``RandomState(42)`` and component *i* goes to fold ``i % n_folds``.
    Every pair then sits inside one fold. A component holding more than
    ``1/n_folds`` of the pairs (a densely compared set) would leave its own
    fold nothing to train on, so its photos are assigned individually instead;
    a pair whose two photos land in different folds is then held out by
    neither and trains only the folds that hold neither photo.

    Fold ``f`` tests the pairs with both photos in ``f`` and trains on the
    pairs with neither photo in ``f``.

    Returns ``(fold_a, fold_b, n_folds_used)``.
    """
    photo_a = [str(p) for p in photo_a]
    photo_b = [str(p) for p in photo_b]
    parent: Dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in zip(photo_a, photo_b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    roots = [find(a) for a in photo_a]
    pair_count: Dict[str, int] = {}
    for r in roots:
        pair_count[r] = pair_count.get(r, 0) + 1
    big = {r for r, c in pair_count.items() if c > len(roots) / n_folds}

    # A unit is a whole component, or one photo of an over-sized component;
    # find() makes every root the component's smallest path, so the keys are
    # deterministic and never collide.
    unit_of = {p: (find(p) if find(p) not in big else p) for p in parent}
    units = sorted(set(unit_of.values()))
    n_used = min(n_folds, len(units))
    if n_used == 0:
        return np.zeros(0, dtype=int), np.zeros(0, dtype=int), 0
    fold_of_unit: Dict[str, int] = {}
    for i, j in enumerate(np.random.RandomState(42).permutation(len(units))):
        fold_of_unit[units[j]] = i % n_used
    fold_a = np.array([fold_of_unit[unit_of[p]] for p in photo_a], dtype=int)
    fold_b = np.array([fold_of_unit[unit_of[p]] for p in photo_b], dtype=int)
    return fold_a, fold_b, n_used


class WeightOptimizer:
    """
    Optimizes scoring weights from pairwise comparisons.

    Uses direct preference optimization: weights are chosen to maximize the
    Bradley-Terry/Davidson likelihood of the observed comparison outcomes
    given the per-photo weighted score (no intermediate "learned scores"
    table; raw comparisons feed the optimizer directly).
    """

    # Score components that can be weighted. Shared with the scorer so the
    # optimizer trains on the exact metric vector production scores (config keys,
    # all 0-10, 'noise' pre-inverted). 'quality' is excluded (always 0).
    SCORE_COMPONENTS = list(SCORING_METRIC_KEYS)

    # Reliability prior per comparison source: explicit A/B votes count
    # fully; synthetic pairs derived from star ratings and culling decisions
    # carry real signal but more noise, so their likelihood terms weigh less
    SOURCE_WEIGHTS = {'vote': 1.0, 'rating': 0.7, 'culling': 0.5}

    def __init__(self, db_path: str = DEFAULT_DB_PATH, config_path: Optional[str] = None):
        self.db_path = db_path
        self.config_path = resolve_scoring_config_path(config_path)
        self._cfg: Optional[ScoringConfig] = None
        self._normalizer: Optional[PercentileNormalizer] = None
        self._normalizer_read_at: Optional[float] = None

    @property
    def cfg(self) -> ScoringConfig:
        """Lazily-loaded scoring config (for metric-vector construction).

        Read-only: ``validate=False``, because validation can rewrite the
        config file, and this runs inside viewer request handlers that do not
        hold ``CONFIG_WRITE_LOCK``.
        """
        if self._cfg is None:
            self._cfg = ScoringConfig(self.config_path, validate=False)
        return self._cfg

    def _get_normalizer(self, conn=None) -> Optional[PercentileNormalizer]:
        """The percentile normalizer the last ``--recompute-average`` scored with.

        Rebuilt from the persisted ``percentiles_snapshot`` (a fresh compute
        over a large library takes over a minute) and cached for a few minutes.
        None when no snapshot exists or the database does not: the stored
        columns are then what is served. ``conn`` reuses a caller's open
        connection.
        """
        now = time.monotonic()
        if self._normalizer_read_at is not None and now - self._normalizer_read_at < _NORMALIZER_TTL_SECONDS:
            return self._normalizer
        settings = self.cfg.get_normalization_settings()
        normalizer = None
        try:
            if conn is not None:
                normalizer = PercentileNormalizer.from_snapshot(conn, settings)
            elif os.path.exists(self.db_path):
                with get_connection(self.db_path) as own:
                    normalizer = PercentileNormalizer.from_snapshot(own, settings)
        except sqlite3.Error:
            logger.warning("Could not read the percentile snapshot; features use stored columns",
                           exc_info=True)
        self._normalizer, self._normalizer_read_at = normalizer, now
        return normalizer

    def _metric_vector(self, row: dict, category: Optional[str], *, mask_missing=False) -> List[float]:
        """Build the metric vector the scorer serves for one photo, in component order.

        The row is first rewritten exactly as ``update_all_aggregates`` rewrites
        it (``Facet.prepare_scoring_row``: percentile-normalized sharpness,
        colour and eye sharpness, group-portrait flag, histogram exposure),
        in ``category`` when one is supplied, so the optimizer trains on what
        production weights. The photo's own category (override and scoring
        context honoured) is used when none is supplied, so the
        category-dependent terms (leading-lines blend, isolation) match scoring.
        Values are clamped to 0-10 exactly as the scorer clamps them. The
        ranker and keeper inference paths come through here too, so they build
        the features they were trained on.
        """
        cfg = self.cfg
        prepared = Facet.prepare_scoring_row(dict(row), cfg, self._get_normalizer(), category=category)
        cat = category or Facet._determine_photo_category(prepared, cfg)
        vec = build_metric_vector(prepared, cfg, cat, unavailable=unavailable_for_config(cfg))
        return [float('-inf') if mask_missing and c in unavailable_for_config(cfg)
                else float('nan') if mask_missing and c in NULLABLE_SCORING_METRICS and prepared.get(c) is None
                else max(0.0, min(10.0, vec.get(c, 0.0)))
                for c in self.SCORE_COMPONENTS]

    def _fetch_comparison_data(
        self,
        conn,
        category: Optional[str] = None,
        include_ties: bool = True,
        sources: Optional[List[str]] = None,
        user_id: Optional[str] = None,
        mask_missing: bool = False,
    ):
        """Fetch comparisons and build both photos' production metric vectors.

        Single source of truth for the optimizer's training data (direct,
        cross-validated and bootstrap paths all consume it). Each photo's feature
        row is the same 0-10 metric vector the scorer weights, so optimized
        weights apply directly to production scoring.

        Args:
            conn: Open DB connection
            category: Restrict to one category (None = all); also used as the
                      scoring category for the metric vectors when set
            include_ties: Include 'tie' outcomes
            sources: Restrict to these comparison sources (None = all)
            user_id: Restrict to one user's rows plus legacy NULL rows
                     (None = every user's rows, the global pooled default)

        Returns:
            Tuple (comparisons, X_a, X_b, winners, row_weights):
            - comparisons: list of {photo_a, photo_b, winner, source}
            - X_a/X_b: metric matrices (n x len(SCORE_COMPONENTS)), each 0-10
            - winners: 1 for 'a', -1 for 'b', 0 for tie
            - row_weights: per-row likelihood weight from SOURCE_WEIGHTS
        """
        where_clauses = [
            "winner IN ('a', 'b', 'tie')" if include_ties else "winner IN ('a', 'b')"
        ]
        params: List = []
        if category:
            where_clauses.append("c.category = ?")
            params.append(category)
        if sources:
            placeholders = ','.join('?' * len(sources))
            where_clauses.append(f"COALESCE(c.source, 'vote') IN ({placeholders})")
            params.extend(sources)
        if user_id is not None:
            where_clauses.append("(c.user_id = ? OR c.user_id IS NULL)")
            params.append(user_id)

        n = len(self.SCORE_COMPONENTS)
        rows = conn.execute(f"""
            SELECT c.photo_a_path, c.photo_b_path, c.winner,
                   COALESCE(c.source, 'vote') AS source
            FROM comparisons c
            JOIN photos p1 ON c.photo_a_path = p1.path
            JOIN photos p2 ON c.photo_b_path = p2.path
            WHERE {' AND '.join(where_clauses)}
        """, params).fetchall()

        if not rows:
            return [], np.zeros((0, n)), np.zeros((0, n)), np.array([]), np.array([])

        # Fetch full photo rows once for every photo involved
        paths = {r['photo_a_path'] for r in rows} | {r['photo_b_path'] for r in rows}
        photos: Dict[str, dict] = {}
        path_list = list(paths)
        for start in range(0, len(path_list), 900):
            chunk = path_list[start:start + 900]
            ph = ','.join('?' * len(chunk))
            for pr in conn.execute(f"SELECT * FROM photos WHERE path IN ({ph})", chunk):
                photos[pr['path']] = dict(pr)
        # A sticky per-photo category / scoring context decides how a photo is
        # served when no comparison category pins it (pooled runs)
        try:
            overrides = get_photo_scoring_overrides(conn, path_list)
        except sqlite3.OperationalError:  # a database from before the table existed
            overrides = {}
        for path, override in overrides.items():
            if path in photos:
                photos[path]['category_override'] = override['category_override']
                photos[path]['scoring_context'] = override['scoring_context']
        self._get_normalizer(conn)

        comparisons = []
        features_a, features_b, winners, row_weights = [], [], [], []
        for row in rows:
            a = photos.get(row['photo_a_path'])
            b = photos.get(row['photo_b_path'])
            if a is None or b is None:
                continue
            comparisons.append({
                'photo_a': row['photo_a_path'],
                'photo_b': row['photo_b_path'],
                'winner': row['winner'],
                'source': row['source'],
            })
            features_a.append(self._metric_vector(a, category, mask_missing=mask_missing))
            features_b.append(self._metric_vector(b, category, mask_missing=mask_missing))
            winners.append(1 if row['winner'] == 'a' else (-1 if row['winner'] == 'b' else 0))
            row_weights.append(self.SOURCE_WEIGHTS.get(row['source'], 1.0))

        if not comparisons:
            return [], np.zeros((0, n)), np.zeros((0, n)), np.array([]), np.array([])
        return (
            comparisons,
            np.array(features_a),
            np.array(features_b),
            np.array(winners),
            np.array(row_weights),
        )

    def _prior(self, category: Optional[str]):
        """The current weights as a dict and as the prior's normalised vector."""
        old_weights = self._load_current_weights(category)
        n = len(self.SCORE_COMPONENTS)
        w0 = np.array([old_weights.get(c, 1.0 / n) for c in self.SCORE_COMPONENTS])
        w0 = w0 / w0.sum() if w0.sum() > 0 else np.full(n, 1.0 / n)
        return old_weights, w0

    @staticmethod
    def _too_few_decisive(winners, total: int, min_comparisons: int) -> Optional[Dict]:
        """The guard every path shares: ties carry no ranking evidence."""
        decisive = int(np.count_nonzero(winners))
        if decisive >= min_comparisons:
            return None
        return {
            'error': f'Need at least {min_comparisons} decisive comparisons (have {decisive})',
            'comparison_count': total,
        }

    def optimize_weights_direct(
        self,
        category: Optional[str] = None,
        min_comparisons: int = 30,
        include_ties: bool = True,
        min_improvement_threshold: float = 2.0,
        l2_regularization: float = DEFAULT_L2_REGULARIZATION,
        sources: Optional[List[str]] = None,
    ) -> Dict:
        """
        Directly optimize weights to maximize comparison agreement.

        Uses the Bradley-Terry probability model::

            P(A > B) = sigmoid(score_A - score_B)

        with a tie counting as half a win plus half a loss, plus a Gaussian
        prior toward the current weights (see :func:`_pairwise_objective`).

        ``suggest_changes`` is the held-out gate of
        :meth:`optimize_weights_with_cv`, never the in-sample gain. The gate is
        run only when the in-sample improvement already reaches
        ``min_improvement_threshold``: a fit that cannot beat the current
        weights on the very pairs it was trained on does not pass held out
        either, so the common "nothing to suggest" answer costs one fit.

        Args:
            category: Optimize weights for specific category (or all if None)
            min_comparisons: Minimum DECISIVE comparisons required (ties do not count)
            include_ties: Whether to include tie comparisons in optimization
            min_improvement_threshold: Minimum accuracy gain (pp), in sample to
                run the gate and held out to pass it
            l2_regularization: Strength of the prior toward the current weights

        Returns:
            Dict with:
            - old_weights, new_weights: weight dictionaries
            - accuracy_before, accuracy_after: % of decisive comparisons predicted correctly (in sample)
            - log_likelihood: final penalised log-likelihood
            - suggest_changes: whether the held-out gate passed
            - gate: the optimize_weights_with_cv result, or None when it was not run
            - per_comparison: list of (photo_a, photo_b, winner, predicted_correct)
        """
        deferred = deferred_if_external(self.config_path)
        if deferred is not None:
            return deferred
        with get_connection(self.db_path) as conn:
            comparisons, X_a, X_b, winners, row_weights = self._fetch_comparison_data(
                conn, category=category, include_ties=include_ties, sources=sources, mask_missing=True,
            )
        too_few = self._too_few_decisive(winners, len(comparisons), min_comparisons)
        if too_few:
            return too_few

        n_features = len(self.SCORE_COMPONENTS)
        old_weights, old_w = self._prior(category)
        D = np.stack((X_a, X_b), axis=1)

        accuracy_before = _decisive_accuracy(old_w, D, winners)

        rng = np.random.RandomState(42)
        starts = [old_w.copy(), np.full(n_features, 1.0 / n_features)]
        starts += [rng.dirichlet(np.ones(n_features)) for _ in range(3)]
        new_w, best_nll = _fit_weights(
            D, winners, row_weights, old_w, l2_regularization, starts, maxiter=500, ftol=1e-9,
            active=_active_columns(D),
        )
        accuracy_after = _decisive_accuracy(new_w, D, winners)

        diff = _pair_difference(D, new_w)
        per_comparison = []
        for comp, d, winner in zip(comparisons, diff, winners):
            if winner == 1:
                predicted_correct = bool(d > 0)
            elif winner == -1:
                predicted_correct = bool(d < 0)
            else:
                predicted_correct = bool(abs(d) < 0.5)  # a tie: scores close
            per_comparison.append({
                'photo_a': comp['photo_a'],
                'photo_b': comp['photo_b'],
                'winner': comp['winner'],
                'predicted_correct': predicted_correct,
            })

        accuracy_improvement = accuracy_after - accuracy_before
        gate = None
        if accuracy_improvement >= min_improvement_threshold:
            gate = self.optimize_weights_with_cv(
                category=category,
                min_comparisons=min_comparisons,
                include_ties=include_ties,
                sources=sources,
                l2_regularization=l2_regularization,
                min_improvement=min_improvement_threshold,
            )
        suggest_changes = bool(gate is not None and gate.get('passed', False))

        new_weights = {c: float(w) for c, w in zip(self.SCORE_COMPONENTS, new_w)}

        with get_connection(self.db_path) as conn:
            conn.execute("""
                INSERT INTO weight_optimization_runs
                (category, comparisons_used, old_weights, new_weights, mse_before, mse_after)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                category,
                len(comparisons),
                json.dumps(old_weights),
                json.dumps(new_weights),
                accuracy_before,  # Store accuracy in mse fields for now
                accuracy_after
            ))
            conn.commit()

        source_counts: Dict[str, int] = {}
        for comp in comparisons:
            source_counts[comp['source']] = source_counts.get(comp['source'], 0) + 1

        return {
            'old_weights': old_weights,
            'new_weights': new_weights,
            'accuracy_before': round(accuracy_before, 1),
            'accuracy_after': round(accuracy_after, 1),
            'improvement': round(accuracy_improvement, 1),
            'log_likelihood': round(-best_nll, 4),
            'suggest_changes': suggest_changes,
            'gate': gate,
            'comparisons_used': len(comparisons),
            'ties_included': sum(1 for c in comparisons if c['winner'] == 'tie'),
            'source_counts': source_counts,
            'per_comparison': per_comparison,
            'method': 'direct_preference_optimization',
        }

    def optimize_weights_with_cv(
        self,
        category: Optional[str] = None,
        n_folds: int = 5,
        min_comparisons: int = 30,
        include_ties: bool = True,
        sources: Optional[List[str]] = None,
        l2_regularization: float = DEFAULT_L2_REGULARIZATION,
        min_improvement: float = 2.0,
    ) -> Dict:
        """
        The held-out apply gate: photo-grouped k-fold CV plus a McNemar test.

        Folds come from :func:`_photo_folds`, so no photo is on both sides of
        a split. Each fold is fitted with the SAME objective and prior that
        ``optimize_weights_direct`` ships, started at the current weights.
        Every held-out decisive pair is then predicted by its fold's fit and by
        the current weights; with ``b`` = pairs only the fit gets right and
        ``c`` = pairs only the current weights get right, the one-sided exact
        McNemar p-value is ``binom.sf(b - 1, b + c, 0.5)``.

        ``passed`` = ``p < 0.05`` AND pooled held-out gain >= ``min_improvement``
        pp. Under random winners it passes about 5% of the time or less, where
        the former "mean fold accuracy - full-set accuracy >= 2 pp" rule passed
        30-45% of the time.

        Args:
            category: Category to optimize
            n_folds: Number of cross-validation folds
            min_comparisons: Minimum DECISIVE comparisons required
            include_ties: Whether to include ties (in training; only decisive
                pairs are scored)
            l2_regularization: Strength of the prior toward the current weights
                (must match ``optimize_weights_direct`` for the gate to be valid)
            min_improvement: Minimum pooled held-out gain (pp) to pass

        Returns:
            Dict with:
            - new_weights / average_weights: mean of the fold weights
            - cv_accuracy: pooled held-out accuracy of the fold fits (%)
            - cv_std: standard deviation of the per-fold accuracies
            - fold_results: per-fold held-out accuracy
            - heldout_gain_pp: pooled held-out accuracy minus the current weights'
            - discordant_new / discordant_old: McNemar's b and c
            - p_value, passed, suggest_changes (= passed)
        """
        deferred = deferred_if_external(self.config_path)
        if deferred is not None:
            return deferred
        with get_connection(self.db_path) as conn:
            all_data, X_a, X_b, winners, row_weights = self._fetch_comparison_data(
                conn, category=category, include_ties=include_ties, sources=sources, mask_missing=True,
            )
        too_few = self._too_few_decisive(winners, len(all_data), min_comparisons)
        if too_few:
            return too_few

        old_weights, old_w = self._prior(category)
        D = np.stack((X_a, X_b), axis=1)
        fold_a, fold_b, n_used = _photo_folds(
            [c['photo_a'] for c in all_data], [c['photo_b'] for c in all_data], n_folds,
        )

        active = _active_columns(D)
        fold_weights, fold_accuracies = [], []
        new_correct, old_correct = [], []
        for fold in range(n_used):
            test = (fold_a == fold) & (fold_b == fold)
            train = (fold_a != fold) & (fold_b != fold)
            if train.sum() < 10:
                continue
            trained_w, _ = _fit_weights(
                D[train], winners[train], row_weights[train], old_w, l2_regularization,
                starts=[old_w.copy()], maxiter=300, active=active,
            )
            fold_weights.append(trained_w)
            new_c = _decisive_correct(trained_w, D[test], winners[test])
            if not new_c.size:
                continue
            new_correct.append(new_c)
            old_correct.append(_decisive_correct(old_w, D[test], winners[test]))
            fold_accuracies.append(float(new_c.mean() * 100))

        if not fold_weights or not new_correct:
            return {
                'error': 'Cross-validation failed - not enough data per fold',
                'comparison_count': len(all_data),
            }

        new_c = np.concatenate(new_correct)
        old_c = np.concatenate(old_correct)
        only_new = int(np.count_nonzero(new_c & ~old_c))  # McNemar's b
        only_old = int(np.count_nonzero(old_c & ~new_c))  # McNemar's c
        discordant = only_new + only_old
        p_value = float(binom.sf(only_new - 1, discordant, 0.5)) if discordant else 1.0
        gain = float((new_c.mean() - old_c.mean()) * 100)
        passed = bool(p_value < _GATE_ALPHA and gain >= min_improvement)

        avg_weights = np.mean(fold_weights, axis=0)
        avg_weights = avg_weights / avg_weights.sum()
        new_weights = {c: float(w) for c, w in zip(self.SCORE_COMPONENTS, avg_weights)}

        return {
            'old_weights': old_weights,
            'new_weights': new_weights,
            'average_weights': new_weights,
            'cv_accuracy': round(float(new_c.mean() * 100), 1),
            'cv_std': round(float(np.std(fold_accuracies)), 1),
            'fold_results': [round(a, 1) for a in fold_accuracies],
            'n_folds': len(fold_accuracies),
            'comparisons_used': len(all_data),
            'heldout_pairs': int(new_c.size),
            'heldout_gain_pp': round(gain, 1),
            'discordant_new': only_new,
            'discordant_old': only_old,
            'p_value': round(p_value, 6),
            'passed': passed,
            'suggest_changes': passed,
            'method': 'cross_validated_direct_optimization',
        }

    def compute_weight_confidence(
        self,
        category: Optional[str] = None,
        n_bootstrap: int = 100,
        min_comparisons: int = 30,
        sources: Optional[List[str]] = None,
        l2_regularization: float = DEFAULT_L2_REGULARIZATION,
    ) -> Dict:
        """
        Bootstrap resampling to estimate weight uncertainty.

        Resamples comparisons with replacement and re-fits each sample with the
        same objective and prior as the direct fit, started at the current
        weights, to estimate confidence intervals for the weights that ship.

        Args:
            category: Category to analyze
            n_bootstrap: Number of bootstrap samples
            min_comparisons: Minimum DECISIVE comparisons required
            l2_regularization: Strength of the prior toward the current weights

        Returns:
            Dict with:
            - weights: point estimates
            - lower_bounds: 2.5th percentile per weight
            - upper_bounds: 97.5th percentile per weight
            - confidence_intervals: per-component CI width
            - stable_components: components with narrow CIs
        """
        deferred = deferred_if_external(self.config_path)
        if deferred is not None:
            return deferred
        with get_connection(self.db_path) as conn:
            all_data, X_a, X_b, winners, row_weights = self._fetch_comparison_data(
                conn, category=category, include_ties=True, sources=sources, mask_missing=True,
            )
        too_few = self._too_few_decisive(winners, len(all_data), min_comparisons)
        if too_few:
            return too_few

        _, old_w = self._prior(category)
        D = np.stack((X_a, X_b), axis=1)
        rng = np.random.RandomState(42)
        active = _active_columns(D)
        samples = []
        for _ in range(n_bootstrap):
            idx = rng.choice(len(all_data), size=len(all_data), replace=True)
            boot_w, _ = _fit_weights(
                D[idx], winners[idx], row_weights[idx], old_w, l2_regularization,
                starts=[old_w.copy()], maxiter=200, active=active,
            )
            samples.append(boot_w)

        if len(samples) < 10:
            return {
                'error': 'Bootstrap failed - not enough successful optimizations',
                'comparison_count': len(all_data),
            }

        bootstrap_weights = np.array(samples)

        # Point estimates (median)
        point_estimates = np.median(bootstrap_weights, axis=0)
        point_estimates = point_estimates / point_estimates.sum()

        # Confidence intervals (2.5th and 97.5th percentiles)
        lower_bounds = np.percentile(bootstrap_weights, 2.5, axis=0)
        upper_bounds = np.percentile(bootstrap_weights, 97.5, axis=0)

        # Identify stable components (CI width < 10%)
        ci_widths = upper_bounds - lower_bounds
        stable_threshold = 0.10
        stable_components = [
            self.SCORE_COMPONENTS[i]
            for i, width in enumerate(ci_widths)
            if width < stable_threshold
        ]

        weights = {c: float(w) for c, w in zip(self.SCORE_COMPONENTS, point_estimates)}
        lower = {c: float(w) for c, w in zip(self.SCORE_COMPONENTS, lower_bounds)}
        upper = {c: float(w) for c, w in zip(self.SCORE_COMPONENTS, upper_bounds)}
        ci_width = {c: float(w) for c, w in zip(self.SCORE_COMPONENTS, ci_widths)}

        return {
            'weights': weights,
            'lower_bounds': lower,
            'upper_bounds': upper,
            'confidence_intervals': ci_width,
            'stable_components': stable_components,
            'n_bootstrap': len(bootstrap_weights),
            'comparisons_used': len(all_data),
        }

    @staticmethod
    def _find_category_entry(config: dict, category: Optional[str]) -> Optional[dict]:
        """The ``categories[]`` entry named ``category`` (None for the v3 blocks)."""
        for cat_entry in config.get('categories', []):
            if cat_entry.get('name') == category:
                return cat_entry
        return None

    def _load_current_weights(self, category: Optional[str]) -> Dict[str, float]:
        """The weights the scorer SERVES for ``category``, from scoring_config.json.

        ``calculate_aggregate_logic`` folds ``quality`` into ``aesthetic`` before
        weighting (``fold_quality_weight``), so the fold is applied here too and
        the result is renormalised over the optimizer's components: the
        optimizer's prior, its accuracy baseline and an apply's bonus shift are
        then all measured against the weights production scores with.
        Components are config metric keys (see SCORING_METRIC_KEYS), so the
        '<key>_percent' lookup is direct - no DB-column translation.
        """
        uniform = {c: 1.0 / len(self.SCORE_COMPONENTS) for c in self.SCORE_COMPONENTS}
        try:
            config = load_resolved(self.config_path)

            cat = category or 'others'

            # Try v4 categories array first, then v3 flat dicts
            entry = self._find_category_entry(config, cat)
            cat_weights = entry.get('weights', {}) if entry else {}
            if not cat_weights:
                if 'category_weights' in config and cat in config['category_weights']:
                    cat_weights = config['category_weights'][cat]
                elif 'weights' in config and cat in config['weights']:
                    cat_weights = config['weights'][cat]

            # Percent values to decimal weights, 'quality' included, then the
            # scorer's own fold
            decimal = {key[:-len('_percent')]: value / 100.0
                       for key, value in cat_weights.items() if key.endswith('_percent')}
            served = fold_quality_weight(decimal)
            weights = {key: float(served.get(key, 0.0)) for key in self.SCORE_COMPONENTS}

            # If all weights are 0, use uniform distribution
            total = sum(weights.values())
            if total <= 0:
                return uniform

            return {key: value / total for key, value in weights.items()}

        except Exception as e:
            logger.warning("Could not load weights from config: %s", e)
            # Return default uniform weights
            return uniform

    @staticmethod
    def _round_percent_weights(new_weights: Dict[str, float], served: Dict[str, float],
                               log: bool = False) -> Dict[str, float]:
        """``new_weights`` as the config stores them: percent, one decimal, summing to 100.

        Rounding to a tenth of a percent can leave the total a hair off 100, so
        the largest weight that moved from ``served`` absorbs the difference: a
        weight the fit held at its prior stays exactly where the operator set it.
        Shared by the write and by the bonus projection, so the shift is measured
        on the weights that land.
        """
        percent = {c: round(w * 100, 1) for c, w in new_weights.items()}
        total = sum(percent.values())
        if total > 0 and abs(total - 100.0) > 0.01:
            moved = [c for c in percent if percent[c] != round(served.get(c, 0.0) * 100, 1)]
            largest = max(moved or percent, key=lambda c: percent[c])
            adjustment = 100.0 - total
            percent[largest] = round(percent[largest] + adjustment, 1)
            if log:
                logger.info("Adjusted %s_percent by %+.1f%% to ensure 100%% total", largest, adjustment)
        return percent

    def _projected_mean_shift(self, new_weights: Dict[str, float], category: Optional[str]) -> Optional[float]:
        """Mean change of ``category``'s scores if ``new_weights`` replace the served ones.

        Mean over the category's photos of the new row score minus the
        served row score, each independently normalized over available inputs.
        ``w_served`` contains the folded current weights. The pairwise likelihood is blind to a constant
        added to a whole category, so without this the apply moves the
        category's level against every other category. None when there is
        nothing to measure: no ``categories[]`` entry, no database, or no photo
        stored in the category.
        """
        if self._find_category_entry(load_resolved(self.config_path), category) is None:
            return None
        if not os.path.exists(self.db_path):
            logger.info("No database at %s: bonus not re-centred", self.db_path)
            return None
        served = self._load_current_weights(category)
        rounded = self._round_percent_weights(new_weights, served)
        diff = np.array([rounded[c] / 100.0 - served[c] if c in rounded else 0.0
                         for c in self.SCORE_COMPONENTS])
        old_w = np.array([served[c] for c in self.SCORE_COMPONENTS])
        new_w = old_w + diff
        total = 0.0
        count = 0
        try:
            with get_connection(self.db_path) as conn:
                self._get_normalizer(conn)
                cursor = conn.execute(
                    f"SELECT {', '.join(SERVED_ROW_COLUMNS)} FROM photos WHERE category = ?", (category,))
                while True:
                    batch = cursor.fetchmany(1000)
                    if not batch:
                        break
                    for row in batch:
                        vector = np.array([self._metric_vector(dict(row), category, mask_missing=True)])
                        total += (_row_scores_and_gradient(vector, new_w)[0][0]
                                  - _row_scores_and_gradient(vector, old_w)[0][0])
                        count += 1
        except sqlite3.Error:
            logger.warning("Could not project the %s category's mean shift: bonus not re-centred",
                           category, exc_info=True)
            return None
        if count == 0:
            logger.info("No photos stored in category %s: bonus not re-centred", category)
            return None
        return float(total / count)

    def apply_optimized_weights(
        self,
        new_weights: Dict[str, float],
        category: str,
        backup: bool = True
    ) -> Optional[int]:
        """
        Apply optimized weights to scoring_config.json.

        The category's ``modifiers.bonus`` is re-centred in the same write by the
        projected mean shift of the category's scores, so applying new weights
        changes how the category's photos rank among themselves, not where the
        category sits against the others. A category with no ``categories[]``
        entry (the v3 ``others`` block) has no bonus and is left as is.

        The quality weight is folded into aesthetic and set to 0, so the served
        weights equal ``new_weights`` (which are over the served weight space).

        Args:
            new_weights: Dict of component -> weight (0.0 to 1.0)
            category: Category to update
            backup: Record a pre-apply weight snapshot (weights and bonus)
                    before modifying

        Returns:
            The snapshot id when backup=True (else None)
        """
        from api.config import CONFIG_WRITE_LOCK
        # Measured before the lock (it reads every photo of the category). A
        # weights writer landing in between leaves a residual of its own size.
        mean_shift = self._projected_mean_shift(new_weights, category)
        with CONFIG_WRITE_LOCK:
            return self._apply_weights_locked(new_weights, category, backup, mean_shift)

    def _apply_weights_locked(
        self,
        new_weights: Dict[str, float],
        category: str,
        backup: bool,
        mean_shift: Optional[float] = None,
    ) -> Optional[int]:
        """Rewrite one category's weights with the config lock already held.

        The lock spans this whole read-modify-write rather than the write
        alone. ``atomic_write_json`` is at BEST atomic per WRITE — and only on
        its rename route; where it has to rewrite the file in place to keep the
        operator's ownership, even a single write is not atomic against an
        outside reader. Either way a concurrent writer landing between the read
        below and the write at the end has its update overwritten wholesale;
        CLAUDE.md makes that lock the single one every scoring_config.json
        writer shares. Nothing here may call
        ``reload_config``, which reaches the same lock through ``_load_config``
        and would deadlock against the frame above.

        ``mean_shift`` is the projected mean change of the category's scores
        (:meth:`_projected_mean_shift`); the bonus read here, inside the lock, is
        moved by minus that, clamped to the viewer's range, in the same write.
        """
        # Load the resolved config: the file is only the operator's override
        config = load_resolved(self.config_path)

        # Update weights for the category — v4 categories array first, v3 fallback
        entry = self._find_category_entry(config, category)
        cat_weights = None
        if entry is not None:
            if 'weights' not in entry:
                entry['weights'] = {}
            cat_weights = entry['weights']

        if cat_weights is None:
            # v3 fallback
            if 'weights' not in config:
                config['weights'] = {}
            if category not in config['weights']:
                config['weights'][category] = {}
            cat_weights = config['weights'][category]

        # The bonus a restore must give back: only a categories[] entry has one
        # (the scorer reads a missing one as 0)
        bonus_old = float((entry.get('modifiers') or {}).get('bonus', 0) or 0) if entry is not None else None

        # Snapshot the current weights before overwriting (restorable from the viewer)
        snapshot_id = None
        if backup:
            try:
                from db import record_weight_snapshot
                snapshot_id = record_weight_snapshot(
                    category, dict(cat_weights),
                    created_by='auto:optimizer', db=self.db_path,
                    category_bonus=bonus_old,
                )
                logger.info("Recorded pre-apply weight snapshot (id=%s)", snapshot_id)
            except Exception:
                logger.warning("Could not record pre-apply weight snapshot", exc_info=True)

        # Components are config metric keys - write '<key>_percent' directly,
        # rounded to a tenth of a percent and summing to exactly 100
        served = self._load_current_weights(category)
        for component, percent in self._round_percent_weights(new_weights, served, log=True).items():
            cat_weights[f"{component}_percent"] = percent

        # The new weights are over the SERVED weight space (quality already folded
        # into aesthetic), so quality must stop contributing: left in place it
        # would be folded into the fitted aesthetic weight a second time.
        if 'quality_percent' in cat_weights:
            cat_weights['quality_percent'] = 0

        # Drop stale '<base>_percent' keys whose base is not a real scoring metric
        # (e.g. DB-column-named keys a pre-alignment apply may have left behind).
        # get_weights treats every '*_percent' as a weight and renormalizes over
        # them, so cruft would silently dilute the real metrics.
        valid_metric_keys = set(SCORING_METRIC_KEYS) | {'quality'}
        # Keep config-enabled extended-IQA metrics: build_metric_vector exposes
        # qrealign/aesthetic_v25/deqa to the aggregate only when their
        # iqa_extended flag is on, so a user who enabled and weighted one must
        # not have that weight stripped here as if it were cruft.
        try:
            ext = self.cfg.get_extended_iqa_settings()
            valid_metric_keys |= {k for k in ('qrealign', 'aesthetic_v25', 'deqa') if ext.get(k)}
        except Exception:
            pass
        for key in [k for k in cat_weights
                    if k.endswith('_percent') and k[:-len('_percent')] not in valid_metric_keys]:
            del cat_weights[key]

        # Re-centre the category bonus so the mean score of the category's photos
        # stays where it was
        if entry is None or bonus_old is None:
            logger.info("no category entry for %s, bonus not re-centred", category)
        elif mean_shift is not None:
            wanted = bonus_old - mean_shift
            new_bonus = max(_BONUS_MIN, min(_BONUS_MAX, wanted))
            logger.info("Projected mean score shift of %s: %+.2f (bonus %.2f -> %.2f)",
                        category, mean_shift, bonus_old, new_bonus)
            if wanted != new_bonus:
                logger.warning(
                    "Bonus for %s is clamped to [%g, %g]: a residual mean shift of %+.2f remains",
                    category, _BONUS_MIN, _BONUS_MAX, new_bonus - wanted)
            if abs(new_bonus - bonus_old) >= 0.005:
                entry.setdefault('modifiers', {})['bonus'] = round(new_bonus, 2)

        # Save through the shared config writer rather than a local
        # open()+os.replace(): it is the one primitive that keeps the three
        # properties this file needs. It copies the DESTINATION's mode onto the
        # replacement, so the 0600 docker-entrypoint.sh seeds on a config
        # holding viewer.password, users.*.password_hash, upload.password,
        # frame.tokens and immich.api_key in plaintext survives an --apply
        # instead of widening to the umask default forever; it keeps that file's
        # OWNER too, rewriting it through its own inode rather than renaming a
        # new one over it when the two differ, so an --apply run inside a
        # rootless container does not leave the operator's config owned by a
        # subuid they cannot chown back from; and it stages under a dotted,
        # gitignored scratch name, so an interrupted write cannot leave a
        # complete copy of that config under a stageable one -- which matters
        # more now, since the one interruption it cannot undo KEEPS that copy on
        # purpose. Imported lazily because api.config mints the server
        # secret at import — the same lazy-import shape facet.py already uses
        # for map_disk_path.
        from api.config import write_user_config
        write_user_config(self.config_path, config)

        return snapshot_id

    def get_optimization_history(self, limit: int = 10) -> List[Dict]:
        """Get recent optimization runs."""
        with get_connection(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT * FROM weight_optimization_runs
                ORDER BY timestamp DESC
                LIMIT ?
            """, (limit,))
            return [dict(row) for row in cursor]

def print_comparison_stats(db_path: str = DEFAULT_DB_PATH):
    """Print comparison statistics for CLI."""
    from comparison import ComparisonManager

    manager = ComparisonManager(db_path)
    stats = manager.get_statistics()

    logger.info("=" * 60)
    logger.info("PAIRWISE COMPARISON STATISTICS")
    logger.info("=" * 60)

    logger.info("Total comparisons: %d", stats['total_comparisons'])
    logger.info("Unique photos compared: %d", stats['unique_photos_compared'])

    logger.info("Winner breakdown:")
    for winner, count in stats['winner_breakdown'].items():
        logger.info("  %s: %d", winner, count)

    if stats['category_breakdown']:
        logger.info("By category:")
        for cat_stat in stats['category_breakdown'][:5]:
            logger.info("  %s: %d", cat_stat['category'], cat_stat['count'])

    if stats['recent_optimization_runs']:
        logger.info("Recent optimization runs:")
        for run in stats['recent_optimization_runs']:
            before = run.get('mse_before') or 0.0
            after = run.get('mse_after') or 0.0
            improvement = after - before
            logger.info(
                "  %s: accuracy %.1f%% -> %.1f%% (%+.1f pp)",
                run['timestamp'][:10],
                before,
                after,
                improvement,
            )

    logger.info("=" * 60)


def run_weight_optimization(
    db_path: str = DEFAULT_DB_PATH,
    config_path: Optional[str] = None,
    min_comparisons: int = 30,
    sources: Optional[List[str]] = None,
    category: Optional[str] = None,
    min_improvement: float = 2.0,
    force: bool = False,
    l2_regularization: float = DEFAULT_L2_REGULARIZATION,
):
    """Run weight optimization from CLI. Applies weights only if they generalize.

    The final weights are fit on all comparisons, but the decision to apply is
    the held-out gate of ``optimize_weights_with_cv`` (photo-grouped folds, a
    one-sided McNemar test at p < 0.05 and a pooled held-out gain of at least
    ``min_improvement`` pp), so weights that merely overfit the labelled set
    are not written. When the gate cannot run (too few independent photo
    groups), nothing is applied. Pass force=True to apply regardless.

    Args:
        min_comparisons: Minimum DECISIVE comparisons required (ties do not count)
        sources: Restrict training data to these comparison sources
                 (vote/culling/rating); None uses all with reliability weighting
        category: Category to train on and write weights to. When set, only
                  that category's comparisons are used and the result lands in
                  the v4 categories[].weights block. When None, all comparisons
                  are pooled and the result is written to the legacy 'others'
                  block (which v4 config does NOT read - pass an explicit
                  category to actually affect scoring).
        min_improvement: Minimum pooled held-out accuracy gain (pp) over the
                  current weights required to apply.
        force: Apply the fitted weights even if the held-out gate is not met.
        l2_regularization: Strength of the prior toward the current weights.
    """
    config_path = resolve_scoring_config_path(config_path)
    optimizer = WeightOptimizer(db_path, config_path)

    logger.info("=" * 60)
    logger.info("WEIGHT OPTIMIZATION%s", f" - category: {category}" if category else " - all comparisons (pooled)")
    logger.info("=" * 60)

    if category is None:
        logger.warning(
            "No --optimize-category given: training on all comparisons and writing to "
            "the legacy 'others' block, which the v4 config does not read. Pass "
            "--optimize-category <name> to actually change scoring."
        )
    else:
        valid_categories = [c.get('name') for c in load_resolved(config_path).get('categories', [])]
        if category not in valid_categories:
            logger.error(
                "Unknown --optimize-category '%s': not a v4 category. Optimized weights "
                "would be written to a block the config never reads. Valid categories: %s",
                category, ', '.join(sorted(n for n in valid_categories if n)),
            )
            return

    logger.info("Optimizing weights via direct preference optimization...")
    result = optimizer.optimize_weights_direct(
        category=category,
        min_comparisons=min_comparisons,
        sources=sources,
        min_improvement_threshold=min_improvement,
        l2_regularization=l2_regularization,
    )

    if 'error' in result:
        logger.error("Error: %s", result['error'])
        return

    logger.info("Comparisons used: %d (%d ties)", result['comparisons_used'], result['ties_included'])
    for source, count in sorted(result.get('source_counts', {}).items()):
        weight = WeightOptimizer.SOURCE_WEIGHTS.get(source, 1.0)
        logger.info("  source %s: %d (likelihood weight %.1f)", source, count, weight)
    logger.info("Accuracy before:       %.1f%% (current weights, full set)", result['accuracy_before'])
    logger.info("Accuracy after (train): %.1f%% (fitted weights, same set - optimistic)", result['accuracy_after'])
    logger.info("Log-likelihood:        %.4f", result.get('log_likelihood', 0.0))

    # The held-out gate decides. The direct fit already ran it when its
    # in-sample gain cleared the threshold; otherwise run it here so the log
    # always carries the honest estimate.
    cv = result.get('gate') or optimizer.optimize_weights_with_cv(
        category=category, min_comparisons=min_comparisons, sources=sources,
        l2_regularization=l2_regularization, min_improvement=min_improvement,
    )
    passed = False
    if 'error' in cv:
        logger.warning("Held-out gate unavailable (%s): not applying.", cv['error'])
    else:
        passed = cv['passed']
        logger.info(
            "Held-out accuracy:      %.1f%% +/- %.1f (%d-fold, photo-grouped) - the honest estimate",
            cv['cv_accuracy'], cv.get('cv_std', 0.0), cv.get('n_folds', 0),
        )
        logger.info(
            "Held-out gain:          %+.1f pp over the current weights on the same %d pairs",
            cv['heldout_gain_pp'], cv['heldout_pairs'],
        )
        logger.info(
            "McNemar (one-sided):    p = %.4f (only the fit right: %d, only the current weights right: %d)",
            cv['p_value'], cv['discordant_new'], cv['discordant_old'],
        )

    logger.info("Optimized weights:")
    for component, weight in sorted(result['new_weights'].items(), key=lambda x: -x[1]):
        if weight > 0.01:
            logger.info("  %s: %.1f%%", component, weight * 100)

    if not (force or passed):
        logger.info(
            "NOT applying: the held-out gate needs p < %.2f and a gain of at least %.1f pp. "
            "Weights likely overfit the %d labelled comparisons. Use force=True to override.",
            _GATE_ALPHA, min_improvement, result['comparisons_used'],
        )
        logger.info("=" * 60)
        return

    if force and not passed:
        logger.warning("Forcing apply despite the held-out gate.")

    logger.info("Applying weights to config...")
    optimizer.apply_optimized_weights(
        result['new_weights'],
        category=category or 'others',
    )
    logger.info("  Config updated: %s", config_path)
    logger.info("Run 'python facet.py --recompute-average' to apply new weights to scores.")

    logger.info("=" * 60)
