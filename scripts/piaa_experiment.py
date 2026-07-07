#!/usr/bin/env python
"""Offline validation harness for the PIAA cold-start prior + blend (roadmap 2.5).

Implements the spec's experiment: four conditions over a low-n sweep, held-out
30% test fold, pairwise accuracy (primary) + SROCC vs ordinal labels (secondary),
reported as mean ± std across seeds (the real DB is a single pooled ``user_id
IS NULL`` set, so seeds re-split the same comparisons).

Conditions (per revealed training count n):
  C0  aggregate ordering (the ranker's own baseline comparator)
  C1  current global ranker (`_fit_logistic` on the n revealed pairs)
  C2  prior-only (public-IAA head; n-independent)
  C3  blend (prior + lambda(n)·delta fit on the n revealed pairs)

Ship criterion (evaluated by the reader of the tables, not enforced here):
  n=0:  C2 >= C0;  n<=30:  C3 > C1 and C3 > C2 beyond the across-seed std;
  n=50: C3 >= C1.

Read-only against the DB (opened `mode=ro`, safe on a 15 GB library copy).
Deterministic: fixed seeds, fixed folds per seed. Writes a JSON report next to
the DB and prints the per-condition/per-n tables.

Example::

    venv/bin/python scripts/piaa_experiment.py \
        --db /copy/facet.db --prior pretrained_models/piaa_prior_768.npz --dims 768
"""

import argparse
import json
import os
import sqlite3
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.piaa_prior import PiaaPrior  # noqa: E402
from optimization.personal_ranker import (  # noqa: E402
    _baseline_accuracy, _fit_logistic, _fit_logistic_offset, _lambda_n,
    _pairwise_accuracy, _scaled_feature, build_ranker_dataset,
)
from optimization.weight_optimizer import WeightOptimizer  # noqa: E402
from utils.embedding import bytes_to_normalized_embedding  # noqa: E402

DEFAULT_N_VALUES = [0, 5, 10, 20, 30, 50]
DEFAULT_SEEDS = 5
DEFAULT_SHRINKAGE_K = 10
DEFAULT_C = 1.0
TEST_FRACTION = 0.30
CONDITIONS = ['C0', 'C1', 'C2', 'C3']


def _ro_connection(db_path):
    conn = sqlite3.connect(f"file:{os.path.abspath(db_path)}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _pairwise_sweep(data, n_values, k, C, seed):
    """One seed: 30% held-out test fold, sweep n over the remaining pool."""
    diff, y, weights = data['diff'], data['y'], data['weights']
    agg_a, agg_b, prior_diff = data['agg_a'], data['agg_b'], data['prior_diff']
    n_total = len(y)
    rng = np.random.RandomState(seed)
    idx = rng.permutation(n_total)
    n_test = max(1, int(round(TEST_FRACTION * n_total)))
    test, pool = idx[:n_test], idx[n_test:]

    c0 = _baseline_accuracy(agg_a[test], agg_b[test], y[test])
    c2 = float(((prior_diff[test] > 0) == (y[test] == 1)).mean())

    out = {}
    for n in n_values:
        n = min(n, len(pool))
        train = pool[:n]
        row = {'C0': c0, 'C2': c2, 'n_used': int(n)}
        if n >= 1:
            w = _fit_logistic(diff[train], y[train], weights[train], C)
            row['C1'] = _pairwise_accuracy(w, diff[test], y[test])
            delta = _fit_logistic_offset(diff[train], y[train], weights[train], C, prior_diff[train])
            blend = prior_diff[test] + _lambda_n(n, k) * (diff[test] @ delta)
        else:
            row['C1'] = float('nan')
            blend = prior_diff[test]
        row['C3'] = float(((blend > 0) == (y[test] == 1)).mean())
        out[n] = row
    return out


def _fetch_labeled(conn, optimizer, prior, col_std, emb_dim):
    """Ordinal labels + per-photo condition scores for the secondary SROCC metric.

    Ordinal: rejected=0, else star_rating, favorite=6. Photos with no label are
    excluded. Returns dict of aligned arrays or None when too few labels.
    """
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM photos WHERE clip_embedding IS NOT NULL "
        "AND (COALESCE(star_rating,0) > 0 OR COALESCE(is_favorite,0)=1 "
        "OR COALESCE(is_rejected,0)=1)").fetchall()]
    ordinal, agg, prior_s, feats = [], [], [], []
    for row in rows:
        emb = bytes_to_normalized_embedding(row['clip_embedding'])
        if emb is None or emb.shape[0] != emb_dim:
            continue
        if row.get('is_rejected'):
            label = 0.0
        elif row.get('is_favorite'):
            label = 6.0
        else:
            label = float(row.get('star_rating') or 0)
        ordinal.append(label)
        agg.append(float(row.get('aggregate') or 0.0))
        prior_s.append(prior.mixed_score(emb))
        feats.append(_scaled_feature(row, emb, optimizer, None, col_std))
    if len(ordinal) < 5 or len(set(ordinal)) < 2:
        return None
    return {
        'ordinal': np.asarray(ordinal),
        'agg': np.asarray(agg),
        'prior': np.asarray(prior_s),
        'feats': np.asarray(feats),
    }


