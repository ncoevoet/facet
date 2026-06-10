"""
Data-mining report over the scored library.

Complements the recommendations engine (config/percentile_normalizer.py),
which already covers weight/collinearity/distribution analyzers - this module
adds the label-centric and freshness views: what ground-truth signal exists,
how metrics relate to user labels, how categories are populated, and how far
stored scores have drifted from current percentiles.
"""

import logging

import numpy as np

from db import get_connection

logger = logging.getLogger("facet.insights")

# Need at least this many positive labels before correlations mean anything
MIN_POSITIVE_LABELS = 50

METRIC_COLUMNS = [
    'aggregate', 'aesthetic', 'quality_score', 'comp_score', 'face_quality',
    'eye_sharpness', 'tech_sharpness', 'exposure_score', 'color_score',
    'contrast_score', 'aesthetic_iaa', 'liqe_score',
    'subject_sharpness', 'subject_prominence', 'subject_placement', 'bg_separation',
]


def _roc_auc(scores, labels):
    """Mann-Whitney AUC of scores against binary labels (no sklearn needed)."""
    scores = np.asarray(scores, dtype=float)
    labels = np.asarray(labels, dtype=bool)
    pos = scores[labels]
    neg = scores[~labels]
    if len(pos) == 0 or len(neg) == 0:
        return None
    order = np.argsort(np.concatenate([pos, neg]))
    ranks = np.empty(len(order), dtype=float)
    ranks[order] = np.arange(1, len(order) + 1)
    rank_sum_pos = ranks[:len(pos)].sum()
    auc = (rank_sum_pos - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))
    return float(auc)


def _point_biserial(scores, labels):
    """Pearson correlation between a metric and a binary label."""
    scores = np.asarray(scores, dtype=float)
    labels = np.asarray(labels, dtype=float)
    if scores.std() < 1e-9 or labels.std() < 1e-9:
        return None
    return float(np.corrcoef(scores, labels)[0, 1])


