#!/usr/bin/env python3
"""
calibrate.py — AVA-backed weight calibration for Facet

Evaluates Facet's scoring correlation with AVA MOS (mean opinion score),
then runs a gradient-free optimizer to find better per-category weight vectors.

Extended modes use AVA semantic tags (columns 13-14) to validate category
detection, analyze filter thresholds, and optimize scoring modifiers.

Usage:
    python facet.py /path/to/ava_images/  # Score AVA photos first
    python calibrate.py \
        --db photo_scores_pro.db \
        --ava-annotations /path/to/AVA.txt \
        [--categories portrait,landscape,default] \
        [--apply]

    # Extended calibration with AVA semantic tags
    python calibrate.py --db photo_scores_pro.db --ava-annotations AVA.txt --ava-tags
    python calibrate.py --db photo_scores_pro.db --ava-annotations AVA.txt --ava-tags-only
    python calibrate.py --db photo_scores_pro.db --ava-annotations AVA.txt --ava-tags --apply --apply-filters
"""

import argparse
import csv
import json
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime

import numpy as np
from scipy.optimize import differential_evolution, minimize
from scipy.stats import pearsonr, spearmanr

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Metrics available for optimization (map from DB column → weight key in config)
# DB column name → config weight key (without _percent suffix)
METRIC_COLUMNS = {
    'aesthetic': 'aesthetic',
    'comp_score': 'composition',
    'face_quality': 'face_quality',
    'tech_sharpness': 'tech_sharpness',
    'exposure_score': 'exposure',
    'color_score': 'color',
    'contrast_score': 'contrast',
    'leading_lines_score': 'leading_lines',
    'aesthetic_iaa': 'aesthetic_iaa',
    'liqe_score': 'liqe',
}

# Additional DB columns needed for modifier optimization and filter analysis
EXTRA_COLUMNS = [
    'noise_sigma', 'shadow_clipped', 'highlight_clipped',
    'histogram_bimodality', 'mean_saturation', 'is_blink',
    'is_monochrome', 'is_silhouette', 'face_ratio', 'face_count',
    'ISO', 'shutter_speed', 'tags', 'luminance',
]

MIN_PHOTOS_FOR_CATEGORY = 100
MIN_PHOTOS_FOR_BASELINE = 10
MIN_MISCLASSIFIED_FOR_ANALYSIS = 20

SCORING_CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'scoring_config.json')

# ---------------------------------------------------------------------------
# AVA Semantic Tag Constants
# ---------------------------------------------------------------------------

# All 66 AVA semantic tag IDs → label strings
AVA_TAG_NAMES = {
    1: 'Abstract', 2: 'Cityscape', 3: 'Fashion', 4: 'Family',
    5: 'Humorous', 6: 'Interior', 7: 'Sky', 8: 'Snapshot',
    9: 'Sports', 10: 'Urban', 11: 'Vintage', 12: 'Emotive',
    13: 'Performance', 14: 'Landscape', 15: 'Nature', 16: 'Candid',
    17: 'Portraiture', 18: 'Still Life', 19: 'Animals', 20: 'Architecture',
    21: 'Black and White', 22: 'Macro', 23: 'Travel', 24: 'Action',
    25: 'Photojournalism', 26: 'Nude', 27: 'Rural', 28: 'Water',
    29: 'Studio', 30: 'Political', 31: 'Advertisement', 32: 'Persuasive',
    33: 'Panoramic', 34: 'Digital Art', 35: 'Seascapes', 36: 'Traditional Art',
    37: 'Diptych / Triptych', 38: 'Floral', 39: 'Transportation',
    40: 'Food and Drink', 41: 'Science and Technology', 42: 'Wedding',
    43: 'Astrophotography', 44: 'Military', 45: 'History', 46: 'Infrared',
    47: 'Self Portrait', 48: 'Textures', 49: 'DPChallenge GTGs', 50: 'Children',
    51: 'Blur', 52: 'Photo-Impressionism', 53: 'High Dynamic Range (HDR)',
    54: 'Texture Library', 55: 'Overlays', 56: 'Maternity', 57: 'Birds',
    58: 'Horror', 59: 'Music', 60: 'Pinhole/Zone Plate', 61: 'Street',
    62: 'Lensbaby', 63: 'Fish Eye', 64: 'Camera Phones',
    65: 'Insects, etc', 66: 'Analog',
}

# AVA tag IDs → Facet category names (None = no mapping)
AVA_TAG_TO_FACET = {
    1: 'abstract',
    2: 'urban',
    3: 'fashion',
    4: 'portrait',       # Family → portrait (face-based)
    6: 'architecture',   # Interior → architecture
    7: 'landscape',      # Sky → landscape
    9: 'sports',
    10: 'urban',
    14: 'landscape',
    15: 'landscape',     # Nature → landscape
    17: 'portrait',      # Portraiture
    19: 'wildlife',      # Animals
    20: 'architecture',
    22: 'macro',
    26: 'portrait',      # Nude → portrait (face-based in Facet)
    27: 'landscape',     # Rural → landscape
    28: 'landscape',     # Water → landscape
    29: 'portrait',      # Studio → portrait
    33: 'landscape',     # Panoramic → landscape
    35: 'landscape',     # Seascapes → landscape
    38: 'macro',         # Floral → macro
    40: 'food',
    42: 'portrait',      # Wedding → portrait
    43: 'astro',
    47: 'portrait',      # Self Portrait → portrait
    48: 'abstract',      # Textures → abstract
    50: 'portrait',      # Children → portrait
    56: 'portrait',      # Maternity → portrait
    57: 'wildlife',      # Birds → wildlife
    61: 'street',
    65: 'macro',         # Insects → macro
}

# Multi-tag combo rules: (tag1, tag2) → Facet category
# Checked before single-tag mapping
AVA_TAG_COMBOS = {
    (17, 21): 'portrait_bw',   # Portraiture + B&W
    (21, 17): 'portrait_bw',
    (4, 21): 'portrait_bw',    # Family + B&W
    (21, 4): 'portrait_bw',
    (47, 21): 'portrait_bw',   # Self Portrait + B&W
    (21, 47): 'portrait_bw',
    (50, 21): 'portrait_bw',   # Children + B&W
    (21, 50): 'portrait_bw',
    (26, 21): 'portrait_bw',   # Nude + B&W
    (21, 26): 'portrait_bw',
    (14, 21): 'monochrome',    # Landscape + B&W
    (21, 14): 'monochrome',
    (20, 21): 'monochrome',    # Architecture + B&W
    (21, 20): 'monochrome',
    (61, 21): 'monochrome',    # Street + B&W
    (21, 61): 'monochrome',
    (19, 57): 'wildlife',      # Animals + Birds
    (57, 19): 'wildlife',
    (22, 38): 'macro',         # Macro + Floral
    (38, 22): 'macro',
    (22, 65): 'macro',         # Macro + Insects
    (65, 22): 'macro',
    (13, 59): 'concert',       # Performance + Music
    (59, 13): 'concert',
    (9, 24): 'sports',         # Sports + Action
    (24, 9): 'sports',
}


