# Face Recognition

> 🌐 **English** · [Français](fr/FACE_RECOGNITION.md) · [Deutsch](de/FACE_RECOGNITION.md) · [Italiano](it/FACE_RECOGNITION.md) · [Español](es/FACE_RECOGNITION.md) · [Português](pt/FACE_RECOGNITION.md) · [简体中文](zh/FACE_RECOGNITION.md)

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
| `min_face_size` | `20` | Minimum face size in pixels (InsightFace only, see note) |
| `blink_ear_threshold` | `0.28` | Eye Aspect Ratio for blink detection |

In commercial mode the YuNet detector uses fixed values (0.7 confidence, 30 px) and ignores `min_confidence_percent` and `min_face_size`.

### Face Clustering

```json
{
  "face_clustering": {
    "enabled": true,
    "min_faces_per_person": 2,
    "min_samples": 2,
    "clustering_algorithm": "best",
    "leaf_size": 40,
    "use_gpu": "auto",
    "thresholds_by_model": {
      "arcface_buffalo_l": { "auto_merge_distance_percent": 15, "merge_threshold": 0.6 },
      "sface": { "auto_merge_distance_percent": 27.5, "merge_threshold": 0.65 }
    }
  }
}
```

| Setting | Default | Description |
|---------|---------|-------------|
| `min_faces_per_person` | `2` | Minimum photos to create a person |
| `min_samples` | `2` | HDBSCAN min_samples parameter |
| `thresholds_by_model` | see JSON | Per model: `auto_merge_distance_percent` and `merge_threshold` (ArcFace `15` / `0.6`, SFace `27.5` / `0.65`) |
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

### GPU and CPU do not produce identical clusters

On the same faces and parameters, cuML makes slightly more, smaller clusters than CPU clustering (about 1.1–1.2× as many). Who is grouped with whom stays about the same, but cluster *counts* differ between a GPU and a CPU run.

**cuML is also not deterministic.** Two GPU runs on the same faces give near-identical cluster counts but different labels.

- **Person IDs are not reproducible across runs.** Name the people you care about; named persons stay stable.
- **Do not diff two clustering runs by label.** Compare face membership instead.

CPU clustering with a fixed `algorithm` is deterministic for the same input.

### Re-clustering and curated people

Every mode except `--cluster-faces-force` keeps existing person records, but all of them recompute every face's person.

- **Interruptions are safe.** Changes are written in one step at the end; a run stopped before then changes nothing.
- **Viewer edits during a run.** A face you reassign while the run is writing its results (the last few seconds) keeps your choice, and the run logs how many it skipped. A save sent then waits for the run; one that waits more than 5 s is refused with "library busy" and must be repeated. An edit made earlier, while faces are still being clustered, is overwritten.

A rebuilt cluster goes back to an existing person when either:

1. its mean embedding is within `merge_threshold` (default 0.6 cosine for ArcFace, 0.65 for SFace) of that person's stored centroid, **or**
2. at least half of its faces belonged to that person before the run.

Rule 2 matters for people photographed over many years: their faces split into tight sub-clusters that sit far from the single averaged centroid. Without it, most faces of named people would not be returned to them.

Because rule 2 follows the previous assignment, an earlier mistake is carried forward. Use `--cluster-faces-force` to start from scratch. When a cluster's faces split evenly between two people, the person who owns its lowest-numbered previously assigned face wins.

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

## Optional OFIQ face quality (commercial mode)

In commercial mode the restricted face-quality model is unavailable. As an optional replacement, install `python-ofiq` (UNICEF's bindings over BSI's OFIQ, ISO/IEC 29794-5; MIT):

```bash
pip install python-ofiq
```

- Wheels exist for Linux x86-64 and macOS arm64 only (on Windows, use WSL2 or Docker). It works with numpy 2 and OpenCV 4.8+.
- On first use Facet downloads the OFIQ models (about 400 MB, MIT/Apache-2.0, SHA-256 pinned) into `pretrained_models/ofiq/`.
- OFIQ's score (0-100) is divided by 10 and stored in `face_quality_iqa`. A photo's value is 0.7 x its worst face + 0.3 x the mean.
- Without `python-ofiq` the column stays NULL and its weight is spread over the other metrics.

## Per-face Expression Signals (eyes-open + smile)

Each face stores two 0-10 scores, used by the culling face panel and photo-level scores: `eyes_open_score` (10 = wide open, 0 = fully closed) and `smile_score` (5 = neutral, 10 = broad smile, 0 = frown).

Two backends produce them on the same scale:

1. **Geometry (always available).** Computed from the stored InsightFace 106-point
   landmarks: Eye Aspect Ratio for eyes, mouth-corner lift for smile.
   `--recompute-face-signals` can backfill them with no GPU and no image reads.
2. **MediaPipe blendshapes (optional).** During scanning and face extraction, each
   face crop runs through the MediaPipe Face Landmarker, whose blendshapes
   (`eyeBlink*`, `mouthSmile*`, `mouthFrown*`) map to the same scales. It reads
   closed eyes, subtle smiles and turned heads better, so its value **replaces**
   the geometric one. If MediaPipe or its model is missing, or the crop is too
   small, the geometric value is kept.

### Installing MediaPipe

MediaPipe is optional. Install it **without** its bundled `opencv-contrib-python`,
which would clash with Facet's `opencv-python` (both provide `cv2`):

```bash
pip install mediapipe==0.10.35 --no-deps
pip install absl-py flatbuffers
```

Never run a plain `pip install mediapipe`.

### Model bundle

