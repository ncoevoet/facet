# Face Recognition

> 🌐 **English** · [Français](fr/FACE_RECOGNITION.md) · [Deutsch](de/FACE_RECOGNITION.md) · [Italiano](it/FACE_RECOGNITION.md) · [Español](es/FACE_RECOGNITION.md) · [Português](pt/FACE_RECOGNITION.md)

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

This opens the merge-suggestions page in the browser.

### Step 4: Manage in the Viewer

The remaining work happens in the web viewer, following the pipeline **Extract → Cluster → Merge → Manage**:

- **Merge** duplicate clusters on the Merge Suggestions page.
- **Manage** persons (merge, batch merge, split, hide, rename, delete) on the Manage Persons page.

See [Viewer Integration](#viewer-integration) for the full UI reference.

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

**Performance note:** For large datasets, use `boruvka_balltree`. With 80K faces it completes in 2-5 minutes, where exact algorithms can hang.

## GPU Clustering (cuML)

For large datasets (80K+ faces), GPU clustering via RAPIDS cuML is faster than CPU.

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
| `bbox_x1`, `bbox_y1`, `bbox_x2`, `bbox_y2` | INTEGER | Bounding box corners |
| `confidence` | REAL | Detection confidence |
| `person_id` | INTEGER | Foreign key to persons |
| `face_thumbnail` | BLOB | JPEG thumbnail |
| `landmark_2d_106` | BLOB | 106-point landmarks (blink detection) |
| `embedding_model` | TEXT | Recognition model tag (default `arcface_buffalo_l`) |

### persons Table

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Primary key |
| `name` | TEXT | Person name (NULL = auto-clustered) |
| `representative_face_id` | INTEGER | Best face for avatar |
| `face_count` | INTEGER | Number of faces |
| `centroid` | BLOB | Cluster centroid embedding |
| `auto_clustered` | INTEGER | 1 if auto-generated |
| `face_thumbnail` | BLOB | Person avatar thumbnail |
| `is_hidden` | INTEGER | 1 = excluded from filters/suggestions |

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
- Clicking a person applies a `person_id` filter on the gallery (no dedicated per-person route)

### Manage Persons Page

Access via header button or `/persons`:

- **Grid View** - All recognized persons
- **Merge** - Select source, click target, confirm
- **Batch Merge** - Select multiple persons and merge into one target
- **Split** - Move selected faces into a new person
- **Hide** - Exclude a cluster from the list, filters, and merge suggestions
- **Delete** - Remove person cluster
- **Rename** - Click name to edit inline

### Merge Suggestions Page

Access via `/merge-suggestions` or the "Merge Suggestions" button on the Manage Persons page:

- Shows pairs of persons with similar face embeddings that may be the same individual
- **Threshold slider** — controls similarity cutoff (lower = more suggestions)
- **One-click merge** — merge a suggested pair instantly
- **Batch merge** — select multiple suggestions and merge them all at once

### Photo Cards

- Small face thumbnails (avatars) shown for recognized people
- Configurable via `viewer.face_thumbnails.output_size_px`

## Embedding-space marker (recognition-model safety)

Every face row carries an `embedding_model` tag (column on `faces`, default
`arcface_buffalo_l` — the current InsightFace `buffalo_l` / ArcFace `w600k_r50`
recognition model). Embeddings produced by **different** recognition models live
in **incompatible vector spaces** and must never be clustered together — doing so
silently produces garbage persons with no error.

`FaceClusterer.load_embeddings()` therefore loads only the **active** embedding
space (`ACTIVE_EMBEDDING_MODEL` in `faces/clusterer.py`; a `NULL` tag is treated
as the legacy ArcFace space) and logs a loud warning if faces from any other
space are present and excluded. This is a forward-compatibility guard: it makes a
future recognition-model swap safe by construction.

### Swapping the recognition model (e.g. AdaFace) — deferred plan

A quality upgrade such as **AdaFace** (quality-adaptive margin, better clustering
of blurry/candid faces) is integrable as an opt-in 512-d backend (same storage
path, same HDBSCAN), but is **not yet implemented** because it cannot be
validated without real data. Doing it correctly requires:

1. **Weights + backbone** — an AdaFace checkpoint (e.g. `adaface_ir101_webface12m`)
   plus its IResNet backbone; a new model-cache download.
2. **Aligned crops** — compute the embedding from a `norm_crop(img, face.kps, 112)`
   aligned 112×112 crop at extraction time (the kps exist on the InsightFace
   `face` object but aren't persisted, so AdaFace cannot be back-filled offline —
   it must run during extraction). Verify BGR/normalization match the checkpoint.
3. **Config switch** — add `face_detection.recognition_model: arcface|adaface`
   and resolve `ACTIVE_EMBEDDING_MODEL` from it; tag new faces accordingly.
4. **Full re-extraction + re-cluster** — `--extract-faces-gpu-force` then
   `--cluster-faces-force`, because ArcFace and AdaFace embeddings are not
   comparable. The embedding-space marker above prevents a half-migrated DB from
   silently clustering the two spaces together (it warns and excludes instead).
5. **Quality validation** — measure cluster quality against labelled identities;
   "runs and emits 512-d vectors" does not prove the preprocessing is correct.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Clustering hangs | Use `boruvka_balltree` algorithm |
| Too many small clusters | Increase `min_faces_per_person` |
| Faces not grouping | Decrease `merge_threshold` |
| GPU clustering fails | Check cuML installation, use `"never"` to force CPU |
| Thumbnails missing | Run `--refill-face-thumbnails-incremental` |
| Wrong blink detection | Adjust `blink_ear_threshold`, run `--recompute-blinks` |
| "Excluded N faces from non-active embedding space" warning | A recognition-model change left mixed embeddings — run `--extract-faces-gpu-force` then `--cluster-faces-force` |
