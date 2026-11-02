"""Chunk N+1's EXIF is fetched on a background thread while chunk N is processed (#433 step 2).

The ordering tests use Events, never sleeps for synchronisation. The exiftool layer is tested
with ``subprocess.run`` patched, so no process is ever spawned.
"""
import subprocess
import threading
import time
from pathlib import Path
from unittest import mock

import pytest

pytest.importorskip("torch")

from exiftool import exiftool_batch  # noqa: E402
from processing import stage_timing  # noqa: E402
from processing.multi_pass import ChunkedMultiPassProcessor, ExifPrefetcher, _resolved  # noqa: E402

WAIT = 5.0


def _paths(n, start=0):
    return [str(Path("/photos") / f"img{i:03d}.jpg") for i in range(start, start + n)]


def _exif_for(paths):
    return {k: {"camera_model": "X"} for k in _resolved(paths)}


class _Recorder:
    """A fake ``fetch``: records every call and returns EXIF for the paths it was given."""

    def __init__(self, fail_first=False):
        self.calls = []
        self.started = {}
        self.fail_first = fail_first
        self._lock = threading.Lock()

    def __call__(self, paths, stop_event):
        with self._lock:
            self.calls.append(list(paths))
            n = len(self.calls)
            event = self.started.setdefault(paths[0], threading.Event())
        event.set()
        if self.fail_first and n == 1:
            raise RuntimeError("exiftool exploded")
        return _exif_for(paths)


def _submit(pf, paths):
    """Plan ``paths`` and start them, as the next ``take`` does."""
    pf.plan(paths)
    pf.take([])


def _scan_processor():
    with mock.patch("processing.multi_pass._ensure_imports"):
        proc = ChunkedMultiPassProcessor(
            scorer=mock.MagicMock(), model_manager=mock.MagicMock(_cache_hits=0, _cache_misses=0),
            config={"processing": {"ram_chunk_size": 4, "auto_tuning": {"enabled": False}}})
    proc.pass_groups = [["clip"]]
    return proc


def _run_scan(proc, paths, process_chunk):
    with mock.patch("processing.multi_pass._ensure_imports"), \
            mock.patch("processing.resource_monitor.MultiPassResourceMonitor"), \
            mock.patch.object(proc, "_process_chunk", side_effect=process_chunk):
        proc.process_directory(paths, show_progress=False)


class TestOverlap:
    def test_the_next_chunk_is_requested_before_the_current_chunk_finishes(self):
        proc = _scan_processor()
        fetch = _Recorder()
        proc._fetch_exif = fetch
        paths = _paths(8)
        seen = {}

        def process_chunk(chunk, idx, total):
            exif, _ = proc._exif_prefetcher.take(chunk)
            seen[idx] = (chunk, exif)
            if idx == 0:
                # chunk 1 must already be on its way while chunk 0 is still being processed
                seen["chunk1_started_in_chunk0"] = fetch.started.setdefault(
                    paths[4], threading.Event()).wait(WAIT)

        _run_scan(proc, paths, process_chunk)
        assert seen["chunk1_started_in_chunk0"] is True
        for idx in (0, 1):
            chunk, exif = seen[idx]
            assert set(exif) == set(_resolved(chunk))
        # chunk 0 is synchronous (nothing was prefetched for it); chunk 1 reused the prefetch
        assert fetch.calls.count(paths[:4]) == 1 and fetch.calls.count(paths[4:]) == 1
        assert len(fetch.calls) == 2

    def test_the_prefetcher_is_closed_and_removed_when_the_scan_unwinds(self):
        proc = _scan_processor()
        proc._fetch_exif = _Recorder()
        holder = {}

        def boom(chunk, idx, total):
            holder["prefetcher"] = proc._exif_prefetcher
            raise RuntimeError("scan died")

        with pytest.raises(RuntimeError, match="scan died"):
            _run_scan(proc, _paths(8), boom)
        assert holder["prefetcher"].stop_event.is_set()
        assert proc._exif_prefetcher is None

    def test_it_is_closed_before_the_decode_executor_is_shut_down(self):
        proc = _scan_processor()
        proc._fetch_exif = _Recorder()
        order = []
        real_close = ExifPrefetcher.close
        monkey_close = lambda self: (order.append("prefetcher"), real_close(self))[1]  # noqa: E731
        with mock.patch.object(ExifPrefetcher, "close", monkey_close), \
                mock.patch.object(proc, "_shutdown_decode_executor",
                                  side_effect=lambda: order.append("executor")):
            _run_scan(proc, _paths(8), lambda *a: None)
        assert order == ["prefetcher", "executor"]


