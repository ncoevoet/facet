"""Tests for the core config module (ScoringConfig, CategoryFilter, determine_category)."""

import json
import os

import pytest

from config.category_filter import CategoryFilter
from config.scoring_config import ScoringConfig

# Resolve the real scoring_config.json path (repo root)
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "scoring_config.json")


@pytest.fixture(scope="module")
def scoring_config():
    """Load the real scoring_config.json once for the whole module."""
    return ScoringConfig(config_path=CONFIG_PATH)


# ---------------------------------------------------------------------------
# ScoringConfig loading
# ---------------------------------------------------------------------------


class TestScoringConfigLoads:
    """ScoringConfig loads the real config without errors."""

    def test_scoring_config_loads(self, scoring_config):
        """ScoringConfig() loads without error and has categories."""
        categories = scoring_config.get_categories()
        assert len(categories) > 0, "Expected at least one category"

    def test_config_has_version_hash(self, scoring_config):
        """Loaded config should have a non-empty version hash."""
        assert scoring_config.version_hash
        assert len(scoring_config.version_hash) == 12  # MD5 truncated to 12 chars


# ---------------------------------------------------------------------------
# get_model_for_task
# ---------------------------------------------------------------------------


class TestGetModelForTask:
    """get_model_for_task resolves 'auto' instead of falling back to legacy."""

    def test_auto_profile_resolves_before_task_lookup(self):
        """With vram_profile='auto', the task model must come from the detected
        profile, not silently from legacy (whose tagger is 'clip')."""
        from unittest import mock

        config = ScoringConfig(config_path=CONFIG_PATH)
        config.config.setdefault("models", {})["vram_profile"] = "auto"
        with mock.patch.object(
            ScoringConfig, "suggest_vram_profile",
            return_value=("16gb", 15.8, "detected"),
        ):
            tag_model = config.get_model_for_task("tagging")
        expected = config.get_model_config()["profiles"]["16gb"]["tagging_model"]
        assert tag_model == expected
        # Resolution is persisted in memory — no repeat detection needed.
        assert config.get_model_config().get("vram_profile") == "16gb"


# ---------------------------------------------------------------------------
# get_weights
# ---------------------------------------------------------------------------


class TestGetWeights:
    """get_weights returns correct weight dicts."""

    def test_get_weights_returns_dict(self, scoring_config):
        """get_weights('portrait') returns a dict with decimal weights summing to ~1.0."""
        weights = scoring_config.get_weights("portrait")
        assert isinstance(weights, dict)
        assert len(weights) > 0

        # Collect only the weight keys (exclude modifiers like 'bonus')
        weight_keys = [
            k for k in weights
            if k not in ("bonus", "noise_tolerance_multiplier",
                         "_apply_blink_penalty", "_clipping_multiplier")
        ]
        total = sum(weights[k] for k in weight_keys)
        assert abs(total - 1.0) < 0.02, f"Weights should sum to ~1.0, got {total}"

    def test_get_weights_contains_expected_keys(self, scoring_config):
        """Portrait weights should include face-related keys."""
        weights = scoring_config.get_weights("portrait")
        assert "face_quality" in weights
        assert "aesthetic" in weights

    def test_get_weights_fallback(self, scoring_config):
        """get_weights for a nonexistent category returns an empty dict."""
        weights = scoring_config.get_weights("nonexistent_category_xyz")
        assert weights == {}

    def test_get_weights_merges_modifiers(self, scoring_config):
        """Modifiers like 'bonus' should be merged into the returned dict."""
        weights = scoring_config.get_weights("portrait")
        assert "bonus" in weights
        assert isinstance(weights["bonus"], (int, float))


# ---------------------------------------------------------------------------
# determine_category
# ---------------------------------------------------------------------------


