"""possible_faces: the bounded centroid scan behind GET /api/person/{id}/possible_faces and the tool.

[REAL] ``agent_app`` (real auth chain, real lifespan) over the shared session database with real
``faces`` / ``persons`` rows holding real float32 embeddings.
"""

import sqlite3
from contextlib import contextmanager

import numpy as np
import pytest

from api.routers import face_matches
from tests.conftest import _TEST_DB_FILE, AGENT_DIR, intercept_internal_call

PFX = AGENT_DIR + "faces/"
PERSON, BOB, HIDDEN, EMPTY = 987101, 987102, 987103, 987104
DIM = 512


def embedding(similarity: float, dim: int = DIM) -> bytes:
    """A unit vector whose cosine with the centroid (axis 0) is ``similarity``."""
    vec = np.zeros(dim, dtype=np.float32)
    vec[0] = similarity
    vec[1] = float(np.sqrt(1.0 - similarity ** 2))
    return vec.tobytes()


PHOTOS = {name: PFX + ("sub/" if name in "ab" else "") + f"{name}.jpg" for name in "abcdefgh"}
# name -> (person_id, similarity, embedding_model, dim)
FACES = {
    "a": (None, 0.90, "arcface_buffalo_l", DIM),
    "b": (None, 0.50, "arcface_buffalo_l", DIM),
    "c": (None, 0.10, "arcface_buffalo_l", DIM),
    "d": (BOB, 0.80, "arcface_buffalo_l", DIM),
    "e": (HIDDEN, 0.95, "arcface_buffalo_l", DIM),
    "f": (None, 0.70, "sface", DIM),
    "g": (None, 0.99, "sface", 128),
    "h": (PERSON, 0.97, "arcface_buffalo_l", DIM),
}


def run(sql, params=()):
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        conn.execute(sql, params)


@pytest.fixture()
def library(seed_photos_prefix):
    seed_photos_prefix(PFX, [{"path": path, "filename": path.rsplit("/", 1)[-1], "aggregate": 5.0}
                             for path in PHOTOS.values()])
    centroid = np.zeros(DIM, dtype=np.float32)
    centroid[0] = 1.0
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        for pid, name, hidden, blob in ((PERSON, "Ann", 0, centroid.tobytes()), (BOB, "Bob", 0, None),
                                        (HIDDEN, "Ghost", 1, None), (EMPTY, "Nobody", 0, None)):
            conn.execute(
                "INSERT INTO persons(id, name, auto_clustered, face_count, is_hidden, centroid, centroid_model) "
                "VALUES (?, ?, 0, 1, ?, ?, ?)", (pid, name, hidden, blob, "arcface_buffalo_l" if blob else None))
        for index, (name, (owner, sim, model, dim)) in enumerate(FACES.items()):
            conn.execute(
                "INSERT INTO faces(photo_path, face_index, embedding, person_id, embedding_model) "
                "VALUES (?, ?, ?, ?, ?)", (PHOTOS[name], index, embedding(sim, dim), owner, model))
    yield
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        conn.execute("DELETE FROM faces WHERE photo_path LIKE ?", (PFX + "%",))
        conn.execute("DELETE FROM persons WHERE id IN (?, ?, ?, ?)", (PERSON, BOB, HIDDEN, EMPTY))


def call(agent_app, arguments, **mcp):
    env = agent_app("open", **mcp)
    return env, env.call(env.token(env.login()), "possible_faces", {"person_id": PERSON, "show": False, **arguments})


BOB_DIR = "/agent-bob-only/faces/"


@pytest.fixture()
def bob_library(library, seed_photos_prefix):
    paths = {"x": BOB_DIR + "x.jpg", "y": BOB_DIR + "y.jpg"}
    seed_photos_prefix(BOB_DIR, [{"path": path, "filename": path.rsplit("/", 1)[-1], "aggregate": 5.0}
                                 for path in paths.values()])
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        for index, (path, owner, sim) in enumerate(((paths["x"], None, 0.40), (paths["y"], PERSON, 0.99))):
            conn.execute(
                "INSERT INTO faces(photo_path, face_index, embedding, person_id, embedding_model) "
                "VALUES (?, ?, ?, ?, 'arcface_buffalo_l')", (path, 20 + index, embedding(sim), owner))
    yield
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        conn.execute("DELETE FROM faces WHERE photo_path LIKE ?", (BOB_DIR + "%",))


