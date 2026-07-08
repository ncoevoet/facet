"""Multi-user directory isolation on the persons list surface (F4').

``/api/persons`` and ``/api/persons/needs_naming`` used to expose every person
cluster globally, leaking foreign users' photo paths. These tests pin that in
multi-user mode the lists only surface persons that have at least one face in a
photo within the caller's directories.
"""

import sqlite3
from contextlib import asynccontextmanager
from unittest import mock

import aiosqlite
import pytest
from fastapi.testclient import TestClient

from api import create_app
from api.auth import CurrentUser, require_authenticated

_HELPERS = "api.db_helpers"

ALICE_PHOTO = "/photos/alice/a.jpg"
BOB_PHOTO = "/photos/bob/b.jpg"

_SCHEMA = """
    CREATE TABLE photos (path TEXT PRIMARY KEY, eye_sharpness REAL, face_quality REAL);
    CREATE TABLE persons (id INTEGER PRIMARY KEY, name TEXT, representative_face_id INTEGER,
                          face_count INTEGER, is_hidden INTEGER DEFAULT 0,
                          face_thumbnail BLOB, auto_clustered INTEGER DEFAULT 0);
    CREATE TABLE faces (id INTEGER PRIMARY KEY, photo_path TEXT, person_id INTEGER);
"""


@pytest.fixture()
def db_path(tmp_path):
    path = str(tmp_path / "persons_vis.db")
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    conn.executemany("INSERT INTO photos VALUES (?, ?, ?)",
                     [(ALICE_PHOTO, 8.0, 7.0), (BOB_PHOTO, 8.0, 7.0)])
    conn.executemany(
        "INSERT INTO persons (id, name, representative_face_id, face_count, "
        "is_hidden, auto_clustered) VALUES (?, ?, ?, ?, 0, ?)",
        [
            (1, "Alice", 1, 1, 0),
            (2, "Bob", 2, 1, 0),
            (3, None, 3, 5, 1),   # unnamed auto-cluster in Alice's dir
            (4, None, 4, 5, 1),   # unnamed auto-cluster in Bob's dir
        ],
    )
    conn.executemany(
        "INSERT INTO faces VALUES (?, ?, ?)",
        [(1, ALICE_PHOTO, 1), (2, BOB_PHOTO, 2),
         (3, ALICE_PHOTO, 3), (4, BOB_PHOTO, 4)],
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
    app.dependency_overrides[require_authenticated] = lambda: user
    patches = [
        mock.patch("api.routers.persons.get_async_db", _async_factory(db_path)),
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


class TestPersonsListIsolation:
    def test_alice_sees_only_own_persons(self, db_path):
        alice = CurrentUser(user_id="alice", role="user")
        client, app, patches = _client(db_path, alice)
        try:
            resp = client.get("/api/persons")
        finally:
            _teardown(app, patches)
        assert resp.status_code == 200
        ids = {p["id"] for p in resp.json()["persons"]}
        assert ids == {1, 3}

    def test_bob_sees_only_own_persons(self, db_path):
        bob = CurrentUser(user_id="bob", role="user")
        client, app, patches = _client(db_path, bob)
        try:
            resp = client.get("/api/persons")
        finally:
            _teardown(app, patches)
        assert resp.status_code == 200
        ids = {p["id"] for p in resp.json()["persons"]}
        assert ids == {2, 4}


class TestNeedsNamingIsolation:
    def test_alice_needs_naming_scoped(self, db_path):
        alice = CurrentUser(user_id="alice", role="user")
        client, app, patches = _client(db_path, alice)
        try:
            resp = client.get("/api/persons/needs_naming", params={"min_faces": 1})
        finally:
            _teardown(app, patches)
        assert resp.status_code == 200
        ids = {p["id"] for p in resp.json()["persons"]}
        assert ids == {3}
