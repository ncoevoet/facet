"""A toggle on a photo that no longer exists must 404, in both auth modes.

The single-user branch has always checked (``SELECT ... FROM photos`` then
``raise HTTPException(404)``). The multi-user branch went straight to an
``INSERT INTO user_preferences``, whose ``photo_path`` column is
``TEXT NOT NULL REFERENCES photos(path)`` with ``PRAGMA foreign_keys = ON``, so
a stale path raised ``IntegrityError`` and surfaced as a 500.

That is reachable from an ordinary client: the gallery holds a photo the user
favourites after a rescan has pruned the row.
"""

import pytest
from fastapi.testclient import TestClient
from unittest import mock

from api import create_app
from api.auth import CurrentUser, require_auth
from api.routers import faces

MISSING = "/no/such/photo-for-toggle.jpg"


@pytest.fixture()
def multi_user_client():
    """Authenticated client with multi-user mode on, so the user_preferences path runs."""
    app = create_app()
    user = CurrentUser(user_id="alice", role="user", edition_authenticated=False)
    app.dependency_overrides[require_auth] = lambda: user
    with mock.patch.object(faces, "is_multi_user_enabled", return_value=True):
        yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.mark.parametrize("endpoint", [
    "/api/photo/toggle_favorite",
    "/api/photo/toggle_rejected",
])
def test_toggle_on_a_missing_photo_is_404_in_multi_user_mode(multi_user_client, endpoint):
    resp = multi_user_client.post(endpoint, json={"photo_path": MISSING})

    assert resp.status_code == 404, (
        f"{endpoint} answered {resp.status_code}; a stale path must be a clean 404, "
        "not a foreign-key IntegrityError surfaced as 500"
    )
    assert resp.json()["detail"] == "Photo not found"
