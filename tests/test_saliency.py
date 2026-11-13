"""Tests for the saliency overlay + face-marker endpoints (api/routers/saliency.py),
and for how ``models.saliency_scorer`` sizes its inference batch.

The BiRefNet model is stubbed via the model_cache loader, so the heatmap path
runs end-to-end (colourise + PNG encode) on CPU with no real weights. The batch
sizing tests stub it a second way, counting forward passes instead of computing
them, because what they assert is a memory decision rather than a mask.
"""

import io
import sqlite3
from contextlib import contextmanager
from unittest import mock

import numpy as np
import pytest
from PIL import Image

pytest.importorskip("torch")

import torch  # noqa: E402
import torchvision.transforms as T  # noqa: E402

from models.saliency_scorer import BYTES_PER_GB, SaliencyScorer  # noqa: E402
from utils import system_memory  # noqa: E402

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
        "bbox_x1 REAL, bbox_y1 REAL, bbox_x2 REAL, bbox_y2 REAL, landmark_2d_106 BLOB, eyes_open_score REAL);"
    )
    conn.execute(
        "INSERT INTO photos VALUES (?, ?, ?, ?)",
        ("/a.jpg", _thumb_bytes() if with_thumb else None, width, height),
    )
    for i, f in enumerate(faces or []):
        conn.execute(
            "INSERT INTO faces VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("/a.jpg", i, f["bbox"][0], f["bbox"][1], f["bbox"][2], f["bbox"][3], f["lm"],
             f.get("eyes_open")),
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
    device = "cpu"

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

    def test_sface_face_uses_the_stored_score_without_landmarks(self, http, tmp_path):
        db = _seed(tmp_path, faces=[{"bbox": [10, 20, 60, 120], "lm": None, "eyes_open": 2.0}])
        with mock.patch(f"{_MODULE}.get_db", _db_cm(db)):
            face = http.get("/api/photo/face_markers", params={"path": "/a.jpg"}).json()["faces"][0]
        assert face["eyes_open_score"] == 2.0
        assert face["is_blink"] is True
        assert face["eyes"] == []

    def test_arcface_face_prefers_the_stored_score_over_the_landmark_one(self, http, tmp_path):
        lm = (np.ones((106, 2), dtype=np.float32) * 10.0).tobytes()
        db = _seed(tmp_path, faces=[{"bbox": [10, 20, 60, 120], "lm": lm, "eyes_open": 8.0}])
        with mock.patch(f"{_MODULE}.get_db", _db_cm(db)):
            face = http.get("/api/photo/face_markers", params={"path": "/a.jpg"}).json()["faces"][0]
        assert face["eyes_open_score"] == 8.0
        assert face["is_blink"] is False
        assert len(face["eyes"]) == 2  # eye points still come from the landmarks

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


class _RecordingBiRefNet:
    """Stand-in for BiRefNet that records the size of every forward pass."""

    def __init__(self, resolution):
        self.batch_sizes = []
        self.resolution = resolution

    def parameters(self):
        yield torch.zeros(1)

    def __call__(self, batch_tensor):
        self.batch_sizes.append(batch_tensor.shape[0])
        return [torch.zeros(batch_tensor.shape[0], 1, self.resolution, self.resolution)]


def _stub_scorer(device="cpu", resolution=8):
    """A loaded SaliencyScorer whose forward passes are counted, not computed."""
    scorer = SaliencyScorer(device=device, resolution=resolution)
    scorer.model = _RecordingBiRefNet(resolution)
    scorer.transform = T.Compose([T.Resize((resolution, resolution)), T.ToTensor()])
    scorer._loaded = True
    return scorer


def _memory(available_gb, total_gb=8.0):
    used = total_gb - available_gb
    return system_memory.EffectiveMemory(
        int(total_gb * BYTES_PER_GB), int(used * BYTES_PER_GB),
        int(available_gb * BYTES_PER_GB), 100.0 * used / total_gb)


def _images(count):
    return [Image.new("RGB", (16, 12))] * count


