"""Per-model inference and load timers (scan-resource-scheduler Stage 1, steps 1 and I2).

Every model pass here is a ``time.sleep`` of a known length, so the expected number is the sleep.
"""
import logging
import time

import pytest

pytest.importorskip("torch")

from tests._phase_support import FakeModelManager, make_processor  # noqa: E402

PASS_S = {"clip": 0.05, "topiq": 0.10}


def _run_chunk(monkeypatch, fake_pass, groups=(("clip", "topiq"),), manager=None):
    proc = make_processor([list(g) for g in groups], manager, monkeypatch)
    monkeypatch.setattr(proc, "_load_images", lambda paths, **kw: {p: {} for p in paths})
    monkeypatch.setattr(proc, "_run_model_pass", fake_pass)
    proc._process_chunk(["a.jpg", "b.jpg"], 0, 1)
    return proc


def _sleeping_pass(model_name, model, images, results):
    time.sleep(PASS_S[model_name])


class TestInferenceByModel:
    def test_each_model_records_its_own_pass_and_the_sum_is_the_inference_bracket(self, monkeypatch):
        proc = _run_chunk(monkeypatch, _sleeping_pass)
        by_model = proc.metrics["inference_by_model"]
        assert set(by_model) == {"clip", "topiq"}
        assert by_model["clip"] == pytest.approx(0.05, abs=0.010)
        assert by_model["topiq"] == pytest.approx(0.10, abs=0.010)
        assert sum(by_model.values()) == pytest.approx(proc.metrics["inference_time"], abs=0.001)

    def test_a_second_chunk_adds_to_the_same_model(self, monkeypatch):
        proc = _run_chunk(monkeypatch, _sleeping_pass)
        first = dict(proc.metrics["inference_by_model"])
        proc._process_chunk(["c.jpg"], 1, 2)
        assert proc.metrics["inference_by_model"]["topiq"] == pytest.approx(2 * first["topiq"], abs=0.02)

    def test_a_failing_model_still_records_the_time_it_took(self, monkeypatch):
        def failing(model_name, model, images, results):
            time.sleep(PASS_S[model_name])
            if model_name == "clip":
                raise RuntimeError("simulated pass failure")

        proc = _run_chunk(monkeypatch, failing)
        by_model = proc.metrics["inference_by_model"]
        assert by_model["clip"] == pytest.approx(0.05, abs=0.010)
        assert by_model["topiq"] == pytest.approx(0.10, abs=0.010)
        assert sum(by_model.values()) == pytest.approx(proc.metrics["inference_time"], abs=0.001)

    def test_a_model_is_keyed_by_its_loaded_name_across_pass_groups(self, monkeypatch):
        proc = _run_chunk(monkeypatch, _sleeping_pass, groups=(("clip",), ("topiq",)))
        assert set(proc.metrics["inference_by_model"]) == {"clip", "topiq"}
        assert proc.metrics["passes_executed"] == 2


class TestSummaryBlock:
    def _summary_lines(self, proc, caplog):
        proc.metrics["total_time"] = 1.0
        with caplog.at_level(logging.INFO, logger="facet.multi_pass"):
            proc._print_summary()
        return [r.getMessage() for r in caplog.records]

    def test_models_print_in_descending_order_with_their_share_of_inference(self, monkeypatch, caplog):
        proc = _run_chunk(monkeypatch, _sleeping_pass)
        lines = self._summary_lines(proc, caplog)
        start = next(i for i, line in enumerate(lines) if line.startswith("Inference by model"))
        assert lines[start + 1].strip().startswith("topiq:")
        assert lines[start + 2].strip().startswith("clip:")
        assert "(67%)" in lines[start + 1] or "(66%)" in lines[start + 1]

    def test_a_scan_that_ran_no_pass_prints_no_by_model_block(self, monkeypatch, caplog):
        proc = make_processor([["clip"]], None, monkeypatch)
        lines = self._summary_lines(proc, caplog)
        assert not any("by model" in line for line in lines)


class TestModelLoadByModel:
    LOAD_S = {"clip": 0.10, "topiq": 0.20}

    def test_loads_are_timed_per_model_and_sum_to_the_load_bracket_within_one_percent(self, monkeypatch):
        manager = FakeModelManager(load_s=self.LOAD_S)
        proc = _run_chunk(monkeypatch, _sleeping_pass, manager=manager)
        by_model = proc.metrics["model_load_by_model"]
        assert by_model["clip"] == pytest.approx(0.10, abs=0.010)
        assert by_model["topiq"] == pytest.approx(0.20, abs=0.010)
        assert sum(by_model.values()) == pytest.approx(proc.metrics["model_load_time"], rel=0.01)

    def test_a_load_that_fails_still_records_its_time(self, monkeypatch):
        manager = FakeModelManager(load_s=self.LOAD_S, fail_load={"topiq"})
        proc = make_processor([["clip", "topiq"]], manager, monkeypatch)
        failed = []
        loaded = proc._load_pass_models(["clip", "topiq"], set(), failed)
        assert list(loaded) == ["clip"] and failed == ["topiq"]
        assert proc.metrics["model_load_by_model"]["topiq"] == pytest.approx(0.20, abs=0.010)

    def test_an_overlapped_load_is_kept_apart_from_the_pass_load(self, monkeypatch):
        manager = FakeModelManager(load_s=self.LOAD_S)
        proc = make_processor([["clip"]], manager, monkeypatch)
        proc._load_pass_models(["clip"], set(), [], beside_decode=True)
        assert proc.metrics["model_load_by_model"] == {}
        assert proc.metrics["model_load_overlapped_by_model"]["clip"] == pytest.approx(0.10, abs=0.010)
