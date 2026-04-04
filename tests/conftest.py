"""Shared fixtures for the Facet test suite.

Existing test files define their own ``client`` fixture locally, which takes
precedence over conftest-level fixtures.  The fixtures here are additive —
they provide common helpers so new tests can import less boilerplate.
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from api import create_app
from api.auth import CurrentUser


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
    """Create a fresh FastAPI application."""
    return create_app()


@pytest.fixture()
def client(app):
    """TestClient wrapping the Facet FastAPI app."""
    return TestClient(app)


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