def _fake_cuda_memory(monkeypatch, free_gb, reserved_gb=0.0, allocated_gb=0.0):
    """Stub the three torch.cuda readings the CUDA batch sizing consults.

    Returns the list of devices each was called with, so a test can assert the
    scorer's own device is passed rather than the current-device default.
    """
    calls = []

    def _gib(value):
        return int(value * BYTES_PER_GB)

    def mem_get_info(device=None):
        calls.append(("mem_get_info", device))
        return _gib(free_gb), _gib(16.0)

    def memory_reserved(device=None):
        calls.append(("memory_reserved", device))
        return _gib(reserved_gb)

    def memory_allocated(device=None):
        calls.append(("memory_allocated", device))
        return _gib(allocated_gb)

    monkeypatch.setattr(torch.cuda, "mem_get_info", mem_get_info)
    monkeypatch.setattr(torch.cuda, "memory_reserved", memory_reserved)
    monkeypatch.setattr(torch.cuda, "memory_allocated", memory_allocated)
    return calls


class TestCudaBatchSizing:
    """Issue #184: on CUDA the batch is sized from free VRAM, not the fixed ceiling.

    A 12 GB card capped to 11.7 GiB OOMs at batch 8 ("Tried to allocate 3.75 GiB")
    while batch 2 passes; the marginal cost is ~2.4 GiB of reserved memory per image.
    """

    def test_roomy_card_keeps_the_ceiling(self, monkeypatch):
        _fake_cuda_memory(monkeypatch, free_gb=24.0)
        assert _stub_scorer(device="cuda")._affordable_batch_size(None) == 8

    def test_sixteen_gib_free_affords_five(self, monkeypatch):
        _fake_cuda_memory(monkeypatch, free_gb=16.0)
        assert _stub_scorer(device="cuda")._affordable_batch_size(None) == 5  # int(16*0.8/2.4)

    def test_nine_gib_free_affords_three(self, monkeypatch):
        _fake_cuda_memory(monkeypatch, free_gb=9.0)
        assert _stub_scorer(device="cuda")._affordable_batch_size(None) == 3

    def test_starved_card_floors_at_the_minimum(self, monkeypatch):
        _fake_cuda_memory(monkeypatch, free_gb=1.0)
        assert _stub_scorer(device="cuda")._affordable_batch_size(None) == SaliencyScorer.MIN_BATCH_SIZE

    def test_explicit_request_stays_a_ceiling(self, monkeypatch):
        _fake_cuda_memory(monkeypatch, free_gb=24.0)
        scorer = _stub_scorer(device="cuda")
        assert scorer._affordable_batch_size(2) == 2
        _fake_cuda_memory(monkeypatch, free_gb=9.0)
        assert scorer._affordable_batch_size(8) == 3

    def test_reusable_torch_cache_counts_as_free(self, monkeypatch):
        """Reserved-but-unallocated memory is reusable by the next forward pass."""
        _fake_cuda_memory(monkeypatch, free_gb=6.0, reserved_gb=5.0, allocated_gb=2.0)
        # 6 + (5 - 2) = 9 GiB -> 3
        assert _stub_scorer(device="cuda")._affordable_batch_size(None) == 3

    def test_higher_resolution_lowers_the_batch(self, monkeypatch):
        _fake_cuda_memory(monkeypatch, free_gb=16.0)
        # per image 2.4 * (1536/1024)**2 = 5.4 GiB -> int(12.8/5.4) == 2
        assert _stub_scorer(device="cuda", resolution=1536)._affordable_batch_size(None) == 2

    def test_lower_resolution_never_prices_below_the_measured_figure(self, monkeypatch):
        _fake_cuda_memory(monkeypatch, free_gb=9.0)
        assert _stub_scorer(device="cuda", resolution=512)._affordable_batch_size(None) == 3

    def test_every_reading_names_the_scorers_own_device(self, monkeypatch):
        calls = _fake_cuda_memory(monkeypatch, free_gb=16.0)
        _stub_scorer(device="cuda:1")._affordable_batch_size(None)
        assert {name for name, _ in calls} == {"mem_get_info", "memory_reserved", "memory_allocated"}
        assert all(device == "cuda:1" for _, device in calls)

    def test_unreadable_vram_falls_back_to_the_ceiling_with_one_warning(self, monkeypatch, caplog):
        def boom(device=None):
            raise RuntimeError("driver gone")

        monkeypatch.setattr(torch.cuda, "mem_get_info", boom)
        scorer = _stub_scorer(device="cuda")
        with caplog.at_level("WARNING", logger="facet.saliency"):
            assert scorer._affordable_batch_size(None) == SaliencyScorer.DEFAULT_BATCH_SIZE
            assert scorer._affordable_batch_size(None) == SaliencyScorer.DEFAULT_BATCH_SIZE
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warnings) == 1

    def test_planner_figure_matches_the_class_property(self):
        assert _stub_scorer().vram_gb == 3


