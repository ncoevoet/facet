"""
AI Critique router — rule-based and VLM-powered score explanations.

Provides per-photo analysis: score breakdown, strengths, weaknesses, suggestions.
"""

import asyncio
import json
import logging
import math
import sqlite3

from typing import Optional

import licensing
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.auth import CurrentUser, get_optional_user, is_edition_authenticated, require_edition
from api.config import VIEWER_CONFIG, _FULL_CONFIG
from api.database import get_async_db, get_db, run_sync
from api.inflight import GenerationInterrupted, InflightGate
from api.db_helpers import get_existing_columns, get_visibility_clause
from api.models.media import MediaCritiqueResponse
from api.model_cache import (
    get_or_load_vlm_tagger,
    resolve_vlm_config,
    vlm_known_unavailable,
    translate_text,
    translation_target,
    vlm_accelerator_lock,
    vlm_generate_lock,
)

router = APIRouter(tags=["critique"])
logger = logging.getLogger(__name__)
_critique_flights = InflightGate()

# Score thresholds for strength/weakness classification
_STRENGTH_THRESHOLD = 7.5
_WEAKNESS_THRESHOLD = 5.0

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
    'noise_sigma': 'Noise quality',
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
    'form_symmetry': 'Symmetry',
    'form_balance': 'Visual Balance',
    'form_edge_entropy': 'Edge Entropy',
    'form_fractal': 'Fractal Complexity',
    'color_harmony': 'Color Harmony',
    'aesthetic_v25': 'Aesthetic v2.5',
    'qrealign_score': 'Q-ReAlign',
    'deqa_score': 'DeQA',
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
    'symmetry': 'form_symmetry',
    'balance': 'form_balance',
    'edge_entropy': 'form_edge_entropy',
    'fractal': 'form_fractal',
    'color_harmony': 'color_harmony',
    'qrealign': 'qrealign_score',
    'deqa': 'deqa_score',
    'aesthetic_v25': 'aesthetic_v25',
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
    'form_symmetry': 'Center the subject or align strong shapes to balance the left and right halves of the frame',
    'form_balance': 'Recompose so the visual weight sits closer to the frame center or a balanced thirds position',
    'form_edge_entropy': 'Add more varied lines and textures — the dominant edges all run in the same direction',
    'form_fractal': 'Include richer detail or texture — the frame reads as visually sparse',
    'color_harmony': 'Adjust the palette toward a harmonic hue scheme such as complementary or analogous colors',
}


