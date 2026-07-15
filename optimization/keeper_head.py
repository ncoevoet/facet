"""Learned keeper-ranking head — roadmap 2.2 v2.

A specialization of the personal ranker (``optimization/personal_ranker.py``) fit
on culling decisions (``source='culling'``) that, within a burst/scene group of
near-duplicate frames, ranks which frame the user would keep. It reuses the
ranker's pairwise-logistic head, feature builder and k-fold gate; the genuinely
new pieces are:

- a **heuristic-pick baseline** — the gate must beat the auto-cull heuristic
  (``processing/burst_score.compute_burst_score``), NOT the ``aggregate`` baseline
  the personal ranker uses, or a "trained" head would not actually be better at
  culling; and
- **within-group softmax normalization** of the head's raw scores into a keeper
  probability, computed on demand per group (nothing per-photo is persisted, so
  it never goes stale when grouping/config changes).

Only the trained head (weight vector + feature scaler + provenance) is persisted,
as a ``stats_cache`` JSON snapshot keyed by (user, category).
"""

import json
import logging
import os
import time
from datetime import datetime, timezone

import numpy as np

from db import DEFAULT_DB_PATH, get_connection
from optimization.personal_ranker import (
    DEFAULT_C, DEFAULT_CV_FOLDS, DEFAULT_MIN_IMPROVEMENT_PP, MIN_COMPARISONS,
    _cv_accuracy, _fit_logistic, _pairwise_accuracy, _scaled_feature,
    build_ranker_dataset,
)
from optimization.weight_optimizer import WeightOptimizer
from processing.burst_score import burst_weights_from_config
from utils.embedding import bytes_to_normalized_embedding

logger = logging.getLogger("facet.keeper_head")

_HEAD_KEY_PREFIX = "keeper_head"


def keeper_head_key(user_id=None, category=None) -> str:
    """stats_cache key for a scope's trained keeper head ('global'/'all' default)."""
    return f"{_HEAD_KEY_PREFIX}:{user_id or 'global'}:{category or 'all'}"


class KeeperHead:
    """Trained keeper head: weight vector, feature scaler, and provenance."""

    def __init__(self, w, col_std, emb_dim, n_metrics, meta=None):
        self.w = np.asarray(w, dtype=np.float64)
        self.col_std = np.asarray(col_std, dtype=np.float64)
        self.emb_dim = int(emb_dim)
        self.n_metrics = int(n_metrics)
        self.meta = meta or {}


def save_keeper_head(conn, head, user_id, category):
    """Persist a trained head as a stats_cache JSON snapshot for (user, category)."""
    payload = {
        'w': head.w.tolist(),
        'col_std': head.col_std.tolist(),
        'emb_dim': head.emb_dim,
        'n_metrics': head.n_metrics,
        **head.meta,
        'updated_at': datetime.now(timezone.utc).isoformat(),
    }
    conn.execute(
        "INSERT OR REPLACE INTO stats_cache (key, value, updated_at) VALUES (?, ?, ?)",
        (keeper_head_key(user_id, category), json.dumps(payload), time.time()),
    )
    conn.commit()


def load_keeper_head(conn, user_id=None, category=None):
    """Load a trained head for (user, category); None when not trained."""
    row = conn.execute(
        "SELECT value FROM stats_cache WHERE key = ?",
        (keeper_head_key(user_id, category),),
    ).fetchone()
    if not row:
        return None
    try:
        d = json.loads(row[0])
    except (ValueError, TypeError):
        return None
    if 'w' not in d or 'col_std' not in d:
        return None
    w, col_std = d['w'], d['col_std']
    emb_dim, n_metrics = d.get('emb_dim', 0), d.get('n_metrics', 0)
    if len(w) != len(col_std) or (emb_dim and n_metrics
                                  and len(w) != emb_dim + n_metrics + 1):
        logger.warning(
            "Ignoring stale keeper head %s: weight dim %d inconsistent with "
            "col_std %d / emb %d + metrics %d + 1; re-run --train-keeper.",
            keeper_head_key(user_id, category), len(w), len(col_std),
            emb_dim, n_metrics,
        )
        return None
    meta = {k: v for k, v in d.items()
            if k not in ('w', 'col_std', 'emb_dim', 'n_metrics')}
    return KeeperHead(w, col_std, emb_dim, n_metrics, meta)


def _keeper_baseline_accuracy(heur_a, heur_b, y):
    """Accuracy of ranking by the auto-cull heuristic pick (the comparator to beat)."""
    if len(y) == 0:
        return 0.0
    pred = np.asarray(heur_a) > np.asarray(heur_b)
    return float((pred == (y == 1)).mean())


def _burst_weights_for(config_path):
    """The burst_scoring weights, read from the config file (defaults if absent)."""
    try:
        with open(config_path) as f:
            block = json.load(f).get('burst_scoring', {})
    except (OSError, ValueError):
        block = {}
    return burst_weights_from_config(block)


