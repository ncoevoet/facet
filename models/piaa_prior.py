"""PIAA cold-start prior heads over frozen embeddings.

Small **linear** heads (one Ridge head per public-IAA dataset plus a few
k-means taste-cluster heads), fit offline on cached public-aesthetic embeddings
and shipped as a per-dim ``.npz`` (``pretrained_models/piaa_prior_<dim>.npz``).
A photo scored under the wrong-dim prior is meaningless, so the loader keys
strictly on the embedding dimension (768 = CLIP ViT-L, 1152 = SigLIP2) and never
crosses dims. Scoring is a single matmul over the stored unit-normalized
embedding — no image decode, no backbone pass.

A missing prior file is not an error on the scan path: ``PiaaPrior.load`` returns
``None`` and the caller falls back to its prior-free behaviour.
"""

import json
import logging
import os

import numpy as np

logger = logging.getLogger("facet.piaa_prior")

DEFAULT_MODELS_DIR = "pretrained_models"


def prior_path(dim, models_dir=DEFAULT_MODELS_DIR):
    """Canonical on-disk path for a per-dim prior."""
    return os.path.join(models_dir, f"piaa_prior_{int(dim)}.npz")


def save_prior(path, weights, bias, head_names, meta, default_mix=None):
    """Write a prior ``.npz``. The fitter passes ``meta`` (version/datasets/fit_date);
    scoring never fabricates metadata. ``default_mix`` defaults to uniform over heads.
    """
    weights = np.asarray(weights, dtype=np.float32)
    bias = np.asarray(bias, dtype=np.float32)
    k = int(weights.shape[0])
    mix = (np.full(k, 1.0 / k, dtype=np.float32)
           if default_mix is None else np.asarray(default_mix, dtype=np.float32))
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    np.savez(
        path,
        weights=weights,
        bias=bias,
        head_names=np.asarray([str(n) for n in head_names]),
        default_mix=mix,
        meta=np.asarray(json.dumps(meta)),
    )


class PiaaPrior:
    """K frozen linear heads over a unit-normalized embedding of one dimension."""

    def __init__(self, weights, bias, head_names, default_mix, meta):
        self.weights = np.asarray(weights, dtype=np.float64)
        self.bias = np.asarray(bias, dtype=np.float64)
        self.head_names = [str(n) for n in head_names]
        self.default_mix = np.asarray(default_mix, dtype=np.float64)
        self.meta = dict(meta)

    @property
    def dim(self):
        return int(self.weights.shape[1])

    @property
    def k(self):
        return int(self.weights.shape[0])

    @property
    def version(self):
        return str(self.meta.get("version", "unknown"))

    @classmethod
    def load_file(cls, path):
        """Load a prior from an explicit ``.npz`` path, or ``None`` if missing/unreadable."""
        if not os.path.exists(path):
            return None
        try:
            data = np.load(path, allow_pickle=False)
            meta = json.loads(data["meta"].item())
            return cls(
                data["weights"], data["bias"],
                list(data["head_names"]), data["default_mix"], meta,
            )
        except Exception:
            logger.warning("Failed to load PIAA prior at %s", path, exc_info=True)
            return None

    @classmethod
    def load(cls, dim, models_dir=DEFAULT_MODELS_DIR):
        """Load the prior for ``dim`` or return ``None`` (no file / unreadable / dim mismatch)."""
        prior = cls.load_file(prior_path(dim, models_dir))
        if prior is None:
            return None
        if prior.dim != int(dim):
            logger.warning(
                "PIAA prior has dim %d, expected %d — ignoring", prior.dim, int(dim),
            )
            return None
        return prior

    def score(self, embeddings):
        """Per-head raw scores: unit-normalized ``embeddings`` (N, dim) -> (N, K)."""
        emb = np.asarray(embeddings, dtype=np.float64)
        if emb.ndim == 1:
            emb = emb[None, :]
        return emb @ self.weights.T + self.bias

    def mixed_score(self, embeddings, mix=None):
        """Single prior score per photo: head scores combined by ``mix`` (default uniform).

        Returns a python float for a single 1-D embedding, else an (N,) array.
        """
        m = self.default_mix if mix is None else np.asarray(mix, dtype=np.float64)
        single = np.asarray(embeddings).ndim == 1
        s = self.score(embeddings) @ m
        return float(s[0]) if single else s
