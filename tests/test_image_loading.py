"""Tests for RAW decode concurrency, timeout, and the parallel chunk loader."""

import sqlite3
import sys
import threading
import time
import types
from unittest import mock

import numpy as np
import pytest
from PIL import Image

from utils import image_loading
from utils.image_loading import configure_raw_decoding, load_image_from_path


@pytest.fixture(autouse=True)
def _reset_decode_state():
    """Restore module decode state after each test."""
    yield
    image_loading._abandoned_decodes = 0
    configure_raw_decoding(concurrency=image_loading._auto_decode_concurrency(),
                           timeout_seconds=0)


def _make_jpegs(tmp_path, count=3):
    paths = []
    for i in range(count):
        arr = np.full((32, 48, 3), i * 60 + 20, dtype=np.uint8)
        arr[:, : (i + 1) * 10] = 255 - i * 40
        p = tmp_path / f"img_{i}.jpg"
        Image.fromarray(arr).save(p, quality=95)
        paths.append(str(p))
    return paths


class TestConfigureRawDecoding:
    def test_concurrency_one_serializes(self):
        configure_raw_decoding(concurrency=1)
        assert image_loading._raw_semaphore._value == 1

    def test_auto_value_bounded(self):
        n = image_loading._auto_decode_concurrency()
        assert 1 <= n <= 4

    def test_zero_keeps_current_concurrency(self):
        configure_raw_decoding(concurrency=3)
        configure_raw_decoding(concurrency=0, timeout_seconds=5)
        assert image_loading._decode_concurrency == 3
        assert image_loading._decode_timeout == 5.0


class TestJpegLoading:
    def test_jpeg_loads_without_semaphore(self, tmp_path):
        path = _make_jpegs(tmp_path, 1)[0]
        pil_img, img_cv = load_image_from_path(path)
        assert pil_img is not None
        assert img_cv.shape == (32, 48, 3)

    def test_missing_file_returns_none_tuple(self, tmp_path):
        pil_img, img_cv = load_image_from_path(str(tmp_path / "nope.jpg"))
        assert pil_img is None and img_cv is None

    def test_concurrent_jpeg_loads_match_sequential(self, tmp_path):
        paths = _make_jpegs(tmp_path, 4)
        reference = {p: load_image_from_path(p)[1] for p in paths}
        results = {}
        errors = []

        def _load(p):
            try:
                results[p] = load_image_from_path(p)[1]
            except Exception as e:  # pragma: no cover
                errors.append(e)

        threads = [threading.Thread(target=_load, args=(p,)) for p in paths]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors
        for p in paths:
            assert np.array_equal(results[p], reference[p])


class _StubRaw:
    """rawpy.imread() stand-in whose postprocess sleeps then returns pixels."""

    def __init__(self, delay):
        self.delay = delay

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_thumb(self):
        raise RuntimeError("no thumb")

    def postprocess(self, **kwargs):
        time.sleep(self.delay)
        return np.zeros((4, 4, 3), dtype=np.uint8)


def _stub_rawpy(delay):
    stub = types.ModuleType("rawpy")
    stub.imread = lambda path: _StubRaw(delay)
    stub.ThumbFormat = types.SimpleNamespace(JPEG="jpeg")
    stub.ColorSpace = types.SimpleNamespace(sRGB="srgb")
    return stub