def _srocc_block(data, labeled, n_values, k, C, seed):
    """SROCC per condition, model fit on the full training pool for this seed."""
    from scipy.stats import spearmanr

    diff, y, weights, prior_diff = data['diff'], data['y'], data['weights'], data['prior_diff']
    rng = np.random.RandomState(seed)
    idx = rng.permutation(len(y))
    pool = idx[max(1, int(round(TEST_FRACTION * len(y)))):]
    n = min(max(n_values), len(pool))
    train = pool[:n]

    w = _fit_logistic(diff[train], y[train], weights[train], C)
    delta = _fit_logistic_offset(diff[train], y[train], weights[train], C, prior_diff[train])

    c1 = labeled['feats'] @ w
    c3 = labeled['prior'] + _lambda_n(n, k) * (labeled['feats'] @ delta)
    ordinal = labeled['ordinal']
    return {
        'C0': float(spearmanr(labeled['agg'], ordinal).correlation),
        'C1': float(spearmanr(c1, ordinal).correlation),
        'C2': float(spearmanr(labeled['prior'], ordinal).correlation),
        'C3': float(spearmanr(c3, ordinal).correlation),
    }


def _aggregate(per_seed_rows):
    """mean/std per (n, condition) from a list of {n: {cond: val}} dicts."""
    out = {}
    n_values = sorted({n for row in per_seed_rows for n in row})
    for n in n_values:
        out[n] = {}
        for cond in CONDITIONS:
            vals = [row[n][cond] for row in per_seed_rows if n in row and cond in row[n]]
            vals = [v for v in vals if v is not None and not np.isnan(v)]
            out[n][cond] = {
                'mean': float(np.mean(vals)) if vals else None,
                'std': float(np.std(vals)) if vals else None,
            }
    return out


def _print_table(title, agg):
    print(f"\n{title}")
    print(f"{'n':>4} | " + " | ".join(f"{c:>13}" for c in CONDITIONS))
    print("-" * (7 + 16 * len(CONDITIONS)))
    for n in sorted(agg):
        cells = []
        for c in CONDITIONS:
            m, s = agg[n][c]['mean'], agg[n][c]['std']
            cells.append("      n/a    " if m is None else f"{m:6.3f}±{s:5.3f}")
        print(f"{n:>4} | " + " | ".join(cells))


def run(db_path, prior_path, dims, n_values, seeds, k, C):
    prior = PiaaPrior.load_file(prior_path)
    if prior is None:
        raise SystemExit(f"No readable PIAA prior at {prior_path}")
    if prior.dim != dims:
        raise SystemExit(f"Prior dim {prior.dim} != --dims {dims}")

    conn = _ro_connection(db_path)
    optimizer = WeightOptimizer(db_path)
    prior_dir = os.path.dirname(os.path.abspath(prior_path))
    data = build_ranker_dataset(conn, optimizer, prior_models_dir=prior_dir)
    if data is None:
        raise SystemExit("No usable comparisons in the DB.")
    if data['prior'] is None or data['emb_dim'] != dims:
        raise SystemExit(
            f"Prior not loaded for the dominant dim {data['emb_dim']} "
            f"(expected {dims}); ensure {prior_path} is named piaa_prior_{dims}.npz")

    labeled = _fetch_labeled(conn, optimizer, prior, data['col_std'], data['emb_dim'])

    pair_rows, srocc_rows = [], []
    for seed in range(seeds):
        pair_rows.append(_pairwise_sweep(data, n_values, k, C, seed))
        if labeled is not None:
            srocc_rows.append(_srocc_block(data, labeled, n_values, k, C, seed))
    conn.close()

    pair_agg = _aggregate(pair_rows)
    srocc_agg = None
    if srocc_rows:
        srocc_agg = {c: {'mean': float(np.nanmean([r[c] for r in srocc_rows])),
                         'std': float(np.nanstd([r[c] for r in srocc_rows]))}
                     for c in CONDITIONS}

    report = {
        'db': os.path.abspath(db_path),
        'prior': os.path.abspath(prior_path),
        'prior_version': prior.version,
        'dims': dims,
        'n_pairs_total': data['n_pairs'],
        'seeds': seeds,
        'shrinkage_k': k,
        'n_values': n_values,
        'pairwise_accuracy': pair_agg,
        'srocc': srocc_agg,
        'srocc_labeled_photos': None if labeled is None else int(len(labeled['ordinal'])),
    }

    out_path = os.path.join(os.path.dirname(os.path.abspath(db_path)) or '.',
                            f"piaa_experiment_dim{dims}.json")
    with open(out_path, 'w') as f:
        json.dump(report, f, indent=2)

    print(f"PIAA experiment — {data['n_pairs']} pooled pairs, dim {dims}, "
          f"prior {prior.version}, {seeds} seeds")
    _print_table("Pairwise accuracy (held-out fold, mean±std across seeds)", pair_agg)
    if srocc_agg is not None:
        print(f"\nSROCC vs ordinal labels ({report['srocc_labeled_photos']} labeled photos):")
        for c in CONDITIONS:
            print(f"  {c}: {srocc_agg[c]['mean']:.3f} ± {srocc_agg[c]['std']:.3f}")
    print(f"\nReport written to {out_path}")
    return report


def main():
    parser = argparse.ArgumentParser(description="PIAA cold-start validation experiment.")
    parser.add_argument("--db", required=True, help="DB path (opened read-only)")
    parser.add_argument("--prior", required=True,
                        help="path to piaa_prior_<dim>.npz (canonically named)")
    parser.add_argument("--dims", type=int, default=768, help="embedding dim to run on")
    parser.add_argument("--seeds", type=int, default=DEFAULT_SEEDS,
                        help="re-splits of the pooled comparisons")
    parser.add_argument("--shrinkage-k", type=int, default=DEFAULT_SHRINKAGE_K)
    parser.add_argument("--C", type=float, default=DEFAULT_C)
    parser.add_argument("--n-values", type=int, nargs="+", default=DEFAULT_N_VALUES)
    args = parser.parse_args()
    run(args.db, args.prior, args.dims, args.n_values, args.seeds, args.shrinkage_k, args.C)


if __name__ == "__main__":
    main()
