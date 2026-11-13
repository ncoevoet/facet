"""RAM-cache eviction by available bytes in the scan (scan-pass spec, step S6b).

Two callers of ``ModelManager.evict_cpu_cache(needed_available_bytes, next_use)`` (S6a):

* ``MultiPassResourceMonitor``: above the memory limit it still shrinks the chunk exactly as
  before, but it evicts cached models only while available memory is below
  ``ram_cache_reserve_gb``, down to that reserve and in Belady order of the processor's
  ``_next_use_order()``; it used to wipe the whole cache on every tick above 85 %.
* ``ChunkedMultiPassProcessor._trim_ram_cache_for_next_chunk``: before decoding chunk >= 1,
  when available memory does not cover the next chunk's decode estimate plus the reserve,
  it evicts down to that figure.

The monitor is driven tick by tick (``_tick``) with ``effective_memory`` monkeypatched, so
nothing here sleeps or depends on the monitor thread's timing.
"""

from __future__ import annotations

import logging
import types
from unittest import mock

import pytest

pytest.importorskip("torch")

from processing.multi_pass import ChunkedMultiPassProcessor  # noqa: E402
from processing.resource_monitor import MultiPassResourceMonitor  # noqa: E402
from utils.system_memory import EffectiveMemory  # noqa: E402

GIB = 1024 ** 3
TOTAL = 32 * GIB


def _reading(percent, available):
    return EffectiveMemory(total=TOTAL, used=TOTAL - available, available=available,
                           percent=percent)


