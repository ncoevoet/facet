"""Tests for data-driven moment discovery (models/moment_discovery.py).

Uses synthetic, well-separated embedding clusters with distinctive captions, so
no model is loaded. Requires hdbscan + scikit-learn (both project deps).
"""

import numpy as np
import pytest

from models.moment_discovery import discover_moments, _slugify

pytest.importorskip("hdbscan")
pytest.importorskip("sklearn")

DIM = 12
PER = 25


def _synthetic():
    rng = np.random.default_rng(0)
    specs = [
        (0, "a sunny beach with waves and sand"),
        (1, "a mountain hiking trail in the alps"),
        (2, "a birthday cake celebration party"),
    ]
    embeddings, captions = [], []
    for axis, text in specs:
        for i in range(PER):
            v = np.zeros(DIM, dtype=np.float32)
            v[axis] = 1.0
            v += rng.normal(0, 0.03, DIM).astype(np.float32)
            v /= np.linalg.norm(v)
            embeddings.append(v)
            captions.append(f"{text} number {i}")
    return embeddings, captions


def test_discovers_three_clusters():
    embeddings, captions = _synthetic()
    clusters = discover_moments(embeddings, captions, min_cluster_size=8)
    assert len(clusters) == 3
    assert [c['size'] for c in clusters] == [PER, PER, PER]


def test_clusters_named_from_distinctive_keywords():
    embeddings, captions = _synthetic()
    clusters = discover_moments(embeddings, captions, min_cluster_size=8)
    blob = " ".join(c['name'] + " " + " ".join(c['keywords']) for c in clusters)
    # Each cluster is named from its own distinctive vocabulary (TF-IDF can pick
    # any of a topic's co-occurring terms, so check topic coverage, not one word).
    assert any(w in blob for w in ('beach', 'waves', 'sand', 'sunny'))
    assert any(w in blob for w in ('mountain', 'hiking', 'trail', 'alps'))
    assert any(w in blob for w in ('birthday', 'cake', 'celebration', 'party'))


def test_prompts_are_member_captions():
    embeddings, captions = _synthetic()
    caption_set = set(captions)
    for c in discover_moments(embeddings, captions, min_cluster_size=8):
        assert c['prompts']
        assert all(p in caption_set for p in c['prompts'])


def test_below_min_cluster_size_returns_empty():
    embeddings, captions = _synthetic()
    assert discover_moments(embeddings[:3], captions[:3], min_cluster_size=8) == []


def test_mixed_dims_kept_to_dominant():
    embeddings, captions = _synthetic()
    # Inject one rogue-dimension embedding; it must be dropped, not crash np.vstack.
    embeddings = list(embeddings) + [np.ones(DIM + 1, dtype=np.float32)]
    captions = list(captions) + ["an odd dimension caption"]
    clusters = discover_moments(embeddings, captions, min_cluster_size=8)
    assert len(clusters) == 3


def test_names_are_unique_slugs():
    embeddings, captions = _synthetic()
    names = [c['name'] for c in discover_moments(embeddings, captions, min_cluster_size=8)]
    assert len(names) == len(set(names))
    assert all(n == _slugify(n, n) for n in names)