class TestDetermineCategory:
    """determine_category classifies photo dicts into the correct category."""

    def test_determine_category_portrait(self, scoring_config):
        """Photo with face_ratio=0.3, face_count=1 should be 'portrait'."""
        photo = {
            "tags": "",
            "face_count": 1,
            "face_ratio": 0.3,
            "is_silhouette": 0,
            "is_group_portrait": 0,
            "is_monochrome": 0,
            "mean_luminance": 0.5,
            "iso": None,
            "shutter_speed": None,
            "focal_length": None,
            "f_stop": None,
        }
        assert scoring_config.determine_category(photo) == "portrait"

    def test_determine_category_portrait_bw(self, scoring_config):
        """Monochrome portrait should be 'portrait_bw'."""
        photo = {
            "tags": "",
            "face_count": 1,
            "face_ratio": 0.3,
            "is_silhouette": 0,
            "is_group_portrait": 0,
            "is_monochrome": 1,
            "mean_luminance": 0.5,
            "iso": None,
            "shutter_speed": None,
            "focal_length": None,
            "f_stop": None,
        }
        assert scoring_config.determine_category(photo) == "portrait_bw"

    def test_determine_category_landscape(self, scoring_config):
        """Photo tagged 'landscape' with no face should match 'landscape'."""
        photo = {
            "tags": "landscape",
            "face_count": 0,
            "face_ratio": 0.0,
            "is_silhouette": 0,
            "is_group_portrait": 0,
            "is_monochrome": 0,
            "mean_luminance": 0.5,
            "iso": None,
            "shutter_speed": None,
            "focal_length": None,
            "f_stop": None,
        }
        result = scoring_config.determine_category(photo)
        assert result == "landscape"

    def test_determine_category_monochrome(self, scoring_config):
        """Monochrome photo with no face and no special tags gets 'monochrome'."""
        photo = {
            "tags": "",
            "face_count": 0,
            "face_ratio": 0.0,
            "is_silhouette": 0,
            "is_group_portrait": 0,
            "is_monochrome": 1,
            "mean_luminance": 0.5,
            "iso": None,
            "shutter_speed": None,
            "focal_length": None,
            "f_stop": None,
        }
        result = scoring_config.determine_category(photo)
        assert result == "monochrome"

    def test_determine_category_default_fallback(self, scoring_config):
        """Photo with no distinguishing features falls to 'default'."""
        photo = {
            "tags": "",
            "face_count": 0,
            "face_ratio": 0.0,
            "is_silhouette": 0,
            "is_group_portrait": 0,
            "is_monochrome": 0,
            "mean_luminance": 0.5,
            "iso": None,
            "shutter_speed": None,
            "focal_length": None,
            "f_stop": None,
        }
        result = scoring_config.determine_category(photo)
        assert result == "default"

    def test_determine_category_group_portrait(self, scoring_config):
        """Photo with multiple faces should be 'group_portrait'."""
        photo = {
            "tags": "",
            "face_count": 4,
            "face_ratio": 0.2,
            "is_silhouette": 0,
            "is_group_portrait": 1,
            "is_monochrome": 0,
            "mean_luminance": 0.5,
            "iso": None,
            "shutter_speed": None,
            "focal_length": None,
            "f_stop": None,
        }
        assert scoring_config.determine_category(photo) == "group_portrait"


# ---------------------------------------------------------------------------
# scoring contexts (get_scoring_contexts / resolve_context_order / determine_category context)
# ---------------------------------------------------------------------------


