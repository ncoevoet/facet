import os
import json
import zipfile
from io import BytesIO
from flask import render_template, request, redirect, jsonify, make_response, send_file
from db import DEFAULT_DB_PATH
from viewer.comparison import comparison_bp
from viewer.config import VIEWER_CONFIG, _FULL_CONFIG, _CONFIG_PATH, get_comparison_mode_settings, map_disk_path
from viewer.auth import is_edition_authenticated, require_edition, get_session_user_id
from viewer.db_helpers import get_db_connection
from viewer.types import TYPE_TO_CATEGORY

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
}


@comparison_bp.route('/compare')
def compare_page():
    """Comparison mode page for pairwise photo ranking."""
    if not is_edition_authenticated():
        return redirect('/')

    settings = get_comparison_mode_settings()
    min_comparisons = settings['min_comparisons_for_optimization']

    # Get current stats
    from comparison import ComparisonManager
    manager = ComparisonManager(DEFAULT_DB_PATH)
    stats = manager.get_statistics()

    # Get category list for filter dropdown
    from config import ScoringConfig
    config = ScoringConfig(validate=False)
    categories = config.get_all_category_names()

    # Get type parameter and map to category for auto-selection
    type_param = request.args.get('type', '')
    selected_category = TYPE_TO_CATEGORY.get(type_param, categories[0] if categories else 'portrait')
    if selected_category not in categories:
        selected_category = categories[0] if categories else 'portrait'

    # Per-category comparison count for selected category
    category_count_map = {item['category']: item['count'] for item in stats['category_breakdown']}
    selected_category_count = category_count_map.get(selected_category, 0)
    progress_pct = min(100, (selected_category_count / min_comparisons) * 100)

    return render_template(
        'compare.html',
        stats=stats,
        min_comparisons=min_comparisons,
        progress_pct=progress_pct,
        strategy=settings['pair_selection_strategy'],
        show_scores=settings['show_current_scores'],
        categories=categories,
        selected_category=selected_category,
        selected_category_count=selected_category_count,
    )


@comparison_bp.route('/api/comparison/next_pair')
@require_edition
def api_comparison_next_pair():
    """API endpoint to get the next pair of photos for comparison."""
    from comparison import PairSelector

    strategy = request.args.get('strategy', 'uncertainty')
    category = request.args.get('category', None)

    selector = PairSelector(DEFAULT_DB_PATH)
    pair = selector.get_next_pair(strategy=strategy, category=category)

    if not pair:
        return jsonify({'error': 'No more pairs available for comparison'})

    return jsonify(pair)


@comparison_bp.route('/api/download')
def api_download_single():
    """Download a single photo file (validated against database).

    RAW files (CR2/CR3) are converted to full-resolution JPEG on-the-fly.
    """
    photo_path = request.args.get('path')
    if not photo_path:
        return jsonify({'error': 'path required'}), 400

    # Validate path exists in the database (prevents path traversal)
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT path FROM photos WHERE path = ?", (photo_path,)
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return jsonify({'error': 'File not found'}), 404

    # Map database path to local disk path
    disk_path = map_disk_path(photo_path)

    if not os.path.isfile(disk_path):
        return jsonify({'error': 'File not found on disk'}), 404

    # Convert RAW files to JPEG for download
    if disk_path.lower().endswith(('.cr2', '.cr3')):
        import rawpy
        from io import BytesIO
        from PIL import Image

        with rawpy.imread(disk_path) as raw:
            rgb = raw.postprocess(
                use_camera_wb=True,
                no_auto_bright=False,
                output_color=rawpy.ColorSpace.sRGB,
                output_bps=8
            )

        pil_img = Image.fromarray(rgb)
        buffer = BytesIO()
        pil_img.save(buffer, format='JPEG', quality=95)
        buffer.seek(0)

        download_name = os.path.splitext(os.path.basename(photo_path))[0] + '.jpg'

        return send_file(
            buffer,
            mimetype='image/jpeg',
            as_attachment=True,
            download_name=download_name
        )

    return send_file(
        disk_path,
        as_attachment=True,
        download_name=os.path.basename(disk_path)
    )


