"""
Tests for the faces API router — rating, favorites, face assignment.

Uses mock-based approach since face operations are mutations.
"""

import sqlite3
from contextlib import asynccontextmanager, contextmanager
from unittest import mock

import aiosqlite
import pytest
from fastapi.testclient import TestClient

from api import create_app
from api.auth import CurrentUser, require_authenticated


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_AUTH_MODULE = "api.auth"


def _cm(conn):
    """Wrap a mock connection in a context manager compatible with get_db()."""
    @contextmanager
    def _ctx():
        yield conn
    return _ctx


def _make_app_and_client(raise_server_exceptions=True):
    app = create_app()
    client = TestClient(app, raise_server_exceptions=raise_server_exceptions)
    return app, client


def _override_auth_user(app, user):
    """Override auth to return the given user."""
    app.dependency_overrides[require_authenticated] = lambda: user
    return app


# ---------------------------------------------------------------------------
# Real-temp-DB helpers for the async GET endpoints (api_person_faces /
# api_photo_faces). A MagicMock connection is not awaitable, so these GETs
# are exercised against a real aiosqlite-backed temp DB (mirrors test_map.py).
# ---------------------------------------------------------------------------

_FACES_SCHEMA = """
    CREATE TABLE photos (
        path TEXT PRIMARY KEY, aggregate REAL
    );
    CREATE TABLE persons (
        id INTEGER PRIMARY KEY, name TEXT
    );
    CREATE TABLE faces (
        id INTEGER PRIMARY KEY,
        photo_path TEXT, face_index INTEGER, person_id INTEGER,
        bbox_x1 REAL, bbox_y1 REAL, bbox_x2 REAL, bbox_y2 REAL
    );
"""


def _make_faces_db(path, photos=(), persons=(), faces=()):
    conn = sqlite3.connect(path)
    conn.executescript(_FACES_SCHEMA)
    for p in photos:
        conn.execute("INSERT INTO photos (path, aggregate) VALUES (?, ?)", p)
    for pe in persons:
        conn.execute("INSERT INTO persons (id, name) VALUES (?, ?)", pe)
    for f in faces:
        cols = list(f.keys())
        placeholders = ", ".join("?" for _ in cols)
        conn.execute(
            f"INSERT INTO faces ({', '.join(cols)}) VALUES ({placeholders})",
            [f[c] for c in cols],
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


@pytest.fixture()
def auth_client():
    """App + client with require_authenticated overridden to a valid admin user."""
    app = create_app()
    user = CurrentUser(user_id="u1", role="admin", edition_authenticated=True)
    app.dependency_overrides[require_authenticated] = lambda: user
    return app, TestClient(app)


# ---------------------------------------------------------------------------
# GET /api/person/{id}/faces  (async)
# ---------------------------------------------------------------------------

class TestPersonFaces:
    """GET /api/person/{person_id}/faces — read-only, async."""

    def test_returns_faces_for_person_ordered_by_aggregate(self, auth_client, tmp_path):
        app, client = auth_client
        db = str(tmp_path / "person_faces.db")
        _make_faces_db(
            db,
            photos=[("/hi.jpg", 9.0), ("/lo.jpg", 3.0)],
            faces=[
                {"id": 1, "photo_path": "/lo.jpg", "face_index": 0, "person_id": 7,
                 "bbox_x1": 0, "bbox_y1": 0, "bbox_x2": 10, "bbox_y2": 10},
                {"id": 2, "photo_path": "/hi.jpg", "face_index": 0, "person_id": 7,
                 "bbox_x1": 1, "bbox_y1": 1, "bbox_x2": 11, "bbox_y2": 11},
                {"id": 3, "photo_path": "/hi.jpg", "face_index": 0, "person_id": 99,
                 "bbox_x1": 2, "bbox_y1": 2, "bbox_x2": 12, "bbox_y2": 12},
            ],
        )
        with mock.patch("api.routers.faces.get_async_db", _async_conn_factory(db)):
            resp = client.get("/api/person/7/faces")

        assert resp.status_code == 200
        faces = resp.json()["faces"]
        # Only person 7's faces, ordered by photo aggregate DESC (hi.jpg first)
        assert [f["id"] for f in faces] == [2, 1]
        assert faces[0]["photo_path"] == "/hi.jpg"

    def test_returns_empty_for_unknown_person(self, auth_client, tmp_path):
        app, client = auth_client
        db = str(tmp_path / "empty_person.db")
        _make_faces_db(db)
        with mock.patch("api.routers.faces.get_async_db", _async_conn_factory(db)):
            resp = client.get("/api/person/123/faces")

        assert resp.status_code == 200
        assert resp.json()["faces"] == []

    def test_requires_auth(self, tmp_path):
        """Without authentication, returns 401."""
        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", {"password": "secret", "edition_password": "", "features": {}}),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=True),
        ):
            app, client = _make_app_and_client(raise_server_exceptions=False)
            resp = client.get("/api/person/7/faces")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/photo/faces  (async)
