"""Tests for the albums API router (api/routers/albums.py).

Uses the shared ``edition_client`` fixture from ``tests/conftest.py`` — see
that file for why dependency_overrides is the only pattern that works for
FastAPI Depends() chains.
"""

from contextlib import nullcontext
from unittest import mock

import pytest

from api.auth import CurrentUser


# Alias the shared fixture so existing ``def test_X(self, client)`` signatures
# work without a mechanical rename pass.
@pytest.fixture()
def client(edition_client):
    return edition_client


def _make_album_row(
    id=1,
    name="Test Album",
    description="A test album",
    cover_photo_path=None,
    is_smart=0,
    smart_filter_json=None,
    created_at="2025-01-01T00:00:00",
    updated_at="2025-01-01T00:00:00",
    share_token=None,
    user_id=None,
):
    """Create a dict-like album row for mocking database results."""
    return {
        "id": id,
        "name": name,
        "description": description,
        "cover_photo_path": cover_photo_path,
        "is_smart": is_smart,
        "smart_filter_json": smart_filter_json,
        "created_at": created_at,
        "updated_at": updated_at,
        "share_token": share_token,
        "user_id": user_id,
    }


_EDITION_USER = CurrentUser(edition_authenticated=True)
_ALBUMS_MODULE = "api.routers.albums"


class TestListAlbums:
    """Tests for GET /api/albums."""

    def test_list_albums_empty(self, client):
        """No albums returns empty list."""
        mock_conn = mock.MagicMock()
        # COUNT(*) returns 0
        mock_conn.execute.return_value.fetchone.return_value = (0,)
        # Album rows: empty
        mock_conn.execute.return_value.fetchall.return_value = []

        with mock.patch(f"{_ALBUMS_MODULE}.get_db", return_value=nullcontext(mock_conn)):
            resp = client.get("/api/albums")

        assert resp.status_code == 200
        body = resp.json()
        assert body["albums"] == []
        assert body["total"] == 0


    def test_list_albums_with_results(self, client):
        """Returns album dicts with expected fields."""
        album_row = _make_album_row(id=1, name="Vacation")
        count_row = {"album_id": 1, "cnt": 5}

        mock_conn = mock.MagicMock()
        # First execute: COUNT(*) for total
        # Second execute: album rows
        # Third execute: photo counts
        # Fourth execute: first photo path (from _get_first_photo_path)
        mock_conn.execute.return_value.fetchone.side_effect = [
            (1,),         # total count
            None,         # _get_first_photo_path: manual album first photo
        ]
        mock_conn.execute.return_value.fetchall.side_effect = [
            [album_row],  # album rows
            [count_row],  # photo count batch
        ]

        with mock.patch(f"{_ALBUMS_MODULE}.get_db", return_value=nullcontext(mock_conn)):
            resp = client.get("/api/albums")

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["albums"]) == 1
        album = body["albums"][0]
        assert album["id"] == 1
        assert album["name"] == "Vacation"
        assert album["description"] == "A test album"
        assert "is_smart" in album
        assert "created_at" in album
        assert "photo_count" in album



