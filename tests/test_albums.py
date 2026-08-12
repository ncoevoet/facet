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

    def test_share_album_reuses_existing_token(self, client):
        """Without rotate, a re-share returns the album's existing token."""
        album_row = _make_album_row(id=1, share_token="existing-tok")
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = album_row

        with mock.patch(f"{_ALBUMS_MODULE}.get_db", return_value=nullcontext(mock_conn)):
            resp = client.post("/api/albums/1/share")

        assert resp.status_code == 200
        assert resp.json()["share_token"] == "existing-tok"

    def test_share_album_rotate_mints_new_token(self, client):
        """rotate=true invalidates the old link by minting a fresh token."""
        album_row = _make_album_row(id=1, share_token="old-tok")
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = album_row

        with mock.patch(f"{_ALBUMS_MODULE}.get_db", return_value=nullcontext(mock_conn)):
            resp = client.post("/api/albums/1/share", params={"rotate": "true"})

        assert resp.status_code == 200
        assert resp.json()["share_token"] != "old-tok"
        assert len(resp.json()["share_token"]) > 0


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

        def _execute(sql, *args):
            cursor = mock.MagicMock()
            cursor.fetchone.return_value = album_row
            cursor.fetchall.return_value = photo_rows
            if "FROM photos WHERE path IN" in sql:
                cursor.__iter__.return_value = iter([(r["photo_path"],) for r in photo_rows])
            return cursor

        conn_mock.execute.side_effect = _execute

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


class TestAlbumScoringContextConflictsComputedBeforeOverwrite:
    """DEFECT 6 regression: ``conflicts`` must be counted from member
    override state read BEFORE this call overwrites it, not after. The old
    docstring implied a dry-run preview the caller could cancel; it's
    actually reported alongside an already-applied change (no separate
    commit step) -- but the read must still precede the write it counts
    against, or the number would be meaningless."""

    ENDPOINT = "/api/albums/1/scoring_context"

    def test_existing_overrides_are_read_before_any_write(self, client):
        album_row = _make_album_row(id=1)

        mock_config = mock.MagicMock()
        mock_config.get_scoring_contexts.return_value = {"default": {}, "action_stage": {}}

        conn_mock = mock.MagicMock()
        photo_rows = [{"photo_path": "/a.jpg"}]

        def _execute(sql, *args):
            cursor = mock.MagicMock()
            cursor.fetchone.return_value = album_row
            cursor.fetchall.return_value = photo_rows
            if "FROM photos WHERE path IN" in sql:
                cursor.__iter__.return_value = iter([(r["photo_path"],) for r in photo_rows])
            return cursor

        conn_mock.execute.side_effect = _execute

        call_order = []

        def _get_overrides(*a, **k):
            call_order.append("get")
            return {"/a.jpg": {"scoring_context": "old_context", "category_override": None}}

        def _set_override(*a, **k):
            call_order.append("set")

        mock_get_overrides = mock.MagicMock(side_effect=_get_overrides)
        mock_set_override = mock.MagicMock(side_effect=_set_override)
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
        assert resp.json()["conflicts"] == 1
        assert call_order == ["get", "set"]


