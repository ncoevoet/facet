# Changelog

All notable changes to Facet are documented in this file.

## [Unreleased]

### Added
- **Edited-look cull preview** (`raw_processor.darktable.cull_styles`, `GET /api/photo/cull_preview`, edition-gated): the culling darkroom's single view gains a **palette** menu that renders a photo's original through a named darktable style so you cull on the developed look instead of the flat RAW preview — Imagen's differentiator, done locally with darktable-cli. Picking a style swaps the main image (spinner while it renders, snackbar + revert to Original on failure); the choice persists across the group's frames and resets per darkroom session. It reuses the download path's darktable-cli machinery and disk-caches rendered JPEGs (keyed by source mtime, style and max edge) under `<db_dir>/.facet_cache/cull_previews/`, so re-viewing a frame is instant. The control only appears when at least one style is configured **and** darktable-cli resolves (surfaced in `GET /api/config`); styles must already exist in the darktable configuration of the user running the viewer. Bounded by `preview_max_edge` (1440) and `preview_timeout_seconds` (60). Also fixes a latent darktable-cli bug where an absent XMP sidecar passed an empty positional that darktable rejects.
- **Static portfolio export** (`portfolio`, `POST /api/albums/{album_id}/export-portfolio`, `viewer.features.show_portfolio_export`): each manual album card gains an edition-only **Export portfolio** action that renders the album into a self-contained static HTML gallery a photographer can drop on any web host — the thumbsup/sigal use case, but native, with no external tool dependency. The output is a responsive CSS-only thumbnail grid with a built-in vanilla-JS lightbox and **zero** external/CDN references (fully offline), an `assets/` folder of sequentially-named JPEGs (no library paths leaked), and a `manifest.json`. Each photo prefers the on-disk original (downscaled to `portfolio.max_edge`, EXIF orientation applied) and falls back to the stored 640px thumbnail when the original is unreachable (offline network shares), recording the source per photo. The `target_dir` is validated against the same allow-list as the copy/move export endpoints, albums over `portfolio.max_photos` (default 500) are refused, and re-export is deterministic and idempotent.
- **Saliency-aware social-export crops** (`social_export`, `GET /api/photo/social_crop`, `viewer.features.show_social_export`): the photo detail download bar gains an edition-only **Social crop** menu that exports a full-resolution JPEG cropped to a configured social aspect preset (square 1:1, portrait 4:5, story 9:16 out of the box) and framed on the detected subject — something Lightroom export presets cannot do. The crop is the largest rectangle of the target aspect that fits the image, centered on the subject with a configurable margin and clamped at the edges (deterministic pure geometry). The subject box comes from a fallback chain: a newly persisted BiRefNet subject box (`photos.subject_bbox`, written by the saliency pass and `--recompute-saliency`) → the union of detected face boxes → a plain center crop, and the preview endpoint surfaces which source framed the crop. Original decoding reuses the existing RAW/HEIC loader with EXIF orientation applied.
- **Genre-aware culling profiles** (`cull_profiles`, `GET /api/culling/profiles`): the culling darkroom toolbar gains a genre preset selector that bundles every culling knob at once — strictness, keeper budget, similarity threshold and the darkroom's eyes-closed / poor-expression face cutoffs — so sports keeps only the sharpest of a burst, weddings keep more eyes-open variants, concerts and wildlife relax the face gates. The choice persists in `localStorage`; nudging any knob by hand reverts the label to Custom. `POST /api/culling/auto` and `POST /api/culling-group/faces` accept an optional `profile` id, and an explicit request `strictness`/`min_keep_per_group` always wins over the preset.
- **Pluggable VLM backend** (`vlm_backend`, `type: local | ollama | openai_compatible`): captioning, VLM tagging, the AI critique and the moment tie-breaker were hardwired to the in-process transformers Qwen models, so `legacy`/`8gb` profiles had no access to any VLM feature. Point them at a remote Ollama or OpenAI-compatible server instead, and those features work regardless of VRAM profile. In-scan tagging still uses the profile's own tagger by design; `--recompute-tags-vlm` is the remote path. A remote request failure surfaces as a per-photo error and never crashes a scan.
- **Junk sweep** (`--detect-junk`, `--recompute-junk`, edition-gated `/junk` review queue): a zero-shot classifier reuses the stored CLIP/SigLIP embeddings (no image decode, no extra model pass) to flag screenshots, scanned documents, receipts, memes and presentation slides as `junk_kind`, auto-running at the end of every scan. A gallery filter and junk-kinds dropdown surface the results, and the review queue lets you keep or reject candidates individually or in bulk. `NULL` means unevaluated and `not_junk` means evaluated clean, so repeat scans only label new photos.
- **Interop guide** (`docs/INTEROP.md`, all six languages): Facet already speaks the XMP protocol AfterShoot and Narrative use to round-trip with Lightroom, but the workflow had no documentation. Step-by-step recipes now cover a full Lightroom Classic round trip, a one-way Capture One flow that avoids rating clobber, and a digiKam sidecar + Batch Queue Manager hook, plus a merge-semantics table and the verified RAW sidecar naming mismatch (`image.ext.xmp` vs `image.xmp`) that silently breaks LR/C1 RAW round trips.
- **MediaPipe blendshape eyes/smile scoring** (`face_detection.blendshapes`): per-face `eyes_open_score` / `smile_score` were computed purely from 106-point landmark geometry. An optional MediaPipe Face Landmarker pass now scores a generous full-resolution crop of each face with `eyeBlink*` / `mouthSmile*` / `mouthFrown*` blendshapes, which read closed eyes and subtle smiles more reliably than geometry and replace the geometric values when available — falling back to geometry when MediaPipe, its auto-downloaded model bundle, or a large-enough crop is missing. Installed independently via `pip install mediapipe==0.10.35 --no-deps` to avoid a double-`cv2` conflict with `opencv-python`.
- **Per-user personal ranker training** (`--train-ranker --user <name>`, `GET /api/ranker/status?user=`): the "My Taste" ranker always trained on every user's pooled comparisons, so in multi-user mode one person's votes shaped everyone's learned scores. Passing `--user` scopes training to that user's own comparisons plus legacy pre-multi-user rows, writing a per-user `learned_scores` snapshot; leaving it off trains the global pooled model exactly as before (byte-identical SQL and snapshot key).

### Changed
- The moment and junk classifiers now share one embedding-decode helper instead of each keeping its own inline copy, and the client's clipboard-copy + basename-extraction logic (client-picks-dialog, gallery, shared-view) is consolidated into one shared utility.