class InsightsMiner:
    """Read-only analysis over photos, comparisons, and label columns."""

    def __init__(self, db_path):
        self.db_path = db_path

    def label_inventory(self, conn):
        """Counts of every ground-truth signal available for learning."""
        def _one(sql, params=()):
            return conn.execute(sql, params).fetchone()[0]

        star_hist = dict(conn.execute(
            "SELECT star_rating, COUNT(*) FROM photos "
            "WHERE COALESCE(star_rating, 0) > 0 GROUP BY star_rating"
        ).fetchall())
        comparisons_by_source = dict(conn.execute(
            "SELECT COALESCE(source, 'vote'), COUNT(*) FROM comparisons GROUP BY 1"
        ).fetchall())
        burst_total = _one(
            "SELECT COUNT(DISTINCT burst_group_id) FROM photos WHERE burst_group_id IS NOT NULL")
        try:
            burst_reviewed = _one(
                "SELECT COUNT(DISTINCT burst_group_id) FROM photos "
                "WHERE burst_group_id IS NOT NULL AND burst_reviewed = 1")
        except Exception:
            burst_reviewed = 0
        user_pref_users = dict(conn.execute(
            "SELECT user_id, COUNT(*) FROM user_preferences GROUP BY user_id"
        ).fetchall())

        return {
            'total_photos': _one("SELECT COUNT(*) FROM photos"),
            'favorites': _one("SELECT COUNT(*) FROM photos WHERE is_favorite = 1"),
            'rejected': _one("SELECT COUNT(*) FROM photos WHERE is_rejected = 1"),
            'star_rating_histogram': star_hist,
            'comparisons_by_source': comparisons_by_source,
            'burst_groups_total': burst_total,
            'burst_groups_reviewed': burst_reviewed,
            'user_preferences_per_user': user_pref_users,
        }

    def metric_label_correlations(self, conn):
        """Point-biserial r and ROC-AUC of every metric against each label.

        Labels: is_favorite, is_rejected, star>=4. Skipped with an explicit
        reason when a label has fewer than MIN_POSITIVE_LABELS positives.
        """
        rows = conn.execute(f"""
            SELECT {', '.join(METRIC_COLUMNS)},
                   COALESCE(is_favorite, 0) AS lbl_favorite,
                   COALESCE(is_rejected, 0) AS lbl_rejected,
                   CASE WHEN COALESCE(star_rating, 0) >= 4 THEN 1 ELSE 0 END AS lbl_star4
            FROM photos WHERE aggregate IS NOT NULL
        """).fetchall()
        if not rows:
            return {'error': 'no scored photos'}

        data = np.array([
            [float(row[c] if row[c] is not None else np.nan) for c in METRIC_COLUMNS]
            for row in rows
        ])
        labels = {
            'is_favorite': np.array([row['lbl_favorite'] for row in rows], dtype=bool),
            'is_rejected': np.array([row['lbl_rejected'] for row in rows], dtype=bool),
            'star_gte_4': np.array([row['lbl_star4'] for row in rows], dtype=bool),
        }

        result = {}
        for label_name, label_vec in labels.items():
            positives = int(label_vec.sum())
            if positives < MIN_POSITIVE_LABELS:
                result[label_name] = {
                    'skipped': f'insufficient labels ({positives} positives, '
                               f'need >= {MIN_POSITIVE_LABELS})',
                    'positives': positives,
                }
                continue
            per_metric = {}
            for j, metric in enumerate(METRIC_COLUMNS):
                col = data[:, j]
                valid = ~np.isnan(col)
                if valid.sum() < MIN_POSITIVE_LABELS:
                    continue
                per_metric[metric] = {
                    'r': _point_biserial(col[valid], label_vec[valid]),
                    'auc': _roc_auc(col[valid], label_vec[valid]),
                }
            ranked = sorted(
                ((m, v) for m, v in per_metric.items() if v['auc'] is not None),
                key=lambda x: -abs(x[1]['auc'] - 0.5),
            )
            result[label_name] = {
                'positives': positives,
                'metrics': dict(ranked),
            }
        return result

    def score_distribution_by_category(self, conn):
        """Aggregate percentiles per category, plus the 'others' bucket share."""
        rows = conn.execute("""
            SELECT COALESCE(category, 'others') AS category, aggregate
            FROM photos WHERE aggregate IS NOT NULL
        """).fetchall()
        if not rows:
            return {}
        by_cat = {}
        for row in rows:
            by_cat.setdefault(row['category'], []).append(row['aggregate'])
        total = len(rows)
        result = {}
        for category, values in sorted(by_cat.items(), key=lambda x: -len(x[1])):
            arr = np.array(values)
            result[category] = {
                'count': len(values),
                'share_percent': round(len(values) / total * 100, 1),
                'p25': round(float(np.percentile(arr, 25)), 2),
                'median': round(float(np.median(arr)), 2),
                'p75': round(float(np.percentile(arr, 75)), 2),
                'mean': round(float(arr.mean()), 2),
            }
        return result

    def percentile_drift(self, conn):
        """Fresh percentiles vs the snapshot persisted at last --recompute-average."""
        from config.percentile_normalizer import PercentileNormalizer
        persisted = PercentileNormalizer.load_persisted(conn)
        if not persisted:
            return {'skipped': 'no persisted percentile snapshot - run --recompute-average first'}

        normalizer = PercentileNormalizer(
            self.db_path,
            target_percentile=persisted.get('target_percentile', 95),
        )
        fresh = normalizer.compute_percentiles()
        old = persisted.get('percentiles', {})
        drift = {}
        for metric, fresh_value in fresh.items():
            old_value = old.get(metric)
            if not old_value:
                continue
            pct = abs(fresh_value - old_value) / abs(old_value) * 100
            drift[metric] = {
                'persisted': round(float(old_value), 4),
                'fresh': round(float(fresh_value), 4),
                'drift_percent': round(pct, 1),
                'stale': pct > 10,
            }
        return {
            'snapshot_photo_count': persisted.get('photo_count'),
            'computed_at': persisted.get('computed_at'),
            'metrics': drift,
            'recompute_recommended': any(d['stale'] for d in drift.values()),
        }

    def comparison_health(self, conn):
        """Coverage stats from the comparison manager plus per-source split."""
        from comparison.comparison_manager import ComparisonManager
        manager = ComparisonManager(self.db_path)
        try:
            coverage = manager.get_comparison_coverage()
        except Exception as e:
            coverage = {'error': str(e)}
        by_source = dict(conn.execute(
            "SELECT COALESCE(source, 'vote'), COUNT(*) FROM comparisons GROUP BY 1"
        ).fetchall())
        return {'coverage': coverage, 'by_source': by_source}

    def run(self):
        """Full report dict."""
        with get_connection(self.db_path) as conn:
            return {
                'labels': self.label_inventory(conn),
                'metric_label_correlations': self.metric_label_correlations(conn),
                'categories': self.score_distribution_by_category(conn),
                'percentile_drift': self.percentile_drift(conn),
                'comparison_health': self.comparison_health(conn),
            }


