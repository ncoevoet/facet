"""Pure-function tests for ``analyzers/composition.py``, ``technical.py``, ``face.py``.

Why this file is light on reference images: only the static / pure methods need
deterministic regression coverage. The model-loading paths (InsightFace,
SAMP-Net, etc.) are integration concerns and live in their own integration
suite. Here we lock the math: bbox -> placement score, EAR formula,
sharpness normalization, monochrome detection.
"""

from __future__ import annotations

import numpy as np
import pytest

from analyzers.composition import CompositionAnalyzer
from analyzers.face import FaceAnalyzer
from analyzers.technical import TechnicalAnalyzer


# ---------------------------------------------------------------------------
# CompositionAnalyzer
# ---------------------------------------------------------------------------


class TestPlacementScore:
    def test_neutral_when_no_bbox(self):
        assert CompositionAnalyzer.get_placement_score(None, 1000, 1000) == 5.0

    def test_subject_at_thirds_intersection_scores_high(self):
        # bbox centered at (1/3 * 1000, 1/3 * 1000) = (333, 333)
        bbox = (300, 300, 366, 366)
        score = CompositionAnalyzer.get_placement_score(bbox, 1000, 1000)
        assert score > 9.0, f"thirds-aligned subject should score >9, got {score}"

    def test_perfectly_centered_subject_scores_high(self):
        # Centered composition is also valid
        bbox = (480, 480, 520, 520)
        score = CompositionAnalyzer.get_placement_score(bbox, 1000, 1000)
        assert score > 9.0, f"centered subject should score >9, got {score}"

    def test_worst_position_scores_low(self):
        # Subject midway between thirds and center on both axes — equidistant
        # from both reference points, neither rule fires strongly.
        bbox = (400, 400, 440, 440)  # center ~0.42, 0.42
        score = CompositionAnalyzer.get_placement_score(bbox, 1000, 1000)
        assert score < 8.5

    def test_returns_float(self):
        score = CompositionAnalyzer.get_placement_score((10, 10, 20, 20), 100, 100)
        assert isinstance(score, float)


class TestPlacementData:
    def test_no_bbox_no_image_falls_back_to_center_assumption(self):
        data = CompositionAnalyzer.get_placement_data(None, 1000, 1000)
        assert data["score"] == 7.0
        assert data["power_point_score"] == 5.0
        assert data["line_score"] == 5.0

    def test_power_point_score_high_at_intersection(self):
        # 1/3, 1/3 intersection
        bbox = (320, 320, 346, 346)
        data = CompositionAnalyzer.get_placement_data(bbox, 1000, 1000)
        assert data["power_point_score"] > 9.0

    def test_power_point_score_low_far_from_intersection(self):
        # Edge of frame
        bbox = (0, 0, 20, 20)
        data = CompositionAnalyzer.get_placement_data(bbox, 1000, 1000)
        assert data["power_point_score"] < 5.0

    def test_returned_fields(self):
        data = CompositionAnalyzer.get_placement_data((100, 100, 200, 200), 1000, 1000)
        assert set(data.keys()) == {"score", "power_point_score", "line_score", "center_score"}
        for v in data.values():
            assert isinstance(v, (int, float))


class TestIntegrateLeadingLines:
    def test_no_faces_lines_lift_low_base(self):
        # Lines should boost composition when there are no faces to anchor the eye.
        base = 4.0
        result = CompositionAnalyzer.integrate_leading_lines(base, leading_lines_score=8.0, has_faces=False)
        assert result > base

    def test_with_faces_lines_have_less_effect(self):
        result_with_faces = CompositionAnalyzer.integrate_leading_lines(4.0, 8.0, has_faces=True)
        result_no_faces = CompositionAnalyzer.integrate_leading_lines(4.0, 8.0, has_faces=False)
        assert result_no_faces >= result_with_faces

    def test_no_lines_returns_base(self):
        assert CompositionAnalyzer.integrate_leading_lines(7.0, 0.0, has_faces=False) == pytest.approx(7.0)


