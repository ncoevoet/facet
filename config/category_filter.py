"""
Facet Category Filter.

Evaluates whether a photo matches a category's filter rules.
"""


import math


FACE_DEFAULT_FIELDS = ("face_count", "face_ratio", "is_group_portrait")


def with_face_defaults(photo_data: dict) -> dict:
    """Return a copy of ``photo_data`` with NULL face fields coalesced to 0.

    A failed face pass stores ``face_count`` / ``face_ratio`` /
    ``is_group_portrait`` as NULL ("unknown"), but category assignment treats
    unknown as "no face", exactly as the scorer does at scan time. Every caller
    that re-derives a category from a stored row must go through this so the
    ``*_max`` face filters do not mismatch on NULL. ``CategoryFilter`` itself
    keeps its NULL-fails-the-filter semantics.
    """
    out = dict(photo_data)
    for field in FACE_DEFAULT_FIELDS:
        if out.get(field) is None:
            out[field] = 0
    return out


def _to_float(val):
    """Preserve numeric/fraction parsing while refusing nonfinite comparisons."""
    if val is None:
        return None
    try:
        if isinstance(val, str) and '/' in val:
            num, denom = val.split('/')
            number = float(num) / float(denom)
        else:
            number = float(val)
    except (ValueError, TypeError, ZeroDivisionError, OverflowError):
        return None
    return number if math.isfinite(number) else None


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

# Numeric filter field -> the photo key it reads (``<field>_min`` / ``_max``).
NUMERIC_FILTER_FIELDS = {
    "face_ratio": "face_ratio",
    "face_count": "face_count",
    "iso": "iso",
    "shutter_speed": "shutter_speed",
    "luminance": "mean_luminance",
    "focal_length": "focal_length",
    "f_stop": "f_stop",
}

# Boolean filter -> the photo key it reads.
BOOLEAN_FILTER_FIELDS = {
    "has_face": "face_count",
    "is_monochrome": "is_monochrome",
    "is_silhouette": "is_silhouette",
    "is_group_portrait": "is_group_portrait",
}


def _boolean_value(field, value):
    """has_face is ``face_count > 0``; every other boolean filter is truthiness.

    The ``or 0`` keeps a NULL, or a falsy TEXT value such as ``''``, from
    raising on the comparison.
    """
    if field == "has_face":
        return (value or 0) > 0
    return bool(value or 0)


def photo_tag_set(tags_str) -> set:
    """The comma-separated tags column as the stripped, lowercased set filters compare."""
    return {t.strip().lower() for t in (tags_str or "").split(",") if t.strip()}

VALID_TAG_FILTERS = [
    "required_tags", "excluded_tags", "tag_match_mode"
]

# All valid weight column names (without _percent suffix)
#
# processing.scorer.SCORING_METRIC_KEYS is the canonical list of metrics the
# aggregate scorer actually weights (plus 'quality', 'symmetry', 'balance',
# 'edge_entropy', 'fractal', 'color_harmony' and the extended-IQA keys, which
# are valid config weights outside that optimizer feature set) — keep this list
# in sync with it by hand. It cannot be imported here: processing.scorer imports
# `config` at module scope, so `config` importing `processing.scorer` would be
# circular.
VALID_WEIGHT_COLUMNS = [
    "aesthetic", "face_quality", "eye_sharpness", "tech_sharpness",
    "face_sharpness", "power_point", "saturation", "noise",
    "exposure", "composition", "color", "quality", "contrast",
    "dynamic_range", "isolation", "leading_lines",
    # Supplementary PyIQA metrics
    "aesthetic_iaa", "face_quality_iqa", "liqe",
    # Extended IQA tier — build_metric_vector exposes these to the aggregate
    # only when their iqa_extended flag is on, but they must stay valid weight
    # columns unconditionally: validate_weights deletes any unknown '*_percent'
    # key and persists the deletion, so a user's weight would vanish on the next
    # load (and the weight optimizer's preservation branch would have nothing
    # left to preserve).
    "qrealign", "aesthetic_v25", "deqa",
    # Subject saliency metrics (BiRefNet)
    "subject_sharpness", "subject_prominence", "subject_placement", "bg_separation",
    # Form facet + Matsuda color harmony (CPU explainability pack)
    "symmetry", "balance", "edge_entropy", "fractal", "color_harmony",
]


