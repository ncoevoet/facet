# Facet

AI-powered photo quality assessment system that analyzes images using CLIP, TOPIQ, SAMP-Net, InsightFace, and OpenCV to rate photos on aesthetics, face quality, technical sharpness, color harmony, exposure, and composition.

## Features

- **Multi-Model Scoring** - TOPIQ (0.93 SRCC) or CLIP+MLP aesthetic assessment with configurable VRAM profiles
- **Semantic Tagging** - Auto-generated tags using CLIP (landscape, portrait, sunset, etc.)
- **Face Recognition** - Detection, quality scoring, blink detection, and person clustering via HDBSCAN
- **Composition Analysis** - SAMP-Net neural network (14 patterns) or rule-based scoring
- **Technical Analysis** - Sharpness, color harmony, exposure, dynamic range, noise, contrast
- **Category System** - 17 content categories with specialized scoring weights
- **Web Gallery** - FastAPI + Angular SPA with filtering, sorting, face recognition, and pairwise comparison
- **Batch Processing** - ~4x faster GPU inference with auto-tuning and continuous streaming

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

## VRAM Profiles

| Profile | GPU VRAM | Models | Best For |
|---------|----------|--------|----------|
| `legacy` | No GPU | CLIP+MLP + SAMP-Net + CLIP tagging (CPU) | No GPU, 8GB+ RAM |
| `8gb` | 6-14GB | CLIP+MLP + SAMP-Net + Qwen3-VL | Mid-range GPUs |
| `16gb` | 16GB+ | TOPIQ + SAMP-Net + Qwen3-VL | Best aesthetic accuracy |
| `24gb` | 24GB+ | TOPIQ + Qwen2-VL + Qwen2.5-VL-7B | Best accuracy + composition explanations |

## Supported File Types

- **JPEG** (.jpg, .jpeg)
- **Canon RAW** (.cr2, .cr3) - skipped if matching JPEG exists

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "externally-managed-environment" | Use virtual environment |
| Slow processing | Check VRAM profile, use `--single-pass` for high-VRAM GPUs |
| Face detection not using GPU | Install `onnxruntime-gpu` |
| Missing exiftool | Install via system package manager |

See [Installation](INSTALLATION.md) for detailed setup instructions.
