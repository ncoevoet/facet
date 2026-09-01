"""Central torch device selection."""

from __future__ import annotations

import os
import re
import shutil
from typing import Any, NamedTuple

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


class CudaArchStatus(NamedTuple):
    """Whether this PyTorch build can actually run kernels on the local GPU.

    ``capability`` and ``arch_list`` are carried so callers can render an
    actionable message; both are empty when the installed torch does not
    expose them. ``reason`` is empty when ``usable`` is True.
    """

    usable: bool
    capability: tuple[int, int] | None
    arch_list: tuple[str, ...]
    reason: str


_ARCH_ENTRY = re.compile(r"^(sm|compute)_(\d+)")


def _parse_arch_entry(entry: str) -> tuple[str, int, int] | None:
    """Split an arch-list entry such as ``sm_86`` into (kind, major, minor)."""
    match = _ARCH_ENTRY.match(str(entry).strip())
    if match is None:
        return None
    digits = match.group(2)
    return match.group(1), int(digits[:-1] or 0), int(digits[-1])


def _arch_entry_covers(entry: str, capability: tuple[int, int]) -> bool:
    """Apply CUDA's own compatibility rules to one arch-list entry.

    A cubin (``sm_XY``) runs on any device of the same major revision whose
    minor is at or above it; PTX (``compute_XY``) is JIT-compiled for any
    device at or above it, across majors.
    """
    parsed = _parse_arch_entry(entry)
    if parsed is None:
        return False
    kind, major, minor = parsed
    if kind == "compute":
        return capability >= (major, minor)
    return capability[0] == major and capability[1] >= minor


def _read_cuda_capability(cuda: Any) -> tuple[int, int] | None:
    """Read the first CUDA device's compute capability, or None if unknowable."""
    get_capability = getattr(cuda, "get_device_capability", None)
    if not callable(get_capability):
        return None
    try:
        major, minor = get_capability(0)
        return int(major), int(minor)
    except Exception:
        return None


def _read_cuda_arch_list(cuda: Any) -> tuple[str, ...]:
    """Read the architectures this torch build ships kernels for, or ()."""
    get_arch_list = getattr(cuda, "get_arch_list", None)
    if not callable(get_arch_list):
        return ()
    try:
        return tuple(str(entry) for entry in get_arch_list())
    except Exception:
        return ()


_PROBE_UNAVAILABLE = "unavailable"
_PROBE_OK = "ok"
_PROBE_ALLOCATION_FAILED = "allocation_failed"
_PROBE_LAUNCH_FAILED = "launch_failed"

_MISSING_KERNEL_SIGNATURES = ("no kernel image", "invalid device function")


def _is_missing_kernel_failure(message: str) -> bool:
    """True for the CUDA runtime errors that a missing cubin produces.

    ``cudaErrorNoKernelImageForDevice`` and ``cudaErrorInvalidDeviceFunction``
    are the only two ways an architecture this build ships no kernels for can
    surface, and both strings come from CUDA's own error table rather than
    from torch. The error class decides, not the phase it surfaced in: a
    missing cubin should only ever reach the launch, but a torch that fills a
    tensor with a kernel would raise it from the allocation instead, and that
    is still an unusable build.

    This allow-lists instead of deny-listing so that an unrecognised failure
    fails open: out of memory, a busy or exclusive-mode device and a driver
    that failed to initialise are all transient or unrelated, and must never
    brand the installed build as wrong.
    """
    lowered = message.lower()
    return any(signature in lowered for signature in _MISSING_KERNEL_SIGNATURES)


def _exception_text(ex: Exception) -> str:
    """The message to report for a probe failure, never an empty string."""
    return str(ex) or ex.__class__.__name__


def _probe_failure_reason(outcome: str, failure: str) -> str:
    """Name the phase that failed, so the diagnosis is not guesswork."""
    phase = "allocation" if outcome == _PROBE_ALLOCATION_FAILED else "kernel launch"
    return f"CUDA {phase} failed: {failure}"


def _probe_cuda_kernel(torch_module: Any) -> tuple[str, str]:
    """Allocate on the GPU, then launch one throwaway kernel on it.

    The two phases are reported separately on purpose. A missing cubin can
    only surface at the launch; an allocation that fails means the card is
    out of memory, busy, in exclusive-compute mode, or driven by a torch
    with no CUDA at all — none of which says anything about the
    architectures this build was compiled for.

    ``_PROBE_UNAVAILABLE`` means the probe could not be attempted, which is
    not evidence of anything and must be treated as unknown.
    """
    zeros = getattr(torch_module, "zeros", None)
    if not callable(zeros):
        return _PROBE_UNAVAILABLE, ""
    try:
        probe = zeros(1, device="cuda")
    except Exception as ex:
        return _PROBE_ALLOCATION_FAILED, _exception_text(ex)
    try:
        probe.add_(1)
        synchronize = getattr(getattr(torch_module, "cuda", None), "synchronize", None)
        if callable(synchronize):
            synchronize()
    except Exception as ex:
        return _PROBE_LAUNCH_FAILED, _exception_text(ex)
    return _PROBE_OK, ""


