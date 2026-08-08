"""Tests for runtime CPU/CUDA/Apple Metal device policy."""

from __future__ import annotations

import os
import sys
import types

import pytest

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
