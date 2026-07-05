"""Tests for the appearance-based MediaPipe blendshape face scores (phase 2).

The core cases never import mediapipe: the blendshape->score mapping is pure
math, and the scorer / FaceAnalyzer wiring is exercised through fakes at the
mediapipe boundary. A final smoke test uses the real package but skips cleanly
when mediapipe or the model bundle is absent.
"""

import os

import numpy as np
import pytest

from analyzers.face import FaceAnalyzer
from analyzers.face_blendshapes import (
    BlendshapeScorer,
    MODEL_PATH,
    blendshapes_to_scores,
    crop_face_region,
    get_blendshape_scorer,
)

ALL_ZERO = {
    'eyeBlinkLeft': 0.0, 'eyeBlinkRight': 0.0,
    'mouthSmileLeft': 0.0, 'mouthSmileRight': 0.0,
    'mouthFrownLeft': 0.0, 'mouthFrownRight': 0.0,
}


def bs(**overrides):
    d = dict(ALL_ZERO)
    d.update(overrides)
    return d


class TestBlendshapesToScores:
    def test_open_eyes_broad_smile(self):
        eyes, smile = blendshapes_to_scores(
            bs(eyeBlinkLeft=0.05, eyeBlinkRight=0.05, mouthSmileLeft=0.95, mouthSmileRight=0.95))
        assert eyes == pytest.approx(9.5)
        assert smile == pytest.approx(9.75)

    def test_closed_eyes_score_below_threshold(self):
        eyes, _ = blendshapes_to_scores(bs(eyeBlinkLeft=0.9, eyeBlinkRight=0.95))
        assert eyes < FaceAnalyzer.EYES_CLOSED_MAX

    def test_blink_of_point_six_lands_at_closed_threshold(self):
        eyes, _ = blendshapes_to_scores(bs(eyeBlinkLeft=0.6, eyeBlinkRight=0.2))
        assert eyes == pytest.approx(FaceAnalyzer.EYES_CLOSED_MAX)

    def test_neutral_mouth_scores_five(self):
        _, smile = blendshapes_to_scores(bs(eyeBlinkLeft=0.1, eyeBlinkRight=0.1))
        assert smile == pytest.approx(5.0)

    def test_frown_scores_below_neutral(self):
        _, smile = blendshapes_to_scores(bs(mouthFrownLeft=0.8, mouthFrownRight=0.8))
        assert smile == pytest.approx(1.0)

    def test_ordering_smile_gt_neutral_gt_frown(self):
        _, smile = blendshapes_to_scores(bs(mouthSmileLeft=0.7, mouthSmileRight=0.7))
        _, neutral = blendshapes_to_scores(bs())
        _, frown = blendshapes_to_scores(bs(mouthFrownLeft=0.7, mouthFrownRight=0.7))
        assert smile > neutral > frown

    def test_scores_clamped_to_zero_ten(self):
        eyes, smile = blendshapes_to_scores(
            bs(mouthSmileLeft=1.0, mouthSmileRight=1.0, mouthFrownLeft=0.0, mouthFrownRight=0.0))
        assert 0.0 <= eyes <= 10.0
        assert 0.0 <= smile <= 10.0

    def test_uses_stronger_eye_blink(self):
        one_eye = blendshapes_to_scores(bs(eyeBlinkLeft=0.8, eyeBlinkRight=0.0))
        assert one_eye[0] == pytest.approx(2.0)


class TestCropFaceRegion:
    def test_pads_around_bbox(self):
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        crop = crop_face_region(img, [40, 40, 60, 60], padding=0.5)
        assert crop.shape[0] == 40 and crop.shape[1] == 40

    def test_clamps_to_image_bounds(self):
        img = np.zeros((50, 50, 3), dtype=np.uint8)
        crop = crop_face_region(img, [0, 0, 10, 10], padding=1.0)
        assert crop.shape[0] <= 50 and crop.shape[1] <= 50

    def test_degenerate_bbox_returns_none(self):
        img = np.zeros((50, 50, 3), dtype=np.uint8)
        assert crop_face_region(img, [30, 30, 30, 30], padding=0.0) is None


class _FakeCategory:
    def __init__(self, name, score):
        self.category_name = name
        self.score = score


class _FakeResult:
    def __init__(self, blendshapes):
        self.face_blendshapes = blendshapes


class _FakeLandmarker:
    def __init__(self, result):
        self._result = result
        self.calls = 0

    def detect(self, image):
        self.calls += 1
        return self._result


class _FakeImageFormat:
    SRGB = 'srgb'


class _FakeMp:
    ImageFormat = _FakeImageFormat

    @staticmethod
    def Image(image_format=None, data=None):
        return object()


def _loaded_scorer(blendshapes):
    scorer = BlendshapeScorer(min_crop_size=1)
    scorer._mp = _FakeMp
    scorer._landmarker = _FakeLandmarker(_FakeResult(blendshapes))
    return scorer


