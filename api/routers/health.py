"""
Health and readiness check endpoints.

Provides /health (liveness) and /ready (readiness) for orchestrators
and load balancers.
"""

import collections
import logging
import threading
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from api.config import _FULL_CONFIG
from api.database import get_async_db, get_db
from db import DEFAULT_DB_PATH

logger = logging.getLogger(__name__)

# Process uptime — captured at module import time. Exposed via /metrics.
_PROCESS_START_TIME = time.monotonic()

# Sliding-window rate limiter for /api/client-errors keyed by IP.
# 20 reports per 60 seconds keeps logs sane while permitting bursty
# Angular crash-on-load scenarios. In-process, single-worker only — for
# multi-worker deployments use an external rate limiter / log filter.
_CLIENT_ERROR_RATE_MAX = 20
_CLIENT_ERROR_RATE_WINDOW = 60.0
_client_error_attempts: dict[str, collections.deque] = {}
_client_error_lock = threading.Lock()


def _client_error_rate_check(key: str) -> bool:
    now = time.monotonic()
    cutoff = now - _CLIENT_ERROR_RATE_WINDOW
    with _client_error_lock:
        dq = _client_error_attempts.setdefault(key, collections.deque())
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= _CLIENT_ERROR_RATE_MAX:
            return False
        dq.append(now)
        return True


def _sanitize_log_field(value: str | None) -> str:
    """Strip newlines and control chars so attacker input can't forge log lines."""
    if not value:
        return ""
    return "".join(ch if 32 <= ord(ch) < 127 or ch == "\t" else "?" for ch in value)

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    """Liveness check — confirms the process is running."""
    return {"status": "ok"}


@router.get("/ready")
async def ready():
    """Readiness check — verifies the database is accessible and reports
    fast-path availability.

    Returns ``status: ready`` (200) when the DB ping succeeds, even if some
    fast paths are unavailable — load balancers should keep routing traffic.
    The ``degraded`` array lists subsystems running in fallback mode so
    operators can see "did the production deploy actually wire up
    sqlite-vec?" with one curl.

    Reference implementation of the get_async_db() migration pattern: the
    endpoint is fully async, opens an aiosqlite connection, runs a trivial
    query without blocking the event loop, and records its elapsed time
    into the readiness payload.
    """
    checks: dict = {}
    t0 = time.monotonic()
    try:
        async with get_async_db() as conn:
            cursor = await conn.execute("SELECT 1")
            await cursor.fetchone()
            await cursor.close()
            checks["database"] = "ok"
            # Probe fast-path availability on the same async connection so a
            # /ready call after a fresh restart populates the cached state
            # before the first /api/search hits production traffic.
            try:
                from api.routers.search import _check_vec_available, _has_fts
                vec_ok = await _check_vec_available(conn)
                fts_ok = await _has_fts(conn)
                checks["vec"] = "ok" if vec_ok else "unavailable"
                checks["fts"] = "ok" if fts_ok else "unavailable"
            except Exception:
                logger.warning("Fast-path probe failed in /ready", exc_info=True)
    except Exception:
        checks["database"] = "unavailable"
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "checks": checks, "degraded": []},
        )

    elapsed_ms = (time.monotonic() - t0) * 1000.0
    _ready_latency_samples.append(elapsed_ms)
    if len(_ready_latency_samples) > _LATENCY_RING_SIZE:
        _ready_latency_samples.pop(0)

    degraded = [name for name in ("vec", "fts") if checks.get(name) == "unavailable"]
    return {
        "status": "ready",
        "checks": checks,
        "degraded": degraded,
        "elapsed_ms": round(elapsed_ms, 2),
    }


# Ring buffer for /ready async DB latency — exposed via /metrics.
_LATENCY_RING_SIZE = 100
_ready_latency_samples: list[float] = []


def _metrics_enabled() -> bool:
    """Read viewer.features.metrics_enabled (default False, opt-in).

    Public metrics expose photo/person/face counts and DB size — useful intel
    for an attacker fingerprinting a public deployment. Defaults to disabled;
    enable explicitly when the endpoint is reachable only from the local
    Prometheus scraper / monitoring network.
    """
    return bool(_FULL_CONFIG.get("viewer", {}).get("features", {}).get("metrics_enabled", False))


