# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Rules

- **No backward-compatibility fallbacks.** When renaming or restructuring config keys, methods, or APIs, do NOT add legacy aliases, fallback lookups, or shims for old names. Update all references to use the new names directly. Old names should be removed completely.

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
python photos.py /path/to/photos

# Force single-pass mode (all models loaded at once, requires high VRAM)
python photos.py /path/to/photos --single-pass

# Run specific pass only
python photos.py /path/to/photos --pass quality      # TOPIQ only
python photos.py /path/to/photos --pass tags         # Configured tagger only
python photos.py /path/to/photos --pass composition  # SAMP-Net only
python photos.py /path/to/photos --pass faces        # InsightFace only
python photos.py /path/to/photos --pass embeddings   # CLIP embeddings only

# Force re-scan of already processed files
python photos.py /path/to/photos --force

# Preview mode - score sample photos without saving (default: 10 photos)
python photos.py /path/to/photos --dry-run
python photos.py /path/to/photos --dry-run --dry-run-count 20

# Re-tag photos with configured tagger model
python photos.py --recompute-tags
python photos.py --recompute-tags-vlm    # Re-tag using VLM tagger

# List available models and VRAM requirements
python photos.py --list-models

# Recompute aggregate scores using stored embeddings (creates backup first)
python photos.py --recompute-average
python photos.py --recompute-category portrait  # Single category only (faster)

# Analyze database and show scoring recommendations
python photos.py --compute-recommendations
python photos.py --compute-recommendations --apply-recommendations  # Auto-apply scoring fixes

# Export scores to CSV or JSON for external analysis
python photos.py --export-csv                    # Auto-named with timestamp
python photos.py --export-csv output.csv         # Specific filename
python photos.py --export-json output.json

# Face recognition commands
python photos.py --extract-faces-gpu-incremental  # Extract faces for new photos only (requires GPU)
python photos.py --extract-faces-gpu-force        # Re-extract all faces, deletes existing (requires GPU)
python photos.py --cluster-faces-incremental      # Cluster faces, preserves existing persons (CPU)
python photos.py --cluster-faces-force            # Full re-cluster, deletes all persons (CPU)
python photos.py --refill-face-thumbnails-incremental  # Generate missing face thumbnails
python photos.py --refill-face-thumbnails-force        # Regenerate ALL face thumbnails from original images
python photos.py --recompute-blinks               # Recompute blink detection for photos with faces
python photos.py --recompute-burst                # Recompute burst detection groups
python photos.py --detect-duplicates              # Detect duplicate photos via pHash

# Composition commands
python photos.py --recompute-composition-cpu  # Rule-based (CPU only, fast)
python photos.py --recompute-composition-gpu  # SAMP-Net (requires GPU)

# Thumbnail management
python photos.py --fix-thumbnail-rotation  # Fix rotation of existing thumbnails using EXIF data

# Configuration commands
python photos.py --validate-categories  # Validate category configurations and show list

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

