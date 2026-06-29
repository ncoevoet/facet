"""Tests for the zero-shot narrative-moment classifier (models/moment_classifier.py).

Uses synthetic embeddings + an injected prompt matrix, so no CLIP/SigLIP model
is loaded.
"""

import numpy as np

from models.moment_classifier import MomentClassifier, OTHER
from utils.embedding import embedding_to_bytes, bytes_to_embedding

_MOMENTS = ['family_formals', 'first_dance', 'vows']
# One prompt per moment, each a distinct unit axis in a 4-dim space.
_PROMPTS = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]]
_PROMPT_MOMENT_IDX = [0, 1, 2]


def _classifier(min_confidence=0.3, min_margin=0.05, priors_enabled=True, weight=0.04,
                moments=_MOMENTS, prompts=_PROMPTS, prompt_moment_idx=_PROMPT_MOMENT_IDX,
                signal_thresholds=None, pooling='max'):
    clf = object.__new__(MomentClassifier)
    clf.moments = list(moments)
    clf._index = {m: i for i, m in enumerate(moments)}
    clf.prompt_matrix = np.array(prompts, dtype=np.float32)
    clf.prompt_moment_idx = np.array(prompt_moment_idx, dtype=np.int64)
    clf.embedding_dim = clf.prompt_matrix.shape[1]
    clf.backend = 'transformers'
    clf.temperature = 0.05
    clf.pooling = pooling
    clf.thresholds = signal_thresholds or {
        'caption': (min_confidence, min_margin),
        'image': (min_confidence, min_margin),
    }
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
    clf = _classifier(min_confidence=0.5, min_margin=0.0)
    # Most of the mass sits on the 4th (non-moment) axis, so every moment cosine
    # stays below min_confidence -> 'other' via the confidence gate (not margin).
    label, _ = clf.classify(_emb([0.30, 0.29, 0.28, 0.80]))
    assert label == OTHER


def test_other_when_margin_too_small():
    clf = _classifier(min_confidence=0.1, min_margin=0.05)
    label, _ = clf.classify(_emb([0.50, 0.49, 0, 0]))  # margin ~0.01 < 0.05
    assert label == OTHER


def test_dimension_mismatch_skipped():
    clf = _classifier()
    label, conf = clf.classify(_emb([1, 0, 0, 0, 0]))  # 5-dim vs 4-dim matrix
    assert label is None and conf is None


def test_max_pool_per_moment():
    # Moment 'm0' has two prompts on orthogonal axes; max-pool must report the
    # best matching prompt (1.0), not the lower mean of the two.
    moments = ['m0', 'm1']
    prompts = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]]
    idx = [0, 0, 1]
    clf = _classifier(moments=moments, prompts=prompts, prompt_moment_idx=idx)
    scores = clf.scores(_emb([0, 1, 0, 0]))
    assert abs(scores['m0'] - 1.0) < 1e-6
    assert abs(scores['m1'] - 0.0) < 1e-6


def test_mean_pool_per_moment():
    # 'm0' has two prompts on orthogonal axes; mean-pool averages their cosines
    # (here (1.0 + 0.0)/2 = 0.5), unlike max-pool which would report 1.0.
    moments = ['m0', 'm1']
    prompts = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]]
    idx = [0, 0, 1]
    clf = _classifier(moments=moments, prompts=prompts, prompt_moment_idx=idx, pooling='mean')
    scores = clf.scores(_emb([0, 1, 0, 0]))
    assert abs(scores['m0'] - 0.5) < 1e-6
    assert abs(scores['m1'] - 0.0) < 1e-6


def test_signal_threshold_switch():
    # Same embedding: passes the loose caption gate but fails the strict image gate.
    clf = _classifier(priors_enabled=False,
                      signal_thresholds={'caption': (0.4, 0.0), 'image': (0.9, 0.0)})
    emb = _emb([0.5, 0.1, 0, 0])  # top cosine ~0.98 after normalization
    assert clf.classify(emb, signal='caption')[0] == 'family_formals'
    emb_low = _emb([0.5, 0.45, 0, 0])  # top cosine ~0.74 < image min_confidence
    assert clf.classify(emb_low, signal='image')[0] == OTHER


def test_caption_embedding_roundtrip():
    clf = _classifier(min_confidence=0.1, min_margin=0.0, priors_enabled=False)
    vec = np.array([0.0, 0.9, 0.1, 0.0], dtype=np.float32)
    blob = embedding_to_bytes(vec)
    assert bytes_to_embedding(blob).tolist() == vec.tolist()
    # A stored caption embedding scores the matching moment under the caption gate.
    assert clf.classify(blob, signal='caption')[0] == 'first_dance'


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
