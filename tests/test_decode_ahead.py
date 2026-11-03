"""Decode-ahead (issue #433 step 4): the next chunk's first photos decode during this chunk's passes.

Only the FIRST ``k`` photos of the next chunk are decoded ahead, within the chunk boundaries the
loop and the auto-tuner fix as before; ``k`` is the smallest of three budgets (physical RAM,
Windows commit headroom, the room under the resource monitor's growth threshold). Everything
else - failed ahead photos, the rest of the chunk - goes through today's path.

Deterministic: the memory, commit and total-RAM readers are injected, threads are ordered with
Events, and no assertion reads the wall clock.
"""

from __future__ import annotations

import gc
import logging
import sys
import threading
import weakref
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

import pytest

pytest.importorskip("torch")

from processing.multi_pass import ChunkedMultiPassProcessor, _resolved  # noqa: E402
from processing.resource_monitor import MultiPassResourceMonitor  # noqa: E402
from utils.system_memory import EffectiveMemory  # noqa: E402
from tests.test_scan_decode_overlap import GIB, TIMEOUT, _Manager, _processor  # noqa: E402

PX = 500_000                      # pixels of every stub photo (1000 x 500)
PER_PHOTO = int(PX * ChunkedMultiPassProcessor.RETAINED_BYTES_PER_PX)
RESERVE = 1 * GIB
BIG = 1024 * GIB


class _Img(dict):
    """A decoded photo that can be weak-referenced (a plain dict cannot)."""

    __hash__ = object.__hash__


def _paths(n):
    return [f'/p/{i:02d}.jpg' for i in range(n)]


def _entry(path):
    return _Img(pil=None, width=1000, height=500, path=path, thumbnail=path.encode())


class _Run:
    """A processor wired for decode-ahead scans, with every observable recorded."""

    def __init__(self, monkeypatch, *, chunk=4, groups=None, ahead=True, available=BIG,
                 commit=None, workers=1, tuning=False, restricted=False, on_error=None):
        self.manager = _Manager(available=available, reserve_gb=RESERVE / GIB)
        self.manager.get_model_ram = lambda name: 0.0
        self.proc = _processor(self.manager, groups or [['clip'], ['insightface']], monkeypatch,
                               chunk=chunk, workers=workers, restricted=restricted,
                               on_error=on_error,
                               executor=ThreadPoolExecutor(1, thread_name_prefix='facet-decode'))
        proc = self.proc
        proc.DECODE_AHEAD = ahead
        proc._commit_provider = lambda: commit
        proc._total_ram_provider = lambda: 100 * GIB
        proc.auto_tuning_enabled = tuning
        self.saved = []           # per saved chunk: [(path, image)]
        self.loads = []           # (tuple(paths), thread name) per _load_images call
        self.submits = []         # photos handed to each ahead decode
        self.fail_once = set()    # paths whose first decode comes back empty
        self.fail_always = set()
        self.fail_error = 'failed to load image'   # what the loader reports for a failed photo
        self.raise_in_ahead = None
        self.raw_decode = None    # path -> runs the real RAW timeout path for a failing photo
        self.size_of = None       # path -> (w, h): the photo then carries a real PIL image
        self._seen = set()
        self.live = weakref.WeakSet()
        self.max_live = 0
        monkeypatch.setattr(proc, '_load_images', self._load_images)
        monkeypatch.setattr(proc, '_fetch_exif', lambda batch, stop_event: {})
        monkeypatch.setattr(proc, '_save_results', self._save)
        monkeypatch.setattr(proc, '_save_results_restricted', self._save)
        real_worker = proc._decode_ahead_on_worker

        def worker(first, errors):
            self.submits.append(list(first))
            if self.raise_in_ahead is not None:
                raise self.raise_in_ahead
            return real_worker(first, errors)

        monkeypatch.setattr(proc, '_decode_ahead_on_worker', worker)
        self.run_pass_hook = None
        self.wait_ahead = False   # let the ahead decode finish before a pass is measured

        def run_pass(name, model, images, results):
            proc._test_log.append(('infer', name, tuple(images)))
            if self.wait_ahead and proc._ahead is not None:
                proc._ahead['future'].result(TIMEOUT)
            self.max_live = max(self.max_live, len(self.live))
            if self.run_pass_hook:
                self.run_pass_hook(name, images)

        monkeypatch.setattr(proc, '_run_model_pass', run_pass)

    def _load_images(self, paths, stop_event=None, report_error=None, exif=None, defer_exif=False,
                     on_decoded=None):
        if exif is None and not defer_exif:
            self.proc._take_exif(paths)
        self.loads.append((tuple(paths), threading.current_thread().name))
        report_error = report_error or self.proc.on_error      # as the real loader's default
        out = {}
        for path in paths:
            first = path not in self._seen
            self._seen.add(path)
            if path in self.fail_always or (first and path in self.fail_once):
                if self.raw_decode is not None:
                    self.raw_decode(path)
                if report_error:
                    report_error(path, 'load', self.fail_error)
                continue
            out[path] = _entry(path)
            out[path]['exif'] = None if defer_exif else {}
            if self.size_of is not None:
                from PIL import Image
                width, height = self.size_of(path)
                out[path].update(pil=Image.new('RGB', (width, height)), width=width, height=height)
            self.live.add(out[path])
            if on_decoded is not None:
                on_decoded(out[path])
        self.max_live = max(self.max_live, len(self.live))
        return out

    def _save(self, results, images):
        self.saved.append([(p, dict(images[p])) for p in images])

    def scan(self, paths):
        self.proc.process_directory(paths, show_progress=False)
        return self


def _enough(run, n_photos):
    """``available`` that admits exactly ``n_photos`` per ahead decode (previous px = PX)."""
    run.proc._last_chunk_mean_px = PX
    return RESERVE + run.proc._decode_inflight_bytes(100) + int(n_photos * PER_PHOTO) + 10


