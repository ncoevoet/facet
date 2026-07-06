"""Tests for GET /api/ranker/status (the "My Taste" confidence surface).

Pins how the endpoint pairs the stats_cache metrics snapshot written by
train_ranker with live learned_scores coverage.
"""

import json
import sqlite3
from contextlib import contextmanager
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from api import create_app
from api.auth import CurrentUser, get_optional_user
from optimization.personal_ranker import ranker_metrics_key

_SCHEMA = """
    CREATE TABLE photos (path TEXT PRIMARY KEY, clip_embedding BLOB);
    CREATE TABLE learned_scores (
        photo_path TEXT, learned_score REAL, comparison_count INTEGER,
        category TEXT, updated_at TEXT, user_id TEXT
    );
    CREATE TABLE stats_cache (key TEXT PRIMARY KEY, value TEXT, updated_at REAL);
"""


def _cm(conn):
    @contextmanager
    def _ctx():
        yield conn
    return _ctx()


def _db(embedded=0, scored=0, metrics=None, user_id=None):
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    for i in range(embedded):
        conn.execute("INSERT INTO photos VALUES (?, ?)", (f"/e{i}.jpg", b"emb"))
    for i in range(scored):
        conn.execute(
            "INSERT INTO learned_scores VALUES (?, ?, ?, ?, ?, ?)",
            (f"/e{i}.jpg", 7.0, 40, None, "now", user_id),
        )
    if metrics is not None:
        conn.execute(
            "INSERT INTO stats_cache VALUES (?, ?, ?)",
            (ranker_metrics_key(user_id, None), json.dumps(metrics), 0.0),
        )
    conn.commit()
    return conn


@pytest.fixture()
def client():
    app = create_app()
    app.dependency_overrides[get_optional_user] = lambda: CurrentUser(
        user_id="test", edition_authenticated=True
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


def _client_for(user):
    """Build a (TestClient, app) whose get_optional_user yields ``user``."""
    app = create_app()
    app.dependency_overrides[get_optional_user] = lambda: user
    return TestClient(app), app


def test_untrained_reports_not_trained(client):
    conn = _db(embedded=4, scored=0, metrics=None)
    with mock.patch("api.routers.ranker.get_db", lambda: _cm(conn)):
        resp = client.get("/api/ranker/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["trained"] is False
    assert body["coverage"] == 0.0
    assert body["comparison_count"] == 0


def test_trained_surfaces_metrics_and_coverage(client):
    metrics = {
        "trained": True, "gated": False, "comparison_count": 40,
        "cv_accuracy": 62.0, "baseline_accuracy": 55.0, "improvement_pp": 7.0,
    }
    conn = _db(embedded=4, scored=2, metrics=metrics)
    with mock.patch("api.routers.ranker.get_db", lambda: _cm(conn)):
        resp = client.get("/api/ranker/status")
    body = resp.json()
    assert body["trained"] is True
    assert body["coverage"] == 0.5  # 2 scored / 4 embedded
    assert body["comparison_count"] == 40
    assert body["cv_accuracy"] == 62.0
    assert body["baseline_accuracy"] == 55.0


def test_user_scope_reads_per_user_key_and_coverage():
    """A superadmin (allowed to read any scope) reads alice's per-user snapshot."""
    metrics = {
        "trained": True, "gated": False, "comparison_count": 25,
        "cv_accuracy": 60.0, "baseline_accuracy": 55.0, "improvement_pp": 5.0,
    }
    conn = _db(embedded=4, scored=3, metrics=metrics, user_id="alice")
    sa = CurrentUser(user_id="root", role="superadmin", edition_authenticated=True)
    client_sa, app = _client_for(sa)
    try:
        with mock.patch("api.routers.ranker.get_db", lambda: _cm(conn)):
            user_body = client_sa.get("/api/ranker/status?user=alice").json()
            global_body = client_sa.get("/api/ranker/status").json()
    finally:
        app.dependency_overrides.clear()
    # ?user=alice reads alice's per-user snapshot + coverage (3 scored / 4 embedded)
    assert user_body["trained"] is True
    assert user_body["coverage"] == 0.75
    assert user_body["comparison_count"] == 25
    # Global scope on the same DB sees no NULL-user rows -> untrained, 0 coverage
    assert global_body["trained"] is False
    assert global_body["coverage"] == 0.0


# --- F6': ?user= scope is restricted to the caller (unless superadmin) ---

def test_cross_user_scope_denied():
    """A non-superadmin reading another user's scope is refused with 403."""
    conn = _db(embedded=4, scored=3, metrics=None, user_id="alice")
    bob = CurrentUser(user_id="bob", role="user")
    client_bob, app = _client_for(bob)
    try:
        with mock.patch("api.routers.ranker.get_db", lambda: _cm(conn)):
            resp = client_bob.get("/api/ranker/status?user=alice")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 403


def test_own_scope_allowed():
    """A user may read their own per-user scope."""
    metrics = {"trained": True, "gated": False, "comparison_count": 25}
    conn = _db(embedded=4, scored=3, metrics=metrics, user_id="alice")
    alice = CurrentUser(user_id="alice", role="user")
    client_alice, app = _client_for(alice)
    try:
        with mock.patch("api.routers.ranker.get_db", lambda: _cm(conn)):
            resp = client_alice.get("/api/ranker/status?user=alice")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["coverage"] == 0.75


def test_anonymous_scope_denied():
    """An anonymous caller cannot request an explicit user scope."""
    conn = _db(embedded=4, scored=3, metrics=None, user_id="alice")
    client_anon, app = _client_for(None)
    try:
        with mock.patch("api.routers.ranker.get_db", lambda: _cm(conn)):
            resp = client_anon.get("/api/ranker/status?user=alice")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 403


def test_no_scope_global_default_unchanged():
    """No ?user= keeps the global pooled default, open to any caller."""
    conn = _db(embedded=4, scored=0, metrics=None)
    client_anon, app = _client_for(None)
    try:
        with mock.patch("api.routers.ranker.get_db", lambda: _cm(conn)):
            resp = client_anon.get("/api/ranker/status")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["trained"] is False
