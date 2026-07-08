# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Rules

- **No backward-compatibility fallbacks.** When renaming or restructuring config keys, methods, or APIs, do NOT add legacy aliases, fallback lookups, or shims for old names. Update all references to use the new names directly. Old names should be removed completely.
- **No custom CSS classes in Angular components.** Use plain Tailwind CSS utilities exclusively. Never define custom CSS classes in component `styles`. Use Angular `host` property for `:host` styling (e.g., `host: { class: 'block h-full' }`). All styling must be done via Tailwind utility classes in templates.
- **Use pipes instead of method calls in Angular templates.** Never call component methods from template expressions (e.g., `{{ method(value) }}`). Use Angular pipes for data transformation in templates to avoid unnecessary change detection cycles.
- **No `mock.patch` on FastAPI auth dependencies.** Use `app.dependency_overrides[require_edition] = ...` or the shared `edition_client` / `regular_client` / `superadmin_client` / `anonymous_client` fixtures in `tests/conftest.py`. FastAPI captures dependency callables inside `Depends()` at app creation, so module-level `mock.patch` rebinds the symbol but not the captured reference — the mock is silently inert and tests pass-by-accident.

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
| [`i18n-sync.md`](.claude/patterns/i18n-sync.md) | Adding or renaming user-facing strings across all 6 languages |
| [`vlm-model-change-checklist.md`](.claude/patterns/vlm-model-change-checklist.md) | Adding/upgrading/renaming/removing a VLM tagging or caption model (config, loaders, all routing sites, docs) |

## Project Overview

Facet is a multi-dimensional photo analysis engine that examines every facet of an image — from aesthetic appeal and composition to facial detail and technical precision — using an ensemble of vision models to surface the photos that truly shine.

**Documentation:** See `docs/` for detailed documentation:
- [docs/CONFIGURATION.md](docs/CONFIGURATION.md) - Full `scoring_config.json` reference with correct defaults
- [docs/COMMANDS.md](docs/COMMANDS.md) - All CLI commands
- [docs/SCORING.md](docs/SCORING.md) - Category system and weight tuning
- [docs/FACE_RECOGNITION.md](docs/FACE_RECOGNITION.md) - Face workflow and clustering
- [docs/VIEWER.md](docs/VIEWER.md) - Web gallery features
- [docs/INTEROP.md](docs/INTEROP.md) - Round-tripping ratings/tags with Lightroom, Capture One, digiKam, darktable
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

# Resume / selective re-processing
python facet.py --resume                          # Resume last interrupted/failed scan run
python facet.py --retry-failed                    # Re-process files that failed last run (or: --retry-failed all)
python facet.py /path/to/photos --force-since 2026-01-01  # Re-process only photos scanned before date

# Watch mode (daemon re-scanning on new files; optional watchdog package)
python facet.py /path/to/photos --watch [--watch-debounce 30]

# Preview mode - score sample photos without saving (default: 10 photos)
python facet.py /path/to/photos --dry-run
python facet.py /path/to/photos --dry-run --dry-run-count 20

# Re-tag photos with configured tagger model
python facet.py --recompute-tags
python facet.py --recompute-tags-vlm    # Re-tag using VLM tagger
python facet.py --recompute-iqa         # Recompute supplementary IQA (TOPIQ IAA, NR-Face, LIQE) from thumbnails
python facet.py --recompute-form         # Recompute explainable form metrics: symmetry, balance, edge-entropy, fractal, color_harmony (CPU, from thumbnails)
python facet.py --recompute-face-signals # Recompute per-face eyes_open_score + smile_score from stored 106-pt landmarks (also runs in --upgrade-db)
python facet.py --recompute-distortions  # Zero-shot distortion attributes over stored embeddings; prints Spearman correlation vs liqe_score/noise_sigma
python facet.py --recompute-skin-tone    # Portrait skin-tone naturalness: CIEDE2000 vs CCT skin locus, green/magenta/blue/yellow cast

# Immich sync (push ratings/favorites to an Immich server via REST)
python facet.py --immich-sync            # Push ratings/favorites to Immich (honors --dry-run and --user)
python facet.py --immich-test            # Check Immich connectivity + API key

# Narrative moments (zero-shot CLIP + temporal smoothing; cheap — cosine over stored embeddings)
python facet.py --detect-moments        # Label new photos with their narrative moment (auto-runs at end of each scan)
python facet.py --recompute-moments     # Re-label the whole library (re-smooths the full timeline)

# Junk sweep (zero-shot non-photo detection: screenshots/documents/receipts/memes/slides; cosine over stored embeddings)
python facet.py --detect-junk           # Flag junk in new/unevaluated photos (auto-runs at end of each scan)
python facet.py --recompute-junk        # Re-evaluate junk_kind for the whole library
python facet.py --discover-moments      # Propose a library-specific moment vocabulary (cluster caption embeddings → scoring_config.discovered.json for review)

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

# Import external editor metadata (ratings/labels/tags) from XMP sidecars into the DB
python facet.py --import-sidecars               # All photos (newest-wins, tag union)
python facet.py --import-sidecars /path         # Limit to a path subtree
python facet.py --import-sidecars --user alice  # Multi-user: write ratings to alice's user_preferences

