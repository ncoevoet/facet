"""Tests for saliency-aware social-export crop.

Three layers:
  * pure crop geometry (``processing.social_crop``) — corner/oversized/panorama/
    exact-fit edge cases, no model;
  * subject-box extraction from a synthetic numpy mask
    (``models.saliency_scorer.bbox_from_mask``);
  * the ``/api/photo/social_crop`` + ``/preview`` endpoints via the shared auth
    fixtures, covering the saliency/faces/center fallback chain, edition gating,
    bad presets and path-traversal safety.
"""

import io
import json
import sqlite3
from contextlib import contextmanager
from unittest import mock

import numpy as np
import pytest
from PIL import Image

from processing.social_crop import compute_crop_rect, parse_aspect
from models.saliency_scorer import bbox_from_mask

_MODULE = "api.routers.social_crop"


# ---------------------------------------------------------------------------
# Pure crop geometry
# ---------------------------------------------------------------------------

def _aspect(rect):
    x0, y0, x1, y1 = rect
    return (x1 - x0) / (y1 - y0)


def _inside(rect, w, h):
    x0, y0, x1, y1 = rect
    return 0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h


class TestParseAspect:
    def test_parses_pair(self):
        assert parse_aspect("4:5") == (4.0, 5.0)

    @pytest.mark.parametrize("bad", ["1", "1:2:3", "a:b", "0:1", "1:0", "-1:2"])
    def test_rejects_malformed(self, bad):
        with pytest.raises(ValueError):
            parse_aspect(bad)


class TestComputeCropRect:
    def test_exact_fit_returns_whole_image(self):
        assert compute_crop_rect(1000, 1000, 1, 1, [0, 0, 1, 1]) == (0, 0, 1000, 1000)

    def test_aspect_matches_image_aspect(self):
        # 16:9 target on a 1600x900 image -> whole frame.
        assert compute_crop_rect(1600, 900, 16, 9) == (0, 0, 1600, 900)

    def test_subject_at_corner_clamps_inside(self):
        rect = compute_crop_rect(1000, 1000, 4, 5, [0.0, 0.0, 0.1, 0.1])
        assert rect == (0, 0, 800, 1000)
        assert _inside(rect, 1000, 1000)
        assert _aspect(rect) == pytest.approx(0.8, abs=0.01)

    def test_subject_larger_than_crop_centers(self):
        # Whole-frame subject can't fit a 9:16 crop; window centers on it.
        rect = compute_crop_rect(1000, 1000, 9, 16, [0, 0, 1, 1])
        assert _inside(rect, 1000, 1000)
        assert _aspect(rect) == pytest.approx(9 / 16, abs=0.01)
        cx = (rect[0] + rect[2]) / 2
        assert cx == pytest.approx(500, abs=1)

    def test_extreme_panorama(self):
        rect = compute_crop_rect(4000, 1000, 9, 16, [0.45, 0.4, 0.55, 0.6])
        assert _inside(rect, 4000, 1000)
        assert rect[3] - rect[1] == 1000  # full height
        assert _aspect(rect) == pytest.approx(9 / 16, abs=0.01)

    def test_tall_image_wide_target(self):
        rect = compute_crop_rect(1000, 4000, 16, 9, [0.4, 0.45, 0.6, 0.55])
        assert _inside(rect, 1000, 4000)
        assert rect[2] - rect[0] == 1000  # full width
        assert _aspect(rect) == pytest.approx(16 / 9, abs=0.01)

    def test_center_fallback_when_no_subject(self):
        rect = compute_crop_rect(2000, 1000, 1, 1, None)
        assert rect == (500, 0, 1500, 1000)

    def test_subject_framed_off_center(self):
        # Subject on the left third pulls the square crop left, still inside.
        rect = compute_crop_rect(2000, 1000, 1, 1, [0.1, 0.4, 0.2, 0.6])
        assert _inside(rect, 2000, 1000)
        assert rect[3] - rect[1] == 1000
        assert rect[0] < 500  # pulled left of the plain center crop

    def test_rejects_bad_dimensions(self):
        with pytest.raises(ValueError):
            compute_crop_rect(0, 100, 1, 1)


