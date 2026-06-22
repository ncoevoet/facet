# Installation

## Quick Start

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
bash install.sh          # auto-detects GPU, creates venv, installs everything

# Activate the venv that install.sh created — the install script can't do this
# for you because it runs in a subshell.
source venv/bin/activate         # macOS/Linux
# .\venv\Scripts\Activate.ps1    # Windows PowerShell

python facet.py --doctor # verify your setup
```

`install.sh` creates the venv, detects GPU/CUDA, installs PyTorch with the matching index URL, the right ONNX Runtime variant, the rest of the dependencies, and builds the Angular frontend.

**Options:**
| Flag | Effect |
|------|--------|
| `--cpu` | Force CPU-only PyTorch (no CUDA) |
| `--cuda VERSION` | Override detected CUDA version (e.g. `--cuda 12.8`) |
| `--skip-client` | Skip Angular frontend build |
| `--no-uv` | Use pip instead of uv |

A `Makefile` is also available: `make install`, `make install-cpu`, `make run`, `make doctor`.

---

## Manual Installation

### System Requirements

- Python 3.12 (3.10+ supported)
- `exiftool` (system package, optional but recommended)

#### Installing exiftool

exiftool provides the best EXIF extraction for all formats. Without it, the app falls back to `exifread` (Python library, handles all RAW formats) then PIL (JPEG/TIFF/DNG only).

| OS | Command |
|----|---------|
| Ubuntu/Debian | `sudo apt install libimage-exiftool-perl` |
| macOS | `brew install exiftool` |
| Windows | Download from [exiftool.org](https://exiftool.org/) |

### Python Environment

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install PyTorch first with the correct CUDA index URL
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128

# Install dependencies (all at once for proper dependency resolution).
# requirements.txt already includes transformers and accelerate, needed for
# the SigLIP/BiRefNet/VLM models used by the 8gb+ profiles.
pip install -r requirements.txt
```

