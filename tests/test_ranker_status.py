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


def test_user_scope_reads_per_user_key_and_coverage(client):
    metrics = {
        "trained": True, "gated": False, "comparison_count": 25,
        "cv_accuracy": 60.0, "baseline_accuracy": 55.0, "improvement_pp": 5.0,
    }
    conn = _db(embedded=4, scored=3, metrics=metrics, user_id="alice")
    with mock.patch("api.routers.ranker.get_db", lambda: _cm(conn)):
        user_body = client.get("/api/ranker/status?user=alice").json()
        global_body = client.get("/api/ranker/status").json()
    # ?user=alice reads alice's per-user snapshot + coverage (3 scored / 4 embedded)
    assert user_body["trained"] is True
    assert user_body["coverage"] == 0.75
    assert user_body["comparison_count"] == 25
    # Global scope on the same DB sees no NULL-user rows -> untrained, 0 coverage
    assert global_body["trained"] is False
    assert global_body["coverage"] == 0.0