def names(result):
    return [row["photo_path"].rsplit("/", 1)[-1][0] for row in result["data"]["rows"]]


class TestVisibility:
    def test_a_users_scan_covers_only_the_faces_they_may_see(self, agent_app, bob_library):
        env = agent_app("multi")
        bob = env.call(env.token(env.login("bob")), "possible_faces",
                       {"person_id": PERSON, "show": False, "limit": 1})
        assert bob["ok"] is True, bob
        assert [r["photo_path"] for r in bob["data"]["rows"]] == [BOB_DIR + "x.jpg"]
        assert bob["data"]["faces_scanned"] == 1 and bob["data"]["candidates"] == 1
        alice = env.call(env.token(env.login("alice")), "possible_faces",
                         {"person_id": PERSON, "show": False, "limit": 1})
        assert [r["photo_path"] for r in alice["data"]["rows"]] == [PHOTOS["a"]]
        assert alice["data"]["candidates"] == 5


class TestScan:
    def test_unassigned_is_best_first_and_drops_wrong_model_and_below_floor(self, agent_app, library):
        _, result = call(agent_app, {})
        assert result["ok"] is True, result
        assert names(result) == ["a", "b"]
        first = result["data"]["rows"][0]
        assert first["similarity"] == pytest.approx(0.90, abs=1e-3)
        assert first["distance"] == pytest.approx(0.10, abs=1e-3)
        assert first["person_id"] is None and first["person_name"] is None

    def test_other_persons_names_the_owner_and_hides_hidden_persons(self, agent_app, library):
        _, result = call(agent_app, {"scope": "other_persons"})
        assert names(result) == ["d"]
        assert result["data"]["rows"][0]["person_name"] == "Bob"

    def test_all_covers_both_but_never_the_persons_own_faces(self, agent_app, library):
        _, result = call(agent_app, {"scope": "all"})
        assert names(result) == ["a", "d", "b"]

    def test_unnamed_is_every_face_without_a_name(self, agent_app, library):
        """In no cluster, or in a cluster nobody named; never a named, hidden or own face."""
        assert names(call(agent_app, {"scope": "unnamed"})[1]) == ["a", "b"]
        run("UPDATE persons SET name = NULL WHERE id = ?", (BOB,))
        assert names(call(agent_app, {"scope": "unnamed"})[1]) == ["a", "d", "b"]
        run("UPDATE persons SET name = '  ' WHERE id = ?", (BOB,))
        assert names(call(agent_app, {"scope": "unnamed"})[1]) == ["a", "d", "b"]

    def test_min_similarity_and_limit_apply(self, agent_app, library):
        assert names(call(agent_app, {"min_similarity": 0.6})[1]) == ["a"]
        assert names(call(agent_app, {"min_similarity": 0.0, "limit": 1})[1]) == ["a"]

    def test_the_count_is_index_only_and_the_scan_reads_matching_dimensions(self, agent_app, library):
        _, result = call(agent_app, {})
        # a, b, c and f are 512-d unassigned faces; g is 128-d: counted (index only), never read.
        assert result["data"]["faces_scanned"] == 4 and result["data"]["candidates"] == 5

    def test_the_candidate_count_is_a_covering_index_scan(self, library):
        from_sql, where_sql, params = face_matches._candidate_filter(PERSON, "unassigned", None, None, None, None)
        with sqlite3.connect(_TEST_DB_FILE.name) as conn:
            plan = " ".join(r[3] for r in conn.execute(
                f"EXPLAIN QUERY PLAN SELECT COUNT(*) FROM {from_sql} WHERE {where_sql}", params))
        assert "COVERING INDEX idx_faces_person" in plan, plan

    def test_the_scan_never_selects_the_model_or_thumbnail_and_checks_the_length(self, agent_app, library, monkeypatch):
        seen = []
        real = face_matches.get_db

        @contextmanager
        def spy():
            with real() as conn:
                conn.set_trace_callback(seen.append)
                yield conn

        monkeypatch.setattr(face_matches, "get_db", spy)
        call(agent_app, {})
        scans = [sql for sql in seen if sql.lstrip().startswith("SELECT f.id, f.embedding")]
        assert len(scans) == 1
        assert "embedding_model" not in scans[0] and "face_thumbnail" not in scans[0]
        assert f"length(f.embedding) = {DIM * 4}" in scans[0]

    def test_a_scan_over_the_ceiling_is_refused_with_the_count_and_the_levers(self, agent_app, library, monkeypatch):
        monkeypatch.setattr(face_matches, "MAX_FACE_SCAN", 3)
        _, result = call(agent_app, {})
        assert result["ok"] is False and result["error"] == "too_large"
        assert "5 faces" in result["message"] and "3" in result["message"] and "path_prefix" in result["message"]

    def test_the_ceiling_constants(self):
        assert face_matches.FACE_SCAN_TIMEOUT_S == 120 and face_matches.MAX_FACE_SCAN == 192000