def resolve_ava_category(tag1: int, tag2: int) -> str | None:
    """Resolve AVA tag pair to a Facet category name.

    Priority: combo rules → tag_1 mapping → tag_2 mapping → None.
    """
    # Check combo rules first
    combo = AVA_TAG_COMBOS.get((tag1, tag2))
    if combo:
        return combo

    # Single-tag fallback: prefer tag_1
    mapped = AVA_TAG_TO_FACET.get(tag1)
    if mapped:
        return mapped

    mapped = AVA_TAG_TO_FACET.get(tag2)
    if mapped:
        return mapped

    return None


# ---------------------------------------------------------------------------
# Phase 1: Data loading
# ---------------------------------------------------------------------------

def parse_ava_annotations(ava_path: str) -> dict[int, dict]:
    """Parse AVA.txt and return {image_id: {'mos': float, 'tags': list[int]}}.

    AVA format: index image_id count_1 count_2 ... count_10 tag_1 tag_2 challenge_id
    MOS = Σ(i * count_i) / Σ(count_i), then normalized to 0-10.
    """
    ava_map = {}
    with open(ava_path, 'r') as f:
        reader = csv.reader(f, delimiter=' ')
        for row in reader:
            if len(row) < 12:
                continue
            try:
                image_id = int(row[1])
                counts = [int(row[i]) for i in range(2, 12)]
                total = sum(counts)
                if total == 0:
                    continue
                mos = sum((i + 1) * c for i, c in enumerate(counts)) / total
                # Normalize from [1, 10] → [0, 10]
                mos_normalized = (mos - 1.0) / 9.0 * 10.0

                # Parse semantic tags (columns 12-13, 0-indexed)
                tags = []
                for idx in (12, 13):
                    if idx < len(row):
                        try:
                            tag_id = int(row[idx])
                            if tag_id > 0:
                                tags.append(tag_id)
                        except ValueError:
                            pass

                ava_map[image_id] = {'mos': mos_normalized, 'tags': tags}
            except (ValueError, IndexError):
                continue
    return ava_map


def query_facet_db(db_path: str, include_extra: bool = False) -> list[dict]:
    """Query Facet DB for scored photos with all relevant metrics.

    Args:
        include_extra: If True, also fetch columns needed for modifier
                       optimization and filter analysis.
    """
    columns = list(METRIC_COLUMNS.keys()) + ['aggregate', 'category', 'filename', 'path']
    if include_extra:
        # Only add columns that actually exist in the DB
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.execute("PRAGMA table_info(photos)")
            existing = {row[1] for row in cursor.fetchall()}
        finally:
            conn.close()
        for col in EXTRA_COLUMNS:
            if col in existing and col not in columns:
                columns.append(col)

    col_sql = ', '.join(columns)
    query = f"""
        SELECT {col_sql}
        FROM photos
        WHERE aggregate IS NOT NULL
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(query).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def match_photos(db_rows: list[dict], ava_map: dict[int, dict]) -> list[dict]:
    """Match DB rows to AVA annotations by image_id extracted from filename.

    Each matched row gets 'mos', 'ava_tags', and 'ava_category' fields.
    """
    matched = []
    for row in db_rows:
        filename = row.get('filename') or os.path.basename(row.get('path', ''))
        stem = os.path.splitext(filename)[0]
        try:
            image_id = int(stem)
        except ValueError:
            continue
        if image_id in ava_map:
            row = dict(row)
            entry = ava_map[image_id]
            row['mos'] = entry['mos']
            row['ava_tags'] = entry['tags']

            # Resolve AVA tags to Facet category
            tags = entry['tags']
            tag1 = tags[0] if len(tags) > 0 else 0
            tag2 = tags[1] if len(tags) > 1 else 0
            row['ava_category'] = resolve_ava_category(tag1, tag2)

            matched.append(row)
    return matched


def report_match_summary(all_rows: list[dict], matched: list[dict], ava_map: dict):
    """Print a summary of matched vs unmatched photos."""
    print(f"\n{'=' * 60}")
    print("AVA MATCHING SUMMARY")
    print(f"{'=' * 60}")
    print(f"  AVA annotations loaded : {len(ava_map):,}")
    print(f"  Photos in Facet DB     : {len(all_rows):,}")
    print(f"  Matched photos         : {len(matched):,}")
    print(f"  Unmatched photos       : {len(all_rows) - len(matched):,}")

    if matched:
        cats = Counter(r.get('category') or 'default' for r in matched)
        print(f"\n  Facet category distribution:")
        for cat, count in sorted(cats.items(), key=lambda x: -x[1]):
            print(f"    {cat:<20} {count:>6,}")

        # AVA tag distribution (show if tags were parsed)
        has_tags = sum(1 for r in matched if r.get('ava_tags'))
        if has_tags:
            print(f"\n  AVA tag distribution ({has_tags:,} photos with tags):")
            tag_counts = Counter()
            for r in matched:
                for tag_id in r.get('ava_tags', []):
                    tag_counts[tag_id] += 1
            for tag_id, count in sorted(tag_counts.items(), key=lambda x: -x[1])[:15]:
                name = AVA_TAG_NAMES.get(tag_id, f'Tag {tag_id}')
                facet_cat = AVA_TAG_TO_FACET.get(tag_id, '-')
                print(f"    {name:<30} {count:>6,}  -> {facet_cat}")
            if len(tag_counts) > 15:
                print(f"    ... and {len(tag_counts) - 15} more tags")

            # Resolved category distribution
            ava_cats = Counter(r.get('ava_category') for r in matched if r.get('ava_category'))
            if ava_cats:
                print(f"\n  Resolved AVA -> Facet category distribution:")
                for cat, count in sorted(ava_cats.items(), key=lambda x: -x[1]):
                    print(f"    {cat:<20} {count:>6,}")
                unmapped = sum(1 for r in matched if r.get('ava_tags') and not r.get('ava_category'))
                if unmapped:
                    print(f"    {'(unmapped)':<20} {unmapped:>6,}")
    print()


# ---------------------------------------------------------------------------
# Phase 2: Baseline evaluation
# ---------------------------------------------------------------------------

def compute_correlations(predicted: np.ndarray, ground_truth: np.ndarray) -> dict:
    """Compute SRCC, PLCC, MAE between two score arrays."""
    if len(predicted) < 2:
        return {'srcc': float('nan'), 'plcc': float('nan'), 'mae': float('nan')}
    srcc, _ = spearmanr(predicted, ground_truth)
    plcc, _ = pearsonr(predicted, ground_truth)
    mae = float(np.mean(np.abs(predicted - ground_truth)))
    return {'srcc': float(srcc), 'plcc': float(plcc), 'mae': mae}


def evaluate_baseline(matched: list[dict]) -> None:
    """Print baseline correlation table for all metrics vs AVA MOS."""
    mos = np.array([r['mos'] for r in matched])
    aggregate = np.array([r.get('aggregate') or 5.0 for r in matched])

    print(f"{'=' * 60}")
    print("BASELINE EVALUATION")
    print(f"{'=' * 60}")
    print(f"  Photos used: {len(matched):,}")
    print()

    # Overall aggregate
    c = compute_correlations(aggregate, mos)
    print(f"  {'Metric':<25} {'SRCC':>8} {'PLCC':>8} {'MAE':>8}")
    print(f"  {'-' * 55}")
    print(f"  {'aggregate (current)':<25} {c['srcc']:>8.4f} {c['plcc']:>8.4f} {c['mae']:>8.4f}")

    # Per-metric correlations
    for col in METRIC_COLUMNS:
        vals = np.array([r.get(col) or 5.0 for r in matched])
        c = compute_correlations(vals, mos)
        print(f"  {col:<25} {c['srcc']:>8.4f} {c['plcc']:>8.4f} {c['mae']:>8.4f}")

    # Per-category breakdown
    by_cat = defaultdict(list)
    for r in matched:
        by_cat[r.get('category') or 'default'].append(r)

    if len(by_cat) > 1:
        print(f"\n  Per-category SRCC (aggregate vs AVA MOS):")
        for cat, rows in sorted(by_cat.items()):
            agg = np.array([r.get('aggregate') or 5.0 for r in rows])
            y = np.array([r['mos'] for r in rows])
            if len(rows) >= 5:
                srcc, _ = spearmanr(agg, y)
                print(f"    {cat:<20} n={len(rows):>5,}  SRCC={srcc:.4f}")
    print()


# ---------------------------------------------------------------------------
# Phase 3: Weight optimization
# ---------------------------------------------------------------------------

def build_metric_matrix(rows: list[dict]) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Build (X, y, col_names) for optimization.

    Skips metrics where >50% of values are NULL/missing (not populated in this profile).
    """
    col_names = list(METRIC_COLUMNS.keys())

    # Filter out columns with too many NULLs
    available_cols = []
    for col in col_names:
        vals = [r.get(col) for r in rows]
        non_null = sum(1 for v in vals if v is not None)
        if non_null / len(vals) >= 0.5:
            available_cols.append(col)

    X = np.array([[r.get(col) or 5.0 for col in available_cols] for r in rows], dtype=np.float64)
    y = np.array([r['mos'] for r in rows], dtype=np.float64)
    return X, y, available_cols


