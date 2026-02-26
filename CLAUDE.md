# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Rules

- **No backward-compatibility fallbacks.** When renaming or restructuring config keys, methods, or APIs, do NOT add legacy aliases, fallback lookups, or shims for old names. Update all references to use the new names directly. Old names should be removed completely.
- **No custom CSS classes in Angular components.** Use plain Tailwind CSS utilities exclusively. Never define custom CSS classes in component `styles`. Use Angular `host` property for `:host` styling (e.g., `host: { class: 'block h-full' }`). All styling must be done via Tailwind utility classes in templates.
- **Use pipes instead of method calls in Angular templates.** Never call component methods from template expressions (e.g., `{{ method(value) }}`). Use Angular pipes for data transformation in templates to avoid unnecessary change detection cycles.

## Code Review

Run `/agents:code-review-agent` to review commits and changes. Supports reviewing the last commit, uncommitted changes, or specific files with configurable depth (quick/standard/deep) and focus areas (security, performance, sql, i18n, config).

## Available Skills

| Skill | Triggers | Purpose |
|-------|----------|---------|
| `signal-patterns` | signal, computed, effect, UI not updating | Signal-based state management for Angular 20 |
| `effect-safety-validator` | infinite loop, ObjectUnsubscribedError, effect safety | Detect unsafe effect patterns in Angular signals |
| `test-creation` | create tests, fix test, TS2345, test coverage | Test suites for Angular 20 zoneless signal components |
| `code-quality-analyzer` | duplicate code, DRY, refactor, code smell | Code smells and refactoring opportunities |
| `css-layout-patterns` | @apply, flex layout, overflow, dark theme | CSS/Tailwind v4 layout patterns |
| `chrome-devtools-debugging` | UI issue, network request, console error | Browser debugging with Chrome DevTools MCP |
| `/agents:code-review-agent` | code review, review commit | Expert code review for Facet changes |
| `/reflexion` | audit .claude, ecosystem health | Audit .claude/ ecosystem for quality and coherence |

## Patterns (`.claude/patterns/`)

Checklists for recurring multi-file changes — consult before starting:

| Pattern | When to use |
|---------|-------------|
| [`new-metric-checklist.md`](.claude/patterns/new-metric-checklist.md) | Adding a new scoring metric (schema, scorer, config validator, API, client) |
| [`i18n-sync.md`](.claude/patterns/i18n-sync.md) | Adding or renaming user-facing strings across all 5 languages |

## Project Overview

Facet is a multi-dimensional photo analysis engine that examines every facet of an image — from aesthetic appeal and composition to facial detail and technical precision — using an ensemble of vision models to surface the photos that truly shine.

**Documentation:** See `docs/` for detailed documentation:
- [docs/CONFIGURATION.md](docs/CONFIGURATION.md) - Full `scoring_config.json` reference with correct defaults
- [docs/COMMANDS.md](docs/COMMANDS.md) - All CLI commands
- [docs/SCORING.md](docs/SCORING.md) - Category system and weight tuning
- [docs/FACE_RECOGNITION.md](docs/FACE_RECOGNITION.md) - Face workflow and clustering
- [docs/VIEWER.md](docs/VIEWER.md) - Web gallery features
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) - Production deployment (Synology NAS, Linux, Docker)

## Commands

