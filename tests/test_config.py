"""Tests for the core config module (ScoringConfig, CategoryFilter, determine_category)."""

import json
import logging
import os

import pytest

from config.category_filter import CategoryFilter, VALID_WEIGHT_COLUMNS
from config.scoring_config import ScoringConfig
from config_resolve import load_defaults

# Resolve the real scoring_config.json path (repo root)
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config/scoring_config.default.json")


@pytest.fixture(scope="module")
def scoring_config():
    """Load the real shipped config once for the whole module.

    The shipped config IS the defaults file: the repo-root scoring_config.json
    is a per-install override, untracked, and absent from a clean clone.
    """
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


class TestDetermineCategoryToleratesNamelessCategory:
    """DEFECT L4 regression: resolve_context_order used to dereference
    c['name'] eagerly for every category while building the evaluation
    order, so a single hand-edited category missing its 'name' field
    KeyErrored on every determine_category call -- master only crashed
    if that particular nameless category actually matched."""

    _CATEGORIES = [
        {"priority": 5, "filters": {"required_tags": ["nonexistent_tag_xyz"]}},
        {"name": "default", "priority": 999, "filters": {}},
    ]

    def _config(self, tmp_path):
        config_path = tmp_path / "scoring_config.json"
        config_path.write_text(json.dumps({"categories": self._CATEGORIES}))
        return ScoringConfig(config_path=str(config_path), validate=False)

    def test_unrelated_photo_does_not_crash_on_the_nameless_category(self, tmp_path):
        cfg = self._config(tmp_path)
        photo = {"tags": "unrelated", "face_count": 0, "face_ratio": 0.0}
        assert cfg.determine_category(photo) == "default"


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

    def test_validate_categories_passes_for_shipped_scoring_contexts(self, scoring_config):
        """The shipped scoring_contexts block raises no validation issues."""
        ok, issues = scoring_config.validate_categories(verbose=False)
        assert ok is True
        assert not any(issue.startswith("scoring_contexts.") for issue in issues)


def _only_these_contexts(scoring_contexts):
    """``scoring_contexts`` with every SHIPPED context neutralised around it.

    ``ScoringConfig`` resolves a config over the shipped defaults, and
    ``scoring_contexts`` is a dict, so the shipped presets merge into any
    fixture that does not mention them -- and are then validated against the
    fixture's handful of categories, which they legitimately fail, since they
    promote fourteen the fixture does not define. Each shipped name is
    overridden with an empty context so only what a test declares is under
    test. Derived from the defaults rather than hard-coded, so a new shipped
    preset cannot silently reintroduce the leak.
    """
    neutralised = {
        name: {"label_key": name, "promote": [], "excluded": [],
               "suggest_from_moments": []}
        for name in load_defaults().get("scoring_contexts", {})
    }
    return {**neutralised, **scoring_contexts}