# Export DB ratings/labels/tags/caption to XMP sidecars (sidecar only by default)
python facet.py --export-sidecars               # All photos (write/merge <image>.xmp)
python facet.py --export-sidecars /path         # Limit to a path subtree
python facet.py --export-sidecars --embed-originals  # Also embed in-file (JPEG/HEIC/TIFF/PNG/DNG); RAW never modified
python facet.py --export-sidecars --user alice  # Multi-user: export alice's ratings from user_preferences

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
python facet.py --recompute-saliency  # Recompute subject saliency metrics from stored thumbnails (BiRefNet, GPU; --force to redo all)

# Composition commands
python facet.py --recompute-composition-cpu  # Rule-based (CPU only, fast)
python facet.py --recompute-composition-gpu  # SAMP-Net (requires GPU)

# Thumbnail management
python facet.py --fix-thumbnail-rotation  # Fix rotation of existing thumbnails using EXIF data

# Configuration commands
python facet.py --validate-categories  # Validate category configurations and show list

# Pairwise comparison and weight optimization
python facet.py --comparison-stats              # Show pairwise comparison statistics
python facet.py --optimize-weights              # Optimize scoring weights from comparisons (all sources, reliability-weighted)
python facet.py --optimize-weights --optimize-sources vote,culling  # Restrict training sources
python facet.py --auto-tune-categories          # Superadmin-only stub: per-category comparison-label readiness for auto-tuning the shared global weights (auto-apply deferred pending labels)
python facet.py --sync-label-comparisons       # Rebuild rating-derived pairs from stars/favorites/rejections
python facet.py --mine-insights [report.json]  # Data-mining report: labels, correlations, drift, comparison health

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
python database.py --cleanup-missing-photos     # Remove photos no longer on disk from the database (cascades & clears cache)
python database.py --cleanup-missing-photos --dry-run # Preview missing photos without deleting
python database.py --cleanup-missing-photos --force   # Required to proceed when ALL photos look missing (unmounted volume guard)
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

For the extended IQA tier (optional, `scoring_config.json` `iqa_extended`, OFF by default): `aesthetic-predictor-v2-5` (for `aesthetic_v25`) and `bitsandbytes>=0.43.0` (for `qalign` 4-/8-bit). Install via `pip install -e .[iqa-extended]`. Q-Align ships with `pyiqa`; DeQA-Score loads via `transformers`.

For appearance-based per-face eyes/smile (optional, `scoring_config.json` `face_detection.blendshapes`, ON when installed): `mediapipe==0.10.35`. MUST be installed as `pip install mediapipe==0.10.35 --no-deps` then `pip install absl-py flatbuffers` — NEVER a plain `pip install mediapipe`, whose bundled `opencv-contrib-python` would double-install the `cv2` namespace against Facet's `opencv-python`. Degrades silently to the landmark-geometry scores when absent. Model bundle `face_landmarker.task` (~3.6 MiB) auto-downloads to `pretrained_models/`. See [docs/FACE_RECOGNITION.md](docs/FACE_RECOGNITION.md).

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
- Without significant face: `aggregate * 0.30 + aesthetic * 0.40 + comp_score * 0.30` (face_quality weight split evenly between aesthetic and composition)

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

**Technical:** noise_sigma, contrast_score, dynamic_range_stops, mean_saturation, is_monochrome, focal_length_35mm, scoring_model, distortion_attributes (JSON, --recompute-distortions), skin_tone_delta, skin_tone_cast (--recompute-skin-tone)

**Histogram:** histogram_spread, histogram_bimodality, mean_luminance, raw_color_entropy, shadow_clipped, highlight_clipped

**Composition:** composition_pattern (SAMP-Net), power_point_score, leading_lines_score, composition_explanation, isolation_bonus

**Form/Color (explainable, opt-in `--recompute-form`):** form_symmetry, form_balance, form_edge_entropy, form_fractal, color_harmony

**Subject Saliency:** subject_sharpness, subject_prominence, subject_placement, bg_separation

**Burst/Duplicates:** burst_group_id, is_burst_lead, is_blink, duplicate_group_id, is_duplicate_lead, phash

**User Actions:** star_rating, is_favorite, is_rejected

**AI/Content:** caption (VLM-generated text description), caption_translated, caption_embedding (BLOB; text-tower embedding of the caption — the caption-semantic moment signal), narrative_moment (zero-shot scene/activity moment, e.g. `beach`/`celebration`/`other`), narrative_moment_confidence, junk_kind (zero-shot non-photo junk: `screenshot`/`document`/`receipt`/`meme`/`slide`, `not_junk` = evaluated clean, NULL = not evaluated), vlm_critique, vlm_critique_translated (VLM critique cache)

**Location:** gps_latitude, gps_longitude

**Tags/Recognition:** tags (JSON), person_id, face_embedding (BLOB)

**Raw data (for recalculation):** clip_embedding (BLOB), histogram_data (BLOB), raw_sharpness_variance, config_version, scanned_at