def _compute_cuda_arch_status(torch_module: Any) -> CudaArchStatus:
    """Combine the static arch comparison with an executed kernel."""
    if not _cuda_is_available(torch_module):
        return CudaArchStatus(False, None, (), "no CUDA device is available")
    cuda = getattr(torch_module, "cuda", None)
    capability = _read_cuda_capability(cuda)
    arch_list = _read_cuda_arch_list(cuda)
    unsupported = (
        capability is not None
        and bool(arch_list)
        and not any(_arch_entry_covers(entry, capability) for entry in arch_list)
    )
    outcome, failure = _probe_cuda_kernel(torch_module)
    if outcome == _PROBE_OK:
        return CudaArchStatus(True, capability, arch_list, "")
    if unsupported:
        return CudaArchStatus(
            False, capability, arch_list,
            f"device sm_{capability[0]}{capability[1]} is not covered by this PyTorch "
            f"build's architectures ({', '.join(arch_list)})",
        )
    if _is_missing_kernel_failure(failure):
        return CudaArchStatus(
            False, capability, arch_list, _probe_failure_reason(outcome, failure)
        )
    return CudaArchStatus(True, capability, arch_list, "")


_cuda_arch_cache: tuple[Any, CudaArchStatus] | None = None


def cuda_arch_status(*, torch_module: Any | None = None) -> CudaArchStatus:
    """Report whether this PyTorch build can run kernels on the local GPU.

    ``torch.cuda.is_available()`` answers "is there a driver and a device",
    never "does this wheel ship kernels for it" — a CUDA 12.6 build on an
    RTX 50-series card (``sm_120``) reports True and then dies on the first
    real op with "no kernel image is available for execution on the device"
    (issue #119). Reading the arch list proves something about the wheel;
    only an executed kernel proves CUDA works on this box, so both run and
    a kernel that runs wins.

    Unknowns fail open: a torch build exposing neither ``get_arch_list`` nor
    a usable allocator is reported usable rather than vetoed, because the
    alternative is disabling GPUs that work. ``usable=False`` needs either a
    definite arch mismatch or a probe that failed with a missing-kernel
    error. A probe that fails any other way — out of memory, a busy or
    exclusive-mode device — is transient and says nothing about the build,
    so it must not demote a whole scan to CPU; the real error is left to
    surface where it always did, at model load.

    Memoised on the torch module because ``is_device_available`` runs from
    hot paths (``clear_device_cache``, ``synchronize_device``).
    """
    global _cuda_arch_cache
    if torch_module is None:
        try:
            torch_module = __import__("torch")
        except ImportError:
            return CudaArchStatus(False, None, (), "PyTorch is not installed")
    cached = _cuda_arch_cache
    if cached is not None and cached[0] is torch_module:
        return cached[1]
    status = _compute_cuda_arch_status(torch_module)
    _cuda_arch_cache = (torch_module, status)
    return status


def cuda_arch_mismatch(*, torch_module: Any | None = None) -> CudaArchStatus | None:
    """Return the status when torch reports a CUDA device it cannot use.

    ``None`` both when there is no CUDA device at all and when the device
    works, so callers can tell "no GPU" apart from "GPU present but this
    build cannot launch a kernel on it".
    """
    if torch_module is None:
        try:
            torch_module = __import__("torch")
        except ImportError:
            return None
    if not _cuda_is_available(torch_module):
        return None
    status = cuda_arch_status(torch_module=torch_module)
    return None if status.usable else status


def _cuda_is_available(torch_module: Any) -> bool:
    """True when torch's own probe reports a device, ignoring arch support."""
    cuda = getattr(torch_module, "cuda", None)
    available = getattr(cuda, "is_available", None)
    try:
        return bool(available()) if callable(available) else False
    except Exception:
        return False


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


def is_device_available(device: str, *, torch_module: Any | None = None) -> bool:
    """Return whether a torch device can be used on this machine."""
    device_type = str(device).split(":", 1)[0].lower()
    if device_type == "cpu":
        return True
    try:
        torch_module = torch_module or __import__("torch")
    except ImportError:
        return False
    if device_type == "cuda":
        if not _cuda_is_available(torch_module):
            return False
        return cuda_arch_status(torch_module=torch_module).usable
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