@comparison_bp.route('/api/download-selected', methods=['POST'])
def api_download_selected():
    """Download selected photos as a ZIP archive."""
    data = request.get_json()
    paths = data.get('paths', [])
    if not paths:
        return jsonify({'error': 'No paths provided'}), 400

    # Validate all paths exist in the database
    conn = get_db_connection()
    try:
        placeholders = ','.join('?' for _ in paths)
        rows = conn.execute(
            f"SELECT path FROM photos WHERE path IN ({placeholders})", paths
        ).fetchall()
        valid_paths = {row[0] for row in rows}
    finally:
        conn.close()

    if not valid_paths:
        return jsonify({'error': 'No valid paths found'}), 404

    # Build ZIP in memory
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_STORED) as zf:
        for path in paths:
            if path not in valid_paths:
                continue
            disk_path = map_disk_path(path)
            if os.path.isfile(disk_path):
                zf.write(disk_path, os.path.basename(disk_path))

    buffer.seek(0)
    from datetime import datetime as _dt
    timestamp = _dt.now().strftime('%Y%m%d_%H%M%S')
    return send_file(
        buffer,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f'photos_{timestamp}.zip'
    )


@comparison_bp.route('/api/comparison/submit', methods=['POST'])
@require_edition
def api_comparison_submit():
    """API endpoint to submit a comparison result."""
    from comparison import ComparisonManager

    data = request.get_json()
    photo_a = data.get('photo_a')
    photo_b = data.get('photo_b')
    winner = data.get('winner')
    category = data.get('category')

    if not photo_a or not photo_b or not winner:
        return jsonify({'error': 'Missing required fields'}), 400

    manager = ComparisonManager(DEFAULT_DB_PATH)
    success = manager.submit_comparison(photo_a, photo_b, winner, category, user_id=get_session_user_id())

    if success:
        stats = manager.get_statistics()
        return jsonify({'success': True, 'stats': stats})
    else:
        return jsonify({'error': 'Failed to save comparison'}), 500