**Lookup tables:**
- `photo_tags(photo_path, tag)` - Normalized tag lookup for fast exact-match queries (replaces `LIKE '%tag%'`)
- `faces(id, photo_path, face_index, embedding, bbox_*, person_id, confidence, face_thumbnail, eyes_open_score, smile_score)` - Face embeddings and thumbnails for recognition (`eyes_open_score`/`smile_score` per-face, from 106-pt landmarks)
- `persons(id, name, representative_face_id, face_count, centroid, auto_clustered, face_thumbnail)` - Person clusters (name=NULL for auto-clustered)
- `albums(id, user_id, name, description, cover_photo_path, is_smart, smart_filter_json, share_token, created_at, updated_at)` - Photo albums (manual, smart, and shared)
- `album_photos(id, album_id, photo_path, position, added_at)` - Album membership with ordering
- `album_client_picks(id, album_id→albums CASCADE, photo_path, picked, comment, client_name, created_at, updated_at, UNIQUE(album_id, photo_path))` - Client proofing picks (isolated from owner ratings)
- `location_names(lat_grid, lon_grid, city, region, country, display_name)` - Reverse geocoding cache (0.1° grid cells)
- `comparisons(id, photo_a_path, photo_b_path, winner, category, timestamp, session_id, user_id, source)` - Pairwise photo comparisons (`source`: `vote` = explicit A/B, `culling` = derived from burst/similar culling decisions, `rating` = synthetic from star ratings/favorites)
- `learned_scores(photo_path, learned_score, comparison_count, category, updated_at, user_id)` - Scores derived from comparisons
- `weight_optimization_runs(id, timestamp, category, comparisons_used, old_weights, new_weights, mse_before, mse_after)` - Weight optimization history
- `weight_config_snapshots(id, timestamp, category, weights, description, accuracy_before, accuracy_after, comparisons_used, created_by)` - Saved weight configurations
- `recommendation_history(id, run_timestamp, config_version_hash, issue_type, target_category, target_key, old_value, proposed_value, was_applied)` - Scoring recommendation audit trail
- `user_preferences(user_id, photo_path, star_rating, is_favorite, is_rejected)` - Per-user photo ratings (multi-user mode)
- `scan_runs(id, started_at, finished_at, status, mode, args_json, total_files, processed_files, failed_files)` - One row per scan invocation (status: running/completed/interrupted/failed; powers `--resume`)
- `scan_failures(scan_run_id, path, stage, error, timestamp)` - Per-file scan errors (powers `--retry-failed`)
- `stats_cache(key, value, updated_at)` - Precomputed statistics with TTL (also holds the persisted percentile snapshot for drift tracking)
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
  "mmap_size_mb": 2048,
  "cache_size_mb": 128,
  "slow_request_ms": 1000
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

**AI Critique:** `GET /api/critique?path=<photo_path>&mode=rule|vlm` — rule-based score breakdown (all profiles) or VLM-powered critique (16gb/24gb only). `mode=vlm` uses a configurable structured prompt (`critique.vlm`), caches to `photos.vlm_critique`, and translates on demand (`refresh=true` regenerates). The per-face batch endpoint `POST /api/culling-group/faces` now returns persisted `eyes_open_score`/`smile_score` plus a `thresholds` object.

**Saliency Overlay:** `GET /api/saliency_overlay?path=` returns a translucent BiRefNet heatmap PNG (alpha = saliency) recomputed on demand from the stored 640px thumbnail (the mask is never persisted; the model loads once via `api/model_cache.get_or_load_saliency_scorer`). `GET /api/photo/face_markers?path=` returns per-face boxes + eye centres (normalised 0..1) and `eyes_open_score`/`is_blink` reconstructed from stored 106-point landmarks (no model). Both read-only; the critique dialog's "Show overlay" toggle composites them. Gated by `viewer.features.show_saliency_overlay` (default `true`).

**Saliency-Aware Social Crop:** `GET /api/photo/social_crop?path=&preset=` (edition-gated) returns the CROPPED full-resolution JPEG for a configured social aspect preset (`social_export.presets`, e.g. `square` 1:1, `portrait_4x5`, `story_9x16`), framing the detected subject — something Lightroom export presets cannot do. The crop is the largest rectangle of the target aspect that fits the image, centered on the subject, clamped at edges (deterministic pure math in `processing/social_crop.py`). Subject box fallback chain: persisted BiRefNet box `photos.subject_bbox` (JSON `[x0,y0,x1,y1]` normalized 0..1, written by the saliency pass + `--recompute-saliency`, extracted in `models/saliency_scorer.bbox_from_mask`) → union of `faces` bboxes → center crop. `GET /api/photo/social_crop/preview?path=&preset=` returns just `{preset, aspect, source: saliency|faces|center, rect}` (normalized) from stored dimensions — no original decode — for the UI overlay/tooltip. Original decode reuses `utils.image_loading.load_image_from_path` (RAW via rawpy, HEIC via pillow-heif, EXIF orientation applied). Config: `social_export` block (`presets`, `jpeg_quality`). Gated by `viewer.features.show_social_export` (default `true`). Column: `subject_bbox`.

