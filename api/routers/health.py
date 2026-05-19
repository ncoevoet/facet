"""
Health and readiness check endpoints.

Provides /health (liveness) and /ready (readiness) for orchestrators
and load balancers.
"""

import collections
import logging
import threading
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from api.config import _FULL_CONFIG
from api.database import get_async_db, get_db

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
    """Readiness check — verifies the database is accessible.

    Reference implementation of the get_async_db() migration pattern: the
    endpoint is fully async, opens an aiosqlite connection, runs a trivial
    query without blocking the event loop, and records its elapsed time
    into the readiness payload. Real load tests should compare this against
    the sync /health endpoint's response time at the same concurrency.
    """
    checks: dict = {}
    t0 = time.monotonic()
    try:
        async with get_async_db() as conn:
            cursor = await conn.execute("SELECT 1")
            await cursor.fetchone()
            await cursor.close()
            checks["database"] = "ok"
    except Exception:
        checks["database"] = "unavailable"
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "checks": checks},
        )

    elapsed_ms = (time.monotonic() - t0) * 1000.0
    _ready_latency_samples.append(elapsed_ms)
    if len(_ready_latency_samples) > _LATENCY_RING_SIZE:
        _ready_latency_samples.pop(0)
    return {"status": "ready", "checks": checks, "elapsed_ms": round(elapsed_ms, 2)}


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
def metrics():
    """Prometheus-style metrics endpoint.

    Returns text in Prometheus exposition format. Includes:
    - facet_photos_total
    - facet_photos_with_embedding
    - facet_photos_with_topiq
    - facet_persons_total
    - facet_faces_total
    - facet_db_size_bytes
    - facet_process_memory_bytes (if psutil is installed)

    Intentionally lightweight (no histograms / counters that require state) —
    sufficient for monitoring scan progress and library size over time.

    Opt-in via ``viewer.features.metrics_enabled = true`` in scoring_config.json.
    """
    if not _metrics_enabled():
        raise HTTPException(status_code=404, detail="Not Found")

    lines: list[str] = []

    def gauge(name: str, value: float | int, help_text: str) -> None:
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} gauge")
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
        from pathlib import Path
        from db import DEFAULT_DB_PATH
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
