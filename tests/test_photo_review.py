"""Persistent review decisions, independent of ratings and bounded by visibility."""
import sqlite3

import pytest

from db import DEFAULT_DB_PATH


@pytest.mark.parametrize("target", ["paths", "filters"])
def test_keep_reset_and_reject(edition_client, seed_photos_prefix, target):
    prefix = "/review-transitions/"
    paths = [prefix + name + ".jpg" for name in ("a", "b")]
    seed_photos_prefix(prefix, [{"path": p, "filename": p.rsplit("/", 1)[-1],
                                "camera_model": "ReviewCam", "is_favorite": 1,
                                "star_rating": 4, "is_rejected": 1} for p in paths])
    scope = {"photo_paths": paths} if target == "paths" else {"filters": {"camera": "ReviewCam"}}
    response = edition_client.post("/api/photos/batch_review", json={**scope, "exclude": [paths[1]], "decision": "kept"})
    assert response.status_code == 200, response.text
    assert response.json() == {"success": True, "count": 1}
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        assert conn.execute("SELECT is_kept, is_rejected, is_favorite, star_rating FROM photos WHERE path=?", [paths[0]]).fetchone() == (1, 0, 1, 4)
        assert conn.execute("SELECT is_rejected FROM photos WHERE path=?", [paths[1]]).fetchone() == (1,)
    response = edition_client.post("/api/photos/batch_review", json={"photo_paths": paths[:1], "decision": "undecided"})
    assert response.json() == {"success": True, "count": 1}
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        assert conn.execute("SELECT is_kept, is_rejected, is_favorite, star_rating FROM photos WHERE path=?", [paths[0]]).fetchone() == (0, 0, 1, 4)
    edition_client.post("/api/photos/batch_review", json={"photo_paths": paths[:1], "decision": "kept"})
    edition_client.post("/api/photos/batch_reject", json={"photo_paths": paths[:1]})
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        assert conn.execute("SELECT is_kept, is_rejected FROM photos WHERE path=?", [paths[0]]).fetchone() == (0, 1)


def test_needs_review_capture_order(edition_client, seed_photos_prefix):
    prefix = "/review-order/"
    seed_photos_prefix(prefix, [
        {"path": prefix + name + ".jpg", "filename": name + ".jpg", "date_taken": date,
         "is_kept": kept, "is_rejected": rejected}
        for name, date, kept, rejected in [("a", "2026:01:03 00:00:00", 0, 0), ("b", "2026:01:01 00:00:00", 0, 0),
                                            ("c", "2026:01:02 00:00:00", 1, 0), ("d", "2026:01:04 00:00:00", 1, 1)]])
    for status, expected in [("undecided", ["b", "a"]), ("kept", ["c"]), ("rejected", ["d"])]:
        response = edition_client.get("/api/photos", params={"path_prefix": prefix, "review_status": status,
            "sort": "date_taken", "sort_direction": "ASC", "hide_rejected": "1"})
        assert response.status_code == 200, response.text
        assert [p["filename"] for p in response.json()["photos"]] == [n + ".jpg" for n in expected]
        assert all("is_kept" in p for p in response.json()["photos"])