class TestValidateCategoriesScoringContexts:
    """validate_categories() reports config mistakes in scoring_contexts rather
    than silently dropping them (typo'd names, promote/excluded overlaps, and
    suggest_from_moments entries that don't exist)."""

    _CATEGORIES = [
        {"name": "silhouette", "priority": 10, "filters": {}},
        {"name": "sports", "priority": 20, "filters": {}},
        {"name": "wildlife", "priority": 30, "filters": {}},
        {"name": "default", "priority": 999, "filters": {}},
    ]

    def _config_with(self, tmp_path, scoring_contexts, narrative_moments=None):
        """A config carrying ONLY the contexts a test declares.

        ``ScoringConfig`` resolves the file over the shipped defaults, and
        ``scoring_contexts`` is a dict, so the shipped presets would otherwise
        merge in and be validated against this fixture's five categories --
        which they legitimately fail, since they promote fourteen the fixture
        does not define. Each shipped name is overridden with an empty context
        so only what the test declares is under test. Derived from the defaults
        rather than hard-coded, so a new shipped preset cannot silently
        reintroduce the leak.
        """
        config_path = tmp_path / "scoring_config.json"
        config = {
            "categories": self._CATEGORIES,
            "scoring_contexts": _only_these_contexts(scoring_contexts),
            "narrative_moments": narrative_moments or {
                "default_event_type": "general",
                "event_types": {"general": {"sports": [], "nature_wildlife": []}},
            },
        }
        config_path.write_text(json.dumps(config))
        return ScoringConfig(config_path=str(config_path), validate=False)

    def test_unknown_promote_name_is_reported(self, tmp_path):
        cfg = self._config_with(tmp_path, {
            "ctx": {"label_key": "x", "promote": ["wildlfe", "sports"], "excluded": [],
                    "suggest_from_moments": []},
        })
        ok, issues = cfg.validate_categories(verbose=False)
        assert ok is False
        assert any("promote references unknown category 'wildlfe'" in i for i in issues)

    def test_unknown_excluded_name_is_reported(self, tmp_path):
        cfg = self._config_with(tmp_path, {
            "ctx": {"label_key": "x", "promote": [], "excluded": ["silhouete"],
                    "suggest_from_moments": []},
        })
        ok, issues = cfg.validate_categories(verbose=False)
        assert ok is False
        assert any("excluded references unknown category 'silhouete'" in i for i in issues)

    def test_name_in_both_promote_and_excluded_is_reported(self, tmp_path):
        cfg = self._config_with(tmp_path, {
            "ctx": {"label_key": "x", "promote": ["sports"], "excluded": ["sports"],
                    "suggest_from_moments": []},
        })
        ok, issues = cfg.validate_categories(verbose=False)
        assert ok is False
        assert any(
            "'sports' is listed in both promote and excluded" in i and "excluded wins" in i
            for i in issues
        )

    def test_unknown_suggest_from_moments_entry_is_reported(self, tmp_path):
        cfg = self._config_with(tmp_path, {
            "ctx": {"label_key": "x", "promote": [], "excluded": [],
                    "suggest_from_moments": ["not_a_real_moment"]},
        })
        ok, issues = cfg.validate_categories(verbose=False)
        assert ok is False
        assert any(
            "suggest_from_moments references unknown moment 'not_a_real_moment'" in i
            for i in issues
        )

    def test_valid_context_reports_nothing(self, tmp_path):
        cfg = self._config_with(tmp_path, {
            "ctx": {"label_key": "x", "promote": ["sports"], "excluded": ["silhouette"],
                    "suggest_from_moments": ["sports"]},
        })
        ok, issues = cfg.validate_categories(verbose=False)
        assert ok is True
        assert issues == []

    def test_typo_does_not_silently_change_resolved_order(self, tmp_path):
        """The adversarial repro: typo'd promote/excluded names are dropped by
        resolve_context_order with no error — validate_categories is what
        surfaces the mistake."""
        cfg = self._config_with(tmp_path, {
            "ctx": {"label_key": "x", "promote": ["wildlfe", "Wildlife", "sports"],
                    "excluded": ["silhouete"], "suggest_from_moments": []},
        })
        order = [name for name, _ in cfg.resolve_context_order("ctx")]
        assert order[0] == "sports"
        assert "silhouette" in order

        ok, issues = cfg.validate_categories(verbose=False)
        assert ok is False
        assert len(issues) >= 3


class TestValidateCategoriesMalformedScoringContexts:
    """DEFECT M2 regression: validate_categories() must report a clear issue
    for a malformed scoring_contexts shape instead of crashing -- it exists
    specifically to diagnose a hand-edited config, so raising on exactly the
    configs it should be diagnosing is the worst possible behaviour."""

    _CATEGORIES = TestValidateCategoriesScoringContexts._CATEGORIES

    def _config_with(self, tmp_path, scoring_contexts):
        config_path = tmp_path / "scoring_config.json"
        config_path.write_text(json.dumps({
            "categories": self._CATEGORIES,
            "scoring_contexts": _only_these_contexts(scoring_contexts),
        }))
        return ScoringConfig(config_path=str(config_path), validate=False)

    def test_promote_not_a_list_is_reported_not_raised(self, tmp_path):
        cfg = self._config_with(tmp_path, {"ctx": {"promote": 5}})
        ok, issues = cfg.validate_categories(verbose=False)
        assert ok is False
        assert any("'promote' should be a list, got int" in i for i in issues)

    def test_suggest_from_moments_not_a_list_is_reported_not_raised(self, tmp_path):
        cfg = self._config_with(tmp_path, {"ctx": {"suggest_from_moments": 3}})
        ok, issues = cfg.validate_categories(verbose=False)
        assert ok is False
        assert any("'suggest_from_moments' should be a list, got int" in i for i in issues)

    def test_promote_entry_that_is_a_list_is_reported_not_raised(self, tmp_path):
        cfg = self._config_with(tmp_path, {"ctx": {"promote": [["sports"]]}})
        ok, issues = cfg.validate_categories(verbose=False)
        assert ok is False
        assert any("promote entry ['sports'] is not a string" in i for i in issues)

    def test_mixed_type_promote_and_excluded_entries_are_reported_not_raised(self, tmp_path):
        cfg = self._config_with(tmp_path, {"ctx": {"promote": [1, "sports"], "excluded": [1, "sports"]}})
        ok, issues = cfg.validate_categories(verbose=False)
        assert ok is False
        assert any("promote entry 1 is not a string" in i for i in issues)
        assert any("excluded entry 1 is not a string" in i for i in issues)

    def test_promote_as_a_bare_string_is_not_iterated_as_characters(self, tmp_path):
        cfg = self._config_with(tmp_path, {"ctx": {"promote": "sports"}})
        ok, issues = cfg.validate_categories(verbose=False)
        assert ok is False
        assert any("'promote' should be a list, got str" in i for i in issues)
        assert not any("unknown category 's'" in i for i in issues)
        assert not any("unknown category 'p'" in i for i in issues)


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
            "scoring_contexts": _only_these_contexts(scoring_contexts),
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


