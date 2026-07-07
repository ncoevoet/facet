#!/usr/bin/env python
"""Offline fitter for the PIAA cold-start prior heads.

Consumes one cached-embedding ``.npz`` per public-IAA dataset and fits K linear
heads — one Ridge head per dataset plus a few k-means taste-cluster heads over
the pooled embeddings — then writes a versioned
``pretrained_models/piaa_prior_<dim>.npz`` (see ``models/piaa_prior.py``).

Embedding-cache contract (one file per dataset)::

    embeddings : float32 (N, dim), L2 unit-normalized, same backbone Facet uses
    scores     : float   (N,),     aesthetic target (mean opinion score / rating)

Pure CPU (numpy + scikit-learn). The fitter NEVER embeds images itself — a
separate pipeline produces the caches. Deterministic: Ridge is closed-form and
``RNG_SEED = 42`` fixes k-means, so re-running on the same caches yields byte-
identical head weights.

Objective — **Ridge on per-dataset z-scored targets**. Rationale: Ryu & Yanaka
(ACL 2026 Findings) show linear heads over frozen features do PIAA well; Ridge is
the closed-form, deterministic L2 linear fit (no RNG, no solver seed to pin), and
z-scoring each dataset's targets puts every head on a comparable scale so the
uniform default mix is meaningful. A pairwise-logistic rank head is a later
upgrade only if the experiment shows ridge underperforms.

Example::

    venv/bin/python scripts/fit_piaa_prior.py \
        caches/ava_768.npz caches/tad66k_768.npz \
        --dim 768 --clusters 2 --alpha 1.0 --version v1 \
        --out pretrained_models/piaa_prior_768.npz
"""

import argparse
import os
import sys
from datetime import datetime, timezone

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.piaa_prior import prior_path, save_prior  # noqa: E402

RNG_SEED = 42
MAX_HEADS = 6
MIN_CLUSTER_SAMPLES = 50


def _unit_normalize(emb):
    """Defensively L2-normalize rows (the cache contract already promises this)."""
    norms = np.linalg.norm(emb, axis=1, keepdims=True)
    norms[norms < 1e-10] = 1.0
    return emb / norms


def _load_cache(path, dim):
    data = np.load(path, allow_pickle=False)
    emb = np.asarray(data["embeddings"], dtype=np.float64)
    scores = np.asarray(data["scores"], dtype=np.float64).ravel()
    if emb.ndim != 2:
        raise ValueError(f"{path}: 'embeddings' must be 2-D, got {emb.shape}")
    if emb.shape[0] != scores.shape[0]:
        raise ValueError(
            f"{path}: {emb.shape[0]} embeddings vs {scores.shape[0]} scores"
        )
    if emb.shape[1] != dim:
        raise ValueError(f"{path}: embedding dim {emb.shape[1]} != --dim {dim}")
    return _unit_normalize(emb), scores


def _zscore(scores):
    std = scores.std()
    if std < 1e-9:
        return np.zeros_like(scores)
    return (scores - scores.mean()) / std


def _fit_ridge_head(emb, z, alpha):
    from sklearn.linear_model import Ridge

    model = Ridge(alpha=alpha, fit_intercept=True)
    model.fit(emb, z)
    return model.coef_.astype(np.float64), float(model.intercept_)


def fit_prior(caches, dim, clusters, alpha, version):
    """Fit the heads and return (weights (K,dim), bias (K,), head_names, meta)."""
    datasets = []
    all_emb, all_z = [], []
    for path in caches:
        name = os.path.splitext(os.path.basename(path))[0]
        emb, scores = _load_cache(path, dim)
        z = _zscore(scores)
        datasets.append((name, emb, z))
        all_emb.append(emb)
        all_z.append(z)

    weights, bias, names = [], [], []

    for name, emb, z in datasets:
        coef, intercept = _fit_ridge_head(emb, z, alpha)
        weights.append(coef)
        bias.append(intercept)
        names.append(f"dataset:{name}")

    pooled_emb = np.concatenate(all_emb, axis=0)
    pooled_z = np.concatenate(all_z, axis=0)

    remaining = MAX_HEADS - len(weights)
    n_clusters = max(0, min(clusters, remaining))
    if n_clusters >= 1 and pooled_emb.shape[0] >= MIN_CLUSTER_SAMPLES * n_clusters:
        from sklearn.cluster import KMeans

        km = KMeans(n_clusters=n_clusters, random_state=RNG_SEED, n_init=10)
        labels = km.fit_predict(pooled_emb)
        for c in range(n_clusters):
            mask = labels == c
            if mask.sum() < MIN_CLUSTER_SAMPLES:
                continue
            coef, intercept = _fit_ridge_head(pooled_emb[mask], pooled_z[mask], alpha)
            weights.append(coef)
            bias.append(intercept)
            names.append(f"cluster:{c}")

    meta = {
        "version": version,
        "dim": int(dim),
        "datasets": [n for (n, _, _) in datasets],
        "objective": "ridge",
        "alpha": float(alpha),
        "clusters": int(n_clusters),
        "seed": RNG_SEED,
        "fit_date": datetime.now(timezone.utc).isoformat(),
    }
    return np.asarray(weights), np.asarray(bias), names, meta


def main():
    parser = argparse.ArgumentParser(description="Fit PIAA cold-start prior heads.")
    parser.add_argument("caches", nargs="+",
                        help="one embedding-cache .npz per public-IAA dataset")
    parser.add_argument("--dim", type=int, required=True,
                        help="embedding dimension (768 = CLIP ViT-L, 1152 = SigLIP2)")
    parser.add_argument("--clusters", type=int, default=2,
                        help="number of k-means taste-cluster heads to add")
    parser.add_argument("--alpha", type=float, default=1.0, help="Ridge L2 strength")
    parser.add_argument("--version", default="v1", help="prior version tag stored in metadata")
    parser.add_argument("--out", default=None, help="output .npz (default: pretrained_models/piaa_prior_<dim>.npz)")
    args = parser.parse_args()

    weights, bias, names, meta = fit_prior(
        args.caches, args.dim, args.clusters, args.alpha, args.version,
    )
    out = args.out or prior_path(args.dim)
    save_prior(out, weights, bias, names, meta)
    print(f"Wrote {out}: {len(names)} heads {names} (version={args.version}, dim={args.dim})")


if __name__ == "__main__":
    main()
