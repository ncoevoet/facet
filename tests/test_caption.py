"""Tests for the caption generation endpoint (api/routers/caption.py).

GET /api/caption is async (Topic 2 step 7), so endpoint-level tests patch
get_async_db with a real aiosqlite-backed temp DB rather than a MagicMock
(a MagicMock is not awaitable). The VLM/translation calls (_generate_caption,
_translate_caption) are blocking inference (wrapped in asyncio.to_thread by the
handler); they are patched with plain stubs. The PUT endpoint stays sync.
"""

import sqlite3
from contextlib import asynccontextmanager
from unittest import mock

import aiosqlite
import pytest
from fastapi.testclient import TestClient

from api import create_app


_CAPTION_SCHEMA = """
    CREATE TABLE photos (
        path TEXT PRIMARY KEY,
        caption TEXT,
        caption_translated TEXT,
        is_rejected INTEGER DEFAULT 0
    );
"""


def _make_db(path, photos):
    conn = sqlite3.connect(path)
    conn.executescript(_CAPTION_SCHEMA)
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


def _read_caption(db_path, path):
    """Helper: read the stored caption for a path from the temp DB."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT caption FROM photos WHERE path = ?", [path]).fetchone()
    conn.close()
    return row["caption"] if row else None


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

    def test_photo_not_found_returns_404(self, client, tmp_path):
        db = str(tmp_path / "caption.db")
        _make_db(db, [])  # empty -> path not found

        with (
            mock.patch("api.routers.caption.VIEWER_CONFIG", {"features": {"show_captions": True}}),
            mock.patch("api.routers.caption.get_async_db", _async_conn_factory(db)),
            mock.patch("api.routers.caption.get_visibility_clause", _fake_vis),
        ):
            resp = client.get("/api/caption", params={"path": "/photos/missing.jpg"})

        assert resp.status_code == 404


    def test_returns_cached_caption(self, client, tmp_path):
        """When the DB already has a caption, return it with source='cached'."""
        db = str(tmp_path / "caption.db")
        _make_db(db, [
            {"path": "/photos/test.jpg", "caption": "A beautiful sunset over the ocean"},
        ])

        with (
            mock.patch("api.routers.caption.VIEWER_CONFIG", {"features": {"show_captions": True}}),
            mock.patch("api.routers.caption.get_async_db", _async_conn_factory(db)),
            mock.patch("api.routers.caption.get_visibility_clause", _fake_vis),
            mock.patch("api.routers.caption.get_existing_columns", return_value={"caption", "path"}),
        ):
            resp = client.get("/api/caption", params={"path": "/photos/test.jpg"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["caption"] == "A beautiful sunset over the ocean"
        assert body["source"] == "cached"


    def test_vlm_unavailable_returns_503(self, client, tmp_path):
        """When no cached caption and VLM is unavailable, return 503."""
        db = str(tmp_path / "caption.db")
        _make_db(db, [{"path": "/photos/test.jpg", "caption": None}])

        with (
            mock.patch("api.routers.caption.VIEWER_CONFIG", {"features": {"show_captions": True}}),
            mock.patch("api.routers.caption.get_async_db", _async_conn_factory(db)),
            mock.patch("api.routers.caption.get_visibility_clause", _fake_vis),
            mock.patch("api.routers.caption.get_existing_columns", return_value={"caption", "path"}),
            mock.patch("api.routers.caption._generate_caption", return_value=None),
        ):
            resp = client.get("/api/caption", params={"path": "/photos/test.jpg"})

        assert resp.status_code == 503
        assert "unavailable" in resp.json()["detail"].lower()


    def test_generates_and_stores_caption(self, client, tmp_path):
        """When no cached caption, generate via VLM and store it."""
        db = str(tmp_path / "caption.db")
        _make_db(db, [{"path": "/photos/test.jpg", "caption": None}])

        with (
            mock.patch("api.routers.caption.VIEWER_CONFIG", {"features": {"show_captions": True}}),
            mock.patch("api.routers.caption.get_async_db", _async_conn_factory(db)),
            mock.patch("api.routers.caption.get_visibility_clause", _fake_vis),
            mock.patch("api.routers.caption.get_existing_columns", return_value={"caption", "path"}),
            mock.patch("api.routers.caption._generate_caption", return_value="A golden retriever playing in a park"),
        ):
            resp = client.get("/api/caption", params={"path": "/photos/test.jpg"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["caption"] == "A golden retriever playing in a park"
        assert body["source"] == "generated"
        # Verify it persisted the generated caption to the DB.
        assert _read_caption(db, "/photos/test.jpg") == "A golden retriever playing in a park"


    def test_no_caption_column_skips_cache(self, client, tmp_path):
        """When caption column doesn't exist, skip cache lookup and storage."""
        db = str(tmp_path / "caption.db")
        _make_db(db, [{"path": "/photos/test.jpg", "caption": None}])

        with (
            mock.patch("api.routers.caption.VIEWER_CONFIG", {"features": {"show_captions": True}}),
            mock.patch("api.routers.caption.get_async_db", _async_conn_factory(db)),
            mock.patch("api.routers.caption.get_visibility_clause", _fake_vis),
            mock.patch("api.routers.caption.get_existing_columns", return_value={"path", "aggregate"}),
            mock.patch("api.routers.caption._generate_caption", return_value="Generated caption"),
        ):
            resp = client.get("/api/caption", params={"path": "/photos/test.jpg"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["source"] == "generated"
        # Caption column treated as absent, so nothing is persisted.
        assert _read_caption(db, "/photos/test.jpg") is None


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