class TestIdenticalToNoAhead:

    def test_results_images_and_pass_order_equal_k_zero(self, monkeypatch):
        paths = _paths(14)

        def scan(ahead):
            run = _Run(monkeypatch, chunk=4, ahead=ahead)
            run.manager.available = _enough(run, 2)    # partial: 2 of each 4
            run.scan(paths)
            return run

        off, on = scan(False), scan(True)
        assert off.proc.metrics['decode_ahead_photos'] == 0
        assert on.proc.metrics['decode_ahead_photos'] >= 4, "the feature did not run"
        assert on.saved == off.saved
        assert [e for e in on.proc._test_log if isinstance(e, tuple)] == [
            e for e in off.proc._test_log if isinstance(e, tuple)]
        assert on.proc.metrics['chunks_processed'] == off.proc.metrics['chunks_processed'] == 4
        assert on.proc.metrics['images_processed'] == 14


class TestBudget:
    """k is floor(min(budgets) - in-flight) / per-photo, clamped to the chunk."""

    def _proc(self, monkeypatch, *, available=BIG, commit=None, tuning=False, peak=50.0,
              total=100 * GIB, **manager_kwargs):
        run = _Run(monkeypatch, available=available, commit=commit, tuning=tuning,
                   **manager_kwargs)
        proc = run.proc
        proc._last_chunk_mean_px = PX
        proc._total_ram_provider = lambda: total
        proc._ram_monitor = mock.Mock(last_chunk_peak_percent=peak, low_threshold=65)
        return proc

    @staticmethod
    def _need(proc, k):
        return RESERVE + proc._decode_inflight_bytes(10) + k * PER_PHOTO

    def test_physical_ram_is_a_term(self, monkeypatch):
        proc = self._proc(monkeypatch)
        proc.model_manager.available = self._need(proc, 5) + PER_PHOTO - 1
        assert proc._decode_ahead_photo_count(1, 10) == 5
        proc.model_manager.available = self._need(proc, 5) + PER_PHOTO
        assert proc._decode_ahead_photo_count(1, 10) == 6
        proc.model_manager.available = RESERVE + proc._decode_inflight_bytes(10) - 1
        assert proc._decode_ahead_photo_count(1, 10) == 0

    def test_windows_commit_headroom_is_a_term(self, monkeypatch):
        proc = self._proc(monkeypatch, commit=0)
        proc._commit_provider = lambda: self._need(proc, 3) + PER_PHOTO - 1
        assert proc._decode_ahead_photo_count(1, 10) == 3      # physical is 1024 GiB
        proc._commit_provider = lambda: self._need(proc, 3) + PER_PHOTO
        assert proc._decode_ahead_photo_count(1, 10) == 4
        proc._commit_provider = lambda: None                    # no commit on this platform
        assert proc._decode_ahead_photo_count(1, 10) == 10

    def test_room_under_the_growth_threshold_is_a_term(self, monkeypatch):
        proc = self._proc(monkeypatch, tuning=True, peak=60.0)
        inflight = proc._decode_inflight_bytes(10)
        # (65 - 60) % of the total, exactly 4 photos plus the in-flight buffers, less a byte
        total = int((inflight + 4 * PER_PHOTO) / 0.05) - 1000
        proc._total_ram_provider = lambda: total
        assert proc._decode_ahead_photo_count(1, 10) == 3
        proc._total_ram_provider = lambda: total + 2000
        assert proc._decode_ahead_photo_count(1, 10) == 4
        proc._ram_monitor.last_chunk_peak_percent = 65.0        # no room left at all
        assert proc._decode_ahead_photo_count(1, 10) == 0

    def test_the_smallest_term_binds(self, monkeypatch):
        proc = self._proc(monkeypatch, tuning=True, peak=60.0)
        proc.model_manager.available = self._need(proc, 7)
        proc._commit_provider = lambda: self._need(proc, 2)
        proc._total_ram_provider = lambda: int((proc._decode_inflight_bytes(10)
                                                + 5 * PER_PHOTO) / 0.05) + 1000
        assert proc._decode_ahead_photo_count(1, 10) == 2

    def test_the_ahead_bytes_leave_room_for_the_next_cacheable_model(self, monkeypatch):
        """The RAM cache keeps a model only while available > its RAM + reserve."""
        proc = self._proc(monkeypatch)
        proc.model_manager.get_model_ram = lambda name: 3.0
        proc.model_manager.available = self._need(proc, 5) + PER_PHOTO - 1 + 3 * GIB
        assert proc._decode_ahead_photo_count(1, 10) == 5
        proc.model_manager.available = self._need(proc, 5) + PER_PHOTO - 1 + 3 * GIB - PER_PHOTO
        assert proc._decode_ahead_photo_count(1, 10) == 4
        # a model the cache never keeps asks for nothing
        proc.model_manager.CPU_CACHEABLE_MODELS = frozenset({'other'})
        proc.model_manager.available = self._need(proc, 5) + PER_PHOTO - 1
        assert proc._decode_ahead_photo_count(1, 10) == 5

    @pytest.mark.parametrize('groups', [
        pytest.param([['clip'], ['topiq']], id='one model per group'),
        pytest.param([['clip', 'samp_net'], ['topiq', 'liqe']], id='two models per group'),
        pytest.param([['topiq'], ['insightface', 'saliency']], id='insightface is never cached'),
    ])
    @pytest.mark.parametrize('spare_gb', [6, 8, 10, 14])
    def test_the_chunk_caches_the_models_it_cached_without_the_ahead(
            self, groups, spare_gb, monkeypatch):
        """Every group of the chunk unloads after the submit, with the ahead bytes resident."""
        from models.model_manager import ModelManager
        ram = ModelManager.MODEL_RAM_REQUIREMENTS
        reserve_gb = 4.0
        proc = self._proc(monkeypatch, groups=groups)
        mm = proc.model_manager
        mm.ram_cache_reserve_gb = reserve_gb
        mm.get_model_ram = lambda name: ram.get(name, 2.0)
        mm.CPU_CACHEABLE_MODELS = ModelManager.CPU_CACHEABLE_MODELS
        proc._last_chunk_mean_px = 20_000_000
        available = int((reserve_gb + spare_gb) * GIB)
        mm.available = available

        def admitted(free):
            cached = []
            for name in (n for group in groups for n in group):
                if name == 'insightface' or name not in ModelManager.CPU_CACHEABLE_MODELS:
                    continue                      # ModelManager._can_cache_to_ram on CUDA
                if free / GIB > ram.get(name, 2.0) + reserve_gb:
                    cached.append(name)
                    free -= int(ram.get(name, 2.0) * GIB)
            return cached

        k = proc._decode_ahead_photo_count(1, 64)
        ahead_bytes = int(k * proc._previous_chunk_px() * proc.RETAINED_BYTES_PER_PX)
        assert admitted(available - ahead_bytes) == admitted(available)

    def test_the_trim_waits_for_the_ahead_decode_it_accounts_for(self, monkeypatch):
        proc = self._proc(monkeypatch)
        order = []
        monkeypatch.setattr(proc, '_trim_ram_cache_for_next_chunk',
                            lambda n: order.append(('trim', n)))
        release = threading.Event()
        pool = ThreadPoolExecutor(1)
        chunk = _paths(4)

        def decode():
            release.wait(TIMEOUT)
            order.append('decoded')
            return {}, 0.0

        proc._ahead = {'paths': chunk[:3], 'future': pool.submit(decode), 'errors': []}
        threading.Timer(0.3, release.set).start()
        try:
            proc._trim_before_chunk(chunk)
        finally:
            release.set()
            pool.shutdown()
        assert order == ['decoded', ('trim', 1)]

    def test_the_trim_before_a_chunk_does_not_count_the_photos_already_decoded_ahead(
            self, monkeypatch):
        proc = self._proc(monkeypatch)
        trimmed = []
        monkeypatch.setattr(proc, '_trim_ram_cache_for_next_chunk', trimmed.append)
        chunk = _paths(4)
        proc._ahead = {'paths': chunk[:3], 'future': mock.Mock(), 'errors': []}
        proc._trim_before_chunk(chunk)
        proc._ahead = None
        proc._trim_before_chunk(chunk)
        assert trimmed == [1, 4]

    @pytest.mark.parametrize('kwargs, chunk_idx, n_next', [
        pytest.param({}, 0, 10, id='chunk-0-has-no-previous-peak'),
        pytest.param({'tuning': True, 'peak': 0.0}, 1, 10, id='peak-unknown'),
        pytest.param({'ahead': False}, 1, 10, id='switched-off'),
        pytest.param({}, 1, 0, id='nothing-next'),
        pytest.param({'keep_in_ram': 'never'}, 1, 10, id='keep-in-ram-never'),
    ])
    def test_refusals(self, kwargs, chunk_idx, n_next, monkeypatch):
        keep = kwargs.pop('keep_in_ram', None)
        proc = self._proc(monkeypatch, **kwargs)
        if keep:
            proc.model_manager.keep_in_ram = keep
        assert proc._decode_ahead_photo_count(chunk_idx, n_next) == 0

    @pytest.mark.parametrize('device', ['cpu', 'mps'])
    def test_only_cuda_decodes_ahead(self, device, monkeypatch):
        proc = self._proc(monkeypatch)
        proc.model_manager.device = device
        assert proc._decode_ahead_photo_count(1, 10) == 0

    def test_k_is_clamped_to_the_next_chunk(self, monkeypatch):
        assert self._proc(monkeypatch)._decode_ahead_photo_count(1, 3) == 3

    def test_a_scan_never_submits_more_than_the_budget(self, monkeypatch):
        run = _Run(monkeypatch, chunk=4)
        run.manager.available = BIG
        run.proc._commit_provider = lambda: _enough(run, 1)     # commit binds: 1 photo
        run.scan(_paths(16))
        assert run.submits, "the feature did not run"
        assert max(len(s) for s in run.submits) == 1
        assert run.proc.metrics['decode_ahead_photos'] == len(run.submits)

    def test_commit_headroom_is_none_off_windows(self, monkeypatch):
        from utils import system_memory
        monkeypatch.setattr(system_memory.sys, 'platform', 'linux')
        assert system_memory.commit_headroom_bytes() is None

    @pytest.mark.skipif(sys.platform != 'win32', reason='Windows commit charge')
    def test_commit_headroom_reads_bytes_on_windows(self):
        from utils.system_memory import commit_headroom_bytes
        value = commit_headroom_bytes()
        assert isinstance(value, int) and 0 < value < 1 << 50


