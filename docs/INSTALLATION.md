# Installation

## System Requirements

- Python 3.12
- `exiftool` (system package)

### Installing exiftool

| OS | Command |
|----|---------|
| Ubuntu/Debian | `sudo apt install libimage-exiftool-perl` |
| macOS | `brew install exiftool` |
| Windows | Download from [exiftool.org](https://exiftool.org/) |

## Python Environment

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install base dependencies
pip install -r requirements.txt

# For 8gb/16gb/24gb profiles, also install:
pip install transformers>=4.57.0 accelerate>=0.25.0

# For 24gb profile, additionally:
pip install qwen-vl-utils>=0.0.2
```

## GPU Setup

### PyTorch with CUDA

Install from [pytorch.org/get-started/locally](https://pytorch.org/get-started/locally/) based on your CUDA version.

### ONNX Runtime for Face Detection

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
python -c "import torch, cv2, flask, insightface, open_clip, numpy, scipy, sklearn, PIL, imagehash, rawpy, tqdm, exifread; print('All imports successful')"
```

## Dependencies Summary

### Required Packages

| Package | Purpose |
|---------|---------|
| `torch`, `torchvision` | Deep learning framework |
| `open-clip-torch` | CLIP model for tagging and aesthetics |
| `opencv-python` | Image processing |
| `pillow` | Image loading |
| `imagehash` | Perceptual hashing for burst detection |
| `rawpy` | RAW file support |
| `flask` | Web viewer |
| `numpy` | Numerical operations |
| `tqdm` | Progress bars |
| `exifread` | EXIF metadata extraction |
| `insightface` | Face detection and recognition |
| `scipy` | Scientific computing |
| `scikit-learn` | Machine learning utilities |
| `hdbscan` | Face clustering algorithm |

### Profile-Specific Packages

| Profile | Additional Packages |
|---------|---------------------|
| `8gb`+ | `transformers>=4.57.0`, `accelerate>=0.25.0` |
| `24gb` | `qwen-vl-utils>=0.0.2` |

### Optional Packages

| Package | Purpose |
|---------|---------|
| `cuml`, `cupy` | GPU-accelerated face clustering (requires conda + CUDA) |
| `onnxruntime-gpu` | GPU-accelerated face detection |

## First Run

On first run, Facet automatically downloads:
- CLIP model (ViT-L-14): ~1.7GB
- InsightFace buffalo_l model: ~400MB
- SAMP-Net weights (all profiles): ~50MB

Models are cached in standard locations (`~/.cache/` or `~/.insightface/`).

### SAMP-Net Manual Download

The automatic download for SAMP-Net weights may fail (the GitHub release URL is no longer available). If you see:
```
Failed to download SAMP-Net weights: HTTP Error 404: Not Found
```

Download manually:
1. Download from [Google Drive](https://drive.google.com/file/d/1sIcYr5cQGbxm--tCGaASmN0xtE_r-QUg/view)
2. Place the file at `pretrained_models/samp_net.pth`