class _RecordingManager:
    def __init__(self, reserve_gb=4.0):
        if reserve_gb is not None:
            self.ram_cache_reserve_gb = reserve_gb
        self.calls = []

    def evict_cpu_cache(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return []


class _Processor:
    """The chunk-size knob plus whatever eviction inputs a test gives it."""

    def __init__(self, manager=None, next_use=None, chunk_size=32, log=None):
        self.chunk_size = chunk_size
        self.min_chunk_size = 10
        self.max_chunk_size = 128
        self.auto_tuning_enabled = True
        self.model_manager = manager
        self.log = log if log is not None else []
        if next_use is not None:
            self._next_use_order = next_use

    def reduce_chunk_size(self):
        self.log.append('reduce')
        new_size = max(self.min_chunk_size, int(self.chunk_size * 0.75))
        if new_size == self.chunk_size:
            return False
        self.chunk_size = new_size
        return True

    def increase_chunk_size(self):
        new_size = min(self.max_chunk_size, int(self.chunk_size * 1.25))
        if new_size == self.chunk_size:
            return False
        self.chunk_size = new_size
        return True


def _tick(processor, percent, available, monkeypatch):
    monitor = MultiPassResourceMonitor(processor, {})
    monkeypatch.setattr('processing.resource_monitor.effective_memory',
                        lambda: _reading(percent, available))
    monitor._tick()
    return monitor


# ---------------------------------------------------------------------------
# Monitor tick
# ---------------------------------------------------------------------------

class TestMonitorEvictsOnlyBelowTheReserve:

    def test_above_the_limit_with_available_above_the_reserve_shrinks_but_evicts_nothing(
            self, monkeypatch):
        manager = _RecordingManager(reserve_gb=4.0)
        processor = _Processor(manager, next_use=lambda: ['clip'])

        _tick(processor, 86.0, int(4.5 * GIB), monkeypatch)

        assert processor.chunk_size == 24
        assert manager.calls == []

    def test_below_the_reserve_evicts_to_exactly_the_reserve_in_next_use_order(
            self, monkeypatch):
        """G10: the eviction really happens, with the reserve target and the order."""
        manager = _RecordingManager(reserve_gb=4.0)
        processor = _Processor(manager, next_use=lambda: ['clip', 'topiq', 'saliency'])

        monitor = _tick(processor, 92.0, int(2.5 * GIB), monkeypatch)

        assert processor.chunk_size == 24
        assert monitor.adjustments == [('reduce', 32, 24)]
        assert manager.calls == [((), {'needed_available_bytes': 4 * GIB,
                                       'next_use': ['clip', 'topiq', 'saliency']})]

    def test_a_configured_reserve_moves_the_eviction_point(self, monkeypatch):
        manager = _RecordingManager(reserve_gb=1.0)
        processor = _Processor(manager, next_use=lambda: ['clip'])

        _tick(processor, 92.0, int(2.5 * GIB), monkeypatch)
        assert manager.calls == []

        _tick(processor, 96.0, int(0.5 * GIB), monkeypatch)
        assert manager.calls == [((), {'needed_available_bytes': 1 * GIB,
                                       'next_use': ['clip']})]

    def test_below_the_limit_neither_shrinks_nor_evicts(self, monkeypatch):
        manager = _RecordingManager()
        processor = _Processor(manager, next_use=lambda: ['clip'])

        _tick(processor, 60.0, 1 * GIB, monkeypatch)

        assert processor.chunk_size == 32
        assert manager.calls == []

    def test_a_real_model_manager_drops_only_what_the_reserve_needs(self, monkeypatch):
        """End to end with S6a's ``evict_cpu_cache``: 1 of 3 cached models goes, the
        one used farthest in the future, and the reading the monitor sees is honoured."""
        from models.model_manager import ModelManager

        sizes = {'clip': 3 * GIB, 'topiq': 2 * GIB, 'saliency': 2 * GIB}
        base_available = int(2.5 * GIB)
        holder = {}

        def provider():
            freed = sum(size for name, size in sizes.items()
                        if name not in holder['manager']._cpu_cache)
            return _reading(92.0, base_available + freed)

        class _Cfg:
            def get_model_config(self):
                return {'vram_profile': 'legacy', 'keep_in_ram': 'auto',
                        'profiles': {'legacy': {}}}

        with mock.patch('utils.device.get_device', return_value='cpu'):
            manager = ModelManager(_Cfg(), memory_provider=provider)
        holder['manager'] = manager
        for name in ('clip', 'topiq', 'saliency'):
            manager._cpu_cache[name] = object()
        processor = _Processor(manager, next_use=lambda: ['clip', 'topiq', 'saliency'])

        _tick(processor, 92.0, base_available, monkeypatch)

        assert list(manager._cpu_cache) == ['clip', 'topiq']
        assert processor.chunk_size == 24


class TestMonitorToleratesOlderStubs:

    def test_a_processor_without_a_model_manager_ticks(self, monkeypatch, caplog):
        processor = _Processor(manager=None)
        with caplog.at_level(logging.WARNING, logger='facet.resources'):
            _tick(processor, 95.0, 0, monkeypatch)
        assert processor.chunk_size == 24
        assert not caplog.records

    def test_a_manager_without_a_reserve_falls_back_to_evicting_everything(
            self, monkeypatch):
        manager = _RecordingManager(reserve_gb=None)
        processor = _Processor(manager, next_use=lambda: ['clip'])

        _tick(processor, 86.0, 10 * GIB, monkeypatch)

        assert manager.calls == [((), {})]

    def test_a_processor_without_next_use_order_evicts_without_an_order(self, monkeypatch):
        manager = _RecordingManager()
        processor = _Processor(manager)

        _tick(processor, 95.0, 1 * GIB, monkeypatch)

        assert manager.calls == [((), {'needed_available_bytes': 4 * GIB,
                                       'next_use': None})]


class TestMonitorFailureIsVisibleOnce:

    def test_a_raising_next_use_order_logs_one_warning_after_the_shrink(
            self, monkeypatch, caplog):
        log = []

        def broken():
            log.append('order')
            raise ValueError('no plan yet')

        manager = _RecordingManager()
        processor = _Processor(manager, next_use=broken, log=log)
        monitor = MultiPassResourceMonitor(processor, {})
        monkeypatch.setattr('processing.resource_monitor.effective_memory',
                            lambda: _reading(95.0, 1 * GIB))

        with caplog.at_level(logging.WARNING, logger='facet.resources'):
            monitor._tick()
            monitor._tick()

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1, [r.getMessage() for r in warnings]
        assert 'no plan yet' in warnings[0].getMessage()
        assert log[:2] == ['reduce', 'order']
        assert log.count('reduce') == 2
        assert manager.calls == []

    def test_the_thread_loop_survives_a_failing_tick_and_warns_once(
            self, monkeypatch, caplog):
        """``run`` drives ``_tick``; a failing reading does not end the thread."""
        manager = _RecordingManager()
        processor = _Processor(manager, next_use=lambda: ['clip'])
        monitor = MultiPassResourceMonitor(
            processor, {'processing': {'auto_tuning': {'monitor_interval_seconds': 0}}})
        reads = []

        def reading():
            reads.append(1)
            if len(reads) <= 2:
                raise OSError('cgroup file vanished')
            monitor.stop_event.set()
            return _reading(95.0, 1 * GIB)

        monkeypatch.setattr('processing.resource_monitor.effective_memory', reading)
        with caplog.at_level(logging.WARNING, logger='facet.resources'):
            monitor.run()

        assert len(reads) == 3
        assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1
        assert manager.calls == [((), {'needed_available_bytes': 4 * GIB,
                                       'next_use': ['clip']})]


# ---------------------------------------------------------------------------
# Pre-chunk trim
# ---------------------------------------------------------------------------

class _TrimManager:
    def __init__(self, available, reserve_gb=4.0, events=None):
        self.available = available
        self.ram_cache_reserve_gb = reserve_gb
        self.device = 'cpu'
        self.keep_in_ram = 'auto'
        self.models = {}
        self._cpu_cache = {}
        self._cache_hits = 0
        self._cache_misses = 0
        self.evictions = []
        self.events = events if events is not None else []

    def detect_vram(self):
        return 16.0

    def get_active_profile(self):
        return {}

    def is_resident_or_cached(self, name):
        return name in self.models or name in self._cpu_cache

    def _available_bytes(self):
        return self.available

    def get_model_ram(self, name):
        return 2.0

    def load_model_only(self, name):
        return object()

    def unload_model(self, name, reclaim=True):
        pass

    def unload_all(self, keep_cached=()):
        pass

    def evict_cpu_cache(self, needed_available_bytes=None, next_use=None):
        self.evictions.append((needed_available_bytes, list(next_use or [])))
        self.events.append(('evict', needed_available_bytes))
        return []


def _processor(manager, groups, monkeypatch, chunk=2):
    config = {'processing': {'ram_chunk_size': chunk, 'load_workers': 1,
                             'auto_tuning': {'enabled': False}}}
    scorer = types.SimpleNamespace(flush_person_centroids=lambda: None)
    with mock.patch('processing.multi_pass._ensure_imports'):
        proc = ChunkedMultiPassProcessor(scorer, manager, config)
    proc.pass_groups = groups
    return proc


class TestNextUseOrder:

    def test_forward_order_of_the_plan_without_repeats(self, monkeypatch):
        proc = _processor(_TrimManager(0), [['clip', 'topiq'], ['insightface'],
                                            ['topiq_nr_face', 'clip']], monkeypatch)
        assert proc._next_use_order() == ['clip', 'topiq', 'insightface', 'topiq_nr_face']

    def test_no_plan_is_an_empty_order(self, monkeypatch):
        proc = _processor(_TrimManager(0), None, monkeypatch)
        assert proc._next_use_order() == []

    @pytest.mark.parametrize('running_group, expected', [
        pytest.param(0, ['insightface', 'topiq_nr_face', 'clip', 'topiq'], id='group-0'),
        pytest.param(1, ['topiq_nr_face', 'clip', 'topiq', 'insightface'], id='group-1'),
        pytest.param(2, ['clip', 'topiq', 'insightface', 'topiq_nr_face'], id='last-group'),
    ])
    def test_mid_chunk_the_order_starts_after_the_running_group_and_wraps(
            self, running_group, expected, monkeypatch):
        """While group k runs, k+1.. come first, then the next chunk's 0..k: the far end
        of the order (what the cache evicts first) is the farthest-in-future model."""
        proc = _processor(_TrimManager(0), [['clip', 'topiq'], ['insightface'],
                                            ['topiq_nr_face', 'clip']], monkeypatch)
        proc._next_group_pos = running_group + 1
        assert proc._next_use_order() == expected

    def test_process_chunk_tracks_the_running_group_and_resets_between_chunks(
            self, monkeypatch):
        proc = _processor(_TrimManager(0), [['a'], ['b'], ['c']], monkeypatch)
        seen = []
        monkeypatch.setattr(proc, '_load_images', lambda paths: {})
        monkeypatch.setattr(proc, '_load_pass_models',
                            lambda group, supp, failed: {n: object() for n in group})
        monkeypatch.setattr(proc, '_run_model_pass',
                            lambda name, model, images, results: seen.append(
                                (name, proc._next_use_order())))
        monkeypatch.setattr(proc, '_compute_aggregates', lambda results, images: None)
        monkeypatch.setattr(proc, '_save_results', lambda results, images: None)
        monkeypatch.setattr(proc, '_unload_group', lambda group, loaded: None)
        monkeypatch.setattr(proc, '_reclaim_freed_memory', lambda: None)

        with mock.patch('processing.multi_pass._ensure_imports'):
            proc._process_chunk(['/p/1.jpg'], 0, 1)

        assert seen == [('a', ['b', 'c', 'a']), ('b', ['c', 'a', 'b']),
                        ('c', ['a', 'b', 'c'])]
        assert proc._next_use_order() == ['a', 'b', 'c']


class TestPreChunkTrim:

    def _estimate(self, n, mean_px, reserve_gb=4.0):
        return int(n * mean_px * ChunkedMultiPassProcessor.RETAINED_BYTES_PER_PX) + int(
            reserve_gb * GIB)

    def test_trims_to_the_next_decode_plus_the_reserve_when_it_does_not_fit(
            self, monkeypatch):
        manager = _TrimManager(available=0)
        proc = _processor(manager, [['clip'], ['topiq']], monkeypatch)
        proc._last_chunk_mean_px = 12_000_000
        needed = self._estimate(16, 12_000_000)

        manager.available = needed - 1
        proc._trim_ram_cache_for_next_chunk(16)

        assert manager.evictions == [(needed, ['clip', 'topiq'])]

    def test_skipped_when_the_next_chunk_fits(self, monkeypatch):
        manager = _TrimManager(available=0)
        proc = _processor(manager, [['clip']], monkeypatch)
        proc._last_chunk_mean_px = 12_000_000
        manager.available = self._estimate(16, 12_000_000)

        proc._trim_ram_cache_for_next_chunk(16)

        assert manager.evictions == []

    def test_an_unknown_previous_mean_uses_the_conservative_default(self, monkeypatch):
        manager = _TrimManager(available=0)
        proc = _processor(manager, [['clip']], monkeypatch)
        assert proc._last_chunk_mean_px is None

        proc._trim_ram_cache_for_next_chunk(3)

        assert manager.evictions == [(
            self._estimate(3, ChunkedMultiPassProcessor.DEFAULT_DECODE_MEAN_PX), ['clip'])]

    @pytest.mark.parametrize('manager', [
        pytest.param(mock.MagicMock(), id='magicmock'),
        pytest.param(types.SimpleNamespace(), id='no-reserve'),
    ])
    def test_a_manager_without_a_numeric_reserve_is_left_alone(self, manager, monkeypatch):
        manager.detect_vram = lambda: 16.0
        proc = _processor(manager, [['clip']], monkeypatch)
        proc._trim_ram_cache_for_next_chunk(4)
        if isinstance(manager, mock.MagicMock):
            manager.evict_cpu_cache.assert_not_called()

    def test_process_directory_trims_before_every_chunk_but_the_first(self, monkeypatch):
        events = []
        manager = _TrimManager(available=0, events=events)
        proc = _processor(manager, [['clip']], monkeypatch, chunk=2)
        trims = []
        real_trim = proc._trim_ram_cache_for_next_chunk

        def trim(n_next):
            trims.append(n_next)
            return real_trim(n_next)

        def decode(paths, stop_event=None, report_error=None):
            events.append(('decode', len(paths)))
            return {p: {'pil': None, 'width': 4000, 'height': 3000} for p in paths}

        monkeypatch.setattr(proc, '_trim_ram_cache_for_next_chunk', trim)
        monkeypatch.setattr(proc, '_load_images', decode)
        monkeypatch.setattr(proc, '_run_model_pass', lambda *a: None)
        monkeypatch.setattr(proc, '_compute_aggregates', lambda results, images: None)
        monkeypatch.setattr(proc, '_save_results', lambda results, images: None)

        proc.process_directory(['/a', '/b', '/c', '/d', '/e'], show_progress=False)

        assert trims == [2, 1]
        needed = self._estimate(2, 12_000_000)
        assert manager.evictions[0] == (needed, ['clip'])
        assert manager.evictions[1] == (self._estimate(1, 12_000_000), ['clip'])
        # each trim happens before that chunk's decode
        assert events == [('decode', 2), ('evict', needed), ('decode', 2),
                          ('evict', self._estimate(1, 12_000_000)), ('decode', 1)]
