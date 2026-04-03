"""Tests for the caption generation endpoint (api/routers/caption.py)."""

from contextlib import contextmanager
from unittest import mock

import pytest


def _cm(conn):
    @contextmanager
    def _ctx():
        yield conn
    return _ctx()
from fastapi.testclient import TestClient

from api import create_app


@pytest.fixture()
def client():
    app = create_app()
    return TestClient(app)


class TestCaptionEndpoint:
    """Tests for GET /api/caption."""

    def test_missing_path_returns_422(self, client):
        """Query parameter 'path' is required."""
        with mock.patch("api.routers.caption.VIEWER_CONFIG", {"features": {"show_captions": True}}):
            resp = client.get("/api/caption")
        assert resp.status_code == 422

    def test_feature_disabled_returns_403(self, client):
        """Returns 403 when show_captions is False."""
        with mock.patch("api.routers.caption.VIEWER_CONFIG", {"features": {"show_captions": False}}):
            resp = client.get("/api/caption", params={"path": "/photos/test.jpg"})
        assert resp.status_code == 403
        assert "disabled" in resp.json()["detail"].lower()

    def test_photo_not_found_returns_404(self, client):
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None

        with (
            mock.patch("api.routers.caption.VIEWER_CONFIG", {"features": {"show_captions": True}}),
            mock.patch("api.routers.caption.get_db", lambda: _cm(mock_conn)),
            mock.patch("api.routers.caption.get_visibility_clause", return_value=("1=1", [])),
        ):
            resp = client.get("/api/caption", params={"path": "/photos/missing.jpg"})

        assert resp.status_code == 404


    def test_returns_cached_caption(self, client):
        """When the DB already has a caption, return it with source='cached'."""
        mock_conn = mock.MagicMock()
        # First execute: photo exists check
        # Second execute: SELECT caption
        mock_conn.execute.return_value.fetchone.side_effect = [
            {"path": "/photos/test.jpg"},  # photo exists
            {"caption": "A beautiful sunset over the ocean"},  # cached caption
        ]

        with (
            mock.patch("api.routers.caption.VIEWER_CONFIG", {"features": {"show_captions": True}}),
            mock.patch("api.routers.caption.get_db", lambda: _cm(mock_conn)),
            mock.patch("api.routers.caption.get_visibility_clause", return_value=("1=1", [])),
            mock.patch("api.routers.caption.get_existing_columns", return_value={"caption", "path"}),
        ):
            resp = client.get("/api/caption", params={"path": "/photos/test.jpg"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["caption"] == "A beautiful sunset over the ocean"
        assert body["source"] == "cached"


    def test_vlm_unavailable_returns_503(self, client):
        """When no cached caption and VLM is unavailable, return 503."""
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchone.side_effect = [
            {"path": "/photos/test.jpg"},  # photo exists
            {"caption": None},  # no cached caption
        ]

        with (
            mock.patch("api.routers.caption.VIEWER_CONFIG", {"features": {"show_captions": True}}),
            mock.patch("api.routers.caption.get_db", lambda: _cm(mock_conn)),
            mock.patch("api.routers.caption.get_visibility_clause", return_value=("1=1", [])),
            mock.patch("api.routers.caption.get_existing_columns", return_value={"caption", "path"}),
            mock.patch("api.routers.caption._generate_caption", return_value=None),
        ):
            resp = client.get("/api/caption", params={"path": "/photos/test.jpg"})

        assert resp.status_code == 503
        assert "unavailable" in resp.json()["detail"].lower()


    def test_generates_and_stores_caption(self, client):
        """When no cached caption, generate via VLM and store it."""
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchone.side_effect = [
            {"path": "/photos/test.jpg"},  # photo exists
            {"caption": None},  # no cached caption
        ]

        with (
            mock.patch("api.routers.caption.VIEWER_CONFIG", {"features": {"show_captions": True}}),
            mock.patch("api.routers.caption.get_db", lambda: _cm(mock_conn)),
            mock.patch("api.routers.caption.get_visibility_clause", return_value=("1=1", [])),
            mock.patch("api.routers.caption.get_existing_columns", return_value={"caption", "path"}),
            mock.patch("api.routers.caption._generate_caption", return_value="A golden retriever playing in a park"),
        ):
            resp = client.get("/api/caption", params={"path": "/photos/test.jpg"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["caption"] == "A golden retriever playing in a park"
        assert body["source"] == "generated"
        # Verify it attempted to store the caption
        mock_conn.commit.assert_called_once()


    def test_no_caption_column_skips_cache(self, client):
        """When caption column doesn't exist, skip cache lookup and storage."""
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = {"path": "/photos/test.jpg"}

        with (
            mock.patch("api.routers.caption.VIEWER_CONFIG", {"features": {"show_captions": True}}),
            mock.patch("api.routers.caption.get_db", lambda: _cm(mock_conn)),
            mock.patch("api.routers.caption.get_visibility_clause", return_value=("1=1", [])),
            mock.patch("api.routers.caption.get_existing_columns", return_value={"path", "aggregate"}),
            mock.patch("api.routers.caption._generate_caption", return_value="Generated caption"),
        ):
            resp = client.get("/api/caption", params={"path": "/photos/test.jpg"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["source"] == "generated"
        # Should NOT call commit since column doesn't exist
        mock_conn.commit.assert_not_called()


class TestGenerateCaption:
    """Tests for the _generate_caption helper."""

    def test_returns_none_for_legacy_profile(self):
        from api.routers.caption import _generate_caption

        with mock.patch("api.routers.caption._FULL_CONFIG", {"models": {"vram_profile": "legacy"}}):
            result = _generate_caption("/photos/test.jpg")
        assert result is None

    def test_returns_none_for_8gb_profile(self):
        from api.routers.caption import _generate_caption

        with mock.patch("api.routers.caption._FULL_CONFIG", {"models": {"vram_profile": "8gb"}}):
            result = _generate_caption("/photos/test.jpg")
        assert result is None

    def test_returns_none_when_no_model_name(self):
        from api.routers.caption import _generate_caption

        with mock.patch("api.routers.caption._FULL_CONFIG", {
            "models": {"vram_profile": "16gb", "vlm_tagger": {"model_name": ""}}
        }):
            result = _generate_caption("/photos/test.jpg")
        assert result is None

    def test_returns_none_on_exception(self):
        from api.routers.caption import _generate_caption

        with mock.patch("api.routers.caption._FULL_CONFIG", {
            "models": {"vram_profile": "16gb", "vlm_tagger": {"model_name": "test-model"}}
        }), mock.patch("api.routers.caption.get_or_load_vlm_tagger", side_effect=RuntimeError("GPU OOM")):
            result = _generate_caption("/photos/test.jpg")
        assert result is None
