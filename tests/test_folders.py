"""Tests for the folders endpoint (api/routers/folders.py)."""

from contextlib import nullcontext
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from api import create_app


@pytest.fixture()
def client():
    app = create_app()
    return TestClient(app)


def _patch_folders():
    return (
        mock.patch("api.routers.folders.get_db"),
        mock.patch("api.routers.folders.get_visibility_clause", return_value=("1=1", [])),
        mock.patch("api.routers.folders.get_photos_from_clause", return_value=("photos", [])),
        mock.patch("api.routers.folders.build_hide_clauses", return_value=[]),
    )


class TestFolders:

    def test_empty_library(self, client):
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []

        p_conn, p_vis, p_from, p_hide = _patch_folders()
        with p_conn as mock_get_conn, p_vis, p_from, p_hide:
            mock_get_conn.return_value = nullcontext(mock_conn)
            resp = client.get("/api/folders")

        assert resp.status_code == 200
        body = resp.json()
        assert body["folders"] == []
        assert body["has_direct_photos"] is False


    def test_root_level_folders(self, client):
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            {"path": "/photos/2024/a.jpg", "aggregate": 7.0},
            {"path": "/photos/2025/b.jpg", "aggregate": 8.0},
        ]

        p_conn, p_vis, p_from, p_hide = _patch_folders()
        with p_conn as mock_get_conn, p_vis, p_from, p_hide:
            mock_get_conn.return_value = nullcontext(mock_conn)
            resp = client.get("/api/folders", params={"prefix": "/photos/"})

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["folders"]) == 2
        names = [f["name"] for f in body["folders"]]
        assert "2024" in names
        assert "2025" in names


    def test_with_prefix(self, client):
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            {"path": "/photos/2024/jan/a.jpg", "aggregate": 6.0},
            {"path": "/photos/2024/feb/b.jpg", "aggregate": 9.0},
        ]

        p_conn, p_vis, p_from, p_hide = _patch_folders()
        with p_conn as mock_get_conn, p_vis, p_from, p_hide:
            mock_get_conn.return_value = nullcontext(mock_conn)
            resp = client.get("/api/folders", params={"prefix": "/photos/2024/"})

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["folders"]) == 2
        names = [f["name"] for f in body["folders"]]
        assert "jan" in names
        assert "feb" in names
        for f in body["folders"]:
            assert f["path"].startswith("/photos/2024/")


    def test_has_direct_photos(self, client):
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            {"path": "/photos/2024/a.jpg", "aggregate": 5.0},
            {"path": "/photos/2024/sub/b.jpg", "aggregate": 6.0},
        ]

        p_conn, p_vis, p_from, p_hide = _patch_folders()
        with p_conn as mock_get_conn, p_vis, p_from, p_hide:
            mock_get_conn.return_value = nullcontext(mock_conn)
            resp = client.get("/api/folders", params={"prefix": "/photos/2024/"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["has_direct_photos"] is True


    def test_cover_photo_highest_score(self, client):
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            {"path": "/photos/2024/low.jpg", "aggregate": 3.0},
            {"path": "/photos/2024/high.jpg", "aggregate": 9.5},
            {"path": "/photos/2024/mid.jpg", "aggregate": 6.0},
        ]

        p_conn, p_vis, p_from, p_hide = _patch_folders()
        with p_conn as mock_get_conn, p_vis, p_from, p_hide:
            mock_get_conn.return_value = nullcontext(mock_conn)
            resp = client.get("/api/folders", params={"prefix": "/photos/"})

        assert resp.status_code == 200
        body = resp.json()
        folder = body["folders"][0]
        assert folder["name"] == "2024"
        assert folder["cover_photo_path"] == "/photos/2024/high.jpg"


    def test_like_wildcard_escaping(self, client):
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []

        p_conn, p_vis, p_from, p_hide = _patch_folders()
        with p_conn as mock_get_conn, p_vis, p_from, p_hide:
            mock_get_conn.return_value = nullcontext(mock_conn)
            resp = client.get("/api/folders", params={"prefix": "/photos/100%_done/"})

        assert resp.status_code == 200
        call_args = mock_conn.execute.call_args
        sql = call_args[0][0]
        params = call_args[0][1]
        assert "ESCAPE" in sql
        matching_params = [p for p in params if isinstance(p, str) and "\\%" in p]
        assert len(matching_params) > 0


    def test_db_error_returns_empty(self):
        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)
        mock_conn = mock.MagicMock()
        mock_conn.execute.side_effect = RuntimeError("db failure")

        p_conn, p_vis, p_from, p_hide = _patch_folders()
        with p_conn as mock_get_conn, p_vis, p_from, p_hide:
            mock_get_conn.return_value = nullcontext(mock_conn)
            resp = client.get("/api/folders")

        assert resp.status_code == 200
        body = resp.json()
        assert body["folders"] == []
        assert body["has_direct_photos"] is False


    def test_backslash_normalization(self, client):
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            {"path": "\\\\server\\share\\dir\\sub\\file.jpg", "aggregate": 7.0},
        ]

        p_conn, p_vis, p_from, p_hide = _patch_folders()
        with p_conn as mock_get_conn, p_vis, p_from, p_hide:
            mock_get_conn.return_value = nullcontext(mock_conn)
            resp = client.get("/api/folders")

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["folders"]) > 0
        for f in body["folders"]:
            assert "\\" not in f["path"]