**Memories:** `GET /api/memories?date=YYYY-MM-DD` — photos taken on the same calendar date in previous years ("On This Day"). The viewer plays the matches as a randomized full-screen diaporama (slideshow) rather than the old grid modal; the nav button tooltip spells this out.

**AI Captioning:** `GET /api/caption?path=<path>` — generate or retrieve AI caption for a photo. Bulk generation via `--generate-captions` CLI.

**Timeline:** `GET /api/timeline?cursor=&limit=&direction=` and `GET /api/timeline/dates?year=&month=` — chronological photo browsing with date navigation. Angular route: `/timeline`.

**Photo Sharing:** `POST|DELETE /api/albums/{id}/share` to generate/revoke share tokens, `GET /api/shared/album/{id}?token=` for public access. Angular route: `/shared/album/:id`.

**AI Culling (Similar Groups):** `GET /api/similar-groups?threshold=&page=&per_page=` — groups of visually similar photos for culling, accessible via similarity tab in burst culling.

**Map View:** `GET /api/photos/map?bounds=&zoom=&limit=` and `GET /api/photos/map/count` — geotagged photo locations for Leaflet map. Angular route: `/map`.

**Capsules:** `GET /api/capsules?page=&per_page=&refresh=&date_from=&date_to=` — curated photo diaporamas grouped by theme. The page header carries an intro line explaining its purpose (curated diaporamas grouped by theme/place/people/time; click a capsule to play it). `GET /api/capsules/{id}/photos` — photos for a capsule. `POST /api/capsules/{id}/save-album` — save capsule as album. Angular route: `/capsules`. Capsule types: journey (GPS trips with reverse geocoding), faces_of, seasonal, golden, color_story, this_week, location, person_pair, seeded, progress, color_palette, rare_pair, favorites, plus dimension-based: year, month, week, camera, lens, tag, day_of_week, composition, focal_range, category, time_of_day, star_rating, and cross-dimensional combos. Slideshow supports themed transitions (crossfade, slide, zoom, kenburns) per capsule type. Cache TTL configurable via `capsules.freshness_hours` (default: 24).

**Burst Culling:** `GET /api/burst-groups`, `POST /api/burst-groups/select`, `GET /api/culling-groups?group_by=all|burst|similar|scene`, `POST /api/culling-groups/confirm` — burst, similar, and scene group culling workflow. `group_by` (default `all` = merged burst+similar, unchanged for existing callers) selects the grouping; `group_by=scene` serves chronological scene groups from `compute_scenes` (the `sort` param is ignored in scene mode), each with `type:'scene'` plus `start`/`end`/`moment`/`moment_confidence`. `POST /api/culling-groups/confirm` is the unified confirm for every group type — scene culling passes `{group_id, type:'scene', paths, keep_paths}` (handled by `apply_scene_cull()` in `api/routers/scenes.py`), rejecting non-kept photos and recording `source='culling'` comparison rows. `POST /api/culling-group/faces` (body `{paths}`) returns per-face crops + metrics (`eyes_open_score`, `expression_score`, `confidence`, `is_blink`) for every photo in a group in one batch call, recomputed from stored 106-point landmarks — powers the per-face badges in the culling lightbox. `GET /api/photo/cull_preview?path=&style=` (edition-gated) renders a photo's original through a configured darktable style (`--style`, bounded to `raw_processor.darktable.preview_max_edge`) so the darkroom's single view can cull on the developed look; it reuses the download path's darktable-cli machinery and disk-caches rendered JPEGs (keyed by source mtime, style, max edge) under `<db_dir>/.facet_cache/cull_previews/`. `style` is validated against `raw_processor.darktable.cull_styles` (400 otherwise); darktable-cli missing → 503, unreadable original → 404, render error/timeout → 502. The configured styles are surfaced in `GET /api/config` (`cull_styles`, only when non-empty AND the executable resolves) so the palette control hides when unavailable.

**Scenes View:** `GET /api/scenes?page=&per_page=&album_id=&date_from=&date_to=` groups burst leads into chronological "scenes" by an adaptive capture-time gap (`scenes.gap_minutes` floor, widened by `adaptive_k × median`), sub-splitting any run over `scenes.max_scene_size` (cache-only, 1h TTL in `stats_cache`); optional `album_id`/`date_from`/`date_to` scope it (this read-only endpoint and `compute_scenes` are unchanged). The Scenes page (`/scenes`) is now a **read-only** browse for all authenticated users (grid + hover loupe + date/moment headers + album scope picker); its former per-photo reject grid and bulk confirm have been removed, and there is no dedicated `POST /api/scenes/confirm` — scene culling runs through the unified `POST /api/culling-groups/confirm` (see Burst Culling). The only entry to the browse is the per-album **Display scenes of this album** action (visible to all authenticated users); the Scenes entry has been removed from the main nav. An edition-only **Cull this scene** button deep-links into the culling surface in scene granularity (`/culling?group_by=scene&album=&from=&to=`), which edition users also reach via the Culling nav's granularity selector. Gated by `viewer.features.show_scenes`. When `narrative_moment` is populated (see below) each scene is named by its dominant moment and (with `scenes.split_on_moment_change`) sub-split where the moment changes.

