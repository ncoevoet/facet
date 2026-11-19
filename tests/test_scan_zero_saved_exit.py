"""A scan that saved nothing out of N > 0 inputs must not exit 0.

Phase A found a 16gb scan under a 16 GB job cap that failed every required model load,
saved 0 photos and still exited rc=0. A legitimately empty scan (no inputs, or every file
already scanned) still exits 0.
"""

import os
import sys

import pytest
from PIL import Image

import facet
from config import ScoringConfig
from utils.exit_codes import SCAN_DID_NOT_RUN_EXIT_CODE
from db.schema import init_database


class _FakeFacet:
    def __init__(self, db_path=None, config_path=None, multi_pass=False):
        self.db_path = db_path
        self.config = ScoringConfig(config_path)
        self.model_manager = None
        self.already_scanned = False

    def filter_unscanned_paths(self, paths):
        return set() if self.already_scanned else set(paths)

    def preflight_models(self):
        pass

    def flush_person_centroids(self):
        pass

    def commit(self):
        pass


def _processor(saved):
    class _Processor:
        def __init__(self, *args, **kwargs):
            self.metrics = {'images_processed': 1, 'photos_saved': saved}

        def process_directory(self, paths):
            return self.metrics
    return _Processor


def _run(tmp_path, monkeypatch, processor, already_scanned=False, extra_args=(),
         photo_dir_exists=True, more_paths=()):
    db_path = str(tmp_path / "scan.db")
    init_database(db_path)
    photo_dir = tmp_path / "photos"
    if photo_dir_exists:
        photo_dir.mkdir()
        Image.new("RGB", (8, 8), (120, 120, 120)).save(photo_dir / "a.jpg", "JPEG")

    class Facet(_FakeFacet):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.already_scanned = already_scanned

    monkeypatch.setattr("processing.scorer.Facet", Facet)
    monkeypatch.setattr("processing.multi_pass.ChunkedMultiPassProcessor", processor)
    monkeypatch.setattr("models.model_manager.ModelManager", lambda *a, **k: object())
    monkeypatch.setattr("plugins.init_global_plugin_manager", lambda *a, **k: None)
    monkeypatch.setattr("processing.scorer.process_bursts", lambda *a, **k: None)
    monkeypatch.setattr("tag_existing.run_tagging", lambda *a, **k: 0)
    monkeypatch.setattr("tag_existing.resolve_scan_tagger", lambda *a, **k: None)
    monkeypatch.setattr("db.vec.populate_vec_table", lambda *a, **k: None)
    monkeypatch.setattr(facet, "detect_all_sequences", lambda *a, **k: None)
    monkeypatch.setattr(facet, "run_moment_detection", lambda *a, **k: {})
    monkeypatch.setattr(facet, "run_junk_detection", lambda *a, **k: {})
    monkeypatch.setattr(facet, "_print_scan_summary", lambda *a, **k: None)
    monkeypatch.setattr(sys, "argv",
                        ["facet.py", str(photo_dir), *[str(p) for p in more_paths],
                         "--db", db_path, *extra_args])
    facet.main()


@pytest.mark.timeout(30)
def test_zero_saved_of_n_inputs_exits_non_zero_with_an_error_line(tmp_path, monkeypatch, caplog):
    with caplog.at_level("ERROR", logger="facet"), pytest.raises(SystemExit) as raised:
        _run(tmp_path, monkeypatch, _processor(saved=0))
    assert raised.value.code == 4
    assert "saved 0 of 1" in caplog.text


@pytest.mark.timeout(30)
def test_a_scan_that_saved_photos_exits_zero(tmp_path, monkeypatch):
    _run(tmp_path, monkeypatch, _processor(saved=1))


@pytest.mark.timeout(30)
def test_everything_already_scanned_exits_zero(tmp_path, monkeypatch):
    _run(tmp_path, monkeypatch, _processor(saved=0), already_scanned=True)


def _calibrating_batch_processor(calibration_saved, main_saved):
    """A BatchProcessor whose first instance stops after calibration and hands paths on."""
    made = []

    class _Batch:
        def __init__(self, *args, **kwargs):
            made.append(self)
            self.first = len(made) == 1
            self.metrics = {'photos_saved': calibration_saved if self.first else main_saved}

        def process_stream(self, paths, total, **kwargs):
            return ['/remaining.jpg'] if self.first else []
    return _Batch