class TestAlbumScoringContextSmartAlbum:
    """DEFECT 1 regression: smart albums have no rows in ``album_photos`` --
    membership is computed at read time from ``smart_filter_json``. Before
    the fix, PUT .../scoring_context read only ``album_photos`` and silently
    materialized onto zero photos for every smart album, a 200 OK
    indistinguishable from success.

    These call the router function directly (not through ``client``): a
    real ``sqlite3.Connection`` created in the test thread cannot cross into
    TestClient's request threadpool (``sqlite3.ProgrammingError``), and a
    real, schema-initialised DB is what actually exercises
    ``_build_gallery_where`` -- the whole point of this regression."""

    ENDPOINT_ARGS = (1,)

    @staticmethod
    def _init_db(tmp_path, smart_filter_json):
        from db.connection import get_connection
        from db.schema import init_database

        db_path = str(tmp_path / "smart_scoring.db")
        init_database(db_path)
        with get_connection(db_path) as conn:
            conn.execute(
                "INSERT INTO albums (id, name, is_smart, smart_filter_json) VALUES (1, 'Wildlife', 1, ?)",
                (smart_filter_json,),
            )
            conn.execute(
                "INSERT INTO photos (path, category) VALUES "
                "('/w1.jpg', 'wildlife'), ('/w2.jpg', 'wildlife'), ('/other.jpg', 'landscape')"
            )
            conn.commit()
        return db_path

    def test_materializes_onto_resolved_smart_album_members(self, tmp_path):
        from db.connection import get_connection
        from db.scoring_overrides import get_photo_scoring_overrides
        from api.routers.albums import set_album_scoring_context, AlbumScoringContextRequest

        db_path = self._init_db(tmp_path, '{"category": "wildlife"}')

        mock_config = mock.MagicMock()
        mock_config.get_scoring_contexts.return_value = {"default": {}, "action_stage": {}}

        with get_connection(db_path) as conn:
            with (
                mock.patch.dict("sys.modules", {"config": mock.MagicMock(ScoringConfig=lambda *a, **k: mock_config)}),
                mock.patch(f"{_ALBUMS_MODULE}.get_db", return_value=nullcontext(conn)),
                mock.patch("api.db_helpers.is_multi_user_enabled", return_value=False),
                mock.patch("api.db_helpers.VIEWER_CONFIG", {"password": ""}),
            ):
                result = set_album_scoring_context(
                    1, AlbumScoringContextRequest(scoring_context="action_stage"), _EDITION_USER
                )

            assert result["updated"] == 2
            assert result["conflicts"] == 0
            assert "warning" not in result

            overrides = get_photo_scoring_overrides(conn, paths=["/w1.jpg", "/w2.jpg", "/other.jpg"])
        assert overrides["/w1.jpg"]["scoring_context"] == "action_stage"
        assert overrides["/w2.jpg"]["scoring_context"] == "action_stage"
        assert "/other.jpg" not in overrides

    def test_warns_instead_of_implying_success_when_smart_album_matches_nothing(self, tmp_path):
        from db.connection import get_connection
        from api.routers.albums import set_album_scoring_context, AlbumScoringContextRequest

        db_path = self._init_db(tmp_path, '{"category": "does_not_exist"}')

        mock_config = mock.MagicMock()
        mock_config.get_scoring_contexts.return_value = {"default": {}, "action_stage": {}}

        with get_connection(db_path) as conn:
            with (
                mock.patch.dict("sys.modules", {"config": mock.MagicMock(ScoringConfig=lambda *a, **k: mock_config)}),
                mock.patch(f"{_ALBUMS_MODULE}.get_db", return_value=nullcontext(conn)),
                mock.patch("api.db_helpers.is_multi_user_enabled", return_value=False),
                mock.patch("api.db_helpers.VIEWER_CONFIG", {"password": ""}),
            ):
                result = set_album_scoring_context(
                    1, AlbumScoringContextRequest(scoring_context="action_stage"), _EDITION_USER
                )

        assert result["updated"] == 0
        assert "warning" in result


class TestAlbumScoringContextClear:
    """DEFECT 2 regression: an album scoring context previously could never
    be undone -- DELETE .../scoring_context must clear the album's own field
    AND undo it on exactly the members THIS album stamped
    (``source == 'album:<id>'``), leaving manual overrides untouched."""

    ENDPOINT = "/api/albums/1/scoring_context"

    def test_requires_edition_403(self, regular_client):
        resp = regular_client.delete(self.ENDPOINT)
        assert resp.status_code == 403

    def test_anonymous_401(self, anonymous_client):
        resp = anonymous_client.delete(self.ENDPOINT)
        assert resp.status_code == 401

    def test_clears_album_context_and_only_its_own_member_overrides(self, tmp_path):
        from db.connection import get_connection
        from db.schema import init_database
        from db.scoring_overrides import get_photo_scoring_overrides, set_photo_scoring_override
        from api.routers.albums import clear_album_scoring_context

        db_path = str(tmp_path / "clear_scoring.db")
        init_database(db_path)

        with get_connection(db_path) as conn:
            conn.execute("INSERT INTO albums (id, name, scoring_context) VALUES (1, 'Trip', 'motorsport')")
            conn.execute("INSERT INTO photos (path) VALUES ('/a.jpg'), ('/b.jpg'), ('/manual.jpg')")
            set_photo_scoring_override(conn, '/a.jpg', scoring_context='motorsport', source='album:1')
            set_photo_scoring_override(conn, '/b.jpg', scoring_context='motorsport', source='album:1')
            set_photo_scoring_override(conn, '/manual.jpg', scoring_context='portrait_session', source='manual')
            conn.commit()

        with get_connection(db_path) as conn:
            with mock.patch(f"{_ALBUMS_MODULE}.get_db", return_value=nullcontext(conn)):
                result = clear_album_scoring_context(1, _EDITION_USER)

            assert result["ok"] is True
            assert result["cleared"] == 2

            album = conn.execute("SELECT scoring_context FROM albums WHERE id = 1").fetchone()
            assert album["scoring_context"] is None

            overrides = get_photo_scoring_overrides(conn, paths=["/a.jpg", "/b.jpg", "/manual.jpg"])
        # Both fields on /a.jpg and /b.jpg are now NULL -> the override row is deleted entirely.
        assert "/a.jpg" not in overrides
        assert "/b.jpg" not in overrides
        assert overrides["/manual.jpg"]["scoring_context"] == "portrait_session"


