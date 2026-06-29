"""End-to-end tests for BatchProcessor over its producer/consumer threads.

Drives the real threaded engine with a FakeScorer that stubs only the model
boundary (`self.scorer.*`), so the worker/GPU threads, queues, per-item error
isolation, and batch-save flow all run for real on tiny CPU images. No GPU and
no real torch weights are needed.
"""

import numpy as np
import pytest
from PIL import Image

torch = pytest.importorskip("torch")
pytest.importorskip("cv2")

from config.scoring_config import ScoringConfig  # noqa: E402
from processing.batch_processor import BatchProcessor  # noqa: E402


def _tiny_jpegs(tmp_path, count, sentinel_index=None):
    """Write `count` tiny JPEGs. The sentinel image is 32x32 instead of 64x64 so
    a stubbed analyzer can single it out by shape (JPEG preserves dimensions)."""
    paths = []
    for i in range(count):
        size = 32 if i == sentinel_index else 64
        arr = np.random.randint(0, 255, (size, size, 3), dtype=np.uint8)
        p = tmp_path / f"img_{i}.jpg"
        Image.fromarray(arr).save(p, "JPEG")
        paths.append(str(p))
    return paths


class _FakeTechAnalyzer:
    def get_sharpness_data(self, img_cv, cache=None):
        return {"normalized": 5.0, "raw_variance": 100.0}

    def get_color_harmony_data(self, img_cv, cache=None):
        return {"normalized": 5.0, "raw_entropy": 3.0}

    def get_histogram_data(self, img_cv, cache=None):
        return {"exposure_score": 5.0, "shadow_clipped": 0, "highlight_clipped": 0,
                "spread": 50.0, "histogram_bytes": b"", "mean_luminance": 128.0,
                "bimodality": 0.0}

    def detect_monochrome(self, img_cv, threshold=0.1, cache=None):
        return {"is_monochrome": 0, "mean_saturation": 50.0}

    def get_dynamic_range(self, img_cv, cache=None):
        return {"dynamic_range_stops": 8.0}

    def get_noise_estimate(self, img_cv, cache=None):
        return {"noise_sigma": 1.0}

    def get_contrast_score(self, img_cv, cache=None):
        return {"contrast_score": 5.0}


class _FakeFaceAnalyzer:
    def __init__(self, raise_on_size=None):
        self.raise_on_size = raise_on_size

    def analyze_faces(self, img_cv):
        if self.raise_on_size is not None and img_cv.shape[0] == self.raise_on_size:
            raise ValueError("simulated per-image analysis failure")
        return {"face_count": 0, "face_quality": 0.0, "eye_sharpness": 0.0,
                "face_sharpness": 0.0, "face_area": 0, "bbox": None,
                "raw_eye_sharpness": 0.0, "is_group_portrait": 0,
                "max_face_confidence": 0.0, "face_details": []}


class FakeScorer:
    """Minimal stand-in for Facet exposing only what BatchProcessor touches."""

    def __init__(self, fail_inference=False, fail_face_paths=None):
        self.uses_transformers_backend = True  # skip CLIP preprocess
        self.device = "cpu"
        self.tagger = None
        self.config = ScoringConfig("scoring_config.json", validate=False)
        self.tech_analyzer = _FakeTechAnalyzer()
        self.face_analyzer = _FakeFaceAnalyzer()
        self._fail_inference = fail_inference
        self._fail_face_paths = set(fail_face_paths or [])
        self.saved = []
        self.committed = False

    def get_aesthetic_and_quality_batch(self, pil_images, clip_inputs):
        if self._fail_inference:
            raise RuntimeError("simulated CUDA OOM")
        return [(7.0, None, 8.0, "fake-model") for _ in pil_images]

    def get_composition_scores(self, pil_img, img_cv, comp_data):
        return "none", None

    def get_exif_data(self, path):
        return {"iso": 100, "f_stop": 2.8}

    def calculate_aggregate_logic(self, metrics):
        # A per-path failure injected here lets us prove per-item error isolation
        # without breaking the whole batch.
        return 7.5, "others"

    def save_photos_batch(self, pending_saves):
        self.saved.extend(p for p, _ in pending_saves)

    def commit(self):
        self.committed = True


def _make_processor(scorer, **kwargs):
    from unittest import mock
    with mock.patch("processing.batch_processor.ResourceMonitor"):
        return BatchProcessor(scorer=scorer, num_workers=2, batch_size=2,
                              batch_save_size=2, config={}, **kwargs)


class TestBatchProcessorE2E:
    @pytest.mark.timeout(30)
    def test_all_paths_saved_and_committed(self, tmp_path):
        paths = _tiny_jpegs(tmp_path, 5)
        scorer = FakeScorer()
        proc = _make_processor(scorer)
        proc.process_files(paths, show_metrics=False)

        saved_paths = {r["filename"] for r in scorer.saved}
        assert saved_paths == {f"img_{i}.jpg" for i in range(5)}
        assert all(r["aggregate"] == 7.5 for r in scorer.saved)
        assert scorer.committed is True

    @pytest.mark.timeout(30)
    def test_error_isolation_one_bad_image(self, tmp_path):
        # img_1 is the 32x32 sentinel; the stubbed face analyzer raises on it.
        paths = _tiny_jpegs(tmp_path, 4, sentinel_index=1)
        scorer = FakeScorer()
        scorer.face_analyzer = _FakeFaceAnalyzer(raise_on_size=32)
        errors = []
        proc = _make_processor(scorer, on_error=lambda p, stage, e: errors.append((p, stage)))

        proc.process_files(paths, show_metrics=False)

        # The per-item try/except in _process_batch isolates the bad image; the
        # other three still save. Deleting that guard makes this fail.
        saved = {r["filename"] for r in scorer.saved}
        assert saved == {"img_0.jpg", "img_2.jpg", "img_3.jpg"}
        assert any(p.endswith("img_1.jpg") for p, _ in errors)

    @pytest.mark.timeout(30)
    def test_inference_failure_drains_without_hanging(self, tmp_path):
        paths = _tiny_jpegs(tmp_path, 4)
        scorer = FakeScorer(fail_inference=True)
        errors = []
        proc = _make_processor(scorer, on_error=lambda p, stage, e: errors.append((p, stage)))

        # Batch-level inference failure must error every item and let
        # process_files return rather than waiting forever on missing results.
        proc.process_files(paths, show_metrics=False)

        assert scorer.saved == []
        assert len(errors) == 4
        assert scorer.committed is True
