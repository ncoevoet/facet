"""
Personal ranker — a learned preference model over [embedding ⊕ scalar scores].

Where ``WeightOptimizer`` tunes the *global scoring weights* over the production
metric vector, the personal ranker learns a richer pairwise model that also sees
the photo's frozen CLIP/SigLIP embedding, capturing taste the scalar metrics
miss (subject, style, content). It is a RankNet / Bradley-Terry linear head:

    s(photo) = w · [embedding ⊕ metric_vector]

trained by pairwise logistic loss on comparisons, L2 rank-smoothed, gated on
held-out k-fold accuracy against the current-``aggregate`` baseline, and written
to the ``learned_scores`` table as an *opt-in alternate sort* — it never
overwrites ``aggregate``.

Reuses ``WeightOptimizer._fetch_comparison_data`` for the metric vectors and
``SOURCE_WEIGHTS`` for per-source reliability weighting, so training data is the
exact 0-10 feature space the scorer produces, plus the embedding.
"""

import json
import logging
import time
from datetime import datetime, timezone

import numpy as np

from db import DEFAULT_DB_PATH, get_connection
from optimization.weight_optimizer import WeightOptimizer
from utils.embedding import bytes_to_normalized_embedding

logger = logging.getLogger("facet.personal_ranker")

RNG_SEED = 42
MIN_COMPARISONS = 30
DEFAULT_MIN_IMPROVEMENT_PP = 2.0
DEFAULT_C = 1.0          # inverse L2 strength for the rank-smoothing penalty
DEFAULT_CV_FOLDS = 5

# stats_cache key prefix for the latest per-scope train metrics, read by the
# /api/ranker/status endpoint to surface a "My Taste" confidence indicator.
_METRICS_KEY_PREFIX = "ranker_metrics"


def ranker_metrics_key(user_id=None, category=None) -> str:
    """stats_cache key for a scope's last-train metrics ('global'/'all' default)."""
    return f"{_METRICS_KEY_PREFIX}:{user_id or 'global'}:{category or 'all'}"


def _persist_ranker_metrics(db_path, category, user_id, result):
    """Persist the latest train metrics to stats_cache for the status endpoint.

    Best-effort: never let a metrics-cache failure break training.
    """
    payload = {
        'trained': True,
        'gated': bool(result.get('gated')),
        'written': int(result.get('written') or 0),
        'comparison_count': int(result.get('n_pairs') or 0),
        'cv_accuracy': result.get('cv_accuracy'),
        'baseline_accuracy': result.get('baseline_accuracy'),
        'improvement_pp': result.get('improvement_pp'),
        'updated_at': datetime.now(timezone.utc).isoformat(),
    }
    try:
        with get_connection(db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO stats_cache (key, value, updated_at) VALUES (?, ?, ?)",
                (ranker_metrics_key(user_id, category), json.dumps(payload), time.time()),
            )
            conn.commit()
    except Exception:
        logger.debug("Failed to persist ranker metrics", exc_info=True)


def _has_moment_confidence(conn):
    """True when the photos table carries the narrative_moment_confidence column."""
    return 'narrative_moment_confidence' in {
        r[1] for r in conn.execute("PRAGMA table_info(photos)").fetchall()
    }


def _load_embeddings_and_aggregate(conn, paths):
    """Return {path: (normalized_embedding_or_None, aggregate_or_None, moment_confidence)}.

    ``moment_confidence`` is the F21 posterior (0..1), or 0.0 when the photo is
    unlabelled or the column is absent — appended to the ranker feature vector as
    one extra signal. A column of all-zeros (un-migrated DB) is a constant the
    feature scaler floors out, so the dimension stays consistent either way.
    """
    has_moment = _has_moment_confidence(conn)
    sel = "path, clip_embedding, aggregate"
    if has_moment:
        sel += ", narrative_moment_confidence"
    out = {}
    path_list = list(paths)
    for start in range(0, len(path_list), 900):
        chunk = path_list[start:start + 900]
        ph = ','.join('?' * len(chunk))
        for r in conn.execute(f"SELECT {sel} FROM photos WHERE path IN ({ph})", chunk):
            mc = r['narrative_moment_confidence'] if has_moment else None
            out[r['path']] = (
                bytes_to_normalized_embedding(r['clip_embedding']), r['aggregate'],
                float(mc) if mc is not None else 0.0,
            )
    return out


