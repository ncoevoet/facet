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


def _jpeg(rgb) -> bytes:
    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (8, 8), rgb).save(buf, format="JPEG")
    return buf.getvalue()


# Every stored BLOB is a different image on purpose. These routes were seeded
# with one shared JPEG, which made a wrong-row leak — Bob's crop served for
# Alice's face, or a photo thumbnail served as a person's — satisfy every
# assertion in the file that exists to prevent exactly that.
ALICE_THUMB = _jpeg((10, 20, 30))
BOB_THUMB = _jpeg((40, 50, 60))
ALICE_FACE = _jpeg((70, 80, 90))
BOB_FACE = _jpeg((100, 110, 120))
ALICE_PERSON = _jpeg((130, 140, 150))
BOB_PERSON = _jpeg((160, 170, 180))

_ALL_BLOBS = (ALICE_THUMB, BOB_THUMB, ALICE_FACE, BOB_FACE, ALICE_PERSON, BOB_PERSON)


def _expect_image(resp, expected: bytes, what: str) -> None:
    """Assert a pixel route returned 200 carrying exactly the row it was asked for."""
    assert resp.status_code == 200, f"{what}: expected 200, got {resp.status_code}"
    assert resp.content == expected, f"{what}: served another row's bytes"


_SCHEMA = """
    CREATE TABLE photos (path TEXT PRIMARY KEY, thumbnail BLOB, sequence_kind TEXT);
    CREATE TABLE persons (id INTEGER PRIMARY KEY, face_thumbnail BLOB,
                          representative_face_id INTEGER);
    CREATE TABLE faces (id INTEGER PRIMARY KEY, photo_path TEXT, person_id INTEGER,
                        face_thumbnail BLOB, bbox_x1 REAL, bbox_y1 REAL,
                        bbox_x2 REAL, bbox_y2 REAL);
"""


@pytest.fixture()
def db_path(tmp_path):
    path = str(tmp_path / "thumbs.db")
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    conn.executemany("INSERT INTO photos (path, thumbnail) VALUES (?, ?)",
                     [(ALICE_PHOTO, ALICE_THUMB), (BOB_PHOTO, BOB_THUMB)])
    conn.executemany(
        "INSERT INTO faces VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [(1, ALICE_PHOTO, 1, ALICE_FACE, 0, 0, 10, 10),
         (2, BOB_PHOTO, 2, BOB_FACE, 0, 0, 10, 10)],
    )
    conn.executemany("INSERT INTO persons VALUES (?, ?, ?)",
                     [(1, ALICE_PERSON, 1), (2, BOB_PERSON, 2)])
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
            _expect_image(client.get("/thumbnail", params={"path": ALICE_PHOTO}),
                          ALICE_THUMB, "/thumbnail alice")
            # /image falls back to the stored thumbnail once the disk path can't
            # be resolved, proving the request cleared the visibility gate.
            _expect_image(
                client.get("/image", params={"path": ALICE_PHOTO, "fallback": "thumbnail"}),
                ALICE_THUMB, "/image alice fallback")
            _expect_image(client.get("/face_thumbnail/1"), ALICE_FACE, "/face_thumbnail/1")
            _expect_image(client.get("/person_thumbnail/1"), ALICE_PERSON, "/person_thumbnail/1")


# --- default open single-user deployment (no password, no multi-user) ------

class TestOpenSingleUserMode:
    """The default install (no ``viewer.password``, no ``users`` block) must
    stay fully open to an anonymous caller — this is the common case and the
    one most likely to regress silently while hardening the auth surface for
    multi-user/password-locked deployments.
    """

    def test_anonymous_allowed_all_pixel_routes(self, db_path):
        with _env(db_path, None, multi_user=False, password="") as client:
            _expect_image(client.get("/thumbnail", params={"path": ALICE_PHOTO}),
                          ALICE_THUMB, "/thumbnail alice")
            _expect_image(
                client.get("/image", params={"path": ALICE_PHOTO, "fallback": "thumbnail"}),
                ALICE_THUMB, "/image alice fallback")
            _expect_image(client.get("/face_thumbnail/1"), ALICE_FACE, "/face_thumbnail/1")
            _expect_image(client.get("/person_thumbnail/1"), ALICE_PERSON, "/person_thumbnail/1")


# --- F4': multi-user per-directory isolation --------------------------------

class TestMultiUserIsolation:
    def test_user_sees_own_denied_foreign(self, db_path):
        alice = CurrentUser(user_id="alice", role="user")
        dirs = {"alice": ["/photos/alice"], "bob": ["/photos/bob"]}
        with _env(db_path, alice, multi_user=True, dirs_map=dirs) as client:
            # Own directory: visible, and carrying Alice's own rows rather than
            # merely some 200 — the isolation this suite exists to pin is about
            # WHICH bytes are served, not whether a response arrives.
            _expect_image(client.get("/thumbnail", params={"path": ALICE_PHOTO}),
                          ALICE_THUMB, "/thumbnail alice")
            _expect_image(client.get("/face_thumbnail/1"), ALICE_FACE, "/face_thumbnail/1")
            _expect_image(client.get("/person_thumbnail/1"), ALICE_PERSON, "/person_thumbnail/1")
            # Foreign directory: denied.
            assert client.get("/thumbnail", params={"path": BOB_PHOTO}).status_code == 404
            assert client.get(
                "/image", params={"path": BOB_PHOTO, "fallback": "thumbnail"}
            ).status_code == 404
            assert client.get("/face_thumbnail/2").status_code == 404
            assert client.get("/person_thumbnail/2").status_code == 404


# --- fixture integrity ------------------------------------------------------

def test_fixture_blobs_are_all_distinct():
    """Every seeded BLOB must differ, or the content assertions above go vacuous.

    This is the property that failed before: six rows sharing one JPEG made
    "served the wrong row" indistinguishable from "served the right row".
    """
    assert len(set(_ALL_BLOBS)) == len(_ALL_BLOBS)
