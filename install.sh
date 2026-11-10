#!/usr/bin/env bash
# Facet — automated installation script
# Usage: bash install.sh [--cpu] [--cuda VERSION] [--skip-client] [--no-uv] [--commercial]
set -euo pipefail

# --- Defaults ---
FORCE_CPU=0
CUDA_OVERRIDE=""
SKIP_CLIENT=0
NO_UV=0
COMMERCIAL=0

# --- Parse args ---
while [[ $# -gt 0 ]]; do
    case "$1" in
        --cpu)        FORCE_CPU=1; shift ;;
        --cuda)       CUDA_OVERRIDE="$2"; shift 2 ;;
        --skip-client) SKIP_CLIENT=1; shift ;;
        --no-uv)      NO_UV=1; shift ;;
        --commercial) COMMERCIAL=1; shift ;;
        -h|--help)
            echo "Usage: bash install.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --cpu           Force CPU-only PyTorch (no CUDA)"
            echo "  --cuda VERSION  Override detected CUDA version (e.g. --cuda 12.8)"
            echo "  --skip-client   Skip Angular frontend build"
            echo "  --no-uv         Use pip instead of uv"
            echo "  --commercial    Commercial-safe install: skip insightface/pyiqa/onnxruntime,"
            echo "                  install mediapipe (--no-deps). Does NOT edit your config: it"
            echo "                  prints the licensing.mode=commercial setting to add yourself"
            echo "  -h, --help      Show this help"
            exit 0
            ;;
        *)  echo "Unknown option: $1"; exit 1 ;;
    esac
done

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
warn() { echo -e "  ${YELLOW}!${NC} $1"; }
err()  { echo -e "  ${RED}✗${NC} $1"; }
info() { echo -e "  ${BLUE}→${NC} $1"; }

echo ""
echo -e "${BLUE}╔══════════════════════════════════╗${NC}"
echo -e "${BLUE}║        Facet — Installer         ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════╝${NC}"
echo ""

# Check the frontend toolchain before modifying the Python environment. Angular
# 22 needs Node 24.15+, and this checkout supports the Node 24 LTS line.
if [[ "$SKIP_CLIENT" -eq 0 && -f "client/package.json" ]]; then
    node_version="$(node --version 2>/dev/null || true)"
    if ! command -v npm &>/dev/null ||
       [[ ! "$node_version" =~ ^v24\.([0-9]+)\.([0-9]+)$ ]] ||
       [[ "${BASH_REMATCH[1]:-0}" -lt 15 ]]; then
        err "Node.js 24.15.0+ (24.x) and npm are required to build the frontend."
        err "Install Node 24 LTS, or pass --skip-client to keep the existing build."
        exit 1
    fi
    ok "Node: $node_version"
fi

# --- Step 1: Find Python ---
PYTHON=""
for cmd in python3.12 python3.13 python3.11 python3.10 python3 python; do
    if command -v "$cmd" &>/dev/null; then
        version=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || true)
        major=$("$cmd" -c "import sys; print(sys.version_info.major)" 2>/dev/null || true)
        minor=$("$cmd" -c "import sys; print(sys.version_info.minor)" 2>/dev/null || true)
        if [[ "$major" == "3" && "$minor" -ge 10 ]]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [[ -z "$PYTHON" ]]; then
    err "Python 3.10+ not found. Install Python 3.12 from https://python.org"
    exit 1
fi
ok "Python: $($PYTHON --version)"

# --- Step 2: Virtual environment ---
if [[ -n "${VIRTUAL_ENV:-}" ]]; then
    ok "Virtual environment: $VIRTUAL_ENV"
else
    if [[ ! -d "venv" ]]; then
        info "Creating virtual environment..."
        $PYTHON -m venv venv
    fi
    source venv/bin/activate
    ok "Virtual environment: $VIRTUAL_ENV"
fi

