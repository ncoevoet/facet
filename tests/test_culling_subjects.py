"""Tests for the batch per-subject culling endpoint (POST /api/culling-group/subjects).

The endpoint crops every photo's stored thumbnail to its persisted BiRefNet
subject box (``photos.subject_bbox``) and returns the crop + a Laplacian-variance
sharpness (raw and group-normalized 0..10) so a burst/similar group of non-face
subjects can be compared at close-up. It runs NO model: photos with no box, a
malformed box, or a near-full-frame box return ``has_subject: false`` rather than
a faked center crop. These tests pin the batching, the fallback/degenerate-box
handling, the near-full-frame threshold and the group normalization.
"""

import io
import json
import sqlite3
from contextlib import contextmanager
from unittest import mock

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from api import create_app
from api.auth import CurrentUser, get_optional_user

_SCHEMA = """
    CREATE TABLE photos (
        path TEXT PRIMARY KEY,
        thumbnail BLOB,
        subject_bbox TEXT,
        subject_sharpness REAL,
        subject_prominence REAL
    );
"""


def _jpeg(pattern: str) -> bytes:
    """Build a 128x128 JPEG thumbnail: 'sharp' = high-contrast checkerboard
    (high Laplacian variance), 'flat' = solid gray (near-zero variance)."""
    if pattern == "sharp":
        arr = np.indices((128, 128)).sum(axis=0) % 2
        arr = (arr * 255).astype(np.uint8)
        img = Image.fromarray(np.stack([arr] * 3, axis=-1), mode="RGB")
    else:
        img = Image.new("RGB", (128, 128), (128, 128, 128))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def _cm(conn):
    @contextmanager
    def _ctx():
        yield conn
    return _ctx()


