"""Tests for the saliency overlay + face-marker endpoints (api/routers/saliency.py).

The BiRefNet model is stubbed via the model_cache loader, so the heatmap path
runs end-to-end (colourise + PNG encode) on CPU with no real weights.
"""

import io
import sqlite3
from contextlib import contextmanager
from unittest import mock

import numpy as np
import pytest
from PIL import Image

_MODULE = "api.routers.saliency"


@pytest.fixture()
def http(client):
    return client


def _db_cm(db_path):
    @contextmanager
    def _cm():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    return _cm


def _thumb_bytes():
    buf = io.BytesIO()
    Image.fromarray(np.zeros((32, 32, 3), dtype=np.uint8)).save(buf, "JPEG")
    return buf.getvalue()


def _seed(tmp_path, *, with_thumb=True, faces=None):
    db = str(tmp_path / "t.db")
    conn = sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE photos (path TEXT PRIMARY KEY, thumbnail BLOB, "
        "image_width INTEGER, image_height INTEGER);"
        "CREATE TABLE faces (photo_path TEXT, face_index INTEGER, "
        "bbox_x1 REAL, bbox_y1 REAL, bbox_x2 REAL, bbox_y2 REAL, landmark_2d_106 BLOB);"
    )
    conn.execute(
        "INSERT INTO photos VALUES (?, ?, ?, ?)",
        ("/a.jpg", _thumb_bytes() if with_thumb else None, 100, 200),
    )
    for i, f in enumerate(faces or []):
        conn.execute(
            "INSERT INTO faces VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("/a.jpg", i, f["bbox"][0], f["bbox"][1], f["bbox"][2], f["bbox"][3], f["lm"]),
        )
    conn.commit()
    conn.close()
    return db


class _FakeSaliency:
    def get_saliency_soft(self, pil_img):
        w, h = pil_img.size
        return np.linspace(0, 1, w * h, dtype=np.float32).reshape(h, w)


class TestSaliencyOverlay:
    def test_returns_png(self, http, tmp_path):
        db = _seed(tmp_path)
        with (
            mock.patch(f"{_MODULE}.get_db", _db_cm(db)),
            mock.patch("api.model_cache.get_or_load_saliency_scorer", return_value=_FakeSaliency()),
        ):
            resp = http.get("/api/saliency_overlay", params={"path": "/a.jpg"})
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"
        assert len(resp.content) > 0

    def test_404_without_thumbnail(self, http, tmp_path):
        db = _seed(tmp_path, with_thumb=False)
        with mock.patch(f"{_MODULE}.get_db", _db_cm(db)):
            resp = http.get("/api/saliency_overlay", params={"path": "/a.jpg"})
        assert resp.status_code == 404

    def test_404_when_feature_disabled(self, http, tmp_path):
        db = _seed(tmp_path)
        with (
            mock.patch(f"{_MODULE}.get_db", _db_cm(db)),
            mock.patch(f"{_MODULE}.VIEWER_CONFIG", {"features": {"show_saliency_overlay": False}}),
        ):
            resp = http.get("/api/saliency_overlay", params={"path": "/a.jpg"})
        assert resp.status_code == 404


class TestFaceMarkers:
    def test_returns_normalized_boxes_and_eyes(self, http, tmp_path):
        lm = (np.ones((106, 2), dtype=np.float32) * 10.0).tobytes()
        db = _seed(tmp_path, faces=[{"bbox": [10, 20, 60, 120], "lm": lm}])
        with mock.patch(f"{_MODULE}.get_db", _db_cm(db)):
            resp = http.get("/api/photo/face_markers", params={"path": "/a.jpg"})
        assert resp.status_code == 200
        faces = resp.json()["faces"]
        assert len(faces) == 1
        # bbox normalised by 100x200
        assert faces[0]["bbox"] == [0.1, 0.1, 0.6, 0.6]
        assert faces[0]["eyes_open_score"] is not None
        assert len(faces[0]["eyes"]) == 2
        # all-equal landmarks -> eye centre at (10,10) normalised
        assert faces[0]["eyes"][0] == pytest.approx([0.1, 0.05])

    def test_unknown_photo_404(self, http, tmp_path):
        db = _seed(tmp_path)
        with mock.patch(f"{_MODULE}.get_db", _db_cm(db)):
            resp = http.get("/api/photo/face_markers", params={"path": "/missing.jpg"})
        assert resp.status_code == 404
