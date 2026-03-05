# Facet

**A local-first photo analysis engine that scores, categorizes, and surfaces your best photos using an ensemble of vision models.**

Point Facet at a directory of photos. Local AI models analyze every image across multiple dimensions — aesthetic quality, composition, face detail, technical precision — store scores in a SQLite database, and serve results through an interactive web gallery. Everything runs locally, no cloud, no API keys.

![Python](https://img.shields.io/badge/python-3.10+-blue)
![Angular](https://img.shields.io/badge/Angular-20-dd0031)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux%20%7C%20Docker-lightgrey)
![License](https://img.shields.io/badge/license-MIT-green)

<p align="center">
  <img src="docs/screenshots/hero-mosaic.jpg" alt="Facet — Top Picks mosaic gallery" width="100%">
</p>

## Features

### Gallery

Two view modes to browse your library:

- **Mosaic** — justified rows that preserve aspect ratios for an edge-to-edge layout
- **Grid** — uniform card grid with optional metadata overlay showing filename, score, date, EXIF, tags, and recognized faces

<img src="docs/screenshots/gallery-grid.jpg" alt="Grid mode with photo details" width="100%">

Hover over any photo for a detailed tooltip with the full score breakdown (quality, composition, technical metrics) and EXIF data.

<img src="docs/screenshots/hover-tooltip.jpg" alt="Hover tooltip with score breakdown" width="100%">

### Filters & Search

Filter by date range, content tag, composition pattern, camera, lens, person, and more. Toggle display options like hiding blinks, best-of-burst, duplicates, and rejected photos. Add custom range filters on any metric.

<img src="docs/screenshots/filter-panel.jpg" alt="Filter sidebar" width="100%">

### Find Similar

Select any photo and find visually similar images across your library. Three similarity modes: visual embedding, color palette, and same-person matching. Adjustable similarity threshold.

<img src="docs/screenshots/similar-photos.jpg" alt="Find Similar results" width="100%">

### Face Recognition

Automatic face detection with InsightFace, HDBSCAN clustering into person groups, and blink detection. The management UI lets you search, rename, merge, and organize person clusters. Filter the gallery by person to browse all photos of someone.

<table><tr>
<td><img src="docs/screenshots/persons-manage.jpg" alt="Manage Persons page" width="100%"></td>
<td><img src="docs/screenshots/person-gallery.jpg" alt="Person gallery" width="100%"></td>
</tr></table>

### Statistics

Interactive dashboards across four tabs:

- **Gear** — camera and lens usage timelines, average scores by equipment, top body+lens combos
- **Categories** — breakdown by content category with shooting profiles (preferred camera, lens, ISO, aperture, focal length per category)
- **Timeline** — photos per month/year, day-of-week and hour-of-day distributions, shooting hours heatmap
- **Correlations** — configurable multi-metric charts across any axis (year, ISO, aperture, focal length, etc.)

<table><tr>
<td><img src="docs/screenshots/stats-gear.jpg" alt="Equipment statistics" width="100%"></td>
<td><img src="docs/screenshots/stats-categories.jpg" alt="Category analytics" width="100%"></td>
</tr><tr>
<td><img src="docs/screenshots/stats-timeline.jpg" alt="Timeline statistics" width="100%"></td>
<td><img src="docs/screenshots/stats-correlations.jpg" alt="Correlation charts" width="100%"></td>
</tr></table>

### Weight Tuning

Per-category weight editor with live preview showing how weight changes affect the top-ranked photos. Includes a correlation chart comparing configured weights vs actual impact on scores. Pairwise A/B photo comparison learns from your choices. Requires edition mode.

<table><tr>
<td><img src="docs/screenshots/weights-sliders.jpg" alt="Category weight sliders" width="100%"></td>
<td><img src="docs/screenshots/weights-compare.jpg" alt="A/B photo comparison" width="100%"></td>
</tr></table>

### Responsive Design

The UI adapts to mobile with a single-column layout, bottom navigation bar, and collapsible filter drawer.

<table><tr>
<td width="50%"><img src="docs/screenshots/mobile-gallery.jpg" alt="Mobile gallery" width="100%"></td>
<td width="50%"><img src="docs/screenshots/mobile-filters.jpg" alt="Mobile filters" width="100%"></td>
</tr></table>

### Multi-Language Support

Available in English, French, German, Spanish, and Italian with a language switcher in the header menu.

## Quick Start

```bash
# 1. Install exiftool (system dependency)
# Ubuntu/Debian: sudo apt install libimage-exiftool-perl
# macOS:         brew install exiftool

# 2. Create virtual environment
python -m venv venv && source venv/bin/activate

# 3. Install PyTorch with CUDA (pick your version at https://pytorch.org/get-started/locally)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128

# 4. Install Python dependencies
pip install -r requirements.txt

# 5. Install ONNX Runtime for face detection (choose ONE)
pip install onnxruntime-gpu>=1.17.0   # GPU (CUDA 12.x)
# pip install onnxruntime>=1.15.0     # CPU fallback

# 6. Build Angular frontend
cd client && npm install && npx ng build && cd ..

# 7. Score photos (auto-detects VRAM, uses multi-pass mode)
python facet.py /path/to/photos

# 8. Run the web viewer (FastAPI API + Angular SPA)
python viewer.py
# Open http://localhost:5000
```

Run `python facet.py --doctor` to diagnose GPU issues. See [Installation](docs/INSTALLATION.md) for VRAM profiles, VLM tagging packages (16gb/24gb), and optional dependencies.

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
