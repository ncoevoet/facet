"""Server side of the people-naming workflow (PR #415 review fixes).

* ``POST /api/person/{id}/face_boxes`` — one batch call for a gallery screen's
  face outlines, instead of one ``/api/photo/faces`` per tile;
* ``POST /api/face/{id}/unassign`` — "Not X" on the one face that was clicked;
* ``GET /api/persons`` — ``hidden_only`` never lets hidden persons into
  ``sort=assignment``, and ``named_only`` / ``hidden_only`` stay inside the
  caller's directories in multi-user mode;
* ``GET /api/person/{id}/possible_faces?scope=unnamed`` through the REST route.

Rows go through the shared ``seed_people`` fixture (real schema, autoincrement
ids, prefix-scoped cleanup). Multi-user mode is switched on by patching the
``api.db_helpers`` visibility helpers, never an auth dependency.
"""

import os
import sqlite3
from contextlib import contextmanager
from unittest import mock

import numpy as np

PREFIX = "/test_people_workflow/"
MINE = PREFIX + "mine/"
THEIRS = PREFIX + "theirs/"


def _db():
    return sqlite3.connect(os.environ["DB_PATH"])


@contextmanager
def _multi_user(directories):
    """Multi-user mode where ``directories`` maps user ids to their roots."""
    with (
        mock.patch("api.db_helpers.is_multi_user_enabled", return_value=True),
        mock.patch("api.db_helpers.get_user_directories",
                   side_effect=lambda uid: directories.get(uid, [])),
    ):
        yield


def _person_row(person_id):
    conn = _db()
    try:
        return conn.execute(
            "SELECT face_count, representative_face_id FROM persons WHERE id = ?",
            (person_id,)).fetchone()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# POST /api/person/{id}/face_boxes
# ---------------------------------------------------------------------------

class TestPersonFaceBoxes:
    def test_returns_only_that_persons_normalised_boxes(self, regular_client, seed_people):
        anna = seed_people.person("Anna")
        bob = seed_people.person("Bob")
        both = seed_people.photo(PREFIX, "both.jpg", image_width=1000, image_height=500)
        alone = seed_people.photo(PREFIX, "alone.jpg", image_width=200, image_height=100)
        nobody = seed_people.photo(PREFIX, "bob_only.jpg", image_width=1000, image_height=500)
        seed_people.face(both, anna, bbox=(100, 50, 300, 250))
        seed_people.face(both, bob, bbox=(500, 50, 700, 250))
        seed_people.face(both, None, bbox=(800, 50, 900, 150))
        seed_people.face(alone, anna, bbox=(20, 10, 60, 50))
        seed_people.face(nobody, bob, bbox=(1, 1, 50, 50))

        resp = regular_client.post(f"/api/person/{anna}/face_boxes",
                                   json={"paths": [both, alone, nobody]})

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"boxes": {
            both: [[0.1, 0.1, 0.3, 0.5]],
            alone: [[0.1, 0.1, 0.3, 0.5]],
        }}

    def test_untrusted_box_is_dropped_and_its_path_omitted(self, regular_client, seed_people):
        anna = seed_people.person("Anna")
        mixed = seed_people.photo(PREFIX, "mixed.jpg", image_width=1000, image_height=500)
        unsized = seed_people.photo(PREFIX, "unsized.jpg")
        seed_people.face(mixed, anna, bbox=(100, 50, 300, 250))
        # Far outside a 1000x500 frame: a coordinate-space mismatch, never drawn.
        seed_people.face(mixed, anna, bbox=(2000, 50, 2400, 250))
        seed_people.face(unsized, anna, bbox=(1, 1, 6, 6))

        body = regular_client.post(f"/api/person/{anna}/face_boxes",
                                   json={"paths": [mixed, unsized]}).json()

        assert body == {"boxes": {mixed: [[0.1, 0.1, 0.3, 0.5]]}}

    def test_invisible_and_unknown_paths_are_absent(self, regular_client, seed_people):
        anna = seed_people.person("Anna")
        mine = seed_people.photo(MINE, "a.jpg", image_width=1000, image_height=500)
        theirs = seed_people.photo(THEIRS, "b.jpg", image_width=1000, image_height=500)
        seed_people.face(mine, anna, bbox=(100, 50, 300, 250))
        seed_people.face(theirs, anna, bbox=(100, 50, 300, 250))

        with _multi_user({"u1": [MINE.rstrip("/")]}):
            body = regular_client.post(
                f"/api/person/{anna}/face_boxes",
                json={"paths": [mine, theirs, PREFIX + "missing.jpg"]}).json()

        assert body == {"boxes": {mine: [[0.1, 0.1, 0.3, 0.5]]}}

    def test_anonymous_caller_on_a_protected_install_is_refused(self, anonymous_client):
        with mock.patch.dict("api.auth.VIEWER_CONFIG", {"password": "secret"}):
            resp = anonymous_client.post("/api/person/1/face_boxes", json={"paths": ["/x/a.jpg"]})

        assert resp.status_code == 401

    def test_rejects_more_than_200_paths_and_none(self, regular_client):
        too_many = regular_client.post("/api/person/1/face_boxes",
                                       json={"paths": [f"/x/{i}.jpg" for i in range(201)]})
        exactly = regular_client.post("/api/person/1/face_boxes",
                                      json={"paths": [f"/x/{i}.jpg" for i in range(200)]})
        empty = regular_client.post("/api/person/1/face_boxes", json={"paths": []})

        assert too_many.status_code == 422
        assert exactly.status_code == 200
        assert exactly.json() == {"boxes": {}}
        assert empty.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/face/{id}/unassign