def objective(w: np.ndarray, X: np.ndarray, y: np.ndarray) -> float:
    """Minimize negative SRCC (maximize correlation)."""
    predicted = X @ w
    srcc, _ = spearmanr(predicted, y)
    return -srcc if np.isfinite(srcc) else 0.0


def optimize_weights(
    rows: list[dict],
    category: str,
    method: str = 'de',
) -> tuple[dict, dict]:
    """Optimize weights for a set of photos.

    Returns (result_info, col_to_weight) where col_to_weight maps DB column
    names to optimized decimal weights (summing to 1.0).
    """
    X, y, col_names = build_metric_matrix(rows)
    n = len(col_names)

    if len(rows) < MIN_PHOTOS_FOR_BASELINE:
        raise ValueError(f"Not enough photos for optimization (need {MIN_PHOTOS_FOR_BASELINE}, got {len(rows)})")

    # Uniform initial weights
    w0 = np.ones(n) / n
    bounds = [(0.0, 1.0)] * n

    # Sum-to-1 constraint: we enforce it by normalizing inside a wrapper
    def constrained_objective(w):
        w_norm = w / (w.sum() + 1e-12)
        return objective(w_norm, X, y)

    srcc_before = -objective(w0, X, y)

    if method == 'de':
        result = differential_evolution(
            constrained_objective,
            bounds=bounds,
            strategy='best1bin',
            popsize=15,
            maxiter=200,
            seed=42,
            tol=1e-6,
            workers=1,
        )
        w_opt = result.x
    else:
        result = minimize(constrained_objective, w0, method='Nelder-Mead',
                          options={'maxiter': 5000, 'xatol': 1e-5, 'fatol': 1e-5})
        w_opt = result.x

    # Normalize to sum to 1
    w_opt = np.clip(w_opt, 0.0, None)
    w_sum = w_opt.sum()
    if w_sum > 0:
        w_opt /= w_sum
    else:
        w_opt = w0

    srcc_after = -objective(w_opt, X, y)

    result_info = {
        'category': category,
        'n_photos': len(rows),
        'srcc_before': srcc_before,
        'srcc_after': srcc_after,
        'col_names': col_names,
        'w_before': w0.tolist(),
        'w_after': w_opt.tolist(),
    }

    col_to_weight = dict(zip(col_names, w_opt.tolist()))
    return result_info, col_to_weight


# ---------------------------------------------------------------------------
# Phase 3b: AVA Tag-based Analysis
# ---------------------------------------------------------------------------

