"""
Facet Scoring Configuration.

Contains ScoringConfig class and helper functions.
"""

import os
import json
import hashlib

# Valid filter fields for v4.0 category-centric config
VALID_NUMERIC_FILTERS = [
    "face_ratio_min", "face_ratio_max",
    "face_count_min", "face_count_max",
    "iso_min", "iso_max",
    "shutter_speed_min", "shutter_speed_max",
    "luminance_min", "luminance_max",
    "focal_length_min", "focal_length_max",
    "f_stop_min", "f_stop_max",
]

VALID_BOOLEAN_FILTERS = [
    "has_face", "is_monochrome", "is_silhouette", "is_group_portrait"
]

VALID_TAG_FILTERS = [
    "required_tags", "excluded_tags", "tag_match_mode"
]

# All valid weight column names (without _percent suffix)
VALID_WEIGHT_COLUMNS = [
    "aesthetic", "face_quality", "eye_sharpness", "tech_sharpness",
    "exposure", "composition", "color", "quality", "contrast",
    "dynamic_range", "isolation", "leading_lines",
    # Supplementary PyIQA metrics
    "aesthetic_iaa", "face_quality_iqa", "liqe",
    # Subject saliency metrics (InSPyReNet)
    "subject_sharpness", "subject_prominence", "subject_placement", "bg_separation",
]

# Tolerance for weight normalization - weights within this range of 100% are not auto-normalized
# This preserves targeted changes from recommendations
NORMALIZATION_TOLERANCE = 5  # +/- 5% tolerance (95-105%)


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

