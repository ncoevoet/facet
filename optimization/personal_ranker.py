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

from config.scoring_config import _resolve_scoring_config_path
from db import DEFAULT_DB_PATH, get_connection
from models.piaa_prior import DEFAULT_MODELS_DIR, PiaaPrior
from optimization.weight_optimizer import WeightOptimizer
from utils.embedding import bytes_to_normalized_embedding

logger = logging.getLogger("facet.personal_ranker")

RNG_SEED = 42
MIN_COMPARISONS = 30
DEFAULT_MIN_IMPROVEMENT_PP = 2.0
DEFAULT_C = 1.0          # inverse L2 strength for the rank-smoothing penalty
DEFAULT_CV_FOLDS = 5
DEFAULT_SHRINKAGE_K = 10  # PIAA blend: lambda(n) = n / (n + k)

# photos BLOB columns the ranker never reads. Excluded from the inference scan
# because thumbnail alone averages ~46 KB/row — several GB of a full library
# materialized, then discarded, on a background thread inside the viewer.
_UNUSED_BLOB_COLS = frozenset({'thumbnail', 'histogram_data', 'caption_embedding'})

# Rows per write transaction. The inference pass rewrites a row per photo; doing
# that in one transaction holds SQLite's single write lock for the whole run, so
# an interactive rating write waits out busy_timeout and fails. Committing in
# slices releases the lock between them.
_WRITE_CHUNK = 2000

# Rows per keyset page of the inference scan. Iterating one cursor lazily while
# numpy scores each row keeps a read snapshot open for the whole (multi-minute)
# pass, so the WAL checkpointer cannot advance past the reader and `-wal` grows
# unbounded. Each page is fetched whole — bounding the snapshot to one page —
# and only the page is held in memory.
_SCAN_PAGE_ROWS = 2000

_ROWID_ALIAS = "_scan_rowid"

# The global-scope score a photo mirrors, repeated by every statement that reads
# it so the two can never drift apart.
_GLOBAL_LEARNED_SCORE = (
    "(SELECT ls.learned_score FROM learned_scores ls"
    "  WHERE ls.photo_path = photos.path"
    "    AND ls.category IS NULL AND ls.user_id IS NULL)"
)


def _load_piaa_config(config_path):
    """Read the ``piaa_prior`` block. Missing file/block -> disabled (flag off)."""
    try:
        with open(config_path) as f:
            block = json.load(f).get('piaa_prior', {})
    except Exception:
        return {'enabled': False}
    return block if isinstance(block, dict) else {'enabled': False}


def _lambda_n(n, k):
    """Cold-start blend weight: 0 at n=0, monotone -> 1 as n grows. k = shrinkage constant."""
    if n <= 0:
        return 0.0
    return float(n) / (float(n) + float(k))

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
        # PIAA: records which prior (if any) produced this scope's scores so a
        # prior re-fit can invalidate stale learned_scores.
        'mode': result.get('mode', 'personal'),
        'prior_version': result.get('prior_version'),
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


def _load_burst_scores(conn, paths, weights):
    """{path: heuristic burst score} — the keeper head's baseline comparator.

    Reads the same photos columns the auto-cull heuristic scores on (including
    the per-photo eyes_open_score / expression_score, which the burst fetcher
    also reads from photos), so the gate compares the keeper head against the
    exact heuristic pick.
    """
    from processing.burst_score import compute_burst_score
    from api.db_helpers import select_in_chunks
    cols = ("path, aggregate, aesthetic, tech_sharpness, is_blink, face_count, "
            "eyes_open_score, expression_score")
    out = {}
    for r in select_in_chunks(
            conn, f"SELECT {cols} FROM photos WHERE path IN ({{placeholders}})", paths):
        out[r['path']] = compute_burst_score(dict(r), weights)
    return out


