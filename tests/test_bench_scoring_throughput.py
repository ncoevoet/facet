"""Memory sampling of the scoring benchmark (scripts/bench/scoring_throughput.py).

The harness runs ``facet.py`` as a subprocess, so the torch allocator counters
it used to read (``torch.cuda.max_memory_allocated``, ``torch.mps.*``) were
process-local and always reported 0.0 for the child. GPU memory now comes from
``nvidia-smi``'s per-pid accounting; these tests drive that parsing and pid
selection with stubbed ``nvidia-smi`` output and a stubbed process tree, and
pin the property that matters: a metric that could not be sampled is None, not
zero.

No CUDA GPU and no Apple Metal device exist in this environment, so the real
driver query is exercised only through stubs.
"""

import subprocess
import sys
from types import SimpleNamespace

import pytest

from scripts.bench.scoring_throughput import (
    _BYTES_PER_MB,
    _GPU_MEMORY_METHOD_NVIDIA_SMI,
    _GPU_MEMORY_METHOD_UNAVAILABLE,
    _RSS_METHOD_PSUTIL,
    _RSS_METHOD_UNAVAILABLE,
    GpuMemorySampler,
    ResourceTracker,
    _format_mb,
    parse_compute_apps,
    read_nvidia_smi_compute_apps,
)
from scripts.bench import scoring_throughput

CHILD_PID = 4242
WORKER_PID = 4243
FOREIGN_PID = 9999


class _FakeProcess:
    """psutil.Process stand-in with a fixed RSS and a fixed descendant list."""

    def __init__(self, pid, rss_mb=None, children=()):
        self.pid = pid
        self._rss_mb = rss_mb
        self._children = list(children)

    def memory_info(self):
        if self._rss_mb is None:
            raise RuntimeError("process vanished")
        return SimpleNamespace(rss=int(self._rss_mb * _BYTES_PER_MB))

    def children(self, recursive=False):
        return list(self._children)


class _FakePsutil:
    def __init__(self, root=None):
        self._root = root

    def Process(self, pid):
        if self._root is None or self._root.pid != pid:
            raise RuntimeError(f"no such process: {pid}")
        return self._root


class _ScriptedSampler:
    """GpuMemorySampler stand-in replaying one reading per sample_once()."""

    def __init__(self, readings):
        self._readings = list(readings)
        self.seen_pids = []

    def sample_mb(self, pids):
        self.seen_pids.append(set(pids))
        return self._readings.pop(0) if self._readings else None


def _tracker(monkeypatch, root_process=None, gpu_readings=()):
    monkeypatch.setattr(
        scoring_throughput, "_try_import_psutil", lambda: _FakePsutil(root_process)
    )
    sampler = _ScriptedSampler(gpu_readings)
    return ResourceTracker(CHILD_PID, gpu_sampler=sampler), sampler


def test_parse_compute_apps_reads_pid_and_megabytes():
    assert parse_compute_apps(f"{CHILD_PID}, 1536\n{FOREIGN_PID}, 64\n") == {
        CHILD_PID: 1536.0,
        FOREIGN_PID: 64.0,
    }


def test_parse_compute_apps_sums_one_pid_across_gpus():
    assert parse_compute_apps("4242, 1000\n4242, 512\n") == {4242: 1512.0}


def test_parse_compute_apps_drops_unquantified_and_malformed_rows():
    csv_output = (
        "4242, [N/A]\n"
        "4243, [Not Supported]\n"
        "\n"
        "no-comma-row\n"
        "not-a-pid, 128\n"
        "4244, 256\n"
    )
    assert parse_compute_apps(csv_output) == {4244: 256.0}


def test_parse_compute_apps_empty_output_is_no_rows():
    assert parse_compute_apps("") == {}


def test_sampler_sums_child_and_worker_rows():
    sampler = GpuMemorySampler(query=lambda: f"{CHILD_PID}, 800\n{WORKER_PID}, 200\n")
    assert sampler.sample_mb({CHILD_PID, WORKER_PID}) == 1000.0


def test_sampler_ignores_rows_of_untracked_pids():
    sampler = GpuMemorySampler(
        query=lambda: f"{CHILD_PID}, 800\n{FOREIGN_PID}, 7000\n"
    )
    assert sampler.sample_mb({CHILD_PID}) == 800.0


@pytest.mark.parametrize(
    "query_output",
    [None, "", f"{FOREIGN_PID}, 7000\n", "Not Supported\n"],
    ids=["nvidia_smi_unavailable", "empty_output", "no_row_for_pid", "unparseable"],
)
def test_sampler_reports_unavailable_never_zero(query_output):
    sampler = GpuMemorySampler(query=lambda: query_output)
    assert sampler.sample_mb({CHILD_PID}) is None


def test_read_nvidia_smi_returns_none_when_binary_absent(monkeypatch):
    monkeypatch.setattr(scoring_throughput.shutil, "which", lambda _name: None)

    def _fail(*_args, **_kwargs):
        raise AssertionError("subprocess must not run when nvidia-smi is absent")

    monkeypatch.setattr(scoring_throughput.subprocess, "run", _fail)
    assert read_nvidia_smi_compute_apps() is None


