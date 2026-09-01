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


PRE_BLACKWELL_ARCHS = ["sm_50", "sm_60", "sm_70", "sm_75", "sm_80", "sm_86", "sm_90"]


OOM_ERROR = "CUDA out of memory. Tried to allocate 2.00 MiB"
BUSY_ERROR = "CUDA error: all CUDA-capable devices are busy or unavailable"
MISSING_KERNEL_ERROR = (
    "CUDA error: no kernel image is available for execution on the device"
)


def _cuda_torch(capability=None, arch_list=None, *, kernel=None, allocation=None,
                sync=None):
    """A CUDA-reporting torch double, optionally exposing the arch APIs.

    The probe's three phases are separately controllable. ``allocation`` makes
    ``torch.zeros`` itself raise (out of memory, busy device); ``kernel``
    makes the launch on the allocated tensor raise; ``sync`` makes
    ``torch.cuda.synchronize`` raise, which is where a real card reports an
    asynchronous launch. Leaving them all ``None`` models a build with no
    allocator to probe at all.
    """
    fake, _ = _torch(cuda=True)
    if sync is not None:
        def _failing_sync():
            raise RuntimeError(sync)
        fake.cuda.synchronize = _failing_sync
        # A synchronize can only be reached through a probe that got that far,
        # so this double needs an allocation and a launch that both succeed.
        fake.zeros = lambda *args, **kwargs: types.SimpleNamespace(add_=lambda value: None)
    if capability is not None:
        fake.cuda.get_device_capability = lambda index=0: capability
    if arch_list is not None:
        fake.cuda.get_arch_list = lambda: list(arch_list)
    if allocation is not None:
        def _failing_allocation(*args, **kwargs):
            raise RuntimeError(allocation)
        fake.zeros = _failing_allocation
    elif kernel == "ok":
        fake.zeros = lambda *args, **kwargs: types.SimpleNamespace(add_=lambda value: None)
    elif kernel is not None:
        def _failing_kernel(value):
            raise RuntimeError(kernel)
        fake.zeros = lambda *args, **kwargs: types.SimpleNamespace(add_=_failing_kernel)
    return fake