def build_ranker_dataset(conn, optimizer, category=None, sources=None):
    """Build the pairwise training dataset: difference vectors + labels + weights.

    Reuses ``optimizer._fetch_comparison_data`` for the per-photo metric vectors,
    then concatenates each photo's frozen embedding to form the feature
    ``[embedding ⊕ metric_vector]``. Pairs are dropped when either photo lacks an
    embedding or its embedding dimension differs from the dominant dimension
    (mixed CLIP-768 / SigLIP-1152 DBs train per-dim, on the majority).

    Returns a dict with:
        diff        (n, F)  feature_a - feature_b
        y           (n,)    1 if 'a' won, 0 if 'b' won (ties excluded)
        weights     (n,)    per-pair SOURCE_WEIGHTS reliability
        agg_a, agg_b (n,)   aggregates, for the baseline comparator
        col_std     (F,)    per-column std (feature scaler, for inference)
        emb_dim, n_metrics, n_pairs
    """
    comparisons, X_a, X_b, winners, row_weights = optimizer._fetch_comparison_data(
        conn, category=category, include_ties=False, sources=sources
    )
    if not comparisons:
        return None

    paths = {c['photo_a'] for c in comparisons} | {c['photo_b'] for c in comparisons}
    emb_agg = _load_embeddings_and_aggregate(conn, paths)

    # Dominant embedding dimension among involved photos.
    dims = [e.shape[0] for (e, _, _) in emb_agg.values() if e is not None]
    if not dims:
        logger.warning("No comparison photos have embeddings — cannot train the ranker.")
        return None
    from collections import Counter
    emb_dim = Counter(dims).most_common(1)[0][0]

    feats_a, feats_b, y, weights, agg_a, agg_b = [], [], [], [], [], []
    dropped = 0
    for i, c in enumerate(comparisons):
        ea, aa, mca = emb_agg.get(c['photo_a'], (None, None, 0.0))
        eb, ab, mcb = emb_agg.get(c['photo_b'], (None, None, 0.0))
        if ea is None or eb is None or ea.shape[0] != emb_dim or eb.shape[0] != emb_dim:
            dropped += 1
            continue
        # Feature = [embedding ⊕ metric_vector/10 ⊕ moment_confidence].
        feats_a.append(np.concatenate([ea, X_a[i] / 10.0, [mca]]))
        feats_b.append(np.concatenate([eb, X_b[i] / 10.0, [mcb]]))
        y.append(1 if winners[i] == 1 else 0)
        weights.append(float(row_weights[i]))
        agg_a.append(aa if aa is not None else 0.0)
        agg_b.append(ab if ab is not None else 0.0)

    if not feats_a:
        return None
    if dropped:
        logger.info("Dropped %d/%d pairs (missing or mismatched-dim embeddings)",
                    dropped, len(comparisons))

    Fa = np.asarray(feats_a, dtype=np.float64)
    Fb = np.asarray(feats_b, dtype=np.float64)
    diff = Fa - Fb
    # Per-column scale from the stacked photo features (mean cancels in the
    # difference; std does not). Floor at 1e-6 so constant columns don't blow up.
    col_std = np.concatenate([Fa, Fb], axis=0).std(axis=0)
    col_std[col_std < 1e-6] = 1e-6

    return {
        'diff': diff / col_std,
        'y': np.asarray(y, dtype=np.int64),
        'weights': np.asarray(weights, dtype=np.float64),
        'agg_a': np.asarray(agg_a, dtype=np.float64),
        'agg_b': np.asarray(agg_b, dtype=np.float64),
        'col_std': col_std,
        'emb_dim': emb_dim,
        'n_metrics': X_a.shape[1],
        'n_pairs': len(y),
    }


def _fit_logistic(diff, y, weights, C):
    """Fit the L2-regularized pairwise logistic head (RankNet/BT), seeded.

    Symmetrized (each pair contributes (d, 1) and (-d, 0)) so the model cannot
    exploit a/b ordering and both classes are always present.
    """
    from sklearn.linear_model import LogisticRegression
    X = np.concatenate([diff, -diff], axis=0)
    yy = np.concatenate([y, 1 - y])
    ww = np.concatenate([weights, weights])
    # L2 is the default penalty (the rank-smoothing the weight-optimizer CV lacks);
    # C is its inverse strength. solver='lbfgs' is deterministic given the seed.
    clf = LogisticRegression(
        fit_intercept=False, C=C, solver='lbfgs',
        max_iter=2000, random_state=RNG_SEED,
    )
    clf.fit(X, yy, sample_weight=ww)
    return clf.coef_[0]


def _pairwise_accuracy(w, diff, y):
    """Fraction of pairs whose winner the model predicts (sign of w·diff)."""
    if len(y) == 0:
        return 0.0
    pred = (diff @ w) > 0
    return float((pred == (y == 1)).mean())


def _baseline_accuracy(agg_a, agg_b, y):
    """Accuracy of ranking by current aggregate (the comparator to beat)."""
    if len(y) == 0:
        return 0.0
    pred = agg_a > agg_b
    return float((pred == (y == 1)).mean())


def _cv_accuracy(diff, y, weights, C, n_folds, seed=RNG_SEED):
    """Mean held-out accuracy over k folds (split on pairs)."""
    n = len(y)
    folds = max(2, min(n_folds, n))
    rng = np.random.RandomState(seed)
    idx = rng.permutation(n)
    chunks = np.array_split(idx, folds)
    accs = []
    for k in range(folds):
        test = chunks[k]
        train = np.concatenate([chunks[j] for j in range(folds) if j != k])
        if len(train) == 0 or len(test) == 0:
            continue
        w = _fit_logistic(diff[train], y[train], weights[train], C)
        accs.append(_pairwise_accuracy(w, diff[test], y[test]))
    return float(np.mean(accs)) if accs else 0.0