class TestResolveContextOrderMalformedShapes:
    """DEFECT M2 regression, runtime twin: the same malformed scoring_contexts
    shapes that validate_categories must report also reached resolve_context_order,
    which 500s the API and aborts a scan. A malformed context must degrade to
    the default order with a warning, never take the process down."""

    _CATEGORIES = TestResolveContextOrderEdgeCases._CATEGORIES

    def _config_with(self, tmp_path, scoring_contexts):
        config_path = tmp_path / "scoring_config.json"
        config_path.write_text(json.dumps({
            "categories": self._CATEGORIES,
            "scoring_contexts": _only_these_contexts(scoring_contexts),
        }))
        return ScoringConfig(config_path=str(config_path), validate=False)

    def test_promote_not_a_list_falls_back_to_default_order(self, tmp_path):
        cfg = self._config_with(tmp_path, {"ctx": {"promote": 5}})
        order = [name for name, _ in cfg.resolve_context_order("ctx")]
        assert set(order) == {"silhouette", "sports", "wildlife", "default"}

    def test_promote_entry_that_is_a_list_is_dropped_not_raised(self, tmp_path):
        cfg = self._config_with(tmp_path, {"ctx": {"promote": [["sports"]]}})
        order = [name for name, _ in cfg.resolve_context_order("ctx")]
        assert set(order) == {"silhouette", "sports", "wildlife", "default"}

    def test_mixed_type_promote_and_excluded_do_not_raise(self, tmp_path):
        cfg = self._config_with(tmp_path, {"ctx": {"promote": [1, "sports"], "excluded": [1, "wildlife"]}})
        order = [name for name, _ in cfg.resolve_context_order("ctx")]
        assert order[0] == "sports"
        assert "wildlife" not in order

    def test_promote_as_a_bare_string_is_not_iterated_as_characters(self, tmp_path):
        cfg = self._config_with(tmp_path, {"ctx": {"promote": "sports"}})
        order = [name for name, _ in cfg.resolve_context_order("ctx")]
        assert set(order) == {"silhouette", "sports", "wildlife", "default"}

    def test_context_definition_that_is_not_an_object_falls_back_to_default_order(self, tmp_path):
        """A whole context value of the wrong type (e.g. hand-edited to an
        int) previously raised AttributeError on context_def.get(...)."""
        cfg = self._config_with(tmp_path, {"ctx": 5})
        order = [name for name, _ in cfg.resolve_context_order("ctx")]
        assert set(order) == {"silhouette", "sports", "wildlife", "default"}


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


# ---------------------------------------------------------------------------
# VALID_WEIGHT_COLUMNS / validate_weights (A3#1: documented metrics were
# missing from the valid set, so validate_weights() silently deleted them)
# ---------------------------------------------------------------------------