# ---------------------------------------------------------------------------

class TestPhotoFaces:
    """GET /api/photo/faces — read-only, async."""

    def test_returns_faces_with_person_name_ordered_by_index(self, auth_client, tmp_path):
        app, client = auth_client
        db = str(tmp_path / "photo_faces.db")
        _make_faces_db(
            db,
            photos=[("/x.jpg", 5.0), ("/other.jpg", 4.0)],
            persons=[(5, "Alice")],
            faces=[
                {"id": 10, "photo_path": "/x.jpg", "face_index": 1, "person_id": 5,
                 "bbox_x1": 0, "bbox_y1": 0, "bbox_x2": 5, "bbox_y2": 5},
                {"id": 11, "photo_path": "/x.jpg", "face_index": 0, "person_id": None,
                 "bbox_x1": 1, "bbox_y1": 1, "bbox_x2": 6, "bbox_y2": 6},
                {"id": 12, "photo_path": "/other.jpg", "face_index": 0, "person_id": 5,
                 "bbox_x1": 2, "bbox_y1": 2, "bbox_x2": 7, "bbox_y2": 7},
            ],
        )
        with mock.patch("api.routers.faces.get_async_db", _async_conn_factory(db)):
            resp = client.get("/api/photo/faces", params={"path": "/x.jpg"})

        assert resp.status_code == 200
        faces = resp.json()["faces"]
        # Only faces in /x.jpg, ordered by face_index ASC
        assert [f["id"] for f in faces] == [11, 10]
        assert faces[0]["person_id"] is None
        assert faces[0]["person_name"] is None
        assert faces[1]["person_id"] == 5
        assert faces[1]["person_name"] == "Alice"

    def test_returns_empty_for_photo_without_faces(self, auth_client, tmp_path):
        app, client = auth_client
        db = str(tmp_path / "no_faces.db")
        _make_faces_db(db)
        with mock.patch("api.routers.faces.get_async_db", _async_conn_factory(db)):
            resp = client.get("/api/photo/faces", params={"path": "/nope.jpg"})

        assert resp.status_code == 200
        assert resp.json()["faces"] == []

    def test_requires_auth(self):
        """Without authentication, returns 401."""
        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", {"password": "secret", "edition_password": "", "features": {}}),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=True),
        ):
            app, client = _make_app_and_client(raise_server_exceptions=False)
            resp = client.get("/api/photo/faces", params={"path": "/x.jpg"})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Set Rating
# ---------------------------------------------------------------------------

class TestSetRating:
    """POST /api/photo/set_rating — star rating (0-5)."""

    def test_set_rating_success(self):
        conn_mock = mock.MagicMock()
        conn_mock.execute.return_value = mock.MagicMock()

        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", {"password": "", "edition_password": "", "features": {}}),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=False),
            mock.patch("api.routers.faces.is_multi_user_enabled", return_value=False),
        ):
            app, client = _make_app_and_client()
            user = CurrentUser(user_id="u1", role="admin", edition_authenticated=True)
            _override_auth_user(app, user)
            with mock.patch("api.routers.faces.get_db", _cm(conn_mock)):
                resp = client.post(
                    "/api/photo/set_rating",
                    json={"photo_path": "/photo.jpg", "rating": 3},
                )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["rating"] == 3

    def test_set_rating_validation(self):
        """Rating outside 0-5 should yield 422 from Pydantic validation."""
        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", {"password": "", "edition_password": "", "features": {}}),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=False),
            mock.patch("api.routers.faces.is_multi_user_enabled", return_value=False),
        ):
            app, client = _make_app_and_client(raise_server_exceptions=False)
            user = CurrentUser(user_id="u1", role="admin", edition_authenticated=True)
            _override_auth_user(app, user)
            resp = client.post(
                "/api/photo/set_rating",
                json={"photo_path": "/photo.jpg", "rating": 6},
            )
        assert resp.status_code == 422

    def test_set_rating_requires_auth(self):
        """Without authentication, set_rating should return 401."""
        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", {"password": "secret", "edition_password": "", "features": {}}),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=True),
        ):
            app, client = _make_app_and_client(raise_server_exceptions=False)
            # No auth override — unauthenticated request
            resp = client.post(
                "/api/photo/set_rating",
                json={"photo_path": "/photo.jpg", "rating": 3},
            )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Toggle Favorite
# ---------------------------------------------------------------------------

