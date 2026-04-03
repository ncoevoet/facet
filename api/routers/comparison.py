"""
Comparison router -- pairwise photo ranking, weight optimization, downloads.

"""

import json
import logging
import os
import shutil
import asyncio
import sqlite3
import subprocess
import sys
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Literal, Optional

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from api.auth import CurrentUser, get_optional_user, require_edition
from api.config import (
    VIEWER_CONFIG, _CONFIG_PATH, FACET_SCRIPT,
    get_comparison_mode_settings, map_disk_path,
    reload_config, _stats_cache, get_all_scan_directories,
    is_multi_user_enabled,
)
from api.database import get_db
from api.db_helpers import get_visibility_clause
from db import DEFAULT_DB_PATH
from utils.image_loading import RAW_EXTENSIONS

router = APIRouter(tags=["comparison"])

# Mapping from optimizer DB column names to config weight names (used by learned_weights and confidence)
METRIC_NAME_MAPPING = {
    # Primary quality
    'aesthetic': 'aesthetic',
    'quality_score': 'quality',
    'face_quality': 'face_quality',
    'face_sharpness': 'face_sharpness',
    'eye_sharpness': 'eye_sharpness',
    'tech_sharpness': 'tech_sharpness',
    # Composition
    'comp_score': 'composition',
    'power_point_score': 'power_point',
    'leading_lines_score': 'leading_lines',
    # Technical
    'exposure_score': 'exposure',
    'color_score': 'color',
    'contrast_score': 'contrast',
    'dynamic_range_stops': 'dynamic_range',
    'mean_saturation': 'saturation',
    'noise_sigma': 'noise',
    # Bonuses
    'isolation_bonus': 'isolation',
    # Supplementary PyIQA
    'aesthetic_iaa': 'aesthetic_iaa',
    'face_quality_iqa': 'face_quality_iqa',
    'liqe_score': 'liqe',
    # Subject saliency
    'subject_sharpness': 'subject_sharpness',
    'subject_prominence': 'subject_prominence',
    'subject_placement': 'subject_placement',
    'bg_separation': 'bg_separation',
}


# ---------------------------------------------------------------------------
# Pydantic request bodies
# ---------------------------------------------------------------------------

class ComparisonSubmitBody(BaseModel):
    photo_a: str
    photo_b: str
    winner: str
    category: Optional[str] = None


class ComparisonEditBody(BaseModel):
    id: int
    winner: str


class ComparisonDeleteBody(BaseModel):
    id: int


class UpdateWeightsBody(BaseModel):
    category: str
    weights: dict
    modifiers: Optional[dict] = None
    filters: Optional[dict] = None
    recalculate: bool = False


class PreviewScoreBody(BaseModel):
    path: str
    weights: dict = {}


class SuggestFiltersBody(BaseModel):
    path: str
    target_category: str


class OverrideCategoryBody(BaseModel):
    path: str
    category: str


class SaveSnapshotBody(BaseModel):
    category: str = 'others'
    description: str = ''
    accuracy_before: Optional[float] = None
    accuracy_after: Optional[float] = None
    comparisons_used: Optional[int] = None
    created_by: str = 'manual'


class RestoreWeightsBody(BaseModel):
    snapshot_id: int


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/api/comparison/next_pair")
def api_comparison_next_pair(
    strategy: str = Query('uncertainty'),
    category: Optional[str] = Query(None),
    user: CurrentUser = Depends(require_edition),
):
    """Get the next pair of photos for comparison."""
    from comparison import PairSelector

    selector = PairSelector(DEFAULT_DB_PATH)
    pair = selector.get_next_pair(strategy=strategy, category=category)

    if not pair:
        return {'error': 'No more pairs available for comparison'}

    return pair


def _validate_and_resolve(path: str, user: Optional[CurrentUser]):
    """Validate a photo path against DB and resolve to disk path.

    Returns (db_path, real_disk) or raises HTTPException.
    """
    if not path:
        raise HTTPException(status_code=400, detail='path required')

    with get_db() as conn:
        user_id = user.user_id if user else None
        vis_sql, vis_params = get_visibility_clause(user_id)
        row = conn.execute(
            f"SELECT path FROM photos WHERE path = ? AND {vis_sql}",
            [path] + vis_params
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail='File not found')

    db_path = row['path']
    disk_path = map_disk_path(db_path)
    real_disk = os.path.realpath(disk_path)
    if is_multi_user_enabled():
        if not any(real_disk.startswith(os.path.realpath(d) + os.sep) for d in get_all_scan_directories()):
            raise HTTPException(status_code=404, detail='File not found')

    if not os.path.isfile(real_disk):
        raise HTTPException(status_code=404, detail='File not found on disk')

    return db_path, real_disk


