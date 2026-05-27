"""Shared fixtures for the Facet test suite.

Existing test files define their own ``client`` fixture locally, which takes
precedence over conftest-level fixtures.  The fixtures here are additive —
they provide common helpers so new tests can import less boilerplate.

**Auth fixtures**: use ``edition_client`` / ``regular_client`` /
``superadmin_client`` / ``anonymous_client`` instead of ``mock.patch`` on
``api.routers.X.require_*``. FastAPI captures dependency callables inside
``Depends()`` at route registration; module-level ``mock.patch`` rebinds the
symbol but not the captured reference, so it's silently inert and tests
pass-by-accident. ``app.dependency_overrides`` is the documented FastAPI
mechanism that actually bypasses the captured reference.
"""

import os
import tempfile

# Point ``DB_PATH`` at a per-session tmp file BEFORE any project module is
# imported. ``db.connection.DEFAULT_DB_PATH`` and every ``from db import
# DEFAULT_DB_PATH`` re-export (api.database, api.routers.comparison,
# comparison.comparison_manager, …) capture the env value at import time,
# so a late ``monkeypatch`` would only patch the symbol in one module while
# the rest keep their original captured copy. Setting the env up-front
# routes every captured copy at the same fresh, schema-initialised DB.
_TEST_DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TEST_DB_FILE.close()
os.environ["DB_PATH"] = _TEST_DB_FILE.name

from unittest.mock import MagicMock  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from api import create_app  # noqa: E402
from api.auth import (  # noqa: E402
    CurrentUser, get_optional_user, require_authenticated,
    require_edition, require_superadmin,
)
from db.schema import init_database  # noqa: E402

init_database(_TEST_DB_FILE.name)


# ---------------------------------------------------------------------------
# Minimal config constants — enough to satisfy most API code paths.
# ---------------------------------------------------------------------------

MINIMAL_VIEWER_CONFIG: dict = {
    "password": "",
    "edition_password": "",
    "pagination": {"default_per_page": 50},
    "defaults": {
        "hide_blinks": True,
        "hide_bursts": True,
        "hide_duplicates": True,
        "hide_details": True,
        "hide_rejected": True,
        "sort": "aggregate",
        "sort_direction": "DESC",
    },
    "features": {
        "show_semantic_search": True,
        "show_albums": True,
        "show_critique": True,
        "show_vlm_critique": False,
        "show_memories": True,
        "show_captions": True,
        "show_timeline": True,
        "show_map": False,
        "show_capsules": True,
        "show_similar_button": True,
        "show_merge_suggestions": True,
        "show_rating_controls": True,
        "show_rating_badge": True,
        "show_folders": True,
    },
    "dropdowns": {"max_cameras": 50, "max_lenses": 50, "max_persons": 50, "max_tags": 20},
    "display": {"tags_per_photo": 3},
    "quality_thresholds": {"good": 6, "great": 7, "excellent": 8, "best": 9},
    "photo_types": {"top_picks_min_score": 7, "low_light_max_luminance": 0.2},
    "cache_ttl_seconds": 0,
    "notification_duration_ms": 2000,
    "raw_processor": {"darktable": {"executable": "darktable-cli", "profiles": []}},
    "face_thumbnails": {"output_size_px": 64, "jpeg_quality": 80, "crop_padding_ratio": 0.2, "min_crop_size_px": 20},
}

MINIMAL_SCORING_CONFIG: dict = {
    "viewer": MINIMAL_VIEWER_CONFIG,
    "burst_detection": {"similarity_threshold_percent": 70, "time_window_minutes": 0.8},
    "face_detection": {"min_confidence_percent": 65, "blink_ear_threshold": 0.28},
    "face_clustering": {"min_faces_per_person": 2, "min_samples": 2, "merge_threshold": 0.6},
}


# ---------------------------------------------------------------------------
# App / client fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def app():
    """Create a fresh FastAPI application.

    The session DB (pointed at via ``DB_PATH`` env var set at module top)
    is already schema-initialised, so routes that read core tables
    (``photos``, ``albums``, ``persons``, ``comparisons``, …) return
    empty results instead of 500-ing on missing tables.
    """
    return create_app()


@pytest.fixture()
def client(app):
    """TestClient wrapping the Facet FastAPI app, no auth overrides.

    Use this only for endpoints that don't require auth. For auth-protected
    endpoints use ``edition_client`` / ``regular_client`` / ``superadmin_client``
    / ``anonymous_client`` so the test exercises the actual ``Depends()`` chain.
    """
    return TestClient(app)


def _make_client_with_user(user):
    """Build a TestClient where every auth dependency yields ``user``.

    Yields a cleanup-aware fixture body (caller wraps in ``yield ... clear()``).
    """
    app = create_app()
    for dep in (require_edition, require_authenticated, require_superadmin, get_optional_user):
        # Bind ``user`` via default arg so the lambda doesn't close over a
        # mutating outer ``user`` reference.
        app.dependency_overrides[dep] = lambda u=user: u
    return app


@pytest.fixture()
def edition_client():
    """TestClient where every auth dependency yields an edition-authenticated user.

    Use this for endpoints decorated with ``Depends(require_edition)``.
    """
    user = CurrentUser(user_id="test", role="admin", edition_authenticated=True)
    app = _make_client_with_user(user)
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def superadmin_client():
    """TestClient where every auth dependency yields a superadmin user.

    Use this for endpoints decorated with ``Depends(require_superadmin)``
    (e.g. ``/api/scan/*``).
    """
    user = CurrentUser(
        user_id="root", role="superadmin", display_name="Super Admin",
        edition_authenticated=True,
    )
    app = _make_client_with_user(user)
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def regular_client():
    """TestClient with a non-edition authenticated user.

    ``require_edition`` is intentionally NOT overridden — endpoints that need
    it will hit the real dependency and return 403, exercising the
    access-denied path.
    """
    user = CurrentUser(user_id="u1", role="user", display_name="User One")
    app = create_app()
    app.dependency_overrides[require_authenticated] = lambda: user
    app.dependency_overrides[get_optional_user] = lambda: user
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def anonymous_client():
    """TestClient with no authenticated user — exercises the public path."""
    app = create_app()
    app.dependency_overrides[get_optional_user] = lambda: None
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# User fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def edition_user():
    """A legacy-mode user with edition privileges."""
    return CurrentUser(edition_authenticated=True)


@pytest.fixture()
def admin_user():
    """A multi-user admin."""
    return CurrentUser(
        user_id="admin",
        role="admin",
        display_name="Admin",
        edition_authenticated=True,
    )


@pytest.fixture()
def superadmin_user():
    """A multi-user superadmin."""
    return CurrentUser(
        user_id="superadmin",
        role="superadmin",
        display_name="Super Admin",
        edition_authenticated=True,
    )


@pytest.fixture()
def regular_user():
    """A multi-user regular user (no edition)."""
    return CurrentUser(
        user_id="user1",
        role="user",
        display_name="User One",
    )


# ---------------------------------------------------------------------------
# Database mock
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_db():
    """Fresh MagicMock that mimics a sqlite3 connection."""
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    conn.execute.return_value = cursor
    cursor.fetchone.return_value = None
    cursor.fetchall.return_value = []
    return conn
