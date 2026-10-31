"""Tests for the persons API router (api/routers/persons.py).

Uses the shared ``edition_client`` fixture from ``tests/conftest.py`` — see
that file for why dependency_overrides is the only pattern that works for
FastAPI Depends() chains.
"""

import os
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from unittest import mock

import aiosqlite
import pytest


def _cm(conn):
    @contextmanager
    def _ctx():
        yield conn
    return _ctx()


# --- Real temp-DB factory for the now-async GET endpoints -----------------
# list_persons and api_persons_needs_naming are async (Topic 2 step 5), so
# they reach the DB via ``async with get_async_db()``. A MagicMock is not
# awaitable, so these tests use a real aiosqlite-backed temp sqlite DB.

_PERSONS_SCHEMA = """
    CREATE TABLE persons (
        id INTEGER PRIMARY KEY,
        name TEXT,
        representative_face_id INTEGER,
        face_count INTEGER DEFAULT 0,
        face_thumbnail BLOB,
        auto_clustered INTEGER DEFAULT 0,
        is_hidden INTEGER DEFAULT 0
    );
    CREATE TABLE faces (
        id INTEGER PRIMARY KEY,
        photo_path TEXT
    );
    CREATE TABLE photos (
        path TEXT PRIMARY KEY,
        eye_sharpness REAL,
        face_quality REAL
    );
"""


