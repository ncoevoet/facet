"""Chunk decode overlapped with the first pass group's model loading (scan-pass spec, S4).

``ChunkedMultiPassProcessor._process_chunk`` used to decode a chunk and only then load the
first pass group's models, so the loader sat idle while the GPU host read weights. With S4
the decode runs on a single-worker executor while the main thread loads group 0, but ONLY
when that can hide something and cannot hurt:

* a group-0 model has a load window (neither resident nor in the RAM cache);
* the device is CUDA and ``keep_in_ram`` is not ``"never"`` (CPU/MPS hosts, and hosts that
  asked for the RAM back, keep today's synchronous path);
* available RAM covers the next decode estimate plus the decode's in-flight buffers (one
  photo per worker) plus the RAM-cache reserve. The window models' own size is NOT in the
  budget: on CUDA the weights go to VRAM, and the host memory a load uses is spent by the
  synchronous path too, beside the same decoded chunk.

Everything here is deterministic: barriers and events order the two threads, a fake clock
measures the metrics, and no assertion reads the wall clock or sleeps to synchronise.
"""

from __future__ import annotations

import logging
import threading
import types
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

import pytest

pytest.importorskip("torch")

from processing.multi_pass import ChunkedMultiPassProcessor  # noqa: E402

GIB = 1024 ** 3
TIMEOUT = 5.0


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class _Manager:
    """Duck-types the ModelManager surface ``process_directory`` and the S4 gate read."""

    def __init__(self, device='cuda', keep_in_ram='auto', resident=(), cached=(),
                 available=1024 * GIB, reserve_gb=4.0, fail_load=(), profile=None,
                 events=None):
        self.device = device
        self.keep_in_ram = keep_in_ram
        self.models = {name: object() for name in resident}
        self._cpu_cache = {name: object() for name in cached}
        self.available = available
        self.ram_cache_reserve_gb = reserve_gb
        self.fail_load = set(fail_load)
        self.profile = profile or {}
        self.events = events if events is not None else []
        self._cache_hits = 0
        self._cache_misses = 0
        self.evictions = []

    def detect_vram(self):
        return 16.0

    def get_active_profile(self):
        return self.profile

    def is_resident_or_cached(self, name):
        return name in self.models or name in self._cpu_cache

    def _available_bytes(self):
        return self.available

    def get_model_ram(self, name):
        return 2.0

    def load_model_only(self, name):
        self.events.append(('load', name))
        if name in self.fail_load:
            return None
        self.models[name] = object()
        return self.models[name]

    def unload_model(self, name, reclaim=True):
        self.events.append(('unload', name))
        self.models.pop(name, None)

    def unload_all(self):
        self.events.append(('unload_all',))
        self.models.clear()

    def evict_cpu_cache(self, needed_available_bytes=None, next_use=None):
        self.evictions.append((needed_available_bytes, next_use))
        return []


class _FutureProxy:
    def __init__(self, future, log, before_wait=None):
        self._future = future
        self._log = log
        self._before_wait = before_wait

    def result(self, timeout=None):
        self._log.append('result-wait')
        if self._before_wait is not None:
            self._before_wait()
        value = self._future.result(timeout)
        self._log.append('result-returned')
        return value

    def done(self):
        return self._future.done()

    def cancel(self):
        return self._future.cancel()


class _RecordingExecutor:
    """A real single-worker executor that records submits and shutdowns."""

    def __init__(self, log, before_wait=None):
        self.real = ThreadPoolExecutor(max_workers=1, thread_name_prefix='test-decode')
        self.log = log
        self.before_wait = before_wait
        self.submits = 0
        self.shutdowns = []
        self.futures = []
        log.append('executor-created')

    def submit(self, fn, *args, **kwargs):
        self.log.append('submit')
        self.submits += 1
        proxy = _FutureProxy(self.real.submit(fn, *args, **kwargs), self.log, self.before_wait)
        self.futures.append(proxy)
        return proxy

    def shutdown(self, wait=True, cancel_futures=False):
        self.shutdowns.append({'wait': wait, 'cancel_futures': cancel_futures})
        self.real.shutdown(wait=wait, cancel_futures=cancel_futures)


class _Log(list):
    """A list appended to from two threads (list.append is atomic in CPython)."""


def _image_entry(width=1000, height=500):
    return {'pil': None, 'width': width, 'height': height}


def _scorer():
    config = types.SimpleNamespace(
        get_exposure_settings=lambda: {}, get_monochrome_settings=lambda: {})
    return types.SimpleNamespace(
        config=config, flush_person_centroids=lambda: None, get_exif_data=lambda path: {})