class TestValidWeightColumnsCoversDocumentedMetrics:
    """face_sharpness, power_point, saturation and noise are documented
    weight keys (docs/SCORING.md, processing.scorer.SCORING_METRIC_KEYS,
    written by optimization/weight_optimizer.py) but were missing from
    VALID_WEIGHT_COLUMNS, so validate_weights() treated their *_percent
    keys as invalid, deleted them, and persisted the deletion to disk."""

    @pytest.mark.parametrize(
        "metric", ["face_sharpness", "power_point", "saturation", "noise"]
    )
    def test_metric_is_a_valid_weight_column(self, metric):
        assert metric in VALID_WEIGHT_COLUMNS

    def test_percent_keys_survive_validate_round_trip(self, tmp_path):
        """A category using these 4 keys must come out of
        ScoringConfig(path, validate=True) unchanged -- not stripped and
        not renormalized away."""
        config_path = tmp_path / "scoring_config.json"
        config_path.write_text(json.dumps({
            "categories": [{
                "name": "test_cat",
                "priority": 1,
                "filters": {},
                "weights": {
                    "face_sharpness_percent": 25,
                    "power_point_percent": 25,
                    "saturation_percent": 25,
                    "noise_percent": 25,
                },
            }],
        }))

        cfg = ScoringConfig(config_path=str(config_path), validate=True)

        weights = cfg.config["categories"][0]["weights"]
        for key in (
            "face_sharpness_percent", "power_point_percent",
            "saturation_percent", "noise_percent",
        ):
            assert key in weights, f"{key} was stripped by validate_weights()"
            assert weights[key] == 25, f"{key} was renormalized: {weights[key]}"


class TestValidWeightColumnsCoversExtendedIQA:
    """qrealign/aesthetic_v25/deqa are documented weight keys (docs/CONFIGURATION.md
    "Extended IQA tier"), are emitted by processing.scorer.build_metric_vector and
    are explicitly preserved by the weight optimizer -- but were missing from
    VALID_WEIGHT_COLUMNS, so validate_weights() deleted their *_percent keys and
    persisted the deletion to disk on the next load."""

    @pytest.mark.parametrize("metric", ["qrealign", "aesthetic_v25", "deqa"])
    def test_metric_is_a_valid_weight_column(self, metric):
        assert metric in VALID_WEIGHT_COLUMNS

    def test_percent_keys_survive_validate_round_trip(self, tmp_path):
        """A category weighting the extended tier must come out of
        ScoringConfig(path, validate=True) intact -- in memory AND on disk,
        since validate_weights() re-saves the config it corrected."""
        config_path = tmp_path / "scoring_config.json"
        config_path.write_text(json.dumps({
            "categories": [{
                "name": "test_cat",
                "priority": 1,
                "filters": {},
                "weights": {
                    "aesthetic_percent": 25,
                    "qrealign_percent": 25,
                    "aesthetic_v25_percent": 25,
                    "deqa_percent": 25,
                },
            }],
        }))

        cfg = ScoringConfig(config_path=str(config_path), validate=True)

        expected = {
            "aesthetic_percent", "qrealign_percent",
            "aesthetic_v25_percent", "deqa_percent",
        }
        weights = cfg.config["categories"][0]["weights"]
        on_disk = json.loads(config_path.read_text())["categories"][0]["weights"]
        for key in expected:
            assert key in weights, f"{key} was stripped by validate_weights()"
            assert weights[key] == 25, f"{key} was renormalized: {weights[key]}"
            assert key in on_disk, f"{key} deletion was persisted to disk"
            assert on_disk[key] == 25

        # get_weights must expose them to the aggregate as real (decimal) weights.
        resolved = cfg.get_weights("test_cat")
        for base in ("qrealign", "aesthetic_v25", "deqa"):
            assert resolved.get(base) == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# validate_weights decimal heuristic (A3#2: the 0b zero-padding step ran
# before the decimal-vs-percent heuristic, so its len(...) > 1 guard was
# always satisfied post-padding and a single small user-set value got
# misread as a decimal fraction)
# ---------------------------------------------------------------------------


