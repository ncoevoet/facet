"""
Facet Scoring Configuration.

Contains ScoringConfig class and helper functions.
"""

import logging
import os
import json
import hashlib

logger = logging.getLogger("facet.config")

from config.category_filter import (
    VALID_NUMERIC_FILTERS, VALID_BOOLEAN_FILTERS, VALID_TAG_FILTERS,
    VALID_WEIGHT_COLUMNS,
)

# Tolerance for weight normalization - weights within this range of 100% are not auto-normalized
# This preserves targeted changes from recommendations
NORMALIZATION_TOLERANCE = 5  # +/- 5% tolerance (95-105%)

# Name of the scoring_contexts preset used when no context (or an unknown one) is requested
DEFAULT_CONTEXT_NAME = "default"

# Name of the catch-all category (priority 999, empty filters) — always evaluated last
DEFAULT_CATEGORY_NAME = "default"

# Minimum total unified memory (GB) per profile on Apple Metal, richest first —
# derivation in ScoringConfig.suggest_profile_for_unified_memory
UNIFIED_MEMORY_PROFILE_THRESHOLDS_GB = (
    ('24gb', 48.0),
    ('16gb', 32.0),
    ('8gb', 16.0),
)
UNIFIED_MEMORY_MINIMUM_PROFILE = 'legacy'

# RAW demosaic and embedded-preview defaults. ``bright`` is a fixed exposure
# gain applied to every frame, replacing LibRaw's per-frame auto-brightness:
# the latter equalises exposure across a bracket, which erases the exposure
# ladder the scoring engine is supposed to measure. Authoritative copy —
# utils/image_loading.py imports this rather than redefining it.
RAW_DECODE_DEFAULTS = {
    'bright': 1.62,
    'prefer_embedded_preview': True,
    'preview_min_sensor_ratio': 0.5,
    'viewer_concurrency': 3,
    'faithful_bracket_render': True,
}


def default_config_path():
    """Absolute path to the repo-root scoring_config.json, or $FACET_CONFIG.

    Resolves what api.config._CONFIG_PATH resolves, but lives here so modules
    outside the api package can reach it without inverting the
    api -> optimization import direction. Duplicated rather than imported for
    the same reason: this one line of env-var handling is cheaper to keep in
    sync than a new cross-package dependency.
    """
    env_path = os.environ.get('FACET_CONFIG', '').strip()
    if env_path:
        return env_path
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'scoring_config.json')


def _calc_stats(values):
    """Calculate statistical summary for a list of values.

    Returns dict with min, max, avg, std, count, and percentiles (p10-p95),
    or None if values is empty.
    """
    import math
    if not values:
        return None
    n = len(values)
    avg = sum(values) / n
    variance = sum((x - avg) ** 2 for x in values) / n if n > 1 else 0
    std = math.sqrt(variance)
    sorted_vals = sorted(values)
    return {
        'count': n,
        'min': sorted_vals[0],
        'max': sorted_vals[-1],
        'avg': avg,
        'std': std,
        'p10': sorted_vals[int(n * 0.10)] if n > 10 else sorted_vals[0],
        'p25': sorted_vals[int(n * 0.25)] if n > 4 else sorted_vals[0],
        'p50': sorted_vals[int(n * 0.50)] if n > 2 else sorted_vals[0],
        'p75': sorted_vals[int(n * 0.75)] if n > 4 else sorted_vals[-1],
        'p90': sorted_vals[int(n * 0.90)] if n > 10 else sorted_vals[-1],
        'p95': sorted_vals[int(n * 0.95)] if n > 20 else sorted_vals[-1],
    }


from config.category_filter import CategoryFilter


def _sanitize_context_names(context_def, field):
    """Coerce a scoring_contexts list field (promote/excluded/suggest_from_moments) to strings.

    Tolerates a hand-edited config where the field is the wrong type, or a
    list with non-string entries, instead of letting callers crash on it.

    Returns:
        Tuple of (clean_names: list of str, problems: list of human-readable
        descriptions of anything dropped). Both empty when the field is absent
        or already well-formed.
    """
    raw = context_def.get(field)
    if raw is None:
        return [], []
    if not isinstance(raw, list):
        return [], [f"'{field}' should be a list, got {type(raw).__name__}"]
    clean = [entry for entry in raw if isinstance(entry, str)]
    problems = [f"{field} entry {entry!r} is not a string" for entry in raw if not isinstance(entry, str)]
    return clean, problems


def _usable_category_name(category):
    """Return a category's name when it is a non-empty string, else None.

    A nameless entry must never reach a context's evaluation order:
    ``determine_category`` returns the matched name verbatim, so an unusable
    one would be persisted as the photo's category instead of failing loudly.
    """
    name = category.get('name')
    return name if isinstance(name, str) and name.strip() else None


def resolve_scoring_config_path(explicit):
    """Path a caller-less ``ScoringConfig()`` loads: the argument, then
    $FACET_CONFIG, then the relative ``'scoring_config.json'`` every CLI entry
    point already resolves against its own working directory. Not
    :func:`default_config_path`: that one is always absolute, while callers
    here (``facet.py``'s ``--config``, and every bare ``ScoringConfig()`` in
    ``api/``) have always resolved the plain string against process cwd, and
    changing that silently would move which file a running install reads.
    """
    return explicit or os.environ.get('FACET_CONFIG', '').strip() or 'scoring_config.json'


def _readable_system_ram_gb():
    """Total memory in GB -- the cgroup limit where one binds -- or None.

    None means no reading at all, which covers both ways that happens: the
    reader raised, or it answered the None ``utils.system_memory.total_gb``
    returns for "nothing could be read". The caller picks a message from the
    absence rather than from a number it would otherwise have to invent.

    The import stays inside the call because ``utils`` reaches back into this
    module for ``RAW_DECODE_DEFAULTS``, so a module-level one would be a cycle.
    """
    try:
        from utils.system_memory import total_gb
        return total_gb()
    except Exception:
        return None


def _unusable_cuda_status():
    """The arch-mismatch status when a present GPU cannot run kernels, else None.

    Lets the profile check say "your card is there but this PyTorch build has
    no kernels for it" instead of "No GPU detected", which is simply wrong on
    an RTX 50-series box (issue #119).
    """
    try:
        from utils.device import cuda_arch_mismatch
        return cuda_arch_mismatch()
    except Exception:
        return None