def _processor(manager, groups, monkeypatch, *, chunk=2, workers=1, log=None,
               executor=None, on_error=None, restricted=False):
    """A processor whose chunk loads/unloads through ``manager`` and stubs the CPU stages."""
    config = {'processing': {'ram_chunk_size': chunk, 'load_workers': workers,
                             'auto_tuning': {'enabled': False}}}
    with mock.patch('processing.multi_pass._ensure_imports'):
        proc = ChunkedMultiPassProcessor(_scorer(), manager, config, on_error=on_error)
    proc.pass_groups = groups
    proc.restricted = restricted
    log = log if log is not None else _Log()
    proc._test_log = log
    proc._test_executor = None

    def make_executor():
        # built when the scan asks for it, so its creation is ordered in the log
        proc._test_executor = executor if executor is not None else _RecordingExecutor(log)
        return proc._test_executor

    monkeypatch.setattr(proc, '_make_decode_executor', make_executor)

    def run_pass(name, model, images, results):
        log.append(('infer', name, len(images)))

    monkeypatch.setattr(proc, '_run_model_pass', run_pass)
    monkeypatch.setattr(proc, '_compute_aggregates', lambda results, images: None)
    monkeypatch.setattr(proc, '_save_results', lambda results, images: None)
    monkeypatch.setattr(proc, '_save_results_restricted', lambda results, images: None)
    return proc


def _stub_decode(proc, record_thread=None):
    """A ``_load_images`` that returns one entry per path and records its thread."""
    def load_images(paths, stop_event=None, report_error=None):
        if record_thread is not None:
            record_thread.append(threading.current_thread())
        proc._test_log.append('decode')
        return {p: _image_entry() for p in paths}
    return load_images


PATHS = ['/p/a.jpg', '/p/b.jpg', '/p/c.jpg', '/p/d.jpg']


# ---------------------------------------------------------------------------
# Overlap
# ---------------------------------------------------------------------------

class TestDecodeRunsWhileGroupZeroLoads:

    def test_decode_and_group_zero_load_are_inside_their_calls_at_the_same_time(
            self, monkeypatch):
        """Sequential execution cannot pass: a 2-party barrier needs both threads inside."""
        barrier = threading.Barrier(2)
        manager = _Manager()
        proc = _processor(manager, [['clip', 'topiq'], ['insightface']], monkeypatch, chunk=2)
        log = proc._test_log

        def load_images(paths, stop_event=None, report_error=None):
            log.append('decode-start')
            barrier.wait(timeout=TIMEOUT)
            log.append('decode-end')
            return {p: _image_entry() for p in paths}

        def load_pass_models(group, supplementary, failed_stages):
            log.append(('load-start', tuple(group)))
            if group == ['clip', 'topiq']:
                barrier.wait(timeout=TIMEOUT)
            log.append(('load-end', tuple(group)))
            return {name: object() for name in group}

        monkeypatch.setattr(proc, '_load_images', load_images)
        monkeypatch.setattr(proc, '_load_pass_models', load_pass_models)

        proc.process_directory(PATHS[:2], show_progress=False)

        assert proc._test_executor.submits == 1
        first_load_end = log.index(('load-end', ('clip', 'topiq')))
        assert log.index('decode-start') < first_load_end
        assert first_load_end < log.index('result-returned')
        # the images exist before group 0's inference starts
        assert log.index('result-returned') < log.index(('infer', 'clip', 2))
        assert ('infer', 'clip', 2) in log and ('infer', 'insightface', 2) in log
        assert proc.metrics['decode_overlapped_chunks'] == 1

    def test_every_chunk_with_a_load_window_overlaps(self, monkeypatch):
        manager = _Manager()
        proc = _processor(manager, [['clip'], ['insightface']], monkeypatch, chunk=2)
        monkeypatch.setattr(proc, '_load_images', _stub_decode(proc))

        proc.process_directory(PATHS, show_progress=False)

        assert proc._test_executor.submits == 2
        assert proc.metrics['decode_overlapped_chunks'] == 2
        assert proc.metrics['images_processed'] == 4

    def test_a_restricted_single_group_scan_hides_its_first_load(self, monkeypatch):
        """A single pass keeps its model, so only chunk 0 still has a load to hide.

        The model is not unloaded after chunk 0, so chunk 1 finds it resident and
        there is no restore to overlap with — the chunk decodes on this thread and
        loses only the copy it no longer has to make.
        """
        manager = _Manager()
        proc = _processor(manager, [['topiq']], monkeypatch, chunk=2, restricted=True)
        monkeypatch.setattr(proc, '_load_images', _stub_decode(proc))

        proc.process_directory(PATHS, show_progress=False)

        assert proc._test_executor.submits == 1
        assert proc.metrics['decode_overlapped_chunks'] == 1
        assert proc.metrics['resident_chunks'] == 1
        assert proc._test_log.count(('infer', 'topiq', 2)) == 2
        assert ('unload', 'topiq') not in manager.events

    def test_overlapped_and_synchronous_chunks_run_the_same_passes_on_the_same_images(
            self, monkeypatch):
        """Results must not depend on decode timing: same calls, same images, same order."""
        def run(device):
            manager = _Manager(device=device)
            proc = _processor(manager, [['clip', 'topiq'], ['insightface']], monkeypatch,
                              chunk=3)
            monkeypatch.setattr(proc, '_load_images', _stub_decode(proc))
            proc.process_directory(PATHS, show_progress=False)
            calls = [e for e in proc._test_log if isinstance(e, tuple)]
            return calls, manager.events, proc._test_executor.submits

        overlapped, overlapped_mm, submits = run('cuda')
        synchronous, synchronous_mm, no_submits = run('cpu')
        assert submits == 2 and no_submits == 0
        assert overlapped == synchronous
        assert overlapped_mm == synchronous_mm


