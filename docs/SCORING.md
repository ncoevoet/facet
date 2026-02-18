# Scoring System

Facet uses a category-based scoring system where photos are automatically classified and scored with specialized weights.

## How Scoring Works

1. **Category Detection** - Photo analyzed for content (faces, tags, EXIF data)
2. **Filter Evaluation** - Categories evaluated in priority order until one matches
3. **Weight Application** - Category-specific weights applied to metrics
4. **Modifier Application** - Bonuses, penalties, and behavior flags applied
5. **Final Score** - Weighted sum clamped to 0-10 range

## Categories

Facet includes 17 built-in categories evaluated in priority order:

| Priority | Category | Detection Method |
|----------|----------|------------------|
| 5 | `art` | Tags: painting, statue, drawing, cartoon, anime |
| 10 | `astro` | Shutter > 10s AND luminance < 0.15 |
| 15 | `concert` | Tags: concert |
| 25 | `street` | Tags: street AND has face |
| 30 | `silhouette` | Has face AND is_silhouette |
| 35 | `group_portrait` | Face ratio > 5% AND multiple faces |
| 45 | `portrait` | Face ratio > 25%, not silhouette/group/mono |
| 50 | `human_others` | Has face AND face ratio < 5% |
| 55 | `macro` | Tags: macro, insect, butterfly, flower |
| 60 | `aerial` | Tags: aerial |
| 65 | `wildlife` | Tags: animal |
| 70 | `food` | Tags: food |
| 75 | `architecture` | Tags: architecture |
| 80 | `long_exposure` | Shutter 1-10 seconds |
| 85 | `night` | Luminance < 0.15 |
| 88 | `monochrome` | Saturation < 5% |
| 100 | `others` | Tags: landscape, mountain, beach, etc. (fallback) |

## Category Definition

Each category in `scoring_config.json` has these components:

```json
{
  "name": "portrait",
  "priority": 45,
  "filters": {
    "face_ratio_min": 0.25,
    "has_face": true,
    "is_silhouette": false,
    "is_group_portrait": false,
    "is_monochrome": false
  },
  "weights": {
    "aesthetic_percent": 61,
    "face_quality_percent": 3,
    "composition_percent": 7,
    "dynamic_range_percent": 6,
    "isolation_percent": 12,
    "leading_lines_percent": 4,
    "power_point_percent": 6,
    "saturation_percent": 1
  },
  "modifiers": {
    "bonus": 0.5,
    "_apply_blink_penalty": true
  },
  "tags": {}
}
```

## Filters Reference

### Numeric Range Filters

| Filter | Field | Description |
|--------|-------|-------------|
| `face_ratio_min` / `face_ratio_max` | `face_ratio` | Face area as fraction (0.0-1.0) |
| `face_count_min` / `face_count_max` | `face_count` | Number of faces |
| `iso_min` / `iso_max` | `ISO` | Camera ISO |
| `shutter_speed_min` / `shutter_speed_max` | `shutter_speed` | Exposure time (seconds) |
| `luminance_min` / `luminance_max` | `mean_luminance` | Brightness (0.0-1.0) |
| `focal_length_min` / `focal_length_max` | `focal_length` | Focal length (mm) |
| `f_stop_min` / `f_stop_max` | `f_stop` | Aperture f-number |

### Boolean Filters

| Filter | Description |
|--------|-------------|
| `has_face` | At least one face detected |
| `is_monochrome` | Saturation < 5% |
| `is_silhouette` | Backlit with heavy shadows/highlights |
| `is_group_portrait` | face_count >= `min_faces_for_group` (configurable, default: 4) |

### Tag Filters

| Filter | Description |
|--------|-------------|
| `required_tags` | List of tags photo must have |
| `excluded_tags` | List of tags photo must NOT have |
| `tag_match_mode` | `"any"` (default) or `"all"` |

## Weight Keys

All weights use `_percent` suffix and must sum to 100 per category.

| Key | Metric | Source | Best For |
|-----|--------|--------|----------|
| `aesthetic_percent` | Visual appeal | TOPIQ or CLIP+MLP | All |
| `face_quality_percent` | Face clarity | InsightFace | Portraits |
| `eye_sharpness_percent` | Eye sharpness | InsightFace landmarks | Portraits |
| `tech_sharpness_percent` | Overall sharpness | Laplacian variance | Landscapes |
| `composition_percent` | Composition | SAMP-Net or rule-based | All |
| `exposure_percent` | Exposure balance | Histogram analysis | All |
| `color_percent` | Color harmony | HSV analysis | Color photos |
| `contrast_percent` | Tonal contrast | Histogram spread | B&W |
| `dynamic_range_percent` | Tonal range | Histogram analysis | HDR, landscapes |
| `isolation_percent` | Subject separation | Face vs background | Portraits, wildlife |
| `leading_lines_percent` | Leading lines | Edge detection | Architecture |
| `power_point_percent` | Rule-of-thirds | Subject placement | All |
| `saturation_percent` | Color saturation | HSV analysis | Vibrant photos |
| `noise_percent` | Noise level | Noise estimation | Low-light |
| `face_sharpness_percent` | Face region sharpness | Face analysis | Portraits |

## Modifiers

Adjust scoring behavior per category:

