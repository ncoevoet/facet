"""Per-stage and per-model timing helpers for the scan (measurement only).

Nothing here changes what a scan does or scores:

* :func:`build_stages` turns the additive counters ``ChunkedMultiPassProcessor``
  keeps in ``self.metrics`` into one ``busy / wait / occupancy`` record per
  pipeline stage, and :func:`format_stage_lines` prints it.
* :func:`add_by_model` / :func:`format_by_model_lines` book and print seconds per model.
* :class:`PhaseLedger` brackets startup, scoring and each post-scan step so the final
  ``Process wall`` line says where the time a user waits for went (the multi-pass
  ``Total time`` covers the scoring loop only).
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, List

logger = logging.getLogger("facet.stage_timing")

# Stages whose work runs on the scan thread, in pipeline order: (stage, metrics key).
# Plane rebuilds are nested inside inference and the thumbnail is carved out of the
# save counter by the processor, so no two of these overlap.
SCAN_THREAD_STAGES = (
    ("model_load", "model_load_time"),
    ("inference", "inference_time"),
    ("model_unload", "model_unload_time"),
    ("aggregate", "aggregate_time"),
    ("thumbnail", "thumbnail_time"),
    ("save", "save_time"),
)

# Stages that run on the decode pool, in worker-seconds: (stage, metrics key).
# ``decode`` is the image load (file read, RAW open and demosaic); ``analyze`` is the
# rest of a photo's worker body (technical metrics, composition, hash).
POOL_STAGES = (
    ("decode", "decode_worker_time"),
    ("analyze", "analyze_worker_time"),
    ("exif_fallback", "exif_fallback_time"),
)


def add_by_model(metrics: Dict[str, Any], key: str, model_name: str, seconds: float) -> None:
    """Accumulate ``seconds`` under ``metrics[key][model_name]`` (the dict is created on first use)."""
    bucket = metrics.setdefault(key, {})
    bucket[model_name] = bucket.get(model_name, 0.0) + seconds


def _stage(busy: float, wait: float, wait_on: str | None, pool: int, wall: float) -> Dict[str, Any]:
    occupancy = busy / (pool * wall) if pool > 0 and wall > 0 else None
    return {"busy_s": busy, "wait_s": wait, "wait_on": wait_on, "pool": pool,
            "wall_s": wall, "occupancy": occupancy}


def build_stages(metrics: Dict[str, Any], load_workers: int) -> Dict[str, Dict[str, Any]]:
    """One ``busy / wait / occupancy`` record per stage, from the processor's counters.

    The scan thread is a pool of one whose wall is ``total_time``; its ``scan`` record
    sums the stages it runs and carries the one wait it has, ``io_time`` (blocked on
    the decode). The decode pool's wall is ``io_decode_time`` and its records are in
    worker-seconds, so occupancy = worker-s / (pool size x wall).
    """
    total = float(metrics.get("total_time") or 0.0)
    stages: Dict[str, Dict[str, Any]] = {}
    scan_busy = 0.0
    for name, key in SCAN_THREAD_STAGES:
        busy = float(metrics.get(key) or 0.0)
        scan_busy += busy
        stages[name] = _stage(busy, 0.0, None, 1, total)
    stages["scan"] = _stage(scan_busy, float(metrics.get("io_time") or 0.0), "decode", 1, total)

    decode_wall = float(metrics.get("io_decode_time") or 0.0)
    for name, key in POOL_STAGES:
        stages[name] = _stage(float(metrics.get(key) or 0.0), 0.0, None, load_workers, decode_wall)
    # The batched exiftool call is one process, not a pool member. It runs on the EXIF
    # prefetch thread beside the previous chunk (plus the synchronous call for chunk 0
    # and any missing path), so its wall is the scan's, not the decode's. The time the
    # decode was blocked on it is ``exif_wait_time``, a part of the decode wall.
    stages["exif_batch"] = _stage(float(metrics.get("exif_batch_time") or 0.0), 0.0, None, 1, total)
    return stages


def scan_thread_accounting(stages: Dict[str, Dict[str, Any]], total_time: float) -> Dict[str, float]:
    """How much of the scan thread's wall the stage records explain.

    ``unaccounted_s`` is what no counter covers (cache trims, chunk bookkeeping).
    """
    scan = stages["scan"]
    accounted = scan["busy_s"] + scan["wait_s"]
    unaccounted = total_time - accounted
    return {"accounted_s": accounted, "unaccounted_s": unaccounted,
            "unaccounted_share": unaccounted / total_time if total_time > 0 else 0.0}


def format_stage_lines(stages: Dict[str, Dict[str, Any]]) -> List[str]:
    """The ``Stages:`` block: the scan thread's summary line, then one line per decode-pool stage."""
    lines = []
    # The serial scan-thread stages are already in the multi-pass "Time breakdown".
    order = ["scan"] + [n for n, _ in POOL_STAGES] + ["exif_batch"]
    for name in order:
        s = stages[name]
        wait_on = s["wait_on"] if s["wait_on"] else "-"
        occ = "-" if s["occupancy"] is None else "%.0f%%" % (100 * s["occupancy"])
        lines.append("    %s: busy %.1fs, wait %.1fs (wait_on=%s), pool %d, wall %.1fs, occupancy %s"
                     % (name, s["busy_s"], s["wait_s"], wait_on, s["pool"], s["wall_s"], occ))
    return lines