```bash
# Score photos in a directory (auto multi-pass mode, VRAM auto-detection)
python facet.py /path/to/photos

# Force single-pass mode (all models loaded at once, requires high VRAM)
python facet.py /path/to/photos --single-pass

# Run specific pass only
python facet.py /path/to/photos --pass quality       # TOPIQ only
python facet.py /path/to/photos --pass quality-iaa   # TOPIQ IAA (aesthetic merit)
python facet.py /path/to/photos --pass quality-face  # TOPIQ NR-Face (face quality)
python facet.py /path/to/photos --pass quality-liqe  # LIQE (quality + distortion diagnosis)
python facet.py /path/to/photos --pass tags          # Configured tagger only
python facet.py /path/to/photos --pass composition   # SAMP-Net only
python facet.py /path/to/photos --pass faces         # InsightFace only
python facet.py /path/to/photos --pass embeddings    # CLIP/SigLIP embeddings only
python facet.py /path/to/photos --pass saliency      # InSPyReNet subject saliency

# Force re-scan of already processed files
python facet.py /path/to/photos --force

# Preview mode - score sample photos without saving (default: 10 photos)
python facet.py /path/to/photos --dry-run
python facet.py /path/to/photos --dry-run --dry-run-count 20

# Re-tag photos with configured tagger model
python facet.py --recompute-tags
python facet.py --recompute-tags-vlm    # Re-tag using VLM tagger
python facet.py --recompute-iqa         # Recompute supplementary IQA (TOPIQ IAA, NR-Face, LIQE) from thumbnails

# List available models and VRAM requirements
python facet.py --list-models

# Recompute aggregate scores using stored embeddings (creates backup first)
python facet.py --recompute-average
python facet.py --recompute-category portrait  # Single category only (faster)

# Analyze database and show scoring recommendations
python facet.py --compute-recommendations
python facet.py --compute-recommendations --apply-recommendations  # Auto-apply scoring fixes

# Export scores to CSV or JSON for external analysis
python facet.py --export-csv                    # Auto-named with timestamp
python facet.py --export-csv output.csv         # Specific filename
python facet.py --export-json output.json

# Face recognition commands
python facet.py --extract-faces-gpu-incremental  # Extract faces for new photos only (requires GPU)
python facet.py --extract-faces-gpu-force        # Re-extract all faces, deletes existing (requires GPU)
python facet.py --cluster-faces-incremental      # Cluster faces, preserves existing persons (CPU)
python facet.py --cluster-faces-force            # Full re-cluster, deletes all persons (CPU)
python facet.py --refill-face-thumbnails-incremental  # Generate missing face thumbnails
python facet.py --refill-face-thumbnails-force        # Regenerate ALL face thumbnails from original images
python facet.py --recompute-blinks               # Recompute blink detection for photos with faces
python facet.py --recompute-burst                # Recompute burst detection groups
python facet.py --detect-duplicates              # Detect duplicate photos via pHash

# Saliency commands
python facet.py --recompute-saliency  # Recompute subject saliency metrics (InSPyReNet, GPU)

# Composition commands
python facet.py --recompute-composition-cpu  # Rule-based (CPU only, fast)
python facet.py --recompute-composition-gpu  # SAMP-Net (requires GPU)

# Thumbnail management
python facet.py --fix-thumbnail-rotation  # Fix rotation of existing thumbnails using EXIF data

# Configuration commands
python facet.py --validate-categories  # Validate category configurations and show list

# Tag existing photos using stored CLIP embeddings
python tag_existing.py
python tag_existing.py --dry-run --threshold 0.25

# Database management
python database.py                  # Initialize/upgrade schema
python database.py --info           # Show schema information
python database.py --migrate-tags   # Populate photo_tags lookup table (faster tag queries)
python database.py --refresh-stats  # Refresh statistics cache for viewer performance
python database.py --stats-info     # Show statistics cache status and age
python database.py --vacuum         # Reclaim space and defragment the database
python database.py --analyze        # Update query planner statistics
python database.py --optimize       # Run both VACUUM and ANALYZE for full optimization

# User management (multi-user mode)
python database.py --add-user USERNAME --role ROLE [--display-name NAME]
python database.py --migrate-user-preferences --user USERNAME

# Run web viewer (FastAPI + Angular on localhost:5000)
python viewer.py
```

## Dependencies

Python packages: `torch`, `torchvision`, `open-clip-torch`, `opencv-python`, `pillow`, `imagehash`, `rawpy`, `fastapi`, `uvicorn`, `pyjwt`, `numpy`, `tqdm`, `exifread`, `insightface`, `scipy`, `scikit-learn`, `hdbscan`, `pyiqa`, `psutil`