# ---------------------------------------------------------------------------

class TestUnassignFace:
    def test_requires_edition(self, regular_client, seed_people):
        anna = seed_people.person("Anna")
        face = seed_people.face(seed_people.photo(PREFIX, "a.jpg"), anna)

        resp = regular_client.post(f"/api/face/{face}/unassign")

        assert resp.status_code == 403
        conn = _db()
        try:
            owner = conn.execute("SELECT person_id FROM faces WHERE id = ?", (face,)).fetchone()[0]
        finally:
            conn.close()
        assert owner == anna

    def test_detaches_only_that_face_and_repairs_the_person(self, edition_client, seed_people):
        anna = seed_people.person("Anna")
        photo = seed_people.photo(PREFIX, "two_annas.jpg")
        clicked = seed_people.face(photo, anna, confidence=0.99)
        kept = seed_people.face(photo, anna, confidence=0.5)
        conn = _db()
        conn.execute("UPDATE persons SET representative_face_id = ? WHERE id = ?", (clicked, anna))
        conn.commit()
        conn.close()

        resp = edition_client.post(f"/api/face/{clicked}/unassign")

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"success": True, "face_id": clicked, "person_id": anna}
        conn = _db()
        try:
            owners = dict(conn.execute(
                "SELECT id, person_id FROM faces WHERE id IN (?, ?)", (clicked, kept)).fetchall())
        finally:
            conn.close()
        # The other face of the same person in the same photo stays put, unlike
        # /api/photo/unassign_person, which drops the person from the whole photo.
        assert owners == {clicked: None, kept: anna}
        assert _person_row(anna) == (1, kept)

    def test_last_face_deletes_the_emptied_person(self, edition_client, seed_people):
        anna = seed_people.person("Anna")
        face = seed_people.face(seed_people.photo(PREFIX, "only.jpg"), anna)

        resp = edition_client.post(f"/api/face/{face}/unassign")

        # Gone, as /api/photo/unassign_person leaves it; still named in the response.
        assert resp.json() == {"success": True, "face_id": face, "person_id": anna}
        assert _person_row(anna) is None

    def test_an_unassigned_face_reports_no_person(self, edition_client, seed_people):
        face = seed_people.face(seed_people.photo(PREFIX, "loose.jpg"))

        resp = edition_client.post(f"/api/face/{face}/unassign")

        assert resp.json() == {"success": True, "face_id": face, "person_id": None}

    def test_unknown_and_invisible_faces_are_404(self, edition_client, seed_people):
        anna = seed_people.person("Anna")
        theirs = seed_people.face(seed_people.photo(THEIRS, "b.jpg"), anna)
        mine = seed_people.face(seed_people.photo(MINE, "a.jpg"), anna)

        unknown = edition_client.post("/api/face/987654321/unassign")
        with _multi_user({"test": [MINE.rstrip("/")]}):
            invisible = edition_client.post(f"/api/face/{theirs}/unassign")
            visible = edition_client.post(f"/api/face/{mine}/unassign")

        assert unknown.status_code == 404
        assert invisible.status_code == 404
        # The same caller may still detach a face in its own directories.
        assert visible.status_code == 200, visible.text
        assert visible.json()["person_id"] == anna
        assert _person_row(anna)[0] == 1


