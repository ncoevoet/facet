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

## 2026-10-23 — Residency confirmed in the wild, sidecar cleanup, RAW embedded-preview plan

- **Single-pass residency validated on a real run** (`python facet.py --resume`, run #12): `Single pass: keeping clip, saliency, topiq, topiq_iaa, topiq_nr_face, liqe, samp_net, insightface in VRAM for the rest of the scan` at 11:09:06, after all eight models loaded once between 11:08:46 and 11:09:06. Four chunk boundaries (32 → 72 → 122 → 184 → 261) with no reload; the per-model `unloaded` lines appear only at 11:10:39–40, during shutdown. Interrupted at 261/2255, so `_print_summary()` never ran and the `Resident weights: N of M chunks` line is still unobserved. Committed as `80a5f453` (19 files, +377/−50), not pushed.
- **Card pressure, unchanged**: the roster now stays resident for the whole scan, and the idle desktop already holds 7.59 GB of 25.77 GB. `models.keep_in_ram: "never"` remains the escape hatch; VRAM still sawtooths by design (kept weights as the floor, per-chunk activations reclaimed by `_reclaim_freed_memory()`), and chunk auto-tuning made the first few humps grow (32 → 40 → 50 → 62 → 77 → 96).
- **Sidecar cleanup**: deleted the 2516 `exiftool -PreviewImage` JPEGs beside the ARWs, then `python database.py --cleanup-missing-photos` removed the 522 preview rows (cascade to faces, albums, vector index). DB is back to 1188 ARW rows and the folder to 2516 ARW files; 1328 ARWs are now unscored (the earlier 2255 pending count included the sidecars).
- **RAW embedded-preview investigation** (for an opt-in metrics mode, not implemented):
  - An A7C II (`ILCE-7CM2`) ARW carries three JPEGs: `ThumbnailImage` ~7–9 KB, `PreviewImage` 1616×1080 (~200–400 KB, what `-PreviewImage` writes) and `JpgFromRaw` 7008×4672 (3.2–4.2 MB, what `rawpy.extract_thumb()` returns — `utils/image_loading.extract_raw_preview()` is built on it, and the display path already uses it).
  - An A7 III (`ILCE-7M3`) ARW has **no** `JpgFromRaw`: only the 1616×1080 preview of a 6000×4000 frame (ratio 0.27), so `exiftool -b -JpgFromRaw` writes nothing. Any preview-metrics mode must be gated on preview coverage, not assumed.
  - Cost per A7C II ARW (warm cache, `/proc/self/io` rchar): demosaic 2.14 s / 38.3 MB read vs `extract_thumb` + JPEG decode 0.12 s / 2.5 MB — 15× less I/O, ~17× less CPU. That targets the HDD + LibRaw bottleneck recorded on 2026-10-22 (concurrency is already 12, so no tuning work here).
  - Expected end-to-end: demosaic path 2.22 s/it (≈0.45 it/s), sidecar-JPEG path 2.40 it/s; per-ARW preview extraction should land near 2.0–2.4 it/s, GPU-bound.
  - Rendering deltas (one photo, 1024 px long edge): preview mean luma 121.6 vs demosaic 83.9; Laplacian variance 46.5 vs 15.2 (camera sharpening). That matches the 2026-10-22 N=261 table: aesthetics and face quality hold, tech sharpness / noise / exposure move with the camera's JPEG processing.
  - Pixel space changes 7028×4688 (LibRaw uncropped) → 7008×4672 (camera crop); `photos.image_width/height` and `faces.bbox_*` are rewritten together by a rescan, so migration is a `--force` rescan, not bbox translation.
- **Corrections made during the investigation**:
  - The extracted `-PreviewImage` bytes carry **no EXIF orientation** while the ARW is `Rotate 270 CW`, so portrait sidecars were scanned sideways. To inspect or use preview bytes, copy the tag (`exiftool -tagsfromfile host.arw -Orientation out.jpg`) or use `_upright_preview()`.
  - An earlier "the preview lost 87 faces" reading came from a probe that never rotated the JPEG. Re-run with orientation applied, demosaic, `JpgFromRaw` and `PreviewImage` found the same 4/4 faces on the sampled group shots. The N=261 score deltas from 2026-10-22 remain directionally valid (portrait rows add noise to the magnitudes), but face count is **not** evidence against previews.
  - Concurrency was not re-opened: `processing.raw_decode_concurrency` is already 12 and the 2026-10-22 entry already names HDD reads + LibRaw decode as the remaining bottleneck.
- **Plan written, not implemented**: `~/.opencode/plan/raw-metrics-from-preview.md` (Plan mode blocked repo writes). Opt-in `raw_decode.metrics_from_embedded_preview` (default `false`) + `metrics_preview_min_sensor_ratio: 0.95`; RAW becomes the canonical row when a same-stem JPEG/HEIF exists (inverts today's `_raw_paired_with_jpeg` suppression, which is what scored the sidecars instead of the RAWs); `photos.metrics_render` stamp so a half-rescanned library is visible; `--raw-metrics-preview` for one-off A/B; tests in `tests/test_raw_decode.py`; docs in all seven locales.
- **Test fixtures**: repo-root `a7cii.arw` (has `JpgFromRaw`, 1.87 MB) and `a7iii.arw` (no `JpgFromRaw`) are user-added and **gitignored** by `*.arw` (`.gitignore:127`) — useful for a manual integration check, must not be committed.
- **Unresolved / next**:
  - Implement phase 1 of the RAW plan (config keys, `_decode_raw` branch, one log line, tests) and A/B with `--dry-run --dry-run-count 20` before any `--force` rescan.
  - Bracket handling: `_decode_raw` has no `sequence_kind`, so bracketed frames would also take the camera tone curve — the highlight compression `faithful_bracket_render` exists to avoid.
  - Finish a scan of the folder: run #12 is interrupted and 1328 ARWs are unscored.
  - Pre-existing docs drift, untouched: `ram_chunk_size` documented as 32 and `max_ram_chunk_size` as 128, while the code defaults are 100 and 500 (all seven locales).

## 2026-10-23 — RAW metrics from the camera-embedded preview, phase 1/4: config, CLI, pairing

- **Settings.** `raw_decode.metrics_from_embedded_preview` (default `false`) and `metrics_preview_min_sensor_ratio` (`0.95`) in `RAW_DECODE_DEFAULTS` and the shipped `scoring_config.default.json`. `configure_raw_decode_profile` coerces both (`_coerce_flag`, `_coerce_ratio`), so a config that writes `"true"`/`1` behaves instead of being read as a truthy string, and a malformed ratio falls back to the default rather than raising mid-scan.
- **Decode branch.** `_decode_raw` takes the opt-in branch right after the display-preview one: `extract_raw_preview(photo, min_sensor_ratio=…)`, falling through to `raw.postprocess` whenever it returns None. `extract_raw_preview` now also rejects a preview when `min_sensor_ratio > 0` and the sensor size is unknown (≤0), because coverage cannot be established — the display path's `min_sensor_ratio=0` keeps its old behaviour, so thumbnails are unchanged.
- **Stamps.** `pil_img.info['metrics_render']` is `1` only when the configured preview branch produced the pixels and `0` only on the `raw.postprocess` demosaic; it is deliberately left unset on the LibRaw-unsupported exiftool/DNG-JXL rescue path so an unresolvably decoded file is not claimed as demosaiced. `thumbnail_source` reuses the metrics render when it is `1`, so a scored RAW is not demosaiced a second time for its thumbnail.
- **Pairing inversion.** `_raw_paired_with_jpeg`-style logic was extracted to a module-level pure function `facet._suppressed_companion_paths(files, raw_canonical, resolve=str)` (testable without a filesystem) and inverted when the mode is on: the same-stem JPEG/HEIF is suppressed and the RAW kept, logged as `Skipped N companion JPEG(s) (RAW embedded preview is canonical)`. `_print_scan_summary` gained a `companion_label` kwarg so the summary says `JPEG w/ RAW preview (skipped)`; the default keeps the old wording for every other caller.
- **Ordering.** `_run_scan` now configures the RAW and HDR profiles *before* pairing and before `--dry-run`, which is what makes `--raw-metrics-preview` affect a dry run at all (previously the profile was configured after the pairing decision), and logs `RAW metrics: camera-embedded preview (>= 95% of frame)` so a scan always states which rendering it will score with.
- **One-off flag.** `--raw-metrics-preview` (`cli_args.py`) sets the key for a single run without editing `scoring_config.json` — the A/B path the plan asks for.
- **No destructive migration.** A companion that already had a row from an earlier scan is *not* deleted (it may carry ratings, tags or faces set by hand); the scan warns and points at `--cleanup-missing-photos`. The inverse direction warns symmetrically when a JPEG row pre-exists and the RAW becomes canonical, so "stored twice" is visible in either direction.

## 2026-10-23 — RAW metrics from the camera-embedded preview, phase 2/4: DB stamp and persistence

- **Column.** `photos.metrics_render` (`('metrics_render', 'INTEGER')` in `PHOTOS_COLUMNS`): `0` demosaic, `1` camera preview, NULL for non-RAW rows. It rides the existing additive migration, so `python database.py` adds it and no backfill is needed — old RAW rows simply read as unstamped.
- **One write site.** The stamp is persisted in `save_photos_batch` (which reads `pil_img.info`), not in each caller, so `processing/batch_processor.py` and the multi-pass path both store it without touching `processing/multi_pass.py`; `score_photo_from_pil` also carries `'metrics_render'` in its result dict so a re-score does not drop it.
- **Reporting.** `count_metrics_render(conn)` in `db/render_version.py`, beside the display-side `render_version` helper and documented as its scoring sibling. It imports `METRICS_DEMOSAIC_RENDER`/`METRICS_PREVIEW_RENDER` lazily from `utils/image_loading.py` — the constants live in the writer rather than in `db/`, because putting them in `db/render_version.py` would give the decode path a utils→db import.
- **Not dead code.** Wired into `python database.py --info`: `RAW metrics render: N preview, N demosaic, N unstamped`, so a library rescanned only in part is visible instead of silently mixed, which is the plan's stated risk mitigation for toggling the setting without `--force`.

## 2026-10-23 — RAW metrics from the camera-embedded preview, phase 3/4: tests and A/B

- **`tests/test_raw_decode.py`**: `TestMetricsFromEmbeddedPreview` (default off still demosaics; on + a full-size preview returns the preview, with `rawpy.RawPy.postprocess` monkeypatched to raise so a demosaic would fail the test; a preview below the ratio demosaics; a corrupt preview demosaics; a preview with no sensor size demosaics; `load_image_for_face_crop` stays in the same pixel space), `TestMetricsProfileCoercion`, `TestCompanionPairingInversion` (raw-canonical vs JPEG-canonical, including the explicit `resolve=` injection that keeps it filesystem-free) and `TestRealCameraFixtures`, which skips when the gitignored `a7cii.arw`/`a7iii.arw` are absent.
- **`tests/test_render_version.py::TestMetricsRenderStamp`**: scoring a fake RAW stores the preview dimensions and `1` with the flag on, the demosaic dimensions and `0` off, and NULL for a JPEG row; `count_metrics_render` then counts the three states.
- **`tests/test_scan.py`**: `raw_metrics_preview` added to `_JOB_MODIFIERS`, so the flag invalidates a running scan's configuration like the other decode flags.
- **Suites**: `test_raw_decode` + `test_render_version` → 133 passed; `test_scan`, `test_multi_pass`, `test_single_pass_residency`, `test_scan_decode_overlap` → 204 passed; `test_rescan_preservation`, `test_batch_processor`, `test_scoring_overrides`, `test_channel_clipping`, `test_repair_int_columns` → 51 passed.
- **A/B on real files** (`/tmp/opencode/rawmetrics`, scratch DBs, real ARW copies): the A7C II row moves 4688×7028/`0` → 4672×7008/`1` (mean luma 0.324→0.399, histogram spread 72.9→81.4, `tech_sharpness` 0.35→0.15, noise 0.68→0.25, aggregate 5.641→5.579); the A7 III row is byte-identical in both runs (`6024×4024`, `0`, ratio 0.27 rejects its 1616×1080 preview); a plain JPEG row stays NULL in both; thumbnail bytes are identical (30,493) in both runs, which is the check that the display path did not change.
- **Pairing A/B** (`/tmp/opencode/rawpair`, real copies — symlinks break pairing because `_resolved()` keys the group on the target's dirname): off → only the `foo.jpg` row; on → `foo.arw` 4672×7008 `1` and `JPEG w/ RAW preview (skipped): 1`. Re-scanning the off-mode DB with the flag on fired the "stored twice" warning instead of deleting the JPEG row.
- **`--dry-run` cannot score in this environment** (pre-existing, unrelated to this change): `ERROR [facet.scorer] Error scoring …: A callable function is expected, but <class 'torch.Tensor'> is provided.` reproduces on a plain JPEG with no metrics stamp, so the A/B above used a real scan into a scratch DB rather than `--dry-run`.

## 2026-10-23 — RAW metrics from the camera-embedded preview, phase 4/4: docs, changelog, plan status

- **`docs/CONFIGURATION.md`**: a third case in the "the two profiles are not interchangeable" paragraph, the two JSON keys, two table rows, and a new `### Scoring from the camera-embedded preview` section — the measured I/O and CPU saving, what the score deltas do and do not preserve (ρ 0.80-0.93 for the semantic metrics, the ±0.31 aggregate shift), the per-file gate with the A7C II (0.997) and A7 III (0.27) ratio contrast, the pairing inversion plus the "stored twice" warning, the `metrics_render` split and why toggling needs `--force`, and the bracket caveat.
- **All six translations** (`de`, `es`, `fr`, `it`, `pt`, `zh`) got the same four pieces in `CONFIGURATION.md`; `-ratio` and the `0.95` gate are described in each locale rather than left as English. `docs/COMMANDS.md` and its six translations gained the `--raw-metrics-preview` row, each pointing at its own translated section anchor.
- **Anchor check.** Every new cross-document link was resolved against the target file's headings (all seven `#…preview…` fragments match their translated heading), and the new table rows were inserted inside the existing table rather than after a blank line, which would have rendered them as text.
- **`CHANGELOG.md`**: `[Unreleased] → Added` entry covering the setting, the flag, the stamp, the pairing inversion and the known trade-offs.
- **Plan status.** The plan the earlier session wrote is at `~/.opencode/plan/raw-metrics-from-preview.md` (there is no `RAW_METRICS_FROM_PREVIEW.md` in the repo, contrary to what the phase list suggested); its status line now reads implemented rather than "proposed, not implemented".
- **Commit bisectability, recorded honestly.** Each commit was checked out and smoke-tested. Phase 2 (`a8cb9ef9`) and phase 3 (`109c1ba1`) are green on their own suites. Phase 1 (`49824f5b`) leaves exactly one test red — `test_scan.py::TestLibraryJobCoverage::test_every_cli_flag_is_classified_for_the_library_lock` — because the new flag only enters `_JOB_MODIFIERS` in phase 3; the four-phase order the plan asked for makes that one-test window unavoidable without moving test bookkeeping into the code commit.
- **Full suite and regressions.** `tests/` at HEAD: 80 failed, 7319 passed, 91 skipped. Replaying those same 80 at the pre-change commit `80a5f453` gives the identical 79 failures plus one order-dependent flake (`test_thumbnails.py::…test_a_truncated_rw2_serves_the_stored_thumbnail_briefly`, which passes when the file runs alone), so the change adds no regression; the rest belong to the pre-existing live-`scoring_config.json` families (`test_cull`, `test_export`, `test_thumbnails`, `test_social_crop`, `test_diagnostics`, `test_path_validation`, `test_async_routes_do_not_block`). `ruff check` passes on every changed file after folding one unused `os` import in `tests/test_raw_decode.py` into the test commit.
- **Unresolved / left to the user**: nothing pushed. Phase 5 of the rollout — enable `metrics_from_embedded_preview` in the real `scoring_config.json`, delete the 1,188 `2026-10-21` `.ARW` rows, and `--force` rescan (expect ~2.0-2.4 it/s instead of ~0.45) — is not done, because it is destructive and opt-in. The plan's **≥ 2.0 it/s** acceptance target is therefore still unmeasured end to end; only the per-file decode cost (0.12 s / 2.5 MB read against 2.14 s / 38.3 MB) and the frame/gate behaviour were verified. A timed sample scan is the first thing to run before enabling it on the library.