def _default_config_path():
    """Resolve the same scoring_config.json api.config._CONFIG_PATH resolves,
    computed here rather than imported to keep the api -> optimization import
    direction one-way.
    """
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'scoring_config.json')


def train_keeper_head(db_path=DEFAULT_DB_PATH, category=None, user_id=None,
                      config_path=None, C=DEFAULT_C,
                      n_folds=DEFAULT_CV_FOLDS,
                      min_improvement_pp=DEFAULT_MIN_IMPROVEMENT_PP,
                      force=False, write=True):
    """Train the keeper head on ``source='culling'`` pairs; persist only if it
    beats the heuristic pick on held-out CV by >= ``min_improvement_pp``.

    ``config_path`` defaults to the repo's ``scoring_config.json`` (resolved
    absolutely, matching the file inference uses) so a train under systemd/Docker
    reads the same config it serves with; an explicit path still wins.

    Returns a result dict. On insufficient data returns ``{'error': ...}``; on a
    failed gate (and not ``force``) returns ``{'gated': True, 'written': False}``
    and persists nothing.
    """
    if config_path is None:
        config_path = _default_config_path()
    weights = _burst_weights_for(config_path)
    optimizer = WeightOptimizer(db_path, config_path)
    with get_connection(db_path) as conn:
        data = build_ranker_dataset(
            conn, optimizer, category=category, sources=['culling'],
            user_id=user_id, with_heuristic=True, heuristic_weights=weights,
        )

    if data is None or data['n_pairs'] < MIN_COMPARISONS:
        n = 0 if data is None else data['n_pairs']
        return {'error': f'insufficient culling pairs: {n} < {MIN_COMPARISONS}',
                'n_pairs': n, 'category': category, 'user_id': user_id}

    diff, y, w_pairs = data['diff'], data['y'], data['weights']
    baseline = _keeper_baseline_accuracy(data['heur_a'], data['heur_b'], y) * 100.0
    cv_acc = _cv_accuracy(diff, y, w_pairs, C, n_folds) * 100.0
    w = _fit_logistic(diff, y, w_pairs, C)
    train_acc = _pairwise_accuracy(w, diff, y) * 100.0
    improvement = cv_acc - baseline

    result = {
        'n_pairs': data['n_pairs'], 'emb_dim': data['emb_dim'],
        'n_metrics': data['n_metrics'],
        'baseline_accuracy': round(baseline, 1), 'cv_accuracy': round(cv_acc, 1),
        'train_accuracy': round(train_acc, 1), 'improvement_pp': round(improvement, 1),
        'category': category, 'user_id': user_id,
    }

    if improvement < min_improvement_pp and not force:
        result['gated'] = True
        result['written'] = False
        logger.info(
            "Keeper head gated: held-out %.1f%% vs heuristic %.1f%% "
            "(+%.1f pp < %.1f pp threshold); nothing persisted.",
            cv_acc, baseline, improvement, min_improvement_pp,
        )
        return result

    result['gated'] = False
    if not write:
        result['written'] = False
        return result

    head = KeeperHead(w, data['col_std'], data['emb_dim'], data['n_metrics'], meta={
        'n_pairs': data['n_pairs'], 'cv_accuracy': round(cv_acc, 1),
        'baseline_accuracy': round(baseline, 1), 'improvement_pp': round(improvement, 1),
        'config_path': config_path,
    })
    with get_connection(db_path) as conn:
        save_keeper_head(conn, head, user_id, category)
    result['written'] = True
    logger.info(
        "Keeper head written: held-out %.1f%% vs heuristic %.1f%% (+%.1f pp), n=%d",
        cv_acc, baseline, improvement, data['n_pairs'],
    )
    return result


def keeper_probs_for_group(head, optimizer, rows, category=None):
    """Softmax keeper probability per photo within one group.

    ``rows`` are full photo dicts (need ``clip_embedding`` + the metric columns +
    ``narrative_moment_confidence``). Returns ``{path: prob}`` summing to 1 over
    the members whose embedding matches ``head.emb_dim``, or None when fewer than
    two match or ``head`` is None.
    """
    if head is None:
        return None
    scored = []
    for row in rows:
        emb = bytes_to_normalized_embedding(row.get('clip_embedding'))
        if emb is None or emb.shape[0] != head.emb_dim:
            continue
        if not scored:
            runtime_dim = emb.shape[0] + len(optimizer._metric_vector(row, category)) + 1
            if runtime_dim != head.w.shape[0]:
                logger.warning(
                    "Ignoring stale keeper head: feature dim %d != runtime %d "
                    "(scoring metrics changed); re-run --train-keeper.",
                    head.w.shape[0], runtime_dim,
                )
                return None
        feat = _scaled_feature(row, emb, optimizer, category, head.col_std)
        scored.append((row['path'], float(feat @ head.w)))
    if len(scored) < 2:
        return None
    raw = np.array([s for _, s in scored])
    raw = raw - raw.max()
    exp = np.exp(raw)
    probs = exp / exp.sum()
    return {path: float(probs[i]) for i, (path, _) in enumerate(scored)}