# --- Step 3: Install uv (or fall back to pip) ---
INSTALLER="pip"
if [[ "$NO_UV" -eq 0 ]]; then
    if command -v uv &>/dev/null; then
        INSTALLER="uv pip"
        ok "Package installer: uv ($(uv --version))"
    else
        info "Installing uv for faster dependency resolution..."
        if pip install uv &>/dev/null; then
            INSTALLER="uv pip"
            ok "Package installer: uv"
        else
            warn "Could not install uv, falling back to pip"
        fi
    fi
else
    ok "Package installer: pip (--no-uv)"
fi
# uv's uninstall has no -y (it never prompts); pip's needs it. Both exit 0 when a
# name is not installed, which the ONNX Runtime swap below relies on.
if [[ "$INSTALLER" == "uv pip" ]]; then
    UNINSTALLER="uv pip uninstall"
else
    UNINSTALLER="pip uninstall -y"
fi

# --- Step 4: Detect GPU / CUDA ---
CUDA_VERSION=""
TORCH_INDEX=""
# Lowest GPU compute capability. Only the nvidia-smi branch below measures it; it
# is initialised here because `--cuda VERSION` skips that branch and the ladder
# reads it under `set -u`.
GPU_MIN_ARCH=""
ONNX_PACKAGE="onnxruntime>=1.15.0"
# onnxruntime-gpu is split by CUDA major on PyPI: 1.19-1.26 are CUDA 12 builds and
# 1.27 onwards are CUDA 13 builds, which cannot load beside the CUDA 12 PyTorch
# (cu124/cu126/cu128) installed below. The ONNX Runtime major follows PyTorch's CUDA
# build, never the driver's CUDA version. CUDA 11 (cu118) has no working GPU build and
# keeps the CPU one. Keep in step with utils/onnx_runtime.py
# (tests/test_onnx_runtime_install_consistency.py fails when they drift).
ORT_GPU_CUDA12="onnxruntime-gpu>=1.19.0,<1.27"
HOST_OS="$(uname -s)"
HOST_ARCH="$(uname -m)"
APPLE_MPS=0

if [[ "$FORCE_CPU" -eq 1 ]]; then
    info "CPU-only mode (--cpu)"
    if [[ "$HOST_OS" != "Darwin" ]]; then
        TORCH_INDEX="https://download.pytorch.org/whl/cpu"
    else
        warn "macOS has no CPU-only PyTorch wheel — the unified wheel includes the Metal (MPS) backend"
        warn "  To disable acceleration at runtime, set FACET_DEVICE=cpu when running Facet"
    fi
elif [[ -n "$CUDA_OVERRIDE" ]]; then
    CUDA_VERSION="$CUDA_OVERRIDE"
    info "CUDA version override: $CUDA_VERSION"
elif [[ "$HOST_OS" == "Darwin" && "$HOST_ARCH" == "arm64" ]]; then
    APPLE_MPS=1
    ok "Apple Silicon detected: PyTorch Metal (MPS) acceleration enabled"
else
    # Auto-detect via nvidia-smi
    if command -v nvidia-smi &>/dev/null; then
        # Newer drivers label the field "CUDA UMD Version" (beside a "KMD Version"), older ones
        # "CUDA Version"; matching only the old label ended on CPU torch with a GPU present.
        CUDA_VERSION=$(nvidia-smi 2>/dev/null | grep -oP 'CUDA (UMD )?Version: \K[0-9.]+' | head -1 || true)
        # The wheel has to cover the WEAKEST installed card, and the driver's
        # CUDA version says nothing about it: a GTX 1080 (sm_61) behind driver
        # 570 reports "CUDA Version: 12.8" just like an RTX 5090 does. Empty
        # when nvidia-smi predates --query-gpu=compute_cap (or cannot initialise NVML, so the
        # grep matches nothing and pipefail would abort the script), in which case the ladder
        # below falls back to the driver version alone.
        GPU_MIN_ARCH=$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>/dev/null \
            | tr -d '[:blank:]' | grep -E '^[0-9]+\.[0-9]+$' | sort -V | head -1 || true)
        if [[ -n "$CUDA_VERSION" ]]; then
            ok "CUDA detected: $CUDA_VERSION"
            [[ -n "$GPU_MIN_ARCH" ]] && info "Lowest GPU compute capability: $GPU_MIN_ARCH"
        else
            warn "nvidia-smi found but could not parse CUDA version — using CPU"
        fi
    else
        info "No nvidia-smi found — installing CPU-only PyTorch"
    fi