@router.get("/api/download/options")
def api_download_options(
    path: str = Query(...),
    is_shared: bool = Query(False),
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Return available download types for a photo."""
    from api.raw_processing import find_companion_raw, get_darktable_profiles

    db_path, real_disk = _validate_and_resolve(path, user)

    options: list[dict] = [{'type': 'original', 'label': 'original'}]

    raw_path = find_companion_raw(real_disk)
    if raw_path:
        for profile_name in get_darktable_profiles():
            options.append({'type': 'darktable', 'profile': profile_name, 'label': profile_name})
        if not is_shared:
            ext = Path(raw_path).suffix.lstrip('.').lower()
            options.append({'type': 'raw', 'label': 'raw', 'extension': ext})

    return {'options': options}


@router.get("/api/download")
async def api_download_single(
    path: str = Query(...),
    type: Literal['original', 'darktable', 'raw'] = Query('original'),
    profile: str = Query(''),
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Download a single photo file (validated against database).

    Supports three download types via the ``type`` query parameter:

    - ``original`` — serve the file as-is (JPG/HEIF) or rawpy-converted (RAW).
    - ``darktable`` — convert companion RAW with a named darktable profile.
    - ``raw`` — serve the companion RAW file as-is.
    """
    from api.raw_processing import convert_raw_to_jpeg, convert_raw_darktable_async, find_companion_raw

    db_path, real_disk = _validate_and_resolve(path, user)

    quality = VIEWER_CONFIG['display'].get('image_jpeg_quality', 96)
    stem = os.path.splitext(os.path.basename(db_path))[0]

    # --- Darktable profile export ---
    if type == 'darktable':
        raw_path = find_companion_raw(real_disk)
        if not raw_path:
            # Fall back to original when no RAW companion exists
            return _serve_original(real_disk, db_path, quality)

        try:
            jpeg_bytes = await convert_raw_darktable_async(raw_path, profile, quality)
        except ValueError:
            raise HTTPException(status_code=400, detail=f'Unknown darktable profile: {profile}')
        except Exception:
            logger.exception("Darktable conversion failed: %s (profile=%s)", real_disk, profile)
            raise HTTPException(status_code=500, detail='Failed to convert RAW file')

        safe_profile = profile.replace('"', '').replace('/', '_')
        download_name = f'{stem}_{safe_profile}.jpg'
        return StreamingResponse(
            BytesIO(jpeg_bytes),
            media_type='image/jpeg',
            headers={'Content-Disposition': f'attachment; filename="{download_name}"'},
        )

    # --- RAW file download ---
    if type == 'raw':
        raw_path = find_companion_raw(real_disk)
        if not raw_path:
            return _serve_original(real_disk, db_path, quality)

        return FileResponse(
            raw_path,
            media_type='application/octet-stream',
            filename=os.path.basename(raw_path),
        )

    # --- Original file download ---
    return _serve_original(real_disk, db_path, quality)


def _serve_original(real_disk: str, db_path: str, quality: int):
    """Serve a photo file as-is, converting standalone RAW via rawpy."""
    from api.raw_processing import convert_raw_to_jpeg

    if Path(real_disk).suffix.lower() in RAW_EXTENSIONS:
        try:
            jpeg_bytes = convert_raw_to_jpeg(real_disk, quality)
        except Exception:
            logger.exception("Failed to convert RAW file for download: %s", real_disk)
            raise HTTPException(status_code=500, detail='Failed to convert RAW file')

        download_name = os.path.splitext(os.path.basename(db_path))[0] + '.jpg'
        return StreamingResponse(
            BytesIO(jpeg_bytes),
            media_type='image/jpeg',
            headers={'Content-Disposition': f'attachment; filename="{download_name}"'},
        )

    return FileResponse(
        real_disk,
        media_type='application/octet-stream',
        filename=os.path.basename(real_disk),
    )


@router.post("/api/comparison/submit")
def api_comparison_submit(
    body: ComparisonSubmitBody,
    user: CurrentUser = Depends(require_edition),
):
    """Submit a comparison result."""
    from comparison import ComparisonManager

    if not body.photo_a or not body.photo_b or not body.winner:
        raise HTTPException(status_code=400, detail='Missing required fields')

    manager = ComparisonManager(DEFAULT_DB_PATH)
    success = manager.submit_comparison(
        body.photo_a, body.photo_b, body.winner, body.category,
        user_id=user.user_id,
    )

    if success:
        stats = manager.get_statistics()
        return {'success': True, 'stats': stats}
    else:
        raise HTTPException(status_code=500, detail='Failed to save comparison')


@router.post("/api/comparison/reset")
def api_comparison_reset(
    user: CurrentUser = Depends(require_edition),
):
    """Reset all comparison data."""
    with get_db() as conn:
        try:
            conn.execute("DELETE FROM comparisons")
            conn.execute("DELETE FROM learned_scores")
            conn.execute("DELETE FROM weight_optimization_runs")
            conn.commit()
            return {'success': True, 'message': 'All comparison data has been reset'}
        except sqlite3.Error:
            logger.exception("Failed to reset comparison data")
            raise HTTPException(status_code=500, detail='Reset failed')


@router.post("/api/recalculate")
async def api_recalculate(
    user: CurrentUser = Depends(require_edition),
):
    """Recalculate all categories and aggregate scores.

    Runs the same logic as ``python facet.py --recompute-average``.
    """
    try:
        config_path = str(_CONFIG_PATH)

        proc = await asyncio.create_subprocess_exec(
            sys.executable, FACET_SCRIPT, '--recompute-average', '--config', config_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=300)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise HTTPException(
                status_code=500,
                detail='Recalculation timed out (>5 minutes). Run manually with: python facet.py --recompute-average',
            )

        stdout = stdout_bytes.decode(errors='replace')
        stderr = stderr_bytes.decode(errors='replace')

        if proc.returncode == 0:
            return {
                'success': True,
                'message': 'Recalculation complete',
                'output': stdout,
            }
        else:
            raise HTTPException(
                status_code=500,
                detail=f'Recalculation failed: {stderr or stdout}',
            )

    except HTTPException:
        raise
    except Exception:
        logger.exception("Recalculation failed")
        raise HTTPException(status_code=500, detail='Recalculation failed')


@router.post("/api/config/update_weights")
async def api_update_weights(
    body: UpdateWeightsBody,
    user: CurrentUser = Depends(require_edition),
):
    """Update category weights in scoring_config.json."""
    try:
        if not body.category:
            raise HTTPException(status_code=400, detail='Missing category')
        if not body.weights:
            raise HTTPException(status_code=400, detail='Missing weights')

        config_path = str(_CONFIG_PATH)

        # Read current config
        with open(config_path, 'r') as f:
            config = json.load(f)

        # Create backup
        backup_path = f"{config_path}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        shutil.copy2(config_path, backup_path)

        # Update weights in v4 config format (categories is a list)
        categories = config.get('categories', [])
        found = False
        for cat in categories:
            if cat.get('name') == body.category:
                if 'weights' not in cat:
                    cat['weights'] = {}
                cat['weights'].update(body.weights)
                if body.modifiers is not None:
                    cat['modifiers'] = body.modifiers
                if body.filters is not None:
                    cat['filters'] = body.filters
                found = True
                break
        if not found:
            raise HTTPException(status_code=404, detail=f'Category "{body.category}" not found in config')

        # Save updated config
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)

        reload_config()
        _stats_cache.clear()

        result = {
            'success': True,
            'message': f'Weights updated for category "{body.category}"',
            'backup': backup_path,
        }

        # Optionally trigger recalculation (only for the updated category)
        if body.recalculate:
            try:
                proc = await asyncio.create_subprocess_exec(
                    sys.executable, FACET_SCRIPT, '--recompute-category', body.category,
                    '--config', config_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                try:
                    stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=300)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.communicate()
                    result['recalculated'] = False
                    result['recalculate_error'] = 'Recalculation timed out'
                else:
                    if proc.returncode == 0:
                        result['recalculated'] = True
                        result['message'] += ' and scores recalculated'
                    else:
                        result['recalculated'] = False
                        result['recalculate_error'] = (stderr_bytes or stdout_bytes).decode(errors='replace')
            except Exception:
                logger.exception("Post-update recalculation failed for category %s", body.category)
                result['recalculated'] = False
                result['recalculate_error'] = 'Recalculation failed'

        return result

    except HTTPException:
        raise
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail='Config file not found')
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail='Invalid JSON in config')
    except Exception:
        logger.exception("Failed to update weights")
        raise HTTPException(status_code=500, detail='Failed to update weights')


