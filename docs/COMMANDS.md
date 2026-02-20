# Commands Reference

## Scanning

| Command | Description |
|---------|-------------|
| `python facet.py /path` | Scan directory (multi-pass mode, auto VRAM detection) |
| `python facet.py /path --force` | Re-scan already processed files |
| `python facet.py /path --single-pass` | Force single-pass mode (all models at once) |
| `python facet.py /path --pass quality` | Run quality scoring pass only |
| `python facet.py /path --pass tags` | Run tagging pass only |
| `python facet.py /path --pass composition` | Run composition pass only |
| `python facet.py /path --pass faces` | Run face detection pass only |
| `python facet.py /path --pass embeddings` | Run CLIP embeddings pass only |
| `python facet.py /path --db custom.db` | Use custom database file |
| `python facet.py /path --config my.json` | Use custom scoring config |

### Processing Modes

**Multi-Pass (Default):** Automatically detects VRAM and loads models sequentially.
Each pass loads its model, processes all photos, then unloads to free VRAM.
This allows using high-quality models even with limited VRAM.

**Single-Pass (`--single-pass`):** Loads all models simultaneously.
Faster but requires more VRAM.

**Specific Pass (`--pass NAME`):** Run only one specific pass on photos. Useful for
updating specific metrics without full reprocessing.

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
| `python facet.py --recompute-composition-cpu` | Recompute composition (rule-based, CPU) |
| `python facet.py --recompute-composition-gpu` | Rescan with SAMP-Net (GPU required) |
| `python facet.py --recompute-blinks` | Recompute blink detection |
| `python facet.py --recompute-burst` | Recompute burst detection groups |
| `python facet.py --detect-duplicates` | Detect duplicate photos using pHash comparison |
| `python facet.py --compute-recommendations` | Analyze database, show scoring summary |
| `python facet.py --compute-recommendations --verbose` | Show detailed statistics |
| `python facet.py --compute-recommendations --apply-recommendations` | Auto-apply scoring fixes |
| `python facet.py --compute-recommendations --simulate` | Preview projected changes |

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
| `python database.py --export-viewer-db` | Export lightweight database for NAS deployment |
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
