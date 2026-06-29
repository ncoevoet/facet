"""Tests for the Scenes View router (api/routers/scenes.py).

Covers chronological scene grouping by time-gap, the paginated /api/scenes
endpoint, and that confirming a scene rejects non-kept photos and writes
source='culling' comparison rows (feeding the personal ranker).
"""

import sqlite3
from contextlib import contextmanager
from unittest import mock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api import create_app
from api.auth import CurrentUser, get_optional_user, require_edition
from api.routers.scenes import compute_scenes

_SCHEMA = """
    CREATE TABLE photos (
        path TEXT PRIMARY KEY, filename TEXT, aggregate REAL, date_taken TEXT,
        is_burst_lead INTEGER, is_rejected INTEGER, category TEXT
    );
    CREATE TABLE album_photos (
        id INTEGER PRIMARY KEY, album_id INTEGER, photo_path TEXT
    );
    CREATE TABLE albums (id INTEGER PRIMARY KEY, user_id TEXT);
    CREATE TABLE stats_cache (key TEXT PRIMARY KEY, value TEXT, updated_at REAL);
    CREATE TABLE comparisons (
        id INTEGER PRIMARY KEY, photo_a_path TEXT, photo_b_path TEXT, winner TEXT,
        category TEXT, session_id TEXT, user_id TEXT, source TEXT,
        UNIQUE(photo_a_path, photo_b_path)
    );
"""

# Scene 1: three frames minutes apart; Scene 2: next day (gap > 4h default).
_PHOTOS = [
    ("/a1.jpg", "a1.jpg", 7.0, "2024:06:15 10:00:00", 1, 0, None),
    ("/a2.jpg", "a2.jpg", 8.0, "2024:06:15 10:05:00", 1, 0, None),
    ("/a3.jpg", "a3.jpg", 6.0, "2024:06:15 10:10:00", 1, 0, None),
    ("/b1.jpg", "b1.jpg", 9.0, "2024:06:16 14:00:00", 1, 0, None),
    ("/b2.jpg", "b2.jpg", 5.0, "2024:06:16 14:02:00", 1, 0, None),
]


def _cm(conn):
    @contextmanager
    def _ctx():
        yield conn
    return _ctx()


def _db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.executemany("INSERT INTO photos VALUES (?, ?, ?, ?, ?, ?, ?)", _PHOTOS)
    conn.commit()
    return conn


@pytest.fixture()
def client():
    app = create_app()
    fake = CurrentUser(user_id="test", edition_authenticated=True)
    app.dependency_overrides[get_optional_user] = lambda: fake
    app.dependency_overrides[require_edition] = lambda: fake
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_compute_scenes_splits_on_time_gap():
    conn = _db()
    with mock.patch("api.routers.scenes.get_visibility_clause", return_value=("1=1", [])):
        scenes = compute_scenes(conn, user_id=None)
    assert len(scenes) == 2
    assert scenes[0]["count"] == 3 and scenes[0]["best_path"] == "/a2.jpg"  # 8.0 wins
    assert scenes[1]["count"] == 2 and scenes[1]["best_path"] == "/b1.jpg"  # 9.0 wins


