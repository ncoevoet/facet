"""
Held-out SRCC evaluation for IQA / aesthetic metrics (Topic 3 step 6).

Measures how well each stored quality metric ranks photos against the library's
own ground-truth labels (star ratings by default), using Spearman rank
correlation (SRCC) — the standard IQA accuracy measure. Read-only over `photos`.

This is how the unsourced "0.93/0.90 SRCC" figures in model_manager can be
replaced with numbers measured on THIS dataset:

    python facet.py --eval-iqa-srcc

The dataset-level benchmark SRCC of the underlying models (e.g. TOPIQ on
KonIQ-10k) is published; this harness reports the SRCC on the user's own taste,
which is what actually matters for ranking their library.
"""

import logging

from db import DEFAULT_DB_PATH, get_connection

logger = logging.getLogger("facet.iqa_eval")

# Stored metric columns worth correlating against the ground-truth label.
DEFAULT_METRICS = [
    'aesthetic', 'topiq_score', 'aesthetic_iaa', 'face_quality_iqa', 'liqe_score',
    'aesthetic_clip', 'qalign_score', 'aesthetic_v25', 'deqa_score', 'aggregate',
]


def spearman_srcc(xs, ys):
    """Spearman rank correlation between two equal-length sequences.

    Returns None when there are fewer than 3 pairs or no variance (undefined).
    Uses scipy when available, else a dependency-free rank-correlation fallback.
    """
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    try:
        from scipy.stats import spearmanr
        rho, _ = spearmanr(xs, ys)
        return None if rho != rho else float(rho)  # NaN guard
    except Exception:
        pass
    # Fallback: Pearson correlation on ranks.
    def _ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        ranks = [0.0] * len(v)
        i = 0
        while i < len(v):
            j = i
            while j + 1 < len(v) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                ranks[order[k]] = avg
            i = j + 1
        return ranks
    rx, ry = _ranks(xs), _ranks(ys)
    n = len(rx)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = sum((a - mx) ** 2 for a in rx) ** 0.5
    dy = sum((b - my) ** 2 for b in ry) ** 0.5
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def evaluate_iqa_srcc(db_path=DEFAULT_DB_PATH, metrics=None, label_col='star_rating'):
    """Compute SRCC of each metric vs the ground-truth label.

    Returns {metric: {'srcc': float|None, 'n': int}} over photos with both the
    label (> 0) and the metric non-NULL. Read-only.
    """
    metrics = metrics or DEFAULT_METRICS
    out = {}
    with get_connection(db_path) as conn:
        existing = {r[1] for r in conn.execute("PRAGMA table_info(photos)")}
        if label_col not in existing:
            return out
        usable = [m for m in metrics if m in existing]
        for metric in usable:
            rows = conn.execute(
                f"SELECT {metric} AS mv, {label_col} AS lv FROM photos "
                f"WHERE {metric} IS NOT NULL AND {label_col} IS NOT NULL AND {label_col} > 0"
            ).fetchall()
            xs = [float(r['mv']) for r in rows]
            ys = [float(r['lv']) for r in rows]
            out[metric] = {'srcc': spearman_srcc(xs, ys), 'n': len(xs)}
    return out


def print_iqa_srcc_report(db_path=DEFAULT_DB_PATH, label_col='star_rating'):
    """Print a per-metric SRCC table against the given label column."""
    results = evaluate_iqa_srcc(db_path, label_col=label_col)
    if not results:
        logger.info("No usable metric/label data for SRCC (label '%s' missing or no rows).", label_col)
        return results
    logger.info("IQA SRCC vs %s (higher = better-aligned ranking):", label_col)
    logger.info("  metric              n      SRCC")
    for metric, r in sorted(results.items(), key=lambda kv: (kv[1]['srcc'] is None, -(kv[1]['srcc'] or -1))):
        srcc = 'n/a' if r['srcc'] is None else f"{r['srcc']:+.3f}"
        logger.info("  %-18s %5d   %s", metric, r['n'], srcc)
    return results
