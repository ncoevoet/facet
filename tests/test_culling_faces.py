"""Tests for the batch per-face culling endpoint (POST /api/culling-group/faces).

The endpoint returns per-face eyes-open/smile/expression/confidence + a
per-face is_blink flag for every photo in a culling group, preferring the
persisted faces.eyes_open_score/smile_score columns and falling back to
on-the-fly landmark computation for rows scanned before those columns existed.
These tests pin the batching, grouping, persisted-vs-fallback precedence and
the config-driven thresholds object; the landmark geometry math itself lives
in analyzers.FaceAnalyzer.
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
        confidence REAL, landmark_2d_106 BLOB,
        eyes_open_score REAL, smile_score REAL
    );
    CREATE TABLE photos (path TEXT PRIMARY KEY);
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
    for path in {f["photo_path"] for f in faces}:
        conn.execute("INSERT OR IGNORE INTO photos (path) VALUES (?)", (path,))
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
        mock.patch("analyzers.FaceAnalyzer.compute_smile_score", lambda lm: 7.0),
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
    assert f0["smile_score"] == 7.0
    assert f0["is_blink"] is False  # 8.0 > 4.0 cutoff
    # face with no landmarks -> scores None, not a blink
    fb = body["/b.jpg"][0]
    assert fb["eyes_open_score"] is None and fb["smile_score"] is None
    assert fb["is_blink"] is False


def test_low_eyes_open_flags_blink(client):
    conn = _db(_faces())
    with (
        mock.patch("api.routers.burst_culling.get_db", lambda: _cm(conn)),
        mock.patch("analyzers.FaceAnalyzer.compute_eyes_open_score", lambda lm: 2.0),
        mock.patch("analyzers.FaceAnalyzer.compute_expression_score", lambda lm: 5.0),
        mock.patch("analyzers.FaceAnalyzer.compute_smile_score", lambda lm: 5.0),
    ):
        resp = client.post("/api/culling-group/faces", json={"paths": ["/a.jpg"]})

    faces = resp.json()["faces_by_path"]["/a.jpg"]
    assert all(f["is_blink"] is True for f in faces)  # 2.0 <= 4.0 cutoff


def test_persisted_values_win_over_recompute(client):
    """Rows with persisted per-face columns must be served as-is: the fallback
    landmark computation is only for NULL rows (old DBs)."""
    conn = _db([
        {"id": 1, "photo_path": "/a.jpg", "face_index": 0, "confidence": 0.9,
         "landmark_2d_106": _LANDMARK_BLOB, "eyes_open_score": 9.5, "smile_score": 8.5},
    ])
    with (
        mock.patch("api.routers.burst_culling.get_db", lambda: _cm(conn)),
        mock.patch("analyzers.FaceAnalyzer.compute_eyes_open_score", lambda lm: 1.0),
        mock.patch("analyzers.FaceAnalyzer.compute_expression_score", lambda lm: 6.0),
        mock.patch("analyzers.FaceAnalyzer.compute_smile_score", lambda lm: 1.0),
    ):
        resp = client.post("/api/culling-group/faces", json={"paths": ["/a.jpg"]})

    face = resp.json()["faces_by_path"]["/a.jpg"][0]
    assert face["eyes_open_score"] == 9.5 and face["smile_score"] == 8.5
    assert face["expression_score"] == 6.0  # openness stays computed on the fly
    assert face["is_blink"] is False  # persisted 9.5 wins over the mocked 1.0


def test_null_rows_fall_back_to_landmark_compute(client):
    """Rows scanned before the per-face columns existed (NULL) fall back to the
    on-the-fly landmark computation, including per-face is_blink."""
    conn = _db([
        {"id": 1, "photo_path": "/a.jpg", "face_index": 0, "confidence": 0.9,
         "landmark_2d_106": _LANDMARK_BLOB},
    ])
    with (
        mock.patch("api.routers.burst_culling.get_db", lambda: _cm(conn)),
        mock.patch("analyzers.FaceAnalyzer.compute_eyes_open_score", lambda lm: 3.0),
        mock.patch("analyzers.FaceAnalyzer.compute_expression_score", lambda lm: 5.5),
        mock.patch("analyzers.FaceAnalyzer.compute_smile_score", lambda lm: 2.0),
    ):
        resp = client.post("/api/culling-group/faces", json={"paths": ["/a.jpg"]})

    face = resp.json()["faces_by_path"]["/a.jpg"][0]
    assert face["eyes_open_score"] == 3.0 and face["smile_score"] == 2.0
    assert face["expression_score"] == 5.5
    assert face["is_blink"] is True  # 3.0 <= 4.0 cutoff


def test_thresholds_come_from_config(client):
    """The response exposes the scoring_config face_detection cutoffs so the
    client never hardcodes them."""
    conn = _db(_faces())
    with (
        mock.patch("api.routers.burst_culling.get_db", lambda: _cm(conn)),
        mock.patch.dict(
            "api.config._FULL_CONFIG",
            {"face_detection": {"eyes_closed_max": 3.5, "poor_expression_min": 2.5}},
        ),
        mock.patch("analyzers.FaceAnalyzer.compute_eyes_open_score", lambda lm: 3.5),
        mock.patch("analyzers.FaceAnalyzer.compute_expression_score", lambda lm: 5.0),
        mock.patch("analyzers.FaceAnalyzer.compute_smile_score", lambda lm: 5.0),
    ):
        resp = client.post("/api/culling-group/faces", json={"paths": ["/a.jpg"]})

    body = resp.json()
    assert body["thresholds"] == {"eyes_closed_max": 3.5, "poor_expression_min": 2.5}
    # is_blink follows the configured cutoff (3.5 <= 3.5)
    assert all(f["is_blink"] is True for f in body["faces_by_path"]["/a.jpg"])


def test_profile_overrides_face_thresholds(client):
    """A genre profile's face cutoffs override the global face_detection ones so
    the darkroom badges/blink flags reflect the chosen genre."""
    conn = _db(_faces())
    with (
        mock.patch("api.routers.burst_culling.get_db", lambda: _cm(conn)),
        mock.patch(
            "api.routers.burst_culling._resolve_cull_profile",
            return_value={"eyes_closed_max": 6.0, "poor_expression_min": 5.0},
        ),
        mock.patch("analyzers.FaceAnalyzer.compute_eyes_open_score", lambda lm: 5.5),
        mock.patch("analyzers.FaceAnalyzer.compute_expression_score", lambda lm: 5.0),
        mock.patch("analyzers.FaceAnalyzer.compute_smile_score", lambda lm: 5.0),
    ):
        resp = client.post(
            "/api/culling-group/faces", json={"paths": ["/a.jpg"], "profile": "wedding"})
    body = resp.json()
    assert body["thresholds"] == {"eyes_closed_max": 6.0, "poor_expression_min": 5.0}
    # eyes 5.5 <= the profile's 6.0 cutoff -> blink under this genre profile
    assert all(f["is_blink"] is True for f in body["faces_by_path"]["/a.jpg"])


def test_empty_paths_returns_empty(client):
    resp = client.post("/api/culling-group/faces", json={"paths": []})
    assert resp.status_code == 200
    body = resp.json()
    assert body["faces_by_path"] == {}
    assert body["thresholds"] == {"eyes_closed_max": 4.0, "poor_expression_min": 4.0}


def test_path_not_visible_is_filtered(client):
    """A path with face rows but absent from the visible photos set must not
    leak face metadata — the visibility join drops it (regression for IDOR)."""
    conn = _db(_faces())
    conn.execute("DELETE FROM photos WHERE path = ?", ("/a.jpg",))
    conn.commit()
    with (
        mock.patch("api.routers.burst_culling.get_db", lambda: _cm(conn)),
        mock.patch("analyzers.FaceAnalyzer.compute_eyes_open_score", lambda lm: 8.0),
        mock.patch("analyzers.FaceAnalyzer.compute_expression_score", lambda lm: 6.0),
    ):
        resp = client.post("/api/culling-group/faces", json={"paths": ["/a.jpg", "/b.jpg"]})

    assert resp.status_code == 200
    body = resp.json()["faces_by_path"]
    assert body["/a.jpg"] == []  # not visible -> no face metadata leaked
    assert len(body["/b.jpg"]) == 1  # visible path still returned