class TestValidateWeightsDecimalHeuristic:
    """A lone user-set _percent value must not be misinterpreted as a
    decimal fraction just because 0b zero-pads the category out to every
    valid weight column first."""

    def _single_key_config(self, tmp_path, value=1):
        config_path = tmp_path / "scoring_config.json"
        config_path.write_text(json.dumps({
            "categories": [{
                "name": "test_cat",
                "priority": 1,
                "filters": {},
                "weights": {"tech_sharpness_percent": value},
            }],
        }))
        return str(config_path)

    def test_lone_small_value_is_not_decimal_converted(self, tmp_path, monkeypatch):
        """Isolates the decimal heuristic (step 1) from step 4's separate,
        legitimate normalize-to-100% pass (which -- correctly -- would also
        scale a category's lone nonzero weight up to 100, masking the step 1
        bug if left enabled). With normalization neutralized, a single
        {"tech_sharpness_percent": 1} must stay 1, not become 100."""
        monkeypatch.setattr(
            ScoringConfig, "normalize_weights_to_100",
            staticmethod(lambda *a, **k: None),
        )
        path = self._single_key_config(tmp_path, value=1)
        cfg = ScoringConfig(config_path=path, validate=False)
        cfg.validate_weights(verbose=False)
        assert cfg.config["categories"][0]["weights"]["tech_sharpness_percent"] == 1

    def test_decimal_to_percent_correction_is_not_logged_for_a_lone_value(self, tmp_path, caplog):
        """End-to-end (normalization included): the value still ends up
        renormalized to 100% -- a category with only one populated weight
        is legitimately entitled to all of it -- but the correction log
        must not attribute that to a bogus 'decimal to percent' misread."""
        path = self._single_key_config(tmp_path, value=1)
        cfg = ScoringConfig(config_path=path, validate=False)
        with caplog.at_level(logging.INFO, logger="facet.config"):
            cfg.validate_weights(verbose=True)
        assert "decimal to percent" not in caplog.text

    def test_genuine_multi_key_decimal_config_still_converts(self, tmp_path):
        """Sanity check: a real decimal-style config (multiple small values
        summing to ~1.0) must still be converted -- the fix narrows the
        guard to single-key configs, it must not disable it entirely."""
        config_path = tmp_path / "scoring_config.json"
        config_path.write_text(json.dumps({
            "categories": [{
                "name": "test_cat",
                "priority": 1,
                "filters": {},
                "weights": {"aesthetic_percent": 0.3, "composition_percent": 0.7},
            }],
        }))
        cfg = ScoringConfig(config_path=str(config_path), validate=False)
        cfg.validate_weights(verbose=False)
        weights = cfg.config["categories"][0]["weights"]
        assert weights["aesthetic_percent"] == 30
        assert weights["composition_percent"] == 70


# ---------------------------------------------------------------------------
# get_tag_vocabulary collision detection (A3#3: two categories claiming the
# same tag name with different synonyms silently overwrote each other)
# ---------------------------------------------------------------------------


