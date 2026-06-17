"""
Weight Optimizer for Pairwise Comparison Feedback System.

Directly optimizes weights to maximize the likelihood that the weighted
component scores correctly predict comparison outcomes. Uses the
Bradley-Terry probability model with Davidson extension for ties.

Usage::

    optimizer = WeightOptimizer(db_path)

    # Single-shot direct optimization
    result = optimizer.optimize_weights_direct(category='others')

    # With cross-validation for robustness
    result = optimizer.optimize_weights_with_cv(category='others')

    # Apply optimized weights to config
    optimizer.apply_optimized_weights(result['new_weights'], category='others')

CLI::

    python facet.py --optimize-weights
"""

import json
import logging
import shutil
from datetime import datetime
from typing import Dict, List, Optional
import numpy as np
from scipy.optimize import minimize
from db import DEFAULT_DB_PATH, get_connection
from config import ScoringConfig
from processing.scorer import build_metric_vector, SCORING_METRIC_KEYS

logger = logging.getLogger("facet.optimizer")


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

    def __init__(self, db_path: str = DEFAULT_DB_PATH, config_path: str = 'scoring_config.json'):
        self.db_path = db_path
        self.config_path = config_path
        self._cfg: Optional[ScoringConfig] = None

    @property
    def cfg(self) -> ScoringConfig:
        """Lazily-loaded scoring config (for metric-vector construction)."""
        if self._cfg is None:
            self._cfg = ScoringConfig(self.config_path)
        return self._cfg

    def _metric_vector(self, row: dict, category: Optional[str]) -> List[float]:
        """Build the production metric vector for one photo, in component order.

        Uses the photo's own determined category when none is supplied so the
        category-dependent terms (leading-lines blend, isolation) match scoring.
        Values are clamped to 0-10 exactly as the scorer clamps them.
        """
        cat = category or self.cfg.determine_category(row)
        vec = build_metric_vector(row, self.cfg, cat, weights=self.cfg.get_weights(cat))
        return [max(0.0, min(10.0, vec.get(c, 0.0))) for c in self.SCORE_COMPONENTS]

    def _fetch_comparison_data(
        self,
        conn,
        category: Optional[str] = None,
        include_ties: bool = True,
        sources: Optional[List[str]] = None,
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
            features_a.append(self._metric_vector(a, category))
            features_b.append(self._metric_vector(b, category))
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

    def optimize_weights_direct(
        self,
        category: Optional[str] = None,
        min_comparisons: int = 30,
        include_ties: bool = True,
        tie_sensitivity: float = 0.1,
        min_improvement_threshold: float = 2.0,
        l2_regularization: float = 0.01,
        sources: Optional[List[str]] = None,
    ) -> Dict:
        """
        Directly optimize weights to maximize comparison agreement.

        Uses Bradley-Terry probability model:
            P(A > B) = sigmoid(score_A - score_B)

        With Davidson extension for ties:
            P(tie) = 2 * theta * sqrt(P(A) * P(B)) / (P(A) + P(B) + 2*theta*sqrt(P(A)*P(B)))

        This approach is superior to the two-stage method because:
        - Uses raw comparison data directly (no information loss)
        - Optimizes for actual prediction accuracy, not MSE to arbitrary scores
        - Handles ties properly with Davidson model
        - More data-efficient (works with fewer comparisons)

        Args:
            category: Optimize weights for specific category (or all if None)
            min_comparisons: Minimum comparisons required before optimization
            include_ties: Whether to include tie comparisons in optimization
            tie_sensitivity: Davidson theta parameter (higher = more ties expected)
            min_improvement_threshold: Only suggest changes if accuracy improves by this %
            l2_regularization: L2 penalty on weight changes from current weights

        Returns:
            Dict with:
            - old_weights, new_weights: weight dictionaries
            - accuracy_before, accuracy_after: % of comparisons predicted correctly
            - log_likelihood: final negative log-likelihood
            - suggest_changes: whether to apply the new weights
            - per_comparison: list of (photo_a, photo_b, winner, predicted_correct)
        """
        with get_connection(self.db_path) as conn:
            comparisons, X_a, X_b, winners, row_weights = self._fetch_comparison_data(
                conn, category=category, include_ties=include_ties, sources=sources,
            )

            if len(comparisons) < min_comparisons:
                return {
                    'error': f'Need at least {min_comparisons} comparisons (have {len(comparisons)})',
                    'comparison_count': len(comparisons),
                }

            n_features = len(self.SCORE_COMPONENTS)

            # Load current weights
            old_weights = self._load_current_weights(category)
            old_w = np.array([old_weights.get(c, 1.0/n_features) for c in self.SCORE_COMPONENTS])
            if old_w.sum() > 0:
                old_w = old_w / old_w.sum()
            else:
                old_w = np.ones(n_features) / n_features

            theta = tie_sensitivity

            def neg_log_likelihood(weights, return_predictions=False):
                """Compute negative log-likelihood of comparison outcomes."""
                # Normalize weights
                w_sum = weights.sum()
                if w_sum > 1e-8:
                    w = weights / w_sum
                else:
                    w = np.ones(n_features) / n_features

                # Compute weighted scores
                scores_a = X_a @ w
                scores_b = X_b @ w
                diff = scores_a - scores_b

                total_nll = 0.0
                predictions = []

                for i, (d, winner) in enumerate(zip(diff, winners)):
                    if winner == 1:  # A wins
                        # Log P(A > B) = log(sigmoid(diff)) = -log(1 + exp(-diff))
                        if d > 20:
                            nll = 0.0
                        elif d < -20:
                            nll = -d
                        else:
                            nll = np.log1p(np.exp(-d))
                        pred_correct = d > 0
                    elif winner == -1:  # B wins
                        # Log P(B > A) = log(sigmoid(-diff)) = -log(1 + exp(diff))
                        if d < -20:
                            nll = 0.0
                        elif d > 20:
                            nll = d
                        else:
                            nll = np.log1p(np.exp(d))
                        pred_correct = d < 0
                    else:  # Tie - Davidson model approximation
                        # For ties, we use a simpler model: higher probability near diff=0
                        # -log P(tie) ≈ (diff/theta)^2 for small theta
                        # This encourages equal scores for ties
                        nll = (d / (theta + 0.1)) ** 2
                        pred_correct = abs(d) < 0.5  # Consider "correct" if scores close

                    # Down-weight noisier comparison sources (rating/culling)
                    total_nll += row_weights[i] * nll

                    if return_predictions:
                        predictions.append(pred_correct)

                # Add L2 regularization to discourage large changes from current weights
                l2_penalty = l2_regularization * np.sum((weights - old_w) ** 2)
                total_nll += l2_penalty

                if return_predictions:
                    return total_nll, predictions
                return total_nll

            def compute_accuracy(weights):
                """Compute prediction accuracy for given weights."""
                w_sum = weights.sum()
                if w_sum > 1e-8:
                    w = weights / w_sum
                else:
                    w = np.ones(n_features) / n_features

                scores_a = X_a @ w
                scores_b = X_b @ w
                diff = scores_a - scores_b

                correct = 0
                total = 0
                for d, winner in zip(diff, winners):
                    if winner == 1:  # A should win
                        if d > 0:
                            correct += 1
                        total += 1
                    elif winner == -1:  # B should win
                        if d < 0:
                            correct += 1
                        total += 1
                    # Ties don't count toward accuracy

                return (correct / total * 100) if total > 0 else 0.0

            # Calculate accuracy with old weights
            accuracy_before = compute_accuracy(old_w)

            # Optimization bounds and constraints
            bounds = [(0.0, 0.60) for _ in range(n_features)]
            constraints = {'type': 'eq', 'fun': lambda w: w.sum() - 1.0}

            # Multiple random restarts
            best_result = None
            best_nll = float('inf')
            n_restarts = 5

            starting_points = [old_w.copy(), np.ones(n_features) / n_features]
            np.random.seed(42)
            for _ in range(n_restarts - 2):
                starting_points.append(np.random.dirichlet(np.ones(n_features)))

            for start in starting_points:
                try:
                    result = minimize(
                        neg_log_likelihood,
                        start,
                        method='SLSQP',
                        bounds=bounds,
                        constraints=constraints,
                        options={'maxiter': 500, 'ftol': 1e-9}
                    )

                    if result.fun < best_nll:
                        best_nll = result.fun
                        best_result = result.x.copy()
                except Exception:
                    continue

            if best_result is None:
                best_result = old_w.copy()

            # Ensure valid weights
            new_w = np.maximum(best_result, 0.0)
            if new_w.sum() > 0:
                new_w = new_w / new_w.sum()
            else:
                new_w = np.ones(n_features) / n_features

            # Calculate metrics with new weights
            accuracy_after = compute_accuracy(new_w)
            _, predictions = neg_log_likelihood(new_w, return_predictions=True)

            # Build per-comparison breakdown
            per_comparison = []
            for i, (comp, pred_correct) in enumerate(zip(comparisons, predictions)):
                per_comparison.append({
                    'photo_a': comp['photo_a'],
                    'photo_b': comp['photo_b'],
                    'winner': comp['winner'],
                    'predicted_correct': pred_correct,
                })

            # Determine if we should suggest changes
            accuracy_improvement = accuracy_after - accuracy_before
            suggest_changes = accuracy_improvement >= min_improvement_threshold

            # Convert to dicts
            new_weights = {c: float(w) for c, w in zip(self.SCORE_COMPONENTS, new_w)}

            # Log the run
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
    ) -> Dict:
        """
        K-fold cross-validation for robust weight optimization.

        Splits comparisons into k folds, trains on k-1 folds, and evaluates
        on the held-out fold. Returns average weights and CV accuracy.

        Args:
            category: Category to optimize
            n_folds: Number of cross-validation folds
            min_comparisons: Minimum comparisons required
            include_ties: Whether to include ties

        Returns:
            Dict with:
            - average_weights: ensemble weights from all folds
            - cv_accuracy: mean accuracy on held-out comparisons
            - cv_std: standard deviation of accuracy across folds
            - fold_results: per-fold accuracy scores
        """
        with get_connection(self.db_path) as conn:
            all_data, X_a, X_b, winners, row_weights = self._fetch_comparison_data(
                conn, category=category, include_ties=include_ties, sources=sources,
            )

            if len(all_data) < min_comparisons:
                return {
                    'error': f'Need at least {min_comparisons} comparisons (have {len(all_data)})',
                    'comparison_count': len(all_data),
                }

            if len(all_data) < n_folds:
                n_folds = len(all_data)

            n_features = len(self.SCORE_COMPONENTS)

            # Create fold indices
            indices = np.arange(len(all_data))
            np.random.seed(42)
            np.random.shuffle(indices)
            folds = np.array_split(indices, n_folds)

            fold_weights = []
            fold_accuracies = []

            for fold_idx in range(n_folds):
                # Test set is current fold, train set is all others
                test_indices = folds[fold_idx]
                train_indices = np.concatenate([folds[j] for j in range(n_folds) if j != fold_idx])

                if len(train_indices) < 10:
                    continue

                # Train weights on train set
                train_X_a = X_a[train_indices]
                train_X_b = X_b[train_indices]
                train_winners = winners[train_indices]
                train_rw = row_weights[train_indices]

                def neg_log_likelihood_train(weights):
                    w_sum = weights.sum()
                    if w_sum > 1e-8:
                        w = weights / w_sum
                    else:
                        w = np.ones(n_features) / n_features

                    scores_a = train_X_a @ w
                    scores_b = train_X_b @ w
                    diff = scores_a - scores_b

                    total_nll = 0.0
                    for d, winner, rw in zip(diff, train_winners, train_rw):
                        if winner == 1:
                            total_nll += rw * np.log1p(np.exp(-np.clip(d, -20, 20)))
                        elif winner == -1:
                            total_nll += rw * np.log1p(np.exp(np.clip(d, -20, 20)))
                        else:
                            total_nll += rw * (d / 0.2) ** 2
                    return total_nll

                # Optimize
                bounds = [(0.0, 0.60) for _ in range(n_features)]
                constraints = {'type': 'eq', 'fun': lambda w: w.sum() - 1.0}
                start = np.ones(n_features) / n_features

                try:
                    result = minimize(
                        neg_log_likelihood_train,
                        start,
                        method='SLSQP',
                        bounds=bounds,
                        constraints=constraints,
                        options={'maxiter': 300}
                    )
                    trained_w = np.maximum(result.x, 0.0)
                    if trained_w.sum() > 0:
                        trained_w = trained_w / trained_w.sum()
                    else:
                        trained_w = np.ones(n_features) / n_features
                except Exception:
                    trained_w = np.ones(n_features) / n_features

                fold_weights.append(trained_w)

                # Evaluate on test set
                test_X_a = X_a[test_indices]
                test_X_b = X_b[test_indices]
                test_winners = winners[test_indices]

                test_scores_a = test_X_a @ trained_w
                test_scores_b = test_X_b @ trained_w
                test_diff = test_scores_a - test_scores_b

                correct = 0
                total = 0
                for d, winner in zip(test_diff, test_winners):
                    if winner == 1 and d > 0:
                        correct += 1
                    elif winner == -1 and d < 0:
                        correct += 1
                    if winner != 0:
                        total += 1

                fold_acc = (correct / total * 100) if total > 0 else 0.0
                fold_accuracies.append(fold_acc)

            if not fold_weights:
                return {
                    'error': 'Cross-validation failed - not enough data per fold',
                    'comparison_count': len(all_data),
                }

            # Average weights across folds
            avg_weights = np.mean(fold_weights, axis=0)
            avg_weights = avg_weights / avg_weights.sum()

            # Load current weights for comparison
            old_weights = self._load_current_weights(category)

            new_weights = {c: float(w) for c, w in zip(self.SCORE_COMPONENTS, avg_weights)}

            return {
                'old_weights': old_weights,
                'new_weights': new_weights,
                'average_weights': new_weights,
                'cv_accuracy': round(np.mean(fold_accuracies), 1),
                'cv_std': round(np.std(fold_accuracies), 1),
                'fold_results': [round(a, 1) for a in fold_accuracies],
                'n_folds': len(fold_accuracies),
                'comparisons_used': len(all_data),
                'method': 'cross_validated_direct_optimization',
            }

    def compute_weight_confidence(
        self,
        category: Optional[str] = None,
        n_bootstrap: int = 100,
        min_comparisons: int = 30,
        sources: Optional[List[str]] = None,
    ) -> Dict:
        """
        Bootstrap resampling to estimate weight uncertainty.

        Resamples comparisons with replacement and re-optimizes weights
        to estimate confidence intervals.

        Args:
            category: Category to analyze
            n_bootstrap: Number of bootstrap samples
            min_comparisons: Minimum comparisons required

        Returns:
            Dict with:
            - weights: point estimates
            - lower_bounds: 2.5th percentile per weight
            - upper_bounds: 97.5th percentile per weight
            - confidence_intervals: per-component CI width
            - stable_components: components with narrow CIs
        """
        with get_connection(self.db_path) as conn:
            all_data, X_a, X_b, winners, row_weights = self._fetch_comparison_data(
                conn, category=category, include_ties=True, sources=sources,
            )

            if len(all_data) < min_comparisons:
                return {
                    'error': f'Need at least {min_comparisons} comparisons (have {len(all_data)})',
                    'comparison_count': len(all_data),
                }

            n_features = len(self.SCORE_COMPONENTS)

            bootstrap_weights = []
            np.random.seed(42)

            for _ in range(n_bootstrap):
                # Sample with replacement
                indices = np.random.choice(len(all_data), size=len(all_data), replace=True)
                boot_X_a = X_a[indices]
                boot_X_b = X_b[indices]
                boot_winners = winners[indices]
                boot_rw = row_weights[indices]

                def neg_log_likelihood_boot(weights):
                    w_sum = weights.sum()
                    if w_sum > 1e-8:
                        w = weights / w_sum
                    else:
                        w = np.ones(n_features) / n_features

                    scores_a = boot_X_a @ w
                    scores_b = boot_X_b @ w
                    diff = scores_a - scores_b

                    total_nll = 0.0
                    for d, winner, rw in zip(diff, boot_winners, boot_rw):
                        if winner == 1:
                            total_nll += rw * np.log1p(np.exp(-np.clip(d, -20, 20)))
                        elif winner == -1:
                            total_nll += rw * np.log1p(np.exp(np.clip(d, -20, 20)))
                        else:
                            total_nll += rw * (d / 0.2) ** 2
                    return total_nll

                bounds = [(0.0, 0.60) for _ in range(n_features)]
                constraints = {'type': 'eq', 'fun': lambda w: w.sum() - 1.0}
                start = np.ones(n_features) / n_features

                try:
                    result = minimize(
                        neg_log_likelihood_boot,
                        start,
                        method='SLSQP',
                        bounds=bounds,
                        constraints=constraints,
                        options={'maxiter': 200}
                    )
                    boot_w = np.maximum(result.x, 0.0)
                    if boot_w.sum() > 0:
                        boot_w = boot_w / boot_w.sum()
                    else:
                        boot_w = np.ones(n_features) / n_features
                    bootstrap_weights.append(boot_w)
                except Exception:
                    continue

            if len(bootstrap_weights) < 10:
                return {
                    'error': 'Bootstrap failed - not enough successful optimizations',
                    'comparison_count': len(all_data),
                }

            bootstrap_weights = np.array(bootstrap_weights)

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

    def _load_current_weights(self, category: Optional[str]) -> Dict[str, float]:
        """Load current weights from scoring_config.json.

        Components are config metric keys (see SCORING_METRIC_KEYS), so the
        '<key>_percent' lookup is direct - no DB-column translation.
        """
        try:
            with open(self.config_path) as f:
                config = json.load(f)

            cat = category or 'others'

            # Try v4 categories array first, then v3 flat dicts
            cat_weights = {}
            for cat_entry in config.get('categories', []):
                if cat_entry.get('name') == cat:
                    cat_weights = cat_entry.get('weights', {})
                    break
            if not cat_weights:
                if 'category_weights' in config and cat in config['category_weights']:
                    cat_weights = config['category_weights'][cat]
                elif 'weights' in config and cat in config['weights']:
                    cat_weights = config['weights'][cat]

            # Convert percent values to decimal weights
            weights = {}
            for key in self.SCORE_COMPONENTS:
                percent_key = f"{key}_percent"
                weights[key] = cat_weights.get(percent_key, 0.0) / 100.0

            # If all weights are 0, use uniform distribution
            if sum(weights.values()) == 0:
                return {c: 1.0 / len(self.SCORE_COMPONENTS) for c in self.SCORE_COMPONENTS}

            return weights

        except Exception as e:
            logger.warning("Could not load weights from config: %s", e)
            # Return default uniform weights
            return {c: 1.0 / len(self.SCORE_COMPONENTS) for c in self.SCORE_COMPONENTS}

    def apply_optimized_weights(
        self,
        new_weights: Dict[str, float],
        category: str,
        backup: bool = True
    ) -> str:
        """
        Apply optimized weights to scoring_config.json.

        Args:
            new_weights: Dict of component -> weight (0.0 to 1.0)
            category: Category to update
            backup: Create backup before modifying

        Returns:
            Path to backup file (if created)
        """
        if backup:
            # Create timestamped backup
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_path = f"{self.config_path}.backup.{timestamp}"
            shutil.copy2(self.config_path, backup_path)
        else:
            backup_path = None

        # Load current config
        with open(self.config_path) as f:
            config = json.load(f)

        # Update weights for the category — v4 categories array first, v3 fallback
        cat_weights = None
        for cat_entry in config.get('categories', []):
            if cat_entry.get('name') == category:
                if 'weights' not in cat_entry:
                    cat_entry['weights'] = {}
                cat_weights = cat_entry['weights']
                break

        if cat_weights is None:
            # v3 fallback
            if 'weights' not in config:
                config['weights'] = {}
            if category not in config['weights']:
                config['weights'][category] = {}
            cat_weights = config['weights'][category]

        # Components are config metric keys - write '<key>_percent' directly
        for component, weight in new_weights.items():
            cat_weights[f"{component}_percent"] = round(weight * 100, 1)

        # Drop stale '<base>_percent' keys whose base is not a real scoring metric
        # (e.g. DB-column-named keys a pre-alignment apply may have left behind).
        # get_weights treats every '*_percent' as a weight and renormalizes over
        # them, so cruft would silently dilute the real metrics.
        valid_metric_keys = set(SCORING_METRIC_KEYS) | {'quality'}
        # Keep config-enabled extended-IQA metrics: build_metric_vector exposes
        # qalign/aesthetic_v25/deqa to the aggregate only when their iqa_extended
        # flag is on, so a user who enabled and weighted one must not have that
        # weight stripped here as if it were cruft.
        try:
            ext = self.cfg.get_extended_iqa_settings()
            valid_metric_keys |= {k for k in ('qalign', 'aesthetic_v25', 'deqa') if ext.get(k)}
        except Exception:
            pass
        for key in [k for k in cat_weights
                    if k.endswith('_percent') and k[:-len('_percent')] not in valid_metric_keys]:
            del cat_weights[key]

        # Post-rounding normalization to ensure weights sum to exactly 100%
        percent_keys = [f"{c}_percent" for c in new_weights.keys()]
        total = sum(cat_weights[k] for k in percent_keys if k in cat_weights)
        if total > 0 and abs(total - 100.0) > 0.01:
            # Adjust largest weight to compensate for rounding error
            adjustment = 100.0 - total
            largest_key = max(percent_keys, key=lambda k: cat_weights.get(k, 0))
            cat_weights[largest_key] = round(cat_weights[largest_key] + adjustment, 1)
            logger.info("Adjusted %s by %+.1f%% to ensure 100%% total", largest_key, adjustment)

        # Save updated config
        with open(self.config_path, 'w') as f:
            json.dump(config, f, indent=2)

        return backup_path

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
    config_path: str = 'scoring_config.json',
    min_comparisons: int = 30,
    sources: Optional[List[str]] = None,
    category: Optional[str] = None,
    min_improvement: float = 2.0,
    force: bool = False,
):
    """Run weight optimization from CLI. Applies weights only if they generalize.

    The final weights are fit on all comparisons, but the decision to apply is
    gated on held-out k-fold accuracy (not training accuracy), so weights that
    merely overfit the labelled set are not written. Pass force=True to apply
    regardless of the gate.

    Args:
        sources: Restrict training data to these comparison sources
                 (vote/culling/rating); None uses all with reliability weighting
        category: Category to train on and write weights to. When set, only
                  that category's comparisons are used and the result lands in
                  the v4 categories[].weights block. When None, all comparisons
                  are pooled and the result is written to the legacy 'others'
                  block (which v4 config does NOT read - pass an explicit
                  category to actually affect scoring).
        min_improvement: Minimum held-out accuracy gain (pp) over current weights
                  required to apply.
        force: Apply the fitted weights even if the held-out gate is not met.
    """
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
        with open(config_path) as f:
            valid_categories = [c.get('name') for c in json.load(f).get('categories', [])]
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
    )

    if 'error' in result:
        logger.error("Error: %s", result['error'])
        return

    logger.info("Comparisons used: %d", result['comparisons_used'])
    for source, count in sorted(result.get('source_counts', {}).items()):
        weight = WeightOptimizer.SOURCE_WEIGHTS.get(source, 1.0)
        logger.info("  source %s: %d (likelihood weight %.1f)", source, count, weight)
    logger.info("Accuracy before:       %.1f%% (current weights, full set)", result['accuracy_before'])
    logger.info("Accuracy after (train): %.1f%% (fitted weights, same set - optimistic)", result['accuracy_after'])
    logger.info("Log-likelihood:        %.4f", result.get('log_likelihood', 0.0))

    # Held-out generalization estimate gates the apply decision
    cv = optimizer.optimize_weights_with_cv(
        category=category, min_comparisons=min_comparisons, sources=sources,
    )
    cv_accuracy = cv.get('cv_accuracy')
    if 'error' in cv:
        logger.warning("Cross-validation unavailable (%s); falling back to train accuracy for the gate.", cv['error'])
        held_out = result['accuracy_after']
    else:
        held_out = cv_accuracy
        logger.info(
            "Held-out accuracy:      %.1f%% +/- %.1f (%d-fold CV) - the honest estimate",
            cv_accuracy, cv.get('cv_std', 0.0), cv.get('n_folds', 0),
        )

    held_out_improvement = held_out - result['accuracy_before']
    logger.info("Held-out improvement:   %+.1f pp", held_out_improvement)

    logger.info("Optimized weights:")
    for component, weight in sorted(result['new_weights'].items(), key=lambda x: -x[1]):
        if weight > 0.01:
            logger.info("  %s: %.1f%%", component, weight * 100)

    should_apply = force or held_out_improvement >= min_improvement
    if not should_apply:
        logger.info(
            "NOT applying: held-out gain %+.1f pp is below the %.1f pp threshold. "
            "Weights likely overfit the %d labelled comparisons. Use force=True to override.",
            held_out_improvement, min_improvement, result['comparisons_used'],
        )
        logger.info("=" * 60)
        return

    if force and held_out_improvement < min_improvement:
        logger.warning("Forcing apply despite held-out gain %+.1f pp below threshold.", held_out_improvement)

    logger.info("Applying weights to config...")
    backup_path = optimizer.apply_optimized_weights(
        result['new_weights'],
        category=category or 'others',
    )
    if backup_path:
        logger.info("  Backup created: %s", backup_path)
    logger.info("  Config updated: %s", config_path)
    logger.info("Run 'python facet.py --recompute-average' to apply new weights to scores.")

    logger.info("=" * 60)
