# SESSION LOG

---

## 2026-10-21 — Bare-metal install & GPU setup
- Python 3.12 (`/usr/bin/python3.12`), torch 2.11.0+cu128, profile `24gb` (RTX 3090).
- `client/dist` built, exiftool 13.50 installed.
- **Gotcha**: `insightface` clobbers `onnxruntime-gpu` with CPU build. Fix: `uv pip uninstall onnxruntime onnxruntime-gpu && uv pip install "onnxruntime-gpu>=1.17.0"`.

## 2026-10-21 — Config & Test scan
- `scoring_config.json` configured (`chmod 600`, holds `viewer.edition_password`).
- Verified 14 Sony ARWs on CUDA: 27s inference, peak 20.7 GB VRAM.
- Known harmless warnings: `mediapipe` absent (optional `uv pip install mediapipe==0.10.35 --no-deps`), `transformers` docstrings.

## 2026-10-21 — UI population pass
- `mediapipe==0.10.35 --no-deps` + `absl-py flatbuffers` installed; `cv2` still a single namespace (5.0.0).
- `--extract-faces-gpu-force` → per-face blendshape eyes_open/smile on 14/14 faces, then `--recompute-blinks` + `--recompute-eyes-expression`.
- `--cluster-faces-incremental` → 2 persons (frames 370/371/373 vs the other 11), both unnamed.
- `--generate-captions` → 14/14 (~1.5 s/photo, Qwen3.5-4B already cached), then `database.py --rebuild-fts` so captions are searchable.
- `--extract-gps` → 0 updated: the ARWs carry no GPS (A7C II has no GNSS), so Map stays empty.
- Unresolved: photo-level `eyes_open_score` NULL on DSC02371/373 despite a per-face score; the 2 clusters need naming in the UI.

## 2026-10-22 — Web scan enablement, CLI verification & GPU pipeline optimization
- **Web UI & Scans**:
  - Enabled `viewer.features.show_scan_button: true` and added `/mnt/wd14tb/_MY PHOTOS and VIDEOS/2026/2026-10-21` to `viewer.scan_directories` in `scoring_config.json`.
  - Clarified auth model: Single-User Mode uses `viewer.edition_password` login; `superadmin` is multi-user only.
  - Verified scan architecture: web-spawned scans pipe output into in-memory ring buffer (500 lines) with no cancel endpoint or terminal passthrough; CLI remains the primary interface for scans and maintenance.
  - Verified missing-file cleanup: deleting out-of-band files requires `database.py --cleanup-missing-photos` (in-app delete requires files present on disk to send to trash).
- **GPU Scan Pipeline Tuning (Single Pass)**:
  - Diagnosed initial low GPU utilization (21%, 119W): `24gb` profile scheduled 33.5 GB of models across 2 passes, reloading ~20 GB weights over PCIe every 32 photos.
  - Configured `models.vram_profile: 16gb` and `models.profiles.16gb.tagging_model: clip` (drops Qwen VLM, saves 7 GB VRAM).
  - Set `iqa_extended.qrealign: false` (frees 3 GB VRAM from 0%-weighted model, allowing `insightface` to merge into Pass 1).
  - Reached True Single Pass: all models fit in 20.5 GB VRAM <= 22.5 GB budget. Weights load once and never unload.
  - Set `processing.gpu_batch_size: 32` and `processing.raw_decode_concurrency: 12`.
  - Performance: scan rate accelerated from 4.55s/it to 2.22s/it (ETA reduced from ~3h to <1h; 1,188 photos committed).
  - Identified remaining bottleneck: mechanical 14TB HDD reads (~13.5 MB/s) and LibRaw CPU decode create periodic idle valleys between GPU inference bursts (resolvable by ingesting from NVMe or using JPEGs).
- **Embedded JPEG Extraction & Final Throughput Benchmark**:
  - Extracted embedded 1616x1080 JPEG previews beside `.arw` files via `exiftool -b -PreviewImage -w %d%f.jpg -ext arw ...`.
  - Leveraged Facet's native RAW+JPEG companion pairing (`facet.py:1760`): presence of same-stem `.jpg` automatically bypasses full RAW LibRaw demosaic, while culling/export retains companion `.arw` linking (`include_companions`).
  - Verified coordinate space: face crops are persisted as pre-cut BLOBs (`faces.face_thumbnail`), and bounding boxes are normalized to image dimensions (`api/routers/saliency.py`), ensuring UI overlays match without manual coordinate re-scaling.
  - Final throughput: Single Pass on JPEGs reached **2.40 it/s (0.41s/photo)**, reducing full 2,516-photo scan time from **~3 hours to ~15 minutes (11× total speedup)**.
  - Architecture note: Sawtooth GPU load (spikes to ~85% with valleys at 0%) is inherent to Facet's synchronous per-chunk lifecycle (sequential CPU technical scoring, histogram computation, and SQLite commits between GPU bursts; no asynchronous double-buffering).
- **RAW vs. Extracted Preview Score Comparison (N=261 Matched Pairs)**:
  - **Aesthetics & Face Quality**: Highly consistent and comparable.
    - `aesthetic` / TOPIQ: RAW mean 6.37 vs JPG mean 6.27 (Delta: -0.10, Pearson: 0.83, Spearman rho: 0.80).
    - `face_quality_iqa`: RAW mean 8.26 vs JPG mean 8.36 (Delta: +0.10, Spearman rho: 0.93).
  - **Exposure & Contrast**: Preserves relative ranking, but elevated in absolute value due to camera sRGB tone curve.
    - `contrast_score`: RAW 5.40 vs JPG 7.16 (Delta: +1.76, Spearman rho: 0.95).
    - `exposure_score`: RAW 6.89 vs JPG 8.22 (Delta: +1.34, Spearman rho: 0.91).
  - **Technical Sharpness & Noise**: Shifts significantly due to in-camera unsharp masking, downsampling (1.7MP preview vs 24MP RAW), and hardware noise reduction.
    - `tech_sharpness`: RAW 0.88 vs JPG 1.36 (Delta: +0.48, Spearman rho: 0.34).
    - `eye_sharpness`: RAW 0.81 vs JPG 2.70 (Delta: +1.89, Spearman rho: 0.52).
    - `noise_sigma`: RAW 1.01 vs JPG 0.51 (Delta: -0.50).
  - **Aggregate Score**: RAW 6.08 vs JPG 6.39 (Delta: +0.31, Spearman rho: 0.24). The shift in sharpness/contrast causes moderate rank shuffling in composite aggregate.
  - **Culling Verdict**: Preview JPEGs are reliable for aesthetic, composition, and face quality culling at 11x speed, but absolute technical sharpness reflects Sony camera JPEG processing rather than pure sensor RAW resolution.
- **Unresolved / Next**:
  - Complete full scan of target directory at 2.4 it/s.
  - Clean superseded/duplicate `.arw` rows in database via `database.py --cleanup-missing-photos` or SQLite filter if needed.
  - Restart `viewer.py` to pick up web configuration changes and browse scored library.

