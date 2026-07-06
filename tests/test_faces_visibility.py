"""Multi-user directory isolation on the faces read surface (F4').

``/api/photo/faces`` and ``/api/person/{id}/faces`` used to return face/person
data for any path or cluster regardless of the caller's directory scope. These
tests pin that in multi-user mode a user only sees faces in photos within their
own directories, while single-user access is unchanged.
"""

import sqlite3
from contextlib import asynccontextmanager
from unittest import mock

import aiosqlite
import pytest
from fastapi.testclient import TestClient

from api import create_app
from api.auth import CurrentUser, require_auth

_HELPERS = "api.db_helpers"

ALICE_PHOTO = "/photos/alice/a.jpg"
BOB_PHOTO = "/photos/bob/b.jpg"

_SCHEMA = """
    CREATE TABLE photos (path TEXT PRIMARY KEY, aggregate REAL);
    CREATE TABLE persons (id INTEGER PRIMARY KEY, name TEXT);
    CREATE TABLE faces (id INTEGER PRIMARY KEY, photo_path TEXT, face_index INTEGER,
                        person_id INTEGER, bbox_x1 REAL, bbox_y1 REAL,
                        bbox_x2 REAL, bbox_y2 REAL);
"""


@pytest.fixture()
def db_path(tmp_path):
    path = str(tmp_path / "faces_vis.db")
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    conn.executemany("INSERT INTO photos VALUES (?, ?)",
                     [(ALICE_PHOTO, 9.0), (BOB_PHOTO, 3.0)])
    conn.executemany("INSERT INTO persons VALUES (?, ?)", [(1, "Alice"), (2, "Bob")])
    conn.executemany(
        "INSERT INTO faces VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [(1, ALICE_PHOTO, 0, 1, 0, 0, 5, 5),
         (2, BOB_PHOTO, 0, 2, 0, 0, 5, 5)],
    )
    conn.commit()
    conn.close()
    return path


def _async_factory(db_path):
    @asynccontextmanager
    async def factory():
        c = await aiosqlite.connect(db_path)
        c.row_factory = aiosqlite.Row
        try:
            yield c
        finally:
            await c.close()
    return factory


def _client(db_path, user):
    dirs = {"alice": ["/photos/alice"], "bob": ["/photos/bob"]}
    app = create_app()
    app.dependency_overrides[require_auth] = lambda: user
    patches = [
        mock.patch("api.routers.faces.get_async_db", _async_factory(db_path)),
        mock.patch(f"{_HELPERS}.is_multi_user_enabled", return_value=True),
        mock.patch(f"{_HELPERS}.get_user_directories",
                   side_effect=lambda uid: dirs.get(uid, [])),
    ]
    for p in patches:
        p.start()
    return TestClient(app), app, patches


def _teardown(app, patches):
    for p in patches:
        p.stop()
    app.dependency_overrides.clear()


class TestPhotoFacesIsolation:
    def test_foreign_path_returns_empty(self, db_path):
        alice = CurrentUser(user_id="alice", role="user")
        client, app, patches = _client(db_path, alice)
        try:
            resp = client.get("/api/photo/faces", params={"path": BOB_PHOTO})
        finally:
            _teardown(app, patches)
        assert resp.status_code == 200
        assert resp.json()["faces"] == []

    def test_own_path_returns_faces(self, db_path):
        alice = CurrentUser(user_id="alice", role="user")
        client, app, patches = _client(db_path, alice)
        try:
            resp = client.get("/api/photo/faces", params={"path": ALICE_PHOTO})
        finally:
            _teardown(app, patches)
        assert resp.status_code == 200
        assert [f["id"] for f in resp.json()["faces"]] == [1]


class TestPersonFacesIsolation:
    def test_foreign_person_faces_hidden(self, db_path):
        """Alice sees none of Bob's cluster (all faces in Bob's directory)."""
        alice = CurrentUser(user_id="alice", role="user")
        client, app, patches = _client(db_path, alice)
        try:
            resp = client.get("/api/person/2/faces")
        finally:
            _teardown(app, patches)
        assert resp.status_code == 200
        assert resp.json()["faces"] == []

    def test_own_person_faces_visible(self, db_path):
        alice = CurrentUser(user_id="alice", role="user")
        client, app, patches = _client(db_path, alice)
        try:
            resp = client.get("/api/person/1/faces")
        finally:
            _teardown(app, patches)
        assert resp.status_code == 200
        assert [f["id"] for f in resp.json()["faces"]] == [1]