# ---------------------------------------------------------------------------
# TechnicalAnalyzer
# ---------------------------------------------------------------------------


class TestIsoAdjustedSharpness:
    def test_low_iso_no_adjustment(self):
        assert TechnicalAnalyzer.get_iso_adjusted_sharpness(100.0, 100) == 100.0

    def test_none_iso_no_adjustment(self):
        assert TechnicalAnalyzer.get_iso_adjusted_sharpness(100.0, None) == 100.0

    def test_high_iso_boosts(self):
        # ISO 800 -> log2(8) = 3 -> factor 1.45
        result = TechnicalAnalyzer.get_iso_adjusted_sharpness(100.0, 800)
        assert result == pytest.approx(145.0, rel=1e-3)

    def test_higher_iso_boosts_more(self):
        low = TechnicalAnalyzer.get_iso_adjusted_sharpness(100.0, 400)
        high = TechnicalAnalyzer.get_iso_adjusted_sharpness(100.0, 3200)
        assert high > low


class TestSharpnessScore:
    def test_none_returns_zero(self):
        assert TechnicalAnalyzer.get_sharpness_score(None) == 0

    def test_uniform_image_is_zero_sharpness(self):
        img = np.full((50, 50, 3), 128, dtype=np.uint8)
        assert TechnicalAnalyzer.get_sharpness_score(img) == pytest.approx(0.0, abs=0.1)

    def test_noisy_image_is_high_sharpness(self):
        rng = np.random.default_rng(42)
        img = rng.integers(0, 255, (50, 50, 3), dtype=np.uint8)
        # Random pixel values produce high Laplacian variance.
        assert TechnicalAnalyzer.get_sharpness_score(img) > 5.0


class TestMonochromeDetection:
    def test_gray_image_is_monochrome(self):
        img = np.full((50, 50, 3), 128, dtype=np.uint8)
        result = TechnicalAnalyzer.detect_monochrome(img)
        assert result["is_monochrome"] == 1
        assert result["mean_saturation"] == pytest.approx(0.0, abs=0.01)

    def test_color_image_is_not_monochrome(self):
        rng = np.random.default_rng(0)
        img = rng.integers(0, 255, (50, 50, 3), dtype=np.uint8)
        result = TechnicalAnalyzer.detect_monochrome(img)
        assert result["is_monochrome"] == 0
        assert result["mean_saturation"] > 0.1


class TestExposureScore:
    def test_mid_gray_image_is_well_exposed(self):
        img = np.full((50, 50, 3), 128, dtype=np.uint8)
        score = TechnicalAnalyzer.get_exposure_score(img)
        assert score == pytest.approx(10.0)

    def test_all_white_is_clipped(self):
        img = np.full((50, 50, 3), 255, dtype=np.uint8)
        score = TechnicalAnalyzer.get_exposure_score(img)
        assert score < 1.0

    def test_all_black_is_clipped(self):
        img = np.zeros((50, 50, 3), dtype=np.uint8)
        score = TechnicalAnalyzer.get_exposure_score(img)
        assert score < 1.0


class TestColorHarmony:
    def test_uniform_image_zero_entropy(self):
        img = np.full((50, 50, 3), 100, dtype=np.uint8)
        assert TechnicalAnalyzer.get_color_harmony(img) == pytest.approx(0.0, abs=0.01)

    def test_diverse_image_higher_entropy(self):
        rng = np.random.default_rng(7)
        img = rng.integers(0, 255, (50, 50, 3), dtype=np.uint8)
        assert TechnicalAnalyzer.get_color_harmony(img) > 0


# ---------------------------------------------------------------------------
# FaceAnalyzer — EAR math (no model load required)
# ---------------------------------------------------------------------------