# ---------------------------------------------------------------------------
# Gate (G2)
# ---------------------------------------------------------------------------

class TestOverlapGate:

    @pytest.mark.parametrize('kwargs', [
        pytest.param({'resident': ('clip',)}, id='resident'),
        pytest.param({'cached': ('clip',)}, id='in-ram-cache'),
        pytest.param({'device': 'cpu'}, id='cpu'),
        pytest.param({'device': 'mps'}, id='mps'),
        pytest.param({'keep_in_ram': 'never'}, id='keep-in-ram-never'),
        pytest.param({'available': 1 * GIB}, id='budget'),
    ])
    def test_not_overlapped_decodes_synchronously_on_the_scan_thread(self, kwargs, monkeypatch):
        manager = _Manager(**kwargs)
        proc = _processor(manager, [['clip'], ['insightface']], monkeypatch, chunk=2)
        threads = []
        monkeypatch.setattr(proc, '_load_images', _stub_decode(proc, threads))

        proc.process_directory(PATHS[:2], show_progress=False)

        assert proc._test_executor.submits == 0
        assert threads == [threading.current_thread()]
        assert proc.metrics['decode_overlapped_chunks'] == 0
        # today's order: decode, then group 0's load
        log = proc._test_log
        assert log.index('decode') < log.index(('infer', 'clip', 2))

    def test_overlapped_when_all_four_conditions_allow_it(self, monkeypatch):
        manager = _Manager(resident=('insightface',), cached=('topiq',))
        proc = _processor(manager, [['clip', 'topiq'], ['insightface']], monkeypatch, chunk=2)
        threads = []
        monkeypatch.setattr(proc, '_load_images', _stub_decode(proc, threads))

        proc.process_directory(PATHS[:2], show_progress=False)

        assert proc._test_executor.submits == 1
        assert len(threads) == 1 and threads[0] is not threading.current_thread()

    def test_the_window_models_ram_requirement_is_not_in_the_budget(self, monkeypatch):
        """The CPU-execution RAM figure of a model loaded to CUDA does not move the boundary.

        ``get_model_ram`` is the FP32 CPU-inference figure (``qwen3_5_tagger`` 5 GB,
        ``clip`` 3, ``topiq`` 2: the 10 GB "model staging" that kept the 16gb group 0 from
        ever overlapping on a 32 GB host). A load to CUDA measured +0.56 GiB of private host
        memory, which the synchronous path spends as well.
        """
        manager = _Manager(cached=('topiq',))
        manager.get_model_ram = lambda name: 100.0
        proc = _processor(manager, [['clip', 'topiq']], monkeypatch)
        needed = (proc._decode_estimate_bytes(2) + proc._decode_inflight_bytes(2)
                  + 4 * GIB)

        manager.available = needed
        assert proc._overlap_allowed(PATHS[:2], ['clip', 'topiq']) is True
        manager.available = needed - 1
        assert proc._overlap_allowed(PATHS[:2], ['clip', 'topiq']) is False

    def test_budget_boundary_uses_decode_in_flight_buffers_and_reserve(self, monkeypatch):
        manager = _Manager(reserve_gb=1.5)
        proc = _processor(manager, [['clip', 'saliency']], monkeypatch)
        decode = int(2 * ChunkedMultiPassProcessor.DEFAULT_DECODE_MEAN_PX
                     * ChunkedMultiPassProcessor.RETAINED_BYTES_PER_PX)
        # one decode worker in this processor: one photo in flight
        in_flight = int(ChunkedMultiPassProcessor.DEFAULT_DECODE_MEAN_PX
                        * ChunkedMultiPassProcessor.DECODE_INFLIGHT_BYTES_PER_PX)
        assert proc._decode_estimate_bytes(2) == decode
        assert proc._decode_inflight_bytes(2) == in_flight
        needed = decode + in_flight + int(1.5 * GIB)

        manager.available = needed
        assert proc._overlap_allowed(PATHS[:2], ['clip', 'saliency']) is True
        manager.available = needed - 1
        assert proc._overlap_allowed(PATHS[:2], ['clip', 'saliency']) is False

    @pytest.mark.parametrize('workers, n_paths, in_flight', [
        pytest.param(4, 16, 4, id='four-workers'),
        pytest.param(4, 2, 2, id='fewer-photos-than-workers'),
        pytest.param(1, 16, 1, id='sequential'),
    ])
    def test_in_flight_buffers_are_one_photo_per_worker(self, workers, n_paths, in_flight,
                                                        monkeypatch):
        proc = _processor(_Manager(), [['clip']], monkeypatch, workers=workers)
        proc._last_chunk_mean_px = 21_000_000
        assert proc._decode_inflight_bytes(n_paths) == int(
            in_flight * 21_000_000 * ChunkedMultiPassProcessor.DECODE_INFLIGHT_BYTES_PER_PX)

    def test_in_flight_buffers_use_the_mean_even_when_the_chunk_mixed_sizes(
            self, monkeypatch):
        """A 24 / 61 MP chunk is sized at its mean: the reserve absorbs the larger frame.

        Sizing from the largest photo was measured to turn a passing margin into a refusal
        (2.1 vs 1.2 GB for 4 workers), so the in-flight term stays at the mean.
        """
        proc = _processor(_Manager(), [['clip']], monkeypatch, workers=4)
        proc._record_chunk_pixels({'a': _image_entry(6000, 4000),
                                   'b': _image_entry(9000, 6778)})
        mean = (6000 * 4000 + 9000 * 6778) / 2
        assert proc._decode_inflight_bytes(16) == int(
            4 * mean * ChunkedMultiPassProcessor.DECODE_INFLIGHT_BYTES_PER_PX)
        assert proc._decode_estimate_bytes(16) == int(
            16 * mean * ChunkedMultiPassProcessor.RETAINED_BYTES_PER_PX)

    def test_both_estimates_fall_back_to_the_default_until_a_chunk_is_recorded(
            self, monkeypatch):
        proc = _processor(_Manager(), [['clip']], monkeypatch, workers=2)
        default = ChunkedMultiPassProcessor.DEFAULT_DECODE_MEAN_PX
        assert proc._previous_chunk_px() == default
        assert proc._decode_inflight_bytes(2) == int(
            2 * default * ChunkedMultiPassProcessor.DECODE_INFLIGHT_BYTES_PER_PX)
        proc._record_chunk_pixels({'a': _image_entry(1000, 500), 'b': _image_entry(3000, 1000)})
        assert proc._previous_chunk_px() == 1_750_000

    def test_the_16gb_group_zero_on_a_busy_32gb_host(self, monkeypatch):
        """The P16-W2 reading: 14.5 GiB available before chunk 0 of 16 photos, 4 workers.

        The old budget asked 15.4 GiB (decode 1.4 + model staging 10.0 + reserve 4.0) and
        refused every chunk. The measured peak of either path was +4.8 to +5.9 GiB of
        available memory, the overlapped one at most 0.77 GiB above the synchronous one.
        The new budget (decode 1.4 + in flight 1.2 + reserve 4.0) admits it, and still
        refuses when the margin is genuinely absent.
        """
        group = ['qwen3_5_tagger', 'clip', 'topiq']
        manager = _Manager(resident=('insightface',))
        proc = _processor(manager, [group, ['insightface']], monkeypatch, workers=4)
        paths = ['/p/%02d.jpg' % i for i in range(16)]
        needed = (proc._decode_estimate_bytes(16) + proc._decode_inflight_bytes(16)
                  + 4 * GIB)
        assert 6.5 * GIB < needed < 7 * GIB

        manager.available = int(14.5 * GIB)
        assert proc._overlap_allowed(paths, group) is True
        manager.available = int(6.5 * GIB)
        assert proc._overlap_allowed(paths, group) is False
        manager.available = needed - 1
        assert proc._overlap_allowed(paths, group) is False

    def test_the_estimate_follows_the_previous_chunks_mean_pixels(self, monkeypatch):
        manager = _Manager()
        proc = _processor(manager, [['clip']], monkeypatch, chunk=2)
        monkeypatch.setattr(proc, '_load_images', _stub_decode(proc))
        assert proc._last_chunk_mean_px is None

        proc.process_directory(PATHS[:2], show_progress=False)

        assert proc._last_chunk_mean_px == 1000 * 500
        assert proc._decode_estimate_bytes(3) == int(
            3 * 1000 * 500 * ChunkedMultiPassProcessor.RETAINED_BYTES_PER_PX)

    def test_a_refused_budget_is_logged_once_at_info(self, monkeypatch, caplog):
        manager = _Manager(available=1 * GIB)
        proc = _processor(manager, [['clip']], monkeypatch, chunk=2)
        monkeypatch.setattr(proc, '_load_images', _stub_decode(proc))

        with caplog.at_level(logging.INFO, logger='facet.multi_pass'):
            proc.process_directory(PATHS, show_progress=False)

        refusals = [r for r in caplog.records
                    if r.levelno == logging.INFO and 'decode overlap' in r.getMessage()]
        assert len(refusals) == 1, [r.getMessage() for r in refusals]
        assert proc._test_executor.submits == 0

    @pytest.mark.parametrize('device, keep_in_ram', [
        pytest.param('cpu', 'auto', id='cpu'),
        pytest.param('mps', 'auto', id='mps'),
        pytest.param('cuda', 'never', id='keep-in-ram-never'),
    ])
    def test_no_window_off_cuda_or_with_keep_in_ram_never(self, device, keep_in_ram,
                                                          monkeypatch):
        manager = _Manager(device=device, keep_in_ram=keep_in_ram)
        proc = _processor(manager, [['clip']], monkeypatch)
        assert proc._overlap_window(['clip']) == []

    def test_a_magicmock_manager_takes_the_synchronous_path(self, monkeypatch):
        proc = _processor(mock.MagicMock(), [['clip']], monkeypatch)
        assert proc._overlap_allowed(PATHS[:2], ['clip']) is False

    def test_the_real_model_managers_predicate_and_reserve_drive_the_gate(self, monkeypatch):
        """E <-> F contract: ``is_resident_or_cached``, ``_available_bytes`` and the reserve."""
        from models.model_manager import ModelManager
        from utils.system_memory import EffectiveMemory

        reading = {'available': 0}

        def provider():
            return EffectiveMemory(256 * GIB, 0, reading['available'], 10.0)

        class _Cfg:
            def get_model_config(self):
                return {'vram_profile': 'legacy', 'keep_in_ram': 'auto',
                        'ram_cache_reserve_gb': 2.0,
                        'profiles': {'legacy': {}}}

        with mock.patch('utils.device.get_device', return_value='cpu'):
            manager = ModelManager(_Cfg(), memory_provider=provider)
        manager.device = 'cuda'
        monkeypatch.setattr(manager, 'detect_vram', lambda: 16.0)
        proc = _processor(manager, [['clip']], monkeypatch)
        needed = (proc._decode_estimate_bytes(2) + proc._decode_inflight_bytes(2)
                  + 2 * GIB)

        reading['available'] = needed
        assert proc._overlap_allowed(PATHS[:2], ['clip']) is True
        reading['available'] = needed - 1
        assert proc._overlap_allowed(PATHS[:2], ['clip']) is False

        reading['available'] = needed
        manager._cpu_cache['clip'] = object()
        assert proc._overlap_allowed(PATHS[:2], ['clip']) is False
        del manager._cpu_cache['clip']
        manager.models['clip'] = object()
        assert proc._overlap_allowed(PATHS[:2], ['clip']) is False
        del manager.models['clip']
        manager.keep_in_ram = 'never'
        assert proc._overlap_allowed(PATHS[:2], ['clip']) is False