@pytest.mark.timeout(30)
@pytest.mark.parametrize("calibration_saved, main_saved, exits", [
    (0, 0, True),
    (1, 0, False),      # the calibration batch saved: the scan did not save nothing
    (0, 1, False),
])
def test_single_pass_sums_the_calibration_and_main_saves(
        tmp_path, monkeypatch, calibration_saved, main_saved, exits):
    monkeypatch.setattr("processing.batch_processor.BatchProcessor",
                        _calibrating_batch_processor(calibration_saved, main_saved))
    # The default TOPIQ profile would fall back to multi-pass; this test is about the BatchProcessor route.
    monkeypatch.setattr(facet, "_resolve_single_pass", lambda requested, *a, **k: requested)

    def run():
        _run(tmp_path, monkeypatch, _processor(saved=0), extra_args=("--single-pass",))
    if exits:
        with pytest.raises(SystemExit) as raised:
            run()
        assert raised.value.code == 4
    else:
        run()


# ---------------------------------------------------------------------------
# Dead scan roots (B147): a scan whose roots are all gone never saw the
# library, so it must not read as a clean "nothing new".
# ---------------------------------------------------------------------------

@pytest.mark.timeout(30)
def test_all_roots_missing_exits_scan_did_not_run(tmp_path, monkeypatch, caplog):
    with caplog.at_level("ERROR", logger="facet"), pytest.raises(SystemExit) as raised:
        _run(tmp_path, monkeypatch, _processor(saved=0), photo_dir_exists=False)
    assert raised.value.code == SCAN_DID_NOT_RUN_EXIT_CODE
    assert "missing or unreadable" in caplog.text


@pytest.mark.timeout(30)
def test_unreadable_root_counts_as_dead(tmp_path, monkeypatch, caplog):
    # A mount that exists but denies every listdir is not an empty library.
    def denied_walk(top, onerror=None):
        if onerror:
            onerror(OSError(13, "Permission denied"))
        return iter(())

    monkeypatch.setattr("os.walk", denied_walk)
    with caplog.at_level("WARNING", logger="facet"), pytest.raises(SystemExit) as raised:
        _run(tmp_path, monkeypatch, _processor(saved=0))
    assert raised.value.code == SCAN_DID_NOT_RUN_EXIT_CODE
    assert "Path is unreadable" in caplog.text


def test_root_stat_permission_error_exits_scan_did_not_run(tmp_path, monkeypatch):
    from pathlib import Path
    original = Path.exists
    root = tmp_path / 'photos'

    def denied(self):
        if self == root:
            raise PermissionError(13, 'Permission denied', str(self))
        return original(self)

    monkeypatch.setattr(Path, 'exists', denied)
    with pytest.raises(SystemExit) as raised:
        _run(tmp_path, monkeypatch, _processor(saved=0))
    assert raised.value.code == SCAN_DID_NOT_RUN_EXIT_CODE


@pytest.mark.timeout(30)
def test_unreadable_subfolder_under_a_readable_root_is_not_dead(tmp_path, monkeypatch, caplog):
    # A root-owned lost+found (or any restricted album) loses that folder only:
    # a fully scanned library with nothing new must still exit 0.
    lib = tmp_path / "photos"
    lib.mkdir()
    Image.new("RGB", (8, 8), (120, 120, 120)).save(lib / "a.jpg", "JPEG")
    real_walk = os.walk

    def walk_with_locked_subfolder(top, onerror=None):
        yield from real_walk(top)
        if onerror:
            onerror(PermissionError(13, "Permission denied", str(lib / "lost+found")))

    monkeypatch.setattr("os.walk", walk_with_locked_subfolder)
    assert facet._gather_scan_files([str(lib)], {})[1] == []
    with caplog.at_level("WARNING", logger="facet"):
        _run(tmp_path, monkeypatch, _processor(saved=0), already_scanned=True,
             photo_dir_exists=False)
    assert "Scan did not run" not in caplog.text
    assert "lost+found" in caplog.text


