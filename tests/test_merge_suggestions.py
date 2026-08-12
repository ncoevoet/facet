"""Tests for the merge suggestions API router (api/routers/merge_suggestions.py)."""

import math
import sqlite3
from contextlib import contextmanager
from unittest import mock

import numpy as np
import pytest
from fastapi.testclient import TestClient

from api import create_app
from api.auth import CurrentUser, require_authenticated

_ROUTER = "api.routers.merge_suggestions"

_ONE_PAIR = [
    {
        "person1": {"id": 1, "name": "Alice", "face_count": 10},
        "person2": {"id": 2, "name": "Alice B", "face_count": 5},
        "similarity": 0.85,
    }
]


@pytest.fixture()
def client():
    app = create_app()
    app.dependency_overrides[require_authenticated] = lambda: CurrentUser(
        user_id="u1", role="admin"
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestGetMergeSuggestions:
    """GET /api/merge_suggestions — person merge suggestions."""

    def test_returns_suggestions(self, client):
        """The endpoint surfaces the pairwise suggestions it computes."""
        with mock.patch(f"{_ROUTER}._pairwise_suggestions", return_value=_ONE_PAIR):
            resp = client.get("/api/merge_suggestions")

        assert resp.status_code == 200
        body = resp.json()
        assert "suggestions" in body
        assert len(body["suggestions"]) == 1
        s = body["suggestions"][0]
        assert s["person1"]["id"] == 1
        assert s["person2"]["id"] == 2
        assert s["similarity"] == 0.85

    def test_empty_persons_returns_empty(self, client):
        """No candidate pairs yields an empty suggestions list."""
        with mock.patch(f"{_ROUTER}._pairwise_suggestions", return_value=[]):
            resp = client.get("/api/merge_suggestions")

        assert resp.status_code == 200
        assert resp.json()["suggestions"] == []

    def test_requires_authentication(self):
        """Unauthenticated request returns 401."""
        app = create_app()
        # No auth override — default auth should reject
        with (
            mock.patch("api.auth.VIEWER_CONFIG", {"password": "secret", "edition_password": "", "features": {}}),
            mock.patch("api.auth.is_multi_user_enabled", return_value=False),
        ):
            unauthenticated_client = TestClient(app, raise_server_exceptions=False)
            resp = unauthenticated_client.get("/api/merge_suggestions")

        assert resp.status_code in (401, 403)


def _planar(angle_deg, dim=512, plane=(0, 1)):
    """A unit vector in the (plane) 2-plane of a ``dim``-space at ``angle_deg``."""
    v = np.zeros(dim, dtype=np.float32)
    r = math.radians(angle_deg)
    v[plane[0]] = math.cos(r)
    v[plane[1]] = math.sin(r)
    return v


def _db_cm(path):
    @contextmanager
    def _cm():
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        try:
            yield c
        finally:
            c.close()
    return _cm


class TestPairwiseSuggestions:
    """The heart of the fix: each emitted pair carries its OWN centroid
    similarity, and a pair merely linked through a chain is never invented.

    Persons are placed by angle in one plane so pairwise cosine similarity is
    exactly ``cos(delta)``:
        P1 @ 0deg, P2 @ 10deg, P4 @ 60deg  ->  (1,2)=cos10, (2,4)=cos50, (1,4)=cos60
    plus P3 orthogonal (no pair). At threshold 0.6:
        (1,2)=0.985 kept, (2,4)=0.643 kept, (1,4)=0.500 dropped.
    The old union-find grouping would have folded 1,2,4 into one group and
    emitted the adjacent pair (1,4) at the group average — a false merge.
    """

    def _seed(self, tmp_path):
        path = str(tmp_path / "pairs.db")
        conn = sqlite3.connect(path)
        conn.execute(
            "CREATE TABLE persons (id INTEGER PRIMARY KEY, name TEXT, "
            "face_count INTEGER, centroid BLOB, is_hidden INTEGER)"
        )
        rows = [
            (1, "P1", 40, _planar(0)),
            (2, "P2", 30, _planar(10)),
            (4, "P4", 20, _planar(60)),
            (3, "P3", 10, _planar(90, plane=(2, 3))),  # orthogonal to the others
        ]
        conn.executemany(
            "INSERT INTO persons VALUES (?, ?, ?, ?, 0)",
            [(i, n, fc, sqlite3.Binary(v.tobytes())) for i, n, fc, v in rows],
        )
        conn.commit()
        conn.close()
        return path

    def _pairs(self, tmp_path):
        from api.routers.merge_suggestions import _pairwise_suggestions
        path = self._seed(tmp_path)
        with mock.patch(f"{_ROUTER}.get_db", _db_cm(path)):
            suggestions = _pairwise_suggestions(0.6)
        return {
            tuple(sorted((s["person1"]["id"], s["person2"]["id"]))): s["similarity"]
            for s in suggestions
        }

    def test_only_true_pairs_above_threshold(self, tmp_path):
        pairs = self._pairs(tmp_path)
        assert set(pairs) == {(1, 2), (2, 4)}, pairs
        # The transitive pair (1,4) is below threshold and must not appear.
        assert (1, 4) not in pairs

    def test_each_pair_carries_its_own_similarity(self, tmp_path):
        pairs = self._pairs(tmp_path)
        assert pairs[(1, 2)] == pytest.approx(math.cos(math.radians(10)), abs=1e-4)
        assert pairs[(2, 4)] == pytest.approx(math.cos(math.radians(50)), abs=1e-4)
        # ...and they are genuinely different, not one shared group average.
        assert pairs[(1, 2)] > pairs[(2, 4)]

    def test_hidden_person_excluded(self, tmp_path):
        path = self._seed(tmp_path)
        conn = sqlite3.connect(path)
        conn.execute("UPDATE persons SET is_hidden = 1 WHERE id = 2")
        conn.commit()
        conn.close()
        from api.routers.merge_suggestions import _pairwise_suggestions
        with mock.patch(f"{_ROUTER}.get_db", _db_cm(path)):
            suggestions = _pairwise_suggestions(0.6)
        ids = {s["person1"]["id"] for s in suggestions} | {
            s["person2"]["id"] for s in suggestions
        }
        assert 2 not in ids