class TestLiveChunks:

    def test_at_most_the_chunk_plus_its_ahead_photos_are_alive(self, monkeypatch):
        run = _Run(monkeypatch, chunk=4)
        run.wait_ahead = True
        run.manager.available = _enough(run, 2)
        run.scan(_paths(16))
        gc.collect()
        assert run.proc.metrics['decode_ahead_photos'] > 0
        assert run.max_live == 4 + 2, run.max_live
        del run.saved[:]
        gc.collect()
        assert len(run.live) == 0


class TestBoundaryChange:

    def _scan(self, monkeypatch, sizes, ahead_photos, configure=None):
        """Chunk sizes follow ``sizes`` (set after each chunk, as the monitor would)."""
        run = _Run(monkeypatch, chunk=sizes[0], on_error=getattr(self, '_on_error', None))
        run.manager.available = _enough(run, ahead_photos)
        if configure is not None:
            configure(run)
        script = iter(sizes[1:])
        proc = run.proc

        class Monitor:
            adjustments: list = []
            last_chunk_peak_percent = 0.0
            low_threshold = 65

            def __init__(self, *_a, **_k):
                pass

            def start(self):
                pass

            def stop(self):
                pass

            def note_chunk_complete(self):
                proc.chunk_size = next(script, proc.chunk_size)

        monkeypatch.setattr('processing.resource_monitor.MultiPassResourceMonitor', Monitor)
        paths = _paths(20)
        run.scan(paths)
        return run, paths

    @pytest.mark.parametrize('sizes', [
        pytest.param([4, 4, 2, 2, 2, 2, 2, 2, 2, 2], id='shrinks-below-the-ahead-photos'),
        pytest.param([4, 4, 8, 8, 8, 8], id='grows'),
        pytest.param([4, 6, 3, 5, 2, 7, 3, 3, 3, 3], id='moves-every-chunk'),
    ])
    def test_every_photo_once_in_order_whatever_the_chunk_size_does(self, sizes, monkeypatch):
        run, paths = self._scan(monkeypatch, sizes, ahead_photos=3)
        saved = [p for chunk in run.saved for p, _ in chunk]
        assert saved == paths
        assert run.proc.metrics['images_processed'] == 20
        for chunk in run.saved:                       # content follows the path
            assert all(img['thumbnail'] == p.encode() for p, img in chunk)
        assert run.proc.metrics['decode_ahead_photos'] > 0

    def test_ahead_photos_past_a_shrunk_boundary_are_dropped_not_reused(self, monkeypatch):
        run, _ = self._scan(monkeypatch, [4, 4, 2, 2, 2, 2, 2, 2, 2, 2, 2], ahead_photos=3)
        # chunk 1 (4 photos) submitted 3 ahead for chunk 2, which shrank to 2: one is dropped
        # and decoded again when it becomes part of chunk 3
        assert run.submits[0] == _paths(20)[8:11]
        assert run.proc.metrics['decode_ahead_photos'] >= 2


    @pytest.mark.parametrize('error, decodes', [
        pytest.param(TimeoutError('slow'), 1, id='timeout: decoded once'),
        pytest.param('failed to load image', 2, id='failure: once more in its own chunk'),
    ])
    def test_a_failed_photo_past_a_shrunk_boundary_is_reported_once(self, error, decodes,
                                                                    monkeypatch):
        errors = []
        self._on_error = lambda *a: errors.append(a)
        victim = _paths(20)[10]       # ahead for chunk 2 (8, 9, 10), which shrank to 8, 9

        def configure(run):
            run.fail_always = {victim}
            run.fail_error = error

        run, _ = self._scan(monkeypatch, [4, 4, 2, 2, 2, 2, 2, 2, 2, 2, 2], 3, configure)
        assert run.submits[0][2] == victim, "the photo was not decoded ahead"
        assert errors == [(victim, 'load', error)]
        assert victim not in {p for chunk in run.saved for p, _ in chunk}
        assert sum(1 for chunk, _ in run.loads if victim in chunk) == decodes