@pytest.mark.timeout(30)
def test_partial_missing_roots_proceed_and_name_what_is_gone(tmp_path, monkeypatch, caplog):
    missing = tmp_path / "gone"
    with caplog.at_level("ERROR", logger="facet"):
        _run(tmp_path, monkeypatch, _processor(saved=1), more_paths=[missing])
    assert str(missing) in caplog.text
    assert "Scan proceeds without" in caplog.text


@pytest.mark.timeout(30)
def test_retry_failed_mode_ignores_dead_roots(tmp_path, monkeypatch, caplog):
    # The worklist comes from scan_failures, not the walk: dead roots must not
    # turn a retry into a hard failure (there may be genuinely nothing left).
    with caplog.at_level("ERROR", logger="facet"):
        _run(tmp_path, monkeypatch, _processor(saved=0), photo_dir_exists=False,
             extra_args=("--retry-failed",))
    assert "Scan did not run" not in caplog.text


@pytest.mark.timeout(30)
def test_the_scan_seeds_the_resolve_cache_with_what_the_walk_resolved(tmp_path, monkeypatch):
    # The walk resolves every photo to dedup it; the pipelines must reuse that
    # answer instead of resolving each path again on a network share.
    from pathlib import Path

    from utils import path_cache

    monkeypatch.setattr(path_cache, '_seeded', {})
    seen = {}

    class _Recording(_processor(saved=1)):
        def process_directory(self, paths):
            seen.update({p: path_cache._seeded.get(p) for p in paths})
            return self.metrics

    _run(tmp_path, monkeypatch, _Recording)
    assert seen and all(resolved == str(Path(p).resolve()) for p, resolved in seen.items())


# ---------------------------------------------------------------------------
# A GPU thread dying mid-chunk (B194): everything it never reached was neither
# scored nor recorded as a failure -- the run must not read as completed.
# ---------------------------------------------------------------------------

@pytest.mark.timeout(30)
def test_gpu_thread_death_fails_the_run_and_records_the_tail(tmp_path, monkeypatch, caplog):
    from processing import batch_processor

    def dying_gpu_thread(self, *args, **kwargs):
        raise RuntimeError("simulated GPU thread crash")

    # process_files spawns _gpu_thread; process_stream (the single-pass route)
    # spawns _gpu_thread_with_tuning. Kill both.
    monkeypatch.setattr(batch_processor.BatchProcessor, "_gpu_thread", dying_gpu_thread)
    monkeypatch.setattr(batch_processor.BatchProcessor, "_gpu_thread_with_tuning", dying_gpu_thread)
    with caplog.at_level("ERROR", logger="facet"), pytest.raises(SystemExit) as raised:
        _run(tmp_path, monkeypatch, _processor(saved=0), extra_args=("--single-pass",))
    assert raised.value.code == 1
    assert "GPU thread exited" in caplog.text

    # The unprocessed tail is retryable and the run is NOT stamped completed.
    import sqlite3
    conn = sqlite3.connect(str(tmp_path / "scan.db"))
    failed = {r[0] for r in conn.execute("SELECT path FROM scan_failures")}
    stages = {r[0] for r in conn.execute("SELECT DISTINCT stage FROM scan_failures")}
    status = conn.execute("SELECT status FROM scan_runs ORDER BY id DESC LIMIT 1").fetchone()[0]
    conn.close()
    assert stages == {"gpu_thread"}
    assert status == "failed"
    assert len(failed) == 1  # the whole one-photo tail