The `face_landmarker.task` bundle (~3.6 MiB, Apache-2.0) downloads on first use
to `pretrained_models/face_landmarker.task`. Offline, download it from
`https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task`
and place it there. If the download fails, Facet warns once and uses geometry.

### Configuration

```json
{
  "face_detection": {
    "blendshapes": {
      "enabled": true,
      "min_crop_size": 192,
      "blink_pose_gate_deg": null
    }
  }
}
```

- `enabled` (default `true`): use blendshapes when MediaPipe and the model are
  available. Set `false` to force geometry only.
- `min_crop_size` (default `192`): faces whose padded crop is smaller than this
  (px, shorter side) use geometry instead of an upscaled crop.
- `blink_pose_gate_deg` (default `null` = off): commercial-mode (MediaPipe) analyzer only. A face turned by more than this many degrees (|yaw| or |pitch|) gets no blink verdict and no eyes-open / smile score, since a turned head looks like closed eyes. Testing found no cutoff between 20° and 45° that helped, so it ships off; set it only if your library has many strongly turned faces. It must be a positive number. It applies to newly scanned photos; existing `is_blink` values change only on rescan.

### Recompute

`--recompute-face-signals` uses stored landmarks only: it is **geometry-only** and
does not run MediaPipe. To refresh the MediaPipe scores, re-extract faces with
`--extract-faces-gpu-force`.

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

### Create a Person

You can name a face the clusterer missed straight from the gallery:

1. On a photo card, open the person actions and pick an unassigned face.
2. In the person picker, choose **Create new person** and type a name.
3. The face is attached to the new person (`auto_clustered = 0`).

A face that already belongs to another person is moved, and a person left with no
faces is deleted. In multi-user mode you can only attach faces from photos in your
own or shared directories. API: `POST /api/persons` (see [API.md](API.md)).

### Needs Naming

The Manage Persons page lists large unnamed clusters in a **Needs naming**
tab, each with a name field. A cluster appears there when it has at least
`viewer.persons.needs_naming_min_faces` faces (default `5`).

Unnamed means no name or a blank one, whether the cluster came from clustering or a split; hidden (ignored) persons are left out. The tab is shown in edition mode only, beside **Named**, which lists named persons only, so each person appears once; **Named** is the tab the page opens on.

### Merge Suggestions Page

Access via `/merge-suggestions` or the "Merge Suggestions" button on the Manage Persons page:

- Shows pairs of persons whose faces look alike
- **Threshold slider** — similarity cutoff (lower = more suggestions)
- **One-click merge** — merge a suggested pair
- **Batch merge** — merge several suggestions at once

### Photo Cards

- Small face thumbnails (avatars) shown for recognized people
- Configurable via `viewer.face_thumbnails.output_size_px`

## Embedding-space marker (recognition-model safety)

Each face stores the recognition model that produced it in `embedding_model` (default `arcface_buffalo_l`, the InsightFace `buffalo_l` / ArcFace `w600k_r50` model). Embeddings from different models cannot be compared, so clustering uses only the **active** model's faces. A `NULL` tag counts as ArcFace. If faces from another model are present, Facet excludes them and logs a warning.

### Swapping the recognition model (e.g. AdaFace) — deferred plan

AdaFace (better clustering of blurry or candid faces) is **not implemented yet**. Adopting it would need a full re-extraction and re-cluster (`--extract-faces-gpu-force` then `--cluster-faces-force`), because ArcFace and AdaFace embeddings are not comparable.

### Mixed libraries, re-extraction and unknown values

- **Mixed libraries.** A library can hold ArcFace (512-d) and SFace (128-d) faces at once. Clustering, merge suggestions, similar-person search and centroids each use one model at a time (`persons.centroid_model` records it).
  - The incremental and named-only modes leave the other model's faces and persons alone.
  - `--cluster-faces-force` clears every face assignment and deletes every person, named ones included, whatever the model.
  - To move a library to the active model, run `--extract-faces-gpu-force` (permissive extractor in commercial mode; named persons are kept), then `--cluster-faces-incremental`.
- **Warnings.** A scan warns when stored faces use a model other than the active one, and `--doctor` reports it too. In commercial mode `--doctor` lists what a scan actually loads (YuNet, SFace, Q-ReAlign, plus OFIQ when `python-ofiq` is installed). On CUDA, a scan warns once when InsightFace runs on the CPU; see the `--doctor` ONNX Runtime section and [Installation › ONNX Runtime for face detection](INSTALLATION.md#onnx-runtime-for-face-detection).
- **Named persons survive re-extraction.** `--extract-faces-gpu-force` gives each re-detected face back to the named person whose old face box overlaps it (IoU >= 0.5, one-to-one). Unmatched faces wait for the next clustering run. An interrupted run resumes on the next extraction. Rescanning a photo keeps its named persons the same way.
- **Unknown is not zero.** Without MediaPipe, the permissive analyzer cannot measure eyes, smile or blinks, so they are stored as NULL; blink filters and penalties treat NULL as "not a blink". If a photo's face pass fails, `face_count`, `face_ratio` and `is_group_portrait` are NULL and its stored faces are kept; it scores as having no face until rescanned.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Clustering hangs | Use `boruvka_balltree` algorithm |
| Too many small clusters | Increase `min_faces_per_person` |
| Faces not grouping | Decrease `merge_threshold` |
| GPU clustering fails | Check cuML installation, use `"never"` to force CPU |
| Thumbnails missing | Run `--refill-face-thumbnails-incremental` |
| Wrong blink detection | Adjust `blink_ear_threshold`, run `--recompute-blinks` |
| "Excluded N faces from non-active embedding space" warning | A recognition-model change left mixed embeddings — run `--extract-faces-gpu-force` then `--cluster-faces-incremental` |