class TestAheadFailureIsRedecoded:
    """A failed ahead decode is decoded again in its chunk; a timeout is reported once, not retried."""

    def test_a_photo_that_ran_out_of_memory_ahead_is_decoded_again_and_not_reported(
            self, monkeypatch):
        errors = []
        paths = _paths(12)
        run = _Run(monkeypatch, chunk=4, on_error=lambda *a: errors.append(a))
        run.manager.available = _enough(run, 2)
        run.fail_once = {paths[8]}
        run.fail_error = MemoryError('commit')
        run.scan(paths)
        assert errors == []
        assert run.proc.metrics['decode_ahead_redecoded'] == 1
        flat = dict(p for chunk in run.saved for p in chunk)
        assert flat[paths[8]]['thumbnail'] == paths[8].encode()
        assert sum(1 for chunk, _ in run.loads if paths[8] in chunk) == 2

    def test_a_failed_ahead_decode_is_decoded_again_in_its_chunk_and_saved(self, monkeypatch):
        """The loaders turn a MemoryError into 'failed to load image': that is a failure too."""
        errors = []
        paths = _paths(12)
        run = _Run(monkeypatch, chunk=4, on_error=lambda *a: errors.append(a))
        run.manager.available = _enough(run, 2)
        run.fail_once = {paths[8]}
        run.scan(paths)
        assert errors == []
        flat = dict(p for chunk in run.saved for p in chunk)
        assert flat[paths[8]]['thumbnail'] == paths[8].encode()
        assert sum(1 for chunk, _ in run.loads if paths[8] in chunk) == 2
        assert run.proc.metrics['decode_ahead_redecoded'] == 1

    def test_a_photo_that_fails_again_in_its_chunk_is_reported_once(self, monkeypatch):
        errors = []
        paths = _paths(12)
        run = _Run(monkeypatch, chunk=4, on_error=lambda *a: errors.append(a))
        run.manager.available = _enough(run, 2)
        run.fail_always = {paths[8]}
        run.scan(paths)
        assert errors == [(paths[8], 'load', 'failed to load image')]
        assert paths[8] not in {p for chunk in run.saved for p, _ in chunk}
        assert sum(1 for chunk, _ in run.loads if paths[8] in chunk) == 2

    def test_a_timeout_is_reported_once_and_never_decoded_again(self, monkeypatch):
        errors = []
        paths = _paths(12)
        run = _Run(monkeypatch, chunk=4, on_error=lambda *a: errors.append(a))
        run.manager.available = _enough(run, 2)
        run.fail_always = {paths[8]}
        run.fail_error = TimeoutError('slow')
        run.scan(paths)
        assert errors == [(paths[8], 'load', run.fail_error)]
        assert paths[8] not in {p for chunk in run.saved for p, _ in chunk}
        assert sum(1 for chunk, _ in run.loads if paths[8] in chunk) == 1
        assert run.proc.metrics['decode_ahead_redecoded'] == 0

    def test_a_real_raw_decode_timeout_is_decoded_once_and_hangs_one_slot(self, monkeypatch):
        """The loader returns None for a timed-out RAW; ``consume_decode_timeout`` tells it apart."""
        from utils import image_loading as il
        release = threading.Event()
        calls = []

        def blocking_decode(photo, use_thumbnail, started=None, *a, **k):
            calls.append(photo)
            if started is not None:
                started.set()
            release.wait(TIMEOUT)

        pool = ThreadPoolExecutor(4)
        monkeypatch.setattr(il, '_decode_raw', blocking_decode)
        monkeypatch.setattr(il, '_decode_timeout', 0.05)
        monkeypatch.setattr(il, '_decode_concurrency', 4)
        monkeypatch.setattr(il, '_decode_executor', pool)
        monkeypatch.setattr(il, '_hung_decodes', 0)
        monkeypatch.setattr(il, '_abandoned_decodes', 0)
        errors = []
        paths = _paths(12)
        run = _Run(monkeypatch, chunk=4, on_error=lambda *a: errors.append(a))
        run.manager.available = _enough(run, 2)
        run.fail_always = {paths[8]}
        run.raw_decode = lambda path: il._decode_raw_with_timeout(path, False, 'library', None, False)
        try:
            run.scan(paths)
            hung = il._hung_decodes
        finally:
            release.set()
            pool.shutdown()
        assert calls == [paths[8]]
        assert hung == 1
        assert [e[0] for e in errors] == [paths[8]]
        assert paths[8] not in {p for chunk in run.saved for p, _ in chunk}
        assert run.proc.metrics['decode_ahead_redecoded'] == 0

    def test_the_ahead_future_running_out_of_memory_falls_back_to_the_normal_path(
            self, monkeypatch):
        errors = []
        paths = _paths(12)
        base = _Run(monkeypatch, chunk=4, ahead=False).scan(paths)
        run = _Run(monkeypatch, chunk=4, on_error=lambda *a: errors.append(a))
        run.manager.available = _enough(run, 2)
        run.raise_in_ahead = MemoryError('commit')
        run.scan(paths)
        assert errors == []
        assert run.saved == base.saved
        assert run.proc.metrics['decode_ahead_redecoded'] >= 2
        assert run.proc.metrics['decode_ahead_chunks'] == 0

    def test_the_ahead_future_raising_anything_else_surfaces_as_the_normal_path_would(
            self, monkeypatch):
        paths = _paths(12)
        run = _Run(monkeypatch, chunk=4)
        run.manager.available = _enough(run, 2)
        run.raise_in_ahead = RuntimeError('abandoned')
        with pytest.raises(RuntimeError, match='abandoned'):
            run.scan(paths)