# ---------------------------------------------------------------------------
# Subject box from a synthetic mask
# ---------------------------------------------------------------------------

class TestBboxFromMask:
    def test_extracts_normalized_box(self):
        mask = np.zeros((100, 200), dtype=np.uint8)
        mask[20:60, 50:150] = 255
        assert bbox_from_mask(mask) == [0.25, 0.2, 0.75, 0.6]

    def test_none_below_min_pixels(self):
        mask = np.zeros((100, 100), dtype=np.uint8)
        mask[0, 0] = 255
        assert bbox_from_mask(mask, min_subject_pixels=50) is None

    def test_none_on_empty_mask(self):
        assert bbox_from_mask(np.zeros((10, 10), dtype=np.uint8)) is None

    def test_full_mask_is_unit_box(self):
        assert bbox_from_mask(np.full((50, 50), 255, dtype=np.uint8)) == [0.0, 0.0, 1.0, 1.0]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

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


def _seed(tmp_path, *, path, subject_bbox=None, faces=None, width=200, height=100):
    db = str(tmp_path / "t.db")
    conn = sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE photos (path TEXT PRIMARY KEY, subject_bbox TEXT, "
        "image_width INTEGER, image_height INTEGER);"
        "CREATE TABLE faces (photo_path TEXT, face_index INTEGER, "
        "bbox_x1 REAL, bbox_y1 REAL, bbox_x2 REAL, bbox_y2 REAL);"
    )
    conn.execute(
        "INSERT INTO photos VALUES (?, ?, ?, ?)",
        (path, subject_bbox, width, height),
    )
    for i, f in enumerate(faces or []):
        conn.execute(
            "INSERT INTO faces VALUES (?, ?, ?, ?, ?, ?)",
            (path, i, f[0], f[1], f[2], f[3]),
        )
    conn.commit()
    conn.close()
    return db


def _write_jpeg(tmp_path, name, size=(200, 100)):
    p = tmp_path / name
    Image.fromarray(np.zeros((size[1], size[0], 3), dtype=np.uint8)).save(str(p), "JPEG")
    return str(p)


