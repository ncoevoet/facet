"""Batch person merge (chain resolution) and merge-suggestion rejection persistence.

Covers the fix for the broken "Accept all" path (client sent {merges:[...]},
server expected {source_ids, target_id}) and the new
rejected_merge_suggestions persistence.
"""

import os
import sqlite3
from unittest import mock

import numpy as np

from api.routers.persons import _resolve_merge_chains


def _db():
    conn = sqlite3.connect(os.environ["DB_PATH"])
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _seed_person(conn, pid, face_paths):
    """Insert a person with `len(face_paths)` faces (each on its own photo)."""
    conn.execute("DELETE FROM persons WHERE id = ?", (pid,))
    # The suite shares one DB per worker and a deleted person leaves its faces
    # behind, so an earlier test's rows can still point at this fixed id and
    # inflate the merged face_count.
    conn.execute("UPDATE faces SET person_id = NULL WHERE person_id = ?", (pid,))
    conn.execute(
        "INSERT INTO persons(id, name, face_count) VALUES (?, ?, ?)",
        (pid, f"P{pid}", len(face_paths)),
    )
    for path in face_paths:
        conn.execute("INSERT OR IGNORE INTO photos(path) VALUES (?)", (path,))
        conn.execute(
            "INSERT INTO faces(photo_path, face_index, embedding, person_id) "
            "VALUES (?, 0, ?, ?)",
            (path, sqlite3.Binary(b"\x00\x00\x00\x00"), pid),
        )


def _cleanup(ids, path_prefix):
    conn = _db()
    placeholders = ",".join("?" * len(ids))
    conn.execute(f"DELETE FROM persons WHERE id IN ({placeholders})", ids)
    conn.execute("DELETE FROM faces WHERE photo_path LIKE ?", (path_prefix + "%",))
    conn.execute("DELETE FROM photos WHERE path LIKE ?", (path_prefix + "%",))
    conn.execute(
        f"DELETE FROM rejected_merge_suggestions WHERE person_a_id IN ({placeholders})",
        ids,
    )
    conn.commit()
    conn.close()


# --------------------------------------------------------------------------
# Pure chain-resolution unit tests (no DB)
# --------------------------------------------------------------------------

class TestResolveMergeChains:
    def test_transitive_chain(self):
        # 2->1 and 1->4 means both 1 and 2 fold into 4.
        assert _resolve_merge_chains([(2, 1), (1, 4)]) == {4: {1, 2}}

    def test_multiple_distinct_targets(self):
        assert _resolve_merge_chains([(10, 11), (12, 13)]) == {11: {10}, 13: {12}}

    def test_shared_target(self):
        assert _resolve_merge_chains([(2, 1), (3, 1)]) == {1: {2, 3}}

    def test_self_pair_ignored(self):
        assert _resolve_merge_chains([(5, 5)]) == {}

    def test_cycle_is_safe(self):
        # A contradictory 1<->2 cycle must terminate (not hang) and merge nothing.
        assert _resolve_merge_chains([(1, 2), (2, 1)]) == {}


# --------------------------------------------------------------------------
# POST /api/persons/merge_batch
# --------------------------------------------------------------------------