def evaluate_category_detection(matched: list[dict]) -> None:
    """Compare Facet category assignments against AVA ground-truth tags.

    Prints confusion matrix, per-category precision/recall/F1,
    top misclassification pairs, and overall accuracy.
    """
    # Filter to photos with resolved AVA category
    tagged = [r for r in matched if r.get('ava_category')]
    if not tagged:
        print("  No photos with resolved AVA categories -- skipping.")
        return

    print(f"\n{'=' * 70}")
    print(f"CATEGORY DETECTION VALIDATION ({len(tagged):,} photos with AVA tags)")
    print(f"{'=' * 70}")

    # Collect all categories present
    ava_cats = sorted(set(r['ava_category'] for r in tagged))
    facet_cats = sorted(set((r.get('category') or 'default') for r in tagged))
    all_cats = sorted(set(ava_cats) | set(facet_cats))

    # Build confusion counts: confusion[ava_cat][facet_cat] = count
    confusion = defaultdict(Counter)
    for r in tagged:
        ava_cat = r['ava_category']
        facet_cat = r.get('category') or 'default'
        confusion[ava_cat][facet_cat] += 1

    # Per-category precision, recall, F1
    # Precision = TP / (TP + FP) — of photos Facet called X, how many were truly X
    # Recall = TP / (TP + FN) — of photos AVA called X, how many did Facet also call X
    facet_totals = Counter()
    for r in tagged:
        facet_totals[r.get('category') or 'default'] += 1

    print(f"\n  {'Category':<20} {'AVA':>6} {'Facet':>6} {'Match':>6} {'Prec':>8} {'Recall':>8} {'F1':>8}")
    print(f"  {'-' * 68}")

    total_correct = 0
    category_stats = []

    for cat in all_cats:
        ava_count = sum(confusion[cat].values())
        facet_count = facet_totals.get(cat, 0)
        tp = confusion[cat].get(cat, 0)
        total_correct += tp

        precision = tp / facet_count if facet_count > 0 else 0.0
        recall = tp / ava_count if ava_count > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        if ava_count > 0 or facet_count > 0:
            print(f"  {cat:<20} {ava_count:>6} {facet_count:>6} {tp:>6} {precision:>8.3f} {recall:>8.3f} {f1:>8.3f}")
            category_stats.append((cat, ava_count, facet_count, tp, precision, recall, f1))

    accuracy = total_correct / len(tagged) if tagged else 0.0
    print(f"\n  Overall accuracy: {total_correct:,}/{len(tagged):,} = {accuracy:.1%}")

    # Top misclassification pairs
    misclass = []
    for ava_cat in ava_cats:
        ava_total = sum(confusion[ava_cat].values())
        for facet_cat, count in confusion[ava_cat].items():
            if facet_cat != ava_cat and count > 0:
                pct = count / ava_total * 100 if ava_total > 0 else 0.0
                misclass.append((ava_cat, facet_cat, count, pct))

    misclass.sort(key=lambda x: -x[2])
    if misclass:
        print(f"\n  Top misclassifications:")
        for ava_cat, facet_cat, count, pct in misclass[:15]:
            print(f"    AVA={ava_cat:<18} -> Facet={facet_cat:<18} ({count:>5,}, {pct:>5.1f}% of AVA {ava_cat})")

    # Print compact confusion matrix for categories with >50 photos
    active_ava = [c for c in ava_cats if sum(confusion[c].values()) >= 50]
    active_facet = sorted(set(
        fc for ac in active_ava for fc, cnt in confusion[ac].items() if cnt >= 10
    ))
    if active_ava and active_facet:
        print(f"\n  Confusion matrix (AVA rows x Facet columns, >=50 AVA photos):")
        header = f"  {'AVA \\ Facet':<18}" + ''.join(f'{c[:8]:>9}' for c in active_facet)
        print(header)
        print(f"  {'-' * len(header)}")
        for ac in active_ava:
            row_str = f"  {ac:<18}"
            for fc in active_facet:
                cnt = confusion[ac].get(fc, 0)
                row_str += f'{cnt:>9,}' if cnt > 0 else f'{"·":>9}'
                # Highlight diagonal
            print(row_str)

    return category_stats


def validate_priorities(matched: list[dict]) -> None:
    """Diagnostic: check if Facet priority ordering conflicts with AVA tag ordering.

    For photos with 2 AVA tags mapping to different Facet categories,
    reports which category Facet tends to assign.
    """
    # Filter to photos with 2 tags mapping to different Facet categories
    dual_mapped = []
    for r in matched:
        tags = r.get('ava_tags', [])
        if len(tags) < 2:
            continue
        cat_a = AVA_TAG_TO_FACET.get(tags[0])
        cat_b = AVA_TAG_TO_FACET.get(tags[1])
        if cat_a and cat_b and cat_a != cat_b:
            dual_mapped.append((r, cat_a, cat_b))

    if not dual_mapped:
        print("\n  No photos with dual-mapped AVA tags -- skipping priority validation.")
        return

    print(f"\n{'=' * 70}")
    print(f"PRIORITY VALIDATION ({len(dual_mapped):,} photos with dual AVA tags)")
    print(f"{'=' * 70}")

    # For each (cat_A, cat_B) pair, count Facet assignments
    pair_counts = defaultdict(lambda: Counter())
    for r, cat_a, cat_b in dual_mapped:
        pair_key = tuple(sorted([cat_a, cat_b]))
        facet_cat = r.get('category') or 'default'
        pair_counts[pair_key][facet_cat] += 1

    print(f"\n  {'AVA pair':<35} {'Facet assigns ->':<40} {'Conflict?':>10}")
    print(f"  {'-' * 85}")

    conflicts = 0
    for (cat_a, cat_b), assignments in sorted(pair_counts.items(), key=lambda x: -sum(x[1].values())):
        total = sum(assignments.values())
        if total < 5:
            continue
        pair_label = f"{cat_a} + {cat_b}"
        # Show top 3 assignments
        top = assignments.most_common(3)
        assign_str = ', '.join(f'{c}={n}' for c, n in top)

        # Conflict: if neither cat_a nor cat_b is the most common assignment
        most_common_cat = top[0][0]
        is_conflict = most_common_cat not in (cat_a, cat_b)
        conflict_str = 'YES' if is_conflict else ''
        if is_conflict:
            conflicts += 1

        print(f"  {pair_label:<35} {assign_str:<40} {conflict_str:>10}")

    print(f"\n  Conflicts: {conflicts} pairs where Facet assigns neither AVA category as primary")


def analyze_filter_boundaries(matched: list[dict], config_path: str) -> list[dict]:
    """Analyze filter thresholds for misclassified photos.

    For each category with significant misclassification, examines metric
    distributions and suggests threshold adjustments.

    Returns list of suggested changes for --apply-filters.
    """
    tagged = [r for r in matched if r.get('ava_category')]
    if not tagged:
        print("  No photos with resolved AVA categories -- skipping.")
        return []

    # Load current config for filter thresholds
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"  WARNING: Could not load config: {e}")
        return []

    # Build category config lookup
    cat_configs = {}
    for cat in config.get('categories', []):
        cat_configs[cat['name']] = cat

    print(f"\n{'=' * 70}")
    print(f"FILTER THRESHOLD ANALYSIS ({len(tagged):,} tagged photos)")
    print(f"{'=' * 70}")

    suggestions = []

    # Group by AVA category
    by_ava_cat = defaultdict(list)
    for r in tagged:
        by_ava_cat[r['ava_category']].append(r)

    for ava_cat, rows in sorted(by_ava_cat.items(), key=lambda x: -len(x[1])):
        # Split into correct vs misclassified
        correct = [r for r in rows if (r.get('category') or 'default') == ava_cat]
        misclassified = [r for r in rows if (r.get('category') or 'default') != ava_cat]

        if len(misclassified) < MIN_MISCLASSIFIED_FOR_ANALYSIS:
            continue

        recall = len(correct) / len(rows) if rows else 0.0
        print(f"\n  {ava_cat} (recall={recall:.3f}, {len(misclassified)} misclassified as other):")

        cat_cfg = cat_configs.get(ava_cat, {})
        filters = cat_cfg.get('filters', {})

        # Analyze numeric filter thresholds
        _analyze_numeric_filters(ava_cat, correct, misclassified, filters, suggestions)

        # Analyze tag-based filters
        _analyze_tag_filters(ava_cat, correct, misclassified, filters)

    return suggestions