class TestPreview:
    def test_saliency_source(self, edition_client, tmp_path):
        db = _seed(tmp_path, path="/a.jpg", subject_bbox=json.dumps([0.4, 0.3, 0.6, 0.7]))
        with mock.patch(f"{_MODULE}.get_db", _db_cm(db)):
            resp = edition_client.get("/api/photo/social_crop/preview",
                                      params={"path": "/a.jpg", "preset": "square"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["source"] == "saliency"
        assert body["aspect"] == "1:1"
        r = body["rect"]
        assert 0.0 <= r["x0"] < r["x1"] <= 1.0
        assert 0.0 <= r["y0"] < r["y1"] <= 1.0

    def test_faces_fallback(self, edition_client, tmp_path):
        db = _seed(tmp_path, path="/a.jpg", subject_bbox=None,
                   faces=[(50, 20, 90, 60), (100, 30, 140, 70)])
        with mock.patch(f"{_MODULE}.get_db", _db_cm(db)):
            resp = edition_client.get("/api/photo/social_crop/preview",
                                      params={"path": "/a.jpg", "preset": "portrait_4x5"})
        assert resp.status_code == 200
        assert resp.json()["source"] == "faces"

    def test_center_fallback(self, edition_client, tmp_path):
        db = _seed(tmp_path, path="/a.jpg", subject_bbox=None, faces=None)
        with mock.patch(f"{_MODULE}.get_db", _db_cm(db)):
            resp = edition_client.get("/api/photo/social_crop/preview",
                                      params={"path": "/a.jpg", "preset": "story_9x16"})
        assert resp.status_code == 200
        assert resp.json()["source"] == "center"

    def test_bad_preset(self, edition_client, tmp_path):
        db = _seed(tmp_path, path="/a.jpg")
        with mock.patch(f"{_MODULE}.get_db", _db_cm(db)):
            resp = edition_client.get("/api/photo/social_crop/preview",
                                      params={"path": "/a.jpg", "preset": "nope"})
        assert resp.status_code == 400

    def test_unknown_path_404(self, edition_client, tmp_path):
        db = _seed(tmp_path, path="/a.jpg")
        with mock.patch(f"{_MODULE}.get_db", _db_cm(db)):
            resp = edition_client.get("/api/photo/social_crop/preview",
                                      params={"path": "/../../etc/passwd", "preset": "square"})
        assert resp.status_code == 404

    def test_non_edition_403(self, regular_client, tmp_path):
        db = _seed(tmp_path, path="/a.jpg")
        with mock.patch(f"{_MODULE}.get_db", _db_cm(db)):
            resp = regular_client.get("/api/photo/social_crop/preview",
                                      params={"path": "/a.jpg", "preset": "square"})
        assert resp.status_code == 403


class TestDownload:
    def test_saliency_crop_returns_jpeg(self, edition_client, tmp_path):
        disk = _write_jpeg(tmp_path, "a.jpg", size=(200, 100))
        db = _seed(tmp_path, path=disk, subject_bbox=json.dumps([0.4, 0.3, 0.6, 0.7]))
        with mock.patch(f"{_MODULE}.get_db", _db_cm(db)):
            resp = edition_client.get("/api/photo/social_crop",
                                      params={"path": disk, "preset": "square"})
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/jpeg"
        assert 'attachment; filename="a_square.jpg"' in resp.headers["content-disposition"]
        out = Image.open(io.BytesIO(resp.content))
        assert out.width == out.height  # 1:1 crop of a 200x100 image -> 100x100

    def test_faces_crop_returns_jpeg(self, edition_client, tmp_path):
        disk = _write_jpeg(tmp_path, "b.jpg", size=(200, 100))
        db = _seed(tmp_path, path=disk, subject_bbox=None,
                   faces=[(60, 20, 120, 80)])
        with mock.patch(f"{_MODULE}.get_db", _db_cm(db)):
            resp = edition_client.get("/api/photo/social_crop",
                                      params={"path": disk, "preset": "portrait_4x5"})
        assert resp.status_code == 200
        out = Image.open(io.BytesIO(resp.content))
        assert out.width / out.height == pytest.approx(4 / 5, abs=0.03)

    def test_center_crop_returns_jpeg(self, edition_client, tmp_path):
        disk = _write_jpeg(tmp_path, "c.jpg", size=(200, 100))
        db = _seed(tmp_path, path=disk, subject_bbox=None, faces=None)
        with mock.patch(f"{_MODULE}.get_db", _db_cm(db)):
            resp = edition_client.get("/api/photo/social_crop",
                                      params={"path": disk, "preset": "square"})
        assert resp.status_code == 200
        assert Image.open(io.BytesIO(resp.content)).size == (100, 100)

    def test_bad_preset_400(self, edition_client, tmp_path):
        disk = _write_jpeg(tmp_path, "d.jpg")
        db = _seed(tmp_path, path=disk)
        with mock.patch(f"{_MODULE}.get_db", _db_cm(db)):
            resp = edition_client.get("/api/photo/social_crop",
                                      params={"path": disk, "preset": "nope"})
        assert resp.status_code == 400

    def test_unknown_path_404(self, edition_client, tmp_path):
        disk = _write_jpeg(tmp_path, "e.jpg")
        db = _seed(tmp_path, path=disk)
        with mock.patch(f"{_MODULE}.get_db", _db_cm(db)):
            resp = edition_client.get("/api/photo/social_crop",
                                      params={"path": "/etc/passwd", "preset": "square"})
        assert resp.status_code == 404

    def test_non_edition_403(self, regular_client, tmp_path):
        disk = _write_jpeg(tmp_path, "f.jpg")
        db = _seed(tmp_path, path=disk)
        with mock.patch(f"{_MODULE}.get_db", _db_cm(db)):
            resp = regular_client.get("/api/photo/social_crop",
                                      params={"path": disk, "preset": "square"})
        assert resp.status_code == 403
