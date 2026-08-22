"""Tests for the batch- and face-processing resource monitors.

Issue #111: under a Docker ``mem_limit``, ``psutil.virtual_memory()`` reports the
HOST's memory, which Docker does not virtualise. An idle host therefore reads as
headroom even while the cgroup the process actually runs in sits near its limit,
and ``MultiPassResourceMonitor`` grows its RAM chunk size straight into the OOM
killer. ``TestMultiPassResourceMonitorHonoursTheCgroupLimit`` below is the
regression guard; the rest of this file covers ``processing.resource_monitor
.ResourceMonitor`` and ``faces.resource_monitor.FaceResourceMonitor``, which the
same ``utils.system_memory.effective_memory`` fix touches at three more sites.
"""

import threading
import time
from types import SimpleNamespace
from unittest import mock

import pytest

pytest.importorskip("torch")
pytest.importorskip("psutil")

from faces.resource_monitor import FaceResourceMonitor  # noqa: E402
from processing.resource_monitor import MultiPassResourceMonitor, ResourceMonitor  # noqa: E402
from utils.system_memory import EffectiveMemory  # noqa: E402

GIB = 1024 ** 3


def _make_monitor():
    processor = SimpleNamespace(batch_size=16, get_metrics=lambda: {})
    return ResourceMonitor(processor, config={})


def test_graceful_reduction_returns_promptly_on_stop():
    monitor = _make_monitor()
    high_memory = EffectiveMemory(
        total=32 * GIB, used=int(31.7 * GIB), available=int(0.3 * GIB), percent=99.0
    )
    with mock.patch(
        "processing.resource_monitor.effective_memory",
        return_value=high_memory,
    ):
        threading.Timer(0.2, monitor.stop_event.set).start()
        started = time.time()
        monitor._graceful_memory_reduction(99.0)
        elapsed = time.time() - started
    assert elapsed < ResourceMonitor.MAX_MEMORY_WAIT_SECONDS
    assert monitor.stop_event.is_set()


def test_graceful_reduction_stops_waiting_once_effective_memory_recovers():
    """Pins the recovery check to ``effective_memory()`` specifically.

    The stop-event test above cannot tell this call site from a stale
    ``psutil.virtual_memory()`` read -- the timer-driven stop dominates
    either way. Here nothing ever sets the stop event: a stale read would
    see this test's high, unrecovering ``psutil`` mock and wait out the
    full ``MAX_MEMORY_WAIT_SECONDS``, while reading ``effective_memory()``
    sees the recovered value and returns after the first one-second wait.
    """
    monitor = _make_monitor()
    recovered_memory = EffectiveMemory(
        total=16 * GIB, used=int(1.6 * GIB), available=int(14.4 * GIB), percent=10.0
    )
    unrecovered_host = SimpleNamespace(
        total=16 * GIB, used=int(15.8 * GIB), available=int(0.2 * GIB), percent=99.0
    )
    with mock.patch(
        "processing.resource_monitor.effective_memory", return_value=recovered_memory
    ), mock.patch(
        "processing.resource_monitor.psutil.virtual_memory", return_value=unrecovered_host
    ):
        started = time.time()
        monitor._graceful_memory_reduction(99.0)
        elapsed = time.time() - started
    assert elapsed < 2.0
    assert not monitor.stop_event.is_set()


def test_collect_metrics_reads_effective_memory():
    monitor = _make_monitor()
    reading = EffectiveMemory(total=16 * GIB, used=8 * GIB, available=8 * GIB, percent=42.0)
    with mock.patch("processing.resource_monitor.effective_memory", return_value=reading):
        monitor._collect_metrics()
    metrics = monitor.get_metrics()
    assert metrics["memory_percent"] == 42.0
    assert metrics["memory_available_gb"] == pytest.approx(8.0)


def _pin_cgroup_near_its_limit(fake_cgroup, limit_bytes, used_bytes):
    """Fake a cgroup v2 hierarchy reporting ``used_bytes`` of ``limit_bytes``.

    The ``fake_cgroup`` fixture (tests/conftest.py) points every path constant
    at ``tmp_path``, v1 included, so nothing falls through to the runner's own
    /sys/fs/cgroup -- which is what three separate copies of this idiom used
    to do for the v1 stat file.
    """
    fake_cgroup(v2_limit=f"{limit_bytes}\n", v2_stat=f"anon {used_bytes}\n")