def _make_eye_landmarks(open_aperture: float):
    """Build a 106-point landmark array with the left eye opened by ``open_aperture``.

    Eye geometry (horizontal=10, vertical=open_aperture):
      [outer=35]      [inner=39]
              [upper=37, upper2=38]
              [lower=41, lower2=40]
    """
    landmarks = np.zeros((106, 2), dtype=np.float32)
    # Left eye
    landmarks[35] = (0.0, 0.0)             # outer
    landmarks[39] = (10.0, 0.0)            # inner
    landmarks[37] = (3.0, -open_aperture / 2)   # upper
    landmarks[41] = (3.0, +open_aperture / 2)   # lower
    landmarks[38] = (7.0, -open_aperture / 2)   # upper2
    landmarks[40] = (7.0, +open_aperture / 2)   # lower2
    # Right eye (open, anchor wide so the avg is dominated by left)
    landmarks[89] = (20.0, 0.0)
    landmarks[93] = (30.0, 0.0)
    landmarks[91] = (23.0, -1.5)
    landmarks[95] = (23.0, +1.5)
    landmarks[92] = (27.0, -1.5)
    landmarks[94] = (27.0, +1.5)
    return landmarks


class TestPoseGatedBlink:
    """is_blinking() should bail out when the head is turned too far for EAR
    to be reliable, but only when 3D landmarks are enabled."""

    @staticmethod
    def _fake_face(pose, ear_aperture=0.4):
        """Build a stand-in face object with the landmarks + pose attrs the
        method expects, without importing InsightFace."""
        import types
        landmarks = _make_eye_landmarks(open_aperture=ear_aperture)
        return types.SimpleNamespace(
            landmark_2d_106=landmarks,
            pose=np.asarray(pose, dtype=np.float32) if pose is not None else None,
        )

    def _analyzer(self, enable_3d):
        analyzer = FaceAnalyzer.__new__(FaceAnalyzer)
        analyzer.enable_3d_landmarks = enable_3d
        analyzer.blink_ear_threshold = 0.21
        return analyzer

    def test_extreme_yaw_skips_blink_when_3d_enabled(self):
        # ear_aperture=0.4 gives EAR=0.04 < 0.21 → would normally be blinking,
        # but yaw=60° is past the 35° gate, so skip.
        analyzer = self._analyzer(enable_3d=True)
        face = self._fake_face(pose=[60.0, 5.0, 0.0], ear_aperture=0.4)
        assert bool(analyzer.is_blinking(face)) is False

    def test_extreme_pitch_skips_blink_when_3d_enabled(self):
        analyzer = self._analyzer(enable_3d=True)
        face = self._fake_face(pose=[0.0, -50.0, 0.0], ear_aperture=0.4)
        assert bool(analyzer.is_blinking(face)) is False

    def test_neutral_pose_runs_blink_check(self):
        analyzer = self._analyzer(enable_3d=True)
        face = self._fake_face(pose=[5.0, 5.0, 0.0], ear_aperture=0.4)
        # Neutral pose, low EAR → real blink
        assert bool(analyzer.is_blinking(face)) is True

    def test_extreme_yaw_ignored_when_3d_disabled(self):
        # Without 3D landmarks, the pose attribute should NOT short-circuit.
        analyzer = self._analyzer(enable_3d=False)
        face = self._fake_face(pose=[60.0, 5.0, 0.0], ear_aperture=0.4)
        assert bool(analyzer.is_blinking(face)) is True