@pytest.mark.parametrize("kind", ["burst", "similar", "scene", "bracket", "panorama"])
@pytest.mark.parametrize("per_user", [False, True])
def test_culling_confirm_persists_keeps(edition_client, seed_photos_prefix, monkeypatch, kind, per_user):
    monkeypatch.setattr("api.db_helpers.trigger_auto_retrain", lambda *args, **kwargs: None)
    prefix = "/review-confirm/"
    paths = [prefix + name + ".jpg" for name in ("keep", "reject")]
    seed_photos_prefix(prefix, [{"path": p, "filename": p.rsplit("/", 1)[-1],
        "burst_group_id": 98765, "sequence_kind": kind if kind in ("bracket", "panorama") else None,
        "sequence_group_id": 1, "is_rejected": 0, "is_kept": index, "star_rating": 4, "is_favorite": 1}
        for index, p in enumerate(paths)])
    from api import config
    if per_user:
        monkeypatch.setitem(config._FULL_CONFIG, "users", {"test": {"directories": [prefix]}})
        with sqlite3.connect(DEFAULT_DB_PATH) as conn:
            conn.executemany("INSERT INTO user_preferences(user_id, photo_path, star_rating, is_favorite, is_kept) VALUES('test', ?, 4, 1, ?)", [(p, index) for index, p in enumerate(paths)])
    response = edition_client.post("/api/culling-groups/confirm", json={
        "type": kind, "group_id": 98765, "paths": paths, "keep_paths": paths[:1]})
    assert response.status_code == 200, response.text
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        table, key = ("user_preferences", "photo_path") if per_user else ("photos", "path")
        assert conn.execute(f"SELECT is_kept, is_rejected, star_rating, is_favorite FROM {table} WHERE {key}=?", paths[:1]).fetchone() == (1, 0, 4, 1)
        assert conn.execute(f"SELECT is_kept, is_rejected FROM {table} WHERE {key}=?", paths[1:]).fetchone() == (0, 1)
        conn.execute("DELETE FROM user_preferences WHERE photo_path LIKE ?", [prefix + "%"])
        conn.execute("DELETE FROM comparisons WHERE photo_a_path LIKE ? OR photo_b_path LIKE ?", [prefix + "%"] * 2)


