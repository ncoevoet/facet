# Commands Reference

> 🌐 **English** · [Français](fr/COMMANDS.md) · [Deutsch](de/COMMANDS.md) · [Italiano](it/COMMANDS.md) · [Español](es/COMMANDS.md) · [Português](pt/COMMANDS.md) · [简体中文](zh/COMMANDS.md)

[Scanning](#scanning) · [Preview & Export](#preview--export) · [Recompute Operations](#recompute-operations) · [Face Recognition](#face-recognition) · [Thumbnail Management](#thumbnail-management) · [Diagnostics](#diagnostics) · [Model Information](#model-information) · [Weight Optimization](#weight-optimization-pairwise-comparison) · [Configuration](#configuration) · [Tagging](#tagging) · [Database Validation](#database-validation) · [Database Maintenance](#database-maintenance) · [Web Viewer](#web-viewer) · [Common Workflows](#common-workflows)

> Requirement tags used below: `[GPU]` · `[8gb/16gb/24gb]` / `[16gb/24gb]` / `[24gb]` (VRAM profile). See the [feature matrix](INSTALLATION.md#feature-requirements).

## Scanning

| Command | Description |
|---------|-------------|
| `python facet.py /path` | Scan a directory (multi-pass, auto VRAM detection) |
| `python facet.py /path --force` | Re-scan files already processed |
| `python facet.py /path --single-pass` | Load all models at once; `legacy`/`8gb` only (see [Processing Modes](#processing-modes)) |
| `python facet.py /path --pass quality` | Run TOPIQ quality scoring only |
| `python facet.py /path --pass quality-iaa` | Run TOPIQ IAA aesthetic merit scoring only |
| `python facet.py /path --pass quality-face` | Run TOPIQ NR-Face quality scoring only |
| `python facet.py /path --pass quality-liqe` | Run LIQE quality + distortion diagnosis only |
| `python facet.py /path --pass tags` | Run tagging only (model depends on VRAM profile) |
| `python facet.py /path --pass composition` | Run SAMP-Net composition pattern detection only |
| `python facet.py /path --pass faces` | Run InsightFace face detection only |
| `python facet.py /path --pass embeddings` | Run CLIP/SigLIP embedding extraction only (writes no tags) |
| `python facet.py /path --pass saliency` | Run BiRefNet subject saliency detection only |
| `python facet.py /path --db custom.db` | Use a custom database file |
| `python facet.py /path --config my.json` | Use a custom scoring config |
| `python facet.py --resume` | Resume the last interrupted, failed or crashed scan |
| `python facet.py --retry-failed` | Re-process files that failed in the last scan (`--retry-failed all` for every run) |
| `python facet.py /path --force-since 2026-01-01` | Like `--force`, only for photos last scanned before the date |
| `python facet.py /path --watch` | Re-scan when new photos appear (needs `pip install watchdog`; `--watch-debounce N`, default 30s) |
| `python facet.py /path --force-low-space` | Skip the free-space check before the scan |

**`--resume`** also recovers a scan killed by a crash, out-of-memory or power loss: a run still marked `running` whose heartbeat is older than `processing.scan_stale_seconds` (default 120). It reuses that run's directories. With `--force`, it skips files already re-scored since the run started. It refuses to start if another scan looks live.

### Scan Bookkeeping

Facet records every scan (status, mode, directories, counters) and every per-file error. Ctrl+C marks the run `interrupted`, so `--resume` can continue it. Failed files are listed and retried only with `--retry-failed`. The viewer shows scan progress from the CLI's `@FACET_PROGRESS` lines.

### Processing Modes

**Multi-pass (default):** detects VRAM and loads models one at a time. Each pass loads its model, processes all photos, then unloads it, so high-quality models run even with limited VRAM.

**Single-pass (`--single-pass`):** loads all models at once. Faster, but needs more VRAM.

- It scores aesthetics with the CLIP+MLP head, so it applies to the `legacy` and `8gb` profiles.
- On `16gb` and `24gb` the aesthetic model is TOPIQ, which only multi-pass runs. A single-pass request (`--single-pass` or `processing.mode: "single-pass"`) logs a warning and runs multi-pass.
- `--pass NAME` and `--dry-run` skip that check.
- Commercial mode keeps single-pass, because native Q-ReAlign scores the aesthetic there.

**Upgrade note:** earlier versions saved a neutral 5.0 aesthetic for every photo of a single-pass scan on `16gb`/`24gb`. Re-scan those folders with `--force` in multi-pass. To find them: `SELECT path FROM photos WHERE scoring_model = 'topiq' AND aesthetic = 5.0 AND topiq_score IS NULL`.

**Specific pass (`--pass NAME`):** runs one pass only, to update some metrics without full reprocessing.

| Pass | Model | Output | VRAM |
|------|-------|--------|------|
| `quality` | TOPIQ | `aesthetic` score (0-10) | ~2 GB |
| `quality-iaa` | TOPIQ IAA | `aesthetic_iaa` (artistic merit, AVA-trained) | Shared w/ TOPIQ |
| `quality-face` | TOPIQ NR-Face | `face_quality_iqa` (face quality) | Shared w/ TOPIQ |
| `quality-liqe` | LIQE | `liqe_score` + distortion diagnosis (blur, overexposure, noise) | ~2 GB |
| `tags` | CLIP / Qwen VLM | Semantic tags from the configured vocabulary | 0-16 GB |
| `composition` | SAMP-Net | `composition_pattern` (8 patterns) + `comp_score` | ~2 GB |
| `faces` | InsightFace buffalo_l | Faces, landmarks, blinks, recognition embeddings | ~2 GB |
| `embeddings` | CLIP ViT-L-14 or SigLIP 2 NaFlex | `clip_embedding` for similarity and tagging | 4-5 GB |
| `saliency` | BiRefNet_dynamic | `subject_sharpness`, `subject_prominence`, `subject_placement`, `bg_separation` | ~3 GB |

## Preview & Export

| Command | Description |
|---------|-------------|
| `python facet.py /path --dry-run` | Score 10 sample photos without saving |
| `python facet.py /path --dry-run --dry-run-count 20` | Score 20 sample photos |
| `python facet.py --export-csv` | Export all scores to a timestamped CSV |
| `python facet.py --export-csv output.csv` | Export to a specific CSV file |
| `python facet.py --export-json` | Export every stored metric to a timestamped JSON |
| `python facet.py --export-json output.json` | Export to a specific JSON file |
| `python facet.py --export-manifest` | Write `facet_manifest.json` for external tools such as the Lightroom Classic plug-in |
| `python facet.py --export-manifest /path` | Limit the manifest to photos under a path |
| `python facet.py --export-manifest --user alice` | Multi-user mode: use Alice's ratings (tags and scores stay global) |
| `python facet.py --import-lightroom FILE` | Import the plug-in's ratings, picks and rejects; Lightroom wins |
| `python facet.py --import-lightroom FILE --user alice` | Multi-user mode: write Alice's ratings; **required** on a multi-user install |
| `python facet.py --import-sidecars` | Import ratings, labels, Keep/Reject, manual GPS and keywords from XMP sidecars |
| `python facet.py --import-sidecars /path` | Import only for photos under a path |
| `python facet.py --import-sidecars /path --dry-run` | Print a JSON plan of changes and conflicts; writes nothing |
| `python facet.py --import-sidecars /path --sidecar-fields keywords,gps` | Import only these groups: `review` (stars, favorite, reject, Keep), `gps`, `keywords` (default: all) |
| `python facet.py --import-sidecars /path --overwrite-sidecar-review` | Apply review fields even over a newer local edit (`newer_local_edit`); preview with `--dry-run` first |
| `python facet.py --import-sidecars --user alice` | Multi-user mode: import ratings and Keep/Reject into Alice's account, for photos she can see |
| `python facet.py --import-sidecars --sidecar-naming full` | Read `<image.ext>.xmp` / `<image.ext>.facet.xmp` (default); newer file wins |
| `python facet.py --import-sidecars --sidecar-naming basename` | Read `<image>.xmp` (extension removed); refuse shared basenames |
| `python facet.py --import-sidecars --sidecar-naming auto` | Accept either naming; skip a photo that has both |
| `python facet.py --import-sidecars --overwrite-manual-gps` | Replace manual GPS already set in Facet with the sidecar's |
| `python facet.py --export-sidecars` | Write or merge `<image>.xmp` sidecars for all photos |
| `python facet.py --export-sidecars /path --reconcile-keywords` | Also remove Facet-owned keywords no longer present (needs ExifTool) |
| `python facet.py --export-sidecars /path` | Export sidecars only for photos under a path |
| `python facet.py --export-sidecars --user alice` | Multi-user mode: export Alice's ratings and Keep/Reject, for photos she can see |
| `python facet.py --export-sidecars --embed-originals` | Also write metadata **into** JPEG/HEIC/TIFF/PNG/DNG originals |
| `python facet.py --export-sidecars --score-to-stars` | Set `xmp:Rating` from the score for photos you have not rated |

**Dry run.** On `16gb`/`24gb` the aesthetic column shows `n/a`, because TOPIQ runs only in a real scan (commercial mode shows the Q-ReAlign score). The aggregate counts it as a neutral 5.0.

**CSV and JSON.** The `tags` column holds AI tags only; [manual tags](VIEWER.md#manual-tags) are not included. In JSON, each photo's `scores` object holds every stored metric; NULL, non-finite numbers and BLOBs become `null`. The JSON export refuses to write over the database or its `-wal`/`-shm`/`-journal` files.

**Manifest.**

- The optional argument limits *which photos* are exported. The file is always `facet_manifest.json` in the working directory.
- It carries `star_rating`/`is_favorite`/`is_rejected` (global, or the `--user`'s), `is_burst_lead`, AI plus manual tags, and a `pending_corrections` count. A non-zero count prints a warning pointing to `--detect-panoramas`.
- _manifest version 2_ adds `burst_group_id`, `sequence_kind`, `sequence_group_id` and `score_stars` (the score mapped through `xmp_export.score_to_rating`). A plug-in built for it refuses an older manifest: re-export. See [the Facet plug-in](INTEROP.md#the-facet-plug-in-star-ratings-pick-flags-metadata-fields-and-keywords).

**`--import-lightroom`** reads the plug-in's own export, `facet_lightroom_state.json` (`{"format":"facet-lightroom-state","version":1,"photos":[...]}`), not the manifest. A file in the wrong format is refused before any write. Lightroom's value wins for every field the file carries; omitted fields keep Facet's value. It prints `matched=… unmatched=… changed=…`. See [Lightroom → Facet](INTEROP.md#lightroom--facet).

**Two-way metadata sync.** Facet writes ratings, color labels, keywords, captions and named-face regions to a standard `<image>.xmp` sidecar that Lightroom, darktable, digiKam, immich and others read.

- Originals are never modified unless you add `--embed-originals` (JPEG/HEIC/TIFF/PNG/DNG only; RAW is never touched).
- Keywords are the AI tags plus your [manual tags](VIEWER.md#manual-tags). They are only added, unless `--reconcile-keywords` removes ones Facet wrote before; foreign keywords are kept. See [Manual tags and XMP keywords](INTEROP.md#manual-tags-and-xmp-keywords).
- Embedding and keyword merging need **exiftool**. Without it, Facet writes a plain XML sidecar.

**Sidecar import.**

- Imported keywords become [manual tags](INTEROP.md#manual-tags-and-xmp-keywords); no `--migrate-tags` is needed.
- A Facet decision (Keep, Reject or undecided) with no standard rating or label is applied without the scan-time check.
- With `--user`, keywords and GPS stay global. With `--export-sidecars --user`, keywords, GPS and capture date stay global.
- How a sidecar is weighed against local edits: [Sidecar import preview and review conflicts](INTEROP.md#sidecar-import-preview-and-review-conflicts).

### Immich Sync

Push Facet ratings and favorites to an [Immich](https://immich.app/) server (one-way, Facet → Immich, REST API only). Assets are matched by `originalPath` through the path-prefix mappings in the `immich` config block.

| Command | Description |
|---------|-------------|
| `python facet.py --immich-test` | Check the connection and API key (`immich.url` + `immich.api_key`, sent as `x-api-key`) |
| `python facet.py --immich-sync` | Push star ratings (1–5) and favorites; honors `--dry-run` and `--user` |
| `python facet.py --immich-sync --dry-run` | Report what would change without writing |

Only ratings 1–5 are sent (never 0/−1). An optional top-picks album collects photos above a rating threshold. See [Configuration — Immich Sync](CONFIGURATION.md#immich-sync).

### Immich stack plans

These accept `--config`, `--db` and `--user`; multi-user mode needs an existing owner. Preview never writes. Apply needs the reviewed plan digest.

| CLI | |
|---|---|
| `python facet.py --immich-stacks-plan import --stack-plan-out NEW_JSON` | Preview remote stacks for local import |
| `python facet.py --immich-stacks-plan push --stack-id UUID --stack-plan-out NEW_JSON` | Preview local stacks for remote creation |
| `python facet.py --immich-stacks-apply PLAN_JSON --ack-stack-plan SHA256` | Apply the reviewed plan |

- Repeat `--stack-id UUID` to choose source groups.
- `--stack-plan-out NEW_JSON` writes a new private file (POSIX `0600`) and never overwrites one. On Windows, pick a folder whose ACL restricts access to your account.
- Limits: 1000 groups, 1000 members per group, 20000 members in total, 16 MiB.
- Incomplete mappings and overlaps skip the whole group. Existing groups are never updated.

See [permissions, conflicts and remote race limits](IMMICH.md#manual-stack-import-and-push).

## Recompute Operations

These update metrics or derive new data without re-running the full scoring pipeline. Most reuse stored thumbnails and landmarks and are light on CPU; the AI rows (such as `--generate-captions`) need a GPU.

| Command | Description |
|---------|-------------|
| `python facet.py --recompute-average` | Recompute aggregate scores and categories from stored metrics (no image is re-read) |
| `python facet.py --recompute-category portrait` | Recompute scores for one category only |
| `python facet.py --tag-untagged` | Tag only photos with no tags yet, from stored embeddings |
| `python facet.py --recompute-tags` | Re-tag all photos with the configured model |
| `python facet.py --recompute-tags-vlm` | Re-tag all photos with the VLM tagger |
| `python facet.py --detect-moments` | Label new photos with their narrative moment (runs after every scan) |
| `python facet.py --recompute-moments` | Re-label narrative moments for the whole library |
| `python facet.py --discover-moments` | Propose a moment vocabulary from your captions into `scoring_config.discovered.json` |
| `python facet.py --detect-junk` | Flag screenshots, documents, receipts, memes and slides (runs after every scan) |
| `python facet.py --recompute-junk` | Re-evaluate `junk_kind` for the whole library |
| `python facet.py --recompute-saliency` | `[GPU]` Recompute subject saliency from stored thumbnails; `--force` redoes all |
| `python facet.py --recompute-composition-cpu` | Recompute composition, rule-based (CPU, any profile) |
| `python facet.py --recompute-composition-gpu` | `[GPU]` Recompute composition with SAMP-Net |
| `python facet.py --recompute-iqa` | `[GPU]` Fill missing TOPIQ IAA, NR-Face and LIQE scores from stored thumbnails. Runs on every profile; on CPU (`legacy`) it is much slower |
| `python facet.py --detect-text` | Read in-image text into `ocr_text` so search finds it (opt-in, see note) |
| `python facet.py --recompute-text` | Re-run OCR over the whole library |
| `python facet.py --recompute-colors` | Extract dominant hue and warm/cool temperature into `dominant_hue` / `color_temp` (CPU, fast) |
| `python facet.py --recompute-form` | Recompute symmetry, balance, edge entropy, fractal complexity and color harmony (CPU) |
| `python facet.py --recompute-skin-tone` | Recompute portrait skin-tone naturalness (CPU; advisory critique note only) |
| `python facet.py --recompute-distortions` | Label likely distortions (motion blur, color cast, …) and correlate them with `liqe_score` / `noise_sigma` (advisory) |
| `python facet.py --upgrade-db` | Migrate the schema and run the full backfill chain (see note) |
| `python facet.py --recompute-blinks` | Recompute blink detection from stored landmarks (CPU, fast) |
| `python facet.py --recompute-eyes-expression` | Recompute eyes-open + expression scores from stored landmarks (CPU, fast) |
| `python facet.py --recompute-face-signals` | Backfill per-face eyes-open + smile scores from stored landmarks (CPU, fast) |
| `python facet.py --recompute-burst` | Recompute burst groups (logs `Burst state: N rows changed`) |
| `python facet.py --detect-sequences` | Detect exposure brackets and panoramas (runs after every scan; see note) |
| `python facet.py --detect-panoramas` | Detect panorama sets from stored thumbnails (runs the bracket pass first; CPU) |
| `python facet.py --detect-duplicates` | Detect duplicate photos via pHash (logs `Duplicate state: N rows changed`) |
| `python facet.py --sweep-dedup-thresholds [labels.json]` | Evaluate near-duplicate cosine thresholds (precision/recall with labels) |
| `python facet.py --generate-captions` | `[GPU]` `[16gb/24gb]` Generate AI captions with the VLM |
| `python facet.py --translate-captions` | Translate English captions to the configured language (CPU, MarianMT) |
| `python facet.py --extract-gps` | Copy EXIF GPS into the database; skips locations set in the viewer |
| `python facet.py --rescan-gps` | Re-extract EXIF GPS for all photos (overwrites); skips locations set in the viewer |
| `python facet.py --recompute-embeddings` | Recompute CLIP/SigLIP embeddings for all photos (needed after a model switch) |
| `python facet.py --score-topiq` | `[GPU]` Re-score `topiq_score` for every photo with a thumbnail (overwrites) |
| `python facet.py --backfill-focal-35mm` | Backfill 35mm-equivalent focal length from EXIF where missing |
| `python facet.py --backfill-clipping` | Derive per-channel clipping percentages from stored histograms (resumable) |
| `python facet.py --recompute-silhouette` | Re-derive `is_silhouette` with the face-aware rule (see note) |
| `python facet.py --repair-int-columns` | Round fractional values that an external EXIF writer stored in integer columns (such as ISO) |
| `python facet.py --repair-neutral-iqa` | Clear the fake neutral 5.0 IQA scores stored before 1.20 (see note) |
| `python facet.py --compute-recommendations` | Analyze the database and show a scoring summary |
| `python facet.py --compute-recommendations --verbose` | Show detailed statistics |
| `python facet.py --compute-recommendations --apply-recommendations` | Auto-apply scoring fixes |
| `python facet.py --compute-recommendations --simulate` | Preview projected changes |

**`--recompute-average`** keeps no snapshot: to roll back, restore a weight snapshot and recompute. After upgrading from 1.20 or earlier, run `--recompute-silhouette` first, then `--recompute-average` twice. The first pass stores new percentiles, so the second still changes some rows.

**Moments.**

- `--detect-moments` encodes each new caption once into `caption_embedding`. The first backfill of an existing library is best done on a GPU; add `--limit N` to try it on a sample.
- Add `--dry-run --verbose` to `--recompute-moments` (or `--detect-junk`) to preview without writing.
- `narrative_moments.vlm_tiebreak` (16gb/24gb): when `narrative_moments.vlm_tiebreak.enabled` is set, the profile VLM re-classifies low-confidence frames.
- `--discover-moments` clusters stored caption embeddings and names each cluster. It never rewrites the active config. Run `--detect-moments` first; tune it with `--discover-min-cluster-size N`.
- `--generate-captions` skips unlabelled, `other` and low-confidence photos when `narrative_moments.caption_min_confidence > 0`.

**Junk.** Clean photos are marked `not_junk`, so later runs only check new ones.

**`--detect-text`** is opt-in: it needs `ocr.enabled` in `scoring_config.json` and `pip install easyocr`. See [Configuration — OCR](CONFIGURATION.md#ocr).

**`--detect-sequences`** finds exposure brackets from EXIF, then panoramas from thumbnail geometry, and moves each burst's lead onto its base exposure. It also runs in `--upgrade-db`. The viewer's **Exposure brackets** / **Panoramas** / **HDR panoramas** culling views and the `hide_brackets` / `hide_panoramas` toggles do nothing until it has run. Each run relabels the whole library, so re-running it (or `--detect-panoramas`) picks a new representative frame after you cull the old one.

**`--upgrade-db`** migrates the schema and runs: extract-gps, detect-duplicates, recompute-iqa, saliency, composition-cpu, burst, blinks, eyes-expression, face-signals, average. It is safe to re-run and skips heavy steps like captioning. It also turns back HEIF thumbnails left sideways by pillow-heif 1.6, with their faces; original files are never written. HEIF files it cannot read are retried on the next run.

**`--recompute-silhouette`** reads only the database, commits per batch and honours `--dry-run`.

- The report groups photos by how their face boxes match the thumbnail: `exact`, `scaled`, `count_mismatch` (matching not validated), `other`.
- A photo with no faces, or whose boxes cannot be placed, is set to 0.
- Photos with a NULL `face_count`, or faces but no thumbnail, are left alone (`skipped_face_count_null` / `skipped_no_thumbnail`).
- Run `--recompute-average` afterwards. See [SCORING.md](SCORING.md).

**`--repair-int-columns`** reads only the database. The gallery shows them correctly without it, but range filters and sorts use the stored value, so a photo shown as ISO 63 can be missed. Values that cannot be integers become NULL.

**`--repair-neutral-iqa`** sets to NULL every value exactly 5.0 in `aesthetic_iaa`, `face_quality_iqa` and `liqe_score`, and prints the count per column.

- It leaves `aesthetic`, `topiq_score`, `aesthetic_v25` and `quality_score` alone.
- A real score of exactly 5.00 is cleared too; `--recompute-iqa` refills it, possibly slightly different.
- Then run `--recompute-iqa` and `--recompute-average`.
- Refused with `--dry-run` (exit code 2). Not part of `--upgrade-db`. Reload open gallery pages to see the new filter ranges.

### Supplementary Quality Models

Three PyIQA models score beyond the main TOPIQ aesthetic. They share VRAM with TOPIQ and run in the default multi-pass scan.

- **TOPIQ IAA** (`--pass quality-iaa`): AVA-trained artistic merit, separate from technical quality. Stored as `aesthetic_iaa`.
- **TOPIQ NR-Face** (`--pass quality-face`): face-region quality. Stored as `face_quality_iqa`.
- **LIQE** (`--pass quality-liqe`): quality score plus a distortion diagnosis (motion blur, overexposure, noise). Stored as `liqe_score`.

When a model cannot score a photo:

- It stores NULL, not a neutral 5.0. A GPU out-of-memory error is first retried at half the batch size, down to one image.
- LIQE skips thumbnails whose short side is under 224 px (after bounding the long edge to 1024 px).
- NR-Face skips photos with `face_count` 0. A photo where it finds no face is remembered in `iqa_declined` until a rescan (`--force`), `--refresh-thumbnails` or `--fix-thumbnail-rotation`. Upgrading pyiqa does not clear it.
- Other failures are not stored; the next `--recompute-iqa` tries again.
- Under `--pass quality`, `quality-iaa`, `quality-face` and `quality-liqe`, a failed photo keeps its stored value.
- A full scan records a photo whose TOPIQ model fails, for `--retry-failed`; `--pass quality` does not.

`--recompute-iqa` fills only NULL columns and never replaces a stored value, including a neutral 5.0 from an earlier version. Clear those with `--repair-neutral-iqa`, then run `--recompute-iqa` and `--recompute-average`, or rescan with `--force`. See [Supplementary IQA Dimensions](SCORING.md#supplementary-iqa-dimensions).

### Benchmarks & supplementary scores

| Command | Description |
|---------|-------------|
| `python scripts/compute_aesthetic_clip.py --db <path>` | Fill `aesthetic_clip` from cached embeddings (no image inference; not in the default `aggregate`). See [SCORING.md](SCORING.md#supplementary-signals-not-in-default-aggregate) |
| `python scripts/benchmark_aesthetic.py --db <path> --ava AVA.txt --photo-dir <dir>` | Compute SRCC + PLCC against AVA ground truth for every score column |

### Subject Saliency

`--pass saliency` and `--recompute-saliency` use BiRefNet-dynamic (`ZhengPeng7/BiRefNet_dynamic`, via `transformers`, ~3 GB VRAM) to find the subject, then derive four metrics:

- **Subject Sharpness**: is the subject in focus (Laplacian variance, subject vs background).
- **Subject Prominence**: subject area / frame area. High for a dominant subject (e.g. macro).
- **Subject Placement**: rule-of-thirds score for the subject centroid.
- **Background Separation**: edge contrast between subject and background (bokeh quality).

Saliency runs on every profile; `legacy` runs it on CPU, slower. `--recompute-saliency` works with the library volume offline and is resumable. On CUDA the batch size follows free VRAM (about 2.4 GiB per image at 1024 px, 1 to 8 images) and halves after an out-of-memory error.

- **A failed photo** is logged as an ERROR and nothing is written. A never-scored photo stays NULL and is picked up by the next `--recompute-saliency`; one that already had saliency keeps its values, even under `--recompute-saliency --force`. A full rescan (for example `python facet.py --force`) stores NULL for it.
- **A photo with no subject** stores NULL sharpness, placement and separation, prominence 0.0, and a NULL `subject_bbox` (and NULL `power_point_score` from the composition step). This is final; it is not measured again.
- **Older rows** stored a neutral 5.0 instead. `--recompute-saliency` and `--recompute-composition-cpu` rewrite them. `--recompute-saliency` also picks up photos scored before `subject_bbox` existed.
- A NULL optional metric is left out of the aggregate and its weight is redistributed over the metrics that are present; only when all of them are missing does the aggregate fall back to a neutral 5.0. See [Scoring System](SCORING.md).

### Tagging Models

The tagging model depends on the VRAM profile:

| Profile | Model | How it works |
|---------|-------|-------------|
| `legacy` | CLIP similarity | Cosine similarity between image and tag-text embeddings. No extra model. |
| `8gb` | CLIP similarity | Same as legacy, on stored CLIP ViT-L-14 embeddings. |
| `16gb` | Qwen3.5-2B | Multimodal model for scene tagging. |
| `24gb` | Qwen3.5-4B | Larger multimodal model. |

All taggers map their output to the configured tag vocabulary. Use `--recompute-tags` to re-tag with the profile's model, or `--recompute-tags-vlm` for the VLM.

**When tags are written.** On CLIP-similarity profiles (`legacy`/`8gb`, and `16gb`/`24gb` when the VLM pass is not scheduled), a multi-pass scan tags during the embeddings pass, so the scan's category and aggregate already use them. A single `--pass` run (for example `--pass embeddings`) writes no tags. `--pass tags` on a CLIP profile stops and points to `--recompute-tags`. Existing rows keep their category until `--recompute-average`.

### Embedding Models

Two embedding models, selected per VRAM profile via `clip_config`:

| Config | Model | Dimensions | Used By |
|--------|-------|-----------|---------|
| `clip` | SigLIP 2 NaFlex SO400M | 1152 | 16gb, 24gb profiles |
| `clip_legacy` | CLIP ViT-L-14 | 768 | legacy, 8gb profiles |

Embeddings power tagging, duplicate detection, similar-photo search and the CLIP+MLP aesthetic (legacy/8gb). Switching models requires re-embedding all photos (`--force`, `--pass embeddings`, or `--recompute-embeddings`).

## Face Recognition

| Command | Description |
|---------|-------------|
| `python facet.py --extract-faces-gpu-incremental` | Extract faces for new photos (GPU, parallel) |
| `python facet.py --extract-faces-gpu-force` | Delete all faces and re-extract (GPU; named persons are kept; permissive extractor in commercial mode) |
| `python facet.py --cluster-faces-incremental` | HDBSCAN clustering, keeps all persons (CPU) |
| `python facet.py --cluster-faces-incremental-named` | Clustering, keeps only named persons (CPU) |
| `python facet.py --cluster-faces-force` | Full re-clustering, deletes all persons (CPU) |
| `python facet.py --suggest-person-merges` | Suggest possible person merges |
| `python facet.py --suggest-person-merges --merge-threshold 0.7` | Use a stricter threshold |
| `python facet.py --refill-face-thumbnails-incremental` | Generate missing face thumbnails (CPU, parallel) |
| `python facet.py --refill-face-thumbnails-force` | Regenerate ALL face thumbnails (CPU, parallel) |

## Thumbnail Management

| Command | Description |
|---------|-------------|
| `python facet.py --fix-thumbnail-rotation` | Rotate stored thumbnails to match EXIF orientation |
| `python facet.py --refresh-thumbnails` | Rebuild RAW thumbnails from the camera-embedded preview |
| `python facet.py --refresh-thumbnails --refresh-thumbnails-workers 16` | Same, with more parallel reads |

**`--fix-thumbnail-rotation`** is for photos processed before EXIF orientation was handled. It reads only the EXIF header and the stored thumbnail.

**`--refresh-thumbnails`** re-renders every RAW photo's stored thumbnail through the display profile (camera preview first, demosaic as fallback; see [CONFIGURATION.md](CONFIGURATION.md#raw-decode)). Use it on a library scanned before that profile existed: older thumbnails flatten the exposure differences between bracketed frames. It loads no model and changes no score.

- **Speed** depends on disk or network throughput, not CPU. `--refresh-thumbnails-workers` (default 8) sets how many files are read at once: raise it on a fast network mount, lower it on a slow local disk. Very high values cost memory.
- **Resumable.** Stop it with Ctrl-C and the next run continues where it left off. A completed run starts over next time.
- **Black renders** (for example from a truncated RAW) are discarded: the photo keeps its old thumbnail, is logged by name and is retried next run.
- **Bracketed frames** are rendered without the camera preview or exposure gain, so each tile shows what the sensor recorded (see [CONFIGURATION.md](CONFIGURATION.md#bracketed-frames-render-uncorrected)). Run it after `--detect-sequences`.

### What updates a stored thumbnail

Thumbnails are made at scan time, so a library scanned before the display profile existed keeps the old rendering in the gallery grid. Two things update them:

| Path | Covers | Cost |
|------|--------|------|
| A rescan (`python facet.py <dir>`) | Everything it scans, thumbnail and histogram | Full scoring run |
| `--refresh-thumbnails` | Every RAW row's thumbnail | Storage-bound, hours on a large library |

**Nothing happens on its own.** The detail view always renders fresh, but the gallery grid shows the stored thumbnail. A dismissible banner counts the rows still waiting. Its count can lag up to an hour after a rescan; `--refresh-thumbnails` and `python database.py --refresh-stats` update it.

## Diagnostics

| Command | Description |
|---------|-------------|
| `python facet.py --doctor` | Run diagnostic checks (Python, GPU, ONNX Runtime, dependencies, config, database) |
| `python facet.py --doctor --simulate-gpu "RTX 5070 Ti" --simulate-vram 16` | Simulate GPU hardware for diagnostics |

`--doctor` reports the Python version, PyTorch/CUDA build, GPU and driver, ONNX Runtime build and providers, recommended VRAM profile, optional dependencies, and config/database status. On CUDA it also test-loads ONNX Runtime on the GPU. When PyTorch or ONNX Runtime is the wrong build, it prints the `pip install` command that fixes it (see [ONNX Runtime for face detection](INSTALLATION.md#onnx-runtime-for-face-detection)).

`--simulate-gpu NAME` and `--simulate-vram GB` require `--doctor`; `--simulate-vram` also requires `--simulate-gpu`.

| Command | Description |
|---------|-------------|
| `python facet.py --check-raw-rendering` | Render 20 sampled RAW photos under the old and current decode settings |
| `python facet.py --check-raw-rendering 50` | Sample 50 photos instead |

Read-only. It prints the mean brightness of each rendering: LibRaw auto-brightness, the fixed-gain demosaic, and the camera preview. Use it to check `raw_decode.bright` on your files before a scan or `--refresh-thumbnails`. The fixed and preview columns keep a bracket's exposure steps; auto-brightness flattens them.

## Model Information

| Command | Description |
|---------|-------------|
| `python facet.py --list-models` | Show available models and VRAM requirements |

## Weight Optimization (Pairwise Comparison)

| Command | Description |
|---------|-------------|
| `python facet.py --comparison-stats` | Show pairwise comparison statistics |
| `python facet.py --optimize-weights` | Optimize weights from your comparisons; applied only if they pass a held-out test (see note) |
| `python facet.py --optimize-weights --optimize-force` | Apply optimized weights even if they fail the test |
| `python facet.py --optimize-weights --optimize-sources vote,culling` | Train only on these comparison sources |
| `python facet.py --optimize-weights --optimize-category portrait` | Train one category and write its v4 `categories[].weights` block |
| `python facet.py --auto-tune-categories` | **Superadmin only** (`--user` in multi-user mode): report per-category label readiness (report only) |
| `python facet.py --sync-label-comparisons` | Rebuild rating-derived pairs (source=rating) from stars, favorites and rejections |
| `python facet.py --train-ranker` | Train the personal ranker and write learned_scores if it beats the aggregate |
| `python facet.py --train-ranker --ranker-category portrait` | Train the ranker on one category |
| `python facet.py --train-ranker --train-ranker-force` | Write learned_scores even if the accuracy gate fails |
| `python facet.py --train-ranker --user alice` | Train on that user's comparisons and write their learned_scores (multi-user mode) |
| `python facet.py --train-keeper` | Train the **keeper-ranking head** from your culling decisions (see note) |
| `python facet.py --train-keeper --train-keeper-force` | Keep the head even if its gate fails (also honors `--ranker-category` and `--user`) |
| `python facet.py --report-unreviewed-bursts` | Count burst groups not yet reviewed (read-only) |
| `python facet.py --eval-iqa-srcc` | Report how well each IQA/aesthetic metric matches your star ratings (SRCC; read-only) |
| `python facet.py --evaluate-models SLOT` | Rank candidate models for a slot by agreement with your picks (read-only; see note) |
| `python facet.py --mine-insights` | Report on labels, metric correlations, categories, percentile drift and comparisons |
| `python facet.py --mine-insights report.json` | Same, and write the full report as JSON |
| `python calibrate.py --db <path> --ava-annotations AVA.txt` | Calibrate category weights against the [AVA dataset](https://github.com/imfing/ava_downloader) (read-only; prints proposals) |
| `python calibrate.py --db <path> --ava-annotations AVA.txt --categories landscape,portrait --apply` | Limit to these categories and write the weights to `scoring_config.json` |
| `python calibrate.py --db <path> --ava-annotations AVA.txt --method nelder-mead` | Choose the optimizer (`de` = differential evolution, default; `nelder-mead` = local simplex) |
| `python calibrate.py --db <path> --ava-annotations AVA.txt --ava-tags` | Also use AVA tags (`--ava-tags-only` for tags only; `--apply-filters` to tune filter thresholds) |

**`--optimize-weights`** trains on all comparison sources, weighted by reliability. New weights are applied only if they beat the current ones on held-out comparisons (5-fold cross-validation, one-sided McNemar test, p < 0.05, gain of at least 2 percentage points). Applying also re-centres the category's `modifiers.bonus`, so its photos are reordered rather than all shifted. See [SCORING.md](SCORING.md).

**`--train-keeper`** learns from `source='culling'` pairs and is kept only if it beats the auto-cull heuristic on held-out data. It powers auto-cull picks and the "a better shot exists in this group" badge. Until there are enough culling pairs, the heuristic is used. It retrains on the same trigger as `--train-ranker`.

**`--evaluate-models SLOT`** slots: `aesthetic`, `quality`, `faces-detect`, `faces-recognize`, `faces-centroid`, `blink`, `face-quality`, `end-to-end`.

- `--candidates a,b` picks candidates (`stored:<column>` or a registered name).
- `--eval-out PATH` sets the output (default `.facet_cache/eval/<slot>-<timestamp>.json`).
- The face slots compare against the stored InsightFace faces instead of your picks, so they suit default-mode libraries only: `faces-detect` (`yunet`, `yunet@<conf>`, `blazeface`), `faces-recognize` (`sface`, `sface@<threshold>`), `faces-centroid` (tunes SFace `merge_threshold` / auto-merge), `blink` (sweeps the permissive blink threshold).
- `--limit N` caps the photos (default 600) or reference faces (default 1200).

## Configuration

`scoring_config.json` is an **override**: it holds only the settings you changed, on top of `config/scoring_config.default.json`. With no config file, Facet runs on the defaults. See [Configuration](CONFIGURATION.md#defaults-and-your-override).

Which file is read:

1. `--config` always wins.
2. Otherwise `FACET_CONFIG`, if set. It applies to `facet.py`, `database.py`, `tag_existing.py`, `diagnostics.py`, `calibrate.py` and `viewer.py`. `viewer.py` has no `--config`, so this is its only override.
3. Otherwise, for the CLI tools (not `viewer.py`), a `scoring_config.json` in the **working directory**, so a library can carry its own config.
4. Otherwise the file beside the install. If that is absent, the shipped defaults apply.

A path named by `--config` or `FACET_CONFIG` that does not exist is an error, not "use defaults". The viewer logs the missing path and refuses to start in open mode.

> **Warning:** `viewer.py` never reads a `scoring_config.json` from the directory you start it in. If you start it from a library and the install root has no config, it runs on the defaults: an empty `viewer.edition_password` and no viewer password, so anyone can browse.

```bash
# 1. --config wins over everything. A missing file is an error.
python facet.py --config /srv/facet/wedding.json /photos/wedding

# 2. $FACET_CONFIG supplies the default when --config is omitted (Docker sets this).
export FACET_CONFIG=/config/scoring_config.json
python facet.py /photos            # reads /config/scoring_config.json
python facet.py --config other.json /photos   # --config still overrides it

# 3. Neither set: a config in the WORKING DIRECTORY wins for the CLI tools.
cd /photos/client-shoot          # holds its own scoring_config.json
python /opt/facet/facet.py .     # scored by /photos/client-shoot/scoring_config.json

# 4. Neither set and nothing here: falls back to the config beside the install.
cd /tmp
python /opt/facet/facet.py /photos   # reads /opt/facet/scoring_config.json
                                     # absent there = running on the shipped defaults

# 5. viewer.py never takes the working-directory step.
cd /photos/client-shoot          # holds its own scoring_config.json -- irrelevant here
python /opt/facet/viewer.py      # still reads /opt/facet/scoring_config.json (or $FACET_CONFIG)
```

| Command | Description |
|---------|-------------|
| `python facet.py --validate-categories` | Validate category configurations |

## Tagging

| Command | Description |
|---------|-------------|
| `python tag_existing.py` | Tag untagged photos from stored CLIP embeddings |
| `python tag_existing.py --dry-run` | Preview tags without saving |
| `python tag_existing.py --threshold 0.25` | Custom similarity threshold (default: the profile's `tag_threshold_percent`, shipped as 8, i.e. 0.08) |
| `python tag_existing.py --max-tags 3` | Limit tags per photo (default: 5) |
| `python tag_existing.py --force` | Re-tag all photos |
| `python tag_existing.py --db custom.db` | Use a custom database |
| `python tag_existing.py --config my.json` | Use a custom config |

On CUDA, the SigLIP profiles (`16gb`, `24gb`) now encode the tag vocabulary in fp16, which changes the tags of a few photos. Run `python tag_existing.py --force` to re-tag photos tagged earlier. CPU and the `legacy`/`8gb` profiles are unchanged.

The tagging step at the end of a scan is skipped when `tagging.enabled` is `false` or no photo is waiting for tags.

## Database Validation

| Command | Description |
|---------|-------------|
| `python validate_db.py` | Validate database consistency (interactive) |
| `python validate_db.py --auto-fix` | Fix all issues automatically |
| `python validate_db.py --report-only` | Report without prompting |
| `python validate_db.py --db custom.db` | Validate a custom database |

Checks: score ranges, face metrics, BLOB corruption, embedding sizes, orphaned faces, statistical outliers.

## Database Maintenance

| Command | Description |
|---------|-------------|
| `python database.py` | Initialize or upgrade the schema and build missing indexes (see note) |
| `python database.py --info` | Show schema information |
| `python database.py --migrate-tags` | One-time setup of the tag lookup table (10-50x faster tag filters) |
| `python database.py --rebuild-fts` | Rebuild the full-text search index from captions and tags |
| `python database.py --populate-vec` | Fill the sqlite-vec vector search table from embeddings |
| `python database.py --refresh-stats` | Refresh the statistics cache |
| `python database.py --compact-config` | Drop every value equal to the shipped default from `scoring_config.json` (takes a `0600` backup first) |
| `python database.py --stats-info` | Show cache status and age |
| `python database.py --vacuum` | Reclaim space, defragment |
| `python database.py --analyze` | Update query planner statistics |
| `python database.py --optimize` | Run VACUUM and ANALYZE |
| `python database.py --backup` | Write a timestamped, WAL-safe snapshot (keeps `--keep N`, default 3) |
| `python database.py --export-viewer-db` | Export a lightweight viewer database (no BLOBs, smaller thumbnails; incremental) |
| `python database.py --export-viewer-db --force-export` | Force a full re-export |
| `python database.py --cleanup-orphaned-persons` | Remove persons with no faces |
| `python database.py --cleanup-missing-photos` | Remove photos no longer on disk, with their tags, faces and album entries |
| `python database.py --cleanup-missing-photos --dry-run` | List missing files without deleting |
| `python database.py --cleanup-missing-photos --force` | Proceed even when every photo looks missing (see warning) |
| `python database.py --relink-photos` | Update paths of photos you moved yourself (preview by default). See [Relink moved photos](#relink-moved-photos) |
| `python database.py --migrate-storage-fs` | Move thumbnails and embeddings from the database to the filesystem |
| `python database.py --migrate-storage-db` | Move thumbnails and embeddings from the filesystem back to the database |
| `python database.py --add-user alice --role admin` | Add a user (prompts for password) |
| `python database.py --add-user alice --role user --display-name "Alice"` | Add a user with a display name |
| `python database.py --migrate-user-preferences --user alice` | Copy ratings from photos to user_preferences |

**`python database.py`** also builds missing gallery indexes (see [VIEWER.md](VIEWER.md#gallery-indexes-and-the-count-cache)). On a large library, run it once before starting the viewer; it can take about a minute. Otherwise the viewer builds them in the background and refuses saves meanwhile.

**`--migrate-tags`** is needed once. After that, scans, `--recompute-tags`, `--recompute-tags-vlm` and `tag_existing.py` keep the table current. Until it is populated, tag filters use a slower `LIKE` search.

**`--cleanup-missing-photos`** also clears the vector index and resets the auto-retrain comparison counters. Library state such as trained models, Immich sync state and the percentile snapshot is kept.

> **Warning:** without `--force`, `--cleanup-missing-photos` stops when every photo appears missing, which usually means a volume is unmounted. Check the mount before adding `--force`.

**Performance tip:** for large databases (50k+ photos), run `--migrate-tags`, `--rebuild-fts` and `--populate-vec` once, then `--optimize` from time to time.

## Web Viewer

| Command | Description |
|---------|-------------|
| `python viewer.py` | Start server on http://localhost:5000 (API + Angular SPA) |
| `python viewer.py --port 5001` | Bind a different port (or set the `PORT` env var; default 5000) |
| `python viewer.py --host 127.0.0.1` | Bind a specific interface (default `0.0.0.0`) |
| `python viewer.py --production` | Production mode (uvicorn workers) |
| `python viewer.py --production --workers 4` | Production mode with N workers (default 1) |

## Culling

Headless auto-cull: the terminal version of the viewer's [Auto-cull](VIEWER.md#auto-cull). Rejects are written to the database. Originals are never moved or deleted; `--copy-keepers` copies the survivors to a folder.

| Command | Description |
|---------|-------------|
| `python facet.py --auto-cull [PATH]` | Cull photos already in the database under `PATH` (folder or file; none or `all` = whole library). **Dry run by default** |
| `python facet.py /path --auto-cull` | Scan `/path`, then cull the photos under it |
| `--apply` | Write the cull: rejections, reviewed-group marks and `source='culling'` comparison pairs |
| `--copy-keepers DIR` | Copy every non-rejected photo in scope, with its same-stem RAW / `.xmp`, into `DIR` |
| `--cull-strictness N` | Keeper budget 0–100, higher keeps fewer per group (default: `auto_cull.default_strictness`) |
| `--cull-min-keep N` | Minimum photos kept per group (default `1`) |
| `--cull-group-by {all,burst,similar,scene}` | Which groups to cull (default `all`) |
| `--cull-min-score X` | Also reject standalone photos with an aggregate score below `X` |
| `--cull-trim-brackets` | Also reject redundant exposure-bracket frames (the viewer's `trim_brackets`) |
| `--user NAME` | Whose ratings and rejections to use; **required** on a multi-user install |

- **Dry run.** Without `--apply` nothing is written and the `--copy-keepers` folder is not created. The summary lists `groups`, `kept`, `rejected_by_groups`, `rejected_by_score`, `spanning_skipped` and, with `--copy-keepers`, `keepers`, `copied`, `already_present`, `skipped`, `errors` (`would_reject_*` / `would_copy` in a dry run). `--dry-run` itself is refused. If a trained keeper model needs its weights corrected, loading it may still rewrite `scoring_config.json`.
- **Scan-then-cull** always scans for real; the cull runs only if the scan completed. It cannot be combined with `--auto-cull PATH`, `--resume`, `--retry-failed` or `--watch`.
- **Rules.** Same as the [viewer's Auto-cull](VIEWER.md#auto-cull): each group keeps its best photo plus all within the strictness margin, at least `--cull-min-keep`. Brackets, panoramas and HDR panoramas are kept whole. `--apply` marks kept photos **Kept** and records comparison pairs as `POST /api/culling/auto` does; no Highlights album is filled.
- **Config.** The [`auto_cull`](CONFIGURATION.md#auto-cull), `burst_scoring` and `similarity_groups` settings come from the **server** config (`FACET_CONFIG` or the default path), not `--config`. If the two disagree on multi-user mode, it exits 1.
- **Scope** matches local real paths, so rows stored before a `path_mapping` was set cannot be scoped by folder: use `all` or re-scan. A burst, bracket or panorama partly outside the scope is skipped whole (`spanning_skipped`). Similar and scene groups are computed inside the scope.
- **`--cull-min-score`** (CLI only) never rejects bracket or panorama frames, unscored photos, favourites, rated or **Keep** photos, or photos an earlier cull already judged, so a second run rejects nothing new. It always spares burst members. It spares similar-group members when the grouping found them (it reads the newest `similarity_groups.max_photos` photos in scope, default `10000`, and drops groups over `similarity_groups.max_group_size`, default `50`). It spares scene-group members only under `--cull-group-by scene`.
- **Copy.** Rejected photos and their companions are never copied. Same-named files from different folders get a `_1` suffix; a re-run skips identical files (`already_present`). `DIR` must not be, contain or sit inside the scope, the library or any folder Facet has scanned (exit 1, checked in a dry run too). Files must be inside the scan-directory allow-list (`users.*.directories` / `viewer.scan_directories`); if every photo is skipped because of it, the command exits 3.
- **Users.** On a multi-user install `--user` is required (exit 1 without it, or for an unknown user). On a single-user install `--user` is ignored with a warning, and the command sees every photo even when a viewer password is set. `--apply` takes the library lock; a dry run does not.
- **Usage errors (exit 2).** `--apply`, `--copy-keepers` or any `--cull-*` without `--auto-cull`; `--dry-run`, `--resume`, `--retry-failed` or `--watch` with `--auto-cull`; `--auto-cull PATH` with positional folders; strictness outside 0–100; `--cull-min-keep` below 1. `--apply` must be typed in full (it no longer abbreviates `--apply-recommendations`).
- **Exit codes.** `0` success (including a dry run or zero groups); `1` precondition, config or database failure; `2` usage error; `75` the library lock is held by another job; `3` the cull worked but the copy had errors or copied nothing (a dry run where every keeper would be skipped also exits `3`).
- **Retraining** does not run inside the CLI. The comparison counter persists, and the retrain runs on the next viewer action or `--train-*` command. The first run may create `.facet_secret`.

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

### Cull a Shoot from the Terminal
```bash
python facet.py --auto-cull /photos/wedding                     # Preview the plan, nothing written
python facet.py --auto-cull /photos/wedding --apply \
    --copy-keepers ~/wedding-keepers                             # Reject, then copy the survivors
python facet.py /photos/new-shoot --auto-cull --apply --cull-min-score 5   # Scan, then cull
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

## Relink moved photos

After moving files yourself, `python database.py --relink-photos` previews the old → new path mappings and keeps each photo's database data. Preview is the default.

- **Apply** needs the saved plan ID and `--acknowledge-unverified-identity`, because Facet cannot prove the new file is the original. Stop viewers and scanners and review the plan first.
- **Refused:** paths outside your configured roots or user visibility, copies, ambiguous names, stale plans and path mappings.
- **Companions** must be listed explicitly; kinds include `sidecar_facet` for `photo.ext.facet.xmp`. Manual rectangles need editor review. Immich state is unchanged.
- **Plans** are saved privately (0600 on POSIX).
- **Mounts:** a readable folder does not prove a volume is mounted, so `source_mount_status` stays `not_verified`. Confirm the original was moved, not offline.
- **Exit codes:** 75 means another job holds the library lock; 1 means the lock is unusable. Preview takes no lock.

See [Relink a missing photo](RELINK.md) for the full contract and examples.