class TestEarMath:
    def test_open_eye_high_ear(self):
        landmarks = _make_eye_landmarks(open_aperture=3.0)
        ear = FaceAnalyzer.calculate_ear(landmarks, FaceAnalyzer.LEFT_EYE_INDICES)
        # Vertical = 3.0, horizontal = 10.0 → EAR = (3 + 3) / (2 * 10) = 0.3
        assert ear == pytest.approx(0.3, abs=0.01)

    def test_closed_eye_low_ear(self):
        landmarks = _make_eye_landmarks(open_aperture=0.4)
        ear = FaceAnalyzer.calculate_ear(landmarks, FaceAnalyzer.LEFT_EYE_INDICES)
        # 0.4 vertical, 10 horizontal → EAR = 0.04
        assert ear == pytest.approx(0.04, abs=0.005)

    def test_zero_horizontal_distance_fallback(self):
        # Degenerate eye — outer and inner at same point → h=0 → fallback 0.3
        landmarks = np.zeros((106, 2), dtype=np.float32)
        landmarks[37] = (0.0, -2.0)
        landmarks[41] = (0.0, 2.0)
        landmarks[38] = (0.0, -2.0)
        landmarks[40] = (0.0, 2.0)
        ear = FaceAnalyzer.calculate_ear(landmarks, FaceAnalyzer.LEFT_EYE_INDICES)
        assert ear == 0.3

    def test_compute_avg_ear_averages_two_eyes(self):
        landmarks = _make_eye_landmarks(open_aperture=2.0)
        # Left eye: v1 = v2 = 2.0, h = 10 -> EAR = 0.2
        # Right eye (fixture defaults): v1 = v2 = 3.0, h = 10 -> EAR = 0.3
        avg = FaceAnalyzer.compute_avg_ear(landmarks)
        assert avg == pytest.approx((0.2 + 0.3) / 2, abs=0.005)


# ---------------------------------------------------------------------------
# TechnicalAnalyzer — extended coverage (dynamic range, noise, contrast, histogram)
# ---------------------------------------------------------------------------


class TestDynamicRange:
    def test_none_image_returns_zero(self):
        out = TechnicalAnalyzer.get_dynamic_range(None)
        assert out == {'dynamic_range_stops': 0}

    def test_uniform_image_low_range(self):
        img = np.full((50, 50, 3), 128, dtype=np.uint8)
        out = TechnicalAnalyzer.get_dynamic_range(img)
        # p2 == p98 -> log2(1) == 0
        assert out['dynamic_range_stops'] == pytest.approx(0.0, abs=0.05)

    def test_full_range_image_max_range(self):
        # Bottom half black, top half white -> p2~0, p98~255
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        img[50:, :, :] = 255
        out = TechnicalAnalyzer.get_dynamic_range(img)
        # p2 clamped to 1 (function rule), p98 = 255 -> log2(255) ≈ 7.99
        assert out['dynamic_range_stops'] >= 7.0

    def test_returns_rounded_float(self):
        img = np.full((20, 20, 3), 100, dtype=np.uint8)
        out = TechnicalAnalyzer.get_dynamic_range(img)
        assert isinstance(out['dynamic_range_stops'], float)


class TestNoiseEstimate:
    def test_none_image_returns_zero(self):
        out = TechnicalAnalyzer.get_noise_estimate(None)
        assert out == {'noise_sigma': 0}

    def test_uniform_image_low_noise(self):
        img = np.full((50, 50, 3), 100, dtype=np.uint8)
        out = TechnicalAnalyzer.get_noise_estimate(img)
        # Immerkaer on a constant image -> 0
        assert out['noise_sigma'] == pytest.approx(0.0, abs=0.1)

    def test_random_image_high_noise(self):
        rng = np.random.default_rng(13)
        img = rng.integers(0, 255, (100, 100, 3), dtype=np.uint8)
        out = TechnicalAnalyzer.get_noise_estimate(img)
        # Random ~uniform noise — sigma should be well above clean threshold (>15)
        assert out['noise_sigma'] > 15.0

    def test_noise_monotonic_with_amplitude(self):
        rng = np.random.default_rng(13)
        base = np.full((100, 100, 3), 128, dtype=np.uint8)
        low_noise = (base + rng.normal(0, 5, base.shape)).clip(0, 255).astype(np.uint8)
        high_noise = (base + rng.normal(0, 30, base.shape)).clip(0, 255).astype(np.uint8)
        s1 = TechnicalAnalyzer.get_noise_estimate(low_noise)['noise_sigma']
        s2 = TechnicalAnalyzer.get_noise_estimate(high_noise)['noise_sigma']
        assert s2 > s1


