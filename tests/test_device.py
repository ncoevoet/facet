"""Tests for runtime CPU/CUDA/Apple Metal device policy."""

from __future__ import annotations

import os
import sys
import types
from unittest import mock

import pytest

from models.deqa_scorer import DeQAScorer
from models.model_manager import ModelManager
from processing.scorer import describe_scoring_device
from utils import device


def _torch(*, cuda=False, mps=False):
    calls = types.SimpleNamespace(cuda_empty=0, cuda_sync=0, mps_empty=0, mps_sync=0)

    def _inc(name):
        setattr(calls, name, getattr(calls, name) + 1)

    fake = types.SimpleNamespace(
        cuda=types.SimpleNamespace(
            is_available=lambda: cuda,
            empty_cache=lambda: _inc("cuda_empty"),
            synchronize=lambda: _inc("cuda_sync"),
        ),
        backends=types.SimpleNamespace(
            mps=types.SimpleNamespace(is_available=lambda: mps),
        ),
        mps=types.SimpleNamespace(
            empty_cache=lambda: _inc("mps_empty"),
            synchronize=lambda: _inc("mps_sync"),
        ),
    )
    return fake, calls


def test_auto_prefers_cuda_over_mps(monkeypatch):
    fake, _ = _torch(cuda=True, mps=True)
    monkeypatch.setitem(sys.modules, "torch", fake)
    monkeypatch.delenv("FACET_DEVICE", raising=False)
    assert device.get_device() == "cuda"


def test_auto_selects_mps_when_cuda_is_unavailable(monkeypatch):
    fake, _ = _torch(mps=True)
    monkeypatch.setitem(sys.modules, "torch", fake)
    monkeypatch.delenv("FACET_DEVICE", raising=False)
    assert device.get_device() == "mps"


def test_cpu_override_wins_even_when_accelerators_exist(monkeypatch):
    fake, _ = _torch(cuda=True, mps=True)
    monkeypatch.setitem(sys.modules, "torch", fake)
    monkeypatch.setenv("FACET_DEVICE", "cpu")
    assert device.get_device() == "cpu"


def test_forced_unavailable_device_fails_clearly(monkeypatch):
    fake, _ = _torch()
    monkeypatch.setitem(sys.modules, "torch", fake)
    monkeypatch.setenv("FACET_DEVICE", "mps")
    with pytest.raises(RuntimeError, match="not available"):
        device.get_device()


def test_invalid_device_override_is_rejected(monkeypatch):
    monkeypatch.setenv("FACET_DEVICE", "metal")
    with pytest.raises(ValueError, match="FACET_DEVICE"):
        device.get_device()


def test_auto_falls_back_to_cpu_with_no_accelerators(monkeypatch):
    fake, _ = _torch()
    monkeypatch.setitem(sys.modules, "torch", fake)
    monkeypatch.delenv("FACET_DEVICE", raising=False)
    assert device.get_device() == "cpu"


def test_auto_without_torch_defaults_to_cpu(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", None)
    monkeypatch.delenv("FACET_DEVICE", raising=False)
    assert device.get_device() == "cpu"


def test_forced_accelerator_without_torch_raises(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", None)
    monkeypatch.setenv("FACET_DEVICE", "mps")
    with pytest.raises(RuntimeError, match="PyTorch is not installed"):
        device.get_device()


def test_mps_cache_and_synchronize_use_metal_api(monkeypatch):
    fake, calls = _torch(mps=True)
    monkeypatch.setitem(sys.modules, "torch", fake)
    device.clear_device_cache("mps")
    device.synchronize_device("mps")
    assert calls.mps_empty == 1
    assert calls.mps_sync == 1
    assert calls.cuda_empty == 0


def test_mps_operator_fallback_enabled_by_default(monkeypatch):
    import importlib
    monkeypatch.delenv("PYTORCH_ENABLE_MPS_FALLBACK", raising=False)
    importlib.reload(device)
    assert os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] == "1"


def test_mps_operator_fallback_respects_explicit_override(monkeypatch):
    import importlib
    monkeypatch.setenv("PYTORCH_ENABLE_MPS_FALLBACK", "0")
    importlib.reload(device)
    assert os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] == "0"


def _use_fake_torch(monkeypatch, *, cuda=False, mps=False):
    fake, _ = _torch(cuda=cuda, mps=mps)
    monkeypatch.setitem(sys.modules, "torch", fake)
    monkeypatch.delenv("FACET_DEVICE", raising=False)
    return fake