class CategoryFilter:
    """Evaluates whether a photo matches a category's filter rules.

    Used by v4.0 config schema for config-driven category determination.
    """

    def __init__(self, filter_config: dict):
        """Initialize with filter configuration dict.

        Args:
            filter_config: Dict with filter rules like:
                {
                    "face_ratio_min": 0.05,
                    "has_face": true,
                    "required_tags": ["portrait"],
                    "tag_match_mode": "any"
                }
        """
        self.filters = filter_config or {}

    def matches(self, photo_data: dict) -> bool:
        """Check if photo data matches all filter criteria.

        Delegates to explain_mismatch — returns True when no mismatch is found.
        """
        return self.explain_mismatch(photo_data) is None

    def explain_mismatch(self, photo_data: dict) -> dict | None:
        """Return the first failing filter with context, or None if photo matches.

        Returns:
            None if photo matches all filters, or dict with:
                - key: filter key (e.g. 'face_ratio_min', 'has_face', 'required_tags')
                - required: the filter's required value
                - actual: the photo's actual value
        """
        if not self.filters:
            return None
        return (self._check_numeric(photo_data)
                or self._check_booleans(photo_data)
                or self._check_tags(photo_data))

    def _check_numeric(self, photo_data: dict) -> dict | None:
        """Check all numeric range filters, return first mismatch or None."""
        for field, key in NUMERIC_FILTER_FIELDS.items():
            actual = photo_data.get(key)
            min_val = self.filters.get(f"{field}_min")
            max_val = self.filters.get(f"{field}_max")
            # Coerce to float — SQLite can return strings for numeric columns,
            # and shutter speeds are fractional strings like '1/250'.
            num_actual = _to_float(actual)
            if min_val is not None:
                if num_actual is None:
                    return {"key": f"{field}_min", "required": min_val, "actual": None}
                if num_actual < min_val:
                    return {"key": f"{field}_min", "required": min_val, "actual": round(num_actual, 3)}
            if max_val is not None:
                if num_actual is None:
                    return {"key": f"{field}_max", "required": max_val, "actual": None}
                if num_actual > max_val:
                    return {"key": f"{field}_max", "required": max_val, "actual": round(num_actual, 3)}

        return None

    def _check_booleans(self, photo_data: dict) -> dict | None:
        """Check all boolean filters, return first mismatch or None."""
        for field, key in BOOLEAN_FILTER_FIELDS.items():
            required = self.filters.get(field)
            if required is not None:
                actual = _boolean_value(field, photo_data.get(key))
                if actual != required:
                    return {"key": field, "required": required, "actual": actual}

        return None

    def _check_tags(self, photo_data: dict) -> dict | None:
        """Check required and excluded tag filters, return first mismatch or None."""
        required_tags = self.filters.get("required_tags", [])
        excluded_tags = self.filters.get("excluded_tags", [])
        match_mode = self.filters.get("tag_match_mode", "any")

        if not required_tags and not excluded_tags:
            return None

        photo_tags = photo_tag_set(photo_data.get("tags"))

        if required_tags:
            required_lower = [t.lower() for t in required_tags]
            if match_mode == "any":
                if not any(tag in photo_tags for tag in required_lower):
                    return {"key": "required_tags", "required": required_tags, "actual": []}
            else:
                missing = [t for t in required_lower if t not in photo_tags]
                if missing:
                    return {"key": "required_tags", "required": required_tags, "actual": [t for t in required_lower if t in photo_tags]}

        if excluded_tags:
            excluded_lower = [t.lower() for t in excluded_tags]
            matched_excluded = [t for t in excluded_lower if t in photo_tags]
            if matched_excluded:
                return {"key": "excluded_tags", "required": excluded_tags, "actual": matched_excluded}

        return None

    def uses_tags(self) -> bool:
        """Whether this filter reads the photo's tags at all."""
        return bool(self.filters.get("required_tags") or self.filters.get("excluded_tags"))

    def compile(self, column_index: dict):
        """Precompile this filter against row positions for bulk evaluation.

        ``column_index`` maps photo keys to positions in a row sequence. Returns
        ``match(values, photo_tags) -> bool`` with exactly the outcome of
        :meth:`matches` over the same values: the caller applies
        ``with_face_defaults`` and any shutter parsing to ``values`` first, and
        passes :func:`photo_tag_set` of the tags column (or None when
        :meth:`uses_tags` is false). A filter field whose key is missing from
        ``column_index`` raises KeyError rather than silently over-matching.
        """
        filters = self.filters
        numeric = []
        for field, key in NUMERIC_FILTER_FIELDS.items():
            min_val = filters.get(f"{field}_min")
            max_val = filters.get(f"{field}_max")
            if min_val is not None or max_val is not None:
                numeric.append((column_index[key], min_val, max_val))
        booleans = []
        for field, key in BOOLEAN_FILTER_FIELDS.items():
            required = filters.get(field)
            if required is not None:
                booleans.append((column_index[key], field, required))
        required_tags = [t.lower() for t in filters.get("required_tags") or []]
        excluded_tags = [t.lower() for t in filters.get("excluded_tags") or []]
        match_all = filters.get("tag_match_mode", "any") != "any"

        def match(values, photo_tags) -> bool:
            for idx, min_val, max_val in numeric:
                num_actual = _to_float(values[idx])
                if min_val is not None and (num_actual is None or num_actual < min_val):
                    return False
                if max_val is not None and (num_actual is None or num_actual > max_val):
                    return False
            for idx, field, required in booleans:
                if _boolean_value(field, values[idx]) != required:
                    return False
            if required_tags:
                hits = (tag in photo_tags for tag in required_tags)
                if not (all(hits) if match_all else any(hits)):
                    return False
            if excluded_tags and any(tag in photo_tags for tag in excluded_tags):
                return False
            return True

        return match
