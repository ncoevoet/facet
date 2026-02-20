"""
Facet Percentile Normalizer.

Dataset-aware normalization using percentile values.
"""

import os
import json
import sqlite3
from db import get_connection

from config.scoring_config import _calc_stats

# Maximum weight change per recommendation run to prevent over-correction
MAX_WEIGHT_CHANGE_PER_RUN = 3  # +/- 3% per run

class PercentileNormalizer:
    """Computes and applies percentile-based normalization from database."""

    # Metrics that benefit from per-category normalization
    CATEGORY_NORMALIZED_METRICS = [
        'raw_sharpness_variance',  # Macro needs higher, landscape lower
        'raw_color_entropy',       # Food/landscape benefit, portraits less so
        'histogram_spread',        # Night/astro have different expectations
        'raw_eye_sharpness',       # Only for face categories
    ]

    def __init__(self, db_path, target_percentile=95, per_category=False, category_min_samples=50):
        self.db_path = db_path
        self.target_percentile = target_percentile
        self.per_category = per_category
        self.category_min_samples = category_min_samples
        self.percentiles = {}
        self.category_percentiles = {}  # {metric: {category: p_value}}

    def compute_percentiles(self):
        """Compute percentile values for all raw metrics in the database."""
        metrics = [
            'raw_sharpness_variance', 'raw_color_entropy', 'raw_eye_sharpness',
            'histogram_spread', 'mean_luminance'
        ]

        with get_connection(self.db_path, row_factory=False) as conn:
            for metric in metrics:
                try:
                    cursor = conn.execute(f"""
                        SELECT {metric} FROM photos
                        WHERE {metric} IS NOT NULL
                        ORDER BY {metric}
                    """)
                    # Filter out non-numeric values (bytes/BLOB)
                    values = [row[0] for row in cursor.fetchall()
                              if isinstance(row[0], (int, float))]
                    if values:
                        idx = int(len(values) * self.target_percentile / 100)
                        self.percentiles[metric] = values[min(idx, len(values) - 1)]
                except sqlite3.OperationalError:
                    # Column doesn't exist yet
                    pass

        return self.percentiles

    def compute_percentiles_per_category(self):
        """Compute percentile values grouped by category.

        Returns:
            Dict of {metric: {category: p_value, ...}, ...}
        """
        with get_connection(self.db_path, row_factory=False) as conn:
            # First check if category column exists
            cursor = conn.execute("PRAGMA table_info(photos)")
            columns = [col[1] for col in cursor.fetchall()]
            if 'category' not in columns:
                print("Warning: category column not found, skipping per-category percentiles")
                return self.category_percentiles

            for metric in self.CATEGORY_NORMALIZED_METRICS:
                try:
                    # Get all categories with enough samples
                    cursor = conn.execute(f"""
                        SELECT category, COUNT(*) as cnt
                        FROM photos
                        WHERE {metric} IS NOT NULL AND category IS NOT NULL
                        GROUP BY category
                        HAVING cnt >= ?
                    """, (self.category_min_samples,))
                    valid_categories = [row[0] for row in cursor.fetchall()]

                    if not valid_categories:
                        continue

                    self.category_percentiles[metric] = {}

                    for category in valid_categories:
                        cursor = conn.execute(f"""
                            SELECT {metric} FROM photos
                            WHERE {metric} IS NOT NULL AND category = ?
                            ORDER BY {metric}
                        """, (category,))
                        values = [row[0] for row in cursor.fetchall()
                                  if isinstance(row[0], (int, float))]
                        if values:
                            idx = int(len(values) * self.target_percentile / 100)
                            self.category_percentiles[metric][category] = values[min(idx, len(values) - 1)]

                except sqlite3.OperationalError:
                    pass

        return self.category_percentiles

    def normalize_with_category(self, metric, raw_value, category):
        """Apply category-specific normalization.

        Falls back to global percentile if:
        - per_category is disabled
        - category has < min_samples photos
        - metric is not in CATEGORY_NORMALIZED_METRICS
        """
        # Handle None or bytes (BLOB) values
        if raw_value is None or isinstance(raw_value, bytes):
            return None

        # Convert numpy types to Python float
        try:
            import numpy as np
            if isinstance(raw_value, (np.floating, np.integer)):
                raw_value = float(raw_value)
        except ImportError:
            pass

        # Check if per-category normalization applies
        use_category = (
            self.per_category and
            metric in self.CATEGORY_NORMALIZED_METRICS and
            category is not None and
            metric in self.category_percentiles and
            category in self.category_percentiles.get(metric, {})
        )

        if use_category:
            p_value = self.category_percentiles[metric][category]
        elif metric in self.percentiles:
            p_value = self.percentiles[metric]
        else:
            return raw_value

        if p_value == 0:
            return raw_value

        # Scale so p_target -> 10.0
        normalized = (float(raw_value) / float(p_value)) * 10.0
        return min(10.0, max(0.0, normalized))

    def normalize(self, metric, raw_value):
        """Normalize a raw value so the target percentile maps to 10.0."""
        # Handle None or bytes (BLOB) values
        if raw_value is None or isinstance(raw_value, bytes):
            return None

        # Convert numpy types to Python float to avoid BLOB storage
        try:
            import numpy as np
            if isinstance(raw_value, (np.floating, np.integer)):
                raw_value = float(raw_value)
        except ImportError:
            pass

        if metric not in self.percentiles:
            return raw_value

        p_value = self.percentiles[metric]
        if p_value == 0:
            return raw_value  # Pass through if no percentile data

        # Scale so p95 -> 10.0
        normalized = (float(raw_value) / float(p_value)) * 10.0
        return min(10.0, max(0.0, normalized))

    def _compute_correlation(self, x, y):
        """Compute Pearson correlation coefficient between two lists."""
        import math
        if len(x) != len(y) or len(x) < 10:
            return None
        x_mean, y_mean = sum(x) / len(x), sum(y) / len(y)
        numerator = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, y))
        denom_x = math.sqrt(sum((xi - x_mean) ** 2 for xi in x))
        denom_y = math.sqrt(sum((yi - y_mean) ** 2 for yi in y))
        if denom_x > 0 and denom_y > 0:
            return numerator / (denom_x * denom_y)
        return None

    def _compute_spearman(self, x, y):
        """Compute Spearman rank correlation coefficient.

        Spearman correlation captures monotonic (not just linear) relationships,
        making it better for scoring metrics that may have nonlinear effects.
        """
        import math
        if len(x) != len(y) or len(x) < 10:
            return None

        def _rank(values):
            """Convert values to ranks (1-indexed), handling ties with average rank."""
            n = len(values)
            sorted_indices = sorted(range(n), key=lambda i: values[i])
            ranks = [0.0] * n
            i = 0
            while i < n:
                # Find all tied values
                j = i
                while j < n - 1 and values[sorted_indices[j]] == values[sorted_indices[j + 1]]:
                    j += 1
                # Assign average rank to all tied values
                avg_rank = (i + j) / 2 + 1  # 1-indexed
                for k in range(i, j + 1):
                    ranks[sorted_indices[k]] = avg_rank
                i = j + 1
            return ranks

        x_ranks = _rank(x)
        y_ranks = _rank(y)

        # Compute Pearson correlation on ranks
        return self._compute_correlation(x_ranks, y_ranks)

    def _expected_correlation(self, weight, num_metrics, metric_std, aggregate_std):
        """Compute expected correlation using variance-aware formula.

        A metric's expected correlation with the aggregate depends on:
        - Its weight in the aggregate formula
        - The number of other metrics (more metrics = lower individual correlation)
        - The metric's variance relative to the aggregate variance

        This replaces the arbitrary weight * 2.5 formula.
        """
        import math
        if aggregate_std == 0 or num_metrics == 0:
            return weight  # Fallback

        # Expected correlation is approximately:
        # r = weight * sqrt(num_metrics) * (metric_std / aggregate_std)
        # Capped at 0.95 to leave room for noise
        expected = weight * math.sqrt(num_metrics) * (metric_std / aggregate_std)
        return min(0.95, max(0.0, expected))

    def _apply_damping(self, current_value, proposed_value):
        """Cap weight changes to MAX_WEIGHT_CHANGE_PER_RUN to prevent over-correction.

        Args:
            current_value: Current weight percentage
            proposed_value: Proposed new weight percentage

        Returns:
            Damped proposed value
        """
        delta = proposed_value - current_value
        if abs(delta) > MAX_WEIGHT_CHANGE_PER_RUN:
            return current_value + (MAX_WEIGHT_CHANGE_PER_RUN if delta > 0 else -MAX_WEIGHT_CHANGE_PER_RUN)
        return proposed_value

    def _detect_conflicts(self, issues):
        """Detect and resolve conflicting recommendations.

        Groups issues by their target (category, weight_key) and detects
        opposite directions (increase vs decrease). Keeps only the highest
        priority recommendation when conflicts exist.

        Args:
            issues: List of issue dicts from _analyze_scoring_issues

        Returns:
            List of issues with conflicts resolved
        """
        # Group proposals by (category, key)
        target_groups = {}  # (category, key) -> list of (issue, direction, priority)

        for issue in issues:
            for proposal in issue.get('proposals', []):
                location = proposal.get('location', '')
                change = proposal.get('change', '')

                if '->' not in location or '->' not in change:
                    continue

                # Parse location to get category and key
                _, path = location.split('->', 1)
                path = path.strip()
                parts = path.split('.')

                if len(parts) >= 3 and parts[0] == 'weights' and '_percent' in parts[2]:
                    category = parts[1]
                    key = parts[2]

                    # Determine direction (increase or decrease)
                    try:
                        old_val = int(change.split('->')[0].strip().replace('%', ''))
                        new_val = int(change.split('->')[1].strip().replace('%', ''))
                        direction = 'increase' if new_val > old_val else 'decrease'
                    except (ValueError, IndexError):
                        continue

                    target_key = (category, key)
                    if target_key not in target_groups:
                        target_groups[target_key] = []
                    target_groups[target_key].append({
                        'issue': issue,
                        'direction': direction,
                        'priority': issue.get('priority', 0),
                    })

        # Detect conflicts and mark issues to remove
        issues_to_remove = set()
        for target_key, group in target_groups.items():
            directions = set(g['direction'] for g in group)
            if len(directions) > 1:
                # Conflict detected - keep only highest priority
                sorted_group = sorted(group, key=lambda g: g['priority'], reverse=True)
                # Keep first (highest priority), mark others for removal
                for g in sorted_group[1:]:
                    issues_to_remove.add(id(g['issue']))

        # Return filtered list
        return [issue for issue in issues if id(issue) not in issues_to_remove]

    def _load_recommendation_history(self, conn, limit=20):
        """Load recent recommendation history for oscillation detection.

        Args:
            conn: Database connection
            limit: Maximum number of recent records to load

        Returns:
            List of history records as dicts
        """
        try:
            cursor = conn.execute("""
                SELECT issue_type, target_category, target_key, old_value, proposed_value,
                       was_applied, run_timestamp
                FROM recommendation_history
                ORDER BY run_timestamp DESC
                LIMIT ?
            """, (limit,))
            return [dict(row) for row in cursor.fetchall()]
        except sqlite3.OperationalError:
            # Table doesn't exist yet
            return []

    def _detect_oscillation(self, history, category, key, old_value, proposed_value):
        """Detect if a recommendation would create an oscillation pattern.

        Checks for A->B->A patterns in recent history for the same target.

        Args:
            history: Recent history records from _load_recommendation_history
            category: Target category
            key: Target weight key
            old_value: Current value
            proposed_value: Proposed new value

        Returns:
            True if oscillation detected, False otherwise
        """
        # Filter history for this target
        target_history = [
            h for h in history
            if h.get('target_category') == category and h.get('target_key') == key
        ]

        if len(target_history) < 2:
            return False

        # Check last 5 applied changes for A->B->A pattern
        applied = [h for h in target_history if h.get('was_applied')][:5]

        if len(applied) < 2:
            return False

        # Look for pattern where we previously changed A->B, then B->A, now proposing A->B again
        # Most recent change
        last = applied[0]
        last_old = last.get('old_value')
        last_proposed = last.get('proposed_value')

        # Second most recent
        prev = applied[1]
        prev_old = prev.get('old_value')
        prev_proposed = prev.get('proposed_value')

        # Check if current proposal reverses the last change
        # Pattern: prev_old -> prev_proposed -> last_old -> last_proposed
        # Current: old_value -> proposed_value
        # Oscillation if proposed_value is close to last_old (going back to where we were)
        if last_old is not None and proposed_value is not None:
            if abs(proposed_value - last_old) <= 1:
                return True

        return False

    def _record_recommendations_to_history(self, conn, issues, config_version_hash, applied=False):
        """Record recommendations to history table.

        Args:
            conn: Database connection
            issues: List of issue dicts
            config_version_hash: Current config version hash
            applied: Whether recommendations were applied
        """
        for issue in issues:
            for proposal in issue.get('proposals', []):
                location = proposal.get('location', '')
                change = proposal.get('change', '')

                if '->' not in location:
                    continue

                _, path = location.split('->', 1)
                path = path.strip()
                parts = path.split('.')

                category = None
                key = None
                old_value = None
                proposed_value = None

                # Parse weight changes
                if len(parts) >= 3 and parts[0] == 'weights':
                    category = parts[1]
                    key = parts[2]
                    if '->' in change:
                        try:
                            old_value = float(change.split('->')[0].strip().replace('%', ''))
                            proposed_value = float(change.split('->')[1].strip().replace('%', ''))
                        except (ValueError, IndexError):
                            pass

                # Record to history
                if category and key:
                    try:
                        conn.execute("""
                            INSERT INTO recommendation_history
                            (config_version_hash, issue_type, target_category, target_key,
                             old_value, proposed_value, was_applied)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (
                            config_version_hash,
                            issue.get('issue_type'),
                            category,
                            key,
                            old_value,
                            proposed_value,
                            1 if applied else 0
                        ))
                    except sqlite3.OperationalError:
                        pass  # Table may not exist yet

    def _get_metric_pairs(self, conn, col_a, col_b):
        """Fetch paired non-null numeric values for two columns."""
        rows = conn.execute(f"""
            SELECT {col_a}, {col_b} FROM photos
            WHERE {col_a} IS NOT NULL AND {col_b} IS NOT NULL
        """).fetchall()
        x, y = [], []
        for r in rows:
            if isinstance(r[0], (int, float)) and isinstance(r[1], (int, float)):
                x.append(r[0])
                y.append(r[1])
        return x, y

    def _confidence_level(self, n, threshold=500):
        """Return confidence level based on sample size."""
        if n >= threshold:
            return 'high'
        elif n >= threshold // 5:
            return 'medium'
        return 'low'

    def _analyze_scoring_issues(self, conn, config, calc_stats, normalizer=None):
        """Analyze scoring data and return proposed config adjustments.

        Returns a list of issue dicts with:
            - issue_type: Type of issue detected
            - description: Human-readable description
            - proposals: List of specific config changes
            - estimated_impact: Estimated score change
            - confidence: 'high', 'medium', or 'low'
            - priority: Numeric priority (higher = more impactful)

        Args:
            normalizer: Optional PercentileNormalizer instance for normalization-aware analysis.
        """
        issues = []
        import math

        # Extract normalization context if available
        norm_target = normalizer.target_percentile if normalizer else None
        norm_per_category = normalizer.per_category if normalizer else False
        norm_percentiles = normalizer.percentiles if normalizer else {}

        # Get analysis thresholds from config
        analysis = config.get_analysis_settings() if config else {}
        aesthetic_max_threshold = analysis.get('aesthetic_max_threshold', 9.0)
        aesthetic_target = analysis.get('aesthetic_target', 9.5)
        quality_avg_threshold = analysis.get('quality_avg_threshold', 7.5)
        quality_weight_threshold = analysis.get('quality_weight_threshold_percent', 10) / 100
        correlation_threshold = analysis.get('correlation_dominant_threshold', 0.5)
        category_min_samples = analysis.get('category_min_samples', 50)
        category_imbalance_threshold = analysis.get('category_imbalance_threshold', 0.5)
        # New thresholds
        ceiling_threshold = analysis.get('ceiling_p90_ratio', 0.95)
        floor_cluster_pct = analysis.get('floor_cluster_percent', 30)
        skew_iqr_ratio = analysis.get('skew_iqr_ratio', 0.3)
        collinearity_threshold = analysis.get('collinearity_threshold', 0.85)
        low_corr_weight_threshold = analysis.get('low_corr_weight_threshold', 0.15)
        low_corr_r_threshold = analysis.get('low_corr_r_threshold', 0.2)
        outlier_iqr_multiplier = analysis.get('outlier_iqr_multiplier', 2.5)
        metric_disagreement_threshold = analysis.get('metric_disagreement_threshold', 4.0)

        total = conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
        if total == 0:
            return issues

        # Get scoring model from a sample photo
        sample = conn.execute(
            "SELECT scoring_model FROM photos WHERE scoring_model IS NOT NULL LIMIT 1"
        ).fetchone()
        scoring_model = sample[0] if sample else 'clip-mlp'

        # === Pre-fetch all metric values and correlations ===
        score_cols = ['aesthetic', 'tech_sharpness', 'exposure_score', 'color_score',
                      'comp_score', 'face_quality', 'quality_score']
        metric_stats = {}
        metric_values = {}
        for col in score_cols:
            try:
                values = [r[0] for r in conn.execute(
                    f"SELECT {col} FROM photos WHERE {col} IS NOT NULL"
                ).fetchall() if isinstance(r[0], (int, float))]
                if values:
                    metric_stats[col] = calc_stats(values)
                    metric_values[col] = values
            except sqlite3.OperationalError:
                pass

        # Compute all correlations with aggregate (using Spearman for robustness)
        correlations = {}
        for col in score_cols:
            try:
                x, y = self._get_metric_pairs(conn, col, 'aggregate')
                if len(x) > 100:
                    # Use Spearman correlation to capture monotonic relationships
                    corr = self._compute_spearman(x, y)
                    if corr is not None:
                        correlations[col] = corr
            except (sqlite3.OperationalError, ZeroDivisionError):
                pass

        # Compute aggregate stats for variance-aware expected correlation
        agg_values = [r[0] for r in conn.execute(
            "SELECT aggregate FROM photos WHERE aggregate IS NOT NULL"
        ).fetchall() if isinstance(r[0], (int, float))]
        agg_stats_full = calc_stats(agg_values) if agg_values else None
        aggregate_std = agg_stats_full['std'] if agg_stats_full else 1.0
        num_metrics = len(score_cols)

        # === 1. UNDERUTILIZED HIGH-VALUE SIGNALS ===
        qual_stats = metric_stats.get('quality_score')
        if qual_stats:
            qual_corr = correlations.get('quality_score', 0)
            qual_already_dominant = qual_corr > correlation_threshold
            if qual_stats['avg'] > quality_avg_threshold and not qual_already_dominant:
                weight_increase = 5
                proposals = []

                ls_weights = config.get_weights('default') if config else {}
                ls_qual = int(ls_weights.get('quality', 0.10) * 100)
                ls_aes = int(ls_weights.get('aesthetic', 0.35) * 100)
                if ls_qual <= quality_weight_threshold * 100:
                    proposals.append({
                        'location': 'scoring_config.json -> weights.default.quality_percent',
                        'change': f'{ls_qual}% -> {ls_qual + weight_increase}%',
                        'offset_from': f'aesthetic_percent ({ls_aes}% -> {ls_aes - weight_increase}%)'
                    })

                pt_weights = config.get_weights('portrait') if config else {}
                pt_qual = int(pt_weights.get('quality', 0.07) * 100)
                pt_face = int(pt_weights.get('face_quality', 0.28) * 100)
                if pt_qual <= quality_weight_threshold * 100:
                    proposals.append({
                        'location': 'scoring_config.json -> weights.portrait.quality_percent',
                        'change': f'{pt_qual}% -> {pt_qual + weight_increase}%',
                        'offset_from': f'face_quality_percent ({pt_face}% -> {pt_face - weight_increase}%)'
                    })

                gp_weights = config.get_weights('group_portrait') if config else {}
                gp_qual = int(gp_weights.get('quality', 0.10) * 100)
                gp_comp = int(gp_weights.get('composition', 0.25) * 100)
                if gp_qual <= quality_weight_threshold * 100:
                    proposals.append({
                        'location': 'scoring_config.json -> weights.group_portrait.quality_percent',
                        'change': f'{gp_qual}% -> {gp_qual + weight_increase}%',
                        'offset_from': f'composition_percent ({gp_comp}% -> {gp_comp - weight_increase}%)'
                    })

                if proposals:
                    issues.append({
                        'issue_type': 'underutilized_signal',
                        'description': f"Quality score high (avg={qual_stats['avg']:.2f}) but weight low",
                        'explanation': f"Quality score (avg {qual_stats['avg']:.2f}) measures "
                                       f"technical image quality (noise, sharpness, artifacts). This signal is strong "
                                       f"but currently given low weight, so it barely affects the final aggregate. "
                                       f"Increasing its weight lets the aggregate better reflect actual image quality.",
                        'proposals': proposals,
                        'estimated_impact': f"+{(0.05 * qual_stats['avg']):.2f} pts from quality boost",
                        'confidence': self._confidence_level(qual_stats['count']),
                        'priority': 70,
                    })

        # === 3. GENERALIZED CORRELATION ANALYSIS ===
        # Build per-category weight maps for all categories
        # metric_col -> weight_key mapping (column name to config key)
        _col_to_weight_key = {
            'aesthetic': 'aesthetic',
            'tech_sharpness': 'tech_sharpness',
            'exposure_score': 'exposure',
            'color_score': 'color',
            'comp_score': 'composition',
            'face_quality': 'face_quality',
            'quality_score': 'quality',
        }
        all_categories = []
        category_weight_maps = {}  # cat_name -> {col: weight}
        if config:
            all_categories = [c.get('name') for c in config.get_categories() if c.get('name')]
            for cat_name in all_categories:
                cat_weights = config.get_weights(cat_name)
                if cat_weights:
                    category_weight_maps[cat_name] = {
                        col: cat_weights.get(wk, 0)
                        for col, wk in _col_to_weight_key.items()
                    }
        # Fallback: use 'default' as default reference for global analysis
        weight_map = category_weight_maps.get('default', {
            col: 0.10 for col in _col_to_weight_key
        })

        def _build_per_category_proposals(col, reduction_fn):
            """Build proposals for all categories that have non-zero weight for col.

            Args:
                col: metric column name (e.g. 'tech_sharpness')
                reduction_fn: callable(current_pct) -> suggested_pct

            Returns:
                list of proposal dicts
            """
            # Map DB column names to config weight key names
            col_to_weight_key = {
                'comp_score': 'composition',
                'color_score': 'color',
                'exposure_score': 'exposure',
            }
            metric_key = col_to_weight_key.get(col, col.replace('_score', '') if col.endswith('_score') else col)
            proposals = []
            for cat_name, cat_wm in category_weight_maps.items():
                current_weight = cat_wm.get(col, 0)
                current_pct = int(current_weight * 100)
                if current_pct < 3:
                    continue  # Skip categories where this metric has negligible weight
                suggested_pct = max(0, reduction_fn(current_pct))
                if suggested_pct >= current_pct:
                    continue  # No reduction needed
                # Apply damping to cap change at MAX_WEIGHT_CHANGE_PER_RUN
                suggested_pct = int(self._apply_damping(current_pct, suggested_pct))
                if suggested_pct >= current_pct:
                    continue  # Damping removed the change
                proposals.append({
                    'location': f'scoring_config.json -> weights.{cat_name}.{metric_key}_percent',
                    'change': f'{current_pct}% -> {suggested_pct}%',
                })
            return proposals
        for col, corr in correlations.items():
            weight = weight_map.get(col, 0.10)
            # Use variance-aware expected correlation formula
            metric_std = metric_stats.get(col, {}).get('std', 1.0) if col in metric_stats else 1.0
            expected_corr = self._expected_correlation(weight, num_metrics, metric_std, aggregate_std)
            if corr > correlation_threshold and corr > expected_corr + 0.15:
                proposals = _build_per_category_proposals(
                    col, lambda pct: max(5, pct - 5))
                if proposals:
                    for p in proposals:
                        p['reason'] = f'Correlation r={corr:.3f} exceeds weight-proportional expectation'
                    current_pct = int(weight * 100)
                    renorm_caveat = (" Note: correlations are computed on post-normalization values and may shift "
                                     "after applying weight changes. Re-run --compute-recommendations after --recompute-average "
                                     "to verify.") if norm_target else ""
                    issues.append({
                        'issue_type': 'dominant_correlation',
                        'description': f"{col} dominates aggregate (r={corr:.3f}, others weight={current_pct}%, expected r~{expected_corr:.2f})",
                        'explanation': f"The correlation between {col} and the aggregate score (r={corr:.3f}) is much higher "
                                       f"than its weight would suggest. This means {col} is effectively "
                                       f"driving the final score — when {col} goes up, the aggregate follows regardless of "
                                       f"other metrics. Reducing its weight across categories restores balance."
                                       + renorm_caveat,
                        'proposals': proposals,
                        'estimated_impact': f'Reduces {col} dominance over aggregate',
                        'confidence': self._confidence_level(metric_stats.get(col, {}).get('count', 0) if isinstance(metric_stats.get(col), dict) else 0),
                        'priority': 60,
                    })

        # 3b. Low-correlation high-weight detection
        for col, weight in weight_map.items():
            if weight >= low_corr_weight_threshold and col in correlations:
                corr = correlations[col]
                if abs(corr) < low_corr_r_threshold:
                    proposals = _build_per_category_proposals(
                        col, lambda pct: max(5, pct - 5))
                    if proposals:
                        for p in proposals:
                            p['reason'] = f'Weight but r={corr:.3f} suggests low influence'
                        current_pct = int(weight * 100)
                        renorm_caveat = (" Note: correlations are computed on post-normalization values and may shift "
                                         "after applying weight changes. Re-run --compute-recommendations after --recompute-average "
                                         "to verify.") if norm_target else ""
                        issues.append({
                            'issue_type': 'low_correlation_high_weight',
                            'description': f"{col} has high weight (others: {current_pct}%) but low correlation with aggregate (r={corr:.3f})",
                            'explanation': f"{col} is given significant weight across categories, but changing "
                                           f"{col} barely moves the aggregate (r={corr:.3f}). The metric is "
                                           f"either too noisy or too uniform to differentiate photos. "
                                           f"Reducing its weight across all categories frees budget for more discriminative metrics."
                                           + renorm_caveat,
                            'proposals': proposals,
                            'estimated_impact': f'Reduces {col} weight across {len(proposals)} categories',
                            'confidence': self._confidence_level(metric_stats.get(col, {}).get('count', 0) if isinstance(metric_stats.get(col), dict) else 0),
                            'priority': 40,
                        })

        # 3c. Inter-metric collinearity detection
        checked_pairs = set()
        for col_a in score_cols:
            for col_b in score_cols:
                if col_a >= col_b:
                    continue
                pair_key = (col_a, col_b)
                if pair_key in checked_pairs:
                    continue
                checked_pairs.add(pair_key)
                try:
                    x, y = self._get_metric_pairs(conn, col_a, col_b)
                    if len(x) > 100:
                        corr = self._compute_correlation(x, y)
                        if corr is not None and corr > collinearity_threshold:
                            w_a = weight_map.get(col_a, 0)
                            w_b = weight_map.get(col_b, 0)
                            lower = col_b if w_b <= w_a else col_a
                            w_lower_pct = int(weight_map.get(lower, 0) * 100)
                            w_higher = col_a if lower == col_b else col_b
                            w_higher_pct = int(weight_map.get(w_higher, 0) * 100)
                            issues.append({
                                'issue_type': 'collinearity',
                                'description': f"{col_a} and {col_b} are highly correlated (r={corr:.3f}) — combined weight is effectively doubled",
                                'explanation': f"These two metrics move together (r={corr:.3f}): when one is high, "
                                               f"the other is almost always high too. With separate weights "
                                               f"({col_a}={int(w_a*100)}%, {col_b}={int(w_b*100)}%), their combined "
                                               f"influence is {int(w_a*100)+int(w_b*100)}% — much more than intended. "
                                               f"Reducing {lower} ({w_lower_pct}%) avoids double-counting the same signal.",
                                'proposals': [{
                                    'location': f'scoring_config.json -> weights',
                                    'change': f'Consider reducing weight of {lower}',
                                    'reason': f'Collinearity r={corr:.3f} means redundant scoring'
                                }],
                                'estimated_impact': 'Reduces double-counting of correlated metrics',
                                'confidence': self._confidence_level(len(x)),
                                'priority': 50,
                            })
                except (sqlite3.OperationalError, ZeroDivisionError):
                    pass

        # === 4. GENERALIZED CATEGORY IMBALANCE ===
        categories = conn.execute(f"""
            SELECT
                CASE
                    WHEN face_ratio > 0.05 AND is_monochrome = 1 THEN 'portrait_bw'
                    WHEN face_ratio > 0.05 THEN 'portrait'
                    WHEN face_count > 1 THEN 'group_portrait'
                    WHEN is_silhouette = 1 THEN 'silhouette'
                    WHEN face_count > 0 THEN 'default'
                    WHEN is_monochrome = 1 THEN 'default'
                    ELSE 'default'
                END as category,
                COUNT(*) as count,
                AVG(aggregate) as avg_score
            FROM photos
            GROUP BY 1
            HAVING count > {category_min_samples}
        """).fetchall()

        cat_scores = {r[0]: (r[1], r[2]) for r in categories}

        # Compute global mean from categories with enough samples
        if cat_scores:
            total_weighted = sum(count * avg for count, avg in cat_scores.values() if avg is not None)
            total_count = sum(count for count, avg in cat_scores.values() if avg is not None)
            global_mean = total_weighted / total_count if total_count > 0 else 0

            # Check every category against global mean
            norm_category_caveat = (" Note: per-category normalization is active, so some score "
                                    "differences between categories may reflect different normalization "
                                    "scales rather than true scoring difficulty.") if norm_per_category else ""
            priority_reduction = 10 if norm_per_category else 0
            for cat_name, (cat_count, cat_avg) in cat_scores.items():
                if cat_avg is None:
                    continue
                gap = global_mean - cat_avg
                if abs(gap) > category_imbalance_threshold:
                    current_weights = config.get_weights(cat_name) if config else {}
                    current_bonus = current_weights.get('bonus', 0)
                    direction = "below" if gap > 0 else "above"
                    if gap > 0 and current_bonus < 0.5:
                        suggested_bonus = round(min(0.5, gap * 0.6), 1)
                        issues.append({
                            'issue_type': 'category_imbalance',
                            'description': f"{cat_name} scores {abs(gap):.2f} {direction} global mean (n={cat_count}, avg={cat_avg:.2f}, global={global_mean:.2f})",
                            'explanation': f"Photos in '{cat_name}' average {cat_avg:.2f} while the global mean is "
                                           f"{global_mean:.2f} — a gap of {abs(gap):.2f} points. This means {cat_name} "
                                           f"photos are systematically penalized compared to other categories. Adding "
                                           f"a bonus of {suggested_bonus} compensates for inherent scoring difficulty "
                                           f"in this category (e.g. group shots are harder to get right)."
                                           + norm_category_caveat,
                            'proposals': [{
                                'location': f'scoring_config.json -> weights.{cat_name}.bonus',
                                'change': f'{current_bonus} -> {suggested_bonus}',
                                'reason': 'Balance category averages toward global mean'
                            }],
                            'estimated_impact': f"+{suggested_bonus:.1f} pts for {cat_name}",
                            'confidence': self._confidence_level(cat_count),
                            'priority': 55 - priority_reduction,
                        })
                    elif gap < 0 and abs(gap) > category_imbalance_threshold * 1.5:
                        issues.append({
                            'issue_type': 'category_imbalance',
                            'description': f"{cat_name} scores {abs(gap):.2f} {direction} global mean (n={cat_count}, avg={cat_avg:.2f}, global={global_mean:.2f})",
                            'explanation': f"Photos in '{cat_name}' average {cat_avg:.2f} vs global mean {global_mean:.2f}. "
                                           f"This category scores significantly higher, which may inflate its photos' "
                                           f"rankings compared to other categories. Consider whether the bonus "
                                           f"(currently {current_bonus}) is too generous or weights are too lenient."
                                           + norm_category_caveat,
                            'proposals': [{
                                'location': f'scoring_config.json -> weights.{cat_name}',
                                'change': f'Review weights or reduce bonus (current bonus={current_bonus})',
                                'reason': 'Category significantly above average'
                            }],
                            'estimated_impact': 'Closer category parity',
                            'confidence': self._confidence_level(cat_count),
                            'priority': 35 - priority_reduction,
                        })

        # === 5. SCORE DISTRIBUTION HEALTH CHECKS ===
        # 5a. Skewed distribution detection (IQR analysis)
        agg_values = metric_values.get('aesthetic', [])
        agg_stats_full = metric_stats.get('aesthetic')
        for col in ['aggregate', 'aesthetic', 'comp_score', 'tech_sharpness']:
            vals = metric_values.get(col) if col != 'aggregate' else None
            if col == 'aggregate':
                vals = [r[0] for r in conn.execute(
                    "SELECT aggregate FROM photos WHERE aggregate IS NOT NULL"
                ).fetchall() if isinstance(r[0], (int, float))]
            if not vals or len(vals) < 50:
                continue
            stats = calc_stats(vals)
            if not stats:
                continue
            iqr = stats['p75'] - stats['p25']
            full_range = stats['max'] - stats['min']
            if full_range > 0 and iqr / full_range < skew_iqr_ratio:
                # Add normalization context if available
                norm_context = ""
                if norm_target:
                    norm_context = f" Current normalization: percentile_target={norm_target}."
                    raw_metric_map = {
                        'tech_sharpness': 'raw_sharpness_variance',
                        'color_score': 'raw_color_entropy',
                    }
                    raw_key = raw_metric_map.get(col)
                    if raw_key and raw_key in norm_percentiles:
                        norm_context += f" Raw metric ({raw_key}) p{norm_target}={norm_percentiles[raw_key]:.4f}."
                issues.append({
                    'issue_type': 'skewed_distribution',
                    'description': f"{col} distribution is narrow (IQR={iqr:.2f}, range={full_range:.2f}, ratio={iqr/full_range:.2f})",
                    'explanation': f"The middle 50% of {col} scores (p25 to p75) spans only {iqr:.2f} points, "
                                   f"while the full range is {full_range:.2f}. This {iqr/full_range:.0%} ratio "
                                   f"(threshold: {skew_iqr_ratio:.0%}) means most photos are bunched in a narrow "
                                   f"band with a few outliers stretching the tails. It's hard to differentiate "
                                   f"'decent' from 'good' when they score within ~{iqr:.1f} points of each other. "
                                   f"Lowering percentile_target (e.g. 90 -> 80) stretches the middle cluster apart."
                                   + norm_context,
                    'proposals': [{
                        'location': 'scoring_config.json -> normalization',
                        'change': f'Adjust percentile normalization for {col} to improve spread',
                        'reason': f'IQR/range ratio {iqr/full_range:.2f} < {skew_iqr_ratio}'
                    }],
                    'estimated_impact': 'Better score differentiation',
                    'confidence': self._confidence_level(len(vals)),
                    'priority': 45,
                })

        # 5b. Score ceiling detection per metric
        for col, stats in metric_stats.items():
            if not stats or stats['count'] < 50:
                continue
            if stats['max'] > 0 and stats['p90'] / stats['max'] > ceiling_threshold:
                issues.append({
                    'issue_type': 'score_ceiling',
                    'description': f"{col} has ceiling effect (p90={stats['p90']:.2f}, max={stats['max']:.2f}, ratio={stats['p90']/stats['max']:.2f})",
                    'explanation': f"90% of {col} scores reach {stats['p90']:.2f} while the maximum is {stats['max']:.2f} — "
                                   f"only {stats['max'] - stats['p90']:.2f} points separate the top 10% from the best. "
                                   f"This ceiling effect compresses the top tier, making it impossible to distinguish "
                                   f"'great' from 'outstanding'. Scaling or adjusting normalization for {col} would "
                                   f"spread out the top scores.",
                    'proposals': [{
                        'location': f'scoring_config.json',
                        'change': f'Adjust scale or normalization for {col}',
                        'reason': f'p90/max ratio > {ceiling_threshold}'
                    }],
                    'estimated_impact': 'Better differentiation at top end',
                    'confidence': self._confidence_level(stats['count']),
                    'priority': 40,
                })

        # 5c. Floor clustering detection
        # Pre-query structural zero counts for face-dependent metrics
        face_na_metrics = {'face_quality', 'eye_sharpness'}
        no_face_count = 0
        if any(m in metric_stats for m in face_na_metrics):
            row = conn.execute("SELECT COUNT(*) FROM photos WHERE face_count = 0 OR face_count IS NULL").fetchone()
            no_face_count = row[0] if row else 0

        for col, stats in metric_stats.items():
            if not stats or stats['count'] < 50:
                continue
            vals = metric_values.get(col, [])
            if not vals:
                continue
            floor_val = stats['min']
            near_floor_count = sum(1 for v in vals if v <= floor_val + 0.5)
            pct_floor = 100 * near_floor_count / len(vals)
            if pct_floor > floor_cluster_pct:
                # Check if floor values are structurally N/A (e.g. face metrics on non-face photos)
                structural_note = ""
                if col in face_na_metrics and no_face_count > 0 and near_floor_count > 0:
                    structural_pct = 100 * no_face_count / near_floor_count if near_floor_count > 0 else 0
                    if structural_pct > 80:
                        structural_note = (f" {structural_pct:.0f}% of floor-value photos have no faces — these are "
                                           f"structurally N/A rather than low-quality. The better fix is ensuring "
                                           f"{col} weight only applies in face-containing categories.")

                proposals = _build_per_category_proposals(
                    col,
                    lambda pct, pf=pct_floor: max(2, pct - max(2, int(pct * min(0.5, pf / 100))))
                )
                if proposals:
                    for p in proposals:
                        p['reason'] = f'{pct_floor:.0f}% of photos clustered at floor — weight is diluted'
                    issues.append({
                        'issue_type': 'floor_clustering',
                        'description': f"{col}: {pct_floor:.0f}% of scores at/near minimum ({floor_val:.2f})",
                        'explanation': f"{pct_floor:.0f}% of photos ({near_floor_count:,}) score at or near {floor_val:.2f} "
                                       f"for {col}. When most photos get the same minimum, the metric stops differentiating — "
                                       f"it just adds a fixed penalty to those photos. Common causes: the metric only applies "
                                       f"to a subset (e.g. face_quality=0 for photos without faces), or the scoring model "
                                       f"bottoms out. Reducing weight across categories limits the penalty impact."
                                       + structural_note,
                        'proposals': proposals,
                        'estimated_impact': f'Reduces {col} influence across {len(proposals)} categories ({near_floor_count} photos at floor)',
                        'confidence': self._confidence_level(len(vals)),
                        'priority': 50,
                    })

        # === 6. OUTLIER & ANOMALY DETECTION ===
        # 6a. Aggregate score outliers (IQR method)
        agg_vals = [r[0] for r in conn.execute(
            "SELECT aggregate FROM photos WHERE aggregate IS NOT NULL"
        ).fetchall() if isinstance(r[0], (int, float))]
        if len(agg_vals) > 50:
            agg_s = calc_stats(agg_vals)
            if agg_s:
                iqr = agg_s['p75'] - agg_s['p25']
                lower = agg_s['p25'] - outlier_iqr_multiplier * iqr
                upper = agg_s['p75'] + outlier_iqr_multiplier * iqr
                outlier_count = sum(1 for v in agg_vals if v < lower or v > upper)
                if outlier_count > 0:
                    pct = 100 * outlier_count / len(agg_vals)
                    issues.append({
                        'issue_type': 'score_outliers',
                        'description': f"{outlier_count} aggregate score outliers ({pct:.1f}%) outside [{lower:.2f}, {upper:.2f}]",
                        'explanation': f"Using the IQR method (p25={agg_s['p25']:.2f}, p75={agg_s['p75']:.2f}, "
                                       f"IQR={iqr:.2f}), scores below {lower:.2f} or above {upper:.2f} are "
                                       f"statistical outliers. {outlier_count} photos ({pct:.1f}%) fall outside "
                                       f"this range. These may be corrupt files, extreme edge cases, or scoring "
                                       f"errors worth investigating in the viewer.",
                        'proposals': [{
                            'location': 'Database',
                            'change': f'Investigate {outlier_count} outlier photos for scoring anomalies',
                            'reason': f'IQR method with {outlier_iqr_multiplier}x multiplier'
                        }],
                        'estimated_impact': f'{outlier_count} photos may need review',
                        'confidence': self._confidence_level(len(agg_vals)),
                        'priority': 25,
                    })

        # 6b. Metric disagreement detection — identify which metrics pull aggregate away
        disagreement_metrics = ['aesthetic', 'tech_sharpness', 'exposure_score', 'color_score',
                                'comp_score', 'face_quality', 'quality_score']
        try:
            cols_sql = ", ".join(disagreement_metrics)
            disagreement_rows = conn.execute(f"""
                SELECT aggregate, {cols_sql}
                FROM photos
                WHERE aesthetic IS NOT NULL AND aggregate IS NOT NULL
            """).fetchall()

            # For each photo with large gap, measure each metric's deviation from aesthetic
            # avg_deviation[metric] = average of (metric - aesthetic) across disagreement photos
            # Negative = metric pulls aggregate down; positive = inflates it
            disagreement_count = 0
            metric_deviation_sums = {m: 0.0 for m in disagreement_metrics if m != 'aesthetic'}
            metric_deviation_counts = {m: 0 for m in disagreement_metrics if m != 'aesthetic'}

            for row in disagreement_rows:
                agg_val = row[0] if isinstance(row[0], (int, float)) else None
                aes_val = row[1] if isinstance(row[1], (int, float)) else None  # aesthetic is index 1
                if agg_val is None or aes_val is None:
                    continue
                if abs(aes_val - agg_val) > metric_disagreement_threshold:
                    disagreement_count += 1
                    for j, m in enumerate(disagreement_metrics):
                        if m == 'aesthetic':
                            continue
                        val = row[j + 1] if isinstance(row[j + 1], (int, float)) else None
                        if val is not None:
                            metric_deviation_sums[m] += (val - aes_val)
                            metric_deviation_counts[m] += 1

            if disagreement_count > 0:
                pct = 100 * disagreement_count / max(len(disagreement_rows), 1)

                # Compute average deviation per metric and rank by absolute impact
                metric_avg_devs = {}
                for m in metric_deviation_sums:
                    if metric_deviation_counts[m] > 0:
                        metric_avg_devs[m] = metric_deviation_sums[m] / metric_deviation_counts[m]

                # Sort by absolute deviation (biggest pullers first)
                sorted_devs = sorted(metric_avg_devs.items(), key=lambda x: abs(x[1]), reverse=True)

                # Build per-category proposals for the top offending metrics
                proposals = []
                explanation_parts = []
                for m, avg_dev in sorted_devs:
                    if abs(avg_dev) < 1.0:
                        continue  # Skip metrics with small deviations
                    direction = "drags down" if avg_dev < 0 else "inflates"
                    explanation_parts.append(f"{m} {direction} by avg {avg_dev:+.1f}")
                    dev_magnitude = abs(avg_dev)
                    metric_proposals = _build_per_category_proposals(
                        m,
                        lambda pct, mag=dev_magnitude: max(2, pct - max(2, min(pct - 2, int(mag * 1.5))))
                    )
                    for p in metric_proposals:
                        p['reason'] = f'{m} {direction} aggregate by avg {avg_dev:+.1f} in disagreement photos'
                    proposals.extend(metric_proposals)

                if not proposals:
                    # Fallback: no single metric stands out enough
                    proposals.append({
                        'location': 'scoring_config.json -> weights',
                        'change': 'Review weight balance — no single metric clearly dominates the gap',
                        'reason': f'{disagreement_count} photos with >±{metric_disagreement_threshold} difference'
                    })

                devs_summary = "; ".join(explanation_parts[:3]) if explanation_parts else "no single dominant metric"
                issues.append({
                    'issue_type': 'metric_disagreement',
                    'description': f"{disagreement_count} photos ({pct:.1f}%) have aesthetic vs aggregate disagreement > {metric_disagreement_threshold}",
                    'explanation': f"For {disagreement_count} photos, aesthetic and aggregate differ by >{metric_disagreement_threshold} pts. "
                                   f"Analysis of what's pulling the aggregate away from aesthetic: {devs_summary}. "
                                   f"Reducing the weight of the biggest offenders narrows the gap so the "
                                   f"aggregate better reflects the aesthetic quality assessment.",
                    'proposals': proposals,
                    'estimated_impact': f'Narrows aesthetic/aggregate gap for {disagreement_count} photos',
                    'confidence': self._confidence_level(len(disagreement_rows)),
                    'priority': 55,
                })
        except sqlite3.OperationalError:
            pass

        # 6c. Stale/missing data detection
        missing_metrics = {}
        for col in ['aesthetic', 'comp_score', 'tech_sharpness', 'exposure_score', 'color_score']:
            try:
                null_count = conn.execute(
                    f"SELECT COUNT(*) FROM photos WHERE {col} IS NULL"
                ).fetchone()[0]
                if null_count > 0:
                    missing_metrics[col] = null_count
            except sqlite3.OperationalError:
                pass
        if missing_metrics:
            most_missing = max(missing_metrics, key=missing_metrics.get)
            total_missing = missing_metrics[most_missing]
            detail = ", ".join(f"{col}={count}" for col, count in sorted(missing_metrics.items(), key=lambda x: -x[1]))
            issues.append({
                'issue_type': 'missing_data',
                'description': f"Missing metrics detected: {detail}",
                'explanation': f"Some photos have NULL values for key scoring metrics. This typically happens "
                               f"when photos were added before a metric was introduced, when scoring was "
                               f"interrupted, or when a model wasn't available during scanning. These photos "
                               f"get incomplete aggregates. Run 'python facet.py /path --force' to rescan them.",
                'proposals': [{
                    'location': 'Command line',
                    'change': 'Run re-scan for photos with missing metrics',
                    'reason': f'{total_missing} photos missing {most_missing}'
                }],
                'estimated_impact': f'{total_missing} photos incomplete',
                'confidence': 'high',
                'priority': 70,
            })

        # === 7. NORMALIZATION EFFECTIVENESS CHECK ===
        # Check if normalized scores actually spread across 0-10
        for col in ['aggregate', 'aesthetic', 'comp_score']:
            vals = metric_values.get(col) if col != 'aggregate' else agg_vals if 'agg_vals' in dir() else None
            if col == 'aggregate' and not vals:
                vals = [r[0] for r in conn.execute(
                    "SELECT aggregate FROM photos WHERE aggregate IS NOT NULL"
                ).fetchall() if isinstance(r[0], (int, float))]
            if not vals or len(vals) < 50:
                continue
            stats = calc_stats(vals)
            if not stats:
                continue
            utilized_range = stats['max'] - stats['min']
            if utilized_range < 4.0:
                issues.append({
                    'issue_type': 'normalization_compressed',
                    'description': f"{col} uses only {utilized_range:.1f} of 10-point scale (range [{stats['min']:.1f}-{stats['max']:.1f}])",
                    'explanation': f"After normalization, {col} scores span only {utilized_range:.1f} points "
                                   f"out of the 0-10 scale. The current percentile normalization maps the "
                                   f"p90 or p95 value to 10.0, but if the raw distribution is already tight, "
                                   f"the result is still compressed. Lowering percentile_target (e.g. 95 -> 85) "
                                   f"or switching to min-max normalization would stretch scores across the "
                                   f"full range, improving differentiation between photos.",
                    'proposals': [{
                        'location': 'scoring_config.json -> normalization',
                        'change': f'Adjust percentile_target or normalization method for {col}',
                        'reason': f'Only {utilized_range:.1f}/10 of range utilized'
                    }],
                    'estimated_impact': 'Better score differentiation',
                    'confidence': self._confidence_level(len(vals)),
                    'priority': 55,
                })

        # === 8. CONFIG VERSION DRIFT ===
        try:
            version_rows = conn.execute("""
                SELECT config_version, COUNT(*) as count
                FROM photos
                WHERE config_version IS NOT NULL
                GROUP BY config_version
                ORDER BY count DESC
            """).fetchall()
            if len(version_rows) > 1:
                latest_version = version_rows[0][0]
                stale_count = sum(r[1] for r in version_rows if r[0] != latest_version)
                if stale_count > 0:
                    pct = 100 * stale_count / total
                    versions_detail = ", ".join(f"v{r[0]}={r[1]}" for r in version_rows[:5])
                    issues.append({
                        'issue_type': 'config_version_drift',
                        'description': f"{stale_count} photos ({pct:.0f}%) scored with older config versions",
                        'explanation': f"The database contains photos scored with {len(version_rows)} different "
                                       f"config versions ({versions_detail}). When you change weights, bonuses, "
                                       f"or normalization settings, only newly scored photos use the new config. "
                                       f"Older photos keep their previous aggregate scores, making comparisons "
                                       f"unfair. Run --recompute-average to recalculate all aggregates with the "
                                       f"current config.",
                        'proposals': [{
                            'location': 'Command line',
                            'change': 'Run --recompute-average to update scores with current config',
                            'reason': f'{len(version_rows)} different config versions in DB'
                        }],
                        'estimated_impact': f'{stale_count} photos may have inconsistent scores',
                        'confidence': 'high',
                        'priority': 75,
                    })
        except sqlite3.OperationalError:
            pass

        # Apply conflict detection - resolve opposing recommendations for same target
        issues = self._detect_conflicts(issues)

        # Load recommendation history and filter out oscillating recommendations
        history = self._load_recommendation_history(conn)
        if history:
            filtered_issues = []
            for issue in issues:
                keep_issue = True
                for proposal in issue.get('proposals', []):
                    location = proposal.get('location', '')
                    change = proposal.get('change', '')

                    if '->' not in location or '->' not in change:
                        continue

                    _, path = location.split('->', 1)
                    path = path.strip()
                    parts = path.split('.')

                    if len(parts) >= 3 and parts[0] == 'weights' and '_percent' in parts[2]:
                        category = parts[1]
                        key = parts[2]
                        try:
                            old_val = float(change.split('->')[0].strip().replace('%', ''))
                            new_val = float(change.split('->')[1].strip().replace('%', ''))
                            if self._detect_oscillation(history, category, key, old_val, new_val):
                                keep_issue = False
                                break
                        except (ValueError, IndexError):
                            pass

                if keep_issue:
                    filtered_issues.append(issue)
            issues = filtered_issues

        # Sort by priority (highest first)
        issues.sort(key=lambda x: x.get('priority', 0), reverse=True)
        return issues

    def print_database_statistics(self, config=None, return_recommendations=False, verbose=False):
        """Print database statistics useful for tuning scoring weights.

        Args:
            config: ScoringConfig instance for weight analysis
            return_recommendations: If True, return list of recommendations instead of just printing
            verbose: If True, show detailed statistics (all sections); otherwise show concise summary

        Returns:
            List of recommendation dicts if return_recommendations=True, else None
        """
        import math

        calc_stats = _calc_stats

        def print_section(title):
            print(f"\n{'='*60}")
            print(f" {title}")
            print('='*60)

        def print_stat_row(label, stats, score_range=False):
            if stats is None:
                print(f"  {label:25} No data")
                return
            if score_range:
                print(f"  {label:25} avg={stats['avg']:5.2f}  std={stats['std']:4.2f}  "
                      f"range=[{stats['min']:.2f}-{stats['max']:.2f}]  "
                      f"p50={stats['p50']:.2f}  p90={stats['p90']:.2f}")
            else:
                print(f"  {label:25} avg={stats['avg']:8.2f}  std={stats['std']:8.2f}  "
                      f"range=[{stats['min']:.2f}-{stats['max']:.2f}]")

        def print_subsection(title):
            print(f"\n {title}")
            print('-'*60)

        def calculate_health_score(agg_stats, tech_issues, rec_count):
            """Calculate database health score (0-100)."""
            score = 100
            if agg_stats:
                if agg_stats['std'] < 0.8:
                    score -= 20
                elif agg_stats['std'] < 1.0:
                    score -= 10
                if agg_stats['max'] < 8.0:
                    score -= 15
                elif agg_stats['max'] < 8.5:
                    score -= 5
            if tech_issues:
                for issue_pct in tech_issues.values():
                    if issue_pct > 20:
                        score -= 5
                    elif issue_pct > 10:
                        score -= 2
            score -= rec_count * 5
            return max(0, min(100, score))

        def get_health_label(score):
            if score >= 90:
                return "Excellent"
            elif score >= 75:
                return "Good"
            elif score >= 60:
                return "Fair"
            elif score >= 40:
                return "Needs Work"
            return "Poor"

        with get_connection(self.db_path) as conn:

            # === GATHER ALL DATA UPFRONT ===
            total = conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]

            if total == 0:
                print("\n" + "="*60)
                print(" FACET DATABASE ANALYSIS")
                print("="*60)
                print("\n  No photos in database. Run scoring first.")
                print("="*60)
                return [] if return_recommendations else None

            # Date range
            dates = conn.execute(
                "SELECT MIN(date_taken), MAX(date_taken) FROM photos WHERE date_taken IS NOT NULL"
            ).fetchone()
            date_range = f"{dates[0][:10]} to {dates[1][:10]}" if dates[0] else "Unknown"

            # Get aggregate stats
            agg_values = [r[0] for r in conn.execute(
                "SELECT aggregate FROM photos WHERE aggregate IS NOT NULL"
            ).fetchall() if isinstance(r[0], (int, float))]
            agg_stats = calc_stats(agg_values)

            # Get categories
            categories = conn.execute("""
                SELECT
                    CASE
                        WHEN face_ratio > 0.05 AND is_monochrome = 1 THEN 'Portrait B&W'
                        WHEN face_ratio > 0.05 THEN 'Portrait'
                        WHEN face_count > 1 THEN 'Group Portrait'
                        WHEN is_silhouette = 1 THEN 'Silhouette'
                        WHEN face_count > 0 THEN 'Human in Others'
                        WHEN is_monochrome = 1 THEN 'Others B&W'
                        ELSE 'Others'
                    END as category,
                    COUNT(*) as count,
                    ROUND(AVG(aggregate), 2) as avg_score,
                    ROUND(MIN(aggregate), 2) as min_score,
                    ROUND(MAX(aggregate), 2) as max_score
                FROM photos
                GROUP BY 1
                ORDER BY count DESC
            """).fetchall()

            # Get technical issues for health score
            issues = conn.execute("""
                SELECT
                    SUM(CASE WHEN shadow_clipped = 1 THEN 1 ELSE 0 END) as shadow_clipped,
                    SUM(CASE WHEN highlight_clipped = 1 THEN 1 ELSE 0 END) as highlight_clipped,
                    SUM(CASE WHEN noise_sigma > 4.0 THEN 1 ELSE 0 END) as noisy,
                    SUM(CASE WHEN tech_sharpness < 4.0 THEN 1 ELSE 0 END) as soft
                FROM photos
            """).fetchone()
            tech_issues = {
                'shadow': 100 * (issues['shadow_clipped'] or 0) / total,
                'highlight': 100 * (issues['highlight_clipped'] or 0) / total,
                'noisy': 100 * (issues['noisy'] or 0) / total,
                'soft': 100 * (issues['soft'] or 0) / total,
            }

            # Get analysis thresholds from config
            analysis = config.get_analysis_settings() if config else {}
            score_clustering_threshold = analysis.get('score_clustering_std_threshold', 1.0)
            top_score_threshold = analysis.get('top_score_threshold', 8.5)
            exposure_avg_threshold = analysis.get('exposure_avg_threshold', 8.0)

            # Get recommendations early so we can show count in summary
            scoring_issues = self._analyze_scoring_issues(conn, config, calc_stats, normalizer=self)

            # Build key findings
            findings = []
            if agg_stats:
                if agg_stats['std'] >= score_clustering_threshold:
                    findings.append(("[OK]", f"Score spread is healthy (std={agg_stats['std']:.2f}, higher=better differentiation)"))
                else:
                    findings.append(("[!]", f"Scores too clustered (std={agg_stats['std']:.2f}, scores not spread enough)"))
                if agg_stats['max'] >= top_score_threshold:
                    findings.append(("[OK]", f"Top scores achievable (max={agg_stats['max']:.2f})"))
                else:
                    findings.append(("[!]", f"Top scores capped low (max={agg_stats['max']:.2f})"))

            exp_values = [r[0] for r in conn.execute(
                "SELECT exposure_score FROM photos WHERE exposure_score IS NOT NULL"
            ).fetchall() if isinstance(r[0], (int, float))]
            exp_stats = calc_stats(exp_values)
            if exp_stats and exp_stats['avg'] > exposure_avg_threshold:
                findings.append(("[!]", f"Exposure scores high (avg={exp_stats['avg']:.2f})"))

            if scoring_issues:
                findings.append(("[!]", f"{len(scoring_issues)} recommendation(s) - see below"))

            # Calculate health score
            health = calculate_health_score(agg_stats, tech_issues, len(scoring_issues))
            health_label = get_health_label(health)

            # === PRINT EXECUTIVE SUMMARY (ALWAYS) ===
            print("\n" + "="*60)
            print(" FACET DATABASE ANALYSIS")
            print("="*60)

            print_subsection("SUMMARY")
            print(f"  Photos: {total:,}  |  Range: {date_range}")
            print(f"  Health: {health}/100 ({health_label})")
            print()
            print("  Findings:")
            for status, msg in findings:
                print(f"    {status:4} {msg}")

            # === PRINT RECOMMENDATIONS PROMINENTLY (ALWAYS) ===
            if scoring_issues:
                print_subsection(f"RECOMMENDATIONS ({len(scoring_issues)} issues, sorted by priority)")
                for i, issue in enumerate(scoring_issues, 1):
                    impact = issue['estimated_impact']
                    confidence = issue.get('confidence', 'unknown')
                    proposals = issue['proposals']
                    if proposals:
                        fix = proposals[0].get('change', '')
                        location = proposals[0].get('location', '').split('->')[-1].strip() if '->' in proposals[0].get('location', '') else ''
                        print(f"  {i}. [{confidence}] {issue['description']}")
                        explanation = issue.get('explanation', '')
                        if explanation:
                            # Wrap explanation to ~72 chars with indent
                            import textwrap
                            wrapped = textwrap.fill(explanation, width=72, initial_indent='     ', subsequent_indent='     ')
                            print(wrapped)
                        print(f"     Impact: {impact}")
                        if location and fix:
                            print(f"     Fix: {location}: {fix}")
                        print()
                print("  [Auto-apply with --apply-recommendations]")

            # === PRINT QUICK STATS (ALWAYS) ===
            print_subsection("QUICK STATS")
            cat_parts = []
            for row in categories[:4]:
                pct = 100.0 * row['count'] / total
                cat_parts.append(f"{row['category']} {pct:.1f}%")
            if len(categories) > 4:
                cat_parts.append("...")
            print(f"  Categories: {', '.join(cat_parts)}")

            if agg_stats:
                print(f"  Scores:     avg={agg_stats['avg']:.2f}  std={agg_stats['std']:.2f}  "
                      f"range=[{agg_stats['min']:.2f}-{agg_stats['max']:.2f}]")

            # === DETAILED SECTIONS (VERBOSE ONLY) ===
            if verbose:
                # === CATEGORY BREAKDOWN ===
                print_section("PHOTO CATEGORIES (Detailed)")
                print(f"  {'Category':<20} {'Count':>6} {'%':>6}  {'Avg':>5} {'Min':>5} {'Max':>5}")
                print(f"  {'-'*20} {'-'*6} {'-'*6}  {'-'*5} {'-'*5} {'-'*5}")
                for row in categories:
                    pct = 100.0 * row['count'] / total
                    print(f"  {row['category']:<20} {row['count']:>6} {pct:>5.1f}%  "
                          f"{row['avg_score']:>5.2f} {row['min_score']:>5.2f} {row['max_score']:>5.2f}")

                # === SCORE DISTRIBUTIONS ===
                print_section("SCORE DISTRIBUTIONS")

                score_cols = ['aggregate', 'aesthetic', 'tech_sharpness', 'exposure_score',
                              'color_score', 'comp_score', 'face_quality', 'eye_sharpness']
                for col in score_cols:
                    try:
                        values = [r[0] for r in conn.execute(
                            f"SELECT {col} FROM photos WHERE {col} IS NOT NULL"
                        ).fetchall() if isinstance(r[0], (int, float))]
                        stats = calc_stats(values)
                        print_stat_row(col, stats, score_range=True)
                    except sqlite3.OperationalError:
                        pass

                # === AGGREGATE SCORE BUCKETS ===
                print_section("AGGREGATE SCORE DISTRIBUTION")
                buckets = conn.execute("""
                    SELECT
                        CASE
                            WHEN aggregate < 3 THEN '0-3 (Poor)'
                            WHEN aggregate < 5 THEN '3-5 (Below Avg)'
                            WHEN aggregate < 6 THEN '5-6 (Average)'
                            WHEN aggregate < 7 THEN '6-7 (Good)'
                            WHEN aggregate < 8 THEN '7-8 (Very Good)'
                            WHEN aggregate < 9 THEN '8-9 (Excellent)'
                            ELSE '9-10 (Outstanding)'
                        END as bucket,
                        COUNT(*) as count
                    FROM photos
                    GROUP BY 1
                    ORDER BY 1
                """).fetchall()

                max_count = max(r['count'] for r in buckets) if buckets else 1
                print(f"  {'Range':<18} {'Count':>6} {'%':>6}  Bar")
                print(f"  {'-'*18} {'-'*6} {'-'*6}  {'-'*30}")
                for row in buckets:
                    pct = 100.0 * row['count'] / total
                    bar_len = int(30 * row['count'] / max_count)
                    bar = '█' * bar_len
                    print(f"  {row['bucket']:<18} {row['count']:>6} {pct:>5.1f}%  {bar}")

                # === RAW METRICS (for normalization tuning) ===
                print_section("RAW METRICS (for percentile normalization)")
                raw_cols = ['raw_sharpness_variance', 'raw_color_entropy', 'raw_eye_sharpness',
                            'histogram_spread', 'mean_luminance', 'noise_sigma', 'contrast_score']
                for col in raw_cols:
                    try:
                        values = [r[0] for r in conn.execute(
                            f"SELECT {col} FROM photos WHERE {col} IS NOT NULL"
                        ).fetchall() if isinstance(r[0], (int, float))]
                        stats = calc_stats(values)
                        if stats:
                            print(f"  {col:25} p90={stats['p90']:8.3f}  p95={stats['p95']:8.3f}  "
                                  f"max={stats['max']:8.3f}")
                    except sqlite3.OperationalError:
                        pass

                # === PER-CATEGORY SCORE DISTRIBUTIONS ===
                # Check if category column exists
                cursor = conn.execute("PRAGMA table_info(photos)")
                columns = [col[1] for col in cursor.fetchall()]
                if 'category' in columns:
                    print_section("CATEGORY DETAILS (Face-Ratio Based)")
                    print("  Categories determined by face_ratio, face_count, is_monochrome:\n")
                    min_samples = 50  # Threshold for reliable statistics

                    cat_scores = conn.execute("""
                    SELECT
                        category,
                        COUNT(*) as count,
                        ROUND(AVG(aggregate), 2) as avg_agg,
                        ROUND(AVG(aesthetic), 2) as avg_aes,
                        ROUND(AVG(comp_score), 2) as avg_comp,
                        ROUND(MIN(aggregate), 2) as min_val,
                        ROUND(MAX(aggregate), 2) as max_val
                    FROM photos
                    WHERE category IS NOT NULL AND aggregate IS NOT NULL
                    GROUP BY category
                    ORDER BY count DESC
                """).fetchall()

                if cat_scores:
                    # Header with aesthetic and comp_score columns
                    print(f"  {'Category':<16} {'Count':>6} {'':>3}  {'Avg Agg':>7} {'Avg Aes':>7} {'Avg Comp':>8} {'p90':>6}")
                    print(f"  {'-'*16} {'-'*6} {'-'*3}  {'-'*7} {'-'*7} {'-'*8} {'-'*6}")
                    for row in cat_scores:
                        cat = row[0]
                        count = row[1]
                        avg_aes = row[3] or 0
                        avg_comp = row[4] or 0
                        status = "✓" if count >= min_samples else "✗"

                        cat_values = [r[0] for r in conn.execute(
                            "SELECT aggregate FROM photos WHERE category = ? AND aggregate IS NOT NULL",
                            (cat,)
                        ).fetchall() if isinstance(r[0], (int, float))]
                        cat_stats = calc_stats(cat_values) if cat_values else None
                        if cat_stats:
                            print(f"  {cat:<16} {count:>6} {status:>3}  "
                                  f"{cat_stats['avg']:>7.2f} {avg_aes:>7.2f} {avg_comp:>8.2f} {cat_stats['p90']:>6.2f}")

                # === PER-CATEGORY PERCENTILES (p90 for normalization) ===
                norm_settings = config.get_normalization_settings() if config else {}
                if norm_settings.get('per_category', False):
                    print_section("PER-CATEGORY PERCENTILES (p90 for normalization)")
                    min_samples = norm_settings.get('category_min_samples', 50)

                    # Get categories with enough samples
                    cat_list = conn.execute(f"""
                        SELECT category, COUNT(*) as cnt FROM photos
                        WHERE category IS NOT NULL
                        GROUP BY category
                        HAVING cnt >= {min_samples}
                        ORDER BY cnt DESC
                    """).fetchall()

                    if cat_list:
                        # Metrics to show per-category
                        norm_metrics = ['raw_sharpness_variance', 'raw_color_entropy', 'histogram_spread']

                        # Build header
                        cat_names = [r[0] for r in cat_list[:6]]  # Limit to 6 categories for display
                        header = f"  {'Metric':<22}"
                        for cat in cat_names:
                            header += f" {cat[:10]:>10}"
                        print(header)
                        print(f"  {'-'*22}" + (' ' + '-'*10) * len(cat_names))

                        for metric in norm_metrics:
                            row_str = f"  {metric:<22}"
                            for cat in cat_names:
                                try:
                                    values = [r[0] for r in conn.execute(f"""
                                        SELECT {metric} FROM photos
                                        WHERE category = ? AND {metric} IS NOT NULL
                                    """, (cat,)).fetchall() if isinstance(r[0], (int, float))]
                                    if values:
                                        stats = calc_stats(values)
                                        row_str += f" {stats['p90']:>10.2f}"
                                    else:
                                        row_str += f" {'N/A':>10}"
                                except sqlite3.OperationalError:
                                    row_str += f" {'N/A':>10}"
                            print(row_str)
                    else:
                        print(f"  No categories with >= {min_samples} samples found.")
                        print(f"  Run --recalculate to populate category column.")

                # === TAG-BASED CATEGORY STATISTICS ===
                print_section("TAG-BASED CATEGORY STATISTICS")
                print("  Categories determined by CLIP semantic tags:\n")

                # Get all weight categories with tags defined from config
                tag_category_tags = {}
                if config:
                    for cat in config.config.get('categories', []):
                        cat_name = cat.get('name')
                        cat_tags = cat.get('tags', {})
                        if cat_name and cat_tags and isinstance(cat_tags, dict):
                            tag_category_tags[cat_name] = cat_tags
                tag_categories = list(tag_category_tags.keys())
                min_samples = 50

                category_stats = []
                for cat in tag_categories:
                    cat_tags = list(tag_category_tags.get(cat, {}).keys())
                    if not cat_tags:
                        continue

                    like_conditions = " OR ".join(
                        f"(',' || tags || ',' LIKE '%,{tag},%')" for tag in cat_tags
                    )

                    try:
                        row = conn.execute(f"""
                            SELECT
                                COUNT(*) as count,
                                ROUND(AVG(aggregate), 2) as avg_agg,
                                ROUND(AVG(aesthetic), 2) as avg_aes,
                                ROUND(AVG(comp_score), 2) as avg_comp
                            FROM photos
                            WHERE tags IS NOT NULL AND ({like_conditions})
                        """).fetchone()

                        if row and row[0] > 0:
                            category_stats.append({
                                'category': cat,
                                'count': row[0],
                                'avg_agg': row[1] or 0,
                                'avg_aes': row[2] or 0,
                                'avg_comp': row[3] or 0,
                                'sufficient': row[0] >= min_samples
                            })
                    except sqlite3.OperationalError:
                        pass

                category_stats.sort(key=lambda x: x['count'], reverse=True)

                if category_stats:
                    print(f"  {'Category':<16} {'Count':>6} {'Status':>3}  {'Avg Agg':>7} {'Avg Aes':>7} {'Avg Comp':>8}")
                    print(f"  {'-'*16} {'-'*6} {'-'*3}  {'-'*7} {'-'*7} {'-'*8}")
                    for stat in category_stats:
                        status = "✓" if stat['sufficient'] else "✗"
                        print(f"  {stat['category']:<16} {stat['count']:>6} {status:>3}  "
                              f"{stat['avg_agg']:>7.2f} {stat['avg_aes']:>7.2f} {stat['avg_comp']:>8.2f}")
                else:
                    print("  No tag-based categories found. Run tagging first.")

                # === FACE ANALYSIS ===
                print_section("FACE ANALYSIS")
                face_stats = conn.execute("""
                    SELECT
                        SUM(CASE WHEN face_count = 0 THEN 1 ELSE 0 END) as no_faces,
                        SUM(CASE WHEN face_count = 1 THEN 1 ELSE 0 END) as single_face,
                        SUM(CASE WHEN face_count > 1 THEN 1 ELSE 0 END) as multi_face,
                        SUM(CASE WHEN is_blink = 1 THEN 1 ELSE 0 END) as blinks,
                        AVG(CASE WHEN face_count > 0 THEN face_ratio ELSE NULL END) as avg_face_ratio
                    FROM photos
                """).fetchone()
                print(f"  No faces: {face_stats['no_faces']} ({100*face_stats['no_faces']/total:.1f}%)")
                print(f"  Single face: {face_stats['single_face']} ({100*face_stats['single_face']/total:.1f}%)")
                print(f"  Multiple faces: {face_stats['multi_face']} ({100*face_stats['multi_face']/total:.1f}%)")
                print(f"  Detected blinks: {face_stats['blinks'] or 0}")
                if face_stats['avg_face_ratio']:
                    print(f"  Avg face ratio (when present): {face_stats['avg_face_ratio']*100:.1f}%")

                # === TECHNICAL ISSUES ===
                print_section("TECHNICAL ISSUES")
                print(f"  Shadow clipped: {issues['shadow_clipped'] or 0} ({tech_issues['shadow']:.1f}%)")
                print(f"  Highlight clipped: {issues['highlight_clipped'] or 0} ({tech_issues['highlight']:.1f}%)")
                print(f"  High noise (σ>4): {issues['noisy'] or 0} ({tech_issues['noisy']:.1f}%)")
                print(f"  Soft images (<4): {issues['soft'] or 0} ({tech_issues['soft']:.1f}%)")

                # === CORRELATION ANALYSIS ===
                print_section("SCORE CORRELATIONS WITH AGGREGATE")
                corr_cols = ['aesthetic', 'tech_sharpness', 'exposure_score', 'color_score',
                             'comp_score', 'face_quality', 'eye_sharpness']
                correlations = []
                for col in corr_cols:
                    try:
                        rows = conn.execute(f"""
                            SELECT {col}, aggregate FROM photos
                            WHERE {col} IS NOT NULL AND aggregate IS NOT NULL
                        """).fetchall()
                        if len(rows) > 10:
                            x = [r[0] for r in rows if isinstance(r[0], (int, float))]
                            y = [r[1] for r in rows if isinstance(r[0], (int, float))]
                            if len(x) == len(y) and len(x) > 10:
                                x_mean, y_mean = sum(x)/len(x), sum(y)/len(y)
                                numerator = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, y))
                                denom_x = math.sqrt(sum((xi - x_mean)**2 for xi in x))
                                denom_y = math.sqrt(sum((yi - y_mean)**2 for yi in y))
                                if denom_x > 0 and denom_y > 0:
                                    corr = numerator / (denom_x * denom_y)
                                    correlations.append((col, corr))
                    except (sqlite3.OperationalError, ZeroDivisionError):
                        pass

                correlations.sort(key=lambda x: abs(x[1]), reverse=True)
                for col, corr in correlations:
                    bar_len = int(20 * abs(corr))
                    bar = '█' * bar_len
                    sign = '+' if corr >= 0 else '-'
                    print(f"  {col:20} {sign}{abs(corr):.3f}  {bar}")

                # === CURRENT CONFIG WEIGHTS ===
                if config:
                    print_section("CURRENT CONFIG WEIGHTS")

                    category_groups = {
                        'People': ['portrait', 'portrait_bw', 'group_portrait', 'silhouette'],
                        'Default': ['default'],
                        'Specialized': ['wildlife', 'architecture', 'food', 'macro', 'street'],
                        'Low Light': ['night', 'astro', 'concert'],
                        'Motion/Aerial': ['long_exposure', 'aerial'],
                        'Other': ['art'],
                    }

                    for group_name, categories_list in category_groups.items():
                        print(f"\n  === {group_name} ===")
                        for category in categories_list:
                            weights = config.get_weights(category)
                            if weights:
                                weight_parts = []
                                for key, val in sorted(weights.items()):
                                    if key == 'bonus':
                                        continue
                                    elif isinstance(val, dict):
                                        continue
                                    elif key.endswith('_multiplier'):
                                        weight_parts.append(f"{key.replace('_multiplier','')}×{val}")
                                    else:
                                        weight_parts.append(f"{key}={val*100:.0f}%")
                                bonus_str = f" +{weights['bonus']:.1f}" if 'bonus' in weights else ""
                                print(f"    {category:16} {', '.join(weight_parts)}{bonus_str}")

                # === DETAILED RECOMMENDATIONS (verbose mode) ===
                if scoring_issues:
                    print_section("RECOMMENDATION DETAILS")
                    print("  Analysis based on raw values in DB. Proposals only affect")
                    print("  aggregate score calculation, not stored raw metrics.\n")

                    for i, issue in enumerate(scoring_issues, 1):
                        issue_icons = {
                            'compressed_range': '📊',
                            'underutilized_signal': '📈',
                            'dominant_correlation': '⚖️',
                            'category_imbalance': '🎯',
                            'low_correlation_high_weight': '📉',
                            'collinearity': '🔗',
                            'skewed_distribution': '📐',
                            'score_ceiling': '🔝',
                            'floor_clustering': '🔻',
                            'score_outliers': '🔍',
                            'metric_disagreement': '⚡',
                            'missing_data': '❓',
                            'normalization_compressed': '📏',
                            'config_version_drift': '🔄',
                        }
                        icon = issue_icons.get(issue['issue_type'], '•')
                        confidence = issue.get('confidence', 'unknown')
                        priority = issue.get('priority', 0)

                        print(f"  {i}. {icon} {issue['description']}")
                        explanation = issue.get('explanation', '')
                        if explanation:
                            import textwrap
                            wrapped = textwrap.fill(explanation, width=72, initial_indent='     ', subsequent_indent='     ')
                            print(wrapped)
                        print(f"     Impact: {issue['estimated_impact']}  [confidence: {confidence}, priority: {priority}]")
                        print(f"     Proposals:")
                        for proposal in issue['proposals']:
                            print(f"       -> {proposal['location']}")
                            print(f"         {proposal['change']}")
                            if 'offset_from' in proposal:
                                print(f"         (offset from {proposal['offset_from']})")
                            if 'offset_to' in proposal:
                                print(f"         (offset to {proposal['offset_to']})")
                            if 'reason' in proposal:
                                print(f"         Reason: {proposal['reason']}")
                        print()

            # === FOOTER ===
            print()
            print("-"*60)
            if not verbose:
                print("  Use --verbose for detailed statistics")
            if scoring_issues and not return_recommendations:
                print("  Use --apply-recommendations to auto-apply fixes")
            print("="*60)

            if return_recommendations:
                return scoring_issues

        return [] if return_recommendations else None

    def simulate_recommendations(self, recommendations, scorer, conn_factory=None):
        """Preview projected score changes without modifying config.

        Samples photos and shows what aggregate scores would look like
        with the proposed changes applied.
        """
        if not recommendations:
            print("\nNo recommendations to simulate.")
            return

        print("\n" + "=" * 60)
        print(" RECOMMENDATION SIMULATION (dry-run)")
        print("=" * 60)

        applicable = [r for r in recommendations if r.get('issue_type') not in self._INFORMATIONAL_ISSUE_TYPES]
        informational = [r for r in recommendations if r.get('issue_type') in self._INFORMATIONAL_ISSUE_TYPES]

        if informational:
            print(f"\n  {len(informational)} informational issue(s) — cannot simulate:")
            for r in informational:
                print(f"    - {r['issue_type']}: {r['description']}")

        if not applicable:
            print("\n  No auto-applicable recommendations to simulate.")
            return

        print(f"\n  Simulating {len(applicable)} applicable recommendation(s):\n")
        for i, rec in enumerate(applicable, 1):
            print(f"  {i}. [{rec.get('issue_type')}] {rec['description']}")
            print(f"     Estimated impact: {rec['estimated_impact']}")

        # Show aggregate stats before/after for sample
        if conn_factory:
            with conn_factory(self.db_path) as conn:
                sample = conn.execute("""
                    SELECT AVG(aggregate), MIN(aggregate), MAX(aggregate),
                           COUNT(*) FROM photos WHERE aggregate IS NOT NULL
                """).fetchone()
                if sample and sample[3] > 0:
                    print(f"\n  Current aggregate: avg={sample[0]:.2f}, "
                          f"range=[{sample[1]:.2f}-{sample[2]:.2f}], n={sample[3]}")

                    # Estimate impact from bonus changes
                    total_bonus_impact = 0
                    bonus_details = []
                    for rec in applicable:
                        if rec.get('issue_type') == 'category_imbalance':
                            for p in rec.get('proposals', []):
                                change = p.get('change', '')
                                if '->' in change:
                                    try:
                                        old_val = float(change.split('->')[0].strip())
                                        new_val = float(change.split('->')[1].strip())
                                        delta = new_val - old_val
                                        if delta != 0:
                                            loc = p.get('location', '')
                                            cat = loc.split('.')[-2] if '.' in loc else '?'
                                            bonus_details.append(f"{cat}: +{delta:.1f}")
                                            total_bonus_impact += delta
                                    except (ValueError, IndexError):
                                        pass

                    if bonus_details:
                        print(f"\n  Projected bonus changes: {', '.join(bonus_details)}")
                        print(f"  (Actual impact depends on category distribution)")

        # Validate proposed changes and show warnings
        self._simulate_validation_check(applicable, scorer.config if scorer else None)

        print("\n  To apply these changes: --compute-recommendations --apply-recommendations")
        print("=" * 60)

    def _simulate_validation_check(self, applicable, config):
        """Check for potential issues in recommendations before applying."""
        if not config:
            return

        # Collect pending weight changes per category
        category_changes = {}  # cat -> {key: new_val}
        invalid_categories = []

        categories_list = config.config.get('categories', [])
        valid_categories = {cat.get('name') for cat in categories_list}

        for rec in applicable:
            for p in rec.get('proposals', []):
                location = p.get('location', '')
                change = p.get('change', '')

                if '->' not in location or '->' not in change:
                    continue

                _, path = location.split('->', 1)
                path = path.strip()
                parts = path.split('.')

                if len(parts) >= 3 and parts[0] == 'weights' and '_percent' in parts[2]:
                    cat = parts[1]
                    key = parts[2]

                    # Check if category exists
                    if cat not in valid_categories:
                        invalid_categories.append(cat)
                        continue

                    if cat not in category_changes:
                        category_changes[cat] = {}

                    try:
                        new_val = int(change.split('->')[1].strip().replace('%', ''))
                        category_changes[cat][key] = new_val
                    except (ValueError, IndexError):
                        pass

        # Report invalid categories
        if invalid_categories:
            print(f"\n  WARNING: Recommendations target non-existent categories:")
            for cat in set(invalid_categories):
                print(f"    - '{cat}' not found in config")

        # Check weight balance per category
        has_balance_issues = False
        for cat_name, changes in category_changes.items():
            # Get current weights for this category
            for cat in categories_list:
                if cat.get('name') == cat_name:
                    current_weights = cat.get('weights', {}).copy()
                    # Apply pending changes
                    current_weights.update(changes)
                    # Sum all _percent weights
                    total = sum(v for k, v in current_weights.items()
                               if '_percent' in k and isinstance(v, (int, float)))
                    if total > 0 and abs(total - 100) > 10:
                        if not has_balance_issues:
                            print(f"\n  Note: Weight totals != 100% (auto-normalized at runtime):")
                            has_balance_issues = True
                        print(f"    - {cat_name}: {total}%")
                    break

    # Issue types that are informational only (cannot be auto-applied to config)
    _INFORMATIONAL_ISSUE_TYPES = frozenset({
        'collinearity', 'skewed_distribution',
        'score_ceiling', 'score_outliers',
        'missing_data', 'normalization_compressed',
        'config_version_drift',
    })

    def _validate_recommendations(self, pending_changes, categories_list, valid_categories):
        """Validate recommendations before applying.

        Returns list of error messages, empty if valid.
        """
        errors = []

        # Build lookup of current weights per category
        cat_weights = {}
        for cat in categories_list:
            name = cat.get('name')
            if name:
                cat_weights[name] = cat.get('weights', {}).copy()

        # 1. Check all target categories exist
        for (category, key), (value, source) in pending_changes.items():
            if category not in valid_categories and category != '_models':
                errors.append(f"Category '{category}' does not exist in config (from {source})")

        # 2. Check weight changes won't create invalid totals
        # Apply pending changes to a copy and check totals
        for (category, key), (value, source) in pending_changes.items():
            if category in cat_weights and '_percent' in key:
                cat_weights[category][key] = value

        # Note: Weight totals != 100% are allowed because get_weights() normalizes
        # them at runtime. We only warn about very large deviations during display.

        # 3. Check no changes would zero out critical weights
        for (category, key), (value, source) in pending_changes.items():
            if value == 0 and key in ('aesthetic_percent', 'composition_percent'):
                errors.append(f"Would zero out {key} in {category} (from {source})")

        return errors

    def apply_recommendations(self, recommendations, config):
        """Apply scoring recommendations to the config file.

        Collects all proposed changes, deduplicates (when multiple issues target
        the same key, takes the lowest/most aggressive value), then writes once.
        Supports v4 category-centric config format (categories[].weights).

        Args:
            recommendations: List of recommendation dicts from _analyze_scoring_issues
            config: ScoringConfig instance

        Returns:
            Path to backup file if created, None otherwise
        """
        import json
        import shutil
        from datetime import datetime

        if not recommendations:
            print("No recommendations to apply.")
            return None

        # Filter to only auto-applicable recommendations
        applicable = [r for r in recommendations if r.get('issue_type') not in self._INFORMATIONAL_ISSUE_TYPES]
        informational = [r for r in recommendations if r.get('issue_type') in self._INFORMATIONAL_ISSUE_TYPES]

        if informational:
            print(f"  Skipping {len(informational)} informational recommendation(s) (manual review needed):")
            for r in informational:
                print(f"    - {r['issue_type']}: {r['description']}")

        if not applicable:
            print("No auto-applicable recommendations.")
            return None

        config_path = config.config_path

        # Create backup
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = f"{config_path}.backup.{timestamp}"
        shutil.copy2(config_path, backup_path)
        print(f"  Backup created: {backup_path}")

        # Load current config
        with open(config_path, 'r') as f:
            config_data = json.load(f)

        # Phase 1: Collect all proposed changes into a dedup map
        # Key: (category, weight_key) -> lowest proposed value (most aggressive reduction)
        # Special keys: ('_models', 'aesthetic_scale') -> value
        #               (category, '_bonus') -> value
        pending_changes = {}  # (section, key) -> (value, source_issue)

        for rec in applicable:
            issue_type = rec.get('issue_type')
            proposals = rec.get('proposals', [])

            for proposal in proposals:
                location = proposal.get('location', '')
                change = proposal.get('change', '')

                if '->' not in location:
                    continue

                _, path = location.split('->', 1)
                path = path.strip()
                parts = path.split('.')

                try:
                    if issue_type == 'compressed_range' and 'aesthetic_scale' in path:
                        if ':' in change:
                            value = float(change.split(':')[1].strip())
                            key = ('_models', 'aesthetic_scale')
                            if key not in pending_changes or value > pending_changes[key][0]:
                                pending_changes[key] = (value, issue_type)

                    elif issue_type == 'category_imbalance' and 'bonus' in path:
                        if len(parts) >= 3 and parts[0] == 'weights' and '->' in change:
                            category = parts[1]
                            new_val = float(change.split('->')[1].strip())
                            key = (category, '_bonus')
                            if key not in pending_changes or new_val > pending_changes[key][0]:
                                pending_changes[key] = (new_val, issue_type)

                    elif issue_type in ('underutilized_signal', 'dominant_correlation',
                                        'floor_clustering', 'low_correlation_high_weight',
                                        'metric_disagreement'):
                        if len(parts) >= 3 and parts[0] == 'weights' and '_percent' in parts[2]:
                            category = parts[1]
                            weight_key = parts[2]
                            if '->' in change:
                                new_val_str = change.split('->')[1].strip()
                                new_val = max(0, int(new_val_str.replace('%', '')))
                                key = (category, weight_key)
                                # Take the lowest value (most aggressive reduction)
                                if key not in pending_changes or new_val < pending_changes[key][0]:
                                    pending_changes[key] = (new_val, issue_type)

                            # Also collect offset changes
                            for offset_key_name in ('offset_from', 'offset_to'):
                                offset = proposal.get(offset_key_name, '')
                                if offset and '->' in offset:
                                    try:
                                        o_key = offset.split('(')[0].strip()
                                        o_change = offset.split('(')[1].replace(')', '')
                                        if '->' in o_change:
                                            o_new = int(o_change.split('->')[1].strip().replace('%', ''))
                                            okey = (category, o_key)
                                            if okey not in pending_changes or o_new < pending_changes[okey][0]:
                                                pending_changes[okey] = (o_new, issue_type)
                                    except (IndexError, ValueError):
                                        pass

                except (ValueError, KeyError, IndexError) as e:
                    print(f"  Warning: Could not parse {location}: {e}")
                    continue

        if not pending_changes:
            print("  No concrete changes could be parsed from recommendations.")
            return None

        # Phase 2: Validate proposed changes before applying
        categories_list = config_data.get('categories', [])
        cat_index = {cat.get('name'): i for i, cat in enumerate(categories_list)}
        valid_categories = set(cat_index.keys())

        validation_errors = self._validate_recommendations(pending_changes, categories_list, valid_categories)
        if validation_errors:
            print("\n  Validation errors found:")
            for err in validation_errors:
                print(f"    - {err}")
            print("\n  Fix the issues above before applying recommendations.")
            return None

        # Phase 3: Apply collected changes (deduplicated)

        applied_count = 0
        for (section, key), (value, source) in sorted(pending_changes.items()):
            if key == '_bonus':
                # Write bonus to category modifiers (v4) or weights (v3)
                if section in cat_index:
                    idx = cat_index[section]
                    if 'modifiers' not in categories_list[idx]:
                        categories_list[idx]['modifiers'] = {}
                    categories_list[idx]['modifiers']['bonus'] = value
                    print(f"  Applied: categories[{section}].modifiers.bonus = {value}  [{source}]")
                    applied_count += 1
            elif '_percent' in key:
                # Write weight to category weights (v4 format)
                if section in cat_index:
                    idx = cat_index[section]
                    if 'weights' not in categories_list[idx]:
                        categories_list[idx]['weights'] = {}
                    old_val = categories_list[idx]['weights'].get(key)
                    categories_list[idx]['weights'][key] = value
                    old_str = f" (was {old_val})" if old_val is not None else ""
                    print(f"  Applied: categories[{section}].weights.{key} = {value}{old_str}  [{source}]")
                    applied_count += 1
                else:
                    print(f"  Warning: category '{section}' not found in config, skipping {key}={value}")

        # Save updated config
        with open(config_path, 'w') as f:
            json.dump(config_data, f, indent=2)

        # Record applied recommendations to history table
        if applied_count > 0:
            try:
                with get_connection(self.db_path) as conn:
                    self._record_recommendations_to_history(
                        conn, applicable, config.version_hash, applied=True
                    )
                    conn.commit()
            except Exception as e:
                print(f"  Warning: Could not record to history: {e}")

        print(f"\n  Applied {applied_count} deduplicated change(s) to {config_path}")
        return backup_path if applied_count > 0 else None


def recalculate_batch_settings(metrics, current_settings):
    """Adjust batch settings based on observed performance metrics.

    Uses actual measured bandwidth and file sizes to dynamically tune:
    - num_workers: Number of prefetch worker threads
    - batch_size: GPU batch size
    - prefetch_queue_multiplier: Queue depth

    Args:
        metrics: Dict with observed metrics from BatchProcessor:
            - elapsed_time: Total processing time
            - images_processed: Number of images processed
            - total_load_time: Sum of all load times
            - total_bytes_loaded: Total bytes read
            - queue_timeouts: Number of queue starvation events
        current_settings: Dict with current batch settings

    Returns:
        Updated settings dict with tuned parameters and observed metrics
    """
    elapsed = metrics.get('elapsed_time', 0)
    if elapsed <= 0 or metrics.get('images_processed', 0) == 0:
        return current_settings

    images_processed = metrics['images_processed']
    total_load_time = metrics.get('total_load_time', 0)
    total_bytes = metrics.get('total_bytes_loaded', 0)

    # Calculate observed values
    if total_load_time > 0 and total_bytes > 0:
        observed_avg_size_mb = (total_bytes / images_processed) / (1024 * 1024)
        observed_bandwidth_mbs = (total_bytes / total_load_time) / (1024 * 1024)
        images_per_second = observed_bandwidth_mbs / max(observed_avg_size_mb, 0.1)
    else:
        # Fallback if no load time data
        images_per_second = images_processed / elapsed
        observed_avg_size_mb = 10.0  # Assume 10MB average
        observed_bandwidth_mbs = images_per_second * observed_avg_size_mb

    gpu_throughput = 6.5  # Approximate batched GPU throughput (images/sec)

    # Get tuning bounds from config
    tuning = current_settings.get('auto_tuning', {})
    min_workers = tuning.get('min_processing_workers', 4)
    max_workers = tuning.get('max_processing_workers', 12)
    min_batch = tuning.get('min_gpu_batch_size', 8)
    max_batch = tuning.get('max_gpu_batch_size', 32)

    queue_timeouts = metrics.get('queue_timeouts', 0)

    if images_per_second < gpu_throughput:
        # I/O bottleneck - increase parallelism, smaller batches (process what's available)
        new_workers = max(min_workers, min(max_workers, int(8 / images_per_second) + 2))
        new_prefetch = max(3, min(6, int(gpu_throughput / images_per_second) + 1))
        new_batch_size = max(min_batch, min(16, int(images_per_second * 2)))
    else:
        # GPU bottleneck - fewer workers, larger batches
        new_workers = min_workers
        new_prefetch = 2
        new_batch_size = max_batch

    # Additional adjustment based on queue health
    if queue_timeouts > 5:
        new_workers = min(new_workers + 2, max_workers)
        new_batch_size = max(min_batch, new_batch_size - 4)  # Smaller batches if starving

    return {
        **current_settings,
        'num_workers': new_workers,
        'prefetch_queue_multiplier': new_prefetch,
        'batch_size': new_batch_size,
        # Observed metrics for display
        '_observed_bandwidth_mbs': round(observed_bandwidth_mbs, 1),
        '_observed_avg_size_mb': round(observed_avg_size_mb, 1),
        '_images_per_second': round(images_per_second, 1),
    }
