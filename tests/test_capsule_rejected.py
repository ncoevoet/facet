"""Capsules never show a photo the viewing user rejected."""

import sqlite3
import time

import pytest

import analyzers.capsule_generator as cg
from api.db_helpers import hide_rejected_sql
from db.schema import init_database

REJECTED = "/p/0.jpg"
# Each generator family the fixture must drive; a family that returns nothing
# would make its exclusion check pass vacuously.
EXPECTED_TYPES = {"faces_of", "person_pair", "rare_pair", "seeded"}


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr("api.db_helpers.is_photo_tags_available", lambda *a, **k: False)
    monkeypatch.setattr("api.db_helpers.get_visibility_clause", lambda *a, **k: ("1=1", []))
    db_path = str(tmp_path / "cap.db")
    init_database(db_path)
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    # Twenty strong photos from one Monday. Ann and Ben are in all of them; Cy
    # joins Ann in four, including the rejected one, which is a rare pair.
    c.executemany(
        "INSERT INTO photos (path, filename, aggregate, date_taken) VALUES (?, ?, ?, ?)",
        [(f"/p/{i}.jpg", f"{i}.jpg", 9.0 if i == 0 else 8.0, "2024:03:11 10:00:00") for i in range(20)],
    )
    c.executemany("INSERT INTO persons (id, name, face_count) VALUES (?, ?, ?)",
                  [(1, "Ann", 20), (2, "Ben", 20), (3, "Cy", 4)])
    faces = [(f"/p/{i}.jpg", index, person)
             for i in range(20) for index, person in enumerate((1, 2))]
    faces += [(f"/p/{i}.jpg", 2, 3) for i in range(4)]
    c.executemany("INSERT INTO faces (photo_path, face_index, person_id, embedding) VALUES (?, ?, ?, x'00')", faces)
    c.commit()
    yield c
    c.close()


def _capsules_by_type(conn, user_id):
    capsules = cg.generate_all_capsules(conn, config={"capsules": {
        "reverse_geocoding": False,
        # Every capsule here draws on the same 20 photos; keep them all.
        "max_photo_overlap": 1.0,
        "seeded": {"num_seeds": 20, "min_photos": 3},
        "faces_of": {"min_photos": 3},
        "person_pairs": {"min_photos": 3},
    }}, user_id=user_id)
    by_type = {}
    for c in capsules:
        by_type.setdefault(c["type"], set()).update([c["cover_photo_path"], *c["params"]["paths"]])
    assert EXPECTED_TYPES <= set(by_type), f"generators missing from fixture: {EXPECTED_TYPES - set(by_type)}"
    return by_type


def _reject(conn, multi_user, user_id="alice", path=REJECTED):
    if multi_user:
        conn.execute("INSERT INTO user_preferences (user_id, photo_path, is_rejected) VALUES (?, ?, 1)", [user_id, path])
    else:
        conn.execute("UPDATE photos SET is_rejected = 1 WHERE path = ?", [path])


@pytest.mark.parametrize("multi_user", [False, True])
def test_no_generator_uses_a_rejected_photo(conn, monkeypatch, multi_user):
    monkeypatch.setattr("api.db_helpers.is_multi_user_enabled", lambda: multi_user)
    before = _capsules_by_type(conn, "alice")
    assert all(REJECTED in before[t] for t in EXPECTED_TYPES - {"seeded"})
    _reject(conn, multi_user)
    for kind, paths in _capsules_by_type(conn, "alice").items():
        assert REJECTED not in paths, kind


def test_multi_user_reject_is_per_user(conn, monkeypatch):
    monkeypatch.setattr("api.db_helpers.is_multi_user_enabled", lambda: True)
    _reject(conn, True, "alice")
    assert all(REJECTED in paths for kind, paths in _capsules_by_type(conn, "bob").items()
               if kind in EXPECTED_TYPES - {"seeded"})


@pytest.mark.parametrize("multi_user", [False, True])
def test_fragment_resolves_beside_a_user_preferences_join(conn, monkeypatch, multi_user):
    monkeypatch.setattr("api.db_helpers.is_multi_user_enabled", lambda: multi_user)
    _reject(conn, multi_user)
    sql, params = hide_rejected_sql("alice", "ph")
    rows = conn.execute(
        "SELECT ph.path FROM photos ph LEFT JOIN user_preferences up ON up.photo_path = ph.path "
        f"WHERE {sql}", params,
    ).fetchall()
    paths = {r["path"] for r in rows}
    assert REJECTED not in paths
    assert len(paths) == 19


