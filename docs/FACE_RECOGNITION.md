# Face Recognition

Facet uses InsightFace for face detection and HDBSCAN for clustering faces into persons.

## Overview

1. **Detection** - InsightFace buffalo_l model detects faces and extracts 512-dim embeddings
2. **Clustering** - HDBSCAN groups similar embeddings into person clusters
3. **Management** - Web viewer for merging, renaming, and organizing persons

## Complete Workflow

### Step 1: Extract Faces

During photo scanning, faces are automatically extracted:

```bash
python facet.py /path/to/photos
```

For existing photos without faces:

```bash
python facet.py --extract-faces-gpu-incremental  # New photos only
python facet.py --extract-faces-gpu-force        # All photos (deletes existing)
```

### Step 2: Cluster Faces

Group similar faces into persons:

```bash
python facet.py --cluster-faces-incremental  # Preserves existing persons
```

**Clustering modes:**

| Command | Behavior |
|---------|----------|
| `--cluster-faces-incremental` | Preserves all persons, matches new to existing |
| `--cluster-faces-incremental-named` | Preserves only named persons |
| `--cluster-faces-force` | Deletes all persons, full re-cluster |

### Step 3: Review and Merge

Find duplicate person clusters:

```bash
python facet.py --suggest-person-merges
python facet.py --suggest-person-merges --merge-threshold 0.7  # Stricter
```

Opens browser to merge suggestions page.

### Step 4: Manual Management

In the web viewer:
- Access `/manage_persons` for person management
- Merge: Select source person, click target, confirm
- Rename: Click person name to edit inline
- Delete: Remove person cluster

## Configuration

### Face Detection

```json
{
  "face_detection": {
    "min_confidence_percent": 65,
    "min_face_size": 20,
    "blink_ear_threshold": 0.28
  }
}
```

| Setting | Default | Description |
|---------|---------|-------------|
| `min_confidence_percent` | `65` | Minimum detection confidence |
| `min_face_size` | `20` | Minimum face size in pixels |
| `blink_ear_threshold` | `0.28` | Eye Aspect Ratio for blink detection |

### Face Clustering

```json
{
  "face_clustering": {
    "enabled": true,
    "min_faces_per_person": 2,
    "min_samples": 2,
    "auto_merge_distance_percent": 15,
    "clustering_algorithm": "best",
    "leaf_size": 40,
    "use_gpu": "auto",
    "merge_threshold": 0.6,
    "chunk_size": 10000
  }
}
```

| Setting | Default | Description |
|---------|---------|-------------|
| `min_faces_per_person` | `2` | Minimum photos to create a person |
| `min_samples` | `2` | HDBSCAN min_samples parameter |
| `merge_threshold` | `0.6` | Centroid similarity for matching |
| `use_gpu` | `"auto"` | GPU mode: `auto`, `always`, `never` |

### Face Processing

```json
{
  "face_processing": {
    "crop_padding": 0.3,
    "use_db_thumbnails": true,
    "face_thumbnail_size": 640,
    "face_thumbnail_quality": 90,
    "extract_workers": 2,
    "extract_batch_size": 16,
    "refill_workers": 4,
    "refill_batch_size": 100
  }
}
```

## Clustering Algorithms

For CPU clustering, choose the algorithm based on dataset size:

| Algorithm | Complexity | Best For |
|-----------|------------|----------|
| `boruvka_balltree` | O(n log n) | High-dimensional (recommended for 50K+ faces) |
| `boruvka_kdtree` | O(n log n) | Low-dimensional data |
| `prims_balltree` | O(n²) | Small datasets, memory-constrained |
| `prims_kdtree` | O(n²) | Small datasets |
| `best` | Auto | Let HDBSCAN decide |

**Performance note:** For large datasets, `boruvka_balltree` is critical. With 80K faces, it completes in 2-5 minutes vs hanging with exact algorithms.

## GPU Clustering (cuML)

For very large datasets (80K+ faces), GPU clustering via RAPIDS cuML provides significant speedup.

### Installation

```bash
# Conda
conda install -c rapidsai -c conda-forge -c nvidia cuml cuda-version=12.0

# Pip
pip install --extra-index-url https://pypi.nvidia.com/ "cuml-cu12"
```

