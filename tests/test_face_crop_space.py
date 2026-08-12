"""Face crops must be taken in the pixel space stored bboxes were detected in.

Face detection runs on the array ``load_image_from_path()`` returns (full
demosaic for RAW), so ``faces.bbox_*`` indexes that array. Every thumbnail
regenerator must therefore crop the same array with the bbox untouched — a
RAW-only rescaling by the embedded-thumbnail ratio moved the crop several
thousand pixels off the face.
"""

import sqlite3
import sys
import types
from io import BytesIO
from unittest import mock

import cv2
import numpy as np
import pytest
from PIL import Image

from faces.clusterer import FaceClusterer
from faces.processor import FaceProcessor
from utils import crop_face_with_padding, load_image_for_face_crop, load_image_from_path
from utils import image_loading

FULL_W, FULL_H = 400, 300
THUMB_W, THUMB_H = 100, 75
STORED_BBOX = (300, 200, 380, 280)
THUMB_SCALE = FULL_W / THUMB_W


def _marked_image():
    """Black BGR image with a white block exactly at STORED_BBOX."""
    img = np.zeros((FULL_H, FULL_W, 3), dtype=np.uint8)
    x1, y1, x2, y2 = STORED_BBOX
    img[y1:y2, x1:x2] = 255
    return img


def _center_brightness(jpeg_bytes):
    img = cv2.imdecode(np.frombuffer(jpeg_bytes, np.uint8), cv2.IMREAD_COLOR)
    h, w = img.shape[:2]
    return float(img[h // 2, w // 2].mean())


class _StubRaw:
    """rawpy.imread() stand-in: a full demosaic plus a 4x smaller embedded thumb."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_thumb(self):
        buf = BytesIO()
        Image.fromarray(np.zeros((THUMB_H, THUMB_W, 3), dtype=np.uint8)).save(
            buf, format="JPEG")
        return types.SimpleNamespace(format="jpeg", data=buf.getvalue())

    def postprocess(self, **kwargs):
        return _marked_image()


@pytest.fixture()
def raw_photo(tmp_path, monkeypatch):
    """A RAW path whose decode yields FULL_W x FULL_H with a 4x smaller thumb."""
    stub = types.ModuleType("rawpy")
    stub.imread = lambda path: _StubRaw()
    stub.ThumbFormat = types.SimpleNamespace(JPEG="jpeg")
    stub.ColorSpace = types.SimpleNamespace(sRGB="srgb")
    monkeypatch.setitem(sys.modules, "rawpy", stub)
    monkeypatch.setattr(image_loading, "_decode_timeout", 0.0)
    path = tmp_path / "shot.nef"
    path.write_bytes(b"fake")
    return str(path)


@pytest.fixture()
def jpeg_photo(tmp_path):
    path = tmp_path / "shot.jpg"
    Image.fromarray(cv2.cvtColor(_marked_image(), cv2.COLOR_BGR2RGB)).save(
        path, quality=100)
    return str(path)


class TestFaceCropLoader:
    def test_jpeg_matches_detection_array(self, jpeg_photo):
        assert np.array_equal(load_image_for_face_crop(jpeg_photo),
                              load_image_from_path(jpeg_photo)[1])

    def test_raw_matches_detection_array(self, raw_photo):
        assert np.array_equal(load_image_for_face_crop(raw_photo),
                              load_image_from_path(raw_photo)[1])

    def test_raw_keeps_full_decode_dimensions(self, raw_photo):
        assert load_image_for_face_crop(raw_photo).shape == (FULL_H, FULL_W, 3)

    def test_stored_bbox_lands_on_the_face_unscaled(self, raw_photo):
        img = load_image_for_face_crop(raw_photo)
        x1, y1, x2, y2 = STORED_BBOX
        assert img[y1:y2, x1:x2].min() == 255

    def test_thumbnail_derived_scale_leaves_the_frame(self, raw_photo):
        img = load_image_for_face_crop(raw_photo)
        scaled = [v * THUMB_SCALE for v in STORED_BBOX]
        assert crop_face_with_padding(img, scaled, size=128) is None
        assert crop_face_with_padding(img, list(STORED_BBOX), size=128) is not None

    def test_missing_file_returns_none(self, tmp_path):
        assert load_image_for_face_crop(str(tmp_path / "gone.jpg")) is None


class TestRefillWorkerCrop:
    def _run_worker(self, image):
        processor = FaceProcessor(db_path=":memory:", config={}, num_workers=1,
                                  batch_size=1, mode='refill')
        processor.work_queue.put((7, "/lib/shot.nef", *STORED_BBOX))
        processor.work_queue.put(None)
        with mock.patch("faces.processor.load_image_for_face_crop",
                        return_value=image):
            processor._worker_thread_refill()
        return processor.result_queue.get_nowait()

    def test_thumbnail_is_cropped_at_the_stored_bbox(self):
        result = self._run_worker(_marked_image())
        assert result['face_id'] == 7
        assert _center_brightness(result['thumbnail']) > 200

    def test_unloadable_photo_is_skipped(self):
        assert self._run_worker(None) is None


class TestClustererThumbnailCrop:
    def _conn(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("""CREATE TABLE faces (id INTEGER PRIMARY KEY, photo_path TEXT,
                        bbox_x1 REAL, bbox_y1 REAL, bbox_x2 REAL, bbox_y2 REAL)""")
        conn.execute("INSERT INTO faces VALUES (?, ?, ?, ?, ?, ?)",
                     (7, "/lib/shot.nef", *STORED_BBOX))
        return conn

    def test_thumbnail_is_cropped_at_the_stored_bbox(self):
        clusterer = FaceClusterer(db_path=":memory:")
        with mock.patch("faces.clusterer.load_image_for_face_crop",
                        return_value=_marked_image()):
            thumbnail = clusterer._generate_face_thumbnail(self._conn(), 7)
        assert _center_brightness(thumbnail) > 200

    def test_unloadable_photo_yields_no_thumbnail(self):
        clusterer = FaceClusterer(db_path=":memory:")
        with mock.patch("faces.clusterer.load_image_for_face_crop",
                        return_value=None):
            assert clusterer._generate_face_thumbnail(self._conn(), 7) is None