class TestBatchSizing:
    """Issue #111: the batch must be sized against the memory it lands in.

    BiRefNet's weights are 0.36 GB, but one image at the default 1024x1024
    costs about 2.4 GB of activations on CPU, so the hardcoded batch of 8 asked
    for roughly 18 GB whatever the container had -- and an 8 GiB one was
    OOM-killed in this pass however carefully the planner, which prices
    declared model weight, had sized it.
    """

    def test_cpu_batch_shrinks_to_the_container_budget(self, monkeypatch):
        """6.7 GB free is an 8 GiB container with a chunk already decoded."""
        scorer = _stub_scorer()
        monkeypatch.setattr(system_memory, "effective_memory", lambda: _memory(6.7))
        scorer.get_saliency_masks(_images(6))
        assert scorer.model.batch_sizes == [2, 2, 2]

    def test_roomy_host_keeps_the_default_batch(self, monkeypatch):
        """The bound only ever narrows: 32 GB free affords more than 8, so 8 it is."""
        scorer = _stub_scorer()
        monkeypatch.setattr(system_memory, "effective_memory",
                            lambda: _memory(32.0, total_gb=48.0))
        scorer.get_saliency_masks(_images(10))
        assert scorer.model.batch_sizes == [8, 2]

    def test_explicit_batch_size_is_a_ceiling_not_a_floor(self, monkeypatch):
        """A caller may narrow the batch; it may not widen it past the budget.

        The defect was a number that ignored memory, so letting an argument
        reinstate one would leave the same hole open through every call site.
        """
        starved = _stub_scorer()
        monkeypatch.setattr(system_memory, "effective_memory", lambda: _memory(6.7))
        starved.get_saliency_masks(_images(4), batch_size=8)
        assert starved.model.batch_sizes == [2, 2]

        roomy = _stub_scorer()
        monkeypatch.setattr(system_memory, "effective_memory",
                            lambda: _memory(32.0, total_gb=48.0))
        roomy.get_saliency_masks(_images(4), batch_size=3)
        assert roomy.model.batch_sizes == [3, 1]

    def test_unreadable_memory_is_not_headroom(self, monkeypatch):
        """UNKNOWN_MEMORY reports nothing available, so the batch is the minimum."""
        scorer = _stub_scorer()
        monkeypatch.setattr(system_memory, "effective_memory",
                            lambda: system_memory.UNKNOWN_MEMORY)
        scorer.get_saliency_masks(_images(2))
        assert scorer.model.batch_sizes == [1, 1]

    def test_cuda_batch_ignores_host_memory(self, monkeypatch):
        """Activations live in VRAM there, which no cgroup limit governs: host RAM is not read.

        Asserted on the sizing decision rather than through a forward pass:
        running one would need a real CUDA device, which is exactly the
        environment this regression must not depend on.
        """
        scorer = _stub_scorer(device="cuda")
        _fake_cuda_memory(monkeypatch, free_gb=24.0)
        monkeypatch.setattr(system_memory, "effective_memory", lambda: _memory(0.1))
        assert scorer._affordable_batch_size(None) == SaliencyScorer.DEFAULT_BATCH_SIZE

    def test_usable_memory_fraction_narrows_the_affordable_batch(self, monkeypatch):
        """12.0 GB available straddles the 80% margin: claiming all of it
        would afford a batch of 5 (12 // 2.4), claiming the fifth-held-back
        fraction affords 4 (12 * 0.8 // 2.4 == 9.6 // 2.4 == 4). The two
        disagree, which is what proves USABLE_MEMORY_FRACTION is read at all
        -- every other value in this class floors to the same batch either
        way and would stay green with the margin deleted.
        """
        scorer = _stub_scorer()
        monkeypatch.setattr(system_memory, "effective_memory",
                            lambda: _memory(12.0, total_gb=16.0))
        scorer.get_saliency_masks(_images(5))
        assert scorer.model.batch_sizes == [4, 1]

    def test_mps_batch_is_capped_regardless_of_available_memory(self, monkeypatch):
        """Discussion #159: psutil's "available" reading cannot see the MPS
        allocator pool, so a Mac reporting plenty of free RAM must not be
        trusted the way a CPU container is -- the ceiling is a small fixed
        constant instead of a memory-derived one.

        Asserted on the sizing decision rather than through a forward pass:
        this CPU-only torch build cannot allocate a real 'mps' tensor, which
        is exactly the environment this regression must not depend on.
        """
        scorer = _stub_scorer(device="mps")
        monkeypatch.setattr(system_memory, "effective_memory",
                            lambda: _memory(1000.0, total_gb=1024.0))
        assert scorer._affordable_batch_size(None) == SaliencyScorer.UNIFIED_MEMORY_MAX_BATCH

    def test_mps_explicit_request_is_still_capped(self, monkeypatch):
        """An explicit batch_size may only narrow, never widen, the MPS ceiling."""
        scorer = _stub_scorer(device="mps")
        monkeypatch.setattr(system_memory, "effective_memory",
                            lambda: _memory(1000.0, total_gb=1024.0))
        assert scorer._affordable_batch_size(8) == SaliencyScorer.UNIFIED_MEMORY_MAX_BATCH

    def test_mps_cap_never_widens_a_tight_memory_budget(self, monkeypatch):
        """The MPS ceiling narrows the RAM-derived size; it never replaces it."""
        scorer = _stub_scorer(device="mps")
        monkeypatch.setattr(system_memory, "effective_memory",
                            lambda: _memory(2.0, total_gb=8.0))
        assert scorer._affordable_batch_size(None) == SaliencyScorer.MIN_BATCH_SIZE

    def test_cpu_and_cuda_batch_sizing_unaffected_by_mps_cap(self, monkeypatch):
        """The MPS cap must not leak into CPU or CUDA sizing."""
        cpu_scorer = _stub_scorer(device="cpu")
        monkeypatch.setattr(system_memory, "effective_memory",
                            lambda: _memory(32.0, total_gb=48.0))
        cpu_scorer.get_saliency_masks(_images(10))
        assert cpu_scorer.model.batch_sizes == [8, 2]

        cuda_scorer = _stub_scorer(device="cuda")
        _fake_cuda_memory(monkeypatch, free_gb=24.0)
        monkeypatch.setattr(system_memory, "effective_memory", lambda: _memory(0.1))
        assert cuda_scorer._affordable_batch_size(None) == SaliencyScorer.DEFAULT_BATCH_SIZE