class TestDeleteAlbumClearsScoringOverrides:
    """DEFECT 2 regression: deleting an album must undo its scoring_context
    stamp on the members it set -- otherwise every member stays stamped
    forever, since ``photo_scoring_overrides`` carries no FK to ``albums``."""

    def test_delete_clears_only_this_albums_overrides(self, tmp_path):
        from db.connection import get_connection
        from db.schema import init_database
        from db.scoring_overrides import get_photo_scoring_overrides, set_photo_scoring_override
        from api.routers.albums import delete_album

        db_path = str(tmp_path / "delete_scoring.db")
        init_database(db_path)

        with get_connection(db_path) as conn:
            conn.execute("INSERT INTO albums (id, name, scoring_context) VALUES (1, 'Trip', 'motorsport')")
            conn.execute("INSERT INTO albums (id, name, scoring_context) VALUES (2, 'Other', 'astro')")
            conn.execute("INSERT INTO photos (path) VALUES ('/a.jpg'), ('/shared.jpg'), ('/manual.jpg')")
            set_photo_scoring_override(conn, '/a.jpg', scoring_context='motorsport', source='album:1')
            set_photo_scoring_override(conn, '/shared.jpg', scoring_context='astro', source='album:2')
            set_photo_scoring_override(conn, '/manual.jpg', scoring_context='portrait_session', source='manual')
            conn.commit()

        with get_connection(db_path) as conn:
            with mock.patch(f"{_ALBUMS_MODULE}.get_db", return_value=nullcontext(conn)):
                result = delete_album(1, _EDITION_USER)

            assert result["ok"] is True

            overrides = get_photo_scoring_overrides(conn, paths=["/a.jpg", "/shared.jpg", "/manual.jpg"])
        assert "/a.jpg" not in overrides
        assert overrides["/shared.jpg"]["scoring_context"] == "astro"
        assert overrides["/manual.jpg"]["scoring_context"] == "portrait_session"


class TestRemovePhotosFromAlbumClearsScoringOverrides:
    """DEFECT 2 regression: removing photos from an album must undo this
    album's stamp on exactly the removed photos; photos that stay in the
    album keep the context."""

    def test_remove_clears_only_removed_photos_overrides(self, tmp_path):
        from db.connection import get_connection
        from db.schema import init_database
        from db.scoring_overrides import get_photo_scoring_overrides, set_photo_scoring_override
        from api.routers.albums import remove_photos_from_album, AlbumPhotosRequest

        db_path = str(tmp_path / "remove_scoring.db")
        init_database(db_path)

        with get_connection(db_path) as conn:
            conn.execute("INSERT INTO albums (id, name, scoring_context) VALUES (1, 'Trip', 'motorsport')")
            conn.execute("INSERT INTO photos (path) VALUES ('/a.jpg'), ('/b.jpg')")
            conn.execute(
                "INSERT INTO album_photos (album_id, photo_path, position) VALUES (1, '/a.jpg', 0), (1, '/b.jpg', 1)"
            )
            set_photo_scoring_override(conn, '/a.jpg', scoring_context='motorsport', source='album:1')
            set_photo_scoring_override(conn, '/b.jpg', scoring_context='motorsport', source='album:1')
            conn.commit()

        with get_connection(db_path) as conn:
            with mock.patch(f"{_ALBUMS_MODULE}.get_db", return_value=nullcontext(conn)):
                result = remove_photos_from_album(1, AlbumPhotosRequest(photo_paths=["/a.jpg"]), _EDITION_USER)

            assert result["ok"] is True

            overrides = get_photo_scoring_overrides(conn, paths=["/a.jpg", "/b.jpg"])
        assert "/a.jpg" not in overrides
        assert overrides["/b.jpg"]["scoring_context"] == "motorsport"


