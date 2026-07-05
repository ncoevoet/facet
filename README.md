# Facet

> 🌐 **English** · [Français](README.fr.md) · [Deutsch](README.de.md) · [Italiano](README.it.md) · [Español](README.es.md) · [Português](README.pt.md)

Facet is a local photo-analysis and culling engine. It scores each image across 9 dimensions — from aesthetic quality to face sharpness — then lets you browse, cull, and organize through a web gallery. Everything runs on your machine; no cloud, accounts, or API keys.

![Python](https://img.shields.io/badge/python-3.10+-blue)
![Angular](https://img.shields.io/badge/Angular-21-dd0031)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux%20%7C%20Docker-lightgrey)
![License](https://img.shields.io/badge/license-MIT-green)

<p align="center">
  <img src="docs/screenshots/hero-mosaic.jpg" alt="Facet — Top Picks mosaic gallery" width="100%">
</p>

<!--
  Demo walkthrough (60–90s): record the viewer at 1280×720 — scan → browse → cull → search —
  then encode to docs/screenshots/walkthrough.gif and it will replace the still above:
    ffmpeg -i walkthrough.mp4 -vf "fps=12,scale=960:-1:flags=lanczos" -c:v gif docs/screenshots/walkthrough.gif
  (higher quality: gifski --fps 12 --width 960 -o docs/screenshots/walkthrough.gif frames/*.png)
  Once the file exists, uncomment the block below.
-->
<!--
<p align="center">
  <img src="docs/screenshots/walkthrough.gif" alt="Facet in action — scan, browse, cull, search" width="100%">
</p>
-->

## How It Works

1. **Scan** — Point Facet at a folder of photos. Each image is analyzed for quality, composition, and faces. Supports JPG, HEIF/HEIC, and 10 RAW formats (CR2, CR3, NEF, ARW, RAF, RW2, DNG, ORF, SRW, PEF).
2. **Browse** — Open the web gallery to explore your library with filters, search, and multiple view modes.
3. **Cull** — Facet detects bursts, flags blinks, groups similar photos, and surfaces top picks.

GPU is auto-detected and optional. Facet runs CPU-only or with up to 24 GB VRAM.

## Features

### Score

Each photo is scored across 9 dimensions: aesthetic quality, composition, face quality, eye sharpness, technical sharpness, color, exposure, subject saliency, and dynamic range. Photos are categorized by content (portrait, landscape, macro, street, etc. — 30+ categories) and scored with category-specific weights. A **Top Picks** filter ranks the library by a combined score.

Hover over any photo for a tooltip with the score breakdown and EXIF data.

<img src="docs/screenshots/hover-tooltip.jpg" alt="Hover tooltip with score breakdown" width="100%">

### Cull

- **Burst detection** — groups rapid-fire shots and auto-selects the best one based on sharpness, quality, and blink detection
- **Similarity groups** — finds visually similar photos across the library, regardless of when they were taken
- **Scenes** — groups a shoot into chronological "scenes" by capture-time gaps, so you cull in story order; tap to mark and confirm to reject
- **Junk sweep** — zero-shot detection of non-photo clutter (screenshots, documents, receipts, memes, slides) with a fast review queue: keep or reject each candidate, or reject all at once
- **Per-face culling badges** — the culling lightbox shows per-face eyes open/closed, expression, and detection-confidence badges, not just a single photo-level blink flag
- **Blink detection** — flags closed-eye shots to hide or reject in one click
- **Duplicate detection** — identifies near-identical images via perceptual hashing

<table><tr>
<td><img src="docs/screenshots/burst-culling.jpg" alt="Burst culling" width="100%"></td>
<td><img src="docs/screenshots/similar-photos.jpg" alt="Similarity groups for culling" width="100%"></td>
</tr></table>

### Browse

- **Gallery modes** — mosaic (justified rows preserving aspect ratios) and grid (uniform cards with metadata overlay)
- **Filters** — date range, content tag, composition pattern, camera, lens, person, quality level, star rating, and custom metric ranges
- **Semantic search** — type a natural-language query like "sunset on the beach" and find matching photos via embedding and text search
- **Timeline** — chronological browser with year/month navigation and infinite scroll
- **Map** — geotagged photos on an interactive map with marker clustering
- **Capsules** — themed slideshows: journeys with place names, golden collection, seasonal palettes, photos of a person, and more
- **Folders** — browse by directory structure with breadcrumb navigation and cover photos
- **Memories** — "On This Day": photos from the same date in previous years
- **Slideshow** — full-screen mode with themed transitions, auto-chaining between capsules, and keyboard controls

<table><tr>
<td><img src="docs/screenshots/filter-panel.jpg" alt="Filter sidebar" width="100%"></td>
<td><img src="docs/screenshots/semantic-search.jpg" alt="Semantic search results" width="100%"></td>
</tr></table>

<details><summary>Full filter sidebar — every section expanded (click to view)</summary>
<p align="center"><img src="docs/screenshots/filter-sidebar-full.jpg" alt="Filter sidebar with every option expanded" width="380"></p>
</details>

**Workflow tips:**
- For chronological review across a trip or year, open **`/timeline`** — sort by aggregate to walk a day's best shots, or page month-by-month.
- The **`/capsules`** view generates themed diaporamas (journeys, "Faces of", seasonal, golden) you can save as albums.
- The gallery hides blinks, non-lead bursts, and duplicates by default. When the **"N photos hidden by current filters"** banner appears, click "Show all" to expand the view.

### Organize

- **Face recognition** — automatic face detection, grouping into persons, and blink detection. Search, rename, merge, and organize person clusters from the management UI. **Merge suggestions** find similar-looking clusters that may be the same person.
- **Albums** — manual collections with drag-and-drop, or smart albums that auto-populate from saved filter combinations
- **Ratings & favorites** — star ratings (1–5), favorites, and reject flags. Cycle through ratings with a single click.
- **Tags** — AI-generated content tags with configurable vocabulary. Click any tag to filter the gallery.
- **Batch operations** — multi-select with Shift+click, Ctrl+click, or Ctrl+A (select all). Set ratings, toggle favorites, mark rejects, or add to albums in bulk — with a 7-second undo for every batch action.
- **Keyboard-first** — arrow keys navigate the gallery, Enter opens, Space selects; press `?` anywhere for the shortcut reference.

<img src="docs/screenshots/albums.jpg" alt="Albums — manual and smart collections" width="100%">

<table><tr>
<td><img src="docs/screenshots/persons-manage.jpg" alt="Manage Persons page" width="100%"></td>
<td><img src="docs/screenshots/person-gallery.jpg" alt="Person gallery" width="100%"></td>
</tr></table>

### Understand

- **Statistics** — dashboards for equipment usage, category breakdown, shooting timeline, and metric correlations
- **AI critique** — score breakdown showing each metric's contribution; VLM natural-language assessment `[GPU]` `[16gb/24gb]`
- **Weight tuning** — per-category weight editor with live score preview. A/B photo comparison learns from your choices and suggests optimized weights.
- **My Taste sort** — sort the gallery by the personal ranker's learned score, with a confidence badge showing learned coverage and held-out accuracy
- **Learning from labels** — culling decisions, star ratings, favorites, and rejections feed the weight optimizer (`--sync-label-comparisons`, `--mine-insights`)
- **Snapshots** — save, restore, and compare weight configurations
- **Histogram** — luminance histogram in the photo tooltip and detail view
- **AI captions** `[GPU]` `[16gb/24gb]` — text descriptions, editable `[Edition]` and translatable to 5 languages (generation and viewing are open)

<table><tr>
<td><img src="docs/screenshots/stats-gear.jpg" alt="Equipment statistics" width="100%"></td>
<td><img src="docs/screenshots/stats-categories.jpg" alt="Category analytics" width="100%"></td>
</tr></table>

<table><tr>
<td><img src="docs/screenshots/stats-timeline.jpg" alt="Shooting timeline" width="100%"></td>
<td><img src="docs/screenshots/stats-correlations.jpg" alt="Metric correlations" width="100%"></td>
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

- **Dark & light mode** with 10 accent color themes; respects system preference
- **Responsive** — adapts from mobile to desktop, with a touch-friendly bulk-actions sheet on small screens
- **Installable PWA** — web app manifest + service worker: install to home screen, offline app shell, cached thumbnails
- **Virtualized gallery** — renders a handful of DOM nodes regardless of library size, so scrolling stays fast at 100k+ photos
- **Resumable scans** — interrupted scans resume (`--resume`), failed files are tracked and retryable (`--retry-failed`), progress streams to the web UI
- **6 languages** — English, French, German, Spanish, Italian, Brazilian Portuguese
- **Multi-user** — per-user directories, ratings, and role-based access
- **Plugins & webhooks** — custom actions triggered on scoring events
- **Scan from web UI** — trigger scans from the browser (superadmin role)

<table><tr>
<td width="33%"><img src="docs/screenshots/mobile-gallery.jpg" alt="Mobile gallery" width="100%"></td>
<td width="33%"><img src="docs/screenshots/tablet-gallery.jpg" alt="Tablet gallery" width="100%"></td>
<td width="33%"><img src="docs/screenshots/gallery-mosaic.jpg" alt="Desktop mosaic" width="100%"></td>
</tr></table>

## What you need

Most of Facet runs on **any machine (CPU)** — scoring, face detection, culling, the gallery, search, albums and metadata export all work without a GPU. A **GPU** (with the `16gb` or `24gb` profile) unlocks the strongest models: TOPIQ aesthetic scoring, SigLIP 2 embeddings, VLM tagging, AI captions and critique, and subject saliency. No local GPU? Point the VLM tagging/captions/critique at a remote **Ollama** or **OpenAI-compatible** server via `vlm_backend` in `scoring_config.json` — those features then work on the CPU `legacy`/`8gb` profiles too. In the viewer, editing actions (ratings, faces, culling) need the **edition password**, and triggering scans needs the **superadmin** role.

→ Full per-feature requirements (GPU, VRAM profile, optional packages, auth): **[Installation › Feature requirements](docs/INSTALLATION.md#feature-requirements)**.

## Is Facet for you?

Facet scores, ranks, and culls a local photo library and serves a gallery to browse it. It runs on your own hardware and keeps photos off the cloud.

**A good fit if you:**

- have a large local library and want to find your best shots and cull bursts and near-duplicates;
- want quality, composition, and face scoring you can tune to your own taste (it learns from your A/B comparisons);
- prefer self-hosted and private — no cloud upload, no account, no subscription;
- already edit in Lightroom, darktable, digiKam or immich — Facet writes ratings, labels, keywords, captions and named-face regions to `.xmp` sidecars (originals untouched by default) and can optionally embed them in-file for JPEG/HEIC/TIFF/PNG/DNG (the gallery "Write metadata to file" action or `--export-sidecars --embed-originals`), and reads external edits back with `--import-sidecars`.

**Probably not for you if you want:**

- a turnkey, mobile, cloud-backed Google Photos replacement with automatic phone backup;
- RAW editing or develop — Facet scores and organizes, it does not edit;
- a zero-setup desktop app — it needs Python, and the best models need a GPU.

**How it relates to other tools**

- Self-hosted libraries (Immich, PhotoPrism) focus on organizing, search, and backup. Facet adds quality scoring, ranking, and a culling workflow they don't, but it has no mobile app or built-in backup/sync.
- AI culling apps (Aftershoot, Narrative, FilterPixel) are polished commercial cullers, often with editing built in. Facet is free, local, broader (gallery, search, faces), and its scoring is tunable — but it is a single-developer project without their support or RAW editing.
- Editors and catalogs (Lightroom, darktable, digiKam) develop and manage photos. Facet complements them through the XMP metadata interop above rather than replacing them.

The aesthetic score is model-based and approximate; expect to tune the weights to match your taste.

## Quick Start

### Docker (recommended)

```bash
cp .env.example .env      # set PHOTOS_DIR + FACET_VRAM_PROFILE (auto-detects the GPU)
docker compose up -d
# Open http://localhost:5000
```

One image serves every profile: `FACET_VRAM_PROFILE=auto` detects the GPU (no GPU → CPU `legacy`), model weights download at runtime, and `PHOTOS_DIR` in `.env` points at your photos. The base compose runs CPU-only — no GPU required to browse and serve an existing library.

**GPU acceleration** (optional) requires an NVIDIA GPU and the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html). Enable it with an override — the generic GPU file or a per-profile overlay (`docker-compose.{legacy,8gb,16gb}.yml`):

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

### Manual Install

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
bash install.sh          # auto-detects GPU, creates venv, installs everything

source venv/bin/activate         # macOS/Linux
# .\venv\Scripts\Activate.ps1    # Windows PowerShell

python facet.py /photos  # score photos
python viewer.py         # start web viewer → http://localhost:5000
```

> **macOS:** ControlCenter's AirPlay Receiver binds port 5000 by default. If you see "Address already in use", run `python viewer.py --port 5001`.

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
cd client && npm install && npx ng build && cd ..

# 7. Score photos and start viewer
python facet.py /path/to/photos
python viewer.py
```
</details>

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
