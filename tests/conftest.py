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
import sqlite3
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
    it hit the real dependency and return 403, exercising the access-denied
    path. An ``edition_password`` is set for the fixture's lifetime so the
    "no edition password configured ⇒ every authenticated user is edition"
    single-user shortcut in ``CurrentUser.is_edition`` is disabled; otherwise
    this ``edition_authenticated=False`` user would be granted edition access
    and the negative test would never reach the 403 path.
    """
    from api.auth import VIEWER_CONFIG
    user = CurrentUser(user_id="u1", role="user", display_name="User One")
    prev_edition_password = VIEWER_CONFIG.get("edition_password", "")
    VIEWER_CONFIG["edition_password"] = "test-edition-lock"
    app = create_app()
    app.dependency_overrides[require_authenticated] = lambda: user
    app.dependency_overrides[get_optional_user] = lambda: user
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        VIEWER_CONFIG["edition_password"] = prev_edition_password


@pytest.fixture()
def anonymous_client():
    """TestClient with no authenticated user — exercises the public path."""
    app = create_app()
    app.dependency_overrides[get_optional_user] = lambda: None
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Seeded photos (shared session database)
# ---------------------------------------------------------------------------

# Rows live under one path prefix so teardown is a single prefix-scoped
# DELETE that cannot touch another module's rows in the shared session DB.
SEEDED_PHOTOS_PREFIX = "/conftest-seeded/"

_SEEDED_PHOTOS = [
    {"path": SEEDED_PHOTOS_PREFIX + "a.jpg", "filename": "a.jpg", "aggregate": 8.5,
     "category": "portrait", "date_taken": "2026:01:01 10:00:00"},
    {"path": SEEDED_PHOTOS_PREFIX + "b.jpg", "filename": "b.jpg", "aggregate": 5.0,
     "category": "landscape", "date_taken": "2026:01:02 10:00:00"},
    {"path": SEEDED_PHOTOS_PREFIX + "c.jpg", "filename": "c.jpg", "aggregate": 2.0,
     "category": "default", "date_taken": "2026:01:03 10:00:00"},
]


@pytest.fixture()
def seeded_photos():
    """Insert a small set of photo rows into the SHARED session database.

    Writes into the DB behind ``DB_PATH`` (the one every ``client`` /
    ``edition_client`` / ``regular_client`` / ``superadmin_client`` /
    ``anonymous_client`` fixture builds its app against) instead of a
    private tmp DB, so a test can combine this with an auth-overridden
    client fixture and see the rows without standing up a second
    ``create_app()``. Modeled on tests/test_immich_webhook.py's
    ``_seed_photos`` / ``_clear_side_state`` idiom.

    Yields the seeded photo dicts (``path``, ``filename``, ``aggregate``,
    ``category``, ``date_taken``).
    """
    conn = sqlite3.connect(_TEST_DB_FILE.name)
    try:
        cols = list(_SEEDED_PHOTOS[0].keys())
        placeholders = ", ".join("?" for _ in cols)
        conn.executemany(
            f"INSERT INTO photos ({', '.join(cols)}) VALUES ({placeholders})",
            [[p[c] for c in cols] for p in _SEEDED_PHOTOS],
        )
        conn.commit()
        yield _SEEDED_PHOTOS
    finally:
        conn.execute("DELETE FROM photos WHERE path LIKE ?", (SEEDED_PHOTOS_PREFIX + "%",))
        conn.commit()
        conn.close()
