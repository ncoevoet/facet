"""MPS unified-memory tests for GitHub discussion #159 (Apple Silicon RSS blowup).

Three independent fixes live here:

1. processing/multi_pass.py: on 'mps', ``clear_device_cache`` runs after EACH
   model in a pass group (not just once per group) so one model's freed
   activation buffers leave the shared pool before the next model allocates
   into it. CUDA/CPU keep the pre-existing once-per-group behaviour only.
2. models/pyiqa_scorer.py: ``score_batch`` caps each forward pass at
   ``MAX_FORWARD_BATCH`` instead of running the whole same-shape group (up to
   the full chunk) through one forward.
3. models/saliency_scorer.py: on a unified-memory device the batch-size
   ceiling is capped at a small constant, since psutil's "available" reading
   cannot see the MPS pool and the model runs fp32 there.
"""

from unittest import mock

import pytest

pytest.importorskip("torch")

from processing.multi_pass import ChunkedMultiPassProcessor  # noqa: E402


class _FakeModelManager:
    def __init__(self, device):
        self.device = device

    def load_model_only(self, name):
        return object()

    def unload_model(self, name, reclaim=False):
        pass

    def get_active_profile(self):
        return {}


def _make_processor(device, model_group):
    """A bare ChunkedMultiPassProcessor with everything except the pass loop stubbed out."""
    proc = ChunkedMultiPassProcessor.__new__(ChunkedMultiPassProcessor)
    proc.model_manager = _FakeModelManager(device)
    proc.pass_groups = [model_group]
    proc.restricted = True
    proc.metrics = {
        'io_time': 0.0,
        'model_load_time': 0.0,
        'inference_time': 0.0,
        'passes_executed': 0,
        'model_unload_time': 0.0,
    }
    proc._load_images = mock.MagicMock(return_value={})
    proc._load_pass_models = mock.MagicMock(
        return_value={name: object() for name in model_group}
    )
    proc._run_model_pass = mock.MagicMock()
    proc._record_chunk_pass_failure = mock.MagicMock()
    proc._save_results_restricted = mock.MagicMock()
    proc._compute_aggregates = mock.MagicMock()
    proc._save_results = mock.MagicMock()
    reclaim_calls = []
    proc._reclaim_freed_memory = lambda: reclaim_calls.append(1)
    proc._reclaim_calls = reclaim_calls
    return proc


class TestPerModelDeviceCacheClear:
    """Each model's freed activations must leave MPS unified memory before the next model runs."""

    def test_mps_clears_cache_once_per_model(self):
        model_group = ['clip', 'saliency', 'samp_net']
        proc = _make_processor('mps', model_group)
        with mock.patch('processing.multi_pass.clear_device_cache') as mock_clear:
            proc._process_chunk(['a.jpg'], 0, 1)
        # One call per model in the group (plus whatever the group-level
        # reclaim would separately trigger, which is stubbed out here).
        assert mock_clear.call_count == len(model_group)
        for call in mock_clear.call_args_list:
            assert call.args[0] == 'mps' or call.kwargs.get('device') == 'mps'

    def test_cuda_has_no_per_model_clears(self):
        model_group = ['clip', 'saliency', 'samp_net']
        proc = _make_processor('cuda', model_group)
        with mock.patch('processing.multi_pass.clear_device_cache') as mock_clear:
            proc._process_chunk(['a.jpg'], 0, 1)
        mock_clear.assert_not_called()

    def test_cpu_has_no_per_model_clears(self):
        model_group = ['clip', 'saliency', 'samp_net']
        proc = _make_processor('cpu', model_group)
        with mock.patch('processing.multi_pass.clear_device_cache') as mock_clear:
            proc._process_chunk(['a.jpg'], 0, 1)
        mock_clear.assert_not_called()

    def test_mps_clears_cache_even_when_a_model_raises(self):
        model_group = ['clip', 'saliency']
        proc = _make_processor('mps', model_group)

        def _raise_on_saliency(model_name, model, images, results):
            if model_name == 'saliency':
                raise RuntimeError("boom")

        proc._run_model_pass = mock.MagicMock(side_effect=_raise_on_saliency)
        with mock.patch('processing.multi_pass.clear_device_cache') as mock_clear:
            proc._process_chunk(['a.jpg'], 0, 1)
        assert mock_clear.call_count == len(model_group)
