# Web Viewer

FastAPI + Angular single-page application for browsing, filtering, and managing photos.

## Starting the Viewer

### Production

```bash
python viewer.py
# Open http://localhost:5000
```

This serves both the API and the pre-built Angular application on a single port.

For higher throughput (4 Uvicorn workers):

```bash
python viewer.py --production
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
| **Color** | Color score, saturation, luminance, histogram spread |
| **Exposure** | Exposure score |
| **User Ratings** | Star rating |
| **Camera Settings** | ISO, aperture (f-stop range slider), focal length (range slider) |
| **Content** | Tags, monochrome toggle |

### Composition Patterns

Filter by SAMP-Net detected patterns:
- rule_of_thirds, golden_ratio, center, diagonal
- horizontal, vertical, symmetric, triangle
- curved, radial, vanishing_point, pattern, fill_frame

## Sorting

25+ sortable columns grouped by category:

| Group | Columns |
|-------|---------|
| **General** | Aggregate Score, Aesthetic, TOPIQ Score, Date Taken, Star Rating, Favorites, Rejected |
| **Extended Quality** | Aesthetic IAA, Face Quality IQA, LIQE Score |
| **Face Metrics** | Face Quality, Eye Sharpness, Face Sharpness, Face Ratio, Face Confidence, Face Count |
| **Technical** | Tech Sharpness, Contrast, Noise Level |
| **Color** | Color Score, Saturation |
| **Exposure** | Exposure Score, Mean Luminance, Histogram Spread, Dynamic Range |
| **Composition** | Composition Score, Power Point Score, Leading Lines, Isolation Bonus, Composition Pattern |
| **Subject Saliency** | Subject Sharpness, Subject Prominence, Subject Placement, Background Separation |

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
- **Copy filenames** — Copy selected filenames to clipboard
- **Download** — Download selected photos
- Clear selection with Escape or the Clear button

Bulk actions require edition mode. Double-click any photo to download it directly.

### Display Options

- **Layout Mode** - Switch between **Grid** (uniform cards) and **Mosaic** (justified rows preserving aspect ratios). Mosaic is desktop-only; mobile always uses grid.
- **Thumbnail Size** - Slider to adjust card/row height (120–400px, persisted in localStorage)
- **Hide Details** - Hide photo metadata on cards (grid mode only)
- **Hide Tooltip** - Disable the hover tooltip that shows photo details on desktop
- **Hide Blinks** - Filter out photos with detected blinks
- **Best of Burst** - Show only top-scored photo from each burst
- **Infinite Scroll** - Photos load as you scroll

### Similar Photos

Click the "Similar" button on any photo to choose a similarity mode:

- **Visual** (default) — pHash hamming distance (70%) + CLIP/SigLIP cosine similarity (30%). Falls back to CLIP-only when no pHash is available.
- **Color** — Histogram intersection (70%) + saturation distance (10%) + luminance distance (10%) + monochrome bonus (10%). Pre-filters by monochrome flag and saturation range.
- **Person** — Finds photos containing the same person(s). Uses `person_id` when available (fast), otherwise falls back to face embedding cosine similarity.

Use the **similarity threshold slider** (0–90%) to control how strict the matching is (not shown in person mode). The panel supports infinite scroll for large result sets.

### Filter Chips

Active filters shown as removable chips with counts at top of gallery.

## Person Management

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

## Scan Trigger (Superadmin)

When `viewer.features.show_scan_button` is `true` and the user has `superadmin` role, a Scan button appears in the gallery header.

- Select directories to scan from the modal
- Scan runs as a background subprocess (`facet.py`)
- Only one scan at a time (global lock)
- Progress displayed in a terminal-style output area

This is useful when the viewer runs on the same machine that has GPU access for scoring.

## Semantic Search

Search photos by natural language description using stored CLIP/SigLIP embeddings. Type a query like "sunset over mountains" or "child playing in snow" and the viewer returns visually matching photos ranked by similarity.

- Requires stored `clip_embedding` data (computed during scoring)
- Uses the same embedding model as the active VRAM profile (SigLIP 2 for 16gb/24gb, CLIP ViT-L-14 for legacy/8gb)
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

### API

| Endpoint | Description |
|----------|-------------|
| `GET /api/albums` | List all albums |
| `POST /api/albums` | Create album |
| `GET /api/albums/{id}` | Get album details |
| `PUT /api/albums/{id}` | Update album (name, description, cover) |
| `DELETE /api/albums/{id}` | Delete album |
| `GET /api/albums/{id}/photos` | List photos in album (supports `page`, `per_page`, `sort`, `sort_direction`) |
| `POST /api/albums/{id}/photos` | Add photos to album |
| `DELETE /api/albums/{id}/photos` | Remove photos from album |

Controlled by `viewer.features.show_albums` (default: `true`).

### Photo Sharing

Share albums with external users via tokenized links. No authentication required to view shared albums.

| Action | How To |
|--------|--------|
| **Share** | Open album, click "Share" button to generate a shareable link |
| **Revoke** | Click "Unshare" to invalidate the share token |
| **View** | Recipients open the link to browse the shared album at `/shared/album/:id` |

### API

| Endpoint | Description |
|----------|-------------|
| `POST /api/albums/{id}/share` | Generate share token for album |
| `DELETE /api/albums/{id}/share` | Revoke share token |
| `GET /api/shared/album/{id}?token=` | View shared album (no auth required) |

## AI Critique

Get a detailed breakdown of a photo's scores with strengths, weaknesses, and improvement suggestions.

### Rule-Based Critique

Available on all VRAM profiles. Analyzes stored metrics (aesthetic, composition, sharpness, face quality, etc.) and generates a structured explanation of why the photo scored the way it did.

### VLM Critique

Uses the configured VLM (Qwen3-VL-2B or Qwen2.5-VL-7B) to provide a richer, context-aware critique. Requires 16gb or 24gb VRAM profile and `viewer.features.show_vlm_critique: true`.

### API

| Endpoint | Description |
|----------|-------------|
| `GET /api/critique?path=<photo_path>&mode=rule` | Rule-based score breakdown |
| `GET /api/critique?path=<photo_path>&mode=vlm` | VLM-powered critique (requires GPU) |

Controlled by `viewer.features.show_critique` (default: `true`) and `viewer.features.show_vlm_critique` (default: `false`).

## AI Captioning

Get an AI-generated natural language caption for any photo. Captions are generated on first request and cached in the `caption` database column. Captions can be edited manually in edition mode via the photo detail page.

### API

| Endpoint | Description |
|----------|-------------|
| `GET /api/caption?path=<photo_path>` | Get or generate caption for a photo |
| `PUT /api/caption` | Update caption text (edition mode required) |

Also available via CLI for bulk generation and translation:

```bash
python facet.py --generate-captions      # Generate captions for all uncaptioned photos
python facet.py --translate-captions     # Translate captions to configured target language
```

Caption translation uses MarianMT (CPU, no GPU required). Configure the target language in `scoring_config.json` under `translation.target_language` (default: `"fr"`). Supported languages: French, German, Spanish, Italian.

Controlled by `viewer.features.show_captions` (default: `true`). Requires 16gb or 24gb VRAM profile for VLM-based captioning.

## Memories ("On This Day")

Browse photos taken on the same calendar date in previous years. A memories dialog shows a year-by-year retrospective of matching photos.

### API

| Endpoint | Description |
|----------|-------------|
| `GET /api/memories?date=YYYY-MM-DD` | Get photos taken on this date in previous years |

Controlled by `viewer.features.show_memories` (default: `true`).

## Timeline View

Chronological photo browser with date-based navigation. Scroll through photos organized by date with a sidebar showing available years and months.

### API

| Endpoint | Description |
|----------|-------------|
| `GET /api/timeline?cursor=&limit=&direction=` | Paginated timeline photos with cursor-based navigation |
| `GET /api/timeline/dates?year=&month=` | Available dates for year/month navigation |

Access via the `/timeline` route. Controlled by `viewer.features.show_timeline` (default: `true`).

## Map View

View photos on an interactive map based on GPS coordinates extracted from EXIF data. Uses Leaflet for map rendering with clustering at different zoom levels.

### Setup

Extract GPS coordinates from existing photos:

```bash
python facet.py --extract-gps    # Extract GPS lat/lng from EXIF into database
```

GPS coordinates are also extracted automatically during scoring for new photos.

### API

| Endpoint | Description |
|----------|-------------|
| `GET /api/photos/map?bounds=&zoom=&limit=` | Photos within map bounds (clustered by zoom) |
| `GET /api/photos/map/count` | Total count of geotagged photos |

Access via the `/map` route. Controlled by `viewer.features.show_map` (default: `true`).

## Capsules

Curated photo diaporamas (slideshows) grouped by theme. Access via the `/capsules` route.

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

### API

| Endpoint | Description |
|----------|-------------|
| `GET /api/capsules` | Paginated capsule list (cached) |
| `GET /api/capsules/{id}/photos` | Photos for a specific capsule |
| `POST /api/capsules/{id}/save-album` | Save capsule as album (edition mode) |

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

- **Similarity threshold slider** — adjust how similar two persons must look to be suggested as a merge (lower = more suggestions, higher = more conservative)
- **One-click merge** — review each suggestion and merge with a single click
- **Batch merge** — select multiple suggestions and merge them all at once
- Also available via CLI: `python facet.py --suggest-person-merges`

## AI Culling (Similar Groups)

Find groups of visually similar photos across your library for culling. Unlike burst detection (which groups by time), similar groups use CLIP/SigLIP embedding similarity to find photos that look alike regardless of when they were taken.

Access via the similarity tab in the burst culling component.

### API

| Endpoint | Description |
|----------|-------------|
| `GET /api/similar-groups?threshold=&page=&per_page=` | Paginated groups of visually similar photos |

## Pairwise Comparison Mode

Requires a non-empty `edition_password` in config (single-user) or `admin`/`superadmin` role (multi-user).

### Access

Click "Compare" button in gallery header.

### Interface

- Side-by-side photo comparison
- Selection strategies dropdown
- Progress bar toward 50 comparisons
- Real-time statistics (A wins, B wins, ties)
- Category filter for focused comparison

### Keyboard Shortcuts (Comparison)

| Key | Action |
|-----|--------|
| `A` | Select left photo as winner |
| `B` | Select right photo as winner |
| `T` | Mark as tie |
| `S` | Skip pair |
| `Escape` | Close category override modal |

### Selection Strategies

| Strategy | Description |
|----------|-------------|
| `uncertainty` | Similar scores (most informative) |
| `boundary` | 6-8 score range (ambiguous zone) |
| `active` | Fewest comparisons (ensures coverage) |
| `random` | Random pairs (baseline) |

### Weight Preview Panel

- Always visible below comparison
- Sliders for each weight metric
- Real-time score preview with delta
- "Suggest Weights" learns from comparisons
- "Reset" restores original weights

### Category Override

1. Click edit button on photo's category badge
2. Select target category
3. Click "Analyze Filter Conflicts"
4. Review why photo doesn't match
5. Apply override to manually assign

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

Interactive dashboard with 4 sub-tabs:

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
2. Adjust the 12 weight sliders (should sum to 100%)
3. Use "Normalize to 100" to auto-balance
4. Expand the collapsible Modifiers section to adjust bonuses/penalties
5. The **Score Distribution Preview** shows a live before/after histogram as you move sliders
6. Click **Save** to update `scoring_config.json` (creates a timestamped backup)
7. Click **Recompute Scores** (appears after save) to apply new weights to all photos in that category

All stats are user-aware in multi-user mode — each user sees analytics for their visible photos only.

## Keyboard Shortcuts (Gallery)

| Key | Action |
|-----|--------|
| `Escape` | Close filter drawer or clear selections |
| `Enter` | Submit search |
| `Shift+Click` | Range-select photos between last selected and clicked |
| `Double-click` | Download photo |

## Configuration

### Display Settings

```json
{
  "viewer": {
    "display": {
      "tags_per_photo": 4,
      "card_width_px": 168,
      "image_width_px": 160
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

Run these for optimal performance:

```bash
python database.py --migrate-tags    # 10-50x faster tag queries
python database.py --refresh-stats   # Precompute aggregations
python database.py --optimize        # Defragment database
```

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

## API Endpoints

Interactive API documentation is available at `/api/docs` (Swagger UI) and the OpenAPI schema at `/api/openapi.json`.

### Gallery

| Endpoint | Description |
|----------|-------------|
| `GET /api/photos` | Paginated photo list with filters |
| `GET /api/type_counts` | Photo counts per type |
| `GET /api/similar_photos/{path}` | Similar photos (modes: `visual`, `color`, `person`) |
| `GET /api/search?q=&limit=&threshold=` | Semantic text-to-image search |
| `GET /api/critique?path=&mode=` | AI critique (rule-based or VLM) |
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
| `POST /api/persons/{id}/rename` | Rename a person |
| `POST /api/persons/{id}/merge` | Merge person into another |
| `DELETE /api/persons/{id}` | Delete a person |

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
| `POST /api/albums/auto-generate` | Auto-generate albums from photo clusters |
| `GET /api/shared/album/{id}?token=` | View shared album (no auth) |

### Memories, Timeline, Map & Captions

| Endpoint | Description |
|----------|-------------|
| `GET /api/memories?date=` | Photos taken on this date in previous years |
| `GET /api/caption?path=` | Get or generate AI caption |
| `PUT /api/caption` | Update photo caption (edition mode) |
| `GET /api/timeline?cursor=&limit=&direction=` | Paginated timeline photos |
| `GET /api/timeline/dates?year=&month=` | Available dates for navigation |
| `GET /api/photos/map?bounds=&zoom=&limit=` | Geotagged photos within bounds |
| `GET /api/photos/map/count` | Count of geotagged photos |
| `GET /api/similar-groups?threshold=&page=&per_page=` | Groups of visually similar photos |

### Statistics

| Endpoint | Description |
|----------|-------------|
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
| `GET /api/comparison/photo_metrics` | Raw metrics for photos |
| `GET /api/comparison/category_weights` | Category weights/filters |
| `POST /api/comparison/preview_score` | Preview with custom weights |
| `GET /api/comparison/learned_weights` | Suggested weights |
| `POST /api/comparison/suggest_filters` | Analyze filter conflicts |
| `POST /api/comparison/override_category` | Override photo category |

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
| Port 5000 in use | Change port in `viewer.py` or kill the conflicting process |
