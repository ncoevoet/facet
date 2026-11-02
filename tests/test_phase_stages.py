"""Per-stage busy / wait / occupancy (scan-resource-scheduler Stage 1, step 2).

The chunk plumbing and the scan thread's wait brackets are the real code; the decode, the model
load and the passes are sleeps, so each expected number is a sleep length.
"""
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

pytest.importorskip("torch")

from processing import stage_timing  # noqa: E402
from tests._phase_support import FakeModelManager, make_processor  # noqa: E402

TOL = 0.020     # the spec's 20 ms


def _overlapped_chunk(monkeypatch, decode_s, load_s, infer_s, aggregate_s=0.02, save_s=0.02):
    """One chunk whose decode runs on the worker beside the first group's model load."""
    manager = FakeModelManager(load_s={"clip": load_s})
    proc = make_processor([["clip"]], manager, monkeypatch, {"aggregate": aggregate_s, "save": save_s})
    proc._decode_executor = ThreadPoolExecutor(max_workers=1)
    proc._decode_stop = threading.Event()
    proc.load_workers = 1
    monkeypatch.setattr(proc, "_overlap_allowed", lambda paths, group: True)

    def fake_decode(paths, stop_event=None, report_error=None):
        time.sleep(decode_s)
        proc.metrics["decode_worker_time"] += decode_s      # one worker, busy for the whole decode
        return {p: {} for p in paths}

    monkeypatch.setattr(proc, "_load_images", fake_decode)
    monkeypatch.setattr(proc, "_run_model_pass",
                        lambda name, model, images, results: time.sleep(infer_s))
    start = time.perf_counter()
    try:
        proc._process_chunk(["a.jpg", "b.jpg"], 0, 1)
    finally:
        proc._decode_executor.shutdown()
    proc.metrics["total_time"] = time.perf_counter() - start
    return proc, stage_timing.build_stages(proc.metrics, proc.load_workers)


class TestWaitAttribution:
    def test_a_slow_decode_is_what_the_scan_thread_waits_on(self, monkeypatch):
        proc, stages = _overlapped_chunk(monkeypatch, decode_s=0.40, load_s=0.10, infer_s=0.05)
        m = proc.metrics
        # decode occupancy ~ 1: the single worker is busy for the whole decode wall
        assert stages["decode"]["occupancy"] == pytest.approx(1.0, abs=0.05)
        # the scan thread loaded for 0.10 s while the decode ran, then waited for the rest of it
        assert stages["scan"]["wait_on"] == "decode"
        assert stages["scan"]["wait_s"] == pytest.approx(m["io_decode_time"] - m["model_load_time"], abs=TOL)
        assert stages["scan"]["wait_s"] == pytest.approx(0.30, abs=TOL)
        assert stages["decode"]["busy_s"] == pytest.approx(0.40, abs=TOL)
        # the first group's load ran beside the decode, so it is booked as overlapped
        assert m["model_load_overlapped_by_model"]["clip"] == pytest.approx(0.10, abs=TOL)
        assert m["model_load_by_model"] == {}

    def test_the_slowest_stage_swapping_swaps_the_result(self, monkeypatch):
        proc, stages = _overlapped_chunk(monkeypatch, decode_s=0.05, load_s=0.10, infer_s=0.40)
        # decode is now hidden entirely behind the load: nothing left to wait for
        assert stages["scan"]["wait_s"] < TOL
        assert stages["inference"]["busy_s"] == pytest.approx(0.40, abs=TOL)
        assert stages["inference"]["busy_s"] > stages["decode"]["busy_s"]
        wall = proc.metrics["total_time"]
        assert stages["inference"]["busy_s"] / wall > 0.5 > stages["decode"]["busy_s"] / wall

    def test_the_scan_thread_stages_plus_its_wait_equal_the_wall_within_two_percent(self, monkeypatch):
        proc, stages = _overlapped_chunk(monkeypatch, decode_s=0.40, load_s=0.10, infer_s=0.15)
        acct = stage_timing.scan_thread_accounting(stages, proc.metrics["total_time"])
        assert abs(acct["unaccounted_share"]) < 0.02
        assert acct["accounted_s"] == pytest.approx(proc.metrics["total_time"], rel=0.02)

    def test_a_synchronous_decode_is_all_scan_thread_wait(self, monkeypatch):
        manager = FakeModelManager(load_s={"clip": 0.05})
        proc = make_processor([["clip"]], manager, monkeypatch)
        proc.load_workers = 1

        def fake_decode(paths, **kw):
            time.sleep(0.25)
            return {p: {} for p in paths}

        monkeypatch.setattr(proc, "_load_images", fake_decode)
        monkeypatch.setattr(proc, "_run_model_pass", lambda *a: time.sleep(0.05))
        proc._process_chunk(["a.jpg"], 0, 1)
        assert proc.metrics["io_time"] == pytest.approx(0.25, abs=TOL)


class TestBuildStages:
    METRICS = {
        "total_time": 100.0, "model_load_time": 20.0, "inference_time": 50.0, "model_unload_time": 5.0,
        "aggregate_time": 2.0, "thumbnail_time": 3.0, "save_time": 4.0, "io_time": 10.0,
        "io_decode_time": 60.0, "decode_worker_time": 120.0, "analyze_worker_time": 60.0, "exif_fallback_time": 0.0,
        "exif_batch_time": 6.0,
    }

    def test_pool_stages_are_in_worker_seconds_over_pool_times_wall(self):
        stages = stage_timing.build_stages(self.METRICS, load_workers=4)
        assert stages["decode"]["occupancy"] == pytest.approx(120.0 / (4 * 60.0))
        assert stages["inference"]["occupancy"] == pytest.approx(0.5)
        assert stages["exif_batch"]["pool"] == 1

    def test_the_scan_record_sums_the_scan_thread_stages_and_carries_the_decode_wait(self):
        stages = stage_timing.build_stages(self.METRICS, load_workers=4)
        assert stages["scan"]["busy_s"] == pytest.approx(20 + 50 + 5 + 2 + 3 + 4)
        assert stages["scan"]["wait_s"] == 10.0 and stages["scan"]["wait_on"] == "decode"
        acct = stage_timing.scan_thread_accounting(stages, 100.0)
        assert acct["unaccounted_s"] == pytest.approx(6.0)

    def test_zero_wall_gives_no_occupancy_instead_of_dividing_by_zero(self):
        stages = stage_timing.build_stages({"total_time": 0}, load_workers=4)
        assert stages["inference"]["occupancy"] is None and stages["decode"]["occupancy"] is None


class TestSummary:
    def test_the_stage_summary_lines_are_logged_once_a_scan_completes(self, monkeypatch, caplog):
        proc = make_processor([["clip"]], None, monkeypatch)
        proc.metrics.update(TestBuildStages.METRICS)
        proc.metrics["stages"] = stage_timing.build_stages(proc.metrics, 4)
        with caplog.at_level(logging.INFO, logger="facet.multi_pass"):
            proc._print_summary()
        text = "\n".join(r.getMessage() for r in caplog.records)
        assert "Stages (scan thread in seconds; decode-pool stages in worker-seconds):" in text
        assert "scan thread: accounted" in text
        # the serial stages are in "Time breakdown" already, so the block does not repeat them
        assert "    inference: busy" not in text and "    save: busy" not in text
        assert "    scan: busy" in text and "    exif_batch: busy" in text
        assert "decode: busy 120.0s" in text and "occupancy 50%" in text
