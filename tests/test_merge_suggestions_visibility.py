"""Multi-user directory isolation on merge suggestions (F4').

Merge suggestions pooled persons globally, so a user could be offered (and
thereby learn about) clusters living entirely in another user's directories.
These tests pin that in multi-user mode a suggestion only survives when both of
its persons are visible to the caller.
"""

import sqlite3
from contextlib import contextmanager
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from api import create_app
from api.auth import CurrentUser, require_authenticated

_HELPERS = "api.db_helpers"
_ROUTER = "api.routers.merge_suggestions"

ALICE_PHOTO = "/photos/alice/a.jpg"
BOB_PHOTO = "/photos/bob/b.jpg"

_SCHEMA = """
    CREATE TABLE photos (path TEXT PRIMARY KEY);
    CREATE TABLE faces (id INTEGER PRIMARY KEY, person_id INTEGER, photo_path TEXT);
    CREATE TABLE rejected_merge_suggestions (person_a_id INTEGER, person_b_id INTEGER);
"""

_GROUPS = [
    {"avg_similarity": 0.9,
     "persons": [{"id": 1, "name": "A", "face_count": 3},
                 {"id": 2, "name": "B", "face_count": 3}]},
    {"avg_similarity": 0.8,
     "persons": [{"id": 1, "name": "A", "face_count": 3},
                 {"id": 3, "name": "C", "face_count": 3}]},
]


@pytest.fixture()
def db_path(tmp_path):
    path = str(tmp_path / "merge_vis.db")
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    conn.executemany("INSERT INTO photos VALUES (?)", [(ALICE_PHOTO,), (BOB_PHOTO,)])
    conn.executemany(
        "INSERT INTO faces VALUES (?, ?, ?)",
        [(1, 1, ALICE_PHOTO), (2, 2, BOB_PHOTO), (3, 3, ALICE_PHOTO)],
    )
    conn.commit()
    conn.close()
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


def _client(db_path, user, multi_user):
    dirs = {"alice": ["/photos/alice"], "bob": ["/photos/bob"]}
    app = create_app()
    app.dependency_overrides[require_authenticated] = lambda: user
    patches = [
        mock.patch(f"{_ROUTER}.get_db", _db_cm(db_path)),
        mock.patch(f"{_ROUTER}.is_multi_user_enabled", return_value=multi_user),
        mock.patch("faces.get_merge_groups", return_value=_GROUPS),
        mock.patch(f"{_HELPERS}.is_multi_user_enabled", return_value=multi_user),
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


def _pairs(body):
    return {tuple(sorted((s["person1"]["id"], s["person2"]["id"])))
            for s in body["suggestions"]}


def test_foreign_person_pair_dropped(db_path):
    """Alice loses the (1,2) pair — person 2 is in Bob's directory."""
    alice = CurrentUser(user_id="alice", role="user")
    client, app, patches = _client(db_path, alice, multi_user=True)
    try:
        resp = client.get("/api/merge_suggestions")
    finally:
        _teardown(app, patches)
    assert resp.status_code == 200
    assert _pairs(resp.json()) == {(1, 3)}


def test_single_user_unscoped(db_path):
    """Single-user mode keeps every suggested pair (no directory scoping)."""
    user = CurrentUser(user_id="owner", role="user")
    client, app, patches = _client(db_path, user, multi_user=False)
    try:
        resp = client.get("/api/merge_suggestions")
    finally:
        _teardown(app, patches)
    assert resp.status_code == 200
    assert _pairs(resp.json()) == {(1, 2), (1, 3)}
