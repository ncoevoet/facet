"""The user config is an OVERRIDE resolved over the shipped defaults.

Two files used to be maintained by hand and copied at install time, and they
drifted: ``scoring_config.default.json`` -- what every container and every
native install starts from -- was missing fourteen key paths the live config
had, so a fresh install silently ran on values hardcoded in the consumers
rather than on the ones documented as shipped. Resolving one file over the
other removes the whole class: there is nothing left to keep in step.
"""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from config import ScoringConfig
from config_resolve import (
    deep_merge, default_config_path, defaults_path, delta_for_write, load_defaults,
    load_resolved, path_is_named, subtract_defaults,
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

    def test_a_non_dict_override_is_rejected_by_name(self, tmp_path):
        """A hand-edited file is operator-authored input at a real boundary.

        It used to die with ``AttributeError: 'list' object has no attribute
        'items'`` from inside the merge, which names neither the file nor the
        mistake.
        """
        path = tmp_path / "scoring_config.json"
        path.write_text("[1, 2, 3]")

        with pytest.raises(ValueError, match="must hold a JSON object"):
            load_resolved(str(path), named=True)

    def test_a_null_section_replaces_rather_than_merging(self, tmp_path):
        """``null`` clobbers, like every other non-dict value.

        Documented rather than special-cased: the merge applies what the
        operator wrote. What must NOT happen is a crash far from the edit --
        ``db.connection.get_pragma_values`` used to raise AttributeError on
        every database connection in the process.
        """
        path = tmp_path / "scoring_config.json"
        path.write_text(json.dumps({"performance": None}))

        assert load_resolved(str(path), named=True)["performance"] is None

    def test_an_override_may_add_a_key_the_defaults_lack(self, tmp_path):
        path = tmp_path / "scoring_config.json"
        path.write_text(json.dumps({"users": {"alice": {"role": "admin"}}}))

        resolved = load_resolved(str(path), named=True)

        assert resolved["users"] == {"alice": {"role": "admin"}}
        assert len(resolved["categories"]) == len(load_defaults()["categories"])

    def test_namedness_falls_back_to_the_environment_when_not_given(self, tmp_path, monkeypatch):
        """``named=None`` is what every caller without an explicit --config uses."""
        absent = str(tmp_path / "nope.json")

        monkeypatch.delenv("FACET_CONFIG", raising=False)
        assert load_resolved(default_config_path()) == load_defaults()

        monkeypatch.setenv("FACET_CONFIG", absent)
        with pytest.raises(FileNotFoundError):
            load_resolved(absent)

    def test_a_three_key_override_still_yields_a_whole_config(self, tmp_path):
        path = tmp_path / "scoring_config.json"
        path.write_text(json.dumps({"performance": {"mmap_size_mb": 7}}))

        resolved = load_resolved(str(path), named=True)

        assert resolved["performance"]["mmap_size_mb"] == 7
        assert len(resolved["categories"]) == len(load_defaults()["categories"])
        assert resolved["performance"]["cache_size_mb"] == \
            load_defaults()["performance"]["cache_size_mb"]


class TestPathIsNamed:
    """One question, one implementation: did a HUMAN choose this path?"""

    def test_no_path_is_the_inherited_default(self, monkeypatch):
        monkeypatch.delenv("FACET_CONFIG", raising=False)
        assert path_is_named(None) is False

    def test_the_install_root_default_is_not_named(self, monkeypatch):
        monkeypatch.delenv("FACET_CONFIG", raising=False)
        assert path_is_named(default_config_path()) is False

    def test_any_other_path_is_named(self, monkeypatch, tmp_path):
        monkeypatch.delenv("FACET_CONFIG", raising=False)
        assert path_is_named(str(tmp_path / "elsewhere.json")) is True

    def test_the_env_var_names_it_whatever_the_argument(self, monkeypatch, tmp_path):
        """Fail-closed: $FACET_CONFIG is aimed by an operator, so a missing
        target must raise rather than resolve to defaults carrying an empty
        ``viewer.edition_password``."""
        monkeypatch.setenv("FACET_CONFIG", str(tmp_path / "x.json"))
        assert path_is_named(None) is True
        assert path_is_named(default_config_path()) is True

    def test_the_env_value_is_stripped(self, monkeypatch, tmp_path):
        """Whitespace padding in a compose file must not read as unset."""
        target = tmp_path / "x.json"
        monkeypatch.setenv("FACET_CONFIG", f"  {target}  ")
        assert path_is_named(None) is True
        assert default_config_path() == str(target)

    def test_a_relative_default_from_a_foreign_cwd_is_named(self, monkeypatch, tmp_path):
        """`python /opt/facet/facet.py` run from elsewhere must not read its
        own directory's absent file as the inherited default and silently score
        on shipped defaults while the operator's real config sits unread."""
        monkeypatch.delenv("FACET_CONFIG", raising=False)
        monkeypatch.chdir(tmp_path)
        assert path_is_named("scoring_config.json") is True


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

    @pytest.mark.parametrize("spelling", ["relative", "absolute"])
    def test_the_inherited_default_is_unnamed_however_it_is_spelled(self, spelling):
        """Passing a path is not the same as a human naming one.

        WeightOptimizer, calibrate and the personal ranker resolve the default
        themselves and hand it over as the relative ``'scoring_config.json'``;
        keeper_head hands over the absolute one from ``default_config_path``.
        Comparing strings rather than paths made the absolute spelling look
        named, so every keeper-head run raised FileNotFoundError on an install
        with no override file -- which is now the ordinary zero-config install.
        """
        path = ("scoring_config.json" if spelling == "relative"
                else default_config_path())

        assert ScoringConfig(config_path=path, validate=False).config["categories"]


class TestCompactConfig:
    """``python database.py --compact-config`` shrinks a pre-split config in place."""

    def _run(self, config_path):
        return subprocess.run(
            [sys.executable, "database.py", "--compact-config"],
            cwd=Path(__file__).resolve().parent.parent,
            env={**os.environ, "FACET_CONFIG": str(config_path)},
            capture_output=True, text=True,
        )

    def test_a_full_config_compacts_to_nothing_and_resolves_the_same(self, tmp_path):
        """The shipped config IS the defaults, so an operator who never changed
        anything ends up with an empty override -- and loses nothing by it."""
        config_path = tmp_path / "scoring_config.json"
        config_path.write_text(json.dumps(load_defaults(), indent=2))
        before = load_resolved(str(config_path), named=True)

        result = self._run(config_path)

        assert result.returncode == 0, result.stderr
        assert json.loads(config_path.read_text()) == {}
        assert load_resolved(str(config_path), named=True) == before

    def test_it_keeps_every_edit_and_drops_only_the_defaults(self, tmp_path):
        config_path = tmp_path / "scoring_config.json"
        full = load_defaults()
        full["performance"]["mmap_size_mb"] = 99
        full["viewer"]["edition_password"] = "kept"
        config_path.write_text(json.dumps(full, indent=2))

        result = self._run(config_path)

        assert result.returncode == 0, result.stderr
        delta = json.loads(config_path.read_text())
        assert delta["performance"] == {"mmap_size_mb": 99}
        assert delta["viewer"] == {"edition_password": "kept"}
        assert load_resolved(str(config_path), named=True) == full

    def test_it_leaves_an_owner_only_backup(self, tmp_path):
        """The file holds plaintext credentials, so the safety copy must not be
        readable by group or other."""
        config_path = tmp_path / "scoring_config.json"
        config_path.write_text(json.dumps(load_defaults(), indent=2))

        assert self._run(config_path).returncode == 0

        backups = list(tmp_path.glob("scoring_config.json.backup.*"))
        assert len(backups) == 1
        assert stat.S_IMODE(backups[0].stat().st_mode) == 0o600
