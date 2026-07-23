"""Tests for processing.batch_processor.BatchProcessor constructor invariants.

The module imports torch/imagehash at top level; these are stubbed only when
absent (e.g. the CI test job that has no GPU stack) so the import succeeds,
leaving a real local install untouched. The thread/GPU processing paths are
integration-level and not covered here.
"""

import importlib.util
import sys
from unittest import mock

# Stub heavy GPU-only imports when absent (e.g. the CI test job has no GPU
# stack) so this module imports. The stubs are removed from sys.modules the
# instant batch_processor is imported (see below).
_STUBBED_MODULES = []
for _name in ("torch", "imagehash"):
    if importlib.util.find_spec(_name) is None and _name not in sys.modules:
        _stub = mock.MagicMock()
        if _name == "torch":
            # scipy.stats probes torch.Tensor via issubclass() at import time;
            # a MagicMock attribute is not a class and raises TypeError, so the
            # stub must expose a real Tensor class.
            _stub.Tensor = type("Tensor", (), {})
        sys.modules[_name] = _stub
        _STUBBED_MODULES.append(_name)

from processing.batch_processor import BatchProcessor  # noqa: E402

# Drop the stubs from sys.modules NOW, not in teardown_module: pytest imports
# every test module during collection before running any test, so a stub left
# here would leak into later modules' collection (e.g. make their `import torch`
# resolve to this fake, masking a real-torch requirement and defeating
# `importorskip("torch")`). batch_processor already holds its own references, so
# removing the entries now is safe for this file's tests.
for _name in _STUBBED_MODULES:
    sys.modules.pop(_name, None)


def _make_processor(**kwargs):
    # Patch ResourceMonitor so construction does not start any auto-tuning.
    with mock.patch("processing.batch_processor.ResourceMonitor"):
        return BatchProcessor(scorer=mock.MagicMock(), **kwargs)


class TestQueueSizing:
    def test_image_queue_maxsize_is_batch_times_prefetch(self):
        bp = _make_processor(batch_size=8, prefetch_multiplier=3)
        assert bp.image_queue.maxsize == 24

    def test_default_prefetch_multiplier_is_two(self):
        bp = _make_processor(batch_size=16)
        assert bp.image_queue.maxsize == 32


class TestInitialMetrics:
    def test_metrics_start_zeroed(self):
        m = _make_processor().get_metrics()
        assert m["images_processed"] == 0
        assert m["total_load_time"] == 0.0
        assert m["total_bytes_loaded"] == 0
        assert m["queue_timeouts"] == 0
        assert m["start_time"] is None

    def test_get_metrics_returns_a_copy(self):
        bp = _make_processor()
        snapshot = bp.get_metrics()
        snapshot["images_processed"] = 999
        assert bp.get_metrics()["images_processed"] == 0


class TestConstructorArgs:
    def test_stores_args(self):
        bp = _make_processor(batch_size=4, num_workers=2, batch_save_size=10)
        assert bp.batch_size == 4
        assert bp.num_workers == 2
        assert bp.batch_save_size == 10

    def test_config_none_is_accepted(self):
        bp = _make_processor(config=None)
        assert bp.config is None


SUPPLEMENTARY_RESULT_KEYS = (
    "topiq_score",
    "aesthetic_iaa",
    "face_quality_iqa",
    "liqe_score",
    "subject_sharpness",
    "subject_prominence",
    "subject_placement",
    "bg_separation",
)


def _configure_scorer_mock(scorer):
    scorer.device = "cpu"
    scorer.tagger = None
    scorer.get_aesthetic_and_quality_batch.return_value = [(5.0, b"emb", None, "topiq")]
    scorer.tech_analyzer.get_sharpness_data.return_value = {"normalized": 5.0, "raw_variance": 1.0}
    scorer.tech_analyzer.get_color_harmony_data.return_value = {"normalized": 5.0, "raw_entropy": 1.0}
    scorer.tech_analyzer.get_histogram_data.return_value = {
        "exposure_score": 5.0, "spread": 1.0, "mean_luminance": 0.5, "bimodality": 0.0,
        "shadow_clipped": 0, "highlight_clipped": 0, "histogram_bytes": b"",
    }
    scorer.tech_analyzer.detect_monochrome.return_value = {"is_monochrome": 0, "mean_saturation": 0.5}
    scorer.tech_analyzer.get_dynamic_range.return_value = {"dynamic_range_stops": 8.0}
    scorer.tech_analyzer.get_noise_estimate.return_value = {"noise_sigma": 1.0}
    scorer.tech_analyzer.get_contrast_score.return_value = {"contrast_score": 5.0}
    scorer.config.get_monochrome_settings.return_value = {"saturation_threshold_percent": 10}
    scorer.config.version_hash = "v1"
    scorer.face_analyzer.analyze_faces.return_value = {
        "face_count": 0, "face_quality": 0.0, "eye_sharpness": 0.0, "face_sharpness": 0.0,
        "face_area": 0, "bbox": None, "face_details": [],
    }
    scorer.get_composition_scores.return_value = ("rule_of_thirds", None)
    scorer.calculate_aggregate_logic.return_value = (7.0, "landscape")


def test_process_batch_result_covers_supplementary_db_columns():
    import numpy as np
    from pathlib import Path
    from unittest import mock

    bp = _make_processor(batch_size=1)
    _configure_scorer_mock(bp.scorer)

    path = "/tmp/facet-test-photo.jpg"
    exif_keys = {
        "date_taken": None, "camera_model": None, "lens_model": None, "iso": None,
        "f_stop": None, "shutter_speed": None, "focal_length": None,
        "focal_length_35mm": None, "gps_latitude": None, "gps_longitude": None,
    }
    bp._exif_cache[str(Path(path).resolve())] = dict(exif_keys)

    item = {
        "path": path,
        "pil_img": mock.MagicMock(),
        "img_cv": np.zeros((10, 10, 3), dtype=np.uint8),
        "clip_input": None,
    }

    with mock.patch("processing.batch_processor.ImageCache"), \
         mock.patch("processing.batch_processor.CompositionAnalyzer") as comp, \
         mock.patch("processing.batch_processor.detect_silhouette", return_value=0), \
         mock.patch("processing.batch_processor.imagehash") as phash_mod:
        comp.get_placement_data.return_value = {"score": 5.0, "power_point_score": 1.0}
        comp.detect_leading_lines.return_value = {"leading_lines_score": 0}
        phash_mod.phash.return_value = "hash"
        bp._process_batch([item])

    queued = bp.result_queue.get_nowait()
    assert "result" in queued, queued
    res = queued["result"]
    for key in SUPPLEMENTARY_RESULT_KEYS:
        assert key in res, f"missing DB column {key} required by save_photos_batch INSERT"
        assert res[key] is None