def _seconds_apart_db(n, step_seconds=30):
    """n photos captured step_seconds apart on one continuous day (no big gap)."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    rows = []
    base_min, base_sec = 0, 0
    for i in range(n):
        total = i * step_seconds
        hh = 10 + total // 3600
        mm = (total % 3600) // 60
        ss = total % 60
        rows.append((f"/c{i}.jpg", f"c{i}.jpg", 5.0 + (i % 5),
                     f"2024:06:15 {hh:02d}:{mm:02d}:{ss:02d}", 1, 0, None))
    conn.executemany("INSERT INTO photos VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    return conn


def test_adaptive_grouping_bounds_scene_size():
    """A 200-frame continuous run with no inter-scene gap must sub-split into
    several bounded scenes — not collapse into one 200-photo blob, and not
    shatter into singletons that min_size drops."""
    conn = _seconds_apart_db(200, step_seconds=30)
    with mock.patch("api.routers.scenes.get_visibility_clause", return_value=("1=1", [])):
        scenes = compute_scenes(conn, user_id=None)
    assert len(scenes) >= 4
    assert all(s["count"] <= 60 for s in scenes)  # max_scene_size cap
    assert sum(s["count"] for s in scenes) == 200  # no photo dropped


def test_album_scopes_scenes():
    conn = _db()
    conn.executemany(
        "INSERT INTO album_photos (album_id, photo_path) VALUES (1, ?)",
        [("/a1.jpg",), ("/a2.jpg",), ("/a3.jpg",)],
    )
    conn.execute("INSERT INTO albums (id, user_id) VALUES (1, NULL)")
    conn.commit()
    with mock.patch("api.routers.scenes.get_visibility_clause", return_value=("1=1", [])):
        scenes = compute_scenes(conn, user_id=None, album_id=1)
    # Only scene "a" (its 3 frames are in album 1); scene "b" excluded.
    assert len(scenes) == 1
    assert scenes[0]["count"] == 3


def test_album_scoped_scenes_ignore_cap(monkeypatch):
    """Whole-library grouping is capped at max_photos, but an album-scoped
    request grinds the full album (no LIMIT) so a big album never silently
    loses photos past the cap."""
    conn = _seconds_apart_db(20, step_seconds=30)
    conn.executemany(
        "INSERT INTO album_photos (album_id, photo_path) VALUES (1, ?)",
        [(f"/c{i}.jpg",) for i in range(20)],
    )
    conn.execute("INSERT INTO albums (id, user_id) VALUES (1, NULL)")
    conn.commit()
    monkeypatch.setattr("api.routers.scenes._scene_config", lambda: {
        'gap_minutes': 20.0, 'min_size': 2, 'max_photos': 6, 'max_scene_size': 60,
        'adaptive': True, 'adaptive_k': 6.0,
        'split_on_moment_change': False, 'moment_split_min_run': 4,
    })
    with mock.patch("api.routers.scenes.get_visibility_clause", return_value=("1=1", [])):
        whole = compute_scenes(conn, user_id=None)
        album = compute_scenes(conn, user_id=None, album_id=1)
    assert sum(s["count"] for s in whole) == 6      # capped at max_photos
    assert sum(s["count"] for s in album) == 20     # full album, cap ignored


def test_album_scope_denies_non_owner():
    conn = _db()
    conn.execute("INSERT INTO albums (id, user_id) VALUES (2, 'userB')")
    conn.commit()
    with mock.patch("api.routers.scenes.get_visibility_clause", return_value=("1=1", [])):
        with pytest.raises(HTTPException) as ei:
            compute_scenes(conn, user_id="userA", album_id=2)
    assert ei.value.status_code == 403


def test_album_scope_missing_album_404():
    conn = _db()
    with mock.patch("api.routers.scenes.get_visibility_clause", return_value=("1=1", [])):
        with pytest.raises(HTTPException) as ei:
            compute_scenes(conn, user_id=None, album_id=999)
    assert ei.value.status_code == 404


def test_scenes_summary_omits_photos(client):
    conn = _db()
    with (
        mock.patch("api.routers.scenes.get_db", lambda: _cm(conn)),
        mock.patch("api.routers.scenes.get_visibility_clause", return_value=("1=1", [])),
    ):
        full = client.get("/api/scenes", params={"per_page": 10}).json()
        summ = client.get("/api/scenes", params={"per_page": 10, "summary": "true"}).json()
    assert full["scenes"] and all("photos" in s for s in full["scenes"])
    assert summ["scenes"] and all("photos" not in s for s in summ["scenes"])
    assert all({"scene_id", "start", "end", "count"} <= set(s) for s in summ["scenes"])


def test_time_window_scopes_scenes():
    conn = _db()
    with mock.patch("api.routers.scenes.get_visibility_clause", return_value=("1=1", [])):
        scenes = compute_scenes(
            conn, user_id=None,
            date_from="2024:06:16 00:00:00", date_to="2024:06:16 23:59:59",
        )
    # Only the 2024-06-16 frames (scene "b").
    assert len(scenes) == 1
    assert scenes[0]["count"] == 2
    assert scenes[0]["best_path"] == "/b1.jpg"


_MOMENT_SCHEMA = """
    CREATE TABLE photos (
        path TEXT PRIMARY KEY, filename TEXT, aggregate REAL, date_taken TEXT,
        is_burst_lead INTEGER, is_rejected INTEGER, category TEXT,
        narrative_moment TEXT, narrative_moment_confidence REAL
    );
    CREATE TABLE album_photos (id INTEGER PRIMARY KEY, album_id INTEGER, photo_path TEXT);
    CREATE TABLE stats_cache (key TEXT PRIMARY KEY, value TEXT, updated_at REAL);
