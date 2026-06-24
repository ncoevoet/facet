# Changelog

All notable changes to Facet are documented in this file.

## [Unreleased]

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
