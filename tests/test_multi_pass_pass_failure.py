"""F28 regression: a required model pass failing on a chunk must not fabricate.

Before the fix, a pass exception (e.g. transient CUDA OOM) dropped that model's
outputs for the whole chunk, yet ``_save_results`` still wrote neutral defaults
(aesthetic=5.0 ...) and stamped the photos scanned-complete, while ``on_error``
was never called. ``--resume`` then treated them as done. The fix records the
affected photos in scan_failures (retryable via ``--retry-failed``) and excludes
them from the save.
"""

import numpy as np
import pytest
from PIL import Image

torch = pytest.importorskip("torch")
pytest.importorskip("cv2")

from config import ScoringConfig  # noqa: E402
from db.schema import init_database  # noqa: E402
from processing.multi_pass import ChunkedMultiPassProcessor  # noqa: E402
from processing.scan_state import ScanRun, get_failed_paths  # noqa: E402


class _StubModelManager:
    def detect_vram(self):
        return 0.0

    def get_active_profile(self):
        return {"supplementary_pyiqa": []}

    def load_model_only(self, name):
        return object()

    def unload_model(self, name):
        pass


class _StubScorer:
    def __init__(self):
        self.config = ScoringConfig("scoring_config.json")
        self.face_analyzer = object()
        self.saved = []

    def calculate_aggregate_logic(self, metrics):
        return 7.5, "default"

    def save_photos_batch(self, batch):
        self.saved.extend(batch)

    def commit(self):
        pass


def _img_data():
    arr = np.zeros((64, 64, 3), dtype=np.uint8)
    return {
        "pil": Image.fromarray(arr), "cv": arr, "height": 64, "width": 64,
        "phash": "0" * 16, "exif": {}, "sharpness": {}, "color": {},
        "histogram": {}, "mono": {}, "dynamic_range": {}, "noise": {},
        "contrast": {}, "form": {}, "cache": None,
    }


@pytest.mark.timeout(30)
def test_required_pass_failure_records_and_excludes(tmp_path, monkeypatch):
    db_path = str(tmp_path / "scan.db")
    init_database(db_path)
    scan_run = ScanRun.start(db_path, "multi-pass", {"directories": []}, 2)

    scorer = _StubScorer()
    proc = ChunkedMultiPassProcessor(scorer, _StubModelManager(), {},
                                     on_error=scan_run.record_failure)
    proc.pass_groups = [["insightface"], ["clip"]]

    paths = [str(tmp_path / "a.jpg"), str(tmp_path / "b.jpg")]

    monkeypatch.setattr(proc, "_load_images", lambda p: {x: _img_data() for x in p})

    def fake_pass(model_name, model, images, results):
        if model_name == "clip":
            raise torch.cuda.OutOfMemoryError("simulated OOM")
        for path in images:
            results[path]["face_count"] = 0  # a prior pass populated real data

    monkeypatch.setattr(proc, "_run_model_pass", fake_pass)

    proc._process_chunk(paths, 0, 1)
    scan_run.finish("interrupted")  # flush buffered failures to the DB

    # No fabricated rows persisted (no aesthetic=5.0 defaults, no scanned stamp).
    assert scorer.saved == []

    # The chunk's photos are recorded and retryable via --retry-failed.
    failed = set(get_failed_paths(db_path, "last"))
    assert failed == set(paths)
