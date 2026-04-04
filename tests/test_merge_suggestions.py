"""Tests for the merge suggestions API router (api/routers/merge_suggestions.py)."""

from contextlib import contextmanager
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from api import create_app
from api.auth import CurrentUser, require_authenticated


def _cm(conn):
    """Wrap a mock connection in a context manager compatible with get_db()."""
    @contextmanager
    def _ctx():
        yield conn
    return _ctx()


@pytest.fixture()
def client():
    app = create_app()
    app.dependency_overrides[require_authenticated] = lambda: CurrentUser(
        user_id="u1", role="admin"
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestGetMergeSuggestions:
    """GET /api/merge_suggestions — person merge suggestions."""

    def test_returns_suggestions(self, client):
        """When get_merge_groups returns groups, endpoint yields pairwise suggestions."""
        fake_groups = [
            {
                "persons": [
                    {"id": 1, "name": "Alice", "face_count": 10},
                    {"id": 2, "name": "Alice B", "face_count": 5},
                ],
                "avg_similarity": 0.85,
            }
        ]
        fake_faces = mock.MagicMock()
        fake_faces.get_merge_groups = mock.MagicMock(return_value=fake_groups)
        with mock.patch.dict("sys.modules", {"faces": fake_faces}):
            resp = client.get("/api/merge_suggestions")

        assert resp.status_code == 200
        body = resp.json()
        assert "suggestions" in body
        assert len(body["suggestions"]) == 1
        s = body["suggestions"][0]
        assert s["person1"]["id"] == 1
        assert s["person2"]["id"] == 2
        assert s["similarity"] == 0.85

    def test_empty_persons_returns_empty(self, client):
        """No merge groups yields an empty suggestions list."""
        fake_faces = mock.MagicMock()
        fake_faces.get_merge_groups = mock.MagicMock(return_value=[])
        with mock.patch.dict("sys.modules", {"faces": fake_faces}):
            resp = client.get("/api/merge_suggestions")

        assert resp.status_code == 200
        assert resp.json()["suggestions"] == []

    def test_requires_authentication(self):
        """Unauthenticated request returns 401."""
        app = create_app()
        # No auth override — default auth should reject
        with (
            mock.patch("api.auth.VIEWER_CONFIG", {"password": "secret", "edition_password": "", "features": {}}),
            mock.patch("api.auth.is_multi_user_enabled", return_value=False),
        ):
            unauthenticated_client = TestClient(app, raise_server_exceptions=False)
            resp = unauthenticated_client.get("/api/merge_suggestions")

        assert resp.status_code in (401, 403)
