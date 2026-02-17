# Commands Reference

## Scanning

| Command | Description |
|---------|-------------|
| `python photos.py /path` | Scan directory (multi-pass mode, auto VRAM detection) |
| `python photos.py /path --force` | Re-scan already processed files |
| `python photos.py /path --single-pass` | Force single-pass mode (all models at once) |
| `python photos.py /path --pass quality` | Run quality scoring pass only |
| `python photos.py /path --pass tags` | Run tagging pass only |
| `python photos.py /path --pass composition` | Run composition pass only |
| `python photos.py /path --pass faces` | Run face detection pass only |
| `python photos.py /path --db custom.db` | Use custom database file |
| `python photos.py /path --config my.json` | Use custom scoring config |

### Processing Modes

**Multi-Pass (Default):** Automatically detects VRAM and loads models sequentially.
Each pass loads its model, processes all photos, then unloads to free VRAM.
This allows using high-quality models even with limited VRAM.

**Single-Pass (`--single-pass`):** Loads all models simultaneously like the legacy
`--batch` mode. Faster but requires more VRAM.

**Specific Pass (`--pass NAME`):** Run only one specific pass on photos. Useful for
updating specific metrics without full reprocessing.

## Preview & Export

| Command | Description |
|---------|-------------|
| `python photos.py /path --dry-run` | Score 10 sample photos without saving |
| `python photos.py /path --dry-run --dry-run-count 20` | Score 20 sample photos |
| `python photos.py --export-csv` | Export all scores to timestamped CSV |
| `python photos.py --export-csv output.csv` | Export to specific CSV file |
| `python photos.py --export-json` | Export all scores to timestamped JSON |
| `python photos.py --export-json output.json` | Export to specific JSON file |

## Recompute Operations

These commands update specific metrics without full photo reprocessing.

| Command | Description |
|---------|-------------|
| `python photos.py --recompute-average` | Recompute aggregate scores (creates backup) |
| `python photos.py --recompute-tags` | Re-tag all photos using configured model |
| `python photos.py --recompute-composition-cpu` | Recompute composition (rule-based, CPU) |
| `python photos.py --recompute-composition-gpu` | Rescan with SAMP-Net (GPU required) |
| `python photos.py --recompute-blinks` | Recompute blink detection |
| `python photos.py --recompute-burst` | Recompute burst detection groups |
| `python photos.py --detect-duplicates` | Detect duplicate photos using pHash comparison |
| `python photos.py --compute-recommendations` | Analyze database, show scoring summary |
| `python photos.py --compute-recommendations --verbose` | Show detailed statistics |
| `python photos.py --compute-recommendations --apply-recommendations` | Auto-apply scoring fixes |
| `python photos.py --compute-recommendations --simulate` | Preview projected changes |

## Face Recognition

| Command | Description |
|---------|-------------|
| `python photos.py --extract-faces-gpu-incremental` | Extract faces for new photos (GPU, parallel) |
| `python photos.py --extract-faces-gpu-force` | Delete all faces and re-extract (GPU) |
| `python photos.py --cluster-faces-incremental` | HDBSCAN clustering, preserves all persons (CPU) |
| `python photos.py --cluster-faces-incremental-named` | Clustering, preserves only named persons (CPU) |
| `python photos.py --cluster-faces-force` | Full re-clustering, deletes all persons (CPU) |
| `python photos.py --suggest-person-merges` | Suggest potential person merges |
| `python photos.py --suggest-person-merges --merge-threshold 0.7` | Use stricter threshold |
| `python photos.py --refill-face-thumbnails-incremental` | Generate missing thumbnails (CPU, parallel) |
| `python photos.py --refill-face-thumbnails-force` | Regenerate ALL thumbnails (CPU, parallel) |

## Thumbnail Management

| Command | Description |
|---------|-------------|
| `python photos.py --fix-thumbnail-rotation` | Fix rotation of existing thumbnails using EXIF data |

Fixes rotation of existing thumbnails in the database by reading EXIF orientation
from original files and rotating the stored thumbnail bytes. This is useful for
photos processed before EXIF handling was added to the codebase.

This is a lightweight operation - it does not re-read full images, only the EXIF
header from each file and the thumbnail from the database.

## Model Information

| Command | Description |
|---------|-------------|
| `python photos.py --list-models` | Show available models and VRAM requirements |

## Weight Optimization (Pairwise Comparison)

| Command | Description |
|---------|-------------|
| `python photos.py --comparison-stats` | Show pairwise comparison statistics |
| `python photos.py --optimize-weights` | Optimize and save weights based on comparisons |

## Configuration

| Command | Description |
|---------|-------------|
| `python photos.py --validate-categories` | Validate category configurations |

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

**Performance tip:** For large databases (50k+ photos), run `--migrate-tags` once and `--optimize` periodically.

## Web Viewer

| Command | Description |
|---------|-------------|
| `python viewer.py` | Start Flask server on http://localhost:5000 |

## Common Workflows

### Initial Setup
```bash
python photos.py /path/to/photos     # Score all photos (auto multi-pass)
python photos.py --cluster-faces-incremental # Cluster faces
python database.py --migrate-tags    # Enable fast tag queries
python viewer.py                     # View results
```

### After Config Changes
```bash
python photos.py --recompute-average  # Update scores with new weights
```

### Face Recognition Setup
```bash
python photos.py /path               # Extract faces during scan
python photos.py --cluster-faces-incremental     # Group into persons
python photos.py --suggest-person-merges         # Find duplicates
# Use /manage_persons in viewer to merge/rename
```

### Switch Tagging Model
```bash
# Edit scoring_config.json: "tagging": {"model": "clip"}
python photos.py --recompute-tags     # Re-tag with new model
```

### Switch VRAM Profile
```bash
# Edit scoring_config.json: "vram_profile": "auto"
# Or use specific: "vram_profile": "8gb"
python photos.py --compute-recommendations  # Check distributions
python photos.py --recompute-average        # Apply new weights
```
