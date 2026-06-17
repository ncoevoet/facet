"""Tests for the folders endpoint (api/routers/folders.py).

GET /api/folders is async (Topic 2 step 7), so these tests patch
get_async_db with a real aiosqlite-backed temp DB rather than a MagicMock
(a MagicMock is not awaitable).
"""

import sqlite3
from contextlib import asynccontextmanager
from unittest import mock

import aiosqlite
import pytest
from fastapi.testclient import TestClient

from api import create_app


_FOLDERS_SCHEMA = """
    CREATE TABLE photos (
        path TEXT PRIMARY KEY,
        aggregate REAL,
        is_blink INTEGER DEFAULT 0,
        is_burst_lead INTEGER DEFAULT 1,
        is_duplicate_lead INTEGER DEFAULT 1,
        is_rejected INTEGER DEFAULT 0
    );
"""


def _make_db(path, photos):
    conn = sqlite3.connect(path)
    conn.executescript(_FOLDERS_SCHEMA)
    for p in photos:
        cols = list(p.keys())
        placeholders = ", ".join("?" for _ in cols)
        conn.execute(
            f"INSERT INTO photos ({', '.join(cols)}) VALUES ({placeholders})",
            [p[c] for c in cols],
        )
    conn.commit()
    conn.close()


def _async_conn_factory(db_path):
    @asynccontextmanager
    async def factory():
        c = await aiosqlite.connect(db_path)
        c.row_factory = aiosqlite.Row
        try:
            yield c
        finally:
            await c.close()
    return factory


def _fake_vis(user_id, table_alias=None):
    return ("1=1", [])


@pytest.fixture()
def client():
    app = create_app()
    return TestClient(app)


def _patch_folders(db):
    """Patch the folders router dependencies to use a real temp DB."""
    return (
        mock.patch("api.routers.folders.get_async_db", _async_conn_factory(db)),
        mock.patch("api.routers.folders.get_visibility_clause", _fake_vis),
        mock.patch("api.routers.folders.get_photos_from_clause", return_value=("photos", [])),
        mock.patch("api.routers.folders.build_hide_clauses", return_value=[]),
    )


class TestFolders:

    def test_empty_library(self, client, tmp_path):
        db = str(tmp_path / "folders.db")
        _make_db(db, [])

        p_conn, p_vis, p_from, p_hide = _patch_folders(db)
        with p_conn, p_vis, p_from, p_hide:
            resp = client.get("/api/folders")

        assert resp.status_code == 200
        body = resp.json()
        assert body["folders"] == []
        assert body["has_direct_photos"] is False

    def test_root_level_folders(self, client, tmp_path):
        db = str(tmp_path / "folders.db")
        _make_db(db, [
            {"path": "/photos/2024/a.jpg", "aggregate": 7.0},
            {"path": "/photos/2025/b.jpg", "aggregate": 8.0},
        ])

        p_conn, p_vis, p_from, p_hide = _patch_folders(db)
        with p_conn, p_vis, p_from, p_hide:
            resp = client.get("/api/folders", params={"prefix": "/photos/"})

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["folders"]) == 2
        names = [f["name"] for f in body["folders"]]
        assert "2024" in names
        assert "2025" in names

    def test_with_prefix(self, client, tmp_path):
        db = str(tmp_path / "folders.db")
        _make_db(db, [
            {"path": "/photos/2024/jan/a.jpg", "aggregate": 6.0},
            {"path": "/photos/2024/feb/b.jpg", "aggregate": 9.0},
        ])

        p_conn, p_vis, p_from, p_hide = _patch_folders(db)
        with p_conn, p_vis, p_from, p_hide:
            resp = client.get("/api/folders", params={"prefix": "/photos/2024/"})

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["folders"]) == 2
        names = [f["name"] for f in body["folders"]]
        assert "jan" in names
        assert "feb" in names
        for f in body["folders"]:
            assert f["path"].startswith("/photos/2024/")

    def test_has_direct_photos(self, client, tmp_path):
        db = str(tmp_path / "folders.db")
        _make_db(db, [
            {"path": "/photos/2024/a.jpg", "aggregate": 5.0},
            {"path": "/photos/2024/sub/b.jpg", "aggregate": 6.0},
        ])

        p_conn, p_vis, p_from, p_hide = _patch_folders(db)
        with p_conn, p_vis, p_from, p_hide:
            resp = client.get("/api/folders", params={"prefix": "/photos/2024/"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["has_direct_photos"] is True

    def test_cover_photo_highest_score(self, client, tmp_path):
        db = str(tmp_path / "folders.db")
        _make_db(db, [
            {"path": "/photos/2024/low.jpg", "aggregate": 3.0},
            {"path": "/photos/2024/high.jpg", "aggregate": 9.5},
            {"path": "/photos/2024/mid.jpg", "aggregate": 6.0},
        ])

        p_conn, p_vis, p_from, p_hide = _patch_folders(db)
        with p_conn, p_vis, p_from, p_hide:
            resp = client.get("/api/folders", params={"prefix": "/photos/"})

        assert resp.status_code == 200
        body = resp.json()
        folder = body["folders"][0]
        assert folder["name"] == "2024"
        assert folder["cover_photo_path"] == "/photos/2024/high.jpg"

    def test_like_wildcard_escaping(self, client, tmp_path):
        """A prefix containing % and _ must be escaped and produce no spurious matches."""
        db = str(tmp_path / "folders.db")
        # A photo whose dir literally is "100%_done" should match; an unrelated
        # path that would match an unescaped LIKE wildcard must not.
        _make_db(db, [
            {"path": "/photos/100%_done/a.jpg", "aggregate": 7.0},
            {"path": "/photos/1009Xdone/other.jpg", "aggregate": 8.0},
        ])

        p_conn, p_vis, p_from, p_hide = _patch_folders(db)
        with p_conn, p_vis, p_from, p_hide:
            resp = client.get("/api/folders", params={"prefix": "/photos/100%_done/"})

        assert resp.status_code == 200
        body = resp.json()
        # The escaped LIKE must only match the literal "100%_done" prefix,
        # so the unrelated "1009Xdone" photo is excluded (has_direct_photos True,
        # no spurious subfolders).
        assert body["has_direct_photos"] is True
        assert body["folders"] == []

    def test_db_error_returns_empty(self, tmp_path):
        """A DB failure inside the handler returns an empty payload (200)."""
        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)

        # Point at a non-existent table so the query raises inside the try block.
        db = str(tmp_path / "folders.db")
        conn = sqlite3.connect(db)
        conn.executescript("CREATE TABLE unrelated (x INTEGER);")
        conn.close()

        p_conn, p_vis, p_from, p_hide = _patch_folders(db)
        with p_conn, p_vis, p_from, p_hide:
            resp = client.get("/api/folders")

        assert resp.status_code == 200
        body = resp.json()
        assert body["folders"] == []
        assert body["has_direct_photos"] is False

    def test_backslash_normalization(self, client, tmp_path):
        db = str(tmp_path / "folders.db")
        _make_db(db, [
            {"path": "\\\\server\\share\\dir\\sub\\file.jpg", "aggregate": 7.0},
        ])

        p_conn, p_vis, p_from, p_hide = _patch_folders(db)
        with p_conn, p_vis, p_from, p_hide:
            resp = client.get("/api/folders")

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["folders"]) > 0
        for f in body["folders"]:
            assert "\\" not in f["path"]
