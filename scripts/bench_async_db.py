"""A/B benchmark for sync vs async SQLite endpoints with a real HTTP pool.

Hits two paths at the same concurrency and reports p50 / p95 / p99 / max
latencies in ms. Uses ``httpx.AsyncClient`` with a connection pool so the
benchmark isolates the server-side cost (DB query + serialization) rather
than the per-request TCP/handshake overhead of stdlib urllib.

Usage::

    python scripts/bench_async_db.py \\
        --base http://localhost:65432 \\
        --sync  /health         --async-path /ready \\
        --concurrency 1 5 20 50 \\
        --requests-per-level 500

The defaults compare /health (sync, just returns ok) against /ready (now
async via aiosqlite + SELECT 1). Override ``--sync`` / ``--async-path`` to
benchmark any pair (e.g. before/after migrating /api/timeline/years).
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import time
from collections.abc import Iterable

import httpx


async def _hit(client: httpx.AsyncClient, url: str) -> float:
    t0 = time.monotonic()
    try:
        resp = await client.get(url, timeout=30.0)
        # Read body so we don't measure only the headers.
        await resp.aread()
        if resp.status_code >= 400:
            return float("nan")
    except httpx.HTTPError:
        return float("nan")
    return time.monotonic() - t0


async def _bench(base: str, path: str, concurrency: int, total: int) -> list[float]:
    """Run ``total`` requests against ``path`` with ``concurrency`` in-flight."""
    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(base_url=base, limits=limits, http2=False) as client:
        sem = asyncio.Semaphore(concurrency)
        results: list[float] = []

        async def worker():
            async with sem:
                results.append(await _hit(client, path))

        await asyncio.gather(*(worker() for _ in range(total)))
    return [r for r in results if r == r]  # drop NaN


def _summarize(name: str, samples: list[float]) -> dict[str, float | int | str]:
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
        print("No samples.")
        return
    cols = ["name", "n", "min", "p50", "p95", "p99", "max", "mean"]
    widths = {c: max(len(c), max(len(str(r.get(c, ""))) for r in rows)) for c in cols}
    print(" | ".join(c.rjust(widths[c]) for c in cols))
    print("-+-".join("-" * widths[c] for c in cols))
    for r in rows:
        print(" | ".join(str(r.get(c, "")).rjust(widths[c]) for c in cols))


async def main_async(args) -> int:
    print(f"Target: {args.base}")
    print(f"Sync path:  {args.sync}")
    print(f"Async path: {args.async_path}")
    print(f"Levels: {args.concurrency}   Requests/level: {args.requests_per_level}")
    print()

    # Warmup pool + caches.
    await _bench(args.base, args.sync, 1, 10)
    await _bench(args.base, args.async_path, 1, 10)

    rows: list[dict] = []
    for c in args.concurrency:
        sync_samples = await _bench(args.base, args.sync, c, args.requests_per_level)
        async_samples = await _bench(args.base, args.async_path, c, args.requests_per_level)
        rows.append(_summarize(f"sync  {args.sync}  c={c}", sync_samples))
        rows.append(_summarize(f"async {args.async_path}  c={c}", async_samples))

    _print_table(rows)
    print()
    print("(latencies in ms; lower is better)")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base", default="http://localhost:65432")
    p.add_argument("--sync", default="/health", help="Path served by a sync handler")
    p.add_argument("--async-path", default="/ready", help="Path served by an async handler")
    p.add_argument("--concurrency", type=int, nargs="+", default=[1, 5, 20, 50])
    p.add_argument("--requests-per-level", type=int, default=500)
    args = p.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