@router.get("/api/comparison/stats")
def api_comparison_stats(
    user: CurrentUser = Depends(require_edition),
):
    """Get comparison statistics."""
    from comparison import ComparisonManager
    manager = ComparisonManager(DEFAULT_DB_PATH)
    stats = manager.get_statistics()
    settings = get_comparison_mode_settings()
    stats['min_comparisons_for_optimization'] = settings.get('min_comparisons_for_optimization', 30)
    return stats


@router.get("/api/comparison/photo_metrics")
def api_comparison_photo_metrics(
    paths: str = Query(''),
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Get raw metrics for photos (for client-side score preview).

    Query params:
        paths: Comma-separated list of photo paths (max 2)
    """
    if not paths:
        raise HTTPException(status_code=400, detail='Missing paths parameter')

    path_list = [p.strip() for p in paths.split(',') if p.strip()]
    if len(path_list) > 2:
        raise HTTPException(status_code=400, detail='Maximum 2 paths allowed')

    # Columns needed for score calculation
    metric_columns = [
        'path', 'category', 'aggregate',
        'aesthetic', 'face_quality', 'eye_sharpness', 'tech_sharpness',
        'color_score', 'exposure_score', 'comp_score', 'isolation_bonus',
        'quality_score', 'contrast_score', 'dynamic_range_stops',
        'noise_sigma', 'histogram_bimodality', 'mean_saturation',
        'is_blink', 'is_silhouette', 'face_ratio', 'face_count',
        'scoring_model', 'tags', 'is_monochrome', 'leading_lines_score',
        'power_point_score', 'histogram_spread', 'mean_luminance',
        'aesthetic_iaa', 'face_quality_iqa', 'liqe_score',
        'subject_sharpness', 'subject_prominence', 'subject_placement', 'bg_separation',
    ]

    user_id = user.user_id if user else None
    vis_sql, vis_params = get_visibility_clause(user_id)

    with get_db() as conn:
        placeholders = ','.join(['?' for _ in path_list])
        cols = ', '.join(metric_columns)
        query = f"SELECT {cols} FROM photos WHERE path IN ({placeholders}) AND {vis_sql}"
        rows = conn.execute(query, path_list + vis_params).fetchall()

    result = {}
    for row in rows:
        row_dict = dict(row)
        result[row_dict['path']] = row_dict

    return result


@router.get("/api/comparison/category_weights")
def api_comparison_category_weights(
    category: Optional[str] = Query(None),
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Get weights for a category (or all categories)."""
    from config import ScoringConfig

    config = ScoringConfig(validate=False)

    # All possible weight keys from the optimizer's scoring components
    all_weight_keys = [f'{v}_percent' for v in METRIC_NAME_MAPPING.values()]

    if category:
        # Return weights for specific category, padded with all components
        for cat in config.get_categories():
            if cat['name'] == category:
                weights = cat.get('weights', {})
                for key in all_weight_keys:
                    if key not in weights:
                        weights[key] = 0
                return {
                    'category': category,
                    'weights': weights,
                    'modifiers': cat.get('modifiers', {}),
                    'filters': cat.get('filters', {}),
                    'priority': cat.get('priority', 100),
                }
        raise HTTPException(status_code=404, detail=f'Category not found: {category}')
    else:
        # Return all categories with their weights
        categories = []
        for cat in config.get_categories():
            categories.append({
                'name': cat['name'],
                'priority': cat.get('priority', 100),
                'weights': cat.get('weights', {}),
                'modifiers': cat.get('modifiers', {}),
                'filters': cat.get('filters', {}),
            })
        return {'categories': categories}


@router.get("/api/comparison/learned_weights")
def api_comparison_learned_weights(
    category: Optional[str] = Query(None),
    include_ties: str = Query('true'),
    use_cv: str = Query('false'),
    user: CurrentUser = Depends(require_edition),
):
    """Get suggested weights based on comparison outcomes.

    Uses Direct Preference Optimization to maximize comparison prediction accuracy.
    """
    include_ties_bool = include_ties.lower() == 'true'
    use_cv_bool = use_cv.lower() == 'true'

    from optimization import WeightOptimizer

    optimizer = WeightOptimizer(DEFAULT_DB_PATH)

    # Check if we have enough comparisons
    with get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM comparisons WHERE winner IN ('a', 'b', 'tie')"
        ).fetchone()
        count = row[0] if row else 0

    settings = get_comparison_mode_settings()
    min_comparisons = settings.get('min_comparisons_for_optimization', 30)

    if count < min_comparisons:
        return {
            'available': False,
            'message': f'Need at least {min_comparisons} comparisons (have {count})',
            'comparisons': count,
            'min_required': min_comparisons,
        }

    # Use direct preference optimization
    try:
        if use_cv_bool:
            result = optimizer.optimize_weights_with_cv(
                category=category,
                min_comparisons=min_comparisons,
                include_ties=include_ties_bool,
            )
        else:
            result = optimizer.optimize_weights_direct(
                category=category,
                min_comparisons=min_comparisons,
                include_ties=include_ties_bool,
            )

        if 'error' in result:
            return {
                'available': False,
                'message': result['error'],
                'comparisons': count,
            }

        # All scoring components (for showing all in UI, even if 0)
        all_components = list(METRIC_NAME_MAPPING.keys())

        # Convert weights to percent format for UI with correct names
        current_weights = {}
        suggested_weights = {}

        # Include ALL components, defaulting to 0 if not present
        for db_key in all_components:
            mapped_key = METRIC_NAME_MAPPING.get(db_key, db_key)
            current_val = result.get('old_weights', {}).get(db_key, 0.0)
            suggested_val = result.get('new_weights', {}).get(db_key, 0.0)
            current_weights[f'{mapped_key}_percent'] = round(current_val * 100)
            suggested_weights[f'{mapped_key}_percent'] = round(suggested_val * 100)

        # Count mispredicted comparisons for display
        per_comparison = result.get('per_comparison', [])
        mispredicted = [c for c in per_comparison if not c.get('predicted_correct', True)]

        response = {
            'available': True,
            'current_weights': current_weights,
            'suggested_weights': suggested_weights,
            'accuracy_before': result.get('accuracy_before', 0),
            'accuracy_after': result.get('accuracy_after', 0),
            'improvement': result.get('improvement', 0),
            'suggest_changes': result.get('suggest_changes', False),
            'comparisons_used': result.get('comparisons_used', 0),
            'ties_included': result.get('ties_included', 0),
            'mispredicted_count': len(mispredicted),
            'category': category,
            'method': result.get('method', 'direct_preference_optimization'),
        }

        # Add CV-specific metrics if available
        if use_cv_bool:
            response['cv_accuracy'] = result.get('cv_accuracy', 0)
            response['cv_std'] = result.get('cv_std', 0)
            response['fold_results'] = result.get('fold_results', [])

        return response

    except Exception:
        logger.exception("Weight optimization failed")
        return {
            'available': False,
            'message': 'Optimization error',
            'comparisons': count,
        }