### Fixed
- **Interrupted and failed scans could corrupt scan state**: Ctrl+C never set the batch processor's stop event, so worker and GPU threads kept scoring the remaining worklist for hours, and a GPU-death abort could join workers blocked forever on the bounded image queue; a `KeyboardInterrupt` also fell through into full post-processing (bursts, tagging, moments, junk, vector index) after marking the run interrupted instead of committing and returning early. A failed required model pass previously saved neutral 5.0 scores stamped as scanned — invisible to `--resume` and `--retry-failed`; failed chunks are now excluded from the save and recorded in `scan_failures`. Library-wide recomputes (VLM re-tag, SAMP rescan, thumbnail-based recomputes) buffered every write in one transaction, losing all progress on interrupt; they now commit per batch.
- **exiftool concurrency and viewer-database maintenance**: the `exiftool -stay_open` singleton was written and read from up to eight loader threads with no lock, letting one photo silently receive another's date, camera or GPS metadata on the batched fallback path, and its readline loop could hang a scan forever on a dead or stalled process; the round-trip is now serialized under a lock with EOF checks and a 30-second watchdog that kills and restarts the process. Incremental viewer-database exports blanket-copied rating columns, wiping stars and favorites set on a viewer-only deployment, and never synced faces extracted after the first export; set viewer values now win and a per-photo face-count comparison re-syncs changed faces. `cleanup_missing_photos` treated permission errors and unmounted shares as deletions, cascade-deleting photos that still exist on disk; only a genuine "file not found" under a readable parent is deletable now, everything else is preserved unless `--force`.

### Security
- The thumbnail, image, face and person pixel routes enforced only a partial multi-user check and ignored the single-user viewer password entirely, serving full-resolution originals to anonymous callers on a locked deployment; they now share one central visibility clause. The persons, faces and merge-suggestion endpoints could leak names, paths and face crops across multi-user directory boundaries and are now scoped. `GET` caption/critique could trigger GPU VLM generation and write shared columns without the edition gate (cached reads stay open), `GET /api/ranker/status?user=` is restricted to the caller or a superadmin, a non-ASCII share token now returns 403 instead of 500, and `metric_ranges` / `location_name` require authentication on locked deployments. Open single-user deployments behave identically.
- The scan progress `EventSource` carried the long-lived superadmin JWT in its query string, where it could land in server logs and proxies. The client now mints a short-lived, purpose-bound token from a new `stream_token` endpoint before connecting (re-minted transparently on drop, falling back to polling on repeated failure), and the stream endpoint rejects any token lacking the `scan_stream` purpose.
- Person create, face assign, assign-all-faces and assign-faces accepted foreign face ids and photo paths, letting a directory-scoped edition user pull another user's faces into a person. New write-side checks validate every face and photo against the caller's directories and return the same 404 as a genuine not-found so existence never leaks, with rollback keeping a rejected create from leaving an orphan person row.

## [1.6.0] "Luster" — 2026-07-02

### Added
- **One-button auto-cull** (`POST /api/culling/auto`, edition-gated): cull a whole scope — all groups, or only bursts / similars / scenes, optionally narrowed to an album or date window — in a single pass. Each group keeps the best photo plus everything within a strictness margin (the same keeper budget the manual darkroom slider used), floored at a per-group minimum, and rejects the rest with `source='culling'` comparison rows. `dry_run` defaults on and returns a per-group keep/reject preview; an optional **Highlights** album collects each group's best above `auto_cull.highlights_min`, idempotently. Overlapping burst and similar groups can no longer leave a photo both kept and rejected. Configured via the `auto_cull` block; the darkroom toolbar adds a preview-then-confirm Auto-cull button and a "better photo in this group" hint badge.
- **Facet → Immich sync** (`--immich-sync`, `--immich-test`): push Facet star ratings and favorites to an Immich server over its REST API (`x-api-key`), resolving assets by `originalPath` through configurable path-prefix mappings with a single bulk search pass. Ratings follow Immich's version-safe policy (1–5 only, never 0/−1); an optional top-picks album collects photos above a rating threshold. `--immich-sync` honors `--dry-run` (resolves but never writes) and `--user` (per-user ratings overlay). REST-only — no Immich database coupling. Configured via the `immich` block.
- **Client proofing on shared albums** (`viewer.features.show_proofing`, off by default): a shared-album link can run in proofing mode where the client (no account) exchanges the share token — plus an optional `viewer.proofing.pin` — for a short-lived session, then hearts photos and leaves comments. Picks live in a dedicated `album_client_picks` table, bounded server-side to that album's photos and fully isolated from the owner's ratings (they never touch `photos.is_favorite` / `user_preferences` and never train the personal ranker). The owner reads them from an edition-gated dialog on the album card.
- **Per-face eyes-open and smile scores** persisted on every face row: a continuous eyes-open score and a new geometric smile score (mouth-corner lift, roll-invariant), computed at scan time from the stored 106-point landmarks and backfillable with `--recompute-face-signals`. The culling darkroom's face panel colour-codes each crop green / orange / red and adds live eyes / smile threshold sliders; the blink and expression cut-offs are now the config keys `face_detection.eyes_closed_max` / `poor_expression_min`.
- **Explainable form and colour-harmony metrics**: five CPU-only signals — left-right symmetry, visual balance, edge-orientation entropy, box-counting fractal complexity, and a Matsuda hue-template colour-harmony score over a k-means palette — computed at scan time and backfillable with `--recompute-form`. They surface in the critique breakdown, suggestions and the photo tooltip, and are available as category weights (shipped at 0 %, so existing aggregates are byte-identical until you opt in).
- **Zero-shot distortion attributes and skin-tone naturalness** in the critique (advisory, no aggregate coupling): `--recompute-distortions` labels each photo with likely defects (motion blur, colour cast, oversharpening, …) via ExIQA-style contrastive prompts over the stored embedding, and prints a correlation report against `liqe_score` / `noise_sigma`; `--recompute-skin-tone` flags portraits whose skin chroma drifts green / magenta / blue / yellow (CIEDE2000 vs a CCT skin locus). Both render in the critique dialog as warning chips and a skin-tone note.
- **True fullscreen** for the culling darkroom: a header toggle and the `F` key drive the Fullscreen API so review runs edge-to-edge; the key is listed in the shortcut legend.
- **Structured VLM critique**: the AI critique (16 GB / 24 GB profiles) now uses a configurable ladder prompt (`critique.vlm`) injecting the full rule breakdown, penalties and EXIF, rendered as Observation / Assessment / Suggestions. The result is cached per photo (`refresh` regenerates), translated on demand, and generated against the stored thumbnail so RAW files no longer fail silently.
- **Brazilian Portuguese caption / critique translation** (`pt`, via `opus-mt-tc-big-en-pt`), completing the six-language set.

