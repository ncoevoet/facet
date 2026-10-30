# Scoring System

> 🌐 **English** · [Français](fr/SCORING.md) · [Deutsch](de/SCORING.md) · [Italiano](it/SCORING.md) · [Español](es/SCORING.md) · [Português](pt/SCORING.md) · [简体中文](zh/SCORING.md)

Photos are classified into a category, then scored with that category's weights.

Missing subject_sharpness, subject_prominence, subject_placement, bg_separation and face_quality_iqa values (absent or NULL) are excluded from weighted scoring. Their weight is redistributed over available metrics only when positive; zero remains a valid value. If all weighted inputs are missing, the neutral input is 5.0. Licence exclusions still apply first. Shipped weights are unchanged. Weight tuning and pairwise/distribution evaluation are follow-ups requiring representative comparison data; no weight benefit is claimed here. To populate saliency, run `--recompute-saliency`, then `--recompute-average`.

## How Scoring Works

1. **Category Detection** - Photo analyzed for content (faces, tags, EXIF data)
2. **Filter Evaluation** - Categories tried in priority order until one matches (a [scoring context](#scoring-contexts) can change this per album or photo)
3. **Weight Application** - Category-specific weights applied to metrics
4. **Modifier Application** - Bonuses, penalties, and behavior flags applied
5. **Final Score** - Weighted sum clamped to 0-10 range

## Categories

`scoring_config.json` defines 34 categories (33 named plus `default`), tried in ascending priority order until one matches. Lower priority wins. The full list is in the `categories` array; the main ones:

| Priority | Category | Detection Method |
|----------|----------|------------------|
| 8 | `art` | Tags: painting, statue, drawing, cartoon, anime |
| 10 | `astro` | Tags: aurora, astrophotography, stars, milky way, AND mean luminance ≤ 0.30 |
| 15 | `concert` | Tags: concert |
| 35 | `group_portrait` | Face ratio ≥ 5% AND is_group_portrait |
| 42 | `silhouette` | Has face AND `is_silhouette` (the largest face is dark against a brighter surround) |
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

On the CLIP-tagging profiles (`legacy`/`8gb`, and `16gb`/`24gb` when their VLM tagger does not run), a scan tags each photo before computing its category, so the stored category uses the tags. A single `--pass NAME` run does not tag.

**Silhouette.** `is_silhouette` comes from a face-aware pixel rule (see [Boolean Filters](#boolean-filters)), not from a tag.

- When `exposure.silhouette_detection` is `true` (the default), a silhouette's aggregate skips the clipping penalty.
- A scan stores `exposure_score` with the clipping penalty. `--recompute-average` recomputes it without the penalty for every photo flagged `is_silhouette`, whatever `exposure.silhouette_detection` says.
- To re-derive the flags of an existing library, run `python facet.py --recompute-silhouette`, then `--recompute-average` twice (see [COMMANDS.md](COMMANDS.md)).

**Astro.** A photo needs an astro tag *and* a mean luminance of at most 0.30 (`luminance_max`). A bright scene tagged `aurora` or `stars` is not astro, and a photo with no stored luminance never matches. If your `scoring_config.json` has its own `categories` array, add `"luminance_max": 0.30` to `astro.filters` yourself; `python facet.py --doctor` tells you when it is missing.

## Scoring Contexts

A **scoring context** changes the category order for some photos without touching the global priorities. It promotes a few categories to the front and excludes others. `default` (empty `promote`/`excluded`) changes nothing, and photos use it unless you assign another.

**Effective order** = `promote` (in the order given) → the global priority order without the promoted and excluded names → `default` last. A name in both `promote` and `excluded` is dropped: `excluded` wins.

Shipped presets, editable in the viewer's **Scoring Context** tab or in the JSON (field reference: [Scoring Contexts](CONFIGURATION.md#scoring-contexts)):

| Context | Promotes | Excludes |
|---------|----------|----------|
| `default` | — | — |
| `action_stage` | `sports`, `concert`, `candid` | `silhouette` |
| `party_event` | `group_portrait`, `candid`, `food` | — |
| `portrait_session` | `portrait`, `portrait_bw`, `fashion` | — |
| `wildlife` | `wildlife` | — |
| `landscape` | `landscape`, `golden_hour`, `blue_hour` | — |
| `motorsport` | `sports`, `vehicle` | `silhouette` |

You edit only the promoted list (edition mode; drag, or move up/down) and the exclusions. The other categories always keep the global order, so a new category is never missing from a context. Validation rules: [Editing a context](CONFIGURATION.md#editing-a-context).

**Assigning a context:**

- **Per album.** Applies to every photo that is in the album now. It is a one-time snapshot: photos added to a smart album later do not get it. See [Assigning a context](CONFIGURATION.md#scoring-contexts).
- **Per photo.** A sticky category override for a single photo.

Both survive rescans and can be cleared separately.

**Neither affects already-scored photos until you recompute:** run `python facet.py --recompute-average`, or recompute from the viewer (see [Changing priorities requires a recompute](CONFIGURATION.md#reordering-the-global-priority)). With `normalization.per_category` enabled, run it twice (see [Normalization](CONFIGURATION.md#normalization)).

### The missing-EXIF trap

Reordering only changes which category is *tried first*. It cannot make a category's filters match. A numeric range filter fails when the photo's value is missing or unreadable, exactly as if it were out of range.

Example: `sports` (priority 71) has `shutter_speed_max: 0.02`. A dance frame shot slower than 1/50s, or with no readable shutter speed, fails that filter even when `action_stage` promotes `sports` to the front. It falls through to the next match, typically `fashion` (priority 43, tagged `fashion`, has a face) or `silhouette` (priority 42, backlit with a face).

**When a photo lands in an unexpected category, check this first:** can the target category's numeric filters match the photo's stored EXIF, not just its tags?

### The missing-tag trap

`required_tags` fails the same way: a filter cannot match a tag missing from the vocabulary. The `required_tags` of `sports` are `sports`, `motion`, `athlete`, `competition`, `action_sport` and `dance`.

`sports.tags.dance` carries 11 CLIP prompts (`dance performance`, `dancer on stage`, `ballet dancer`, `contemporary dance`, `ballroom dancing`, `latin dance`, `hip hop dance`, `dance competition`, `dance troupe performing`, `dancer mid leap`, `dancer in motion`), and `dance` is in `sports.filters.required_tags`. A tagged dance photo can reach `sports`, but a slow-shutter or EXIF-less one still fails `shutter_speed_max: 0.02`.

**Existing photos keep their tags.** A vocabulary change only affects new tagging; run `python facet.py --recompute-tags` to apply it to the library.

### Reordering global priority

You can reorder the global priority in the viewer (edition mode). The reorder swaps the existing priority numbers between categories instead of renumbering, so the numbers in the table above stay meaningful. `default` (priority 999) always stays last. Each write saves a timestamped `.backup.<timestamp>` copy of `scoring_config.json` first.

Reordering does not change any photo's stored `category`: run a recompute afterwards.

**Known limitation:** the gallery's type dropdown keeps its old order until the viewer restarts. Matching and filtering use the new order at once.

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
| `is_silhouette` | The largest face is dark against a bright surround (see below). A photo without a face is never a silhouette |
| `is_group_portrait` | face_count >= `min_faces_for_group` (configurable, default: 4) |

**`is_silhouette` rule.** The mean brightness (luma, 0-1) of the central 60% of the face box is below 0.12, and the band around the box (from 0.2 to 0.75 of the box's size outward on each side, clipped to the frame) is brighter by more than 0.20. The CLIP `silhouette` tag and the whole-frame histogram do not set it.

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
| `quality_percent` | Legacy quality | Added to `aesthetic_percent` before scoring (no separate signal) | — |
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

**`quality_percent` counts toward `aesthetic`.** The quality metric has no score of its own, so a category's `quality_percent` is redistributed into `aesthetic`: it is added to `aesthetic_percent` before scoring, and the weights still sum to 100. Earlier versions lost that share from the aggregate; run `--recompute-average` once after upgrading to get it back. Categories do not change.

## Modifiers

Adjust scoring behavior per category:

| Modifier | Type | Description |
|----------|------|-------------|
| `bonus` | float | Added to final score (e.g., 0.5) |
| `noise_tolerance_multiplier` | float | Scale noise penalty (0.5 = half) |
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

**No subject, no number.** When no subject is found, `subject_sharpness`, `subject_placement` and `bg_separation` are stored as NULL (as is `power_point_score` when there is no subject box), `subject_prominence` is 0.0 and `subject_bbox` is NULL.

- Gallery range filters skip a NULL (`min_subject_sharpness=0` does not return a photo without a subject). Statistics leave it out of averages, and the UI shows it as absent.
- The aggregate scores a NULL as a neutral 5.0, so no aggregate moves.
- Earlier versions stored a neutral 5.0. Existing rows keep it until `--recompute-saliency` and `--recompute-composition-cpu` rewrite them.

**When saliency fails**, nothing is written; Facet never stores a neutral number for a failed result. A never-scored photo keeps NULL in all five saliency columns (`subject_sharpness`, `subject_prominence`, `subject_placement`, `bg_separation`, `subject_bbox`) and scores neutral (5.0), like a photo scanned before saliency existed. Retry and batch-size rules: [Subject Saliency](COMMANDS.md#subject-saliency).

## Supplementary IQA Dimensions

Three additional quality models:

| Weight Key | Model | Description |
|-----------|-------|-------------|
| `aesthetic_iaa_percent` | TOPIQ IAA | AVA-trained aesthetic merit, distinct from the technical-quality aesthetic score. Best for art/creative categories. |
| `face_quality_iqa_percent` | TOPIQ NR-Face | Face-region quality assessment. Best for portrait categories. |
| `liqe_percent` | LIQE | Quality score plus a distortion diagnosis (motion blur, overexposure, noise). |

These models run as part of the default scoring pipeline on every profile, including the CPU `legacy` profile (slower there), and share VRAM with TOPIQ on a GPU. Add their weight keys to any category where the assessment is useful.

**When a supplementary model cannot score a photo**, it stores NULL in that model's column (`face_quality_iqa`, `liqe_score`, `aesthetic_iaa`, `aesthetic_v25`) instead of a neutral 5.0. This happens when TOPIQ NR-Face finds no face, or LIQE gets a short side under 224 px; Aesthetic V2.5, when enabled, can fail on any image. A CPU memory error is not retried at a smaller batch size.

- **Aggregate:** a NULL scores neutral (5.0), so scores, categories and rankings do not move.
- **Gallery:** a range filter on Aesthetic (IAA), Face Quality (IQA), LIQE or Aesthetic V2.5 does not match an unscored photo (`min_face_quality_iqa=0` skips a faceless photo). An ascending sort on those, Q-ReAlign or DeQA puts unscored photos last, in the gallery and in albums.
- **Old neutral 5.0 values** stay until `--repair-neutral-iqa` clears them; then run `--recompute-iqa` and `--recompute-average`, or rescan with `--force`.
- **Primary model failure** (TOPIQ on `16gb` and `24gb`): the photo is recorded as failed instead of saved with a neutral 5.0. A new photo is picked up by the next scan; a stored one keeps its row and is retried by `--retry-failed all` (a bare `--retry-failed` covers only the latest run with failures) or another `--force` rescan.

Retry rules for each command: [Supplementary Quality Models](COMMANDS.md#supplementary-quality-models).

### Supplementary signals (not in default aggregate)

| Column | Source | Description |
|--------|--------|-------------|
| `aesthetic_clip` | `analyzers/aesthetic_clip.py` + cached CLIP/SigLIP embedding | Free aesthetic score (0-10) from cached embeddings; **not** in the default `aggregate` |

`aesthetic_clip` projects each image embedding onto an "aesthetic axis" built from text prompts, so it needs no extra image inference.

- Fill it with `python scripts/compute_aesthetic_clip.py --db <path>`.
- Benchmark with `python scripts/benchmark_aesthetic.py --db <path> --ava AVA.txt --photo-dir <dir>`.
- AVA SRCC ≈ 0.52 on the 500-photo `ava_test/` set (vs 0.94 for `aesthetic_iaa`). Use it as a cheap pre-filter or when TOPIQ-IAA is unavailable.

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

All profiles, including the CPU `legacy` profile, additionally run supplementary PyIQA models (TOPIQ IAA, TOPIQ NR-Face, LIQE) and optionally BiRefNet_dynamic for subject saliency.

Run `--compute-recommendations` after switching profiles to analyze score distributions.

## Weight Tuning Workflow

### Option A: Via Viewer (Recommended)

1. Open `/stats` → **Categories** tab → **Weights** sub-tab
2. Unlock edition mode
3. Select a category from the editor dropdown
4. Adjust sliders — the live **Score Distribution Preview** shows estimated impact
5. Click **Save** then **Recompute Scores** to apply

The viewer runs `--recompute-category` under the hood, updating only photos in that category.

An MCP assistant can read these weights and dry-run a change without touching anything: `explain_score` (why a photo scored what it did), `category_weights` and `preview_weights` (an approximate preview with rank changes). See [Scoring and weights](AGENTS.md#scoring-and-weights).

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
- Keyboard: ← (left wins), → (right wins), T (tie), S (skip). The on-screen buttons are labelled **A** / **B**.
- Progress bar shows comparisons toward 50 minimum

### Comparison Sources

Each comparison has a `source`, which the optimizer weights by reliability:

- `vote` — explicit A/B votes from the comparison interface
- `culling` — from burst/similar culling decisions: each rejected photo is paired
  with up to two kept photos from its group (at most 12 pairs per group). Kept
  photos win. Explicit votes on the same pair are never overwritten.
- `rating` — synthetic pairs from star ratings and favorites

So reviewing burst groups in the viewer also grows the training set.

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

Besides A/B votes, two label streams feed the optimizer:

1. **Culling decisions** are captured on every burst/similar confirm (`source='culling'`).
2. **Star ratings, favorites and rejections** become synthetic pairs with
   `python facet.py --sync-label-comparisons` (`source='rating'`). Re-running
   re-syncs from the current labels, so retracted ratings disappear.

**How the fit works.** The optimizer finds the weights that best predict each comparison's winner (a Bradley-Terry model).

- Sources count by reliability: vote 1.0, rating 0.7, culling 0.5.
- A **tie** counts as half a win and half a loss.
- The fit is **anchored to your current weights**: with few comparisons it stays close to them.
- It uses the same 0-10 metrics as the aggregate (including `liqe`, `aesthetic_iaa`, `face_quality_iqa` and subject saliency), with eye sharpness, technical sharpness and colour normalised by the percentiles the last `--recompute-average` saved.
- `quality_percent` is folded into `aesthetic`, as the scorer does; applying writes `quality_percent: 0`.

**Weights are applied only if they generalize.** The decision uses held-out comparisons: 5-fold cross-validation with **photo-grouped folds** (no photo is in both training and held-out pairs).

- A **one-sided exact McNemar test** checks whether the new weights win significantly more of the pairs where the two weight sets disagree.
- The weights are applied only when `p < 0.05` **and** the held-out gain is at least 2 percentage points. Otherwise the run logs the numbers and writes nothing.
- Pass `--optimize-force` to apply anyway. If the test cannot run (too few independent photo groups), nothing is applied unless forced.
- Each category needs at least 30 **decisive** comparisons (one photo won) **in that category**. Ties and other categories do not count.

Example log:

```
Held-out accuracy:      69.2% +/- 4.0 (5-fold, photo-grouped) - the honest estimate
Held-out gain:          +8.5 pp over the current weights on the same 389 pairs
McNemar (one-sided):    p = 0.0006 (only the fit right: 66, only the current weights right: 33)
NOT applying: the held-out gate needs p < 0.05 and a gain of at least 2.0 pp. ...   (logged when the gate fails)
```

**Applying keeps the category's level.** `--optimize-weights` changes how a category's photos rank among themselves, not against other categories. It moves `modifiers.bonus` to cancel the category's mean score shift.

- The bonus stays within [-5, 5]; the log says when that limit applies.
- A category with no entry in `categories` (`others`) has no bonus and is not re-centred.
- Restoring a weight snapshot restores weights **and** bonus. Older snapshots, those from `calibrate.py` and those for `others` leave the bonus alone.
- The viewer's **Apply** button and hand edits in the Weights tab do not re-centre the bonus; only `--optimize-weights` does.

**After upgrading, retrain the personal ranker and the keeper head (`--train-ranker`, `--train-keeper`), then run `--recompute-average`.** They now read percentile-normalised eye sharpness, technical sharpness and colour, and an older saved model cannot detect the change.

Recommended cadence:

```bash
python facet.py --mine-insights          # what signal exists, drift, health
python facet.py --sync-label-comparisons # refresh rating-derived pairs
python facet.py --optimize-weights       # learn weights from all sources
python facet.py --recompute-average      # apply + persist percentile snapshot
```

### In-UI Weight Tuning

During comparison, the Weight Preview panel shows score changes as you move the sliders, and **Suggest Weights** proposes optimized values. Saving and recomputing work as in [Option A: Via Viewer](#option-a-via-viewer-recommended).

**Suggest Weights** shows two figures, in the Weight Suggestions tab and the A/B Compare sidebar:

- `accuracy_before`: how often the current weights predict the winner of this category's labelled pairs.
- `accuracy_after`: the same for the suggested weights. It is measured on the pairs it was fit on, so it is optimistic.

**Apply** is offered only when the same held-out McNemar test as the CLI passes (`suggest_changes` is true). The cross-validation runs only when the optimistic gain reaches 2 percentage points (`?use_cv=true` always runs it). The viewer needs `min_comparisons_for_optimization` (default 50) decisive comparisons in the category, where the CLI needs 30. Below that it reports "Need at least N decisive comparisons (have K)".

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
