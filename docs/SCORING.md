# Scoring System

> 🌐 **English** · [Français](fr/SCORING.md) · [Deutsch](de/SCORING.md) · [Italiano](it/SCORING.md) · [Español](es/SCORING.md) · [Português](pt/SCORING.md)

Photos are classified into a category, then scored with that category's weights.

## How Scoring Works

1. **Category Detection** - Photo analyzed for content (faces, tags, EXIF data)
2. **Filter Evaluation** - Categories evaluated in priority order until one matches
3. **Weight Application** - Category-specific weights applied to metrics
4. **Modifier Application** - Bonuses, penalties, and behavior flags applied
5. **Final Score** - Weighted sum clamped to 0-10 range

## Categories

`scoring_config.json` defines 34 categories (33 named plus `default`), evaluated in ascending priority order until one matches. Lower priority wins. The full list lives in the `categories` array; the main ones:

| Priority | Category | Detection Method |
|----------|----------|------------------|
| 8 | `art` | Tags: painting, statue, drawing, cartoon, anime |
| 10 | `astro` | Tags: aurora, astrophotography, stars, milky way |
| 15 | `concert` | Tags: concert |
| 35 | `group_portrait` | Face ratio ≥ 5% AND is_group_portrait |
| 42 | `silhouette` | Has face AND is_silhouette |
| 45 | `portrait` | Face ratio ≥ 5%, not silhouette/group/mono |
| 46 | `portrait_bw` | Monochrome portrait (face ≥ 5%) |
| 55 | `macro` | Tags: macro, insect, butterfly, dewdrop, ... |
| 65 | `wildlife` | Tags: animal, bird, marine, reptile, primate |
| 80 | `long_exposure` | Shutter 1-10 seconds |
| 85 | `night` | Luminance < 0.15 |
| 88 | `monochrome` | is_monochrome (saturation < 5%) |
| 95 | `street` | Tags: street, urban_culture |
| 96 | `human_others` | Has face AND face ratio < 5% |
| 100 | `landscape` | Tags: landscape, mountain, beach, forest, ... |
| 999 | `default` | Fallback (no filter) |

Other tag-based categories include `aerial`, `food`, `sports`, `vehicle`, `travel`, `fashion`, `candid`, `product`, `architecture`, `urban`, `golden_hour`, `blue_hour`, `cinematic`, `vintage`, `abstract`, `minimalist`, `dramatic`, and `weather`.

## Category Definition

Each category in `scoring_config.json` has these components:

