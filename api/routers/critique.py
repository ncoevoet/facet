"""
AI Critique router — rule-based and VLM-powered score explanations.

Provides per-photo analysis: score breakdown, strengths, weaknesses, suggestions.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth import CurrentUser, get_optional_user
from api.config import VIEWER_CONFIG, _FULL_CONFIG
from api.database import get_db
from api.db_helpers import get_visibility_clause
from api.model_cache import get_or_load_vlm_tagger

router = APIRouter(tags=["critique"])
logger = logging.getLogger(__name__)

# Score thresholds for strength/weakness classification
_STRENGTH_THRESHOLD = 7.5
_WEAKNESS_THRESHOLD = 5.0
# Noise thresholds
_NOISE_CLEAN_THRESHOLD = 3.0
_NOISE_HIGH_THRESHOLD = 8.0
_NOISE_PENALTY_THRESHOLD = 4.0

# Metric labels for human-readable output
METRIC_LABELS = {
    'aesthetic': 'Aesthetic Quality',
    'tech_sharpness': 'Technical Sharpness',
    'face_quality': 'Face Quality',
    'eye_sharpness': 'Eye Sharpness',
    'face_sharpness': 'Face Sharpness',
    'comp_score': 'Composition',
    'exposure_score': 'Exposure',
    'color_score': 'Color',
    'contrast_score': 'Contrast',
    'isolation_bonus': 'Subject Isolation',
    'noise_sigma': 'Noise Level',
    'dynamic_range_stops': 'Dynamic Range',
    'leading_lines_score': 'Leading Lines',
    'power_point_score': 'Power Points',
    'aesthetic_iaa': 'Aesthetic (IAA)',
    'face_quality_iqa': 'Face Quality (IQA)',
    'liqe_score': 'LIQE Quality',
    'subject_sharpness': 'Subject Sharpness',
    'subject_prominence': 'Subject Prominence',
    'subject_placement': 'Subject Placement',
    'bg_separation': 'Background Separation',
    'mean_saturation': 'Saturation',
    'mean_luminance': 'Luminance',
}

# Map config weight keys to DB column names
WEIGHT_TO_COLUMN = {
    'aesthetic': 'aesthetic',
    'quality': 'quality_score',
    'face_quality': 'face_quality',
    'face_sharpness': 'face_sharpness',
    'eye_sharpness': 'eye_sharpness',
    'tech_sharpness': 'tech_sharpness',
    'composition': 'comp_score',
    'exposure': 'exposure_score',
    'color': 'color_score',
    'contrast': 'contrast_score',
    'isolation': 'isolation_bonus',
    'dynamic_range': 'dynamic_range_stops',
    'leading_lines': 'leading_lines_score',
    'power_point': 'power_point_score',
    'aesthetic_iaa': 'aesthetic_iaa',
    'face_quality_iqa': 'face_quality_iqa',
    'liqe': 'liqe_score',
    'subject_sharpness': 'subject_sharpness',
    'subject_prominence': 'subject_prominence',
    'subject_placement': 'subject_placement',
    'bg_separation': 'bg_separation',
    'noise': 'noise_sigma',
    'saturation': 'mean_saturation',
}

# Suggestions keyed by metric name (low score triggers these)
SUGGESTIONS = {
    'aesthetic': 'Consider stronger visual impact through better lighting or subject matter',
    'tech_sharpness': 'Use a faster shutter speed or tripod to improve sharpness',
    'face_quality': 'Ensure the face is well-lit and in focus',
    'eye_sharpness': 'Focus precisely on the eyes for portraits',
    'face_sharpness': 'Ensure the face region is sharp — avoid motion blur',
    'comp_score': 'Try applying compositional rules like rule of thirds or leading lines',
    'exposure_score': 'Adjust exposure to avoid clipping highlights or crushing shadows',
    'color_score': 'Consider white balance correction or more vibrant color grading',
    'contrast_score': 'Increase tonal contrast for more visual depth',
    'noise_sigma': 'Use a lower ISO or apply noise reduction',
    'dynamic_range_stops': 'Bracket exposures or use graduated filters for better dynamic range',
    'leading_lines_score': 'Look for natural lines that draw the eye into the frame',
    'subject_sharpness': 'Ensure your main subject is the sharpest element in the frame',
    'subject_prominence': 'Give the subject more frame space or use a shallower depth of field',
    'bg_separation': 'Use wider aperture or greater distance to separate subject from background',
    'liqe_score': 'Improve overall image quality — check for distortions or artifacts',
    'isolation_bonus': 'Use wider aperture to better isolate the subject from background',
}


def _build_category_trail(photo, matched_category, sc):
    """Build list of interesting rejected categories evaluated before the match.

    Only includes categories where the rejection is non-trivial (not just
    'no matching tags for a tag-only category').
    """
    from config.category_filter import CategoryFilter

    rejected = []
    for cat in sc.get_categories():
        name = cat.get('name')
        if name == matched_category:
            break

        filters = cat.get('filters', {})
        if not filters:
            continue

        cf = CategoryFilter(filters)
        mismatch = cf.explain_mismatch(photo)
        if mismatch is None:
            continue

        # Skip trivially irrelevant tag-only categories: if the only filters
        # are tag-related and none of the required tags appear in the photo
        filter_keys = set(filters.keys()) - {'tag_match_mode'}
        is_tag_only = filter_keys <= {'required_tags', 'excluded_tags'}
        if is_tag_only and mismatch['key'] == 'required_tags' and not mismatch.get('actual'):
            continue

        rejected.append({'category': name, 'mismatch': mismatch})
        if len(rejected) >= 5:
            break

    return rejected


def _build_category_reason(photo, category, sc):
    """Build structured category reason for i18n on the frontend."""
    cat_config = sc.get_category_config(category)
    if not cat_config:
        return {'reason_key': 'default', 'category': category or 'default', 'details': [], 'rejected': []}

    filters = cat_config.get('filters', {})
    details = []

    if 'face_ratio_min' in filters and photo.get('face_ratio'):
        details.append({
            'key': 'face_ratio',
            'value': round(photo['face_ratio'], 2),
            'threshold': filters['face_ratio_min'],
        })
    if 'face_count_min' in filters and photo.get('face_count'):
        details.append({
            'key': 'face_count',
            'value': photo['face_count'],
            'threshold': filters['face_count_min'],
        })
    if filters.get('is_monochrome') and photo.get('is_monochrome'):
        details.append({'key': 'monochrome'})
    if filters.get('is_silhouette') and photo.get('is_silhouette'):
        details.append({'key': 'silhouette'})
    if filters.get('required_tags'):
        tags = photo.get('tags', '') or ''
        matched = [t for t in filters['required_tags'] if t in tags]
        if matched:
            details.append({'key': 'tags', 'tags': matched})
    if 'luminance_max' in filters and photo.get('mean_luminance') is not None:
        details.append({
            'key': 'luminance',
            'value': round(photo['mean_luminance'], 2),
            'threshold': filters['luminance_max'],
        })
    if 'shutter_speed_min' in filters and photo.get('shutter_speed'):
        details.append({'key': 'long_exposure'})

    rejected = _build_category_trail(photo, category, sc)

    return {
        'reason_key': 'matched' if details else 'matched_generic',
        'category': category,
        'details': details,
        'rejected': rejected,
    }


def _calculate_breakdown(photo, sc, category):
    """Calculate score breakdown from photo metrics and category weights.

    Returns a sorted list of score contributions with metric details.
    """
    weights = sc.get_weights(category)
    if not weights:
        weights = sc.get_weights('')

    breakdown = []

    for weight_key, weight_val in weights.items():
        if weight_key in ('bonus', 'blink_penalty', 'noise_tolerance_multiplier',
                          'noise_penalty_max', 'noise_threshold', 'score_min', 'score_max',
                          'bimodality_threshold', 'bimodality_penalty',
                          'oversaturation_threshold', 'oversaturation_penalty',
                          'clipping_multiplier', 'noise_penalty_rate'):
            continue

        col = WEIGHT_TO_COLUMN.get(weight_key)
        if not col or weight_val <= 0:
            continue

        value = photo.get(col)
        if value is None:
            continue

        display_value = float(value)
        contribution = display_value * weight_val

        breakdown.append({
            'metric': METRIC_LABELS.get(col, weight_key),
            'metric_key': col,
            'value': round(display_value, 2),
            'weight': round(weight_val, 3),
            'contribution': round(contribution, 2),
        })

    breakdown.sort(key=lambda x: x['contribution'], reverse=True)
    return breakdown


def _identify_strengths_weaknesses(breakdown):
    """Identify strengths and weaknesses from a score breakdown.

    Returns a (strengths, weaknesses, suggestions) tuple. Strengths and weaknesses
    are lists of dicts with metric_key and value; suggestions is a list of metric keys.
    """
    strengths = []
    weaknesses = []
    suggestions = []

    for item in breakdown:
        val = item['value']
        metric_key = item['metric_key']

        # Noise is inverted -- high noise_sigma is bad
        if metric_key == 'noise_sigma':
            if val < _NOISE_CLEAN_THRESHOLD:
                strengths.append({'metric_key': metric_key, 'value': round(val, 1)})
            elif val > _NOISE_HIGH_THRESHOLD:
                weaknesses.append({'metric_key': metric_key, 'value': round(val, 1)})
                if metric_key in SUGGESTIONS:
                    suggestions.append(metric_key)
        elif metric_key in ('mean_saturation', 'mean_luminance'):
            continue  # Not meaningful as strengths/weaknesses
        else:
            if val >= _STRENGTH_THRESHOLD:
                strengths.append({'metric_key': metric_key, 'value': round(val, 1)})
            elif val < _WEAKNESS_THRESHOLD and item['weight'] > 0.05:
                weaknesses.append({'metric_key': metric_key, 'value': round(val, 1)})
                if metric_key in SUGGESTIONS:
                    suggestions.append(metric_key)

    return strengths, weaknesses, suggestions


def _check_penalties(photo):
    """Check for scoring penalties (blink, noise, clipping).

    Returns a dict of penalty names to values.
    """
    penalties = {}
    if photo.get('is_blink'):
        penalties['blink'] = True
    if photo.get('noise_sigma') and photo['noise_sigma'] > _NOISE_PENALTY_THRESHOLD:
        noise_penalty = min(1.5, max(0, (photo['noise_sigma'] - _NOISE_PENALTY_THRESHOLD) * 0.3))
        if noise_penalty > 0:
            penalties['noise'] = round(-noise_penalty, 2)
    if photo.get('highlight_clipped') and photo['highlight_clipped'] > 0:
        penalties['highlight_clipping'] = round(-photo['highlight_clipped'] * 1.0, 2)
    if photo.get('shadow_clipped') and photo['shadow_clipped'] > 0:
        penalties['shadow_clipping'] = round(-photo['shadow_clipped'] * 0.5, 2)
    return penalties


def _build_rule_critique(photo):
    """Build a rule-based critique from stored metrics."""
    from config import ScoringConfig

    sc = ScoringConfig()
    category = photo.get('category', '')

    breakdown = _calculate_breakdown(photo, sc, category)
    strengths, weaknesses, suggestions = _identify_strengths_weaknesses(breakdown)
    penalties = _check_penalties(photo)
    category_reason = _build_category_reason(photo, category, sc)

    return {
        'category': category or 'default',
        'category_reason': category_reason,
        'aggregate': photo.get('aggregate'),
        'breakdown': breakdown,
        'strengths': sorted(strengths, key=lambda x: x['value'], reverse=True)[:5],
        'weaknesses': sorted(weaknesses, key=lambda x: x['value'])[:5],
        'suggestions': suggestions[:3],
        'penalties': penalties,
    }


@router.get("/api/critique")
def api_critique(
    path: str = Query(...),
    mode: str = Query("rule"),
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Get AI critique for a photo's score.

    Modes:
      - rule: Fast rule-based analysis (always available)
      - vlm: VLM-powered natural language critique (requires GPU + VLM model)
    """
    if not VIEWER_CONFIG.get('features', {}).get('show_critique', True):
        raise HTTPException(status_code=403, detail="Critique feature is disabled")

    with get_db() as conn:
        user_id = user.user_id if user else None
        vis_sql, vis_params = get_visibility_clause(user_id)

        # Select only columns needed for critique (avoid loading BLOB fields)
        critique_cols = [
            'path', 'category', 'aggregate', 'aesthetic', 'tech_sharpness',
            'face_quality', 'eye_sharpness', 'face_sharpness', 'comp_score',
            'exposure_score', 'color_score', 'contrast_score', 'isolation_bonus',
            'noise_sigma', 'dynamic_range_stops', 'leading_lines_score',
            'power_point_score', 'aesthetic_iaa', 'face_quality_iqa', 'liqe_score',
            'subject_sharpness', 'subject_prominence', 'subject_placement',
            'bg_separation', 'mean_saturation', 'mean_luminance',
            'face_ratio', 'face_count', 'is_monochrome', 'is_blink',
            'is_silhouette', 'is_group_portrait',
            'highlight_clipped', 'shadow_clipped', 'tags', 'shutter_speed',
            'focal_length', 'f_stop', 'iso',
        ]
        col_str = ', '.join(critique_cols)
        photo = conn.execute(
            f"SELECT {col_str} FROM photos WHERE path = ? AND {vis_sql}",
            [path] + vis_params
        ).fetchone()

        if not photo:
            raise HTTPException(status_code=404, detail="Photo not found")

        photo = dict(photo)
        result = _build_rule_critique(photo)

        if mode == 'vlm':
            vlm_critique = _get_vlm_critique(photo, result)
            if vlm_critique:
                result['vlm_critique'] = vlm_critique
            else:
                result['vlm_available'] = False

        return result