class ScoringConfig:
    """Loads and manages scoring configuration from JSON file.

    Requires v4.0 category-centric config format. The config file must contain
    a 'categories' array with category definitions sorted by priority.
    """

    def __init__(self, config_path=None, validate=True):
        self.config_path = config_path or 'scoring_config.json'
        self.config = self._load_config()
        self.version_hash = self._compute_version_hash()
        if validate:
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
            # If all values are <= 1 and sum <= 1, assume they're decimals
            all_small = all(v <= 1 for v in percent_items.values())
            total_small = sum(percent_items.values()) <= 1.01
            if all_small and total_small and len(percent_items) > 1:
                for key, value in percent_items.items():
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
                    print(f"Normalized '{category}' weights from {old_total}% to 100%")

            if corrections:
                corrected_categories.append(category)
                if verbose:
                    print(f"Corrected '{category}' weights:")
                    for c in corrections:
                        print(c)

        # Save config if any categories were corrected
        if corrected_categories:
            self.save_config()
            self.version_hash = self._compute_version_hash()
            if verbose:
                print(f"Saved corrected config to {self.config_path}")

        is_valid = len(corrected_categories) == 0
        if verbose and is_valid:
            print(f"Config validation passed: all {len(categories)} categories have valid weight totals")

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
            'min_confidence_percent': 70,
            'min_face_size': 30
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
            'similarity_threshold_percent': 88,
            'time_window_minutes': 60,
            'rapid_burst_seconds': 5
        })

    def get_duplicate_detection_settings(self):
        """Get duplicate detection settings (similarity threshold)."""
        return self.config.get('duplicate_detection', {
            'similarity_threshold_percent': 90
        })

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
            'merge_threshold': 0.6,
            'chunk_size': 10000
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
                    'composition_model': 'qwen2-vl-2b',
                    'tagging_model': 'qwen2.5-vl-7b',
                    'description': 'TOPIQ aesthetic, Qwen2-VL composition (~18GB VRAM)'
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
        return models_config.get('samp_net', {
            'model_path': 'pretrained_models/samp_net.pth',
            'download_url': 'https://github.com/bcmi/Image-Composition-Assessment-with-SAMP/releases/download/v1.0/samp_net.pth',
            'input_size': 384,
            'patterns': ['none', 'center', 'rule_of_thirds', 'golden_ratio', 'triangle',
                        'horizontal', 'vertical', 'diagonal', 'symmetric',
                        'curved', 'radial', 'vanishing_point', 'pattern', 'fill_frame']
        })

    def get_model_for_task(self, task: str) -> str:
        """Get the model name configured for a specific task (aesthetic, composition, tagging).

        Args:
            task: One of 'aesthetic', 'composition', or 'tagging'

        Returns:
            Model name string (e.g., 'topiq', 'samp-net', 'rule-based')
        """
        models_config = self.get_model_config()
        profile_name = models_config.get('vram_profile', 'legacy')
        profiles = models_config.get('profiles', {})
        profile = profiles.get(profile_name, profiles.get('legacy', {}))

        task_key = f'{task}_model'
        return profile.get(task_key, 'rule-based')

    def is_using_samp_net(self) -> bool:
        """Check if SAMP-Net is configured for composition scoring."""
        return self.get_model_for_task('composition') == 'samp-net'

    @staticmethod
    def detect_gpu_vram_gb():
        """Detect available GPU VRAM in gigabytes.

        Returns:
            Float representing VRAM in GB, or None if no GPU detected
        """
        try:
            import torch
            if not torch.cuda.is_available():
                return None
            # Get VRAM of the first GPU (index 0)
            vram_bytes = torch.cuda.get_device_properties(0).total_memory
            vram_gb = vram_bytes / (1024 ** 3)
            return round(vram_gb, 1)
        except Exception:
            return None

    @staticmethod
    def suggest_vram_profile(vram_gb=None):
        """Suggest the appropriate VRAM profile based on detected or provided VRAM.

        Args:
            vram_gb: VRAM in GB (if None, will auto-detect)

        Returns:
            Tuple of (suggested_profile: str, vram_gb: float or None, message: str)
        """
        if vram_gb is None:
            vram_gb = ScoringConfig.detect_gpu_vram_gb()

        if vram_gb is None:
            try:
                import psutil
                ram_gb = psutil.virtual_memory().total / (1024**3)
                if ram_gb >= 8:
                    msg = f"No GPU detected, {ram_gb:.0f}GB RAM - legacy profile (TOPIQ + SAMP-Net on CPU)"
                else:
                    msg = f"No GPU detected, {ram_gb:.0f}GB RAM - legacy profile (limited CPU mode)"
            except Exception:
                msg = "No GPU detected, using legacy (CPU-only) profile"
            return 'legacy', None, msg

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
                print(f"Auto-detecting VRAM profile: {msg}")

            # Update config in memory to use the resolved profile
            if 'models' in self.config:
                self.config['models']['vram_profile'] = suggested_profile
            current_profile = suggested_profile

            return True, suggested_profile, msg

        if vram_gb is None:
            if current_profile != 'legacy':
                if verbose:
                    print(f"Warning: No GPU detected but profile '{current_profile}' is configured")
                    print("  Consider setting vram_profile to 'legacy' or 'auto' in scoring_config.json")
                return False, 'legacy', "No GPU detected"
            return True, current_profile, "OK (CPU mode)"

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
                print(f"Warning: Profile '{current_profile}' requires ~{required_vram}GB VRAM, but only {vram_gb:.1f}GB detected")
                print(f"  {msg}")
                print(f"  Consider setting vram_profile to '{suggested_profile}' or 'auto' in scoring_config.json")
            return False, suggested_profile, f"Insufficient VRAM for {current_profile}"

        if verbose and current_profile != suggested_profile:
            # Profile is compatible but could use a better one
            print(f"Note: {msg}")

        return True, current_profile, "OK"

    def get_tag_vocabulary(self):
        """Build tag vocabulary from all category tags and standalone tags.

        Returns dict: {tag_name: [synonyms]} aggregated from all categories
        plus any standalone_tags defined at the top level.
        """
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

    def get_categories(self):
        """Get list of category configurations sorted by priority.

        Returns:
            List of category config dicts sorted by priority (lower = higher priority).
            Each dict contains: 'name', 'priority', 'filters', 'weights', 'modifiers', 'tags'
        """
        categories = self.config.get('categories', [])
        return sorted(categories, key=lambda c: c.get('priority', 100))

    def determine_category(self, photo_data: dict) -> str:
        """Determine which category a photo belongs to using config-driven filters.

        Evaluates categories in priority order, returns first match.

        Args:
            photo_data: Dict with photo metrics. Expected keys:
                - tags: comma-separated string
                - face_count, face_ratio, is_silhouette, is_group_portrait, is_monochrome
                - mean_luminance, iso, shutter_speed, focal_length, f_stop

        Returns:
            Category name string (e.g., 'portrait', 'default')
        """
        for category in self.get_categories():
            filter_config = category.get('filters', {})
            category_filter = CategoryFilter(filter_config)
            if category_filter.matches(photo_data):
                return category['name']

        return self.config.get('viewer', {}).get('default_category', 'default')

    def validate_categories(self, verbose=True):
        """Validate all category configurations.

        Checks:
        - Weights sum to 100%
        - Priority is set and unique
        - Filters use valid keys

        Args:
            verbose: If True, print validation issues

        Returns:
            Tuple of (is_valid: bool, issues: list of error strings)
        """
        issues = []
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

        if verbose:
            for issue in issues:
                print(f"Validation issue: {issue}")
            if not issues:
                print(f"Category validation passed: {len(self.get_categories())} categories valid")

        return len(issues) == 0, issues

    def get_all_category_names(self):
        """Get list of all category names in priority order.

        Returns:
            List of category name strings
        """
        return [cat['name'] for cat in self.get_categories()]