class _FakeChunkProcessor:
    """Duck-types the chunk-size knob ``MultiPassResourceMonitor`` drives.

    Mirrors ``ChunkedMultiPassProcessor.reduce_chunk_size`` /
    ``increase_chunk_size`` (``processing/multi_pass.py``) exactly -- the
    same 25% step, the same clamping -- without dragging in that class's
    model-loading imports, which this monitor never touches.
    """

    def __init__(self, chunk_size, min_chunk_size, max_chunk_size):
        self.chunk_size = chunk_size
        self.min_chunk_size = min_chunk_size
        self.max_chunk_size = max_chunk_size
        self.auto_tuning_enabled = True
        self.model_manager = None

    def reduce_chunk_size(self):
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


class TestMultiPassResourceMonitorHonoursTheCgroupLimit:
    """Issue #111 regression: an idle host must not be read as headroom.

    Drives the real monitor thread -- not a reimplementation of its loop --
    against an idle 23 GiB host pinned inside an 8 GiB cgroup sitting at
    ~95%. Unpatched, the monitor reads the host's 26% as headroom and grows
    the chunk size (measured: 32->40->50->62->77->96->120->128 in ~105s at
    the shipped 5s interval); it must instead shrink towards the floor.
    """

    def test_chunk_size_never_grows_and_the_reduce_path_fires(self, fake_cgroup, monkeypatch):
        _pin_cgroup_near_its_limit(
            fake_cgroup, limit_bytes=8 * GIB, used_bytes=int(7.6 * GIB)
        )
        idle_host = SimpleNamespace(total=23 * GIB, used=6 * GIB, available=17 * GIB, percent=26.0)
        monkeypatch.setattr(
            "processing.resource_monitor.psutil.virtual_memory",
            lambda: idle_host,
        )
        processor = _FakeChunkProcessor(chunk_size=32, min_chunk_size=10, max_chunk_size=128)
        config = {
            "processing": {
                "auto_tuning": {
                    "monitor_interval_seconds": 0.1,
                    "memory_limit_percent": 85,
                },
            },
        }
        monitor = MultiPassResourceMonitor(processor, config)

        monitor.start()
        time.sleep(0.75)
        monitor.stop()
        monitor.join(timeout=2.0)

        assert processor.chunk_size <= 32, (
            f"chunk size grew to {processor.chunk_size} while the cgroup sat "
            f"at ~95% of its limit -- adjustments: {monitor.adjustments}"
        )
        assert any(direction == "reduce" for direction, _, _ in monitor.adjustments)
        assert not any(direction == "increase" for direction, _, _ in monitor.adjustments)


def test_face_resource_monitor_reduces_batch_size_from_effective_memory():
    processor = SimpleNamespace(batch_size=32, config_lock=threading.Lock())
    config = {
        "auto_tuning": {
            "memory_limit_percent": 80,
            "monitor_interval_seconds": 0.05,
            "min_batch_size": 8,
        },
    }
    monitor = FaceResourceMonitor(processor, config)
    near_full_cgroup = EffectiveMemory(
        total=8 * GIB, used=int(7.6 * GIB), available=int(0.4 * GIB), percent=95.0
    )

    with mock.patch(
        "faces.resource_monitor.effective_memory", return_value=near_full_cgroup
    ):
        monitor.start()
        time.sleep(0.2)
        monitor.stop()
        monitor.join(timeout=2.0)

    assert processor.batch_size < 32


class _PhasedMemory:
    """An ``effective_memory`` whose reading the test moves between phases.

    Counting scripted readings would race the monitor's own sampling; a level
    the test sets and the thread reads does not.
    """

    def __init__(self, percent):
        self.percent = percent

    def __call__(self):
        total = 8 * GIB
        used = int(total * self.percent / 100)
        return EffectiveMemory(total=total, used=used, available=total - used,
                               percent=self.percent)