def _get_vlm_critique(photo, rule_critique):
    """Generate VLM-powered critique if available."""
    try:
        models_config = _FULL_CONFIG.get('models', {})
        profile = models_config.get('vram_profile', 'legacy')
        if profile not in ('16gb', '24gb'):
            return None

        if not VIEWER_CONFIG.get('features', {}).get('show_vlm_critique', False):
            return None

        from api.config import map_disk_path
        from PIL import Image

        vlm_config = models_config.get('vlm_tagger', {})
        if not vlm_config.get('model_name'):
            return None

        tagger = get_or_load_vlm_tagger(vlm_config, _FULL_CONFIG)

        # Build critique prompt
        category = rule_critique.get('category', 'photo')
        aggregate = rule_critique.get('aggregate', 0)
        strengths = ', '.join(
            METRIC_LABELS.get(s['metric_key'], s['metric_key']) for s in rule_critique.get('strengths', [])[:3]
        ) or 'none identified'
        weaknesses = ', '.join(
            METRIC_LABELS.get(w['metric_key'], w['metric_key']) for w in rule_critique.get('weaknesses', [])[:3]
        ) or 'none identified'

        prompt = (
            f"This {category} photo scored {aggregate:.1f}/10. "
            f"Strengths: {strengths}. Weaknesses: {weaknesses}. "
            f"Give a 2-3 sentence photography critique with specific improvement suggestions."
        )

        disk_path = map_disk_path(photo['path'])
        img = Image.open(disk_path).convert('RGB')
        img.thumbnail((640, 640))

        # Use VLM generate method
        response = tagger.generate(img, prompt, max_new_tokens=200)
        return response

    except Exception:
        logger.exception("VLM critique failed")
        return None