class TestAlbumSuggestedContext:
    """Tests for GET /api/albums/{id}/suggested_context.

    Real ``sqlite3.Connection`` fixtures (not a mocked connection): the
    endpoint now resolves membership through ``_resolve_album_member_paths``
    (DEFECT F8 regression -- it used to read ``album_photos`` directly, which
    carries no rows for a smart album, so the suggestion silently starved for
    every smart album), the same real-DB exercise as
    ``TestAlbumScoringContextSmartAlbum``.
    """

    _MOMENT_PHOTOS = (
        "INSERT INTO photos (path, category, narrative_moment) VALUES "
        "('/a.jpg', 'wildlife', 'sports_action'), ('/b.jpg', 'wildlife', 'sports_action'), "
        "('/c.jpg', 'wildlife', 'sports_action'), ('/d.jpg', 'wildlife', 'sports_action'), "
        "('/e.jpg', 'wildlife', 'sports_action'), ('/f.jpg', 'wildlife', 'sports_action'), "
        "('/g.jpg', 'wildlife', 'sports_action'), ('/h.jpg', 'wildlife', 'sports_action'), "
        "('/i.jpg', 'wildlife', 'celebration'), ('/j.jpg', 'wildlife', 'celebration'), "
        "('/other.jpg', 'landscape', NULL)"
    )
    _MOMENT_MEMBER_PATHS = [
        '/a.jpg', '/b.jpg', '/c.jpg', '/d.jpg', '/e.jpg',
        '/f.jpg', '/g.jpg', '/h.jpg', '/i.jpg', '/j.jpg',
    ]
    _CONTEXTS = {
        "default": {"suggest_from_moments": []},
        "action_stage": {"suggest_from_moments": ["sports_action"]},
    }

    @staticmethod
    def _init_db(tmp_path, name, is_smart=0, smart_filter_json=None, seed_photos=True):
        from db.connection import get_connection
        from db.schema import init_database

        db_path = str(tmp_path / name)
        init_database(db_path)
        with get_connection(db_path) as conn:
            conn.execute(
                "INSERT INTO albums (id, name, is_smart, smart_filter_json) VALUES (1, 'Trip', ?, ?)",
                (is_smart, smart_filter_json),
            )
            if seed_photos:
                conn.execute(TestAlbumSuggestedContext._MOMENT_PHOTOS)
                if not is_smart:
                    conn.executemany(
                        "INSERT INTO album_photos (album_id, photo_path, position) VALUES (1, ?, ?)",
                        [(p, i) for i, p in enumerate(TestAlbumSuggestedContext._MOMENT_MEMBER_PATHS)],
                    )
            conn.commit()
        return db_path

    def test_writes_nothing_and_suggests_from_dominant_moment(self, tmp_path):
        from db.connection import get_connection
        from api.routers.albums import get_album_suggested_context

        db_path = self._init_db(tmp_path, "manual_suggest.db")
        mock_config = mock.MagicMock()
        mock_config.get_scoring_contexts.return_value = self._CONTEXTS

        with get_connection(db_path) as conn:
            with (
                mock.patch.dict("sys.modules", {"config": mock.MagicMock(ScoringConfig=lambda *a, **k: mock_config)}),
                mock.patch(f"{_ALBUMS_MODULE}.get_db", return_value=nullcontext(conn)),
                mock.patch("api.db_helpers.is_multi_user_enabled", return_value=False),
                mock.patch("api.db_helpers.VIEWER_CONFIG", {"password": ""}),
            ):
                result = get_album_suggested_context(1, None)

            assert conn.total_changes == 0  # suggestion only -- must not write anything

        assert result["suggested"] == "action_stage"
        assert result["moment"] == "sports_action"
        assert result["share"] == 0.8
        assert result["counts"] == {"sports_action": 8, "celebration": 2}

    def test_suggests_from_dominant_moment_on_smart_album(self, tmp_path):
        """DEFECT F8 regression: a smart album's members carry the moments, but
        ``album_photos`` is empty for it -- the suggestion must still resolve."""
        from db.connection import get_connection
        from api.routers.albums import get_album_suggested_context

        db_path = self._init_db(tmp_path, "smart_suggest.db", is_smart=1, smart_filter_json='{"category": "wildlife"}')
        mock_config = mock.MagicMock()
        mock_config.get_scoring_contexts.return_value = self._CONTEXTS

        with get_connection(db_path) as conn:
            with (
                mock.patch.dict("sys.modules", {"config": mock.MagicMock(ScoringConfig=lambda *a, **k: mock_config)}),
                mock.patch(f"{_ALBUMS_MODULE}.get_db", return_value=nullcontext(conn)),
                mock.patch("api.db_helpers.is_multi_user_enabled", return_value=False),
                mock.patch("api.db_helpers.VIEWER_CONFIG", {"password": ""}),
            ):
                result = get_album_suggested_context(1, None)

        assert result["suggested"] == "action_stage"
        assert result["moment"] == "sports_action"
        assert result["counts"] == {"sports_action": 8, "celebration": 2}

    def test_no_moments_returns_none(self, tmp_path):
        from db.connection import get_connection
        from api.routers.albums import get_album_suggested_context

        db_path = self._init_db(tmp_path, "no_moments.db", seed_photos=False)
        with get_connection(db_path) as conn:
            conn.execute("INSERT INTO photos (path) VALUES ('/a.jpg')")
            conn.execute("INSERT INTO album_photos (album_id, photo_path, position) VALUES (1, '/a.jpg', 0)")
            conn.commit()

        with get_connection(db_path) as conn:
            with (
                mock.patch(f"{_ALBUMS_MODULE}.get_db", return_value=nullcontext(conn)),
                mock.patch("api.db_helpers.is_multi_user_enabled", return_value=False),
                mock.patch("api.db_helpers.VIEWER_CONFIG", {"password": ""}),
            ):
                result = get_album_suggested_context(1, None)

        assert result["suggested"] is None
        assert result["moment"] is None
        assert result["share"] == 0.0


