"""Tests for the Scenes View router (api/routers/scenes.py).

Covers chronological scene grouping by time-gap, the paginated /api/scenes
endpoint, and that confirming a scene rejects non-kept photos and writes
source='culling' comparison rows (feeding the personal ranker).
"""

import sqlite3
from contextlib import contextmanager
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from api import create_app
from api.auth import CurrentUser, get_optional_user, require_edition
from api.routers.scenes import compute_scenes

_SCHEMA = """
    CREATE TABLE photos (
        path TEXT PRIMARY KEY, filename TEXT, aggregate REAL, date_taken TEXT,
        is_burst_lead INTEGER, is_rejected INTEGER, category TEXT
    );
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
