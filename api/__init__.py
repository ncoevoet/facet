"""
FastAPI application factory for the Facet API server.

Replaces Flask viewer — serves JSON API + Angular static files.
"""

import os
import sys

# Ensure the project root is in Python path for local imports
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — startup/shutdown hooks."""
    # Startup: warm up caches
    from api.db_helpers import get_existing_columns, is_photo_tags_available, backfill_image_dimensions
    get_existing_columns()
    is_photo_tags_available()
    backfill_image_dimensions()
    yield
    # Shutdown: nothing to clean up (sqlite connections are per-request)


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

    # CORS middleware (dev: allow Angular dev server)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:4200",  # Angular dev server
            "http://localhost:5000",  # Same-port access
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routers
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