"""


def _moment_db(photos):
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_MOMENT_SCHEMA)
    conn.executemany(
        "INSERT INTO photos (path, filename, aggregate, date_taken, is_burst_lead, "
        "is_rejected, category, narrative_moment, narrative_moment_confidence) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", photos)
    conn.commit()
    return conn


def test_scene_named_by_dominant_moment(monkeypatch):
    photos = [
        (f"/v{i}.jpg", f"v{i}.jpg", 7.0, f"2024:06:15 10:0{i}:00", 1, 0, None,
         "vows" if i != 2 else "first_kiss", 0.8)
        for i in range(5)
    ]
    conn = _moment_db(photos)
    # Pin the shipped defaults (split_on_moment_change off) like the sibling tests,
    # so a future config flip can't split the run and break this assertion.
    monkeypatch.setattr("api.routers.scenes._scene_config", lambda: {
        'gap_minutes': 20.0, 'min_size': 2, 'max_photos': 5000, 'max_scene_size': 60,
        'adaptive': True, 'adaptive_k': 6.0,
        'split_on_moment_change': False, 'moment_split_min_run': 4,
    })
    with mock.patch("api.routers.scenes.get_visibility_clause", return_value=("1=1", [])):
        scenes = compute_scenes(conn, user_id=None)
    assert len(scenes) == 1
    assert scenes[0]["moment"] == "vows"          # weighted mode over the 5 frames
    assert scenes[0]["moment_confidence"] is not None


def test_split_on_moment_change(monkeypatch):
    # One continuous time-run: first 5 frames 'vows', next 5 'first_dance'.
    photos = [
        (f"/m{i}.jpg", f"m{i}.jpg", 7.0, f"2024:06:15 10:{i:02d}:00", 1, 0, None,
         "vows" if i < 5 else "first_dance", 0.8)
        for i in range(10)
    ]
    conn = _moment_db(photos)
    monkeypatch.setattr("api.routers.scenes._scene_config", lambda: {
        'gap_minutes': 20.0, 'min_size': 2, 'max_photos': 5000, 'max_scene_size': 60,
        'adaptive': True, 'adaptive_k': 6.0,
        'split_on_moment_change': True, 'moment_split_min_run': 4,
    })
    with mock.patch("api.routers.scenes.get_visibility_clause", return_value=("1=1", [])):
        scenes = compute_scenes(conn, user_id=None)
    assert len(scenes) == 2                        # split on the moment change
    assert {s["moment"] for s in scenes} == {"vows", "first_dance"}


def test_get_scenes_paginates(client):
    conn = _db()
    with (
        mock.patch("api.routers.scenes.get_db", lambda: _cm(conn)),
        mock.patch("api.routers.scenes.get_visibility_clause", return_value=("1=1", [])),
    ):
        resp = client.get("/api/scenes", params={"page": 1, "per_page": 1})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert body["total_pages"] == 2
    assert len(body["scenes"]) == 1


def test_confirm_scene_rejects_and_records_pairs(client):
    conn = _db()
    with (
        mock.patch("api.routers.scenes.get_db", lambda: _cm(conn)),
        mock.patch("api.routers.scenes.get_visibility_clause", return_value=("1=1", [])),
        mock.patch("api.routers.scenes.trigger_auto_retrain", lambda *a, **k: None),
    ):
        resp = client.post("/api/scenes/confirm", json={
            "paths": ["/a1.jpg", "/a2.jpg", "/a3.jpg"],
            "keep_paths": ["/a2.jpg"],
        })
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "kept": 1, "rejected": 2}
    # non-kept rejected
    rejected = conn.execute(
        "SELECT path FROM photos WHERE is_rejected = 1 ORDER BY path"
    ).fetchall()
    assert [r["path"] for r in rejected] == ["/a1.jpg", "/a3.jpg"]
    # culling comparison rows written with source='culling'
    pairs = conn.execute("SELECT source FROM comparisons").fetchall()
    assert len(pairs) >= 1
    assert all(p["source"] == "culling" for p in pairs)