def _make_persons_db(path, persons=None, faces=None, photos=None):
    conn = sqlite3.connect(path)
    conn.executescript(_PERSONS_SCHEMA)
    for tbl, rows in (("persons", persons), ("faces", faces), ("photos", photos)):
        for r in (rows or []):
            cols = list(r.keys())
            placeholders = ", ".join("?" for _ in cols)
            conn.execute(
                f"INSERT INTO {tbl} ({', '.join(cols)}) VALUES ({placeholders})",
                [r[c] for c in cols],
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


# Alias the shared fixture under the local name ``client`` so the existing
# test signatures (``def test_X(self, client)``) keep working without a
# mechanical rename pass.
@pytest.fixture()
def client(edition_client):
    return edition_client


class TestMergePersons:
    """Tests for POST /api/persons/merge."""

    def test_merge_self(self, client):
        """Merging a person into itself returns 400."""
        resp = client.post("/api/persons/merge", json={"source_id": 1, "target_id": 1})

        assert resp.status_code == 400
        assert "itself" in resp.json()["detail"].lower()

    def test_merge_success(self, client):
        """Merge moves faces, deletes source, and updates count."""
        mock_conn = mock.MagicMock()
        # COUNT(*) for new face_count after merge
        mock_conn.execute.return_value.fetchone.return_value = (5,)

        with mock.patch(
            "api.routers.persons.get_db", lambda: _cm(mock_conn)
        ):
            resp = client.post(
                "/api/persons/merge", json={"source_id": 1, "target_id": 2}
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["new_count"] == 5

        calls = [str(c) for c in mock_conn.execute.call_args_list]
        # Faces moved from source to target
        assert any("UPDATE faces SET person_id" in c for c in calls)
        # Source person deleted
        assert any("DELETE FROM persons" in c for c in calls)
        mock_conn.commit.assert_called_once()


    def test_merge_via_path_params(self, client):
        """POST /api/persons/merge/{source}/{target} also works."""
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (3,)

        with mock.patch(
            "api.routers.persons.get_db", lambda: _cm(mock_conn)
        ):
            resp = client.post("/api/persons/merge/1/2")

        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert resp.json()["new_count"] == 3


class TestMergeBatch:
    """Tests for POST /api/persons/merge_batch (pair-list contract).

    The client sends arbitrary {source_id, target_id} pairs; the server
    resolves transitive chains and may have several distinct targets.
    """

    def test_merge_batch_empty(self, client):
        """Empty merges list returns 400."""
        resp = client.post("/api/persons/merge_batch", json={"merges": []})
        assert resp.status_code == 400

    def test_merge_batch_only_self_pairs(self, client):
        """Self-referential pairs resolve to nothing -> 400 (no DB touched)."""
        resp = client.post(
            "/api/persons/merge_batch",
            json={"merges": [{"source_id": 1, "target_id": 1}]},
        )
        assert resp.status_code == 400

    def test_merge_batch_success(self, client):
        """Batch merge moves faces from all sources into the shared target."""
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (12,)

        with mock.patch(
            "api.routers.persons.get_db", lambda: _cm(mock_conn)
        ):
            resp = client.post(
                "/api/persons/merge_batch",
                json={"merges": [
                    {"source_id": 2, "target_id": 1},
                    {"source_id": 3, "target_id": 1},
                    {"source_id": 4, "target_id": 1},
                ]},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["targets"] == [1]
        assert body["merged_count"] == 3
        # The actual face-move / source-delete row effects are asserted against a
        # real DB in test_persons_merge_batch.py; here we only verify the
        # endpoint resolves the batch and commits once.
        mock_conn.commit.assert_called_once()

    def test_merge_batch_resolves_chains(self, client):
        """A chain (2->1, 1->4) folds both 1 and 2 into the final target 4."""
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (7,)

        with mock.patch(
            "api.routers.persons.get_db", lambda: _cm(mock_conn)
        ):
            resp = client.post(
                "/api/persons/merge_batch",
                json={"merges": [
                    {"source_id": 2, "target_id": 1},
                    {"source_id": 1, "target_id": 4},
                ]},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["targets"] == [4]
        assert body["merged_count"] == 2



class TestRenamePerson:
    """Tests for POST /api/persons/{id}/rename."""

    def test_rename_person(self, edition_client, seed_people):
        """Renaming stores the trimmed name on the person row and touches nothing else."""
        path = seed_people.photo("/test_persons_rename/", "a.jpg")
        person_id = seed_people.person()
        other_id = seed_people.person("Untouched")
        seed_people.face(path, person_id)
        seed_people.face(path, person_id)
        seed_people.face(path, other_id)

        resp = edition_client.post(f"/api/persons/{person_id}/rename", json={"name": "  Alice "})

        assert resp.status_code == 200
        # face_count is the renamed person's own, not the other person's.
        assert resp.json() == {"success": True, "name": "Alice", "face_count": 2,
                               "same_name_persons": []}
        conn = sqlite3.connect(os.environ["DB_PATH"])
        try:
            names = dict(conn.execute(
                "SELECT id, name FROM persons WHERE id IN (?, ?)", (person_id, other_id)).fetchall())
        finally:
            conn.close()
        assert names == {person_id: "Alice", other_id: "Untouched"}

    def test_rename_person_clear(self, edition_client, seed_people):
        """Renaming with an empty string stores NULL and answers the placeholder name."""
        path = seed_people.photo("/test_persons_rename/", "b.jpg")
        person_id = seed_people.person("Alice")
        seed_people.face(path, person_id)

        resp = edition_client.post(f"/api/persons/{person_id}/rename", json={"name": "  "})

        assert resp.status_code == 200
        assert resp.json() == {"success": True, "name": f"Person {person_id}",
                               "face_count": 1, "same_name_persons": []}
        conn = sqlite3.connect(os.environ["DB_PATH"])
        try:
            name = conn.execute("SELECT name FROM persons WHERE id = ?", (person_id,)).fetchone()[0]
        finally:
            conn.close()
        assert name is None


class TestDeletePerson:
    """Tests for POST /api/persons/{id}/delete."""

    def test_delete_person(self, client):
        """Deleting unassigns faces and removes the person row."""
        mock_conn = mock.MagicMock()

        with mock.patch(
            "api.routers.persons.get_db", lambda: _cm(mock_conn)
        ):
            resp = client.post("/api/persons/1/delete")

        assert resp.status_code == 200
        assert resp.json()["success"] is True

        calls = mock_conn.execute.call_args_list
        # First call: unassign faces
        assert calls[0] == mock.call(
            "UPDATE faces SET person_id = NULL WHERE person_id = ?", (1,)
        )
        # Second call: delete person
        assert calls[1] == mock.call(
            "DELETE FROM persons WHERE id = ?", (1,)
        )
        mock_conn.commit.assert_called_once()



class TestDeleteBatch:
    """Tests for POST /api/persons/delete_batch."""

    def test_delete_batch(self, client):
        """Batch delete unassigns faces and removes all listed persons."""
        mock_conn = mock.MagicMock()

        with mock.patch(
            "api.routers.persons.get_db", lambda: _cm(mock_conn)
        ):
            resp = client.post(
                "/api/persons/delete_batch",
                json={"person_ids": [1, 2, 3]},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["deleted_count"] == 3

        calls = [str(c) for c in mock_conn.execute.call_args_list]
        assert any("UPDATE faces SET person_id = NULL" in c for c in calls)
        assert any("DELETE FROM persons" in c for c in calls)
        mock_conn.commit.assert_called_once()


    def test_delete_batch_empty(self, client):
        """Empty person_ids returns 400."""
        resp = client.post(
            "/api/persons/delete_batch", json={"person_ids": []}
        )

        assert resp.status_code == 400
        assert "person_ids" in resp.json()["detail"].lower()


class TestListPersons:
    """Tests for GET /api/persons (async, real temp DB)."""

    def test_list_persons(self, client, tmp_path):
        """Returns paginated person list, default count_desc ordering."""
        db = str(tmp_path / "persons.db")
        _make_persons_db(
            db,
            persons=[
                {"id": 1, "name": "Alice", "representative_face_id": 10,
                 "face_count": 25, "auto_clustered": 0},
                {"id": 2, "name": None, "representative_face_id": 20,
                 "face_count": 5, "auto_clustered": 1},
            ],
            faces=[
                {"id": 10, "photo_path": "/a.jpg"},
                {"id": 20, "photo_path": "/b.jpg"},
            ],
            photos=[
                {"path": "/a.jpg", "eye_sharpness": 8.0, "face_quality": 7.5},
                {"path": "/b.jpg", "eye_sharpness": 3.0, "face_quality": 6.0},
            ],
        )
        with mock.patch(
            "api.routers.persons.get_async_db", _async_conn_factory(db)
        ):
            resp = client.get("/api/persons", params={"page": 1, "per_page": 48})

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert body["sort"] == "count_desc"
        assert len(body["persons"]) == 2
        # count_desc → Alice (25 faces) first
        assert body["persons"][0]["id"] == 1
        assert body["persons"][0]["name"] == "Alice"
        assert body["persons"][0]["face_count"] == 25

    def test_search_by_name(self, client, tmp_path):
        """Searching with a text string filters by name LIKE (case-insensitive)."""
        db = str(tmp_path / "persons.db")
        _make_persons_db(
            db,
            persons=[
                {"id": 1, "name": "Alice", "face_count": 25},
                {"id": 2, "name": "Bob", "face_count": 5},
                # Numeric-looking *name* — must NOT match a text search for "alice"
                {"id": 42, "name": "Charlie", "face_count": 3},
            ],
        )
        with mock.patch(
            "api.routers.persons.get_async_db", _async_conn_factory(db)
        ):
            resp = client.get("/api/persons", params={"search": "alice"})

        assert resp.status_code == 200
        body = resp.json()
        # Only Alice matches by name; ID is not consulted for a non-numeric term
        assert body["total"] == 1
        assert len(body["persons"]) == 1
        assert body["persons"][0]["name"] == "Alice"

    def test_search_by_id(self, client, tmp_path):
        """Searching with a numeric string matches person ID OR name."""
        db = str(tmp_path / "persons.db")
        _make_persons_db(
            db,
            persons=[
                {"id": 42, "name": "Alice", "face_count": 25},
                # name contains "42" → matched via the name LIKE branch
                {"id": 7, "name": "Agent 42", "face_count": 5},
                {"id": 99, "name": "Bob", "face_count": 3},
            ],
        )
        with mock.patch(
            "api.routers.persons.get_async_db", _async_conn_factory(db)
        ):
            resp = client.get("/api/persons", params={"search": "42"})

        assert resp.status_code == 200
        body = resp.json()
        # Matches id=42 (by id) and id=7 (by name LIKE '%42%'), not Bob
        assert body["total"] == 2
        returned_ids = {p["id"] for p in body["persons"]}
        assert returned_ids == {42, 7}


class TestListPersonsNamedOnly:
    """GET /api/persons?named_only=true leaves out persons still waiting for a name."""

    def test_named_only(self, client, tmp_path):
        db = str(tmp_path / "persons_named.db")
        _make_persons_db(db, persons=[
            {"id": 1, "name": "Alice", "face_count": 25},
            {"id": 2, "name": None, "face_count": 30},
            {"id": 3, "name": "  ", "face_count": 9},
            {"id": 4, "name": "Bob", "face_count": 3},
        ])
        with mock.patch("api.routers.persons.get_async_db", _async_conn_factory(db)):
            named = client.get("/api/persons", params={"named_only": True}).json()
            everyone = client.get("/api/persons").json()

        assert [p["id"] for p in named["persons"]] == [1, 4]
        assert named["total"] == 2
        assert everyone["total"] == 4


class TestListPersonsHiddenOnly:
    """GET /api/persons?hidden_only=true lists the hidden (ignored) persons alone."""

    def test_hidden_only(self, client, tmp_path):
        db = str(tmp_path / "persons_hidden.db")
        _make_persons_db(db, persons=[
            {"id": 1, "name": "Alice", "face_count": 25, "is_hidden": 0},
            {"id": 2, "name": "Waiter", "face_count": 6, "is_hidden": 1},
            {"id": 3, "name": None, "face_count": 3, "is_hidden": 1},
            {"id": 4, "name": "Bob", "face_count": 3},
        ])
        with mock.patch("api.routers.persons.get_async_db", _async_conn_factory(db)):
            hidden = client.get("/api/persons", params={"hidden_only": True}).json()
            default = client.get("/api/persons").json()

        assert [p["id"] for p in hidden["persons"]] == [2, 3]
        assert hidden["total"] == 2
        assert [p["id"] for p in default["persons"]] == [1, 4]


class TestNeedsNaming:
    """Tests for GET /api/persons/needs_naming (async, real temp DB)."""

    def test_needs_naming_filters(self, client, tmp_path):
        """Every unnamed, visible person over the min_faces threshold, largest first."""
        db = str(tmp_path / "persons.db")
        _make_persons_db(
            db,
            persons=[
                # Unnamed, auto-clustered, enough faces → included
                {"id": 1, "name": None, "face_count": 10, "auto_clustered": 1},
                {"id": 2, "name": None, "face_count": 6, "auto_clustered": 1},
                # Named → excluded
                {"id": 3, "name": "Alice", "face_count": 20, "auto_clustered": 1},
                # Unnamed from a split (not auto-clustered) → still waiting for a name
                {"id": 4, "name": None, "face_count": 8, "auto_clustered": 0},
                # Below threshold → excluded
                {"id": 5, "name": None, "face_count": 2, "auto_clustered": 1},
                # Blank name counts as unnamed
                {"id": 6, "name": "  ", "face_count": 7, "auto_clustered": 1},
                # Hidden → excluded
                {"id": 7, "name": None, "face_count": 30, "auto_clustered": 1, "is_hidden": 1},
            ],
        )
        with mock.patch(
            "api.routers.persons.get_async_db", _async_conn_factory(db)
        ):
            resp = client.get("/api/persons/needs_naming", params={"min_faces": 5})

        assert resp.status_code == 200
        body = resp.json()
        assert body["min_faces"] == 5
        assert body["total"] == 4
        assert [p["id"] for p in body["persons"]] == [1, 4, 6, 2]

    def test_min_faces_one_lists_every_unnamed_person(self, client, tmp_path):
        db = str(tmp_path / "persons_all.db")
        _make_persons_db(db, persons=[
            {"id": 1, "name": None, "face_count": 1, "auto_clustered": 1},
            {"id": 2, "name": "Bob", "face_count": 1, "auto_clustered": 1},
        ])
        with mock.patch("api.routers.persons.get_async_db", _async_conn_factory(db)):
            body = client.get("/api/persons/needs_naming", params={"min_faces": 1}).json()
        assert [p["id"] for p in body["persons"]] == [1]