def print_insights_report(report):
    """Human-readable rendering of the report dict."""
    labels = report['labels']
    logger.info("=" * 70)
    logger.info("LIBRARY INSIGHTS")
    logger.info("=" * 70)
    logger.info("Photos: %d | favorites: %d | rejected: %d | star ratings: %s",
                labels['total_photos'], labels['favorites'], labels['rejected'],
                labels['star_rating_histogram'] or 'none')
    logger.info("Comparisons by source: %s", labels['comparisons_by_source'] or 'none')
    logger.info("Burst groups reviewed: %d / %d",
                labels['burst_groups_reviewed'], labels['burst_groups_total'])
    if labels['user_preferences_per_user']:
        logger.info("Per-user preferences: %s", labels['user_preferences_per_user'])

    logger.info("-" * 70)
    logger.info("METRIC <-> LABEL CORRELATIONS")
    for label_name, info in report['metric_label_correlations'].items():
        if 'skipped' in info:
            logger.info("  %s: %s", label_name, info['skipped'])
            continue
        logger.info("  %s (%d positives), top metrics by |AUC-0.5|:",
                    label_name, info['positives'])
        for metric, v in list(info['metrics'].items())[:8]:
            logger.info("    %-22s AUC %.3f  r %+.3f", metric, v['auc'], v['r'] or 0.0)

    logger.info("-" * 70)
    logger.info("CATEGORY DISTRIBUTION (share of library, aggregate quartiles)")
    for category, stats in report['categories'].items():
        logger.info("  %-16s %6d (%4.1f%%)  p25 %.2f  med %.2f  p75 %.2f",
                    category, stats['count'], stats['share_percent'],
                    stats['p25'], stats['median'], stats['p75'])

    logger.info("-" * 70)
    drift = report['percentile_drift']
    if 'skipped' in drift:
        logger.info("PERCENTILE DRIFT: %s", drift['skipped'])
    else:
        logger.info("PERCENTILE DRIFT (vs snapshot of %s photos)",
                    drift.get('snapshot_photo_count'))
        for metric, d in drift['metrics'].items():
            flag = '  << STALE' if d['stale'] else ''
            logger.info("  %-24s %.4f -> %.4f (%.1f%%)%s",
                        metric, d['persisted'], d['fresh'], d['drift_percent'], flag)
        if drift['recompute_recommended']:
            logger.info("  Drift exceeds 10%% - run --recompute-average to re-normalize")

    logger.info("-" * 70)
    health = report['comparison_health']
    logger.info("COMPARISON HEALTH: %s", health['by_source'] or 'no comparisons')
    coverage = health['coverage']
    if 'error' not in coverage:
        logger.info("  total: %s | coverage score: %s | optimization ready: %s",
                    coverage.get('total_comparisons'),
                    coverage.get('coverage_score'),
                    coverage.get('optimization_ready'))
        for rec in coverage.get('recommendations', []):
            logger.info("  hint: %s", rec)
    logger.info("=" * 70)