class TestAutoTuneUnchanged:

    @staticmethod
    def _tuned_scan(monkeypatch, ahead, *, size_of, total, base_pct, n, chunk, max_chunk,
                    high=85):
        """A scan whose host reading is base + the bytes of every live photo, as a host's is.

        The photos carry real PIL images of ``size_of(path)``; ``high`` is the shrink limit
        (``low`` is high - 20). Every pass reads the monitor once, the ahead decode finished.
        """
        run = _Run(monkeypatch, chunk=chunk, ahead=ahead, tuning=True, workers=1)
        run.manager.available = BIG
        run.size_of = size_of
        proc = run.proc
        proc.max_chunk_size = max_chunk
        proc.min_chunk_size = 2
        proc._total_ram_provider = lambda: total
        run.wait_ahead = True
        holder = {}

        def reading():
            gc.collect()
            used = int(base_pct / 100 * total) + sum(
                e['width'] * e['height'] * 4 + len(e['thumbnail']) for e in list(run.live))
            return EffectiveMemory(total, used, total - used, 100.0 * used / total)

        monkeypatch.setattr('processing.resource_monitor.effective_memory', reading)

        class Monitor(MultiPassResourceMonitor):
            def __init__(self, processor, config=None):
                cfg = {'processing': {'auto_tuning': {'memory_limit_percent': high}}}
                super().__init__(processor, cfg)
                holder['m'] = self

            def start(self):
                pass

        monkeypatch.setattr('processing.resource_monitor.MultiPassResourceMonitor', Monitor)
        run.run_pass_hook = lambda name, images: holder['m']._tick()
        run.scan(_paths(n))
        return run, [len(c) for c in run.saved], list(holder['m'].adjustments)

    def test_photos_of_changing_size_decide_as_without_ahead(self, monkeypatch):
        """Small photos, then RAW-sized ones: the held bytes are measured, not estimated."""
        def scan(ahead):
            return self._tuned_scan(
                monkeypatch, ahead, size_of=lambda p: (100, 100) if int(p[3:-4]) < 150 else (400, 300),
                total=120 * 360_000, base_pct=56.0, n=600, chunk=16, max_chunk=200)

        off, sizes_off, adj_off = scan(False)
        on, sizes_on, adj_on = scan(True)
        assert max(sizes_off) > 16 and adj_off, "the scan never tuned"
        assert on.proc.metrics['decode_ahead_photos'] > 0, "the feature did not run"
        assert sizes_on == sizes_off and adj_on == adj_off

    def test_the_shrink_test_reads_the_value_without_the_ahead_bytes(self, monkeypatch):
        """Small photos, then large ones: the ahead holds far more than its estimate said."""
        def scan(ahead):
            return self._tuned_scan(
                monkeypatch, ahead, size_of=lambda p: (100, 100) if int(p[3:-4]) < 32 else (400, 300),
                total=55 * 480_000, base_pct=15.0, n=64, chunk=16, max_chunk=16, high=45)

        off, sizes_off, adj_off = scan(False)
        on, sizes_on, adj_on = scan(True)
        assert on.proc.metrics['decode_ahead_photos'] > 0, "the feature did not run"
        assert not [a for a in adj_off if a[0] == 'reduce'], "the base scan must not shrink"
        assert sizes_on == sizes_off and adj_on == adj_off

    @pytest.mark.parametrize('peak, grows', [(64.9, True), (65.0, False), (0.0, False)])
    def test_the_growth_rule_and_the_exposed_peak(self, peak, grows):
        proc = mock.Mock(chunk_size=10, increase_chunk_size=mock.Mock(return_value=True))
        monitor = MultiPassResourceMonitor(proc, {})
        monitor._peak_percent = peak
        monitor.note_chunk_complete()
        assert proc.increase_chunk_size.called is grows
        assert monitor.last_chunk_peak_percent == peak
        assert monitor._peak_percent == 0.0


