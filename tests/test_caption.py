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
from api.auth import CurrentUser, get_optional_user


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


def _client_for(user):
    """Build a (TestClient, app) whose get_optional_user yields ``user``."""
    app = create_app()
    app.dependency_overrides[get_optional_user] = lambda: user
    return TestClient(app), app


class TestCaptionEditionGate:
    """F5': on-demand VLM generation is edition-only; cached reads stay open."""

    def test_generation_denied_for_non_edition(self, tmp_path):
        """A regular multi-user caller cannot trigger generation or the DB write."""
        db = str(tmp_path / "caption.db")
        _make_db(db, [{"path": "/photos/test.jpg", "caption": None}])
        gen = mock.Mock(return_value="new caption")
        client, app = _client_for(CurrentUser(user_id="u1", role="user"))
        try:
            with (
                mock.patch("api.routers.caption.VIEWER_CONFIG", {"features": {"show_captions": True}}),
                mock.patch("api.routers.caption.get_async_db", _async_conn_factory(db)),
                mock.patch("api.routers.caption.get_visibility_clause", _fake_vis),
                mock.patch("api.routers.caption.get_existing_columns", return_value={"caption", "path"}),
                mock.patch("api.routers.caption._generate_caption", gen),
                mock.patch("api.auth.is_multi_user_enabled", return_value=True),
            ):
                resp = client.get("/api/caption", params={"path": "/photos/test.jpg"})
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json()["source"] == "edition_required"
        gen.assert_not_called()
        assert _read_caption(db, "/photos/test.jpg") is None

    def test_cached_read_open_to_non_edition(self, tmp_path):
        """A cached caption is still returned to a non-edition caller."""
        db = str(tmp_path / "caption.db")
        _make_db(db, [{"path": "/photos/test.jpg", "caption": "cached text"}])
        client, app = _client_for(CurrentUser(user_id="u1", role="user"))
        try:
            with (
                mock.patch("api.routers.caption.VIEWER_CONFIG", {"features": {"show_captions": True}}),
                mock.patch("api.routers.caption.get_async_db", _async_conn_factory(db)),
                mock.patch("api.routers.caption.get_visibility_clause", _fake_vis),
                mock.patch("api.routers.caption.get_existing_columns", return_value={"caption", "path"}),
                mock.patch("api.auth.is_multi_user_enabled", return_value=True),
            ):
                resp = client.get("/api/caption", params={"path": "/photos/test.jpg"})
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json() == {"caption": "cached text", "source": "cached"}

    def test_generation_allowed_for_edition_admin(self, tmp_path):
        """A multi-user admin (edition) still generates and stores the caption."""
        db = str(tmp_path / "caption.db")
        _make_db(db, [{"path": "/photos/test.jpg", "caption": None}])
        client, app = _client_for(CurrentUser(user_id="admin", role="admin", edition_authenticated=True))
        try:
            with (
                mock.patch("api.routers.caption.VIEWER_CONFIG", {"features": {"show_captions": True}}),
                mock.patch("api.routers.caption.get_async_db", _async_conn_factory(db)),
                mock.patch("api.routers.caption.get_visibility_clause", _fake_vis),
                mock.patch("api.routers.caption.get_existing_columns", return_value={"caption", "path"}),
                mock.patch("api.routers.caption._generate_caption", return_value="fresh caption"),
                mock.patch("api.auth.is_multi_user_enabled", return_value=True),
            ):
                resp = client.get("/api/caption", params={"path": "/photos/test.jpg"})
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json()["source"] == "generated"
        assert _read_caption(db, "/photos/test.jpg") == "fresh caption"


class TestGenerateCaption:
    """Tests for the _generate_caption helper."""

    # resolve_vlm_config lives in api.model_cache and reads api.config._FULL_CONFIG
    # via a function-level import — patch THAT module, not the router's stale
    # import, or the tests only pass on boxes whose detected profile has no VLM.

    def test_returns_none_for_legacy_profile(self):
        from api.routers.caption import _generate_caption

        cfg = {"models": {"vram_profile": "legacy",
                          "profiles": {"legacy": {"tagging_model": "clip"}}}}
        with mock.patch("api.config._FULL_CONFIG", cfg):
            result = _generate_caption("/photos/test.jpg")
        assert result is None

    def test_returns_none_for_8gb_profile(self):
        from api.routers.caption import _generate_caption

        cfg = {"models": {"vram_profile": "8gb",
                          "profiles": {"8gb": {"tagging_model": "clip"}}}}
        with mock.patch("api.config._FULL_CONFIG", cfg):
            result = _generate_caption("/photos/test.jpg")
        assert result is None

    def test_returns_none_when_no_model_path(self):
        from api.routers.caption import _generate_caption

        cfg = {"models": {"vram_profile": "16gb",
                          "profiles": {"16gb": {"tagging_model": "qwen3.5-2b"}},
                          "qwen3_5_2b": {}}}
        with mock.patch("api.config._FULL_CONFIG", cfg):
            result = _generate_caption("/photos/test.jpg")
        assert result is None

    def test_returns_none_on_exception(self):
        from api.routers.caption import _generate_caption

        cfg = {"models": {"vram_profile": "16gb",
                          "profiles": {"16gb": {"tagging_model": "qwen3.5-2b"}},
                          "qwen3_5_2b": {"model_path": "Qwen/Qwen3.5-2B"}}}
        with (
            mock.patch("api.config._FULL_CONFIG", cfg),
            mock.patch("api.routers.caption.resolve_photo_disk_path",
                       return_value="/photos/test.jpg"),
            mock.patch("api.routers.caption.get_or_load_vlm_tagger",
                       side_effect=RuntimeError("GPU OOM")),
        ):
            result = _generate_caption("/photos/test.jpg")
        assert result is None

    def test_decodes_raw_via_shared_loader(self):
        from PIL import Image
        from api.routers.caption import _generate_caption

        cfg = {"models": {"vram_profile": "16gb",
                          "profiles": {"16gb": {"tagging_model": "qwen3.5-2b"}},
                          "qwen3_5_2b": {"model_path": "Qwen/Qwen3.5-2B"}}}
        raw_img = Image.new("RGB", (800, 600))
        tagger = mock.Mock()
        tagger.generate.return_value = "  A serene mountain lake  "
        with (
            mock.patch("api.config._FULL_CONFIG", cfg),
            mock.patch("api.routers.caption.resolve_photo_disk_path",
                       return_value="/photos/test.cr2"),
            mock.patch("api.routers.caption.get_or_load_vlm_tagger",
                       return_value=tagger),
            mock.patch("utils.image_loading.load_image_from_path",
                       return_value=(raw_img, None)) as mock_load,
        ):
            result = _generate_caption("/photos/test.cr2")
        assert result == "A serene mountain lake"
        mock_load.assert_called_once()