### Configuration

```json
{
  "face_clustering": {
    "use_gpu": "auto"
  }
}
```

| Mode | Behavior |
|------|----------|
| `"auto"` | Use GPU if cuML available, fallback to CPU |
| `"always"` | Try GPU, warn and fallback if unavailable |
| `"never"` | Always use CPU |

**Note:** cuML uses its own HDBSCAN implementation. The `algorithm` and `leaf_size` parameters only apply to CPU clustering.

## Blink Detection

Uses Eye Aspect Ratio (EAR) from InsightFace 106-point landmarks.

### How It Works

EAR measures the ratio of eye height to width. When eyes close, EAR drops below the threshold.

### Configuration

```json
{
  "face_detection": {
    "blink_ear_threshold": 0.28
  }
}
```

Lower threshold = stricter detection (more photos flagged as blinks).

### Recompute After Threshold Change

```bash
python facet.py --recompute-blinks
```

Only processes photos with faces, no GPU needed.

## Face Thumbnails

Thumbnails are stored in the database for fast display.

### Storage

- Generated during scanning from full-resolution images
- Stored in `faces.face_thumbnail` column as JPEG BLOBs (~5-10KB each)
- Used by clustering and viewer instead of regenerating

### Regeneration

```bash
# Generate missing thumbnails
python facet.py --refill-face-thumbnails-incremental

# Regenerate ALL thumbnails
python facet.py --refill-face-thumbnails-force
```

Both commands use parallel processing for speed.

## Database Schema

### faces Table

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Primary key |
| `photo_path` | TEXT | Foreign key to photos |
| `face_index` | INTEGER | Index within photo |
| `embedding` | BLOB | 512-dim face embedding |
| `bbox_x`, `bbox_y` | REAL | Bounding box position |
| `bbox_w`, `bbox_h` | REAL | Bounding box size |
| `person_id` | INTEGER | Foreign key to persons |
| `confidence` | REAL | Detection confidence |
| `face_thumbnail` | BLOB | JPEG thumbnail |

### persons Table

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Primary key |
| `name` | TEXT | Person name (NULL = auto-clustered) |
| `representative_face_id` | INTEGER | Best face for avatar |
| `face_count` | INTEGER | Number of faces |
| `centroid` | BLOB | Cluster centroid embedding |
| `auto_clustered` | BOOLEAN | True if auto-generated |
| `face_thumbnail` | BLOB | Person avatar thumbnail |

## Incremental vs Force Modes

### Incremental Clustering

- Preserves all existing persons (named and auto-clustered)
- Clusters only new, unassigned faces
- Matches new clusters to existing persons via centroid similarity
- Updates centroids after merging

**Use when:** Adding new photos to existing collection

### Force Clustering

- Deletes ALL persons including named ones
- Full re-cluster from scratch

**Use when:** Starting fresh or major algorithm changes

### Incremental-Named Clustering

- Preserves only named persons
- Deletes auto-clustered persons
- Re-clusters all unnamed faces

**Use when:** Maintaining curated names while refreshing auto-detected clusters

## Viewer Integration

### Person Filter

- Dropdown shows persons with face thumbnails
- Filter gallery by person

### Person Gallery

- Click person in dropdown to view all their photos
- URL: `/person/<id>`

### Manage Persons Page

Access via header button or `/manage_persons`:

- **Grid View** - All recognized persons
- **Merge** - Select source, click target, confirm
- **Delete** - Remove person cluster
- **Rename** - Click name to edit inline

### Photo Cards

- Small face thumbnails (avatars) shown for recognized people
- Configurable via `viewer.face_thumbnails.output_size_px`

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Clustering hangs | Use `boruvka_balltree` algorithm |
| Too many small clusters | Increase `min_faces_per_person` |
| Faces not grouping | Decrease `merge_threshold` |
| GPU clustering fails | Check cuML installation, use `"never"` to force CPU |
| Thumbnails missing | Run `--refill-face-thumbnails-incremental` |
| Wrong blink detection | Adjust `blink_ear_threshold`, run `--recompute-blinks` |
