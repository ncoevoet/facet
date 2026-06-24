# Installation

> 🌐 **English** · [Français](fr/INSTALLATION.md) · [Deutsch](de/INSTALLATION.md) · [Italiano](it/INSTALLATION.md) · [Español](es/INSTALLATION.md)

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

# Install PyTorch first with the correct CUDA index URL.
# cu128 targets CUDA 12.8+/13.x; for CUDA 11.8 use cu118, for CUDA 12.4 use cu124.
# When unsure, pick the matching command at https://pytorch.org/get-started/locally/
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
| `psutil` | Batch-processing auto-tuning (system monitoring) |
| `aiosqlite` | Async SQLite for FastAPI read endpoints |
| `sqlite-vec` | On-disk KNN for semantic search & similarity (falls back to in-memory NumPy cache if missing) |

All of these are in `requirements.txt`; no profile needs extra base packages.

### Optional Packages

Each unlocks a feature; without it the feature is skipped or a fallback is used.

| Package | Unlocks / purpose | Without it |
|---------|-------------------|-----------|
| `watchdog` | Watch mode (`--watch` daemon re-scans new files) — **not in `requirements.txt`**; only pulled via `pip install .[watch]`, so direct `requirements.txt` users don't get `--watch` | `--watch` unavailable |
| `pillow-heif` | HEIF/HEIC decode | HEIF/HEIC files skipped |
| `rawpy` | RAW decode (CR2/CR3/NEF/ARW/…) | RAW files skipped (already in base `requirements.txt`) |
| `cuml`, `cupy` | GPU-accelerated face clustering (conda + CUDA) | Clustering runs on CPU via `hdbscan` (default) |
| `onnxruntime-gpu` | GPU-accelerated face detection | CPU `onnxruntime` (slower) |
| `aesthetic-predictor-v2-5`, `bitsandbytes` | Extended IQA tier (`pip install -e .[iqa-extended]`; `iqa_extended` in `scoring_config.json`, off by default) | Extended IQA metrics unavailable |
| `darktable-cli` (system) | RAW/darktable profile export from the viewer | Only original/embedded download offered |
| `exiftool` (system) | Best EXIF/GPS extraction | Falls back to `exifread`, then PIL |

## Feature requirements

Most of Facet runs anywhere (CPU, any profile). Some features need a GPU, a higher **VRAM profile**, an optional package, or the viewer's **edition password** / **superadmin** role. Tags used throughout the docs:
`[GPU]` · `[16gb/24gb]` (VRAM profile) · `[Edition]` · `[Superadmin]` · `[Optional: pkg]`.

| Feature | GPU | Profile | Auth | Optional package |
|---------|:---:|---------|:----:|------------------|
| Scoring / scan (baseline) | optional | any (`legacy` = CPU) | — | — |
| TOPIQ aesthetic | yes | `16gb`/`24gb` | — | — |
| Supplementary IQA (TOPIQ IAA, NR-Face, LIQE) | yes | `8gb`/`16gb`/`24gb` | — | — |
| SigLIP 2 embeddings | yes | `16gb`/`24gb` | — | — |
| VLM tagging (Qwen3.5) | yes | `16gb`/`24gb` | — | — |
| Composition pattern (SAMP-Net) | optional | any (`legacy` = CPU) | — | — |
| Composition (Qwen2-VL) | yes | `24gb` | — | — |
| Subject saliency (BiRefNet) | yes | `16gb`/`24gb` | — | — |
| AI captions (generate / view) | yes | `16gb`/`24gb` | — | — |
| AI captions (edit) | yes | `16gb`/`24gb` | edition | — |
| VLM critique | yes | `16gb`/`24gb` | — | — |
| Face detection / extraction (InsightFace) | recommended (CPU works, slow) | any | — | — |
| Face clustering (HDBSCAN) | no (CPU) | any | — | `cuml`/`cupy` (optional GPU accel) |
| Semantic search | no | any | — | `sqlite-vec` (falls back to NumPy) |
| RAW / HEIF decode | no | any | — | `rawpy` / `pillow-heif` |
| Watch mode (`--watch`) | no | any | — | `watchdog` |
| GPS extract / darktable export | no | any | — | `exiftool` / `darktable-cli` |
| Ratings, favorites, face & person edits, culling | no | any | edition | — |
| Trigger scans from the web UI | no | any | superadmin | — |
| Multi-user (per-user ratings & roles) | no | any | role-based | — |

> Face *clustering* runs on CPU by default (standalone `hdbscan`); `cuml`/`cupy` only add optional GPU acceleration — they are **not** required. The edition password and user roles are configured in `scoring_config.json` — see [Configuration](CONFIGURATION.md) for auth.

## Troubleshooting Dependency Conflicts

Facet has many ML dependencies (`torch`, `open-clip-torch`, `insightface`, etc.) that pull in their own transitive dependencies. pip resolves dependencies sequentially, which can lead to cascading errors where installing one package breaks another.

### Symptoms

- Installing packages one-by-one triggers errors asking you to install yet another package
- Version conflicts between `torch`, `numpy`, `huggingface-hub`, or `open-clip-torch`
- `pip install` succeeds but `import` fails at runtime

### Solutions

**1. Install everything at once** — `pip install -r requirements.txt` gives pip the full dependency graph to solve. Don't install packages individually (`pip install open-clip-torch && pip install insightface && ...`); that prevents pip from resolving the full graph.

**2. Use [uv](https://docs.astral.sh/uv/) instead of pip** — `uv` resolves the complete dependency graph upfront before installing anything, avoiding cascading conflicts:

```bash
# Install uv
pip install uv

# Install all dependencies with full resolution
uv pip install -r requirements.txt

# With CUDA index for PyTorch:
uv pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cu128
```

**3. Start fresh** — if your environment is already in a broken state, `deactivate`, `rm -rf venv`, and rebuild it by re-running the [Python Environment](#python-environment) steps above.

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

On first run, Facet automatically downloads the embedding model for your profile:
- CLIP ViT-L-14 (legacy/8gb profiles): ~1.7GB — or SigLIP 2 NaFlex SO400M (16gb/24gb profiles), larger
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

SAMP-Net weights download automatically on first use from the project's model-weights release (`github.com/ncoevoet/facet/releases/download/model-weights-v1/samp_net.pth`). No manual step is normally required.

If the automatic download fails (e.g. offline or network-restricted) you'll see:
```
Failed to download SAMP-Net weights: HTTP Error 404: Not Found
```

Then download manually:
1. Download `samp_net.pth` from the [model-weights-v1 release](https://github.com/ncoevoet/facet/releases/download/model-weights-v1/samp_net.pth) (or, as a secondary fallback, [Google Drive](https://drive.google.com/file/d/1sIcYr5cQGbxm--tCGaASmN0xtE_r-QUg/view))
2. Place the file at `pretrained_models/samp_net.pth`