class TestScoreFaceCropFakeBoundary:
    def test_maps_detected_blendshapes(self):
        cats = [_FakeCategory(name, score) for name, score in
                bs(eyeBlinkLeft=0.05, eyeBlinkRight=0.05,
                   mouthSmileLeft=0.9, mouthSmileRight=0.9).items()]
        scorer = _loaded_scorer([cats])
        eyes, smile = scorer.score_face_crop(np.zeros((10, 10, 3), dtype=np.uint8))
        assert eyes == pytest.approx(9.5)
        assert smile > 8.0

    def test_no_face_detected_returns_none(self):
        scorer = _loaded_scorer([])
        assert scorer.score_face_crop(np.zeros((10, 10, 3), dtype=np.uint8)) is None

    def test_none_crop_returns_none(self):
        assert _loaded_scorer([]).score_face_crop(None) is None

    def test_too_small_crop_skips_detection(self):
        scorer = _loaded_scorer([])
        scorer.min_crop_size = 192
        assert scorer.score_face_crop(np.zeros((100, 100, 3), dtype=np.uint8)) is None
        assert scorer._landmarker.calls == 0


class TestScoreFaceCropFallback:
    def test_load_failure_returns_none(self):
        """MediaPipe absent (load failed) -> None so the caller keeps geometry."""
        scorer = BlendshapeScorer(min_crop_size=1)
        scorer._load_failed = True
        assert scorer.score_face_crop(np.zeros((10, 10, 3), dtype=np.uint8)) is None


class TestEnsureModelFile:
    def test_failed_download_does_not_leave_partial_file(self, tmp_path, monkeypatch):
        model_path = str(tmp_path / "face_landmarker.task")
        scorer = BlendshapeScorer(model_path=model_path)

        def fake_urlretrieve(url, path):
            with open(path, 'wb') as f:
                f.write(b'\x00' * 100)
            raise ConnectionError("simulated network drop")

        monkeypatch.setattr(
            "analyzers.face_blendshapes.urllib.request.urlretrieve", fake_urlretrieve)

        with pytest.raises(ConnectionError):
            scorer._ensure_model_file()

        assert not os.path.exists(model_path)

    def test_undersized_download_does_not_leave_file(self, tmp_path, monkeypatch):
        model_path = str(tmp_path / "face_landmarker.task")
        scorer = BlendshapeScorer(model_path=model_path)

        def fake_urlretrieve(url, path):
            with open(path, 'wb') as f:
                f.write(b'\x00' * 10)

        monkeypatch.setattr(
            "analyzers.face_blendshapes.urllib.request.urlretrieve", fake_urlretrieve)

        with pytest.raises(RuntimeError):
            scorer._ensure_model_file()

        assert not os.path.exists(model_path)


class _FixedScorer:
    def __init__(self, result):
        self.result = result

    def score_face_crop(self, crop):
        return self.result


def _bare_analyzer(**attrs):
    analyzer = FaceAnalyzer.__new__(FaceAnalyzer)
    analyzer.enable_blendshapes = False
    analyzer.blendshape_min_crop = 1
    analyzer._blendshape_scorer = None
    for key, value in attrs.items():
        setattr(analyzer, key, value)
    return analyzer


class TestFaceAnalyzerBlendshapeWiring:
    def test_disabled_returns_none(self):
        analyzer = _bare_analyzer(enable_blendshapes=False)
        img = np.zeros((50, 50, 3), dtype=np.uint8)
        assert analyzer._blendshape_face_scores(img, [10, 10, 40, 40]) is None

    def test_enabled_returns_appearance_scores(self):
        analyzer = _bare_analyzer(
            enable_blendshapes=True, _blendshape_scorer=_FixedScorer((7.0, 8.0)))
        img = np.zeros((50, 50, 3), dtype=np.uint8)
        assert analyzer._blendshape_face_scores(img, [10, 10, 40, 40]) == (7.0, 8.0)

    def test_enabled_but_no_face_returns_none(self):
        analyzer = _bare_analyzer(
            enable_blendshapes=True, _blendshape_scorer=_FixedScorer(None))
        img = np.zeros((50, 50, 3), dtype=np.uint8)
        assert analyzer._blendshape_face_scores(img, [10, 10, 40, 40]) is None


class TestRealMediapipeSmoke:
    def test_real_scorer_load_and_detect(self):
        pytest.importorskip("mediapipe", exc_type=ImportError)
        if not os.path.exists(MODEL_PATH):
            pytest.skip("face_landmarker.task model bundle not present")
        scorer = get_blendshape_scorer()
        rng = np.random.default_rng(0)
        noise = rng.integers(0, 256, size=(256, 256, 3), dtype=np.uint8)
        result = scorer.score_face_crop(noise)
        assert result is None or (
            0.0 <= result[0] <= 10.0 and 0.0 <= result[1] <= 10.0)