class TestAlbumContextMaterializesOntoLaterPhotos:
    """Real-DB test (no mocked connection): append_album_photos calls
    _apply_album_scoring_context internally, so photos added to an album
    AFTER its scoring_context was set inherit that context too, not just the
    members present when PUT .../scoring_context ran."""

    def test_photos_appended_later_inherit_the_album_context(self, tmp_path):
        from db.connection import get_connection
        from db.schema import init_database
        from db.scoring_overrides import get_photo_scoring_overrides
        from api.routers.albums import append_album_photos

        db_path = str(tmp_path / "albums.db")
        init_database(db_path)

        with get_connection(db_path) as conn:
            conn.execute(
                "INSERT INTO albums (id, name, scoring_context) VALUES (1, 'Trip', 'action_stage')"
            )
            conn.execute("INSERT INTO photos (path) VALUES ('/a.jpg'), ('/b.jpg')")
            conn.commit()

            append_album_photos(conn, 1, ['/a.jpg'])
            conn.commit()

        before = get_photo_scoring_overrides(db_path, paths=['/a.jpg', '/b.jpg'])
        assert before.get('/a.jpg', {}).get('scoring_context') == 'action_stage'
        assert '/b.jpg' not in before

        with get_connection(db_path) as conn:
            append_album_photos(conn, 1, ['/b.jpg'])
            conn.commit()

        after = get_photo_scoring_overrides(db_path, paths=['/a.jpg', '/b.jpg'])
        assert after['/a.jpg']['scoring_context'] == 'action_stage'
        assert after['/b.jpg']['scoring_context'] == 'action_stage'

    def test_append_is_a_noop_when_the_album_carries_no_context(self, tmp_path):
        from db.connection import get_connection
        from db.schema import init_database
        from db.scoring_overrides import get_photo_scoring_overrides
        from api.routers.albums import append_album_photos

        db_path = str(tmp_path / "albums.db")
        init_database(db_path)

        with get_connection(db_path) as conn:
            conn.execute("INSERT INTO albums (id, name) VALUES (1, 'No Context')")
            conn.execute("INSERT INTO photos (path) VALUES ('/a.jpg')")
            conn.commit()

            append_album_photos(conn, 1, ['/a.jpg'])
            conn.commit()

        overrides = get_photo_scoring_overrides(db_path, paths=['/a.jpg'])
        assert overrides == {}