@router.post("/api/comparison/preview_score")
def api_comparison_preview_score(
    body: PreviewScoreBody,
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Preview score with custom weights."""
    from config import ScoringConfig

    if not body.path:
        raise HTTPException(status_code=400, detail='Missing path parameter')

    # Get photo metrics
    user_id = user.user_id if user else None
    vis_sql, vis_params = get_visibility_clause(user_id)

    with get_db() as conn:
        row = conn.execute(f"SELECT * FROM photos WHERE path = ? AND {vis_sql}", [body.path] + vis_params).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail='Photo not found')

    metrics = dict(row)
    original_score = metrics.get('aggregate', 0)
    category = metrics.get('category', 'others')

    # Create scorer with custom weights for preview
    config = ScoringConfig(validate=False)

    # Calculate preview score using simplified weighted sum
    weights = config.get_weights(category)

    # Override with custom weights (convert from percent to decimal)
    for key, value in body.weights.items():
        if key.endswith('_percent'):
            base_key = key[:-8]
            weights[base_key] = value / 100
        else:
            weights[key] = value / 100

    # Simple weighted sum calculation
    preview_score = 0.0
    weight_map = {
        'aesthetic': 'aesthetic',
        'face_quality': 'face_quality',
        'eye_sharpness': 'eye_sharpness',
        'tech_sharpness': 'tech_sharpness',
        'exposure': 'exposure_score',
        'composition': 'comp_score',
        'color': 'color_score',
        'contrast': 'contrast_score',
        'quality': 'quality_score',
        'dynamic_range': 'dynamic_range_stops',
        'isolation': 'isolation_bonus',
        'leading_lines': 'leading_lines_score',
        # Supplementary PyIQA
        'aesthetic_iaa': 'aesthetic_iaa',
        'face_quality_iqa': 'face_quality_iqa',
        'liqe': 'liqe_score',
        # Subject saliency
        'subject_sharpness': 'subject_sharpness',
        'subject_prominence': 'subject_prominence',
        'subject_placement': 'subject_placement',
        'bg_separation': 'bg_separation',
    }

    for weight_key, metric_key in weight_map.items():
        weight = weights.get(weight_key, 0)
        if weight > 0:
            value = metrics.get(metric_key) or 0
            # Special handling for isolation_bonus (scale 1-3 to 0-10)
            if metric_key == 'isolation_bonus' and value:
                value = min(10, (value - 1) * 5)
            # Special handling for dynamic_range (scale to 0-10)
            if metric_key == 'dynamic_range_stops' and value:
                value = min(10, value / 0.6)  # Assuming 6 stops = 10
            preview_score += value * weight

    # Add bonus if present
    bonus = weights.get('bonus', 0)
    preview_score = min(10, preview_score + bonus)

    return {
        'path': body.path,
        'category': category,
        'original_score': original_score,
        'preview_score': round(preview_score, 2),
        'delta': round(preview_score - (original_score or 0), 2),
    }


@router.post("/api/comparison/suggest_filters")
def api_comparison_suggest_filters(
    body: SuggestFiltersBody,
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Suggest filter changes when moving a photo to another category."""
    from config import ScoringConfig

    if not body.path or not body.target_category:
        raise HTTPException(status_code=400, detail='Missing path or target_category')

    # Get photo metrics
    user_id = user.user_id if user else None
    vis_sql, vis_params = get_visibility_clause(user_id)

    with get_db() as conn:
        row = conn.execute(f"SELECT * FROM photos WHERE path = ? AND {vis_sql}", [body.path] + vis_params).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail='Photo not found')

    metrics = dict(row)
    current_category = metrics.get('category', 'others')

    if current_category == body.target_category:
        return {
            'current_category': current_category,
            'target_category': body.target_category,
            'conflicts': [],
            'suggestions': [],
            'message': 'Photo is already in the target category',
        }

    config = ScoringConfig(validate=False)

    # Build photo_data dict for filter evaluation
    photo_data = {
        'tags': metrics.get('tags', '') or '',
        'face_count': metrics.get('face_count', 0) or 0,
        'face_ratio': metrics.get('face_ratio', 0) or 0,
        'is_silhouette': metrics.get('is_silhouette', 0),
        'is_group_portrait': metrics.get('is_group_portrait', 0),
        'is_monochrome': metrics.get('is_monochrome', 0),
        'mean_luminance': metrics.get('mean_luminance', 0.5),
        'iso': metrics.get('ISO'),
        'shutter_speed': metrics.get('shutter_speed'),
        'focal_length': metrics.get('focal_length'),
        'f_stop': metrics.get('f_stop'),
    }

    # Get target category config
    target_config = None
    for cat in config.get_categories():
        if cat['name'] == body.target_category:
            target_config = cat
            break

    if not target_config:
        raise HTTPException(status_code=404, detail=f'Category not found: {body.target_category}')

    # Analyze conflicts between photo values and target category filters
    target_filters = target_config.get('filters', {})
    conflicts = []
    suggestions = []

    # Numeric filter analysis
    numeric_mappings = {
        'face_ratio': ('face_ratio', 'Face ratio'),
        'face_count': ('face_count', 'Face count'),
        'iso': ('iso', 'ISO'),
        'shutter_speed': ('shutter_speed', 'Shutter speed'),
        'luminance': ('mean_luminance', 'Luminance'),
        'focal_length': ('focal_length', 'Focal length'),
        'f_stop': ('f_stop', 'F-stop'),
    }

    for filter_key, (data_key, label) in numeric_mappings.items():
        min_val = target_filters.get(f'{filter_key}_min')
        max_val = target_filters.get(f'{filter_key}_max')
        actual = photo_data.get(data_key)

        if min_val is not None:
            if actual is None:
                conflicts.append({
                    'type': 'missing_value',
                    'filter': f'{filter_key}_min',
                    'required': min_val,
                    'actual': None,
                    'message': f'{label} is required but missing',
                })
            elif actual < min_val:
                conflicts.append({
                    'type': 'below_minimum',
                    'filter': f'{filter_key}_min',
                    'required': min_val,
                    'actual': actual,
                    'message': f'{label} ({actual:.3f}) is below minimum ({min_val})',
                })
                suggestions.append({
                    'type': 'lower_minimum',
                    'filter': f'{filter_key}_min',
                    'current': min_val,
                    'suggested': round(actual * 0.9, 4),  # 10% margin
                    'message': f'Lower {filter_key}_min from {min_val} to {round(actual * 0.9, 4)}',
                })

        if max_val is not None:
            if actual is None:
                conflicts.append({
                    'type': 'missing_value',
                    'filter': f'{filter_key}_max',
                    'required': max_val,
                    'actual': None,
                    'message': f'{label} is required but missing',
                })
            elif actual > max_val:
                conflicts.append({
                    'type': 'above_maximum',
                    'filter': f'{filter_key}_max',
                    'required': max_val,
                    'actual': actual,
                    'message': f'{label} ({actual:.3f}) is above maximum ({max_val})',
                })
                suggestions.append({
                    'type': 'raise_maximum',
                    'filter': f'{filter_key}_max',
                    'current': max_val,
                    'suggested': round(actual * 1.1, 4),  # 10% margin
                    'message': f'Raise {filter_key}_max from {max_val} to {round(actual * 1.1, 4)}',
                })

    # Boolean filter analysis
    bool_mappings = {
        'has_face': ('Has face', lambda pd: (pd.get('face_count') or 0) > 0),
        'is_monochrome': ('Monochrome', lambda pd: bool(pd.get('is_monochrome', 0))),
        'is_silhouette': ('Silhouette', lambda pd: bool(pd.get('is_silhouette', 0))),
        'is_group_portrait': ('Group portrait', lambda pd: bool(pd.get('is_group_portrait', 0))),
    }

    for filter_key, (label, getter) in bool_mappings.items():
        required = target_filters.get(filter_key)
        if required is not None:
            actual = getter(photo_data)
            if actual != required:
                conflicts.append({
                    'type': 'boolean_mismatch',
                    'filter': filter_key,
                    'required': required,
                    'actual': actual,
                    'message': f'{label} is {actual}, but category requires {required}',
                })
                suggestions.append({
                    'type': 'change_boolean',
                    'filter': filter_key,
                    'current': required,
                    'suggested': actual,
                    'message': f'Change {filter_key} from {required} to {actual}',
                })

    # Tag filter analysis
    required_tags = target_filters.get('required_tags', [])
    excluded_tags = target_filters.get('excluded_tags', [])
    match_mode = target_filters.get('tag_match_mode', 'any')

    if required_tags:
        tags_str = photo_data.get('tags') or ''
        photo_tags = [t.strip().lower() for t in tags_str.split(',') if t.strip()]
        required_lower = [t.lower() for t in required_tags]

        if match_mode == 'any':
            if not any(tag in photo_tags for tag in required_lower):
                conflicts.append({
                    'type': 'missing_tags',
                    'filter': 'required_tags',
                    'required': required_tags,
                    'actual': photo_tags,
                    'message': f'Photo needs at least one of: {", ".join(required_tags)}',
                })
                suggestions.append({
                    'type': 'remove_tag_requirement',
                    'filter': 'required_tags',
                    'message': 'Remove or modify required_tags filter',
                })
        else:  # all
            missing = [t for t in required_lower if t not in photo_tags]
            if missing:
                conflicts.append({
                    'type': 'missing_tags',
                    'filter': 'required_tags',
                    'required': required_tags,
                    'actual': photo_tags,
                    'missing': missing,
                    'message': f'Photo is missing required tags: {", ".join(missing)}',
                })

    if excluded_tags:
        tags_str = photo_data.get('tags') or ''
        photo_tags = [t.strip().lower() for t in tags_str.split(',') if t.strip()]
        excluded_lower = [t.lower() for t in excluded_tags]
        found_excluded = [t for t in excluded_lower if t in photo_tags]

        if found_excluded:
            conflicts.append({
                'type': 'excluded_tags_present',
                'filter': 'excluded_tags',
                'excluded': excluded_tags,
                'found': found_excluded,
                'message': f'Photo has excluded tags: {", ".join(found_excluded)}',
            })
            suggestions.append({
                'type': 'modify_excluded_tags',
                'filter': 'excluded_tags',
                'current': excluded_tags,
                'to_remove': found_excluded,
                'message': f'Remove from excluded_tags: {", ".join(found_excluded)}',
            })

    # Format photo values for display
    photo_values = {
        'face_ratio': round(photo_data.get('face_ratio', 0), 4),
        'face_count': photo_data.get('face_count', 0),
        'is_monochrome': bool(photo_data.get('is_monochrome', 0)),
        'is_silhouette': bool(photo_data.get('is_silhouette', 0)),
        'is_group_portrait': bool(photo_data.get('is_group_portrait', 0)),
        'mean_luminance': round(photo_data.get('mean_luminance', 0), 4),
        'iso': photo_data.get('iso'),
        'shutter_speed': photo_data.get('shutter_speed'),
        'focal_length': photo_data.get('focal_length'),
        'f_stop': photo_data.get('f_stop'),
        'tags': photo_data.get('tags', ''),
    }

    return {
        'current_category': current_category,
        'target_category': body.target_category,
        'target_filters': target_filters,
        'conflicts': conflicts,
        'suggestions': suggestions,
        'photo_values': photo_values,
        'no_conflicts': len(conflicts) == 0,
    }


