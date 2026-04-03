"""Tests for the persons API router (api/routers/persons.py)."""

from contextlib import contextmanager
from unittest import mock

import pytest


def _cm(conn):
    @contextmanager
    def _ctx():
        yield conn
    return _ctx()
from fastapi.testclient import TestClient

from api import create_app
from api.auth import CurrentUser


@pytest.fixture()
def client():
    app = create_app()
    with (
        mock.patch(
            "api.routers.persons.require_edition",
            return_value=CurrentUser(edition_authenticated=True),
        ),
        mock.patch(
            "api.routers.persons.require_authenticated",
            return_value=CurrentUser(),
        ),
    ):
        yield TestClient(app)


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
    """Tests for POST /api/persons/merge_batch."""

    def test_merge_batch_empty_sources(self, client):
        """Empty source_ids returns 400."""
        resp = client.post(
            "/api/persons/merge_batch",
            json={"source_ids": [], "target_id": 1},
        )

        assert resp.status_code == 400
        assert "source_ids" in resp.json()["detail"].lower()

    def test_merge_batch_target_in_sources(self, client):
        """target_id present in source_ids returns 400."""
        resp = client.post(
            "/api/persons/merge_batch",
            json={"source_ids": [1, 2, 3], "target_id": 2},
        )

        assert resp.status_code == 400
        assert "target" in resp.json()["detail"].lower()

    def test_merge_batch_success(self, client):
        """Batch merge moves faces from all sources into target."""
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (12,)

        with mock.patch(
            "api.routers.persons.get_db", lambda: _cm(mock_conn)
        ):
            resp = client.post(
                "/api/persons/merge_batch",
                json={"source_ids": [2, 3, 4], "target_id": 1},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["target_id"] == 1
        assert body["merged_count"] == 3
        assert body["new_count"] == 12

        calls = [str(c) for c in mock_conn.execute.call_args_list]
        # Faces moved
        assert any("UPDATE faces SET person_id" in c for c in calls)
        # Source persons deleted
        assert any("DELETE FROM persons" in c for c in calls)
        mock_conn.commit.assert_called_once()



class TestRenamePerson:
    """Tests for POST /api/persons/{id}/rename."""

    def test_rename_person(self, client):
        """Renaming sets the name on the person row."""
        mock_conn = mock.MagicMock()

        with mock.patch(
            "api.routers.persons.get_db", lambda: _cm(mock_conn)
        ):
            resp = client.post(
                "/api/persons/1/rename", json={"name": "Alice"}
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["name"] == "Alice"

        mock_conn.execute.assert_called_once_with(
            "UPDATE persons SET name = ? WHERE id = ?", ("Alice", 1)
        )
        mock_conn.commit.assert_called_once()


    def test_rename_person_clear(self, client):
        """Renaming with empty string sets name to NULL."""
        mock_conn = mock.MagicMock()

        with mock.patch(
            "api.routers.persons.get_db", lambda: _cm(mock_conn)
        ):
            resp = client.post(
                "/api/persons/1/rename", json={"name": ""}
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["name"] == "Person 1"

        # Empty string stripped becomes falsy, so NULL is passed
        mock_conn.execute.assert_called_once_with(
            "UPDATE persons SET name = ? WHERE id = ?", (None, 1)
        )


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
    """Tests for GET /api/persons."""

    def test_list_persons(self, client):
        """Returns paginated person list."""
        mock_conn = mock.MagicMock()
        # COUNT query
        mock_conn.execute.return_value.fetchone.return_value = (2,)
        # Person rows
        mock_conn.execute.return_value.fetchall.return_value = [
            {
                "id": 1,
                "name": "Alice",
                "representative_face_id": 10,
                "face_count": 25,
                "face_thumbnail": 1,
                "rep_quality": 0.8,
            },
            {
                "id": 2,
                "name": None,
                "representative_face_id": 20,
                "face_count": 5,
                "face_thumbnail": 0,
                "rep_quality": 0.3,
            },
        ]

        with mock.patch(
            "api.routers.persons.get_db", lambda: _cm(mock_conn)
        ):
            resp = client.get("/api/persons", params={"page": 1, "per_page": 48})

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert body["sort"] == "count_desc"
        assert len(body["persons"]) == 2
        assert body["persons"][0]["id"] == 1
        assert body["persons"][0]["name"] == "Alice"


    def test_search_by_name(self, client):
        """Searching with a text string filters by name LIKE."""
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (1,)
        mock_conn.execute.return_value.fetchall.return_value = []

        with mock.patch(
            "api.routers.persons.get_db", lambda: _cm(mock_conn)
        ):
            resp = client.get("/api/persons", params={"search": "alice"})

        assert resp.status_code == 200
        # The COUNT query should use name LIKE only (no ID match)
        count_call = mock_conn.execute.call_args_list[0]
        sql = count_call[0][0]
        params = count_call[0][1]
        assert "p.name LIKE ?" in sql
        assert "p.id = ?" not in sql
        assert params == ["%alice%"]

    def test_search_by_id(self, client):
        """Searching with a numeric string also matches person ID."""
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (1,)
        mock_conn.execute.return_value.fetchall.return_value = []

        with mock.patch(
            "api.routers.persons.get_db", lambda: _cm(mock_conn)
        ):
            resp = client.get("/api/persons", params={"search": "42"})

        assert resp.status_code == 200
        # The COUNT query should use both name LIKE and ID match
        count_call = mock_conn.execute.call_args_list[0]
        sql = count_call[0][0]
        params = count_call[0][1]
        assert "p.name LIKE ?" in sql
        assert "p.id = ?" in sql
        assert params == ["%42%", 42]