### Changed
- Concurrent VLM generate calls (critique and captioning share one cached model) are serialized behind a lock instead of racing the GPU.
- The three stored-landmark backfills (blink, eyes/expression, face signals) share one iteration scaffold; the auto-cull and album-fill paths reuse the shared reviewed-flag and album-append helpers.
- Scan-time form metrics resize with `reducing_gap`, and the thumbnail / embedding recompute paths stream row-by-row instead of loading the whole library into RAM (avoids OOM on large libraries).

### Fixed
- **Data loss on re-scan**: re-scoring an already-scored photo (`--force`, `--retry-failed`, watch mode) went through `INSERT OR REPLACE`, which deletes and re-inserts the row — silently cascade-deleting its faces, comparisons, learned scores and per-user ratings and resetting star ratings, favorites, captions, moments and the VLM critique, and corrupting the full-text search index. Both save paths now UPSERT, so a re-scan preserves all user and derived data and keeps search consistent.
- **Security (anonymous access)**: an unauthenticated request was served every photo (and download) even in multi-user mode or with a viewer password set, because the visibility filter fell open to "all photos". It now returns nothing unless the install is genuinely open (single-user, no password).
- **Security (committed secret)**: the JWT signing secret shipped in the tracked `scoring_config.json`; it is now blank and generated per install on first run. Existing deployments should let it regenerate (delete the `share_secret` value).
- **Security (proofing)**: a share-client session token was accepted across the entire API through `get_optional_user`, so on the default empty-`edition_password` setup a shared-album link escalated to full edition access (mass reject, file move / trash). The token now authenticates nothing but its own picks routes. The PIN check is rate-limited against brute force, live sessions stop working the moment an album is unshared or proofing is disabled, and secret comparison is byte-safe.
- `--score-topiq` / `--recompute-tags` crashed with an `UnboundLocalError` on `tqdm`; the database validator flagged every photo of a SigLIP library as corrupt (hardcoded to the CLIP embedding size); full-text search came back empty after a schema upgrade until a manual rebuild; and `--optimize-weights` categorized photos differently from production because it could not parse fractional shutter speeds. All fixed.
- The VLM critique path was dead with the shipped config — it gated on a non-existent `models.vlm_tagger` block and the raw `vram_profile` value ("auto"), so `mode=vlm` always returned unavailable. It now resolves the active profile like the caption endpoint.
- `--recompute-colors` and `--recompute-ocr` crashed with a `NameError` (a later local `import tqdm` shadowed the module in the recompute helper).
- The incremental viewer-database export no longer wipes the GPU-expensive VLM-critique cache with NULLs, and now propagates the new per-face eyes / smile columns.

## [1.5.0] "Aperture" — 2026-07-01

### Added
- One self-contained Docker image for **every VRAM profile**. Weights are not baked in — they download once at first run into Docker-managed named volumes (`facet-hf-cache`, `facet-torch-cache`, `facet-insightface`, `facet-pretrained`), so the image never touches the host's caches. Dependencies are pinned in `requirements.lock.txt` (a frozen, tested set). Pick a profile without editing any JSON via `FACET_VRAM_PROFILE=auto|legacy|8gb|16gb|24gb` (a new env override honored by `config/scoring_config.py`) or the per-profile overlays `docker-compose.{legacy,8gb,16gb,24gb}.yml`; deploy knobs live in `.env` (`.env.example`: profile, photos dir, port, DB path) and the base compose is templated with them.
- Preconfigured out of the box: a sanitized `scoring_config.default.json` (empty secrets, `vram_profile: auto`, all profiles at full feature set) is baked into the image as the active config, so `docker compose up -d` runs with zero host setup; mount your own to customize.
- GPU face clustering baked into the image (RAPIDS cuML). GPU profiles cluster on GPU (`face_clustering.use_gpu="auto"`); the legacy profile is always CPU, guarded by a CUDA device-count check and a CPU fallback on any GPU error.
- Gallery **"Keep top N%"** percentile cull in the toolbar — keep the best N% of the current selection and reject the rest.
- GitHub Pages landing page (`docs/`): an interactive Docker profile picker with copy-to-clipboard commands, browser-language localization (English, French, German, Italian, Spanish, Portuguese with English fallback), and a benefit-focused feature tour.
- Windows deployment guide for running the stack in Docker CE inside a WSL2 distro on a data drive (no Docker Desktop required), plus a documented image-size breakdown and per-profile model download sizes.

### Changed
- **Every VRAM profile now runs its full model set**: the `legacy` and `8gb` profiles gain the supplementary IQA models (TOPIQ IAA / NR-Face / LIQE) and BiRefNet subject saliency, previously enabled only on `16gb`/`24gb`.
- Faster gallery at scale: the "My Taste" and "Moment Confidence" sorts are backed by standalone, ANALYZE'd indexes (with `learned_score` denormalized onto `photos`), and the hidden-summary aggregate is cached instead of recomputed per page.
- The Docker dependency set is pinned for reproducibility: `transformers` is held below 5.3 (5.3+ broke Qwen3.5 batched VLM tagging) and `kornia` is included for BiRefNet.

### Fixed
- **16gb/24gb VLM tagging** now actually loads the Qwen3.5-2B / Qwen3.5-4B taggers instead of silently falling back to CLIP: all tagging-model routing is centralized in one `TAGGING_MODELS` map, closing the gaps that a rename left behind.
- The percentile cull removes the worst tail when the selection is capped, instead of leaving it unculled.
- The Docker entrypoint no longer crash-loops from CRLF line endings (normalized to LF and enforced via `.gitattributes` + a Dockerfile guard).

## [1.4.0] "Refraction" — 2026-06-29

