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
from utils import system_memory  # noqa: E402
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


def _pin_cgroup_near_its_limit(monkeypatch, tmp_path, limit_bytes, used_bytes):
    """Point the cgroup v2 path constants at real files under ``tmp_path``.

    Mirrors ``tests/test_system_memory.py``'s ``_fake_cgroup`` idiom -- the
    path constants are module-level precisely so a test can retarget them,
    the same way ``facet.LIBRARY_LOCK_MOUNTS_PATH`` is faked in
    ``tests/test_scan.py``. The v1 constants are pointed at files that do
    not exist, which is what a host with only the unified hierarchy looks
    like, so v2 is unambiguously what gets read.
    """
    limit_path = tmp_path / "memory.max"
    stat_path = tmp_path / "memory.stat"
    limit_path.write_text(f"{limit_bytes}\n")
    stat_path.write_text(f"anon {used_bytes}\n")
    monkeypatch.setattr(system_memory, "CGROUP_V2_LIMIT_PATH", str(limit_path))
    monkeypatch.setattr(system_memory, "CGROUP_V2_STAT_PATH", str(stat_path))
    monkeypatch.setattr(system_memory, "CGROUP_V2_USAGE_PATH", str(tmp_path / "memory.current"))
    monkeypatch.setattr(system_memory, "CGROUP_V1_LIMIT_PATH", str(tmp_path / "v1_limit"))
    monkeypatch.setattr(system_memory, "CGROUP_V1_USAGE_PATH", str(tmp_path / "v1_usage"))


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

    def test_chunk_size_never_grows_and_the_reduce_path_fires(self, tmp_path, monkeypatch):
        _pin_cgroup_near_its_limit(
            monkeypatch, tmp_path, limit_bytes=8 * GIB, used_bytes=int(7.6 * GIB)
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