def test_detect_accelerator_reports_mps_when_cuda_is_absent(monkeypatch):
    _use_fake_torch(monkeypatch, mps=True)
    assert ModelManager.detect_accelerator() == "mps"


def test_detect_accelerator_reports_cuda(monkeypatch):
    _use_fake_torch(monkeypatch, cuda=True)
    assert ModelManager.detect_accelerator() == "cuda"


def test_detect_accelerator_is_none_without_accelerators(monkeypatch):
    _use_fake_torch(monkeypatch)
    assert ModelManager.detect_accelerator() is None


def _fake_effective_memory(monkeypatch, total_gb):
    """Point ``suggest_vram_profile``'s memory read at a synthetic reading.

    ``suggest_vram_profile`` resolves ``effective_memory`` with a
    function-local import, so patching the ``utils.system_memory`` module
    attribute -- not ``sys.modules["psutil"]`` -- is what actually reaches it.
    """
    from utils import system_memory

    reading = system_memory.EffectiveMemory(
        total=int(total_gb * 1024**3), used=0,
        available=int(total_gb * 1024**3), percent=0.0,
    )
    monkeypatch.setattr(system_memory, "effective_memory", lambda: reading)
    return reading


class TestUnifiedMemoryProfileSelection:
    """``auto`` must size a Metal machine, not floor it at the weakest profile.

    Metal reports no dedicated VRAM, so the CUDA probe returns None there. The
    suggestion is driven end to end from a simulated torch: the same fake that
    makes ``mps_available()`` true also makes ``torch.cuda.is_available()``
    false, exactly as an Apple Silicon machine does.
    """

    def _suggest(self, monkeypatch, total_memory_gb, *, mps=True):
        from config.scoring_config import ScoringConfig

        _use_fake_torch(monkeypatch, mps=mps)
        _fake_effective_memory(monkeypatch, total_memory_gb)
        return ScoringConfig.suggest_vram_profile()

    def test_large_mac_gets_the_richest_profile(self, monkeypatch):
        profile, vram, msg = self._suggest(monkeypatch, 128)
        assert profile == "24gb"
        assert vram is None
        assert "unified memory" in msg

    def test_mid_mac_gets_the_16gb_profile(self, monkeypatch):
        profile, _, _ = self._suggest(monkeypatch, 32)
        assert profile == "16gb"

    def test_small_mac_stays_on_legacy(self, monkeypatch):
        profile, _, _ = self._suggest(monkeypatch, 8)
        assert profile == "legacy"

    def test_cpu_override_keeps_legacy_on_a_large_mac(self, monkeypatch):
        from config.scoring_config import ScoringConfig

        _use_fake_torch(monkeypatch, mps=True)
        _fake_effective_memory(monkeypatch, 128)
        monkeypatch.setenv("FACET_DEVICE", "cpu")
        profile, _, msg = ScoringConfig.suggest_vram_profile()
        assert profile == "legacy"
        assert "FACET_DEVICE=cpu" in msg

    def test_no_accelerator_stays_on_legacy(self, monkeypatch):
        profile, _, msg = self._suggest(monkeypatch, 128, mps=False)
        assert profile == "legacy"
        assert "No GPU detected" in msg


class TestAcceleratorAwareTaggerGate:
    """The multi-pass tagger gate must not read an MPS Mac as "no accelerator".

    ``detect_vram`` reports dedicated CUDA VRAM only, so on Apple Metal it is
    0.0 while models really do run on the GPU. Gating the profile's VLM tagger
    on that number silently downgraded a configured 16gb profile to CLIP
    similarity tagging.
    """

    PROFILE_TAGGER = "qwen3_5_tagger"

    def _processor(self, monkeypatch, *, cuda=False, mps=False, available_vram=0.0):
        from processing.multi_pass import ChunkedMultiPassProcessor
        _use_fake_torch(monkeypatch, cuda=cuda, mps=mps)
        profile = {
            "aesthetic_model": "topiq",
            "tagging_model": "qwen3.5-2b",
            "supplementary_pyiqa": [],
            "saliency_enabled": False,
            "composition_model": "samp-net",
        }
        model_manager = types.SimpleNamespace(
            detect_vram=lambda: available_vram,
            get_active_profile=lambda: profile,
        )
        scorer = mock.MagicMock()
        scorer.config.get_extended_iqa_settings.return_value = {}
        with mock.patch("processing.multi_pass._ensure_imports"):
            return ChunkedMultiPassProcessor(
                scorer=scorer, model_manager=model_manager, config={}
            )

    def test_mps_keeps_the_configured_profile_tagger(self, monkeypatch):
        proc = self._processor(monkeypatch, mps=True)
        assert proc.accelerator == "mps"
        assert self.PROFILE_TAGGER in proc._select_models()

    def test_no_accelerator_still_degrades_to_clip_tagging(self, monkeypatch):
        proc = self._processor(monkeypatch)
        assert proc.accelerator is None
        assert self.PROFILE_TAGGER not in proc._select_models()

    def test_cuda_vram_still_vetoes_a_tagger_that_does_not_fit(self, monkeypatch):
        proc = self._processor(monkeypatch, cuda=True, available_vram=2.0)
        assert self.PROFILE_TAGGER not in proc._select_models()

    def test_cuda_with_enough_vram_keeps_the_tagger(self, monkeypatch):
        proc = self._processor(monkeypatch, cuda=True, available_vram=16.0)
        assert self.PROFILE_TAGGER in proc._select_models()

    def test_mps_is_not_reported_as_cpu_only(self, monkeypatch):
        proc = self._processor(monkeypatch, mps=True)
        assert proc._memory_budget_label() == "mps accelerator, unified memory"

    def test_cpu_is_still_reported_as_cpu_only(self, monkeypatch):
        proc = self._processor(monkeypatch)
        assert proc._memory_budget_label() == "CPU-only"