# Run web viewer (Flask on localhost:5000)
python viewer.py
```

## Dependencies

Python packages: `torch`, `torchvision`, `open-clip-torch`, `opencv-python`, `pillow`, `pillow-heif`, `imagehash`, `rawpy`, `flask`, `numpy`, `tqdm`, `exifread`, `insightface`, `scipy`, `scikit-learn`, `hdbscan`, `pyiqa`, `psutil`

For VLM tagging (8gb+ profiles): `transformers>=4.57.0`, `accelerate>=0.25.0`

For GPU face clustering (optional): `cuml`, `cupy` (requires conda + CUDA)

External tool: `exiftool` (command-line)

## Architecture

### Core Components

**photos.py** - Main scoring engine with model management:
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

**viewer.py** - Flask web gallery with filtering, sorting, face recognition, and tag search

**scoring_config.json** - All configurable weights, thresholds, and model settings

### VRAM Profiles

| Profile | Models | Use Case |
|---------|--------|----------|
| `legacy` | CLIP+MLP + SAMP-Net + CLIP tagging (CPU) | No GPU, 8GB+ RAM |
| `8gb` | CLIP+MLP + SAMP-Net + Qwen3-VL | 6-14GB VRAM |
| `16gb` | TOPIQ + SAMP-Net + Qwen3-VL | Best aesthetic accuracy (~14GB) |
| `24gb` | TOPIQ + Qwen2-VL + Qwen2.5-VL-7B | Composition explanations (~18GB) |

### Data Flow

1. `photos.py` scans directories for JPG/JPEG/CR2/CR3/HEIC/HEIF files
2. BatchProcessor processes images with continuous GPU batching (no inter-batch gaps)
3. Each image gets: CLIP embedding + tags, aesthetic score, face analysis, technical metrics, composition pattern
4. Results stored in SQLite with 640x640 thumbnail BLOBs
5. Post-processing groups images into bursts, flags best-of-burst
6. `viewer.py` serves the gallery with filtering by tag, person, camera, score

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

### Category Filters Reference

Each category in `scoring_config.json` has a `filters` block that determines when a photo matches that category. Evaluated by `CategoryFilter` in `config.py`.

**Numeric range filters** (suffix `_min`/`_max`):
| Filter | Field | Description |
|--------|-------|-------------|
| `face_ratio_min` / `face_ratio_max` | `face_ratio` | Face area as fraction of frame (0.0-1.0) |
| `face_count_min` / `face_count_max` | `face_count` | Number of detected faces |
| `iso_min` / `iso_max` | `ISO` | Camera ISO sensitivity |
| `shutter_speed_min` / `shutter_speed_max` | `shutter_speed` | Exposure time in seconds |
| `luminance_min` / `luminance_max` | `mean_luminance` | Average image brightness (0.0-1.0) |
| `focal_length_min` / `focal_length_max` | `focal_length` | Lens focal length in mm |
| `f_stop_min` / `f_stop_max` | `f_stop` | Aperture f-number |

**Boolean filters** (true/false):
| Filter | Description |
|--------|-------------|
| `has_face` | Photo contains at least one detected face |
| `is_monochrome` | Photo is black & white (saturation < 5%) |
| `is_silhouette` | Backlit subject with heavy shadows + highlights |
| `is_group_portrait` | Multiple faces detected |

**Tag filters**:
| Filter | Description |
|--------|-------------|
| `required_tags` | List of tag names the photo must have |
| `excluded_tags` | List of tag names the photo must NOT have |
| `tag_match_mode` | `"any"` (default) = at least one tag matches; `"all"` = all tags must match |

### Category Modifiers Reference

The `modifiers` block adjusts scoring behavior for matched photos:

| Modifier | Type | Description |
|----------|------|-------------|
| `bonus` | float | Added to final aggregate score (e.g., 0.3 = +0.3 pts) |
| `noise_tolerance_multiplier` | float | Scales noise penalty (0.5 = half penalty, good for night/astro) |
| `iso_tolerance_multiplier` | float | Scales ISO-based penalty |
| `min_saturation_bonus` | float | Bonus for high saturation (concerts with colored lights) |
| `contrast_bonus` | float | Bonus for high contrast scenes |
| `_skip_clipping_penalty` | bool | Don't penalize shadow/highlight clipping (silhouettes, astro) |
| `_skip_oversaturation_penalty` | bool | Don't penalize oversaturated colors (concerts, night) |
| `_clipping_multiplier` | float | Scale clipping penalty (1.5 = stricter for B&W) |
| `_apply_blink_penalty` | bool | Apply blink detection penalty (portraits, groups) |

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

The `top_picks_score` is computed in SQL via `get_top_picks_score_sql()` in `viewer.py`.

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

**Scores:** aesthetic, face_count, face_quality, eye_sharpness, face_ratio, tech_sharpness, color_score, exposure_score, comp_score, aggregate

**Technical:** noise_sigma, contrast_score, dynamic_range_stops, mean_saturation, is_monochrome

**Composition:** composition_pattern (SAMP-Net), power_point_score, leading_lines_score

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

**Query Optimizations in viewer.py:**
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

Facet uses two complementary approaches for composition scoring:

**Rule-Based Analysis** (`--recompute-composition-cpu`)
- CPU-only, fast recomputation
- Detects subject region using edge detection and saliency
- Computes: `power_point_score`, `leading_lines_score`, `comp_score`
- Scores based on rule-of-thirds placement and leading line quality
- Use when: algorithm changes, quick iteration, no GPU available

**SAMP-Net Neural Network** (`--recompute-composition-gpu`)
- GPU required (~2GB VRAM)
- Deep learning model trained on composition quality
- Computes: `comp_score`, `composition_pattern`
- Identifies patterns: rule_of_thirds, diagonal, horizontal, vertical, triangular, etc.
- Use when: better accuracy needed, pattern identification required

| Command | Hardware | Updates | Speed |
|---------|----------|---------|-------|
| `--recompute-composition-cpu` | CPU | power_point, leading_lines, comp_score | Fast |
| `--recompute-composition-gpu` | GPU | comp_score, composition_pattern | Slower |

After either command, run `--recompute-average` to update aggregate scores.

### Face Recognition

**face_clustering.py** - Face clustering module:
- `FaceProcessor` - Producer-consumer processor for parallel face operations with auto-tuning
- `FaceResourceMonitor` - Monitors memory and adjusts batch size during processing
- `FaceClusterer` - HDBSCAN-based clustering of face embeddings into persons
- `extract_faces_from_existing()` - Extract faces from ALL photos (deletes existing faces first)
- `refill_face_thumbnails()` - Regenerate ALL face thumbnails from original images
- `run_face_clustering()` - Main entry point called from photos.py
- `_check_cuml_available()` - Detect if cuML GPU clustering is available

**Database tables:**
- `faces(id, photo_path, face_index, embedding, bbox_*, person_id, confidence, face_thumbnail)` - Individual face records with pre-generated thumbnails
- `persons(id, name, representative_face_id, face_count, centroid, auto_clustered, face_thumbnail)` - Person clusters

**Face thumbnail storage:**
- Thumbnails are generated during scanning from full-resolution images (higher quality)
- Stored in `faces.face_thumbnail` column as JPEG BLOBs (~5-10KB each)
- Clustering uses stored thumbnails instead of regenerating (fast)
- Run `--refill-face-thumbnails-force` to regenerate ALL thumbnails from original images (parallel processing)
- Run `--refill-face-thumbnails-incremental` to generate only missing thumbnails

**Clustering modes:**
- `--cluster-faces-incremental`: Preserves all existing persons, matches new clusters to them via centroid similarity (threshold 0.6), updates centroids after merging
- `--cluster-faces-force`: Deletes all persons including named ones, full re-cluster

**GPU clustering (cuML):**
- Configure via `face_clustering.use_gpu` in scoring_config.json: `"auto"` (default), `"always"`, or `"never"`
- cuML HDBSCAN is significantly faster for large datasets (80K+ faces)
- Falls back to CPU HDBSCAN when cuML is unavailable
- Note: `algorithm` and `leaf_size` parameters only apply to CPU clustering; cuML uses its own optimized implementation

**Key methods in FaceClusterer:**
- `cluster_faces(force=False)` - Main clustering entry point
- `_should_use_gpu()` - Determine if GPU clustering should be used
- `_update_database(face_to_cluster, embeddings, face_ids, force=False)` - Handles preservation logic
- `match_face_to_person(embedding_bytes, threshold=0.6)` - Match single face to existing person

**Blink detection:**
- Uses Eye Aspect Ratio (EAR) calculated from InsightFace 106-point landmarks
- Configurable threshold in `scoring_config.json` under `face_detection.blink_ear_threshold` (default: 0.28)
- Run `--recompute-blinks` to re-evaluate blink detection without full rescan (processes only photos with faces)

**Viewer integration:**
- Person dropdown filter with face thumbnails
- `/manage_persons` page for merge/rename/delete operations
- Person avatars on photo cards

### Face Recognition Workflow

Complete workflow for face recognition setup:

1. **Scan photos** - Process photos to extract faces and embeddings
   ```bash
   python photos.py /path/to/photos
   ```
   This extracts faces during scoring. For existing photos without faces:
   ```bash
   python photos.py --extract-faces-gpu-incremental
   ```

2. **Cluster faces into persons** - Group similar faces
   ```bash
   python photos.py --cluster-faces-incremental
   ```
   Or force full re-cluster (deletes existing persons):
   ```bash
   python photos.py --cluster-faces-force
   ```

3. **Review and merge persons** - Find duplicate clusters
   ```bash
   python photos.py --suggest-person-merges
   ```
   Opens browser to merge suggestions page. Manual merging via `/manage_persons` in viewer.

### Key Implementation Details

- PyIQA quality models: TOPIQ (0.93 SRCC), HyperIQA (0.90), DBCNN (0.90), MUSIQ (0.87)
- SAMP-Net for composition pattern detection (14 patterns including rule_of_thirds, golden_ratio, vanishing_point)
- InsightFace buffalo_l for face detection with 106-point landmarks and recognition embeddings
- CLIP ViT-L-14 for semantic tagging with configurable similarity threshold
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
