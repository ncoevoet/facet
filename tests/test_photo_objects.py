"""User-marked objects: labelled boxes on a photo, searchable, never faces."""

import sqlite3

import pytest

from tests.conftest import _TEST_DB_FILE

PREFIX = "/photo-objects-test/"


@pytest.fixture()
def photo(seed_photos_prefix):
    seed_photos_prefix(PREFIX, [
        {"path": PREFIX + "party.jpg", "filename": "party.jpg", "aggregate": 7.0,
         "category": "default", "date_taken": "2026:02:01 10:00:00"},
        {"path": PREFIX + "beach.jpg", "filename": "beach.jpg", "aggregate": 6.0,
         "category": "default", "date_taken": "2026:02:02 10:00:00"},
    ])
    yield PREFIX + "party.jpg"
    # The seeder's teardown connection does not enforce foreign keys.
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        conn.execute("DELETE FROM photo_objects WHERE photo_path LIKE ?", (PREFIX + "%",))


def _faces(path):
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        return conn.execute("SELECT COUNT(*) FROM faces WHERE photo_path = ?", (path,)).fetchone()[0]


def test_mark_list_and_remove(edition_client, photo):
    created = edition_client.post("/api/photo/objects", json={
        "path": photo, "label": "  Birthday   Cake ", "box": [0.1, 0.2, 0.4, 0.5]})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["label"] == "birthday cake"
    assert body["box"] == [0.1, 0.2, 0.4, 0.5]

    listed = edition_client.get("/api/photo/objects", params={"path": photo}).json()
    assert listed == {"objects": [body]}

    removed = edition_client.delete(f"/api/photo/objects/{body['id']}").json()
    assert removed == {"success": True, "removed": True}
    assert edition_client.get("/api/photo/objects", params={"path": photo}).json() == {"objects": []}
    assert edition_client.delete(f"/api/photo/objects/{body['id']}").json()["removed"] is False


def test_never_touches_faces(edition_client, photo):
    before = _faces(photo)
    edition_client.post("/api/photo/objects", json={"path": photo, "label": "car", "box": [0, 0, 1, 1]})
    assert _faces(photo) == before
    assert edition_client.get("/api/photo/faces", params={"path": photo}).json()["faces"] == []


@pytest.mark.parametrize("box", [[0.5, 0.5, 0.4, 0.6], [-0.1, 0, 0.5, 0.5], [0, 0, 1.2, 1], [0, 0, 0.5]])
def test_rejects_a_bad_box(edition_client, photo, box):
    r = edition_client.post("/api/photo/objects", json={"path": photo, "label": "car", "box": box})
    assert r.status_code == 422


def test_rejects_an_empty_label(edition_client, photo):
    r = edition_client.post("/api/photo/objects", json={"path": photo, "label": "   ", "box": [0, 0, 0.5, 0.5]})
    assert r.status_code == 422


def test_unknown_photo_is_404(edition_client):
    r = edition_client.post("/api/photo/objects", json={
        "path": PREFIX + "missing.jpg", "label": "car", "box": [0, 0, 0.5, 0.5]})
    assert r.status_code == 404


def test_writes_need_edition(regular_client, photo):
    r = regular_client.post("/api/photo/objects", json={"path": photo, "label": "car", "box": [0, 0, 0.5, 0.5]})
    assert r.status_code == 403
    assert regular_client.get("/api/photo/objects", params={"path": photo}).status_code == 200


def test_gallery_search_finds_the_label(edition_client, photo):
    edition_client.post("/api/photo/objects", json={"path": photo, "label": "birthday cake", "box": [0, 0, 0.5, 0.5]})
    paths = [p["path"] for p in edition_client.get("/api/photos", params={"search": "cake"}).json()["photos"]]
    assert photo in paths
    assert PREFIX + "beach.jpg" not in paths


def _count(path):
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        return conn.execute("SELECT COUNT(*) FROM photo_objects WHERE photo_path = ?", (path,)).fetchone()[0]


def test_cap_is_enforced_by_the_insert_itself(edition_client, photo):
    from api.routers.photo_objects import MAX_OBJECTS_PER_PHOTO
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        conn.executemany(
            "INSERT INTO photo_objects (photo_path, label, x1, y1, x2, y2) VALUES (?, ?, 0, 0, 1, 1)",
            [(photo, f"o{i}") for i in range(MAX_OBJECTS_PER_PHOTO - 1)])
    ok = edition_client.post("/api/photo/objects", json={"path": photo, "label": "last", "box": [0, 0, 1, 1]})
    assert ok.status_code == 201, ok.text
    full = edition_client.post("/api/photo/objects", json={"path": photo, "label": "extra", "box": [0, 0, 1, 1]})
    assert full.status_code == 409
    assert _count(photo) == MAX_OBJECTS_PER_PHOTO


def test_cap_is_one_conditional_insert_not_check_then_insert(edition_client, photo, monkeypatch):
    """A row landing between a count and the insert must not get past the cap."""
    from api.routers import photo_objects as mod
    monkeypatch.setattr(mod, "MAX_OBJECTS_PER_PHOTO", 1)
    real = mod.get_db

    class Racer:
        """Lets a rival insert in right after any COUNT(*) read, as a concurrent request would."""
        def __init__(self, conn):
            self._c = conn

        def __getattr__(self, name):
            return getattr(self._c, name)

        def execute(self, sql, params=()):
            cur = self._c.execute(sql, params)
            if sql.lstrip().startswith("SELECT COUNT(*)"):
                with sqlite3.connect(_TEST_DB_FILE.name) as other:
                    other.execute("INSERT INTO photo_objects (photo_path, label, x1, y1, x2, y2) "
                                  "VALUES (?, 'rival', 0, 0, 1, 1)", (photo,))
            return cur

    class Ctx:
        def __enter__(self):
            self._cm = real()
            return Racer(self._cm.__enter__())

        def __exit__(self, *a):
            return self._cm.__exit__(*a)

    monkeypatch.setattr(mod, "get_db", lambda: Ctx())
    r = edition_client.post("/api/photo/objects", json={"path": photo, "label": "mine", "box": [0, 0, 1, 1]})
    assert r.status_code == 201 and _count(photo) == 1
