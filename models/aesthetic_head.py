"""CLIP-MLP aesthetic head (LAION improved-aesthetic-predictor).

The single definition of this model. It previously existed twice — once here in
the shape the checkpoint actually has, once in the scorer as a 768->256->1 stub
loaded with ``strict=False`` — and the stub silently matched none of the
checkpoint's tensors, so ``legacy``/``8gb`` scans scored every photo with an
untrained head.

Contract, both halves of which the checkpoint depends on:

* input is the **L2-normalized** 768-dim ViT-L-14 embedding. Raw CLIP features
  have an L2 norm around 19, and feeding those saturates half the library at the
  top of the scale.
* output is an AVA-style 1-10 rating, so Facet's 0-10 aesthetic column is that
  value clamped — not rescaled.
"""

import logging

import numpy as np
import torch
import torch.nn as nn

from models.weights import (
    AESTHETIC_MLP_WEIGHTS_SHA256, AESTHETIC_MLP_WEIGHTS_URL, download_weights, pretrained_model_path,
)

logger = logging.getLogger("facet.models")

AESTHETIC_HEAD_WEIGHTS_FILENAME = 'aesthetic_predictor_weights.pth'
AESTHETIC_HEAD_EMBEDDING_DIM = 768
AESTHETIC_SCORE_MIN = 0.0
AESTHETIC_SCORE_MAX = 10.0


class AestheticMLP(nn.Module):
    """The predictor's architecture, matching the checkpoint's ``layers.*`` keys."""

    def __init__(self, input_size: int = AESTHETIC_HEAD_EMBEDDING_DIM):
        super().__init__()
        self.layers = nn.Sequential(
            nn.Linear(input_size, 1024),
            nn.Dropout(0.2),
            nn.Linear(1024, 128),
            nn.Dropout(0.2),
            nn.Linear(128, 64),
            nn.Dropout(0.1),
            nn.Linear(64, 16),
            nn.Linear(16, 1),
        )

    def forward(self, x):
        return self.layers(x)


def load_aesthetic_head(device: str = 'cpu') -> AestheticMLP:
    """Build the head and load its checkpoint strictly.

    ``strict=True`` because a partially-loaded head produces plausible-looking
    scores from untrained weights: a scan that stops is recoverable, a library
    scored with noise is not.
    """
    weights_path = pretrained_model_path(AESTHETIC_HEAD_WEIGHTS_FILENAME)
    if not weights_path.exists():
        download_weights(AESTHETIC_MLP_WEIGHTS_URL, weights_path, sha256=AESTHETIC_MLP_WEIGHTS_SHA256)

    head = AestheticMLP()
    state_dict = torch.load(weights_path, map_location=device, weights_only=True)
    try:
        head.load_state_dict(state_dict, strict=True)
    except RuntimeError as ex:
        raise RuntimeError(
            f"Aesthetic head checkpoint at {weights_path} does not match the model: {ex}. "
            f"Delete the file to re-download it."
        ) from ex

    logger.info("CLIP-MLP aesthetic head loaded: %s", weights_path)
    return head.to(device).eval()


def score_aesthetic(head, features_normalized) -> np.ndarray:
    """Score L2-normalized CLIP embeddings, clamped to Facet's 0-10 scale."""
    with torch.no_grad():
        raw = head(features_normalized.float()).cpu().numpy().flatten()
    return np.clip(raw, AESTHETIC_SCORE_MIN, AESTHETIC_SCORE_MAX)
