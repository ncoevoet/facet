"""The user config is an OVERRIDE resolved over the shipped defaults.

Two files used to be maintained by hand and copied at install time, and they
drifted: ``scoring_config.default.json`` -- what every container and every
native install starts from -- was missing fourteen key paths the live config
had, so a fresh install silently ran on values hardcoded in the consumers
rather than on the ones documented as shipped. Resolving one file over the
other removes the whole class: there is nothing left to keep in step.
"""

import errno
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

import config_resolve
from config import ScoringConfig
from config_resolve import (
    deep_merge, default_config_path, defaults_path, delta_for_write, load_defaults,
    load_resolved, path_is_named, staged_config_copies, subtract_defaults,
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

    def test_the_result_shares_no_mutable_object_with_either_argument(self):
        """The guarantee every caller depends on, stated as an identity check.

        ``==`` cannot see this: a result that SHARES ``base``'s inner list
        compares equal to a result that copied it, right up until a caller
        appends to the resolved ``categories`` and appends to the shipped
        defaults too. Editing the result and re-reading the inputs is the only
        assertion that fails on a shallow copy.
        """
        base = {"kept": {"deep": [1]}, "overridden": {"a": 1}}
        override = {"overridden": {"b": [2]}}

        merged = deep_merge(base, override)
        merged["kept"]["deep"].append(99)
        merged["overridden"]["b"].append(99)

        assert base == {"kept": {"deep": [1]}, "overridden": {"a": 1}}
        assert override == {"overridden": {"b": [2]}}

    def test_it_copies_each_node_once(self):
        """``_merge_into`` exists for this, and only an accounting test sees it.

        Recursing into ``deep_merge`` re-deep-copied every OVERLAPPING subtree
        once per level of nesting, on top of the whole-tree copy the call had
        already made. The output was correct either way, so nothing else here
        can fail when it comes back.
        """
        import config_resolve

        base = {"a": {"b": {"c": {"d": 1}}}}
        override = {"a": {"b": {"c": {"e": 2}}}}

        calls = []
        real_deepcopy = config_resolve.copy.deepcopy

        def counting_deepcopy(value, *args):
            calls.append(value)
            return real_deepcopy(value, *args)

        config_resolve.copy.deepcopy = counting_deepcopy
        try:
            merged = deep_merge(base, override)
        finally:
            config_resolve.copy.deepcopy = real_deepcopy

        assert merged == {"a": {"b": {"c": {"d": 1, "e": 2}}}}
        # One whole-tree copy of `base`, plus one copy of the single leaf the
        # override contributes. Four levels of overlap used to cost four more.
        assert len(calls) == 2


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

    def test_a_utf8_override_is_decoded_as_utf8_whatever_the_locale(self, tmp_path):
        """A hand-edited override saved as UTF-8 must not be read with the
        locale's code page (cp1252 on Windows, ASCII under LC_ALL=C)."""
        path = tmp_path / "scoring_config.json"
        path.write_bytes(
            json.dumps({"viewer": {"directories": ["/photos/Été"]}}, ensure_ascii=False).encode("utf-8"))
        code = ("import json, sys, config_resolve;"
                "r = config_resolve.load_resolved(sys.argv[1], named=True);"
                "sys.stdout.write(json.dumps(r['viewer']['directories']))")
        result = subprocess.run(
            [sys.executable, "-X", "utf8=0", "-c", code, str(path)],
            cwd=Path(__file__).resolve().parent.parent,
            env={**os.environ, "PYTHONUTF8": "0", "PYTHONCOERCECLOCALE": "0", "LC_ALL": "C"},
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == ["/photos/Été"]


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
        assert Path(defaults_path()).parts[-2:] == ("config", "scoring_config.default.json")

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

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits do not apply on Windows")
    def test_it_leaves_an_owner_only_backup_mode(self, tmp_path):
        config_path = tmp_path / "scoring_config.json"
        config_path.write_text(json.dumps(load_defaults(), indent=2))

        assert self._run(config_path).returncode == 0

        backups = list(tmp_path.glob("scoring_config.json.backup.*"))
        assert len(backups) == 1
        assert stat.S_IMODE(backups[0].stat().st_mode) == 0o600


class TestStagedConfigCopies:
    """A config write that had to rewrite the file IN PLACE — to keep the owner
    an ``os.replace`` would have changed — can be interrupted partway, leaving a
    torn config plus the one complete copy it was about to become.

    ``api.config`` names that copy to the operator when the config fails to
    parse. Finding it is all this does: nothing restores it, because the
    directory is writable by the account the server runs as and the suffix is
    verified against nothing.
    """

    @staticmethod
    def _stage(directory, name, mtime):
        staged = directory / name
        staged.write_text("{}")
        os.utime(staged, (mtime, mtime))
        return staged

    def test_a_clean_directory_has_none(self, tmp_path):
        (tmp_path / "scoring_config.json").write_text("{}")
        assert staged_config_copies(str(tmp_path / "scoring_config.json")) == []

    def test_they_come_back_newest_first(self, tmp_path):
        """The newest is the one the interrupted write staged; anything older is
        an earlier crash, and offering that first would restore the wrong config.
        """
        older = self._stage(tmp_path, ".scoring_config.tmpaaa.json", 1_000_000)
        newer = self._stage(tmp_path, ".scoring_config.tmpbbb.json", 2_000_000)

        assert staged_config_copies(str(tmp_path / "scoring_config.json")) == [
            str(newer), str(older)]

    def test_the_config_and_its_backups_are_not_staging_copies(self, tmp_path):
        config_path = tmp_path / "scoring_config.json"
        config_path.write_text("{}")
        (tmp_path / "scoring_config.json.backup").write_text("{}")
        (tmp_path / "scoring_config.json.backup.20260101_000000").write_text("{}")
        staged = self._stage(tmp_path, ".scoring_config.tmpccc.json", 1_000_000)

        assert staged_config_copies(str(config_path)) == [str(staged)]

    @pytest.mark.skipif(sys.platform == 'win32', reason="POSIX directory permissions")
    @pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0,
                        reason="root reads a directory whatever its mode says")
    def test_an_unreadable_directory_yields_nothing(self, tmp_path):
        """This is a diagnostic on an already-failing path: it must not raise a
        second error on top of the one the operator is being told about."""
        closed = tmp_path / "closed"
        closed.mkdir()
        os.chmod(closed, 0o000)
        try:
            assert staged_config_copies(str(closed / "scoring_config.json")) == []
        finally:
            os.chmod(closed, 0o700)


class TestInPlaceCommitStillWritesTheDelta:
    """The route the writer takes must not change WHAT it writes.

    ``write_user_config`` persists the override, not the resolved config, and the
    in-place route is reached through exactly the same function — so a config
    whose owner could not be adopted must still end up holding three keys rather
    than the 3700-line resolved tree.
    """

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX ownership has no Windows analogue")
    def test_a_denied_chown_still_persists_only_the_override(self, tmp_path, monkeypatch):
        config_path = tmp_path / "scoring_config.json"
        config_path.write_text("{}")
        before = os.stat(config_path).st_ino

        real_identity = config_resolve._destination_identity

        class _ForeignOwner:
            """The real lstat with somebody else's uid — an unprivileged test
            cannot create a file it does not own, so the ANSWER is faked and
            every identity field left real."""

            def __init__(self, real):
                self._real = real
                self.st_uid = real.st_uid + 1
                self.st_gid = real.st_gid + 1

            def __getattr__(self, name):
                return getattr(self._real, name)

        def _foreign(path):
            info = real_identity(path)
            return info if info is None else _ForeignOwner(info)

        def _refuse(*args, **kwargs):
            # Two-arg: a bare PermissionError carries errno None, which the
            # writer re-raises rather than downgrading to the in-place route.
            raise PermissionError(errno.EPERM, "Operation not permitted")

        monkeypatch.setattr(config_resolve, "_destination_identity", _foreign)
        monkeypatch.setattr(os, "chown", _refuse)

        resolved = load_resolved(str(config_path), named=True)
        resolved["performance"]["mmap_size_mb"] = 4096
        config_resolve.write_user_config(str(config_path), resolved)

        assert os.stat(config_path).st_ino == before, "the file was renamed over, not rewritten"
        assert json.loads(config_path.read_text()) == {"performance": {"mmap_size_mb": 4096}}
        assert load_resolved(str(config_path), named=True)["performance"]["mmap_size_mb"] == 4096
