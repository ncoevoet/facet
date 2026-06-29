"""Tests for the zero-shot narrative-moment classifier (models/moment_classifier.py).

Uses synthetic embeddings + an injected moment matrix, so no CLIP/SigLIP model
is loaded.
"""

import numpy as np

from models.moment_classifier import MomentClassifier, OTHER
from utils.embedding import embedding_to_bytes

_MOMENTS = ['family_formals', 'first_dance', 'vows']
# Each moment is a distinct unit axis in a 4-dim space.
_MATRIX = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]]


def _classifier(min_confidence=0.3, min_margin=0.05, priors_enabled=True, weight=0.04):
    clf = object.__new__(MomentClassifier)
    clf.moments = list(_MOMENTS)
    clf._index = {m: i for i, m in enumerate(_MOMENTS)}
    clf.moment_matrix = np.array(_MATRIX, dtype=np.float32)
    clf.embedding_dim = clf.moment_matrix.shape[1]
    clf.backend = 'transformers'
    clf.temperature = 0.05
    clf.min_confidence = min_confidence
    clf.min_margin = min_margin
    clf.priors_cfg = {'enabled': priors_enabled, 'weight': weight}
    return clf


def _emb(vec):
    return embedding_to_bytes(np.array(vec, dtype=np.float32))


def test_argmax_label():
    clf = _classifier()
    label, conf = clf.classify(_emb([0.9, 0.1, 0, 0]))
    assert label == 'family_formals'
    assert conf > 0.5


def test_other_when_below_confidence():
    clf = _classifier(min_confidence=0.5)
    # All three axes near-equal and small -> top cosine below min_confidence.
    label, _ = clf.classify(_emb([0.30, 0.29, 0.28, 0]))
    assert label == OTHER


def test_other_when_margin_too_small():
    clf = _classifier(min_confidence=0.1, min_margin=0.05)
    label, _ = clf.classify(_emb([0.50, 0.49, 0, 0]))  # margin ~0.01 < 0.05
    assert label == OTHER


def test_dimension_mismatch_skipped():
    clf = _classifier()
    label, conf = clf.classify(_emb([1, 0, 0, 0, 0]))  # 5-dim vs 4-dim matrix
    assert label is None and conf is None


def test_group_portrait_prior_breaks_near_tie():
    clf = _classifier(min_margin=0.0)
    emb = _emb([0.70, 0.72, 0, 0])  # first_dance has the slightly higher cosine
    photo = {'face_count': 5, 'is_group_portrait': 1}

    clf.priors_cfg = {'enabled': False, 'weight': 0.04}
    assert clf.classify(emb, photo)[0] == 'first_dance'

    clf.priors_cfg = {'enabled': True, 'weight': 0.04}
    assert clf.classify(emb, photo)[0] == 'family_formals'


def test_probabilities_sum_to_one():
    clf = _classifier()
    moments, probs = clf.probabilities(_emb([0.9, 0.1, 0, 0]))
    assert moments == _MOMENTS
    assert probs is not None
    assert abs(float(probs.sum()) - 1.0) < 1e-6