class TestDecodeTimeout:
    def test_timeout_returns_none_tuple(self, tmp_path, monkeypatch):
        raw_path = tmp_path / "slow.dng"
        raw_path.write_bytes(b"fake")
        monkeypatch.setitem(sys.modules, "rawpy", _stub_rawpy(delay=1.5))
        image_loading._abandoned_decodes = 0
        configure_raw_decoding(concurrency=2, timeout_seconds=0.2)

        start = time.time()
        pil_img, img_cv = load_image_from_path(str(raw_path))
        elapsed = time.time() - start

        assert pil_img is None and img_cv is None
        assert elapsed < 1.0
        assert image_loading._abandoned_decodes == 1

    def test_budget_exhaustion_raises(self, tmp_path, monkeypatch):
        raw_path = tmp_path / "slow.nef"
        raw_path.write_bytes(b"fake")
        monkeypatch.setitem(sys.modules, "rawpy", _stub_rawpy(delay=1.5))
        image_loading._abandoned_decodes = 0
        configure_raw_decoding(concurrency=2, timeout_seconds=0.1)

        for _ in range(image_loading._ABANDON_BUDGET):
            assert load_image_from_path(str(raw_path)) == (None, None)
        with pytest.raises(RuntimeError, match="storage likely stalled"):
            load_image_from_path(str(raw_path))

    def test_queue_wait_excluded_from_timeout(self, tmp_path, monkeypatch):
        raw_path = tmp_path / "queued.cr2"
        raw_path.write_bytes(b"fake")
        monkeypatch.setitem(sys.modules, "rawpy", _stub_rawpy(delay=0.3))
        image_loading._abandoned_decodes = 0
        configure_raw_decoding(concurrency=1, timeout_seconds=0.5)

        results = {}

        def _load(key):
            results[key] = load_image_from_path(str(raw_path))

        threads = [threading.Thread(target=_load, args=(k,)) for k in ("a", "b")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert results["a"][0] is not None and results["b"][0] is not None
        assert image_loading._abandoned_decodes == 0

    def test_fast_decode_succeeds_within_timeout(self, tmp_path, monkeypatch):
        raw_path = tmp_path / "fast.arw"
        raw_path.write_bytes(b"fake")
        monkeypatch.setitem(sys.modules, "rawpy", _stub_rawpy(delay=0.0))
        configure_raw_decoding(concurrency=2, timeout_seconds=5)

        pil_img, img_cv = load_image_from_path(str(raw_path))
        assert pil_img is not None
        assert img_cv.shape == (4, 4, 3)


class TestMultiPassParallelLoader:
    def _make_processor(self, load_workers):
        # The parallel loader itself is torch-free, but constructing the
        # processor runs multi_pass._ensure_imports(), which eagerly imports
        # torch. CI installs no torch, so skip there; runs locally where torch
        # is present.
        pytest.importorskip("torch")
        from processing.multi_pass import ChunkedMultiPassProcessor
        scorer = mock.MagicMock()
        scorer.config.get_exposure_settings.return_value = {}
        scorer.config.get_monochrome_settings.return_value = {}
        scorer.get_exif_data.return_value = {"iso": 100}
        model_manager = mock.MagicMock()
        model_manager.detect_vram.return_value = 0
        config = {"processing": {"load_workers": load_workers}}
        return ChunkedMultiPassProcessor(scorer, model_manager, config)

    def test_parallel_output_matches_sequential(self, tmp_path):
        paths = _make_jpegs(tmp_path, 4)
        sequential = self._make_processor(1)._load_images(paths)
        parallel = self._make_processor(4)._load_images(paths)

        assert list(parallel.keys()) == list(sequential.keys()) == paths
        for path in paths:
            assert parallel[path]["phash"] == sequential[path]["phash"]
            assert parallel[path]["exif"] is not None
            assert (
                parallel[path]["sharpness"]["raw_variance"]
                == sequential[path]["sharpness"]["raw_variance"]
            )

    def test_failed_image_skipped(self, tmp_path):
        paths = _make_jpegs(tmp_path, 2)
        bad = str(tmp_path / "corrupt.jpg")
        with open(bad, "wb") as f:
            f.write(b"not an image")
        images = self._make_processor(4)._load_images(paths + [bad])
        assert set(images.keys()) == set(paths)

    def test_load_workers_capped_at_eight(self):
        processor = self._make_processor(32)
        assert processor.load_workers == 8


class TestFilterUnscannedPaths:
    @pytest.fixture()
    def scorer_db(self, tmp_path):
        from db.schema import init_database
        from processing.scorer import Facet
        db_path = str(tmp_path / "scan.db")
        init_database(db_path)
        conn = sqlite3.connect(db_path)
        conn.executemany(
            "INSERT INTO photos (path, filename) VALUES (?, ?)",
            [(f"/lib/p{i}.jpg", f"p{i}.jpg") for i in range(25)],
        )
        conn.commit()
        conn.close()
        return Facet(db_path=db_path, lightweight=True)

    def test_filters_known_paths(self, scorer_db):
        candidates = [f"/lib/p{i}.jpg" for i in range(20)] + ["/new/a.jpg", "/new/b.jpg"]
        result = scorer_db.filter_unscanned_paths(candidates)
        assert result == {"/new/a.jpg", "/new/b.jpg"}

    def test_chunk_boundaries(self, scorer_db):
        candidates = [f"/lib/p{i}.jpg" for i in range(25)] + ["/new/x.jpg"]
        result = scorer_db.filter_unscanned_paths(candidates, chunk=10)
        assert result == {"/new/x.jpg"}

    def test_empty_input(self, scorer_db):
        assert scorer_db.filter_unscanned_paths([]) == set()

    def test_all_new(self, scorer_db):
        candidates = ["/other/1.jpg", "/other/2.jpg"]
        assert scorer_db.filter_unscanned_paths(candidates, chunk=1) == set(candidates)


class TestExifPrefetch:
    def _make_processor(self):
        from processing.batch_processor import BatchProcessor
        scorer = mock.MagicMock()
        return BatchProcessor(scorer, batch_size=4, num_workers=2)

    def test_cache_hit_avoids_sync_fetch(self, monkeypatch):
        import exiftool
        processor = self._make_processor()
        from pathlib import Path
        resolved = str(Path("/x/a.jpg").resolve())
        processor._exif_cache[resolved] = {"iso": 200}
        sync_calls = []
        monkeypatch.setattr(
            exiftool, "get_exif_batch",
            lambda paths, **kw: sync_calls.append(paths) or {},
        )
        result = processor._get_batch_exif(["/x/a.jpg"])
        assert result[resolved] == {"iso": 200}
        assert sync_calls == []
        assert processor._exif_cache == {}

    def test_miss_falls_back_to_sync_fetch(self, monkeypatch):
        import exiftool
        processor = self._make_processor()
        from pathlib import Path
        resolved = str(Path("/x/b.jpg").resolve())
        monkeypatch.setattr(
            exiftool, "get_exif_batch",
            lambda paths, **kw: {resolved: {"iso": 400}},
        )
        result = processor._get_batch_exif(["/x/b.jpg"])
        assert result[resolved] == {"iso": 400}

    def test_prefetch_thread_fills_cache(self, monkeypatch):
        import exiftool
        processor = self._make_processor()
        from pathlib import Path
        resolved = str(Path("/x/c.jpg").resolve())
        monkeypatch.setattr(
            exiftool, "get_exif_batch",
            lambda paths, **kw: {resolved: {"iso": 800}},
        )
        processor._start_exif_prefetch(["/x/c.jpg"])
        processor._exif_prefetch_thread.join(timeout=5)
        assert processor._exif_cache[resolved] == {"iso": 800}

    def test_prefetch_disabled_is_noop(self):
        processor = self._make_processor()
        processor.exif_prefetch_enabled = False
        processor._start_exif_prefetch(["/x/d.jpg"])
        assert processor._exif_prefetch_thread is None
