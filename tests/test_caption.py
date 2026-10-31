"""Tests for the caption generation endpoint (api/routers/caption.py).

GET /api/caption is async (Topic 2 step 7), so endpoint-level tests patch
get_async_db with a real aiosqlite-backed temp DB rather than a MagicMock
(a MagicMock is not awaitable). The VLM/translation calls (_generate_caption,
_translate_caption) are blocking inference (wrapped in asyncio.to_thread by the
handler); they are patched with plain stubs. The PUT endpoint stays sync.
"""

import sqlite3
from contextlib import asynccontextmanager, contextmanager
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


    def test_vlm_unavailable_returns_503(self, edition_session_client, tmp_path):
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
            resp = edition_session_client.post("/api/caption", json={"path": "/photos/test.jpg"})

        assert resp.status_code == 503
        assert "unavailable" in resp.json()["detail"].lower()


    def test_generates_and_stores_caption(self, edition_session_client, tmp_path):
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
            resp = edition_session_client.post("/api/caption", json={"path": "/photos/test.jpg"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["caption"] == "A golden retriever playing in a park"
        assert body["source"] == "generated"
        # Verify it persisted the generated caption to the DB.
        assert _read_caption(db, "/photos/test.jpg") == "A golden retriever playing in a park"


    def test_no_caption_column_skips_cache(self, edition_session_client, tmp_path):
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
            resp = edition_session_client.post("/api/caption", json={"path": "/photos/test.jpg"})

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
                resp = client.post("/api/caption", json={"path": "/photos/test.jpg"})
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code in (401, 403)
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
                resp = client.post("/api/caption", json={"path": "/photos/test.jpg"})
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


class TestCaptionGetIsReadOnly:
    """GET /api/caption never generates, translates or writes, for any caller."""

    def _get(self, client, db, gen, translate, **params):
        with (
            mock.patch("api.routers.caption.VIEWER_CONFIG", {"features": {"show_captions": True}}),
            mock.patch("api.routers.caption.get_async_db", _async_conn_factory(db)),
            mock.patch("api.routers.caption.get_visibility_clause", _fake_vis),
            mock.patch(
                "api.routers.caption.get_existing_columns",
                return_value={"caption", "caption_translated", "path"},
            ),
            mock.patch("api.routers.caption._generate_caption", gen),
            mock.patch("api.routers.caption.translate_text", translate),
            mock.patch("api.routers.caption.translation_target", lambda lang: "fr" if lang else None),
        ):
            return client.get("/api/caption", params={"path": "/photos/test.jpg", **params})

    def _stored(self, db):
        conn = sqlite3.connect(db)
        row = conn.execute("SELECT caption, caption_translated FROM photos").fetchone()
        conn.close()
        return row

    def test_nothing_cached_is_not_generated_even_for_an_edition_caller(self, edition_session_client, tmp_path):
        db = str(tmp_path / "caption.db")
        _make_db(db, [{"path": "/photos/test.jpg", "caption": None}])
        gen, translate = mock.Mock(return_value="generated"), mock.Mock(return_value="traduit")
        resp = self._get(edition_session_client, db, gen, translate, lang="fr")
        assert resp.status_code == 200
        assert resp.json() == {"caption": None, "source": "none"}
        gen.assert_not_called()
        translate.assert_not_called()
        assert self._stored(db) == (None, None)

    def test_a_missing_translation_is_not_made_or_persisted(self, edition_session_client, tmp_path):
        db = str(tmp_path / "caption.db")
        _make_db(db, [{"path": "/photos/test.jpg", "caption": "cached text"}])
        gen, translate = mock.Mock(), mock.Mock(return_value="traduit")
        resp = self._get(edition_session_client, db, gen, translate, lang="fr")
        assert resp.json() == {"caption": "cached text", "source": "cached"}
        translate.assert_not_called()
        assert self._stored(db) == ("cached text", None)

    def test_a_stored_translation_is_served(self, client, tmp_path):
        db = str(tmp_path / "caption.db")
        _make_db(db, [{"path": "/photos/test.jpg", "caption": "cached text", "caption_translated": "texte"}])
        resp = self._get(client, db, mock.Mock(), mock.Mock(), lang="fr")
        assert resp.json() == {"caption": "texte", "source": "cached", "lang": "fr"}


class TestCaptionPost:
    """POST /api/caption: edition only, translates and persists, deduplicates."""

    @staticmethod
    @contextmanager
    def _patched(db, gen, translate=None):
        with (
            mock.patch("api.routers.caption.VIEWER_CONFIG", {"features": {"show_captions": True}}),
            mock.patch("api.routers.caption.get_async_db", _async_conn_factory(db)),
            mock.patch("api.routers.caption.get_visibility_clause", _fake_vis),
            mock.patch(
                "api.routers.caption.get_existing_columns",
                return_value={"caption", "caption_translated", "path"},
            ),
            mock.patch("api.routers.caption._generate_caption", gen),
            mock.patch("api.routers.caption.translate_text", translate or mock.Mock(return_value="traduit")),
            mock.patch("api.routers.caption.translation_target", lambda lang: "fr" if lang else None),
        ):
            yield

    def _post(self, client, db, gen, translate=None, **body):
        with self._patched(db, gen, translate):
            return client.post("/api/caption", json={"path": "/photos/test.jpg", **body})

    def test_requires_edition(self, anonymous_client, regular_client):
        for denied in (anonymous_client, regular_client):
            resp = denied.post("/api/caption", json={"path": "/photos/test.jpg"})
            assert resp.status_code in (401, 403), resp.text

    def test_generates_translates_and_persists_both(self, edition_session_client, tmp_path):
        db = str(tmp_path / "caption.db")
        _make_db(db, [{"path": "/photos/test.jpg", "caption": None}])
        resp = self._post(edition_session_client, db, mock.Mock(return_value="generated"), lang="fr")
        assert resp.json() == {"caption": "traduit", "source": "translated", "lang": "fr"}
        conn = sqlite3.connect(db)
        assert conn.execute("SELECT caption, caption_translated FROM photos").fetchone() == ("generated", "traduit")
        conn.close()

    def test_translates_a_stored_caption_without_regenerating(self, edition_session_client, tmp_path):
        db = str(tmp_path / "caption.db")
        _make_db(db, [{"path": "/photos/test.jpg", "caption": "cached text"}])
        gen = mock.Mock()
        resp = self._post(edition_session_client, db, gen, lang="fr")
        assert resp.json()["caption"] == "traduit"
        gen.assert_not_called()
        conn = sqlite3.connect(db)
        assert conn.execute("SELECT caption_translated FROM photos").fetchone()[0] == "traduit"
        conn.close()

    def test_concurrent_posts_share_one_generation(self, edition_session_client, tmp_path):
        import threading
        from concurrent.futures import ThreadPoolExecutor
        db = str(tmp_path / "caption.db")
        _make_db(db, [{"path": "/photos/test.jpg", "caption": None}])
        from api.routers import caption as cap
        calls, entered = [], threading.Event()
        gate = cap._caption_flights

        def slow(path):
            calls.append(path)
            entered.set()
            # Hold the leader until the second request is awaiting its flight.
            assert _wait_for_joiner(gate)
            return "shared"

        def post():
            return edition_session_client.post("/api/caption", json={"path": "/photos/test.jpg"})

        # Patch once, outside the threads: nested patches of one attribute from
        # two threads restore each other's mocks and leak into later tests.
        with (
            self._patched(db, slow),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            first = pool.submit(post)
            assert entered.wait(10)
            second = pool.submit(post)
            responses = [first.result(timeout=30), second.result(timeout=30)]
        assert [r.status_code for r in responses] == [200, 200]
        assert {r.json()["caption"] for r in responses} == {"shared"}
        assert len(calls) == 1


def _wait_for_joiner(gate, timeout=10.0):
    """Block until a second caller is awaiting the in-flight future.

    ``asyncio.wrap_future`` registers a done-callback on the shared future, so a
    callback there proves the joiner already holds the leader's flight and can
    no longer become a leader itself.
    """
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with gate._lock:
            flights = list(gate._flights.values())
        if any(f._done_callbacks for f in flights):
            return True
        time.sleep(0.005)
    return False