# ---------------------------------------------------------------------------
# GET /api/persons — hidden_only / named_only
# ---------------------------------------------------------------------------

class TestPersonsListFilters:
    TOKEN = "Zqxwfl"  # a name fragment nothing else in the session DB carries

    def _ids(self, client, **params):
        resp = client.get("/api/persons", params={"search": self.TOKEN, "per_page": 200, **params})
        assert resp.status_code == 200, resp.text
        return {p["id"] for p in resp.json()["persons"]}

    def test_hidden_only_does_not_admit_hidden_persons_to_assignment(self, regular_client, seed_people):
        shown = seed_people.person(f"{self.TOKEN} shown")
        hidden = seed_people.person(f"{self.TOKEN} hidden", is_hidden=1)
        photo = seed_people.photo(PREFIX, "a.jpg")
        seed_people.face(photo, shown)
        seed_people.face(photo, hidden)

        assignment = self._ids(regular_client, sort="assignment", hidden_only=True)
        ignored = self._ids(regular_client, hidden_only=True)

        assert assignment == {shown}
        assert ignored == {hidden}

    def test_named_and_hidden_only_stay_inside_the_callers_directories(self, regular_client, seed_people):
        mine = seed_people.photo(MINE, "a.jpg")
        theirs = seed_people.photo(THEIRS, "b.jpg")
        my_named = seed_people.person(f"{self.TOKEN} mine")
        their_named = seed_people.person(f"{self.TOKEN} theirs")
        my_hidden = seed_people.person(f"{self.TOKEN} mine hidden", is_hidden=1)
        their_hidden = seed_people.person(f"{self.TOKEN} theirs hidden", is_hidden=1)
        for path, person in ((mine, my_named), (theirs, their_named),
                             (mine, my_hidden), (theirs, their_hidden)):
            seed_people.face(path, person)

        with _multi_user({"u1": [MINE.rstrip("/")]}):
            named = self._ids(regular_client, named_only=True)
            hidden = self._ids(regular_client, hidden_only=True)

        assert named == {my_named}
        assert hidden == {my_hidden}


# ---------------------------------------------------------------------------
# GET /api/person/{id}/possible_faces?scope=unnamed
# ---------------------------------------------------------------------------

def _vector(*head):
    vector = np.zeros(512, dtype=np.float32)
    vector[:len(head)] = head
    return vector.tobytes()


def test_possible_faces_unnamed_scope_through_rest(regular_client, seed_people):
    target = seed_people.person("Anna")
    unnamed = seed_people.person(None)
    named = seed_people.person("Bob")
    conn = _db()
    conn.execute("UPDATE persons SET centroid = ? WHERE id = ?", (_vector(1.0), target))
    conn.commit()
    conn.close()
    photo = seed_people.photo(PREFIX, "crowd.jpg")
    own = seed_people.face(photo, target, embedding=_vector(1.0))
    loose = seed_people.face(photo, None, embedding=_vector(1.0, 0.1))
    in_unnamed = seed_people.face(photo, unnamed, embedding=_vector(1.0, 0.2))
    seed_people.face(photo, named, embedding=_vector(1.0, 0.3))

    resp = regular_client.get(f"/api/person/{target}/possible_faces",
                              params={"scope": "unnamed", "path_prefix": PREFIX})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    # A face in no cluster and a face in an unnamed cluster; never the target's own
    # face, nor one already in a named cluster.
    assert [f["face_id"] for f in body["faces"]] == [loose, in_unnamed]
    assert own not in {f["face_id"] for f in body["faces"]}
    assert body["candidates"] == 2