def _analyze_numeric_filters(
    category: str,
    correct: list[dict],
    misclassified: list[dict],
    filters: dict,
    suggestions: list[dict],
) -> None:
    """Analyze numeric filter thresholds for one category."""
    # Metrics to check based on common filter keys
    filter_metrics = {
        'face_ratio_min': ('face_ratio', 'min'),
        'face_ratio_max': ('face_ratio', 'max'),
        'luminance_max': ('luminance', 'max'),
        'shutter_speed_min': ('shutter_speed', 'min'),
        'shutter_speed_max': ('shutter_speed', 'max'),
    }

    for filter_key, (db_col, direction) in filter_metrics.items():
        if filter_key not in filters:
            continue

        current_threshold = filters[filter_key]

        # Collect values for correct and misclassified
        correct_vals = [r.get(db_col) for r in correct if r.get(db_col) is not None]
        misclass_vals = [r.get(db_col) for r in misclassified if r.get(db_col) is not None]

        if not correct_vals or not misclass_vals:
            continue

        correct_arr = np.array(correct_vals)
        misclass_arr = np.array(misclass_vals)

        # Sweep thresholds to find better boundary
        if direction == 'min':
            # For min filters, lowering the threshold captures more photos
            candidates = np.percentile(misclass_arr, [5, 10, 15, 20, 25])
            best_threshold = current_threshold
            best_gain = 0
            best_loss = 0

            for candidate in candidates:
                if candidate >= current_threshold:
                    continue
                # How many misclassified would now pass the filter?
                gained = np.sum(misclass_arr >= candidate)
                # How many correct would we incorrectly exclude?
                # (For min filters, lowering threshold shouldn't exclude correct photos)
                lost = 0
                net = gained - lost
                if net > best_gain:
                    best_gain = net
                    best_loss = lost
                    best_threshold = float(candidate)

            if best_gain > 0 and best_threshold != current_threshold:
                recall_gain = best_gain / (len(correct) + len(misclassified)) * 100
                print(f"    {filter_key}: current={current_threshold}, "
                      f"suggested={best_threshold:.4f} "
                      f"(+{best_gain} photos, +{recall_gain:.1f}% recall)")
                suggestions.append({
                    'category': category,
                    'filter_key': filter_key,
                    'current': current_threshold,
                    'suggested': round(best_threshold, 4),
                    'gain': best_gain,
                })

        elif direction == 'max':
            # For max filters, raising the threshold captures more photos
            candidates = np.percentile(misclass_arr, [75, 80, 85, 90, 95])
            best_threshold = current_threshold
            best_gain = 0

            for candidate in candidates:
                if candidate <= current_threshold:
                    continue
                gained = np.sum(misclass_arr <= candidate)
                net = gained
                if net > best_gain:
                    best_gain = net
                    best_threshold = float(candidate)

            if best_gain > 0 and best_threshold != current_threshold:
                recall_gain = best_gain / (len(correct) + len(misclassified)) * 100
                print(f"    {filter_key}: current={current_threshold}, "
                      f"suggested={best_threshold:.4f} "
                      f"(+{best_gain} photos, +{recall_gain:.1f}% recall)")
                suggestions.append({
                    'category': category,
                    'filter_key': filter_key,
                    'current': current_threshold,
                    'suggested': round(best_threshold, 4),
                    'gain': best_gain,
                })


def _analyze_tag_filters(
    category: str,
    correct: list[dict],
    misclassified: list[dict],
    filters: dict,
) -> None:
    """Analyze tag-based filter hit rate for misclassified photos."""
    required_tags = filters.get('required_tags')
    if not required_tags:
        return

    # Check what % of misclassified photos lack the required tags
    missing_count = 0
    for r in misclassified:
        photo_tags = r.get('tags')
        if not photo_tags:
            missing_count += 1
            continue
        # Tags may be stored as JSON string or already a list
        if isinstance(photo_tags, str):
            try:
                photo_tags = json.loads(photo_tags)
            except (json.JSONDecodeError, TypeError):
                photo_tags = []
        has_required = any(t in photo_tags for t in required_tags)
        if not has_required:
            missing_count += 1

    if missing_count > 0:
        pct = missing_count / len(misclassified) * 100
        print(f"    Missing required tags: {missing_count}/{len(misclassified)} "
              f"({pct:.0f}%) lack {required_tags[:3]}{'...' if len(required_tags) > 3 else ''} "
              f"-> tagger bottleneck")