fi

# Map CUDA version to PyTorch index URL
if [[ -n "$CUDA_VERSION" ]]; then
    cuda_major=$(echo "$CUDA_VERSION" | cut -d. -f1)
    cuda_minor=$(echo "$CUDA_VERSION" | cut -d. -f2)

    # cu128 wheels ship sm_75 upwards and DROP sm_50/sm_60/sm_70, so a Maxwell,
    # Pascal or Volta card on a modern driver would install a build with no
    # kernels for it and die with "no kernel image is available for execution on
    # the device" -- issue #119 all over again, from the other direction. cu126
    # still carries sm_50...sm_90. This is the bare-metal twin of the
    # latest-cuda / latest-cuda-legacy image split.
    arch_needs_legacy_wheel=0
    if [[ -n "$GPU_MIN_ARCH" ]]; then
        arch_major=$(echo "$GPU_MIN_ARCH" | cut -d. -f1)
        arch_minor=$(echo "$GPU_MIN_ARCH" | cut -d. -f2)
        if [[ "$arch_major" -lt 7 ]] || [[ "$arch_major" -eq 7 && "$arch_minor" -lt 5 ]]; then
            arch_needs_legacy_wheel=1
        fi
    fi

    if [[ "$arch_needs_legacy_wheel" -eq 1 ]]; then
        TORCH_INDEX="https://download.pytorch.org/whl/cu126"
        ONNX_PACKAGE="$ORT_GPU_CUDA12"
        ok "PyTorch variant: cu126 (pre-Turing GPU, compute capability $GPU_MIN_ARCH)"
        info "cu128 ships no kernels below sm_75 — pinned to cu126 despite CUDA $CUDA_VERSION"
    elif [[ "$cuda_major" -ge 13 ]] || [[ "$cuda_major" -eq 12 && "$cuda_minor" -ge 8 ]]; then
        TORCH_INDEX="https://download.pytorch.org/whl/cu128"
        ONNX_PACKAGE="$ORT_GPU_CUDA12"
        ok "PyTorch variant: cu128"
    elif [[ "$cuda_major" -eq 12 && "$cuda_minor" -ge 6 ]]; then
        TORCH_INDEX="https://download.pytorch.org/whl/cu126"
        ONNX_PACKAGE="$ORT_GPU_CUDA12"
        ok "PyTorch variant: cu126"
    elif [[ "$cuda_major" -eq 12 && "$cuda_minor" -ge 4 ]]; then
        TORCH_INDEX="https://download.pytorch.org/whl/cu124"
        ONNX_PACKAGE="$ORT_GPU_CUDA12"
        ok "PyTorch variant: cu124"
    elif [[ "$cuda_major" -eq 12 ]] || [[ "$cuda_major" -eq 11 && "$cuda_minor" -ge 8 ]]; then
        TORCH_INDEX="https://download.pytorch.org/whl/cu118"
        ok "PyTorch variant: cu118"
        # The only onnxruntime-gpu for CUDA 11 (1.17) links libcudnn.so.8, while the cu118
        # PyTorch wheels depend on cuDNN 9, so its CUDA provider never loads: ONNX_PACKAGE
        # stays the CPU build instead of installing a GPU wheel that silently runs on the CPU.
        info "No onnxruntime-gpu build matches this PyTorch's CUDA 11.8 + cuDNN 9; face detection runs on the CPU — update the NVIDIA driver to one reporting CUDA 12.4+ for GPU face detection"
    else
        warn "CUDA $CUDA_VERSION is too old — using CPU-only PyTorch"
        TORCH_INDEX="https://download.pytorch.org/whl/cpu"
    fi
elif [[ -z "$TORCH_INDEX" && "$APPLE_MPS" -eq 0 && "$HOST_OS" != "Darwin" ]]; then
    TORCH_INDEX="https://download.pytorch.org/whl/cpu"