### Added
- Narrative Moments: a zero-shot, fully-local classifier labels each photo's scene/activity moment from a library-agnostic `general` vocabulary (beach, dining, cityscape, celebration, children, …, or `other`; `wedding` ships as an opt-in `event_type`). It scores each caption's text-tower embedding (new `caption_embedding` column, encoded once) against max-pooled per-moment prompts — falling back to the stored image embedding when there's no caption — then applies config-driven face/tag priors (L1) and stay-heavy Viterbi temporal smoothing (L2) across the shoot timeline; an optional Qwen VLM tie-breaker (L3, `vlm_tiebreak`, default off) re-classifies only low-margin frames on 16/24 GB. It's a free cosine over embeddings already in the DB — no image decode — chained onto the end of every scan and exposed as `--detect-moments` / `--recompute-moments`. Filter the gallery via `GET /api/photos?narrative_moment=` and `GET /api/filter_options/narrative_moments`; scenes are named (and optionally sub-split) by their dominant moment. Configured via the `narrative_moments` block.
- Moment confidence: a forward-backward posterior is stored per frame (`narrative_moment_confidence`) and drives confidence dimming (labels render dimmed with an "(uncertain)" suffix below `viewer.moment_confidence_min`, default `0` = never dim), a "Moment Confidence" sort (NULLs sink), a min/max range filter (new sidebar "Moments" section), an opt-in caption-quality gate (`narrative_moments.caption_min_confidence`), a personal-ranker input feature, and an optional capsule MMR blend (`capsules.mmr_moment_weight`). Every new knob defaults to a no-op.
- `--discover-moments`: clusters the stored `caption_embedding` vectors (HDBSCAN), names each cluster from its captions (TF-IDF keyword + centroid-nearest captions as prompts), and writes a proposed `event_types.discovered` block to `scoring_config.discovered.json` for review — a data-driven, library-specific moment vocabulary that never rewrites the active config (`--discover-min-cluster-size N` tunes granularity).
- Culling granularity: the `/culling` darkroom gains an All | Bursts | Similar | Scenes selector (`GET /api/culling-groups?group_by=`, sort/category persisted to localStorage). Scene culling, previously a separate page and `POST /api/scenes/confirm`, is folded into this one surface and the unified `POST /api/culling-groups/confirm` (now handling `type:'scene'`).
- Scene and album scoping: cull or browse one album or capture-time window at a time — `compute_scenes`, the burst/similar group queries and `compute_similarity_groups` take an optional `album_id` plus `date_from`/`date_to`, and the darkroom offers a nested album → scene scope cascade. Scenes split on an adaptive capture-time gap (`scenes.gap_minutes` widened by `adaptive_k × median`) and recursively sub-split past `scenes.max_scene_size`, so a continuously-shot event no longer collapses into one unreviewable scene.
- Read-only Scenes browse (`/scenes`): a grid with a hover loupe, date/moment headers and an album-scope picker, open to all authenticated users. Entry is the per-album "Display scenes of this album" action, with an edition-only "Cull this scene" deep-link into the darkroom scoped to that scene's window.
- Cull to folder (`POST /api/cull/apply`, edition-gated): physically act on a culling decision — `copy_keeps` (additive), `move_rejects`, or `trash_rejects` (OS-trash via optional `send2trash`, behind `viewer.cull.allow_trash`). Defaults to `dry_run`, returning the resolved would-copy/move/trash lists for a zero-I/O preview; destructive actions need an explicit `dry_run=false`, are bounded server-side to the user's actual reject set, and reuse album export's validated target-dir allow-list. Opt-in `include_companions` extends the action to a shot's sibling RAW/XMP.
- Synced 2-up / 4-up compare in the cull lightbox: a Single / Compare 2 / Compare 4 toggle drives panes bound to one shared zoom/pan signal for true side-by-side pixel-peeking, swapping each pane to the full-resolution source past fit scale. Adds a Z-key loupe (100–800%) to the single-view lightbox and a hover-magnifier loupe over the Scenes tiles.
- Visual "why this score" overlay: the critique dialog gains a feature-gated "Show overlay" toggle compositing a translucent BiRefNet saliency heatmap (`GET /api/saliency_overlay`, recomputed on the stored 640px thumbnail, never persisted) and per-face boxes + eye centres (`GET /api/photo/face_markers`, reconstructed from stored landmarks — no model) over the photo.
- In-app scan launcher: a superadmin-only "Scan photos to get started" button on the empty gallery (gated by `features.show_scan_button`, shipped off) picks a directory and streams live scan progress (SSE with polling fallback); a new `viewer.scan_directories` list gives standalone/Docker installs a pickable target.
- Keyboard rate-and-advance in the main gallery grid: on a focused card, 1–5 set the star rating and 0/X reject (both auto-advance to the next photo), while F toggles favorite without advancing — edition-only, gated on `features.show_rating_controls`.
- Weight snapshots are now automatic and managed: every weight-mutating path (edit, restore, optimizer apply, per-category edit) records a restorable snapshot first; the Snapshots tab paginates by infinite scroll (`GET /api/config/weight_snapshots` gains `offset`/`has_more`) and can delete a snapshot (`DELETE /api/config/weight_snapshots/{id}`, edition-gated); and a restore raises a "scores are stale" banner with a one-click per-category recompute.
- XMP export can map the aggregate score to `xmp:Rating`: a `score_to_stars` mapping fills the star rating only when a photo carries no manual signal (any manual rating/favorite/reject wins), gated by the `xmp_export.score_to_rating` block (off by default) or forced for one run with `--score-to-stars`, so Lightroom/darktable/immich finally see Facet's computed quality.
- Comparison pair selection defaults to a new `learning` strategy: cold-start samples embedding-distant pairs for fresh feature coverage, and once "My Taste" is trained it prefers pairs whose aggregate order disagrees with their learned-score order — the highest-information clicks (`viewer.comparison_mode.candidate_pool_size`, default 200).
- `--auto-tune-categories` (superadmin-only): prints each category's comparison-label readiness against `comparison.min_comparisons_for_optimization` and points ready ones at `--optimize-weights --optimize-category`; auto-apply is deferred pending labels.
- JSON-schema validation for `scoring_config.json` (`config/scoring_config.schema.json`, Draft 2020-12): `ScoringConfig.validate_schema()` runs at load (soft-warn, never blocks) and via `--validate-categories` / `--doctor`, catching typo'd keys and wrong-typed values with a JSON-path error. `jsonschema` becomes a core dependency (guarded so its absence degrades gracefully).
- A `PRAGMA user_version` migration ladder (`SCHEMA_VERSION` + ordered `MIGRATIONS`, run inside `init_database`'s transaction) for non-additive schema changes, surfaced in `database.py --info` and warned on mismatch in `--doctor`.
- Hard-crashed scans are resumable: a `heartbeat_at` column is written on every progress flush, and `--resume` now also reclaims a `running` row whose heartbeat is older than `processing.scan_stale_seconds` (default 120) — the SIGKILL/OOM/power-loss case the old `interrupted`/`failed` match missed — while refusing to hijack a still-live scan.
- Database integrity + free-space guards: `--doctor` runs `PRAGMA quick_check` and `validate_db` flags structural corruption as UNFIXABLE; a scan estimates its thumbnail/embedding footprint against the DB volume's free space (`processing.bytes_per_photo_estimate`, `processing.disk_safety_margin`) and refuses unless `--force-low-space`.
- `database.py --backup [--keep N]`: an explicit, WAL-safe online snapshot of the database for deliberate manual use.
- Global help system: a single header help button reveals a per-page description panel (gallery, albums, timeline, folders, persons, stats, map, compare, culling), replacing the scattered per-page info toggles.
- Brazilian Portuguese (pt) viewer language and full `docs/pt/` set, bringing the UI to six languages. The supported-language list is now data-driven from a single source of truth: `GET /api/i18n/languages` returns `[{code, name}]`, and the API and both switcher menus derive from it instead of hardcoding the set.

### Changed
- Responsive header-slot redesign: every page projects its toolbar into the global header on large screens (and keeps a bottom bar / mobile UI on small screens) via a shared header-slot, with card titles becoming top-left thumbnail overlays (albums, capsules, timeline, folders), a sticky timeline breadcrumb, and the culling header consolidated to icon-driven controls (group-type icons, per-slider menus, Confirm-All, a back button in scoped view). Merge Suggestions is rebuilt as an avatar grid where a click merges directly behind a confirmation modal.
- "My Taste" is now the first option in both gallery sort selects (still gated on `features.show_my_taste`), and its confidence badge renders as an amber icon.
- `torch.compile()` is preflighted for a working C compiler (gcc/g++/CC) before it's enabled, falling back to eager CUDA with honest logging instead of silently failing every image at first inference on a compiler-less Docker GPU host (issue #15); an all-failed `--dry-run` now exits non-zero.
- Memories ("On This Day") plays as a randomized full-screen diaporama instead of a grid modal.
- Person cards gain a photo-count badge and a name overlay; clicking a needs-naming person opens the gallery filtered by them.
- Scan progress phase labels are localized across all six bundles (the launcher previously rendered the raw English phase word).
- `/image` gains an opt-in `fallback=thumbnail` so the loupe and cull lightbox show the stored thumbnail when an original is offline, instead of a black lens / 404; the default 404-on-missing behaviour is unchanged.
- Normal text/outlined/filled button corner radius tightened to 8px (Material 3's full-pill shape read too round against the app's flatter surfaces).

### Fixed
- A transient parse failure (a half-written file or bad manual edit) no longer permanently clobbers `scoring_config.json` and its backup with a `{share_secret}` stub; the file is left untouched for repair and an ephemeral secret is used. All weight-config writes are atomic (tempfile + `os.replace`) and clean up their `.tmp` on failure.
- The edition toggle no longer opens a password modal that can never succeed when no edition password is configured; new `/api/auth/status` flags (`edition_password_required`, `login_password_required`) hide the edition toggle and logout entirely in no-password deployments. The header nav now reflects a freshly granted edition without an app reload.
- An empty "On This Day" no longer opens a blank slideshow.
- A frame's stored `narrative_moment_confidence` now describes the label it's paired with, and `other` frames store a neutral `0.5` on the same 0–1 scale instead of a raw cosine. The L1 priors (previously hardcoded to wedding moment names, so inert for the shipped `general` vocabulary) and the `pooling` key now actually take effect.
- The in-app scan launcher's auto-close no longer fires on a prior run's stale `{running:false}` status; it closes only once the new run is seen live.
- Ctrl/Cmd/Alt+1–5 no longer hijack browser tab-switching from the gallery grid shortcuts.
- `--discover-moments` names a lone discovered cluster correctly, skips gracefully on a database without the `caption_embedding` column, and its adoption hint now includes the required merge step. Misconfigured `scenes.max_scene_size` (0/negative) and `--discover-min-cluster-size 1` are clamped instead of crashing.

### Security
- Burst/similar/scene culling feeds (`GET /api/culling-groups`, all `group_by` branches) and album-scoped Scenes/gallery queries now verify album ownership, so a caller can no longer scope to another user's `album_id` (IDOR).
- Scene-cull confirms intersect the client's path list with the caller's visibility set, so a confirm can no longer reject photos or train the ranker on arbitrary library paths.
- The on-demand saliency overlay and `face_markers` endpoints now require an authenticated user and apply the per-user visibility clause, closing a cross-user metadata disclosure in multi-user mode; model failures surface as 503.
- `POST /api/cull/apply` resolves each path's per-user `is_rejected` server-side and bounds the op to its semantic set (mismatches reported as `excluded_by_state`), and `include_companions` now defaults off, so a destructive cull can never exceed the user's reject set or silently destroy a rejected JPEG's untouched companion RAW/sidecar.
- The schema migration ladder never stamps `user_version` downward on a newer database.

### Performance
- Smart-album covers are cached in `stats_cache` (keyed by album id + filter hash + user) and pre-warmed by `--refresh-stats`, cutting a 16-smart-album `/api/albums` load on a 126k-photo library from ~3.8s to ~3ms.
- The saliency overlay PNG is memoized per thumbnail so repeated requests don't re-run BiRefNet on the GPU.
- The per-photo moment score-vector is computed once per frame instead of three times.

### Removed
- `POST /api/scenes/confirm` (scene culling now flows through the unified `POST /api/culling-groups/confirm`), along with the Scenes page's per-photo reject grid and its main-nav entry.
- The `--recompute-average` / `--recompute-category` full-DB auto-snapshot, plus the now-dead `--no-backup` flag and `maintenance.backup_retention` key — the snapshot guarded nothing re-derivable (rewritten columns rebuild from raw inputs + weights); use the explicit `database.py --backup` for deliberate snapshots.
- The deprecated Florence-2 tagger references that lingered, and dead i18n strings (`my_taste_badge`, `merge_suggestions_title`) orphaned by the header-slot and scenes migrations.

## [1.3.1] "Polish" — 2026-06-24

### Security
- `POST /api/culling-group/faces` now applies the viewer's visibility filter, so it no longer returns per-face metadata for arbitrary caller-supplied photo paths (IDOR).
- Shared smart albums evaluate their saved filter against the album owner's visibility instead of the viewer's, so a share token can no longer surface photos from other users' libraries.

### Fixed
- Memories "On This Day" returned nothing for every user: `strftime` ran on the raw EXIF-format `date_taken` (`YYYY:MM:DD`), which SQLite cannot parse, so `/api/memories` and `/api/memories/check` were silently dead. The date is now converted to ISO first, matching the timeline and capsule queries.
- Burst, similar-group and scene culling wrote rejections to the global `photos.is_rejected` column in multi-user mode — hiding photos for every user while the acting user's own per-user view never reflected the change. Rejections now route through `user_preferences` (visibility-checked) via a shared helper.
- A batch-level GPU inference failure (e.g. CUDA OOM) escaped the per-item handler, killed the scoring thread, and left the scan waiting forever on results that never arrived. Batch failures now fail their own items and the consumer loop aborts when the GPU thread dies.
- The `/metrics` `photo_tags_available` and `existing_columns_cached` gauges always reported 0; they now read the live cache values through `api.config`.
- i18n interpolation only replaced the first occurrence of a repeated `{placeholder}`; it now replaces all of them.
- Edit-album save, photo-detail rating/favorite/reject actions, album-list load, and the scan SSE stream now handle errors instead of leaving an unhandled rejection or a silent blank UI on failure. The face DB-writer thread surfaces write errors instead of reporting success.
- Submitting a pairwise comparison canonicalizes the photo pair, so swapped (A,B)/(B,A) votes no longer store contradictory duplicate rows that bias weight optimization.
- The capsule slideshow and "save as album" honour the active date filter instead of returning the wrong photos or a 404.
- Reassigning a face to a non-existent person is rejected instead of silently orphaning the face.
- Similar-photos search returns a controlled error on a corrupt embedding/phash blob instead of an unhandled 500.
- Weight-snapshot restore writes to the configured absolute config path regardless of the working directory.
- Database statistics `--verbose` no longer raises `UnboundLocalError` on a database without the `category` column.
- A/B comparison keyboard shortcuts no longer fire while the strategy dropdown is focused, preventing bogus votes.
- "Confirm All" in burst culling confirms only the groups visible under the active category filter, not hidden ones.
- The Q-Align AVA benchmark script runs on CPU-only hosts instead of crashing on a CUDA call.

## [1.3.0] "Brilliance" — 2026-06-24

### Added
- Scenes View (`/scenes`): groups burst-lead photos into chronological "scenes" by capture-time gaps so you cull a shoot in story order. Tap photos to mark them, then confirm to reject the rest — the decision feeds the personal ranker. Cache-only (no schema), configurable via `scenes.gap_hours` / `min_size` / `max_photos`, gated by `viewer.features.show_scenes`.
- "My Taste" sort: the personal-ranker `learned_score` sort is now a first-class, feature-flagged option (`viewer.features.show_my_taste`) with a confidence badge showing learned coverage and held-out accuracy, backed by a new `GET /api/ranker/status`. Renamed from "Picked for you".
- Per-face culling badges: the burst/similar culling lightbox now shows per-face eyes-open/closed, poor-expression and detection-confidence badges (instead of a single photo-level blink flag), fetched in one batch call (`POST /api/culling-group/faces`) and recomputed from stored landmarks.
- CLI `--user` flag on `--export-sidecars` / `--import-sidecars`: in multi-user mode reads/writes that user's `user_preferences` ratings instead of the global columns (keywords stay global).
- Default-OFF `iqa_extended` block in `scoring_config.json`, so the optional extended-IQA tier matches its documentation.

### Changed
- Capsule "Star Rating" diaporamas honour per-user ratings in multi-user mode (previously read the global column only).
- `DatabaseStorage` write methods are now explicit no-ops that raise, with the backend documented as read + migrate only (DB-mode writes flow through the scorer).

### Removed
- Deprecated Florence-2 tagger and all its references (no VRAM profile used it).

## [1.2.0] "Lustre" — 2026-06-22

### Added
- Culling workflow ("darkroom"): a dedicated `/culling` page that reviews burst and visually-similar groups together, with global sort (easiest, redundant, best, recent, needs-comparisons), a cooldown-based confirm/skip (cancellable within the window), per-photo cull reasons, a face/expression grid, and a strictness slider.
- Weight Suggestions tab in the comparison view: learned-vs-current weights with a before/after top-10 preview and one-click apply, gated on comparison volume.
- Editor export: write ratings, colour labels and tags to XMP sidecars (read by Lightroom and darktable) without modifying originals, plus a "basket" export that copies or symlinks selected photos and an album export.
- Person cluster split and hide/ignore. Rejected merge suggestions are persisted so they don't reappear.
- Embedding-space guard so faces detected by different recognition models are never merged into one person.
- Search facets: text-in-image (OCR) search scope, colour (temperature + hue bucket), and quality-tier filters.
- Personalization: a "Picked for you" sort backed by the extended-IQA tier, and background auto-retraining of the personal ranker from culling and rating signals.

### Changed
- Burst/similar culling derives comparison pairs from keep/reject decisions to feed weight tuning and the personal ranker.

### Fixed
- Multi-user data isolation: text-scope search now applies the per-user visibility filter to its results (previously an OCR/caption match could surface another user's photo metadata).
- Culling confirmations are no longer dropped when the cooldown is interrupted by a filter change or navigation; the keep/reject decision is committed on teardown.
- Auto-retrain keeps its accumulated comparison counter when a worker thread fails to start, instead of discarding it.
- XMP export removes its temporary file if the write fails, rather than leaving a stray `.tmp` next to the photo.
- Non-finite metric ranges from corrupt EXIF apertures no longer break filter options.
- Batch person merge repaired; rejected merge suggestions persisted.

### Performance
- The colour filter facet is cached (300s) instead of scanning the whole `dominant_hue` column per request; culling-group pagination reuses one enrichment of the unreviewed set rather than re-scoring every group per page; the hot culling-confirm path reuses the request connection for its retrain counter.

### Accessibility
- Accessible names on the culling icon buttons (view-detail, help) and a non-colour indicator for rejected photos.

### Documentation
- Accuracy pass over the README and `docs/`: corrected stale model names, config defaults, category counts, schema columns, install steps and the Docker section; removed marketing-style prose.

## [1.1.0] "Prism" — 2026-06-17

### Added
- Extended IQA tier is now usable end-to-end. Aesthetic Predictor V2.5 (`aesthetic_v25`) loads via the `aesthetic-predictor-v2-5` package, and Q-Align (`iqa_extended.qalign`) takes a selectable quantisation variant — `"4bit"` (runs on a 16GB card), `"8bit"`, or `true`/`"full"`. Their scores are written to dedicated columns during a normal scan. New `iqa-extended` optional dependency group (`pip install -e .[iqa-extended]`).

### Changed
- Burst best-of selection now applies the composite eyes-open / expression / sharpness tie-break on the live `--recompute-burst` path, not just an unused code path.
- Per-metric filter ranges computed from exact SQL `MIN`/`MAX` plus a bounded histogram sample instead of materialising the whole `photos` table.

### Fixed
- Burst composite tie-break was effectively dead — wired only into a never-instantiated processor while the live scan picked the lead by aggregate alone; the live path now also persists the extended-IQA columns it scores.
- Weight optimizer no longer deletes a config-enabled extended-IQA weight (`qalign`/`aesthetic_v25`/`deqa`) when stripping stale keys.
- Rating clicks coalesce into a single rating-derived comparison rebuild instead of rebuilding the full set per click.
- Gallery metric sliders keep an active out-of-range filter value reachable instead of pinning to the data-driven bound.
- Flaky client `download` spec (asserted on the shared global `URL.createObjectURL` spy count under parallel vitest).

## [1.0.11] — 2026-06-16

### Added
- Gallery filter finder — search filters by name from the sidebar; metrics split into Common and Advanced groups
- Data-driven slider bounds and distribution histograms on metric filters — the observed min/max clamp each slider, with a 20-bin sparkline of the value distribution

### Changed
- Gallery sidebar reorganized — display preferences (hide details, virtual scroll, layout) split into a "View" section, separated from result-affecting filters under "Refine"; "Save as smart album" pinned as a sticky footer
- Range filters debounced so dragging a slider fires a single request instead of one per step
- Index the range-filterable metric columns and skip the page query when the filtered count is zero, so metric filtering uses an index instead of a full-table scan
- Compute metric-range histograms in a single matrix build instead of re-scanning the result set per metric
- Bump CI actions to the Node 24 runtime majors (checkout/setup-node/setup-python)

### Fixed
- Give the filter finder input an accessible name for screen readers
- Align the weight optimizer with production scoring and gate "apply" on held-out accuracy; strip stale weight keys when applying optimized weights
- Share one complete Leaflet mock across map specs to stop a flaky CI failure

## [1.0.10] — 2026-06-13

### Changed
- Docker model cache persists across container restarts (written to the facet home dir); `HOME` pinned to `/home/facet` so the cache path is deterministic
- SAMP-Net treated as optional — a missing weight file no longer aborts a scan; SAMP-Net/U2-Net-P weights fetched from a rehosted release
- Self-host Roboto and Material Icons instead of the Google Fonts CDN (offline-capable, no third-party requests)

### Fixed
- Stop the real Leaflet module leaking into the shared Vitest module registry (flaky map-component test on CI)
- Tagging and image-loader tests pass without `torch`/`transformers` installed; jsdom polyfills for `ResizeObserver`/`IntersectionObserver`

## [1.0.9] — 2026-06-11

### Added
- Watch mode daemon (`--watch`) re-scans as new files appear
- Scan-run bookkeeping with `--resume` / `--retry-failed` and structured progress streamed to the web UI (SSE heartbeats keep `/api/scan/stream` alive through proxies)
- Learn weights from user labels — culling decisions captured as comparison pairs; `--mine-insights` library report
- Viewer: PWA install/offline shell, luminance histogram, mobile actions sheet, undo system, keyboard grid navigation and shortcuts help, select-all/optimistic UI/skeletons
- Stats CSV export, scroll-to-top, slow-request logging; "Exclude Rejected" option in culling; `database.py` cleanup of deleted photos
- Security-headers middleware

### Changed
- Gallery virtualized with row windowing (fast deep scroll at 100k+ photos)
- Image loading parallelized with bounded RAW-decode concurrency
- Performance: async `filter_options` router, cached aperture/focal dropdowns, composite indexes for favorites/rejected sorts, wider FTS5 schema with IN-subquery person matching
- Shared `DateRangeFilterComponent`; pure filter codec extracted from the gallery store; deprecated two-stage weight optimizer dropped

### Fixed
- Populate `topiq_score` when TOPIQ is the primary aesthetic model; SigLIP-profile auto-tagging now produces tags
- `--optimize-weights` can target a real v4 category; FTS corruption surfaced clearly during `--recompute-average`
- CSV formula injection neutralized; scan-dir allowlist enforced before opening photo files
- Leaflet marker icons vendored instead of CDN; mosaic rows tracked by photo path; i18n re-renders on runtime language switch

## [1.0.8] — 2026-05-20

### Added
- Async read endpoints across the API via `aiosqlite` (photos, search, timeline, memories, capsules, albums, similar photos)
- `--doctor` Fast-path Availability section; `/metrics` (GPU, uptime, scan-active) and `/ready` fast-path gradation; cache-invalidation hooks
- AestheticMLP trained/scored on SigLIP-2 embeddings + AVA benchmark; Q-Align variants registered in `PyIQAScorer`; `aesthetic_clip` supplementary score
- Auto-apply schema migrations on viewer startup; `--upgrade-db` schema migration incl. GPS/duplicates; WAL checkpoint thread and final WAL TRUNCATE on shutdown
- Client-side 5xx crash sink (`/api/client-errors`) and SPA error boundary; sqlite-vec auto-populate after scan
- Apple Silicon MPS detection; install paper-cut fixes (issue #7)

### Changed
- `accelerate` promoted to a required dependency; tunable aesthetic prompts; 3D landmark opt-in
- Litestream backup docs; content-visibility on grid cards

### Security
- Patched postcss + ws CVEs and aligned Angular pins to 20.3.21
- Hardened input validation and exception handling; album actions gated on edition rights

## [1.0.7] — 2026-04-06

### Added
- Categories with auto-include dropdown and weight rebalance; compare skip button and weight-suggestion threshold
- Photo detail: GPS editing with map, zoom/pan, download disable while processing; Material datepicker
- Rejected-categories trail in the critique modal; double-click logo resets filters; persons searchable by ID
- User-facing error notifications for 429/403/500; arrow-key navigation and URL sync for tooltip state

### Changed
- Angular ESLint set up and all lint errors fixed; `PhotoDetailBase` directive extracted; `paginate()` utility; 85 manual `conn.close()` replaced with a `get_db()` context manager

### Fixed
- Culling group-ID collisions and preserved manual selections; gallery stale-response races; 422 (not 500) for invalid gallery query params; capsule slideshow error handling; numerous accessibility (aria-label) fixes

### Security
- Hash legacy passwords, add login rate limiting, exclude config from the Docker image

## [1.0.6] — 2026-03-25

### Added
- Upgraded ML models; sqlite-vec + FTS5 search, SSE scan progress, async subprocess, accessibility pass

### Fixed
- Mixed embedding dimensions in `np.stack`; NumPy 2.0 compatibility shim for pyiqa/imgaug; darktable-cli Windows path handling
- Saliency model treated as optional (no crash on load failure); BiRefNet model ID updated after HuggingFace repo rename; capsules reshuffle on refresh

## [1.0.5] — 2026-03-21

### Added
- Multi-type download with darktable profiles, companion RAW detection, and a per-photo download menu (`darktable-cli` as a configurable RAW processor)

### Changed
- Extracted shared utilities and removed dead code

## [1.0.4] — 2026-03-21

### Added
- Mobile-first responsive layout for gallery and shared views; person multi-select with autocomplete in the gallery sidebar; shared-album sidebar with full filter support

### Changed
- Filter definitions and display pipe decoupled from the gallery store

## [1.0.3] — 2026-03-20

Maintenance release (build and packaging fixes).

## [1.0.2] — 2026-03-20

### Added
- HEIF/HEIC image format support
- Rich shared-album experience: mosaic, slideshow, multi-select, photo detail, and filter sidebar for shared manual albums
- Timeline URL navigation, album/search chips, person autocomplete, image-quality config

### Changed
- Unified card layout across albums, capsules, timeline, folders, and persons; removed the standalone person detail page (redirects to the gallery person filter)

### Fixed
- Smart-album filter normalization before SQL; shared-album cover selection and download token handling; folders leaf-redirect back-button navigation

## [1.0.1] — 2026-03-17

Maintenance release.

## [1.0.0] — 2026-03-17

### Scoring & Analysis
- Multi-dimensional scoring: aesthetic, composition, sharpness, exposure, color, face quality, eye sharpness, noise
- TOPIQ IQA (0.93 SRCC), with TOPIQ IAA, TOPIQ NR-Face, and LIQE as supplementary quality metrics
- SAMP-Net composition pattern detection (14 patterns: rule of thirds, golden ratio, vanishing point, symmetry, …)
- BiRefNet subject saliency: sharpness, prominence, placement, and background separation per photo
- CLIP ViT-L-14 (8 GB) and SigLIP 2 NaFlex SO400M (16/24 GB) embedding profiles
- VRAM auto-detection with four profiles: legacy / 8 GB / 16 GB / 24 GB
- Percentile normalization — 90th-percentile maps to 10.0 regardless of library size

### Categories & Weights
- 17 content categories with per-category scoring weights (portrait, landscape, wildlife, macro, street, …)
- Config-driven category determination via `filters` (numeric ranges, booleans, tags) and `modifiers` (bonus/penalty)
- A/B weight comparison: tune weights, preview score changes against a snapshot, apply or discard
- `--compute-recommendations` analyses the database and suggests scoring fixes

### Culling
- Burst detection groups similar photos taken within a configurable time window
- Best-of-burst selection surfaces the top-scoring frame per group
- Blink detection flags closed-eye portraits
- Duplicate detection via perceptual hash (pHash)
- AI similarity culling groups visually similar photos for manual review (`/api/similar-groups`)

### Face Recognition
- InsightFace buffalo_l detection with 106-point landmarks
- HDBSCAN face clustering into named or auto-labelled persons
- Merge suggestions UI with similarity threshold slider and one-click batch merge
- Incremental and force-reprocess modes for extraction and clustering
- Per-face and per-person thumbnails stored in SQLite

### Gallery & Browse
- Gallery modes: mosaic, grid, list
- Real-time filter panel: score, date, camera, lens, aperture, focal length, tag, person, category, composition pattern, GPS radius, Top Picks
- Semantic text-to-image search via CLIP/SigLIP embeddings
- Timeline view with year → month → day drill-down and mini-calendar heatmap
- Map view with marker clustering (Leaflet), GPS filter dialog with radius picker
- Folders browser with breadcrumb navigation and directory cover photos
- Memories — "On This Day" photos from previous years
- Slideshow with per-capsule transitions (crossfade, slide, zoom, Ken Burns)
- Capsules — 30+ AI-curated themed collections: journeys, seasonal, golden, faces of, color story, progress, person pairs, and more
- Albums: manual and smart (filter-based), with sharing via tokenised links

### Organize
- Star ratings and favorites per photo
- Batch tag/rate/favorite/delete operations
- AI captions (VLM-generated) with automatic translation via MarianMT
- Tags from CLIP similarity (8 GB) or Qwen VLM (16/24 GB)
- `photo_tags` lookup table for 10–50× faster tag filtering at scale
- GPS extraction from EXIF into the database; reverse geocoding via `reverse_geocoder`

### Statistics & Understand
- Statistics dashboard: score distribution, top cameras/lenses, composition breakdown, category split
- Per-category weight editor with live recompute
- AI critique: rule-based score breakdown (all profiles) or VLM-powered critique (16/24 GB)

### Web Viewer
- FastAPI backend + Angular 20 zoneless signal-based SPA on port 5000
- Dark/light theme with 10 accent colours; responsive layout
- 5 languages: English, French, German, Spanish, Italian
- Multi-user mode with role-based access (admin / viewer) and per-user ratings
- Edition password for single-user locking
- Photo detail page with EXIF, GPS chip, face chips, clickable tags/persons, caption edit
- Scan trigger from the web UI
- Photo download and CSV/JSON export
- Plugin/webhook system for post-scan automation

### Infrastructure
- SQLite with WAL mode, mmap, and statistics cache (`stats_cache` table, 5-minute TTL)
- RAW support: CR2, CR3, NEF, ARW, RAF, RW2, DNG, ORF, SRW, PEF (via rawpy + exifread)
- Multi-pass GPU scheduling — no inter-batch idle time; single-pass available for high-VRAM setups
- `--doctor` diagnostic command (Python, GPU, deps, config, database)
- `--dry-run` preview mode — scores a sample without writing to the database
- Deployment guides for Linux, Synology NAS, and Docker

### Quality
- 267 automated tests across 20 test files (Python pytest + FastAPI TestClient)
- LIKE wildcard escaping in all path-prefix SQL filters
- No silent `except` blocks — all errors logged via Python `logging`
- CodeQL SSRF alerts resolved

[Unreleased]: https://github.com/ncoevoet/facet/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/ncoevoet/facet/compare/v1.0.11...v1.1.0
[1.0.11]: https://github.com/ncoevoet/facet/compare/v1.0.10...v1.0.11
[1.0.10]: https://github.com/ncoevoet/facet/compare/v1.0.9...v1.0.10
[1.0.9]: https://github.com/ncoevoet/facet/compare/v1.0.8...v1.0.9
[1.0.8]: https://github.com/ncoevoet/facet/compare/v1.0.7...v1.0.8
[1.0.7]: https://github.com/ncoevoet/facet/compare/v1.0.6...v1.0.7
[1.0.6]: https://github.com/ncoevoet/facet/compare/v1.0.5...v1.0.6
[1.0.5]: https://github.com/ncoevoet/facet/compare/v1.0.4...v1.0.5
[1.0.4]: https://github.com/ncoevoet/facet/compare/v1.0.3...v1.0.4
[1.0.3]: https://github.com/ncoevoet/facet/compare/v1.0.2...v1.0.3
[1.0.2]: https://github.com/ncoevoet/facet/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/ncoevoet/facet/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/ncoevoet/facet/releases/tag/v1.0.0
