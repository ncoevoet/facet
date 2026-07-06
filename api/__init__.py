"""
FastAPI application factory for the Facet API server.

Replaces Flask viewer — serves JSON API + Angular static files.
"""

import logging
import os
import sys
import time
import warnings
from contextlib import asynccontextmanager

# Ensure the project root is in Python path for local imports
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# scikit-image 0.26 deprecated SimilarityTransform.estimate() but InsightFace
# 0.7.3 still calls it. Drop once upstream ships a fix.
warnings.filterwarnings(
    "ignore", category=FutureWarning,
    message=r".*estimate.*deprecated.*", module=r"insightface\..*",
)

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.encoders import jsonable_encoder  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log HTTP requests with method, path, status, and duration.

    Requests slower than ``slow_request_ms`` are logged at WARNING with a SLOW
    marker so they stand out in production logs. A threshold <= 0 disables the
    escalation (everything stays at INFO).
    """

    def __init__(self, app, slow_request_ms: int = 1000):
        super().__init__(app)
        self.slow_request_ms = slow_request_ms

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        # Default to 500: if the inner app raises, no response is produced and
        # the exception propagates to ServerErrorMiddleware which returns 500.
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            # finally — so failed requests (and slow failures) are still logged.
            elapsed_ms = (time.perf_counter() - start) * 1000
            # Skip logging static asset requests to reduce noise
            path = request.url.path
            if not path.startswith("/assets/") and not path.endswith((".js", ".css", ".ico", ".map")):
                if 0 < self.slow_request_ms < elapsed_ms:
                    logger.warning(
                        "SLOW %s %s %d (%.0fms)",
                        request.method, path, status_code, elapsed_ms,
                    )
                else:
                    logger.info(
                        "%s %s %d (%.0fms)",
                        request.method, path, status_code, elapsed_ms,
                    )


# Default Content-Security-Policy that permits exactly the SPA's own surface:
# the inline theme-bootstrap script and loading-spinner style in index.html
# ('unsafe-inline'), Google Fonts (Roboto + Material Icons), OpenStreetMap
# tiles and data/blob thumbnails (img-src), and same-origin API calls. Tighten
# or disable via viewer.security_headers.content_security_policy.
DEFAULT_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com data:; "
    "img-src 'self' data: blob: https:; "
    "connect-src 'self'; "
    "frame-ancestors 'self'; "
    "base-uri 'self'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach security headers to every response.

    Three headers are always applied (no app-breaking risk): MIME-sniffing
    protection, same-origin framing, and a referrer policy. The
    Content-Security-Policy and HSTS headers are configurable via
    ``viewer.security_headers``. CSP defaults to a policy permitting the SPA's
    own resources; set it to an empty string to disable. HSTS is opt-in because
    the viewer often runs over plain HTTP on a LAN/NAS.
    """

    def __init__(self, app, csp: str = "", hsts: bool = False):
        super().__init__(app)
        self.csp = csp
        self.hsts = hsts

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if self.csp:
            response.headers.setdefault("Content-Security-Policy", self.csp)
        if self.hsts:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains",
            )
        return response


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Handle request-validation (422) errors.

    FastAPI's default 422 is silent server-side, which makes a malformed client
    request hard to diagnose. This logs the failure at WARNING and returns
    FastAPI's standard 422 body unchanged, so clients see no difference.
    """
    logger.warning("422 %s %s — %s", request.method, request.url.path, exc.errors())
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(exc.errors())})


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all for unhandled errors.

    Logs the traceback and returns a clean JSON body so a failure never leaks a
    stack trace or an HTML error page. HTTPException keeps its own handler and
    is unaffected.
    """
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — startup/shutdown hooks."""
    # Apply any pending schema migrations before warming caches that read the
    # column list.  init_database is idempotent: it CREATEs missing tables and
    # ALTERs in missing columns from db/schema.py.  Without this, an older
    # photo_scores_pro.db missing newer columns (similarity_reviewed,
    # burst_group_id, gps_*, caption, ...) causes runtime 500s on the
    # culling, capsules, and similar-photos endpoints.
    from api.database import DEFAULT_DB_PATH
    from db.schema import init_database
    try:
        init_database(DEFAULT_DB_PATH)
    except Exception:
        logger.warning("Schema migration on startup failed", exc_info=True)

    # init_database may have ALTERed columns onto the photos table — clear the
    # cache before warming it so the new column set is reflected. Without this,
    # a hot-deploy that adds a column would serve queries with the old column
    # set until the next API restart.
    from api.db_helpers import (
        get_existing_columns, is_photo_tags_available,
        backfill_image_dimensions, invalidate_existing_columns_cache,
    )
    invalidate_existing_columns_cache()
    get_existing_columns()
    is_photo_tags_available()
    backfill_image_dimensions()

    # Pre-compute capsules in a background thread so first visitor gets instant results
    from api.config import _FULL_CONFIG
    if _FULL_CONFIG.get("viewer", {}).get("features", {}).get("show_capsules", True):
        import threading
        def _precompute_capsules():
            try:
                from api.database import get_db_connection
                from api.routers.capsules import _set_cached_capsules
                from analyzers.capsule_generator import generate_all_capsules
                conn = get_db_connection()
                try:
                    capsules = generate_all_capsules(conn, config=_FULL_CONFIG)
                    _set_cached_capsules(None, capsules)
                    logger.info("Pre-computed %d capsules on startup", len(capsules))
                finally:
                    conn.close()
            except Exception:
                logger.warning("Failed to pre-compute capsules", exc_info=True)
        threading.Thread(target=_precompute_capsules, daemon=True).start()

    # WAL checkpoint thread — periodically truncates the WAL to keep it from
    # ballooning on long-running deployments. Skip if interval <= 0.
    wal_minutes = int(_FULL_CONFIG.get("performance", {}).get("wal_checkpoint_minutes", 30))
    wal_stop = None
    wal_thread = None
    if wal_minutes > 0:
        import threading
        wal_stop = threading.Event()

        def _wal_checkpoint_loop():
            from api.database import get_db_connection
            interval = max(60, wal_minutes * 60)
            while not wal_stop.wait(interval):
                try:
                    conn = get_db_connection()
                    try:
                        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                        conn.commit()
                    finally:
                        conn.close()
                except Exception:
                    # Broad except: the loop must survive any transient error
                    # (sqlite lock contention, extension load issues, OSError
                    # when the DB file is being moved, etc.). A narrow sqlite3.Error
                    # let non-sqlite exceptions kill the thread silently.
                    logger.warning("WAL checkpoint failed", exc_info=True)

        # daemon=True so the thread doesn't block process exit if join() times out,
        # but we still try to join cleanly on lifespan shutdown.
        wal_thread = threading.Thread(target=_wal_checkpoint_loop, daemon=True, name="wal-checkpoint")
        wal_thread.start()
        logger.info("WAL checkpoint thread enabled (every %d min)", wal_minutes)

    # Expose the WAL thread reference so /metrics can report whether it died.
    app.state.wal_thread = wal_thread

    logger.info("Facet API ready")
    yield
    if wal_stop is not None:
        wal_stop.set()
    if wal_thread is not None:
        # Bound the join so a stuck PRAGMA can't hang shutdown.
        wal_thread.join(timeout=5.0)
    # One-time WAL checkpoint on clean shutdown so the next start doesn't
    # inherit a bloated -wal file. Best-effort: a failure here is logged but
    # never blocks shutdown.
    if wal_minutes > 0:
        try:
            from api.database import get_db_connection
            conn = get_db_connection()
            try:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                conn.commit()
            finally:
                conn.close()
        except Exception:
            logger.warning("Final WAL checkpoint on shutdown failed", exc_info=True)
    # Shutdown: clean up plugin thread pool
    from plugins import get_plugin_manager
    _plugin_mgr = get_plugin_manager()
    if _plugin_mgr is not None:
        _plugin_mgr.shutdown()


def create_app() -> FastAPI:
    """FastAPI application factory."""
    app = FastAPI(
        title="Facet API",
        description="Multi-dimensional photo analysis engine API",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    from api.config import _FULL_CONFIG

    # Request logging middleware — requests slower than the configured
    # threshold (performance.slow_request_ms) are logged at WARNING.
    slow_request_ms = int(_FULL_CONFIG.get("performance", {}).get("slow_request_ms", 1000))
    app.add_middleware(RequestLoggingMiddleware, slow_request_ms=slow_request_ms)

    # CORS middleware — origins from scoring_config.json viewer.allowed_origins
    default_origins = ["http://localhost:4200", "http://localhost:5000"]
    allowed_origins = _FULL_CONFIG.get("viewer", {}).get("allowed_origins", default_origins)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Security headers — safe headers always on; CSP + HSTS configurable via
    # viewer.security_headers (CSP defaults to a SPA-safe policy, HSTS opt-in).
    sec_headers = _FULL_CONFIG.get("viewer", {}).get("security_headers", {})
    app.add_middleware(
        SecurityHeadersMiddleware,
        csp=sec_headers.get("content_security_policy", DEFAULT_CSP),
        hsts=bool(sec_headers.get("hsts", False)),
    )

    # Exception handlers — uniform JSON error responses + server-side logging.
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    # Register routers
    from api.routers.health import router as health_router
    from api.routers.auth import router as auth_router
    from api.routers.gallery import router as gallery_router
    from api.routers.thumbnails import router as thumbnails_router
    from api.routers.filter_options import router as filter_options_router
    from api.routers.faces import router as faces_router
    from api.routers.persons import router as persons_router
    from api.routers.merge_suggestions import router as merge_suggestions_router
    from api.routers.comparison import router as comparison_router
    from api.routers.stats import router as stats_router
    from api.routers.scan import router as scan_router
    from api.routers.i18n import router as i18n_router
    from api.routers.search import router as search_router
    from api.routers.albums import router as albums_router
    from api.routers.proofing import router as proofing_router
    from api.routers.critique import router as critique_router
    from api.routers.burst_culling import router as burst_culling_router
    from api.routers.plugins import router as plugins_router
    from api.routers.memories import router as memories_router
    from api.routers.caption import router as caption_router
    from api.routers.timeline import router as timeline_router
    from api.routers.map import router as map_router
    from api.routers.capsules import router as capsules_router
    from api.routers.folders import router as folders_router
    from api.routers.export import router as export_router
    from api.routers.ranker import router as ranker_router
    from api.routers.scenes import router as scenes_router
    from api.routers.saliency import router as saliency_router
    from api.routers.social_crop import router as social_crop_router
    from api.routers.portfolio import router as portfolio_router
    from api.routers.cull_preview import router as cull_preview_router
    from api.routers.frame import router as frame_router

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(gallery_router)
    app.include_router(thumbnails_router)
    app.include_router(filter_options_router)
    app.include_router(faces_router)
    app.include_router(persons_router)
    app.include_router(merge_suggestions_router)
    app.include_router(comparison_router)
    app.include_router(stats_router)
    app.include_router(scan_router)
    app.include_router(i18n_router)
    app.include_router(search_router)
    app.include_router(albums_router)
    app.include_router(proofing_router)
    app.include_router(critique_router)
    app.include_router(burst_culling_router)
    app.include_router(plugins_router)
    app.include_router(memories_router)
    app.include_router(caption_router)
    app.include_router(timeline_router)
    app.include_router(map_router)
    app.include_router(capsules_router)
    app.include_router(folders_router)
    app.include_router(export_router)
    app.include_router(ranker_router)
    app.include_router(scenes_router)
    app.include_router(saliency_router)
    app.include_router(social_crop_router)
    app.include_router(portfolio_router)
    app.include_router(cull_preview_router)
    app.include_router(frame_router)

    # Check for plaintext passwords at startup
    from api.auth import check_legacy_password_warnings
    check_legacy_password_warnings()

    # Initialise plugin manager (global singleton + router reference)
    from plugins import init_global_plugin_manager
    from api.routers.plugins import init_plugin_manager
    init_plugin_manager(init_global_plugin_manager(config=_FULL_CONFIG))

    # Mount Angular static files (production)
    client_dist = os.path.join(_project_root, 'client', 'dist', 'client', 'browser')
    if os.path.isdir(client_dist):
        index_html = os.path.join(client_dist, 'index.html')

        # Serve static assets (JS, CSS, images) from the dist directory
        app.mount("/assets", StaticFiles(directory=os.path.join(client_dist, "assets")), name="assets") if os.path.isdir(os.path.join(client_dist, "assets")) else None

        # SPA catch-all: return index.html for any non-API route
        @app.get("/{path:path}", include_in_schema=False)
        async def spa_fallback(path: str):
            # Serve static files if they exist (JS chunks, CSS, etc.)
            resolved = os.path.realpath(os.path.join(client_dist, path))
            if not resolved.startswith(os.path.realpath(client_dist) + os.sep):
                return FileResponse(index_html)
            if os.path.isfile(resolved):
                return FileResponse(resolved)
            # Otherwise return index.html for client-side routing
            return FileResponse(index_html)

    return app