class TestLoadPrecision:
    """Commit 4ef53d3: the published checkpoint is stored fp16, and CPU/MPS
    have no fp16 kernel path -- a 256x256 forward measured 49.97s in fp16
    against 1.10s in float32, and a single 1024x1024 forward ran 28 minutes.
    ``load()`` must upcast off a dedicated GPU and leave CUDA at its
    checkpoint precision.
    """

    def test_load_casts_to_float32_off_a_dedicated_gpu(self):
        fake_model = mock.MagicMock(name="birefnet")
        with mock.patch(
            "transformers.AutoModelForImageSegmentation.from_pretrained",
            return_value=fake_model,
        ):
            scorer = SaliencyScorer(device="cpu")
            scorer.load()
        fake_model.float.assert_called_once()

    def test_load_leaves_cuda_at_checkpoint_precision(self):
        fake_model = mock.MagicMock(name="birefnet")
        with mock.patch(
            "transformers.AutoModelForImageSegmentation.from_pretrained",
            return_value=fake_model,
        ):
            scorer = SaliencyScorer(device="cuda")
            scorer.load()
        fake_model.float.assert_not_called()

    def test_load_leaves_mps_at_checkpoint_precision(self):
        """Float32 BiRefNet on MPS went from 0.9 s to 9 s a photo past batch 1 (M4 Pro);
        fp16 held 0.7-0.9 s. Linux CI cannot notice the upcast coming back."""
        fake_model = mock.MagicMock(name="birefnet")
        with mock.patch(
            "transformers.AutoModelForImageSegmentation.from_pretrained",
            return_value=fake_model,
        ):
            scorer = SaliencyScorer(device="mps")
            scorer.load()
        fake_model.float.assert_not_called()


