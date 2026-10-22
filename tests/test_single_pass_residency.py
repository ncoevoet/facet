"""A single-pass plan keeps its models in VRAM across chunk boundaries.

``_process_chunk`` unloaded every pass group after every chunk. For a plan that
fits in one group that meant moving the whole roster off the card
(``ModelManager.unload_model`` -> ``_move_to_cpu``) and copying it back at the
next chunk's first load (``load_model_only`` -> ``_restore_from_cache`` ->
``.to(device)``): every weight crossed PCIe twice per chunk, and the host held a
second copy of it beside the next chunk's decode. The pass had already held all
of those models at once before its inference, so the boundary reached no VRAM
level the chunk had not reached — the cost bought nothing.

Scope of the retention (``_keeps_plan_resident``): a one-group plan on CUDA
only. A multi-group plan still unloads, because the planner split it precisely
because those models do not fit together; CPU and MPS keep their RAM-cache
admission rules; and ``models.keep_in_ram: "never"`` still gives the memory back
between chunks.
"""

import logging
import types
from unittest import mock

import pytest

from processing.multi_pass import ChunkedMultiPassProcessor


class _Manager:
    """Records load/unload, mirroring ``ModelManager``'s resident short-circuit."""

    def __init__(self, device='cuda', keep_in_ram='auto', fail_once=()):
        self.device = device
        self.keep_in_ram = keep_in_ram
        self.profile = {}
        self.models = {}
        self.events = []
        self._fail_once = set(fail_once)
        self._cache_hits = 0
        self._cache_misses = 0

    def detect_vram(self):
        return 16.0

    def get_active_profile(self):
        return self.profile

    def load_model_only(self, name):
        if name in self.models:
            self.events.append(('reuse', name))
            return self.models[name]
        if name in self._fail_once:
            self._fail_once.discard(name)
            self.events.append(('load-failed', name))
            return None
        self.events.append(('load', name))
        self.models[name] = object()
        return self.models[name]

    def unload_model(self, name, reclaim=True):
        self.events.append(('unload', name))
        self.models.pop(name, None)


class _Scorer:
    config = types.SimpleNamespace()

    def flush_person_centroids(self):
        pass


def _processor(manager, pass_groups, monkeypatch, restricted=False):
    """A chunk processor whose only real work is the load/infer/unload cycle."""
    with mock.patch("processing.multi_pass._ensure_imports"):
        proc = ChunkedMultiPassProcessor(_Scorer(), manager, {})
    proc.pass_groups = pass_groups
    proc.restricted = restricted
    proc._decode_executor = None  # the chunk decodes synchronously
    monkeypatch.setattr(
        proc, '_load_images',
        lambda paths: {p: {'pil': None, 'width': 100, 'height': 100} for p in paths})
    monkeypatch.setattr(proc, '_run_model_pass',
                        lambda name, model, images, results: manager.events.append(('infer', name)))
    monkeypatch.setattr(proc, '_compute_aggregates', lambda results, images: None)
    monkeypatch.setattr(proc, '_save_results', lambda results, images: None)
    monkeypatch.setattr(proc, '_save_results_restricted', lambda results, images: None)
    return proc


def _count(events, kind, name=None):
    return sum(1 for event in events
               if event[0] == kind and (name is None or event[1] == name))


class TestSinglePassKeepsItsGroup:
    """The one group a single-pass plan runs is the next chunk's first group."""

    def test_models_load_once_and_are_never_unloaded_between_chunks(self, monkeypatch):
        manager = _Manager()
        proc = _processor(manager, [['clip', 'topiq']], monkeypatch)

        for chunk_idx in range(3):
            proc._process_chunk(['/p/a.jpg'], chunk_idx, 3)

        assert _count(manager.events, 'load') == 2, "each model is read once for the scan"
        assert _count(manager.events, 'unload') == 0, "nothing is unloaded between chunks"
        assert _count(manager.events, 'reuse') == 4, "both models are reused by chunks 1 and 2"
        assert _count(manager.events, 'infer') == 6, "every chunk still runs every pass"
        assert proc.metrics['resident_chunks'] == 2
        assert proc.metrics['passes_executed'] == 3
        assert proc.metrics['model_unload_time'] == 0

    def test_the_models_are_still_in_the_manager_for_the_next_chunk(self, monkeypatch):
        manager = _Manager()
        proc = _processor(manager, [['clip']], monkeypatch)

        proc._process_chunk(['/p/a.jpg'], 0, 2)

        assert set(manager.models) == {'clip'}

    def test_the_whole_scan_still_loads_and_unloads_nothing_extra(self, monkeypatch):
        """A one-chunk scan loads each model once, infers once, and unloads nothing."""
        manager = _Manager()
        proc = _processor(manager, [['clip', 'topiq']], monkeypatch)

        proc._process_chunk(['/p/a.jpg'], 0, 1)

        assert manager.events == [
            ('load', 'clip'), ('load', 'topiq'),
            ('infer', 'clip'), ('infer', 'topiq'),
        ]

    def test_the_summary_says_how_many_chunks_reused_the_group(self, monkeypatch, caplog):
        manager = _Manager()
        proc = _processor(manager, [['clip']], monkeypatch)

        for chunk_idx in range(3):
            proc._process_chunk(['/p/a.jpg'], chunk_idx, 3)
        # process_directory owns these two counters; _process_chunk was driven directly
        proc.metrics['chunks_processed'] = 3
        proc.metrics['images_processed'] = 3
        proc.metrics['total_time'] = 1.0

        with caplog.at_level(logging.INFO):
            proc._print_summary()

        assert "Resident weights: 2 of 3 chunks reused the kept single-pass models" in caplog.text