> **Hitting dependency errors?** See [Troubleshooting Dependency Conflicts](#troubleshooting-dependency-conflicts) below.

### GPU Setup

#### PyTorch with CUDA

Install from [pytorch.org/get-started/locally](https://pytorch.org/get-started/locally/) based on your CUDA version. The install script does this automatically.

#### ONNX Runtime for Face Detection

Choose ONE based on your setup:

| Option | Command |
|--------|---------|
| CPU only | `pip install onnxruntime>=1.15.0` |
| CUDA 12.x | `pip install onnxruntime-gpu>=1.17.0` |
| CUDA 11.8 | `pip install onnxruntime-gpu>=1.15.0,<1.18` |

**Check your CUDA version:** Run `nvidia-smi` and look at the top-right corner for "CUDA Version: X.X".

If switching from CPU to GPU version:
```bash
pip uninstall onnxruntime
pip install onnxruntime-gpu>=1.17.0
```

### RAPIDS cuML for GPU Face Clustering (Optional)

For large face databases (80K+ faces), GPU-accelerated clustering via cuML significantly speeds up face clustering. Requires conda environment:

```bash
# Create conda environment with CUDA support
conda create -n facet python=3.12
conda activate facet

# Install cuML (choose your CUDA version)
conda install -c rapidsai -c conda-forge -c nvidia cuml cuda-version=12.0

# Alternative: pip install
pip install --extra-index-url https://pypi.nvidia.com/ "cuml-cu12"

# Install other dependencies
pip install -r requirements.txt
```

When cuML is available, face clustering automatically uses GPU (configurable via `face_clustering.use_gpu` in `scoring_config.json`).

## Verify Installation

```bash
python -c "import torch, cv2, fastapi, insightface, open_clip, pyiqa, numpy, scipy, sklearn, PIL, imagehash, rawpy, tqdm, exifread; print('All imports successful')"
```

## Dependencies Summary

### Required Packages

| Package | Purpose |
|---------|---------|
| `torch`, `torchvision` | Deep learning framework (installed separately, see above) |
| `open-clip-torch` | CLIP embeddings/tagging (legacy/8gb profiles) |
| `pyiqa` | TOPIQ and other quality/aesthetic models |
| `opencv-python` | Image processing |
| `pillow` | Image loading |
| `imagehash` | Perceptual hashing for burst detection |
| `rawpy` | RAW file support |
| `fastapi`, `uvicorn` | API server |
| `pyjwt` | JWT authentication |
| `numpy` | Numerical operations |
| `tqdm` | Progress bars |
| `exifread` | EXIF metadata extraction |
| `insightface` | Face detection and recognition |
| `transformers`, `accelerate` | SigLIP/BiRefNet/VLM models (8gb+ profiles) |
| `scipy` | Scientific computing |
| `hdbscan` | Face clustering (pulls in scikit-learn) |
| `reverse_geocoder` | Reverse geocoding for GPS |

All of these are in `requirements.txt`; no profile needs extra base packages.

### Optional Packages

Each unlocks a feature; without it the feature is skipped or a fallback is used.

| Package | Unlocks / purpose | Without it |
|---------|-------------------|-----------|
| `sqlite-vec>=0.1.6` | On-disk KNN for semantic search & similarity | Falls back to in-memory NumPy embedding cache |
| `watchdog` | Watch mode (`--watch` daemon re-scans new files) | `--watch` unavailable |
| `pillow-heif` | HEIF/HEIC decode | HEIF/HEIC files skipped |
| `rawpy` | RAW decode (CR2/CR3/NEF/ARW/…) | RAW files skipped (already in base `requirements.txt`) |
| `cuml`, `cupy` | GPU-accelerated face clustering (conda + CUDA) | Clustering runs on CPU via `hdbscan` (default) |
| `onnxruntime-gpu` | GPU-accelerated face detection | CPU `onnxruntime` (slower) |
| `aesthetic-predictor-v2-5`, `bitsandbytes` | Extended IQA tier (`pip install -e .[iqa-extended]`; `iqa_extended` in `scoring_config.json`, off by default) | Extended IQA metrics unavailable |
| `darktable-cli` (system) | RAW/darktable profile export from the viewer | Only original/embedded download offered |
| `exiftool` (system) | Best EXIF/GPS extraction | Falls back to `exifread`, then PIL |

## Troubleshooting Dependency Conflicts

Facet has many ML dependencies (`torch`, `open-clip-torch`, `insightface`, etc.) that pull in their own transitive dependencies. pip resolves dependencies sequentially, which can lead to cascading errors where installing one package breaks another.

### Symptoms

- Installing packages one-by-one triggers errors asking you to install yet another package
- Version conflicts between `torch`, `numpy`, `huggingface-hub`, or `open-clip-torch`
- `pip install` succeeds but `import` fails at runtime

### Solutions

**1. Install everything at once** — gives pip the full dependency graph to solve:

```bash
pip install -r requirements.txt
```

Do **not** install packages individually (`pip install open-clip-torch && pip install insightface && ...`) — this prevents pip from resolving the full graph.

**2. Use [uv](https://docs.astral.sh/uv/) instead of pip** — `uv` resolves the complete dependency graph upfront before installing anything, avoiding cascading conflicts:

```bash
# Install uv
pip install uv

# Install all dependencies with full resolution
uv pip install -r requirements.txt

# With CUDA index for PyTorch:
uv pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cu128
```

**3. Start fresh** — if your environment is already in a broken state:

```bash
deactivate
rm -rf venv
python3 -m venv venv && source venv/bin/activate
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
pip install -r requirements.txt
```

### GPU Detection Issues

If your GPU is not detected (common with newer GPUs like RTX 5070 Ti), run the diagnostic tool:

```bash
python facet.py --doctor
```

This checks PyTorch CUDA support, driver compatibility, and suggests the correct pip install command. You can also simulate GPU scenarios for testing:

```bash
python facet.py --doctor --simulate-gpu "RTX 5070 Ti" --simulate-vram 16
```

## First Run

On first run, Facet automatically downloads:
- CLIP model (ViT-L-14): ~1.7GB
- InsightFace buffalo_l model: ~400MB
- SAMP-Net weights (all profiles): ~50MB

Models are cached in standard locations (`~/.cache/` or `~/.insightface/`).

## Angular Client (Optional)

Only needed for development or custom builds; `install.sh` already builds it.

```bash
cd client
npm install
npm run build    # Production build → client/dist/
npm start        # Dev server on http://localhost:4200 (proxies API to :5000)
```

> **`npm audit` warnings:** Angular pulls in a deep transitive dependency tree
> and `npm audit` will report findings most of which are in build-time dev
> dependencies that never reach the browser. Review the list before running
> `npm audit fix` — it can silently downgrade or remove packages.

> **macOS port 5000:** ControlCenter's AirPlay Receiver listens on 5000 by
> default. Start the viewer with `python viewer.py --port 5001` (or set the
> `PORT` env var) to avoid the conflict.

### SAMP-Net Manual Download

The automatic download for SAMP-Net weights may fail (the GitHub release URL is no longer available). If you see:
```
Failed to download SAMP-Net weights: HTTP Error 404: Not Found
```

Download manually:
1. Download from [Google Drive](https://drive.google.com/file/d/1sIcYr5cQGbxm--tCGaASmN0xtE_r-QUg/view)
2. Place the file at `pretrained_models/samp_net.pth`