class TestTagVocabularyCollisionWarning:
    """get_tag_vocabulary() must warn (not silently overwrite) when two
    categories -- or a category and standalone_tags -- define the same tag
    name with different synonym lists."""

    def _config_with_colliding_tags(self, tmp_path):
        config_path = tmp_path / "scoring_config.json"
        config_path.write_text(json.dumps({
            "categories": [
                {
                    "name": "cat_a", "priority": 1, "filters": {},
                    "tags": {"street": ["street", "urban", "city life"]},
                },
                {
                    "name": "cat_b", "priority": 2, "filters": {},
                    "tags": {"street": ["street scene", "city street"]},
                },
                {"name": "default", "priority": 999, "filters": {}},
            ],
        }))
        return ScoringConfig(config_path=str(config_path), validate=False)

    def test_collision_with_different_synonyms_logs_a_warning(self, tmp_path, caplog):
        cfg = self._config_with_colliding_tags(tmp_path)
        with caplog.at_level(logging.WARNING, logger="facet.config"):
            cfg.get_tag_vocabulary()
        assert any(
            "street" in record.message and "redefines synonyms" in record.message
            for record in caplog.records
        )

    def test_collision_last_definition_still_wins(self, tmp_path):
        """Behaviour is otherwise unchanged: last category processed wins."""
        cfg = self._config_with_colliding_tags(tmp_path)
        vocab = cfg.get_tag_vocabulary()
        assert vocab["street"] == ["street scene", "city street"]

    def test_identical_synonyms_across_categories_do_not_warn(self, tmp_path, caplog):
        """Two categories legitimately sharing the exact same synonym list
        for a tag is not a collision.

        The tag is one the shipped vocabulary cannot define. ``categories`` is
        replaced wholesale when a config overrides it, but ``standalone_tags``
        is a dict and merges, so a real tag name here would collide with the
        shipped synonyms and warn for a reason that has nothing to do with what
        this test asserts. The guard below fails loudly if the name ever stops
        being fictional.
        """
        tag = "fixture_only_tag"
        assert tag not in load_defaults().get("standalone_tags", {})
        config_path = tmp_path / "scoring_config.json"
        config_path.write_text(json.dumps({
            "categories": [
                {"name": "cat_a", "priority": 1, "filters": {},
                 "tags": {tag: ["one synonym", "another synonym"]}},
                {"name": "cat_b", "priority": 2, "filters": {},
                 "tags": {tag: ["one synonym", "another synonym"]}},
            ],
        }))
        cfg = ScoringConfig(config_path=str(config_path), validate=False)
        with caplog.at_level(logging.WARNING, logger="facet.config"):
            cfg.get_tag_vocabulary()
        assert not any("redefines synonyms" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Fallback defaults (A3#4: get_face_detection_settings / get_burst_detection_
# settings fell back to values that had drifted from docs/CONFIGURATION.md
# and the shipped config)
# ---------------------------------------------------------------------------


class TestFallbackDefaultsMatchDocumentedDefaults:
    """When a config omits face_detection/burst_detection entirely, the
    in-code fallback must match docs/CONFIGURATION.md (and the shipped
    scoring_config.json), not a stale value that scores differently."""

    def _minimal_config(self, tmp_path):
        config_path = tmp_path / "scoring_config.json"
        config_path.write_text(json.dumps({
            "categories": [{"name": "default", "priority": 999, "filters": {}}],
        }))
        return ScoringConfig(config_path=str(config_path), validate=False)

    def test_face_detection_fallback_matches_docs(self, tmp_path):
        cfg = self._minimal_config(tmp_path)
        settings = cfg.get_face_detection_settings()
        assert settings["min_confidence_percent"] == 65
        assert settings["min_face_size"] == 20

    def test_burst_detection_fallback_matches_docs(self, tmp_path):
        cfg = self._minimal_config(tmp_path)
        settings = cfg.get_burst_detection_settings()
        assert settings["similarity_threshold_percent"] == 70
        assert settings["time_window_minutes"] == 0.8
        assert settings["rapid_burst_seconds"] == 0.4


class TestSaveConfigDoesNotBakeTheEnvironmentVramProfile:
    """$FACET_VRAM_PROFILE is a per-container knob, not a stored setting.

    ``_load_config`` folds the variable into ``self.config`` in place, and
    ``save_config`` writes the resolved dict minus the shipped defaults -- so
    the env value landed in the operator's override file. Any write reaches it:
    ``validate_weights`` calls ``save_config`` whenever it corrects a category's
    percentages, so simply scanning with the variable set was enough.

    What that costs is the documented purpose of the variable. It exists so one
    mounted config can serve every Docker profile; once 8gb is written INTO
    that config, the 24gb container reading the same mount starts from 8gb.
    """

    _PROFILE_ENV = "FACET_VRAM_PROFILE"

    def _config(self, tmp_path, name, override):
        path = tmp_path / name
        path.write_text(json.dumps(override))
        return path

    def test_the_env_value_is_not_written_to_the_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv(self._PROFILE_ENV, "8gb")
        path = self._config(tmp_path, "a.json", {"viewer": {"password": "secret"}})

        config = ScoringConfig(str(path), validate=False)
        assert config.config["models"]["vram_profile"] == "8gb"
        config.save_config()

        assert json.loads(path.read_text()) == {"viewer": {"password": "secret"}}

    def test_a_profile_the_file_chose_survives_the_write(self, tmp_path, monkeypatch):
        """The other half: restoring must not mean deleting.

        An operator who wrote ``vram_profile`` into their config and then ran a
        container with the variable set must get their own value back in the
        file, not the env one and not an absent key.
        """
        monkeypatch.setenv(self._PROFILE_ENV, "8gb")
        path = self._config(
            tmp_path, "b.json", {"models": {"vram_profile": "24gb"}, "viewer": {"password": "s"}},
        )

        config = ScoringConfig(str(path), validate=False)
        config.save_config()

        assert json.loads(path.read_text())["models"]["vram_profile"] == "24gb"

    def test_the_running_process_keeps_the_env_profile_after_saving(self, tmp_path, monkeypatch):
        monkeypatch.setenv(self._PROFILE_ENV, "8gb")
        path = self._config(tmp_path, "c.json", {"viewer": {"password": "s"}})

        config = ScoringConfig(str(path), validate=False)
        config.save_config()

        assert config.config["models"]["vram_profile"] == "8gb"

    def test_without_the_variable_a_deliberate_profile_still_saves(self, tmp_path, monkeypatch):
        monkeypatch.delenv(self._PROFILE_ENV, raising=False)
        path = self._config(tmp_path, "d.json", {"viewer": {"password": "s"}})

        config = ScoringConfig(str(path), validate=False)
        config.config["models"]["vram_profile"] = "16gb"
        config.save_config()

        assert json.loads(path.read_text())["models"]["vram_profile"] == "16gb"
