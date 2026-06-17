"""
Unit tests for the two-stage near-duplicate gate (utils/duplicate.py),
Topic 4 steps 1-2.

Stage 1: loose pHash Hamming candidates. Stage 2: SigLIP/CLIP cosine gate.
A pair that is a strong pHash candidate but has low embedding cosine must NOT
be merged; a DB with no embeddings must reproduce the original pHash-only groups.
"""

import numpy as np

from utils.duplicate import _two_stage_union, _build_embedding_matrix
from utils.embedding import embedding_to_bytes


MAX_D = 6           # strict pHash-only gate (~90% similarity)
PREFILTER = 12      # loose stage-1 gate
COS = 0.90          # stage-2 cosine gate


def _norm(v):
    v = np.asarray(v, dtype=np.float32)
    return v / np.linalg.norm(v)


# hashes with controlled Hamming distances to h0 = 0, with set bits in DISJOINT
# regions so the only candidate links are the intended ones (no transitive bridge):
#   h1 = 0b111            -> Hamming 3   (strict candidate)
#   h2 = 0xFF << 32       -> Hamming 8   (loose-only candidate: 6 < 8 <= 12)
#   h3 = 0x1FFFF << 40    -> Hamming 17  (beyond prefilter, never a candidate)
# Cross distances are all > prefilter except h1~h2 (=11) which the cosine gate handles.
_HASHES = np.array([0, 0b111, 0xFF << 32, 0x1FFFF << 40], dtype=np.uint64)


def _matrix(vecs):
    matrix, has_emb = _build_embedding_matrix([embedding_to_bytes(_norm(v)) for v in vecs])
    return matrix, has_emb


def test_high_phash_low_cosine_not_merged():
    """h0~h1 are near-identical pHash but orthogonal embeddings -> NOT merged."""
    # e0 vs e1 orthogonal (cos 0); e2 == e0 (cos 1)
    matrix, has_emb = _matrix([[1, 0, 0, 0], [0, 1, 0, 0], [1, 0, 0, 0], [0, 0, 1, 0]])
    uf = _two_stage_union(_HASHES, matrix, has_emb, MAX_D, PREFILTER, COS)
    assert uf.find(0) != uf.find(1)   # strong pHash, low cosine -> rejected (precision)
    assert uf.find(0) == uf.find(2)   # loose pHash (8) + cosine 1.0 -> merged (recall)
    assert uf.find(0) != uf.find(3)   # Hamming 17 > prefilter -> never a candidate


def test_high_phash_high_cosine_merged():
    """h0~h1 near-identical pHash AND near-identical embedding -> merged."""
    matrix, has_emb = _matrix([[1, 0, 0, 0], [0.99, 0.01, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]])
    uf = _two_stage_union(_HASHES, matrix, has_emb, MAX_D, PREFILTER, COS)
    assert uf.find(0) == uf.find(1)


def test_missing_embedding_falls_back_to_strict_phash():
    """If either photo lacks an embedding, the strict pHash gate decides."""
    # Only h0 has an embedding; h1 (Hamming 3, strict) and h2 (Hamming 8, loose) lack one.
    matrix, has_emb = _build_embedding_matrix([
        embedding_to_bytes(_norm([1, 0, 0, 0])), None, None, None,
    ])
    uf = _two_stage_union(_HASHES, matrix, has_emb, MAX_D, PREFILTER, COS)
    assert uf.find(0) == uf.find(1)   # Hamming 3 <= strict 6 -> merged on pHash alone
    assert uf.find(0) != uf.find(2)   # Hamming 8 > strict 6 -> not merged (no loose gate without both embeddings)


def test_no_embeddings_identical_to_pure_phash():
    """With no embeddings at all, groups match the original pHash-only detector."""
    matrix, has_emb = _build_embedding_matrix([None, None, None, None])
    assert matrix is None and not has_emb.any()
    uf = _two_stage_union(_HASHES, matrix, has_emb, MAX_D, PREFILTER, COS)
    # Pure pHash <= 6: only h0~h1 (Hamming 3) group together.
    assert uf.find(0) == uf.find(1)
    assert uf.find(0) != uf.find(2)
    assert uf.find(0) != uf.find(3)


def test_build_embedding_matrix_drops_minority_dim():
    """Mixed-dimension DBs keep the dominant dim; the odd one out is marked absent."""
    a = embedding_to_bytes(_norm([1, 0, 0, 0]))
    b = embedding_to_bytes(_norm([0, 1, 0, 0]))
    odd = embedding_to_bytes(_norm([1, 2, 3]))   # dim 3, minority
    matrix, has_emb = _build_embedding_matrix([a, b, odd])
    assert matrix.shape == (3, 4)
    assert has_emb.tolist() == [True, True, False]


def test_evaluate_dedup_thresholds_precision_recall():
    from utils.duplicate import evaluate_dedup_thresholds
    # 3 true dups at high cosine, 2 non-dups at low cosine.
    pairs = [(0.97, True), (0.95, True), (0.91, True), (0.70, False), (0.60, False)]
    res = {r['threshold']: r for r in evaluate_dedup_thresholds(pairs, [0.90, 0.96])}
    # At 0.90: all 3 dups predicted, no false positives -> perfect.
    assert res[0.90]['precision'] == 1.0 and res[0.90]['recall'] == 1.0
    # At 0.96: only the 0.97 dup predicted -> precision 1.0, recall 1/3.
    assert res[0.96]['tp'] == 1 and res[0.96]['fn'] == 2
    assert res[0.96]['precision'] == 1.0
    assert round(res[0.96]['recall'], 2) == 0.33
