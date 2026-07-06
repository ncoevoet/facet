"""Multi-user directory isolation on the face-assignment write surface.

The security pass on the read side (test_faces_visibility.py /
test_persons_visibility.py) left the write endpoints open: a directory-scoped
edition user could assign foreign faces or a foreign photo's faces to a person.
These tests pin the hardening on the three write endpoints:

  * POST /api/face/{id}/assign            — assert_faces_visible
  * POST /api/photo/assign_all_faces      — assert_photo_visible
  * POST /api/persons/{id}/assign_faces   — assert_faces_visible

Foreign inputs must yield the same 404 as nonexistent ones (no existence leak);
single-user mode is a no-op (covered by the existing mock tests in
tests/test_faces.py). Follows the session-DB pattern from
tests/test_persons_create.py.
"""

import os
import sqlite3
from unittest import mock

_HELPERS = "api.db_helpers"
_EMBEDDING = sqlite3.Binary(b"\x00\x00\x00\x00")
OWN_PREFIX = "/av_own/"
FOREIGN_PREFIX = "/av_foreign/"
CALLER_DIRS = ["/av_own"]


def _db():
    conn = sqlite3.connect(os.environ["DB_PATH"])
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def _seed_faces(conn, paths, person_id=None):
    face_ids = []
    for face_index, path in enumerate(paths):
        conn.execute("INSERT OR IGNORE INTO photos(path) VALUES (?)", (path,))
        cur = conn.execute(
            "INSERT INTO faces(photo_path, face_index, embedding, person_id) "
            "VALUES (?, ?, ?, ?)",
            (path, face_index, _EMBEDDING, person_id),
        )
        face_ids.append(cur.lastrowid)
    return face_ids


def _seed_person(conn, pid, name):
    conn.execute("DELETE FROM persons WHERE id = ?", (pid,))
    conn.execute(
        "INSERT INTO persons(id, name, auto_clustered, face_count) VALUES (?, ?, 0, 0)",
        (pid, name),
    )


def _cleanup(person_ids):
    conn = _db()
    for prefix in (OWN_PREFIX, FOREIGN_PREFIX):
        conn.execute("DELETE FROM faces WHERE photo_path LIKE ?", (prefix + "%",))
        conn.execute("DELETE FROM photos WHERE path LIKE ?", (prefix + "%",))
    if person_ids:
        placeholders = ",".join("?" * len(person_ids))
        conn.execute(f"DELETE FROM persons WHERE id IN ({placeholders})", person_ids)
    conn.commit()
    conn.close()


def _multi_user_patches():
    return [
        mock.patch(f"{_HELPERS}.is_multi_user_enabled", return_value=True),
        mock.patch(
            f"{_HELPERS}.get_user_directories",
            side_effect=lambda uid: CALLER_DIRS,
        ),
    ]


def _post_as_scoped_user(edition_client, url, payload):
    patches = _multi_user_patches()
    for p in patches:
        p.start()
    try:
        return edition_client.post(url, json=payload)
    finally:
        for p in patches:
            p.stop()


class TestAssignFaceVisibility:
    def test_foreign_face_denied(self, edition_client):
        try:
            conn = _db()
            _seed_person(conn, 9501, "Target")
            fid = _seed_faces(conn, [FOREIGN_PREFIX + "a.jpg"])[0]
            conn.commit()
            conn.close()

            resp = _post_as_scoped_user(
                edition_client, f"/api/face/{fid}/assign", {"person_id": 9501}
            )

            assert resp.status_code == 404
            assert resp.json()["detail"] == "Face not found"
            conn = _db()
            owner = conn.execute(
                "SELECT person_id FROM faces WHERE id = ?", (fid,)
            ).fetchone()["person_id"]
            conn.close()
            assert owner is None
        finally:
            _cleanup([9501])

    def test_own_face_allowed(self, edition_client):
        try:
            conn = _db()
            _seed_person(conn, 9501, "Target")
            fid = _seed_faces(conn, [OWN_PREFIX + "a.jpg"])[0]
            conn.commit()
            conn.close()

            resp = _post_as_scoped_user(
                edition_client, f"/api/face/{fid}/assign", {"person_id": 9501}
            )

            assert resp.status_code == 200, resp.text
            conn = _db()
            owner = conn.execute(
                "SELECT person_id FROM faces WHERE id = ?", (fid,)
            ).fetchone()["person_id"]
            conn.close()
            assert owner == 9501
        finally:
            _cleanup([9501])