class TestAlbumScoringContextPreservesManualOverride:
    """DEFECT F2 regression: a member's manual override must never be
    silently converted into an album-sourced one. Before the fix,
    ``set_album_scoring_context`` stamped every member unconditionally, so a
    photo the user had manually marked (``source == 'manual'``) had its
    ``source`` flipped to ``album:<id>`` -- and a later clear of that album's
    context would then wipe the photo's own choice."""

    @staticmethod
    def _init_db(tmp_path):
        from db.connection import get_connection
        from db.schema import init_database
        from db.scoring_overrides import set_photo_scoring_override

        db_path = str(tmp_path / "manual_protect.db")
        init_database(db_path)
        with get_connection(db_path) as conn:
            conn.execute("INSERT INTO albums (id, name) VALUES (1, 'Trip')")
            conn.execute("INSERT INTO photos (path) VALUES ('/manual.jpg'), ('/plain.jpg')")
            conn.executemany(
                "INSERT INTO album_photos (album_id, photo_path, position) VALUES (1, ?, ?)",
                [('/manual.jpg', 0), ('/plain.jpg', 1)],
            )
            set_photo_scoring_override(conn, '/manual.jpg', category_override='sports', source='manual')
            conn.commit()
        return db_path

    def test_set_skips_and_counts_manual_members(self, tmp_path):
        from db.connection import get_connection
        from db.scoring_overrides import get_photo_scoring_overrides
        from api.routers.albums import set_album_scoring_context, AlbumScoringContextRequest

        db_path = self._init_db(tmp_path)
        mock_config = mock.MagicMock()
        mock_config.get_scoring_contexts.return_value = {"default": {}, "action_stage": {}}

        with get_connection(db_path) as conn:
            with (
                mock.patch.dict("sys.modules", {"config": mock.MagicMock(ScoringConfig=lambda *a, **k: mock_config)}),
                mock.patch(f"{_ALBUMS_MODULE}.get_db", return_value=nullcontext(conn)),
                mock.patch("api.db_helpers.is_multi_user_enabled", return_value=False),
                mock.patch("api.db_helpers.VIEWER_CONFIG", {"password": ""}),
            ):
                result = set_album_scoring_context(
                    1, AlbumScoringContextRequest(scoring_context="action_stage"), _EDITION_USER
                )

            row = conn.execute(
                "SELECT scoring_context, source FROM photo_scoring_overrides WHERE photo_path = '/manual.jpg'"
            ).fetchone()

        assert result["updated"] == 1
        assert result["manual_skipped"] == 1
        assert row["scoring_context"] is None
        assert row["source"] == "manual"

        overrides = get_photo_scoring_overrides(db_path, paths=['/plain.jpg'])
        assert overrides['/plain.jpg']['scoring_context'] == 'action_stage'

    def test_append_later_also_skips_manual_members(self, tmp_path):
        """``_apply_album_scoring_context`` (run from ``append_album_photos``)
        must apply the same manual-override protection as the initial stamp."""
        from db.connection import get_connection
        from db.scoring_overrides import get_photo_scoring_overrides, set_photo_scoring_override
        from api.routers.albums import append_album_photos

        db_path = self._init_db(tmp_path)
        with get_connection(db_path) as conn:
            conn.execute("UPDATE albums SET scoring_context = 'action_stage' WHERE id = 1")
            conn.execute("DELETE FROM album_photos")
            conn.execute("INSERT INTO photos (path) VALUES ('/new_manual.jpg')")
            set_photo_scoring_override(conn, '/new_manual.jpg', category_override='sports', source='manual')
            conn.commit()

            append_album_photos(conn, 1, ['/manual.jpg', '/new_manual.jpg', '/plain.jpg'])
            conn.commit()

        overrides = get_photo_scoring_overrides(db_path, paths=['/manual.jpg', '/new_manual.jpg', '/plain.jpg'])
        assert overrides['/manual.jpg']['scoring_context'] is None
        assert overrides['/new_manual.jpg']['scoring_context'] is None
        assert overrides['/plain.jpg']['scoring_context'] == 'action_stage'