def build_ranker_dataset(conn, optimizer, category=None, sources=None, user_id=None,
                         prior_models_dir=None, with_heuristic=False,
                         heuristic_weights=None):
    """Build the pairwise training dataset: difference vectors + labels + weights.

    Reuses ``optimizer._fetch_comparison_data`` for the per-photo metric vectors,
    then concatenates each photo's frozen embedding to form the feature
    ``[embedding ⊕ metric_vector]``. Pairs are dropped when either photo lacks an
    embedding or its embedding dimension differs from the dominant dimension
    (mixed CLIP-768 / SigLIP-1152 DBs train per-dim, on the majority).

    ``user_id`` scopes the comparisons to one user's rows plus legacy NULL rows
    (None = the global pooled default).

    ``prior_models_dir`` (None = disabled, the prior-free default) loads the PIAA
    cold-start prior for the dominant dim; when found the result also carries the
    prior object and the per-pair prior logit offset ``prior_diff`` used to fit
    the personal delta regularized toward the prior.

    Returns a dict with:
        diff        (n, F)  feature_a - feature_b
        y           (n,)    1 if 'a' won, 0 if 'b' won (ties excluded)
        weights     (n,)    per-pair SOURCE_WEIGHTS reliability
        agg_a, agg_b (n,)   aggregates, for the baseline comparator
        col_std     (F,)    per-column std (feature scaler, for inference)
        emb_dim, n_metrics, n_pairs
        prior       PiaaPrior or None
        prior_diff  (n,) prior mixed score(a) - score(b), or None
    """
    comparisons, X_a, X_b, winners, row_weights = optimizer._fetch_comparison_data(
        conn, category=category, include_ties=False, sources=sources, user_id=user_id
    )
    if not comparisons:
        return None

    paths = {c['photo_a'] for c in comparisons} | {c['photo_b'] for c in comparisons}
    emb_agg = _load_embeddings_and_aggregate(conn, paths)
    from processing.burst_score import DEFAULT_BURST_WEIGHTS
    heur = (_load_burst_scores(conn, paths, heuristic_weights or DEFAULT_BURST_WEIGHTS)
            if with_heuristic else None)

    # Dominant embedding dimension among involved photos.
    dims = [e.shape[0] for (e, _, _) in emb_agg.values() if e is not None]
    if not dims:
        logger.warning("No comparison photos have embeddings — cannot train the ranker.")
        return None
    from collections import Counter
    emb_dim = Counter(dims).most_common(1)[0][0]

    prior = PiaaPrior.load(emb_dim, prior_models_dir) if prior_models_dir is not None else None

    feats_a, feats_b, y, weights, agg_a, agg_b = [], [], [], [], [], []
    prior_a, prior_b = [], []
    heur_a, heur_b = [], []
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
        if prior is not None:
            prior_a.append(prior.mixed_score(ea))
            prior_b.append(prior.mixed_score(eb))
        if heur is not None:
            heur_a.append(heur.get(c['photo_a'], 0.0))
            heur_b.append(heur.get(c['photo_b'], 0.0))

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

    prior_diff = (np.asarray(prior_a, dtype=np.float64) - np.asarray(prior_b, dtype=np.float64)
                  if prior is not None else None)

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
        'prior': prior,
        'prior_diff': prior_diff,
        'heur_a': np.asarray(heur_a, dtype=np.float64) if with_heuristic else None,
        'heur_b': np.asarray(heur_b, dtype=np.float64) if with_heuristic else None,
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