class TestToggleFavorite:
    """POST /api/photo/toggle_favorite — toggle favorite flag."""

    def test_toggle_favorite_success(self):
        conn_mock = mock.MagicMock()
        # Simulate existing photo row with is_favorite=0
        row_mock = mock.MagicMock()
        row_mock.__getitem__ = lambda self, key: 0  # is_favorite = 0
        conn_mock.execute.return_value.fetchone.return_value = row_mock

        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", {"password": "", "edition_password": "", "features": {}}),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=False),
            mock.patch("api.routers.faces.is_multi_user_enabled", return_value=False),
        ):
            app, client = _make_app_and_client()
            user = CurrentUser(user_id="u1", role="admin", edition_authenticated=True)
            _override_auth_user(app, user)
            with mock.patch("api.routers.faces.get_db", _cm(conn_mock)):
                resp = client.post(
                    "/api/photo/toggle_favorite",
                    json={"photo_path": "/photo.jpg"},
                )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["is_favorite"] is True
        # Verify UPDATE was called
        calls = [str(c) for c in conn_mock.execute.call_args_list]
        assert any("UPDATE" in c for c in calls)


# ---------------------------------------------------------------------------
# Assign Face
# ---------------------------------------------------------------------------

class TestAssignFace:
    """POST /api/face/{face_id}/assign — assign a face to a person."""

    def test_assign_face_not_found(self):
        conn_mock = mock.MagicMock()
        conn_mock.execute.return_value.fetchone.return_value = None

        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", {"password": "", "edition_password": "", "features": {}}),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=False),
            mock.patch("api.routers.faces.is_multi_user_enabled", return_value=False),
        ):
            app, client = _make_app_and_client(raise_server_exceptions=False)
            user = CurrentUser(user_id="u1", role="admin", edition_authenticated=True)
            _override_auth_user(app, user)
            with mock.patch("api.routers.faces.get_db", _cm(conn_mock)):
                resp = client.post(
                    "/api/face/999/assign",
                    json={"person_id": 1},
                )
        assert resp.status_code == 404

    def test_assign_face_success(self):
        conn_mock = mock.MagicMock()
        # First call: SELECT person_id FROM faces WHERE id = ?
        face_row = mock.MagicMock()
        face_row.__getitem__ = lambda self, key: None  # person_id = None (unassigned)
        conn_mock.execute.return_value.fetchone.return_value = face_row

        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", {"password": "", "edition_password": "", "features": {}}),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=False),
            mock.patch("api.routers.faces.is_multi_user_enabled", return_value=False),
        ):
            app, client = _make_app_and_client()
            user = CurrentUser(user_id="u1", role="admin", edition_authenticated=True)
            _override_auth_user(app, user)
            with mock.patch("api.routers.faces.get_db", _cm(conn_mock)):
                resp = client.post(
                    "/api/face/1/assign",
                    json={"person_id": 5},
                )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_assign_face_repairs_stale_representative(self, tmp_path):
        db = str(tmp_path / "assign_rep.db")
        conn = sqlite3.connect(db, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE photos (path TEXT PRIMARY KEY);
            CREATE TABLE persons (
                id INTEGER PRIMARY KEY, name TEXT,
                representative_face_id INTEGER, face_thumbnail BLOB, face_count INTEGER
            );
            CREATE TABLE faces (
                id INTEGER PRIMARY KEY, photo_path TEXT, person_id INTEGER,
                confidence REAL, face_thumbnail BLOB
            );
        """)
        conn.execute("INSERT INTO photos (path) VALUES ('/a.jpg')")
        conn.execute(
            "INSERT INTO persons (id, name, representative_face_id, face_thumbnail, face_count) "
            "VALUES (1, 'Alice', 10, ?, 2)", (b'F1thumb',)
        )
        conn.execute("INSERT INTO persons (id, name, face_count) VALUES (2, 'Bob', 0)")
        conn.execute(
            "INSERT INTO faces (id, photo_path, person_id, confidence, face_thumbnail) "
            "VALUES (10, '/a.jpg', 1, 0.9, ?)", (b'F1thumb',)
        )
        conn.execute(
            "INSERT INTO faces (id, photo_path, person_id, confidence, face_thumbnail) "
            "VALUES (11, '/a.jpg', 1, 0.8, ?)", (b'F2thumb',)
        )
        conn.commit()

        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", {"password": "", "edition_password": "", "features": {}}),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=False),
            mock.patch("api.routers.faces.is_multi_user_enabled", return_value=False),
        ):
            app, client = _make_app_and_client()
            user = CurrentUser(user_id="u1", role="admin", edition_authenticated=True)
            _override_auth_user(app, user)
            with mock.patch("api.routers.faces.get_db", _cm(conn)):
                resp = client.post("/api/face/10/assign", json={"person_id": 2})

        assert resp.status_code == 200
        alice = conn.execute(
            "SELECT representative_face_id, face_thumbnail FROM persons WHERE id = 1"
        ).fetchone()
        assert alice["representative_face_id"] == 11
        assert alice["face_thumbnail"] == b'F2thumb'
        conn.close()
