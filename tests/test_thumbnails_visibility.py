"""Visibility enforcement on the thumbnail/image/face routers (F3' + F4').

The thumbnail router used to bypass the single-user viewer-password lock
(``/thumbnail``, ``/image``) and the multi-user per-directory isolation
(``/face_thumbnail``, ``/person_thumbnail``). These tests pin that every pixel
route now routes through the central ``get_visibility_clause`` mechanism:

* single-user password lock — an unauthenticated caller sees nothing, an
  authenticated one sees everything;
* multi-user isolation — a user only sees photos/faces/persons in their own
  directories.
"""

import sqlite3
from contextlib import contextmanager
from io import BytesIO
from unittest import mock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api import create_app
from api.auth import CurrentUser, get_optional_user
from api.routers.thumbnails import _get_face_thumbnail_data

_HELPERS = "api.db_helpers"
_ROUTER = "api.routers.thumbnails"

ALICE_PHOTO = "/photos/alice/a.jpg"
BOB_PHOTO = "/photos/bob/b.jpg"


def _jpeg() -> bytes:
    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (8, 8), (10, 20, 30)).save(buf, format="JPEG")
    return buf.getvalue()


_SCHEMA = """
    CREATE TABLE photos (path TEXT PRIMARY KEY, thumbnail BLOB);
    CREATE TABLE persons (id INTEGER PRIMARY KEY, face_thumbnail BLOB,
                          representative_face_id INTEGER);
    CREATE TABLE faces (id INTEGER PRIMARY KEY, photo_path TEXT, person_id INTEGER,
                        face_thumbnail BLOB, bbox_x1 REAL, bbox_y1 REAL,
                        bbox_x2 REAL, bbox_y2 REAL);
"""


@pytest.fixture()
def db_path(tmp_path):
    jpeg = _jpeg()
    path = str(tmp_path / "thumbs.db")
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    conn.executemany("INSERT INTO photos VALUES (?, ?)",
                     [(ALICE_PHOTO, jpeg), (BOB_PHOTO, jpeg)])
    conn.executemany(
        "INSERT INTO faces VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [(1, ALICE_PHOTO, 1, jpeg, 0, 0, 10, 10),
         (2, BOB_PHOTO, 2, jpeg, 0, 0, 10, 10)],
    )
    conn.executemany("INSERT INTO persons VALUES (?, ?, ?)",
                     [(1, jpeg, 1), (2, jpeg, 2)])
    conn.commit()
    conn.close()
    _get_face_thumbnail_data.cache_clear()
    return path


def _connect(path):
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    return c


def _db_cm(path):
    @contextmanager
    def _cm():
        c = _connect(path)
        try:
            yield c
        finally:
            c.close()
    return _cm


@contextmanager
def _env(db_path, user, *, multi_user, password="", dirs_map=None):
    app = create_app()
    app.dependency_overrides[get_optional_user] = lambda: user
    dirs_map = dirs_map or {}
    patches = [
        mock.patch(f"{_ROUTER}.get_db", _db_cm(db_path)),
        mock.patch(f"{_ROUTER}.get_db_connection", lambda: _connect(db_path)),
        mock.patch(f"{_ROUTER}.resolve_photo_disk_path",
                   side_effect=HTTPException(status_code=404, detail="x")),
        mock.patch(f"{_HELPERS}.is_multi_user_enabled", return_value=multi_user),
        mock.patch(f"{_HELPERS}.get_user_directories",
                   side_effect=lambda uid: dirs_map.get(uid, [])),
        mock.patch.dict(f"{_HELPERS}.VIEWER_CONFIG", {"password": password}, clear=False),
    ]
    for p in patches:
        p.start()
    try:
        yield TestClient(app)
    finally:
        for p in patches:
            p.stop()
        app.dependency_overrides.clear()
        _get_face_thumbnail_data.cache_clear()


# --- F3': single-user viewer-password lock ---------------------------------

class TestPasswordLock:
    def test_anonymous_denied_all_pixel_routes(self, db_path):
        with _env(db_path, None, multi_user=False, password="secret") as client:
            assert client.get("/thumbnail", params={"path": ALICE_PHOTO}).status_code == 404
            assert client.get(
                "/image", params={"path": ALICE_PHOTO, "fallback": "thumbnail"}
            ).status_code == 404
            assert client.get("/face_thumbnail/1").status_code == 404
            assert client.get("/person_thumbnail/1").status_code == 404

    def test_authenticated_allowed(self, db_path):
        user = CurrentUser(user_id="owner")
        with _env(db_path, user, multi_user=False, password="secret") as client:
            assert client.get("/thumbnail", params={"path": ALICE_PHOTO}).status_code == 200
            # /image falls back to the stored thumbnail once the disk path can't
            # be resolved, proving the request cleared the visibility gate.
            assert client.get(
                "/image", params={"path": ALICE_PHOTO, "fallback": "thumbnail"}
            ).status_code == 200
            assert client.get("/face_thumbnail/1").status_code == 200
            assert client.get("/person_thumbnail/1").status_code == 200


# --- default open single-user deployment (no password, no multi-user) ------

class TestOpenSingleUserMode:
    """The default install (no ``viewer.password``, no ``users`` block) must
    stay fully open to an anonymous caller — this is the common case and the
    one most likely to regress silently while hardening the auth surface for
    multi-user/password-locked deployments.
    """

    def test_anonymous_allowed_all_pixel_routes(self, db_path):
        with _env(db_path, None, multi_user=False, password="") as client:
            assert client.get("/thumbnail", params={"path": ALICE_PHOTO}).status_code == 200
            assert client.get(
                "/image", params={"path": ALICE_PHOTO, "fallback": "thumbnail"}
            ).status_code == 200
            assert client.get("/face_thumbnail/1").status_code == 200
            assert client.get("/person_thumbnail/1").status_code == 200


# --- F4': multi-user per-directory isolation --------------------------------

class TestMultiUserIsolation:
    def test_user_sees_own_denied_foreign(self, db_path):
        alice = CurrentUser(user_id="alice", role="user")
        dirs = {"alice": ["/photos/alice"], "bob": ["/photos/bob"]}
        with _env(db_path, alice, multi_user=True, dirs_map=dirs) as client:
            # Own directory: visible.
            assert client.get("/thumbnail", params={"path": ALICE_PHOTO}).status_code == 200
            assert client.get("/face_thumbnail/1").status_code == 200
            assert client.get("/person_thumbnail/1").status_code == 200
            # Foreign directory: denied.
            assert client.get("/thumbnail", params={"path": BOB_PHOTO}).status_code == 404
            assert client.get(
                "/image", params={"path": BOB_PHOTO, "fallback": "thumbnail"}
            ).status_code == 404
            assert client.get("/face_thumbnail/2").status_code == 404
            assert client.get("/person_thumbnail/2").status_code == 404