def _build_category_trail(photo, matched_category, sc):
    """Build list of interesting rejected categories evaluated before the match.

    Only includes categories where the rejection is non-trivial (not just
    'no matching tags for a tag-only category').
    """
    from config.category_filter import CategoryFilter, with_face_defaults

    photo = with_face_defaults(photo)
    rejected = []
    for cat in sc.get_categories(context=photo.get('scoring_context')):
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
    if photo.get('category_override') == category and category:
        return {'reason_key': 'override', 'category': category,
                'details': [], 'rejected': []}
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
    from processing.scorer import (
        build_metric_vector, fold_quality_weight, weights_for_row,
        unavailable_for_config, weighted_metric_contribution,
    )

    weights = fold_quality_weight(sc.get_weights(category))
    unavailable = unavailable_for_config(sc)
    weights = weights_for_row(weights, photo, unavailable)
    vector = build_metric_vector(photo, sc, category, unavailable=unavailable)
    breakdown = []
    for metric_key, value in vector.items():
        weight = weights.get(metric_key, 0)
        if not weight > 0:
            continue
        if not math.isfinite(weight):
            raise ValueError("Finite contribution weights required")
        col = WEIGHT_TO_COLUMN.get(metric_key, metric_key)
        # Match the native weighted sum; these are effective quality inputs,
        # not the raw physical measurements stored in the database.
        effective = max(0., min(10., value))
        breakdown.append({
            'metric': METRIC_LABELS.get(col, metric_key),
            'metric_key': col,
            'value': round(float(effective), 2),
            'weight': round(float(weight), 3),
            'contribution': round(float(weighted_metric_contribution(value, weight)), 2),
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

        if metric_key in ('mean_saturation', 'mean_luminance'):
            continue  # Not meaningful as strengths/weaknesses
        else:
            if val >= _STRENGTH_THRESHOLD:
                strengths.append({'metric_key': metric_key, 'value': round(val, 1)})
            elif val < _WEAKNESS_THRESHOLD and item['weight'] > 0.05:
                weaknesses.append({'metric_key': metric_key, 'value': round(val, 1)})
                if metric_key in SUGGESTIONS:
                    suggestions.append(metric_key)

    return strengths, weaknesses, suggestions


def _finite_number(value):
    """True for a finite int or float; a bool or a stringified SQLite value is not one."""
    return type(value) in (int, float) and math.isfinite(value)


def _stored_score(photo):
    """The stored aggregate as ``(value, state)``: the value only when it is a finite number."""
    stored = photo.get('aggregate')
    if _finite_number(stored):
        return float(stored), 'present'
    return None, 'missing' if stored is None else 'invalid'


def _check_penalties(photo):
    """Surface advisory flags (blink and skin-tone cast), without scoring math.

    Returns advisory flags, never hand-derived numerical score deductions.
    The native net adjustment is authoritative. The skin-tone entry is advisory
    (it never enters the aggregate) and surfaces whenever the stored worst-face
    cast is present: ``compute_photo_skin_tone`` already applied the configured
    ``cast_delta_threshold`` once at recompute time (``skin_tone_cast`` is NULL
    below it), so the stored decision is trusted here rather than re-gated.
    """
    penalties = {}
    if photo.get('is_blink'):
        penalties['blink'] = True
    skin_delta = photo.get('skin_tone_delta')
    if _finite_number(skin_delta) and photo.get('skin_tone_cast'):
        penalties['skin_tone'] = {
            'cast': photo['skin_tone_cast'],
            'delta': round(float(skin_delta), 1),
        }
    return penalties


def _parse_distortions(raw):
    """Attribute keys from the stored distortion_attributes JSON column."""
    if not raw:
        return []
    try:
        entries = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(entries, list):
        return []
    return [e['attribute'] for e in entries if isinstance(e, dict) and e.get('attribute')]


def _build_rule_critique(photo, *, config=None, normalizer=None, overrides=None):
    """Build a rule-based critique from stored metrics."""
    from api.config import server_scoring_config

    from processing.scorer import Facet

    sc = config or server_scoring_config()
    prepared = dict(photo)
    if overrides:
        prepared.update(overrides)
    Facet.prepare_scoring_row(prepared, sc, normalizer)
    # The normal constructor initializes the database; explanation is read-only.
    native = Facet.__new__(Facet)
    native.config = sc
    current_total, category = native.calculate_aggregate_logic(prepared)
    if not math.isfinite(current_total):
        raise ValueError("Native calculation is not finite")
    breakdown = _calculate_breakdown(prepared, sc, category)
    strengths, weaknesses, suggestions = _identify_strengths_weaknesses(breakdown)
    # Advisory flags remain separate from the reconciled native adjustment.
    penalties = _check_penalties(photo)
    category_reason = _build_category_reason(prepared, category, sc)
    stored, stored_state = _stored_score(photo)
    displayed_total = round(float(current_total), 2)
    display_base_cents = sum(round(item['contribution'] * 100) for item in breakdown)

    return {
        'category': category or 'default',
        'category_reason': category_reason,
        'aggregate': stored,
        'score_basis': 'current_formula',
        'current_formula_score': displayed_total,
        'native_adjustment': (round(displayed_total * 100) - display_base_cents) / 100,
        'stored_score_matches_current_formula': (
            round(stored, 2) == displayed_total if stored is not None else None),
        'normalization_basis': ('persisted_percentiles' if normalizer is not None
                                else 'stored_metrics'),
        'stored_score_state': stored_state,
        'breakdown': breakdown,
        'strengths': sorted(strengths, key=lambda x: x['value'], reverse=True)[:5],
        'weaknesses': sorted(weaknesses, key=lambda x: x['value'])[:5],
        'suggestions': suggestions[:3],
        'penalties': penalties,
        'distortions': _parse_distortions(photo.get('distortion_attributes')),
    }


def _unavailable_critique(photo, reason):
    stored, stored_state = _stored_score(photo)
    category = photo.get('category') or 'default'
    return {'category': category,
            'category_reason': {'reason_key': 'unavailable', 'category': category, 'details': []},
            'aggregate': stored,
            'score_basis': 'current_formula', 'current_formula_score': None,
            'native_adjustment': None, 'stored_score_matches_current_formula': None,
            'explanation_unavailable_reason': reason,
            'stored_score_state': stored_state,
            'breakdown': [], 'strengths': [], 'weaknesses': [], 'suggestions': [],
            'penalties': _check_penalties(photo),
            'distortions': _parse_distortions(photo.get('distortion_attributes'))}


def _usable_snapshot(snapshot):
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get('percentiles'), dict):
        return False
    def finite(value):
        return _finite_number(value) and value >= 0
    categories = snapshot.get('category_percentiles', {})
    return (all(finite(value) for value in snapshot['percentiles'].values())
            and isinstance(categories, dict)
            and all(isinstance(values, dict) and all(finite(value) for value in values.values())
                    for values in categories.values()))


def _snapshot_malformed(conn):
    """True when a percentile snapshot is persisted but cannot be scored with.

    An ABSENT snapshot is not malformed. Only ``--recompute-average`` and
    ``--recompute-category`` persist one (and a photo delete keeps it); a scan
    scores every photo from its stored metrics with no normalizer, and
    ``PercentileNormalizer.from_snapshot`` answers None in that case so the
    explanation reads the stored metrics exactly as the scan did.
    ``load_persisted`` also answers None for a row that does not parse, or for
    any read error, so the row is probed to tell those apart from an absent
    one. Only a missing ``stats_cache`` table counts as absent; any other read
    error (a locked database) reports the snapshot unavailable rather than
    explaining a normalized library un-normalized.
    """
    from config.percentile_normalizer import PercentileNormalizer
    from db.stats_cache import PERCENTILES_SNAPSHOT_KEY

    snapshot = PercentileNormalizer.load_persisted(conn)
    if snapshot is not None:
        return not _usable_snapshot(snapshot)
    try:
        row = conn.execute("SELECT 1 FROM stats_cache WHERE key = ?",
                           (PERCENTILES_SNAPSHOT_KEY,)).fetchone()
    except sqlite3.OperationalError as ex:
        return 'no such table' not in str(ex)
    return row is not None


def _load_rule_critique(path, user):
    """Read one visible scoring row, overrides and normalizer in one snapshot."""
    from config.percentile_normalizer import PercentileNormalizer
    from api.config import server_scoring_config
    from db.scoring_overrides import get_photo_scoring_overrides
    from processing.scorer import SERVED_ROW_COLUMNS

    config = server_scoring_config()
    with get_db() as conn, conn:
        conn.execute("BEGIN")
        existing = {row[1] for row in conn.execute("PRAGMA table_info(photos)")}
        columns = list(dict.fromkeys((*SERVED_ROW_COLUMNS, 'category', 'aggregate',
                    'distortion_attributes', 'skin_tone_delta', 'skin_tone_cast')))
        columns = [column for column in columns if column in existing]
        user_id = user.user_id if user else None
        vis_sql, vis_params = get_visibility_clause(user_id)
        row = conn.execute(
            f"SELECT {', '.join(columns)} FROM photos WHERE path = ? AND {vis_sql}",
            [path] + vis_params,
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Photo not found")
        photo = dict(row)
        if set(SERVED_ROW_COLUMNS) - existing:
            return photo, _unavailable_critique(photo, 'missing_scoring_inputs')
        settings = config.get_normalization_settings()
        if settings.get('method') == 'percentile' and _snapshot_malformed(conn):
            return photo, _unavailable_critique(photo, 'normalization_snapshot_unavailable')
        normalizer = PercentileNormalizer.from_snapshot(conn, settings)
        has_overrides = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='photo_scoring_overrides'"
        ).fetchone()
        overrides = get_photo_scoring_overrides(conn, [path]).get(path) if has_overrides else None
        try:
            result = _build_rule_critique(photo, config=config, normalizer=normalizer,
                                          overrides=overrides)
        except (TypeError, ValueError, OverflowError) as error:
            # SQLite affinity permits malformed text even in numeric columns.
            # Keep the valid stored score; never invent a replacement breakdown.
            logger.info("Native explanation unavailable (%s)", type(error).__name__)
            result = _unavailable_critique(photo, 'invalid_scoring_inputs')
    return photo, result


@router.get("/api/critique", response_model=MediaCritiqueResponse, response_model_exclude_unset=True)
async def api_critique(
    path: str = Query(...),
    mode: str = Query("rule"),
    lang: Optional[str] = Query(None),
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Get AI critique for a photo's score. Strictly read-only.

    Modes:
      - rule: Fast rule-based analysis (always available)
      - vlm: the rule critique plus the VLM critique already cached for the
        photo (and its stored translation when ``lang`` selects one). Nothing is generated,
        translated or written here: ``vlm_available`` tells the client whether
        ``POST /api/critique/vlm`` can produce one for this caller.
    """
    if not VIEWER_CONFIG.get('features', {}).get('show_critique', True):
        raise HTTPException(status_code=403, detail="Critique feature is disabled")

    photo, result = await run_sync(_load_rule_critique, path, user)
    if mode == 'vlm':
        async with get_async_db() as conn:
            await _attach_cached_vlm_critique(conn, photo['path'], result, lang, user)
    return result


class CritiqueVlmRequest(BaseModel):
    path: str
    lang: Optional[str] = None
    refresh: bool = False


@router.post("/api/critique/vlm", response_model=MediaCritiqueResponse, response_model_exclude_unset=True)
async def api_generate_vlm_critique(
    body: CritiqueVlmRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Generate (or, with ``refresh``, regenerate) and store the VLM critique.

    Edition only. Concurrent requests for the same photo share one generation.
    When ``lang`` matches ``translation.target_language`` the critique is also
    translated and the translation stored.
    """
    if not VIEWER_CONFIG.get('features', {}).get('show_critique', True):
        raise HTTPException(status_code=403, detail="Critique feature is disabled")

    photo, result = await run_sync(_load_rule_critique, body.path, user)
    async with get_async_db() as conn:
        await _generate_vlm_critique(conn, photo, result, body.lang, body.refresh)
    return result


async def _cached_vlm_columns(conn, path):
    if 'vlm_critique' not in get_existing_columns():
        return None, None
    cur = await conn.execute(
        "SELECT vlm_critique, vlm_critique_translated FROM photos WHERE path = ?", [path]
    )
    row = await cur.fetchone()
    await cur.close()
    return (row['vlm_critique'], row['vlm_critique_translated']) if row else (None, None)


def _vlm_generation_possible(user):
    """True when the model is enabled and configured and the caller may run it."""
    return bool(
        is_edition_authenticated(user)
        and VIEWER_CONFIG.get('features', {}).get('show_vlm_critique', False)
        # GET must never import torch: on an unresolved ``auto`` profile this stays
        # optimistic and the POST discovers the truth.
        and not vlm_known_unavailable()
    )


async def _attach_cached_vlm_critique(conn, path, result, lang, user):
    """Attach the stored VLM critique to the rule result; never generate, translate or write."""
    text, translated = await _cached_vlm_columns(conn, path)
    if not text:
        result['vlm_available'] = await asyncio.to_thread(_vlm_generation_possible, user)
        return
    # A translation is served only when it is already stored: producing one runs a model.
    wants_translation = bool(translation_target(lang))
    result['vlm_critique'] = (translated if wants_translation else None) or text
    result['vlm_source'] = 'cached'
    result['vlm_translation_missing'] = wants_translation and not translated


async def _generate_vlm_critique(conn, photo, result, lang, refresh):
    """Attach a cached or freshly generated VLM critique, storing what it produces."""
    path = photo['path']
    can_cache = 'vlm_critique' in get_existing_columns()
    text, translated = (None, None) if refresh else await _cached_vlm_columns(conn, path)
    source = 'cached'

    if not text:
        cur = await conn.execute("SELECT thumbnail FROM photos WHERE path = ?", [path])
        row = await cur.fetchone()
        await cur.close()
        thumbnail = row['thumbnail'] if row else None

        async def generate_and_store():
            # VLM inference is GPU/CPU-bound and blocking: run it off the event loop.
            generated = await asyncio.to_thread(_get_vlm_critique, photo, result, thumbnail)
            if generated and can_cache:
                # Only the leader of a shared run stores the text (and drops the
                # translation of the text it replaces); joiners resume after this.
                await conn.execute(
                    "UPDATE photos SET vlm_critique = ?, vlm_critique_translated = NULL WHERE path = ?",
                    [generated, path],
                )
                await conn.commit()
            return generated

        try:
            text, _ = await _critique_flights.run(path, generate_and_store)
        except GenerationInterrupted:
            raise HTTPException(status_code=503, detail="VLM critique generation was interrupted")
        translated = None
        source = 'generated'

    if not text:
        result['vlm_available'] = False
        return

    target_lang = translation_target(lang)
    if target_lang:
        if not translated:
            translated = await asyncio.to_thread(translate_text, text, target_lang)
            if translated and can_cache:
                await conn.execute(
                    "UPDATE photos SET vlm_critique_translated = ? WHERE path = ? AND vlm_critique = ?",
                    [translated, path, text],
                )
                await conn.commit()
        if translated:
            text = translated

    result['vlm_critique'] = text
    result['vlm_source'] = source


_DEFAULT_VLM_PROMPT = (
    "You are an expert photography critic reviewing a {category} photograph "
    "that Facet's metrics scored {aggregate}/10 overall.\n"
    "Measured metrics (0-10):\n{breakdown}\n"
    "{penalties}"
    "Camera settings: {exif}.\n\n"
    "Judge the picture from what you actually see. Treat the metrics as context "
    "to confirm or contradict from the pixels, never restate the numbers. First "
    "perceive the scene, then register the feeling it evokes, then judge it, then "
    "advise. Write exactly three titled sections in compact prose, no bullet "
    "lists:\n"
    "Observation: one or two sentences naming the subject, the moment and the "
    "framing you see.\n"
    "Assessment: three to four sentences giving a short verdict on each of "
    "composition, color & light, focus/depth-of-field & technical execution, and "
    "subject & moment; say where the pixels back the metrics or contradict them, "
    "and what the image makes a viewer feel.\n"
    "Suggestions: at most three concrete fixes for the weakest dimensions above, "
    "mixing shooting and editing advice."
)


def _build_vlm_prompt(rule_critique, photo):
    """Fill the configured critique prompt template with the rule breakdown and EXIF."""
    vlm_cfg = _FULL_CONFIG.get('critique', {}).get('vlm', {})
    template = vlm_cfg.get('prompt_template') or _DEFAULT_VLM_PROMPT

    lines = [f"- {item['metric']}: {item['value']} (weight {item['weight']:.0%}, higher quality is better)"
             for item in rule_critique.get('breakdown', [])[:12]]
    breakdown = '\n'.join(lines) or '- no per-metric data available'

    advisory_keys = list(rule_critique.get('penalties', {}))
    advisories = f"Detected conditions: {', '.join(advisory_keys)}.\n" if advisory_keys else ''

    stored = rule_critique.get('aggregate')
    current = rule_critique.get('current_formula_score')
    stored_text = f"{stored:.2f}" if stored is not None else 'unavailable'
    if current is not None:
        scope = ("These inputs describe a current-formula recalculation, not verified "
                 f"historical publication provenance. Stored score: {stored_text}. "
                 f"Current formula: {current:.2f}. Net adjustments and rounding: "
                 f"{rule_critique.get('native_adjustment'):.2f}.\n")
    else:
        scope = f"Stored score: {stored_text}. No current-formula breakdown is available.\n"

    exif_parts = []
    if photo.get('f_stop'):
        exif_parts.append(f"f/{photo['f_stop']}")
    if photo.get('shutter_speed'):
        exif_parts.append(f"{photo['shutter_speed']}s")
    if photo.get('iso'):
        exif_parts.append(f"ISO {photo['iso']}")
    if photo.get('focal_length'):
        exif_parts.append(f"{photo['focal_length']}mm")
    exif = ', '.join(exif_parts) or 'unknown'

    aggregate = current if current is not None else stored
    prompt = template.format(
        category=rule_critique.get('category', 'photo'),
        aggregate=f"{aggregate:.1f}" if aggregate is not None else 'unscored',
        breakdown=breakdown,
        penalties=advisories + scope,
        exif=exif,
    )

    # A custom template that omits {penalties}, or renders only part of it
    # ({penalties[0]}, {penalties:.20}), must still carry the scope statement.
    if scope not in prompt:
        prompt += "\n" + scope
    return prompt


def _load_critique_image(path, thumbnail_bytes):
    """Build the PIL image fed to the VLM: stored thumbnail, else decoded original.

    The stored 640px thumbnail is preferred — it exists for every scored photo
    including RAW files, which PIL cannot decode from disk.
    """
    from io import BytesIO

    from PIL import Image

    if thumbnail_bytes:
        return Image.open(BytesIO(thumbnail_bytes)).convert('RGB')

    from api.path_validation import resolve_photo_disk_path
    from utils.image_loading import open_nonraw_image

    disk_path = resolve_photo_disk_path(path)
    img = open_nonraw_image(disk_path)
    img.thumbnail((640, 640))
    return img


def _get_vlm_critique(photo, rule_critique, thumbnail_bytes):
    """Generate a VLM critique; None when the VLM is unavailable or fails."""
    try:
        if not VIEWER_CONFIG.get('features', {}).get('show_vlm_critique', False):
            return None

        vlm_config = resolve_vlm_config()
        if not vlm_config:
            return None

        tagger = get_or_load_vlm_tagger(vlm_config)
        prompt = _build_vlm_prompt(rule_critique, photo)
        img = _load_critique_image(photo['path'], thumbnail_bytes)

        max_new_tokens = int(_FULL_CONFIG.get('critique', {}).get('vlm', {}).get('max_new_tokens', 320))
        with vlm_generate_lock, vlm_accelerator_lock(tagger):
            response = tagger.generate(img, prompt, max_new_tokens=max_new_tokens)
        response = (response or '').strip()
        return response or None

    except Exception:
        licensing.reraise_if_refused()
        logger.exception("VLM critique failed")
        return None
