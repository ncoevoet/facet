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
from config_resolve import defaults_path  # noqa: E402
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

    def unload_model(self, name, reclaim=True):
        pass


class _StubScorer:
    def __init__(self, db_path):
        self.config = ScoringConfig(defaults_path())
        self.face_analyzer = object()
        self.saved = []
        self.db_path = db_path

    def calculate_aggregate_logic(self, metrics):
        return 7.5, "default"

    def save_photos_batch(self, batch):
        self.saved.extend(batch)

    def commit(self):
        pass


def _img_data():
    arr = np.zeros((64, 64, 3), dtype=np.uint8)
    return {
        "pil": Image.fromarray(arr), "height": 64, "width": 64,
        "phash": "0" * 16, "exif": {}, "sharpness": {}, "color": {},
        "histogram": {}, "mono": {}, "dynamic_range": {}, "noise": {},
        "contrast": {}, "form": {}, "cache": None, "thumbnail": b"thumb",
        # what _load_images now hoists into the worker for a non-restricted processor
        "composition": {"score": 7.0, "power_point_score": 5.0, "leading_lines_score": 0},
    }


@pytest.mark.timeout(30)
def test_required_pass_failure_records_and_excludes(tmp_path, monkeypatch):
    db_path = str(tmp_path / "scan.db")
    init_database(db_path)
    scan_run = ScanRun.start(db_path, "multi-pass", {"directories": []}, 2)

    scorer = _StubScorer(db_path)
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


@pytest.mark.timeout(30)
def test_required_model_load_failure_records_instead_of_aborting(tmp_path, monkeypatch):
    db_path = str(tmp_path / "scan.db")
    init_database(db_path)
    scan_run = ScanRun.start(db_path, "multi-pass", {"directories": []}, 2)

    scorer = _StubScorer(db_path)

    class _OomModelManager(_StubModelManager):
        def load_model_only(self, name):
            return None if name == "clip" else object()

    proc = ChunkedMultiPassProcessor(scorer, _OomModelManager(), {},
                                     on_error=scan_run.record_failure)
    proc.pass_groups = [["insightface"], ["clip"]]

    paths = [str(tmp_path / "a.jpg"), str(tmp_path / "b.jpg")]

    monkeypatch.setattr(proc, "_load_images", lambda p: {x: _img_data() for x in p})
    monkeypatch.setattr(proc, "_run_model_pass", lambda *a, **k: None)

    proc._process_chunk(paths, 0, 1)  # a real OOM surfaces as load returning None
    scan_run.finish("interrupted")

    # Load failure of a required model degrades to a retryable failure, never a
    # RuntimeError that aborts the whole scan, and never a neutral-default save.
    assert scorer.saved == []
    failed = set(get_failed_paths(db_path, "last"))
    assert failed == set(paths)


class _FaceStubScorer(_StubScorer):
    """Records the metrics the aggregate saw and every restricted save."""

    def __init__(self, db_path):
        super().__init__(db_path)
        self.metrics = []
        self.partial = []

    def calculate_aggregate_logic(self, metrics):
        self.metrics.append(dict(metrics))
        return 7.5, "default"

    def save_photos_partial(self, batch, refresh_faces):
        self.partial.extend(batch)


class _FaceAnalyzer:
    def __init__(self, fail):
        self.fail = fail

    def analyze_faces(self, img_cv):
        if self.fail:
            raise ValueError("simulated face failure")
        return {
            "face_count": 0, "face_quality": None, "eye_sharpness": None,
            "face_sharpness": None, "is_blink": None, "is_group_portrait": 0,
            "face_details": [], "face_area": 0,
        }


def _run_face_chunk(tmp_path, monkeypatch, fail, restricted=False):
    db_path = str(tmp_path / "scan.db")
    init_database(db_path)
    scorer = _FaceStubScorer(db_path)
    proc = ChunkedMultiPassProcessor(scorer, _StubModelManager(), {})
    proc.pass_groups = [["insightface"]]
    paths = [str(tmp_path / "a.jpg")]
    monkeypatch.setattr(proc, "_load_images", lambda p: {x: _img_data() for x in p})
    analyzer = _FaceAnalyzer(fail)
    monkeypatch.setattr(proc, "_run_model_pass",
                        lambda name, model, images, results: proc._pass_insightface(analyzer, images, results))
    if restricted:
        monkeypatch.setattr(proc, "_save_results", proc._save_results_restricted)
    proc._process_chunk(paths, 0, 1)
    return scorer


@pytest.mark.timeout(30)
def test_face_pass_exception_stores_unknown_not_no_face(tmp_path, monkeypatch):
    scorer = _run_face_chunk(tmp_path, monkeypatch, fail=True)
    row = scorer.saved[0]
    assert row["face_count"] is None
    assert row["face_ratio"] is None
    assert row["is_group_portrait"] is None
    assert row["face_details"] is None  # stored faces are kept