class TestCrud:
    """Tests for album CRUD operations."""

    def test_create_album(self, client):
        """POST /api/albums creates an album and returns it."""
        created_album = _make_album_row(id=10, name="New Album", description="desc")

        mock_conn = mock.MagicMock()
        mock_cursor = mock.MagicMock()
        mock_cursor.lastrowid = 10

        # First execute: INSERT (returns cursor)
        # Second execute: SELECT newly created album
        call_count = 0

        def execute_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_cursor
            result = mock.MagicMock()
            result.fetchone.return_value = created_album
            return result

        mock_conn.execute.side_effect = execute_side_effect

        # Auth is overridden by the fixture's app.dependency_overrides;
        # only mock the DB context manager here.
        with mock.patch(f"{_ALBUMS_MODULE}.get_db", return_value=nullcontext(mock_conn)):
            resp = client.post("/api/albums", json={"name": "New Album", "description": "desc"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "New Album"
        assert body["photo_count"] == 0
        mock_conn.commit.assert_called_once()


    def test_get_album_not_found(self, client):
        """GET /api/albums/999 returns 404 when album does not exist."""
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None

        with mock.patch(f"{_ALBUMS_MODULE}.get_db", return_value=nullcontext(mock_conn)):
            resp = client.get("/api/albums/999")

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Album not found"


    def test_delete_album(self, client):
        """DELETE /api/albums/1 deletes album and its photos."""
        album_row = _make_album_row(id=1)

        mock_conn = mock.MagicMock()
        # _check_album_access: SELECT * FROM albums WHERE id = ?
        mock_conn.execute.return_value.fetchone.return_value = album_row

        # Auth is overridden by the fixture; only mock the DB context manager.
        with mock.patch(f"{_ALBUMS_MODULE}.get_db", return_value=nullcontext(mock_conn)):
            resp = client.delete("/api/albums/1")

        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        # Verify both deletes were issued (album_photos + albums)
        delete_calls = [
            c for c in mock_conn.execute.call_args_list
            if c.args and isinstance(c.args[0], str) and "DELETE" in c.args[0]
        ]
        assert len(delete_calls) == 2
        mock_conn.commit.assert_called_once()



class TestSharing:
    """Tests for album sharing endpoints."""

    def test_share_album(self, client):
        """POST /api/albums/1/share returns share_url and token."""
        album_row = _make_album_row(id=1, share_token=None)

        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = album_row

        # Auth is overridden by the fixture; only mock the DB context manager.
        with mock.patch(f"{_ALBUMS_MODULE}.get_db", return_value=nullcontext(mock_conn)):
            resp = client.post("/api/albums/1/share")

        assert resp.status_code == 200
        body = resp.json()
        assert "share_url" in body
        assert "share_token" in body
        assert body["share_url"].startswith("/shared/album/1?token=")
        assert len(body["share_token"]) > 0
        mock_conn.commit.assert_called_once()


    def test_shared_album_invalid_token(self, client):
        """GET /api/shared/album/1 with wrong token returns 403."""
        from contextlib import asynccontextmanager
        album_row = _make_album_row(id=1, share_token="correct-secret-token")

        class _Cursor:
            async def fetchone(self):
                return album_row
            async def fetchall(self):
                return []
            async def close(self):
                pass

        class _Conn:
            async def execute(self, *a, **kw):
                return _Cursor()

        @asynccontextmanager
        async def _async_cm():
            yield _Conn()

        # Share-token endpoint is public by design — the share token IS the
        # auth. Tested via the regular ``client`` fixture; user state is
        # immaterial because the token check short-circuits before any
        # user-based filtering.
        with mock.patch(f"{_ALBUMS_MODULE}.get_async_db", _async_cm):
            resp = client.get("/api/shared/album/1", params={"token": "wrong"})

        assert resp.status_code == 403
        assert "Invalid share token" in resp.json()["detail"]

    def test_shared_album_non_ascii_token_403_not_500(self, client):
        """F7': a non-ASCII token is rejected with 403, not a 500 TypeError."""
        from contextlib import asynccontextmanager
        album_row = _make_album_row(id=1, share_token="correct-secret-token")

        class _Cursor:
            async def fetchone(self):
                return album_row
            async def fetchall(self):
                return []
            async def close(self):
                pass

        class _Conn:
            async def execute(self, *a, **kw):
                return _Cursor()

        @asynccontextmanager
        async def _async_cm():
            yield _Conn()

        with mock.patch(f"{_ALBUMS_MODULE}.get_async_db", _async_cm):
            resp = client.get("/api/shared/album/1", params={"token": "clé-privée-☂"})

        assert resp.status_code == 403
        assert "Invalid share token" in resp.json()["detail"]


    def test_shared_album_valid_token(self, client):
        """GET /api/shared/album/1 with correct token returns album data."""
        from contextlib import asynccontextmanager
        token = "valid-share-token-abc123"
        album_row = _make_album_row(id=1, name="Shared Vacation", share_token=token)

        # Async conn mock — /api/shared/album/{id} now uses get_async_db.
        class _Cursor:
            def __init__(self, rows, one):
                self._rows = rows
                self._one = one
            async def fetchall(self):
                return self._rows
            async def fetchone(self):
                return self._one
            async def close(self):
                pass

        call_counter = {"n": 0}
        async def _exec(*args, **kwargs):
            call_counter["n"] += 1
            n = call_counter["n"]
            if n == 1:
                return _Cursor([], album_row)  # SELECT album
            if n == 2:
                return _Cursor([], (0,))  # COUNT(*)
            return _Cursor([], None)

        class _Conn:
            async def execute(self, *a, **kw):
                return await _exec(*a, **kw)

        @asynccontextmanager
        async def _async_cm():
            yield _Conn()

        async def _async_noop(*args, **kwargs):
            return None

        # Share-token endpoint is public by design — see comment above.
        with (
            mock.patch(f"{_ALBUMS_MODULE}.get_async_db", _async_cm),
            mock.patch(f"{_ALBUMS_MODULE}.get_visibility_clause", return_value=("1=1", [])),
            mock.patch(f"{_ALBUMS_MODULE}.get_photos_from_clause", return_value=("photos", [])),
            mock.patch(f"{_ALBUMS_MODULE}.build_photo_select_columns", return_value=["photos.path"]),
            mock.patch(f"{_ALBUMS_MODULE}.split_photo_tags", return_value=[]),
            mock.patch(f"{_ALBUMS_MODULE}.attach_person_data_async", _async_noop),
            mock.patch(f"{_ALBUMS_MODULE}.sanitize_float_values"),
            mock.patch(f"{_ALBUMS_MODULE}.VIEWER_CONFIG", {
                "pagination": {"default_per_page": 48},
                "display": {"tags_per_photo": 5},
            }),
        ):
            resp = client.get("/api/shared/album/1", params={"token": token})

        assert resp.status_code == 200
        body = resp.json()
        assert "album" in body
        assert body["album"]["name"] == "Shared Vacation"
        assert body["album"]["is_shared"] is True
        assert "photos" in body
        assert body["total"] == 0


class TestAlbumAccessInstallMode:
    """Install-mode carve-out for album ownership (regression for the
    no-password legacy-album 403 bug)."""

    def test_legacy_album_readable_in_no_password_mode(self, anonymous_client):
        """A ``_legacy``-owned album must open on a fully open single-user
        install, where ``get_optional_user`` yields no user (user_id=None).

        RED against the unfixed code: ``_check_album_access`` denies because
        ``'_legacy' != None``. GREEN once the check honours the world-readable
        install carve-out.
        """
        album_row = _make_album_row(id=1, user_id="_legacy")

        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchone.side_effect = [
            album_row,  # _check_album_access SELECT
            (3,),       # photo_count COUNT
        ]

        with (
            mock.patch(f"{_ALBUMS_MODULE}.get_db", return_value=nullcontext(mock_conn)),
            mock.patch("api.db_helpers.is_multi_user_enabled", return_value=False),
            mock.patch("api.db_helpers.VIEWER_CONFIG", {"password": ""}),
        ):
            resp = anonymous_client.get("/api/albums/1")

        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == 1
        assert body["photo_count"] == 3

    def test_foreign_album_denied_in_multi_user_mode(self, regular_client):
        """Multi-user isolation preserved: user ``u1`` cannot open an album owned
        by another user. Ownership denial must behave exactly as before the fix.
        """
        album_row = _make_album_row(id=2, user_id="someone-else")

        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = album_row

        with (
            mock.patch(f"{_ALBUMS_MODULE}.get_db", return_value=nullcontext(mock_conn)),
            mock.patch("api.db_helpers.is_multi_user_enabled", return_value=True),
        ):
            resp = regular_client.get("/api/albums/2")

        assert resp.status_code == 403
        assert resp.json()["detail"] == "Access denied"


class TestAlbumSerializerScoringContext:
    """``_album_to_dict`` surfaces the album's scoring context."""

    def test_scoring_context_included_when_present(self, client):
        row = _make_album_row(id=1)
        row["scoring_context"] = "action_stage"

        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchone.side_effect = [row, (2,)]

        with mock.patch(f"{_ALBUMS_MODULE}.get_db", return_value=nullcontext(mock_conn)):
            resp = client.get("/api/albums/1")

        assert resp.status_code == 200
        assert resp.json()["scoring_context"] == "action_stage"

    def test_scoring_context_defaults_none_when_column_absent(self, client):
        row = _make_album_row(id=1)  # no 'scoring_context' key -- pre-migration row shape

        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchone.side_effect = [row, (0,)]

        with mock.patch(f"{_ALBUMS_MODULE}.get_db", return_value=nullcontext(mock_conn)):
            resp = client.get("/api/albums/1")

        assert resp.status_code == 200
        assert resp.json()["scoring_context"] is None


class TestAlbumScoringContext:
    """Tests for PUT /api/albums/{id}/scoring_context."""

    ENDPOINT = "/api/albums/1/scoring_context"

    def test_requires_edition_403(self, regular_client):
        resp = regular_client.put(self.ENDPOINT, json={"scoring_context": "action_stage"})
        assert resp.status_code == 403

    def test_anonymous_401(self, anonymous_client):
        resp = anonymous_client.put(self.ENDPOINT, json={"scoring_context": "action_stage"})
        assert resp.status_code == 401

    def test_unknown_context_400(self, client):
        mock_config = mock.MagicMock()
        mock_config.get_scoring_contexts.return_value = {"default": {}, "action_stage": {}}

        with mock.patch.dict("sys.modules", {"config": mock.MagicMock(ScoringConfig=lambda *a, **k: mock_config)}):
            resp = client.put(self.ENDPOINT, json={"scoring_context": "not_a_context"})

        assert resp.status_code == 400

    def test_materializes_context_and_counts_conflicts(self, client):
        album_row = _make_album_row(id=1)

        mock_config = mock.MagicMock()
        mock_config.get_scoring_contexts.return_value = {"default": {}, "action_stage": {}}

        conn_mock = mock.MagicMock()
        photo_rows = [{"photo_path": "/a.jpg"}, {"photo_path": "/b.jpg"}, {"photo_path": "/c.jpg"}]
        conn_mock.execute.return_value.fetchone.return_value = album_row
        conn_mock.execute.return_value.fetchall.return_value = photo_rows

        mock_get_overrides = mock.MagicMock(return_value={
            "/a.jpg": {"scoring_context": "portrait_session", "category_override": None},
            "/b.jpg": {"scoring_context": None, "category_override": None},
            # /c.jpg has no existing override row at all
        })
        mock_set_override = mock.MagicMock()
        fake_module = mock.MagicMock(
            get_photo_scoring_overrides=mock_get_overrides,
            set_photo_scoring_override=mock_set_override,
        )

        with (
            mock.patch.dict("sys.modules", {
                "config": mock.MagicMock(ScoringConfig=lambda *a, **k: mock_config),
                "db.scoring_overrides": fake_module,
            }),
            mock.patch(f"{_ALBUMS_MODULE}.get_db", return_value=nullcontext(conn_mock)),
        ):
            resp = client.put(self.ENDPOINT, json={"scoring_context": "action_stage"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["updated"] == 3
        # Only /a.jpg carried a different, non-null context -> exactly one conflict.
        assert data["conflicts"] == 1

        assert mock_set_override.call_count == 3
        for call in mock_set_override.call_args_list:
            assert call.kwargs["scoring_context"] == "action_stage"
            assert call.kwargs["source"] == "album:1"

        update_calls = [
            c for c in conn_mock.execute.call_args_list
            if c.args and isinstance(c.args[0], str) and "UPDATE albums SET scoring_context" in c.args[0]
        ]
        assert len(update_calls) == 1
        assert update_calls[0].args[1][0] == "action_stage"

        conn_mock.commit.assert_called_once()


class TestAlbumSuggestedContext:
    """Tests for GET /api/albums/{id}/suggested_context."""

    ENDPOINT = "/api/albums/1/suggested_context"

    def test_writes_nothing_and_suggests_from_dominant_moment(self, client):
        album_row = _make_album_row(id=1)

        mock_config = mock.MagicMock()
        mock_config.get_scoring_contexts.return_value = {
            "default": {"suggest_from_moments": []},
            "action_stage": {"suggest_from_moments": ["sports_action"]},
        }

        conn_mock = mock.MagicMock()
        conn_mock.execute.return_value.fetchone.return_value = album_row
        conn_mock.execute.return_value.fetchall.return_value = [
            {"narrative_moment": "sports_action", "cnt": 8},
            {"narrative_moment": "celebration", "cnt": 2},
        ]

        with (
            mock.patch.dict("sys.modules", {"config": mock.MagicMock(ScoringConfig=lambda *a, **k: mock_config)}),
            mock.patch(f"{_ALBUMS_MODULE}.get_db", return_value=nullcontext(conn_mock)),
        ):
            resp = client.get(self.ENDPOINT)

        assert resp.status_code == 200
        data = resp.json()
        assert data["suggested"] == "action_stage"
        assert data["moment"] == "sports_action"
        assert data["share"] == 0.8
        assert data["counts"] == {"sports_action": 8, "celebration": 2}

        # Suggestion only -- must not write anything.
        conn_mock.commit.assert_not_called()
        write_calls = [
            c for c in conn_mock.execute.call_args_list
            if c.args and isinstance(c.args[0], str) and c.args[0].strip().upper().startswith(("UPDATE", "INSERT", "DELETE"))
        ]
        assert write_calls == []

    def test_no_moments_returns_none(self, client):
        album_row = _make_album_row(id=1)

        conn_mock = mock.MagicMock()
        conn_mock.execute.return_value.fetchone.return_value = album_row
        conn_mock.execute.return_value.fetchall.return_value = []

        with mock.patch(f"{_ALBUMS_MODULE}.get_db", return_value=nullcontext(conn_mock)):
            resp = client.get(self.ENDPOINT)

        assert resp.status_code == 200
        data = resp.json()
        assert data["suggested"] is None
        assert data["moment"] is None
        assert data["share"] == 0.0

