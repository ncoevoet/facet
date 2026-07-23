import threading
import time
from types import SimpleNamespace
from unittest import mock

import pytest

pytest.importorskip("torch")
pytest.importorskip("psutil")

from processing.resource_monitor import ResourceMonitor  # noqa: E402


class _FakeMemory:
    def __init__(self, percent):
        self.percent = percent


def _make_monitor():
    processor = SimpleNamespace(batch_size=16, get_metrics=lambda: {})
    return ResourceMonitor(processor, config={}, multi_pass_processor=None)


def test_graceful_reduction_returns_promptly_on_stop():
    monitor = _make_monitor()
    high_memory = _FakeMemory(99.0)
    with mock.patch(
        "processing.resource_monitor.psutil.virtual_memory",
        return_value=high_memory,
    ):
        threading.Timer(0.2, monitor.stop_event.set).start()
        started = time.time()
        monitor._graceful_memory_reduction(99.0)
        elapsed = time.time() - started
    assert elapsed < ResourceMonitor.MAX_MEMORY_WAIT_SECONDS
    assert monitor.stop_event.is_set()
