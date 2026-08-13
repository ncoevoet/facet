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


def _seed(tmp_path, *, with_thumb=True, faces=None, width=100, height=200):
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
        ("/a.jpg", _thumb_bytes() if with_thumb else None, width, height),
    )
    for i, f in enumerate(faces or []):
        conn.execute(
            "INSERT INTO faces VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("/a.jpg", i, f["bbox"][0], f["bbox"][1], f["bbox"][2], f["bbox"][3], f["lm"]),
        )
    conn.commit()
    conn.close()
    return db


def _max_coordinate(faces):
    """Largest normalised coordinate the endpoint emitted, over boxes and eyes."""
    values = [v for f in faces for v in (f["bbox"] or [])]
    values += [v for f in faces for point in f["eyes"] for v in point]
    return max(values, default=0.0)


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

    def test_edge_face_overhanging_the_frame_is_clamped(self, http, tmp_path):
        """A box within FACE_FRAME_TOLERANCE is kept, both overhanging edges
        pinned to the frame -- the low end (x1/y1 negative) and the high end
        (x2/y2 past width/height) alike.
        """
        db = _seed(tmp_path, faces=[{"bbox": [-10, -20, 110, 220], "lm": None}])
        with mock.patch(f"{_MODULE}.get_db", _db_cm(db)):
            resp = http.get("/api/photo/face_markers", params={"path": "/a.jpg"})
        faces = resp.json()["faces"]
        assert faces[0]["bbox"] == [0.0, 0.0, 1.0, 1.0]
        # A kept box is always a fraction of the frame -- a missing ceiling
        # clamp would leak x2/y2 > 1.0 here (110/100 = 1.1, 220/200 = 1.1).
        assert _max_coordinate(faces) <= 1.0

    def test_box_from_a_different_frame_is_dropped(self, http, tmp_path):
        """Dimensions from the 640px thumbnail, boxes in original-image pixels.

        Normalising by the recorded frame would scatter the markers several
        frames off the photo, so the geometry is withheld; the eyes-open score
        is a landmark ratio and survives.
        """
        lm = (np.ones((106, 2), dtype=np.float32) * 1500.0).tobytes()
        db = _seed(tmp_path, width=640, height=427,
                   faces=[{"bbox": [1200, 900, 1600, 1300], "lm": lm}])
        with mock.patch(f"{_MODULE}.get_db", _db_cm(db)):
            resp = http.get("/api/photo/face_markers", params={"path": "/a.jpg"})
        face = resp.json()["faces"][0]
        assert face["bbox"] is None
        assert face["eyes"] == []
        assert face["eyes_open_score"] is not None

    def test_photo_without_dimensions_drops_geometry(self, http, tmp_path):
        lm = (np.ones((106, 2), dtype=np.float32) * 10.0).tobytes()
        db = _seed(tmp_path, width=None, height=None,
                   faces=[{"bbox": [10, 20, 60, 120], "lm": lm}])
        with mock.patch(f"{_MODULE}.get_db", _db_cm(db)):
            resp = http.get("/api/photo/face_markers", params={"path": "/a.jpg"})
        face = resp.json()["faces"][0]
        assert face["bbox"] is None
        assert face["eyes"] == []
        assert face["eyes_open_score"] is not None