For VLM tagging: `transformers>=4.57.0`, `accelerate>=0.25.0` (Qwen VLMs for 16gb/24gb)

For subject saliency (optional): `transparent-background` (InSPyReNet)

For GPU face clustering (optional): `cuml`, `cupy` (requires conda + CUDA)

External tool: `exiftool` (command-line)

## Architecture

### Core Components

**facet.py** - Main scoring engine with model management:
- `ModelManager` - Loads models based on VRAM profile (legacy/8gb/16gb/24gb)
- `Facet` - Orchestrator for SQLite DB and scoring coordination
- `BatchProcessor` - Continuous streaming producer-consumer pattern for batched GPU inference

**config.py** - Configuration classes:
- `ScoringConfig` - Loads weights from JSON, provides `get_weights()`, `get_category_tags()`, `get_tag_vocabulary()`
- `CategoryFilter` - Evaluates category membership rules (v4.0 config)
- `determine_category(photo_data)` - Config-driven category determination
- `get_categories()` - Returns categories sorted by priority (v4.0) or builds from v3 weights
- `migrate_to_v4()` - Migrates v3 config to v4 category-centric format
- `PercentileNormalizer` - Dataset-aware normalization using percentile values

**tagger.py** - CLIP-based semantic tagging with configurable vocabulary

**viewer.py** - FastAPI server entry point (API + Angular SPA on port 5000)

**scoring_config.json** - All configurable weights, thresholds, and model settings

### VRAM Profiles

| Profile | Embeddings | Aesthetic | Tagger | Use Case |
|---------|------------|-----------|--------|----------|
| `legacy` | CLIP ViT-L-14 | CLIP+MLP | CLIP similarity | No GPU, 8GB+ RAM |
| `8gb` | CLIP ViT-L-14 | CLIP+MLP | CLIP similarity | 6-14GB VRAM |
| `16gb` | SigLIP 2 SO400M | TOPIQ | Qwen3-VL-2B | Best accuracy (~14GB) |
| `24gb` | SigLIP 2 SO400M | TOPIQ | Qwen2.5-VL-7B | Largest models (~18GB) |

All profiles additionally run: SAMP-Net (composition), InsightFace (faces), supplementary PyIQA models (TOPIQ IAA, TOPIQ NR-Face, LIQE), and optionally InSPyReNet (subject saliency).

### Data Flow

1. `facet.py` scans directories for JPG/JPEG/CR2/CR3 files
2. BatchProcessor processes images with continuous GPU batching (no inter-batch gaps)
3. Each image gets: CLIP/SigLIP embedding + tags, aesthetic scores (TOPIQ + IAA + LIQE), face analysis, technical metrics, composition pattern, subject saliency
4. Results stored in SQLite with 640x640 thumbnail BLOBs
5. Post-processing groups images into bursts, flags best-of-burst
6. `viewer.py` serves the API and Angular SPA with filtering by tag, person, camera, score

### Scoring Algorithm

Photos are categorized by content and scored with specialized weights:

**Face-based categories** (determined by face_ratio):
- `portrait` - face > 5% of frame
- `portrait_bw` - B&W portrait
- `group_portrait` - multiple faces
- `silhouette` - backlit faces

**Tag-based categories** (determined by CLIP similarity):
- `art`, `macro`, `astro`, `street`, `aerial`, `concert`, `night`, `wildlife`, `architecture`, `food`, `landscape`

Each category has configurable weights in `scoring_config.json` using `_percent` suffix (e.g., `face_quality_percent: 30`).

### Category Filters & Modifiers