class _OomBiRefNet(_RecordingBiRefNet):
    """BiRefNet stand-in that raises OOM by rule: any batch over ``max_ok``, or an image tagged ``poison``.

    An image is identified by its first pixel value, which ``_tagged_images`` sets
    to its index, so the rule can follow one photo through a split.
    """

    def __init__(self, resolution, max_ok=None, poison=(), exc=None):
        super().__init__(resolution)
        self.max_ok = max_ok
        self.poison = set(poison)
        self.exc = exc

    def __call__(self, batch_tensor):
        n = batch_tensor.shape[0]
        self.batch_sizes.append(n)
        ids = {round(float(batch_tensor[i].flatten()[0]) * 255) for i in range(n)}
        if (self.max_ok is not None and n > self.max_ok) or ids & self.poison:
            raise self.exc if self.exc is not None else torch.cuda.OutOfMemoryError(
                "CUDA out of memory. Tried to allocate 3.75 GiB")
        # Each image's mask marks the whole frame so order is checkable: pixel value == index.
        out = torch.zeros(n, 1, self.resolution, self.resolution)
        for i in range(n):
            out[i] += 10.0 if round(float(batch_tensor[i].flatten()[0]) * 255) % 2 else -10.0
        return [out]


def _tagged_images(count):
    return [Image.new("RGB", (16, 12), (i, i, i)) for i in range(count)]


def _oom_scorer(**kwargs):
    scorer = _stub_scorer()
    scorer.model = _OomBiRefNet(8, **kwargs)
    return scorer


def _fixed_batch(scorer, size):
    scorer._affordable_batch_size = lambda requested: size
    return scorer