class TestPeople:
    def test_a_person_without_a_centroid_is_invalid_input(self, agent_app, library):
        env = agent_app("open")
        result = env.call(env.token(env.login()), "possible_faces", {"person_id": EMPTY, "show": False})
        assert result["error"] == "invalid_input" and "centroid" in result["message"]

    def test_an_unknown_person_is_not_found(self, agent_app, library):
        env = agent_app("open")
        result = env.call(env.token(env.login()), "possible_faces", {"person_id": 999999, "show": False})
        assert result["error"] == "not_found"


class TestShow:
    def test_the_distinct_photos_are_pinned_in_similarity_order(self, agent_app, fake_tab, library):
        env = agent_app("open")
        tab = fake_tab(env, None, reply=lambda c: {"ok": True, "data": {"shown": 2, "missing": [], "total": 2}})
        result = env.call(env.token(env.login()), "possible_faces", {"person_id": PERSON})
        assert [(c["tool"], c["args"]) for c in tab.calls] == [
            ("ui_show_photos", {"paths": [PHOTOS["a"], PHOTOS["b"]]})]
        assert result["shown_in_tab"]["applied"] is True and result["shown_in_tab"]["mode"] == "paths"

    def test_show_false_and_an_empty_result_send_no_frame(self, agent_app, fake_tab, library):
        env = agent_app("open")
        tab = fake_tab(env, None, reply=lambda c: {"ok": True, "data": {}})
        token = env.token(env.login())
        env.call(token, "possible_faces", {"person_id": PERSON, "show": False})
        empty = env.call(token, "possible_faces", {"person_id": PERSON, "min_similarity": 0.999})
        assert tab.calls == [] and empty["shown_in_tab"]["reason"] == "empty_result"


class TestScanBounds:
    def test_a_refused_scan_reads_no_embedding(self, agent_app, library, monkeypatch):
        seen = []
        real = face_matches.get_db

        @contextmanager
        def spy():
            with real() as conn:
                conn.set_trace_callback(seen.append)
                yield conn

        monkeypatch.setattr(face_matches, "get_db", spy)
        monkeypatch.setattr(face_matches, "MAX_FACE_SCAN", 3)
        assert call(agent_app, {})[1]["error"] == "too_large"
        assert not [sql for sql in seen if "f.embedding FROM" in sql]

    def test_path_prefix_narrows_a_refused_scan_under_the_ceiling(self, agent_app, library, monkeypatch):
        monkeypatch.setattr(face_matches, "MAX_FACE_SCAN", 2)
        assert call(agent_app, {})[1]["error"] == "too_large"
        _, narrowed = call(agent_app, {"path_prefix": PFX + "sub"})
        assert narrowed["ok"] is True and narrowed["data"]["candidates"] == 2
        assert names(narrowed) == ["a", "b"]
        _, none = call(agent_app, {"date_from": "2999-01-01"})
        assert none["ok"] is True and none["data"]["candidates"] == 0 and none["data"]["rows"] == []

    def test_the_tool_waits_for_the_scan_budget_not_the_call_timeout(self, agent_app, library, monkeypatch):
        seen = {}

        def spy(tool, kwargs):
            if tool == "possible_faces":
                seen["timeout"] = kwargs["timeout"]

        intercept_internal_call(monkeypatch, spy)
        call(agent_app, {})
        assert seen["timeout"] == face_matches.FACE_SCAN_TIMEOUT_S == 120