class _EvictingManager(_Manager):
    """A fake memory monitor: available = base + what the evicted cache entries held."""

    def __init__(self, base_available, cached_sizes, **kwargs):
        super().__init__(cached=tuple(cached_sizes), **kwargs)
        self.base_available = base_available
        self.sizes = dict(cached_sizes)
        self.freed = 0
        self.evicted = []

    def _available_bytes(self):
        return self.base_available + self.freed

    def evict_cpu_cache(self, needed_available_bytes=None, next_use=None):
        order = list(next_use or [])
        # Belady: the cached model whose next use is farthest goes first
        for name in sorted(self._cpu_cache, key=lambda n: -order.index(n)):
            if needed_available_bytes is not None and self._available_bytes() >= needed_available_bytes:
                break
            self._cpu_cache.pop(name)
            self.freed += self.sizes[name]
            self.evicted.append(name)
        return list(self.evicted)


class TestTrimNeverEvictsForTheOverlap:
    """The pre-chunk trim keeps the synchronous need; the overlap only uses what is left."""

    GROUPS = [['qwen3_5_tagger', 'clip'], ['saliency', 'liqe'], ['insightface']]
    CHUNK = ['/p/%d' % i for i in range(16)]

    def _proc(self, manager, monkeypatch):
        proc = _processor(manager, self.GROUPS, monkeypatch, workers=4)
        proc._last_chunk_mean_px = 20_000_000
        return proc

    def _sync_need(self, proc):
        return proc._decode_estimate_bytes(16) + 4 * GIB

    def _overlap_need(self, proc):
        return self._sync_need(proc) + proc._decode_inflight_bytes(16)

    @pytest.mark.parametrize('offset_gib, old_policy_evicts', [
        (-1.5, ['liqe', 'saliency']),
        (-0.5, ['liqe']),
        (0.0, []),
        (0.5, []),
    ])
    def test_an_overlap_never_evicts_a_model_the_old_policy_would_keep(
            self, monkeypatch, offset_gib, old_policy_evicts):
        """Offsets are from the synchronous need (decode + reserve), the old trim's target.

        The in-flight buffers (4 workers x 20 MP x 16 B = 1.19 GiB) exceed every
        shortfall here, so a trim that also covered them would evict more models.
        """
        manager = _EvictingManager(0, {'clip': 1 * GIB, 'saliency': 1 * GIB,
                                       'liqe': 1 * GIB})
        proc = self._proc(manager, monkeypatch)
        assert proc._overlap_window(self.GROUPS[0]) == ['qwen3_5_tagger']
        manager.base_available = self._sync_need(proc) + int(offset_gib * GIB)

        proc._trim_ram_cache_for_next_chunk(16)

        assert manager.evicted == old_policy_evicts
        assert manager._available_bytes() >= self._sync_need(proc)

    def test_a_chunk_short_of_the_margin_after_the_old_trim_decodes_first(self, monkeypatch):
        manager = _EvictingManager(0, {'clip': 1 * GIB, 'saliency': 1 * GIB,
                                       'liqe': 1 * GIB})
        proc = self._proc(manager, monkeypatch)
        manager.base_available = self._sync_need(proc) - int(0.5 * GIB)

        proc._trim_ram_cache_for_next_chunk(16)

        # the old trim's single eviction, and nothing more for the overlap
        assert manager.evicted == ['liqe']
        assert set(manager._cpu_cache) == {'clip', 'saliency'}
        assert manager._available_bytes() < self._overlap_need(proc)
        assert proc._overlap_allowed(self.CHUNK, self.GROUPS[0]) is False
        assert manager.evicted == ['liqe']

    def test_a_chunk_whose_margin_survives_the_old_trim_overlaps(self, monkeypatch):
        manager = _EvictingManager(0, {'clip': 1 * GIB, 'saliency': 1 * GIB,
                                       'liqe': 1 * GIB})
        proc = self._proc(manager, monkeypatch)
        manager.base_available = self._overlap_need(proc)

        proc._trim_ram_cache_for_next_chunk(16)

        assert manager.evicted == []
        assert proc._overlap_allowed(self.CHUNK, self.GROUPS[0]) is True

    def test_an_emptied_cache_that_is_still_short_decodes_synchronously(self, monkeypatch):
        manager = _EvictingManager(0, {'saliency': 1 * GIB, 'liqe': 1 * GIB})
        proc = self._proc(manager, monkeypatch)
        manager.base_available = self._sync_need(proc) - 3 * GIB

        proc._trim_ram_cache_for_next_chunk(16)

        assert manager.evicted == ['liqe', 'saliency']
        assert proc._overlap_allowed(self.CHUNK, self.GROUPS[0]) is False


