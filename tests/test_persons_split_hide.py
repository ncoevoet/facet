"""Tests for person cluster split + hide/unhide (api/routers/persons.py).

Two backend features:
  * POST /api/persons/{id}/split  — move a subset of faces to a new person.
  * POST /api/persons/{id}/hide | /unhide  — flip the is_hidden flag, which
    excludes a person from the persons list, the filter dropdown, and merge
    suggestions.

Seeding follows the real-temp-DB pattern from tests/test_persons_merge_batch.py:
faces need a photo_path FK (photos row) and a non-null embedding. The session
DB (DB_PATH) is shared, so every test cleans up its own rows.
"""

import os
import sqlite3

import numpy as np


def _db():
    conn = sqlite3.connect(os.environ["DB_PATH"])
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def _seed_person(conn, pid, face_paths, *, is_hidden=0, centroid=None, name=None):
    """Insert a person with one face per photo path.

    Returns the list of face ids created, in path order.
    """
    conn.execute("DELETE FROM persons WHERE id = ?", (pid,))
    conn.execute(
        "INSERT INTO persons(id, name, face_count, is_hidden, centroid) "
        "VALUES (?, ?, ?, ?, ?)",
        (pid, name if name is not None else f"P{pid}", len(face_paths), is_hidden,
         sqlite3.Binary(centroid.tobytes()) if centroid is not None else None),
    )
    face_ids = []
    for path in face_paths:
        conn.execute("INSERT OR IGNORE INTO photos(path) VALUES (?)", (path,))
        cur = conn.execute(
            "INSERT INTO faces(photo_path, face_index, embedding, person_id) "
            "VALUES (?, 0, ?, ?)",
            (path, sqlite3.Binary(b"\x00\x00\x00\x00"), pid),
        )
        face_ids.append(cur.lastrowid)
    return face_ids


def _cleanup(ids, path_prefix):
    conn = _db()
    placeholders = ",".join("?" * len(ids))
    conn.execute("DELETE FROM faces WHERE photo_path LIKE ?", (path_prefix + "%",))
    conn.execute("DELETE FROM photos WHERE path LIKE ?", (path_prefix + "%",))
    # New persons created by split have auto-assigned ids; clear any face-less
    # persons whose faces were on this prefix (already gone above) plus seeds.
    conn.execute(f"DELETE FROM persons WHERE id IN ({placeholders})", ids)
    conn.execute(
        f"DELETE FROM rejected_merge_suggestions WHERE person_a_id IN ({placeholders})",
        ids,
    )
    conn.commit()
    conn.close()


# --------------------------------------------------------------------------
# POST /api/persons/{id}/split
# --------------------------------------------------------------------------