def test_schema_upgrade_and_preference_migration(tmp_path):
    from db.schema import init_database
    from database import migrate_user_preferences
    path = str(tmp_path / "upgrade.db")
    init_database(path)
    with sqlite3.connect(path) as conn:
        # Reproduce a real pre-feature database using the production schema.
        conn.execute("ALTER TABLE photos DROP COLUMN is_kept")
        conn.execute("ALTER TABLE user_preferences DROP COLUMN is_kept")
        conn.execute("INSERT INTO photos(path, filename, star_rating, is_favorite) VALUES('/legacy.jpg', 'legacy.jpg', 5, 1)")
    init_database(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT is_kept FROM photos").fetchone() == (0,)
        conn.execute("INSERT INTO photos(path, filename, is_kept) VALUES('/kept.jpg', 'kept.jpg', 1)")
    migrate_user_preferences("alice", path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT is_kept FROM user_preferences WHERE photo_path='/kept.jpg'").fetchone() == (1,)
        assert conn.execute("SELECT is_kept FROM user_preferences WHERE photo_path='/legacy.jpg'").fetchone() == (0,)


@pytest.mark.parametrize("per_user", [False, True])
def test_external_reject_clears_keep(tmp_path, per_user):
    from db.schema import init_database
    from processing.rating_writer import upsert_rating_state
    path = str(tmp_path / "ratings.db")
    init_database(path)
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("INSERT INTO photos(path, filename, is_kept) VALUES('/a.jpg', 'a.jpg', 1)")
        conn.execute("INSERT INTO user_preferences(user_id, photo_path, is_kept) VALUES('alice', '/a.jpg', 1)")
        upsert_rating_state(conn, "/a.jpg", "alice", star_rating=5, per_user=per_user)
        table = "user_preferences" if per_user else "photos"
        assert conn.execute(f"SELECT is_kept FROM {table}").fetchone()[0] == 1
        upsert_rating_state(conn, "/a.jpg", "alice", is_rejected=True, per_user=per_user)
        assert conn.execute(f"SELECT is_kept, is_rejected, star_rating FROM {table}").fetchone()[:] == (0, 1, 5)


@pytest.mark.parametrize("decision", ["kept", "undecided", "rejected"])
@pytest.mark.parametrize("target", ["paths", "filters"])
def test_review_is_per_user(edition_client, seed_photos_prefix, monkeypatch, decision, target):
    from api import config
    prefix = "/review-user/"
    visible, hidden = prefix + "visible/a.jpg", prefix + "hidden/b.jpg"
    monkeypatch.setitem(config._FULL_CONFIG, "users", {"test": {"directories": [prefix + "visible"]}})
    seed_photos_prefix(prefix, [{"path": p, "filename": "a.jpg", "camera_model": "ReviewUserCam", "is_kept": 1}
                               for p in [visible, hidden]])
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.execute("INSERT INTO user_preferences(user_id, photo_path, star_rating, is_favorite, is_rejected) VALUES('test', ?, 5, 1, 1)", [visible])
        conn.execute("INSERT INTO user_preferences(user_id, photo_path, is_kept) VALUES('bob', ?, 1)", [visible])
    try:
        scope = {"photo_paths": [visible, hidden, prefix + "missing.jpg"]} if target == "paths" else {"filters": {"camera": "ReviewUserCam"}}
        response = edition_client.post("/api/photos/batch_review", json={**scope, "decision": decision})
        assert response.json() == {"success": True, "count": 1}
        with sqlite3.connect(DEFAULT_DB_PATH) as conn:
            assert conn.execute("SELECT is_kept, is_rejected, star_rating, is_favorite FROM user_preferences WHERE user_id='test' AND photo_path=?", [visible]).fetchone() == (int(decision == "kept"), int(decision == "rejected"), 0 if decision == "rejected" else 5, 0 if decision == "rejected" else 1)
            assert conn.execute("SELECT is_kept FROM user_preferences WHERE user_id='bob' AND photo_path=?", [visible]).fetchone() == (1,)
            assert conn.execute("SELECT COUNT(*) FROM user_preferences WHERE photo_path=?", [hidden]).fetchone() == (0,)
            assert conn.execute("SELECT is_kept FROM photos WHERE path=?", [visible]).fetchone() == (1,)
        response = edition_client.get("/api/photos", params={"path_prefix": prefix, "review_status": decision})
        assert [p["path"] for p in response.json()["photos"]] == [visible]
        assert response.json()["photos"][0]["is_kept"] == int(decision == "kept")
    finally:
        with sqlite3.connect(DEFAULT_DB_PATH) as conn:
            conn.execute("DELETE FROM user_preferences WHERE photo_path LIKE ?", [prefix + "%"])


@pytest.mark.parametrize("per_user", [False, True])
@pytest.mark.parametrize("kind", ["burst", "bracket"])
def test_auto_cull_persists_keepers(tmp_path, monkeypatch, per_user, kind):
    from api import config
    from api.db_helpers import get_visibility_clause
    from api.routers.burst_culling import _apply_auto_cull_group
    from db.schema import init_database
    path = str(tmp_path / "auto.db")
    init_database(path)
    if per_user:
        monkeypatch.setitem(config._FULL_CONFIG, "users", {"alice": {"directories": ["/auto"]}})
    else:
        monkeypatch.delitem(config._FULL_CONFIG, "users", raising=False)
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        conn.executemany("INSERT INTO photos(path, filename, star_rating, is_favorite) VALUES(?, 'a.jpg', 4, 1)",
                         [("/auto/keep.jpg",), ("/auto/reject.jpg",)])
        if per_user:
            conn.executemany("INSERT INTO user_preferences(user_id, photo_path, star_rating, is_favorite) VALUES('alice', ?, 4, 1)",
                             [("/auto/keep.jpg",), ("/auto/reject.jpg",)])
        group = {"type": kind, "sequence_kind": kind if kind == "bracket" else None,
                 "photos": [{"path": "/auto/keep.jpg"}, {"path": "/auto/reject.jpg"}]}
        vis_sql, vis_params = get_visibility_clause("alice")
        _apply_auto_cull_group(conn, group, ["/auto/keep.jpg"], ["/auto/reject.jpg"], "alice", vis_sql, vis_params)
        table, key = ("user_preferences", "photo_path") if per_user else ("photos", "path")
        assert conn.execute(f"SELECT is_kept, is_rejected, star_rating, is_favorite FROM {table} WHERE {key}='/auto/keep.jpg'").fetchone()[:] == (1, 0, 4, 1)
        assert conn.execute(f"SELECT is_kept, is_rejected FROM {table} WHERE {key}='/auto/reject.jpg'").fetchone()[:] == (0, 1)


@pytest.mark.parametrize("target", ["paths", "filters"])
def test_review_rejection_clears_rating_and_favorite(edition_client, seed_photos_prefix, target):
    prefix = "/review-restore-rejected/"
    path = prefix + "a.jpg"
    seed_photos_prefix(prefix, [{"path": path, "filename": "a.jpg", "camera_model": "ReviewRestoreCam",
                               "is_kept": 1, "is_favorite": 1, "star_rating": 4}])
    scope = {"photo_paths": [path]} if target == "paths" else {"filters": {"camera": "ReviewRestoreCam"}}
    response = edition_client.post("/api/photos/batch_review", json={**scope, "decision": "rejected"})
    assert response.json() == {"success": True, "count": 1}
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        assert conn.execute("SELECT is_kept, is_rejected, is_favorite, star_rating FROM photos WHERE path=?", [path]).fetchone() == (0, 1, 0, 0)


def test_single_reject_clears_keep(edition_session_client, seed_photos_prefix, monkeypatch):
    monkeypatch.setattr("api.routers.faces._mint_rating_comparisons", lambda user_id: None)
    path = "/review-toggle/a.jpg"
    seed_photos_prefix("/review-toggle/", [{"path": path, "filename": "a.jpg", "is_kept": 1}])
    response = edition_session_client.post("/api/photo/toggle_rejected", json={"photo_path": path})
    assert response.status_code == 200, response.text
    assert response.json()["is_kept"] is False
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        assert conn.execute("SELECT is_kept, is_rejected FROM photos WHERE path=?", [path]).fetchone() == (0, 1)


@pytest.mark.parametrize("per_user", [False, True])
@pytest.mark.parametrize("record", [False, True])
def test_culling_keep_tracks_label_origin(tmp_path, monkeypatch, per_user, record):
    """An agent un-rejecting a keeper must not turn its labels into human taste."""
    from api import config
    from api.db_helpers import record_culling_decision
    from db.schema import init_database
    database = str(tmp_path / "keeper-origin.db")
    init_database(database)
    if per_user:
        monkeypatch.setitem(config._FULL_CONFIG, "users", {"alice": {"directories": ["/review"]}})
    else:
        monkeypatch.delitem(config._FULL_CONFIG, "users", raising=False)
    with sqlite3.connect(database) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("INSERT INTO photos(path, filename, is_rejected, star_rating) VALUES('/review/a.jpg', 'a.jpg', 1, 4)")
        if per_user:
            conn.execute("INSERT INTO user_preferences(user_id, photo_path, is_rejected, star_rating) VALUES('alice', '/review/a.jpg', 1, 4)")
        scope = 'alice' if per_user else ''
        conn.execute("INSERT INTO rating_provenance(user_id, photo_path, star_rating, is_rejected) VALUES(?, '/review/a.jpg', 4, 1)", [scope])
        record_culling_decision(conn, ['/review/a.jpg'], [], set(), user_id='alice', record=record)
        origin = conn.execute("SELECT star_rating, is_favorite, is_rejected FROM rating_provenance WHERE user_id=?", [scope]).fetchone()
        if record:
            assert origin is None
        else:
            assert tuple(origin) == (4, 0, 0)
        table = 'user_preferences' if per_user else 'photos'
        assert tuple(conn.execute(f"SELECT is_kept, is_rejected FROM {table}").fetchone()) == (1, 0)


@pytest.mark.parametrize("per_user", [False, True])
def test_auto_cull_guard_preserves_new_keep(tmp_path, monkeypatch, per_user):
    """A Keep made after preview is as authoritative as a changed star rating."""
    from types import SimpleNamespace
    from api import config
    from api.db_helpers import set_photos_kept
    from api.routers import burst_culling
    from db.schema import init_database
    database = str(tmp_path / "keeper-guard.db")
    init_database(database)
    if per_user:
        monkeypatch.setitem(config._FULL_CONFIG, "users", {"alice": {"directories": ["/review"]}})
    else:
        monkeypatch.delitem(config._FULL_CONFIG, "users", raising=False)
    monkeypatch.setattr(burst_culling, '_guard_snapshots', {})
    path = '/review/a.jpg'
    plan = [{'group': {'type': 'burst', 'group_id': 1}, 'keep_paths': [], 'reject_paths': [path]}]
    result = SimpleNamespace(plan_digest='test-digest', state_guard=None)
    with sqlite3.connect(database) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("INSERT INTO photos(path, filename) VALUES(?, 'a.jpg')", [path])
        burst_culling._remember_plan(conn, 'alice', 'test-digest', plan, (), result)
        set_photos_kept(conn, [path], 'alice')
        changed, skipped = burst_culling._reconcile_plan(conn, 'alice', plan, result, 'test-digest', (), True)
        assert changed == skipped == {path}


@pytest.mark.parametrize("target", ["paths", "filters"])
def test_agent_review_records_label_origin(edition_client, seed_photos_prefix, monkeypatch, target):
    from api.auth import CurrentUser, require_edition
    path = '/review-agent/a.jpg'
    seed_photos_prefix('/review-agent/', [{'path': path, 'filename': 'a.jpg', 'camera_model': 'AgentReviewCam', 'is_rejected': 1, 'star_rating': 4}])
    monkeypatch.setitem(edition_client.app.dependency_overrides, require_edition,
                        lambda: CurrentUser(user_id='test', role='admin', edition_authenticated=True, agent=True))
    scope = {'photo_paths': [path]} if target == 'paths' else {'filters': {'camera': 'AgentReviewCam'}}
    response = edition_client.post('/api/photos/batch_review', json={**scope, 'decision': 'kept'})
    assert response.status_code == 200, response.text
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        assert conn.execute("SELECT star_rating, is_favorite, is_rejected FROM rating_provenance WHERE photo_path=?", [path]).fetchone() == (4, 0, 0)


@pytest.mark.parametrize('target', ['paths', 'filters'])
@pytest.mark.parametrize('decision', ['kept', 'undecided'])
@pytest.mark.parametrize('per_user', [False, True])
def test_review_keeps_unchanged_agent_rating_origin(edition_client, seed_photos_prefix, monkeypatch, target, decision, per_user):
    path = f'/review-origin/{per_user}-{decision}-{target}/a.jpg'
    seed_photos_prefix('/review-origin/', [{'path': path, 'filename': 'a.jpg', 'camera_model': 'OriginReviewCam', 'star_rating': 4}])
    scope_user = ''
    if per_user:
        from api import config
        monkeypatch.setitem(config._FULL_CONFIG, 'users', {'test': {'directories': ['/review-origin/']}})
        scope_user = 'test'
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        if per_user:
            conn.execute("INSERT INTO user_preferences(user_id, photo_path, star_rating) VALUES('test', ?, 4)", [path])
        conn.execute("INSERT INTO rating_provenance(user_id, photo_path, star_rating) VALUES(?, ?, 4)", [scope_user, path])
    scope = {'photo_paths': [path]} if target == 'paths' else {'filters': {'camera': 'OriginReviewCam'}}
    response = edition_client.post('/api/photos/batch_review', json={**scope, 'decision': decision})
    assert response.status_code == 200, response.text
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        assert conn.execute("SELECT star_rating FROM rating_provenance WHERE photo_path=?", [path]).fetchone() == (4,)