def _fit_logistic_offset(diff, y, weights, C, offset):
    """Pairwise-logistic delta with a fixed per-pair prior logit offset.

    Fits ``delta`` so ``sign(offset + delta·diff)`` predicts the winner, with an
    L2 penalty (strength ``1/C``) on ``delta`` — the personal head regularized
    *toward* the prior (``delta = 0`` is pure prior). Symmetrized like
    ``_fit_logistic``. Deterministic: fixed zero start, L-BFGS-B.
    """
    from scipy.optimize import minimize
    X = np.concatenate([diff, -diff], axis=0)
    yy = np.concatenate([y, 1 - y]).astype(np.float64)
    off = np.concatenate([offset, -offset])
    ww = np.concatenate([weights, weights])
    lam = 1.0 / C

    def objective(d):
        z = off + X @ d
        loss = np.where(yy == 1.0, np.logaddexp(0.0, -z), np.logaddexp(0.0, z))
        prob = 1.0 / (1.0 + np.exp(-z))
        grad = X.T @ (ww * (prob - yy)) + lam * d
        return float((ww * loss).sum() + 0.5 * lam * float(d @ d)), grad

    res = minimize(objective, np.zeros(X.shape[1]), jac=True, method='L-BFGS-B',
                   options={'maxiter': 2000})
    return res.x


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
                 sources=None, config_path=None,
                 C=DEFAULT_C, n_folds=DEFAULT_CV_FOLDS,
                 min_improvement_pp=DEFAULT_MIN_IMPROVEMENT_PP, force=False,
                 write=True):
    """Train the personal ranker and (if gated) write learned_scores.

    Returns a result dict. On insufficient data or a failed gate (and not
    ``force``), returns ``{'error': ...}`` / ``{'gated': True, ...}`` and writes
    nothing.
    """
    config_path = _resolve_scoring_config_path(config_path)
    piaa = _load_piaa_config(config_path)
    prior_enabled = bool(piaa.get('enabled', False))
    prior_models_dir = piaa.get('models_dir', DEFAULT_MODELS_DIR) if prior_enabled else None

    optimizer = WeightOptimizer(db_path, config_path)
    with get_connection(db_path) as conn:
        data = build_ranker_dataset(conn, optimizer, category=category, sources=sources,
                                    user_id=user_id, prior_models_dir=prior_models_dir)

    if data is None or data['n_pairs'] < MIN_COMPARISONS:
        if prior_enabled:
            return _train_prior_only(db_path, piaa, category, user_id, data, write)
        n = 0 if data is None else data['n_pairs']
        return {'error': f'insufficient comparisons: {n} < {MIN_COMPARISONS}', 'n_pairs': n}

    diff, y, weights = data['diff'], data['y'], data['weights']
    baseline = _baseline_accuracy(data['agg_a'], data['agg_b'], y) * 100.0
    cv_acc = _cv_accuracy(diff, y, weights, C, n_folds) * 100.0
    # Final model on all pairs.
    w = _fit_logistic(diff, y, weights, C)
    train_acc = _pairwise_accuracy(w, diff, y) * 100.0
    improvement = cv_acc - baseline

    prior = data.get('prior')
    use_blend = prior_enabled and prior is not None and data.get('prior_diff') is not None

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
        # The CV gate governs divergence from the prior, not whether we write:
        # a gated user with the prior on keeps prior-only scores, not nothing.
        if use_blend and write:
            result['written'] = _write_prior_scores(
                db_path, prior, data['emb_dim'], category, user_id, data['n_pairs'])
            result['mode'] = 'prior_only'
            result['prior_version'] = prior.version
        else:
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

    if use_blend:
        lam = _lambda_n(data['n_pairs'], float(piaa.get('shrinkage_k', DEFAULT_SHRINKAGE_K)))
        delta = _fit_logistic_offset(diff, y, weights, C, data['prior_diff'])
        written = _write_blended_scores(db_path, prior, delta, data['col_std'],
                                        data['emb_dim'], optimizer, category, user_id,
                                        data['n_pairs'], lam)
        result['mode'] = 'blend'
        result['prior_version'] = prior.version
        result['lambda'] = round(lam, 4)
    else:
        written = _write_learned_scores(db_path, w, data['col_std'], data['emb_dim'],
                                        optimizer, category, user_id, data['n_pairs'])
    result['gated'] = False
    result['written'] = written
    _persist_ranker_metrics(db_path, category, user_id, result)
    logger.info("Ranker written: %d learned_scores (held-out %.1f%% vs baseline %.1f%%, +%.1f pp)",
                written, cv_acc, baseline, improvement)
    return result


def _scaled_feature(row, emb, optimizer, category, col_std):
    """The ranker inference feature [embedding ⊕ metric/10 ⊕ moment_conf] / col_std."""
    mv = np.asarray(optimizer._metric_vector(row, category), dtype=np.float64) / 10.0
    mc = row.get('narrative_moment_confidence')
    mc = float(mc) if mc is not None else 0.0
    return np.concatenate([emb, mv, [mc]]) / col_std


def _scoring_columns(conn):
    """Every ``photos`` column except the BLOBs the ranker never reads.

    An exclude-list rather than an allow-list: the feature builder reads ~26
    columns via build_metric_vector AND whatever columns the user's category
    filters name (ScoringConfig.determine_category), so an allow-list would
    silently drop a column the moment a filter referenced a new one.
    """
    return [r[1] for r in conn.execute("PRAGMA table_info(photos)")
            if r[1] not in _UNUSED_BLOB_COLS]


