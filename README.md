# Facet

**Your photos deserve more than a star rating.** Facet is a local photo analysis engine that scores every image across 9 dimensions — from aesthetic appeal to face sharpness — then lets you browse, cull, and organize through an interactive web gallery. No cloud, no subscriptions, no API keys. Your photos stay on your machine.

![Python](https://img.shields.io/badge/python-3.10+-blue)
![Angular](https://img.shields.io/badge/Angular-20-dd0031)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux%20%7C%20Docker-lightgrey)
![License](https://img.shields.io/badge/license-MIT-green)
![PyPI](https://img.shields.io/pypi/v/facet-photo)

<p align="center">
  <img src="docs/screenshots/hero-mosaic.jpg" alt="Facet — Top Picks mosaic gallery" width="100%">
</p>

## How It Works

1. **Scan** — Point Facet at a folder of photos. AI models analyze each image for quality, composition, faces, and more. Supports JPG and 10 RAW formats (CR2, CR3, NEF, ARW, RAF, RW2, DNG, ORF, SRW, PEF).
2. **Browse** — Open the web gallery to explore your library with filters, search, and multiple view modes.
3. **Cull** — Find your best shots instantly. Facet auto-detects bursts, flags blinks, groups similar photos, and highlights top picks.

Everything runs 100% locally. GPU is auto-detected and optional — Facet adapts to your hardware from CPU-only to 24 GB VRAM.

## Features

### Score

AI models analyze every photo across 9 scoring dimensions: aesthetic quality, composition, face quality, eye sharpness, technical sharpness, color, exposure, subject saliency, and dynamic range. Each photo is automatically categorized (portrait, landscape, macro, street, etc. — 17 categories) and scored with category-specific weights. A **Top Picks** filter surfaces your best photos across the library.

Hover over any photo for a detailed tooltip with the full score breakdown and EXIF data.

<img src="docs/screenshots/hover-tooltip.jpg" alt="Hover tooltip with score breakdown" width="100%">

### Cull

Dedicated tools to find your keepers fast:

- **Burst detection** — groups rapid-fire shots and auto-selects the best one based on sharpness, quality, and blink detection
- **Similarity groups** — finds visually similar photos across your entire library, regardless of when they were taken
- **Blink detection** — flags closed-eye shots so you can hide or reject them in one click
- **Duplicate detection** — identifies near-identical images via perceptual hashing

<img src="docs/screenshots/burst-culling.jpg" alt="Burst culling" width="100%">

### Browse

Multiple ways to explore your library:

- **Gallery modes** — mosaic (justified rows preserving aspect ratios) and grid (uniform cards with metadata overlay)
- **Filters** — date range, content tag, composition pattern, camera, lens, person, quality level, star rating, and custom metric ranges
- **Semantic search** — type a natural-language query like "sunset on the beach" or "child playing in snow" and find matching photos
- **Timeline** — chronological browser with year/month navigation and infinite scroll
- **Map** — browse geotagged photos on an interactive map with marker clustering
- **Capsules** — AI-curated themed slideshows: journeys with place names, golden collection, seasonal palettes, moments with a person, and more
- **Folders** — browse by directory structure with breadcrumb navigation and cover photos
- **Memories** — "On This Day" retrospective showing photos from the same date in previous years
- **Slideshow** — full-screen mode with themed transitions, auto-chaining between capsules, and keyboard controls

<table><tr>
<td><img src="docs/screenshots/filter-panel.jpg" alt="Filter sidebar" width="100%"></td>
<td><img src="docs/screenshots/semantic-search.jpg" alt="Semantic search results" width="100%"></td>
</tr></table>

### Organize

- **Face recognition** — automatic face detection, grouping into persons, and blink detection. Search, rename, merge, and organize person clusters from the management UI. **Merge suggestions** find similar-looking clusters that may be the same person.
- **Albums** — manual collections with drag-and-drop, or smart albums that auto-populate from saved filter combinations
- **Ratings & favorites** — star ratings (1–5), favorites, and reject flags. Cycle through ratings with a single click.
- **Tags** — AI-generated content tags with configurable vocabulary. Click any tag to filter the gallery.
- **Batch operations** — multi-select with Shift+click and Ctrl+click. Set ratings, toggle favorites, mark rejects, or add to albums in bulk.

<table><tr>
<td><img src="docs/screenshots/persons-manage.jpg" alt="Manage Persons page" width="100%"></td>
<td><img src="docs/screenshots/person-gallery.jpg" alt="Person gallery" width="100%"></td>
</tr></table>

### Understand

- **Statistics** — interactive dashboards: equipment usage, category breakdown, shooting timeline, and custom metric correlations
- **AI critique** — detailed score breakdown showing each metric's contribution. VLM-powered natural-language assessment available with 16+ GB VRAM.
- **Weight tuning** — per-category weight editor with live score preview. A/B photo comparison learns from your choices and suggests optimized weights.
- **Snapshots** — save, restore, and compare weight configurations
- **AI captions** — natural-language photo descriptions, editable and translatable to 5 languages

<table><tr>
<td><img src="docs/screenshots/stats-gear.jpg" alt="Equipment statistics" width="100%"></td>
<td><img src="docs/screenshots/stats-categories.jpg" alt="Category analytics" width="100%"></td>
</tr></table>

<table><tr>
<td><img src="docs/screenshots/critique.jpg" alt="AI Critique dialog" width="100%"></td>
<td><img src="docs/screenshots/snapshots.jpg" alt="Snapshots" width="100%"></td>
</tr></table>

<table><tr>
<td><img src="docs/screenshots/weights-sliders.jpg" alt="Category weight sliders" width="100%"></td>
<td><img src="docs/screenshots/weights-compare.jpg" alt="A/B photo comparison" width="100%"></td>
</tr></table>

### Share

- **Album sharing** — generate shareable links for any album, no login required for recipients. Revoke access at any time.
- **Photo download** — download individual photos or selections from the gallery
- **Export** — export all scores to CSV or JSON for external analysis

### More

- **Dark & light mode** with 10 accent color themes, respects system preference
- **Responsive** — adapts from mobile to desktop
- **5 languages** — English, French, German, Spanish, Italian
- **Multi-user** — per-user directories, ratings, and role-based access for family NAS setups
- **Plugins & webhooks** — extend Facet with custom actions on scoring events
- **Scan from web UI** — trigger photo scanning directly from the browser (superadmin role)

<table><tr>
<td width="33%"><img src="docs/screenshots/mobile-gallery.jpg" alt="Mobile gallery" width="100%"></td>
<td width="33%"><img src="docs/screenshots/tablet-gallery.jpg" alt="Tablet gallery" width="100%"></td>
<td width="33%"><img src="docs/screenshots/gallery-mosaic.jpg" alt="Desktop mosaic" width="100%"></td>
</tr></table>

## Quick Start

### Docker (recommended)

```bash
docker compose up
# Open http://localhost:5000
```

GPU acceleration requires the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html). Mount your photos directory in `docker-compose.yml`.

### Manual Install

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
bash install.sh          # auto-detects GPU, creates venv, installs everything
python facet.py /photos  # score photos
python viewer.py         # start web viewer → http://localhost:5000
```

The install script auto-detects your CUDA version, installs the right PyTorch variant, builds the Angular frontend, and verifies all imports. Options: `--cpu` (force CPU), `--cuda 12.8` (override CUDA version), `--skip-client` (skip frontend build).

<details>
<summary>Step-by-step manual install</summary>

```bash
# 1. Install exiftool (optional but recommended)
# Ubuntu/Debian: sudo apt install libimage-exiftool-perl
# macOS:         brew install exiftool

# 2. Create virtual environment
python -m venv venv && source venv/bin/activate

# 3. Install PyTorch with CUDA (pick your version at https://pytorch.org/get-started/locally)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128

# 4. Install Python dependencies (all at once — see Troubleshooting if you hit conflicts)
pip install -r requirements.txt

# 5. Install ONNX Runtime for face detection (choose ONE)
pip install onnxruntime-gpu>=1.17.0   # GPU (CUDA 12.x)
# pip install onnxruntime>=1.15.0     # CPU fallback

# 6. Build Angular frontend
cd client && npm ci && npx ng build && cd ..

# 7. Score photos and start viewer
python facet.py /path/to/photos
python viewer.py
```
</details>

### PyPI

```bash
pip install facet-photo
facet /path/to/photos        # Score photos
facet-viewer                 # Start the web viewer
facet-doctor                 # Diagnose GPU issues
```

Run `python facet.py --doctor` to diagnose GPU issues. See [Installation](docs/INSTALLATION.md) for VRAM profiles, VLM tagging packages (16gb/24gb), optional dependencies, and [dependency troubleshooting](docs/INSTALLATION.md#troubleshooting-dependency-conflicts).

## Documentation

| Document | Description |
|----------|-------------|
| [Installation](docs/INSTALLATION.md) | Requirements, GPU setup, VRAM profiles, dependencies |
| [Commands](docs/COMMANDS.md) | All CLI commands reference |
| [Configuration](docs/CONFIGURATION.md) | Full `scoring_config.json` reference |
| [Scoring](docs/SCORING.md) | Categories, weights, tuning guide |
| [Face Recognition](docs/FACE_RECOGNITION.md) | Face workflow, clustering, person management |
| [Viewer](docs/VIEWER.md) | Web gallery features and usage |
| [Deployment](docs/DEPLOYMENT.md) | Production deployment (Synology NAS, Linux, Docker) |
| [Contributing](CONTRIBUTING.md) | Development setup, architecture, code style |

## License

[MIT](LICENSE)
