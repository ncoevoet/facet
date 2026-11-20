"""Pipeline robustness: the single-pass EXIF prefetch is a bounded window with
per-request stops, a prefetcher-less _take_exif fetches synchronously without
building background-work objects after shutdown, and the single-pass resource
monitor warns once when its tuning loop dies."""

import threading
import time
from types import SimpleNamespace
from unittest import mock

from processing import multi_pass
from processing.batch_processor import BatchProcessor
from processing.resource_monitor import ResourceMonitor


def _processor():
    scorer = SimpleNamespace(get_metrics=lambda: {})
    processor = BatchProcessor(scorer, batch_save_size=50, config={})
    processor._exif_prefetch_cap = 2  # a tiny window for the tests
    return processor


class TestExifPrefetchWindow:
    def test_prefetch_stays_a_bounded_window_ahead(self, monkeypatch, tmp_path):
        processor = _processor()
        calls: list[list[str]] = []
        monkeypatch.setattr('exiftool.get_exif_batch',
                            lambda paths, chunk_size=100, stop_event=None:
                            calls.append(list(paths)) or {p: {'iso': 100} for p in paths})
        paths = [str(tmp_path / f'{i}.jpg') for i in range(600)]  # 500 + 100

        processor._start_exif_prefetch(paths)
        deadline = time.time() + 5
        while len(calls) < 1 and time.time() < deadline:
            time.sleep(0.02)
        assert len(calls) == 1
        # Chunk 1 filled the window (500 entries >= cap 2): the prefetcher must
        # WAIT for the consumer to drain instead of pulling chunk 2 as well.
        time.sleep(0.4)
        assert len(calls) == 1
        # The consumer pops all but one entry — the next chunk goes out.
        with processor._exif_lock:
            for key in list(processor._exif_cache)[:-1]:
                processor._exif_cache.pop(key)
        deadline = time.time() + 5
        while len(calls) < 2 and time.time() < deadline:
            time.sleep(0.02)
        assert len(calls) == 2
        thread = processor._exif_prefetch_thread
        processor._stop_exif_prefetch()
        assert not thread.is_alive()

    def test_stop_uses_a_per_request_event(self, monkeypatch, tmp_path):
        processor = _processor()
        entered = threading.Event()
        release = threading.Event()
        calls: list[list[str]] = []

        def slow_batch(paths, chunk_size=100, stop_event=None):
            entered.set()
            release.wait(10)
            calls.append(list(paths))
            return {p: {'iso': 100} for p in paths}

        monkeypatch.setattr('exiftool.get_exif_batch', slow_batch)
        # A multi-chunk worklist: the old thread has a NEXT chunk it could
        # still fetch after the join times out — the revival this pins.
        processor._start_exif_prefetch([str(tmp_path / f'{i}.jpg') for i in range(600)])
        assert entered.wait(5)
        old_stop = processor._exif_stop
        old_thread = processor._exif_prefetch_thread

        # The join times out (the fake exiftool call is still blocked), but
        # the old request's own event is set.
        processor._stop_exif_prefetch()
        assert old_stop.is_set()
        # A new start must NOT clear the old request's event (the old thread
        # may still be inside its exiftool call) and must get a fresh one.
        processor._start_exif_prefetch([str(tmp_path / 'b.jpg')])
        assert processor._exif_stop is not old_stop
        assert not processor._exif_stop.is_set()
        # Releasing lets the old thread finish chunk 1, see ITS OWN stop and
        # exit without ever fetching its stale chunk 2 (paths 500+); the new
        # thread's worklist is the only other fetch.
        release.set()
        old_thread.join(12)
        assert not old_thread.is_alive()
        deadline = time.time() + 5
        while len(calls) < 2 and time.time() < deadline:
            time.sleep(0.02)
        assert len(calls) == 2
        assert all('500.jpg' not in path for call in calls for path in call)
        processor._stop_exif_prefetch()


class TestTakeExifWithoutPrefetcher:
    def test_fetches_directly_without_building_a_prefetcher(self, monkeypatch):
        # Building a one-shot ExifPrefetcher during the shutdown unwind could
        # plan or start background exiftool work after the close — the fetch
        # must be direct, with no object and no background work.
        monkeypatch.setattr(multi_pass, 'ExifPrefetcher',
                            mock.Mock(side_effect=AssertionError('no prefetcher object')))
        monkeypatch.setattr(multi_pass, 'cached_resolve', lambda p: p)
        booked = []
        proc = SimpleNamespace(
            _exif_prefetcher=None, _decode_stop=None,
            _fetch_exif=lambda paths, stop_event: {'/p/a.jpg': {'iso': 100}},
            _book_exif_batch=lambda seconds: booked.append(seconds),
            metrics={'exif_wait_time': 0.0},
        )

        result = multi_pass.ChunkedMultiPassProcessor._take_exif(proc, ['/p/a.jpg'])

        assert result == {'/p/a.jpg': {'iso': 100}}
        assert len(booked) == 1
        assert proc.metrics['exif_wait_time'] >= 0

    def test_the_shutdown_unwind_honours_the_decode_stop(self, monkeypatch):
        monkeypatch.setattr(multi_pass, 'ExifPrefetcher',
                            mock.Mock(side_effect=AssertionError('no prefetcher object')))
        monkeypatch.setattr(multi_pass, 'cached_resolve', lambda p: p)
        stop = threading.Event()
        stop.set()
        seen_stops = []
        proc = SimpleNamespace(
            _exif_prefetcher=None, _decode_stop=stop,
            _fetch_exif=lambda paths, stop_event: seen_stops.append(stop_event) or {},
            _book_exif_batch=lambda seconds: None,
            metrics={'exif_wait_time': 0.0},
        )

        multi_pass.ChunkedMultiPassProcessor._take_exif(proc, ['/p/a.jpg'])

        assert seen_stops == [stop]


class TestSinglePassMonitorWarnOnce:
    def test_a_dead_tuning_loop_warns_once_and_keeps_the_loop_alive(self):
        processor = SimpleNamespace(batch_size=16, get_metrics=lambda: {})
        monitor = ResourceMonitor(processor, config={})
        monitor.monitor_interval = 0.1
        with mock.patch.object(monitor, '_collect_metrics',
                               side_effect=RuntimeError('psutil dead')), \
             mock.patch('processing.resource_monitor.logger.warning') as warn:
            threading.Timer(0.5, monitor.stop_event.set).start()
            monitor._monitor_loop()
        assert warn.call_count == 1
        assert 'adaptive chunk tuning' in warn.call_args[0][0]
