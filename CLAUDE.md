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
| `signal-patterns` | signal, computed, effect, UI not updating, array mutation, object mutation, zoneless, change detection | Signal-based state management for Angular 20 |
| `effect-safety-validator` | infinite loop, NG0101, Maximum call stack, ObjectUnsubscribedError, effect safety, form patchValue | Detect unsafe effect patterns in Angular signals |
| `test-creation` | create tests, fix test, TS2345, NullInjectorError, fakeAsync, flushEffects, test coverage | Test suites for Angular 20 zoneless signal components |
| `code-quality-analyzer` | duplicate code, DRY, refactor, code smell | Code smells and refactoring opportunities |
| `css-layout-patterns` | @apply, flex layout, overflow, dark theme, responsive | CSS/Tailwind v4 layout patterns |
| `chrome-devtools-debugging` | UI issue, button not working, network request, console error, 422 error, screenshot | Browser debugging with Chrome DevTools MCP |
| `/reflexion` | audit .claude, ecosystem health | Audit .claude/ ecosystem for quality and coherence |
| `/adaptive` | complex task, multi-step, orchestrate agents | Autonomous multi-agent workflow orchestrator |

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
python facet.py /path/to/photos --pass saliency      # BiRefNet subject saliency

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

# Run diagnostic checks (Python, GPU, deps, config, database)
python facet.py --doctor

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

# AI captioning
python facet.py --generate-captions          # Generate AI captions for uncaptioned photos (VLM, GPU)
python facet.py --extract-gps                # Extract GPS coordinates from EXIF into database

# Saliency commands
python facet.py --recompute-saliency  # Recompute subject saliency metrics (BiRefNet, GPU)

# Composition commands
python facet.py --recompute-composition-cpu  # Rule-based (CPU only, fast)
python facet.py --recompute-composition-gpu  # SAMP-Net (requires GPU)

# Thumbnail management
python facet.py --fix-thumbnail-rotation  # Fix rotation of existing thumbnails using EXIF data

# Configuration commands
python facet.py --validate-categories  # Validate category configurations and show list

# Pairwise comparison and weight optimization
python facet.py --comparison-stats              # Show pairwise comparison statistics
python facet.py --optimize-weights              # Optimize scoring weights from comparisons

# Face clustering (additional)
python facet.py --cluster-faces-incremental-named  # Cluster preserving only named persons

# Tag existing photos using stored CLIP embeddings
python tag_existing.py
python tag_existing.py --dry-run --threshold 0.25

# Database management
python database.py                  # Initialize/upgrade schema
python database.py --info           # Show schema information
python database.py --migrate-tags   # Populate photo_tags lookup table (faster tag queries)
python database.py --rebuild-fts    # Rebuild FTS5 full-text search index from captions/tags
python database.py --populate-vec   # Populate photos_vec table for sqlite-vec vector search
python database.py --refresh-stats  # Refresh statistics cache for viewer performance
python database.py --stats-info     # Show statistics cache status and age
python database.py --vacuum         # Reclaim space and defragment the database
python database.py --analyze        # Update query planner statistics
python database.py --optimize       # Run both VACUUM and ANALYZE for full optimization

# Export lightweight viewer database (strips BLOBs, downsizes thumbnails)
python database.py --export-viewer-db                    # Incremental export to default path
python database.py --export-viewer-db output.db          # Custom output path
python database.py --export-viewer-db --force-export     # Full re-export

# Cleanup and storage migration
python database.py --cleanup-orphaned-persons    # Delete persons with no assigned faces
python database.py --migrate-storage-fs          # Migrate thumbnails/embeddings from DB to filesystem
python database.py --migrate-storage-db          # Migrate thumbnails/embeddings from filesystem to DB

# User management (multi-user mode)
python database.py --add-user USERNAME --role ROLE [--display-name NAME]
python database.py --migrate-user-preferences --user USERNAME

# Database consistency validation
python validate_db.py               # Run all consistency checks
python validate_db.py --auto-fix    # Auto-fix detected issues
python validate_db.py --report-only # Report only, no prompts