class TestAssignAllFacesVisibility:
    def test_foreign_photo_denied(self, edition_client):
        try:
            conn = _db()
            _seed_person(conn, 9502, "Target")
            fids = _seed_faces(
                conn, [FOREIGN_PREFIX + "b.jpg", FOREIGN_PREFIX + "b.jpg"]
            )
            conn.commit()
            conn.close()

            resp = _post_as_scoped_user(
                edition_client,
                "/api/photo/assign_all_faces",
                {"photo_path": FOREIGN_PREFIX + "b.jpg", "person_id": 9502},
            )

            assert resp.status_code == 404
            assert resp.json()["detail"] == "No unassigned faces found"
            conn = _db()
            owners = [
                r["person_id"]
                for r in conn.execute(
                    f"SELECT person_id FROM faces WHERE id IN ({','.join('?' * len(fids))})",
                    fids,
                ).fetchall()
            ]
            conn.close()
            assert owners == [None, None]
        finally:
            _cleanup([9502])

    def test_own_photo_allowed(self, edition_client):
        try:
            conn = _db()
            _seed_person(conn, 9502, "Target")
            fids = _seed_faces(conn, [OWN_PREFIX + "b.jpg", OWN_PREFIX + "b.jpg"])
            conn.commit()
            conn.close()

            resp = _post_as_scoped_user(
                edition_client,
                "/api/photo/assign_all_faces",
                {"photo_path": OWN_PREFIX + "b.jpg", "person_id": 9502},
            )

            assert resp.status_code == 200, resp.text
            assert resp.json()["assigned_count"] == 2
            conn = _db()
            owners = [
                r["person_id"]
                for r in conn.execute(
                    f"SELECT person_id FROM faces WHERE id IN ({','.join('?' * len(fids))})",
                    fids,
                ).fetchall()
            ]
            conn.close()
            assert owners == [9502, 9502]
        finally:
            _cleanup([9502])


class TestAssignFacesBatchVisibility:
    def test_foreign_face_denied(self, edition_client):
        try:
            conn = _db()
            _seed_person(conn, 9503, "Target")
            own = _seed_faces(conn, [OWN_PREFIX + "c.jpg"])
            foreign = _seed_faces(conn, [FOREIGN_PREFIX + "c.jpg"])
            conn.commit()
            conn.close()

            resp = _post_as_scoped_user(
                edition_client,
                "/api/persons/9503/assign_faces",
                {"face_ids": own + foreign},
            )

            assert resp.status_code == 404
            conn = _db()
            owners = [
                r["person_id"]
                for r in conn.execute(
                    "SELECT person_id FROM faces WHERE id IN (?, ?)",
                    own + foreign,
                ).fetchall()
            ]
            count = conn.execute(
                "SELECT face_count FROM persons WHERE id = 9503"
            ).fetchone()["face_count"]
            conn.close()
            assert owners == [None, None]
            assert count == 0
        finally:
            _cleanup([9503])

    def test_own_faces_allowed(self, edition_client):
        try:
            conn = _db()
            _seed_person(conn, 9503, "Target")
            own = _seed_faces(conn, [OWN_PREFIX + "c.jpg", OWN_PREFIX + "d.jpg"])
            conn.commit()
            conn.close()

            resp = _post_as_scoped_user(
                edition_client,
                "/api/persons/9503/assign_faces",
                {"face_ids": own},
            )

            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["assigned_count"] == 2
            assert body["face_count"] == 2
        finally:
            _cleanup([9503])