@pytest.mark.timeout(30)
def test_face_pass_exception_scores_exactly_like_a_zero_face_result(tmp_path, monkeypatch):
    failed = _run_face_chunk(tmp_path, monkeypatch, fail=True)
    clean = _run_face_chunk(tmp_path, monkeypatch, fail=False)
    for key in ("face_count", "face_ratio", "is_group_portrait"):
        assert failed.metrics[0][key] == clean.metrics[0][key] == 0
    assert failed.metrics[0] == clean.metrics[0]
    assert failed.saved[0]["aggregate"] == clean.saved[0]["aggregate"]
    assert failed.saved[0]["category"] == clean.saved[0]["category"]
    # The clean zero-face result is a real "no face" and stays 0.
    assert clean.saved[0]["face_count"] == 0


@pytest.mark.timeout(30)
def test_restricted_save_leaves_the_face_columns_out_after_a_failed_face_pass(tmp_path, monkeypatch):
    scorer = _run_face_chunk(tmp_path, monkeypatch, fail=True, restricted=True)
    res, _pil, columns = scorer.partial[0]
    for key in ("face_count", "face_ratio", "is_group_portrait", "face_quality", "is_blink",
                "isolation_bonus"):
        assert key not in columns
        assert key not in res
    assert "_face_failed" not in columns


@pytest.mark.timeout(30)
def test_restricted_save_writes_the_face_columns_when_the_pass_succeeds(tmp_path, monkeypatch):
    scorer = _run_face_chunk(tmp_path, monkeypatch, fail=False, restricted=True)
    _res, _pil, columns = scorer.partial[0]
    assert "face_count" in columns and "face_ratio" in columns


@pytest.mark.timeout(30)
def test_vlm_tagger_chunk_failure_records_and_excludes(tmp_path, monkeypatch):
    """The VLM tagger is a required pass, driven through _process_chunk: a
    failed tagging chunk lands in scan_failures (retryable via --retry-failed)
    and nothing is saved -- no photo is scored on an empty tag feature space
    and stamped complete."""
    db_path = str(tmp_path / "scan.db")
    init_database(db_path)
    scan_run = ScanRun.start(db_path, "multi-pass", {"directories": []}, 2)

    scorer = _StubScorer(db_path)
    proc = ChunkedMultiPassProcessor(scorer, _StubModelManager(), {},
                                     on_error=scan_run.record_failure)
    proc.pass_groups = [["vlm_tagger"]]

    paths = [str(tmp_path / "a.jpg"), str(tmp_path / "b.jpg")]

    monkeypatch.setattr(proc, "_load_images", lambda p: {x: _img_data() for x in p})

    class _Tagger:
        def tag_batch(self, pil_imgs, max_tags=None):
            raise RuntimeError("simulated VLM OOM")

    def fake_pass(model_name, model, images, results):
        if model_name == "vlm_tagger":
            proc._pass_vlm_tagger(_Tagger(), images, results)
        for path in images:
            results[path]["face_count"] = 0  # a prior pass populated real data

    monkeypatch.setattr(proc, "_run_model_pass", fake_pass)

    proc._process_chunk(paths, 0, 1)
    scan_run.finish("interrupted")  # flush buffered failures to the DB

    # No fabricated rows persisted (no aggregate from an empty tag space).
    assert scorer.saved == []

    # The chunk's photos are recorded and retryable via --retry-failed.
    failed = set(get_failed_paths(db_path, "last"))
    assert failed == set(paths)


@pytest.mark.timeout(30)
def test_vlm_tagger_one_bad_photo_fails_only_that_photo(tmp_path, monkeypatch):
    """tag_batch falls back per photo only on OOM, so one photo the model
    rejects fails the whole call. The pass retries photo by photo: only the
    bad photo is recorded and left unsaved, the rest of the chunk is tagged
    and saved -- otherwise the same chunk would fail on every --retry-failed."""
    db_path = str(tmp_path / "scan.db")
    init_database(db_path)
    scan_run = ScanRun.start(db_path, "multi-pass", {"directories": []}, 3)

    scorer = _StubScorer(db_path)
    proc = ChunkedMultiPassProcessor(scorer, _StubModelManager(), {},
                                     on_error=scan_run.record_failure)
    proc.pass_groups = [["vlm_tagger"]]

    paths = [str(tmp_path / n) for n in ("a.jpg", "bad.jpg", "c.jpg")]
    images = {x: _img_data() for x in paths}
    bad_pil = images[paths[1]]["pil"]
    monkeypatch.setattr(proc, "_load_images", lambda p: images)

    class _Tagger:
        def tag_batch(self, pil_imgs, max_tags=None):
            if any(img is bad_pil for img in pil_imgs):
                raise ValueError("image rejected by the processor")
            return [["dog"] for _ in pil_imgs]

    def fake_pass(model_name, model, imgs, results):
        if model_name == "vlm_tagger":
            proc._pass_vlm_tagger(_Tagger(), imgs, results)
        for path in imgs:
            results[path]["face_count"] = 0

    monkeypatch.setattr(proc, "_run_model_pass", fake_pass)

    proc._process_chunk(paths, 0, 1)
    scan_run.finish("interrupted")

    saved_paths = {row["path"] for row in scorer.saved}
    assert saved_paths == {paths[0], paths[2]}
    assert set(get_failed_paths(db_path, "last")) == {paths[1]}