class TestStopAndCleanup:

    @staticmethod
    def _ahead_threads():
        return [t for t in threading.enumerate()
                if t.name.startswith(('facet-decode', 'facet-exif-prefetch', 'imgload'))
                and t.is_alive()]

    def test_interrupt_while_the_ahead_decode_runs_unwinds_and_drops_its_images(
            self, monkeypatch):
        release = threading.Event()
        started = threading.Event()
        run = _Run(monkeypatch, chunk=4)
        run.manager.available = BIG
        real = run._load_images
        probes = []

        def load_images(paths, stop_event=None, report_error=None, exif=None, defer_exif=False,
                        on_decoded=None):
            if threading.current_thread().name.startswith('facet-decode') \
                    and paths[0] == _paths(12)[8]:
                started.set()
                release.wait(TIMEOUT)
            out = real(paths, stop_event, report_error, exif, defer_exif)
            if paths[0] == _paths(12)[8]:
                probes.extend(weakref.ref(v) for v in out.values())
            return out

        monkeypatch.setattr(run.proc, '_load_images', load_images)

        def interrupt(name, images):
            if started.wait(TIMEOUT):
                raise KeyboardInterrupt()

        run.run_pass_hook = interrupt
        try:
            with pytest.raises(KeyboardInterrupt):
                run.scan(_paths(12))
            assert run.proc._ahead is None
        finally:
            release.set()
        for thread in self._ahead_threads():
            thread.join(TIMEOUT)
        assert self._ahead_threads() == []
        run.saved.clear()
        run.proc._test_log.clear()
        gc.collect()
        assert probes and all(ref() is None for ref in probes), "ahead images are still held"
        assert ('unload_all',) in run.manager.events

    def test_interrupt_while_the_scan_thread_waits_for_the_ahead_decode(self, monkeypatch):
        import _thread
        release = threading.Event()
        run = _Run(monkeypatch, chunk=4)
        run.manager.available = BIG
        real = run._load_images

        def load_images(paths, stop_event=None, report_error=None, exif=None, defer_exif=False,
                        on_decoded=None):
            if threading.current_thread().name.startswith('facet-decode') \
                    and paths[0] == _paths(12)[4] and defer_exif:
                # the ahead decode of chunk 1 blocks; chunk 0's passes are over by then
                threading.Timer(0.5, _thread.interrupt_main).start()
                release.wait(TIMEOUT)
            return real(paths, stop_event, report_error, exif, defer_exif)

        monkeypatch.setattr(run.proc, '_load_images', load_images)
        # chunk 0 never decodes ahead; make chunk 1 the first that does by lifting the guard
        orig = run.proc._decode_ahead_photo_count
        monkeypatch.setattr(run.proc, '_decode_ahead_photo_count',
                            lambda idx, n: orig(max(idx, 1), n))
        try:
            with pytest.raises(KeyboardInterrupt):
                run.scan(_paths(12))
        finally:
            release.set()
        for thread in self._ahead_threads():
            thread.join(TIMEOUT)
        assert self._ahead_threads() == []
        assert run.proc._ahead is None


class TestLastChunkAndSubmissions:

    @pytest.mark.parametrize('n, chunk, submissions', [
        pytest.param(4, 4, 0, id='single-chunk'),
        pytest.param(8, 4, 0, id='two-chunks: chunk 0 cannot decode ahead'),
        pytest.param(12, 4, 1, id='three-chunks'),
        pytest.param(17, 4, 3, id='short-last-chunk'),
    ])
    def test_chunk_zero_and_the_last_chunk_submit_nothing(self, n, chunk, submissions,
                                                          monkeypatch):
        run = _Run(monkeypatch, chunk=chunk).scan(_paths(n))
        assert len(run.submits) == submissions
        flat = [p for c in run.saved for p, _ in c]
        assert flat == _paths(n)

    def test_the_switch_off_never_submits(self, monkeypatch):
        run = _Run(monkeypatch, chunk=4, ahead=False).scan(_paths(16))
        assert run.submits == []
        assert run.proc.metrics['decode_ahead_chunks'] == 0


class TestRestrictedAndResume:

    def test_restricted_scans_save_the_same_chunks_with_and_without_ahead(self, monkeypatch):
        def scan(ahead):
            return _Run(monkeypatch, chunk=3, groups=[['topiq']], ahead=ahead,
                        restricted=True).scan(_paths(13))

        off, on = scan(False), scan(True)
        assert len(on.submits) == 3
        assert on.saved == off.saved

    def test_a_worklist_scans_like_a_fresh_library_of_its_own_size(self, monkeypatch):
        worklist = _paths(20)[10:]
        run = _Run(monkeypatch, chunk=3).scan(worklist)
        fresh = _Run(monkeypatch, chunk=3).scan(_paths(10))
        assert len(run.submits) == len(fresh.submits) == 2
        assert all(p in worklist for s in run.submits for p in s)
        assert run.submits[0] == worklist[6:9]


