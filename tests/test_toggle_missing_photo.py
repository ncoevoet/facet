"""Per-photo write endpoints must 404 on a photo the caller cannot write, in both auth modes.

Three endpoints share one shape — ``photo_path`` in, a write to either
``photos`` or ``user_preferences`` out — and each got the guard wrong
differently:

* multi-user: ``user_preferences.photo_path`` is
  ``TEXT NOT NULL REFERENCES photos(path)`` with ``PRAGMA foreign_keys = ON``,
  so a stale path raised ``IntegrityError`` and surfaced as a 500. That is
  reachable from an ordinary client — the gallery holds a photo the user
  favourites after a rescan has pruned the row.
* single-user: ``UPDATE photos ... WHERE path = ?`` against an unknown path
  matches zero rows, and ``set_rating`` reported ``{'success': True}`` anyway.
* the first fix probed ``SELECT 1 FROM photos WHERE path = ?`` with NO
  visibility clause, which turned the 404 into a per-path existence oracle over
  every other tenant's library — and then wrote a ``user_preferences`` row for a
  photo the caller cannot see.

The guard therefore has to answer identically for "does not exist" and "exists
but is not yours", and must still let a caller write her own photos.
"""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from api import config as api_config
from api import create_app
from api.auth import CurrentUser, require_auth
from api.routers import faces
from db import DEFAULT_DB_PATH

ALICE_DIR = "/mu-alice"
BOB_DIR = "/mu-bob"
ALICE_PHOTO = ALICE_DIR + "/own.jpg"
BOB_PHOTO = BOB_DIR + "/secret.jpg"
BOB_MISSING = BOB_DIR + "/nope.jpg"
MISSING = "/no/such/photo-for-toggle.jpg"

# (endpoint, extra body keys beyond photo_path)
ENDPOINTS = [
    ("/api/photo/toggle_favorite", {}),
    ("/api/photo/toggle_rejected", {}),
    ("/api/photo/set_rating", {"rating": 3}),
]
ENDPOINT_IDS = [path.rsplit("/", 1)[-1] for path, _ in ENDPOINTS]


def _body(extra, photo_path):
    return {"photo_path": photo_path, **extra}


def _client_for(user):
    app = create_app()
    app.dependency_overrides[require_auth] = lambda: user
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        faces.flush_rating_comparisons()


@pytest.fixture()
def multi_user_client():
    """Authenticated client with multi-user mode genuinely on.

    ``users`` is injected into the live config rather than patched onto one
    module, because ``assert_photo_visible`` resolves ``is_multi_user_enabled``
    and ``get_user_directories`` through ``api.db_helpers`` / ``api.config`` —
    patching only ``api.routers.faces`` would leave the visibility probe inert
    and the cross-tenant test would pass without exercising anything.
    """
    prev_users = api_config._FULL_CONFIG.get("users")
    api_config._FULL_CONFIG["users"] = {"alice": {"directories": [ALICE_DIR]}}
    user = CurrentUser(user_id="alice", role="user", edition_authenticated=False)
    try:
        yield from _client_for(user)
    finally:
        if prev_users is None:
            api_config._FULL_CONFIG.pop("users", None)
        else:
            api_config._FULL_CONFIG["users"] = prev_users
        _clear_side_state()


@pytest.fixture()
def single_user_client():
    """Authenticated client on a single-user install (no ``users`` block)."""
    prev_users = api_config._FULL_CONFIG.pop("users", None)
    user = CurrentUser(user_id=None, role="admin", edition_authenticated=True)
    try:
        yield from _client_for(user)
    finally:
        if prev_users is not None:
            api_config._FULL_CONFIG["users"] = prev_users
        _clear_side_state()