fi

# Every onnxruntime-gpu wheel the pins above can select (1.15-1.26) is published for
# x86_64 only; PyPI's aarch64 GPU wheels start at 1.29, which are CUDA 13 builds. Keep the
# CPU build there instead of letting the install abort on a missing wheel; everything
# below keys off ONNX_PACKAGE, so the swap and the verify step follow.
if [[ "$ONNX_PACKAGE" == onnxruntime-gpu* && "$HOST_ARCH" != "x86_64" ]]; then
    info "No CUDA 12 onnxruntime-gpu wheel exists for $HOST_ARCH — keeping CPU onnxruntime (face detection runs on the CPU)"
    ONNX_PACKAGE="onnxruntime>=1.15.0"
fi

# --- Step 5: Install PyTorch ---
info "Installing PyTorch..."
if [[ -n "$TORCH_INDEX" ]]; then
    $INSTALLER install torch torchvision --index-url "$TORCH_INDEX"
else
    # PyPI supplies the native macOS wheel with its MPS backend.
    $INSTALLER install torch torchvision
fi
ok "PyTorch installed"

# --- Step 6: Install project dependencies ---
info "Installing Facet dependencies..."
if [[ "$COMMERCIAL" -eq 0 ]]; then
    # Default: base + restricted (insightface, pyiqa) — the full feature set.
    $INSTALLER install -r requirements.txt -r requirements.restricted.txt
else
    # Commercial: base only. mediapipe MUST go in with --no-deps (its bundled
    # opencv-contrib-python would double-install the cv2 namespace), then its
    # real runtime deps separately.
    $INSTALLER install -r requirements.txt
    $INSTALLER install mediapipe==0.10.35 --no-deps
    $INSTALLER install absl-py flatbuffers
fi
ok "Dependencies installed"

# --- Step 7: Install transformers + accelerate (needed for 8gb+ profiles) ---
info "Installing transformers + accelerate..."
$INSTALLER install "transformers>=5.3.0,<5.16" "accelerate>=0.25.0"
ok "Transformers installed"

# --- Step 8: Install ONNX Runtime (insightface only; skipped with --commercial) ---
# Deliberately the LAST install that resolves dependencies: insightface (requirements.restricted.txt) requires
# the plain CPU `onnxruntime`, and the CPU and GPU distributions install into the same
# onnxruntime/ tree, so whichever pip installs last wins. Installing the GPU build before
# the dependencies left it overwritten by the CPU one (issue #229). Both names are
# uninstalled first, whichever variant follows, because uninstalling only the CPU one
# would remove files the GPU wheel shares with it, and installing one variant over a venv
# holding the other (a re-run with --cpu over a GPU venv, or the reverse) would leave both.
if [[ "$COMMERCIAL" -eq 0 ]]; then
    info "Installing ONNX Runtime ($ONNX_PACKAGE) last: insightface pulls the CPU build and would overwrite the GPU one..."
    $UNINSTALLER onnxruntime onnxruntime-gpu
    $INSTALLER install "$ONNX_PACKAGE"
    ok "ONNX Runtime installed"
else
    info "Skipping ONNX Runtime (--commercial: insightface is not installed)"
fi