PREFIX = "/capsule_rejected_test/"
KEPT, GONE = PREFIX + "kept.jpg", PREFIX + "rejected.jpg"


@pytest.fixture()
def cached_capsule(seed_photos_prefix, monkeypatch):
    """A cached capsule whose cover is a photo rejected after caching."""
    seed_photos_prefix(PREFIX, [
        {"path": KEPT, "filename": "kept.jpg", "aggregate": 8.0},
        {"path": GONE, "filename": "rejected.jpg", "aggregate": 8.0},
    ])
    capsule = {
        "id": "c1", "type": "golden", "title": "Best", "title_key": "", "title_params": {}, "subtitle": "",
        "cover_photo_path": GONE, "photo_count": 2, "icon": "star", "params": {"paths": [GONE, KEPT]},
    }
    cache = {}
    monkeypatch.setattr("api.routers.capsules._capsule_cache", cache)
    # The capsule router reaches the multi-user check through the reject fragment.
    monkeypatch.setattr("api.routers.capsules.get_visibility_clause", lambda *a, **k: ("1=1", []))

    def put(user_id, multi_user):
        monkeypatch.setattr("api.db_helpers.is_multi_user_enabled", lambda: multi_user)
        cache[(user_id, "", "")] = {"data": [capsule], "ts": time.time()}
    return put


def _db():
    from tests.conftest import _TEST_DB_FILE
    return sqlite3.connect(_TEST_DB_FILE.name)


def _reject_in_shared_db(multi_user, user_id):
    with _db() as c:
        if multi_user:
            c.execute("INSERT INTO user_preferences (user_id, photo_path, is_rejected) VALUES (?, ?, 1)", [user_id, GONE])
        else:
            c.execute("UPDATE photos SET is_rejected = 1 WHERE path = ?", [GONE])


@pytest.mark.parametrize("multi_user", [False, True])
def test_slideshow_drops_a_reject_made_after_caching(edition_client, cached_capsule, multi_user):
    cached_capsule("test", multi_user)
    _reject_in_shared_db(multi_user, "test")

    body = edition_client.get("/api/capsules/c1/photos").json()

    assert [p["path"] for p in body["photos"]] == [KEPT]
    assert body["capsule"]["photo_count"] == 1
    assert body["capsule"]["cover_photo_path"] == KEPT


def test_another_users_reject_leaves_the_slideshow_alone(edition_client, cached_capsule):
    cached_capsule("test", True)
    _reject_in_shared_db(True, "someone-else")

    body = edition_client.get("/api/capsules/c1/photos").json()

    assert [p["path"] for p in body["photos"]] == [GONE, KEPT]


@pytest.mark.parametrize("multi_user", [False, True])
def test_save_as_album_leaves_out_a_reject_made_after_caching(edition_client, cached_capsule, multi_user):
    cached_capsule("test", multi_user)
    _reject_in_shared_db(multi_user, "test")

    resp = edition_client.post("/api/capsules/c1/save-album")

    assert resp.status_code == 200
    album_id = resp.json()["album_id"]
    with _db() as c:
        try:
            members = [r[0] for r in c.execute(
                "SELECT photo_path FROM album_photos WHERE album_id = ? ORDER BY position", [album_id])]
            cover = c.execute("SELECT cover_photo_path FROM albums WHERE id = ?", [album_id]).fetchone()[0]
        finally:
            c.execute("DELETE FROM album_photos WHERE album_id = ?", [album_id])
            c.execute("DELETE FROM albums WHERE id = ?", [album_id])
    assert members == [KEPT]
    assert cover == KEPT


@pytest.mark.parametrize("multi_user", [False, True])
def test_list_swaps_a_cover_rejected_after_caching(edition_client, cached_capsule, multi_user):
    cached_capsule("test", multi_user)
    _reject_in_shared_db(multi_user, "test")

    [card] = edition_client.get("/api/capsules").json()["capsules"]

    assert card["cover_photo_path"] == KEPT


def test_a_capsule_rejected_entirely_has_no_cover(edition_client, cached_capsule):
    cached_capsule("test", False)
    with _db() as c:
        c.execute("UPDATE photos SET is_rejected = 1 WHERE path IN (?, ?)", [GONE, KEPT])

    body = edition_client.get("/api/capsules/c1/photos").json()
    [card] = edition_client.get("/api/capsules").json()["capsules"]

    assert body["photos"] == [] and body["capsule"]["photo_count"] == 0
    assert body["capsule"].get("cover_photo_path") is None
    assert card.get("cover_photo_path") is None