def optimize_modifiers(
    rows: list[dict],
    category: str,
    config_path: str,
) -> dict | None:
    """Optimize bonus, noise_tolerance_multiplier, and _clipping_multiplier.

    Uses pure Python/NumPy replication of the penalty math from scorer.py
    to simulate aggregate scores, then optimizes modifiers via differential
    evolution to maximize SRCC against AVA MOS.

    Returns optimized modifier dict or None if insufficient data.
    """
    if len(rows) < MIN_PHOTOS_FOR_BASELINE:
        return None

    # Load config for current weights and penalty settings
    try:
        with open(config_path, 'r') as f:
            config_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None

    # Find category config
    cat_cfg = None
    for cat in config_data.get('categories', []):
        if cat.get('name') == category:
            cat_cfg = cat
            break
    if not cat_cfg:
        return None

    weights = cat_cfg.get('weights', {})
    modifiers = cat_cfg.get('modifiers', {})
    penalty_settings = config_data.get('penalty_settings', {})

    # Current modifier values
    current_bonus = modifiers.get('bonus', 0.0)
    current_noise_tol = modifiers.get('noise_tolerance_multiplier', 1.0)
    current_clip_mult = modifiers.get('_clipping_multiplier',
                                      1.5 if category in ('default',) else 1.0)

    # Penalty thresholds from config
    noise_threshold = penalty_settings.get('noise_sigma_threshold', 4.0)
    noise_max_pen = penalty_settings.get('noise_max_penalty_points', 1.5)
    noise_rate = penalty_settings.get('noise_penalty_per_sigma', 0.3)
    bimodality_threshold = penalty_settings.get('bimodality_threshold', 2.5)
    bimodality_pen = penalty_settings.get('bimodality_penalty_points', 0.5)
    oversat_threshold = penalty_settings.get('oversaturation_threshold', 0.9)
    oversat_pen = penalty_settings.get('oversaturation_penalty_points', 0.5)
    skip_clipping = weights.get('_skip_clipping_penalty', category == 'silhouette')
    skip_oversat = weights.get('_skip_oversaturation_penalty',
                               category in ('night', 'astro', 'concert'))

    # Build weight vector from config (metric_name → decimal weight)
    metric_weights = {}
    for key, val in weights.items():
        if key.endswith('_percent'):
            metric_name = key[:-len('_percent')]
            metric_weights[metric_name] = val / 100.0

    # Map DB columns to config metric names for the weight lookup
    db_to_metric = {
        'aesthetic': 'aesthetic',
        'comp_score': 'composition',
        'face_quality': 'face_quality',
        'tech_sharpness': 'tech_sharpness',
        'exposure_score': 'exposure',
        'color_score': 'color',
        'contrast_score': 'contrast',
        'leading_lines_score': 'leading_lines',
        'aesthetic_iaa': 'aesthetic_iaa',
        'liqe_score': 'liqe',
    }

    # Precompute per-photo base weighted score and penalty components
    n = len(rows)
    base_scores = np.zeros(n)
    noise_penalties = np.zeros(n)
    clipping_penalties = np.zeros(n)
    bimodality_penalties = np.zeros(n)
    oversat_penalties = np.zeros(n)
    mos = np.zeros(n)

    for i, r in enumerate(rows):
        mos[i] = r['mos']

        # Weighted sum of metrics
        score = 0.0
        for db_col, metric_name in db_to_metric.items():
            w = metric_weights.get(metric_name, 0.0)
            if w > 0:
                val = max(0.0, min(10.0, float(r.get(db_col) or 5.0)))
                score += val * w
        base_scores[i] = score

        # Noise penalty
        noise_sigma = float(r.get('noise_sigma') or 0)
        if noise_sigma > noise_threshold:
            noise_penalties[i] = min(noise_max_pen, (noise_sigma - noise_threshold) * noise_rate)

        # Clipping penalty
        if not skip_clipping:
            shadow = float(r.get('shadow_clipped') or 0)
            highlight = float(r.get('highlight_clipped') or 0)
            if shadow or highlight:
                clipping_penalties[i] = shadow * 0.5 + highlight * 1.0

        # Bimodality penalty
        bimod = float(r.get('histogram_bimodality') or 0)
        if bimod > bimodality_threshold:
            bimodality_penalties[i] = bimodality_pen

        # Oversaturation penalty
        if not skip_oversat:
            mean_sat = float(r.get('mean_saturation') or 0)
            if mean_sat > oversat_threshold:
                oversat_penalties[i] = oversat_pen

    def simulate(params):
        """Simulate aggregate with given modifier params."""
        bonus, noise_tol, clip_mult = params
        scores = base_scores + bonus
        scores -= clipping_penalties * clip_mult
        scores -= noise_penalties * noise_tol
        scores -= bimodality_penalties
        scores -= oversat_penalties
        return np.clip(scores, 0.0, 10.0)

    def modifier_objective(params):
        predicted = simulate(params)
        srcc, _ = spearmanr(predicted, mos)
        return -srcc if np.isfinite(srcc) else 0.0

    # Current SRCC
    current_params = [current_bonus, current_noise_tol, current_clip_mult]
    srcc_before = -modifier_objective(current_params)

    # Optimize
    bounds = [(0.0, 1.0), (0.0, 1.0), (0.5, 3.0)]
    result = differential_evolution(
        modifier_objective,
        bounds=bounds,
        strategy='best1bin',
        popsize=15,
        maxiter=100,
        seed=42,
        tol=1e-6,
        workers=1,
    )

    opt_bonus, opt_noise_tol, opt_clip_mult = result.x
    srcc_after = -modifier_objective(result.x)

    return {
        'category': category,
        'n_photos': n,
        'srcc_before': srcc_before,
        'srcc_after': srcc_after,
        'current': {
            'bonus': current_bonus,
            'noise_tolerance_multiplier': current_noise_tol,
            '_clipping_multiplier': current_clip_mult,
        },
        'optimized': {
            'bonus': round(float(opt_bonus), 3),
            'noise_tolerance_multiplier': round(float(opt_noise_tol), 3),
            '_clipping_multiplier': round(float(opt_clip_mult), 3),
        },
    }


def run_ava_tag_analysis(
    matched: list[dict],
    config_path: str,
    apply_filters: bool,
    apply_modifiers: bool = False,
) -> None:
    """Run all AVA tag-based analysis phases."""

    # Phase 2: Category detection validation
    evaluate_category_detection(matched)

    # Phase 4: Priority validation
    validate_priorities(matched)

    # Phase 5: Filter threshold analysis
    suggestions = analyze_filter_boundaries(matched, config_path)

    # Phase 6: Modifier optimization
    modifier_results = []
    tagged = [r for r in matched if r.get('ava_category')]
    if tagged:
        by_ava_cat = defaultdict(list)
        for r in tagged:
            by_ava_cat[r['ava_category']].append(r)

        print(f"\n{'=' * 70}")
        print("MODIFIER OPTIMIZATION")
        print(f"{'=' * 70}")

        for cat, rows in sorted(by_ava_cat.items(), key=lambda x: -len(x[1])):
            if len(rows) < MIN_PHOTOS_FOR_CATEGORY:
                continue

            print(f"\n  Optimizing modifiers for '{cat}' ({len(rows):,} photos)...")
            result = optimize_modifiers(rows, cat, config_path)
            if result:
                delta = result['srcc_after'] - result['srcc_before']
                sign = '+' if delta >= 0 else ''
                print(f"    SRCC: {result['srcc_before']:.4f} -> {result['srcc_after']:.4f} ({sign}{delta:.4f})")
                print(f"    {'Modifier':<35} {'Current':>10} {'Optimized':>10}")
                print(f"    {'-' * 55}")
                for key in ('bonus', 'noise_tolerance_multiplier', '_clipping_multiplier'):
                    cur = result['current'].get(key, '-')
                    opt = result['optimized'].get(key, '-')
                    cur_str = f'{cur:.3f}' if isinstance(cur, float) else str(cur)
                    opt_str = f'{opt:.3f}' if isinstance(opt, float) else str(opt)
                    print(f"    {key:<35} {cur_str:>10} {opt_str:>10}")
                modifier_results.append(result)

    # Apply modifier results if requested
    if apply_modifiers and modifier_results:
        print(f"\n{'=' * 70}")
        print("APPLYING MODIFIER CHANGES")
        print(f"{'=' * 70}")
        _apply_modifier_results(config_path, modifier_results)
    elif modifier_results and not apply_modifiers:
        print(f"\n  Tip: rerun with --apply to also write optimized modifiers")

    # Apply filter suggestions if requested
    if apply_filters and suggestions:
        print(f"\n{'=' * 70}")
        print("APPLYING FILTER THRESHOLD CHANGES")
        print(f"{'=' * 70}")
        _apply_filter_suggestions(config_path, suggestions)
    elif suggestions and not apply_filters:
        print(f"\n  Tip: rerun with --apply-filters to write suggested threshold changes")


