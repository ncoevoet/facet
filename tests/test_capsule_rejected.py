"""Capsules never show a photo the viewing user rejected."""

import sqlite3

import pytest

import analyzers.capsule_generator as cg
from api.db_helpers import hide_rejected_sql
from db.schema import init_database

REJECTED = "/p/0.jpg"


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr("api.db_helpers.is_photo_tags_available", lambda *a, **k: False)
    monkeypatch.setattr("api.db_helpers.get_visibility_clause", lambda *a, **k: ("1=1", []))
    db_path = str(tmp_path / "cap.db")
    init_database(db_path)
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    # Twenty strong photos from one Monday, enough for several generators.
    c.executemany(
        "INSERT INTO photos (path, filename, aggregate, date_taken) VALUES (?, ?, ?, ?)",
        [(f"/p/{i}.jpg", f"{i}.jpg", 9.0 if i == 0 else 8.0, "2024:03:11 10:00:00") for i in range(20)],
    )
    c.commit()
    yield c
    c.close()


def _capsule_paths(conn, user_id):
    capsules = cg.generate_all_capsules(conn, config={"capsules": {"reverse_geocoding": False}}, user_id=user_id)
    assert capsules, "the fixture must produce capsules, or the exclusion check proves nothing"
    return {p for c in capsules for p in [c["cover_photo_path"], *c["params"]["paths"]]}


def test_single_user_reject_is_left_out(conn, monkeypatch):
    monkeypatch.setattr("api.db_helpers.is_multi_user_enabled", lambda: False)
    assert REJECTED in _capsule_paths(conn, None)
    conn.execute("UPDATE photos SET is_rejected = 1 WHERE path = ?", [REJECTED])
    assert REJECTED not in _capsule_paths(conn, None)


def test_multi_user_reject_is_per_user(conn, monkeypatch):
    monkeypatch.setattr("api.db_helpers.is_multi_user_enabled", lambda: True)
    conn.execute("INSERT INTO user_preferences (user_id, photo_path, is_rejected) VALUES ('alice', ?, 1)", [REJECTED])
    assert REJECTED not in _capsule_paths(conn, "alice")
    assert REJECTED in _capsule_paths(conn, "bob")


@pytest.mark.parametrize("multi_user", [False, True])
def test_fragment_resolves_under_an_alias(conn, monkeypatch, multi_user):
    """The person generators filter `photos ph` joined to other tables."""
    monkeypatch.setattr("api.db_helpers.is_multi_user_enabled", lambda: multi_user)
    if multi_user:
        conn.execute("INSERT INTO user_preferences (user_id, photo_path, is_rejected) VALUES ('alice', ?, 1)", [REJECTED])
    else:
        conn.execute("UPDATE photos SET is_rejected = 1 WHERE path = ?", [REJECTED])
    sql, params = hide_rejected_sql("alice", "ph")
    rows = conn.execute(
        "SELECT ph.path FROM photos ph LEFT JOIN user_preferences up ON up.photo_path = ph.path "
        f"WHERE {sql}", params,
    ).fetchall()
    paths = {r["path"] for r in rows}
    assert REJECTED not in paths
    assert len(paths) == 19


def test_photos_endpoint_drops_a_reject_made_after_caching(client, seed_photos_prefix, monkeypatch):
    """The capsule list is cached for hours; a photo rejected since must not play."""
    import time

    prefix = "/capsule_rejected_test/"
    kept, rejected = prefix + "kept.jpg", prefix + "rejected.jpg"
    seed_photos_prefix(prefix, [
        {"path": kept, "filename": "kept.jpg", "aggregate": 8.0},
        {"path": rejected, "filename": "rejected.jpg", "aggregate": 8.0, "is_rejected": 1},
    ])
    capsule = {
        "id": "c1", "type": "golden", "title": "", "title_key": "", "title_params": {}, "subtitle": "",
        "cover_photo_path": kept, "photo_count": 2, "icon": "star", "params": {"paths": [kept, rejected]},
    }
    monkeypatch.setattr("api.routers.capsules._capsule_cache", {(None, "", ""): {"data": [capsule], "ts": time.time()}})

    resp = client.get("/api/capsules/c1/photos")

    assert resp.status_code == 200
    assert [p["path"] for p in resp.json()["photos"]] == [kept]