# Run web viewer (FastAPI + Angular on localhost:5000)
python viewer.py
```

## Dependencies

Python packages: `torch`, `torchvision`, `open-clip-torch`, `opencv-python`, `pillow`, `pillow-heif`, `imagehash`, `rawpy`, `fastapi`, `uvicorn`, `pyjwt`, `numpy`, `tqdm`, `exifread`, `insightface`, `scipy`, `scikit-learn`, `hdbscan`, `pyiqa`, `psutil`, `transformers>=4.57.0`, `accelerate>=0.25.0`, `reverse_geocoder`

For GPU face clustering (optional): `cuml`, `cupy` (requires conda + CUDA)

For vector search (optional): `sqlite-vec>=0.1.6` (enables KNN search in SQLite, replaces in-memory NumPy cache)

External tool: `exiftool` (command-line, optional — `exifread` fallback handles all RAW formats)

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
| `16gb` | SigLIP 2 NaFlex SO400M | TOPIQ | Qwen3.5-2B | Best accuracy (~14GB) |
| `24gb` | SigLIP 2 NaFlex SO400M | TOPIQ | Qwen3.5-4B | Largest models (~18GB) |

All profiles additionally run: SAMP-Net (composition), InsightFace (faces), supplementary PyIQA models (TOPIQ IAA, TOPIQ NR-Face, LIQE), and optionally BiRefNet (subject saliency).

### Data Flow

1. `facet.py` scans directories for JPG/JPEG, HEIF/HEIC, and RAW files (CR2, CR3, NEF, ARW, RAF, RW2, DNG, ORF, SRW, PEF)
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

**Scores:** aesthetic, face_count, face_quality, eye_sharpness, face_ratio, tech_sharpness, color_score, exposure_score, comp_score, aggregate, aesthetic_iaa, face_quality_iqa, liqe_score, topiq_score, quality_score

**Faces (extended):** face_sharpness, face_confidence, is_silhouette, is_group_portrait, raw_eye_sharpness

**Technical:** noise_sigma, contrast_score, dynamic_range_stops, mean_saturation, is_monochrome, focal_length_35mm, scoring_model

**Histogram:** histogram_spread, histogram_bimodality, mean_luminance, raw_color_entropy, shadow_clipped, highlight_clipped

**Composition:** composition_pattern (SAMP-Net), power_point_score, leading_lines_score, composition_explanation, isolation_bonus

**Subject Saliency:** subject_sharpness, subject_prominence, subject_placement, bg_separation

**Burst/Duplicates:** burst_group_id, is_burst_lead, is_blink, duplicate_group_id, is_duplicate_lead, phash

**User Actions:** star_rating, is_favorite, is_rejected

**AI/Content:** caption (VLM-generated text description), caption_translated

**Location:** gps_latitude, gps_longitude

**Tags/Recognition:** tags (JSON), person_id, face_embedding (BLOB)

**Raw data (for recalculation):** clip_embedding (BLOB), histogram_data (BLOB), raw_sharpness_variance, config_version

**Lookup tables:**
- `photo_tags(photo_path, tag)` - Normalized tag lookup for fast exact-match queries (replaces `LIKE '%tag%'`)
- `faces(id, photo_path, face_index, embedding, bbox_*, person_id, confidence, face_thumbnail)` - Face embeddings and thumbnails for recognition
- `persons(id, name, representative_face_id, face_count, centroid, auto_clustered, face_thumbnail)` - Person clusters (name=NULL for auto-clustered)
- `albums(id, user_id, name, description, cover_photo_path, is_smart, smart_filter_json, share_token, created_at, updated_at)` - Photo albums (manual, smart, and shared)
- `album_photos(id, album_id, photo_path, position, added_at)` - Album membership with ordering
- `location_names(lat_grid, lon_grid, city, region, country, display_name)` - Reverse geocoding cache (0.1° grid cells)
- `comparisons(id, photo_a_path, photo_b_path, winner, category, timestamp, session_id, user_id)` - Pairwise photo comparisons
- `learned_scores(photo_path, learned_score, comparison_count, category, updated_at, user_id)` - Scores derived from comparisons
- `weight_optimization_runs(id, timestamp, category, comparisons_used, old_weights, new_weights, mse_before, mse_after)` - Weight optimization history
- `weight_config_snapshots(id, timestamp, category, weights, description, accuracy_before, accuracy_after, comparisons_used, created_by)` - Saved weight configurations
- `recommendation_history(id, run_timestamp, config_version_hash, issue_type, target_category, target_key, old_value, proposed_value, was_applied)` - Scoring recommendation audit trail
- `user_preferences(user_id, photo_path, star_rating, is_favorite, is_rejected)` - Per-user photo ratings (multi-user mode)
- `stats_cache(key, value, updated_at)` - Precomputed statistics with TTL
- `photos_fts(path, caption, tags)` - FTS5 virtual table for BM25-ranked text search on captions/tags (content-sync with `photos`)
- `photos_vec(path, embedding)` - sqlite-vec virtual table for KNN vector search on CLIP/SigLIP embeddings (requires `sqlite-vec`)

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

**FTS5 Full-Text Search** - Run `python database.py --rebuild-fts` to build the `photos_fts` index from captions and tags. Enables BM25-ranked text search on AI-generated captions without loading the CLIP model. Sync triggers keep the index updated automatically.

**Vector Search (sqlite-vec)** - Install `sqlite-vec` and run `python database.py --populate-vec` to populate the `photos_vec` table from existing embeddings. Replaces the in-memory NumPy embedding cache (~440MB for 100k photos) with on-disk KNN search. Falls back to NumPy if sqlite-vec is not installed.

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

### Viewer API Routes (New Features)

**Semantic Search:** `GET /api/search?q=<text>&limit=50&threshold=0.15` — hybrid text-to-image search combining CLIP/SigLIP embedding similarity (70%) with FTS5 BM25 text matching on captions/tags (30%). Uses sqlite-vec KNN when available, falls back to NumPy.

**Albums:** Full CRUD via `GET|POST /api/albums`, `GET|PUT|DELETE /api/albums/{id}`, `GET|POST|DELETE /api/albums/{id}/photos`. Smart albums store filter combinations in `smart_filter_json`. Angular routes: `/albums` (list), `/album/:albumId` (gallery filtered by album).

**AI Critique:** `GET /api/critique?path=<photo_path>&mode=rule|vlm` — rule-based score breakdown (all profiles) or VLM-powered critique (16gb/24gb only).

**Memories:** `GET /api/memories?date=YYYY-MM-DD` — photos taken on the same calendar date in previous years ("On This Day").

**AI Captioning:** `GET /api/caption?path=<path>` — generate or retrieve AI caption for a photo. Bulk generation via `--generate-captions` CLI.

**Timeline:** `GET /api/timeline?cursor=&limit=&direction=` and `GET /api/timeline/dates?year=&month=` — chronological photo browsing with date navigation. Angular route: `/timeline`.

**Photo Sharing:** `POST|DELETE /api/albums/{id}/share` to generate/revoke share tokens, `GET /api/shared/album/{id}?token=` for public access. Angular route: `/shared/album/:id`.

**AI Culling (Similar Groups):** `GET /api/similar-groups?threshold=&page=&per_page=` — groups of visually similar photos for culling, accessible via similarity tab in burst culling.

**Map View:** `GET /api/photos/map?bounds=&zoom=&limit=` and `GET /api/photos/map/count` — geotagged photo locations for Leaflet map. Angular route: `/map`.

**Capsules:** `GET /api/capsules?page=&per_page=&refresh=&date_from=&date_to=` — curated photo diaporamas grouped by theme. `GET /api/capsules/{id}/photos` — photos for a capsule. `POST /api/capsules/{id}/save-album` — save capsule as album. Angular route: `/capsules`. Capsule types: journey (GPS trips with reverse geocoding), faces_of, seasonal, golden, color_story, this_week, location, person_pair, seeded, progress, color_palette, rare_pair, favorites, plus dimension-based: year, month, week, camera, lens, tag, day_of_week, composition, focal_range, category, time_of_day, star_rating, and cross-dimensional combos. Slideshow supports themed transitions (crossfade, slide, zoom, kenburns) per capsule type. Cache TTL configurable via `capsules.freshness_hours` (default: 24).

**Burst Culling:** `GET /api/burst-groups`, `POST /api/burst-groups/select`, `GET /api/culling-groups`, `POST /api/culling-groups/confirm` — burst and similar group culling workflow.

**Scan:** `POST /api/scan/start`, `GET /api/scan/status`, `GET /api/scan/stream?token=<jwt>` (SSE), `GET /api/scan/directories` — trigger and monitor scoring scans (superadmin only). The `/stream` endpoint uses Server-Sent Events for real-time progress with automatic fallback to polling.

**Face Management:** `GET /api/person/{id}/faces`, `POST /api/person/{id}/avatar`, `GET /api/photo/faces`, `POST /api/face/{id}/assign`, `POST /api/photo/assign_all_faces`, `POST /api/photo/unassign_person` — face-to-person assignment and avatar management.

**Photo Actions:** `POST /api/photo/set_rating`, `POST /api/photo/toggle_favorite`, `POST /api/photo/toggle_rejected` — single-photo ratings. Batch variants: `POST /api/photos/batch_favorite`, `POST /api/photos/batch_reject`, `POST /api/photos/batch_rating`.

**Comparison Mode:** Full pairwise comparison workflow — `GET /api/comparison/next_pair`, `POST /api/comparison/submit`, `GET /api/comparison/stats`, `GET /api/comparison/history`, `GET /api/comparison/coverage`, `GET /api/comparison/confidence`, plus weight management via `POST /api/config/update_weights`, `GET /api/config/weight_snapshots`, `POST /api/config/save_snapshot`, `POST /api/config/restore_weights`.

**Merge Suggestions:** `GET /api/merge_suggestions` — suggested person merges based on face embedding similarity.

**Plugins:** `GET /api/plugins`, `POST /api/plugins/test-webhook` — plugin listing and webhook testing.

**Health:** `GET /health`, `GET /ready` — server health and readiness checks.

**i18n:** `GET /api/i18n/languages`, `GET /api/i18n/{lang}` — language list and translation bundles.

**Folders:** `GET /api/folders` — photo folder structure for folder-based browsing.

**Download:** `GET /api/download/options?path=<path>&is_shared=<bool>` — available download types (original, darktable profiles, raw). `GET /api/download?path=<path>&type=original|darktable|raw&profile=<name>` — download with companion RAW detection and darktable profile conversion.

### Key Implementation Details

- **Embeddings:** SigLIP 2 NaFlex SO400M (1152-dim, 16gb/24gb, native aspect ratio via `transformers`) or CLIP ViT-L-14 (768-dim, legacy/8gb via `open_clip`)
- **Quality:** TOPIQ (0.93 SRCC), HyperIQA (0.90), DBCNN (0.90), MUSIQ (0.87)
- **Supplementary PyIQA:** TOPIQ IAA (aesthetic merit), TOPIQ NR-Face (face quality), LIQE (quality + distortion diagnosis)
- **Composition:** SAMP-Net for pattern detection (14 patterns including rule_of_thirds, golden_ratio, vanishing_point)
- **Subject saliency:** BiRefNet_dynamic (`ZhengPeng7/BiRefNet_dynamic`) via `transformers` — subject sharpness, prominence, placement, background separation
- **Faces:** InsightFace buffalo_l for detection with 106-point landmarks and recognition embeddings
- **Tagging:** CLIP similarity (legacy/8gb), Qwen3.5-2B (16gb), Qwen3.5-4B (24gb)
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
| `viewer.defaults` | `hide_tooltip` | `false` |
| `viewer.defaults` | `gallery_mode` | `"mosaic"` |
| `viewer.features` | `show_semantic_search` | `true` |
| `viewer.features` | `show_albums` | `true` |
| `viewer.features` | `show_critique` | `true` |
| `viewer.features` | `show_vlm_critique` | `true` |
| `viewer.features` | `show_memories` | `true` |
| `viewer.features` | `show_captions` | `true` |
| `viewer.features` | `show_timeline` | `true` |
| `viewer.features` | `show_map` | `true` |
| `viewer.features` | `show_capsules` | `true` |
| `viewer.features` | `show_similar_button` | `true` |
| `viewer.features` | `show_merge_suggestions` | `true` |
| `viewer.features` | `show_rating_controls` | `true` |
| `viewer.features` | `show_rating_badge` | `true` |
| `viewer.features` | `show_folders` | `true` |
| `capsules` | `freshness_hours` | `24` |
| `capsules` | `reverse_geocoding` | `true` |
| `capsules` | `min_aggregate` | `6.0` |
| `capsules` | `max_photos_per_capsule` | `40` |
| `capsules` | `mmr_lambda` | `0.5` |
| `similarity_groups` | `default_threshold` | `0.85` |
| `similarity_groups` | `min_group_size` | `2` |
| `similarity_groups` | `max_photos` | `10000` |
| `similarity_groups` | `max_group_size` | `50` |
| `viewer.raw_processor` | `darktable.executable` | `"darktable-cli"` |
| `viewer.raw_processor` | `darktable.profiles` | `[]` (array of `{name, hq, width, height, extra_args}`) |
See [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for the complete reference.
