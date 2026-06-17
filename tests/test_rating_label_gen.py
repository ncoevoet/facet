"""
Topic 1 step 7: rating endpoints mint source='rating' comparison pairs inline.

Setting a high star on one photo and a low star on another (same category, gap
>= MIN_STAR_GAP) should leave a derived comparison row, closing the label gap so
the optimizer/ranker can consume ratings without a manual --sync-label-comparisons.
"""

import sqlite3
from contextlib import contextmanager
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from api import create_app
from api.auth import CurrentUser, require_auth, get_optional_user
from db.schema import init_database


def _sync_conn_factory(db_path):
    @contextmanager
    def factory():
        c = sqlite3.connect(db_path)
        c.row_factory = sqlite3.Row
        try:
            yield c
        finally:
            c.close()
    return factory


@pytest.fixture()
def rating_db(tmp_path):
    db_path = str(tmp_path / "rating.db")
    init_database(db_path)
    conn = sqlite3.connect(db_path)
    for name in ('a', 'b'):
        conn.execute(
            "INSERT INTO photos (path, filename, category, aggregate, star_rating) "
            "VALUES (?, ?, 'portrait', 6.0, 0)",
            (f'/r/{name}.jpg', f'{name}.jpg'),
        )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture(autouse=True)
def _inline_rating_sync(monkeypatch):
    # The rating-comparison rebuild is normally debounced; run it inline so the
    # mint-on-rating assertions below see the derived rows immediately.
    monkeypatch.setattr("api.routers.faces._RATING_SYNC_DEBOUNCE_S", 0)


def _client(db_path):
    # Rating endpoints use require_auth, which in single-user mode demands an
    # edition-authenticated user. Override it directly (per CLAUDE.md — no
    # mock.patch on auth dependencies).
    user = CurrentUser(user_id="u1", role="admin", edition_authenticated=True)
    app = create_app()
    app.dependency_overrides[require_auth] = lambda: user
    app.dependency_overrides[get_optional_user] = lambda: user
    return app


def _count_rating_comparisons(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM comparisons WHERE source = 'rating'").fetchone()[0]
    finally:
        conn.close()


def test_rating_endpoints_mint_comparison_pair(rating_db):
    app = _client(rating_db)
    with (
        mock.patch("api.routers.faces.get_db", _sync_conn_factory(rating_db)),
        mock.patch("db.DEFAULT_DB_PATH", rating_db),
        mock.patch("api.routers.faces.is_multi_user_enabled", return_value=False),
    ):
        client = TestClient(app)
        r1 = client.post("/api/photo/set_rating", json={"photo_path": "/r/a.jpg", "rating": 5})
        assert r1.status_code == 200
        r2 = client.post("/api/photo/set_rating", json={"photo_path": "/r/b.jpg", "rating": 1})
        assert r2.status_code == 200

    # A (5*) vs B (1*), gap 4 >= MIN_STAR_GAP -> exactly one derived rating pair.
    assert _count_rating_comparisons(rating_db) >= 1
    conn = sqlite3.connect(rating_db)
    row = conn.execute(
        "SELECT photo_a_path, photo_b_path, winner FROM comparisons WHERE source = 'rating'"
    ).fetchone()
    conn.close()
    a_path, b_path, winner = row
    winner_path = a_path if winner == 'a' else b_path
    assert winner_path == "/r/a.jpg"   # the 5* photo wins


def test_mint_is_idempotent_on_retract(rating_db):
    """Re-rating rebuilds the derived set: retracting a star removes stale pairs."""
    app = _client(rating_db)
    with (
        mock.patch("api.routers.faces.get_db", _sync_conn_factory(rating_db)),
        mock.patch("db.DEFAULT_DB_PATH", rating_db),
        mock.patch("api.routers.faces.is_multi_user_enabled", return_value=False),
    ):
        client = TestClient(app)
        client.post("/api/photo/set_rating", json={"photo_path": "/r/a.jpg", "rating": 5})
        client.post("/api/photo/set_rating", json={"photo_path": "/r/b.jpg", "rating": 1})
        assert _count_rating_comparisons(rating_db) >= 1
        # Retract: set both to 0 stars -> no qualifying pair remains.
        client.post("/api/photo/set_rating", json={"photo_path": "/r/a.jpg", "rating": 0})
        client.post("/api/photo/set_rating", json={"photo_path": "/r/b.jpg", "rating": 0})
    assert _count_rating_comparisons(rating_db) == 0


def test_rapid_ratings_coalesce_into_one_rebuild(rating_db, monkeypatch):
    """N rapid rating changes schedule ONE debounced rebuild, not N (perf)."""
    from api.routers import faces
    import optimization.label_pairs as lp

    monkeypatch.setattr(faces, "_RATING_SYNC_DEBOUNCE_S", 5)   # debounce active (overrides autouse)
    monkeypatch.setattr("db.DEFAULT_DB_PATH", rating_db)
    calls = []
    monkeypatch.setattr(lp, "sync_label_comparisons", lambda *a, **k: calls.append(1))
    try:
        for _ in range(3):
            faces._mint_rating_comparisons(None)
        assert len(faces._rating_sync_timers) == 1   # three clicks -> one pending timer
        assert calls == []                            # nothing ran yet (within debounce window)
        faces.flush_rating_comparisons()
        assert calls == [1]                           # coalesced into exactly one rebuild
        assert not faces._rating_sync_timers
    finally:
        faces.flush_rating_comparisons()              # ensure no stray timer leaks to other tests