def train_ranker(db_path=DEFAULT_DB_PATH, category=None, user_id=None,
                 sources=None, config_path='scoring_config.json',
                 C=DEFAULT_C, n_folds=DEFAULT_CV_FOLDS,
                 min_improvement_pp=DEFAULT_MIN_IMPROVEMENT_PP, force=False,
                 write=True):
    """Train the personal ranker and (if gated) write learned_scores.

    Returns a result dict. On insufficient data or a failed gate (and not
    ``force``), returns ``{'error': ...}`` / ``{'gated': True, ...}`` and writes
    nothing.
    """
    optimizer = WeightOptimizer(db_path, config_path)
    with get_connection(db_path) as conn:
        data = build_ranker_dataset(conn, optimizer, category=category, sources=sources)

    if data is None or data['n_pairs'] < MIN_COMPARISONS:
        n = 0 if data is None else data['n_pairs']
        return {'error': f'insufficient comparisons: {n} < {MIN_COMPARISONS}', 'n_pairs': n}

    diff, y, weights = data['diff'], data['y'], data['weights']
    baseline = _baseline_accuracy(data['agg_a'], data['agg_b'], y) * 100.0
    cv_acc = _cv_accuracy(diff, y, weights, C, n_folds) * 100.0
    # Final model on all pairs.
    w = _fit_logistic(diff, y, weights, C)
    train_acc = _pairwise_accuracy(w, diff, y) * 100.0
    improvement = cv_acc - baseline

    result = {
        'n_pairs': data['n_pairs'],
        'emb_dim': data['emb_dim'],
        'n_metrics': data['n_metrics'],
        'baseline_accuracy': round(baseline, 1),
        'cv_accuracy': round(cv_acc, 1),
        'train_accuracy': round(train_acc, 1),
        'improvement_pp': round(improvement, 1),
        'category': category,
        'user_id': user_id,
    }

    if improvement < min_improvement_pp and not force:
        result['gated'] = True
        result['written'] = 0
        logger.info(
            "Ranker gated: held-out %.1f%% vs aggregate baseline %.1f%% "
            "(+%.1f pp < %.1f pp threshold). Use force=True to write anyway.",
            cv_acc, baseline, improvement, min_improvement_pp,
        )
        _persist_ranker_metrics(db_path, category, user_id, result)
        return result

    if not write:
        result['written'] = 0
        return result

    written = _write_learned_scores(db_path, w, data['col_std'], data['emb_dim'],
                                    optimizer, category, user_id, data['n_pairs'])
    result['gated'] = False
    result['written'] = written
    _persist_ranker_metrics(db_path, category, user_id, result)
    logger.info("Ranker written: %d learned_scores (held-out %.1f%% vs baseline %.1f%%, +%.1f pp)",
                written, cv_acc, baseline, improvement)
    return result


def _write_learned_scores(db_path, w, col_std, emb_dim, optimizer, category, user_id, n_pairs):
    """Score every embedded photo and write percentile-normalized learned_scores.

    Clears stale rows for this (category, user) scope first, then inserts the raw
    score percentile-normalized to 0-10. Photos without an embedding of the
    trained dimension get no row (NULL → opt-in sort skips them).
    """
    with get_connection(db_path) as conn:
        cur = conn.execute("SELECT * FROM photos WHERE clip_embedding IS NOT NULL")
        rows = [dict(r) for r in cur.fetchall()]

        scored = []
        for row in rows:
            emb = bytes_to_normalized_embedding(row['clip_embedding'])
            if emb is None or emb.shape[0] != emb_dim:
                continue
            mv = np.asarray(optimizer._metric_vector(row, category), dtype=np.float64) / 10.0
            mc = row.get('narrative_moment_confidence')
            mc = float(mc) if mc is not None else 0.0
            feat = np.concatenate([emb, mv, [mc]]) / col_std
            scored.append((row['path'], float(feat @ w)))

        if not scored:
            return 0

        raw = np.array([s for _, s in scored])
        order = np.argsort(np.argsort(raw))  # rank 0..n-1
        denom = max(1, len(raw) - 1)
        normalized = 10.0 * order / denom

        now = datetime.now(timezone.utc).isoformat()
        # Clear stale rows for this scope, then insert fresh.
        if user_id is None:
            conn.execute("DELETE FROM learned_scores WHERE category IS ? AND user_id IS NULL", (category,))
        else:
            conn.execute("DELETE FROM learned_scores WHERE category IS ? AND user_id = ?", (category, user_id))
        conn.executemany(
            """INSERT OR REPLACE INTO learned_scores
               (photo_path, learned_score, comparison_count, category, updated_at, user_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [
                (path, float(normalized[i]), n_pairs, category, now, user_id)
                for i, (path, _) in enumerate(scored)
            ],
        )
        conn.commit()
        return len(scored)