class TestCudaArchGate:
    """A wheel shipping no kernels for the local GPU is not a usable CUDA device.

    ``torch.cuda.is_available()`` answers "driver and device present", never
    "this build ships kernels for it". That gap let an RTX 50-series card
    (``sm_120``) on a CUDA 12.6 wheel commit the 16gb profile and then die on
    the first real tensor op (issue #119).
    """

    def test_blackwell_on_a_pre_blackwell_wheel_is_unavailable(self, monkeypatch):
        fake = _cuda_torch((12, 0), PRE_BLACKWELL_ARCHS)
        monkeypatch.setitem(sys.modules, "torch", fake)
        monkeypatch.delenv("FACET_DEVICE", raising=False)
        assert device.is_device_available("cuda", torch_module=fake) is False
        assert device.get_device() == "cpu"

    def test_ampere_on_the_same_wheel_is_available(self, monkeypatch):
        fake = _cuda_torch((8, 6), PRE_BLACKWELL_ARCHS)
        monkeypatch.setitem(sys.modules, "torch", fake)
        monkeypatch.delenv("FACET_DEVICE", raising=False)
        assert device.is_device_available("cuda", torch_module=fake) is True
        assert device.get_device() == "cuda"

    def test_binary_compatibility_within_a_major_is_honoured(self):
        fake = _cuda_torch((6, 1), ["sm_60", "sm_70"])
        assert device.is_device_available("cuda", torch_module=fake) is True

    def test_a_wheel_without_an_arch_list_fails_open(self):
        fake, _ = _torch(cuda=True)
        assert device.is_device_available("cuda", torch_module=fake) is True

    def test_a_capability_without_an_arch_list_fails_open(self):
        fake = _cuda_torch((12, 0))
        assert device.is_device_available("cuda", torch_module=fake) is True

    def test_ptx_covers_a_newer_device(self):
        fake = _cuda_torch((12, 0), ["sm_80", "compute_80"])
        assert device.is_device_available("cuda", torch_module=fake) is True

    def test_a_missing_kernel_image_overrules_a_matching_arch_list(self):
        fake = _cuda_torch((8, 6), PRE_BLACKWELL_ARCHS, kernel=MISSING_KERNEL_ERROR)
        assert device.is_device_available("cuda", torch_module=fake) is False
        assert "no kernel image" in device.cuda_arch_status(torch_module=fake).reason

    def test_a_missing_kernel_image_at_allocation_also_disqualifies(self):
        """The error class decides, not the phase it surfaced in.

        A torch that fills the probe tensor with a kernel would raise this
        from the allocation, and the arch list cannot always corroborate --
        a build need not expose one at all.
        """
        fake = _cuda_torch((8, 6), PRE_BLACKWELL_ARCHS, allocation=MISSING_KERNEL_ERROR)
        assert device.is_device_available("cuda", torch_module=fake) is False
        assert "allocation failed" in device.cuda_arch_status(torch_module=fake).reason

    def test_an_invalid_device_function_also_disqualifies(self):
        fake = _cuda_torch(
            (8, 6), PRE_BLACKWELL_ARCHS, kernel="CUDA error: invalid device function")
        assert device.is_device_available("cuda", torch_module=fake) is False

    def test_an_executed_kernel_keeps_a_matching_wheel_usable(self):
        fake = _cuda_torch((8, 6), PRE_BLACKWELL_ARCHS, kernel="ok")
        assert device.is_device_available("cuda", torch_module=fake) is True

    def test_out_of_memory_does_not_disqualify_the_build(self):
        """A full card is a transient condition, not a wrong PyTorch build.

        Reading an allocation failure as "no kernels for this device" would
        demote a whole scan to CPU -- hours instead of minutes -- memoise
        that for the process lifetime, and blame the install for it. The
        real error must surface where it always did, at model load.
        """
        fake = _cuda_torch((8, 6), PRE_BLACKWELL_ARCHS, allocation=OOM_ERROR)
        assert device.is_device_available("cuda", torch_module=fake) is True
        assert device.cuda_arch_mismatch(torch_module=fake) is None

    def test_a_busy_device_does_not_disqualify_the_build(self):
        """Another process holding the card, or exclusive-compute mode."""
        fake = _cuda_torch((8, 6), PRE_BLACKWELL_ARCHS, allocation=BUSY_ERROR)
        assert device.is_device_available("cuda", torch_module=fake) is True
        assert device.cuda_arch_mismatch(torch_module=fake) is None

    def test_out_of_memory_at_launch_does_not_disqualify_the_build(self):
        """The failure phase alone is not enough; the error class decides too."""
        fake = _cuda_torch((8, 6), PRE_BLACKWELL_ARCHS, kernel=OOM_ERROR)
        assert device.is_device_available("cuda", torch_module=fake) is True

    def test_a_transient_failure_cannot_mask_a_real_arch_mismatch(self):
        """An unusable card that is also busy is still an unusable card."""
        fake = _cuda_torch((12, 0), PRE_BLACKWELL_ARCHS, allocation=BUSY_ERROR)
        assert device.is_device_available("cuda", torch_module=fake) is False
        assert "sm_120" in device.cuda_arch_status(torch_module=fake).reason

    def test_status_without_a_cuda_device_says_so(self):
        """The public helper must be honest when called on its own.

        Every current caller gates on availability first, but a "launch
        failed" story for a machine that simply has no GPU would mislead the
        next one.
        """
        fake, _ = _torch()
        status = device.cuda_arch_status(torch_module=fake)
        assert status.usable is False
        assert "no CUDA device" in status.reason
        assert "launch failed" not in status.reason

    def test_forced_cuda_on_a_mismatched_build_fails_clearly(self, monkeypatch):
        fake = _cuda_torch((12, 0), PRE_BLACKWELL_ARCHS)
        monkeypatch.setitem(sys.modules, "torch", fake)
        monkeypatch.setenv("FACET_DEVICE", "cuda")
        with pytest.raises(RuntimeError, match="not available"):
            device.get_device()

    def test_status_carries_the_detail_a_diagnosis_needs(self):
        status = device.cuda_arch_status(
            torch_module=_cuda_torch((12, 0), PRE_BLACKWELL_ARCHS))
        assert status.usable is False
        assert status.capability == (12, 0)
        assert status.arch_list == tuple(PRE_BLACKWELL_ARCHS)
        assert "sm_120" in status.reason

    def test_mismatch_is_none_when_torch_sees_no_device(self):
        fake, _ = _torch()
        assert device.cuda_arch_mismatch(torch_module=fake) is None

    def test_mismatch_is_none_when_the_device_works(self):
        fake = _cuda_torch((8, 6), PRE_BLACKWELL_ARCHS)
        assert device.cuda_arch_mismatch(torch_module=fake) is None

    def test_mismatch_names_the_unusable_device(self):
        fake = _cuda_torch((12, 0), PRE_BLACKWELL_ARCHS)
        assert device.cuda_arch_mismatch(torch_module=fake).capability == (12, 0)

    def test_the_gate_is_memoised_per_torch_module(self):
        probes = []
        fake = _cuda_torch((8, 6), PRE_BLACKWELL_ARCHS)

        def _counted_zeros(*args, **kwargs):
            probes.append(1)
            return types.SimpleNamespace(add_=lambda value: None)

        fake.zeros = _counted_zeros
        for _ in range(3):
            device.is_device_available("cuda", torch_module=fake)
        assert len(probes) == 1

        other = _cuda_torch((12, 0), PRE_BLACKWELL_ARCHS)
        assert device.is_device_available("cuda", torch_module=other) is False

    def test_blackwell_on_its_own_wheel_is_available(self):
        """The three-digit arch the whole fix exists for.

        ``sm_120`` must split into major 12, minor 0 -- not 1 and 20. Getting
        that backwards makes the CORRECT Blackwell image report its own GPU
        unusable and silently demote every scan to CPU, which is the fix
        running in reverse (issue #119).
        """
        fake = _cuda_torch((12, 0), ["sm_75", "sm_90", "sm_100", "sm_120"])
        assert device.is_device_available("cuda", torch_module=fake) is True
        assert device.cuda_arch_mismatch(torch_module=fake) is None

    def test_a_three_digit_datacentre_arch_is_matched_too(self):
        """``sm_100`` is compute capability 10.0, not 1.0 and not 100."""
        assert device._parse_arch_entry("sm_100") == ("sm", 10, 0)
        fake = _cuda_torch((10, 0), ["sm_90", "sm_100"])
        assert device.is_device_available("cuda", torch_module=fake) is True

    def test_a_higher_minor_cubin_does_not_cover_a_lower_device(self):
        """Binary compatibility runs upwards only, within one major.

        The mirror of test_binary_compatibility_within_a_major_is_honoured:
        an sm_86-only wheel has nothing an sm_80 card can execute. Without
        this, dropping the minor comparison entirely reads as green.
        """
        fake = _cuda_torch((8, 0), ["sm_86"])
        assert device.is_device_available("cuda", torch_module=fake) is False
        assert "sm_80" in device.cuda_arch_status(torch_module=fake).reason

    def test_ptx_does_not_cover_an_older_device(self):
        """PTX JITs forward, never backward."""
        fake = _cuda_torch((7, 0), ["compute_80"])
        assert device.is_device_available("cuda", torch_module=fake) is False

    def test_an_async_launch_failure_surfaces_at_synchronize(self):
        """On real hardware the launch is where a missing cubin is reported.

        ``probe.add_(1)`` returns immediately -- CUDA kernel launches are
        asynchronous -- so the error only lands when the queue is drained.
        The synchronize IS the detector for a build whose arch list is
        absent or inconclusive; without this, deleting it reads as green.
        """
        fake = _cuda_torch((8, 6), PRE_BLACKWELL_ARCHS, sync=MISSING_KERNEL_ERROR)
        assert device.is_device_available("cuda", torch_module=fake) is False
        assert "kernel launch failed" in device.cuda_arch_status(torch_module=fake).reason

    def test_a_transient_failure_at_synchronize_still_fails_open(self):
        """The fail-open rule is pinned on the synchronize phase too."""
        fake = _cuda_torch((8, 6), PRE_BLACKWELL_ARCHS, sync=OOM_ERROR)
        assert device.is_device_available("cuda", torch_module=fake) is True
        assert device.cuda_arch_mismatch(torch_module=fake) is None


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