class TestScoringContexts:
    """Scoring contexts reorder/exclude categories on top of the base priority order."""

    def _silhouette_sports_photo(self, **overrides):
        photo = {
            "tags": "athlete, competition, fashion, sports",
            "face_count": 1,
            "face_ratio": 0.15,
            "is_silhouette": 1,
            "is_group_portrait": 0,
            "is_monochrome": 0,
            "mean_luminance": 0.2,
            "iso": None,
            "shutter_speed": None,
            "focal_length": None,
            "f_stop": None,
        }
        photo.update(overrides)
        return photo

    def test_silhouette_wins_under_default(self, scoring_config):
        """A silhouette-flagged, sports-tagged photo is 'silhouette' with no context."""
        assert scoring_config.determine_category(self._silhouette_sports_photo()) == "silhouette"

    def test_action_stage_excludes_silhouette(self, scoring_config):
        """The same photo never resolves to 'silhouette' under action_stage."""
        result = scoring_config.determine_category(self._silhouette_sports_photo(), context="action_stage")
        assert result != "silhouette"

    def test_action_stage_promotes_sports_when_it_actually_matches(self, scoring_config):
        """With a valid shutter speed, action_stage promotes 'sports' ahead of 'silhouette'."""
        photo = self._silhouette_sports_photo(shutter_speed="1/500")
        assert scoring_config.determine_category(photo, context="action_stage") == "sports"

    def test_unknown_context_falls_back_to_default_order(self, scoring_config):
        """An unconfigured context name behaves exactly like no context at all."""
        photo = self._silhouette_sports_photo()
        default_result = scoring_config.determine_category(photo)
        fallback_result = scoring_config.determine_category(photo, context="not_a_real_context")
        assert fallback_result == default_result

    def test_get_categories_with_no_context_is_unchanged(self, scoring_config):
        """get_categories() with no argument keeps the plain priority-sorted list."""
        categories = scoring_config.get_categories()
        priorities = [c.get("priority", 100) for c in categories]
        assert priorities == sorted(priorities)
        assert categories[-1]["name"] == "default"

    def test_get_scoring_contexts_includes_shipped_presets(self, scoring_config):
        """The shipped presets are all present with the required keys."""
        contexts = scoring_config.get_scoring_contexts()
        expected_keys = {"label_key", "promote", "excluded", "suggest_from_moments"}
        for name in ("default", "action_stage", "party_event", "portrait_session",
                     "wildlife", "landscape", "motorsport"):
            assert name in contexts
            assert set(contexts[name].keys()) == expected_keys

    def test_context_names_reference_real_categories_and_moments(self, scoring_config):
        """Every promote/excluded name is a real category; every suggested moment is real."""
        category_names = {c["name"] for c in scoring_config.get_categories()}
        moment_names = set(
            scoring_config.config.get("narrative_moments", {})
            .get("event_types", {}).get("general", {}).keys()
        )
        for context in scoring_config.get_scoring_contexts().values():
            for name in context["promote"] + context["excluded"]:
                assert name in category_names
            for moment in context["suggest_from_moments"]:
                assert moment in moment_names

    def test_resolve_context_order_is_memoized(self, scoring_config):
        """Repeated calls for the same context return the identical cached result."""
        first = scoring_config.resolve_context_order("action_stage")
        second = scoring_config.resolve_context_order("action_stage")
        assert first is second

    def test_resolve_context_order_is_consistent_across_calls(self, scoring_config):
        """The resolved order is stable (same names, same sequence) across calls."""
        first_names = [name for name, _ in scoring_config.resolve_context_order("landscape")]
        second_names = [name for name, _ in scoring_config.resolve_context_order("landscape")]
        assert first_names == second_names


class TestResolveContextOrderEdgeCases:
    """resolve_context_order edge cases, isolated from the real scoring_config.json
    with a small fabricated category set so promote/excluded interactions can be
    pinned down exactly."""

    _CATEGORIES = [
        {"name": "silhouette", "priority": 10, "filters": {}},
        {"name": "sports", "priority": 20, "filters": {}},
        {"name": "wildlife", "priority": 30, "filters": {}},
        {"name": "default", "priority": 999, "filters": {}},
    ]

    def _config_with(self, tmp_path, scoring_contexts):
        config_path = tmp_path / "scoring_config.json"
        config_path.write_text(json.dumps({
            "categories": self._CATEGORIES,
            "scoring_contexts": scoring_contexts,
        }))
        return ScoringConfig(config_path=str(config_path), validate=False)

    def test_name_in_both_promote_and_excluded_is_dropped_entirely(self, tmp_path):
        """excluded wins: a name listed in both never appears in the order at all."""
        cfg = self._config_with(tmp_path, {
            "conflict": {"promote": ["sports"], "excluded": ["sports"]},
        })
        order = [name for name, _ in cfg.resolve_context_order("conflict")]
        assert "sports" not in order
        assert set(order) == {"silhouette", "wildlife", "default"}

    def test_promote_name_that_does_not_exist_is_ignored(self, tmp_path):
        """A promote entry naming a nonexistent category is dropped, not crashed on."""
        cfg = self._config_with(tmp_path, {
            "ctx": {"promote": ["not_a_real_category"], "excluded": []},
        })
        order = [name for name, _ in cfg.resolve_context_order("ctx")]
        assert "not_a_real_category" not in order
        assert set(order) == {"silhouette", "sports", "wildlife", "default"}

    def test_excluded_name_that_does_not_exist_is_harmless(self, tmp_path):
        """An excluded entry naming a nonexistent category changes nothing."""
        cfg = self._config_with(tmp_path, {
            "ctx": {"promote": [], "excluded": ["not_a_real_category"]},
        })
        order = [name for name, _ in cfg.resolve_context_order("ctx")]
        assert set(order) == {"silhouette", "sports", "wildlife", "default"}

    def test_default_named_in_promote_is_still_evaluated_last(self, tmp_path):
        """'default' can never be promoted ahead of the rest, even if listed."""
        cfg = self._config_with(tmp_path, {
            "ctx": {"promote": ["default", "wildlife"], "excluded": []},
        })
        order = [name for name, _ in cfg.resolve_context_order("ctx")]
        assert order[0] == "wildlife"
        assert order[-1] == "default"

    def test_default_named_in_excluded_is_still_evaluated_last(self, tmp_path):
        """'default' can never be excluded — it always stays, always last."""
        cfg = self._config_with(tmp_path, {
            "ctx": {"promote": [], "excluded": ["default"]},
        })
        order = [name for name, _ in cfg.resolve_context_order("ctx")]
        assert order[-1] == "default"
        assert set(order) == {"silhouette", "sports", "wildlife", "default"}

    def test_duplicate_promote_names_produce_one_entry(self, tmp_path):
        """A name repeated in promote is only placed once, at its first occurrence."""
        cfg = self._config_with(tmp_path, {
            "ctx": {"promote": ["wildlife", "sports", "wildlife"], "excluded": []},
        })
        order = [name for name, _ in cfg.resolve_context_order("ctx")]
        assert order.count("wildlife") == 1
        assert order[:2] == ["wildlife", "sports"]


