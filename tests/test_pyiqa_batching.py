"""
Tests for real tensor batching in PyIQAScorer.score_batch (Topic 3 step 4).

pyiqa_scorer.py had no tests. We stub the underlying model with a deterministic,
per-sample-independent callable so the tests run on CPU without pyiqa/GPU, and
verify: a batchable model does ONE forward for same-size images and produces
results bit-identical to per-image scoring; a non-batchable model stays serial;
mismatched sizes split into per-shape forwards.
"""

import numpy as np
import pytest
from PIL import Image

# PyIQAScorer imports torch at module load; skip (don't error) where torch is
# absent, e.g. the lightweight CI test env.
pytest.importorskip("torch")

from models.pyiqa_scorer import PyIQAScorer


class _CountingModel:
    """Returns mean pixel intensity per image as a (B, 1) tensor; counts calls."""
    def __init__(self):
        self.calls = 0
        self.batch_sizes = []

    def __call__(self, batch):
        self.calls += 1
        self.batch_sizes.append(batch.shape[0])
        return batch.mean(dim=[1, 2, 3], keepdim=False).unsqueeze(1)


def _scorer(model_name):
    s = PyIQAScorer(model_name, device='cpu')
    s.model = _CountingModel()
    s._loaded = True
    return s


def _img(seed, size=(64, 64)):
    rng = np.random.RandomState(seed)
    arr = (rng.rand(size[1], size[0], 3) * 255).astype(np.uint8)
    return Image.fromarray(arr, 'RGB')


def test_batchable_single_forward_matches_serial():
    images = [_img(i) for i in range(5)]
    batched = _scorer('topiq')          # topiq is in _BATCHABLE_MODELS
    serial = _scorer('topiq')

    batched_scores = batched.score_batch(images)
    serial_scores = [serial.score_image(im) for im in images]

    assert batched.supports_batching is True
    assert batched.model.calls == 1                 # one stacked forward
    assert batched.model.batch_sizes == [5]
    assert serial.model.calls == 5                  # per-image
    for b, s in zip(batched_scores, serial_scores):
        assert abs(b - s) < 1e-4


def test_non_batchable_stays_serial():
    images = [_img(i) for i in range(4)]
    s = _scorer('musiq')                # musiq is resolution-sensitive -> serial
    scores = s.score_batch(images)
    assert s.supports_batching is False
    assert s.model.calls == 4           # one forward per image
    assert len(scores) == 4


def test_mixed_sizes_split_into_per_shape_forwards():
    images = [_img(0, (64, 64)), _img(1, (64, 64)), _img(2, (32, 48))]
    s = _scorer('topiq')
    scores = s.score_batch(images)
    assert len(scores) == 3
    # Two distinct shapes -> two forwards (one of size 2, one of size 1).
    assert s.model.calls == 2
    assert sorted(s.model.batch_sizes) == [1, 2]


def test_single_image_uses_serial_path():
    s = _scorer('topiq')
    scores = s.score_batch([_img(0)])
    assert len(scores) == 1
    assert s.model.calls == 1