def _apply_filter_suggestions(config_path: str, suggestions: list[dict]) -> None:
    """Write filter threshold suggestions to scoring_config.json."""
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"  ERROR: Could not load config: {e}", file=sys.stderr)
        return

    applied = 0
    for suggestion in suggestions:
        cat_name = suggestion['category']
        filter_key = suggestion['filter_key']
        new_value = suggestion['suggested']

        for cat in config.get('categories', []):
            if cat.get('name') != cat_name:
                continue
            filters = cat.setdefault('filters', {})
            old_value = filters.get(filter_key)
            filters[filter_key] = new_value
            print(f"  {cat_name}.filters.{filter_key}: {old_value} -> {new_value}")
            applied += 1
            break

    if applied:
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)
            f.write('\n')
        print(f"\n  Applied {applied} filter changes to {config_path}")
        print(f"  Run: python facet.py --recompute-average")
    else:
        print("  No changes applied.")


def _apply_modifier_results(config_path: str, modifier_results: list[dict]) -> None:
    """Write optimized modifier values to scoring_config.json."""
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"  ERROR: Could not load config: {e}", file=sys.stderr)
        return

    applied = 0
    for result in modifier_results:
        cat_name = result['category']
        optimized = result['optimized']

        for cat in config.get('categories', []):
            if cat.get('name') != cat_name:
                continue
            modifiers = cat.setdefault('modifiers', {})
            for key, new_val in optimized.items():
                old_val = modifiers.get(key)
                modifiers[key] = new_val
                old_str = f'{old_val:.3f}' if isinstance(old_val, (int, float)) else str(old_val)
                print(f"  {cat_name}.modifiers.{key}: {old_str} -> {new_val:.3f}")
            applied += 1
            break

    if applied:
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)
            f.write('\n')
        print(f"\n  Applied modifiers for {applied} categories to {config_path}")
    else:
        print("  No modifier changes applied.")


# ---------------------------------------------------------------------------
# Phase 4: Output & persistence
# ---------------------------------------------------------------------------

def print_optimization_result(info: dict, col_to_weight: dict) -> None:
    """Print a comparison table for one category."""
    col_names = info['col_names']
    w_before = info['w_before']
    w_after = info['w_after']

    print(f"\nCategory: {info['category']}  ({info['n_photos']:,} photos matched)")
    print(f"{'Metric':<30} {'Current':>12} {'Optimized':>12}")
    print(f"{'-' * 56}")
    for col, wb, wa in zip(col_names, w_before, w_after):
        print(f"  {col:<28} {wb * 100:>10.1f}%  {wa * 100:>10.1f}%")
    delta = info['srcc_after'] - info['srcc_before']
    sign = '+' if delta >= 0 else ''
    print(f"\n  SRCC before: {info['srcc_before']:.4f}  ->  after: {info['srcc_after']:.4f}  ({sign}{delta:.4f})")