class TestExifChainStaysOneChunkAhead:

    def test_each_chunks_exif_starts_before_the_previous_chunks_passes_one_at_a_time(
            self, monkeypatch):
        paths = _paths(16)
        log, active, peak = [], [], []
        lock = threading.Lock()

        def fetch(batch, stop_event):
            with lock:
                active.append(1)
                peak.append(len(active))
                log.append(('exif', tuple(batch)))
            try:
                return {key: {'iso': 100} for key in _resolved(batch)}
            finally:
                with lock:
                    active.pop()

        run = _Run(monkeypatch, chunk=4)
        run.manager.available = BIG
        monkeypatch.setattr(run.proc, '_fetch_exif', fetch)
        run.proc._test_log = log
        run.scan(paths)

        assert run.proc.metrics['decode_ahead_photos'] > 0, "the feature did not run"
        assert max(peak) == 1
        assert [e[1] for e in log if e[0] == 'exif'] == [
            tuple(paths[i:i + 4]) for i in range(0, 16, 4)], "a chunk's EXIF was fetched twice"
        index = {e[1]: i for i, e in enumerate(log) if e[0] == 'exif'}
        for c in range(3):
            nxt = tuple(paths[4 * (c + 1):4 * (c + 2)])
            this_pass = next(i for i, e in enumerate(log)
                             if e[0] == 'infer' and set(e[2]) == set(paths[4 * c:4 * (c + 1)]))
            assert index[nxt] < this_pass, f"chunk {c + 1}'s EXIF started after chunk {c}'s passes"


class TestExifBesideTheFirstModelLoad:

    @staticmethod
    def _scan(monkeypatch, ahead):
        """A chunk's EXIF fetch holds until the first group's model of that chunk loads."""
        run = _Run(monkeypatch, chunk=4, ahead=ahead, groups=[['clip'], ['topiq']])
        run.manager.available = BIG
        proc = run.proc
        order = []
        started = {}
        fetches = [0]

        def fetch(batch, stop_event):
            fetches[0] += 1
            chunk = fetches[0] - 1
            if chunk >= 2:
                order.append((chunk, started.setdefault(chunk, threading.Event()).wait(1.5)))
            return {key: {'iso': 1} for key in _resolved(batch)}

        monkeypatch.setattr(proc, '_fetch_exif', fetch)
        real_load = run.manager.load_model_only
        loads = [0]

        def load(name):
            if name == 'clip':
                loads[0] += 1
                started.setdefault(loads[0] - 1, threading.Event()).set()
            return real_load(name)

        run.manager.load_model_only = load
        run.scan(_paths(16))
        return order, proc.metrics

    def test_a_chunk_decoded_ahead_in_full_collects_its_exif_beside_the_model_load(
            self, monkeypatch):
        off, _ = self._scan(monkeypatch, False)
        on, metrics = self._scan(monkeypatch, True)
        assert metrics['decode_ahead_photos'] > 0, "the feature did not run"
        assert off == on == [(2, True), (3, True)]     # the fetch returned once the load began


class TestSummaryLine:

    def test_the_summary_states_what_the_decode_ahead_did(self, monkeypatch, caplog):
        run = _Run(monkeypatch, chunk=4)
        run.manager.available = _enough(run, 2)
        run.fail_once = {_paths(16)[9]}
        run.fail_error = MemoryError('commit')
        with caplog.at_level(logging.INFO):
            run.scan(_paths(16))
        m = run.proc.metrics
        line = (f"Decode-ahead: {m['decode_ahead_photos']} photos in "
                f"{m['decode_ahead_chunks']} chunks ({m['decode_ahead_redecoded']} re-decoded)")
        assert line in caplog.text
        assert m['decode_ahead_photos'] > 0 and m['decode_ahead_redecoded'] == 1


class TestRealLoadImagesExif:
    """The REAL ``_load_images`` and EXIF assembly; only the decoder and exiftool are stubbed."""

    def _scan(self, monkeypatch, ahead):
        from pathlib import Path

        import numpy as np
        from PIL import Image

        monkeypatch.setattr('exiftool.get_exif_batch', lambda paths, chunk_size=100, stop_event=None: {
            str(Path(p).resolve()): {'camera_model': 'batch'} for p in paths})
        monkeypatch.setattr('utils.load_image_from_path', lambda path: (
            Image.fromarray(np.full((64, 64, 3), 90, np.uint8)), np.full((64, 64, 3), 90, np.uint8)))
        manager = _Manager(available=BIG, reserve_gb=RESERVE / GIB)
        manager.get_model_ram = lambda name: 0.0
        proc = _processor(manager, [['clip']], monkeypatch, chunk=4, restricted=True,
                          executor=ThreadPoolExecutor(1, thread_name_prefix='facet-decode'))
        proc.DECODE_AHEAD = ahead
        proc._commit_provider = lambda: None
        proc.scorer.get_exif_data = lambda path: {'camera_model': 'single'}
        sizes = iter([4, 6, 6, 6, 6, 6])
        saved = {}
        monkeypatch.setattr(proc, '_save_results_restricted', lambda results, images: saved.update(
            {p: d['exif']['camera_model'] for p, d in images.items()}))

        class Monitor:
            adjustments: list = []
            last_chunk_peak_percent = 0.0
            low_threshold = 65

            def __init__(self, *_a, **_k):
                pass

            def start(self):
                pass

            def stop(self):
                pass

            def note_chunk_complete(self):
                proc.chunk_size = next(sizes, proc.chunk_size)

        monkeypatch.setattr('processing.resource_monitor.MultiPassResourceMonitor', Monitor)
        proc.process_directory(_paths(24), show_progress=False)
        return proc, saved

    def test_a_chunk_grown_after_the_submit_reads_its_exif_as_a_batch_like_without_ahead(
            self, monkeypatch):
        _, off = self._scan(monkeypatch, False)
        proc, on = self._scan(monkeypatch, True)
        assert proc.metrics['decode_ahead_photos'] > 0, "the feature did not run"
        assert set(off.values()) == {'batch'} and len(off) == 24
        assert on == off, [p for p in on if on[p] != off[p]]


