"""Batch I: the scan pipeline's background machinery stops trusting silence.

B196/B197 — the single-pass EXIF prefetch stays a bounded window ahead of the
GPU consumer and its stop event is per request, so a thread that outlives its
join can never be revived by a later start's clear(). B199 — _take_exif
without a prefetcher fetches synchronously instead of building a one-shot
ExifPrefetcher that could plan background exiftool work after the shutdown
close. B200 — the single-pass ResourceMonitor warns once when its tuning loop
dies, mirroring MultiPassResourceMonitor._tick.
"""

import threading
import time
from types import SimpleNamespace
from unittest import mock


from processing import multi_pass
from processing.batch_processor import BatchProcessor
from processing.resource_monitor import ResourceMonitor

GIB = 1024 ** 3


def _processor(**overrides):
    scorer = SimpleNamespace(get_metrics=lambda: {})
    processor = BatchProcessor(scorer, batch_save_size=50, config={})
    for key, value in overrides.items():
        setattr(processor, key, value)
    return processor


class TestExifPrefetchWindow:
    def test_prefetch_stays_a_bounded_window_ahead(self, monkeypatch, tmp_path):
        processor = _processor()
        processor._exif_prefetch_cap = 2  # a tiny window for the test
        calls: list[list[str]] = []
        monkeypatch.setattr('exiftool.get_exif_batch',
                            lambda paths, chunk_size=100, stop_event=None:
                            calls.append(list(paths)) or {p: {'iso': 100} for p in paths})
        paths = [str(tmp_path / f'{i}.jpg') for i in range(600)]  # 2 chunks of 500

        processor._start_exif_prefetch(paths)
        deadline = time.time() + 5
        while len(calls) < 1 and time.time() < deadline:
            time.sleep(0.02)
        assert len(calls) == 1
        # Chunk 1 filled the window (500 entries ≥ cap 2): the prefetcher must
        # WAIT for the consumer to drain instead of pulling chunk 2 as well.
        time.sleep(0.4)
        assert len(calls) == 1
        # The consumer pops most of the window — the next chunk goes out.
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

        def slow_batch(paths, chunk_size=100, stop_event=None):
            entered.set()
            release.wait(10)
            return {p: {'iso': 100} for p in paths}

        monkeypatch.setattr('exiftool.get_exif_batch', slow_batch)
        processor._start_exif_prefetch([str(tmp_path / 'a.jpg')])
        assert entered.wait(5)
        old_stop = processor._exif_stop
        old_thread = processor._exif_prefetch_thread

        # The join times out (the fake exiftool call is still blocked), but
        # the old request's own event is set.
        processor._stop_exif_prefetch()
        assert old_stop.is_set()
        assert not old_thread.is_alive() or old_thread.join(12) is None

        # A new start gets a FRESH event: clearing the shared event used to
        # revive the old thread mid-chunk with a stale worklist.
        processor._start_exif_prefetch([str(tmp_path / 'b.jpg')])
        assert processor._exif_stop is not old_stop
        assert not processor._exif_stop.is_set()
        release.set()
        old_thread.join(12)
        assert not old_thread.is_alive()
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
