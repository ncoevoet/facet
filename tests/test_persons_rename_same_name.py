"""POST /api/persons/{id}/rename reports other persons of the same name.

Clustering often splits one person over several clusters; naming the second one
"peter salem" when "Peter Salem" exists should let the viewer offer a merge. The
rename itself never merges (two people may share a name), it only reports.

Rows are built with the shared ``seed_people`` fixture (real schema, autoincrement
person ids, prefix-scoped cleanup), never a hand-rolled table or fixed ids.
"""

import os
import sqlite3

PREFIX = "/test_rename_same_name/"


def _person_with_faces(seed_people, name, faces, is_hidden=0):
    person_id = seed_people.person(name, is_hidden=is_hidden)
    for i in range(faces):
        seed_people.face(seed_people.photo(PREFIX, f"{person_id}_{i}.jpg"), person_id)
    return person_id


def _names(ids):
    conn = sqlite3.connect(os.environ["DB_PATH"])
    try:
        return dict(conn.execute(
            f"SELECT id, name FROM persons WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall())
    finally:
        conn.close()


def test_rename_reports_same_name_ignoring_case_and_spaces(edition_client, seed_people):
    target = _person_with_faces(seed_people, None, 1)
    smaller = _person_with_faces(seed_people, "Peter Salem", 2)
    larger = _person_with_faces(seed_people, "  PETER salem ", 3)
    _person_with_faces(seed_people, "Peter Salemi", 4)

    resp = edition_client.post(f"/api/persons/{target}/rename", json={"name": "peter salem"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "peter salem"
    assert body["face_count"] == 1
    # Largest first; the near-miss "Peter Salemi" is not reported.
    assert body["same_name_persons"] == [
        {"id": larger, "name": "  PETER salem ", "face_count": 3},
        {"id": smaller, "name": "Peter Salem", "face_count": 2},
    ]
    # Reporting only: nothing merged, nothing else renamed.
    assert _names([target, smaller, larger]) == {
        target: "peter salem", smaller: "Peter Salem", larger: "  PETER salem "}


def test_rename_skips_hidden_same_name(edition_client, seed_people):
    target = _person_with_faces(seed_people, None, 1)
    _person_with_faces(seed_people, "Anna", 2, is_hidden=1)

    body = edition_client.post(f"/api/persons/{target}/rename", json={"name": "anna"}).json()

    assert body["same_name_persons"] == []


def test_rename_folds_non_ascii_case(edition_client, seed_people):
    target = _person_with_faces(seed_people, None, 1)
    elodie = _person_with_faces(seed_people, "Élodie", 2)

    body = edition_client.post(f"/api/persons/{target}/rename", json={"name": "élodie"}).json()

    assert [p["id"] for p in body["same_name_persons"]] == [elodie]


def test_clearing_a_name_reports_nothing(edition_client, seed_people):
    target = _person_with_faces(seed_people, "Bob", 1)
    _person_with_faces(seed_people, None, 2)

    body = edition_client.post(f"/api/persons/{target}/rename", json={"name": ""}).json()

    assert body["same_name_persons"] == []
    assert _names([target]) == {target: None}