# ---------------------------------------------------------------------------
# possible_faces: owners, counts, best_similarity, similar_groups
# ---------------------------------------------------------------------------

def _set_centroid(person_id, vector, model=None):
    conn = _db()
    conn.execute("UPDATE persons SET centroid = ?, centroid_model = ? WHERE id = ?",
                 (vector, model, person_id))
    conn.commit()
    conn.close()


class TestPossibleFacesOwners:
    @staticmethod
    def _crowd(seed_people):
        """Target Anna; five ungrouped faces that beat one unnamed-group and one named face."""
        target = seed_people.person("Anna")
        unnamed = seed_people.person(None)
        bob = seed_people.person("Bob")
        _set_centroid(target, _vector(1.0))
        photo = seed_people.photo(PREFIX, "crowd.jpg")
        ungrouped = [seed_people.face(photo, None, embedding=_vector(1.0, 0.01 * i)) for i in range(5)]
        in_unnamed = seed_people.face(photo, unnamed, embedding=_vector(1.0, 0.2))
        in_bob = seed_people.face(photo, bob, embedding=_vector(1.0, 0.3))
        seed_people.face(photo, None, embedding=_vector(0.0, 1.0))  # unrelated: below any threshold
        return target, ungrouped, in_unnamed, in_bob

    def _get(self, client, person_id, **params):
        return client.get(f"/api/person/{person_id}/possible_faces",
                          params={"scope": "all", "path_prefix": PREFIX, **params})

    def test_owners_filters_before_the_limit(self, regular_client, seed_people):
        target, ungrouped, _, in_bob = self._crowd(seed_people)

        named = self._get(regular_client, target, limit=1, owners="named")
        anyone = self._get(regular_client, target, limit=1)

        assert named.status_code == 200, named.text
        # Five better ungrouped faces fill the keep window (4 x limit) before Bob's is seen.
        assert [(f["face_id"], f["owner"]) for f in named.json()["faces"]] == [(in_bob, "named")]
        assert [(f["face_id"], f["owner"]) for f in anyone.json()["faces"]] == [(ungrouped[0], "ungrouped")]

    def test_counts_ignore_owners_and_limit(self, regular_client, seed_people):
        target, *_ = self._crowd(seed_people)

        expected = {"ungrouped": 5, "unnamed_group": 1, "named": 1}
        for params in ({}, {"owners": "named", "limit": 1}, {"owners": "ungrouped,unnamed_group"}):
            body = self._get(regular_client, target, **params).json()
            assert body["counts"] == expected, params

    def test_owner_classes_on_each_face(self, regular_client, seed_people):
        target, ungrouped, in_unnamed, in_bob = self._crowd(seed_people)

        body = self._get(regular_client, target, owners="unnamed_group,named").json()

        assert {f["face_id"]: f["owner"] for f in body["faces"]} == {
            in_unnamed: "unnamed_group", in_bob: "named"}

    def test_per_owner_limit_applies_to_each_class(self, regular_client, seed_people):
        target, ungrouped, in_unnamed, in_bob = self._crowd(seed_people)

        body = self._get(regular_client, target, limit=1, per_owner="true").json()

        assert [(f["face_id"], f["owner"]) for f in body["faces"]] == [
            (ungrouped[0], "ungrouped"), (in_unnamed, "unnamed_group"), (in_bob, "named")]
        sims = [f["similarity"] for f in body["faces"]]
        assert sims == sorted(sims, reverse=True)
        assert body["counts"] == {"ungrouped": 5, "unnamed_group": 1, "named": 1}

    def test_per_owner_still_honours_owners(self, regular_client, seed_people):
        target, ungrouped, _, in_bob = self._crowd(seed_people)

        body = self._get(regular_client, target, limit=2, per_owner="true",
                         owners="ungrouped,named").json()

        assert [f["face_id"] for f in body["faces"]] == [ungrouped[0], ungrouped[1], in_bob]

    def test_default_keeps_one_global_limit(self, regular_client, seed_people):
        target, ungrouped, *_ = self._crowd(seed_people)

        explicit = self._get(regular_client, target, limit=2, per_owner="false").json()
        default = self._get(regular_client, target, limit=2).json()

        assert explicit == default
        assert [f["face_id"] for f in default["faces"]] == ungrouped[:2]

    def test_best_similarity_when_every_face_is_below_the_threshold(self, regular_client, seed_people):
        target = seed_people.person("Anna")
        _set_centroid(target, _vector(1.0))
        photo = seed_people.photo(PREFIX, "far.jpg")
        seed_people.face(photo, None, embedding=_vector(1.0, 0.5))  # cos = 0.8944
        seed_people.face(photo, None, embedding=_vector(0.0, 1.0))

        body = self._get(regular_client, target, min_similarity=0.95).json()

        assert body["faces"] == []
        assert body["counts"] == {"ungrouped": 0, "unnamed_group": 0, "named": 0}
        assert body["best_similarity"] == 0.8944

    def test_best_similarity_is_null_when_nothing_is_scanned(self, regular_client, seed_people):
        target = seed_people.person("Anna")
        _set_centroid(target, _vector(1.0))

        body = self._get(regular_client, target, path_prefix=PREFIX + "empty/").json()

        assert body["faces_scanned"] == 0
        assert body["best_similarity"] is None

    def test_bad_owner_is_422(self, regular_client, seed_people):
        target = seed_people.person("Anna")
        _set_centroid(target, _vector(1.0))

        for owners in ("strangers", "named,", ""):
            assert self._get(regular_client, target, owners=owners).status_code == 422, owners