class TestBoundary:
    def test_a_chunk_that_grew_gets_the_missing_paths_in_one_batch(self):
        fetch = _Recorder()
        pf = ExifPrefetcher(fetch)
        paths = _paths(8, start=10)
        _submit(pf, paths[:3])                      # requested while the chunk size was 3
        exif, _ = pf.take(paths[:5])              # ... but the chunk turned out to be 5
        assert set(exif) == set(_resolved(paths[:5]))
        assert sorted(map(len, fetch.calls)) == [2, 3]
        assert fetch.calls.count(paths[3:5]) == 1  # the two missing paths: ONE synchronous batch

    def test_a_chunk_that_shrank_keeps_only_its_own_entries(self):
        fetch = _Recorder()
        pf = ExifPrefetcher(fetch)
        paths = _paths(8)
        _submit(pf, paths)
        exif, _ = pf.take(paths[:3])
        assert set(exif) == set(_resolved(paths[:3]))   # none stale, none foreign
        assert len(fetch.calls) == 1                     # nothing missing, no extra batch

    def test_a_request_for_other_paths_is_ignored_and_the_chunk_is_read_synchronously(self):
        fetch = _Recorder()
        pf = ExifPrefetcher(fetch)
        _submit(pf, _paths(4, start=50))
        paths = _paths(4)
        exif, _ = pf.take(paths)
        assert set(exif) == set(_resolved(paths))
        assert paths in fetch.calls

    def test_the_older_request_is_dropped_once_a_newer_one_is_taken(self):
        fetch = _Recorder()
        pf = ExifPrefetcher(fetch)
        a, b = _paths(3), _paths(3, start=3)
        _submit(pf, a)
        older = pf._requests[0]
        _submit(pf, b)
        pf.take(b)
        assert pf._requests == []
        assert older["stop"].is_set()        # a dropped request stops at its next sub-batch
        pf.close()

    def test_the_next_request_starts_only_after_the_current_chunk_is_collected(self):
        fetch = _Recorder()
        pf = ExifPrefetcher(fetch)
        a, b = _paths(3), _paths(3, start=3)
        pf.plan(b)
        assert fetch.calls == []             # planning starts no exiftool process
        pf.take(a)
        assert fetch.calls[0] == a           # the current chunk first ...
        assert fetch.started.setdefault(b[0], threading.Event()).wait(WAIT)  # ... then the next
        pf.close()


class TestScanBoundary:
    def test_a_chunk_size_change_between_iterations_still_matches_every_photo(self):
        proc = _scan_processor()
        proc.auto_tuning_enabled = True
        fetch = _Recorder()
        proc._fetch_exif = fetch
        paths = _paths(12)
        got = {}

        def process_chunk(chunk, idx, total):
            exif, _ = proc._exif_prefetcher.take(chunk)
            got[idx] = (list(chunk), exif)
            if idx == 0:
                proc.chunk_size = 6       # auto-tuning grew the chunk after chunk 1 was planned

        proc.chunk_size = 4
        _run_scan(proc, paths, process_chunk)
        seen = [p for chunk, _ in got.values() for p in chunk]
        assert seen == paths
        for chunk, exif in got.values():
            assert set(exif) == set(_resolved(chunk))
            assert all(v == {"camera_model": "X"} for v in exif.values())


class TestFailure:
    def test_a_failed_prefetch_falls_back_to_the_synchronous_call(self):
        fetch = _Recorder(fail_first=True)
        pf = ExifPrefetcher(fetch)
        paths = _paths(4)
        _submit(pf, paths)
        exif, _ = pf.take(paths)
        assert set(exif) == set(_resolved(paths))
        assert len(fetch.calls) == 2

    def test_the_exception_never_escapes_the_thread(self, caplog, monkeypatch):
        escaped = []
        monkeypatch.setattr(threading, "excepthook", lambda args: escaped.append(args))
        fetch = _Recorder(fail_first=True)
        pf = ExifPrefetcher(fetch)
        with caplog.at_level("WARNING", logger="facet.multi_pass"):
            _submit(pf, _paths(2))
            request = pf._requests[0]
            request["done"].wait(WAIT)
            request["thread"].join(WAIT)
        assert isinstance(request["error"], RuntimeError)
        assert escaped == []
        assert any("EXIF prefetch failed" in r.getMessage() for r in caplog.records)


