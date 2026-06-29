"""Central torch device selection."""

from __future__ import annotations

import os
import shutil


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

    Currently CUDA→CPU only. MPS (Apple Silicon) is detected separately via
    `mps_available()` for diagnostics, but Facet does not route torch models
    to MPS yet — see issue #7. Returning 'mps' here would silently break
    InsightFace (ONNX CUDAExecutionProvider) and several other torch paths
    that have not been validated on Metal.
    """
    try:
        import torch
    except ImportError:
        return "cpu"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def mps_available() -> bool:
    """True iff PyTorch reports Apple Silicon MPS is available.

    Used by `--doctor` to report MPS presence. Does NOT influence runtime
    device selection (see `get_device()`).
    """
    try:
        import torch
    except ImportError:
        return False
    backends = getattr(torch, "backends", None)
    mps = getattr(backends, "mps", None) if backends is not None else None
    is_available = getattr(mps, "is_available", None) if mps is not None else None
    return bool(is_available()) if callable(is_available) else False