**Narrative Moments:** zero-shot layered classifier that labels each photo's scene/activity moment with a library-agnostic **general** vocabulary (e.g. `beach`, `celebration`, `cityscape`, `children`, `nature_wildlife`, `concert`, …, or `other`; `wedding` ships as an opt-in `event_type`) — something Narrative Select / AfterShoot don't do. **Caption-semantic**: each caption is encoded once with the text tower and stored in `caption_embedding`; the moment is the best **max-pooled** cosine of that caption embedding vs per-moment text prompts (`models/moment_classifier.py` L0), with the stored image embedding as the fallback when no caption (each signal has its own `other`-gate thresholds — caption cosines run ~2.4× higher). config-driven L1 face/tag priors (`priors.rules`, vocabulary-agnostic `{kind, when, boost}`; tag rules down-weighted on the caption signal via `caption_tag_scale`; per-`event_types` rule overrides) break near-ties; `models/moment_smoothing.py` L2 Viterbi (stay-heavy, no forward bias — the agnostic vocab has no canonical order) and a forward-backward posterior as the stored per-frame confidence (`narrative_moment_confidence`; neutral `0.5` for `other`); an optional, now-implemented L3 Qwen VLM tie-breaker (`vlm_tiebreak.enabled`, default off) re-classifies only low-posterior / low-margin frames on 16gb/24gb profiles during `--detect-moments` / `--recompute-moments`. Config: `narrative_moments` block (`enabled`, `default_event_type`, `pooling`, per-`event_types` prompt vocabulary, per-signal/per-backend `thresholds`, `priors`, `transitions`, `vlm_tiebreak` (`{enabled, min_confidence, min_margin}`), `caption_min_confidence`). Caption embeddings are stored once so re-labelling is a free cosine (no image decode, no per-image model pass); `--detect-moments` auto-runs at the end of every scan (encoding only new captions), the first full backfill over an existing library is a manual `--detect-moments` (GPU recommended; `--limit N` to sample), and `--recompute-moments` re-labels the whole library. Filter the gallery via `GET /api/photos?narrative_moment=` and the `GET /api/filter_options/narrative_moments` dropdown. Columns: `caption_embedding`, `narrative_moment`, `narrative_moment_confidence`. **Confidence consumers:** the stored `narrative_moment_confidence` posterior drives confidence dimming (labels render dimmed with an "(uncertain)" suffix below `viewer.moment_confidence_min`, default `0` = never dim — in the Scenes header, the Culling scene-group header, and the gallery tooltip, which also shows the confidence %), a "Moment Confidence" sort option (NULLs sink) and a `min_moment_confidence` / `max_moment_confidence` gallery range filter (a new sidebar "Moments" section), a caption gate (`narrative_moments.caption_min_confidence`, default `0` = no gate; when > 0, `--generate-captions` and the on-demand caption endpoint skip unlabelled / `other` / below-threshold photos), and is fed as an auto-normalized input feature to the personal ranker and optionally blended into capsule MMR selection via `capsules.mmr_moment_weight` (default `0.0` = unchanged). **Data-driven vocab (opt-in):** `--discover-moments` (`models/moment_discovery.py`) clusters the stored `caption_embedding` vectors (HDBSCAN), names each cluster from its captions (TF-IDF keyword + centroid-nearest captions as prompts), and writes a proposed `event_types.discovered` block to `scoring_config.discovered.json` for review — it never rewrites the active config (`--discover-min-cluster-size N` tunes granularity).

