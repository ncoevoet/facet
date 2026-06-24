# Commands Reference

> 🌐 **English** · [Français](fr/COMMANDS.md) · [Deutsch](de/COMMANDS.md) · [Italiano](it/COMMANDS.md) · [Español](es/COMMANDS.md)

[Scanning](#scanning) · [Preview & Export](#preview--export) · [Recompute Operations](#recompute-operations) · [Face Recognition](#face-recognition) · [Thumbnail Management](#thumbnail-management) · [Diagnostics](#diagnostics) · [Model Information](#model-information) · [Weight Optimization](#weight-optimization-pairwise-comparison) · [Configuration](#configuration) · [Tagging](#tagging) · [Database Validation](#database-validation) · [Database Maintenance](#database-maintenance) · [Web Viewer](#web-viewer) · [Common Workflows](#common-workflows)

> Requirement tags used below: `[GPU]` · `[8gb/16gb/24gb]` / `[16gb/24gb]` / `[24gb]` (VRAM profile). See the [feature matrix](../README.md#feature-availability--requirements).

## Scanning

| Command | Description |
|---------|-------------|
| `python facet.py /path` | Scan directory (multi-pass mode, auto VRAM detection) |
| `python facet.py /path --force` | Re-scan already processed files |
| `python facet.py /path --single-pass` | Force single-pass mode (all models at once) |
| `python facet.py /path --pass quality` | Run TOPIQ quality scoring pass only |
| `python facet.py /path --pass quality-iaa` | Run TOPIQ IAA aesthetic merit scoring only |
| `python facet.py /path --pass quality-face` | Run TOPIQ NR-Face quality scoring only |
| `python facet.py /path --pass quality-liqe` | Run LIQE quality + distortion diagnosis only |
| `python facet.py /path --pass tags` | Run tagging pass only (model depends on VRAM profile) |
| `python facet.py /path --pass composition` | Run SAMP-Net composition pattern detection only |
| `python facet.py /path --pass faces` | Run InsightFace face detection only |
| `python facet.py /path --pass embeddings` | Run CLIP/SigLIP embedding extraction only |
| `python facet.py /path --pass saliency` | Run BiRefNet subject saliency detection only |
| `python facet.py /path --db custom.db` | Use custom database file |
| `python facet.py /path --config my.json` | Use custom scoring config |
| `python facet.py --resume` | Resume the last interrupted/failed scan (reuses its directories; with `--force`, skips files already re-scored since that run started) |
| `python facet.py --retry-failed` | Re-process only the files that failed during the last scan run (`--retry-failed all` for failures across all runs) |
| `python facet.py /path --force-since 2026-01-01` | Like `--force`, but only re-process photos last scanned before the date |
| `python facet.py /path --watch` | Stay running and re-scan whenever new photos appear (requires `pip install watchdog`; `--watch-debounce N` tunes the quiet period, default 30s) |

### Scan Bookkeeping

Every scan records a row in `scan_runs` (status, mode, directories, counters)
and per-file errors in `scan_failures` (path, stage, error). Interrupting a
scan with Ctrl+C marks the run `interrupted` so `--resume` can pick it up;
failed files are visible and retryable instead of being silently retried on
every incremental scan. The CLI also emits structured `@FACET_PROGRESS` JSON
lines (phase, current/total, ETA) which the viewer's scan API surfaces in the
`progress` field of `/api/scan/status` and the SSE stream.

### Processing Modes

**Multi-pass (default):** detects VRAM and loads models sequentially. Each pass loads its model, processes all photos, then unloads to free VRAM, so high-quality models run even with limited VRAM.

**Single-pass (`--single-pass`):** loads all models at once. Faster, needs more VRAM.

**Specific pass (`--pass NAME`):** run one pass only, to update specific metrics without full reprocessing. Available passes:

| Pass | Model | Output | VRAM |
|------|-------|--------|------|
| `quality` | TOPIQ | `aesthetic` score (0-10) | ~2 GB |
| `quality-iaa` | TOPIQ IAA | `aesthetic_iaa` score (artistic merit vs technical quality, AVA-trained) | Shared w/ TOPIQ |
| `quality-face` | TOPIQ NR-Face | `face_quality_iqa` score (purpose-built face quality) | Shared w/ TOPIQ |
| `quality-liqe` | LIQE | `liqe_score` + distortion diagnosis (blur, overexposure, noise) | ~2 GB |
| `tags` | CLIP / Qwen VLM | Semantic tags from configured vocabulary | 0-16 GB |
| `composition` | SAMP-Net | `composition_pattern` (14 patterns) + `comp_score` | ~2 GB |
| `faces` | InsightFace buffalo_l | Face detection, landmarks, blink detection, recognition embeddings | ~2 GB |
| `embeddings` | CLIP ViT-L-14 or SigLIP 2 NaFlex | `clip_embedding` BLOB for similarity/tagging | 4-5 GB |
| `saliency` | BiRefNet_dynamic | `subject_sharpness`, `subject_prominence`, `subject_placement`, `bg_separation` | ~2 GB |

## Preview & Export

| Command | Description |
|---------|-------------|
| `python facet.py /path --dry-run` | Score 10 sample photos without saving |
| `python facet.py /path --dry-run --dry-run-count 20` | Score 20 sample photos |
| `python facet.py --export-csv` | Export all scores to timestamped CSV |
| `python facet.py --export-csv output.csv` | Export to specific CSV file |
| `python facet.py --export-json` | Export all scores to timestamped JSON |
| `python facet.py --export-json output.json` | Export to specific JSON file |
| `python facet.py --import-sidecars` | Import ratings/labels/tags from `<image>.xmp` sidecars back into the DB (all photos) |
| `python facet.py --import-sidecars /path` | Import sidecars only for photos under a path subtree |
| `python facet.py --import-sidecars --user alice` | Multi-user mode: import ratings into Alice's `user_preferences` instead of the global columns (keywords stay global) |
| `python facet.py --export-sidecars` | Write/merge `<image>.xmp` sidecars from the DB for all photos (sidecar only) |
| `python facet.py --export-sidecars /path` | Export sidecars only for photos under a path subtree |
| `python facet.py --export-sidecars --user alice` | Multi-user mode: export Alice's `user_preferences` ratings instead of the global columns (keywords stay global) |
| `python facet.py --export-sidecars --embed-originals` | Also embed metadata **in-file** for JPEG/HEIC/TIFF/PNG/DNG (rewrites the originals) |

> **Two-way metadata sync.** Facet writes ratings, color labels, keywords, captions and named-face regions to a standard `<image>.xmp` sidecar that the whole ecosystem reads (Lightroom, darktable, digiKam, immich, …). **By default the original image is never modified** — only the sidecar is written/merged. To embed the metadata *in-file* for JPEG/HEIC/TIFF/PNG/DNG (so editors that ignore sidecars also see it), opt in explicitly: the viewer's per-thumbnail **"Write metadata to file"** action, or the CLI `--export-sidecars --embed-originals`. RAW originals are never modified. Embedding and safe sidecar merging require **exiftool** (existing/foreign keywords are read and merged into the union, never wiped); without it, Facet falls back to a dependency-free pure-XML sidecar. `--import-sidecars` is the reverse direction: it folds external edits back into Facet — ratings/labels apply *newest-wins* (by `xmp:MetadataDate`, else sidecar mtime, vs the photo's `scanned_at`), and keywords are merged (union), so Facet's auto-tags are never lost.
>
> **Caveats.** The photo-side timestamp for *newest-wins* is `scanned_at` (the last scan), not a per-rating edit time — so a sidecar newer than the last scan can override a rating you changed in Facet *after* that scan. Run `--import-sidecars` before re-rating in Facet if the external editor is the source of truth. By default the CLI `--import-sidecars` / `--export-sidecars` operate on the **global single-user** rating columns. In multi-user mode, pass `--user <name>` to read/write that user's `user_preferences` ratings instead (keywords remain global either way). If you use the `photo_tags` lookup table, run `python database.py --migrate-tags` after importing.

## Recompute Operations

These commands update specific metrics without full photo reprocessing.

| Command | Description |
|---------|-------------|
| `python facet.py --recompute-average` | Recompute aggregate scores (creates backup) |
| `python facet.py --recompute-category portrait` | Recompute scores for a single category only |
| `python facet.py --recompute-tags` | Re-tag all photos using configured model |
| `python facet.py --recompute-tags-vlm` | Re-tag all photos using VLM tagger |
| `python facet.py --recompute-saliency` | `[GPU]` `[16gb/24gb]` Recompute subject saliency metrics (BiRefNet_dynamic) |
| `python facet.py --recompute-composition-cpu` | Recompute composition, rule-based (CPU, any profile) |
| `python facet.py --recompute-composition-gpu` | `[GPU]` Recompute composition with SAMP-Net |
| `python facet.py --recompute-iqa` | `[GPU]` `[8gb/16gb/24gb]` Recompute supplementary IQA metrics (TOPIQ IAA, NR-Face, LIQE) from stored thumbnails |
| `python facet.py --recompute-ocr` | Extract in-image text into `ocr_text` from thumbnails (opt-in; no-op without an OCR engine; run `--rebuild-fts` after to index) |
| `python facet.py --recompute-colors` | Extract dominant hue + warm/cool color temperature from thumbnails (CPU, fast) into `dominant_hue` / `color_temp` |
| `python facet.py --upgrade-db` | Migrate schema and run the full backfill chain: extract-gps, detect-duplicates, recompute-iqa, saliency, composition-cpu, burst, blinks, average. Idempotent; skips heavy steps like captioning. |
| `python facet.py --recompute-blinks` | Recompute blink detection from stored landmarks (CPU, fast) |
| `python facet.py --recompute-eyes-expression` | Recompute eyes-open + expression scores from stored landmarks (CPU, fast) |
| `python facet.py --recompute-burst` | Recompute burst detection groups |
| `python facet.py --detect-duplicates` | Detect duplicate photos via pHash |
| `python facet.py --sweep-dedup-thresholds [labels.json]` | Evaluate near-dup cosine thresholds (precision/recall table with labels, else candidate-cosine distribution) |
| `python facet.py --generate-captions` | `[GPU]` `[16gb/24gb]` Generate AI captions for photos using VLM |
| `python facet.py --translate-captions` | Translate English captions to configured target language (CPU, MarianMT) |
| `python facet.py --extract-gps` | Extract GPS coordinates from EXIF data into database columns |
| `python facet.py --rescan-gps` | Re-extract GPS coordinates from EXIF for all photos (overwrites existing) |
| `python facet.py --recompute-embeddings` | Recompute CLIP/SigLIP embeddings for all photos (required after model switch) |
| `python facet.py --score-topiq` | Backfill TOPIQ quality scores from stored thumbnails (GPU required) |
| `python facet.py --backfill-focal-35mm` | Backfill 35mm-equivalent focal length from EXIF for photos missing it |
| `python facet.py --compute-recommendations` | Analyze database, show scoring summary |
| `python facet.py --compute-recommendations --verbose` | Show detailed statistics |
| `python facet.py --compute-recommendations --apply-recommendations` | Auto-apply scoring fixes |
| `python facet.py --compute-recommendations --simulate` | Preview projected changes |

### Supplementary Quality Models

Three additional PyIQA models score beyond the primary TOPIQ aesthetic score. They share VRAM with TOPIQ and run as part of the default multi-pass pipeline.

- **TOPIQ IAA** (`--pass quality-iaa`): AVA-trained artistic aesthetic merit, separate from technical quality. Stored as `aesthetic_iaa`.
- **TOPIQ NR-Face** (`--pass quality-face`): face-region quality assessment. Stored as `face_quality_iqa`.
- **LIQE** (`--pass quality-liqe`): quality score plus a distortion-type diagnosis (e.g. motion blur, overexposure, noise). Stored as `liqe_score`.

### Benchmarks & supplementary scores

| Command | Description |
|---------|-------------|
| `python scripts/compute_aesthetic_clip.py --db <path>` | Populate the `aesthetic_clip` column by projecting cached CLIP/SigLIP embeddings onto a text-derived aesthetic axis. Zero extra image inference. Not part of the default `aggregate`. See [docs/SCORING.md](SCORING.md#supplementary-signals-not-in-default-aggregate). |
| `python scripts/benchmark_aesthetic.py --db <path> --ava AVA.txt --photo-dir <dir>` | Compute SRCC + PLCC against the AVA mean-opinion-score ground truth for every populated score column in the DB. Useful when adding or tuning a model variant. |

### Subject Saliency

`--pass saliency` and `--recompute-saliency` use BiRefNet-dynamic (`ZhengPeng7/BiRefNet_dynamic`, via `transformers`) to generate a binary subject mask, then derive four metrics:

- **Subject Sharpness**: Laplacian variance on the subject region vs background — whether the subject is in focus.
- **Subject Prominence**: subject area / frame area — high for a dominant subject (e.g. macro).
- **Subject Placement**: rule-of-thirds score for the subject centroid.
- **Background Separation**: edge-gradient difference between subject boundary and background — bokeh quality.

Requires `transformers` (~2 GB VRAM).

### Tagging Models

The tagging model is selected per VRAM profile:

| Profile | Model | How it works |
|---------|-------|-------------|
| `legacy` | CLIP similarity | Cosine similarity between image embedding and tag-text embeddings. No extra model load. |
| `8gb` | CLIP similarity | Same as legacy, on stored CLIP ViT-L-14 embeddings. |
| `16gb` | Qwen3.5-2B | Multimodal model for semantic scene tagging. |
| `24gb` | Qwen3.5-4B | Larger multimodal model. |

All taggers map output to the configured tag vocabulary. Use `--recompute-tags` to re-tag with the profile's default model, or `--recompute-tags-vlm` for VLM-based re-tagging.

### Embedding Models

Two embedding models available, selected per VRAM profile via `clip_config`:

| Config | Model | Dimensions | Used By |
|--------|-------|-----------|---------|
| `clip` | SigLIP 2 NaFlex SO400M | 1152 | 16gb, 24gb profiles |
| `clip_legacy` | CLIP ViT-L-14 | 768 | legacy, 8gb profiles |

Embeddings power semantic tagging, duplicate detection, similar-photo search, and CLIP+MLP aesthetic (legacy/8gb). Switching models requires re-embedding all photos (`--force`, `--pass embeddings`, or `--recompute-embeddings`).

## Face Recognition

| Command | Description |
|---------|-------------|
| `python facet.py --extract-faces-gpu-incremental` | Extract faces for new photos (GPU, parallel) |
| `python facet.py --extract-faces-gpu-force` | Delete all faces and re-extract (GPU) |
| `python facet.py --cluster-faces-incremental` | HDBSCAN clustering, preserves all persons (CPU) |
| `python facet.py --cluster-faces-incremental-named` | Clustering, preserves only named persons (CPU) |
| `python facet.py --cluster-faces-force` | Full re-clustering, deletes all persons (CPU) |
| `python facet.py --suggest-person-merges` | Suggest potential person merges |
| `python facet.py --suggest-person-merges --merge-threshold 0.7` | Use stricter threshold |
| `python facet.py --refill-face-thumbnails-incremental` | Generate missing thumbnails (CPU, parallel) |
| `python facet.py --refill-face-thumbnails-force` | Regenerate ALL thumbnails (CPU, parallel) |

## Thumbnail Management

| Command | Description |
|---------|-------------|
| `python facet.py --fix-thumbnail-rotation` | Fix rotation of stored thumbnails using EXIF orientation |

Reads EXIF orientation from the original files and rotates the stored thumbnail bytes; for photos processed before EXIF handling existed. It reads only the EXIF header and the stored thumbnail, not the full images.

## Diagnostics

| Command | Description |
|---------|-------------|
| `python facet.py --doctor` | Run diagnostic checks (Python, GPU, dependencies, config, database) |
| `python facet.py --doctor --simulate-gpu "RTX 5070 Ti" --simulate-vram 16` | Simulate GPU hardware for diagnostics |

Reports Python version, PyTorch/CUDA build, GPU detection and driver, VRAM profile recommendation, optional dependencies, and config/database status. When PyTorch can't see the GPU but `nvidia-smi` can, it prints the `pip install` command to fix the CUDA build.

`--simulate-gpu NAME` and `--simulate-vram GB` test behavior with different hardware. Both require `--doctor`; `--simulate-vram` requires `--simulate-gpu`.

## Model Information

| Command | Description |
|---------|-------------|
| `python facet.py --list-models` | Show available models and VRAM requirements |

## Weight Optimization (Pairwise Comparison)

| Command | Description |
|---------|-------------|
| `python facet.py --comparison-stats` | Show pairwise comparison statistics |
| `python facet.py --optimize-weights` | Optimize and save weights from comparisons (all sources, reliability-weighted); applied only if held-out k-fold accuracy beats current weights |
| `python facet.py --optimize-weights --optimize-force` | Apply optimized weights even if the accuracy gate is not met |
| `python facet.py --optimize-weights --optimize-sources vote,culling` | Restrict training data to specific comparison sources |
| `python facet.py --optimize-weights --optimize-category portrait` | Train only on one category and write its v4 `categories[].weights` block |
| `python facet.py --sync-label-comparisons` | Rebuild rating-derived pairs (source=rating) from star ratings/favorites/rejections |
| `python facet.py --train-ranker` | Train the personal ranker over [embedding + scores] and write learned_scores (gated on held-out k-fold accuracy vs the aggregate baseline) |
| `python facet.py --train-ranker --ranker-category portrait` | Train the ranker on one category only |
| `python facet.py --train-ranker --train-ranker-force` | Write learned_scores even if the accuracy gate is not met |
| `python facet.py --report-unreviewed-bursts` | Report how many burst groups remain unreviewed (read-only) |
| `python facet.py --eval-iqa-srcc` | Report Spearman SRCC of each IQA/aesthetic metric vs your star ratings (read-only) |
| `python facet.py --mine-insights` | Data-mining report: label inventory, metric-label correlations, category distribution, percentile drift, comparison health |
| `python facet.py --mine-insights report.json` | Same, also writes the full report as JSON |

## Configuration

| Command | Description |
|---------|-------------|
| `python facet.py --validate-categories` | Validate category configurations |

## Tagging

| Command | Description |
|---------|-------------|
| `python tag_existing.py` | Add tags to untagged photos using stored CLIP embeddings |
| `python tag_existing.py --dry-run` | Preview tags without saving |
| `python tag_existing.py --threshold 0.25` | Custom similarity threshold (default: 0.22) |
| `python tag_existing.py --max-tags 3` | Limit tags per photo (default: 5) |
| `python tag_existing.py --force` | Re-tag all photos |
| `python tag_existing.py --db custom.db` | Use custom database |
| `python tag_existing.py --config my.json` | Use custom config |

## Database Validation

| Command | Description |
|---------|-------------|
| `python validate_db.py` | Validate database consistency (interactive) |
| `python validate_db.py --auto-fix` | Automatically fix all issues |
| `python validate_db.py --report-only` | Report without prompting |
| `python validate_db.py --db custom.db` | Validate custom database |

Checks: Score ranges, face metrics, BLOB corruption, embedding sizes, orphaned faces, statistical outliers.

## Database Maintenance

| Command | Description |
|---------|-------------|
| `python database.py` | Initialize/upgrade schema |
| `python database.py --info` | Show schema information |
| `python database.py --migrate-tags` | Populate photo_tags lookup (10-50x faster queries) |
| `python database.py --rebuild-fts` | Rebuild FTS5 full-text search index from captions/tags |
| `python database.py --populate-vec` | Populate sqlite-vec vector search table from embeddings |
| `python database.py --refresh-stats` | Refresh statistics cache |
| `python database.py --stats-info` | Show cache status and age |
| `python database.py --vacuum` | Reclaim space, defragment |
| `python database.py --analyze` | Update query planner statistics |
| `python database.py --optimize` | Run VACUUM and ANALYZE |
| `python database.py --export-viewer-db` | Export lightweight viewer database (strips BLOBs, downsizes thumbnails; incremental if output exists) |
| `python database.py --export-viewer-db --force-export` | Force full re-export, even if viewer DB already exists |
| `python database.py --cleanup-orphaned-persons` | Remove persons with no associated faces |
| `python database.py --cleanup-missing-photos` | Remove photos no longer on disk from the database (cascading deletes clean up tags, detected faces, etc.; also clears album memberships, the vector index, and invalidates stats cache) |
| `python database.py --cleanup-missing-photos --dry-run` | Preview missing files without deleting |
| `python database.py --cleanup-missing-photos --force` | Proceed even when every photo appears missing (guard against deleting everything when a volume is unmounted) |
| `python database.py --migrate-storage-fs` | Migrate thumbnails and embeddings from database BLOBs to filesystem |
| `python database.py --migrate-storage-db` | Migrate thumbnails and embeddings from filesystem back to database |
| `python database.py --add-user alice --role admin` | Add a user (prompts for password) |
| `python database.py --add-user alice --role user --display-name "Alice"` | Add user with display name |
| `python database.py --migrate-user-preferences --user alice` | Copy ratings from photos to user_preferences |

**Performance tip:** For large databases (50k+ photos), run `--migrate-tags`, `--rebuild-fts`, and `--populate-vec` once, then `--optimize` periodically.

## Web Viewer

| Command | Description |
|---------|-------------|
| `python viewer.py` | Start server on http://localhost:5000 (API + Angular SPA) |
| `python viewer.py --port 5001` | Bind a different port (or set the `PORT` env var; default 5000) |
| `python viewer.py --host 127.0.0.1` | Bind a specific interface (default `0.0.0.0`) |
| `python viewer.py --production` | Production mode (uvicorn workers) |
| `python viewer.py --production --workers 4` | Production mode with N workers (default 1) |

## Common Workflows

### Initial Setup
```bash
python facet.py /path/to/photos     # Score all photos (auto multi-pass)
python facet.py --cluster-faces-incremental # Cluster faces
python database.py --migrate-tags    # Enable fast tag queries
python viewer.py                    # View results
```

### After Config Changes
```bash
python facet.py --recompute-average                # Update all scores with new weights
python facet.py --recompute-category portrait      # Update only one category (faster)
```

### Face Recognition Setup
```bash
python facet.py /path               # Extract faces during scan
python facet.py --cluster-faces-incremental     # Group into persons
python facet.py --suggest-person-merges         # Find duplicates
# Use /persons in viewer to merge/rename
```

### Multi-User Setup
```bash
# Add users (prompts for password)
python database.py --add-user alice --role superadmin --display-name "Alice"
python database.py --add-user bob --role user --display-name "Bob"
# Edit scoring_config.json to set directories and shared_directories
# Migrate existing ratings to a user
python database.py --migrate-user-preferences --user alice
```

### Switch Tagging Model
```bash
# Edit scoring_config.json: "tagging": {"model": "clip"}
python facet.py --recompute-tags     # Re-tag with new model
```

### Switch VRAM Profile
```bash
# Edit scoring_config.json: "vram_profile": "auto"
# Or use specific: "vram_profile": "8gb"
python facet.py --compute-recommendations  # Check distributions
python facet.py --recompute-average        # Apply new weights
```
