"""Tests for the health and readiness check endpoints (api/routers/health.py)."""

from unittest import mock

import pytest
from fastapi.testclient import TestClient

from api import create_app


@pytest.fixture()
def client():
    app = create_app()
    return TestClient(app)


class TestHealthEndpoint:
    def test_liveness_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestReadyEndpoint:
    def test_ready_when_database_accessible(self, client):
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value = None

        with mock.patch("api.routers.health.get_db_connection", return_value=mock_conn):
            resp = client.get("/ready")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ready"
        assert body["checks"]["database"] == "ok"
        mock_conn.close.assert_called_once()

    def test_not_ready_when_database_unavailable(self, client):
        with mock.patch(
            "api.routers.health.get_db_connection",
            side_effect=Exception("connection refused"),
        ):
            resp = client.get("/ready")

        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "not_ready"
        assert body["checks"]["database"] == "unavailable"

    def test_not_ready_when_query_fails(self, client):
        mock_conn = mock.MagicMock()
        mock_conn.execute.side_effect = Exception("disk I/O error")

        with mock.patch("api.routers.health.get_db_connection", return_value=mock_conn):
            resp = client.get("/ready")

        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "not_ready"
        assert body["checks"]["database"] == "unavailable"
        mock_conn.close.assert_called_once()
