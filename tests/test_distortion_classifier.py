"""Tests for the zero-shot distortion-attribute classifier (models/distortion_classifier.py).

Monkeypatches encode_text_prompts with deterministic vectors so no CLIP/SigLIP
model is loaded: attribute i's positive prompt maps to +e_i and its negative
prompt to -e_i in a small orthogonal space, making the pair-softmax exact.
"""

from types import SimpleNamespace

import numpy as np
import pytest

import models.distortion_classifier as dc
from models.distortion_classifier import (
    BUILTIN_ATTRIBUTES,
    DistortionClassifier,
    NEGATIVE_TEMPLATE,
    POSITIVE_TEMPLATE,
)
from utils.embedding import embedding_to_bytes

_DIM = 4
_VOCAB = {'motion_blur': 'motion blur', 'haze': 'haze', 'banding': 'color banding'}


def _fake_encode(model, model_name, backend, device, texts):
    """Deterministic prompt vectors: positive i -> +e_i, negative i -> -e_i."""
    n = len(texts) // 2
    vectors = np.zeros((len(texts), max(_DIM, n)), dtype=np.float32)
    for i in range(len(texts)):
        vectors[i, i % n] = 1.0 if i < n else -1.0
    return vectors


def _classifier(monkeypatch, backend='transformers', block=None, capture=None):
    def encode(model, model_name, enc_backend, device, texts):
        if capture is not None:
            capture.extend(texts)
        return _fake_encode(model, model_name, enc_backend, device, texts)

    monkeypatch.setattr(dc, 'encode_text_prompts', encode)
    config = SimpleNamespace(config={'distortion_attributes': block if block is not None
                                     else {'vocabulary': _VOCAB}})
    return DistortionClassifier(
        clip_model=None, device='cpu', config=config,
        model_name='fake', backend=backend, embedding_dim=_DIM,
    )


def _emb(vec):
    return embedding_to_bytes(np.array(vec, dtype=np.float32))


def test_exact_exiqa_template(monkeypatch):
    texts = []
    _classifier(monkeypatch, capture=texts)
    assert texts[0] == 'There is motion blur in the photo'
    assert texts[len(_VOCAB)] == 'There is not motion blur in the photo'
    assert POSITIVE_TEMPLATE.format(a='haze') == 'There is haze in the photo'
    assert NEGATIVE_TEMPLATE.format(a='haze') == 'There is not haze in the photo'


def test_pair_softmax(monkeypatch):
    clf = _classifier(monkeypatch)
    conf = clf.confidences(_emb([1, 0, 0, 0]))
    # cos_pos=1, cos_neg=-1 for motion_blur -> sigmoid(2/T) ~ 1.0
    assert conf['motion_blur'] > 0.99
    # Orthogonal attributes see cos_pos == cos_neg == 0 -> exactly 0.5
    assert conf['haze'] == pytest.approx(0.5)
    assert conf['banding'] == pytest.approx(0.5)


def test_thresholding_drops_uncertain_attributes(monkeypatch):
    clf = _classifier(monkeypatch)
    hits = clf.classify(_emb([1, 0, 0, 0]))
    # 0.5 confidences sit below the default 0.6 gate -> only motion_blur remains
    assert [h['attribute'] for h in hits] == ['motion_blur']
    assert hits[0]['confidence'] > 0.99


def test_top_n_cap_and_ordering(monkeypatch):
    block = {'vocabulary': _VOCAB, 'top_n': 2}
    clf = _classifier(monkeypatch, block=block)
    hits = clf.classify(_emb([3, 2, 1, 0]))
    assert len(hits) == 2
    assert [h['attribute'] for h in hits] == ['motion_blur', 'haze']
    assert hits[0]['confidence'] >= hits[1]['confidence']


def test_dim_mismatch_skipped(monkeypatch):
    clf = _classifier(monkeypatch)
    assert clf.confidences(_emb([1, 0, 0, 0, 0])) is None  # 5-dim vs 4-dim matrix
    assert clf.classify(_emb([1, 0, 0, 0, 0])) is None


def test_missing_or_zero_embedding_skipped(monkeypatch):
    clf = _classifier(monkeypatch)
    assert clf.confidences(None) is None
    assert clf.confidences(_emb([0, 0, 0, 0])) is None


def test_per_backend_thresholds(monkeypatch):
    block = {
        'vocabulary': _VOCAB,
        'thresholds': {
            'open_clip': {'temperature': 0.01, 'min_confidence': 0.7},
            'transformers': {'temperature': 0.1, 'min_confidence': 0.55},
        },
    }
    open_clip = _classifier(monkeypatch, backend='open_clip', block=block)
    transformers = _classifier(monkeypatch, backend='transformers', block=block)
    assert open_clip.temperature == pytest.approx(0.01)
    assert open_clip.min_confidence == pytest.approx(0.7)
    assert transformers.temperature == pytest.approx(0.1)
    assert transformers.min_confidence == pytest.approx(0.55)


def test_default_thresholds_mirror_backend_scales(monkeypatch):
    open_clip = _classifier(monkeypatch, backend='open_clip')
    transformers = _classifier(monkeypatch, backend='transformers')
    assert open_clip.temperature < transformers.temperature
    assert open_clip.min_confidence == transformers.min_confidence == pytest.approx(0.6)


def test_builtin_vocabulary_used_when_override_empty(monkeypatch):
    clf = _classifier(monkeypatch, block={'vocabulary': {}})
    assert clf.attributes == list(BUILTIN_ATTRIBUTES.keys())
    assert len(clf.attributes) == 16
