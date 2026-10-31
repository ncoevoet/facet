"""Which ONNX Runtime build a CUDA PyTorch needs, and the command that installs it (issue #229).

``onnxruntime`` and ``onnxruntime-gpu`` install into the same ``onnxruntime/``
tree, so whichever pip installs last wins, and ``insightface`` hard-requires the
CPU one. On top of that ``onnxruntime-gpu`` is split by CUDA major on PyPI: the
1.19-1.26 wheels are CUDA 12 builds and 1.27 onwards are CUDA 13 builds, which
cannot load beside the CUDA 12 PyTorch that Facet installs. The ONNX Runtime
major has to follow the PyTorch CUDA build, never the driver's CUDA version.

CUDA 11 has no GPU wheel that works. The only CUDA 11 build (1.17 and earlier)
links ``libcudnn.so.8``, while the PyTorch cu118 wheels Facet installs depend on
cuDNN 9 (``nvidia-cudnn-cu11==9.1.0.70``), so its CUDA provider never loads. A
CUDA 11 PyTorch therefore keeps the CPU ``onnxruntime``.

This module owns that mapping and the repair text so the doctor, the scan
warning, ``install.sh``'s verify step and the consistency tests share one copy.
It imports neither torch, onnx nor onnxruntime: the doctor and the scan warning
must be able to describe a broken ONNX Runtime without importing it.
"""

import importlib.metadata
import platform

ORT_DISTRIBUTIONS = ("onnxruntime", "onnxruntime-gpu")

# Machines that have a CUDA 12 onnxruntime-gpu wheel. The aarch64 GPU wheels exist
# only for 1.29 and later, which are CUDA 13 builds.
GPU_WHEEL_MACHINES = frozenset({"x86_64", "amd64"})
ARM64_MACHINES = frozenset({"aarch64", "arm64"})

GPU_REQUIREMENT_CUDA12 = "onnxruntime-gpu>=1.19.0,<1.27"
GPU_REQUIREMENT_CUDA13 = "onnxruntime-gpu>=1.27.0"

CPU_REPAIR_COMMAND = 'pip uninstall -y onnxruntime onnxruntime-gpu && pip install "onnxruntime>=1.15.0"'


def installed_distributions():
    """Names of the ONNX Runtime distributions pip has installed, CPU build first."""
    found = []
    for name in ORT_DISTRIBUTIONS:
        try:
            importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            continue
        found.append(name)
    return found


def cuda_major(version):
    """The major of a CUDA version string (``"12.6"`` gives 12), or None when absent or unparsable."""
    if not version:
        return None
    try:
        return int(str(version).split(".")[0])
    except ValueError:
        return None


def cuda_mismatch(ort_cuda, torch_cuda):
    """The sentence naming an ONNX Runtime wheel built for another CUDA major than PyTorch, else "".

    Empty when the majors match or either version is absent (the CPU wheel has no
    ``cuda_version``), so the caller can append it unconditionally.
    """
    ort_major = cuda_major(ort_cuda)
    if ort_major is None or ort_major == cuda_major(torch_cuda):
        return ""
    return f"onnxruntime is built for CUDA {ort_cuda} but PyTorch uses CUDA {torch_cuda}"


def gpu_requirement(torch_cuda):
    """The ``onnxruntime-gpu`` requirement for a PyTorch CUDA version, or None when no GPU wheel works.

    ``torch_cuda`` is ``torch.version.cuda``: None on a CPU build and on ROCm,
    whose torch still reports the ``cuda`` device but carries no CUDA version.
    CUDA 11 gets None as well: its only ``onnxruntime-gpu`` needs cuDNN 8 (see the
    module docstring), so the CPU build is the working one there.
    """
    major = cuda_major(torch_cuda)
    if major is None or major < 12:
        return None
    if major == 12:
        return GPU_REQUIREMENT_CUDA12
    return GPU_REQUIREMENT_CUDA13


def _machine(machine):
    return (machine or platform.machine()).lower()


def repair_command(torch_cuda, machine=None):
    """Shell command that leaves exactly the ONNX Runtime build this PyTorch can use, or None.

    The matching ``onnxruntime-gpu`` on a machine that has a wheel for it; the CPU
    build for a CUDA 11 PyTorch, whose cuDNN 9 no ``onnxruntime-gpu`` matches. None
    when there is nothing to repair towards: no CUDA version on the PyTorch build,
    or a machine with no CUDA 12 wheel (it keeps the CPU build already). Uninstalling
    both names first is what makes the swap safe, because the two distributions own
    the same shared libraries.
    """
    major = cuda_major(torch_cuda)
    if major is None:
        return None
    if major < 12:
        return CPU_REPAIR_COMMAND
    if _machine(machine) not in GPU_WHEEL_MACHINES:
        return None
    return f'pip uninstall -y onnxruntime onnxruntime-gpu && pip install "{gpu_requirement(torch_cuda)}"'


def _cuda11_hint(torch_cuda):
    return (f"no onnxruntime-gpu build matches this PyTorch's CUDA {torch_cuda} with cuDNN 9 (the only CUDA 11 "
            "build needs cuDNN 8), so InsightFace stays on the CPU. "
            f"To repair a broken install back to the CPU build: {CPU_REPAIR_COMMAND}. "
            "For GPU face detection, update the NVIDIA driver to one reporting CUDA 12.4 or newer "
            "and re-run install.sh")


def _no_wheel_hint(major, machine):
    """Why this machine gets no onnxruntime-gpu, for a PyTorch CUDA 12 or later."""
    if machine in ARM64_MACHINES:
        if major == 12:
            return (f"no onnxruntime-gpu wheel built for CUDA 12 exists for {machine} (its GPU wheels start at "
                    "1.29 and are CUDA 13 builds); InsightFace stays on the CPU here")
        return (f"Facet installs no onnxruntime-gpu for {machine}: its CUDA 13 wheels start at 1.29 and are "
                "not validated with Facet; InsightFace stays on the CPU here")
    return (f"no onnxruntime-gpu wheel built for CUDA {major} exists for {machine}; "
            "InsightFace stays on the CPU here")


def repair_hint(torch_cuda, machine=None):
    """One sentence for the doctor and the scan warning: the fix, or why none applies."""
    major = cuda_major(torch_cuda)
    if major is None:
        return "ONNX Runtime CUDA does not apply: this PyTorch build reports no CUDA version (CPU or ROCm)"
    if major < 12:
        return _cuda11_hint(torch_cuda)
    command = repair_command(torch_cuda, machine)
    if command is not None:
        return f"Fix: {command}"
    return _no_wheel_hint(major, _machine(machine))