def _collect_scored(db_path, emb_dim, raw_fn):
    """Return [(path, raw_score)] for every photo whose embedding matches emb_dim.

    ``raw_fn(row, emb)`` computes the un-normalized head output; percentile
    normalization happens once, later, in ``_persist_scores`` — the PIAA blend
    is applied HERE, on the raw scores, never after the rank/percentile step.

    Rows are read one keyset page at a time rather than materialized whole: a
    full library's thumbnails alone are several GB, and this runs on a background
    thread inside the viewer process. Each page is exhausted before it is scored,
    so the read snapshot lasts a page rather than the whole run — a cursor held
    open across multi-minute numpy work pins the WAL and lets it grow unbounded.
    """
    scored = []
    with get_connection(db_path) as conn:
        cols = ", ".join(_scoring_columns(conn))
        query = (f"SELECT rowid AS {_ROWID_ALIAS}, {cols} FROM photos "
                 f"WHERE clip_embedding IS NOT NULL AND rowid > ? ORDER BY rowid LIMIT ?")
        last_rowid = 0
        while True:
            page = conn.execute(query, (last_rowid, _SCAN_PAGE_ROWS)).fetchall()
            if not page:
                return scored
            for r in page:
                row = dict(r)
                last_rowid = row.pop(_ROWID_ALIAS)
                emb = bytes_to_normalized_embedding(row['clip_embedding'])
                if emb is None or emb.shape[0] != emb_dim:
                    continue
                scored.append((row['path'], float(raw_fn(row, emb))))


def _mirror_learned_score(conn):
    """Copy the global learned_scores into photos.learned_score, in rowid slices.

    The gallery "My Taste" sort reads the denormalized column so it hits
    idx_learned_score instead of a per-row correlated subquery. The correlated
    SELECT is a primary-key probe (learned_scores.photo_path is the PK), and it
    yields NULL for photos that no longer have a score — so one statement both
    clears stale values and writes new ones, replacing a full-table NULL sweep
    plus a per-photo UPDATE.

    The subquery repeats the caller's global-scope predicate. photo_path is the
    whole primary key, so a photo carries at most one row across every scope; an
    unmatched per-user row left over from another scope's training must mirror as
    NULL, not leak into the global column.

    The ``IS NOT`` predicate (NULL-safe on both sides) restricts the write to
    rows whose score actually moved: without it every photo in the slice is
    rewritten, and a photos record carries a ~46 KB thumbnail.
    """
    top = conn.execute("SELECT MAX(rowid) FROM photos").fetchone()[0]
    if top is None:
        return
    for start in range(1, top + 1, _WRITE_CHUNK):
        conn.execute(
            f"""UPDATE photos SET learned_score = {_GLOBAL_LEARNED_SCORE}
                WHERE rowid BETWEEN ? AND ?
                  AND learned_score IS NOT {_GLOBAL_LEARNED_SCORE}""",
            (start, start + _WRITE_CHUNK - 1),
        )
        conn.commit()


def _scope_clause(category, user_id):
    """``(sql, params)`` selecting exactly one (category, user) scope's rows."""
    if user_id is None:
        return "category IS ? AND user_id IS NULL", [category]
    return "category IS ? AND user_id = ?", [category, user_id]


def _delete_superseded_scores(conn, category, user_id, run_marker):
    """Drop the scope's rows this run did not rewrite, in committed slices.

    Every row the run wrote carries ``run_marker`` as its ``updated_at``, so what
    is left is exactly the photos that dropped out of the ranker and must stop
    sorting. Runs last, and only on rows the new scores did not replace, so an
    interrupted run leaves the PREVIOUS scores in place instead of a hole.
    """
    scope_sql, scope_params = _scope_clause(category, user_id)
    while True:
        deleted = conn.execute(
            f"""DELETE FROM learned_scores WHERE rowid IN (
                    SELECT rowid FROM learned_scores
                    WHERE {scope_sql} AND updated_at IS NOT ? LIMIT ?)""",
            (*scope_params, run_marker, _WRITE_CHUNK),
        ).rowcount
        conn.commit()
        if deleted < _WRITE_CHUNK:
            return