def format_by_model_lines(values: Dict[str, float], share_of: float | None) -> List[str]:
    """``name: X.Xs (N%)`` lines sorted descending; ``share_of`` None omits the percent."""
    lines = []
    for name, secs in sorted(values.items(), key=lambda kv: kv[1], reverse=True):
        if share_of:
            lines.append("    %s: %.1fs (%.0f%%)" % (name, secs, 100 * secs / share_of))
        else:
            lines.append("    %s: %.1fs" % (name, secs))
    return lines


class PhaseLedger:
    """Brackets for startup, scoring and every post-scan step of one scan process.

    ``elapsed_before`` is how long the process had lived when the ledger was made
    (``psutil`` create time); everything after is measured on ``clock``. The final
    line splits the wall into startup (process start until the first bracketed
    phase), scoring, post-scan and ``other`` (gaps between brackets), so a bracket
    that is missing shows up as ``other`` rather than vanishing.
    """

    def __init__(self, clock: Callable[[], float] = time.perf_counter, elapsed_before: float = 0.0):
        self._clock = clock
        self._elapsed_before = elapsed_before
        self._t0 = clock()
        self._open: Dict[str, tuple] = {}
        self._first_start: float | None = None
        self.durations: Dict[str, float] = {}
        self.groups: Dict[str, str] = {}

    @classmethod
    def for_process(cls) -> "PhaseLedger":
        """A ledger anchored at this process's creation time (0 elapsed if psutil cannot say)."""
        try:
            import psutil
            before = max(0.0, time.time() - psutil.Process().create_time())
        except Exception:  # measurement only: never fail a scan over it
            before = 0.0
        return cls(elapsed_before=before)

    def begin(self, name: str, group: str = "post-scan") -> None:
        now = self._clock()
        if self._first_start is None:
            self._first_start = now
        self._open[name] = (now, group)

    def end(self, name: str) -> None:
        """Close ``name``; idempotent, so a ``finally`` may call it after a normal end."""
        opened = self._open.pop(name, None)
        if opened is None:
            return
        start, group = opened
        seconds = self._clock() - start
        self.durations[name] = self.durations.get(name, 0.0) + seconds
        self.groups[name] = group
        if group == "post-scan":
            logger.info("Post-scan %s: %.1fs", name, seconds)

    def parts(self) -> Dict[str, float]:
        """``{wall, startup, scoring, post_scan, other}`` in seconds."""
        wall = self._elapsed_before + (self._clock() - self._t0)
        first = self._first_start if self._first_start is not None else self._clock()
        startup = self._elapsed_before + (first - self._t0)
        scoring = sum(v for n, v in self.durations.items() if self.groups[n] == "scoring")
        post = sum(v for n, v in self.durations.items() if self.groups[n] == "post-scan")
        return {"wall": wall, "startup": startup, "scoring": scoring, "post_scan": post,
                "other": wall - startup - scoring - post}

    def summary_line(self) -> str:
        p = self.parts()
        return ("Process wall: %.1fs (startup %.1fs, scoring %.1fs, post-scan %.1fs, other %.1fs)"
                % (p["wall"], p["startup"], p["scoring"], p["post_scan"], p["other"]))