@router.post("/api/comparison/override_category")
def api_comparison_override_category(
    body: OverrideCategoryBody,
    user: CurrentUser = Depends(require_edition),
):
    """Manually override a photo's category."""
    if not body.path or not body.category:
        raise HTTPException(status_code=400, detail='Missing path or category')

    # Verify photo exists and user has visibility
    user_id = user.user_id if user else None
    vis_sql, vis_params = get_visibility_clause(user_id)

    with get_db() as conn:
        row = conn.execute(f"SELECT category FROM photos WHERE path = ? AND {vis_sql}", [body.path] + vis_params).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='Photo not found')

        old_category = row[0]

        # Update the category
        conn.execute(f"UPDATE photos SET category = ? WHERE path = ? AND {vis_sql}", [body.category, body.path] + vis_params)
        conn.commit()

    _stats_cache.clear()

    return {
        'success': True,
        'path': body.path,
        'old_category': old_category,
        'new_category': body.category,
    }


@router.get("/api/comparison/history")
def api_comparison_history(
    limit: int = Query(50),
    offset: int = Query(0),
    category: Optional[str] = Query(None),
    winner: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    user: CurrentUser = Depends(require_edition),
):
    """Get paginated comparison history with filters."""
    from comparison import ComparisonManager

    manager = ComparisonManager(DEFAULT_DB_PATH)

    try:
        result = manager.get_comparison_history_filtered(
            limit=limit,
            offset=offset,
            category=category,
            winner=winner,
            start_date=start_date,
            end_date=end_date,
        )
        return result
    except Exception:
        logger.exception("Failed to fetch comparison history")
        raise HTTPException(status_code=500, detail='Internal server error')