# ---------------------------------------------------------------------------
# get_categories
# ---------------------------------------------------------------------------


class TestGetCategories:
    """get_categories returns a sorted list."""

    def test_get_categories_returns_sorted(self, scoring_config):
        """Categories should be sorted by priority (ascending)."""
        categories = scoring_config.get_categories()
        priorities = [c.get("priority", 100) for c in categories]
        assert priorities == sorted(priorities), "Categories should be sorted by priority"

    def test_get_categories_contains_known_categories(self, scoring_config):
        """Known categories like 'portrait', 'landscape', 'default' should exist."""
        names = [c["name"] for c in scoring_config.get_categories()]
        for expected in ("portrait", "landscape", "default"):
            assert expected in names, f"Expected category '{expected}' in config"

    def test_default_has_highest_priority_value(self, scoring_config):
        """'default' should have the highest priority number (evaluated last)."""
        categories = scoring_config.get_categories()
        default_cat = next(c for c in categories if c["name"] == "default")
        for c in categories:
            if c["name"] != "default":
                assert c["priority"] < default_cat["priority"], (
                    f"'{c['name']}' (priority {c['priority']}) should be lower than "
                    f"'default' (priority {default_cat['priority']})"
                )


# ---------------------------------------------------------------------------
# CategoryFilter
# ---------------------------------------------------------------------------


