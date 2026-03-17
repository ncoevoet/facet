"""
FastAPI application factory for the Facet API server.

Replaces Flask viewer — serves JSON API + Angular static files.
"""

import logging
import os
import sys
import time

# Ensure the project root is in Python path for local imports
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log HTTP requests with method, path, status, and duration."""

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000
        # Skip logging static asset requests to reduce noise
        path = request.url.path
        if not path.startswith("/assets/") and not path.endswith((".js", ".css", ".ico", ".map")):
            logger.info(
                "%s %s %d (%.0fms)",
                request.method, path, response.status_code, elapsed_ms,
            )
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — startup/shutdown hooks."""
    # Startup: warm up caches
    from api.db_helpers import get_existing_columns, is_photo_tags_available, backfill_image_dimensions
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

    logger.info("Facet API ready")
    yield
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

    # Request logging middleware
    app.add_middleware(RequestLoggingMiddleware)

    # CORS middleware — origins from scoring_config.json viewer.allowed_origins
    from api.config import _FULL_CONFIG
    default_origins = ["http://localhost:4200", "http://localhost:5000"]
    allowed_origins = _FULL_CONFIG.get("viewer", {}).get("allowed_origins", default_origins)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

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
    from api.routers.critique import router as critique_router
    from api.routers.burst_culling import router as burst_culling_router
    from api.routers.plugins import router as plugins_router
    from api.routers.memories import router as memories_router
    from api.routers.caption import router as caption_router
    from api.routers.timeline import router as timeline_router
    from api.routers.map import router as map_router
    from api.routers.capsules import router as capsules_router
    from api.routers.folders import router as folders_router

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
    app.include_router(critique_router)
    app.include_router(burst_culling_router)
    app.include_router(plugins_router)
    app.include_router(memories_router)
    app.include_router(caption_router)
    app.include_router(timeline_router)
    app.include_router(map_router)
    app.include_router(capsules_router)
    app.include_router(folders_router)

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