class TestTheRetentionIsBounded:
    """Every other shape keeps today's per-chunk lifecycle."""

    def test_a_multi_group_plan_still_unloads_every_group_per_chunk(self, monkeypatch):
        manager = _Manager()
        proc = _processor(manager, [['clip'], ['insightface']], monkeypatch)

        for chunk_idx in range(2):
            proc._process_chunk(['/p/a.jpg'], chunk_idx, 2)

        assert _count(manager.events, 'load') == 4
        assert _count(manager.events, 'unload') == 4
        assert proc.metrics['resident_chunks'] == 0

    def test_keep_in_ram_never_still_gives_the_weights_back(self, monkeypatch):
        """The documented escape hatch: the card is free between chunks."""
        manager = _Manager(keep_in_ram='never')
        proc = _processor(manager, [['clip']], monkeypatch)

        for chunk_idx in range(2):
            proc._process_chunk(['/p/a.jpg'], chunk_idx, 2)

        assert _count(manager.events, 'load') == 2
        assert _count(manager.events, 'unload') == 2
        assert proc.metrics['resident_chunks'] == 0

    @pytest.mark.parametrize('device', ['cpu', 'mps'])
    def test_cpu_and_mps_keep_their_ram_cache_lifecycle(self, device, monkeypatch):
        """Only CUDA has a pool to keep the weights in; these plan against RAM."""
        manager = _Manager(device=device)
        proc = _processor(manager, [['clip']], monkeypatch)

        for chunk_idx in range(2):
            proc._process_chunk(['/p/a.jpg'], chunk_idx, 2)

        assert _count(manager.events, 'unload') == 2
        assert proc.metrics['resident_chunks'] == 0

    def test_a_restricted_pass_also_keeps_its_one_model(self, monkeypatch):
        """``--pass X`` builds a one-group plan; the model is read once for the run."""
        manager = _Manager()
        proc = _processor(manager, [['saliency']], monkeypatch, restricted=True)

        for chunk_idx in range(2):
            proc._process_chunk(['/p/a.jpg'], chunk_idx, 2)

        assert _count(manager.events, 'load') == 1
        assert _count(manager.events, 'unload') == 0


class TestAFailedLoadIsStillRetried:
    """Keeping the group does not turn one load failure into a scan-long hole."""

    def test_the_missing_model_is_retried_while_its_siblings_stay_resident(self, monkeypatch):
        manager = _Manager(fail_once=('topiq',))
        proc = _processor(manager, [['clip', 'topiq']], monkeypatch)

        proc._process_chunk(['/p/a.jpg'], 0, 3)
        assert 'topiq' not in manager.models
        assert 'clip' in manager.models

        proc._process_chunk(['/p/a.jpg'], 1, 3)

        assert 'topiq' in manager.models, "chunk 1 asks for the group again and loads it"
        assert _count(manager.events, 'reuse', 'clip') == 1, "clip was never reloaded"
        assert _count(manager.events, 'load', 'clip') == 1
        assert _count(manager.events, 'load', 'topiq') == 1
        assert proc.metrics['resident_chunks'] == 0, "chunk 1 had to load, so it is no reuse"

        proc._process_chunk(['/p/a.jpg'], 2, 3)

        assert proc.metrics['resident_chunks'] == 1, "chunk 2 starts with the whole group on the card"
