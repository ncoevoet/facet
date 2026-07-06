"""Tests for POST /api/persons — create a person from the viewer.

Covers the create-from-UI endpoint (api/routers/persons.py::api_create_person):
happy path with face attachment, name validation, unknown faces, the edition
gate, reassignment of faces that already belong to another person, and
multi-user directory isolation (an edition user scoped to a subset of
directories cannot pull foreign faces into a new person).

Follows the real-temp-DB pattern from tests/test_persons_split_hide.py: the
session DB (``DB_PATH``) is shared, so every test cleans up its own rows.
"""

import os
import sqlite3
from unittest import mock

_HELPERS = "api.db_helpers"
_EMBEDDING = sqlite3.Binary(b"\x00\x00\x00\x00")


def _db():
    conn = sqlite3.connect(os.environ["DB_PATH"])
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def _seed_faces(conn, paths, person_id=None):
    """Insert one face per photo path (person_id NULL = unassigned by default).

    Returns the list of face ids created, in path order.
    """
    face_ids = []
    for path in paths:
        conn.execute("INSERT OR IGNORE INTO photos(path) VALUES (?)", (path,))
        cur = conn.execute(
            "INSERT INTO faces(photo_path, face_index, embedding, person_id) "
            "VALUES (?, 0, ?, ?)",
            (path, _EMBEDDING, person_id),
        )
        face_ids.append(cur.lastrowid)
    return face_ids


def _seed_person(conn, pid, name="Existing"):
    conn.execute("DELETE FROM persons WHERE id = ?", (pid,))
    conn.execute(
        "INSERT INTO persons(id, name, auto_clustered, face_count) VALUES (?, ?, 0, 0)",
        (pid, name),
    )


def _cleanup(path_prefix, person_ids):
    conn = _db()
    conn.execute("DELETE FROM faces WHERE photo_path LIKE ?", (path_prefix + "%",))
    conn.execute("DELETE FROM photos WHERE path LIKE ?", (path_prefix + "%",))
    if person_ids:
        placeholders = ",".join("?" * len(person_ids))
        conn.execute(f"DELETE FROM persons WHERE id IN ({placeholders})", person_ids)
    conn.commit()
    conn.close()


class TestCreatePerson:
    def test_create_with_faces_happy_path(self, edition_client):
        prefix = "create_happy/"
        new_id = None
        try:
            conn = _db()
            fids = _seed_faces(conn, [prefix + f"{i}.jpg" for i in range(2)])
            conn.commit()
            conn.close()

            resp = edition_client.post(
                "/api/persons", json={"name": "  Alice  ", "face_ids": fids}
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()
            new_id = body["id"]
            assert body["name"] == "Alice"
            assert body["face_count"] == 2

            conn = _db()
            row = conn.execute(
                "SELECT name, auto_clustered, face_count FROM persons WHERE id = ?",
                (new_id,),
            ).fetchone()
            assert row["name"] == "Alice"
            assert row["auto_clustered"] == 0
            assert row["face_count"] == 2
            owners = [
                r["person_id"]
                for r in conn.execute(
                    f"SELECT person_id FROM faces WHERE id IN ({','.join('?' * len(fids))})",
                    fids,
                ).fetchall()
            ]
            assert all(o == new_id for o in owners)
            conn.close()
        finally:
            _cleanup(prefix, [new_id] if new_id else [])

    def test_create_without_faces(self, edition_client):
        new_id = None
        try:
            resp = edition_client.post("/api/persons", json={"name": "Bob"})
            assert resp.status_code == 200, resp.text
            body = resp.json()
            new_id = body["id"]
            assert body["name"] == "Bob"
            assert body["face_count"] == 0
        finally:
            _cleanup("create_none/", [new_id] if new_id else [])

    def test_empty_name_rejected(self, edition_client):
        resp = edition_client.post("/api/persons", json={"name": "   ", "face_ids": []})
        assert resp.status_code == 400
        assert "name" in resp.json()["detail"].lower()

    def test_unknown_face_404(self, edition_client):
        resp = edition_client.post(
            "/api/persons", json={"name": "Ghost", "face_ids": [999999999]}
        )
        assert resp.status_code == 404
        conn = _db()
        exists = conn.execute(
            "SELECT 1 FROM persons WHERE name = 'Ghost'"
        ).fetchone()
        conn.close()
        assert exists is None

    def test_reassigns_face_from_other_person(self, edition_client):
        prefix = "create_reassign/"
        new_id = None
        try:
            conn = _db()
            _seed_person(conn, 9401, name="Old")
            fids = _seed_faces(
                conn, [prefix + f"{i}.jpg" for i in range(2)], person_id=9401
            )
            conn.execute("UPDATE persons SET face_count = 2 WHERE id = 9401")
            conn.commit()
            conn.close()

            resp = edition_client.post(
                "/api/persons", json={"name": "New", "face_ids": [fids[0]]}
            )
            assert resp.status_code == 200, resp.text
            new_id = resp.json()["id"]
            assert resp.json()["face_count"] == 1

            conn = _db()
            moved = conn.execute(
                "SELECT person_id FROM faces WHERE id = ?", (fids[0],)
            ).fetchone()["person_id"]
            assert moved == new_id
            old_count = conn.execute(
                "SELECT face_count FROM persons WHERE id = 9401"
            ).fetchone()["face_count"]
            assert old_count == 1
            conn.close()
        finally:
            _cleanup(prefix, [9401] + ([new_id] if new_id else []))

    def test_edition_gate_forbids_regular_user(self, regular_client):
        resp = regular_client.post("/api/persons", json={"name": "NoAccess"})
        assert resp.status_code == 403


class TestCreatePersonVisibility:
    """Multi-user directory isolation on the create surface.

    An edition user scoped to ``/vis_alice`` must not be able to attach a face
    that lives under another user's directory.
    """

    def _patches(self, caller_dirs):
        return [
            mock.patch(f"{_HELPERS}.is_multi_user_enabled", return_value=True),
            mock.patch(
                f"{_HELPERS}.get_user_directories",
                side_effect=lambda uid: caller_dirs,
            ),
        ]

    def test_foreign_face_denied(self, edition_client):
        prefix = "/vis_bob/"
        try:
            conn = _db()
            fids = _seed_faces(conn, [prefix + "y.jpg"])
            conn.commit()
            conn.close()

            patches = self._patches(["/vis_alice"])
            for p in patches:
                p.start()
            try:
                resp = edition_client.post(
                    "/api/persons", json={"name": "Intruder", "face_ids": fids}
                )
            finally:
                for p in patches:
                    p.stop()

            assert resp.status_code == 404
            conn = _db()
            leaked = conn.execute(
                "SELECT 1 FROM persons WHERE name = 'Intruder'"
            ).fetchone()
            conn.close()
            assert leaked is None
        finally:
            _cleanup(prefix, [])

    def test_own_face_allowed(self, edition_client):
        prefix = "/vis_alice/"
        new_id = None
        try:
            conn = _db()
            fids = _seed_faces(conn, [prefix + "x.jpg"])
            conn.commit()
            conn.close()

            patches = self._patches(["/vis_alice"])
            for p in patches:
                p.start()
            try:
                resp = edition_client.post(
                    "/api/persons", json={"name": "Owner", "face_ids": fids}
                )
            finally:
                for p in patches:
                    p.stop()

            assert resp.status_code == 200, resp.text
            new_id = resp.json()["id"]
            assert resp.json()["face_count"] == 1
        finally:
            _cleanup(prefix, [new_id] if new_id else [])
