# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Rules

- **No backward-compatibility fallbacks.** When renaming or restructuring config keys, methods, or APIs, do NOT add legacy aliases, fallback lookups, or shims for old names. Update all references to use the new names directly. Old names should be removed completely.
- **No custom CSS classes in Angular components.** Use plain Tailwind CSS utilities exclusively. Never define custom CSS classes in component `styles`. Use Angular `host` property for `:host` styling (e.g., `host: { class: 'block h-full' }`). All styling must be done via Tailwind utility classes in templates.
- **Use pipes instead of method calls in Angular templates.** Never call component methods from template expressions (e.g., `{{ method(value) }}`). Use Angular pipes for data transformation in templates to avoid unnecessary change detection cycles.
- **No `mock.patch` on FastAPI auth dependencies.** Use `app.dependency_overrides[require_edition] = ...` or the shared `edition_client` / `regular_client` / `superadmin_client` / `anonymous_client` fixtures in `tests/conftest.py`. FastAPI captures dependency callables inside `Depends()` at app creation, so module-level `mock.patch` rebinds the symbol but not the captured reference — the mock is silently inert and tests pass-by-accident.

## Code Review

Run `/review-all:review-all` to review commits and changes — it takes a target (`last commit`, `--staged`, `PR #N`, `vs <branch>`, paths) and runs parallel agents across standards, bugs, security, DRY, performance, tests, API contracts and a11y/i18n, verifying each finding before reporting.

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
| [`panorama-detection.md`](.claude/patterns/panorama-detection.md) | Touching panorama detection, the sequence override table, or any "pending correction" surface |

## Project Overview

Facet is a multi-dimensional photo analysis engine that examines every facet of an image — from aesthetic appeal and composition to facial detail and technical precision — using an ensemble of vision models to surface the photos that truly shine.

**Documentation:** See `docs/` for detailed documentation:
- [docs/CONFIGURATION.md](docs/CONFIGURATION.md) - Full `scoring_config.json` reference with correct defaults
- [docs/COMMANDS.md](docs/COMMANDS.md) - All CLI commands
- [docs/SCORING.md](docs/SCORING.md) - Category system and weight tuning
- [docs/FACE_RECOGNITION.md](docs/FACE_RECOGNITION.md) - Face workflow and clustering
- [docs/VIEWER.md](docs/VIEWER.md) - Web gallery features
- [docs/INTEROP.md](docs/INTEROP.md) - Round-tripping ratings/tags with Lightroom, Capture One, digiKam, darktable
- [docs/IMMICH.md](docs/IMMICH.md) - Syncing ratings/favorites with an Immich server, plus the inbound webhook
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) - Production deployment (Synology NAS, Linux, Docker)

## Commands

Every CLI flag lives in [docs/COMMANDS.md](docs/COMMANDS.md) — it is the complete
reference and a superset of anything listed here. Only the handful used in almost
every session are repeated below.

```bash
# Scan / score a directory (auto multi-pass, VRAM auto-detection)
python facet.py /path/to/photos

# Run the viewer (FastAPI + Angular on localhost:5000)
python viewer.py

# Recompute aggregates after a weight, category or scoring-context change
python facet.py --recompute-average

# Schema init / upgrade
python database.py

# Tests and lint — ALWAYS the venv interpreter, never system Python
venv/bin/python -m pytest tests/ -q
venv/bin/python -m ruff check .
cd client && npm run test          # Vitest builder, not `ng test`
cd client && npx tsc --noEmit -p tsconfig.json
```

A gate that ran through a pipe reports the pipe's exit code, not the command's —
use `${PIPESTATUS[0]}` or redirect to a file before calling a suite green.

## Dependencies

Python packages: `torch`, `torchvision`, `open-clip-torch`, `opencv-python`, `pillow`, `pillow-heif`, `imagehash`, `rawpy`, `fastapi`, `uvicorn`, `pyjwt`, `numpy`, `tqdm`, `exifread`, `insightface`, `scipy`, `scikit-learn`, `hdbscan`, `pyiqa`, `psutil`, `transformers>=5.3.0,<5.16`, `accelerate>=0.25.0`, `reverse_geocoder`

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