def log_run_to_db(db_path: str, info: dict, col_to_weight: dict, current_config_weights: dict) -> None:
    """Insert a row into weight_optimization_runs."""
    old_w = {col: wb for col, wb in zip(info['col_names'], info['w_before'])}
    new_w = col_to_weight

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("""
            INSERT INTO weight_optimization_runs
              (category, comparisons_used, old_weights, new_weights, mse_before, mse_after)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            info['category'],
            info['n_photos'],
            json.dumps(old_w),
            json.dumps(new_w),
            1.0 - info['srcc_before'],  # "mse" proxy = 1 - SRCC
            1.0 - info['srcc_after'],
        ))
        conn.commit()
    finally:
        conn.close()


def snapshot_config_to_db(db_path: str, category: str, weights_dict: dict, srcc_before: float) -> None:
    """Save current config weights to weight_config_snapshots before overwriting."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("""
            INSERT INTO weight_config_snapshots
              (category, weights, description, accuracy_before, created_by)
            VALUES (?, ?, ?, ?, ?)
        """, (
            category,
            json.dumps(weights_dict),
            f"Pre-calibration snapshot (SRCC={srcc_before:.4f})",
            srcc_before,
            'calibrate.py',
        ))
        conn.commit()
    finally:
        conn.close()


def apply_weights_to_config(
    config_path: str,
    category: str,
    col_to_weight: dict,
    col_names: list[str],
) -> None:
    """Write optimized weights back to scoring_config.json.

    Maps DB column names back to config weight keys (with _percent suffix),
    rounds to integers summing to 100.
    """
    # Column → config key mapping (inverse of METRIC_COLUMNS)
    col_to_config_key = {col: key for col, key in METRIC_COLUMNS.items()}

    with open(config_path, 'r') as f:
        config = json.load(f)

    for cat in config.get('categories', []):
        if cat.get('name') != category:
            continue

        weights_block = cat.setdefault('weights', {})

        # Convert optimized decimals to percentages
        new_percents = {}
        for col in col_names:
            config_key = col_to_config_key.get(col)
            if config_key:
                percent_key = f'{config_key}_percent'
                new_percents[percent_key] = col_to_weight.get(col, 0.0) * 100.0

        # Round to integers while keeping sum = 100
        # Keep existing _percent keys not in our optimization set unchanged
        existing_other = {k: v for k, v in weights_block.items()
                          if k.endswith('_percent') and k not in new_percents}
        other_total = sum(existing_other.values())
        budget = 100 - other_total

        # Scale new_percents to fit in budget
        total_new = sum(new_percents.values())
        if total_new > 0:
            scaled = {k: v / total_new * budget for k, v in new_percents.items()}
        else:
            scaled = new_percents

        # Round with remainder fix
        rounded = {k: int(v) for k, v in scaled.items()}
        remainder = budget - sum(rounded.values())
        if remainder != 0 and rounded:
            # Add remainder to the largest weight
            largest = max(rounded, key=lambda k: scaled[k])
            rounded[largest] += remainder

        # Update config
        weights_block.update(rounded)
        break
    else:
        print(f"  WARNING: Category '{category}' not found in scoring_config.json -- skipping apply.", file=sys.stderr)
        return

    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)
        f.write('\n')

    print(f"  Updated weights for category '{category}' in {config_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description='Calibrate Facet scoring weights against AVA human ratings dataset.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--db', required=True, help='Path to Facet SQLite database')
    parser.add_argument('--ava-annotations', required=True, metavar='AVA_TXT',
                        help='Path to AVA.txt annotations file')
    parser.add_argument('--categories', metavar='CAT1,CAT2',
                        help='Comma-separated categories to optimize (default: all with enough data)')
    parser.add_argument('--apply', action='store_true',
                        help='Write optimized weights back to scoring_config.json')
    parser.add_argument('--method', choices=['de', 'nelder-mead'], default='de',
                        help='Optimization method: de=differential_evolution (default), nelder-mead=faster')
    parser.add_argument('--config', default=SCORING_CONFIG_PATH,
                        help=f'Path to scoring_config.json (default: {SCORING_CONFIG_PATH})')
    # AVA tag-based analysis flags
    parser.add_argument('--ava-tags', action='store_true',
                        help='Enable extended calibration using AVA semantic tags (phases 2-5)')
    parser.add_argument('--ava-tags-only', action='store_true',
                        help='Skip weight optimization, run only AVA tag-based analysis')
    parser.add_argument('--apply-filters', action='store_true',
                        help='Apply suggested filter threshold changes to scoring_config.json')
    return parser.parse_args()


def main():
    args = parse_args()

    if not os.path.exists(args.db):
        print(f"ERROR: Database not found: {args.db}", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(args.ava_annotations):
        print(f"ERROR: AVA annotations file not found: {args.ava_annotations}", file=sys.stderr)
        sys.exit(1)

    use_ava_tags = args.ava_tags or args.ava_tags_only
    skip_weights = args.ava_tags_only

    # -----------------------------------------------------------------------
    # Phase 1: Load data
    # -----------------------------------------------------------------------
    print("Loading AVA annotations...")
    ava_map = parse_ava_annotations(args.ava_annotations)
    print(f"  Loaded {len(ava_map):,} AVA annotations.")

    if use_ava_tags:
        tagged_count = sum(1 for v in ava_map.values() if v['tags'])
        print(f"  AVA entries with semantic tags: {tagged_count:,}")

    print("Querying Facet database...")
    all_rows = query_facet_db(args.db, include_extra=use_ava_tags)
    print(f"  Found {len(all_rows):,} scored photos in DB.")

    matched = match_photos(all_rows, ava_map)
    report_match_summary(all_rows, matched, ava_map)

    if len(matched) < MIN_PHOTOS_FOR_BASELINE:
        print(f"ERROR: Only {len(matched)} photos matched AVA. Need at least {MIN_PHOTOS_FOR_BASELINE}.")
        print("       Score AVA images with: python facet.py /path/to/ava_images/")
        sys.exit(1)

    # -----------------------------------------------------------------------
    # Phase 2: Baseline evaluation
    # -----------------------------------------------------------------------
    evaluate_baseline(matched)

    # -----------------------------------------------------------------------
    # Phase 3: Weight optimization (unless --ava-tags-only)
    # -----------------------------------------------------------------------
    if not skip_weights:
        by_cat = defaultdict(list)
        for r in matched:
            by_cat[r.get('category') or 'default'].append(r)

        # Determine which categories to optimize
        if args.categories:
            target_cats = [c.strip() for c in args.categories.split(',')]
        else:
            # Always include combined optimization; add per-category if enough data
            target_cats = ['_all_']
            for cat, rows in by_cat.items():
                if len(rows) >= MIN_PHOTOS_FOR_CATEGORY:
                    target_cats.append(cat)

        method = 'de' if args.method == 'de' else 'nelder-mead'

        print(f"{'=' * 60}")
        print("WEIGHT OPTIMIZATION")
        print(f"{'=' * 60}")
        print(f"  Method: {args.method}")

        optimization_results = []

        for cat in target_cats:
            if cat == '_all_':
                rows = matched
                cat_label = 'default (all photos combined)'
                cat_key = 'default'
            else:
                rows = by_cat.get(cat, [])
                cat_label = cat
                cat_key = cat

            if len(rows) < MIN_PHOTOS_FOR_BASELINE:
                print(f"\n  Skipping '{cat_label}': only {len(rows)} photos (need {MIN_PHOTOS_FOR_BASELINE})")
                continue

            print(f"\n  Optimizing '{cat_label}' ({len(rows):,} photos)...")
            try:
                info, col_to_weight = optimize_weights(rows, cat_key, method=method)
            except Exception as e:
                print(f"  ERROR optimizing '{cat_label}': {e}", file=sys.stderr)
                continue

            print_optimization_result(info, col_to_weight)
            optimization_results.append((cat_key, info, col_to_weight))

            # Log to DB
            try:
                log_run_to_db(args.db, info, col_to_weight, current_config_weights={})
            except Exception as e:
                print(f"  WARNING: Could not log run to DB: {e}", file=sys.stderr)

        # Apply weights if requested
        if args.apply and optimization_results:
            print(f"\n{'=' * 60}")
            print("APPLYING OPTIMIZED WEIGHTS")
            print(f"{'=' * 60}")

            if not os.path.exists(args.config):
                print(f"  ERROR: scoring_config.json not found at {args.config}", file=sys.stderr)
                sys.exit(1)

            for cat_key, info, col_to_weight in optimization_results:
                # Snapshot existing weights first
                try:
                    with open(args.config, 'r') as f:
                        config = json.load(f)
                    for cat in config.get('categories', []):
                        if cat.get('name') == cat_key:
                            snapshot_config_to_db(args.db, cat_key, cat.get('weights', {}), info['srcc_before'])
                            break
                except Exception as e:
                    print(f"  WARNING: Could not snapshot config: {e}", file=sys.stderr)

                # Apply
                try:
                    apply_weights_to_config(args.config, cat_key, col_to_weight, info['col_names'])
                except Exception as e:
                    print(f"  ERROR applying weights for '{cat_key}': {e}", file=sys.stderr)

            print(f"\n  Done. Run the following to recompute all aggregate scores:")
            print(f"    python facet.py --recompute-average")
        elif not args.apply and optimization_results:
            print(f"\n  Tip: rerun with --apply to write these weights to scoring_config.json")

    # -----------------------------------------------------------------------
    # Phase 5: AVA tag-based analysis (if --ava-tags or --ava-tags-only)
    # -----------------------------------------------------------------------
    if use_ava_tags:
        run_ava_tag_analysis(matched, args.config, args.apply_filters,
                             apply_modifiers=args.apply)


if __name__ == '__main__':
    main()