class TestAlbumScoringContextMultiAlbumMembership:
    """DEFECT F3 regression: a single ``source`` column cannot represent
    multi-album membership. Removing a photo from the album that most
    recently stamped it must not strip a context that another album, which
    still counts the photo a member, still declares."""

    def test_remove_from_one_album_restamps_from_a_still_declaring_album(self, tmp_path):
        from db.connection import get_connection
        from db.schema import init_database
        from db.scoring_overrides import get_photo_scoring_overrides, set_photo_scoring_override
        from api.routers.albums import remove_photos_from_album, AlbumPhotosRequest

        db_path = str(tmp_path / "multi_album.db")
        init_database(db_path)
        with get_connection(db_path) as conn:
            conn.execute("INSERT INTO albums (id, name, scoring_context) VALUES (1, 'Motorsport', 'motorsport')")
            conn.execute("INSERT INTO albums (id, name, scoring_context) VALUES (2, 'Astro', 'astro')")
            conn.execute("INSERT INTO photos (path) VALUES ('/shared.jpg')")
            conn.executemany(
                "INSERT INTO album_photos (album_id, photo_path, position) VALUES (?, '/shared.jpg', 0)",
                [(1,), (2,)],
            )
            # Album 2 stamped last -- 'source' can only name one of the two albums.
            set_photo_scoring_override(conn, '/shared.jpg', scoring_context='astro', source='album:2')
            conn.commit()

        with get_connection(db_path) as conn:
            with mock.patch(f"{_ALBUMS_MODULE}.get_db", return_value=nullcontext(conn)):
                result = remove_photos_from_album(2, AlbumPhotosRequest(photo_paths=['/shared.jpg']), _EDITION_USER)

            assert result["ok"] is True

            row = conn.execute(
                "SELECT source FROM photo_scoring_overrides WHERE photo_path = '/shared.jpg'"
            ).fetchone()
            assert row["source"] == "album:1"

        overrides = get_photo_scoring_overrides(db_path, paths=['/shared.jpg'])
        # Still a member of album 1, which still declares a context -- re-derived, not cleared.
        assert overrides['/shared.jpg']['scoring_context'] == 'motorsport'

    def test_remove_from_only_declaring_album_clears_as_before(self, tmp_path):
        from db.connection import get_connection
        from db.schema import init_database
        from db.scoring_overrides import get_photo_scoring_overrides, set_photo_scoring_override
        from api.routers.albums import remove_photos_from_album, AlbumPhotosRequest

        db_path = str(tmp_path / "single_album.db")
        init_database(db_path)
        with get_connection(db_path) as conn:
            conn.execute("INSERT INTO albums (id, name, scoring_context) VALUES (1, 'Motorsport', 'motorsport')")
            conn.execute("INSERT INTO photos (path) VALUES ('/a.jpg')")
            conn.execute("INSERT INTO album_photos (album_id, photo_path, position) VALUES (1, '/a.jpg', 0)")
            set_photo_scoring_override(conn, '/a.jpg', scoring_context='motorsport', source='album:1')
            conn.commit()

        with get_connection(db_path) as conn:
            with mock.patch(f"{_ALBUMS_MODULE}.get_db", return_value=nullcontext(conn)):
                remove_photos_from_album(1, AlbumPhotosRequest(photo_paths=['/a.jpg']), _EDITION_USER)

            overrides = get_photo_scoring_overrides(db_path, paths=['/a.jpg'])
        assert overrides == {}


class TestSmartAlbumRemovePhotosIsANoop:
    """DEFECT F4 regression: ``album_photos`` carries no rows for a smart
    album -- membership is resolved live from ``smart_filter_json`` -- so
    DELETE .../photos must not strip scoring-context stamps from photos that
    are (still) members."""

    def test_remove_photos_is_a_noop_for_a_smart_album(self, tmp_path):
        from db.connection import get_connection
        from db.schema import init_database
        from db.scoring_overrides import get_photo_scoring_overrides, set_photo_scoring_override
        from api.routers.albums import remove_photos_from_album, AlbumPhotosRequest

        db_path = str(tmp_path / "smart_remove.db")
        init_database(db_path)
        with get_connection(db_path) as conn:
            conn.execute(
                "INSERT INTO albums (id, name, is_smart, smart_filter_json, scoring_context) "
                "VALUES (1, 'Wildlife', 1, '{\"category\": \"wildlife\"}', 'action_stage')"
            )
            conn.execute("INSERT INTO photos (path, category) VALUES ('/w1.jpg', 'wildlife')")
            set_photo_scoring_override(conn, '/w1.jpg', scoring_context='action_stage', source='album:1')
            conn.commit()

        with get_connection(db_path) as conn:
            with (
                mock.patch(f"{_ALBUMS_MODULE}.get_db", return_value=nullcontext(conn)),
                mock.patch("api.db_helpers.is_multi_user_enabled", return_value=False),
                mock.patch("api.db_helpers.VIEWER_CONFIG", {"password": ""}),
            ):
                result = remove_photos_from_album(1, AlbumPhotosRequest(photo_paths=['/w1.jpg']), _EDITION_USER)

            overrides = get_photo_scoring_overrides(conn, paths=['/w1.jpg'])
        assert result["ok"] is True
        assert overrides['/w1.jpg']['scoring_context'] == 'action_stage'