# ---------------------------------------------------------------------------
# Warm-up on the main thread (G1, issue #55)
# ---------------------------------------------------------------------------

class TestWarmupRunsOnTheMainThreadFirst:

    def test_warmup_is_on_the_main_thread_before_the_executor_and_any_model_load(
            self, monkeypatch):
        log = _Log()
        manager = _Manager()
        proc = _processor(manager, [['clip']], monkeypatch, chunk=2, log=log)
        warm_threads = []

        def warmup():
            warm_threads.append(threading.current_thread())
            log.append('warmup')

        monkeypatch.setattr('analyzers.form_facet.warmup', warmup)
        monkeypatch.setattr(proc, '_load_images', _stub_decode(proc))

        def load_pass_models(group, supplementary, failed_stages):
            log.append('load-models')
            return {name: object() for name in group}

        monkeypatch.setattr(proc, '_load_pass_models', load_pass_models)

        proc.process_directory(PATHS[:2], show_progress=False)

        assert warm_threads == [threading.main_thread()]
        assert proc._test_executor.submits == 1
        assert log.index('warmup') < log.index('executor-created')
        assert log.index('warmup') < log.index('submit')
        assert log.index('warmup') < log.index('load-models')


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class TestDecodeFailure:

    def test_a_decode_runtime_error_is_raised_and_group_zero_is_unloaded(self, monkeypatch):
        manager = _Manager()
        proc = _processor(manager, [['clip', 'topiq'], ['insightface']], monkeypatch, chunk=2)
        reclaims = []
        monkeypatch.setattr(proc, '_reclaim_freed_memory', lambda: reclaims.append(
            list(manager.events)))

        def failing_decode(paths, stop_event=None, report_error=None):
            raise RuntimeError('decode abandonment budget exhausted')

        monkeypatch.setattr(proc, '_load_images', failing_decode)

        with pytest.raises(RuntimeError, match='abandonment'):
            proc.process_directory(PATHS[:2], show_progress=False)

        events = manager.events
        assert ('load', 'clip') in events and ('load', 'topiq') in events
        assert ('load', 'insightface') not in events
        unload_all = events.index(('unload_all',))
        assert events.index(('unload', 'clip')) < unload_all
        assert events.index(('unload', 'topiq')) < unload_all
        # the chunk reclaimed after its own unloads, before the scan's unload_all
        assert reclaims and ('unload', 'topiq') in reclaims[0]
        assert ('unload_all',) not in reclaims[0]
        # the failed decode is finished, so the worker is joined, not abandoned
        assert proc._test_executor.shutdowns == [{'wait': True, 'cancel_futures': True}]
        assert not [t for t in threading.enumerate() if t.name.startswith('test-decode')]
        assert not [e for e in proc._test_log if isinstance(e, tuple) and e[0] == 'infer']

    def test_the_decode_executor_is_shut_down_and_its_thread_ends_after_a_normal_scan(
            self, monkeypatch):
        manager = _Manager()
        proc = _processor(manager, [['clip']], monkeypatch, chunk=2)
        monkeypatch.setattr(proc, '_load_images', _stub_decode(proc))

        proc.process_directory(PATHS, show_progress=False)

        assert proc._test_executor.shutdowns == [{'wait': True, 'cancel_futures': True}]
        assert not [t for t in threading.enumerate() if t.name.startswith('test-decode')]

    def test_a_model_load_failure_skips_or_records_exactly_as_the_synchronous_path(
            self, monkeypatch):
        profile = {'supplementary_pyiqa': ['topiq']}

        def run(device):
            errors = []
            manager = _Manager(device=device, fail_load=('clip', 'topiq'), profile=profile)
            proc = _processor(manager, [['clip', 'topiq'], ['insightface']], monkeypatch,
                              chunk=2, on_error=lambda *a: errors.append(a))
            monkeypatch.setattr(proc, '_load_images', _stub_decode(proc))
            proc.process_directory(PATHS[:2], show_progress=False)
            calls = [e for e in proc._test_log if isinstance(e, tuple)]
            return errors, calls, proc._test_executor.submits

        errors, calls, submits = run('cuda')
        sync_errors, sync_calls, sync_submits = run('cpu')
        assert submits == 1 and sync_submits == 0
        assert errors == sync_errors
        assert [(p, s) for p, s, _ in errors] == [(PATHS[0], 'clip'), (PATHS[1], 'clip')]
        assert calls == sync_calls == [('infer', 'insightface', 2)]

    def test_a_photo_that_failed_to_load_is_still_reported_when_the_decode_aborts(
            self, monkeypatch):
        """Photo A fails to load, then the abandonment RuntimeError aborts the chunk: A must
        reach ``on_error`` (scan_failures) as it does on the synchronous path."""
        errors = []
        manager = _Manager()
        proc = _processor(manager, [['clip']], monkeypatch, chunk=2,
                          on_error=lambda *a: errors.append((threading.current_thread(), a)))

        def decode(paths, stop_event=None, report_error=None):
            report_error(paths[0], 'load', 'failed to load image')
            raise RuntimeError('decode abandonment budget exhausted')

        monkeypatch.setattr(proc, '_load_images', decode)

        with pytest.raises(RuntimeError, match='abandonment'):
            proc.process_directory(PATHS[:2], show_progress=False)

        assert proc._test_executor.submits == 1
        assert errors == [(threading.current_thread(),
                           (PATHS[0], 'load', 'failed to load image'))]

    def test_decode_errors_reach_on_error_on_the_scan_thread(self, monkeypatch):
        errors = []
        manager = _Manager()
        proc = _processor(manager, [['clip']], monkeypatch, chunk=2,
                          on_error=lambda *a: errors.append((threading.current_thread(), a)))

        def decode(paths, stop_event=None, report_error=None):
            report_error(paths[0], 'load', 'failed to load image')
            return {p: _image_entry() for p in paths[1:]}

        monkeypatch.setattr(proc, '_load_images', decode)

        proc.process_directory(PATHS[:2], show_progress=False)

        assert proc._test_executor.submits == 1
        assert errors == [(threading.current_thread(),
                           (PATHS[0], 'load', 'failed to load image'))]