class TestPossibleFacesSimilarGroups:
    def test_lists_close_visible_same_model_groups_best_first(self, regular_client, seed_people):
        target = seed_people.person("Anna")
        close_unnamed = seed_people.person(None)
        closer_named = seed_people.person("Anna B")
        hidden = seed_people.person(None, is_hidden=1)
        other_model = seed_people.person(None)
        far = seed_people.person(None)
        _set_centroid(target, _vector(1.0))
        _set_centroid(close_unnamed, _vector(1.0, 0.3))
        _set_centroid(closer_named, _vector(1.0, 0.1))
        _set_centroid(hidden, _vector(1.0))
        _set_centroid(other_model, _vector(1.0), model="sface")
        _set_centroid(far, _vector(0.0, 1.0))
        photo = seed_people.photo(PREFIX, "groups.jpg")
        for person in (close_unnamed, closer_named, closer_named, hidden, other_model, far):
            seed_people.face(photo, person)
        mine = {target, close_unnamed, closer_named, hidden, other_model, far}

        body = regular_client.get(f"/api/person/{target}/possible_faces",
                                  params={"path_prefix": PREFIX}).json()

        groups = [g for g in body["similar_groups"] if g["person_id"] in mine]
        assert groups == [
            {"person_id": closer_named, "name": "Anna B", "face_count": 2, "similarity": 0.995},
            {"person_id": close_unnamed, "name": None, "face_count": 1, "similarity": 0.9578},
        ]


# ---------------------------------------------------------------------------
# Unassign keeps the surviving person's centroid in step
# ---------------------------------------------------------------------------

def _stored_centroid(person_id):
    conn = _db()
    try:
        raw = conn.execute("SELECT centroid FROM persons WHERE id = ?", (person_id,)).fetchone()[0]
    finally:
        conn.close()
    return None if raw is None else np.frombuffer(raw, dtype=np.float32)