@pytest.mark.timeout(30)
def test_gpu_thread_death_records_only_the_photos_it_never_reached(tmp_path, monkeypatch):
    from processing import batch_processor

    def one_result_then_crash(self, *args, **kwargs):
        item = self.image_queue.get(timeout=10)
        self.result_queue.put({'path': item['path'], 'result': {'path': item['path']}})
        raise RuntimeError("simulated GPU thread crash")

    monkeypatch.setattr(batch_processor.BatchProcessor, "_gpu_thread_with_tuning", one_result_then_crash)
    monkeypatch.setattr(facet, "_resolve_single_pass", lambda requested, *a, **k: requested)
    saved = []
    monkeypatch.setattr(_FakeFacet, "save_photos_batch", lambda self, batch: saved.extend(batch), raising=False)
    other = tmp_path / "more"
    other.mkdir()
    Image.new("RGB", (8, 8), (90, 90, 90)).save(other / "b.jpg", "JPEG")
    with pytest.raises(SystemExit) as raised:
        _run(tmp_path, monkeypatch, _processor(saved=0), extra_args=("--single-pass",),
             more_paths=[other])
    assert raised.value.code == 1

    import sqlite3
    conn = sqlite3.connect(str(tmp_path / "scan.db"))
    failed = {r[0] for r in conn.execute("SELECT path FROM scan_failures")}
    status = conn.execute("SELECT status FROM scan_runs ORDER BY id DESC LIMIT 1").fetchone()[0]
    conn.close()
    assert len(saved) == 1
    assert failed and saved[0]['path'] not in failed
    assert len(failed) == 1
    assert status == "failed"


@pytest.mark.timeout(30)
def test_gpu_thread_death_during_calibration_survives_the_processor_swap(tmp_path, monkeypatch):
    calibration_tail = str(tmp_path / "photos" / "calibration-tail.jpg")
    made = []

    class _Batch:
        def __init__(self, *args, **kwargs):
            made.append(self)
            self.first = len(made) == 1
            self.metrics = {'photos_saved': 1}
            if self.first:
                self.metrics.update(gpu_thread_died=True, unprocessed_paths=[calibration_tail])

        def process_stream(self, paths, total, **kwargs):
            return ['/remaining.jpg'] if self.first else None

    monkeypatch.setattr("processing.batch_processor.BatchProcessor", _Batch)
    monkeypatch.setattr(facet, "_resolve_single_pass", lambda requested, *a, **k: requested)
    with pytest.raises(SystemExit) as raised:
        _run(tmp_path, monkeypatch, _processor(saved=0), extra_args=("--single-pass",))
    assert raised.value.code == 1

    import sqlite3
    conn = sqlite3.connect(str(tmp_path / "scan.db"))
    failed = {r[0] for r in conn.execute("SELECT path FROM scan_failures")}
    status = conn.execute("SELECT status FROM scan_runs ORDER BY id DESC LIMIT 1").fetchone()[0]
    conn.close()
    assert failed == {calibration_tail}
    assert status == "failed"


@pytest.mark.timeout(60)
def test_gpu_thread_death_during_a_retry_still_clears_the_records_it_resolved(tmp_path, monkeypatch):
    import sqlite3

    from db.schema import init_database
    from processing.scan_state import ScanRun

    db_path = str(tmp_path / "scan.db")
    init_database(db_path)
    resolved = str(tmp_path / "photos" / "a.jpg")
    unreached = str(tmp_path / "more" / "b.jpg")
    (tmp_path / "more").mkdir()
    Image.new("RGB", (8, 8), (90, 90, 90)).save(unreached, "JPEG")
    old = ScanRun.start(db_path, "multi-pass", {"directories": []}, 2)
    old.record_failure(resolved, "score", "old failure")
    old.record_failure(unreached, "score", "old failure")
    old.finish("failed")

    class _Batch:
        def __init__(self, *args, **kwargs):
            # a.jpg was scored and saved; the GPU thread died before b.jpg.
            self.metrics = {'photos_saved': 1, 'gpu_thread_died': True,
                            'unprocessed_paths': [unreached]}

        def process_stream(self, paths, total, **kwargs):
            return None

    monkeypatch.setattr("processing.batch_processor.BatchProcessor", _Batch)
    monkeypatch.setattr(facet, "_resolve_single_pass", lambda requested, *a, **k: requested)
    with pytest.raises(SystemExit) as raised:
        _run(tmp_path, monkeypatch, _processor(saved=0),
             extra_args=("--single-pass", "--retry-failed"))
    assert raised.value.code == 1
    conn = sqlite3.connect(db_path)
    rows = {(r[0] != old.run_id, r[1]) for r in conn.execute("SELECT scan_run_id, path FROM scan_failures")}
    conn.close()
    # The saved photo's old record is gone; the unreached one has a record in the new run.
    assert (False, resolved) not in rows
    assert (True, unreached) in rows