def _db(photos):
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    for p in photos:
        cols = list(p.keys())
        conn.execute(
            f"INSERT INTO photos ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
            [p[c] for c in cols],
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


def _bbox(x0, y0, x1, y1):
    return json.dumps([x0, y0, x1, y1])


def test_normal_bbox_yields_crop_and_metrics(client):
    conn = _db([
        {"path": "/a.jpg", "thumbnail": _jpeg("sharp"), "subject_bbox": _bbox(0.2, 0.2, 0.6, 0.6),
         "subject_sharpness": 7.5, "subject_prominence": 0.3},
    ])
    with mock.patch("api.routers.burst_culling.get_db", lambda: _cm(conn)):
        resp = client.post("/api/culling-group/subjects", json={"paths": ["/a.jpg"]})

    assert resp.status_code == 200
    entry = resp.json()["subjects_by_path"]["/a.jpg"]
    assert entry["has_subject"] is True
    assert entry["crop"].startswith("data:image/jpeg;base64,")
    assert entry["crop_sharpness"] is not None and entry["crop_sharpness"] > 0
    # sole subject in the group -> normalized to the top of the 0..10 scale
    assert entry["crop_sharpness_score"] == 10.0
    # stored saliency metrics are passed through untouched
    assert entry["subject_sharpness"] == 7.5
    assert entry["subject_prominence"] == 0.3


def test_missing_bbox_returns_no_subject(client):
    conn = _db([
        {"path": "/a.jpg", "thumbnail": _jpeg("sharp"), "subject_bbox": None,
         "subject_sharpness": 5.0, "subject_prominence": 0.1},
    ])
    with mock.patch("api.routers.burst_culling.get_db", lambda: _cm(conn)):
        resp = client.post("/api/culling-group/subjects", json={"paths": ["/a.jpg"]})

    entry = resp.json()["subjects_by_path"]["/a.jpg"]
    assert entry["has_subject"] is False
    assert entry["crop"] is None
    assert entry["crop_sharpness"] is None
    # stored metrics still surface even without a crop
    assert entry["subject_sharpness"] == 5.0


def test_near_full_frame_bbox_returns_no_subject(client):
    """A box covering more than 90% of the frame area means BiRefNet found no
    subject distinct from the background -> no close-up worth offering."""
    conn = _db([
        {"path": "/a.jpg", "thumbnail": _jpeg("sharp"), "subject_bbox": _bbox(0.0, 0.0, 0.98, 0.98),
         "subject_sharpness": 5.0, "subject_prominence": 0.95},
    ])
    with mock.patch("api.routers.burst_culling.get_db", lambda: _cm(conn)):
        resp = client.post("/api/culling-group/subjects", json={"paths": ["/a.jpg"]})

    entry = resp.json()["subjects_by_path"]["/a.jpg"]
    assert entry["has_subject"] is False
    assert entry["crop"] is None


def test_degenerate_bbox_returns_no_subject(client):
    """A zero/negative-area box (x1<=x0) is malformed -> no subject, no crash."""
    conn = _db([
        {"path": "/a.jpg", "thumbnail": _jpeg("sharp"), "subject_bbox": _bbox(0.6, 0.2, 0.6, 0.6),
         "subject_sharpness": None, "subject_prominence": None},
        {"path": "/b.jpg", "thumbnail": _jpeg("sharp"), "subject_bbox": "not-json",
         "subject_sharpness": None, "subject_prominence": None},
    ])
    with mock.patch("api.routers.burst_culling.get_db", lambda: _cm(conn)):
        resp = client.post("/api/culling-group/subjects", json={"paths": ["/a.jpg", "/b.jpg"]})

    body = resp.json()["subjects_by_path"]
    assert body["/a.jpg"]["has_subject"] is False
    assert body["/b.jpg"]["has_subject"] is False


def test_group_normalization_ranks_sharpest_at_ten(client):
    """crop_sharpness_score rescales the group so the sharpest crop reads 10 and
    a flat (low-variance) crop reads lower — the badge ranks within the group."""
    conn = _db([
        {"path": "/sharp.jpg", "thumbnail": _jpeg("sharp"), "subject_bbox": _bbox(0.1, 0.1, 0.9, 0.9),
         "subject_sharpness": None, "subject_prominence": None},
        {"path": "/flat.jpg", "thumbnail": _jpeg("flat"), "subject_bbox": _bbox(0.1, 0.1, 0.9, 0.9),
         "subject_sharpness": None, "subject_prominence": None},
    ])
    with mock.patch("api.routers.burst_culling.get_db", lambda: _cm(conn)):
        resp = client.post(
            "/api/culling-group/subjects", json={"paths": ["/sharp.jpg", "/flat.jpg"]})

    body = resp.json()["subjects_by_path"]
    assert body["/sharp.jpg"]["has_subject"] is True
    assert body["/flat.jpg"]["has_subject"] is True
    assert body["/sharp.jpg"]["crop_sharpness"] > body["/flat.jpg"]["crop_sharpness"]
    assert body["/sharp.jpg"]["crop_sharpness_score"] == 10.0
    assert body["/flat.jpg"]["crop_sharpness_score"] < 10.0


def test_empty_paths_returns_empty(client):
    resp = client.post("/api/culling-group/subjects", json={"paths": []})
    assert resp.status_code == 200
    assert resp.json()["subjects_by_path"] == {}


def test_path_not_visible_is_filtered(client):
    """A requested path absent from the visible photos set must not leak a crop —
    it is returned defaulted to has_subject=false (no photos row matched)."""
    conn = _db([
        {"path": "/b.jpg", "thumbnail": _jpeg("sharp"), "subject_bbox": _bbox(0.2, 0.2, 0.6, 0.6),
         "subject_sharpness": None, "subject_prominence": None},
    ])
    with mock.patch("api.routers.burst_culling.get_db", lambda: _cm(conn)):
        resp = client.post(
            "/api/culling-group/subjects", json={"paths": ["/a.jpg", "/b.jpg"]})

    body = resp.json()["subjects_by_path"]
    assert body["/a.jpg"]["has_subject"] is False  # unknown path -> defaulted, no leak
    assert body["/b.jpg"]["has_subject"] is True