class TestAlbumScoringContextChunksLargeMemberSets:
    """DEFECT F5 regression: every ``IN (?, ?, ...)`` query built from a
    member list must be chunked under SQLite's bound-variable limit, like
    every other bulk lookup in the codebase (``select_in_chunks``). Exercised
    with 2200 members -- more than double ``select_in_chunks``'s default
    900-per-chunk -- so a chunk-boundary bug (e.g. only the last chunk's
    results surviving) would be caught, independent of exactly where a given
    SQLite build's variable ceiling sits."""

    _COUNT = 2200

    def test_set_and_clear_handle_thousands_of_members(self, tmp_path):
        from db.connection import get_connection
        from db.schema import init_database
        from db.scoring_overrides import get_photo_scoring_overrides
        from api.routers.albums import (
            set_album_scoring_context, clear_album_scoring_context, AlbumScoringContextRequest,
        )

        db_path = str(tmp_path / "chunking.db")
        init_database(db_path)
        paths = [f'/bulk_{i}.jpg' for i in range(self._COUNT)]
        with get_connection(db_path) as conn:
            conn.execute("INSERT INTO albums (id, name) VALUES (1, 'Bulk')")
            conn.executemany("INSERT INTO photos (path) VALUES (?)", [(p,) for p in paths])
            conn.executemany(
                "INSERT INTO album_photos (album_id, photo_path, position) VALUES (1, ?, ?)",
                [(p, i) for i, p in enumerate(paths)],
            )
            conn.commit()

        mock_config = mock.MagicMock()
        mock_config.get_scoring_contexts.return_value = {"default": {}, "action_stage": {}}

        with get_connection(db_path) as conn:
            with (
                mock.patch.dict("sys.modules", {"config": mock.MagicMock(ScoringConfig=lambda *a, **k: mock_config)}),
                mock.patch(f"{_ALBUMS_MODULE}.get_db", return_value=nullcontext(conn)),
                mock.patch("api.db_helpers.is_multi_user_enabled", return_value=False),
                mock.patch("api.db_helpers.VIEWER_CONFIG", {"password": ""}),
            ):
                set_result = set_album_scoring_context(
                    1, AlbumScoringContextRequest(scoring_context="action_stage"), _EDITION_USER
                )

        assert set_result["updated"] == self._COUNT

        overrides = get_photo_scoring_overrides(db_path, paths=paths)
        assert len(overrides) == self._COUNT
        assert all(o['scoring_context'] == 'action_stage' for o in overrides.values())

        with get_connection(db_path) as conn:
            with (
                mock.patch(f"{_ALBUMS_MODULE}.get_db", return_value=nullcontext(conn)),
                mock.patch("api.db_helpers.is_multi_user_enabled", return_value=False),
                mock.patch("api.db_helpers.VIEWER_CONFIG", {"password": ""}),
            ):
                clear_result = clear_album_scoring_context(1, _EDITION_USER)

        assert clear_result["cleared"] == self._COUNT
        assert get_photo_scoring_overrides(db_path, paths=paths) == {}



class TestSmartAlbumCoverAppliesHideDefaults:
    """A smart album's cover must obey the same hide toggles its gallery does.

    `smart_filter_json` deliberately carries only the filter the user chose and
    excludes the view toggles, so the cover query has to re-supply them from
    `viewer.defaults`. A toggle missing from that list reads as "do not hide",
    and the cover becomes a photo the album's own gallery view is hiding --
    which is exactly how `hide_brackets` shipped.
    """

    _DEFAULTS = {
        'hide_blinks': True, 'hide_bursts': True, 'hide_duplicates': True,
        'hide_brackets': True, 'hide_rejected': True, 'sort': 'aggregate',
    }

    def _filters_passed_to_the_gallery(self, saved_filters):
        import json as _json

        from api.routers.albums import _compute_smart_album_cover

        conn = mock.MagicMock()
        conn.execute.return_value.fetchone.return_value = None
        album = _make_album_row(is_smart=1, smart_filter_json=_json.dumps(saved_filters))
        with (
            mock.patch("api.routers.gallery._build_gallery_where",
                       return_value=([], [])) as build_where,
            mock.patch(f"{_ALBUMS_MODULE}.VIEWER_CONFIG", {'defaults': self._DEFAULTS}),
        ):
            _compute_smart_album_cover(conn, album)
        return build_where.call_args[0][0]

    def test_every_configured_hide_toggle_reaches_the_cover_query(self):
        passed = self._filters_passed_to_the_gallery({'sort': 'aggregate'})
        expected = {k for k in self._DEFAULTS if k.startswith('hide_')}
        # Structural on purpose: a hide toggle added to viewer.defaults and not
        # to the cover's default list is the regression this guards, and naming
        # the keys individually would not catch the next one.
        assert expected <= set(passed)

    def test_a_toggle_defaulting_to_true_is_applied_not_dropped(self):
        passed = self._filters_passed_to_the_gallery({'sort': 'aggregate'})
        assert passed['hide_brackets'] == '1'

    def test_an_explicit_choice_in_the_saved_filter_wins(self):
        passed = self._filters_passed_to_the_gallery(
            {'sort': 'aggregate', 'hide_brackets': '0'})
        assert passed['hide_brackets'] == '0'
