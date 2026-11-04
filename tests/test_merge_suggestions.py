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
from db.schema import init_database

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
        with mock.patch(f"{_ROUTER}._pairwise_suggestions", return_value=(_ONE_PAIR, False)):
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
        with mock.patch(f"{_ROUTER}._pairwise_suggestions", return_value=([], False)):
            resp = client.get("/api/merge_suggestions")

        assert resp.status_code == 200
        assert resp.json()["suggestions"] == []
        assert resp.json()["truncated"] is False

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
        init_database(path)
        conn = sqlite3.connect(path)
        rows = [
            (1, "P1", 40, _planar(0)),
            (2, "P2", 30, _planar(10)),
            (4, "P4", 20, _planar(60)),
            (3, "P3", 10, _planar(90, plane=(2, 3))),  # orthogonal to the others
        ]
        conn.executemany(
            "INSERT INTO persons (id, name, face_count, centroid, is_hidden) VALUES (?, ?, ?, ?, 0)",
            [(i, n, fc, sqlite3.Binary(v.tobytes())) for i, n, fc, v in rows],
        )
        conn.commit()
        conn.close()
        return path

    def _pairs(self, tmp_path):
        from api.routers.merge_suggestions import _pairwise_suggestions
        path = self._seed(tmp_path)
        with mock.patch(f"{_ROUTER}.get_db", _db_cm(path)):
            suggestions, _ = _pairwise_suggestions(0.6)
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

    def test_orders_by_similarity_and_caps_the_response(self, tmp_path, monkeypatch):
        """The most similar pairs come first, and a low threshold cannot
        serialize an unbounded hit set into one response."""
        monkeypatch.setattr('api.routers.merge_suggestions.MAX_MERGE_SUGGESTIONS', 2)
        from api.routers.merge_suggestions import _pairwise_suggestions
        path = self._seed(tmp_path)
        with mock.patch(f"{_ROUTER}.get_db", _db_cm(path)):
            suggestions, _ = _pairwise_suggestions(0.0)
        assert len(suggestions) == 2
        sims = [s['similarity'] for s in suggestions]
        assert sims == sorted(sims, reverse=True)
        # The planar geometry makes (1,2) at cos(10deg) the closest pair.
        assert suggestions[0]['person1']['id'] == 1 and suggestions[0]['person2']['id'] == 2

    def test_dismissals_do_not_consume_the_cap(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(f"{_ROUTER}.MAX_MERGE_SUGGESTIONS", 2)
        monkeypatch.setattr(f"{_ROUTER}._SCORE_BLOCK_ROWS", 1)
        path = self._seed(tmp_path)
        with sqlite3.connect(path) as conn:
            conn.execute(
                "INSERT INTO rejected_merge_suggestions (person_a_id, person_b_id) VALUES (1, 2)"
            )
            # A legacy or hand-edited self-pair must not mask another person.
            conn.execute(
                "INSERT INTO rejected_merge_suggestions (person_a_id, person_b_id) VALUES (1, 1)"
            )

        with mock.patch(f"{_ROUTER}.get_db", _db_cm(path)):
            response = client.get("/api/merge_suggestions", params={"threshold": 0.0})
            exact = client.get("/api/merge_suggestions", params={"threshold": 0.49})
            monkeypatch.setattr(f"{_ROUTER}.MAX_MERGE_SUGGESTIONS", 5)
            all_eligible = client.get("/api/merge_suggestions", params={"threshold": 0.0})

        assert response.status_code == 200
        body = response.json()
        assert [(s["person1"]["id"], s["person2"]["id"]) for s in body["suggestions"]] == [
            (2, 4), (1, 4),
        ]
        assert body["truncated"] is True
        assert exact.status_code == 200
        assert exact.json()["suggestions"] == body["suggestions"]
        assert exact.json()["truncated"] is False
        assert all_eligible.status_code == 200
        assert len(all_eligible.json()["suggestions"]) == 5
        assert all_eligible.json()["truncated"] is False

    def test_visible_scoping_skips_scoring_outside_the_set(self, tmp_path):
        """Multi-user scoping applies before the quadratic work: a caller whose
        visible set is small must not pay to score the whole installation."""
        from api.routers.merge_suggestions import _pairwise_suggestions
        path = self._seed(tmp_path)
        with mock.patch(f"{_ROUTER}.get_db", _db_cm(path)):
            suggestions, _ = _pairwise_suggestions(0.6, visible={1, 2})
        assert {tuple(sorted((s['person1']['id'], s['person2']['id']))) for s in suggestions} == {(1, 2)}

    def test_hidden_person_excluded(self, tmp_path):
        path = self._seed(tmp_path)
        conn = sqlite3.connect(path)
        conn.execute("UPDATE persons SET is_hidden = 1 WHERE id = 2")
        conn.commit()
        conn.close()
        from api.routers.merge_suggestions import _pairwise_suggestions
        with mock.patch(f"{_ROUTER}.get_db", _db_cm(path)):
            suggestions, _ = _pairwise_suggestions(0.6)
        ids = {s["person1"]["id"] for s in suggestions} | {
            s["person2"]["id"] for s in suggestions
        }
        assert 2 not in ids


class TestReportedThreshold:
    """The response names the threshold it applied, so the client need not know a per-model one."""

    def test_reports_the_active_models_default_when_none_is_sent(self, client):
        cfg = mock.Mock()
        cfg.get_face_clustering_settings.return_value = {"merge_threshold": 0.45}
        with mock.patch(f"{_ROUTER}.server_scoring_config", return_value=cfg), \
                mock.patch(f"{_ROUTER}._pairwise_suggestions", return_value=([], False)) as pairwise:
            body = client.get("/api/merge_suggestions").json()
        assert body["threshold"] == 0.45
        assert pairwise.call_args.args[0] == 0.45

    def test_reports_the_callers_threshold_when_sent(self, client):
        with mock.patch(f"{_ROUTER}._pairwise_suggestions", return_value=([], False)):
            body = client.get("/api/merge_suggestions", params={"threshold": 0.7}).json()
        assert body["threshold"] == 0.7


class TestConfigAdvertisesMergeThreshold:
    """/api/config seeds the slider before the first /merge_suggestions response."""

    def test_reports_the_active_models_threshold(self, client):
        cfg = mock.Mock()
        cfg.get_face_clustering_settings.return_value = {"merge_threshold": 0.65}
        with mock.patch("api.config.server_scoring_config", return_value=cfg):
            body = client.get("/api/config").json()
        assert body["face_merge_threshold"] == 0.65
        assert isinstance(body["face_merge_threshold"], float)

    def test_omits_the_field_when_the_model_has_no_entry(self, client):
        cfg = mock.Mock()
        cfg.get_face_clustering_settings.side_effect = ValueError("no entry")
        with mock.patch("api.config.server_scoring_config", return_value=cfg):
            body = client.get("/api/config").json()
        assert "face_merge_threshold" not in body