def test_unassign_recomputes_the_surviving_persons_centroid(edition_client, seed_people):
    anna = seed_people.person("Anna")
    photo = seed_people.photo(PREFIX, "centroid.jpg")
    clicked = seed_people.face(photo, anna, embedding=_vector(0.0, 1.0))
    seed_people.face(photo, anna, embedding=_vector(1.0, 0.0))
    _set_centroid(anna, _vector(1.0, 1.0))

    resp = edition_client.post(f"/api/face/{clicked}/unassign")

    assert resp.status_code == 200, resp.text
    # Only the (1, 0) face remains: the stale mean of both faces would not be this.
    centroid = _stored_centroid(anna)
    assert centroid is not None
    assert np.allclose(centroid[:2], [1.0, 0.0], atol=1e-5)


# ---------------------------------------------------------------------------
# POST /api/face/{id}/assign — the target's representative
# ---------------------------------------------------------------------------

class TestAssignRepresentative:
    def test_a_target_without_a_representative_gets_one(self, edition_client, seed_people):
        anna = seed_people.person("Anna")
        face = seed_people.face(seed_people.photo(PREFIX, "loose_assign.jpg"))
        assert _person_row(anna) == (0, None)

        resp = edition_client.post(f"/api/face/{face}/assign", json={"person_id": anna})

        assert resp.status_code == 200, resp.text
        assert _person_row(anna) == (1, face)

    def test_a_target_that_has_one_keeps_it(self, edition_client, seed_people):
        anna = seed_people.person("Anna")
        photo = seed_people.photo(PREFIX, "keeps.jpg")
        first = seed_people.face(photo, anna, confidence=0.5)
        newcomer = seed_people.face(photo, None, confidence=0.99)
        conn = _db()
        conn.execute("UPDATE persons SET representative_face_id = ? WHERE id = ?", (first, anna))
        conn.commit()
        conn.close()

        resp = edition_client.post(f"/api/face/{newcomer}/assign", json={"person_id": anna})

        assert resp.status_code == 200, resp.text
        assert _person_row(anna) == (2, first)


# ---------------------------------------------------------------------------
# Multi-user: another user's persons never leak into the suggestions
# ---------------------------------------------------------------------------

def test_possible_faces_similar_groups_omit_a_persons_only_in_other_directories(
        regular_client, seed_people):
    target = seed_people.person("Anna")
    mine = seed_people.person(None)
    theirs = seed_people.person(None)
    for person in (target, mine, theirs):
        _set_centroid(person, _vector(1.0))
    seed_people.face(seed_people.photo(MINE, "t.jpg"), target)
    seed_people.face(seed_people.photo(MINE, "m.jpg"), mine)
    seed_people.face(seed_people.photo(THEIRS, "x.jpg"), theirs)

    with _multi_user({"u1": [MINE.rstrip("/")]}):
        body = regular_client.get(f"/api/person/{target}/possible_faces",
                                  params={"path_prefix": PREFIX}).json()

    ids = {g["person_id"] for g in body["similar_groups"]}
    assert mine in ids
    assert theirs not in ids


def test_rename_same_name_persons_omit_a_person_only_in_other_directories(
        edition_client, seed_people):
    target = seed_people.person(None)
    mine = seed_people.person("Peter Salem")
    theirs = seed_people.person("peter salem")
    seed_people.face(seed_people.photo(MINE, "t.jpg"), target)
    seed_people.face(seed_people.photo(MINE, "m.jpg"), mine)
    seed_people.face(seed_people.photo(THEIRS, "x.jpg"), theirs)

    with _multi_user({"test": [MINE.rstrip("/")]}):
        resp = edition_client.post(f"/api/persons/{target}/rename", json={"name": "Peter Salem"})

    assert resp.status_code == 200, resp.text
    assert [p["id"] for p in resp.json()["same_name_persons"]] == [mine]


def test_unnamed_sql_clause_and_python_predicate_agree():
    from api.db_helpers import is_unnamed, person_unnamed_clause
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE p (name TEXT)")
    for name in (None, "", "  ", "\t", "Ann"):
        conn.execute("DELETE FROM p")
        conn.execute("INSERT INTO p VALUES (?)", (name,))
        in_sql = bool(conn.execute(f"SELECT {person_unnamed_clause('p')} FROM p").fetchone()[0])
        assert in_sql == is_unnamed(name), repr(name)
    conn.close()