```json
{
  "name": "portrait",
  "priority": 45,
  "filters": {
    "face_ratio_min": 0.05,
    "has_face": true,
    "is_silhouette": false,
    "is_group_portrait": false,
    "is_monochrome": false
  },
  "weights": {
    "aesthetic_percent": 32,
    "eye_sharpness_percent": 16,
    "face_quality_percent": 14,
    "composition_percent": 12,
    "liqe_percent": 8,
    "exposure_percent": 4,
    "tech_sharpness_percent": 4,
    "color_percent": 4,
    "contrast_percent": 4,
    "aesthetic_iaa_percent": 2
  },
  "modifiers": {
    "bonus": 0.419,
    "_apply_blink_penalty": true,
    "noise_tolerance_multiplier": 0.006,
    "_clipping_multiplier": 0.5
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

All weights use the `_percent` suffix. They are normalized by `get_weights()`, so totals need not equal exactly 100 — but keeping them at 100 keeps scores on the 0-10 scale.

| Key | Metric | Source | Best For |
|-----|--------|--------|----------|
| `aesthetic_percent` | Visual appeal | TOPIQ or CLIP+MLP | All |
| `quality_percent` | Legacy quality | Redistributed into `aesthetic` (no separate signal) | — |
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
| `aesthetic_iaa_percent` | Artistic aesthetic merit | TOPIQ IAA (AVA-trained) | Art, creative |
| `face_quality_iqa_percent` | Face quality (IQA) | TOPIQ NR-Face | Portraits |
| `liqe_percent` | LIQE quality score | LIQE | Diagnostics |
| `subject_sharpness_percent` | Subject region sharpness | BiRefNet + Laplacian | Portraits, wildlife |
| `subject_prominence_percent` | Subject area ratio | BiRefNet | Macro, wildlife |
| `subject_placement_percent` | Subject rule-of-thirds | BiRefNet | All |
| `bg_separation_percent` | Background separation | BiRefNet | Portraits, macro |

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

## Subject Saliency Dimensions

Four dimensions derived from BiRefNet subject segmentation:

| Weight Key | Metric | Description |
|-----------|--------|-------------|
| `subject_sharpness_percent` | Subject sharpness | Focus quality of the subject region vs the background. High = sharp subject, soft background. |
| `subject_prominence_percent` | Subject prominence | Subject area as a fraction of the frame. High for macro and tightly-framed subjects, low for wide scenes. |
| `subject_placement_percent` | Subject placement | Rule-of-thirds score for the subject's center of mass. |
| `bg_separation_percent` | Background separation | Edge gradient difference at the subject boundary (bokeh quality). |

Use `subject_sharpness_percent` and `bg_separation_percent` for portrait/wildlife; `subject_prominence_percent` for macro.

## Supplementary IQA Dimensions

Three additional quality models:

| Weight Key | Model | Description |
|-----------|-------|-------------|
| `aesthetic_iaa_percent` | TOPIQ IAA | AVA-trained aesthetic merit, distinct from the technical-quality aesthetic score. Best for art/creative categories. |
| `face_quality_iqa_percent` | TOPIQ NR-Face | Face-region quality assessment. Best for portrait categories. |
| `liqe_percent` | LIQE | Quality score plus a distortion diagnosis (motion blur, overexposure, noise). |

These models run as part of the default scoring pipeline on all GPU profiles (8gb/16gb/24gb) and share VRAM with TOPIQ; the CPU legacy profile skips them. Add their weight keys to any category where the assessment is useful.

### Supplementary signals (not in default aggregate)

| Column | Source | Description |
|--------|--------|-------------|
| `aesthetic_clip` | `analyzers/aesthetic_clip.py` + cached CLIP/SigLIP embedding | A free supplementary aesthetic score (0-10) derived from cached image embeddings by projecting onto an "aesthetic axis" built from positive/negative text prompts. Zero extra image inference at scan time. **Not** part of the default `aggregate`. Populate with `python scripts/compute_aesthetic_clip.py --db <path>`. Benchmark with `python scripts/benchmark_aesthetic.py --db <path> --ava AVA.txt --photo-dir <dir>`. AVA SRCC ≈ 0.52 on the 500-photo `ava_test/` set (vs 0.94 for `aesthetic_iaa`) — useful as a cheap pre-filter or when TOPIQ-IAA is unavailable. |

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
- Without face: `face_quality_percent` redistributed evenly (half each) to `aesthetic` and `composition` (with default weights: aesthetic 0.40, composition 0.30)

## VRAM Profile Considerations

Default weights are optimized for **TOPIQ** (0.93 SRCC), the aesthetic model for all profiles.

| Profile | Aesthetic Model | Embeddings | Tagger | Recommendations |
|---------|-----------------|-----------|--------|-----------------|
| `24gb` | TOPIQ (0.93 SRCC) | SigLIP 2 NaFlex SO400M | Qwen3.5-4B | Best accuracy, default weights |
| `16gb` | TOPIQ (0.93 SRCC) | SigLIP 2 NaFlex SO400M | Qwen3.5-2B | Default weights |
| `8gb` | CLIP+MLP (0.76 SRCC) | CLIP ViT-L-14 | CLIP similarity | Default weights work well |
| `legacy` | CLIP+MLP on CPU | CLIP ViT-L-14 | CLIP similarity | Default weights, slower |

All GPU profiles (8gb/16gb/24gb) additionally run supplementary PyIQA models (TOPIQ IAA, TOPIQ NR-Face, LIQE) and optionally BiRefNet_dynamic for subject saliency; the CPU legacy profile skips them.

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
python facet.py --compute-recommendations
```

