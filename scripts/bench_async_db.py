"""A/B benchmark for the sync vs async SQLite endpoints.

Hits the viewer's ``/health`` (sync sqlite3 inside the FastAPI thread pool) and
``/ready`` (aiosqlite via ``get_async_db``) at the same concurrency level and
reports p50 / p95 / p99 / max latencies. Use the numbers to decide whether the
async migration is worth pursuing on the hot read endpoints — or to set a
baseline before re-running after migrating each one.

Usage::

    python scripts/bench_async_db.py --base http://localhost:65432 \\
        --concurrency 1 5 20 --requests-per-level 200

The viewer must be running. Both endpoints are unauthenticated so this works
even when ``viewer.password`` is set.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from collections.abc import Iterable

import urllib.request
import urllib.error


def _hit_sync(url: str) -> float:
    """Single request via blocking stdlib. Returns elapsed seconds."""
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            resp.read()
    except urllib.error.URLError:
        return float("nan")
    return time.monotonic() - t0


async def _bench_endpoint(base: str, path: str, concurrency: int, total: int) -> list[float]:
    """Fire ``total`` requests with ``concurrency`` in-flight at a time."""
    url = base.rstrip("/") + path
    semaphore = asyncio.Semaphore(concurrency)
    results: list[float] = []

    async def worker():
        async with semaphore:
            # urllib is sync — offload to a thread so we don't serialize the loop.
            elapsed = await asyncio.to_thread(_hit_sync, url)
            results.append(elapsed)

    await asyncio.gather(*(worker() for _ in range(total)))
    return [r for r in results if r == r]  # filter NaN (failed)


def _summarize(name: str, samples: list[float]) -> dict[str, float | int]:
    if not samples:
        return {"name": name, "n": 0}
    samples_ms = sorted(s * 1000.0 for s in samples)
    n = len(samples_ms)
    return {
        "name": name,
        "n": n,
        "min": round(samples_ms[0], 2),
        "p50": round(samples_ms[n // 2], 2),
        "p95": round(samples_ms[min(n - 1, int(n * 0.95))], 2),
        "p99": round(samples_ms[min(n - 1, int(n * 0.99))], 2),
        "max": round(samples_ms[-1], 2),
        "mean": round(statistics.mean(samples_ms), 2),
    }


def _print_table(rows: Iterable[dict]) -> None:
    rows = list(rows)
    if not rows:
        print("No samples collected.")
        return
    cols = ["name", "n", "min", "p50", "p95", "p99", "max", "mean"]
    widths = {c: max(len(c), max(len(str(r.get(c, ""))) for r in rows)) for c in cols}
    print(" | ".join(c.rjust(widths[c]) for c in cols))
    print("-+-".join("-" * widths[c] for c in cols))
    for r in rows:
        print(" | ".join(str(r.get(c, "")).rjust(widths[c]) for c in cols))


async def main_async(args) -> int:
    print(f"Target: {args.base}")
    print(f"Levels: {args.concurrency}  Requests per level: {args.requests_per_level}")
    print()

    # Warmup so the first sample doesn't include cold caches.
    await _bench_endpoint(args.base, "/health", 1, 5)
    await _bench_endpoint(args.base, "/ready", 1, 5)

    rows: list[dict] = []
    for c in args.concurrency:
        sync_samples = await _bench_endpoint(args.base, "/health", c, args.requests_per_level)
        async_samples = await _bench_endpoint(args.base, "/ready", c, args.requests_per_level)
        rows.append(_summarize(f"sync /health  c={c}", sync_samples))
        rows.append(_summarize(f"async /ready  c={c}", async_samples))

    _print_table(rows)
    print()
    print("(latencies in ms; lower is better)")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base", default="http://localhost:65432", help="Viewer base URL")
    p.add_argument(
        "--concurrency",
        type=int,
        nargs="+",
        default=[1, 5, 20],
        help="Concurrency levels to test",
    )
    p.add_argument(
        "--requests-per-level",
        type=int,
        default=200,
        help="Number of requests at each concurrency level",
    )
    args = p.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