# ---------------------------------------------------------------------------
# Cancellation (G8)
# ---------------------------------------------------------------------------

class TestKeyboardInterruptDoesNotWaitForTheChunk:

    @pytest.mark.timeout(60)
    def test_interrupt_during_group_zero_load_returns_while_the_decode_is_blocked(
            self, monkeypatch):
        release = threading.Event()
        two_started = threading.Event()
        started = []
        lock = threading.Lock()

        def blocking_load(path):
            with lock:
                started.append(path)
                if len(started) >= 2:
                    two_started.set()
            release.wait(30)
            return None, None

        monkeypatch.setattr('utils.load_image_from_path', blocking_load)
        monkeypatch.setattr('exiftool.get_exif_batch', lambda paths, chunk_size=100: {})
        errors = []
        manager = _Manager()
        paths = [f'/p/{i}.jpg' for i in range(6)]
        proc = _processor(manager, [['clip']], monkeypatch, chunk=6, workers=2,
                          on_error=lambda *a: errors.append(a))

        def load_pass_models(group, supplementary, failed_stages):
            assert two_started.wait(TIMEOUT)
            raise KeyboardInterrupt()

        monkeypatch.setattr(proc, '_load_pass_models', load_pass_models)

        outcome = {}

        def scan():
            try:
                proc.process_directory(paths, show_progress=False)
            except BaseException as exc:  # noqa: BLE001 - the test inspects it
                outcome['exc'] = exc

        runner = threading.Thread(target=scan, name='scan-under-test')
        try:
            runner.start()
            runner.join(TIMEOUT)
            returned_while_blocked = not runner.is_alive()
            decode_still_running = not proc._test_executor.futures[0].done()
        finally:
            release.set()
        assert returned_while_blocked, "process_directory waited for the blocked decode"
        assert decode_still_running
        assert isinstance(outcome.get('exc'), KeyboardInterrupt)
        assert proc._test_executor.shutdowns == [{'wait': False, 'cancel_futures': True}]

        # let the in-flight photos finish into a discarded result, then reap the thread
        finisher = threading.Thread(target=proc._test_executor.real.shutdown)
        finisher.start()
        finisher.join(TIMEOUT)
        assert not finisher.is_alive(), "the decode thread did not end after the stop flag"
        assert len(started) == 2, (
            f"photos beyond the in-flight ones were decoded after the stop: {started}")
        assert errors == [], "a cancelled decode recorded scan failures"
        assert ('unload_all',) in manager.events