@router.post("/api/comparison/edit")
def api_comparison_edit(
    body: ComparisonEditBody,
    user: CurrentUser = Depends(require_edition),
):
    """Edit a past comparison."""
    from comparison import ComparisonManager

    if not body.id or not body.winner:
        raise HTTPException(status_code=400, detail='Missing id or winner')

    manager = ComparisonManager(DEFAULT_DB_PATH)

    try:
        success = manager.edit_comparison(body.id, body.winner)
        if success:
            return {'success': True}
        else:
            raise HTTPException(status_code=404, detail='Comparison not found')
    except ValueError:
        raise HTTPException(status_code=400, detail='Invalid value')
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to edit comparison")
        raise HTTPException(status_code=500, detail='Internal server error')


@router.post("/api/comparison/delete")
def api_comparison_delete(
    body: ComparisonDeleteBody,
    user: CurrentUser = Depends(require_edition),
):
    """Delete a comparison."""
    from comparison import ComparisonManager

    if not body.id:
        raise HTTPException(status_code=400, detail='Missing id')

    manager = ComparisonManager(DEFAULT_DB_PATH)

    try:
        success = manager.delete_comparison(body.id)
        if success:
            return {'success': True}
        else:
            raise HTTPException(status_code=404, detail='Comparison not found')
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to delete comparison")
        raise HTTPException(status_code=500, detail='Internal server error')