class ScoringConfig:
    """Loads and manages scoring configuration from JSON file.

    Requires v4.0 category-centric config format. The config file must contain
    a 'categories' array with category definitions sorted by priority.
    """

    def __init__(self, config_path=None, validate=True):
        self.config_path = resolve_scoring_config_path(config_path)
        self.config = self._load_config()
        self._context_order_cache = {}
        self.version_hash = self._compute_version_hash()
        if validate:
            for schema_error in self.validate_schema():
                logger.warning("Config schema error: %s", schema_error)
            self.validate_weights(verbose=True)

    def _load_config(self):
        """Load config from file.

        Raises:
            FileNotFoundError: If config file doesn't exist
            ValueError: If config is not v4.0 format (no 'categories' array)
        """
        if not os.path.exists(self.config_path):
            raise FileNotFoundError(
                f"Config file not found: {self.config_path}\n"
                f"Please ensure scoring_config.json exists with v4.0 format."
            )

        try:
            with open(self.config_path, 'r') as f:
                config = json.load(f)
        except Exception as e:
            raise ValueError(f"Could not load config from {self.config_path}: {e}")

        # Validate v4 format
        if 'categories' not in config:
            raise ValueError(
                f"Config file {self.config_path} is not v4.0 format (missing 'categories' array).\n"
                f"Config must have a 'categories' array with category definitions."
            )

        # Environment override for the VRAM profile. Lets a single mounted config
        # serve every Docker profile (legacy/8gb/16gb/24gb/auto) via an env var
        # instead of editing the JSON — e.g. `FACET_VRAM_PROFILE=8gb`. Invalid
        # values are ignored with a warning so a typo can't silently mis-scan.
        env_profile = os.environ.get('FACET_VRAM_PROFILE', '').strip()
        if env_profile:
            valid_profiles = {'auto', 'legacy', '8gb', '16gb', '24gb'}
            if env_profile in valid_profiles:
                config.setdefault('models', {})['vram_profile'] = env_profile
                logger.info("VRAM profile overridden by FACET_VRAM_PROFILE=%s", env_profile)
            else:
                logger.warning(
                    "Ignoring FACET_VRAM_PROFILE=%r (not one of %s)",
                    env_profile, sorted(valid_profiles),
                )

        return config

    def _merge_configs(self, base, override):
        """Deep merge override into base config."""
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._merge_configs(result[key], value)
            else:
                result[key] = value
        return result

    def _compute_version_hash(self):
        """Compute a hash of the config for tracking which version was used."""
        config_str = json.dumps(self.config, sort_keys=True)
        return hashlib.md5(config_str.encode()).hexdigest()[:12]

    @staticmethod
    def normalize_weights_to_100(weights_dict, skip_within_tolerance=True):
        """Normalize a dict of weights to sum to exactly 100.

        Uses proportional scaling with the last weight getting the remainder
        to ensure the sum is exactly 100 (avoids rounding errors).

        Args:
            weights_dict: Dict of {key: value} where values are percentages
            skip_within_tolerance: If True, skip normalization when total is
                within NORMALIZATION_TOLERANCE of 100%

        Returns:
            Dict of {key: new_value} with values summing to exactly 100,
            or None if weights_dict is empty, sums to 0, or within tolerance
        """
        if not weights_dict:
            return None

        total = sum(weights_dict.values())
        if total == 0:
            return None

        if abs(total - 100) <= 0.01:
            # Already at 100%, no change needed
            return None

        # Skip normalization if within tolerance to preserve targeted changes
        if skip_within_tolerance and abs(total - 100) <= NORMALIZATION_TOLERANCE:
            return None

        scale_factor = 100.0 / total
        new_weights = {}
        running_total = 0

        # Sort by value descending - largest weights get rounded, smallest gets remainder
        sorted_keys = sorted(weights_dict.keys(), key=lambda k: weights_dict[k], reverse=True)

        for i, key in enumerate(sorted_keys):
            old_val = weights_dict[key]
            if i == len(sorted_keys) - 1:
                # Last weight gets remainder to ensure exact 100%
                new_val = max(0, 100 - running_total)
            else:
                new_val = round(old_val * scale_factor)
            running_total += new_val
            new_weights[key] = new_val

        return new_weights

    def validate_weights(self, verbose=True):
        """Validate and auto-correct weight percentages per category.

        Auto-corrections applied:
        1. Convert decimals to percentages (0.30 -> 30)
        2. Clamp negative values to 0
        3. Round floats to integers
        4. Normalize weights to sum to exactly 100%

        Args:
            verbose: If True, print validation results

        Returns:
            Tuple of (is_valid: bool, corrected_categories: list of category names)
        """
        categories = self.config.get('categories', [])
        corrected_categories = []

        for cat in categories:
            category = cat.get('name', 'unnamed')
            cat_weights = cat.get('weights', {})

            if not isinstance(cat_weights, dict):
                continue

            # Collect all *_percent keys and values
            percent_items = {}
            invalid_keys = []
            for key, value in cat_weights.items():
                if key.endswith('_percent') and isinstance(value, (int, float)):
                    # Check if this is a valid weight key
                    base_key = key[:-8]  # Remove '_percent'
                    if base_key in VALID_WEIGHT_COLUMNS:
                        percent_items[key] = value
                    else:
                        invalid_keys.append(key)

            # Skip categories without percentage weights
            if not percent_items:
                continue

            # Snapshot which keys the user actually set, before 0b below zero-pads
            # percent_items out to every valid column — the decimal heuristic in
            # step 1 must judge ambiguity only on what the user provided.
            user_set_keys = set(percent_items)

            corrections = []

            # === 0. Remove invalid weight keys ===
            for key in invalid_keys:
                corrections.append(f"  {key}: removed (not a valid weight)")
                del cat_weights[key]

            # === 0b. Add missing valid weight keys with value 0 ===
            for valid_key in VALID_WEIGHT_COLUMNS:
                key = f"{valid_key}_percent"
                if key not in cat_weights:
                    cat_weights[key] = 0
                    percent_items[key] = 0
                    corrections.append(f"  {key}: added (default 0)")

            # === 1. Convert decimals to percentages ===
            # If all *user-set* values are <= 1 and sum <= 1, assume they're decimals.
            # Must judge only user_set_keys, not the post-0b percent_items: 0b zero-pads
            # every valid column, which would make len(...) > 1 always true and
            # misinterpret a single small user-set value (e.g. {"tech_sharpness_percent": 1})
            # as a decimal fraction and inflate it to 100.
            user_set_items = {k: percent_items[k] for k in user_set_keys}
            all_small = all(v <= 1 for v in user_set_items.values())
            total_small = sum(user_set_items.values()) <= 1.01
            if all_small and total_small and len(user_set_items) > 1:
                for key, value in user_set_items.items():
                    new_value = round(value * 100)
                    if new_value != value:
                        corrections.append(f"  {key}: {value} -> {new_value} (decimal to percent)")
                        cat_weights[key] = new_value
                        percent_items[key] = new_value

            # === 2. Clamp negative values to 0 ===
            for key, value in percent_items.items():
                if value < 0:
                    corrections.append(f"  {key}: {value} -> 0 (negative clamped)")
                    cat_weights[key] = 0
                    percent_items[key] = 0

            # === 3. Round floats to integers ===
            for key, value in percent_items.items():
                if isinstance(value, float) and value != int(value):
                    new_value = round(value)
                    corrections.append(f"  {key}: {value} -> {new_value} (rounded)")
                    cat_weights[key] = new_value
                    percent_items[key] = new_value

            # === 4. Normalize to 100% ===
            new_weights = self.normalize_weights_to_100(percent_items)
            if new_weights:
                old_total = sum(percent_items.values())
                for key in percent_items:
                    if new_weights[key] != percent_items[key]:
                        corrections.append(f"  {key}: {percent_items[key]} -> {new_weights[key]}")
                    cat_weights[key] = new_weights[key]
                if verbose and not corrections:
                    # Only show normalization message if no other corrections
                    logger.info("Normalized '%s' weights from %s%% to 100%%", category, old_total)

            if corrections:
                corrected_categories.append(category)
                if verbose:
                    logger.info("Corrected '%s' weights:", category)
                    for c in corrections:
                        logger.info(c)

        # Save config if any categories were corrected
        if corrected_categories:
            self.save_config()
            self.version_hash = self._compute_version_hash()
            if verbose:
                logger.info("Saved corrected config to %s", self.config_path)

        is_valid = len(corrected_categories) == 0
        if verbose and is_valid:
            logger.info("Config validation passed: all %d categories have valid weight totals", len(categories))

        return is_valid, corrected_categories

    def save_config(self):
        """Save the current config to the config file."""
        with open(self.config_path, 'w') as f:
            json.dump(self.config, f, indent=2)
            f.write('\n')  # Trailing newline

    def get_weights(self, category):
        """Get weights for a scoring category (portrait, human_others, others).

        Converts percentage values (e.g., 'face_quality_percent': 30) to decimals
        (e.g., 'face_quality': 0.30) for backward compatibility with scoring logic.
        Also merges in modifiers (like 'bonus').

        Weights are normalized to sum to 1.0 so scoring works correctly even if
        config percentages don't sum to exactly 100%.
        """
        # Find the category in the categories array
        for cat in self.config.get('categories', []):
            if cat.get('name') == category:
                converted = {}
                weight_keys = []  # Track which keys are weights (for normalization)

                # Convert weights
                for key, value in cat.get('weights', {}).items():
                    if key.endswith('_percent'):
                        # Convert percentage to decimal, strip '_percent' suffix
                        base_key = key[:-8]  # Remove '_percent'
                        converted[base_key] = value / 100
                        weight_keys.append(base_key)
                    else:
                        converted[key] = value

                # Normalize weights to sum to 1.0
                if weight_keys:
                    total = sum(converted[k] for k in weight_keys)
                    if total > 0 and abs(total - 1.0) > 0.001:
                        for k in weight_keys:
                            converted[k] = converted[k] / total

                # Merge modifiers (like 'bonus', 'noise_tolerance_multiplier')
                converted.update(cat.get('modifiers', {}))
                return converted

        return {}  # Category not found

    def get_scoring_limits(self):
        """Get scoring range limits and precision."""
        scoring = self.config.get('scoring', {})
        return {
            'score_min': scoring.get('score_min', 0.0),
            'score_max': scoring.get('score_max', 10.0),
            'score_precision': scoring.get('score_precision', 2),
        }

    def get_threshold(self, name):
        """Get a threshold value."""
        return self.config.get('thresholds', {}).get(name, 0)

    def get_thresholds(self):
        """Get all threshold values."""
        return self.config.get('thresholds', {})

    def get_composition_weights(self):
        """Get composition analysis weights."""
        return self.config.get('composition', {})

    def get_normalization_settings(self):
        """Get normalization method settings."""
        return self.config.get('normalization', {})

    def get_processing_settings(self):
        """Get unified processing settings.

        Returns settings for both GPU batch processing and RAM chunk processing
        (multi-pass mode). Includes auto-tuning configuration and thumbnail settings.
        """
        return self.config.get('processing', {
            'mode': 'auto',
            'gpu_batch_size': 16,
            'ram_chunk_size': 100,
            'num_workers': 4,
            'auto_tuning': {
                'enabled': True,
                'monitor_interval_seconds': 5,
                'tuning_interval_images': 50,
                'min_processing_workers': 1,
                'max_processing_workers': 24,
                'min_gpu_batch_size': 2,
                'max_gpu_batch_size': 32,
                'min_ram_chunk_size': 10,
                'max_ram_chunk_size': 500,
                'memory_limit_percent': 85,
                'cpu_target_percent': 80,
                'metrics_print_interval_seconds': 30,
            },
            'thumbnails': {
                'photo_size': 640,
                'photo_quality': 80,
                'face_padding_ratio': 0.3,
            }
        })

    def get_raw_decode_settings(self):
        """Get RAW demosaic and embedded-preview settings."""
        block = self.config.get('raw_decode', {})
        if not isinstance(block, dict):
            return dict(RAW_DECODE_DEFAULTS)
        return {**RAW_DECODE_DEFAULTS, **block}

    def get_scanning_settings(self):
        """Get directory scanning settings.

        Returns settings for directory traversal during photo scanning,
        including whether to skip hidden directories.
        """
        return self.config.get('scanning', {
            'skip_hidden_directories': True
        })

    def get_exif_adjustments(self):
        """Get EXIF-based scoring adjustment settings."""
        return self.config.get('exif_adjustments', {
            'iso_sharpness_compensation': True,
            'aperture_isolation_boost': True
        })

    def get_exposure_settings(self):
        """Get exposure analysis settings."""
        return self.config.get('exposure', {
            'shadow_clip_threshold_percent': 15,
            'highlight_clip_threshold_percent': 10,
            'silhouette_detection': True
        })

    def get_penalty_settings(self):
        """Get penalty settings for noise, bimodality, and leading lines blend."""
        return self.config.get('penalties', {
            'noise_sigma_threshold': 4.0,
            'noise_max_penalty_points': 1.5,
            'noise_penalty_per_sigma': 0.3,
            'bimodality_threshold': 2.5,
            'bimodality_penalty_points': 0.5,
            'leading_lines_blend_percent': 30
        })

    def get_analysis_settings(self):
        """Get analysis thresholds for --compute-percentiles recommendations."""
        return self.config.get('analysis', {
            'aesthetic_max_threshold': 9.0,
            'aesthetic_target': 9.5,
            'quality_avg_threshold': 7.5,
            'quality_weight_threshold_percent': 10,
            'correlation_dominant_threshold': 0.5,
            'category_min_samples': 50,
            'category_imbalance_threshold': 0.5,
            'score_clustering_std_threshold': 1.0,
            'top_score_threshold': 8.5,
            'exposure_avg_threshold': 8.0
        })

    def get_face_detection_settings(self):
        """Get face detection settings (confidence threshold, min face size)."""
        return self.config.get('face_detection', {
            'min_confidence_percent': 65,
            'min_face_size': 20
        })

    def get_monochrome_settings(self):
        """Get monochrome/B&W detection settings."""
        return self.config.get('monochrome_detection', {
            'saturation_threshold_percent': 10
        })

    def get_tagging_settings(self):
        """Get general tagging settings (enabled, max_tags).

        Note: Tagging model is configured per-profile in models.profiles.*.tagging_model.
        Use get_model_for_task('tagging') to get the configured model.
        CLIP-specific settings like similarity_threshold are in get_clip_settings().
        """
        return self.config.get('tagging', {
            'enabled': True,
            'max_tags': 5
        })

    def get_clip_settings(self):
        """Get CLIP model settings including similarity threshold for tagging."""
        models_config = self.get_model_config()
        return models_config.get('clip', {
            'model_name': 'ViT-L-14',
            'pretrained': 'laion2b_s32b_b82k',
            'similarity_threshold_percent': 22
        })

    def get_burst_detection_settings(self):
        """Get burst detection settings (similarity threshold percent, time window, rapid burst)."""
        return self.config.get('burst_detection', {
            'similarity_threshold_percent': 70,
            'time_window_minutes': 0.8,
            'rapid_burst_seconds': 0.4
        })

    def get_sequence_detection_settings(self):
        """Get exposure-bracket detection settings.

        Returns only what the config carries; `utils.sequence.DEFAULTS` supplies
        the rest, so a partial block tunes one threshold without having to
        restate the others.
        """
        return self.config.get('sequence_detection', {})

    def get_panorama_detection_settings(self):
        """Get panorama detection settings.

        Returns only what the config carries; `utils.panorama.DEFAULTS` supplies
        the rest, so a partial block tunes one threshold without having to
        restate the others.
        """
        return self.config.get('panorama_detection', {})

    def get_duplicate_detection_settings(self):
        """Get duplicate detection settings.

        Two-stage near-dup keys (with safe defaults when absent):
        - similarity_threshold_percent: strict pHash-only Hamming gate used when
          an embedding is missing for either photo (backward-compatible path).
        - prefilter_hamming: looser Hamming gate for the stage-1 candidate set
          when both photos have embeddings (recall); coerced to be >= the strict
          gate so two-stage is never stricter than pHash-only.
        - embedding_cosine_threshold: stage-2 SigLIP/CLIP cosine gate (precision);
          a loose-pHash candidate only merges if cosine >= this.
        """
        return self.config.get('duplicate_detection', {
            'similarity_threshold_percent': 90,
            'prefilter_hamming': 12,
            'embedding_cosine_threshold': 0.90,
        })

    def get_extended_iqa_settings(self):
        """Get the optional extended-IQA tier flags, as plain bools.

        These gate the heavy/experimental scorers that are NEVER a replacement
        for TOPIQ — they add supplementary columns only:
        - qrealign: Q-ReAlign-Mini 0.8B LLM-based IQA (pyiqa-backed). **
          Tri-state**: ``true`` | ``false`` | ``"auto"`` (the default). ``"auto"``
          resolves to enabled on every resolved VRAM profile except ``legacy``:
          at ~3GB it is the first extended-IQA scorer that fits from the 8gb
          profile up, so it does not need the opt-in the heavier scorers do.
          An explicit ``true``/``false`` always wins over the profile.
        - aesthetic_v25: Aesthetic Predictor V2.5 (light SigLIP head, ~2GB).
          Plain bool, OFF by default.
        - deqa: DeQA-Score VLM (very heavy; 16GB+ GPU to validate). Plain bool,
          OFF by default.

        Returns:
            dict of {'qrealign': bool, 'aesthetic_v25': bool, 'deqa': bool} —
            every value is a resolved bool, so callers never re-interpret
            'auto'.
        """
        section = self.config.get('iqa_extended', {})
        qrealign_raw = section.get('qrealign', 'auto')
        if isinstance(qrealign_raw, str) and qrealign_raw.strip().lower() == 'auto':
            # 'legacy' is the no-GPU / <6GB profile — a 3GB scorer does not
            # belong there, but every other profile has room for it.
            qrealign = self._resolved_vram_profile() != 'legacy'
        else:
            qrealign = bool(qrealign_raw)
        return {
            'qrealign': qrealign,
            'aesthetic_v25': bool(section.get('aesthetic_v25', False)),
            'deqa': bool(section.get('deqa', False)),
        }

    def get_face_clustering_settings(self):
        """Get face clustering settings."""
        return self.config.get('face_clustering', {
            'enabled': True,
            'min_faces_per_person': 2,
            'min_samples': 2,
            'auto_merge_distance_percent': 0,
            'clustering_algorithm': 'boruvka_balltree',
            'leaf_size': 40,
            'use_gpu': 'auto',
            'merge_threshold': 0.6
        })

    def get_face_processing_settings(self):
        """Get face processing settings (thumbnails, crop, parallel workers)."""
        return self.config.get('face_processing', {
            'crop_padding': 0.3,
            'use_db_thumbnails': True,
            'face_thumbnail_size': 640,
            'face_thumbnail_quality': 90,
            'extract_workers': 2,
            'extract_batch_size': 16,
            'refill_workers': 4,
            'refill_batch_size': 100,
            'auto_tuning': {
                'enabled': True,
                'memory_limit_percent': 80,
                'min_batch_size': 8,
                'monitor_interval_seconds': 5
            }
        })

    def get_comparison_mode_settings(self):
        """Get pairwise comparison mode settings."""
        return self.config.get('viewer', {}).get('comparison_mode', {
            'enabled': False,
            'min_comparisons_for_optimization': 50,
            'pair_selection_strategy': 'uncertainty',
            'show_current_scores': False
        })

    def get_model_config(self):
        """Get model configuration including VRAM profile and model settings."""
        default_models = {
            'vram_profile': 'legacy',
            'profiles': {
                'legacy': {
                    'aesthetic_model': 'clip-mlp',
                    'composition_model': 'rule-based',
                    'tagging_model': 'clip',
                    'description': 'CLIP+MLP aesthetic, rule-based composition (~2GB VRAM)'
                },
                '8gb': {
                    'aesthetic_model': 'clip-mlp',
                    'composition_model': 'samp-net',
                    'tagging_model': 'clip',
                    'description': 'CLIP+MLP aesthetic, SAMP-Net composition (~2GB VRAM)'
                },
                '16gb': {
                    'aesthetic_model': 'topiq',
                    'composition_model': 'samp-net',
                    'tagging_model': 'ram++',
                    'description': 'TOPIQ aesthetic, SAMP-Net composition (~14GB VRAM)'
                },
                '24gb': {
                    'aesthetic_model': 'topiq',
                    'composition_model': 'samp-net',
                    'tagging_model': 'qwen2.5-vl-7b',
                    'description': 'TOPIQ aesthetic, SAMP-Net composition (~18GB VRAM)'
                }
            },
            'qwen2_vl': {
                'model_path': 'Qwen/Qwen2-VL-2B-Instruct',
                'torch_dtype': 'bfloat16',
                'max_new_tokens': 256
            },
            'clip': {
                'model_name': 'ViT-L-14',
                'pretrained': 'laion2b_s32b_b82k'
            }
        }
        return self._merge_configs(default_models, self.config.get('models', {}))

    def get_clip_config(self):
        """Resolve CLIP/SigLIP model config based on active VRAM profile.

        Returns:
            dict with 'model_name', 'pretrained', 'embedding_dim', etc.
        """
        model_config = self.get_model_config()
        profiles = model_config.get('profiles', {})
        profile_name = model_config.get('vram_profile', 'legacy')
        active_profile = profiles.get(profile_name, profiles.get('legacy', {}))
        clip_config_key = active_profile.get('clip_config', 'clip')
        return model_config.get(clip_config_key, model_config.get('clip', {}))

    def get_samp_net_config(self):
        """Get SAMP-Net model configuration for composition scoring."""
        models_config = self.get_model_config()
        return models_config.get('samp_net', {'model_path': 'pretrained_models/samp_net.pth'})

    def _resolved_vram_profile(self) -> str:
        """The active VRAM profile name, with 'auto' resolved to the detected one.

        Single place that turns the configured profile into a concrete one, so
        every profile-conditional feature agrees on the answer. The
        FACET_VRAM_PROFILE env override is already folded into
        models.vram_profile by _load_config, so it is honored here too.
        """
        profile_name = self.get_model_config().get('vram_profile', 'legacy')
        if profile_name == 'auto':
            # Resolve 'auto' to the detected profile (in-memory, once) so the
            # lookup never falls through to the legacy profile.
            self.check_vram_profile_compatibility(verbose=False)
            profile_name = self.get_model_config().get('vram_profile', 'legacy')
        return profile_name

    def get_model_for_task(self, task: str) -> str:
        """Get the model name configured for a specific task (aesthetic, composition, tagging).

        Args:
            task: One of 'aesthetic', 'composition', or 'tagging'

        Returns:
            Model name string (e.g., 'topiq', 'samp-net', 'rule-based')
        """
        models_config = self.get_model_config()
        profile_name = self._resolved_vram_profile()
        profiles = models_config.get('profiles', {})
        profile = profiles.get(profile_name, profiles.get('legacy', {}))

        task_key = f'{task}_model'
        return profile.get(task_key, 'rule-based')

    def is_using_samp_net(self) -> bool:
        """Check if SAMP-Net is configured for composition scoring."""
        return self.get_model_for_task('composition') == 'samp-net'

    @staticmethod
    def detect_gpu_vram_gb():
        """Detect usable GPU VRAM in gigabytes.

        A card whose compute capability this PyTorch build ships no kernels
        for reports its VRAM happily and then dies on the first real op, so
        the sizing goes through utils.device.is_device_available rather than
        torch.cuda.is_available (issue #119).

        Returns:
            Float representing VRAM in GB, or None if no usable GPU
        """
        try:
            import torch

            from utils.device import is_device_available
            if not is_device_available("cuda", torch_module=torch):
                return None
            # Get VRAM of the first GPU (index 0)
            vram_bytes = torch.cuda.get_device_properties(0).total_memory
            vram_gb = vram_bytes / (1024 ** 3)
            return round(vram_gb, 1)
        except Exception:
            return None

    @staticmethod
    def suggest_profile_for_unified_memory(total_memory_gb):
        """Pick a profile for an Apple Metal machine from its total unified memory.

        Metal has no dedicated VRAM, so the CUDA sizing path has no number to
        read there. Unified memory is system RAM: the models share it with
        macOS, the window server and every other running application, and a Mac
        that swaps is far slower than one on a smaller profile. Each threshold
        in UNIFIED_MEMORY_PROFILE_THRESHOLDS_GB therefore asks for about twice
        the profile's model footprint (legacy ~2GB, 8gb ~6GB, 16gb ~14GB, 24gb
        ~20GB of weights plus inference), never less than that footprint plus
        8GB left to the rest of the system, rounded up to a memory
        configuration Apple actually ships.

        Args:
            total_memory_gb: Total unified memory in GB

        Returns:
            Profile name: 'legacy', '8gb', '16gb', or '24gb'
        """
        for profile, minimum_gb in UNIFIED_MEMORY_PROFILE_THRESHOLDS_GB:
            if total_memory_gb >= minimum_gb:
                return profile
        return UNIFIED_MEMORY_MINIMUM_PROFILE

    @staticmethod
    def suggest_vram_profile(vram_gb=None):
        """Suggest the appropriate VRAM profile based on detected or provided VRAM.

        A CUDA device is sized from its dedicated VRAM. Apple Metal reports no
        such figure, so it is sized from total unified memory instead (see
        suggest_profile_for_unified_memory) and the returned VRAM stays None
        rather than borrowing a number that does not exist there.

        A card this PyTorch build ships no kernels for yields no VRAM either,
        but it is present: the message says so instead of "No GPU detected",
        which would contradict --doctor's own arch diagnosis (issue #119).

        Args:
            vram_gb: VRAM in GB (if None, will auto-detect)

        Returns:
            Tuple of (suggested_profile: str, vram_gb: float or None, message: str)
        """
        if vram_gb is None:
            vram_gb = ScoringConfig.detect_gpu_vram_gb()

        if vram_gb is None:
            try:
                from utils.device import mps_available
                has_mps = mps_available()
            except Exception:
                has_mps = False
            force_cpu = os.environ.get('FACET_DEVICE', 'auto').strip().lower() == 'cpu'
            mismatch = None if has_mps else _unusable_cuda_status()
            no_gpu = (
                "GPU unusable by this PyTorch build"
                if mismatch is not None else "No GPU detected"
            )
            profile = UNIFIED_MEMORY_MINIMUM_PROFILE
            ram_gb = _readable_system_ram_gb()
            if ram_gb is None:
                msg = (
                    "Apple Metal (MPS) detected, using legacy profile"
                    if has_mps and not force_cpu else
                    f"{no_gpu}, using legacy (CPU-only) profile"
                )
            elif has_mps and not force_cpu:
                profile = ScoringConfig.suggest_profile_for_unified_memory(ram_gb)
                msg = (
                    f"Apple Metal (MPS) detected, {ram_gb:.0f}GB unified memory - "
                    f"{profile} profile (sized from total unified memory; "
                    "Torch models accelerated, InsightFace on CPU)"
                )
            elif has_mps:
                msg = (
                    f"Apple Metal (MPS) available, {ram_gb:.0f}GB RAM - "
                    "legacy profile (FACET_DEVICE=cpu)"
                )
            elif ram_gb >= 8:
                msg = f"{no_gpu}, {ram_gb:.0f}GB RAM - legacy profile (TOPIQ + SAMP-Net on CPU)"
            else:
                msg = f"{no_gpu}, {ram_gb:.0f}GB RAM - legacy profile (limited CPU mode)"
            if mismatch is not None:
                msg += f"\n  {mismatch.reason}"
            msg += "\n  Tip: run 'python facet.py --doctor' for GPU setup diagnostics"
            return profile, None, msg

        # Profile recommendations based on VRAM
        if vram_gb >= 20:
            profile = '24gb'
            msg = f"Detected {vram_gb:.1f}GB VRAM - recommended profile: 24gb (TOPIQ + Qwen2-VL)"
        elif vram_gb >= 14:
            profile = '16gb'
            msg = f"Detected {vram_gb:.1f}GB VRAM - recommended profile: 16gb (TOPIQ + SAMP-Net)"
        elif vram_gb >= 6:
            profile = '8gb'
            msg = f"Detected {vram_gb:.1f}GB VRAM - recommended profile: 8gb (TOPIQ + SAMP-Net)"
        else:
            profile = 'legacy'
            msg = f"Detected {vram_gb:.1f}GB VRAM - recommended profile: legacy (TOPIQ + SAMP-Net)"

        return profile, vram_gb, msg

    def check_vram_profile_compatibility(self, verbose=True):
        """Check if the configured VRAM profile is compatible with available hardware.

        If vram_profile is "auto", automatically selects the best profile based on
        detected VRAM and updates the config in memory.

        Args:
            verbose: If True, print warnings/suggestions

        Returns:
            Tuple of (is_compatible: bool, suggested_profile: str, message: str)
        """
        current_profile = self.get_model_config().get('vram_profile', 'legacy')
        suggested_profile, vram_gb, msg = self.suggest_vram_profile()

        # Handle "auto" profile - automatically select best profile
        if current_profile == 'auto':
            if verbose:
                logger.info("Auto-detecting VRAM profile: %s", msg)

            # Update config in memory to use the resolved profile
            if 'models' in self.config:
                self.config['models']['vram_profile'] = suggested_profile
            current_profile = suggested_profile

            return True, suggested_profile, msg

        if vram_gb is None:
            try:
                from utils.device import mps_available
                has_mps = (
                    mps_available()
                    and os.environ.get('FACET_DEVICE', 'auto').strip().lower() != 'cpu'
                )
            except Exception:
                has_mps = False
            if current_profile != 'legacy':
                if has_mps:
                    if verbose:
                        logger.info(
                            "Profile '%s' on Metal: unified memory is not dedicated VRAM, so the "
                            "profile is taken as configured rather than sized automatically",
                            current_profile)
                        logger.info("  Set vram_profile to 'auto' to size it from total unified memory instead")
                    return True, current_profile, "OK (MPS mode, profile as configured)"
                mismatch = _unusable_cuda_status()
                if verbose:
                    if mismatch is not None:
                        logger.warning(
                            "GPU present but unusable by this PyTorch build, so profile '%s' "
                            "cannot run: %s", current_profile, mismatch.reason)
                    else:
                        logger.warning("No GPU does not support VRAM profile '%s'", current_profile)
                    logger.warning("  Consider setting vram_profile to 'legacy' or 'auto' in scoring_config.json")
                    logger.warning("  Tip: run 'python facet.py --doctor' for GPU setup diagnostics")
                if mismatch is not None:
                    return False, 'legacy', f"GPU unusable by this PyTorch build: {mismatch.reason}"
                return False, 'legacy', "No GPU detected"
            return True, current_profile, "OK (MPS mode)" if has_mps else "OK (CPU mode)"

        # Define VRAM requirements for each profile
        profile_requirements = {
            'legacy': 2,
            '8gb': 6,
            '16gb': 14,
            '24gb': 20,
        }

        required_vram = profile_requirements.get(current_profile, 0)

        if vram_gb < required_vram:
            if verbose:
                logger.warning("Profile '%s' requires ~%dGB VRAM, but only %.1fGB detected", current_profile, required_vram, vram_gb)
                logger.warning("  %s", msg)
                logger.warning("  Consider setting vram_profile to '%s' or 'auto' in scoring_config.json", suggested_profile)
            return False, suggested_profile, f"Insufficient VRAM for {current_profile}"

        if verbose and current_profile != suggested_profile:
            # Profile is compatible but could use a better one
            logger.info("Note: %s", msg)

        return True, current_profile, "OK"

    def _tag_vocabulary_collisions(self):
        """Find tag names redefined with a *different* synonym list.

        Used by get_tag_vocabulary() to warn instead of silently overwriting
        — plain dict.update() has no collision check on its own, so two
        categories (or a category and standalone_tags) claiming the same tag
        name would otherwise drop a synonym list library-wide without a trace.

        Returns:
            List of human-readable collision descriptions.
        """
        vocabulary = {}
        collisions = []
        for cat in self.config.get('categories', []):
            tags = cat.get('tags', {})
            if not isinstance(tags, dict):
                continue
            for tag_name, synonyms in tags.items():
                if tag_name in vocabulary and vocabulary[tag_name] != synonyms:
                    collisions.append(
                        f"tag '{tag_name}': category '{cat.get('name', 'unnamed')}' "
                        f"redefines synonyms {vocabulary[tag_name]!r} -> {synonyms!r}"
                    )
                vocabulary[tag_name] = synonyms
        standalone = self.config.get('standalone_tags', {})
        if isinstance(standalone, dict):
            for tag_name, synonyms in standalone.items():
                if tag_name in vocabulary and vocabulary[tag_name] != synonyms:
                    collisions.append(
                        f"tag '{tag_name}': standalone_tags redefines synonyms "
                        f"{vocabulary[tag_name]!r} -> {synonyms!r}"
                    )
                vocabulary[tag_name] = synonyms
        return collisions

    def get_tag_vocabulary(self):
        """Build tag vocabulary from all category tags and standalone tags.

        Returns dict: {tag_name: [synonyms]} aggregated from all categories
        plus any standalone_tags defined at the top level. When two entries
        claim the same tag name with different synonyms, the last one
        encountered wins (dict.update() semantics) and a warning is logged —
        see _tag_vocabulary_collisions().
        """
        for collision in self._tag_vocabulary_collisions():
            logger.warning("get_tag_vocabulary: %s (last definition wins)", collision)
        vocabulary = {}
        # Add tags from categories
        for cat in self.config.get('categories', []):
            tags = cat.get('tags', {})
            if isinstance(tags, dict):
                vocabulary.update(tags)
        # Add standalone tags (detection-only, no category)
        standalone = self.config.get('standalone_tags', {})
        if isinstance(standalone, dict):
            vocabulary.update(standalone)
        return vocabulary

    def get_art_tags(self):
        """Get set of tags that indicate artwork."""
        return set(self.get_category_tags('art'))

    def get_narrative_moments_config(self):
        """Return the narrative_moments config block (empty/disabled if absent)."""
        nm = self.config.get('narrative_moments', {})
        if not isinstance(nm, dict):
            return {'enabled': False}
        return nm

    def get_active_event_type(self):
        """Return the configured default event type (e.g. 'general')."""
        return self.get_narrative_moments_config().get('default_event_type', 'general')

    def get_narrative_moment_vocabulary(self, event_type=None):
        """Return ``{moment: [prompt synonyms]}`` for the active/given event type.

        The narrative-moment analog of ``get_tag_vocabulary()``. Insertion order
        of the moments is the canonical chronological order used by L2 smoothing.
        """
        nm = self.get_narrative_moments_config()
        event_types = nm.get('event_types', {})
        et = event_type or nm.get('default_event_type', 'general')
        vocab = event_types.get(et, {})
        return vocab if isinstance(vocab, dict) else {}

    def get_moment_transitions(self, event_type=None):
        """Return the L2 transition params plus the canonical moment order."""
        nm = self.get_narrative_moments_config()
        transitions = dict(nm.get('transitions', {}))
        transitions['order'] = list(self.get_narrative_moment_vocabulary(event_type).keys())
        return transitions

    def get_moment_priors(self, event_type=None):
        """Return the L1 prior settings + resolved rule list for an event type.

        Per-event-type ``priors.event_types.<et>.rules`` overrides the global
        ``priors.rules`` when present, so the shared list stays vocabulary-clean
        while a custom vocab (e.g. ``wedding``) can ship its own boosts. Each
        rule is ``{kind, when, boost}`` (see ``MomentClassifier._prior_logits``).
        """
        nm = self.get_narrative_moments_config()
        priors = nm.get('priors', {}) or {}
        et = event_type or nm.get('default_event_type', 'general')
        per_et = (priors.get('event_types', {}) or {}).get(et, {})
        rules = per_et.get('rules')
        if rules is None:
            rules = priors.get('rules', [])
        return {
            'enabled': bool(priors.get('enabled', True)),
            'weight': float(priors.get('weight', 0.04)),
            'caption_tag_scale': float(priors.get('caption_tag_scale', 0.25)),
            'rules': rules if isinstance(rules, list) else [],
        }

    def get_moment_thresholds(self, signal):
        """Return the per-backend ``other``-gate thresholds for a moment signal.

        ``signal`` is ``'caption'`` (matched against the stored caption text
        embedding) or ``'image'`` (the stored image embedding). Caption cosines
        run ~2.4x higher than image cosines, so each signal carries its own
        ``{backend: {min_confidence, min_margin}}`` set.
        """
        thresholds = self.get_narrative_moments_config().get('thresholds', {})
        return thresholds.get(signal, {})

    def get_moment_vlm_tiebreak(self):
        """Return the L3 VLM tie-break settings for narrative-moment labelling.

        ``{enabled, min_confidence, min_margin}``. Only frames whose smoothed
        posterior falls below ``min_confidence`` *or* whose L0+L1 top-1/top-2
        probability margin falls below ``min_margin`` are re-classified by the
        VLM (16gb/24gb profiles only). Disabled by default — a config-only stub
        until enabled.
        """
        vt = self.get_narrative_moments_config().get('vlm_tiebreak', {}) or {}
        return {
            'enabled': bool(vt.get('enabled', False)),
            'min_confidence': float(vt.get('min_confidence', 0.0)),
            'min_margin': float(vt.get('min_margin', 0.04)),
        }

    def get_caption_min_confidence(self):
        """Min narrative-moment posterior required to auto-caption a photo (F5).

        ``0`` (default) disables the gate — every uncaptioned photo is eligible.
        When > 0, ``--generate-captions`` and the on-demand caption endpoint skip
        photos that are unlabelled, labelled ``other``, or below this confidence.
        """
        return float(self.get_narrative_moments_config().get('caption_min_confidence', 0.0))

    def get_ocr_config(self):
        """Return the ocr config block (empty/disabled if absent)."""
        block = self.config.get('ocr', {})
        if not isinstance(block, dict):
            return {'enabled': False}
        return block

    def get_junk_sweep_config(self):
        """Return the junk_sweep config block (empty/disabled if absent)."""
        js = self.config.get('junk_sweep', {})
        if not isinstance(js, dict):
            return {'enabled': False}
        return js

    def get_junk_kinds(self):
        """Return ``{kind: [prompt synonyms]}`` for zero-shot junk detection."""
        kinds = self.get_junk_sweep_config().get('kinds', {})
        return kinds if isinstance(kinds, dict) else {}

    def get_junk_not_junk_prompts(self):
        """Return the contrast ``not_junk`` prompts that gate real photographs."""
        prompts = self.get_junk_sweep_config().get('not_junk_prompts', [])
        return prompts if isinstance(prompts, list) else []

    def get_junk_thresholds(self):
        """Return per-backend junk-gate thresholds ``{backend: {min_confidence, min_margin}}``.

        Backend is ``open_clip`` (CLIP, lower cosines) or ``transformers``
        (SigLIP, higher cosines), so each carries its own confidence/margin.
        """
        thresholds = self.get_junk_sweep_config().get('thresholds', {})
        return thresholds if isinstance(thresholds, dict) else {}

    def get_category_tags(self, category):
        """Get trigger tags for a category.

        Args:
            category: Category name (e.g., 'astro', 'concert', 'wildlife')

        Returns:
            List of tag names (keys from tags dict) for the category
        """
        for cat in self.config.get('categories', []):
            if cat.get('name') == category:
                tags = cat.get('tags', {})
                if isinstance(tags, dict):
                    return list(tags.keys())
        return []

    def get_category_config(self, category):
        """Get full config for a category.

        Args:
            category: Category name (e.g., 'street')

        Returns:
            Dict with category configuration (name, priority, filters, weights, modifiers, tags)
        """
        for cat in self.config.get('categories', []):
            if cat.get('name') == category:
                return cat
        return {}

    def _priority_sorted_categories(self):
        """Get list of category configurations sorted by priority.

        Returns:
            List of category config dicts sorted by priority (lower = higher priority).
            Each dict contains: 'name', 'priority', 'filters', 'weights', 'modifiers', 'tags'
        """
        categories = self.config.get('categories', [])
        return sorted(categories, key=lambda c: c.get('priority', 100))

    def get_categories(self, context=None):
        """Get category configurations, optionally reordered by a scoring context.

        Args:
            context: Scoring context name (see ``get_scoring_contexts``), or None
                for the plain global priority order.

        Returns:
            List of category config dicts. With no context, sorted by priority
            (lower = higher priority) — identical to prior behaviour. With a
            context, the delta-adjusted order from ``resolve_context_order``.
        """
        if context is None:
            return self._priority_sorted_categories()
        return [self.get_category_config(name) for name, _ in self.resolve_context_order(context)]

    def get_scoring_contexts(self):
        """Return the ``scoring_contexts`` config block.

        Returns:
            Dict mapping context name to ``{label_key, promote, excluded,
            suggest_from_moments}``. Empty dict when the block is absent.
        """
        contexts = self.config.get('scoring_contexts', {})
        return contexts if isinstance(contexts, dict) else {}

    def resolve_context_order(self, context=None):
        """Resolve the memoized, delta-adjusted category evaluation order for a context.

        Effective order = the context's ``promote`` names (in the order given)
        → the global priority order minus promoted and excluded names →
        ``default`` last (untouched by promote/excluded). An unknown or
        unconfigured context name falls back to the ``default`` preset and logs
        a warning. Result is memoized per context name for the lifetime of this
        instance.

        Args:
            context: Scoring context name, or None for the ``default`` preset.

        Returns:
            List of ``(category_name, CategoryFilter)`` tuples.
        """
        cache_key = context or DEFAULT_CONTEXT_NAME
        if cache_key in self._context_order_cache:
            return self._context_order_cache[cache_key]

        contexts = self.get_scoring_contexts()
        context_def = contexts.get(context)
        if context_def is None:
            if context:
                logger.warning("Unknown scoring context %r, falling back to default order", context)
            context_def = contexts.get(DEFAULT_CONTEXT_NAME, {})
        if not isinstance(context_def, dict):
            logger.warning(
                "Malformed scoring context %r (expected object, got %s), falling back to default order",
                context or DEFAULT_CONTEXT_NAME, type(context_def).__name__,
            )
            context_def = {}

        promote, promote_problems = _sanitize_context_names(context_def, 'promote')
        excluded_names, excluded_problems = _sanitize_context_names(context_def, 'excluded')
        excluded = set(excluded_names)
        for problem in promote_problems + excluded_problems:
            logger.warning("scoring_contexts.%s: %s", cache_key, problem)

        by_name = {}
        for category in self.config.get('categories', []):
            name = _usable_category_name(category)
            if name is None:
                logger.warning(
                    "categories: entry with priority %r has no usable 'name' (%r), skipping it",
                    category.get('priority'), category.get('name'),
                )
                continue
            by_name[name] = category

        ordered = []
        seen = set()
        for name in promote:
            category = by_name.get(name)
            if category is None or name == DEFAULT_CATEGORY_NAME or name in excluded or name in seen:
                continue
            ordered.append(category)
            seen.add(name)

        for category in self._priority_sorted_categories():
            name = _usable_category_name(category)
            if name is None or name == DEFAULT_CATEGORY_NAME or name in excluded or name in seen:
                continue
            ordered.append(category)
            seen.add(name)

        default_category = by_name.get(DEFAULT_CATEGORY_NAME)
        if default_category is not None:
            ordered.append(default_category)

        result = [(c.get('name'), CategoryFilter(c.get('filters', {}))) for c in ordered]
        self._context_order_cache[cache_key] = result
        return result

    def determine_category(self, photo_data: dict, context: str | None = None) -> str:
        """Determine which category a photo belongs to using config-driven filters.

        Evaluates categories in the context's effective order, returns first match.

        Args:
            photo_data: Dict with photo metrics. Expected keys:
                - tags: comma-separated string
                - face_count, face_ratio, is_silhouette, is_group_portrait, is_monochrome
                - mean_luminance, iso, shutter_speed, focal_length, f_stop
            context: Scoring context name, or None for the global priority order.

        Returns:
            Category name string (e.g., 'portrait', 'default')
        """
        for name, category_filter in self.resolve_context_order(context):
            if category_filter.matches(photo_data):
                return name

        return self.config.get('viewer', {}).get('default_category', 'default')

    def validate_schema(self):
        """Validate config structure against config/scoring_config.schema.json.

        Returns a list of human-readable errors, each prefixed with the failing
        JSON path. Empty when valid — or when jsonschema is not installed, since
        the structural check is optional and soft-fails rather than blocking a
        load.
        """
        try:
            import jsonschema
        except ImportError:
            return []
        schema_path = os.path.join(os.path.dirname(__file__), 'scoring_config.schema.json')
        try:
            with open(schema_path) as f:
                schema = json.load(f)
        except (OSError, ValueError) as ex:
            logger.warning("Could not load config schema: %s", ex)
            return []
        validator = jsonschema.Draft202012Validator(schema)
        errors = []
        for err in sorted(validator.iter_errors(self.config), key=lambda e: list(e.path)):
            path = "/".join(str(p) for p in err.path) or "(root)"
            errors.append(f"{path}: {err.message}")
        return errors

    def validate_categories(self, verbose=True):
        """Validate all category configurations.

        Checks:
        - Structural schema (config/scoring_config.schema.json)
        - Weights sum to 100%
        - Priority is set and unique
        - Filters use valid keys
        - scoring_contexts reference real category names and narrative moments,
          and don't list the same category in both promote and excluded

        Args:
            verbose: If True, print validation issues

        Returns:
            Tuple of (is_valid: bool, issues: list of error strings)
        """
        issues = [f"schema: {e}" for e in self.validate_schema()]
        priorities_seen = {}

        for cat in self.get_categories():
            name = cat.get('name', 'unnamed')
            weights = cat.get('weights', {})

            # Check weights sum to ~100%
            percent_weights = {k: v for k, v in weights.items() if k.endswith('_percent')}
            if percent_weights:
                total = sum(percent_weights.values())
                if abs(total - 100) > 1:  # Allow 1% tolerance
                    issues.append(f"{name}: weights sum to {total}%, expected 100%")

            # Check priority
            priority = cat.get('priority')
            if priority is None:
                issues.append(f"{name}: missing priority field")
            elif priority in priorities_seen:
                issues.append(f"Duplicate priority {priority}: {name} and {priorities_seen[priority]}")
            else:
                priorities_seen[priority] = name

            # Check filter validity
            filters = cat.get('filters', {})
            all_valid_filters = VALID_NUMERIC_FILTERS + VALID_BOOLEAN_FILTERS + VALID_TAG_FILTERS
            for key in filters:
                if key not in all_valid_filters:
                    issues.append(f"{name}: unknown filter '{key}'")

            # Check tag_match_mode
            if filters.get('tag_match_mode') not in (None, 'any', 'all'):
                issues.append(f"{name}: invalid tag_match_mode '{filters.get('tag_match_mode')}'")

        category_names = {cat.get('name') for cat in self.get_categories()}
        moment_names = set(self.get_narrative_moment_vocabulary())
        event_type = self.get_active_event_type()

        for context_name, context_def in self.get_scoring_contexts().items():
            if not isinstance(context_def, dict):
                continue
            promote, promote_problems = _sanitize_context_names(context_def, 'promote')
            excluded, excluded_problems = _sanitize_context_names(context_def, 'excluded')
            moments, moment_problems = _sanitize_context_names(context_def, 'suggest_from_moments')
            for problem in promote_problems + excluded_problems + moment_problems:
                issues.append(f"scoring_contexts.{context_name}: {problem}")

            for name in promote:
                if name not in category_names:
                    issues.append(
                        f"scoring_contexts.{context_name}: promote references unknown category '{name}'"
                    )
            for name in excluded:
                if name not in category_names:
                    issues.append(
                        f"scoring_contexts.{context_name}: excluded references unknown category '{name}'"
                    )

            for name in sorted(set(promote) & set(excluded)):
                issues.append(
                    f"scoring_contexts.{context_name}: '{name}' is listed in both promote and excluded "
                    f"(excluded wins — the promote entry is dropped)"
                )

            for moment in moments:
                if moment not in moment_names:
                    issues.append(
                        f"scoring_contexts.{context_name}: suggest_from_moments references unknown moment "
                        f"'{moment}' (not in narrative_moments.event_types.{event_type})"
                    )

        if verbose:
            for issue in issues:
                logger.warning("Validation issue: %s", issue)
            if not issues:
                logger.info("Category validation passed: %d categories valid", len(self.get_categories()))

        return len(issues) == 0, issues

    def get_all_category_names(self):
        """Get list of all category names in priority order.

        Returns:
            List of category name strings
        """
        return [cat['name'] for cat in self.get_categories()]