class TestStop:
    def test_close_returns_promptly_ends_the_thread_and_starts_nothing_more(self):
        entered = threading.Event()
        calls = []

        def blocking(paths, stop_event):
            calls.append(list(paths))
            entered.set()
            stop_event.wait(30)
            return {}

        pf = ExifPrefetcher(blocking)
        _submit(pf, _paths(3))
        assert entered.wait(WAIT)
        thread = pf._requests[0]["thread"]
        start = time.monotonic()
        pf.close()
        assert time.monotonic() - start < 2.0
        thread.join(WAIT)
        assert not thread.is_alive()
        _submit(pf, _paths(3, start=10))     # after close: no new thread, no new call
        assert len(calls) == 1

    def test_close_is_bounded_when_the_fetch_ignores_the_stop_event(self, monkeypatch):
        monkeypatch.setattr("processing.multi_pass.EXIF_CLOSE_JOIN_SECONDS", 0.3)
        release = threading.Event()
        entered = threading.Event()

        def deaf(paths, stop_event):
            entered.set()
            release.wait(30)
            return {}

        pf = ExifPrefetcher(deaf)
        _submit(pf, _paths(2))
        assert entered.wait(WAIT)
        start = time.monotonic()
        pf.close()
        assert time.monotonic() - start < 2.0
        release.set()

    def test_nothing_is_booked_after_close(self):
        booked = []
        release = threading.Event()
        entered = threading.Event()

        def slow(paths, stop_event):
            entered.set()
            release.wait(30)
            return {}

        pf = ExifPrefetcher(slow, on_exec=booked.append)
        _submit(pf, _paths(2))
        thread = pf._requests[0]["thread"]
        assert entered.wait(WAIT)
        pf.close()
        release.set()
        thread.join(WAIT)
        assert booked == []

    def test_ctrl_c_while_waiting_propagates_promptly_and_stops_the_request(self):
        entered = threading.Event()
        release = threading.Event()

        def slow(paths, stop_event):
            entered.set()
            release.wait(30)
            return {}

        pf = ExifPrefetcher(slow)
        paths = _paths(2)
        _submit(pf, paths)
        request = pf._requests[0]
        assert entered.wait(WAIT)
        real_wait = request["done"].wait
        calls = []

        def interrupted(timeout=None):
            calls.append(timeout)
            if len(calls) == 2:
                raise KeyboardInterrupt
            return real_wait(timeout)

        request["done"] = mock.Mock(wait=interrupted)
        start = time.monotonic()
        with pytest.raises(KeyboardInterrupt):
            pf.take(paths)
        assert time.monotonic() - start < 1.0
        assert all(t is not None and t <= 0.5 for t in calls)   # sliced, never an untimed wait
        assert request["stop"].is_set()
        release.set()
        pf.close()

    def test_the_thread_is_a_daemon(self):
        pf = ExifPrefetcher(_Recorder())
        _submit(pf, _paths(1))
        assert pf._requests[0]["thread"].daemon
        pf.close()


class TestExiftoolLayer:
    def _batch(self):
        return exiftool_batch.ExifToolBatch.__new__(exiftool_batch.ExifToolBatch)

    def test_a_stop_after_the_first_subprocess_spawns_no_retry_and_no_next_batch(self):
        stop = threading.Event()
        calls = []

        def killed_child(*args, **kwargs):
            calls.append(args)
            stop.set()                       # Ctrl-C: the child dies with a nonzero exit, no exception
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="")

        with mock.patch.object(exiftool_batch.subprocess, "run", side_effect=killed_child):
            result = self._batch().get_metadata_batch(
                [f"/p/{i}.jpg" for i in range(250)], chunk_size=100, stop_event=stop)
        assert result == {}
        assert len(calls) == 1

    def test_without_a_stop_the_failed_chunk_is_retried_and_the_next_one_runs(self):
        calls = []

        def failing(*args, **kwargs):
            calls.append(args)
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="")

        with mock.patch.object(exiftool_batch.subprocess, "run", side_effect=failing):
            self._batch().get_metadata_batch([f"/p/{i}.jpg" for i in range(150)], chunk_size=100)
        assert len(calls) == 4               # 2 sub-batches x 2 attempts

    def test_get_exiftool_builds_one_instance_under_a_race(self, monkeypatch):
        built = []
        gate = threading.Event()

        class Counting:
            def __init__(self):
                built.append(self)
                gate.wait(0.3)               # hold the first constructor open so the second thread arrives

        monkeypatch.setattr(exiftool_batch, "ExifToolBatch", Counting)
        monkeypatch.setattr(exiftool_batch, "_exiftool_instance", None)
        got = []
        threads = [threading.Thread(target=lambda: got.append(exiftool_batch.get_exiftool()))
                   for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(WAIT)
        assert len(built) == 1 and got[0] is got[1]


class TestTimers:
    def test_load_images_books_the_wait_and_the_exec_seconds(self, tmp_path):
        from PIL import Image
        img = tmp_path / "a.jpg"
        Image.new("RGB", (32, 24), (10, 20, 30)).save(img)
        proc = _scan_processor()
        proc.scorer.config.get_exposure_settings.return_value = {}
        proc.scorer.config.get_monochrome_settings.return_value = {}
        proc.scorer.get_exif_data.return_value = {}
        proc._fetch_exif = lambda paths, stop: _exif_for(paths)
        proc._load_images([str(img)])        # direct call: a synchronous chunk-0 style fetch
        assert proc.metrics["exif_wait_time"] > 0.0
        assert proc.metrics["exif_batch_time"] > 0.0

    def test_exif_batch_wall_is_the_process_total_not_the_decode_wall(self):
        metrics = {"total_time": 100.0, "io_decode_time": 40.0, "exif_batch_time": 8.0,
                   "exif_wait_time": 1.0}
        stage = stage_timing.build_stages(metrics, load_workers=4)["exif_batch"]
        assert stage["wall_s"] == 100.0
        assert stage["occupancy"] == pytest.approx(0.08)