@comparison_bp.route('/api/comparison/reset', methods=['POST'])
@require_edition
def api_comparison_reset():
    """API endpoint to reset all comparison data."""
    try:
        with get_db_connection() as conn:
            conn.execute("DELETE FROM comparisons")
            conn.execute("DELETE FROM learned_scores")
            conn.execute("DELETE FROM weight_optimization_runs")
            conn.commit()
        return jsonify({'success': True, 'message': 'All comparison data has been reset'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@comparison_bp.route('/api/recalculate', methods=['POST'])
def api_recalculate():
    """API endpoint to recalculate all categories and aggregate scores.

    This runs the same logic as `python photos.py --recompute-average`:
    - Re-determines category for each photo based on current config
    - Recalculates aggregate scores using current weights
    - Updates burst processing

    Note: This runs synchronously and may take a while for large databases.
    """
    try:
        import subprocess
        import sys

        # Get config path from current config if available
        config_path = 'scoring_config.json'

        # Run recalculate as subprocess to avoid blocking
        # Using the same Python interpreter as the viewer
        result = subprocess.run(
            [sys.executable, 'photos.py', '--recompute-average', '--config', config_path],
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout
        )

        if result.returncode == 0:
            return jsonify({
                'success': True,
                'message': 'Recalculation complete',
                'output': result.stdout
            })
        else:
            return jsonify({
                'success': False,
                'error': f'Recalculation failed: {result.stderr or result.stdout}'
            }), 500

    except subprocess.TimeoutExpired:
        return jsonify({
            'success': False,
            'error': 'Recalculation timed out (>5 minutes). Run manually with: python photos.py --recompute-average'
        }), 500
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@comparison_bp.route('/api/config/update_weights', methods=['POST'])
def api_update_weights():
    """API endpoint to update category weights in scoring_config.json.

    Request body:
        {
            "category": "portrait",
            "weights": {
                "aesthetic_percent": 30,
                "face_quality_percent": 25,
                ...
            },
            "recalculate": true  // optional: trigger recalculation after saving
        }

    Returns success/error status.
    """
    try:
        import json
        from datetime import datetime

        data = request.get_json()
        category = data.get('category')
        weights = data.get('weights', {})
        should_recalculate = data.get('recalculate', False)

        if not category:
            return jsonify({'success': False, 'error': 'Missing category'}), 400

        if not weights:
            return jsonify({'success': False, 'error': 'Missing weights'}), 400

        config_path = 'scoring_config.json'

        # Read current config
        with open(config_path, 'r') as f:
            config = json.load(f)

        # Create backup
        backup_path = f"{config_path}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        with open(backup_path, 'w') as f:
            json.dump(config, f, indent=2)

        # Update weights in v4 config format (categories is a list)
        categories = config.get('categories', [])
        found = False
        for cat in categories:
            if cat.get('name') == category:
                # Update weights in the category
                if 'weights' not in cat:
                    cat['weights'] = {}
                cat['weights'].update(weights)
                found = True
                break
        if not found:
            return jsonify({'success': False, 'error': f'Category "{category}" not found in config'}), 404

        # Save updated config
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)

        result = {
            'success': True,
            'message': f'Weights updated for category "{category}"',
            'backup': backup_path
        }

        # Optionally trigger recalculation (only for the updated category)
        if should_recalculate:
            import subprocess
            import sys
            try:
                recalc_result = subprocess.run(
                    [sys.executable, 'photos.py', '--recompute-category', category,
                     '--config', config_path],
                    capture_output=True,
                    text=True,
                    timeout=300
                )
                if recalc_result.returncode == 0:
                    result['recalculated'] = True
                    result['message'] += ' and scores recalculated'
                else:
                    result['recalculated'] = False
                    result['recalculate_error'] = recalc_result.stderr or recalc_result.stdout
            except subprocess.TimeoutExpired:
                result['recalculated'] = False
                result['recalculate_error'] = 'Recalculation timed out'

        return jsonify(result)

    except FileNotFoundError:
        return jsonify({'success': False, 'error': 'Config file not found'}), 404
    except json.JSONDecodeError as e:
        return jsonify({'success': False, 'error': f'Invalid JSON in config: {e}'}), 500
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@comparison_bp.route('/api/comparison/stats')
@require_edition
def api_comparison_stats():
    """API endpoint to get comparison statistics."""
    from comparison import ComparisonManager
    manager = ComparisonManager(DEFAULT_DB_PATH)
    stats = manager.get_statistics()
    return jsonify(stats)


@comparison_bp.route('/api/comparison/photo_metrics')
def api_comparison_photo_metrics():
    """API endpoint to get raw metrics for photos (for client-side score preview).

    Query params:
        paths: Comma-separated list of photo paths (max 2)

    Returns:
        Dict mapping path to metrics dict with all scoring columns
    """
    paths_param = request.args.get('paths', '')
    if not paths_param:
        return jsonify({'error': 'Missing paths parameter'}), 400

    paths = [p.strip() for p in paths_param.split(',') if p.strip()]
    if len(paths) > 2:
        return jsonify({'error': 'Maximum 2 paths allowed'}), 400

    # Columns needed for score calculation
    metric_columns = [
        'path', 'category', 'aggregate',
        'aesthetic', 'face_quality', 'eye_sharpness', 'tech_sharpness',
        'color_score', 'exposure_score', 'comp_score', 'isolation_bonus',
        'quality_score', 'contrast_score', 'dynamic_range_stops',
        'noise_sigma', 'histogram_bimodality', 'mean_saturation',
        'is_blink', 'is_silhouette', 'face_ratio', 'face_count',
        'scoring_model', 'tags', 'is_monochrome', 'leading_lines_score',
        'power_point_score', 'histogram_spread', 'mean_luminance'
    ]

    with get_db_connection() as conn:
        placeholders = ','.join(['?' for _ in paths])
        cols = ', '.join(metric_columns)
        query = f"SELECT {cols} FROM photos WHERE path IN ({placeholders})"
        rows = conn.execute(query, paths).fetchall()

    result = {}
    for row in rows:
        row_dict = dict(row)
        path = row_dict['path']
        result[path] = row_dict

    return jsonify(result)


@comparison_bp.route('/api/comparison/category_weights')
def api_comparison_category_weights():
    """API endpoint to get weights for a category (or all categories).

    Query params:
        category: Optional category name. If omitted, returns all categories.

    Returns:
        Dict with category weights as percentages (for UI sliders)
    """
    from config import ScoringConfig

    category = request.args.get('category')
    config = ScoringConfig(validate=False)

    if category:
        # Return weights for specific category
        for cat in config.get_categories():
            if cat['name'] == category:
                return jsonify({
                    'category': category,
                    'weights': cat.get('weights', {}),
                    'modifiers': cat.get('modifiers', {}),
                    'filters': cat.get('filters', {}),
                    'priority': cat.get('priority', 100)
                })
        return jsonify({'error': f'Category not found: {category}'}), 404
    else:
        # Return all categories with their weights
        categories = []
        for cat in config.get_categories():
            categories.append({
                'name': cat['name'],
                'priority': cat.get('priority', 100),
                'weights': cat.get('weights', {}),
                'modifiers': cat.get('modifiers', {}),
                'filters': cat.get('filters', {})
            })
        return jsonify({'categories': categories})


@comparison_bp.route('/api/comparison/learned_weights')
@require_edition
def api_comparison_learned_weights():
    """API endpoint to get suggested weights based on comparison outcomes.

    Uses Direct Preference Optimization to maximize comparison prediction accuracy.

    Query params:
        category: Optional category name
        include_ties: Include tie comparisons (default: true)
        use_cv: Use cross-validation for robustness (default: false)

    Returns:
        Dict with current_weights, suggested_weights, accuracy metrics, etc.
    """
    category = request.args.get('category')
    include_ties = request.args.get('include_ties', 'true').lower() == 'true'
    use_cv = request.args.get('use_cv', 'false').lower() == 'true'

    from optimization import WeightOptimizer

    optimizer = WeightOptimizer(DEFAULT_DB_PATH)

    # Check if we have enough comparisons (lower threshold with direct optimization)
    with get_db_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM comparisons WHERE winner IN ('a', 'b', 'tie')"
        ).fetchone()[0]

    settings = get_comparison_mode_settings()
    # Direct optimization needs fewer comparisons (30 vs 50)
    min_comparisons = settings.get('min_comparisons_for_optimization', 30)

    if count < min_comparisons:
        return jsonify({
            'available': False,
            'message': f'Need at least {min_comparisons} comparisons (have {count})',
            'comparisons': count,
            'min_required': min_comparisons
        })

    # Use new direct preference optimization
    try:
        if use_cv:
            result = optimizer.optimize_weights_with_cv(
                category=category,
                min_comparisons=min_comparisons,
                include_ties=include_ties
            )
        else:
            result = optimizer.optimize_weights_direct(
                category=category,
                min_comparisons=min_comparisons,
                include_ties=include_ties
            )

        if 'error' in result:
            return jsonify({
                'available': False,
                'message': result['error'],
                'comparisons': count
            })

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
        if use_cv:
            response['cv_accuracy'] = result.get('cv_accuracy', 0)
            response['cv_std'] = result.get('cv_std', 0)
            response['fold_results'] = result.get('fold_results', [])

        return jsonify(response)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'available': False,
            'message': f'Optimization error: {str(e)}',
            'comparisons': count
        })