@router.get("/api/comparison/coverage")
def api_comparison_coverage(
    category: Optional[str] = Query(None),
    user: CurrentUser = Depends(require_edition),
):
    """Get comparison coverage statistics."""
    from comparison import ComparisonManager

    manager = ComparisonManager(DEFAULT_DB_PATH)

    try:
        result = manager.get_comparison_coverage(category=category)
        return result
    except Exception:
        logger.exception("Failed to fetch comparison coverage")
        raise HTTPException(status_code=500, detail='Internal server error')


@router.get("/api/comparison/confidence")
def api_comparison_confidence(
    category: Optional[str] = Query(None),
    n_bootstrap: int = Query(100),
    user: CurrentUser = Depends(require_edition),
):
    """Get bootstrap confidence intervals for weights."""
    from optimization import WeightOptimizer

    optimizer = WeightOptimizer(DEFAULT_DB_PATH)

    try:
        result = optimizer.compute_weight_confidence(
            category=category,
            n_bootstrap=n_bootstrap,
        )

        if 'error' in result:
            return {
                'available': False,
                'message': result['error'],
            }

        # Convert to UI format
        weights_ui = {}
        lower_ui = {}
        upper_ui = {}
        ci_ui = {}

        for db_key, mapped_key in METRIC_NAME_MAPPING.items():
            ui_key = f'{mapped_key}_percent'
            weights_ui[ui_key] = round(result['weights'].get(db_key, 0) * 100)
            lower_ui[ui_key] = round(result['lower_bounds'].get(db_key, 0) * 100)
            upper_ui[ui_key] = round(result['upper_bounds'].get(db_key, 0) * 100)
            ci_ui[ui_key] = round(result['confidence_intervals'].get(db_key, 0) * 100)

        return {
            'available': True,
            'weights': weights_ui,
            'lower_bounds': lower_ui,
            'upper_bounds': upper_ui,
            'confidence_intervals': ci_ui,
            'stable_components': result.get('stable_components', []),
            'n_bootstrap': result.get('n_bootstrap', 0),
            'comparisons_used': result.get('comparisons_used', 0),
        }
    except Exception:
        logger.exception("Failed to compute weight confidence")
        raise HTTPException(status_code=500, detail='Internal server error')


