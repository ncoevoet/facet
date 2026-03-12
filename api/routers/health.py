"""
Health and readiness check endpoints.

Provides /health (liveness) and /ready (readiness) for orchestrators
and load balancers.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from api.database import get_db_connection

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    """Liveness check — confirms the process is running."""
    return {"status": "ok"}


@router.get("/ready")
async def ready():
    """Readiness check — verifies the database is accessible."""
    checks = {}
    try:
        conn = get_db_connection()
        try:
            conn.execute("SELECT 1")
            checks["database"] = "ok"
        finally:
            conn.close()
    except Exception as exc:
        checks["database"] = "unavailable"
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "checks": checks},
        )

    return {"status": "ready", "checks": checks}