class TestMergeBatchEndpoint:
    def test_stale_faces_on_a_recycled_person_id_are_not_merged(self, edition_client):
        prefix = "mtest_stale/"
        try:
            conn = _db()
            conn.execute("INSERT OR IGNORE INTO photos(path) VALUES (?)", ("mtest_other/x.jpg",))
            conn.execute(
                "INSERT INTO faces(photo_path, face_index, embedding, person_id) VALUES (?, 0, ?, 9021)",
                ("mtest_other/x.jpg", sqlite3.Binary(b"\x00\x00\x00\x00")))
            _seed_person(conn, 9021, [prefix + "a.jpg"])
            _seed_person(conn, 9022, [prefix + "b.jpg"])
            conn.commit()
            conn.close()
            resp = edition_client.post(
                "/api/persons/merge_batch", json={"merges": [{"source_id": 9021, "target_id": 9022}]})
            assert resp.status_code == 200, resp.text
            conn = _db()
            assert conn.execute("SELECT face_count FROM persons WHERE id = 9022").fetchone()[0] == 2
            conn.close()
        finally:
            _cleanup([9021, 9022], prefix)
            conn = _db()
            conn.execute("DELETE FROM faces WHERE photo_path LIKE 'mtest_other/%'")
            conn.execute("DELETE FROM photos WHERE path LIKE 'mtest_other/%'")
            conn.commit()
            conn.close()

    def test_transitive_chain_merges_into_final_target(self, edition_client):
        prefix = "mtest_chain/"
        try:
            conn = _db()
            _seed_person(conn, 9001, [prefix + "a1.jpg", prefix + "a2.jpg"])
            _seed_person(conn, 9002, [prefix + "b1.jpg"])
            _seed_person(conn, 9003, [prefix + "c1.jpg", prefix + "c2.jpg", prefix + "c3.jpg"])
            conn.commit()
            conn.close()

            resp = edition_client.post(
                "/api/persons/merge_batch",
                json={"merges": [
                    {"source_id": 9001, "target_id": 9002},
                    {"source_id": 9002, "target_id": 9003},
                ]},
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["success"] is True
            assert body["merged_count"] == 2
            assert body["targets"] == [9003]

            conn = _db()
            survivors = [r[0] for r in conn.execute(
                "SELECT id FROM persons WHERE id IN (9001, 9002, 9003)").fetchall()]
            assert survivors == [9003]
            count = conn.execute(
                "SELECT face_count FROM persons WHERE id = 9003").fetchone()[0]
            assert count == 6
            owners = [r[0] for r in conn.execute(
                "SELECT DISTINCT person_id FROM faces WHERE photo_path LIKE ?",
                (prefix + "%",)).fetchall()]
            assert owners == [9003]
            conn.close()
        finally:
            _cleanup([9001, 9002, 9003], prefix)

    def test_multiple_distinct_targets(self, edition_client):
        prefix = "mtest_multi/"
        try:
            conn = _db()
            _seed_person(conn, 9010, [prefix + "a.jpg"])
            _seed_person(conn, 9011, [prefix + "b.jpg"])
            _seed_person(conn, 9012, [prefix + "c.jpg"])
            _seed_person(conn, 9013, [prefix + "d.jpg"])
            conn.commit()
            conn.close()

            resp = edition_client.post(
                "/api/persons/merge_batch",
                json={"merges": [
                    {"source_id": 9010, "target_id": 9011},
                    {"source_id": 9012, "target_id": 9013},
                ]},
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["targets"] == [9011, 9013]

            conn = _db()
            survivors = sorted(r[0] for r in conn.execute(
                "SELECT id FROM persons WHERE id IN (9010,9011,9012,9013)").fetchall())
            assert survivors == [9011, 9013]
            for pid in (9011, 9013):
                cnt = conn.execute(
                    "SELECT face_count FROM persons WHERE id = ?", (pid,)).fetchone()[0]
                assert cnt == 2
            conn.close()
        finally:
            _cleanup([9010, 9011, 9012, 9013], prefix)

    def test_empty_merges_returns_400(self, edition_client):
        resp = edition_client.post("/api/persons/merge_batch", json={"merges": []})
        assert resp.status_code == 400


# --------------------------------------------------------------------------
# POST /api/persons/merge_suggestions/reject  +  GET /api/merge_suggestions
# --------------------------------------------------------------------------

class TestRejectMergeSuggestion:
    def test_rejected_pair_is_filtered_out(self, edition_client):
        try:
            conn = _db()
            for pid in (9100, 9101):
                conn.execute("DELETE FROM persons WHERE id = ?", (pid,))
                conn.execute(
                    "INSERT INTO persons(id, name, face_count) VALUES (?, ?, 0)",
                    (pid, f"P{pid}"))
            conn.execute(
                "DELETE FROM rejected_merge_suggestions WHERE person_a_id = 9100")
            conn.commit()
            conn.close()

            centroid = np.array([1.0, 0.0])
            people = [
                {"id": pid, "name": f"P{pid}", "face_count": 0, "centroid": centroid}
                for pid in (9100, 9101)
            ]
            # Isolate these centroids from the shared test database while
            # exercising the real ranking and dismissal lookup.
            with mock.patch("db.person_centroids.load_person_centroids", return_value=people):
                before = edition_client.get("/api/merge_suggestions")
                assert before.status_code == 200
                assert len(before.json()["suggestions"]) == 1

                # Reject with reversed id order to exercise canonicalization.
                rej = edition_client.post(
                    "/api/persons/merge_suggestions/reject",
                    json={"person1_id": 9101, "person2_id": 9100})
                assert rej.status_code == 200

                after = edition_client.get("/api/merge_suggestions")
                assert after.status_code == 200
                assert after.json()["suggestions"] == []

            conn = _db()
            row = conn.execute(
                "SELECT person_a_id, person_b_id FROM rejected_merge_suggestions "
                "WHERE person_a_id = 9100 AND person_b_id = 9101").fetchone()
            assert row == (9100, 9101)
            conn.close()
        finally:
            conn = _db()
            conn.execute("DELETE FROM rejected_merge_suggestions WHERE person_a_id = 9100")
            conn.execute("DELETE FROM persons WHERE id IN (9100, 9101)")
            conn.commit()
            conn.close()