@pytest.mark.parametrize(
    "outcome",
    [
        FileNotFoundError("nvidia-smi"),
        scoring_throughput.subprocess.TimeoutExpired("nvidia-smi", 5.0),
        SimpleNamespace(returncode=1, stdout="", stderr="driver error"),
    ],
    ids=["binary_disappeared", "timeout", "non_zero_exit"],
)
def test_read_nvidia_smi_returns_none_on_failure(monkeypatch, outcome):
    monkeypatch.setattr(scoring_throughput.shutil, "which", lambda _name: "/usr/bin/nvidia-smi")

    def _run(*_args, **_kwargs):
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(scoring_throughput.subprocess, "run", _run)
    assert read_nvidia_smi_compute_apps() is None


def test_read_nvidia_smi_returns_stdout_on_success(monkeypatch):
    monkeypatch.setattr(scoring_throughput.shutil, "which", lambda _name: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(
        scoring_throughput.subprocess,
        "run",
        lambda *_a, **_k: SimpleNamespace(returncode=0, stdout="4242, 1536\n", stderr=""),
    )
    assert read_nvidia_smi_compute_apps() == "4242, 1536\n"


def test_tracker_keeps_gpu_high_water_mark(monkeypatch):
    tracker, _ = _tracker(monkeypatch, gpu_readings=[None, 500.0, 1200.0, 300.0])
    for _ in range(4):
        tracker.sample_once()
    assert tracker.peak_gpu_memory_mb == 1200.0
    assert tracker.gpu_memory_method == _GPU_MEMORY_METHOD_NVIDIA_SMI


def test_tracker_reports_gpu_unavailable_rather_than_zero(monkeypatch):
    tracker, _ = _tracker(monkeypatch, gpu_readings=[None, None, None])
    for _ in range(3):
        tracker.sample_once()
    assert tracker.peak_gpu_memory_mb is None
    assert tracker.gpu_memory_method == _GPU_MEMORY_METHOD_UNAVAILABLE


def test_tracker_samples_gpu_for_the_whole_child_tree(monkeypatch):
    worker = _FakeProcess(WORKER_PID, rss_mb=100.0)
    root = _FakeProcess(CHILD_PID, rss_mb=200.0, children=[worker])
    tracker, sampler = _tracker(monkeypatch, root_process=root, gpu_readings=[10.0])
    tracker.sample_once()
    assert sampler.seen_pids == [{CHILD_PID, WORKER_PID}]


def test_tracker_samples_child_pid_without_psutil(monkeypatch):
    monkeypatch.setattr(scoring_throughput, "_try_import_psutil", lambda: None)
    sampler = _ScriptedSampler([64.0])
    tracker = ResourceTracker(CHILD_PID, gpu_sampler=sampler)
    tracker.sample_once()
    assert sampler.seen_pids == [{CHILD_PID}]
    assert tracker.peak_gpu_memory_mb == 64.0
    assert tracker.peak_rss_mb is None
    assert tracker.rss_method == _RSS_METHOD_UNAVAILABLE


def test_tracker_sums_rss_over_the_child_tree(monkeypatch):
    worker = _FakeProcess(WORKER_PID, rss_mb=100.0)
    root = _FakeProcess(CHILD_PID, rss_mb=200.0, children=[worker])
    tracker, _ = _tracker(monkeypatch, root_process=root)
    tracker.sample_once()
    assert tracker.peak_rss_mb == pytest.approx(300.0)
    assert tracker.rss_method == _RSS_METHOD_PSUTIL


def test_tracker_keeps_rss_peak_when_the_child_exits(monkeypatch):
    root = _FakeProcess(CHILD_PID, rss_mb=250.0)
    tracker, _ = _tracker(monkeypatch, root_process=root)
    tracker.sample_once()
    root._rss_mb = None
    tracker.sample_once()
    assert tracker.peak_rss_mb == pytest.approx(250.0)
    assert tracker.samples[-1]["rss_mb"] is None


def test_tracker_records_unavailable_samples_as_none(monkeypatch):
    tracker, _ = _tracker(monkeypatch, gpu_readings=[None])
    tracker.sample_once()
    assert tracker.samples[-1]["gpu_memory_mb"] is None
    assert tracker.samples[-1]["rss_mb"] is None


def test_tracker_measures_a_real_child_process():
    """End-to-end over a real subprocess: RSS is the child's, not the harness's."""
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        tracker = ResourceTracker(child.pid, interval_s=0.01)
        tracker.sample_once()
        tracker.sample_once()
    finally:
        child.terminate()
        child.wait(timeout=10)
    assert tracker.peak_rss_mb > 0.0
    assert tracker.rss_method == _RSS_METHOD_PSUTIL
    gpu_unavailable = tracker.peak_gpu_memory_mb is None
    assert gpu_unavailable == (tracker.gpu_memory_method == _GPU_MEMORY_METHOD_UNAVAILABLE)


def test_format_mb_distinguishes_unavailable_from_zero():
    assert _format_mb(None) == "unavailable"
    assert _format_mb(0.0) == "0.0MB"
    assert _format_mb(1536.5) == "1536.5MB"