@router.get("/metrics")
def metrics(request: Request):
    """Prometheus-style metrics endpoint.

    Returns text in Prometheus exposition format. Includes DB-derived
    counters, GPU VRAM, scan activity, async readiness latency, and
    fast-path availability gauges.

    The fast-path gauges (vec_available, fts_available, photo_tags_available,
    etc.) let operators answer "is search actually using the intended fast
    path?" without code inspection. See plan
    drifting-crafting-lampson.md Part B for context.

    Intentionally lightweight (no histograms / per-handler buckets) —
    sufficient for scan progress and library-size monitoring.

    Opt-in via ``viewer.features.metrics_enabled = true`` in scoring_config.json.
    """
    if not _metrics_enabled():
        raise HTTPException(status_code=404, detail="Not Found")

    lines: list[str] = []

    def gauge(name: str, value: float | int, help_text: str) -> None:
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} gauge")
        lines.append(f"{name} {value}")

    def counter(name: str, value: int, help_text: str) -> None:
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} counter")
        lines.append(f"{name} {value}")

    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT "
                "COUNT(*) AS photos, "
                "SUM(CASE WHEN clip_embedding IS NOT NULL THEN 1 ELSE 0 END) AS with_emb, "
                "SUM(CASE WHEN topiq_score IS NOT NULL THEN 1 ELSE 0 END) AS with_topiq "
                "FROM photos"
            ).fetchone()
            gauge("facet_photos_total", row["photos"] or 0, "Total photos in DB")
            gauge("facet_photos_with_embedding", row["with_emb"] or 0, "Photos with cached CLIP/SigLIP embedding")
            gauge("facet_photos_with_topiq", row["with_topiq"] or 0, "Photos with TOPIQ score populated")

            persons_row = conn.execute("SELECT COUNT(*) AS n FROM persons").fetchone()
            gauge("facet_persons_total", persons_row["n"] or 0, "Total person clusters")

            faces_row = conn.execute("SELECT COUNT(*) AS n FROM faces").fetchone()
            gauge("facet_faces_total", faces_row["n"] or 0, "Total faces")
    except Exception:
        # If the DB is unreachable, still serve metrics that don't depend on it.
        pass

    # DB file size on disk (sum of main file + WAL + SHM)
    try:
        db_path = Path(DEFAULT_DB_PATH)
        total_bytes = 0
        for suffix in ("", "-wal", "-shm"):
            p = db_path.with_name(db_path.name + suffix) if suffix else db_path
            if p.exists():
                total_bytes += p.stat().st_size
        gauge("facet_db_size_bytes", total_bytes, "DB file size on disk including WAL and SHM")
    except Exception:
        pass

    # Process memory (best-effort, requires psutil)
    try:
        import psutil
        import os as _os
        rss = psutil.Process(_os.getpid()).memory_info().rss
        gauge("facet_process_memory_bytes", rss, "Resident set size of the API process")
    except Exception:
        pass

    # Process uptime
    gauge(
        "facet_uptime_seconds",
        round(time.monotonic() - _PROCESS_START_TIME, 1),
        "Seconds since the API process started",
    )

    # GPU VRAM (best-effort, requires torch with CUDA)
    try:
        import torch
        if torch.cuda.is_available():
            allocated = torch.cuda.memory_allocated(0)
            reserved = torch.cuda.memory_reserved(0)
            total = torch.cuda.get_device_properties(0).total_memory
            gauge("facet_gpu_vram_allocated_bytes", allocated,
                  "GPU memory currently allocated by torch")
            gauge("facet_gpu_vram_reserved_bytes", reserved,
                  "GPU memory reserved by torch's caching allocator")
            gauge("facet_gpu_vram_total_bytes", total,
                  "Total GPU memory available on device 0")
    except Exception:
        pass

    # Scan activity — read from the scan module's global state.
    try:
        from api.routers.scan import _scan_state
        is_running = bool((_scan_state or {}).get("running"))
        gauge("facet_scan_active", 1 if is_running else 0,
              "1 if a scan is currently running, 0 otherwise")
    except Exception:
        pass

    # Fast-path availability — answers "is the production deploy actually
    # using the intended fast paths?" without forcing operators to inspect code.
    # All reads are O(1) in-process state; no DB calls in the metrics handler.
    try:
        from api.routers.search import (
            _vec_available, _fts_available,
            _search_vec_fallback_total, _search_fts_skip_total,
        )
        gauge(
            "facet_vec_available",
            1 if _vec_available is True else 0,
            "1 if sqlite-vec extension loaded and photos_vec populated; 0 means /api/search uses NumPy fallback",
        )
        gauge(
            "facet_fts_available",
            1 if _fts_available is True else 0,
            "1 if photos_fts virtual table is queryable; 0 means text search skips BM25",
        )
        counter(
            "facet_search_vec_fallback_total",
            _search_vec_fallback_total,
            "Times /api/search ran NumPy matmul instead of sqlite-vec — climbing = degraded perf",
        )
        counter(
            "facet_search_fts_skip_total",
            _search_fts_skip_total,
            "Times FTS5 query threw OperationalError and returned empty",
        )
    except Exception:
        pass

    try:
        from api import config as _cfg
        from api.config import _count_cache, _stats_cache
        gauge(
            "facet_photo_tags_available",
            1 if _cfg._photo_tags_available is True else 0,
            "1 if photo_tags lookup table is populated; 0 means tag filters use slow LIKE scan",
        )
        gauge(
            "facet_existing_columns_cached",
            1 if _cfg._existing_columns_cache is not None else 0,
            "1 if lifespan-warmed PRAGMA table_info cache is populated",
        )
        gauge(
            "facet_count_cache_entries",
            len(_count_cache),
            "Number of cached SELECT COUNT(*) results in the in-memory cache",
        )
        # stats_cache_age = seconds since the oldest entry was stored.
        # An entry's `expires` is set via `time.time() + ttl` (see
        # api/config.py:_get_stats_cached), so the age MUST be computed in the
        # same clock domain — using time.monotonic() here would silently
        # report 0 forever because `expires - monotonic_now` evaluates to a
        # huge positive (it's roughly wall-clock time) which the `ttl - …`
        # then clamps to 0.
        if _stats_cache:
            ttl = max(0.0, float(_FULL_CONFIG.get("viewer", {}).get("cache_ttl_seconds", 3600)))
            now_wall = time.time()
            ages = [max(0.0, ttl - (e["expires"] - now_wall)) for e in _stats_cache.values()]
            gauge(
                "facet_stats_cache_age_seconds",
                round(max(ages), 1),
                "Age in seconds of the oldest entry in the in-memory stats cache",
            )
        else:
            gauge("facet_stats_cache_age_seconds", 0,
                  "Age in seconds of the oldest entry in the in-memory stats cache")
    except Exception:
        pass

    # WAL checkpoint thread liveness — if the thread died silently, the
    # `-wal` file grows unbounded between restarts. wal_file_size_bytes
    # tracks the symptom directly. The `enabled` gauge distinguishes
    # "intentionally disabled" (config sets wal_checkpoint_minutes=0) from
    # "thread died" — both would otherwise read alive=0.
    try:
        wal_thread = getattr(request.app.state, "wal_thread", None)
        enabled = wal_thread is not None
        gauge(
            "facet_wal_thread_enabled",
            1 if enabled else 0,
            "1 if WAL checkpoint thread is configured to run (performance.wal_checkpoint_minutes > 0)",
        )
        if enabled:
            gauge(
                "facet_wal_thread_alive",
                1 if wal_thread.is_alive() else 0,
                "1 if the periodic WAL checkpoint thread is running; 0 here = thread died silently",
            )
    except Exception:
        pass

    try:
        # Path + DEFAULT_DB_PATH are already imported above for the db_size
        # gauge; reuse rather than reimporting.
        wal_path = Path(DEFAULT_DB_PATH + "-wal")
        wal_size = wal_path.stat().st_size if wal_path.exists() else 0
        gauge(
            "facet_wal_file_size_bytes",
            wal_size,
            "Size of the SQLite -wal file on disk; growing without checkpoint = dead WAL thread",
        )
    except Exception:
        pass

    # Async readiness check latency — sampled from /ready hits, ring of last 100
    if _ready_latency_samples:
        sorted_samples = sorted(_ready_latency_samples)
        n = len(sorted_samples)
        gauge(
            "facet_ready_async_latency_ms_count",
            n,
            "Number of /ready async DB samples in the ring",
        )
        gauge(
            "facet_ready_async_latency_ms_p50",
            sorted_samples[n // 2],
            "Median latency of async DB readiness check (ms)",
        )
        gauge(
            "facet_ready_async_latency_ms_p95",
            sorted_samples[min(n - 1, int(n * 0.95))],
            "95th percentile latency of async DB readiness check (ms)",
        )
        gauge(
            "facet_ready_async_latency_ms_max",
            sorted_samples[-1],
            "Max latency of async DB readiness check in the ring (ms)",
        )

    body = "\n".join(lines) + "\n"
    return PlainTextResponse(body, media_type="text/plain; version=0.0.4")


class ClientErrorReport(BaseModel):
    """A crash report posted by the Angular GlobalErrorHandler."""
    message: str = Field(default="", max_length=2000)
    name: str | None = Field(default=None, max_length=200)
    stack: str | None = Field(default=None, max_length=8000)
    url: str | None = Field(default=None, max_length=2000)
    user_agent: str | None = Field(default=None, max_length=500)
    ts: str | None = Field(default=None, max_length=64)


@router.post("/api/client-errors")
def report_client_error(report: ClientErrorReport, request: Request):
    """Receive an SPA crash report and log it server-side.

    No DB writes — these are diagnostic logs only. Rate-limited at 20
    reports per IP per minute (in-process sliding window). All user-supplied
    fields are stripped of newlines and control chars before logging to
    prevent log injection. The remote IP is taken from request.client.host
    — behind a reverse proxy this is the proxy's IP, not the originator;
    document via X-Forwarded-For if abuse triage is needed.
    """
    client_ip = request.client.host if request.client else "unknown"
    if not _client_error_rate_check(client_ip):
        raise HTTPException(status_code=429, detail="Too many error reports")

    name = _sanitize_log_field(report.name) or "Error"
    message = _sanitize_log_field(report.message)
    url = _sanitize_log_field(report.url)
    logger.warning(
        "SPA error from %s — %s: %s (url=%s)",
        client_ip, name, message, url,
    )
    if report.stack:
        logger.warning("SPA stack: %s", _sanitize_log_field(report.stack))
    return {"received": True}
