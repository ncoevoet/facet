"""Tests for the batch per-face culling endpoint (POST /api/culling-group/faces).

The endpoint returns per-face eyes-open/expression/confidence + a per-face
is_blink flag for every photo in a culling group, recomputing eyes/expression
from stored landmarks. These tests pin the batching, grouping and is_blink
threshold; the landmark geometry math itself lives in analyzers.FaceAnalyzer.
"""

import sqlite3
from contextlib import contextmanager
from unittest import mock

import numpy as np
import pytest
from fastapi.testclient import TestClient

from api import create_app
from api.auth import CurrentUser, get_optional_user

_LANDMARK_BLOB = np.zeros(106 * 2, dtype=np.float32).tobytes()

_SCHEMA = """
    CREATE TABLE faces (
        id INTEGER PRIMARY KEY,
        photo_path TEXT, face_index INTEGER,
        bbox_x1 REAL, bbox_y1 REAL, bbox_x2 REAL, bbox_y2 REAL,
        confidence REAL, landmark_2d_106 BLOB
    );
"""


def _cm(conn):
    @contextmanager
    def _ctx():
        yield conn
    return _ctx()


def _db(faces):
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    for f in faces:
        cols = list(f.keys())
        conn.execute(
            f"INSERT INTO faces ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
            [f[c] for c in cols],
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


def _faces():
    return [
        {"id": 1, "photo_path": "/a.jpg", "face_index": 0, "bbox_x1": 1, "bbox_y1": 2,
         "bbox_x2": 3, "bbox_y2": 4, "confidence": 0.9, "landmark_2d_106": _LANDMARK_BLOB},
        {"id": 2, "photo_path": "/a.jpg", "face_index": 1, "bbox_x1": 5, "bbox_y1": 6,
         "bbox_x2": 7, "bbox_y2": 8, "confidence": 0.8, "landmark_2d_106": _LANDMARK_BLOB},
        {"id": 3, "photo_path": "/b.jpg", "face_index": 0, "bbox_x1": 0, "bbox_y1": 0,
         "bbox_x2": 1, "bbox_y2": 1, "confidence": 0.7, "landmark_2d_106": None},
    ]


def test_batches_and_groups_by_path(client):
    conn = _db(_faces())
    with (
        mock.patch("api.routers.burst_culling.get_db", lambda: _cm(conn)),
        mock.patch("analyzers.FaceAnalyzer.compute_eyes_open_score", lambda lm: 8.0),
        mock.patch("analyzers.FaceAnalyzer.compute_expression_score", lambda lm: 6.0),
    ):
        resp = client.post("/api/culling-group/faces", json={"paths": ["/a.jpg", "/b.jpg"]})

    assert resp.status_code == 200
    body = resp.json()["faces_by_path"]
    assert set(body) == {"/a.jpg", "/b.jpg"}
    assert len(body["/a.jpg"]) == 2  # both faces of /a.jpg in one call
    f0 = body["/a.jpg"][0]
    assert f0["id"] == 1 and f0["face_index"] == 0
    assert f0["confidence"] == 0.9
    assert f0["eyes_open_score"] == 8.0 and f0["expression_score"] == 6.0
    assert f0["is_blink"] is False  # 8.0 > 4.0 cutoff
    # face with no landmarks -> scores None, not a blink
    fb = body["/b.jpg"][0]
    assert fb["eyes_open_score"] is None and fb["is_blink"] is False


def test_low_eyes_open_flags_blink(client):
    conn = _db(_faces())
    with (
        mock.patch("api.routers.burst_culling.get_db", lambda: _cm(conn)),
        mock.patch("analyzers.FaceAnalyzer.compute_eyes_open_score", lambda lm: 2.0),
        mock.patch("analyzers.FaceAnalyzer.compute_expression_score", lambda lm: 5.0),
    ):
        resp = client.post("/api/culling-group/faces", json={"paths": ["/a.jpg"]})

    faces = resp.json()["faces_by_path"]["/a.jpg"]
    assert all(f["is_blink"] is True for f in faces)  # 2.0 <= 4.0 cutoff


def test_empty_paths_returns_empty(client):
    resp = client.post("/api/culling-group/faces", json={"paths": []})
    assert resp.status_code == 200
    assert resp.json() == {"faces_by_path": {}}