def _persist_scores(db_path, scored, category, user_id, n_pairs):
    """Percentile-normalize raw scores to 0-10 and write the (category, user) scope.

    Committed in _WRITE_CHUNK slices rather than one transaction: this runs on a
    background thread while the user is still rating, and SQLite's write lock is
    per database file, so one long transaction times out interactive writes. The
    cost is that a concurrent "My Taste" sort can observe a partially rebuilt
    table for a few seconds (missing rows read NULL and sink) — acceptable for an
    opt-in alternate sort, unlike failing the user's saves.

    New rows land first and the superseded ones are removed last, so the failure
    mode of a mid-run error is stale scores rather than missing ones: deleting
    the scope up front committed a hole that no later error could undo, and the
    caller (``optimization/auto_retrain._run_retrain``) swallows the exception.
    """
    if not scored:
        return 0
    raw = np.array([s for _, s in scored])
    order = np.argsort(np.argsort(raw))  # rank 0..n-1
    denom = max(1, len(raw) - 1)
    normalized = 10.0 * order / denom
    now = datetime.now(timezone.utc).isoformat()
    with get_connection(db_path) as conn:
        for start in range(0, len(scored), _WRITE_CHUNK):
            conn.executemany(
                """INSERT OR REPLACE INTO learned_scores
                   (photo_path, learned_score, comparison_count, category, updated_at, user_id)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    (path, float(normalized[start + i]), n_pairs, category, now, user_id)
                    for i, (path, _) in enumerate(scored[start:start + _WRITE_CHUNK])
                ],
            )
            conn.commit()
        _delete_superseded_scores(conn, category, user_id, now)
        if category is None and user_id is None:
            _mirror_learned_score(conn)
    return len(scored)


def _write_learned_scores(db_path, w, col_std, emb_dim, optimizer, category, user_id, n_pairs):
    """Score every embedded photo with the personal head and write learned_scores.

    Photos without an embedding of the trained dimension get no row (NULL → the
    opt-in sort skips them).
    """
    def raw_fn(row, emb):
        return _scaled_feature(row, emb, optimizer, category, col_std) @ w
    return _persist_scores(db_path, _collect_scored(db_path, emb_dim, raw_fn),
                           category, user_id, n_pairs)


def _write_prior_scores(db_path, prior, emb_dim, category, user_id, n_pairs):
    """Cold-start prior-only learned_scores: percentile-normalized prior head output."""
    return _persist_scores(
        db_path, _collect_scored(db_path, emb_dim, lambda row, emb: prior.mixed_score(emb)),
        category, user_id, n_pairs,
    )


def _write_blended_scores(db_path, prior, delta, col_std, emb_dim, optimizer,
                          category, user_id, n_pairs, lam):
    """Blend learned_scores: raw ``prior + lambda(n)·delta`` then a single percentile step."""
    def raw_fn(row, emb):
        feat = _scaled_feature(row, emb, optimizer, category, col_std)
        return prior.mixed_score(emb) + lam * float(feat @ delta)
    return _persist_scores(db_path, _collect_scored(db_path, emb_dim, raw_fn),
                           category, user_id, n_pairs)


def _dominant_photo_dim(db_path):
    """Most common embedding dimension across stored photos (byte length / 4), or None."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT length(clip_embedding) AS blob_len, COUNT(*) AS c FROM photos "
            "WHERE clip_embedding IS NOT NULL GROUP BY blob_len ORDER BY c DESC LIMIT 1"
        ).fetchone()
    if not row or not row['blob_len']:
        return None
    return int(row['blob_len']) // 4


def _train_prior_only(db_path, piaa, category, user_id, data, write):
    """Below MIN_COMPARISONS with the flag on: write prior-only scores, never nothing."""
    models_dir = piaa.get('models_dir', DEFAULT_MODELS_DIR)
    if data is not None and data.get('prior') is not None:
        prior, emb_dim, n = data['prior'], data['emb_dim'], data['n_pairs']
    else:
        emb_dim = _dominant_photo_dim(db_path)
        prior = PiaaPrior.load(emb_dim, models_dir) if emb_dim else None
        n = 0 if data is None else data['n_pairs']
    if prior is None:
        return {'error': f'no PIAA prior for dim {emb_dim}; cold start unavailable',
                'n_pairs': n}
    written = _write_prior_scores(db_path, prior, emb_dim, category, user_id, n) if write else 0
    result = {
        'n_pairs': n, 'emb_dim': emb_dim, 'mode': 'prior_only',
        'prior_version': prior.version, 'gated': False, 'written': written,
        'category': category, 'user_id': user_id,
    }
    _persist_ranker_metrics(db_path, category, user_id, result)
    logger.info("PIAA cold start: wrote %d prior-only learned_scores (prior %s, n=%d)",
                written, prior.version, n)
    return result