class _Py310Timeout(Exception):
    """What ``Future.result(timeout=)`` raises before Python 3.11: not the builtin TimeoutError."""


class TestReview3:

    def test_wait_ahead_survives_the_python_310_future_timeout(self, monkeypatch):
        run = _Run(monkeypatch)
        calls = []

        class Future:
            def result(self, timeout=None):
                calls.append(timeout)
                if len(calls) < 3:
                    raise _Py310Timeout()
                return 'done'

            def done(self):
                return False

        monkeypatch.setattr('processing.multi_pass.FuturesTimeoutError', _Py310Timeout)
        assert run.proc._wait_ahead(Future()) == 'done'
        assert len(calls) == 3

    def test_the_python_310_timeout_class_is_a_timeout_when_the_ahead_reports_it(self, monkeypatch):
        errors = []
        paths = _paths(12)
        run = _Run(monkeypatch, chunk=4, on_error=lambda *a: errors.append(a))
        run.manager.available = _enough(run, 2)
        run.fail_always = {paths[8]}
        run.fail_error = _Py310Timeout('slow')
        monkeypatch.setattr('processing.multi_pass.FuturesTimeoutError', _Py310Timeout)
        run.scan(paths)
        assert [e[0] for e in errors] == [paths[8]]
        assert sum(1 for chunk, _ in run.loads if paths[8] in chunk) == 1

    def test_unreadable_commit_headroom_on_windows_is_zero_not_unbounded(self, monkeypatch):
        import ctypes
        import types
        from utils import system_memory
        monkeypatch.setattr(system_memory.sys, 'platform', 'win32')
        monkeypatch.setattr(ctypes, 'windll', types.SimpleNamespace(
            kernel32=types.SimpleNamespace(GlobalMemoryStatusEx=lambda *_: 0)), raising=False)
        assert system_memory.commit_headroom_bytes() == 0

    def test_zero_commit_headroom_decodes_nothing_ahead(self, monkeypatch):
        run = _Run(monkeypatch, commit=0)
        run.proc._last_chunk_mean_px = PX
        assert run.proc._decode_ahead_photo_count(1, 10) == 0

    def test_the_cacheability_rule_is_the_model_managers_own(self):
        from models.model_manager import ModelManager
        mm = ModelManager.__new__(ModelManager)
        mm.keep_in_ram, mm.device, mm._cpu_plan = 'auto', 'cuda', None
        mm.ram_cache_reserve_gb = 1.0
        mm._available_bytes = lambda: 1 << 50
        for name in list(ModelManager.CPU_CACHEABLE_MODELS) + ['insightface', 'qrealign', 'nope']:
            assert mm._can_cache_to_ram(name) == mm.is_cacheable_model(name), name

    def test_the_submitted_metric_counts_only_photos_sent_to_the_worker(self, monkeypatch):
        run = _Run(monkeypatch, chunk=4)
        run.manager.available = _enough(run, 3)
        paths = _paths(12)
        run.proc._decode_executor = ThreadPoolExecutor(1)
        run.proc._ahead_failed = {paths[4]}
        run.proc._next_paths = paths[4:8]
        run.proc._last_chunk_mean_px = PX
        run.proc._submit_decode_ahead(1)
        assert run.proc.metrics['decode_ahead_submitted'] == len(run.submits[0]) < 3
        run.proc._wait_ahead(run.proc._ahead['future'])

    def test_entry_bytes_count_a_pillow_rgb_pixel_as_four_bytes_and_a_shared_image_once(self):
        from PIL import Image
        img = Image.new('RGB', (100, 50))
        entry = ChunkedMultiPassProcessor._entry_bytes
        assert entry({'pil': img, 'bounded': img, 'thumbnail': b'xy'}) == 100 * 50 * 4 + 2
        assert entry({'pil': img, 'bounded': Image.new('L', (10, 10))}) == 100 * 50 * 4 + 100

    def test_chunks_tool_keeps_the_scan_threads_events_inside_an_ahead_span(self, tmp_path):
        import importlib.util
        import json
        from pathlib import Path
        spec = importlib.util.spec_from_file_location(
            'perf_chunks', Path(__file__).resolve().parent.parent / 'scripts' / 'perf' / 'chunks.py')
        chunks = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(chunks)
        ev = [['scan', 0, 20, {}], ['chunk', 0, 10, {'n': 4}], ['ahead', 2, 8, {}],
              ['io', 3, 5, {'thread': 'w'}], ['infer:clip', 3, 7, {}], ['chunk', 10, 20, {'n': 4}]]
        (tmp_path / 'events.json').write_text(json.dumps(ev))
        (tmp_path / 'summary.json').write_text(json.dumps({'wall_s': 20, 'exit': 0}))
        (tmp_path / 'accum.json').write_text('{}')
        (tmp_path / 'samples.csv').write_text('t,sys_mem_pct,swap_used_gib,rss_gib,private_gib,gpu_util,phase\n')
        first = chunks.analyse(str(tmp_path))['per_chunk'][0]
        assert first['infer:clip'] == 4.0
        assert 'io@thread' not in first
