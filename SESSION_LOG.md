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


## 2026-10-22 — Single-pass model residency (no per-chunk reload)

- **Change**: `ChunkedMultiPassProcessor._process_chunk` no longer unloads a plan's only pass group after each chunk. The new `_keeps_plan_resident()` gates it on three conditions: exactly one pass group, `model_manager.device == CUDA_DEVICE`, and `models.keep_in_ram != "never"`. That group loads for chunk 0 and stays in VRAM until the scan ends; the log says so once (`Single pass: keeping … in VRAM for the rest of the scan`).
- **Why**: a one-group plan is the next chunk's first group, and its inference already held every model at once, so the boundary unloaded the roster to host RAM (`.cpu()`) and copied it back at the next chunk's first load (`.to(device)`) — or re-read it from disk where the RAM cache refuses it — for no VRAM the chunk could spend. Measured here (RTX 3090, torch 2.11.0+cu128, CUDA 12.8): pageable 1 GiB round trip ≈ 0.70 s (0.59 s off the card, 0.11 s back); pinned upload ≈ 21.9 GiB/s.
- **Observability**: `metrics['resident_chunks']` (chunks that *started* with the whole group on the card — see `was_resident`) and the scan-summary line `Resident weights: N of M chunks reused the kept single-pass models`.
- **Deliberately not changed**: `ModelManager` — `_load_pass_models` still asks for the group every chunk, so `load_model_only` returns resident models for free and a load that failed at chunk 0 is retried at chunk 1. CPU and Apple MPS keep their per-chunk unload: neither has a VRAM pool separate from the decode, and both plan against RAM.
- **Tests**: new `tests/test_single_pass_residency.py` (10 tests: retention over 3 chunks, manager still holding the models, multi-group plan unchanged, `keep_in_ram: "never"`, cpu/mps, a restricted `--pass` run, failed-load retry, the summary line). `tests/test_scan_decode_overlap.py::test_restricted_single_group_scans_overlap_too` became `test_a_restricted_single_group_scan_hides_its_first_load` (submits == 1, `resident_chunks == 1`, no `('unload','topiq')`). Fault injection: forcing `_keeps_plan_resident()` to return False failed 6 tests (5 new + the overlap one); the restore was verified by `sha256sum` of `processing/multi_pass.py`.
- **Suites**: `test_single_pass_residency`, `test_scan_decode_overlap`, `test_multi_pass`, `test_mps_memory`, `test_ram_cache_trim` all pass. Full `tests/`: 7279 passed, 79 failed — all pre-existing/environmental (the live `scoring_config.json`), reproduced at HEAD in a clean worktree and failing there too once that config is copied in; same for `test_async_routes_do_not_block.py::test_no_route_runs_a_blocking_opener_on_the_event_loop` (`/api/caption` 503).
- **Docs**: `docs/CONFIGURATION.md` plus all six translations (de, es, fr, it, pt, zh) — new "A plan that fits in one pass keeps its models loaded" paragraph, step 2 of "How Multi-Pass Works", the overlap caveat, a RAM-cache note, the `keep_in_ram` row and the 35GB+ planner row. `docs/COMMANDS.md` plus its six translations: the multi-pass bullet no longer claims every pass unloads. `CHANGELOG.md` gained a `[Unreleased] → Changed` entry.
- **Review follow-up**: `resident_chunks` now counts only chunks whose group was already in `model_manager.models` *before* the chunk loaded anything, so a chunk that reloads a model after a chunk-0 load failure is not reported as a reuse (`test_the_missing_model_is_retried_while_its_siblings_stay_resident` extended to 3 chunks; forcing `was_resident` False fails 4 tests).
- **Unresolved**: nothing committed (the `.gitignore` and `client/package-lock.json` edits in the tree are the user's). Consequences to watch: the card now stays occupied for the whole scan, so a viewer search encoder sharing it has less room; chunk 0 is the only chunk whose decode can overlap a load. Separate idea, not implemented: overlap the decode with inference rather than only with the first load.