@router.get("/api/config/weight_snapshots")
def api_weight_snapshots(
    category: Optional[str] = Query(None),
    limit: int = Query(20),
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """List weight configuration snapshots."""
    try:
        with get_db() as conn:
            if category:
                cursor = conn.execute("""
                    SELECT * FROM weight_config_snapshots
                    WHERE category = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (category, limit))
            else:
                cursor = conn.execute("""
                    SELECT * FROM weight_config_snapshots
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (limit,))

            snapshots = []
            for row in cursor:
                snapshot = dict(row)
                # Parse weights JSON
                if snapshot.get('weights'):
                    try:
                        snapshot['weights'] = json.loads(snapshot['weights'])
                    except (json.JSONDecodeError, TypeError):
                        snapshot['weights'] = {}
                snapshots.append(snapshot)

            return {'snapshots': snapshots}
    except Exception:
        logger.exception("Failed to list weight snapshots")
        raise HTTPException(status_code=500, detail='Internal server error')


@router.post("/api/config/save_snapshot")
def api_save_weight_snapshot(
    body: SaveSnapshotBody,
    user: CurrentUser = Depends(require_edition),
):
    """Save current weights as a snapshot."""
    from config import ScoringConfig

    try:
        # Get current weights
        config = ScoringConfig(validate=False)
        weights = config.get_weights(body.category)

        with get_db() as conn:
            cursor = conn.execute("""
                INSERT INTO weight_config_snapshots
                (category, weights, description, accuracy_before, accuracy_after,
                 comparisons_used, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                body.category,
                json.dumps(weights),
                body.description,
                body.accuracy_before,
                body.accuracy_after,
                body.comparisons_used,
                body.created_by,
            ))
            conn.commit()
            snapshot_id = cursor.lastrowid

        return {'success': True, 'snapshot_id': snapshot_id}
    except Exception:
        logger.exception("Failed to save weight snapshot")
        raise HTTPException(status_code=500, detail='Internal server error')


@router.post("/api/config/restore_weights")
def api_restore_weights(
    body: RestoreWeightsBody,
    user: CurrentUser = Depends(require_edition),
):
    """Restore weights from a snapshot."""
    if not body.snapshot_id:
        raise HTTPException(status_code=400, detail='Missing snapshot_id')

    try:
        # Get snapshot
        with get_db() as conn:
            row = conn.execute("""
                SELECT * FROM weight_config_snapshots WHERE id = ?
            """, (body.snapshot_id,)).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail='Snapshot not found')

        snapshot = dict(row)
        try:
            weights = json.loads(snapshot['weights'])
        except (json.JSONDecodeError, TypeError):
            raise HTTPException(status_code=500, detail='Corrupted snapshot data')
        category = snapshot['category']

        # Load and update config
        config_path = 'scoring_config.json'

        # Create backup first
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = f"{config_path}.backup.{timestamp}"
        shutil.copy2(config_path, backup_path)

        with open(config_path) as f:
            config = json.load(f)

        # Update weights in v4 config format
        categories = config.get('categories', [])
        found = False
        for cat in categories:
            if cat.get('name') == category:
                cat['weights'] = weights
                found = True
                break

        if not found:
            raise HTTPException(status_code=404, detail=f'Category "{category}" not found in config')

        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)

        reload_config()
        _stats_cache.clear()

        return {
            'success': True,
            'restored_weights': weights,
            'category': category,
            'backup_path': backup_path,
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to restore weights from snapshot")
        raise HTTPException(status_code=500, detail='Internal server error')