# --- Step 9: Keep only the headless OpenCV build (every mode, commercial included) ---
# opencv-python and opencv-python-headless install into the same cv2/ directory, so whichever
# pip installs last wins, exactly as with the two ONNX Runtime distributions above. The
# requirements ask for both: requirements.txt for opencv-python, pyiqa for the headless one,
# insightface and facexlib for opencv-python again, so the build left providing cv2 follows
# install order. The GUI build links libGL.so.1, which Debian/WSL and slim hosts do not have,
# and `import cv2` then fails with an ImportError. Facet calls no OpenCV GUI function (no
# imshow, waitKey or namedWindow), so the headless build is always enough. This runs after
# every install that can pull opencv-python (steps 6, 7 and 8) and, being --no-deps, cannot pull
# the CPU onnxruntime back in over step 8. Both names are uninstalled first, for the reason
# step 8 gives: uninstalling only one would remove files the other shares. requirements.txt
# carries opencv-python in --commercial mode too, so there is no mode check. The version is
# the headless one's when it is installed, else opencv-python's; nothing is touched when
# neither distribution is installed.
CV_VER=$($PYTHON -c '
import importlib.metadata as metadata
for name in ("opencv-python-headless", "opencv-python"):
    try:
        print(metadata.version(name))
        break
    except metadata.PackageNotFoundError:
        pass
' 2>/dev/null || true)
if [[ -n "$CV_VER" ]]; then
    info "Keeping only OpenCV headless $CV_VER: the GUI build needs libGL, which many hosts lack..."
    $UNINSTALLER opencv-python opencv-python-headless
    $INSTALLER install --no-deps "opencv-python-headless==$CV_VER"
    ok "OpenCV installed (opencv-python-headless $CV_VER)"
else
    info "Skipping the OpenCV swap (no OpenCV distribution is installed)"
fi

# --- Step 10: Check exiftool ---
echo ""
if command -v exiftool &>/dev/null; then
    ok "exiftool: $(exiftool -ver)"
else
    warn "exiftool not found (optional but recommended for best EXIF extraction)"
    echo "     Install: sudo apt install libimage-exiftool-perl  (Debian/Ubuntu)"
    echo "              brew install exiftool                    (macOS)"
fi

# --- Step 11: Build Angular client ---
# Build away from the served tree so a failed dependency install or compilation
# cannot destroy the working frontend. Keep the previous tree until publication
# succeeds; if restoration itself fails, leave its path available for recovery.
build_angular_client() (
    client_root="$(cd client && pwd -P)"
    build_dir="$(mktemp -d "$client_root/.facet-build.XXXXXX")"
    published=0
    cleanup_client_build() {
        if [[ "$published" -eq 1 || ! -e "$build_dir/previous" && ! -L "$build_dir/previous" ]]; then
            rm -rf -- "$build_dir"
        else
            warn "Previous frontend retained at $build_dir/previous; restore it to $client_root/dist/client"
        fi
    }
    trap cleanup_client_build EXIT
    cd "$client_root"
    npm ci --no-audit --no-fund
    npm run build -- --output-path "$build_dir/client"
    if [[ ! -f "$build_dir/client/browser/index.html" ]]; then
        err "Angular build did not produce browser/index.html"
        exit 1
    fi
    mkdir -p "$client_root/dist"
    if [[ -e "$client_root/dist/client" || -L "$client_root/dist/client" ]]; then
        mv -- "$client_root/dist/client" "$build_dir/previous"
    fi
    if ! mv -- "$build_dir/client" "$client_root/dist/client"; then
        if [[ -e "$build_dir/previous" || -L "$build_dir/previous" ]]; then
            mv -- "$build_dir/previous" "$client_root/dist/client"
        fi
        err "Could not publish the frontend build"
        exit 1
    fi
    published=1
)

if [[ "$SKIP_CLIENT" -eq 0 ]]; then
    if [[ -f "client/package.json" ]]; then
        info "Building Angular frontend (Node $node_version)..."
        build_angular_client
        ok "Angular client built"
    fi
else
    info "Skipping Angular build (--skip-client)"
fi

# --- Step 12: Verify imports ---
echo ""
info "Verifying installation..."
CORE_IMPORTS="torch, cv2, fastapi, open_clip, numpy, scipy, PIL, imagehash, rawpy, tqdm, exifread"
if [[ "$COMMERCIAL" -eq 0 ]]; then
    CORE_IMPORTS="$CORE_IMPORTS, insightface"
fi
IMPORTS_FAILED=0
if $PYTHON -c "import $CORE_IMPORTS; cv2.__version__" 2>/dev/null; then
    ok "All core imports successful"
else
    IMPORTS_FAILED=1
    err "Some imports failed — run 'python facet.py --doctor' for diagnostics"
fi

# A GPU install must end on the CUDA build of ONNX Runtime, alone, and actually running on
# it: a CUDA 13 wheel or a cuDNN mismatch still LISTS the provider, then falls back to the
# CPU when a session is created. So this runs diagnostics.verify_onnx_runtime from the repo
# root, which creates the same one-node CUDA session `python facet.py --doctor` does (and
# takes the fix text from utils/onnx_runtime.py, so it has exactly one source). It prints a
# report and exits with one of four codes, which tests/test_onnx_runtime_install_consistency.py
# keeps in step with VERIFY_* in diagnostics.py:
#   0  a CUDA test session runs on CUDAExecutionProvider
#   3  the provider is listed and onnxruntime-gpu is alone, but no session could be created
#      (PyTorch sees no GPU on this machine, or the onnx package is missing)
#   1  ONNX Runtime is not on CUDA (broken, doubled, CPU-only, or the session fell back)
#   2  the check itself could not run (anything else, a crash included)
# Only 1 is a verdict about the install; 2 says so without guessing at one.
report_lines() {  # report_lines PRINTER TEXT: the first line through PRINTER, the rest indented under it
    local printer="$1" line first=1
    while IFS= read -r line; do
        if [[ "$first" -eq 1 ]]; then "$printer" "$line"; first=0; else echo "       $line"; fi
    done <<< "$2"
}
if [[ "$COMMERCIAL" -eq 0 && "$ONNX_PACKAGE" == onnxruntime-gpu* ]]; then
    ort_rc=0
    ORT_REPORT=$($PYTHON -c '
import sys
try:
    from diagnostics import verify_onnx_runtime
except Exception as ex:
    print("%s: %s" % (type(ex).__name__, ex))
    sys.exit(2)
sys.exit(verify_onnx_runtime())
' 2>/dev/null) || ort_rc=$?
    case "$ort_rc" in
        0|3) report_lines ok "ONNX Runtime: $ORT_REPORT" ;;
        1) report_lines err "ONNX Runtime is not running on CUDA, so face detection will use the CPU:"$'\n'"$ORT_REPORT" ;;
        *)
            report_lines warn "Could not check whether ONNX Runtime runs on CUDA (the check itself failed, so this is not a verdict):"$'\n'"${ORT_REPORT:-exit code $ort_rc, no output}"
            echo "       run 'python facet.py --doctor' to check it"
            ;;
    esac
