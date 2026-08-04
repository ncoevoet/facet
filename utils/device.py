"""Central torch device selection."""

from __future__ import annotations

import os
import shutil

# Let PyTorch execute individual unsupported MPS operators on CPU.  This must be
# set before torch initialises its MPS backend, so keep it in this lightweight
# module and import this module before torch in Facet's lazy loaders.
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

_DEVICE_ENV = "FACET_DEVICE"
_VALID_DEVICES = {"auto", "cpu", "cuda", "mps"}


def detect_c_compiler() -> str | None:
    """Return the path to a usable C compiler (honouring ``$CC``), or None.

    torch.compile's inductor backend shells out to a C compiler the first
    time a compiled module runs inference. Minimal Docker GPU images often
    ship ``torch`` + CUDA but no ``gcc``/``g++``, so the failure surfaces
    lazily on every image instead of at startup (issue #15). Probe up-front
    so callers can fall back to eager execution honestly.
    """
    return (
        shutil.which(os.environ.get("CC") or "cc")
        or shutil.which("gcc")
        or shutil.which("g++")
    )


def torch_compile_status() -> tuple[bool, str]:
    """Decide whether torch.compile should be enabled, with a human reason.

    Returns ``(enabled, reason)``. Honours ``TORCH_COMPILE_DISABLE`` and the
    presence of a C compiler. Callers add their own device/platform gating
    (CUDA-only, not Windows) before consulting this.
    """
    if os.environ.get("TORCH_COMPILE_DISABLE"):
        return False, "TORCH_COMPILE_DISABLE is set"
    if not detect_c_compiler():
        return False, "no C compiler (gcc/g++) found"
    return True, "C compiler available"


def get_device() -> str:
    """Return the torch device string Facet should run on.

    Automatic selection prefers CUDA, then Apple Metal (MPS), then CPU. Set
    ``FACET_DEVICE`` to ``cpu``, ``cuda``, or ``mps`` for a deterministic
    override (useful for benchmarking). An unavailable forced accelerator is
    an error rather than a silent fallback.
    """
    requested = os.environ.get(_DEVICE_ENV, "auto").strip().lower()
    if requested not in _VALID_DEVICES:
        valid = ", ".join(sorted(_VALID_DEVICES))
        raise ValueError(f"Invalid {_DEVICE_ENV}={requested!r}; expected one of: {valid}")

    try:
        import torch
    except ImportError:
        if requested not in {"auto", "cpu"}:
            raise RuntimeError(
                f"{_DEVICE_ENV}={requested} was requested, but PyTorch is not installed"
            )
        return "cpu"

    if requested != "auto":
        if is_device_available(requested, torch_module=torch):
            return requested
        raise RuntimeError(
            f"{_DEVICE_ENV}={requested} was requested, but that device is not available"
        )

    if is_device_available("cuda", torch_module=torch):
        return "cuda"
    if is_device_available("mps", torch_module=torch):
        return "mps"
    return "cpu"


def is_device_available(device: str, *, torch_module=None) -> bool:
    """Return whether a torch device can be used on this machine."""
    device_type = str(device).split(":", 1)[0].lower()
    if device_type == "cpu":
        return True
    try:
        torch_module = torch_module or __import__("torch")
    except ImportError:
        return False
    if device_type == "cuda":
        cuda = getattr(torch_module, "cuda", None)
        available = getattr(cuda, "is_available", None)
        try:
            return bool(available()) if callable(available) else False
        except Exception:
            return False
    if device_type == "mps":
        backends = getattr(torch_module, "backends", None)
        mps = getattr(backends, "mps", None) if backends is not None else None
        available = getattr(mps, "is_available", None) if mps is not None else None
        try:
            return bool(available()) if callable(available) else False
        except Exception:
            return False
    return False


def mps_available() -> bool:
    """True iff PyTorch reports Apple Silicon MPS is available."""
    return is_device_available("mps")


def clear_device_cache(device: str | None = None) -> None:
    """Release unused allocator memory for CUDA or MPS, when supported."""
    try:
        import torch
    except ImportError:
        return
    device_type = (device or get_device()).split(":", 1)[0]
    if device_type == "cuda" and is_device_available("cuda", torch_module=torch):
        empty_cache = getattr(torch.cuda, "empty_cache", None)
    elif device_type == "mps" and is_device_available("mps", torch_module=torch):
        empty_cache = getattr(getattr(torch, "mps", None), "empty_cache", None)
    else:
        empty_cache = None
    if callable(empty_cache):
        empty_cache()


def synchronize_device(device: str | None = None) -> None:
    """Wait for queued accelerator work, primarily for accurate benchmarks."""
    try:
        import torch
    except ImportError:
        return
    device_type = (device or get_device()).split(":", 1)[0]
    if device_type == "cuda" and is_device_available("cuda", torch_module=torch):
        synchronize = getattr(torch.cuda, "synchronize", None)
    elif device_type == "mps" and is_device_available("mps", torch_module=torch):
        synchronize = getattr(getattr(torch, "mps", None), "synchronize", None)
    else:
        synchronize = None
    if callable(synchronize):
        synchronize()
