"""``facet.py`` throughput benchmark.

Runs ``facet.py`` on a fixed photo directory and reports photos/sec, peak
process-tree RSS, peak per-process GPU memory, and per-pass wallclock. Output
mirrors ``bench.py`` so before/after diffs are mechanical.

Every memory figure describes the scoring *subprocess tree*, never this
harness. ``torch.cuda.max_memory_allocated`` and the ``torch.mps`` counters
only ever see the process that calls them, so they cannot observe a child;
GPU memory is therefore read from ``nvidia-smi``'s per-pid accounting. Apple
Metal has no equivalent per-process counter, and unified memory is system RAM,
so on that platform ``peak_rss_mb`` is the only defensible proxy and
``peak_gpu_memory_mb`` is reported as ``null``. A figure that could not be
sampled is always ``null``, never zero.

Example::

    venv/bin/python scripts/bench/scoring_throughput.py \\
        --photos /path/to/sample-1000 --pass embeddings --device mps --force

Note: this *does* modify the scoring database (the whole point is to measure
real scoring). Always run against a throwaway DB (``--db /tmp/bench.db``) or a
copy of your prod DB.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.bench import _common as bench

_BYTES_PER_MB = 1024 * 1024
_MB_SUFFIX = "MB"
_UNAVAILABLE = "unavailable"
_MB_DECIMALS = 1
_NVIDIA_SMI = "nvidia-smi"
_NVIDIA_SMI_ARGS = (
    "--query-compute-apps=pid,used_gpu_memory",
    "--format=csv,noheader,nounits",
)
_NVIDIA_SMI_TIMEOUT_S = 5.0
_CSV_SEPARATOR = ","
_GPU_MEMORY_METHOD_NVIDIA_SMI = (
    "nvidia-smi --query-compute-apps=pid,used_gpu_memory, summed over the "
    "scoring subprocess tree (MiB, high-water mark across samples)"
)
_GPU_MEMORY_METHOD_UNAVAILABLE = (
    "unavailable: nvidia-smi never attributed GPU memory to the scoring "
    "subprocess tree (binary absent, query unsupported, pid namespace "
    "mismatch, or no CUDA device used). Apple Metal exposes no per-process "
    "GPU memory counter at all -- on unified memory read peak_rss_mb, which "
    "is RSS and not a GPU measurement"
)
_RSS_METHOD_PSUTIL = (
    "psutil RSS summed over the scoring subprocess tree (MiB, high-water mark "
    "across samples; pages shared between those processes are counted once "
    "per process)"
)
_RSS_METHOD_UNAVAILABLE = (
    "unavailable: psutil could not sample the scoring subprocess tree"
)


def _try_import_psutil():
    try:
        import psutil  # type: ignore

        return psutil
    except Exception:
        return None


def read_nvidia_smi_compute_apps() -> str | None:
    """Raw per-process GPU memory CSV from ``nvidia-smi``, or None if it cannot run.

    None means "not measured" — the binary is absent, the query is unsupported
    on this driver, or the call failed — and is deliberately distinct from an
    output that reports no memory.
    """
    if shutil.which(_NVIDIA_SMI) is None:
        return None
    try:
        completed = subprocess.run(
            [_NVIDIA_SMI, *_NVIDIA_SMI_ARGS],
            capture_output=True,
            text=True,
            timeout=_NVIDIA_SMI_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


def parse_compute_apps(csv_output: str) -> dict[int, float]:
    """Map pid to GPU memory in MiB from ``nvidia-smi``'s compute-apps CSV.

    A pid holding memory on several GPUs gets one row per GPU, so rows for the
    same pid are summed. Rows nvidia-smi could not quantify (``[N/A]``,
    ``[Not Supported]``) carry no number and are dropped.
    """
    usage: dict[int, float] = {}
    for line in csv_output.splitlines():
        fields = [field.strip() for field in line.split(_CSV_SEPARATOR)]
        if len(fields) < 2:
            continue
        try:
            pid = int(fields[0])
            used_mb = float(fields[1])
        except ValueError:
            continue
        usage[pid] = usage.get(pid, 0.0) + used_mb
    return usage


class GpuMemorySampler:
    """Reads another process tree's GPU memory from the driver, not from torch.

    ``torch.cuda.max_memory_allocated`` and the ``torch.mps`` counters are
    process-local, so a harness watching a scoring subprocess cannot use them.
    ``nvidia-smi`` attributes memory per pid, which crosses the process
    boundary. A sample counts as measured only when at least one tracked pid
    appears in that output: a run whose pids are invisible (no NVIDIA driver,
    container pid namespace mismatch, Apple Metal) yields None rather than a
    plausible-looking zero.
    """

    def __init__(
        self,
        query: Callable[[], str | None] = read_nvidia_smi_compute_apps,
    ):
        self._query = query

    def sample_mb(self, pids: Iterable[int]) -> float | None:
        output = self._query()
        if not output:
            return None
        tracked_pids = set(pids)
        usage = parse_compute_apps(output)
        tracked = [mb for pid, mb in usage.items() if pid in tracked_pids]
        if not tracked:
            return None
        return sum(tracked)


def _running_peak(peak: float | None, value: float | None) -> float | None:
    if value is None:
        return peak
    return value if peak is None else max(peak, value)


def _rounded_mb(value: float | None) -> float | None:
    return None if value is None else round(value, _MB_DECIMALS)


def _format_mb(value: float | None) -> str:
    return _UNAVAILABLE if value is None else f"{value}{_MB_SUFFIX}"


class ResourceTracker:
    """Polls the scoring subprocess tree's RSS + GPU memory until ``stop()``.

    Both figures describe the child process tree, never this harness. A metric
    that could not be sampled stays None all the way into the JSON, so an
    unmeasurable run is never reported as zero usage.
    """

    def __init__(
        self,
        pid: int,
        interval_s: float = 0.5,
        gpu_sampler: GpuMemorySampler | None = None,
    ):
        self._psutil = _try_import_psutil()
        self._pid = pid
        self._interval = interval_s
        self._gpu_sampler = gpu_sampler or GpuMemorySampler()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.peak_rss_mb: float | None = None
        self.peak_gpu_memory_mb: float | None = None
        self.samples: list[dict[str, float | None]] = []

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    @property
    def gpu_memory_method(self) -> str:
        if self.peak_gpu_memory_mb is None:
            return _GPU_MEMORY_METHOD_UNAVAILABLE
        return _GPU_MEMORY_METHOD_NVIDIA_SMI

    @property
    def rss_method(self) -> str:
        if self.peak_rss_mb is None:
            return _RSS_METHOD_UNAVAILABLE
        return _RSS_METHOD_PSUTIL

    def _process_tree(self) -> list[Any]:
        """The scoring child plus its descendants, which fork after startup."""
        if self._psutil is None:
            return []
        try:
            child = self._psutil.Process(self._pid)
            return [child, *child.children(recursive=True)]
        except Exception:
            return []

    def _tree_rss_mb(self, tree: list[Any]) -> float | None:
        total: float | None = None
        for proc in tree:
            try:
                rss_mb = proc.memory_info().rss / _BYTES_PER_MB
            except Exception:
                continue
            total = rss_mb if total is None else total + rss_mb
        return total

    def sample_once(self) -> None:
        tree = self._process_tree()
        rss_mb = self._tree_rss_mb(tree)
        gpu_mb = self._gpu_sampler.sample_mb({self._pid, *(proc.pid for proc in tree)})
        self.peak_rss_mb = _running_peak(self.peak_rss_mb, rss_mb)
        self.peak_gpu_memory_mb = _running_peak(self.peak_gpu_memory_mb, gpu_mb)
        self.samples.append(
            {
                "t": time.time(),
                "rss_mb": _rounded_mb(rss_mb),
                "gpu_memory_mb": _rounded_mb(gpu_mb),
            }
        )

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.sample_once()
            if self._stop.wait(self._interval):
                return


def count_photos(directory: Path) -> int:
    exts = {
        ".jpg",
        ".jpeg",
        ".heif",
        ".heic",
        ".cr2",
        ".cr3",
        ".nef",
        ".arw",
        ".raf",
        ".rw2",
        ".dng",
        ".orf",
        ".srw",
        ".pef",
    }
    n = 0
    for root, _dirs, files in os.walk(directory):
        for f in files:
            if Path(f).suffix.lower() in exts:
                n += 1
    return n


def run_facet(args: argparse.Namespace) -> dict[str, Any]:
    cmd = [
        sys.executable,
        str(bench.REPO_ROOT / "facet.py"),
        str(args.photos),
    ]
    if args.pass_:
        cmd.extend(["--pass", args.pass_])
    if args.force:
        cmd.append("--force")
    if args.db:
        cmd.extend(["--db", str(args.db)])
    if args.single_pass:
        cmd.append("--single-pass")

    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    env["FACET_DEVICE"] = args.device

    started = time.perf_counter()
    proc = subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=str(bench.REPO_ROOT),
    )
    tracker = ResourceTracker(proc.pid)
    tracker.start()
    output_lines: list[str] = []
    try:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").rstrip()
            output_lines.append(line)
            print(line)
    finally:
        proc.wait()
        tracker.stop()
    elapsed_s = time.perf_counter() - started

    photo_count = count_photos(args.photos)
    photos_per_sec = photo_count / elapsed_s if elapsed_s > 0 else 0.0
    return {
        "cmd": cmd,
        "returncode": proc.returncode,
        "elapsed_s": round(elapsed_s, 2),
        "photo_count": photo_count,
        "device": args.device,
        "photos_per_sec": round(photos_per_sec, 3),
        "peak_rss_mb": _rounded_mb(tracker.peak_rss_mb),
        "rss_method": tracker.rss_method,
        "peak_gpu_memory_mb": _rounded_mb(tracker.peak_gpu_memory_mb),
        "gpu_memory_method": tracker.gpu_memory_method,
        "stdout_tail": output_lines[-50:],
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--photos", type=Path, required=True, help="Photo directory")
    p.add_argument(
        "--pass",
        dest="pass_",
        default=None,
        help="Run a single pass (quality, embeddings, tags, faces, ...)",
    )
    p.add_argument(
        "--device",
        choices=("auto", "cpu", "cuda", "mps"),
        default="auto",
        help="Set FACET_DEVICE for the benchmark subprocess",
    )
    p.add_argument(
        "--force", action="store_true", help="Re-scan photos already in the DB"
    )
    p.add_argument(
        "--single-pass",
        action="store_true",
        help="Force single-pass mode (all models in VRAM)",
    )
    p.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Use a specific DB path (recommended: a throwaway copy)",
    )
    p.add_argument(
        "--label",
        default="scoring",
        help="Suite label, written into the result filename",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    started_at = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    print(f"=== scoring_throughput started at {started_at} ===")
    result = run_facet(args)
    payload = {
        "suite": args.label,
        "branch": bench.repo_branch(),
        "commit": bench.repo_commit(),
        "started_at": started_at,
        "args": {
            "photos": str(args.photos),
            "pass": args.pass_,
            "device": args.device,
            "force": args.force,
            "single_pass": args.single_pass,
            "db": str(args.db) if args.db else None,
        },
        "result": result,
    }
    out_path = bench.results_path(args.label)
    out_path.write_text(json.dumps(payload, indent=2))
    print(
        f"\ndevice={result['device']} photos={result['photo_count']} "
        f"elapsed={result['elapsed_s']}s "
        f"throughput={result['photos_per_sec']} photos/sec "
        f"peak_rss={_format_mb(result['peak_rss_mb'])} "
        f"peak_gpu_memory={_format_mb(result['peak_gpu_memory_mb'])}"
    )
    print(f"peak_rss_mb measured by: {result['rss_method']}")
    print(f"peak_gpu_memory_mb measured by: {result['gpu_memory_method']}")
    print(f"Saved: {out_path.relative_to(bench.REPO_ROOT)}")
    return result["returncode"]


if __name__ == "__main__":
    raise SystemExit(main())