class TestSplitPerson:
    def test_split_moves_faces_and_recounts(self, edition_client):
        prefix = "split_basic/"
        new_id = None
        try:
            conn = _db()
            fids = _seed_person(
                conn, 9300,
                [prefix + f"{i}.jpg" for i in range(5)],
            )
            conn.commit()
            conn.close()

            # Move 2 of the 5 faces to a new person named "Split".
            move = fids[:2]
            resp = edition_client.post(
                "/api/persons/9300/split",
                json={"face_ids": move, "name": "Split"},
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["success"] is True
            new_id = body["new_person_id"]
            assert new_id != 9300
            assert body["new_count"] == 2
            assert body["source_count"] == 3

            conn = _db()
            # New person exists, named, correct count, faces reassigned.
            np_row = conn.execute(
                "SELECT name, face_count FROM persons WHERE id = ?", (new_id,)
            ).fetchone()
            assert np_row["name"] == "Split"
            assert np_row["face_count"] == 2
            moved_owners = [
                r["person_id"] for r in conn.execute(
                    f"SELECT person_id FROM faces WHERE id IN ({','.join('?' * len(move))})",
                    move,
                ).fetchall()
            ]
            assert all(o == new_id for o in moved_owners)
            # Source kept the rest.
            src_count = conn.execute(
                "SELECT face_count FROM persons WHERE id = 9300"
            ).fetchone()["face_count"]
            assert src_count == 3
            conn.close()
        finally:
            ids = [9300] + ([new_id] if new_id else [])
            _cleanup(ids, prefix)

    def test_split_deletes_emptied_source(self, edition_client):
        prefix = "split_all/"
        new_id = None
        try:
            conn = _db()
            fids = _seed_person(conn, 9301, [prefix + "a.jpg", prefix + "b.jpg"])
            conn.commit()
            conn.close()

            # Move ALL faces — source should be deleted.
            resp = edition_client.post(
                "/api/persons/9301/split",
                json={"face_ids": fids},
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()
            new_id = body["new_person_id"]
            assert body["new_count"] == 2
            assert body["source_count"] == 0

            conn = _db()
            src = conn.execute(
                "SELECT id FROM persons WHERE id = 9301"
            ).fetchone()
            assert src is None  # source deleted
            conn.close()
        finally:
            ids = [9301] + ([new_id] if new_id else [])
            _cleanup(ids, prefix)

    def test_split_with_foreign_face_ids_returns_400(self, edition_client):
        prefix = "split_foreign/"
        try:
            conn = _db()
            fids_a = _seed_person(conn, 9302, [prefix + "a.jpg", prefix + "b.jpg"])
            fids_b = _seed_person(conn, 9303, [prefix + "c.jpg"])
            conn.commit()
            conn.close()

            # Mix one face that belongs to 9303 into a split of 9302.
            resp = edition_client.post(
                "/api/persons/9302/split",
                json={"face_ids": [fids_a[0], fids_b[0]]},
            )
            assert resp.status_code == 400, resp.text
            assert str(fids_b[0]) in resp.json()["detail"]

            # Nothing moved — both persons intact.
            conn = _db()
            assert conn.execute(
                "SELECT face_count FROM persons WHERE id = 9302"
            ).fetchone()["face_count"] == 2
            owners = {
                r["person_id"] for r in conn.execute(
                    "SELECT DISTINCT person_id FROM faces WHERE photo_path LIKE ?",
                    (prefix + "%",),
                ).fetchall()
            }
            assert owners == {9302, 9303}
            conn.close()
        finally:
            _cleanup([9302, 9303], prefix)

    def test_split_empty_face_ids_rejected_by_validation(self, edition_client):
        # Pydantic min_length=1 -> 422 before the handler runs.
        resp = edition_client.post("/api/persons/9304/split", json={"face_ids": []})
        assert resp.status_code == 422

    def test_split_requires_edition(self, regular_client):
        resp = regular_client.post(
            "/api/persons/1/split", json={"face_ids": [1]}
        )
        assert resp.status_code == 403


# --------------------------------------------------------------------------
# POST /api/persons/{id}/hide  +  /unhide
# --------------------------------------------------------------------------

class TestHideUnhidePerson:
    def test_hide_then_unhide_flips_state(self, edition_client):
        prefix = "hide_flip/"
        try:
            conn = _db()
            _seed_person(conn, 9310, [prefix + "a.jpg"])
            conn.commit()
            conn.close()

            resp = edition_client.post("/api/persons/9310/hide")
            assert resp.status_code == 200, resp.text
            assert resp.json() == {"success": True, "is_hidden": True}
            conn = _db()
            assert conn.execute(
                "SELECT is_hidden FROM persons WHERE id = 9310"
            ).fetchone()["is_hidden"] == 1
            conn.close()

            resp = edition_client.post("/api/persons/9310/unhide")
            assert resp.status_code == 200, resp.text
            assert resp.json() == {"success": True, "is_hidden": False}
            conn = _db()
            assert conn.execute(
                "SELECT is_hidden FROM persons WHERE id = 9310"
            ).fetchone()["is_hidden"] == 0
            conn.close()
        finally:
            _cleanup([9310], prefix)

    def test_hide_requires_edition(self, regular_client):
        assert regular_client.post("/api/persons/1/hide").status_code == 403

    def test_unhide_requires_edition(self, regular_client):
        assert regular_client.post("/api/persons/1/unhide").status_code == 403


# --------------------------------------------------------------------------
# GET /api/persons — hidden exclusion / include_hidden
# --------------------------------------------------------------------------

class TestListPersonsHidden:
    def test_list_excludes_hidden_by_default(self, edition_client):
        prefix = "list_hidden/"
        try:
            conn = _db()
            _seed_person(conn, 9320, [prefix + "v.jpg"], is_hidden=0)
            _seed_person(conn, 9321, [prefix + "h.jpg"], is_hidden=1)
            conn.commit()
            conn.close()

            resp = edition_client.get(
                "/api/persons", params={"per_page": 200, "search": "P932"}
            )
            assert resp.status_code == 200, resp.text
            ids = {p["id"] for p in resp.json()["persons"]}
            assert 9320 in ids
            assert 9321 not in ids

            # include_hidden=true surfaces it, with is_hidden in the payload.
            resp = edition_client.get(
                "/api/persons",
                params={"per_page": 200, "search": "P932", "include_hidden": "true"},
            )
            assert resp.status_code == 200, resp.text
            persons = {p["id"]: p for p in resp.json()["persons"]}
            assert 9320 in persons and 9321 in persons
            assert persons[9321]["is_hidden"] == 1
            assert persons[9320]["is_hidden"] == 0
        finally:
            _cleanup([9320, 9321], prefix)


# --------------------------------------------------------------------------
# GET /api/filter_options/persons — hidden exclusion
# --------------------------------------------------------------------------

class TestFilterOptionsPersonsHidden:
    def test_filter_options_excludes_hidden(self, edition_client):
        prefix = "fopt_hidden/"
        try:
            conn = _db()
            # min_photos_for_person defaults to 1 in MINIMAL config? Use enough
            # photos so HAVING photo_count >= min_photos passes regardless.
            _seed_person(conn, 9330,
                         [prefix + f"v{i}.jpg" for i in range(12)], is_hidden=0)
            _seed_person(conn, 9331,
                         [prefix + f"h{i}.jpg" for i in range(12)], is_hidden=1)
            conn.commit()
            conn.close()

            resp = edition_client.get("/api/filter_options/persons")
            assert resp.status_code == 200, resp.text
            ids = {row[0] for row in resp.json()["persons"]}
            assert 9330 in ids
            assert 9331 not in ids
        finally:
            _cleanup([9330, 9331], prefix)


# --------------------------------------------------------------------------
# GET /api/merge_suggestions — hidden persons not proposed
# --------------------------------------------------------------------------

class TestMergeSuggestionsHidden:
    def test_hidden_person_not_suggested(self, edition_client):
        prefix = "msug_hidden/"
        try:
            # Three near-identical centroids: 9340 visible, 9341 visible, 9342 hidden.
            base = np.ones(8, dtype=np.float32)
            conn = _db()
            _seed_person(conn, 9340, [prefix + "a.jpg"], centroid=base.copy())
            _seed_person(conn, 9341, [prefix + "b.jpg"], centroid=base.copy())
            _seed_person(conn, 9342, [prefix + "c.jpg"],
                         centroid=base.copy(), is_hidden=1)
            conn.commit()
            conn.close()

            resp = edition_client.get(
                "/api/merge_suggestions", params={"threshold": 0.9}
            )
            assert resp.status_code == 200, resp.text
            suggested_ids = set()
            for s in resp.json()["suggestions"]:
                suggested_ids.add(s["person1"]["id"])
                suggested_ids.add(s["person2"]["id"])
            # The two visible near-duplicates should be suggested together.
            assert {9340, 9341}.issubset(suggested_ids)
            # The hidden one must never appear.
            assert 9342 not in suggested_ids
        finally:
            _cleanup([9340, 9341, 9342], prefix)