class TestContrastScore:
    def test_none_image_returns_zero(self):
        out = TechnicalAnalyzer.get_contrast_score(None)
        assert out['contrast_score'] == 0
        assert out['rms_contrast'] == 0

    def test_uniform_image_low_contrast(self):
        img = np.full((50, 50, 3), 100, dtype=np.uint8)
        out = TechnicalAnalyzer.get_contrast_score(img)
        # Flat image -> near-zero rms_contrast
        assert out['rms_contrast'] == pytest.approx(0.0, abs=0.1)

    def test_high_contrast_image_scores_higher(self):
        flat = np.full((100, 100, 3), 128, dtype=np.uint8)
        bipolar = np.zeros((100, 100, 3), dtype=np.uint8)
        bipolar[50:, :, :] = 255
        s_flat = TechnicalAnalyzer.get_contrast_score(flat)['rms_contrast']
        s_bipolar = TechnicalAnalyzer.get_contrast_score(bipolar)['rms_contrast']
        assert s_bipolar > s_flat


class TestHistogramData:
    def test_none_image_returns_defaults(self):
        out = TechnicalAnalyzer.get_histogram_data(None)
        assert out['exposure_score'] == 5.0
        assert out['shadow_clipped'] == 0
        assert out['highlight_clipped'] == 0
        assert out['is_silhouette'] == 0

    def test_all_black_flags_shadow_clip(self):
        img = np.zeros((50, 50, 3), dtype=np.uint8)
        out = TechnicalAnalyzer.get_histogram_data(img)
        assert out['shadow_clipped'] == 1
        assert out['mean_luminance'] == pytest.approx(0.0, abs=0.01)

    def test_all_white_flags_highlight_clip(self):
        img = np.full((50, 50, 3), 255, dtype=np.uint8)
        out = TechnicalAnalyzer.get_histogram_data(img)
        assert out['highlight_clipped'] == 1
        assert out['mean_luminance'] == pytest.approx(1.0, abs=0.01)

    def test_mid_gray_no_clipping(self):
        img = np.full((50, 50, 3), 128, dtype=np.uint8)
        out = TechnicalAnalyzer.get_histogram_data(img)
        assert out['shadow_clipped'] == 0
        assert out['highlight_clipped'] == 0
        assert out['mean_luminance'] == pytest.approx(0.5, abs=0.02)

    def test_bimodal_silhouette_pattern(self):
        # Half black, half white — classic silhouette pattern
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        img[:, 50:, :] = 255
        out = TechnicalAnalyzer.get_histogram_data(img)
        assert out['is_silhouette'] == 1

    def test_histogram_bytes_length(self):
        img = np.full((10, 10, 3), 50, dtype=np.uint8)
        out = TechnicalAnalyzer.get_histogram_data(img)
        # 256 float32s = 1024 bytes
        assert len(out['histogram_bytes']) == 256 * 4


# ---------------------------------------------------------------------------
# CompositionAnalyzer — leading lines
# ---------------------------------------------------------------------------


class TestLeadingLines:
    def test_none_image_returns_zero(self):
        out = CompositionAnalyzer.detect_leading_lines(None)
        assert out == {'leading_lines_score': 0, 'line_count': 0}

    def test_uniform_image_no_lines(self):
        img = np.full((200, 200, 3), 100, dtype=np.uint8)
        out = CompositionAnalyzer.detect_leading_lines(img)
        assert out['line_count'] == 0
        assert out['leading_lines_score'] == 0

    def test_strong_diagonal_detected(self):
        # 300x300 black image with a thick white diagonal line
        import cv2
        img = np.zeros((300, 300, 3), dtype=np.uint8)
        cv2.line(img, (20, 20), (280, 280), (255, 255, 255), thickness=4)
        out = CompositionAnalyzer.detect_leading_lines(img)
        assert out['line_count'] >= 1
        assert out['leading_lines_score'] > 0