fi

# --- Commercial mode: licensing.mode is configuration, not an install side effect ---
if [[ "$COMMERCIAL" -eq 1 ]]; then
    echo ""
    info "Commercial install: enable commercial mode in your scoring_config.json override:"
    echo '       { "licensing": { "mode": "commercial" } }'
    echo "     (or export FACET_LICENSING_MODE=commercial). Check with: python facet.py --doctor"
fi

# --- Summary ---
# A failed core import is not a finished install: exit non-zero (after the checks above have
# all had their say) so a script or CI step wrapping install.sh sees the failure.
if [[ "$IMPORTS_FAILED" -eq 1 ]]; then
    echo ""
    echo -e "${RED}══════════════════════════════════${NC}"
    echo -e "${RED}  Installation finished with errors${NC}"
    echo -e "${RED}══════════════════════════════════${NC}"
    echo ""
    echo "  Some core imports failed (see above). Activate the venv and run:"
    echo ""
    echo "    source venv/bin/activate         # macOS/Linux"
    echo "    python facet.py --doctor"
    echo ""
    exit 1
fi
echo ""
echo -e "${GREEN}══════════════════════════════════${NC}"
echo -e "${GREEN}  Installation complete!${NC}"
echo -e "${GREEN}══════════════════════════════════${NC}"
echo ""
echo "  Next steps:"
echo ""
echo "    # Activate the venv (install.sh ran in a subshell — your shell doesn't see it)"
echo "    source venv/bin/activate         # macOS/Linux"
echo "    # .\\venv\\Scripts\\Activate.ps1   # Windows PowerShell"
echo ""
echo "    # Check your setup"
echo "    python facet.py --doctor"
echo ""
echo "    # Score photos"
echo "    python facet.py /path/to/photos"
echo ""
echo "    # Start the web viewer"
echo "    python viewer.py"
echo ""