**Junk Sweep:** zero-shot detector that flags non-photo "junk" (screenshots, scanned documents, receipts, memes, presentation slides) by cosine of the **stored image embedding** vs per-kind text prompts, **max-pooled** per kind (`models/junk_classifier.py`), gated by a `not_junk` contrast prompt set — a photo is only flagged when the best junk kind clears `min_confidence` AND beats the best contrast prompt by `min_margin`. No image decode, no per-image model pass (mirrors moments without the temporal smoothing). Clean photos are persisted as the `not_junk` sentinel (like moments' `other`) so `--detect-junk` scopes to genuinely unevaluated rows (`junk_kind IS NULL`) and never re-loads the whole clean library; `--detect-junk` auto-runs at the end of every scan, and `--recompute-junk` re-evaluates the whole library. Config: `junk_sweep` block (`enabled`, `prompt_template`, `pooling`, per-`kinds` prompt lists, `not_junk_prompts`, per-backend `thresholds` `{open_clip|transformers: {min_confidence, min_margin}}`). Column: `junk_kind`. The viewer's **Junk sweep** review queue (`/junk`, nav gated by `viewer.features.show_junk_sweep` + edition) reuses the gallery grid: filter chips per kind (from `GET /api/filter_options/junk_kinds`), per-photo **Keep** (`POST /api/photo/clear_junk` sets `junk_kind='not_junk'` so the photo leaves the queue permanently and is never re-flagged) / **Reject** (existing `POST /api/photos/batch_reject`), and a bulk **Reject all shown**. Filter the gallery via `GET /api/photos?junk_kind=<kind>` (exact) or `junk_kind=any` (any junk, excludes `not_junk`); the default gallery is unchanged (junk stays visible until the user filters). Gated by `viewer.features.show_junk_sweep` (default `true`).

**Personal Ranker ("My Taste"):** `GET /api/ranker/status` returns the global pooled ranker's training status — `trained`, `comparison_count`, `coverage` (share of embedded photos with a `learned_score`), `cv_accuracy`, `baseline_accuracy`, `improvement_pp` — from the `stats_cache` snapshot written by `train_ranker`. Powers the "My Taste" sort confidence badge. Gated by `viewer.features.show_my_taste`.

**Scan:** `POST /api/scan/start`, `GET /api/scan/status`, `GET /api/scan/stream?token=<jwt>` (SSE), `GET /api/scan/directories` — trigger and monitor scoring scans (superadmin only). The `/stream` endpoint uses Server-Sent Events for real-time progress with automatic fallback to polling. Status payloads include a structured `progress` field (`{phase, current, total, eta_seconds}`) parsed from the CLI's `@FACET_PROGRESS` lines.

**Face Management:** `GET /api/person/{id}/faces`, `POST /api/person/{id}/avatar`, `GET /api/photo/faces`, `POST /api/face/{id}/assign`, `POST /api/photo/assign_all_faces`, `POST /api/photo/unassign_person` — face-to-person assignment and avatar management.

**Photo Actions:** `POST /api/photo/set_rating`, `POST /api/photo/toggle_favorite`, `POST /api/photo/toggle_rejected` — single-photo ratings (DB only, never touch files). Batch variants: `POST /api/photos/batch_favorite`, `POST /api/photos/batch_reject`, `POST /api/photos/batch_rating`.

**Metadata Export:** `POST /api/photo/export_xmp` (single, sidecar only), `POST /api/export/sidecars` (bulk by paths/filters, sidecar only), `POST /api/photo/embed_metadata` (single, embeds into the original file for JPEG/HEIC/TIFF/PNG/DNG via exiftool — the gallery "Write metadata to file" action; RAW originals never modified). All edition-gated.

**Cull to folder:** `POST /api/cull/apply` (edition-gated) physically acts on a culling decision — `copy_keeps` (additive), `move_rejects`, or `trash_rejects` (OS-trash via optional `send2trash`, gated behind `viewer.cull.allow_trash`). `dry_run` defaults true (returns the resolved `would_copy/would_move/would_trash` lists for a preview with no I/O); destructive actions require an explicit `dry_run=false`. The op is bounded server-side to the action's reject state (per-user `is_rejected`): `copy_keeps` acts only on non-rejected photos, `move_rejects`/`trash_rejects` only on rejected ones, so a buggy client can never act outside the user's reject set — the mismatch count is returned as `excluded_by_state`. Destinations go through the same validated `viewer.export.allowed_target_dirs` + scan-dir allow-list as album export; `include_companions` (opt-in, default off — a rejected JPEG must not silently destroy its untouched companion RAW/sidecar) extends the action to the sibling RAW/XMP so a moved shot stays whole. After a real move/trash, run `database.py --cleanup-missing-photos`. `processing.xmp_export.write_metadata(..., embed_original=False)` is sidecar-only by default; embedding is opt-in (this endpoint and the `--export-sidecars --embed-originals` CLI). Keyword lists are read-merged (union), so external Lightroom/darktable keywords are preserved. The CLI `--export-sidecars` / `--import-sidecars` default to the global rating columns; pass `--user <name>` in multi-user mode to read/write that user's `user_preferences` ratings instead (keywords stay global).

**Static Portfolio Export:** `POST /api/albums/{album_id}/export-portfolio` (edition-gated) renders an album into a self-contained static HTML gallery (the thumbsup/sigal use case, native — no external tool) inside a caller-provided `target_dir`. Body `{target_dir, title?, max_edge?, include_captions?}`. The generator (`processing/portfolio_export.py`, pure Python) writes `index.html` (responsive CSS-only grid + inline vanilla-JS lightbox with ZERO external/CDN references — fully offline), an `assets/` folder of sequentially-named JPEGs (no library paths leaked), and a `manifest.json` (counts + per-photo source). Each photo prefers the on-disk ORIGINAL (downscaled to `portfolio.max_edge`, EXIF orientation applied, via `utils.image_loading.load_image_from_path`) and falls back to the stored 640px thumbnail BLOB when the original is unreachable — the source is recorded per photo. `target_dir` is validated by the same `_validate_target_dir_required` allow-list (`viewer.export.allowed_target_dirs` + scan dirs) as cull/album export; album access uses the shared `_check_album_access`; albums over `portfolio.max_photos` (default 500) are refused with a 400. Generation is deterministic and idempotent (rewrites only its own files). Response `{exported, from_original, from_thumbnail, output_dir}`. Config: `portfolio` block. Gated by `viewer.features.show_portfolio_export` (default `true`). See [docs/VIEWER.md](docs/VIEWER.md).

**AI Auto-cull:** `POST /api/culling/auto` (edition-gated) — one-shot cull of a scope (`group_by=all|burst|similar|scene`, optional `album_id`/date range) keeping the best photo per group within a strictness margin. `dry_run` defaults true (returns a per-group preview with no writes); optional Highlights album collects the kept picks. Config: `auto_cull` block.

**Photo Frame / Kiosk:** anonymous, static-token endpoints for login-less kiosk devices (smart photo frames, Home Assistant, ImmichFrame/Immich-Kiosk). `GET /api/frame/photos?token=&count=` → `{photos: [{id, caption?, date_taken?, width, height}]}` where `id` is an opaque signed identifier (the row `rowid` signed with the server secret — **never** a filesystem path). `GET /api/frame/image/{id}?token=&max_edge=` → the photo JPEG (on-disk original downscaled to `frame.max_edge`, falling back to the stored thumbnail when unreachable; long immutable cache). `GET /api/frame/next?token=` → one random curated JPEG per call (`no-store`; the dumb-frame / HA generic-camera case). Auth: `frame.tokens` (opaque strings, compared constant-time as UTF-8 bytes) — empty list → 404 (feature disabled), missing token → 401, wrong/non-ASCII → 403. Curation excludes rejected/junk/blink, honors `min_aggregate`, optional `favorites_only` and `categories` allow-list; `count` capped at `max_count`. Score-weighted random sampling (shuffle of a top-by-score candidate pool). No client UI. Config: `frame` block. See [docs/VIEWER.md](docs/VIEWER.md#photo-frame--kiosk-endpoint).

**Phone Auto-Upload (WebDAV):** a deliberately minimal WebDAV subset under `/dav` (`api/routers/webdav.py`) so phone auto-upload apps (PhotoSync et al.) push photos into an inbox directory that `facet.py --watch` then scores — the PhotoPrism mobile-sync pattern. Methods: `OPTIONS` (advertises `DAV: 1` + `Allow`), `PROPFIND` depth 0/1 (207 multistatus, minimal `xml.etree` propstat), `MKCOL` (201/405/409), `PUT` (streamed to a temp file + `os.replace`, 201 new / 204 overwrite, 413 over `upload.max_file_mb`), `MOVE` (within the share; 201/204, 403 outside), `DELETE` (204), `GET`/`HEAD` (within the share). `LOCK`/`UNLOCK` unimplemented; PROPFIND `infinity` served as depth 1. Auth: HTTP Basic against `upload.username`/`upload.password` (constant-time UTF-8 compare, `WWW-Authenticate: Basic realm="Facet upload"` on 401), never a user session/JWT. The whole tree 404s unless `upload.username`, `upload.password`, and `upload.inbox_dir` are all set. Every path is realpath-contained to `upload.inbox_dir` (traversal / absolute / symlink escape → 403). Config: `upload` block. See [docs/VIEWER.md](docs/VIEWER.md#phone-auto-upload).

**Client Proofing:** `POST /api/shared/album/{id}/session` exchanges a share token (+ optional PIN) for a session; `PUT|GET /api/shared/album/{id}/picks` read/write the client's picks (share-session auth, bounded to album membership); `GET /api/albums/{id}/picks` is the owner view (edition-gated). Picks live in `album_client_picks`, isolated from owner ratings. Gated by `viewer.features.show_proofing` (default `false`).

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
| `face_detection` | `eyes_closed_max` | `4.0` |
| `face_detection` | `poor_expression_min` | `4.0` |
| `face_detection.blendshapes` | `enabled` | `true` (appearance-based eyes/smile via MediaPipe when installed; else geometry fallback) |
| `face_detection.blendshapes` | `min_crop_size` | `192` |
| `processing` | `load_workers` | `num_workers` (multi-pass chunk loader threads, cap 8) |
| `processing` | `raw_decode_concurrency` | `0` (auto: 1-4 from CPU/RAM; `1` = serialized) |
| `processing` | `raw_decode_timeout_seconds` | `120` (`0` = disabled) |
| `processing` | `exif_prefetch` | `true` |
| `face_clustering` | `min_faces_per_person` | `2` |
| `face_clustering` | `min_samples` | `2` |
| `face_clustering` | `merge_threshold` | `0.6` |
| `face_clustering` | `use_gpu` | `"auto"` |
| `models` | `keep_in_ram` | `"auto"` |
| `viewer` | `edition_password` | `""` (empty = disabled) |
| `viewer` | `moment_confidence_min` | `0` (0 = never dim moment labels) |
| `viewer.pagination` | `default_per_page` | `64` |
| `viewer.dropdowns` | `min_photos_for_person` | `10` |
| `viewer.defaults` | `type` | `""` (empty = All Photos) |
| `viewer.defaults` | `sort` | `"aggregate"` |
| `viewer.defaults` | `sort_direction` | `"DESC"` |
| `viewer.defaults` | `hide_blinks` | `true` |
| `viewer.defaults` | `hide_bursts` | `true` |
| `viewer.defaults` | `hide_duplicates` | `true` |
| `viewer.defaults` | `hide_details` | `true` |
| `viewer.defaults` | `tooltip_mode` | `"hover"` |
| `viewer.defaults` | `gallery_mode` | `"mosaic"` |
| `viewer.features` | `show_semantic_search` | `true` |
| `viewer.features` | `show_albums` | `true` |
| `viewer.features` | `show_critique` | `true` |
| `viewer.features` | `show_vlm_critique` | `true` |
| `viewer.features` | `show_embed_metadata` | `true` |
| `viewer.features` | `show_memories` | `true` |
| `viewer.features` | `show_captions` | `true` |
| `viewer.features` | `show_timeline` | `true` |
| `viewer.features` | `show_map` | `true` |
| `viewer.features` | `show_capsules` | `true` |
| `viewer.features` | `show_my_taste` | `true` |
| `viewer.features` | `show_scenes` | `true` |
| `viewer.features` | `show_junk_sweep` | `true` |
| `viewer.features` | `show_similar_button` | `true` |
| `viewer.features` | `show_merge_suggestions` | `true` |
| `viewer.features` | `show_rating_controls` | `true` |
| `viewer.features` | `show_rating_badge` | `true` |
| `viewer.features` | `show_folders` | `true` |
| `viewer.features` | `show_social_export` | `true` |
| `viewer.features` | `show_portfolio_export` | `true` |
| `viewer.features` | `show_proofing` | `false` |
| `social_export` | `jpeg_quality` | `92` |
| `portfolio` | `max_photos` | `500` |
| `portfolio` | `max_edge` | `2048` |
| `portfolio` | `jpeg_quality` | `88` |
| `capsules` | `freshness_hours` | `24` |
| `capsules` | `reverse_geocoding` | `true` |
| `capsules` | `min_aggregate` | `6.0` |
| `capsules` | `max_photos_per_capsule` | `40` |
| `capsules` | `mmr_lambda` | `0.5` |
| `capsules` | `mmr_moment_weight` | `0.0` (0 = unchanged MMR) |
| `similarity_groups` | `default_threshold` | `0.85` |
| `similarity_groups` | `min_group_size` | `2` |
| `similarity_groups` | `max_photos` | `10000` |
| `similarity_groups` | `max_group_size` | `50` |
| `scenes` | `gap_minutes` | `20.0` |
| `scenes` | `max_scene_size` | `60` |
| `scenes` | `adaptive` | `true` |
| `scenes` | `adaptive_k` | `6.0` |
| `scenes` | `min_size` | `2` |
| `scenes` | `max_photos` | `5000` |
| `scenes` | `split_on_moment_change` | `false` |
| `narrative_moments` | `enabled` | `true` |
| `narrative_moments` | `default_event_type` | `"general"` |
| `narrative_moments` | `pooling` | `"max"` |
| `narrative_moments` | `vlm_tiebreak.enabled` | `false` |
| `narrative_moments` | `vlm_tiebreak.min_confidence` | `0.0` |
| `narrative_moments` | `caption_min_confidence` | `0` (0 = no caption gate) |
| `junk_sweep` | `enabled` | `true` |
| `junk_sweep` | `pooling` | `"max"` |
| `junk_sweep` | `thresholds.open_clip` | `{min_confidence: 0.2, min_margin: 0.06}` |
| `junk_sweep` | `thresholds.transformers` | `{min_confidence: 0.1, min_margin: 0.02}` |
| `piaa_prior` | `enabled` | `false` (personal-ranker cold-start prior blend; validation-gated — the 2026-07-07 offline experiment failed the ship criterion, keep off; see `.claude/specs/piaa-cold-start-design.md`) |
| `auto_cull` | `default_strictness` | `50` |
| `auto_cull` | `highlights_min` | `8.0` |
| `frame` | `tokens` | `[]` (empty = feature disabled → 404) |
| `frame` | `count` | `20` |
| `frame` | `max_count` | `100` |
| `frame` | `min_aggregate` | `7.0` |
| `frame` | `max_edge` | `1920` |
| `frame` | `favorites_only` | `false` |
| `frame` | `categories` | `[]` (empty = all) |
| `upload` | `username` | `""` (empty = feature disabled → 404) |
| `upload` | `password` | `""` (empty = feature disabled → 404) |
| `upload` | `inbox_dir` | `""` (empty = feature disabled → 404) |
| `upload` | `max_file_mb` | `500` |
| `distortion_attributes` | `enabled` | `true` |
| `skin_tone` | `cast_delta_threshold` | `12.0` |
| `critique.vlm` | `max_new_tokens` | `320` |
| `vlm_backend` | `type` | `"local"` (`local` \| `ollama` \| `openai_compatible`; remote un-gates VLM on legacy/8gb) |
| `immich` | `url` | `""` (empty = disabled) |
| `viewer.proofing` | `session_minutes` | `1440` |
| `translation` | `target_language` | `"fr"` (supported: fr/de/es/it/pt) |
| `viewer.raw_processor` | `darktable.executable` | `"darktable-cli"` |
| `viewer.raw_processor` | `darktable.profiles` | `[]` (array of `{name, hq, width, height, extra_args}`) |
| `viewer.raw_processor` | `darktable.cull_styles` | `[]` (array of `{name, label_key?}`; edited-look cull preview; empty = hidden) |
| `viewer.raw_processor` | `darktable.preview_max_edge` | `1440` |
| `viewer.raw_processor` | `darktable.preview_timeout_seconds` | `60` |
See [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for the complete reference.
