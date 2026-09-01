"""The user config is an OVERRIDE resolved over the shipped defaults.

Two files used to be maintained by hand and copied at install time, and they
drifted: ``scoring_config.default.json`` -- what every container and every
native install starts from -- was missing fourteen key paths the live config
had, so a fresh install silently ran on values hardcoded in the consumers
rather than on the ones documented as shipped. Resolving one file over the
other removes the whole class: there is nothing left to keep in step.
"""

import json

import pytest

from config import ScoringConfig
from config_resolve import (
    deep_merge, defaults_path, delta_for_write, load_defaults, load_resolved,
    subtract_defaults,
)


class TestDeepMerge:
    """Dicts merge by key; everything else, lists included, replaces."""

    def test_absent_keys_come_from_the_base(self):
        assert deep_merge({"a": 1, "b": 2}, {"b": 3}) == {"a": 1, "b": 3}

    def test_nested_dicts_merge_rather_than_replace(self):
        merged = deep_merge({"x": {"a": 1, "b": 2}}, {"x": {"b": 3}})
        assert merged == {"x": {"a": 1, "b": 3}}

    def test_lists_replace_wholesale(self):
        """The decision the whole design turns on.

        ``scoring_contexts.*.promote`` is read in the order given and
        ``categories`` is first-match-wins over a priority sort that breaks ties
        on array position, so an element-wise merge would silently reorder
        evaluation. It would also resurrect a category the operator deleted,
        which is the one edit a merge can never be allowed to undo.
        """
        assert deep_merge({"l": [1, 2, 3]}, {"l": [9]}) == {"l": [9]}

    def test_a_scalar_overrides_a_dict_and_vice_versa(self):
        assert deep_merge({"k": {"a": 1}}, {"k": 5}) == {"k": 5}
        assert deep_merge({"k": 5}, {"k": {"a": 1}}) == {"k": {"a": 1}}

    def test_it_does_not_mutate_either_argument(self):
        base = {"x": {"a": 1}}
        override = {"x": {"b": 2}}
        deep_merge(base, override)
        assert base == {"x": {"a": 1}}
        assert override == {"x": {"b": 2}}


class TestSubtractDefaults:
    """The inverse, as far as a merge can be inverted."""

    @pytest.mark.parametrize("override", [
        {},
        {"new_key": 1},
        {"a": 2},
        {"nested": {"deep": {"leaf": "changed"}}},
        {"list_key": [3, 2, 1]},
        {"a": 2, "new_key": {"x": 1}, "list_key": []},
    ])
    def test_the_round_trip_reproduces_the_override(self, override):
        defaults = {
            "a": 1,
            "nested": {"deep": {"leaf": "shipped", "other": 1}},
            "list_key": [1, 2, 3],
        }
        merged = deep_merge(defaults, override)
        assert subtract_defaults(merged, defaults) == override

    def test_a_value_equal_to_its_default_is_dropped(self):
        assert subtract_defaults({"a": 1, "b": 9}, {"a": 1, "b": 2}) == {"b": 9}

    def test_a_subtree_equal_to_its_default_is_dropped_entirely(self):
        defaults = {"x": {"a": 1, "b": 2}}
        assert subtract_defaults({"x": {"a": 1, "b": 2}}, defaults) == {}

    def test_it_cannot_express_removing_a_default_key(self):
        """Stated rather than worked around, because no merge can express it.

        ``delta_for_write`` therefore promises that the file RESOLVES the same,
        not that it holds the same keys -- a config written before a default
        existed comes back carrying that default. That is what adopting
        defaults means, and the guarantee below is the one that matters.
        """
        defaults = {"a": 1, "b": 2}
        assert deep_merge(defaults, subtract_defaults({"a": 1}, defaults)) == defaults


class TestDeltaForWrite:

    def test_writing_the_delta_resolves_to_the_same_config(self):
        """The guarantee every writer depends on."""
        defaults = load_defaults()
        merged = load_resolved()
        delta = delta_for_write(merged, defaults)
        assert deep_merge(defaults, delta) == deep_merge(defaults, merged)

    def test_the_shipped_config_needs_no_override_at_all(self):
        """The shipped state is the defaults, so the delta is empty.

        This is the drift guard. The two files were independently hand-edited
        and diverged by fourteen key paths; a non-empty delta here means they
        have started to diverge again.
        """
        assert delta_for_write(load_resolved()) == {}

    def test_it_keeps_a_key_the_defaults_do_not_have(self):
        merged = deep_merge(load_defaults(), {"users": {"someone": {"role": "admin"}}})
        assert delta_for_write(merged)["users"] == {"someone": {"role": "admin"}}


class TestLoadResolved:

    def test_an_absent_unnamed_config_yields_the_defaults(self, tmp_path):
        assert load_resolved(str(tmp_path / "nope.json"), named=False) == load_defaults()

    def test_an_absent_named_config_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_resolved(str(tmp_path / "nope.json"), named=True)

    def test_a_three_key_override_still_yields_a_whole_config(self, tmp_path):
        path = tmp_path / "scoring_config.json"
        path.write_text(json.dumps({"performance": {"mmap_size_mb": 7}}))

        resolved = load_resolved(str(path), named=True)

        assert resolved["performance"]["mmap_size_mb"] == 7
        assert len(resolved["categories"]) == len(load_defaults()["categories"])
        assert resolved["performance"]["cache_size_mb"] == \
            load_defaults()["performance"]["cache_size_mb"]


class TestShippedDefaults:

    def test_they_live_inside_the_config_package(self):
        """They are read at runtime now, so they must ship with the package.

        The repository root is not a package and setuptools' package-data rule
        covers ``config/*.json``; left at the root they would not be installed.
        """
        assert defaults_path().endswith("config/scoring_config.default.json")

    def test_they_are_a_valid_v4_config_on_their_own(self):
        """An install with no config file at all must still score."""
        defaults = load_defaults()
        assert defaults["categories"]
        assert all(c.get("name") for c in defaults["categories"])

    def test_they_carry_no_credentials(self):
        """They seed every container, so a value here ships to every install."""
        defaults = load_defaults()
        viewer = defaults.get("viewer", {})
        assert not viewer.get("password")
        assert not viewer.get("edition_password")
        assert not defaults.get("users")
        assert not defaults.get("immich", {}).get("api_key")
        assert not defaults.get("upload", {}).get("password")
        assert not defaults.get("frame", {}).get("tokens")


class TestScoringConfigResolvesTheSameWay:

    def test_an_empty_override_scores_like_the_shipped_config(self, tmp_path):
        """The migration promise: an operator can empty their file and lose nothing."""
        path = tmp_path / "scoring_config.json"
        path.write_text("{}")

        cfg = ScoringConfig(config_path=str(path), validate=False)

        assert cfg.config == load_defaults()
        for category in load_defaults()["categories"]:
            assert cfg.get_weights(category["name"])

    def test_a_named_missing_config_still_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            ScoringConfig(config_path=str(tmp_path / "nope.json"), validate=False)