class TestCategoryFilter:
    """CategoryFilter evaluates filter rules against photo data."""

    def _base_photo(self, **overrides):
        """Helper to build a photo dict with sensible defaults."""
        photo = {
            "tags": "",
            "face_count": 0,
            "face_ratio": 0.0,
            "is_silhouette": 0,
            "is_group_portrait": 0,
            "is_monochrome": 0,
            "mean_luminance": 0.5,
            "iso": None,
            "shutter_speed": None,
            "focal_length": None,
            "f_stop": None,
        }
        photo.update(overrides)
        return photo

    def test_empty_filter_matches_everything(self):
        """A filter with no rules should match any photo."""
        cf = CategoryFilter({})
        assert cf.matches(self._base_photo()) is True

    def test_face_ratio_min(self):
        """face_ratio_min filter should reject photos below the threshold."""
        cf = CategoryFilter({"face_ratio_min": 0.25})
        assert cf.matches(self._base_photo(face_ratio=0.3)) is True
        assert cf.matches(self._base_photo(face_ratio=0.1)) is False

    def test_face_ratio_max(self):
        """face_ratio_max filter should reject photos above the threshold."""
        cf = CategoryFilter({"face_ratio_max": 0.02})
        assert cf.matches(self._base_photo(face_ratio=0.0)) is True
        assert cf.matches(self._base_photo(face_ratio=0.1)) is False

    def test_has_face_true(self):
        """has_face=true should require face_count > 0."""
        cf = CategoryFilter({"has_face": True})
        assert cf.matches(self._base_photo(face_count=1)) is True
        assert cf.matches(self._base_photo(face_count=0)) is False

    def test_has_face_false(self):
        """has_face=false should require face_count == 0."""
        cf = CategoryFilter({"has_face": False})
        assert cf.matches(self._base_photo(face_count=0)) is True
        assert cf.matches(self._base_photo(face_count=1)) is False

    def test_is_monochrome(self):
        """is_monochrome filter should match/reject correctly."""
        cf = CategoryFilter({"is_monochrome": True})
        assert cf.matches(self._base_photo(is_monochrome=1)) is True
        assert cf.matches(self._base_photo(is_monochrome=0)) is False

    def test_tag_match_any(self):
        """required_tags with tag_match_mode='any' should match if any tag present."""
        cf = CategoryFilter({
            "required_tags": ["landscape", "mountain"],
            "tag_match_mode": "any",
        })
        assert cf.matches(self._base_photo(tags="landscape")) is True
        assert cf.matches(self._base_photo(tags="mountain, sunset")) is True
        assert cf.matches(self._base_photo(tags="portrait")) is False

    def test_tag_match_all(self):
        """required_tags with tag_match_mode='all' should require all tags present."""
        cf = CategoryFilter({
            "required_tags": ["landscape", "mountain"],
            "tag_match_mode": "all",
        })
        assert cf.matches(self._base_photo(tags="landscape, mountain")) is True
        assert cf.matches(self._base_photo(tags="landscape")) is False

    def test_excluded_tags(self):
        """excluded_tags should reject photos with any excluded tag."""
        cf = CategoryFilter({"excluded_tags": ["cartoon"]})
        assert cf.matches(self._base_photo(tags="landscape")) is True
        assert cf.matches(self._base_photo(tags="cartoon, landscape")) is False

    def test_numeric_filter_none_value_does_not_match(self):
        """When filter requires a numeric range but actual value is None, no match."""
        cf = CategoryFilter({"shutter_speed_min": 10.0})
        assert cf.matches(self._base_photo(shutter_speed=None)) is False
        assert cf.matches(self._base_photo(shutter_speed=15.0)) is True

    def test_combined_filters(self):
        """Multiple filters must all pass (AND logic)."""
        cf = CategoryFilter({
            "face_ratio_min": 0.05,
            "has_face": True,
            "is_monochrome": False,
        })
        # Matches: has face, above ratio, not monochrome
        assert cf.matches(self._base_photo(
            face_count=1, face_ratio=0.1, is_monochrome=0,
        )) is True
        # Fails: monochrome
        assert cf.matches(self._base_photo(
            face_count=1, face_ratio=0.1, is_monochrome=1,
        )) is False
        # Fails: no face
        assert cf.matches(self._base_photo(
            face_count=0, face_ratio=0.0, is_monochrome=0,
        )) is False


# ---------------------------------------------------------------------------
# get_tag_vocabulary / get_category_tags
# ---------------------------------------------------------------------------


class TestTagVocabulary:
    """Tag vocabulary and category tag accessors."""

    def test_get_tag_vocabulary(self, scoring_config):
        """get_tag_vocabulary returns a non-empty dict mapping tag names to synonym lists."""
        vocab = scoring_config.get_tag_vocabulary()
        assert isinstance(vocab, dict)
        assert len(vocab) > 0
        # Each value should be a list of synonyms
        for tag, synonyms in vocab.items():
            assert isinstance(tag, str)
            assert isinstance(synonyms, list)
            assert len(synonyms) > 0, f"Tag '{tag}' should have at least one synonym"

    def test_vocabulary_includes_standalone_tags(self, scoring_config):
        """Standalone tags (not tied to a category) should be in the vocabulary."""
        vocab = scoring_config.get_tag_vocabulary()
        # 'bokeh' is defined as a standalone_tag in the config
        assert "bokeh" in vocab

    def test_get_category_tags_landscape(self, scoring_config):
        """get_category_tags('landscape') should return landscape tag names."""
        tags = scoring_config.get_category_tags("landscape")
        assert isinstance(tags, list)
        assert "landscape" in tags
        assert "mountain" in tags

    def test_get_category_tags_art(self, scoring_config):
        """get_category_tags('art') should return art-related tag names."""
        tags = scoring_config.get_category_tags("art")
        assert "painting" in tags
        assert "statue" in tags

    def test_get_category_tags_nonexistent(self, scoring_config):
        """get_category_tags for unknown category returns empty list."""
        tags = scoring_config.get_category_tags("nonexistent_xyz")
        assert tags == []