def face_id(name):
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        return conn.execute("SELECT id FROM faces WHERE photo_path = ?", (PHOTOS[name],)).fetchone()[0]


def owner(name):
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        return conn.execute("SELECT person_id FROM faces WHERE photo_path = ?", (PHOTOS[name],)).fetchone()[0]


def assign(agent_app, face_names=(), extra=(), level="edition", destructive=False, **arguments):
    env = agent_app("legacy", allow_destructive=destructive)
    headers = env.login(edition=True)
    ids = [face_id(n) for n in face_names] + list(extra)
    return env, headers, env.call(env.token(headers, level), "assign_faces",
                                  {"person_id": PERSON, "face_ids": ids, **arguments})


class TestAssignFaces:
    def test_a_face_owned_by_another_person_is_left_alone_by_default(self, agent_app, library):
        _, _, result = assign(agent_app, "d")
        assert result["ok"] is True, result
        assert result["data"]["assigned_count"] == 0 and result["data"]["skipped_assigned"] == [face_id("d")]
        assert owner("d") == BOB

    def test_an_unknown_id_is_missing_and_the_rest_is_still_assigned(self, agent_app, library):
        _, _, result = assign(agent_app, "a", extra=[987654321])
        assert result["data"]["missing"] == [987654321] and result["data"]["assigned_count"] == 1
        assert owner("a") == PERSON

    def test_assigned_count_is_what_moved_not_what_was_asked(self, agent_app, library):
        _, _, result = assign(agent_app, "ab"[0] + "d", extra=[987654321])
        data = result["data"]
        assert data["assigned_count"] == 1 and len(data["missing"]) == 1 and len(data["skipped_assigned"]) == 1

    def test_a_face_of_another_model_and_a_hidden_persons_face_are_skipped(self, agent_app, library):
        _, _, result = assign(agent_app, "fe", destructive=True, allow_reassign=True)
        data = result["data"]
        assert data["skipped_model"] == [face_id("f")] and data["skipped_hidden"] == [face_id("e")]
        assert data["assigned_count"] == 0

    def test_a_face_already_on_the_person_is_reported_as_already(self, agent_app, library):
        _, _, result = assign(agent_app, "h")
        assert result["data"]["already"] == [face_id("h")] and result["data"]["assigned_count"] == 0

    def test_allow_reassign_moves_the_only_face_and_reports_the_deleted_person(self, agent_app, library):
        _, _, result = assign(agent_app, "d", destructive=True, allow_reassign=True)
        assert result["data"]["assigned_count"] == 1 and result["data"]["deleted_persons"] == [BOB]
        assert owner("d") == PERSON

    def test_allow_reassign_is_refused_without_allow_destructive_and_moves_nothing(self, agent_app, library):
        _, _, result = assign(agent_app, "d", allow_reassign=True)
        assert result["error"] == "feature_disabled" and "viewer.mcp.allow_destructive" in result["message"]
        assert owner("d") == BOB

    def test_a_readonly_token_is_forbidden_and_fifty_one_ids_are_too_large(self, agent_app, library):
        assert assign(agent_app, "a", level="readonly")[2]["error"] == "forbidden_level"
        assert owner("a") is None
        assert assign(agent_app, extra=list(range(1, 52)))[2]["error"] == "too_large"

    def test_the_viewer_route_still_404s_on_an_unknown_id(self, agent_app, library):
        env = agent_app("legacy")
        headers = env.login(edition=True)
        resp = env.client.post(f"/api/persons/{PERSON}/assign_faces", json={"face_ids": [987654321]},
                               headers=headers)
        assert resp.status_code == 404


def test_only_unassigned_without_tolerant_is_refused_by_the_request_model():
    import pydantic
    from api.routers.persons import AssignFacesRequest
    with pytest.raises(pydantic.ValidationError, match="only_unassigned"):
        AssignFacesRequest(face_ids=[1], only_unassigned=True)
    assert AssignFacesRequest(face_ids=[1], only_unassigned=True, tolerant=True).only_unassigned
    assert not AssignFacesRequest(face_ids=[1]).only_unassigned