Shows:
- Score distributions per category
- Weight correlation analysis
- Suggested adjustments

#### 2. Adjust Weights

Edit `scoring_config.json` category weights. Ensure they sum to 100.

#### 3. Recompute Scores

```bash
python facet.py --recompute-average               # All categories
python facet.py --recompute-category portrait      # Single category (faster)
```

Uses stored embeddings - no GPU needed.

#### 4. Validate Changes

```bash
python facet.py --compute-recommendations
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
- Keyboard: ← (left wins), → (right wins), T (tie), S (skip). The on-screen buttons are still labelled **A** / **B** (the values submitted), but the keys are ArrowLeft/ArrowRight.
- Progress bar shows comparisons toward 50 minimum

### Comparison Sources

Comparisons carry a `source` marker so the optimizer can weight them by reliability:

- `vote` — explicit A/B votes from the comparison interface
- `culling` — derived automatically from burst/similar culling decisions: each
  rejected photo is paired against up to two kept photos from the same group
  (capped at 12 pairs per group). Kept photos win. Explicit votes on the same
  pair are never overwritten.
- `rating` — synthetic pairs generated from star ratings and favorites

Reviewing burst groups in the viewer therefore grows the training set for
weight optimization without any extra effort.

### Weight Optimization

```bash
# Check comparison stats
python facet.py --comparison-stats

# Optimize weights from comparisons (applied only if it generalizes)
python facet.py --optimize-weights --optimize-category portrait

# Restrict training data to specific sources
python facet.py --optimize-weights --optimize-category portrait --optimize-sources vote,culling

# Apply even if the held-out gate is not met
python facet.py --optimize-weights --optimize-category portrait --optimize-force

# Apply to all photos
python facet.py --recompute-average
```

### Label-to-Weight Pipeline

Beyond explicit A/B votes, two more label streams feed the optimizer:

1. **Culling decisions** are captured automatically on every burst/similar
   confirm (`source='culling'`).
2. **Star ratings, favorites and rejections** are materialized into synthetic
   pairs with `python facet.py --sync-label-comparisons` (`source='rating'`).
   Re-running re-syncs from the current labels, so retracted ratings disappear.

The optimizer weighs each source by reliability (vote 1.0, rating 0.7,
culling 0.5) when maximizing the Bradley-Terry likelihood. It trains on the
exact 0-10 metric vector the scorer uses (including `liqe`, `aesthetic_iaa`,
`face_quality_iqa` and the subject-saliency metrics), so optimized weights map
directly onto production scoring.

Weights are **applied only if they generalize**: the final weights are fit on
all comparisons, but the decision to write them is gated on held-out k-fold
accuracy, not training accuracy. If the held-out gain over the current weights
is below the threshold (default 2 pp) the run reports the numbers and writes
nothing — pass `--optimize-force` to override. Optimization is per-category and
needs labelled comparisons **for that category**; categories with no votes
cannot be tuned from data.

Recommended cadence:

```bash
python facet.py --mine-insights          # what signal exists, drift, health
python facet.py --sync-label-comparisons # refresh rating-derived pairs
python facet.py --optimize-weights       # learn weights from all sources
python facet.py --recompute-average      # apply + persist percentile snapshot
```

### In-UI Weight Tuning

During comparison, the Weight Preview panel lets you adjust sliders for
real-time score changes and click "Suggest Weights" for optimized values.
This is the same in-viewer slider workflow described in
[Option A: Via Viewer](#option-a-via-viewer-recommended) above — see there
for the full save/recompute flow.

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

python facet.py --recompute-category concert
```

Or use the viewer's weight editor at `/stats` → Categories → Weights for live preview and one-click recompute.

### Switch to 8gb Profile

```bash
# Edit: "vram_profile": "8gb"
python facet.py --compute-recommendations  # Analyze
# Reduce aesthetic_percent in categories if needed
python facet.py --recompute-average
```

### Add Underwater Category

1. Add category definition (see above)
2. Run `python facet.py --validate-categories`
3. Run `python facet.py --recompute-average`
