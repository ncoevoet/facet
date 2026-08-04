"""``facet.py`` throughput benchmark.

Runs ``facet.py`` on a fixed photo directory and reports photos/sec, peak RSS,
peak VRAM, and per-pass wallclock. Output mirrors ``bench.py`` so before/after
diffs are mechanical.

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
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.bench import _common as bench


def _try_import_psutil():
    try:
        import psutil  # type: ignore

        return psutil
    except Exception:
        return None


def _try_import_torch():
    try:
        import torch  # type: ignore

        return torch
    except Exception:
        return None


class ResourceTracker:
    """Polls RSS + VRAM in a background thread until ``stop()``."""

    def __init__(self, pid: int, interval_s: float = 0.5):
        self._psutil = _try_import_psutil()
        self._torch = _try_import_torch()
        self._pid = pid
        self._interval = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.peak_rss_mb = 0.0
        self.peak_vram_mb = 0.0
        self.samples: list[dict[str, float]] = []

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _loop(self) -> None:
        proc = None
        if self._psutil is not None:
            try:
                proc = self._psutil.Process(self._pid)
            except Exception:
                proc = None
        while not self._stop.is_set():
            t = time.time()
            rss_mb = 0.0
            if proc is not None:
                try:
                    rss_mb = proc.memory_info().rss / (1024 * 1024)
                except Exception:
                    rss_mb = 0.0
            vram_mb = 0.0
            if self._torch is not None and self._torch.cuda.is_available():
                try:
                    vram_mb = self._torch.cuda.max_memory_allocated() / (1024 * 1024)
                except Exception:
                    vram_mb = 0.0
            self.peak_rss_mb = max(self.peak_rss_mb, rss_mb)
            self.peak_vram_mb = max(self.peak_vram_mb, vram_mb)
            self.samples.append(
                {"t": t, "rss_mb": round(rss_mb, 1), "vram_mb": round(vram_mb, 1)}
            )
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
        "peak_rss_mb": round(tracker.peak_rss_mb, 1),
        "peak_vram_mb": round(tracker.peak_vram_mb, 1),
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
        f"peak_rss={result['peak_rss_mb']}MB "
        f"peak_vram={result['peak_vram_mb']}MB"
    )
    print(f"Saved: {out_path.relative_to(bench.REPO_ROOT)}")
    return result["returncode"]


if __name__ == "__main__":
    raise SystemExit(main())
