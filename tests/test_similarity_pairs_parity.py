"""The vectorized pair computation must return exactly what the old per-row
loop returned: every (i, j), i < j, whose cosine similarity reaches the
threshold — no more, no fewer, including borderline pairs at exactly the
threshold."""

import numpy as np

from api.similarity_groups import _similar_pairs


def _old_pairs(matrix, threshold):
    """The pre-refactor per-row loop, verbatim."""
    pairs = []
    n = len(matrix)
    for i in range(0, n, 500):
        sims = matrix[i:i + 500] @ matrix.T
        for ci in range(len(sims)):
            gi = i + ci
            for j in np.where(sims[ci, gi + 1:] >= threshold)[0] + gi + 1:
                pairs.append((gi, int(j)))
    return sorted(set(pairs))


def test_pairs_match_the_old_per_row_loop_exactly():
    rng = np.random.default_rng(42)
    matrix = rng.standard_normal((37, 64)).astype(np.float32)
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
    # A fixture with structure: a tight cluster, a chain, and outliers.
    matrix[0:5] = matrix[0] + rng.standard_normal((5, 64)) * 0.01
    matrix[0:5] /= np.linalg.norm(matrix[0:5], axis=1, keepdims=True)
    matrix[5] = matrix[4] + rng.standard_normal(64) * 0.02
    matrix[5] /= np.linalg.norm(matrix[5])

    for threshold in (0.0, 0.3, 0.85, 0.99):
        got = sorted({(int(a), int(b)) for a, b in _similar_pairs(matrix, threshold)})
        want = _old_pairs(matrix, threshold)
        assert got == want, f"threshold {threshold}: {len(got)} vs {len(want)}"


def test_cross_chunk_pairs_are_not_lost_at_the_chunk_boundary():
    # A 600-row matrix spans two 500-row chunks: pairs (499, 500+) sit exactly
    # at the boundary the per-chunk offset mask must keep.
    rng = np.random.default_rng(7)
    matrix = rng.standard_normal((600, 128)).astype(np.float32)
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
    matrix[499] = matrix[500]  # a cross-boundary exact pair
    matrix[499] /= np.linalg.norm(matrix[499])

    pairs = {(int(a), int(b)) for a, b in _similar_pairs(matrix, 0.9999)}
    assert (499, 500) in pairs


def test_single_row_matrix_returns_no_pairs():
    matrix = np.ones((1, 8), dtype=np.float32)
    assert list(_similar_pairs(matrix, 0.5)) == []
