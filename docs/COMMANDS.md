# Commands Reference

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
| `python facet.py /path --pass saliency` | Run InSPyReNet subject saliency detection only |
| `python facet.py /path --db custom.db` | Use custom database file |
| `python facet.py /path --config my.json` | Use custom scoring config |

### Processing Modes

**Multi-Pass (Default):** Automatically detects VRAM and loads models sequentially.
Each pass loads its model, processes all photos, then unloads to free VRAM.
This allows using high-quality models even with limited VRAM.

**Single-Pass (`--single-pass`):** Loads all models simultaneously.
Faster but requires more VRAM.

**Specific Pass (`--pass NAME`):** Run only one specific pass on photos. Useful for
updating specific metrics without full reprocessing. Available passes:

| Pass | Model | Output | VRAM |
|------|-------|--------|------|
| `quality` | TOPIQ | `aesthetic` score (0-10) | ~2 GB |
| `quality-iaa` | TOPIQ IAA | `aesthetic_iaa` score (artistic merit vs technical quality, AVA-trained) | Shared w/ TOPIQ |
| `quality-face` | TOPIQ NR-Face | `face_quality_iqa` score (purpose-built face quality) | Shared w/ TOPIQ |
| `quality-liqe` | LIQE | `liqe_score` + distortion diagnosis (blur, overexposure, noise) | ~2 GB |
| `tags` | CLIP / Qwen VLM | Semantic tags from configured vocabulary | 0-16 GB |
| `composition` | SAMP-Net | `composition_pattern` (14 patterns) + `comp_score` | ~2 GB |
| `faces` | InsightFace buffalo_l | Face detection, landmarks, blink detection, recognition embeddings | ~2 GB |
| `embeddings` | CLIP ViT-L-14 or SigLIP 2 | `clip_embedding` BLOB for similarity/tagging | 4-5 GB |
| `saliency` | InSPyReNet | `subject_sharpness`, `subject_prominence`, `subject_placement`, `bg_separation` | ~2 GB |

## Preview & Export

| Command | Description |
|---------|-------------|
| `python facet.py /path --dry-run` | Score 10 sample photos without saving |
| `python facet.py /path --dry-run --dry-run-count 20` | Score 20 sample photos |
| `python facet.py --export-csv` | Export all scores to timestamped CSV |
| `python facet.py --export-csv output.csv` | Export to specific CSV file |
| `python facet.py --export-json` | Export all scores to timestamped JSON |
| `python facet.py --export-json output.json` | Export to specific JSON file |

## Recompute Operations

These commands update specific metrics without full photo reprocessing.

| Command | Description |
|---------|-------------|
| `python facet.py --recompute-average` | Recompute aggregate scores (creates backup) |
| `python facet.py --recompute-category portrait` | Recompute scores for a single category only |
| `python facet.py --recompute-tags` | Re-tag all photos using configured model |
| `python facet.py --recompute-tags-vlm` | Re-tag all photos using VLM tagger |
| `python facet.py --recompute-saliency` | Recompute subject saliency metrics (InSPyReNet, GPU) |
| `python facet.py --recompute-composition-cpu` | Recompute composition (rule-based, CPU) |
| `python facet.py --recompute-composition-gpu` | Rescan with SAMP-Net (GPU required) |
| `python facet.py --recompute-iqa` | Recompute supplementary IQA metrics (TOPIQ IAA, NR-Face, LIQE) from thumbnails |
| `python facet.py --recompute-blinks` | Recompute blink detection |
| `python facet.py --recompute-burst` | Recompute burst detection groups |
| `python facet.py --detect-duplicates` | Detect duplicate photos using pHash comparison |
| `python facet.py --compute-recommendations` | Analyze database, show scoring summary |
| `python facet.py --compute-recommendations --verbose` | Show detailed statistics |
| `python facet.py --compute-recommendations --apply-recommendations` | Auto-apply scoring fixes |
| `python facet.py --compute-recommendations --simulate` | Preview projected changes |

### Supplementary Quality Models

Three additional PyIQA models provide specialized scoring beyond the primary TOPIQ aesthetic score:

- **TOPIQ IAA** (`--pass quality-iaa`): Trained on the AVA dataset for artistic aesthetic merit. Measures artistic quality (composition, creativity, visual impact) separately from technical quality. Stored as `aesthetic_iaa`.
- **TOPIQ NR-Face** (`--pass quality-face`): Purpose-built face quality assessment. More accurate than generic quality models for face regions. Stored as `face_quality_iqa`.
- **LIQE** (`--pass quality-liqe`): Outputs both a quality score and a distortion type diagnosis (e.g., "motion blur", "overexposure", "noise"). Stored as `liqe_score`.