class TestStopFlagInLoadImages:

    def _patch_io(self, monkeypatch, load):
        monkeypatch.setattr('utils.load_image_from_path', load)
        monkeypatch.setattr('exiftool.get_exif_batch', lambda paths, chunk_size=100: {})

    @pytest.mark.parametrize('workers', [1, 3])
    def test_a_set_stop_flag_starts_no_photo_and_records_nothing(self, workers, monkeypatch):
        from processing.multi_pass import _DecodeCancelled
        started = []
        self._patch_io(monkeypatch, lambda p: started.append(p) or (None, None))
        errors = []
        proc = _processor(_Manager(), [['clip']], monkeypatch, workers=workers,
                          on_error=lambda *a: errors.append(a))
        stop = threading.Event()
        stop.set()

        with pytest.raises(_DecodeCancelled):
            proc._load_images(PATHS, stop_event=stop)

        assert started == [] and errors == []

    def test_a_sequential_decode_starts_nothing_after_the_flag(self, monkeypatch):
        from processing.multi_pass import _DecodeCancelled
        stop = threading.Event()
        started = []

        def load(path):
            started.append(path)
            stop.set()
            return None, None

        self._patch_io(monkeypatch, load)
        proc = _processor(_Manager(), [['clip']], monkeypatch, workers=1)

        with pytest.raises(_DecodeCancelled):
            proc._load_images(PATHS, stop_event=stop)

        assert started == [PATHS[0]]

    def test_without_a_stop_event_load_errors_go_to_on_error_as_before(self, monkeypatch):
        self._patch_io(monkeypatch, lambda p: (None, None))
        errors = []
        proc = _processor(_Manager(), [['clip']], monkeypatch, workers=2,
                          on_error=lambda *a: errors.append(a))

        assert proc._load_images(PATHS[:2]) == {}
        assert errors == [(PATHS[0], 'load', 'failed to load image'),
                          (PATHS[1], 'load', 'failed to load image')]


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