@comparison_bp.route('/api/comparison/preview_score', methods=['POST'])
def api_comparison_preview_score():
    """API endpoint to preview score with custom weights.

    Request body:
        path: Photo path
        weights: Dict of weight overrides (as percentages, e.g., {"aesthetic_percent": 40})

    Returns:
        Dict with original and preview scores
    """
    from config import ScoringConfig
    from processing.scorer import Facet

    data = request.get_json()
    path = data.get('path')
    custom_weights = data.get('weights', {})

    if not path:
        return jsonify({'error': 'Missing path parameter'}), 400

    # Get photo metrics
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM photos WHERE path = ?", (path,)).fetchone()

    if not row:
        return jsonify({'error': 'Photo not found'}), 404

    metrics = dict(row)
    original_score = metrics.get('aggregate', 0)
    category = metrics.get('category', 'others')

    # Create scorer with custom weights for preview
    # We'll calculate using the standard logic but with modified weights
    config = ScoringConfig(validate=False)

    # Build photo_data for determine_category
    photo_data = {
        'tags': metrics.get('tags', '') or '',
        'face_count': metrics.get('face_count', 0) or 0,
        'face_ratio': metrics.get('face_ratio', 0) or 0,
        'is_silhouette': metrics.get('is_silhouette', 0),
        'is_group_portrait': metrics.get('is_group_portrait', 0),
        'is_monochrome': metrics.get('is_monochrome', 0),
        'mean_luminance': metrics.get('mean_luminance', 0.5),
    }

    # Calculate preview score using simplified weighted sum
    weights = config.get_weights(category)

    # Override with custom weights (convert from percent to decimal)
    for key, value in custom_weights.items():
        if key.endswith('_percent'):
            base_key = key[:-8]
            weights[base_key] = value / 100
        else:
            weights[base_key if key.endswith('_percent') else key] = value / 100

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

    return jsonify({
        'path': path,
        'category': category,
        'original_score': original_score,
        'preview_score': round(preview_score, 2),
        'delta': round(preview_score - (original_score or 0), 2)
    })


