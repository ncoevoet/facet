# Web Viewer

> 🌐 **English** · [Français](fr/VIEWER.md) · [Deutsch](de/VIEWER.md) · [Italiano](it/VIEWER.md) · [Español](es/VIEWER.md) · [Português](pt/VIEWER.md)

FastAPI + Angular single-page application for browsing, filtering, and managing photos.

## Contents

- [Starting the Viewer](#starting-the-viewer) · [Authentication](#authentication) · [Filtering Options](#filtering-options) · [Sorting](#sorting) · [Gallery Features](#gallery-features)
- [Person Management](#person-management) · [Scan Trigger (Superadmin)](#scan-trigger-superadmin) · [Semantic Search](#semantic-search) · [Albums](#albums)
- [AI Critique](#ai-critique) · [AI Captioning](#ai-captioning-gpu-16gb24gb-edition) · [Memories ("On This Day")](#memories-on-this-day) · [Timeline View](#timeline-view) · [Map View](#map-view) · [Capsules](#capsules)
- [Folders View](#folders-view) · [GPS Filter Dialog](#gps-filter-dialog) · [Merge Suggestions](#merge-suggestions) · [Editor Export](#editor-export) · [Culling](#culling) · [Junk Sweep](#junk-sweep) · [Pairwise Comparison Mode](#pairwise-comparison-mode)
- [EXIF Statistics](#exif-statistics) · [Keyboard Shortcuts](#keyboard-shortcuts-gallery) · [Undo](#undo) · [Progressive Web App](#progressive-web-app) · [Mobile](#mobile)
- [Configuration](#configuration) · [Performance](#performance) · [API Endpoints](#api-endpoints) · [Troubleshooting](#troubleshooting)

> **Feature requirements** are tagged inline: `[GPU]` · `[16gb/24gb]` (VRAM profile) · `[Edition]` (edition password) · `[Superadmin]`. See the [feature matrix](../README.md#feature-availability--requirements).

## Starting the Viewer

### Production

```bash
python viewer.py
# Open http://localhost:5000
```

This serves both the API and the pre-built Angular application on a single port.

For higher throughput, run in production mode (Uvicorn, no auto-reload). Add `--workers N` to scale (default 1):

```bash
python viewer.py --production --workers 4
```

### Development

Run the API server and Angular dev server separately:

```bash
# Terminal 1: API server
python viewer.py
# API available at http://localhost:5000

# Terminal 2: Angular dev server with hot reload
cd client && npx ng serve
# Open http://localhost:4200 (proxies API calls to :5000)
```

## Authentication

### Single-User Mode (Default)

Optional password protection via config:

```json
{
  "viewer": {
    "password": "your-password-here"
  }
}
```

When set, users must authenticate before accessing the viewer. An optional `edition_password` grants access to person management and comparison mode.

### Multi-User Mode

For family NAS scenarios where each member has private photo directories. Enabled by adding a `users` section to `scoring_config.json`:

```json
{
  "users": {
    "alice": {
      "password_hash": "salt_hex:dk_hex",
      "display_name": "Alice",
      "role": "superadmin",
      "directories": ["/volume1/Photos/Alice"]
    },
    "bob": {
      "password_hash": "salt_hex:dk_hex",
      "display_name": "Bob",
      "role": "user",
      "directories": ["/volume1/Photos/Bob"]
    },
    "shared_directories": [
      "/volume1/Photos/Family",
      "/volume1/Photos/Vacations"
    ]
  }
}
```

Users are created via CLI only (no registration UI):

```bash
python database.py --add-user alice --role superadmin --display-name "Alice"
```

See [Configuration](CONFIGURATION.md#users) for full reference.

### Roles

| Role | View own + shared | Rate/favorite | Manage persons/faces | Trigger scans |
|------|:-:|:-:|:-:|:-:|
| `user` | yes | yes | no | no |
| `admin` | yes | yes | yes | no |
| `superadmin` | yes | yes | yes | yes |

### Photo Visibility

Each user sees photos from their configured directories plus shared directories. Visibility is enforced across all endpoints: gallery, thumbnails, downloads, stats, filter options, and person pages.

### Per-User Ratings

In multi-user mode, star ratings, favorites, and rejected flags are stored per-user in the `user_preferences` table. Each user rates independently — Alice's favorites don't affect Bob's view.

To migrate existing single-user ratings:

```bash
python database.py --migrate-user-preferences --user alice
```

## Filtering Options

<details><summary>Full filter sidebar — every section expanded (click to view)</summary>
<p align="center"><img src="screenshots/filter-sidebar-full.jpg" alt="Filter sidebar with every section expanded" width="360"></p>
</details>

### Primary Filters

| Filter | Options |
|--------|---------|
| **Photo Type** | Top Picks, Portraits, People in Scene, Landscapes, Architecture, Nature, Animals, Art & Statues, Black & White, Low Light, Silhouettes, Macro, Astrophotography, Street, Long Exposure, Aerial & Drone, Concerts |
| **Quality Level** | Good (6+), Great (7+), Excellent (8+), Best (9+) |
| **Camera & Lens** | Equipment-based filtering |
| **Person** | Filter by recognized person |
| **Category** | Filter by photo category |

### Advanced Filters

| Category | Filters |
|----------|---------|
| **Date** | Start and end date |
| **Scores** | Aggregate, aesthetic, TOPIQ score, quality score |
| **Extended Quality** | Aesthetic IAA (artistic merit), Face Quality IQA, LIQE score |
| **Face Metrics** | Face quality, eye sharpness, face sharpness, face ratio, face confidence, face count |
| **Composition** | Composition score, power points, leading lines, isolation, composition pattern |
| **Subject Saliency** | Subject sharpness, subject prominence, subject placement, background separation |
| **Technical** | Sharpness, contrast, dynamic range, noise level |
| **Color** | Color score, saturation, luminance, histogram spread; color temperature (warm/cool/neutral) and hue bucket (requires `--recompute-colors`) |
| **Exposure** | Exposure score |
| **User Ratings** | Star rating |
| **Camera Settings** | ISO, aperture (f-stop range slider), focal length (range slider) |
| **Content** | Tags, monochrome toggle |
| **Moments** | Narrative moment confidence (0–1 range slider: `min_moment_confidence` / `max_moment_confidence`) |

### Composition Patterns

Filter by SAMP-Net detected patterns:
- rule_of_thirds, golden_ratio, center, diagonal
- horizontal, vertical, symmetric, triangle
- curved, radial, vanishing_point, pattern, fill_frame

## Sorting

Sortable columns grouped by category (from `viewer.sort_options`):

| Group | Columns |
|-------|---------|
| **General** | Aggregate Score, Aesthetic, Quality Score, Date Taken, Star Rating, Aesthetic (IAA), LIQE Score |
| **Face Metrics** | Face Quality, Face Quality (IQA), Eye Sharpness, Face Sharpness, Face Ratio, Face Count |
| **Technical** | Tech Sharpness, Contrast, Noise Level |
| **Color** | Color Score, Saturation |
| **Exposure** | Exposure Score, Mean Luminance, Histogram Spread, Dynamic Range |
| **Composition** | Composition Score, Power Point Score, Leading Lines, Isolation Bonus, Composition Pattern |
| **Subject Saliency** | Subject Sharpness, Subject Prominence, Subject Placement, Background Separation |
| **Content** | Moment Confidence (NULLs sink) |

### My Taste

A first-class sort option backed by the personal ranker's `learned_score` (renamed from "Picked for you"). It orders photos by what the ranker has learned from your A/B comparisons, ratings, and culling decisions. A confidence badge next to the sort shows the learned coverage (% of photos with a learned score) and the ranker's held-out accuracy, so you can judge how much to trust the ordering. Train or refresh the ranker with `python facet.py --train-ranker`.

Controlled by `viewer.features.show_my_taste` (default: `true`). Ranker status is exposed via `GET /api/ranker/status`.

## Gallery Features

### Photo Cards

- Thumbnail with score badge
- Clickable tags for quick filtering
- Person avatars for recognized faces
- Category badge

### Multi-Select & Bulk Actions

- Click photos to select, Shift+Click for range selection
- Action bar appears with selection count and available actions
- **Favorite** — Mark all selected as favorite (clears rejected)
- **Reject** — Mark all selected as rejected (clears favorite and rating)
- **Rate** — Set star rating (1–5) for all selected, or clear rating
- **Add to album** — Add selected to an existing or new album
- **Copy filenames** — Copy selected filenames to clipboard
- **Export** — Write XMP sidecars (rating/favorite/reject) next to the selected files (see [Editor Export](#editor-export))
- **Download** — Download selected photos
- Clear selection with Escape or the Clear button

Bulk actions require edition mode. Double-click any photo to download it directly.

### Keep Top N%

A **Keep top %** control in the gallery toolbar (edition mode) turns the whole filtered view into a one-step cull. Set a percentage; the server ranks the current view by the **current sort** (aggregate, My Taste, Top Picks, sharpness, …), keeps that top share, and **selects the rest** — the lowest-ranked photos — so you can reject them from the selection action bar (or deselect any you want to spare first). Nothing is moved or deleted: it only populates the selection (and every reject still trains "My Taste"). The selection is capped at 5000 photos; on a very large view the control says so — narrow the filter (album, date, person…) to act on the remainder.

### Display Options

- **Layout Mode** - Switch between **Grid** (uniform cards) and **Mosaic** (justified rows preserving aspect ratios). Mosaic is desktop-only; mobile always uses grid.
- **Thumbnail Size** - Slider to adjust card/row height (120–400px, persisted in localStorage)
- **Hide Details** - Hide photo metadata on cards (grid mode only)
- **Hide Tooltip** - Disable the hover tooltip that shows photo details on desktop
- **Hide Blinks** - Filter out photos with detected blinks
- **Best of Burst** - Show only top-scored photo from each burst
- **Infinite Scroll** - Photos load as you scroll
- **Fast Scrolling (virtualized)** - Row-windowed rendering: only rows near the
  viewport are in the DOM, so deep scrolling through tens of thousands of photos
  stays responsive. On by default; disable in the Display section of the filter
  sidebar if you hit layout issues (grid mode with details shown always uses
  full rendering since row heights aren't deterministic there). Persisted in
  localStorage (`facet_virtual_scroll`).

### Similar Photos

Click the "Similar" button on any photo to choose a similarity mode:

- **Visual** (default) — pHash hamming distance (70%) + CLIP/SigLIP cosine similarity (30%). Falls back to CLIP-only when no pHash is available.
- **Color** — Histogram intersection (70%) + saturation distance (10%) + luminance distance (10%) + monochrome bonus (10%). Pre-filters by monochrome flag and saturation range.
- **Person** — Finds photos containing the same person(s). Uses `person_id` when available (fast), otherwise falls back to face embedding cosine similarity.

Use the **similarity threshold slider** (0–90%) to control how strict the matching is (not shown in person mode). The panel supports infinite scroll for large result sets.

### Filter Chips

Active filters shown as removable chips with counts at top of gallery.

## Person Management

> Browsing persons is open to all viewers; renaming, merging, avatar changes and face assignment require `[Edition]`.

### Person Filter

Dropdown shows persons with face thumbnails. Click to filter gallery.

### Person Gallery

Click person name to view all their photos at `/person/<id>`.

### Manage Persons Page

Access via header button or `/persons`:

| Action | How To |
|--------|--------|
| **Merge** | Select source person, click target, confirm |
| **Delete** | Click delete button on person card |
| **Rename** | Click person name to edit inline |
| **Split** | Open a person's faces, select a subset, split them into a new person |
| **Hide** | Hide a cluster from the persons list, filters, and merge suggestions (reversible) |

## Scan Trigger (Superadmin)

When `viewer.features.show_scan_button` is `true` and the user has `superadmin` role, a **Scan photos to get started** button appears on the empty-gallery state. It ships set to **`false`** in `scoring_config.json` (superadmin opt-in). The button opens the scan launcher dialog (`ScanLauncherComponent`).

- Pick a directory from the launcher's list and start the scan in-app
- The launcher streams live progress (SSE with automatic polling fallback) into a `mat-progress-bar` driven by the structured `progress` field, plus a tail of output lines, and refreshes the gallery when the scan finishes
- Scan runs as a background subprocess (`facet.py`); only one scan at a time (global lock)
- Directory choices come from `get_all_scan_directories()`, which unions each user's `directories`, shared directories, `path_mapping` targets, and the standalone `viewer.scan_directories` list — seed the latter (e.g. `/data/photos`) so single-user / Docker installs have a pickable target

This is useful when the viewer runs on the same machine that has GPU access for scoring.

## Semantic Search

Hybrid search combining CLIP/SigLIP embedding similarity (70%) with FTS5 BM25 text matching on captions and tags (30%). Type a query like "sunset over mountains" or "child playing in snow" and the viewer returns matching photos ranked by combined score.

- Requires stored `clip_embedding` data (computed during scoring)
- Uses sqlite-vec for KNN vector search when installed, falls back to in-memory NumPy
- FTS5 text search on AI captions/tags provides additional keyword matching (run `database.py --rebuild-fts` to enable)
- Uses the same embedding model as the active VRAM profile (SigLIP 2 for 16gb/24gb, CLIP ViT-L-14 for legacy/8gb)
- `scope=text` restricts the query to literal FTS5 matches in OCR/caption text and skips the embedding search
- Controlled by `viewer.features.show_semantic_search` (default: `true`)

## Albums

Organize photos into named albums. Access via the `/albums` route.

### Manual Albums

Create albums and add photos from the gallery using multi-select. Albums support:
- Name and description
- Custom cover photo
- Custom ordering
- Browse album contents at `/album/:albumId`

### Smart Albums

Save a combination of filters (camera, tag, person, date range, score thresholds, etc.) as a smart album. Smart albums dynamically update as new photos match the saved filter criteria. The filter combination is stored as JSON in `smart_filter_json`.

API: see the [API Endpoints](#api-endpoints) section below.

Controlled by `viewer.features.show_albums` (default: `true`).

### Photo Sharing

Share albums with external users via tokenized links. No authentication required to view shared albums.

| Action | How To |
|--------|--------|
| **Share** | Open album, click "Share" button to generate a shareable link |
| **Revoke** | Click "Unshare" to invalidate the share token |
| **View** | Recipients open the link to browse the shared album at `/shared/album/:id` |

API: see the [API Endpoints](#api-endpoints) section below.

### Client Proofing

When `viewer.features.show_proofing` is enabled (default `false`), a shared-album link can run in **proofing mode**: the client (no account) opens the share link, optionally enters a PIN (`viewer.proofing.pin`), and can then **heart** photos and leave **comments** — a lightweight way to let a client choose their favorites from a delivery.

Client picks are fully isolated from your library. They live in a dedicated `album_client_picks` table, are bounded to that album's photos, and never touch your own favorites/ratings (`photos.is_favorite` / `user_preferences`) or train the personal ranker. As the owner you read the picks from an `[Edition]` dialog on the album card. Sessions are short-lived (`viewer.proofing.session_minutes`, default 24h) and stop working the moment the album is unshared or proofing is disabled.

Controlled by `viewer.features.show_proofing` (default: `false`). See [Configuration — Client Proofing](CONFIGURATION.md#client-proofing).

## AI Critique

Breaks down a photo's scores into strengths, weaknesses, and suggestions.

### Rule-Based Critique

Available on all VRAM profiles. Analyzes stored metrics (aesthetic, composition, sharpness, face quality, etc.) and generates a structured explanation of the score.

The breakdown also surfaces the explainable **form and color-harmony** rows (symmetry, balance, edge-orientation entropy, fractal complexity, Matsuda color harmony — populated by `--recompute-form`), **distortion-attribute chips** for any likely defects (motion blur, color cast, oversharpening, … — from `--recompute-distortions`), and a **skin-tone note** for portraits whose skin chroma drifts off-natural (`--recompute-skin-tone`). All three are advisory — they explain the photo, they do not change the aggregate — and each row shows only when its underlying column is populated.

### VLM Critique `[GPU]` `[16gb/24gb]`

Uses the configured VLM (Qwen3.5-2B or Qwen3.5-4B) for a context-aware critique. Requires 16gb or 24gb VRAM profile and `viewer.features.show_vlm_critique: true`.

The prompt is a configurable ladder (`critique.vlm`) that injects the full rule breakdown, penalties and EXIF, and the reply is rendered as **Observation / Assessment / Suggestions**. The result is cached per photo (`photos.vlm_critique`) and translated on demand, with a **Regenerate** button to recompute it. It runs against the stored thumbnail, so RAW files critique correctly instead of failing silently.

API: see the [API Endpoints](#api-endpoints) section below.

Controlled by `viewer.features.show_critique` (default: `true`) and `viewer.features.show_vlm_critique` (default: `true`).

**Visual "why this score" overlay.** When `viewer.features.show_saliency_overlay` is `true` (default), the critique dialog gains a **Show overlay** toggle: it draws the BiRefNet saliency map as a translucent heatmap over the photo (recomputed on demand from the stored thumbnail — `GET /api/saliency_overlay`), plus soft per-face boxes and eye markers reconstructed from stored landmarks (`GET /api/photo/face_markers`). Boxes are green when eyes are open, amber on a blink. The heatmap is illustrative (thumbnail-resolution), not pixel-exact; the toggle hides itself on profiles where no saliency mask is producible.

## AI Captioning `[GPU]` `[16gb/24gb]` `[Edition]`

Get an AI-generated natural language caption for any photo. Captions are generated on first request and cached in the `caption` database column. Captions can be edited manually in edition mode via the photo detail page. (Caption *translation* runs on CPU — see below.)

API: see the [API Endpoints](#api-endpoints) section below.

Also available via CLI for bulk generation and translation:

```bash
python facet.py --generate-captions      # Generate captions for all uncaptioned photos
python facet.py --translate-captions     # Translate captions to configured target language
```

Caption translation uses MarianMT (CPU, no GPU required). Configure the target language in `scoring_config.json` under `translation.target_language` (default: `"fr"`). Supported languages: French, German, Spanish, Italian.

Controlled by `viewer.features.show_captions` (default: `true`). Requires 16gb or 24gb VRAM profile for VLM-based captioning.

## Memories ("On This Day")

Browse photos taken on the same calendar date in previous years. Opening Memories starts a randomized full-screen diaporama (slideshow) of the matching photos rather than a grid; the nav button's tooltip spells out what it does.

API: see the [API Endpoints](#api-endpoints) section below.

Controlled by `viewer.features.show_memories` (default: `true`).

## Common workflows

- **Cull a vacation** — open Capsules → look for the auto-generated `journey` capsule for the trip dates. Each capsule offers a Save-as-Album action.
- **Walk a day-by-day review** — open Timeline → sort by aggregate → step through the year. Top shots float up first when you've enabled `hide_bursts` and `hide_duplicates` (defaults: on).
- **Show what's hidden** — the gallery hides blinks / non-lead bursts / non-lead duplicates by default. When at least one of those filters is on and would exclude rows, a "N photos hidden by current filters · Show all" banner appears above the grid.

## Timeline View

Chronological photo browser with date-based navigation. Scroll through photos organized by date with a sidebar showing available years and months.

API: see the [API Endpoints](#api-endpoints) section below.

Access via the `/timeline` route. Controlled by `viewer.features.show_timeline` (default: `true`).

## Map View

View photos on an interactive map based on GPS coordinates extracted from EXIF data. Uses Leaflet for map rendering with clustering at different zoom levels.

### Setup

Extract GPS coordinates from existing photos:

```bash
python facet.py --extract-gps    # Extract GPS lat/lng from EXIF into database
```

GPS coordinates are also extracted automatically during scoring for new photos.

API: see the [API Endpoints](#api-endpoints) section below.

Access via the `/map` route. Controlled by `viewer.features.show_map` (default: `true`).

## Capsules

Curated photo diaporamas (slideshows) grouped by theme, place, people, and time — click a capsule to play it. Access via the `/capsules` route.

### Capsule Types

Capsules are auto-generated from your library using multiple algorithms:

- **Journey** — trips detected via GPS clustering, with reverse-geocoded destination names ("Journey to Rome — March 2025")
- **Moments with [Person]** — best photos of each recognized person
- **Seasonal Palette** — photos grouped by season + year
- **Golden Collection** — top 1% by aggregate score
- **Color Story** — visually similar groups via CLIP embedding clustering
- **This Week, Years Ago** — extended "On This Day" across ±3 days
- **Location** — geotagged photo clusters with place names
- **Favorites** — favorited photos grouped by year and season
- **Dimension-based** — auto-generated from camera, lens, category, composition pattern, focal length range, time of day, star rating, and cross-dimensional combos

### Slideshow

Click any capsule card to start a slideshow. Features:
- **Themed transitions** — slide (journeys), zoom (portraits), kenburns (golden/seasonal), crossfade (default)
- **Auto-chaining** — when a capsule finishes, a transition card shows the next capsule before continuing
- **Shuffle & resume** — photos are shuffled for variety; resume position is tracked per capsule
- **Adaptive grouping** — portrait photos are grouped side-by-side based on viewport aspect ratio
- **Save as album** — save any capsule as a permanent album

### Freshness

Capsules rotate on a configurable schedule (default: 24 hours). Cover photos and seeded discovery capsules align to the same rotation period. The "Regenerate" button in the header forces an immediate refresh.

### Reverse Geocoding

Location and journey capsules show place names (e.g., "Paris, France") instead of coordinates. This uses offline geocoding via the `reverse_geocoder` package — no API calls needed. Results are cached in the database.

Install: `pip install reverse_geocoder`

API: see the [API Endpoints](#api-endpoints) section below.

### Configuration

See [Configuration — Capsules](CONFIGURATION.md#capsules) for all settings.

## Folders View

Browse your photo library by directory structure. Access via the `/folders` route.

- Breadcrumb navigation to move up the directory tree
- Each folder shows a cover photo (highest-scoring image in that directory)
- Click a folder to descend into it, or click a photo to open it in the gallery
- Respects multi-user directory visibility in multi-user mode

## GPS Filter Dialog

Filter photos by geographic location using an interactive map picker:

- Click the location filter button to open the map dialog
- Click or drag on the map to set a center point
- Adjust the radius slider to control the search area
- Photos within the selected radius are filtered into the gallery
- Requires GPS coordinates (run `--extract-gps` if photos have EXIF GPS data)

## Merge Suggestions

Find person clusters that may be the same individual. Access via `/merge-suggestions` or from the Manage Persons page.

- **Similarity threshold slider** — how similar two persons must look to be suggested (lower = more suggestions, higher = fewer)
- **Merge** — accept a suggestion to merge the two persons
- **Batch merge** — select multiple suggestions and merge them at once
- Dismissed suggestions are remembered and not proposed again
- Also available via CLI: `python facet.py --suggest-person-merges`

## Editor Export

Write your ratings, favorites, and rejections to disk as XMP sidecars, so external editors (darktable, Lightroom) pick them up. Requires edition mode.

- **From the gallery** — select photos, then **Actions → Export** writes a sidecar next to each file.
- **From an album** ("basket") — export the whole album as sidecars, or copy/symlink the files to a target directory.
- **Write metadata to file** — the photo detail "Write metadata to file" action embeds the rating/keywords directly into the original file (JPEG/HEIC/TIFF/PNG/DNG via exiftool) in addition to writing the sidecar, so the whole photo ecosystem sees them. Proprietary RAW originals are never modified. Controlled by `viewer.features.show_embed_metadata` (default: `true`).

API: see the [API Endpoints](#api-endpoints) section below.

## Culling

The culling page (`/culling`, edition mode) groups near-identical shots so you can keep the best of each and reject the rest. A **granularity** select — the first, highest-impact control in the toolbar — chooses how photos are grouped:

- **All** (default) — merged burst + similar groups.
- **Bursts** — photos shot close together in time (from burst detection).
- **Similar** — photos that look alike regardless of when they were taken, grouped by CLIP/SigLIP embedding similarity. A threshold slider controls how strict the grouping is.
- **Scenes** — chronological scene groups (capture-time runs), each headed by its time span and dominant narrative moment. Gated on `viewer.features.show_scenes`.

For each group, pick the keeper(s); confirming rejects the rest. Confirms are deferred and can be undone (see [Undo](#undo)). The granularity, sort, and category choices persist in `localStorage`. Controls that don't apply to the current granularity are hidden — the sort dropdown and similarity-threshold slider disappear in scene mode, and the scope button is hidden when you have no manual albums. Every toolbar and group-action button carries a tooltip, and on small screens the toolbar detaches into a scrollable bottom bar.

**Scoped culling.** The darkroom can be narrowed to a subset via query params: `?group_by=scene` switches to scene granularity, `?album=<id>` restricts it to an album, and `?from=&to=` (EXIF capture-time window, the basis of **Cull this scene**) restricts it to one scene. A banner shows the active scope with an **Exit scene** control; the burst member fetch stays album-scoped but ignores the window, so a burst straddling the scene boundary still shows all its frames.

**My Taste chip.** Every confirm records `source='culling'` comparison rows that train the personal ranker, so the header shows a small "My Taste · N comparisons" chip that updates after each decision — the AI learns your eye as you cull (`GET /api/ranker/status`).

**Genre profiles.** A **Profile** selector in the toolbar applies a genre preset that bundles every culling knob at once — strictness, keeper budget, similarity threshold and the darkroom's eyes-closed / poor-expression face cutoffs — so sports keeps only the sharpest of a burst, weddings keep more eyes-open variants, concerts and wildlife relax the face gates. The choice persists in `localStorage`; nudging any knob by hand reverts the label to "Custom". Presets live in the [`cull_profiles`](CONFIGURATION.md#genre-aware-culling-profiles) block (`GET /api/culling/profiles`).

### Auto-cull

A toolbar **Auto-cull** button culls a whole scope in one pass instead of group-by-group. Pick the scope with the granularity/scope controls (all groups, or only bursts / similars / scenes, optionally an album or date window), set a **strictness** — the keeper budget, where higher keeps fewer per group — and preview. Each group keeps its best photo plus everything within the strictness margin (floored at a per-group minimum) and rejects the rest.

The preview is a **dry run** (nothing is written): it shows the per-group keep/reject split. Confirm to apply — rejections are recorded and, like every cull, train "My Taste"; an optional **Highlights** album idempotently collects each group's best photo scoring at least `auto_cull.highlights_min`. A "better photo in this group" hint badge flags groups where auto-cull would keep a different frame than the current lead. `POST /api/culling/auto`; configured via the [`auto_cull`](CONFIGURATION.md#auto-cull) block.

### Fullscreen

Press **`F`** (or the header toggle) to drive the browser Fullscreen API and review edge-to-edge — the darkroom fills the screen with no app chrome. The key is listed in the darkroom's shortcut legend; press `F` or `Esc` to exit.

### Loupe / Z-key zoom

Press **`Z`** in the single-view lightbox to toggle a Photo-Mechanic-style loupe (fit ↔ 2×; wheel/`+`/`-` zoom up to 800%). Past the fit scale the pane swaps its thumbnail for the full-resolution `/image` source, so you judge critical focus on real pixels without leaving the view. On the Scenes contact strip, `Z` toggles a hover-magnifier that follows the cursor over a tile (sourced from the full-res image), with an adjustable zoom slider. Stored thumbnails cap at 640px, so the loupe is the way to pixel-peek beyond that.

### Per-Face Badges

In the burst/similar culling lightbox, each detected face carries its own badges — eyes open/closed, poor expression, and detection confidence — instead of a single photo-level blink flag. This makes group shots easier to cull: you can see at a glance which face has closed eyes or a weak expression. The badges are fetched for a whole group in one batch call (`POST /api/culling-group/faces`).

The darkroom's **face panel** colour-codes each face crop green / orange / red from its continuous eyes-open and smile scores, and adds live **eyes** and **smile** threshold sliders so you can tune what counts as a blink or a weak expression on the fly. The cut-offs are the config keys `face_detection.eyes_closed_max` and `face_detection.poor_expression_min` (both default `4.0`); the sliders start there.

**Synced compare (2-up / 4-up).** The lightbox header has Single / Compare 2 / Compare 4 buttons. In compare mode the panes share one pan/zoom transform, so scroll-wheel zoom or drag-pan on any pane moves them all to the identical crop — the way to pick the sharpest frame of a burst by actually peeping pixels. Double-click toggles fit ↔ zoom; past the fit scale each pane lazily swaps its 1920px thumbnail for the full-resolution `/image` source so the peek is crisp. No backend change — both image routes already exist. (Touch-pinch is not yet wired; use the wheel on desktop.)

API: see the [API Endpoints](#api-endpoints) section below.

## Scenes View

A **read-only** browse of your library grouped into chronological "scenes" — capture-time runs shown in story order with a grid, a hover loupe, and date/moment headers. Open to **all authenticated users** (read-only and edition alike). Photos are split into scenes by capture-time gaps (a new scene starts when more than `scenes.gap_minutes` pass between consecutive shots, adaptively widened on sparse shoots), and any over-long run is sub-split so a continuously-shot event never collapses into one giant scene.

The only entry point is the per-album **Display scenes of this album** action button in the Albums grid (an album-scope picker inside the browse lets you switch the scope). There is no Scenes entry in the main nav. Each scene carries an edition-only **Cull this scene** button that deep-links into the [Culling](#culling) surface in scene granularity (`/culling?group_by=scene&album=&from=&to=`); edition users can also reach Scenes-as-culling directly from the Culling nav. The browse itself has no reject grid or bulk confirm — all culling now happens through the unified Culling surface.

When narrative moments are computed (below), each scene is also titled by its dominant moment, and `scenes.split_on_moment_change` can sub-split a long run where the moment changes.

## Narrative Moments

Facet labels each photo with the scene/activity "moment" it depicts. The default **general** vocabulary is library-agnostic — celebration, dining, beach, water activity, mountains, nature & wildlife, cityscape, travel landmark, concert, sports, group gathering, portrait, children, pets, nightlife, ceremony, scenic landscape, snow & winter, home indoor, road & vehicle — or `other` (a `wedding` vocabulary ships as an opt-in genre). Neither Narrative Select nor AfterShoot does this; they group by time and visual similarity only.

It is **zero-shot and fully local**, and **caption-semantic**: each photo's AI caption is encoded once and stored, and the moment is the best **max-pooled** cosine of that caption embedding against each moment's text prompts (L0) — the stored image embedding is the fallback when a photo has no caption. The caption signal matches moments ~2.4× more cleanly than the raw image. Small face/tag priors break near-ties (L1), then a Viterbi pass **smooths along the timeline** so an isolated misread is pulled back into the surrounding run (L2). An optional VLM tie-breaker (L3, 16gb/24gb) can re-judge low-confidence frames. Caption embeddings are computed once and reused, so re-labelling is a cheap dot product over stored vectors — no image decode, no per-image model pass; it **runs automatically at the end of every scan** (encoding only the new captions). The first full pass over an existing library encodes every caption (GPU recommended); re-label the whole library with `python facet.py --recompute-moments`.

Moments surface as scene titles and as a gallery filter (`GET /api/photos?narrative_moment=beach`, options from `GET /api/filter_options/narrative_moments`). The vocabulary is config-driven per event type — see [Configuration — Narrative Moments](CONFIGURATION.md#narrative-moments) to tune prompts/thresholds or switch genre.

**Moment confidence.** Each label stores a posterior confidence (`narrative_moment_confidence`). Labels below `viewer.moment_confidence_min` (default `0` = never dim) render dimmed with an "(uncertain)" suffix in the Scenes header, the Culling scene-group header, and the gallery photo tooltip (which also shows the confidence %). Confidence is also a sort option — **Moment Confidence** (NULLs sink) under the Content group — and a gallery range filter (`min_moment_confidence` / `max_moment_confidence`, a 0–1 slider in the sidebar **Moments** section).

- Each scene shows its lead photos in capture order
- Cull a scene from its **Cull this scene** button, which opens the culling surface scoped to that scene
- Scenes smaller than `scenes.min_size` are omitted; at most `scenes.max_photos` photos are loaded

API: see the [API Endpoints](#api-endpoints) section below.

Controlled by `viewer.features.show_scenes` (default: `true`). See [Configuration — Scenes](CONFIGURATION.md#scenes) for `gap_minutes`, `min_size`, `max_photos`, `max_scene_size`, `adaptive`, and `adaptive_k`.

## Junk Sweep

A fast review queue for the non-photo "junk" that piles up in a hobbyist library — screenshots, scanned documents, receipts, memes, and presentation slides. Detection is zero-shot over the stored image embeddings (see [Configuration — Junk Sweep](CONFIGURATION.md#junk-sweep)); run `python facet.py --detect-junk` (or let it auto-run at the end of each scan) to populate `junk_kind`.

Open it from the **Junk Sweep** nav button (the `/junk` route, edition-only). The page reuses the gallery grid and shows every flagged candidate:

- **Kind filter chips** — "All kinds" plus one chip per detected kind with its count (from `GET /api/filter_options/junk_kinds`). Click to narrow the queue to one kind.
- **Keep** (per photo) — clears the junk label so the photo leaves the queue **permanently**: it is marked evaluated-clean (`not_junk`) and is never re-flagged by a later `--detect-junk`.
- **Reject** (per photo) — flags the photo as rejected using the same reject plumbing as everywhere else (nothing is deleted from disk).
- **Reject all shown** — a bulk reject of every candidate currently loaded, behind a confirmation dialog.
- **Loupe** — press **`Z`** (or the toolbar toggle) for a Photo-Mechanic-style hover magnifier to read fine text before deciding.

Junk photos are **not** hidden from the normal gallery — they stay visible until you filter for them. Filter any gallery view with `?junk_kind=<kind>` (exact) or `?junk_kind=any` (any junk, excludes the `not_junk` sentinel).

Controlled by `viewer.features.show_junk_sweep` (default: `true`).

## Pairwise Comparison Mode

Rank photos by judging them two at a time. The accumulated votes feed weight tuning. Access via the `/compare` route (Compare button in the header). Requires a non-empty `edition_password` (single-user) or `admin`/`superadmin` role (multi-user).

The page has four tabs:

### A/B Compare tab

Side-by-side photo pairs. Pick a winner, mark a tie, or skip. A progress bar tracks votes toward 50, with running A-wins/B-wins/tie counts. A category filter scopes the session, and a selection-strategy dropdown controls how pairs are chosen.

| Strategy | Description |
|----------|-------------|
| `uncertainty` | Photos with similar scores (most informative) |
| `boundary` | 6–8 score range (ambiguous zone) |
| `active` | Photos with the fewest comparisons (ensures coverage) |
| `random` | Random pairs (baseline) |

**Keyboard shortcuts:**

| Key | Action |
|-----|--------|
| `A` | Left photo wins |
| `B` | Right photo wins |
| `T` | Tie |
| `S` | Skip pair |
| `Escape` | Close category override modal |

### Weight Suggestions tab

Shows the weights learned from comparisons against the current weights, side by side, with model accuracy before/after. The current top 10 photos and the predicted top 10 after recompute are previewed in adjacent columns. **Apply** writes the suggested weights; **Recompute** rescores the category to apply them (both require edition mode).

### Weights tab

Manual weight editor: a slider per metric for the selected category with a live score preview. **Save** writes to `scoring_config.json` (with a backup); **Recompute Scores** applies them; **Reset** reloads the stored weights.

### Snapshots tab

Save the current weights as a named snapshot and restore any earlier snapshot.

### Category Override

To reassign a photo's category from the comparison view: edit the category badge, select a target category, run "Analyze Filter Conflicts" to see which filters exclude it, then apply the override.

## EXIF Statistics

The Stats page (`/stats`) provides analytics across 5 tabs. Use the **category** and **date range** selectors in the toolbar to filter all charts to a specific subset of your library.

### Tabs

| Tab | Description |
|-----|-------------|
| **Equipment** | Camera bodies, lenses, and combos (top 20 each) |
| **Shooting Settings** | ISO, aperture, focal length, shutter speed distributions |
| **Timeline** | Photos over time |
| **Categories** | Category analytics, weight management, and score correlations |
| **Correlations** | Custom X/Y metric correlation charts with grouping |

### Categories Tab

Four sub-tabs:

| Sub-tab | Description |
|---------|-------------|
| **Breakdown** | Photo counts per category, average scores, score distribution histograms |
| **Weights** | Radar chart comparison (up to 5 categories), weight heatmap, and weight editor (edition mode) |
| **Correlations** | Pearson correlation heatmap showing how each dimension influences the aggregate, click-to-detail view |
| **Overlap** | Filter overlap analysis showing which categories share matching photos |

Each chart has a toggleable `?` help button explaining how to read it. A global help toggle in the sub-tab bar shows explanations for all sub-tabs.

### Weight Editor (Edition Mode)

Available in the Weights sub-tab when edition mode is active:

1. Select a category from the dropdown
2. Adjust the weight sliders (one per metric, should sum to 100%)
3. Use "Normalize to 100" to auto-balance
4. Expand the collapsible Modifiers section to adjust bonuses/penalties
5. The **Score Distribution Preview** shows a live before/after histogram as you move sliders
6. Click **Save** to update `scoring_config.json` (creates a timestamped backup)
7. Click **Recompute Scores** (appears after save) to apply new weights to all photos in that category

All stats are user-aware in multi-user mode — each user sees analytics for their visible photos only.

## Keyboard Shortcuts (Gallery)

| Key | Action |
|-----|--------|
| `←` `→` `↑` `↓` | Move keyboard focus between photo cards (grid columns and mosaic rows) |
| `Enter` | Open the focused photo |
| `Space` | Select / deselect the focused photo |
| `Ctrl+A` | Select all loaded photos |
| `Escape` | Clear selection / close filter drawer |
| `Shift+Click` | Range-select photos between last selected and clicked |
| `Double-click` | Open photo |
| `?` | Show the keyboard shortcuts reference (works on every page) |

## Undo

Batch favorite/reject/rating operations and culling confirms show a snackbar
with an **Undo** action for ~7 seconds. Batch flag operations are committed
immediately and undone via inverse API calls (capped at 500 photos); culling
confirms are deferred — the group disappears instantly but the API call only
fires once the undo window elapses.

## Progressive Web App

The viewer ships a web app manifest and an Angular service worker (production
builds only): it can be installed to the home screen, the app shell loads
offline, and up to 1000 thumbnails are LRU-cached for 7 days. API responses
are never cached (except i18n bundles with a freshness strategy), and logout
clears the thumbnail cache so multi-user setups sharing a browser can't leak
previews across accounts. A snackbar offers a reload when a new version has
been deployed.

## Mobile

On small screens the bulk-selection bar collapses to the selection count,
clear, select-all and a single **Actions** button that opens a touch-friendly
bottom sheet with all bulk operations (favorite, reject, rate, albums, copy,
download).

## Configuration

### Display Settings

```json
{
  "viewer": {
    "display": {
      "tags_per_photo": 4,
      "card_width_px": 168,
      "image_width_px": 160,
      "image_jpeg_quality": 96
    }
  }
}
```

### Pagination

```json
{
  "viewer": {
    "pagination": {
      "default_per_page": 64
    }
  }
}
```

### Dropdown Limits

```json
{
  "viewer": {
    "dropdowns": {
      "max_cameras": 50,
      "max_lenses": 50,
      "max_persons": 50,
      "max_tags": 20,
      "min_photos_for_person": 10
    }
  }
}
```

Set `min_photos_for_person` higher to hide persons with few photos from the filter dropdown.

### Quality Thresholds

```json
{
  "viewer": {
    "quality_thresholds": {
      "good": 6,
      "great": 7,
      "excellent": 8,
      "best": 9
    }
  }
}
```

### Default Filters

```json
{
  "viewer": {
    "defaults": {
      "hide_blinks": true,
      "hide_bursts": true,
      "hide_duplicates": true,
      "hide_details": true,
      "hide_rejected": true,
      "sort": "aggregate",
      "sort_direction": "DESC",
      "type": ""
    },
    "default_category": ""
  }
}
```

### Top Picks Weights

```json
{
  "viewer": {
    "photo_types": {
      "top_picks_min_score": 7,
      "top_picks_min_face_ratio": 0.2,
      "top_picks_weights": {
        "aggregate_percent": 30,
        "aesthetic_percent": 28,
        "composition_percent": 18,
        "face_quality_percent": 24
      }
    }
  }
}
```

## Performance

### Large Databases (50k+ photos)

Run these for better performance:

```bash
python database.py --migrate-tags    # 10-50x faster tag queries
python database.py --refresh-stats   # Precompute aggregations
python database.py --optimize        # Defragment database
```

### Async SQLite (opt-in, for high-concurrency read paths)

`api.database.get_async_db()` is an aiosqlite-backed async context manager
parallel to `get_db()`. Endpoints are currently sync (FastAPI offloads them
to a worker thread pool, which is fine at typical concurrency). For high-
concurrency read paths (>5 simultaneous users), individual endpoints can be
migrated by:

1. Change `def foo(...)` to `async def foo(...)`.
2. Replace `with get_db() as conn:` with `async with get_async_db() as conn:`.
3. `await` every `.execute()` and `.fetchone()` / `.fetchall()`.
4. Keep write paths sync — aiosqlite serializes writes anyway, and the sync
   path's connection pool already handles them.

The plan's hottest candidates are `/api/photos`, `/api/timeline`,
`/api/search`. Migrate one at a time and benchmark before promoting.

### Statistics Cache

Precomputed aggregations with 5-minute TTL:
- Total photo counts
- Camera/lens model counts
- Person counts
- Category and pattern counts

Check status:
```bash
python database.py --stats-info
```

### Lazy Filter Loading

Filter dropdowns load on-demand via API:
- `/api/filter_options/cameras`
- `/api/filter_options/lenses`
- `/api/filter_options/tags`
- `/api/filter_options/persons`
- `/api/filter_options/patterns`
- `/api/filter_options/categories`
- `/api/filter_options/apertures`
- `/api/filter_options/focal_lengths`
- `/api/filter_options/colors`
- `/api/filter_options/metric_ranges`

## API Endpoints

Interactive API documentation is available at `/api/docs` (Swagger UI) and the OpenAPI schema at `/api/openapi.json`.

### Gallery

| Endpoint | Description |
|----------|-------------|
| `GET /api/photos` | Paginated photo list with filters |
| `GET /api/photo` | Single photo details |
| `GET /api/type_counts` | Photo counts per type |
| `GET /api/similar_photos/{path}` | Similar photos (modes: `visual`, `color`, `person`) |
| `GET /api/search?q=&limit=&threshold=&scope=` | Semantic text-to-image search (`scope=text` = OCR/caption text only) |
| `GET /api/critique?path=&mode=&refresh=` | AI critique (rule-based or VLM); `refresh=true` regenerates the cached VLM critique |
| `GET /api/ranker/status` | Personal-ranker status for the "My Taste" sort (learned coverage %, held-out accuracy) |
| `GET /api/config` | Viewer configuration |

### Authentication

| Endpoint | Description |
|----------|-------------|
| `POST /api/auth/login` | Authenticate and receive token |
| `POST /api/auth/edition/login` | Unlock edition mode |
| `POST /api/auth/edition/logout` | Lock edition mode (drop privileges, stay authenticated) |
| `GET /api/auth/status` | Check authentication status |

### Thumbnails and Images

| Endpoint | Description |
|----------|-------------|
| `GET /thumbnail` | Photo thumbnail |
| `GET /face_thumbnail/{id}` | Face crop thumbnail |
| `GET /person_thumbnail/{id}` | Person representative thumbnail |
| `GET /image` | Full-resolution image |

### Filter Options

| Endpoint | Description |
|----------|-------------|
| `GET /api/filter_options/cameras` | Camera models with counts |
| `GET /api/filter_options/lenses` | Lens models with counts |
| `GET /api/filter_options/tags` | Tags with counts |
| `GET /api/filter_options/persons` | Persons with counts |
| `GET /api/filter_options/patterns` | Composition patterns |
| `GET /api/filter_options/categories` | Categories with counts |
| `GET /api/filter_options/apertures` | Distinct f-stop values with counts |
| `GET /api/filter_options/focal_lengths` | Distinct focal lengths with counts |
| `GET /api/filter_options/colors` | Color temperature and hue-bucket facets with counts |
| `GET /api/filter_options/metric_ranges` | Observed min/max and histogram per numeric metric (for slider bounds) |

### Batch Operations

| Endpoint | Description |
|----------|-------------|
| `POST /api/photos/batch_favorite` | Mark multiple photos as favorite |
| `POST /api/photos/batch_reject` | Mark multiple photos as rejected |
| `POST /api/photos/batch_rating` | Set star rating for multiple photos |

### Persons

| Endpoint | Description |
|----------|-------------|
| `GET /api/persons` | List all persons |
| `POST /api/persons` | Create a new person, optionally attaching faces (edition-gated). Body: `{name, face_ids}` |
| `GET /api/persons/needs_naming?min_faces=N` | List unnamed auto-clustered persons with `face_count >= N` (default from `viewer.persons.needs_naming_min_faces`) |
| `POST /api/persons/{id}/rename` | Rename a person |
| `POST /api/persons/{id}/assign_faces` | Bulk-attach faces to a person; empty old-persons are auto-deleted (edition-gated). Body: `{face_ids}` |
| `POST /api/persons/{id}/split` | Split a subset of a person's faces into a new person (edition-gated). Body: `{face_ids, name}` |
| `POST /api/persons/{id}/hide` | Hide a person from the list, filters, and merge suggestions |
| `POST /api/persons/{id}/unhide` | Unhide a previously hidden person |
| `POST /api/persons/merge` | Merge two persons (JSON body) |
| `POST /api/persons/merge/{source_id}/{target_id}` | Merge source person into target |
| `POST /api/persons/merge_batch` | Merge multiple persons at once |
| `POST /api/persons/merge_suggestions/reject` | Dismiss a merge suggestion so it is not proposed again |
| `POST /api/persons/{id}/delete` | Delete a person |
| `POST /api/persons/delete_batch` | Delete multiple persons at once |

### Albums

| Endpoint | Description |
|----------|-------------|
| `GET /api/albums` | List all albums |
| `POST /api/albums` | Create album |
| `GET /api/albums/{id}` | Get album details |
| `PUT /api/albums/{id}` | Update album |
| `DELETE /api/albums/{id}` | Delete album |
| `GET /api/albums/{id}/photos` | List photos in album (paginated) |
| `POST /api/albums/{id}/photos` | Add photos to album |
| `DELETE /api/albums/{id}/photos` | Remove photos from album |
| `POST /api/albums/{id}/share` | Generate share token |
| `DELETE /api/albums/{id}/share` | Revoke share token |
| `GET /api/shared/album/{id}?token=` | View shared album (no auth) |
| `POST /api/shared/album/{id}/session` | Exchange a share token (+ optional PIN) for a client proofing session (rate-limited) |
| `PUT /api/shared/album/{id}/picks` | Client upserts a heart/comment on a photo (proofing session) |
| `GET /api/shared/album/{id}/picks` | Client reads their own picks (proofing session) |
| `GET /api/albums/{id}/picks` | `[Edition]` Owner reads all client picks for the album |

### Memories, Timeline, Map & Captions

| Endpoint | Description |
|----------|-------------|
| `GET /api/memories?date=` | Photos taken on this date in previous years |
| `GET /api/memories/check` | Check if memories exist for a date |
| `GET /api/caption?path=` | Get or generate AI caption |
| `PUT /api/caption` | Update photo caption (edition mode) |
| `GET /api/timeline?cursor=&limit=&direction=` | Paginated timeline photos |
| `GET /api/timeline/dates?year=&month=` | Available dates for navigation |
| `GET /api/timeline/years` | Available years with photo counts |
| `GET /api/timeline/months` | Available months for a year |
| `GET /api/photos/map?bounds=&zoom=&limit=` | Geotagged photos within bounds |
| `GET /api/photos/map/count` | Count of geotagged photos |

### Capsules

| Endpoint | Description |
|----------|-------------|
| `GET /api/capsules` | Paginated capsule list (cached) |
| `GET /api/capsules/{id}/photos` | Photos for a specific capsule |
| `POST /api/capsules/{id}/save-album` | Save capsule as album (edition mode) |

### Statistics

| Endpoint | Description |
|----------|-------------|
| `GET /api/stats/overview` | Overall scoring statistics summary |
| `GET /api/stats/score_distribution` | Score distribution histogram data |
| `GET /api/stats/top_cameras` | Top cameras by photo count |
| `GET /api/stats/categories` | Category counts and averages |
| `GET /api/stats/gear` | Camera/lens/combo counts |
| `GET /api/stats/settings` | Shooting settings distributions |
| `GET /api/stats/timeline` | Timeline data |
| `GET /api/stats/correlations` | Custom metric correlations |
| `GET /api/stats/categories/breakdown` | Per-category photo counts and score distributions |
| `GET /api/stats/categories/weights` | Category weights and modifiers from config |
| `GET /api/stats/categories/correlations` | Pearson r correlation per dimension per category |
| `GET /api/stats/categories/metrics?category=X` | Raw metric values for client-side preview |
| `GET /api/stats/categories/overlap` | Filter overlap analysis between categories |
| `POST /api/stats/categories/update` | Update category weights/modifiers (edition mode) |
| `POST /api/stats/categories/recompute` | Recompute scores for a category (edition mode) |

### Comparison Mode

| Endpoint | Description |
|----------|-------------|
| `GET /api/comparison/next_pair` | Get next photo pair for comparison |
| `POST /api/comparison/submit` | Submit comparison result |
| `POST /api/comparison/reset` | Reset comparison data |
| `GET /api/comparison/stats` | Comparison session statistics |
| `GET /api/comparison/history` | List past comparisons |
| `POST /api/comparison/edit` | Edit a comparison result |
| `POST /api/comparison/delete` | Delete a comparison |
| `GET /api/comparison/coverage` | Category coverage of comparisons |
| `GET /api/comparison/confidence` | Confidence metrics for learned scores |
| `GET /api/comparison/photo_metrics` | Raw metrics for photos |
| `GET /api/comparison/category_weights` | Category weights/filters |
| `GET /api/comparison/learned_weights` | Suggested weights from comparisons |
| `POST /api/comparison/preview_score` | Preview with custom weights |
| `POST /api/comparison/suggest_filters` | Analyze filter conflicts |
| `POST /api/comparison/override_category` | Override photo category |
| `POST /api/recalculate` | Recalculate scores with current weights |

### Burst Culling

| Endpoint | Description |
|----------|-------------|
| `GET /api/burst-groups` | List burst groups for culling |
| `POST /api/burst-groups/select` | Select keepers from a burst group |
| `GET /api/similar-groups?threshold=&page=&per_page=` | Groups of visually similar photos |
| `POST /api/similar-groups/select` | Select keepers from a similar group |
| `GET /api/culling-groups?group_by=all\|burst\|similar\|scene&exclude_rejected=true&similarity_threshold=&page=&per_page=` | Burst/similar/scene groups for culling. `group_by` (default `all`) selects merged burst+similar, burst-only, similar-only, or chronological scene groups (scene groups add `type`/`start`/`end`/`moment`/`moment_confidence`; the `sort` param is ignored in scene mode). `exclude_rejected` (default `true`) hides photos with `is_rejected=1`; groups with fewer than 2 remaining photos are dropped |
| `POST /api/culling-groups/confirm` | Confirm culling selections (burst, similar, or scene). Body `{group_id, type, paths, keep_paths}`; `type:'scene'` records the scene-cull comparison rows |
| `POST /api/culling/auto` | `[Edition]` One-button auto-cull for a whole scope. Body `{group_by, album_id?, date_from?, date_to?, strictness?, min_keep_per_group, highlights_album, dry_run}`; `dry_run` (default `true`) returns the per-group keep/reject preview, an apply rejects the rest and records culling pairs |
| `POST /api/culling-group/faces` | Per-face badges (eyes open/closed, expression, confidence) for a group, in one batch |
| `GET /api/scenes` | Chronological scenes of burst-lead photos (read-only browse) |
| `GET /api/filter_options/junk_kinds` | Detected junk kinds with counts (excludes the `not_junk` sentinel) for the Junk Sweep chips |
| `POST /api/photo/clear_junk` | `[Edition]` Keep a junk candidate — clears its `junk_kind` to `not_junk` so it leaves the queue permanently. Body `{photo_path}` |

### Scan

| Endpoint | Description |
|----------|-------------|
| `POST /api/scan/start` | `[Superadmin]` Start a scoring scan |
| `GET /api/scan/status` | Check scan progress (structured `progress`: `{phase, current, total, eta_seconds}`) |
| `GET /api/scan/stream?token=<jwt>` | `[Superadmin]` Real-time progress via Server-Sent Events; token is passed as a query param (the `EventSource` API can't set headers), with automatic fallback to polling `/status` |
| `GET /api/scan/directories` | List configured scan directories |

### Face Management

| Endpoint | Description |
|----------|-------------|
| `GET /api/person/{id}/faces` | List faces for a person |
| `POST /api/person/{id}/avatar` | Set person avatar face |
| `GET /api/photo/faces` | List faces detected in a photo |
| `POST /api/face/{id}/assign` | Assign a face to a person |
| `POST /api/photo/assign_all_faces` | Assign all faces in a photo to a person |
| `POST /api/photo/unassign_person` | Unassign a person from a photo |

### Photo Actions

| Endpoint | Description |
|----------|-------------|
| `POST /api/photo/set_rating` | Set star rating for a photo |
| `POST /api/photo/toggle_favorite` | Toggle favorite status |
| `POST /api/photo/toggle_rejected` | Toggle rejected status |

### Config Management

| Endpoint | Description |
|----------|-------------|
| `POST /api/config/update_weights` | Update scoring weights |
| `GET /api/config/weight_snapshots` | List saved weight snapshots |
| `POST /api/config/save_snapshot` | Save current weights as snapshot |
| `POST /api/config/restore_weights` | Restore weights from snapshot |

### Merge Suggestions

| Endpoint | Description |
|----------|-------------|
| `GET /api/merge_suggestions` | Suggested person merges based on face similarity |

### Folders

| Endpoint | Description |
|----------|-------------|
| `GET /api/folders` | List photo folder structure |

### Download

| Endpoint | Description |
|----------|-------------|
| `GET /api/download/options` | Available download types for a photo (`path`, optional `is_shared`) |
| `GET /api/download` | Download a photo (`path`, `type=original\|darktable\|raw`, optional `profile`) |
| `GET /api/photo/social_crop` | `[Edition]` Download the cropped full-resolution JPEG for a social aspect preset (`path`, `preset`) |
| `GET /api/photo/social_crop/preview` | `[Edition]` Return just the normalized crop rectangle + framing source for a preset (`path`, `preset`) — no original decode |

**Download types:**

- `original` — Serve the file as-is (JPG/HEIF) or rawpy-converted to JPEG (RAW files).
- `darktable` — Convert companion RAW with a named darktable profile (requires `profile` param). Falls back to original if no companion RAW exists.
- `raw` — Serve the companion RAW file as-is (not available in shared albums).

The `/api/download/options` endpoint detects companion RAW files automatically and returns available options including configured darktable profiles. The viewer uses this to populate a per-photo download menu.

**Saliency-aware social crop.** When `viewer.features.show_social_export` is `true` (default) and edition is unlocked, the photo detail download bar gains a **Social crop** menu listing the configured `social_export.presets` (square 1:1, portrait 4:5, story 9:16 out of the box). Choosing a preset downloads a full-resolution JPEG cropped to that aspect and framed on the detected subject — something Lightroom export presets cannot do. The crop window is the largest rectangle of the target aspect that fits inside the image, centered on the subject with a configurable margin (`social_export.subject_margin_percent`) and clamped at the edges. The subject box comes from a fallback chain: the persisted BiRefNet subject box (`photos.subject_bbox`, written by the saliency pass and `--recompute-saliency`) → the union of detected face boxes → a plain center crop. The `preview` endpoint returns which source drove the crop (`saliency` / `faces` / `center`), shown in the menu tooltip. Original decoding reuses the same RAW (rawpy) and HEIC (pillow-heif) loader as the download path, with EXIF orientation applied before cropping.

### Editor Export

| Endpoint | Description |
|----------|-------------|
| `POST /api/photo/export_xmp` | `[Edition]` Write one XMP sidecar |
| `POST /api/export/sidecars` | `[Edition]` Write sidecars for explicit paths or a filter set |
| `POST /api/photo/embed_metadata` | `[Edition]` Embed metadata into the original file (JPEG/HEIC/TIFF/PNG/DNG; RAW never modified) and write the sidecar |
| `POST /api/albums/{id}/export` | `[Edition]` Album export as sidecars, copy, or symlink |

### Plugins

| Endpoint | Description |
|----------|-------------|
| `GET /api/plugins` | List configured plugins |
| `POST /api/plugins/test-webhook` | Test a webhook plugin |

### Health

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Server health check |
| `GET /ready` | Server readiness check |
| `GET /metrics` | Prometheus-format metrics: photo counts, embedding coverage, DB size, process memory |

### Internationalization

| Endpoint | Description |
|----------|-------------|
| `GET /api/i18n/languages` | List available languages |
| `GET /api/i18n/{lang}` | Get translations for a language |

### Filter Options (additional)

| Endpoint | Description |
|----------|-------------|
| `GET /api/filter_options/location_name?lat=&lng=` | Reverse geocode coordinates to place name |

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Slow page load | Run `--migrate-tags` and `--optimize` |
| Filters not showing | Check `--stats-info`, run `--refresh-stats` |
| Person filter empty | Run `--cluster-faces-incremental` |
| Compare button missing | Set a non-empty `edition_password` (single-user) or use `admin`/`superadmin` role (multi-user) |
| Password not working | Check `viewer.password` (single-user) or verify password hash (multi-user) |
| User can't see photos | Check `directories` in their user config and `shared_directories` |
| Scan button missing | Requires `superadmin` role and `viewer.features.show_scan_button: true` |
| Search returns no results | Ensure photos have `clip_embedding` data (run scoring first) |
| VLM critique unavailable | Requires 16gb/24gb VRAM profile and `viewer.features.show_vlm_critique: true` |
| Map shows no photos | Run `--extract-gps` to populate GPS columns, ensure photos have EXIF GPS data |
| Captions not generating | Requires 16gb/24gb VRAM profile for VLM captioning |
| Timeline empty | Ensure photos have `date_taken` values |
| Port 5000 in use | Run `python viewer.py --port 5001` (or set `PORT=5001`). On macOS, ControlCenter's AirPlay Receiver binds 5000 by default — either pick another port or disable AirPlay Receiver in System Settings → General → AirDrop & Handoff. |