Each category in `scoring_config.json` has `filters` (numeric ranges, booleans, tags) and `modifiers` (bonus, penalty scaling). Evaluated by `CategoryFilter` in `config.py`. See [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for the full filter and modifier reference.

### Top Picks

The "Top Picks" filter in the viewer uses a custom weighted score computed on-the-fly:

```json
"photo_types": {
  "top_picks_min_score": 7,
  "top_picks_min_face_ratio": 0.20,
  "top_picks_weights": {
    "aggregate_percent": 30,
    "aesthetic_percent": 28,
    "composition_percent": 18,
    "face_quality_percent": 24
  }
}
```

**Score computation:**
- With significant face (face_ratio >= 20%): `aggregate * 0.30 + aesthetic * 0.28 + comp_score * 0.18 + face_quality * 0.24`
- Without significant face: `aggregate * 0.30 + aesthetic * 0.426 + comp_score * 0.274` (face_quality weight redistributed proportionally)

The `top_picks_score` is computed in SQL via `get_top_picks_score_sql()` in `api/top_picks.py`.

**Note:** Default weights are optimized for TOPIQ (0.93 SRCC), which is the aesthetic model for all profiles.

### Category Tags

Tags are defined per weight category with synonyms for CLIP matching:
```json
"landscape": {
  "tags": {
    "landscape": ["landscape", "scenic view", "nature scene"],
    "mountain": ["mountain", "alpine", "peaks"],
    "beach": ["beach", "ocean", "seaside", "coastal"]
  },
  "aesthetic_percent": 35,
  "bonus": 0.5
}
```

Use `ScoringConfig.get_category_tags(category)` to get tag names or `get_tag_vocabulary()` for full vocabulary with synonyms.

### Database Schema

SQLite table `photos` with columns:

**Core:** path (PK), filename, date_taken, camera_model, lens_model, ISO, f_stop, shutter_speed, focal_length, image_width, image_height

**Scores:** aesthetic, face_count, face_quality, eye_sharpness, face_ratio, tech_sharpness, color_score, exposure_score, comp_score, aggregate, aesthetic_iaa, face_quality_iqa, liqe_score

**Technical:** noise_sigma, contrast_score, dynamic_range_stops, mean_saturation, is_monochrome

**Composition:** composition_pattern (SAMP-Net), power_point_score, leading_lines_score

**Subject Saliency:** subject_sharpness, subject_prominence, subject_placement, bg_separation

**Duplicates:** duplicate_group_id, is_duplicate_lead

**Tags/Recognition:** tags (JSON), person_id, face_embedding (BLOB)

**Raw data (for recalculation):** clip_embedding (BLOB), histogram_data (BLOB), raw_sharpness_variance, config_version

**Lookup tables:**
- `photo_tags(photo_path, tag)` - Normalized tag lookup for fast exact-match queries (replaces `LIKE '%tag%'`)
- `faces(id, photo_path, face_index, embedding, bbox_*, person_id, confidence, face_thumbnail)` - Face embeddings and thumbnails for recognition
- `persons(id, name, representative_face_id, face_count, centroid, auto_clustered, face_thumbnail)` - Person clusters (name=NULL for auto-clustered)

### Performance Optimizations

For large databases (50k+ photos), the following optimizations are available:

**Statistics Cache** - Run `python database.py --refresh-stats` to precompute expensive aggregations:
- Total photo counts
- Camera/lens model counts for dropdowns
- Person counts for face recognition filter
- Category and composition pattern counts
- Filtered counts (hide blinks, hide bursts)

The cache is stored in the `stats_cache` table with a 5-minute TTL. Run `--stats-info` to check cache freshness.

**Tag Lookup Table** - Run `python database.py --migrate-tags` to populate the `photo_tags` table. This enables 10-50x faster tag filtering by replacing slow `LIKE '%tag%'` scans with indexed exact-match queries.

**Query Optimizations in api/:**
- COUNT result caching (5 minute TTL) to avoid repeated full-table scans
- Lazy-loaded filter dropdowns via `/api/filter_options/*` endpoints
- EXISTS subqueries instead of IN for person filters
- Conditional use of photo_tags table when available

**Configuration (in scoring_config.json):**
```json
"performance": {
  "mmap_size_mb": 12288,
  "cache_size_mb": 64
}
```

### Composition Analysis

Two approaches: `--recompute-composition-cpu` (rule-based, fast) and `--recompute-composition-gpu` (SAMP-Net, 14 patterns). After either, run `--recompute-average` to update aggregate scores.

### Face Recognition

**face_clustering.py** - HDBSCAN-based clustering of face embeddings into persons. Key classes: `FaceProcessor`, `FaceClusterer`, `FaceResourceMonitor`.

**Database tables:** `faces` (embeddings, thumbnails, bbox) and `persons` (clusters, centroids, names).

**Clustering modes:** `--cluster-faces-incremental` (preserves existing persons) vs `--cluster-faces-force` (full re-cluster). Optional GPU via cuML.

See [docs/FACE_RECOGNITION.md](docs/FACE_RECOGNITION.md) for the complete workflow, thumbnail storage, blink detection, and viewer integration.

### Key Implementation Details

- **Embeddings:** SigLIP 2 SO400M (1152-dim, 16gb/24gb) or CLIP ViT-L-14 (768-dim, legacy/8gb)
- **Quality:** TOPIQ (0.93 SRCC), HyperIQA (0.90), DBCNN (0.90), MUSIQ (0.87)
- **Supplementary PyIQA:** TOPIQ IAA (aesthetic merit), TOPIQ NR-Face (face quality), LIQE (quality + distortion diagnosis)
- **Composition:** SAMP-Net for pattern detection (14 patterns including rule_of_thirds, golden_ratio, vanishing_point)
- **Subject saliency:** InSPyReNet via `transparent-background` — subject sharpness, prominence, placement, background separation
- **Faces:** InsightFace buffalo_l for detection with 106-point landmarks and recognition embeddings
- **Tagging:** CLIP similarity (legacy/8gb), Qwen3-VL-2B (16gb), Qwen2.5-VL-7B (24gb)
- Face recognition uses HDBSCAN clustering on embeddings (standalone hdbscan library)
- Percentile normalization: scales metrics so 90th percentile maps to 10.0
- Burst detection groups similar photos within configurable time windows

### Key Configuration Defaults (from scoring_config.json)

For quick reference, here are the actual defaults from the config file:

| Section | Key | Default |
|---------|-----|---------|
| `burst_detection` | `similarity_threshold_percent` | `70` |
| `burst_detection` | `time_window_minutes` | `0.8` |
| `burst_detection` | `rapid_burst_seconds` | `0.4` |
| `duplicate_detection` | `similarity_threshold_percent` | `90` |
| `face_detection` | `min_confidence_percent` | `65` |
| `face_detection` | `blink_ear_threshold` | `0.28` |
| `face_detection` | `min_faces_for_group` | `4` |
| `face_clustering` | `min_faces_per_person` | `2` |
| `face_clustering` | `min_samples` | `2` |
| `face_clustering` | `merge_threshold` | `0.6` |
| `face_clustering` | `use_gpu` | `"auto"` |
| `models` | `keep_in_ram` | `"auto"` |
| `viewer` | `edition_password` | `""` (empty = disabled) |
| `viewer.pagination` | `default_per_page` | `64` |
| `viewer.dropdowns` | `min_photos_for_person` | `10` |
| `viewer.defaults` | `type` | `""` (empty = All Photos) |
| `viewer.defaults` | `sort` | `"aggregate"` |
| `viewer.defaults` | `sort_direction` | `"DESC"` |
| `viewer.defaults` | `hide_blinks` | `true` |
| `viewer.defaults` | `hide_bursts` | `true` |
| `viewer.defaults` | `hide_duplicates` | `true` |
| `viewer.defaults` | `hide_details` | `true` |

See [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for the complete reference.
