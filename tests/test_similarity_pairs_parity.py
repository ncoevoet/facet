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


def _boundary_matrix():
    rng = np.random.default_rng(84)
    matrix = rng.standard_normal((600, 128)).astype(np.float32)
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
    matrix[499] = matrix[500]
    matrix[598] = matrix[599]
    return matrix


def _cpu_tensors_for_cuda_loop(monkeypatch):
    """Exercise CUDA dispatch with real CPU torch ops; not a CUDA hardware test."""
    import pytest
    import api.similarity_groups as groups
    torch = pytest.importorskip('torch')
    original_to = torch.Tensor.to

    def cpu_to(self, device, *args, **kwargs):
        assert str(device) == 'cuda'
        return original_to(self, 'cpu', *args, **kwargs)

    monkeypatch.setattr(groups, '_cuda_available', lambda: True)
    monkeypatch.setattr(torch.Tensor, 'to', cpu_to)
    return torch


def test_cuda_dispatch_bounds_score_blocks_and_transfers_only_pair_indices(monkeypatch):
    torch = _cpu_tensors_for_cuda_loop(monkeypatch)
    sizes = []
    transfers = []
    original_matmul = torch.Tensor.__matmul__
    original_cpu = torch.Tensor.cpu

    def matmul(self, other):
        sizes.append((tuple(self.shape), tuple(other.shape)))
        return original_matmul(self, other)

    def cpu(self, *args, **kwargs):
        transfers.append((self.dtype, tuple(self.shape)))
        return original_cpu(self, *args, **kwargs)

    monkeypatch.setattr(torch.Tensor, '__matmul__', matmul)
    monkeypatch.setattr(torch.Tensor, 'cpu', cpu)
    matrix = _boundary_matrix()
    pairs = list(_similar_pairs(matrix, 0.9999))
    assert pairs == [(499, 500), (598, 599)]
    assert sizes == [((500, 128), (128, 600)), ((100, 128), (128, 600))]
    assert transfers == [(torch.int64, (1, 2)), (torch.int64, (1, 2))]


def test_cuda_oom_during_transfer_falls_back_to_cpu(monkeypatch):
    torch = _cpu_tensors_for_cuda_loop(monkeypatch)

    def oom(*args, **kwargs):
        raise torch.OutOfMemoryError('injected transfer OOM')

    monkeypatch.setattr(torch.Tensor, 'to', oom)
    matrix = _boundary_matrix()
    assert list(_similar_pairs(matrix, 0.9999)) == _old_pairs(matrix, 0.9999)


def test_cuda_oom_after_one_block_resumes_without_repeating_pairs(monkeypatch, caplog):
    torch = _cpu_tensors_for_cuda_loop(monkeypatch)
    original = torch.Tensor.__matmul__
    calls = []

    def matmul(self, other):
        calls.append(tuple(self.shape))
        if len(calls) == 2:
            raise torch.OutOfMemoryError('injected later-block OOM')
        return original(self, other)

    monkeypatch.setattr(torch.Tensor, '__matmul__', matmul)
    matrix = _boundary_matrix()
    pairs = list(_similar_pairs(matrix, 0.9999))
    assert len(calls) == 2
    assert pairs == [(499, 500), (598, 599)]
    assert len(pairs) == len(set(pairs))
    assert 'CPU' in caplog.text


def test_cuda_non_memory_errors_are_not_hidden(monkeypatch):
    import pytest
    torch = _cpu_tensors_for_cuda_loop(monkeypatch)

    def broken(self, other):
        raise RuntimeError('injected unrelated CUDA failure')

    monkeypatch.setattr(torch.Tensor, '__matmul__', broken)
    with pytest.raises(RuntimeError, match='unrelated CUDA failure'):
        list(_similar_pairs(_boundary_matrix(), 0.9999))


def test_real_cuda_cross_block_pairs(monkeypatch, record_property):
    import pytest
    import api.similarity_groups as groups
    torch = pytest.importorskip('torch')
    if not torch.cuda.is_available():
        pytest.skip('requires a real CUDA device and CUDA-enabled torch')
    monkeypatch.setattr(groups, '_cuda_available', lambda: True)
    torch.cuda.reset_peak_memory_stats()
    pairs = list(_similar_pairs(_boundary_matrix(), 0.9999))
    torch.cuda.synchronize()
    assert pairs == [(499, 500), (598, 599)]
    record_property('cuda_peak_allocated_bytes', torch.cuda.max_memory_allocated())


def test_cpu_only_process_never_imports_torch():
    import subprocess
    import sys
    code = (
        "import sys, numpy as np\n"
        "from api.similarity_groups import _similar_pairs\n"
        "m = np.eye(4, dtype='float32')\n"
        "list(_similar_pairs(m, 0.5))\n"
        "assert 'torch' not in sys.modules, 'similarity imported torch'\n"
    )
    subprocess.run([sys.executable, '-c', code], check=True)


def test_facet_device_cpu_keeps_similarity_off_cuda(monkeypatch):
    import pytest
    import api.similarity_groups as groups
    torch = pytest.importorskip('torch')
    monkeypatch.setattr(torch.cuda, 'is_available', lambda: True)
    monkeypatch.setattr(torch.cuda, 'device_count', lambda: 1)
    monkeypatch.setenv('FACET_DEVICE', 'cpu')
    assert groups._cuda_available() is False


def test_cuda_context_oom_falls_back_to_cpu(monkeypatch):
    torch = _cpu_tensors_for_cuda_loop(monkeypatch)

    def oom(*args, **kwargs):
        raise RuntimeError('CUDA error: out of memory')

    monkeypatch.setattr(torch.Tensor, 'to', oom)
    matrix = _boundary_matrix()
    assert list(_similar_pairs(matrix, 0.9999)) == _old_pairs(matrix, 0.9999)