class _FakeClock:
    """``time.time`` / ``time.perf_counter`` that move only when a stub advances them."""

    def __init__(self):
        self.now = 1000.0
        self._lock = threading.Lock()

    def advance(self, seconds):
        with self._lock:
            self.now += seconds

    def read(self):
        with self._lock:
            return self.now


class TestMetrics:

    def _clock(self, monkeypatch):
        clock = _FakeClock()
        monkeypatch.setattr('processing.multi_pass.time', types.SimpleNamespace(
            time=clock.read, perf_counter=clock.read, monotonic=clock.read))
        return clock

    def test_io_time_is_the_wait_and_io_decode_time_is_the_worker_wall(self, monkeypatch):
        clock = self._clock(monkeypatch)
        decode_started = threading.Event()
        main_waiting = threading.Event()
        log = _Log()
        executor = _RecordingExecutor(log, before_wait=main_waiting.set)
        manager = _Manager()
        proc = _processor(manager, [['clip']], monkeypatch, chunk=2, log=log,
                          executor=executor)

        def decode(paths, stop_event=None, report_error=None):
            decode_started.set()
            assert main_waiting.wait(TIMEOUT)
            clock.advance(3.0)          # the part of the decode the load did not hide
            return {p: _image_entry() for p in paths}

        def load_pass_models(group, supplementary, failed_stages):
            assert decode_started.wait(TIMEOUT)
            clock.advance(7.0)          # group 0's load, overlapped with the decode
            return {name: object() for name in group}

        monkeypatch.setattr(proc, '_load_images', decode)
        monkeypatch.setattr(proc, '_load_pass_models', load_pass_models)

        proc.process_directory(PATHS[:2], show_progress=False)

        assert proc.metrics['io_time'] == pytest.approx(3.0)
        assert proc.metrics['io_decode_time'] == pytest.approx(10.0)
        assert proc.metrics['model_load_time'] == pytest.approx(7.0)

    def test_a_synchronous_decode_counts_its_whole_wall_as_both(self, monkeypatch):
        clock = self._clock(monkeypatch)
        manager = _Manager(device='cpu')
        proc = _processor(manager, [['clip']], monkeypatch, chunk=2)

        def decode(paths, stop_event=None, report_error=None):
            clock.advance(4.0)
            return {p: _image_entry() for p in paths}

        monkeypatch.setattr(proc, '_load_images', decode)

        proc.process_directory(PATHS[:2], show_progress=False)

        assert proc.metrics['io_time'] == pytest.approx(4.0)
        assert proc.metrics['io_decode_time'] == pytest.approx(4.0)
        assert proc.metrics['decode_overlapped_chunks'] == 0