**config/** - Configuration package (`config/scoring_config.py`, `config/category_filter.py`, `config/percentile_normalizer.py`):
- `ScoringConfig` - Loads weights from JSON, provides `get_weights()`, `get_category_tags()`, `get_tag_vocabulary()`
- `CategoryFilter` - Evaluates category membership rules (numeric ranges, booleans, tags)
- `determine_category(photo_data, context=None)` - Config-driven category determination; `context` selects a scoring context's evaluation order
- `get_categories(context=None)` - Categories sorted by `priority` ascending, or delta-adjusted for a named scoring context
- `get_scoring_contexts()` / `resolve_context_order(context)` - Scoring-context presets and their memoized, delta-adjusted `[(name, CategoryFilter)]` evaluation order
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

Each category in `scoring_config.json` has `filters` (numeric ranges, booleans, tags) and `modifiers` (bonus, penalty scaling). Evaluated by `CategoryFilter` in `config/category_filter.py`. See [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for the full filter and modifier reference. A `scoring_contexts` block can reorder/exclude categories per album or photo without touching this global priority — see [Viewer API Routes](#viewer-api-routes) below and [docs/SCORING.md](docs/SCORING.md#scoring-contexts).

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

Column and table definitions live in `db/schema.py` (`PHOTOS_COLUMNS`, the `*_COLUMNS`
lists and `init_database`), which is the only source that cannot drift. Read it rather
than a copy. The semantics you cannot read off a column name:

- **`photos` is rewritten wholesale on rescan** (`INSERT OR REPLACE`), so anything the user
  set by hand belongs in a side table — see the invariant list under Viewer API Routes.
- **Sentinels are meaningful:** `junk_kind='not_junk'` and `narrative_moment='other'` mean
  *evaluated and clean*, NULL means *never evaluated*. The detect passes scope on that
  difference.
- **`sequence_*` columns are shared by two passes** — always filter by `sequence_kind`
  before grouping by `sequence_group_id`.
- **`is_sequence_lead`** marks the frame that stands for a set (the middle frame of a
  panorama, the base exposure of a bracket) so the gallery's hide clause is an indexed
  equality rather than a window function per query.
- **`sequence_ev_offset`** is signed the way a camera labels an AEB set: `-2` dark, `+2`
  bright. NULL for panoramas, which have no base exposure.
- **BLOB columns** (`thumbnail`, `clip_embedding`, `caption_embedding`, `histogram_data`,
  `face_embedding`) must be excluded from any bulk scan — the ranker's inference pass and
  the viewer DB export both do this deliberately.
- **`user_preferences` holds per-user ratings** in multi-user mode; the `photos` rating
  columns are the single-user/global fallback. A feature that reads one must know which.

Lookup and side tables: `photo_tags`, `faces`, `persons`, `albums`, `album_photos`,
`album_client_picks`, `photo_scoring_overrides`, `photo_sequence_overrides`,
`location_names`, `comparisons`, `learned_scores`, `weight_optimization_runs`,
`weight_config_snapshots`, `recommendation_history`, `user_preferences`, `scan_runs`,
`scan_failures`, `stats_cache`, plus the virtual tables `photos_fts` (FTS5) and
`photos_vec` (sqlite-vec).

### Performance Optimizations

For large databases (50k+ photos), the following optimizations are available:

**Statistics Cache** - Run `python database.py --refresh-stats` to precompute expensive aggregations:
- Total photo counts
- Camera/lens model counts for dropdowns
- Person counts for face recognition filter
- Category and composition pattern counts
- Filtered counts (hide blinks, hide bursts)
- Gallery filter-sidebar metric ranges and sparkline histograms (`metric_ranges`, 1h TTL)

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

### Viewer API Routes

The route catalogue lives in [docs/VIEWER.md](docs/VIEWER.md) and the handlers in
`api/routers/` — both stay current on their own, so it is not repeated here. What follows is
only what reading those two will NOT tell you.

#### Invariants that will bite you

- **A sequence set's identity is the pair `(sequence_kind, sequence_group_id)`.** The bracket
  and panorama passes share those columns, own disjoint rows, and each renumbers its sets from
  1 every run — so **every reader must filter by kind before grouping by id**. See
  [.claude/patterns/panorama-detection.md](.claude/patterns/panorama-detection.md).
- **`sequence_override` means a correction exists; `sequence_override_pending` means it has not
  been applied.** Never drive a "pending" badge off the first — an override row persists for as
  long as the correction applies.
- **Sticky per-photo state goes in a side table, never a new column on `photos`.**
  `save_photo` / `save_photos_batch` write with `INSERT OR REPLACE`, so a new column is silently
  wiped on the next rescan. This is why `photo_scoring_overrides` and `photo_sequence_overrides`
  exist. For the same reason `POST /api/comparison/override_category` records an override rather
  than writing `photos.category`, which `--recompute-average` would discard.
- **A scoring context is a *delta* over the global priority order**, never a standalone
  ordering — so a category added later cannot go missing from six separate lists. `PUT` requires
  both `promote` and `excluded`; a partial body 422s rather than silently clearing one.
- **Every writer of `scoring_config.json` shares `api.config.CONFIG_WRITE_LOCK`** — priorities,
  weights, contexts, panorama thresholds, the share-secret bootstrap and the plaintext-password
  upgrade. They rewrite different parts of one file, and two locks lost whole updates.
- **`facet.LibraryLock` is per host.** `flock` is host-local on SMB/CIFS, so two machines sharing
  an SMB-mounted DB directory would each believe they hold it (the acquire warns once on such a
  mount; NFS between Linux clients is fine). The mutex is the OS lock, not the file's existence,
  so a leftover file can never wedge a later job.
- **Auto-retrain arms on a counter but fires on idle.** Crossing `auto_retrain.threshold` starts
  an idle timer that each later action pushes back, so the write never lands mid-rating-burst
  where it would contend with the user's own saves.
- **Destructive endpoints are bounded server-side, not by the client.** `POST /api/cull/apply`
  re-derives the target set from the user's own `is_rejected` state and reports the mismatch as
  `excluded_by_state`; `include_companions` is opt-in because a rejected JPEG must not silently
  destroy its untouched companion RAW.
- **`/api/frame/*` ids are signed rowids, never filesystem paths**, and `/dav` authenticates with
  HTTP Basic against `upload.*` — never a user session or JWT — with every path realpath-contained
  to `upload.inbox_dir`.
- **`not_junk` and `other` are stored sentinels, not absences.** They mark a photo as *evaluated
  and clean*, which is what lets `--detect-junk` / `--detect-moments` scope to genuinely
  unevaluated rows instead of re-reading the whole library each run.
- **Known limitation — `path_prefix` scopes the photo list only.** `/api/filter_options/*`,
  `/api/type_counts`, `/api/stats/*`, `/api/timeline`, `/api/search` and the map stay
  library-wide.
- **Known limitation — `api/types.py` builds the gallery type dropdown at import time**, so a
  category-priority reorder only restyles its ordering after a server restart. Filtering itself
  is unaffected.

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

### Key Configuration Defaults

Every key and its default is in [docs/CONFIGURATION.md](docs/CONFIGURATION.md) — do not
duplicate the table here; it drifted from the shipped defaults twice before it was removed.
Only the defaults that routinely surprise are worth carrying:

| Key | Default | Why it surprises |
|-----|---------|------------------|
| `viewer.defaults.hide_bursts` / `hide_duplicates` / `hide_brackets` / `hide_panoramas` | `true` | The gallery hides most of a set **by default**, so a bug in a hide clause makes photos vanish rather than duplicate |
| `viewer.edition_password` | `""` | Empty disables edition gating entirely — the shipped config is an open install |
| `narrative_moments.caption_min_confidence` | `0` | `0` means *no* gate, not "reject everything" |
| `viewer.moment_confidence_min` | `0` | Same inversion: `0` = never dim |
| `piaa_prior.enabled` | `false` | Validation-gated; the 2026-07-07 experiment failed the ship criterion — keep it off |
| `frame.tokens` / `upload.username` | `[]` / `""` | Empty means the whole feature 404s, not that it is unauthenticated |
| `auto_retrain.idle_seconds` | `60` | The retrain is *armed* at `threshold` but only fires after this much quiet, so it never lands mid-rating-burst |
| `panorama_detection.min_frames` | `8` | The strongest discriminator — every confirmed non-panorama was ≤ 6 frames |