class TestAcceleratorAwareDeQAGate:
    """DeQA-Score must not read an MPS Mac's 0.0GB of dedicated VRAM as "no GPU".

    ``detect_vram`` reports dedicated CUDA memory only, so gating the load on it
    refused DeQA-Score on every Apple Silicon machine however much unified
    memory it had, while the same class of model runs on Metal elsewhere in the
    codebase. The CUDA comparison is deliberately left untouched.
    """

    def _scorer(self, monkeypatch, *, cuda=False, mps=False, vram_gb=0.0, ram_gb=8.0):
        import models.model_manager as mm

        _use_fake_torch(monkeypatch, cuda=cuda, mps=mps)
        monkeypatch.setattr(mm.ModelManager, "detect_vram", staticmethod(lambda: vram_gb))
        monkeypatch.setattr(mm.ModelManager, "detect_system_ram_gb", staticmethod(lambda: ram_gb))
        return DeQAScorer()

    def test_large_memory_mac_may_run(self, monkeypatch):
        assert self._scorer(monkeypatch, mps=True, ram_gb=64.0).can_run() is True

    def test_small_memory_mac_is_refused(self, monkeypatch):
        assert self._scorer(monkeypatch, mps=True, ram_gb=16.0).can_run() is False

    def test_mac_requirement_doubles_the_vram_bar(self, monkeypatch):
        required = DeQAScorer.unified_memory_required_gb(DeQAScorer.DEFAULT_MIN_VRAM_GB)
        assert required == 32.0
        assert self._scorer(monkeypatch, mps=True, ram_gb=required).can_run() is True
        assert self._scorer(monkeypatch, mps=True, ram_gb=required - 0.5).can_run() is False

    def test_a_small_model_still_leaves_the_system_its_headroom(self):
        assert DeQAScorer.unified_memory_required_gb(4.0) == 12.0

    def test_cuda_above_the_vram_bar_is_unchanged(self, monkeypatch):
        assert self._scorer(monkeypatch, cuda=True, vram_gb=24.0).can_run() is True

    def test_cuda_below_the_vram_bar_is_unchanged(self, monkeypatch):
        assert self._scorer(monkeypatch, cuda=True, vram_gb=8.0).can_run() is False

    def test_no_accelerator_is_still_refused(self, monkeypatch):
        assert self._scorer(monkeypatch, ram_gb=256.0).can_run() is False

    def test_refused_load_names_both_memory_budgets(self, monkeypatch):
        scorer = self._scorer(monkeypatch, mps=True, ram_gb=8.0)
        with pytest.raises(RuntimeError, match="unified memory"):
            scorer.load()
        assert scorer._loaded is False


class TestScoringDeviceLabel:
    """A Metal run is GPU-accelerated and must not be logged as "CPU"."""

    def test_metal_is_labelled_by_its_unified_memory(self):
        assert describe_scoring_device("mps", 0.0, 36.0) == (
            "mps accelerator, unified memory (36GB)"
        )

    def test_cuda_is_still_labelled_by_its_vram(self):
        assert describe_scoring_device("cuda", 24.0, 64.0) == "GPU (24GB)"

    def test_no_accelerator_is_still_labelled_cpu(self):
        assert describe_scoring_device(None, 0.0, 64.0) == "CPU"
