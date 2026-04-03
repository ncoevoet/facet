"""Tests for the semantic search endpoint (api/routers/search.py)."""

from contextlib import contextmanager
from unittest import mock

import numpy as np
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


class TestSearch:
    """Tests for GET /api/search."""

    def test_search_disabled(self, client):
        """When show_semantic_search is False, returns error message."""
        disabled_config = {
            "features": {"show_semantic_search": False},
            "display": {"tags_per_photo": 3},
        }
        with mock.patch.dict("api.routers.search.VIEWER_CONFIG", disabled_config):
            resp = client.get("/api/search", params={"q": "sunset"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["photos"] == []
        assert body["total"] == 0
        assert "error" in body
        assert "disabled" in body["error"].lower()

    def test_no_embeddings(self, client):
        """When _load_embedding_matrix returns (None, []), returns empty photos."""
        mock_conn = mock.MagicMock()

        with (
            mock.patch("api.routers.search.VIEWER_CONFIG", {
                "features": {"show_semantic_search": True},
                "display": {"tags_per_photo": 3},
            }),
            mock.patch("api.routers.search.get_db", lambda: _cm(mock_conn)),
            mock.patch("api.routers.search.get_visibility_clause", return_value=("1=1", [])),
            mock.patch("api.routers.search.get_existing_columns", return_value={"path", "aggregate"}),
            mock.patch("api.routers.search.get_photos_from_clause", return_value=("photos", [])),
            mock.patch("api.routers.search.get_preference_columns", return_value={}),
            mock.patch("api.routers.search._load_embedding_matrix", return_value=(None, [])),
        ):
            resp = client.get("/api/search", params={"q": "mountains"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["photos"] == []
        assert body["total"] == 0


    def test_successful_search(self, client):
        """Mock matrix with 3 embeddings, text_emb that matches 2 above threshold."""
        # 3 photo embeddings (4-dim for simplicity)
        matrix = np.array([
            [1.0, 0.0, 0.0, 0.0],   # photo a
            [0.0, 1.0, 0.0, 0.0],   # photo b
            [0.9, 0.1, 0.0, 0.0],   # photo c - similar to a
        ], dtype=np.float32)
        paths = ["/photos/a.jpg", "/photos/b.jpg", "/photos/c.jpg"]

        # text_emb aligned with photo a and c (cosine sim > 0.15 threshold)
        text_emb = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)

        mock_conn = mock.MagicMock()
        # DB returns photo rows for matching paths
        mock_conn.execute.return_value.fetchall.return_value = [
            {"path": "/photos/a.jpg", "filename": "a.jpg", "tags": "sunset,sky",
             "date_taken": "2024:06:15 18:30:00", "aggregate": 8.5},
            {"path": "/photos/c.jpg", "filename": "c.jpg", "tags": "dawn",
             "date_taken": "2024:07:01 06:00:00", "aggregate": 7.2},
        ]

        with (
            mock.patch("api.routers.search.VIEWER_CONFIG", {
                "features": {"show_semantic_search": True},
                "display": {"tags_per_photo": 3},
            }),
            mock.patch("api.routers.search.get_db", lambda: _cm(mock_conn)),
            mock.patch("api.routers.search.get_visibility_clause", return_value=("1=1", [])),
            mock.patch("api.routers.search.get_existing_columns", return_value={"path", "aggregate"}),
            mock.patch("api.routers.search.get_photos_from_clause", return_value=("photos", [])),
            mock.patch("api.routers.search.get_preference_columns", return_value={}),
            mock.patch("api.routers.search._load_embedding_matrix", return_value=(matrix, paths)),
            mock.patch("api.routers.search._encode_text", return_value=text_emb),
            mock.patch("api.routers.search._has_fts", return_value=False),
            mock.patch("api.routers.search._check_vec_available", return_value=False),
            mock.patch("api.routers.search.attach_person_data"),
            mock.patch("api.routers.search.sanitize_float_values"),
        ):
            resp = client.get("/api/search", params={"q": "sunset", "threshold": 0.15})

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert len(body["photos"]) == 2
        # Photos should have similarity scores
        for photo in body["photos"]:
            assert "similarity" in photo
            assert photo["similarity"] > 0
        # Sorted by similarity descending: a (1.0) before c (0.9)
        assert body["photos"][0]["path"] == "/photos/a.jpg"
        assert body["photos"][1]["path"] == "/photos/c.jpg"


    def test_dimension_mismatch(self, client):
        """When text_emb dimension != matrix columns, returns empty."""
        # Matrix is 3x4 but text_emb will be 5-dim
        matrix = np.array([
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.5, 0.5, 0.0, 0.0],
        ], dtype=np.float32)
        paths = ["/photos/a.jpg", "/photos/b.jpg", "/photos/c.jpg"]

        text_emb = np.array([1.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float32)  # wrong dim

        mock_conn = mock.MagicMock()

        with (
            mock.patch("api.routers.search.VIEWER_CONFIG", {
                "features": {"show_semantic_search": True},
                "display": {"tags_per_photo": 3},
            }),
            mock.patch("api.routers.search.get_db", lambda: _cm(mock_conn)),
            mock.patch("api.routers.search.get_visibility_clause", return_value=("1=1", [])),
            mock.patch("api.routers.search.get_existing_columns", return_value={"path", "aggregate"}),
            mock.patch("api.routers.search.get_photos_from_clause", return_value=("photos", [])),
            mock.patch("api.routers.search.get_preference_columns", return_value={}),
            mock.patch("api.routers.search._load_embedding_matrix", return_value=(matrix, paths)),
            mock.patch("api.routers.search._encode_text", return_value=text_emb),
        ):
            resp = client.get("/api/search", params={"q": "sunset"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["photos"] == []
        assert body["total"] == 0


    def test_no_results_above_threshold(self, client):
        """When all similarities are below threshold, returns empty."""
        # Orthogonal vectors: cosine similarity = 0
        matrix = np.array([
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
        ], dtype=np.float32)
        paths = ["/photos/a.jpg", "/photos/b.jpg"]

        text_emb = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)

        mock_conn = mock.MagicMock()

        with (
            mock.patch("api.routers.search.VIEWER_CONFIG", {
                "features": {"show_semantic_search": True},
                "display": {"tags_per_photo": 3},
            }),
            mock.patch("api.routers.search.get_db", lambda: _cm(mock_conn)),
            mock.patch("api.routers.search.get_visibility_clause", return_value=("1=1", [])),
            mock.patch("api.routers.search.get_existing_columns", return_value={"path", "aggregate"}),
            mock.patch("api.routers.search.get_photos_from_clause", return_value=("photos", [])),
            mock.patch("api.routers.search.get_preference_columns", return_value={}),
            mock.patch("api.routers.search._load_embedding_matrix", return_value=(matrix, paths)),
            mock.patch("api.routers.search._encode_text", return_value=text_emb),
        ):
            resp = client.get("/api/search", params={"q": "sunset", "threshold": 0.15})

        assert resp.status_code == 200
        body = resp.json()
        assert body["photos"] == []
        assert body["total"] == 0


    def test_search_error_returns_safe(self, client):
        """When _encode_text raises, returns error dict not 500."""
        matrix = np.array([[1.0, 0.0]], dtype=np.float32)
        paths = ["/photos/a.jpg"]

        mock_conn = mock.MagicMock()

        with (
            mock.patch("api.routers.search.VIEWER_CONFIG", {
                "features": {"show_semantic_search": True},
                "display": {"tags_per_photo": 3},
            }),
            mock.patch("api.routers.search.get_db", lambda: _cm(mock_conn)),
            mock.patch("api.routers.search.get_visibility_clause", return_value=("1=1", [])),
            mock.patch("api.routers.search.get_existing_columns", return_value={"path", "aggregate"}),
            mock.patch("api.routers.search.get_photos_from_clause", return_value=("photos", [])),
            mock.patch("api.routers.search.get_preference_columns", return_value={}),
            mock.patch("api.routers.search._load_embedding_matrix", return_value=(matrix, paths)),
            mock.patch("api.routers.search._encode_text", side_effect=RuntimeError("GPU OOM")),
        ):
            resp = client.get("/api/search", params={"q": "sunset"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["photos"] == []
        assert "error" in body


    def test_query_validation(self, client):
        """Empty query returns 422 validation error."""
        resp = client.get("/api/search", params={"q": ""})
        assert resp.status_code == 422
