#!/usr/bin/env bash
# Facet — automated installation script
# Usage: bash install.sh [--cpu] [--cuda VERSION] [--skip-client] [--no-uv]
set -euo pipefail

# --- Defaults ---
FORCE_CPU=0
CUDA_OVERRIDE=""
SKIP_CLIENT=0
NO_UV=0

# --- Parse args ---
while [[ $# -gt 0 ]]; do
    case "$1" in
        --cpu)        FORCE_CPU=1; shift ;;
        --cuda)       CUDA_OVERRIDE="$2"; shift 2 ;;
        --skip-client) SKIP_CLIENT=1; shift ;;
        --no-uv)      NO_UV=1; shift ;;
        -h|--help)
            echo "Usage: bash install.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --cpu           Force CPU-only PyTorch (no CUDA)"
            echo "  --cuda VERSION  Override detected CUDA version (e.g. --cuda 12.8)"
            echo "  --skip-client   Skip Angular frontend build"
            echo "  --no-uv         Use pip instead of uv"
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

# --- Step 4: Detect GPU / CUDA ---
CUDA_VERSION=""
TORCH_INDEX=""
ONNX_PACKAGE="onnxruntime>=1.15.0"
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
        CUDA_VERSION=$(nvidia-smi 2>/dev/null | grep -oP 'CUDA Version: \K[0-9.]+' || true)
        if [[ -n "$CUDA_VERSION" ]]; then
            ok "CUDA detected: $CUDA_VERSION"
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

    if [[ "$cuda_major" -ge 13 ]] || [[ "$cuda_major" -eq 12 && "$cuda_minor" -ge 8 ]]; then
        TORCH_INDEX="https://download.pytorch.org/whl/cu128"
        ONNX_PACKAGE="onnxruntime-gpu>=1.17.0"
        ok "PyTorch variant: cu128"
    elif [[ "$cuda_major" -eq 12 && "$cuda_minor" -ge 4 ]]; then
        TORCH_INDEX="https://download.pytorch.org/whl/cu124"
        ONNX_PACKAGE="onnxruntime-gpu>=1.17.0"
        ok "PyTorch variant: cu124"
    elif [[ "$cuda_major" -eq 12 ]] || [[ "$cuda_major" -eq 11 && "$cuda_minor" -ge 8 ]]; then
        TORCH_INDEX="https://download.pytorch.org/whl/cu118"
        ONNX_PACKAGE="onnxruntime-gpu>=1.15.0,<1.18"
        ok "PyTorch variant: cu118"
    else
        warn "CUDA $CUDA_VERSION is too old — using CPU-only PyTorch"
        TORCH_INDEX="https://download.pytorch.org/whl/cpu"
    fi
elif [[ -z "$TORCH_INDEX" && "$APPLE_MPS" -eq 0 && "$HOST_OS" != "Darwin" ]]; then
    TORCH_INDEX="https://download.pytorch.org/whl/cpu"
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

# --- Step 6: Install ONNX Runtime ---
info "Installing ONNX Runtime ($ONNX_PACKAGE)..."
$INSTALLER install "$ONNX_PACKAGE"
ok "ONNX Runtime installed"

# --- Step 7: Install project dependencies ---
info "Installing Facet dependencies..."
$INSTALLER install -r requirements.txt
ok "Dependencies installed"

# --- Step 8: Install transformers + accelerate (needed for 8gb+ profiles) ---
info "Installing transformers + accelerate..."
$INSTALLER install "transformers>=5.3.0,<5.16" "accelerate>=0.25.0"
ok "Transformers installed"

# --- Step 9: Check exiftool ---
echo ""
if command -v exiftool &>/dev/null; then
    ok "exiftool: $(exiftool -ver)"
else
    warn "exiftool not found (optional but recommended for best EXIF extraction)"
    echo "     Install: sudo apt install libimage-exiftool-perl  (Debian/Ubuntu)"
    echo "              brew install exiftool                    (macOS)"
fi

# --- Step 10: Build Angular client ---
if [[ "$SKIP_CLIENT" -eq 0 ]]; then
    if [[ -f "client/package.json" && ! -d "client/dist" ]]; then
        if command -v node &>/dev/null && command -v npm &>/dev/null; then
            node_version=$(node --version)
            info "Building Angular frontend (Node $node_version)..."
            (cd client && npm install --no-audit --no-fund && npx ng build)
            ok "Angular client built"
        else
            warn "Node.js not found — skipping Angular build"
            echo "     Install Node 18+ to build the frontend, or use --skip-client"
        fi
    elif [[ -d "client/dist" ]]; then
        ok "Angular client: already built"
    fi
else
    info "Skipping Angular build (--skip-client)"
fi

# --- Step 11: Verify imports ---
echo ""
info "Verifying installation..."
if $PYTHON -c "import torch, cv2, fastapi, insightface, open_clip, numpy, scipy, PIL, imagehash, rawpy, tqdm, exifread" 2>/dev/null; then
    ok "All core imports successful"
else
    err "Some imports failed — run 'python facet.py --doctor' for diagnostics"
fi

# --- Summary ---
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
