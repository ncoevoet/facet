"""
Facet Category Filter.

Evaluates whether a photo matches a category's filter rules.
"""


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
    # Subject saliency metrics (BiRefNet)
    "subject_sharpness", "subject_prominence", "subject_placement", "bg_separation",
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
        numeric_fields = {
            "face_ratio": photo_data.get("face_ratio"),
            "face_count": photo_data.get("face_count"),
            "iso": photo_data.get("iso"),
            "shutter_speed": photo_data.get("shutter_speed"),
            "luminance": photo_data.get("mean_luminance"),
            "focal_length": photo_data.get("focal_length"),
            "f_stop": photo_data.get("f_stop"),
        }

        for field, actual in numeric_fields.items():
            min_val = self.filters.get(f"{field}_min")
            max_val = self.filters.get(f"{field}_max")
            # Coerce to float — SQLite can return strings for numeric columns
            try:
                num_actual = float(actual) if actual is not None else None
            except (ValueError, TypeError):
                num_actual = None
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
        bool_mappings = {
            "has_face": lambda pd: (pd.get("face_count") or 0) > 0,
            "is_monochrome": lambda pd: bool(pd.get("is_monochrome", 0)),
            "is_silhouette": lambda pd: bool(pd.get("is_silhouette", 0)),
            "is_group_portrait": lambda pd: bool(pd.get("is_group_portrait", 0)),
        }

        for field, getter in bool_mappings.items():
            required = self.filters.get(field)
            if required is not None:
                actual = getter(photo_data)
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

        tags_str = photo_data.get("tags") or ""
        photo_tags = [t.strip().lower() for t in tags_str.split(",") if t.strip()]

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