These models share VRAM with the primary TOPIQ model and run as part of the default multi-pass pipeline.

### Subject Saliency

The `--pass saliency` and `--recompute-saliency` commands use InSPyReNet (via the `transparent-background` library) to generate a binary subject mask, then derive four metrics:

- **Subject Sharpness**: Laplacian variance on the subject mask region vs background. Detects whether the main subject is in focus.
- **Subject Prominence**: Ratio of subject area to total frame area. High values indicate a dominant subject (e.g., macro photos).
- **Subject Placement**: Rule-of-thirds scoring for the subject centroid position. Measures compositional placement.
- **Background Separation**: Edge gradient difference between subject boundary and background. Measures bokeh quality.

Requires `pip install transparent-background` (~2 GB VRAM).

### Tagging Models

The tagging model is selected per VRAM profile:

| Profile | Model | How It Works |
|---------|-------|-------------|
| `legacy` | CLIP similarity | Cosine similarity between image embedding and tag text embeddings — captures mood/atmosphere (dramatic, golden_hour, vintage). No extra model load. |
| `8gb` | CLIP similarity | Same as legacy. Uses stored CLIP ViT-L-14 embeddings. |
| `16gb` | Qwen3-VL-2B | Vision-language model prompted with vocabulary list — best semantic scene understanding for size (landscape, architecture, reflection). |
| `24gb` | Qwen2.5-VL-7B | Largest VLM — most capable for complex/ambiguous scenes with nuanced tags. |

All taggers map output to the configured tag vocabulary. Use `--recompute-tags` to re-tag with the profile's default model, or `--recompute-tags-vlm` for VLM-based re-tagging.

### Embedding Models

Two embedding models available, selected per VRAM profile via `clip_config`:

| Config | Model | Dimensions | Used By |
|--------|-------|-----------|---------|
| `clip` | SigLIP 2 SO400M-384 | 1152 | 16gb, 24gb profiles |
| `clip_legacy` | CLIP ViT-L-14 | 768 | legacy, 8gb profiles |

Embeddings power: semantic tagging, duplicate detection, similar photo search, and CLIP+MLP aesthetic (legacy/8gb). Switching models requires re-embedding all photos (`--force` or `--pass embeddings`).

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
| `python facet.py --fix-thumbnail-rotation` | Fix rotation of existing thumbnails using EXIF data |

Fixes rotation of existing thumbnails in the database by reading EXIF orientation
from original files and rotating the stored thumbnail bytes. This is useful for
photos processed before EXIF handling was added to the codebase.

This is a lightweight operation - it does not re-read full images, only the EXIF
header from each file and the thumbnail from the database.

## Model Information

| Command | Description |
|---------|-------------|
| `python facet.py --list-models` | Show available models and VRAM requirements |

## Weight Optimization (Pairwise Comparison)

| Command | Description |
|---------|-------------|
| `python facet.py --comparison-stats` | Show pairwise comparison statistics |
| `python facet.py --optimize-weights` | Optimize and save weights based on comparisons |

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
| `python database.py --refresh-stats` | Refresh statistics cache |
| `python database.py --stats-info` | Show cache status and age |
| `python database.py --vacuum` | Reclaim space, defragment |
| `python database.py --analyze` | Update query planner statistics |
| `python database.py --optimize` | Run VACUUM and ANALYZE |
| `python database.py --export-viewer-db` | Export/update lightweight database for NAS deployment (incremental if output exists) |
| `python database.py --export-viewer-db --force-export` | Force full re-export, even if viewer DB already exists |
| `python database.py --cleanup-orphaned-persons` | Remove persons with no associated faces |
| `python database.py --add-user alice --role admin` | Add a user (prompts for password) |
| `python database.py --add-user alice --role user --display-name "Alice"` | Add user with display name |
| `python database.py --migrate-user-preferences --user alice` | Copy ratings from photos to user_preferences |

**Performance tip:** For large databases (50k+ photos), run `--migrate-tags` once and `--optimize` periodically.

## Web Viewer

| Command | Description |
|---------|-------------|
| `python viewer.py` | Start server on http://localhost:5000 (API + Angular SPA) |
| `python viewer.py --production` | Production mode with 4 workers |

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