def _clear_side_state():
    """Drop the rows the success-path tests leave in the SHARED session database.

    ``seed_photos_prefix`` tears photos down with a plain ``DELETE``, but its
    connection has sqlite3's default ``PRAGMA foreign_keys = 0``, so
    ``user_preferences``' ``ON DELETE CASCADE`` never fires and the preference
    rows outlive the photos they point at. The ``auto_retrain_pending:*``
    counters matter more than the orphans: that is the persisted value the
    arming logic reads, so leaving them behind makes a later suite's result
    depend on whether this file ran first.
    """
    conn = sqlite3.connect(DEFAULT_DB_PATH)
    try:
        conn.execute("DELETE FROM user_preferences WHERE photo_path LIKE '/mu-%'")
        conn.execute("DELETE FROM stats_cache WHERE key LIKE 'auto_retrain_pending:%'")
        conn.commit()
    finally:
        conn.close()


def _preferences_for(photo_path):
    conn = sqlite3.connect(DEFAULT_DB_PATH)
    try:
        return conn.execute(
            "SELECT user_id FROM user_preferences WHERE photo_path = ?", (photo_path,)
        ).fetchall()
    finally:
        conn.close()


@pytest.mark.parametrize("endpoint,extra", ENDPOINTS, ids=ENDPOINT_IDS)
def test_write_on_a_missing_photo_is_404_in_multi_user_mode(multi_user_client, endpoint, extra):
    resp = multi_user_client.post(endpoint, json=_body(extra, MISSING))

    assert resp.status_code == 404, (
        f"{endpoint} answered {resp.status_code}; a stale path must be a clean 404, "
        "not a foreign-key IntegrityError surfaced as 500"
    )
    assert resp.json()["detail"] == "Photo not found"
    assert _preferences_for(MISSING) == []


@pytest.mark.parametrize("endpoint,extra", ENDPOINTS, ids=ENDPOINT_IDS)
def test_write_on_a_missing_photo_is_404_in_single_user_mode(single_user_client, endpoint, extra):
    resp = single_user_client.post(endpoint, json=_body(extra, MISSING))

    assert resp.status_code == 404, (
        f"{endpoint} answered {resp.status_code}; an UPDATE that matched zero rows "
        "must not be reported as success"
    )
    assert resp.json()["detail"] == "Photo not found"


@pytest.mark.parametrize("endpoint,extra", ENDPOINTS, ids=ENDPOINT_IDS)
def test_write_on_another_tenants_photo_is_indistinguishable_from_missing(
    multi_user_client, seed_photos_prefix, endpoint, extra
):
    """The 404 must not become a cross-tenant existence oracle."""
    seed_photos_prefix(BOB_DIR + "/", [
        {"path": BOB_PHOTO, "filename": "secret.jpg", "aggregate": 9.0},
    ])

    existing = multi_user_client.post(endpoint, json=_body(extra, BOB_PHOTO))
    absent = multi_user_client.post(endpoint, json=_body(extra, BOB_MISSING))

    assert existing.status_code == absent.status_code == 404, (
        f"{endpoint} answered {existing.status_code} for another tenant's real photo "
        f"and {absent.status_code} for a nonexistent one — that difference is the oracle"
    )
    assert existing.json() == absent.json()
    assert _preferences_for(BOB_PHOTO) == [], (
        "a preference row was written for a photo the caller cannot see"
    )


@pytest.mark.parametrize("endpoint,extra", ENDPOINTS, ids=ENDPOINT_IDS)
def test_write_on_an_own_photo_still_succeeds_in_multi_user_mode(
    multi_user_client, seed_photos_prefix, endpoint, extra
):
    """The guard must not blanket-404 the caller's own library."""
    seed_photos_prefix(ALICE_DIR + "/", [
        {"path": ALICE_PHOTO, "filename": "own.jpg", "aggregate": 7.0},
    ])

    resp = multi_user_client.post(endpoint, json=_body(extra, ALICE_PHOTO))

    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is True
    assert _preferences_for(ALICE_PHOTO) == [("alice",)]


@pytest.mark.parametrize("endpoint,extra", ENDPOINTS, ids=ENDPOINT_IDS)
def test_write_on_an_own_photo_still_succeeds_in_single_user_mode(
    single_user_client, seed_photos_prefix, endpoint, extra
):
    seed_photos_prefix(ALICE_DIR + "/", [
        {"path": ALICE_PHOTO, "filename": "own.jpg", "aggregate": 7.0},
    ])

    resp = single_user_client.post(endpoint, json=_body(extra, ALICE_PHOTO))

    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is True
