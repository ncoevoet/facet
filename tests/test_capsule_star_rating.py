"""The per-star-rating capsule generator honors per-user ratings (Phase F4).

``_generate_star_rating_capsules`` replaces the generic dimension loop's global
``photos.star_rating`` read so that, in multi-user mode, each user's own ratings
from ``user_preferences`` drive their star capsules.
"""

import sqlite3

from analyzers.capsule_generator import _generate_star_rating_capsules


def _db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE photos (path TEXT PRIMARY KEY, star_rating INTEGER, aggregate REAL)")
    conn.execute(
        "CREATE TABLE user_preferences (user_id TEXT, photo_path TEXT, star_rating INTEGER "
        "DEFAULT 0, is_favorite INTEGER DEFAULT 0, is_rejected INTEGER DEFAULT 0, "
        "PRIMARY KEY (user_id, photo_path))"
    )
    return conn


_CFG = {"star_rating": {"min_photos": 2}, "max_photos_per_capsule": 40}


def test_honors_user_preferences(monkeypatch):
    monkeypatch.setattr("api.config.is_multi_user_enabled", lambda: True)
    conn = _db()
    # Global ratings are all 0; only user 'alice' has rated p0/p1 five stars.
    for i in range(3):
        conn.execute("INSERT INTO photos VALUES (?, ?, ?)", (f"/p{i}.jpg", 0, 8.0))
    conn.execute("INSERT INTO user_preferences VALUES (?, ?, ?, ?, ?)", ("alice", "/p0.jpg", 5, 0, 0))
    conn.execute("INSERT INTO user_preferences VALUES (?, ?, ?, ?, ?)", ("alice", "/p1.jpg", 5, 0, 0))

    caps = _generate_star_rating_capsules(conn, _CFG, 6.0, ("1=1", []), "alice")

    assert len(caps) == 1
    assert caps[0]["type"] == "star_rating"
    assert caps[0]["photo_count"] == 2
    assert set(caps[0]["params"]["paths"]) == {"/p0.jpg", "/p1.jpg"}


def test_global_ratings_in_single_user_mode(monkeypatch):
    monkeypatch.setattr("api.config.is_multi_user_enabled", lambda: False)
    conn = _db()
    for i in range(2):
        conn.execute("INSERT INTO photos VALUES (?, ?, ?)", (f"/g{i}.jpg", 4, 8.0))

    caps = _generate_star_rating_capsules(conn, _CFG, 6.0, ("1=1", []), "alice")

    assert len(caps) == 1
    assert caps[0]["photo_count"] == 2