| Modifier | Type | Description |
|----------|------|-------------|
| `bonus` | float | Added to final score (e.g., 0.5) |
| `noise_tolerance_multiplier` | float | Scale noise penalty (0.5 = half) |
| `iso_tolerance_multiplier` | float | Scale ISO penalty |
| `min_saturation_bonus` | float | Bonus for high saturation |
| `contrast_bonus` | float | Bonus for high contrast |
| `_skip_clipping_penalty` | bool | Skip exposure clipping penalty |
| `_skip_oversaturation_penalty` | bool | Skip oversaturation penalty |
| `_clipping_multiplier` | float | Scale clipping penalty |
| `_apply_blink_penalty` | bool | Apply blink detection penalty |

## Category Tags (CLIP Vocabulary)

Tags trigger tag-based categories and are matched using CLIP similarity:

```json
{
  "tags": {
    "landscape": ["landscape", "scenic view", "nature scene"],
    "mountain": ["mountain", "alpine", "peaks"],
    "beach": ["beach", "ocean", "seaside", "coastal"]
  }
}
```

Each key is the canonical tag name, and the array contains synonyms for CLIP matching.

## Top Picks Scoring

The viewer's "Top Picks" filter uses a custom weighted score:

```json
"top_picks_weights": {
  "aggregate_percent": 30,
  "aesthetic_percent": 28,
  "composition_percent": 18,
  "face_quality_percent": 24
}
```

**Score computation:**
- With face (face_ratio ≥ 20%): All four metrics contribute
- Without face: `face_quality_percent` redistributed to `aesthetic` and `composition`

## VRAM Profile Considerations

Default weights are optimized for **TOPIQ** (0.93 SRCC), the aesthetic model for all profiles.

| Profile | Aesthetic Model | Recommendations |
|---------|-----------------|-----------------|
| `16gb` | TOPIQ (0.93 SRCC) | Default weights |
| `8gb` | TOPIQ (0.93 SRCC) | Default weights work well |
| `legacy` | TOPIQ on CPU | Default weights work well, slower |

Run `--compute-recommendations` after switching profiles to analyze score distributions.

## Weight Tuning Workflow

### Option A: Via Viewer (Recommended)

1. Open `/stats` → **Categories** tab → **Weights** sub-tab
2. Unlock edition mode
3. Select a category from the editor dropdown
4. Adjust sliders — the live **Score Distribution Preview** shows estimated impact
5. Click **Save** then **Recompute Scores** to apply

The viewer runs `--recompute-category` under the hood, updating only photos in that category.

### Option B: Via CLI

#### 1. Analyze Current Scores

```bash
python photos.py --compute-recommendations
```

Shows:
- Score distributions per category
- Weight correlation analysis
- Suggested adjustments

#### 2. Adjust Weights

Edit `scoring_config.json` category weights. Ensure they sum to 100.

#### 3. Recompute Scores

```bash
python photos.py --recompute-average               # All categories
python photos.py --recompute-category portrait      # Single category (faster)
```

Uses stored embeddings - no GPU needed.

#### 4. Validate Changes

```bash
python photos.py --compute-recommendations
```

Compare distributions before/after.

## Pairwise Comparison Mode

Train weights by comparing photo pairs:

### Setup

1. Set a non-empty `edition_password` in config: `"viewer": { "edition_password": "your-password" }`
2. Start viewer: `python viewer.py`
3. Click "Compare" button

### Comparison Interface

- Side-by-side photos
- Keyboard: A (left wins), B (right wins), T (tie), S (skip)
- Progress bar shows comparisons toward 50 minimum

### Weight Optimization

```bash
# Check comparison stats
python photos.py --comparison-stats

# Optimize weights from comparisons
python photos.py --optimize-weights

# Apply to all photos
python photos.py --recompute-average
```

### In-UI Weight Tuning

1. Open Weight Preview panel during comparison
2. Adjust sliders to see real-time score changes
3. Click "Suggest Weights" for optimized values
4. Manually update config

## Adding Custom Categories

```json
{
  "name": "underwater",
  "priority": 62,
  "filters": {
    "required_tags": ["underwater"],
    "tag_match_mode": "any"
  },
  "weights": {
    "aesthetic_percent": 40,
    "color_percent": 25,
    "composition_percent": 20,
    "exposure_percent": 15
  },
  "modifiers": {
    "noise_tolerance_multiplier": 0.3,
    "bonus": 0.5
  },
  "tags": {
    "underwater": ["underwater", "scuba", "diving", "ocean"],
    "fish": ["fish", "coral", "reef"]
  }
}
```

Add to the `categories` array in `scoring_config.json`, then run `--recompute-average` (or `--recompute-category underwater` for just the new category).

## Workflow Examples

### Tune Concert Category

```bash
# Edit scoring_config.json:
# Find "concert" category, adjust:
#   "noise_tolerance_multiplier": 0.05
#   "exposure_percent": 5

python photos.py --recompute-category concert
```

Or use the viewer's weight editor at `/stats` → Categories → Weights for live preview and one-click recompute.

### Switch to 8gb Profile

```bash
# Edit: "vram_profile": "8gb"
python photos.py --compute-recommendations  # Analyze
# Reduce aesthetic_percent in categories if needed
python photos.py --recompute-average
```

### Add Underwater Category

1. Add category definition (see above)
2. Run `python photos.py --validate-categories`
3. Run `python photos.py --recompute-average`
