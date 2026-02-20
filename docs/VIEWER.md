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
# Open http://localhost:4200 (proxies API calls to :8000)
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
| **Face Metrics** | Face quality, eye sharpness, face sharpness, face ratio, face confidence, face count |
| **Composition** | Composition score, power points, leading lines, isolation, composition pattern |
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
| **Face Metrics** | Face Quality, Eye Sharpness, Face Sharpness, Face Ratio, Face Confidence, Face Count |
| **Technical** | Tech Sharpness, Contrast, Noise Level |
| **Color** | Color Score, Saturation |
| **Exposure** | Exposure Score, Mean Luminance, Histogram Spread, Dynamic Range |
| **Composition** | Composition Score, Power Point Score, Leading Lines, Isolation Bonus, Composition Pattern |

## Gallery Features

### Photo Cards

- Thumbnail with score badge
- Clickable tags for quick filtering
- Person avatars for recognized faces
- Category badge

### Multi-Select

- Click photos to select (Ctrl+click for multiple)
- Copy paths to clipboard
- Clear selection with Escape

### Display Options

- **Hide Blinks** - Filter out photos with detected blinks
- **Best of Burst** - Show only top-scored photo from each burst
- **Infinite Scroll** - Photos load as you scroll

### Similar Photos

Click the "Similar" button on any photo to open the similar photos panel. Results use a two-pass algorithm:
- **Pass 1** - Perceptual hash (pHash) hamming distance for fast visual similarity
- **Pass 2** - CLIP embedding cosine similarity for semantic matching
- Blended score: `pHash × 0.7 + CLIP × 0.3`

Use the **similarity threshold slider** (0–90%) to control how strict the matching is. The panel supports infinite scroll for large result sets.

### Filter Chips

Active filters shown as removable chips with counts at top of gallery.

## Person Management

### Person Filter

Dropdown shows persons with face thumbnails. Click to filter gallery.

### Person Gallery

Click person name to view all their photos at `/persons/<id>`.

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
| `Enter` | Submit filename search |

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
| `GET /api/similar_photos/{path}` | Similar photos by embedding |
| `GET /api/config` | Viewer configuration |

### Authentication

| Endpoint | Description |
|----------|-------------|
| `POST /api/auth/login` | Authenticate and receive token |
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

### Persons

| Endpoint | Description |
|----------|-------------|
| `GET /api/persons` | List all persons |
| `POST /api/persons/{id}/rename` | Rename a person |
| `POST /api/persons/{id}/merge` | Merge person into another |
| `DELETE /api/persons/{id}` | Delete a person |

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
| Port 5000 in use | Change port in `viewer.py` or kill the conflicting process |