class TestOomRetry:
    """Issue #184: a CUDA OOM halves the sub-batch instead of failing the whole call."""

    def test_oom_halves_the_chunk_and_keeps_every_mask_in_order(self):
        scorer = _fixed_batch(_oom_scorer(max_ok=2), 4)
        masks = scorer.get_saliency_masks(_tagged_images(4))
        assert scorer.model.batch_sizes == [4, 2, 2]
        assert len(masks) == 4
        # odd-indexed images were rendered as full-frame masks, even ones as empty
        assert [bool(m.any()) for m in masks] == [False, True, False, True]

    def test_oom_at_every_size_marks_every_image_failed_and_logs_the_batch_size(self, caplog):
        scorer = _fixed_batch(_oom_scorer(max_ok=0), 4)
        imgs = _tagged_images(4)
        cv = [np.zeros((12, 16, 3), dtype=np.uint8)] * 4
        with caplog.at_level("WARNING", logger="facet.saliency"):
            results = scorer.score_batch(imgs, cv)
        assert len(results) == 4
        for r in results:
            assert r == {'subject_sharpness': None, 'subject_prominence': None,
                         'subject_placement': None, 'bg_separation': None, 'subject_bbox': None}
        errors = [r for r in caplog.records if r.levelname == "ERROR"]
        assert errors and any("4" in r.getMessage() for r in errors)

    def test_mixed_batch_fails_only_the_image_that_cannot_fit_alone(self):
        # Batches over 1 OOM, and image 2 OOMs even alone.
        scorer = _fixed_batch(_oom_scorer(max_ok=1, poison={2}), 4)
        imgs = _tagged_images(4)
        masks = scorer.get_saliency_masks(imgs)
        assert [m is None for m in masks] == [False, False, True, False]
        cv = [np.full((12, 16, 3), 200, dtype=np.uint8)] * 4
        scorer2 = _fixed_batch(_oom_scorer(max_ok=1, poison={2}), 4)
        results = scorer2.score_batch(imgs, cv)
        failed = [all(v is None for v in r.values()) for r in results]
        assert failed == [False, False, True, False]

    def test_score_image_returns_the_failure_dict_when_the_mask_is_none(self):
        scorer = _fixed_batch(_oom_scorer(max_ok=0), 4)
        img = Image.new("RGB", (16, 12), (255, 255, 255))
        result = scorer.score_image(img, np.zeros((12, 16, 3), dtype=np.uint8))
        assert result == {'subject_sharpness': None, 'subject_prominence': None,
                          'subject_placement': None, 'bg_separation': None, 'subject_bbox': None}

    def test_non_oom_error_is_not_retried(self):
        scorer = _fixed_batch(_oom_scorer(max_ok=0, exc=ValueError("bad tensor")), 4)
        with pytest.raises(ValueError):
            scorer.get_saliency_masks(_tagged_images(4))
        assert scorer.model.batch_sizes == [4]

    def test_non_oom_error_in_score_batch_fails_every_photo(self, caplog):
        scorer = _fixed_batch(_oom_scorer(max_ok=0, exc=ValueError("bad tensor")), 4)
        cv = [np.zeros((12, 16, 3), dtype=np.uint8)] * 4
        with caplog.at_level("ERROR", logger="facet.saliency"):
            results = scorer.score_batch(_tagged_images(4), cv)
        assert all(all(v is None for v in r.values()) for r in results)
        assert any("batch size 4" in r.getMessage() for r in caplog.records)

    def test_reduction_warning_omits_the_exception_text(self, caplog):
        scorer = _fixed_batch(_oom_scorer(max_ok=2), 4)
        with caplog.at_level("WARNING", logger="facet.saliency"):
            scorer.get_saliency_masks(_tagged_images(4))
        warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
        assert len(warnings) == 1
        assert "reduced" in warnings[0]
        assert "Tried to allocate" not in warnings[0] and "out of memory" not in warnings[0].lower()

    def test_cache_is_released_outside_the_handler(self, monkeypatch):
        """empty_cache must run after the except block, or the traceback pins the activations."""
        import sys
        seen = []

        def fake_clear(device=None):
            seen.append(sys.exc_info()[1])

        monkeypatch.setattr("utils.device.clear_device_cache", fake_clear)
        scorer = _fixed_batch(_oom_scorer(max_ok=2), 4)
        scorer.get_saliency_masks(_tagged_images(4))
        assert seen and all(exc is None for exc in seen)

    def test_empty_mask_stays_a_successful_no_subject_result(self):
        scorer = _fixed_batch(_oom_scorer(), 4)
        imgs = [Image.new("RGB", (16, 12), (0, 0, 0))]  # even id -> empty mask
        result = scorer.score_batch(imgs, [np.zeros((12, 16, 3), dtype=np.uint8)])[0]
        # no subject: three metrics have no value, prominence 0.0 is a real measurement
        assert result['subject_sharpness'] is None and result['subject_bbox'] is None
        assert result['subject_prominence'] == 0.0