def _cycling_memory(percents):
    """An ``effective_memory`` that walks ``percents``, holding on the last one.

    A chunk is not one memory reading. It loads its images, then runs each
    pass in turn, and every unload between passes drops usage back towards
    the floor -- so any single sample is as likely to catch the trough as
    the peak.
    """
    remaining = list(percents)

    def read():
        percent = remaining.pop(0) if len(remaining) > 1 else remaining[0]
        total = 8 * GIB
        used = int(total * percent / 100)
        return EffectiveMemory(total=total, used=used, available=total - used,
                               percent=percent)

    return read


class TestGrowthFollowsTheChunkPeakNotTheTroughBetweenPasses:
    """Issue #111, second half: the trough between passes is not headroom.

    Reading the cgroup instead of the host fixed the denominator, not the
    policy. Replaying the anonymous-memory trace measured inside the 8 GiB
    container through this monitor's own decision body, chunk size ran
    10 -> 12 -> 15 -> ... -> 500 during the FIRST chunk and was clamped back
    to 375: every unload between passes dropped the reading to 11-56%, three
    of those in a row cleared the 65% bar, and the chunk that had just peaked
    at 93% counted for nothing. The next chunk then tried to decode every
    remaining photo at once and was OOM-killed before it loaded a model.

    The peak is what the chunk has to survive, so the peak is what decides
    whether the next one may be larger.
    """

    def _monitor(self, percents, chunk_size=10):
        processor = _FakeChunkProcessor(
            chunk_size=chunk_size, min_chunk_size=10, max_chunk_size=500)
        config = {"processing": {"auto_tuning": {
            "monitor_interval_seconds": 0.1, "memory_limit_percent": 85}}}
        monitor = MultiPassResourceMonitor(processor, config)
        return processor, monitor, _cycling_memory(percents)

    def _drive(self, monitor, reader, seconds=0.8):
        with mock.patch("processing.resource_monitor.effective_memory", reader):
            monitor.start()
            time.sleep(seconds)
            monitor.stop()
            monitor.join(timeout=2.0)

    def test_a_trough_between_passes_does_not_grow_the_chunk(self):
        cycle = [80, 80, 15, 15, 15, 40, 40, 40] * 20
        processor, monitor, reader = self._monitor(cycle)

        self._drive(monitor, reader)
        monitor.note_chunk_complete()

        assert processor.chunk_size == 10, (
            f"chunk grew to {processor.chunk_size} although the chunk peaked at "
            f"80% of the limit -- adjustments: {monitor.adjustments}"
        )
        assert not any(d == "increase" for d, _, _ in monitor.adjustments)

    def test_a_chunk_that_stayed_low_throughout_still_grows(self):
        processor, monitor, reader = self._monitor([20, 25, 30, 22] * 20)

        self._drive(monitor, reader)
        monitor.note_chunk_complete()

        assert processor.chunk_size == 12, (
            "a chunk whose peak stayed well under the threshold must still "
            f"grow -- adjustments: {monitor.adjustments}"
        )

    def test_growth_is_decided_once_per_chunk_not_once_per_sample(self):
        processor, monitor, reader = self._monitor([20] * 200)

        self._drive(monitor, reader, seconds=0.8)

        assert processor.chunk_size == 10, (
            "the monitor grew the chunk mid-chunk, so the size the chunk was "
            "sized for changed while it was being processed"
        )

    def test_the_high_water_mark_resets_with_each_chunk(self):
        processor, monitor, _ = self._monitor([0])
        reading = _PhasedMemory(80.0)

        with mock.patch("processing.resource_monitor.effective_memory", reading):
            monitor.start()
            time.sleep(0.5)
            reading.percent = 20.0
            time.sleep(0.2)
            monitor.note_chunk_complete()
            after_heavy_chunk = processor.chunk_size
            time.sleep(0.5)
            monitor.stop()
            monitor.join(timeout=2.0)
        monitor.note_chunk_complete()

        assert after_heavy_chunk == 10
        assert processor.chunk_size == 12, (
            "a high peak in an earlier chunk kept blocking growth, so the "
            "monitor can never recover from one heavy chunk"
        )
