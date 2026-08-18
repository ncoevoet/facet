"""The batch write endpoints must not write photos the caller cannot write.

The batch twin of ``tests/test_toggle_missing_photo.py``. All three endpoints
share one helper, ``faces._batch_update``, which had no visibility clause and no
existence check at all:

* multi-user: ``user_preferences.photo_path`` is
  ``TEXT NOT NULL REFERENCES photos(path)`` with ``PRAGMA foreign_keys = ON``,
  so one stale path in a batch of a thousand raised ``IntegrityError``, surfaced
  as a 500, and rolled back the 999 good ones.
* multi-user: nothing stopped an edition user writing ``user_preferences`` rows
  for another tenant's photos — the single-photo oracle, at batch scale.
* both modes: ``count`` was ``len(photo_paths)`` unconditionally, so a batch
  that wrote nothing still reported every path as written.

Unlike the single-photo guard this one drops rather than 404s — answering
per-path would rebuild the existence oracle the guard exists to close — so the
assertions below are about what landed in the database and what ``count`` says,
never about a status code.
"""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from api import config as api_config
from api import create_app
from api.auth import CurrentUser, require_edition
from db import DEFAULT_DB_PATH

ALICE_DIR = "/batch-alice"
BOB_DIR = "/batch-bob"
ALICE_ONE = ALICE_DIR + "/one.jpg"
ALICE_TWO = ALICE_DIR + "/two.jpg"
BOB_PHOTO = BOB_DIR + "/secret.jpg"
MISSING = "/batch-nowhere/gone.jpg"

SEEDED = [ALICE_ONE, ALICE_TWO, BOB_PHOTO]

# (endpoint, extra body keys beyond photo_paths)
ENDPOINTS = [
    ("/api/photos/batch_favorite", {}),
    ("/api/photos/batch_reject", {}),
    ("/api/photos/batch_rating", {"rating": 4}),
]
ENDPOINT_IDS = [path.rsplit("/", 1)[-1] for path, _ in ENDPOINTS]


@pytest.fixture()
def seeded(seed_photos_prefix):
    """Two photos under alice's directory and one under bob's."""
    seed_photos_prefix(
        "/batch-",
        [{"path": path, "filename": path.rsplit("/", 1)[-1]} for path in SEEDED],
    )
    yield
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.execute("DELETE FROM user_preferences WHERE photo_path LIKE '/batch-%'")


def _client_for(user):
    app = create_app()
    app.dependency_overrides[require_edition] = lambda: user
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def alice_client():
    """Edition client for alice, with multi-user mode genuinely on.

    ``users`` goes into the live config rather than onto one module, because the
    visibility clause resolves ``is_multi_user_enabled`` and
    ``get_user_directories`` through ``api.config``; patching only
    ``api.routers.faces`` would leave the clause inert and every assertion below
    would pass without exercising anything.
    """
    prev = api_config._FULL_CONFIG.get("users")
    api_config._FULL_CONFIG["users"] = {"alice": {"directories": [ALICE_DIR]}}
    try:
        yield from _client_for(CurrentUser(user_id="alice", role="user", edition_authenticated=True))
    finally:
        if prev is None:
            api_config._FULL_CONFIG.pop("users", None)
        else:
            api_config._FULL_CONFIG["users"] = prev


@pytest.fixture()
def single_user_client():
    """Edition client on a single-user install — no ``users`` block at all."""
    prev = api_config._FULL_CONFIG.get("users")
    api_config._FULL_CONFIG.pop("users", None)
    try:
        yield from _client_for(CurrentUser(user_id=None, role="admin", edition_authenticated=True))
    finally:
        if prev is not None:
            api_config._FULL_CONFIG["users"] = prev


def _written_prefs(paths):
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        placeholders = ",".join("?" * len(paths))
        rows = conn.execute(
            f"SELECT photo_path FROM user_preferences WHERE photo_path IN ({placeholders})",
            list(paths),
        ).fetchall()
    return {row[0] for row in rows}


@pytest.mark.parametrize(("endpoint", "extra"), ENDPOINTS, ids=ENDPOINT_IDS)
class TestMultiUser:
    def test_another_tenants_photo_is_never_written(self, alice_client, seeded, endpoint, extra):
        resp = alice_client.post(endpoint, json={"photo_paths": [BOB_PHOTO], **extra})
        assert resp.status_code == 200, resp.text
        assert resp.json()["count"] == 0, (
            f"{endpoint} reported writing another tenant's photo: {resp.json()}"
        )
        assert _written_prefs([BOB_PHOTO]) == set(), (
            f"{endpoint} created a user_preferences row for a photo alice cannot see"
        )

    def test_a_stale_path_does_not_500_the_whole_batch(self, alice_client, seeded, endpoint, extra):
        resp = alice_client.post(endpoint, json={"photo_paths": [ALICE_ONE, MISSING], **extra})
        assert resp.status_code == 200, (
            f"{endpoint} lost the whole batch to one stale path: {resp.status_code} {resp.text}"
        )
        assert resp.json()["count"] == 1, resp.json()
        assert _written_prefs([ALICE_ONE, MISSING]) == {ALICE_ONE}

    def test_a_mixed_batch_writes_only_the_callers_own_photos(self, alice_client, seeded, endpoint, extra):
        paths = [ALICE_ONE, BOB_PHOTO, ALICE_TWO, MISSING]
        resp = alice_client.post(endpoint, json={"photo_paths": paths, **extra})
        assert resp.status_code == 200, resp.text
        assert resp.json()["count"] == 2, resp.json()
        assert _written_prefs(paths) == {ALICE_ONE, ALICE_TWO}

    def test_the_callers_own_photos_are_still_written(self, alice_client, seeded, endpoint, extra):
        """Positive control: the guard must not simply refuse everything."""
        resp = alice_client.post(endpoint, json={"photo_paths": [ALICE_ONE, ALICE_TWO], **extra})
        assert resp.status_code == 200, resp.text
        assert resp.json()["count"] == 2, resp.json()
        assert _written_prefs([ALICE_ONE, ALICE_TWO]) == {ALICE_ONE, ALICE_TWO}

    def test_duplicate_paths_are_counted_once(self, alice_client, seeded, endpoint, extra):
        resp = alice_client.post(endpoint, json={"photo_paths": [ALICE_ONE, ALICE_ONE], **extra})
        assert resp.status_code == 200, resp.text
        assert resp.json()["count"] == 1, resp.json()


@pytest.mark.parametrize(("endpoint", "extra"), ENDPOINTS, ids=ENDPOINT_IDS)
class TestSingleUser:
    def test_a_missing_path_is_not_reported_as_written(self, single_user_client, seeded, endpoint, extra):
        """``UPDATE ... WHERE path IN (...)`` matches nothing, so count must be 0."""
        resp = single_user_client.post(endpoint, json={"photo_paths": [MISSING], **extra})
        assert resp.status_code == 200, resp.text
        assert resp.json()["count"] == 0, (
            f"{endpoint} reported writing a photo that does not exist: {resp.json()}"
        )

    def test_present_photos_are_still_written(self, single_user_client, seeded, endpoint, extra):
        """Positive control, and the whole library is visible here — bob's too."""
        paths = [ALICE_ONE, BOB_PHOTO, MISSING]
        resp = single_user_client.post(endpoint, json={"photo_paths": paths, **extra})
        assert resp.status_code == 200, resp.text
        assert resp.json()["count"] == 2, resp.json()
