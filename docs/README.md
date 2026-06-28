# Facet

> 🌐 **English** · [Français](fr/README.md) · [Deutsch](de/README.md) · [Italiano](it/README.md) · [Español](es/README.md) · [Português](pt/README.md)

Photo quality assessment that analyzes images using CLIP, TOPIQ, SAMP-Net, InsightFace, and OpenCV to rate photos on aesthetics, face quality, technical sharpness, color, exposure, and composition.

## Features

- **Multi-model scoring** - TOPIQ (0.93 SRCC) or CLIP+MLP aesthetic assessment, with configurable VRAM profiles
- **Semantic tagging** - auto-generated tags using CLIP (landscape, portrait, sunset, etc.)
- **Face recognition** - detection, quality scoring, blink detection, and person clustering via HDBSCAN
- **Composition analysis** - SAMP-Net (14 patterns) or rule-based scoring
- **Technical analysis** - sharpness, color, exposure, dynamic range, noise, contrast
- **Category system** - 30+ content categories with category-specific scoring weights
- **Web gallery** - FastAPI + Angular SPA with filtering, sorting, face recognition, and pairwise comparison
- **Batch processing** - continuous-streaming GPU batching with auto-tuned batch sizes

## Quick Start

```bash
# Install dependencies
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Score photos
python facet.py /path/to/photos

# View results
python viewer.py
# Open http://localhost:5000
```

## Documentation

| Document | Description |
|----------|-------------|
| [Installation](INSTALLATION.md) | Requirements, GPU setup, dependencies |
| [Commands](COMMANDS.md) | All CLI commands reference |
| [Configuration](CONFIGURATION.md) | Full `scoring_config.json` reference |
| [Scoring](SCORING.md) | Categories, weights, tuning guide |
| [Face Recognition](FACE_RECOGNITION.md) | Face workflow, clustering, person management |
| [Viewer](VIEWER.md) | Web gallery features and usage |
| [Deployment](DEPLOYMENT.md) | Production deployment (Synology NAS, Linux, Docker) |

## VRAM Profiles

| Profile | GPU VRAM | Models | Best For |
|---------|----------|--------|----------|
| `legacy` | No GPU | CLIP+MLP + SAMP-Net + CLIP tagging (CPU) | No GPU, 8GB+ RAM |
| `8gb` | 6-14GB | CLIP+MLP + SAMP-Net + CLIP tagging | Mid-range GPUs |
| `16gb` | 16GB+ | TOPIQ + SAMP-Net + Qwen3.5-2B | Best aesthetic accuracy |
| `24gb` | 24GB+ | TOPIQ + Qwen2-VL + Qwen3.5-4B | Best accuracy + composition explanations |

## Supported File Types

- **JPEG** (.jpg, .jpeg)
- **HEIF/HEIC** (.heic, .heif) — requires `pillow-heif`
- **RAW files** (.cr2, .cr3, .nef, .arw, .raf, .rw2, .dng, .orf, .srw, .pef) - skipped if matching JPEG/HEIC exists

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "externally-managed-environment" | Use virtual environment |
| Slow processing | Check VRAM profile, use `--single-pass` for high-VRAM GPUs |
| Face detection not using GPU | Install `onnxruntime-gpu` |
| Missing exiftool | Optional — install via system package manager for best results, otherwise `exifread` handles all RAW formats |

See [Installation](INSTALLATION.md) for detailed setup instructions.
