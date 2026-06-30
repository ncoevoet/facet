"""Tests for ChunkedMultiPassProcessor chunk-size tuning (processing/multi_pass.py).

The threaded process_directory path mirrors BatchProcessor and is covered e2e in
test_batch_processor_e2e.py; here we lock down the RAM chunk-size auto-tuning
(the OOM-recovery knob) which is pure arithmetic and must never crash a scan.
"""

from unittest import mock

import pytest

pytest.importorskip("torch")

from processing.multi_pass import ChunkedMultiPassProcessor  # noqa: E402


class _FakeModelManager:
    def detect_vram(self):
        return 8.0


def _make(config):
    with mock.patch("processing.multi_pass._ensure_imports"):
        return ChunkedMultiPassProcessor(
            scorer=mock.MagicMock(), model_manager=_FakeModelManager(), config=config
        )


def _config(chunk=100, min_chunk=10, max_chunk=500, enabled=True):
    return {
        "processing": {
            "ram_chunk_size": chunk,
            "auto_tuning": {
                "enabled": enabled,
                "min_ram_chunk_size": min_chunk,
                "max_ram_chunk_size": max_chunk,
            },
        }
    }


class TestChunkSizeTuning:
    def test_reduce_shrinks_by_25_percent(self):
        proc = _make(_config(chunk=100))
        assert proc.reduce_chunk_size() is True
        assert proc.chunk_size == 75

    def test_reduce_respects_minimum(self):
        proc = _make(_config(chunk=12, min_chunk=10))
        # 12 -> 9 clamps to 10
        assert proc.reduce_chunk_size() is True
        assert proc.chunk_size == 10
        # already at floor -> no change, returns False (does not crash)
        assert proc.reduce_chunk_size() is False
        assert proc.chunk_size == 10

    def test_increase_grows_and_respects_maximum(self):
        proc = _make(_config(chunk=100, max_chunk=110))
        assert proc.increase_chunk_size() is True
        assert proc.chunk_size == 110  # 125 clamps to 110
        assert proc.increase_chunk_size() is False

    def test_tuning_disabled_is_noop(self):
        proc = _make(_config(chunk=100, enabled=False))
        assert proc.reduce_chunk_size() is False
        assert proc.increase_chunk_size() is False
        assert proc.chunk_size == 100

    def test_initial_chunk_size_from_config(self):
        proc = _make(_config(chunk=42))
        assert proc.chunk_size == 42


class _ProfileModelManager:
    """Model manager stub exposing a fixed active profile for routing tests."""

    def __init__(self, profile):
        self._profile = profile

    def detect_vram(self):
        return 24.0

    def get_active_profile(self):
        return self._profile


def _make_with_profile(tagging_model, available_vram):
    profile = {
        "aesthetic_model": "topiq",
        "tagging_model": tagging_model,
        "supplementary_pyiqa": [],
        "saliency_enabled": False,
        "composition_model": "samp-net",
    }
    scorer = mock.MagicMock()
    scorer.config.get_extended_iqa_settings.return_value = {}
    with mock.patch("processing.multi_pass._ensure_imports"):
        proc = ChunkedMultiPassProcessor(
            scorer=scorer, model_manager=_ProfileModelManager(profile), config=_config()
        )
    proc.available_vram = available_vram
    return proc


class TestTaggingModelRouting:
    """Regression guard: the 16gb/24gb profiles route to the real Qwen3.5 taggers.

    Commit 3cf0604 upgraded the profile tagging_model to ``qwen3.5-2b``/``qwen3.5-4b``
    but never taught ``_select_models`` those strings, so VLM tagging silently fell
    through to CLIP. These tests lock the routing so that cannot recur.
    """

    def test_16gb_routes_to_qwen3_5_tagger(self):
        proc = _make_with_profile("qwen3.5-2b", available_vram=16.0)
        assert "qwen3_5_tagger" in proc._select_models()

    def test_24gb_routes_to_qwen3_5_4b_tagger(self):
        proc = _make_with_profile("qwen3.5-4b", available_vram=24.0)
        assert "qwen3_5_4b_tagger" in proc._select_models()

    def test_qwen3_5_4b_falls_back_to_clip_without_vram(self):
        proc = _make_with_profile("qwen3.5-4b", available_vram=4.0)
        models = proc._select_models()
        assert "qwen3_5_4b_tagger" not in models
        assert "qwen3_5_tagger" not in models

    def test_clip_profile_loads_no_vlm_tagger(self):
        proc = _make_with_profile("clip", available_vram=24.0)
        models = proc._select_models()
        assert not any(m.endswith("_tagger") or m == "vlm_tagger" for m in models)

    def test_run_model_pass_dispatches_all_vlm_taggers(self):
        # The 3cf0604 regression also left _run_model_pass's dispatch unaware of the
        # qwen3.5 taggers, so a selected model would silently no-op. Lock the contract.
        proc = _make_with_profile("qwen3.5-2b", available_vram=16.0)
        for tagger in ("vlm_tagger", "qwen3_vl_tagger", "qwen3_5_tagger", "qwen3_5_4b_tagger"):
            proc._pass_vlm_tagger = mock.MagicMock()
            proc._run_model_pass(tagger, model=None, images={}, results={})
            assert proc._pass_vlm_tagger.called, f"{tagger} not dispatched to _pass_vlm_tagger"

    def test_selected_tagger_is_dispatchable(self):
        proc = _make_with_profile("qwen3.5-4b", available_vram=24.0)
        selected = [m for m in proc._select_models() if m.endswith("_tagger")]
        assert selected == ["qwen3_5_4b_tagger"]
        proc._pass_vlm_tagger = mock.MagicMock()
        proc._run_model_pass(selected[0], model=None, images={}, results={})
        assert proc._pass_vlm_tagger.called