@comparison_bp.route('/api/comparison/suggest_filters', methods=['POST'])
def api_comparison_suggest_filters():
    """API endpoint to suggest filter changes when moving a photo to another category.

    When a user wants to re-categorize a photo during comparison, this endpoint
    analyzes why the photo doesn't match the target category and suggests filter
    modifications that would make similar photos automatically categorized correctly.

    Request body:
        path: Photo path
        target_category: Category to move the photo to

    Returns:
        Dict with:
            - current_category: Current category of the photo
            - target_category: Requested target category
            - conflicts: List of filter conflicts (why it doesn't match)
            - suggestions: List of suggested filter changes
            - photo_values: Actual metric values for the photo
    """
    from config import ScoringConfig, CategoryFilter

    data = request.get_json()
    path = data.get('path')
    target_category = data.get('target_category')

    if not path or not target_category:
        return jsonify({'error': 'Missing path or target_category'}), 400

    # Get photo metrics
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM photos WHERE path = ?", (path,)).fetchone()

    if not row:
        return jsonify({'error': 'Photo not found'}), 404

    metrics = dict(row)
    current_category = metrics.get('category', 'others')

    if current_category == target_category:
        return jsonify({
            'current_category': current_category,
            'target_category': target_category,
            'conflicts': [],
            'suggestions': [],
            'message': 'Photo is already in the target category'
        })

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
        if cat['name'] == target_category:
            target_config = cat
            break

    if not target_config:
        return jsonify({'error': f'Category not found: {target_category}'}), 404

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
                    'message': f'{label} is required but missing'
                })
            elif actual < min_val:
                conflicts.append({
                    'type': 'below_minimum',
                    'filter': f'{filter_key}_min',
                    'required': min_val,
                    'actual': actual,
                    'message': f'{label} ({actual:.3f}) is below minimum ({min_val})'
                })
                suggestions.append({
                    'type': 'lower_minimum',
                    'filter': f'{filter_key}_min',
                    'current': min_val,
                    'suggested': round(actual * 0.9, 4),  # 10% margin
                    'message': f'Lower {filter_key}_min from {min_val} to {round(actual * 0.9, 4)}'
                })

        if max_val is not None:
            if actual is None:
                conflicts.append({
                    'type': 'missing_value',
                    'filter': f'{filter_key}_max',
                    'required': max_val,
                    'actual': None,
                    'message': f'{label} is required but missing'
                })
            elif actual > max_val:
                conflicts.append({
                    'type': 'above_maximum',
                    'filter': f'{filter_key}_max',
                    'required': max_val,
                    'actual': actual,
                    'message': f'{label} ({actual:.3f}) is above maximum ({max_val})'
                })
                suggestions.append({
                    'type': 'raise_maximum',
                    'filter': f'{filter_key}_max',
                    'current': max_val,
                    'suggested': round(actual * 1.1, 4),  # 10% margin
                    'message': f'Raise {filter_key}_max from {max_val} to {round(actual * 1.1, 4)}'
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
                    'message': f'{label} is {actual}, but category requires {required}'
                })
                suggestions.append({
                    'type': 'change_boolean',
                    'filter': filter_key,
                    'current': required,
                    'suggested': actual,
                    'message': f'Change {filter_key} from {required} to {actual}'
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
                    'message': f'Photo needs at least one of: {", ".join(required_tags)}'
                })
                suggestions.append({
                    'type': 'remove_tag_requirement',
                    'filter': 'required_tags',
                    'message': 'Remove or modify required_tags filter'
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
                    'message': f'Photo is missing required tags: {", ".join(missing)}'
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
                'message': f'Photo has excluded tags: {", ".join(found_excluded)}'
            })
            suggestions.append({
                'type': 'modify_excluded_tags',
                'filter': 'excluded_tags',
                'current': excluded_tags,
                'to_remove': found_excluded,
                'message': f'Remove from excluded_tags: {", ".join(found_excluded)}'
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

    return jsonify({
        'current_category': current_category,
        'target_category': target_category,
        'target_filters': target_filters,
        'conflicts': conflicts,
        'suggestions': suggestions,
        'photo_values': photo_values,
        'no_conflicts': len(conflicts) == 0
    })


@comparison_bp.route('/api/comparison/override_category', methods=['POST'])
def api_comparison_override_category():
    """API endpoint to manually override a photo's category.

    This stores the category override for learning purposes.

    Request body:
        path: Photo path
        category: New category to assign

    Returns:
        Dict with success status and updated category
    """
    data = request.get_json()
    path = data.get('path')
    category = data.get('category')

    if not path or not category:
        return jsonify({'error': 'Missing path or category'}), 400

    # Verify photo exists
    with get_db_connection() as conn:
        row = conn.execute("SELECT category FROM photos WHERE path = ?", (path,)).fetchone()
        if not row:
            return jsonify({'error': 'Photo not found'}), 404

        old_category = row[0]

        # Update the category
        conn.execute("UPDATE photos SET category = ? WHERE path = ?", (category, path))
        conn.commit()

    return jsonify({
        'success': True,
        'path': path,
        'old_category': old_category,
        'new_category': category
    })


@comparison_bp.route('/api/comparison/history')
@require_edition
def api_comparison_history():
    """API endpoint to get paginated comparison history with filters.

    Query params:
        limit: Max results (default 50)
        offset: Skip results (default 0)
        category: Filter by category
        winner: Filter by winner ('a', 'b', 'tie', 'skip')
        start_date: Filter by start date (ISO format)
        end_date: Filter by end date (ISO format)

    Returns:
        Dict with comparisons, total, has_more
    """
    from comparison import ComparisonManager

    manager = ComparisonManager(DEFAULT_DB_PATH)

    try:
        result = manager.get_comparison_history_filtered(
            limit=int(request.args.get('limit', 50)),
            offset=int(request.args.get('offset', 0)),
            category=request.args.get('category'),
            winner=request.args.get('winner'),
            start_date=request.args.get('start_date'),
            end_date=request.args.get('end_date'),
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@comparison_bp.route('/api/comparison/edit', methods=['POST'])
@require_edition
def api_comparison_edit():
    """API endpoint to edit a past comparison.

    Request body:
        id: Comparison ID
        winner: New winner value ('a', 'b', 'tie', 'skip')

    Returns:
        Dict with success status
    """
    from comparison import ComparisonManager

    data = request.get_json()
    comparison_id = data.get('id')
    new_winner = data.get('winner')

    if not comparison_id or not new_winner:
        return jsonify({'error': 'Missing id or winner'}), 400

    manager = ComparisonManager(DEFAULT_DB_PATH)

    try:
        success = manager.edit_comparison(int(comparison_id), new_winner)
        if success:
            return jsonify({'success': True})
        else:
            return jsonify({'error': 'Comparison not found'}), 404
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@comparison_bp.route('/api/comparison/delete', methods=['POST'])
@require_edition
def api_comparison_delete():
    """API endpoint to delete a comparison.

    Request body:
        id: Comparison ID

    Returns:
        Dict with success status
    """
    from comparison import ComparisonManager

    data = request.get_json()
    comparison_id = data.get('id')

    if not comparison_id:
        return jsonify({'error': 'Missing id'}), 400

    manager = ComparisonManager(DEFAULT_DB_PATH)

    try:
        success = manager.delete_comparison(int(comparison_id))
        if success:
            return jsonify({'success': True})
        else:
            return jsonify({'error': 'Comparison not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@comparison_bp.route('/api/comparison/coverage')
@require_edition
def api_comparison_coverage():
    """API endpoint to get comparison coverage statistics.

    Shows score distribution coverage and optimization readiness.

    Query params:
        category: Optional category filter

    Returns:
        Dict with coverage metrics and recommendations
    """
    from comparison import ComparisonManager

    manager = ComparisonManager(DEFAULT_DB_PATH)
    category = request.args.get('category')

    try:
        result = manager.get_comparison_coverage(category=category)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@comparison_bp.route('/api/comparison/confidence')
@require_edition
def api_comparison_confidence():
    """API endpoint to get bootstrap confidence intervals for weights.

    Query params:
        category: Optional category filter
        n_bootstrap: Number of bootstrap samples (default 100)

    Returns:
        Dict with weight confidence intervals
    """
    from optimization import WeightOptimizer

    optimizer = WeightOptimizer(DEFAULT_DB_PATH)
    category = request.args.get('category')
    n_bootstrap = int(request.args.get('n_bootstrap', 100))

    try:
        result = optimizer.compute_weight_confidence(
            category=category,
            n_bootstrap=n_bootstrap
        )

        if 'error' in result:
            return jsonify({
                'available': False,
                'message': result['error']
            })

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

        return jsonify({
            'available': True,
            'weights': weights_ui,
            'lower_bounds': lower_ui,
            'upper_bounds': upper_ui,
            'confidence_intervals': ci_ui,
            'stable_components': result.get('stable_components', []),
            'n_bootstrap': result.get('n_bootstrap', 0),
            'comparisons_used': result.get('comparisons_used', 0),
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@comparison_bp.route('/api/config/weight_snapshots')
def api_weight_snapshots():
    """API endpoint to list weight configuration snapshots.

    Query params:
        category: Optional category filter
        limit: Max results (default 20)

    Returns:
        List of snapshots with metadata
    """
    category = request.args.get('category')
    limit = int(request.args.get('limit', 20))

    try:
        with get_db_connection() as conn:
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
                import json
                if snapshot.get('weights'):
                    snapshot['weights'] = json.loads(snapshot['weights'])
                snapshots.append(snapshot)

            return jsonify({'snapshots': snapshots})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@comparison_bp.route('/api/config/save_snapshot', methods=['POST'])
def api_save_weight_snapshot():
    """API endpoint to save current weights as a snapshot.

    Request body:
        category: Category to snapshot
        description: Optional description
        accuracy_before: Optional accuracy metric
        accuracy_after: Optional accuracy metric after applying

    Returns:
        Dict with snapshot ID
    """
    import json as json_module
    from config import ScoringConfig

    data = request.get_json()
    category = data.get('category', 'others')
    description = data.get('description', '')
    accuracy_before = data.get('accuracy_before')
    accuracy_after = data.get('accuracy_after')
    comparisons_used = data.get('comparisons_used')
    created_by = data.get('created_by', 'manual')

    try:
        # Get current weights
        config = ScoringConfig(validate=False)
        weights = config.get_weights(category)

        with get_db_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO weight_config_snapshots
                (category, weights, description, accuracy_before, accuracy_after,
                 comparisons_used, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                category,
                json_module.dumps(weights),
                description,
                accuracy_before,
                accuracy_after,
                comparisons_used,
                created_by
            ))
            conn.commit()
            snapshot_id = cursor.lastrowid

        return jsonify({'success': True, 'snapshot_id': snapshot_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@comparison_bp.route('/api/config/restore_weights', methods=['POST'])
def api_restore_weights():
    """API endpoint to restore weights from a snapshot.

    Request body:
        snapshot_id: ID of snapshot to restore

    Returns:
        Dict with success status and restored weights
    """
    import json as json_module
    import shutil
    from datetime import datetime

    data = request.get_json()
    snapshot_id = data.get('snapshot_id')

    if not snapshot_id:
        return jsonify({'error': 'Missing snapshot_id'}), 400

    try:
        # Get snapshot
        with get_db_connection() as conn:
            row = conn.execute("""
                SELECT * FROM weight_config_snapshots WHERE id = ?
            """, (snapshot_id,)).fetchone()

            if not row:
                return jsonify({'error': 'Snapshot not found'}), 404

            snapshot = dict(row)
            weights = json_module.loads(snapshot['weights'])
            category = snapshot['category']

        # Load and update config
        config_path = 'scoring_config.json'

        # Create backup first
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = f"{config_path}.backup.{timestamp}"
        shutil.copy2(config_path, backup_path)

        with open(config_path) as f:
            config = json_module.load(f)

        # Update weights in v4 config format
        categories = config.get('categories', [])
        found = False
        for cat in categories:
            if cat.get('name') == category:
                cat['weights'] = weights
                found = True
                break

        if not found:
            return jsonify({'error': f'Category "{category}" not found in config'}), 404

        with open(config_path, 'w') as f:
            json_module.dump(config, f, indent=2)

        return jsonify({
            'success': True,
            'restored_weights': weights,
            'category': category,
            'backup_path': backup_path
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


