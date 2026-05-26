"""HTTP endpoint benchmark driver.

Run named suites against a running viewer. Output is a JSON file in
``bench/results/`` plus a console table.

Example::

    venv/bin/python scripts/bench/bench.py --suite filters \\
        --base http://localhost:5000 --concurrency 10 --requests 50

If the viewer is in multi-user mode, pass a JWT via ``FACET_BENCH_TOKEN`` or
``--token``.

Suites:
    filters           — filter_options dropdowns (cameras/lenses/tags/etc.)
    stats             — /api/stats/* aggregates
    search            — full-text gallery search via /api/photos?q=...
    semantic_search   — /api/search?q=... (sqlite-vec + FTS5 hybrid)
    gallery           — /api/photos paged listings
    all               — every suite above in one run
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

if __package__ in (None, ""):
    # Allow ``python scripts/bench/bench.py`` (no -m) by fixing sys.path.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.bench import _common as bench
from scripts.bench._common import Sample, SuiteRun


@dataclass
class Endpoint:
    label: str
    method: str
    path: str
    params: dict | None = None

    def as_tuple(self) -> tuple[str, str, str, dict]:
        kwargs = {"params": self.params} if self.params else {}
        return (self.label, self.method, self.path, kwargs)


SUITES: dict[str, list[Endpoint]] = {
    "filters": [
        Endpoint("filter_options/cameras", "GET", "/api/filter_options/cameras"),
        Endpoint("filter_options/lenses", "GET", "/api/filter_options/lenses"),
        Endpoint("filter_options/tags", "GET", "/api/filter_options/tags"),
        Endpoint("filter_options/apertures", "GET", "/api/filter_options/apertures"),
        Endpoint(
            "filter_options/focal_lengths",
            "GET",
            "/api/filter_options/focal_lengths",
        ),
        Endpoint("filter_options/categories", "GET", "/api/filter_options/categories"),
    ],
    "stats": [
        Endpoint("stats/overview", "GET", "/api/stats/overview"),
        Endpoint("stats/score_distribution", "GET", "/api/stats/score_distribution"),
        Endpoint("stats/top_cameras", "GET", "/api/stats/top_cameras"),
        Endpoint("stats/categories", "GET", "/api/stats/categories"),
        Endpoint("stats/gear", "GET", "/api/stats/gear"),
        Endpoint("stats/timeline", "GET", "/api/stats/timeline"),
    ],
    "search": [
        Endpoint(
            "photos?search=portrait",
            "GET",
            "/api/photos",
            {"search": "portrait", "page": 1, "per_page": 64},
        ),
        Endpoint(
            "photos?search=mountain",
            "GET",
            "/api/photos",
            {"search": "mountain", "page": 1, "per_page": 64},
        ),
        Endpoint(
            "photos?search=beach",
            "GET",
            "/api/photos",
            {"search": "beach", "page": 1, "per_page": 64},
        ),
        Endpoint(
            "photos?search=street",
            "GET",
            "/api/photos",
            {"search": "street", "page": 1, "per_page": 64},
        ),
        Endpoint(
            "photos?search=sunset",
            "GET",
            "/api/photos",
            {"search": "sunset", "page": 1, "per_page": 64},
        ),
    ],
    "semantic_search": [
        Endpoint(
            "search?q=red car",
            "GET",
            "/api/search",
            {"q": "red car", "limit": 50},
        ),
        Endpoint(
            "search?q=family at the beach",
            "GET",
            "/api/search",
            {"q": "family at the beach", "limit": 50},
        ),
        Endpoint(
            "search?q=golden hour mountain",
            "GET",
            "/api/search",
            {"q": "golden hour mountain", "limit": 50},
        ),
        Endpoint(
            "search?q=black and white portrait",
            "GET",
            "/api/search",
            {"q": "black and white portrait", "limit": 50},
        ),
    ],
    "gallery": [
        Endpoint(
            "photos page=1",
            "GET",
            "/api/photos",
            {"page": 1, "per_page": 64},
        ),
        Endpoint(
            "photos page=5",
            "GET",
            "/api/photos",
            {"page": 5, "per_page": 64},
        ),
        Endpoint(
            "photos sort=aesthetic",
            "GET",
            "/api/photos",
            {"page": 1, "per_page": 64, "sort": "aesthetic", "sort_direction": "DESC"},
        ),
        Endpoint("type_counts", "GET", "/api/type_counts"),
    ],
    "index_targets": [
        Endpoint(
            "favorites_only",
            "GET",
            "/api/photos",
            {"page": 1, "per_page": 64, "favorites_only": 1},
        ),
        Endpoint(
            "hide_rejected",
            "GET",
            "/api/photos",
            {"page": 1, "per_page": 64, "hide_rejected": 1},
        ),
        Endpoint(
            "show_rejected",
            "GET",
            "/api/photos",
            {"page": 1, "per_page": 64, "show_rejected": 1},
        ),
        Endpoint(
            "min_rating=4",
            "GET",
            "/api/photos",
            {"page": 1, "per_page": 64, "min_rating": 4},
        ),
        Endpoint(
            "tag=portrait",
            "GET",
            "/api/photos",
            {"page": 1, "per_page": 64, "tag": "portrait"},
        ),
        Endpoint(
            "tag=landscape",
            "GET",
            "/api/photos",
            {"page": 1, "per_page": 64, "tag": "landscape"},
        ),
    ],
}


def resolve_suites(name: str) -> list[str]:
    if name == "all":
        return [s for s in SUITES.keys()]
    if name not in SUITES:
        raise SystemExit(
            f"Unknown suite '{name}'. Choose: {', '.join(SUITES.keys())}, all"
        )
    return [name]


async def run_one(
    suite: str,
    *,
    base_url: str,
    concurrency: int,
    warmup: int,
    requests: int,
    token: str | None,
) -> SuiteRun:
    endpoints = SUITES[suite]
    samples: list[Sample] = await bench.run_suite(
        base_url,
        [e.as_tuple() for e in endpoints],
        concurrency=concurrency,
        warmup=warmup,
        requests_per_endpoint=requests,
        auth_token=token,
    )
    return SuiteRun(
        suite=suite,
        base_url=base_url,
        branch=bench.repo_branch(),
        commit=bench.repo_commit(),
        started_at=bench.utc_stamp(),
        concurrency=concurrency,
        warmup=warmup,
        requests_per_endpoint=requests,
        samples=samples,
    )


async def main_async(args: argparse.Namespace) -> int:
    token = args.token or bench.env_token()
    suites = resolve_suites(args.suite)
    overall_ok = True
    for suite in suites:
        print(f"\n=== suite: {suite} ===")
        run = await run_one(
            suite,
            base_url=args.base,
            concurrency=args.concurrency,
            warmup=args.warmup,
            requests=args.requests,
            token=token,
        )
        # Table per label
        rows = []
        by_label: dict[str, list[Sample]] = {}
        for s in run.samples:
            by_label.setdefault(s.label, []).append(s)
        for label, entries in by_label.items():
            rows.append(bench.summarize(label, entries))
            if any(e.error for e in entries):
                overall_ok = False
        bench.print_table(rows)
        out = bench.save_results(run)
        print(f"\nSaved: {out.relative_to(bench.REPO_ROOT)}")
    return 0 if overall_ok else 2


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--suite",
        default="all",
        help="Suite name (filters, stats, search, semantic_search, gallery, all)",
    )
    p.add_argument(
        "--base",
        default="http://localhost:5000",
        help="Viewer base URL (default: http://localhost:5000)",
    )
    p.add_argument(
        "--concurrency", type=int, default=5, help="Concurrent in-flight requests"
    )
    p.add_argument(
        "--warmup",
        type=int,
        default=2,
        help="Warmup hits per endpoint before measurement",
    )
    p.add_argument(
        "--requests",
        type=int,
        default=20,
        help="Measured requests per endpoint (default 20)",
    )
    p.add_argument(
        "--token",
        default=None,
        help="JWT for multi-user mode (or set FACET_BENCH_TOKEN)",
    )
    return p.parse_args()


def main() -> int:
    return asyncio.run(main_async(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
