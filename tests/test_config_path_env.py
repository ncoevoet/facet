"""Tests for the ``$FACET_CONFIG`` env var and its three resolution sites:
``config.default_config_path`` (which ``api.config`` imports to fill its
module-level ``_CONFIG_PATH``), ``db.connection._resolve_config_path`` (a
deliberate copy — see :class:`TestDbConnectionResolvePath`), and
``config.scoring_config.resolve_scoring_config_path`` (feeding
``ScoringConfig.__init__``'s default). All three must agree that an unset
variable resolves to exactly the path each already resolved to before
``$FACET_CONFIG`` existed, and a set variable overrides every one of them.

The two ``_CONFIG_PATH`` constants are additionally checked in a child
interpreter: they are resolved once at import, so a resolver that honours the
variable while the constant beside it keeps a literal would pass every
in-process test and still ignore the variable in the container.

The variable also decides how a MISSING config reads. A path nobody named is a
fresh install and legitimately open; a path the operator named and mistyped is
not, and must fail closed — see
:class:`TestAMissingConfigOnlyReadsAsAFreshInstallWhenNobodyNamedIt`.
"""

import json
import logging
import os
import stat
import subprocess
import sys

import pytest

import api.config as api_config
import db.connection as db_connection
from config import default_config_path
from config_resolve import load_defaults
from config.scoring_config import resolve_scoring_config_path

_ENV_VAR = "FACET_CONFIG"


def _repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(api_config.__file__)))


def _todays_api_config_path():
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(api_config.__file__))), "scoring_config.json")


class TestApiConfigReusesTheSharedResolver:
    """``api.config`` must not re-derive the path — it imports the resolver.

    It used to carry ``_resolve_config_path``, a byte-for-byte copy of
    ``config.default_config_path``'s body, which could drift from it silently.
    Nothing stopped it: the copy sat in a different package from every test that
    pinned the original.
    """

    def test_it_imports_the_shared_resolver(self):
        assert api_config.default_config_path is default_config_path

    def test_it_no_longer_carries_its_own_copy(self):
        assert not hasattr(api_config, "_resolve_config_path")

    def test_the_constant_is_what_the_shared_resolver_returns(self, monkeypatch):
        monkeypatch.delenv(_ENV_VAR, raising=False)
        assert api_config._CONFIG_PATH == default_config_path()


class TestDefaultConfigPath:
    def test_unset_resolves_to_the_repo_root_file(self, monkeypatch):
        monkeypatch.delenv(_ENV_VAR, raising=False)
        assert default_config_path() == _todays_api_config_path()

    def test_set_overrides_with_the_exact_value(self, monkeypatch, tmp_path):
        custom = tmp_path / "custom.json"
        monkeypatch.setenv(_ENV_VAR, str(custom))
        assert default_config_path() == str(custom)

    def test_empty_env_falls_back(self, monkeypatch):
        monkeypatch.setenv(_ENV_VAR, "")
        assert default_config_path() == _todays_api_config_path()


class TestScoringConfigInitDefault:
    """``ScoringConfig.__init__``'s bare default: a config in the WORKING
    DIRECTORY if there is one, else the absolute install-root path.

    Both halves are load-bearing and were each broken at some point. Reading
    the working directory is a real workflow -- run Facet from a photo library
    carrying its own ``scoring_config.json`` and that config scores it -- so an
    unconditional absolute default silently ignores the operator's file.
    Falling through to the install root when there is NO local file is the
    other half: while an absent config still raised, an unconditional relative
    name was harmless because the failure was loud wherever you ran from, but
    once "absent" became a supported state it made "no config here"
    indistinguishable from "no config anywhere" -- so running the install's
    facet.py from elsewhere scored silently on shipped defaults while the
    operator's real config sat unread.
    """

    def test_explicit_argument_wins_over_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv(_ENV_VAR, str(tmp_path / "env.json"))
        assert resolve_scoring_config_path(str(tmp_path / "explicit.json")) == str(tmp_path / "explicit.json")

    def test_env_overrides_the_default(self, monkeypatch, tmp_path):
        custom = tmp_path / "custom.json"
        monkeypatch.setenv(_ENV_VAR, str(custom))
        assert resolve_scoring_config_path(None) == str(custom)

    def test_a_config_in_the_working_directory_is_used(self, monkeypatch, tmp_path):
        """Run Facet from a library that carries its own config and it wins."""
        monkeypatch.delenv(_ENV_VAR, raising=False)
        monkeypatch.chdir(tmp_path)
        (tmp_path / "scoring_config.json").write_text("{}")
        assert resolve_scoring_config_path(None) == "scoring_config.json"

    def test_no_config_in_the_working_directory_falls_through_to_the_install_root(
        self, monkeypatch, tmp_path,
    ):
        """The regression the fall-through exists to prevent.

        A bare relative name here reads *this* directory's absent file as the
        inherited default, which resolves to the shipped defaults -- silently
        discarding the operator's real config in the install root.
        """
        monkeypatch.delenv(_ENV_VAR, raising=False)
        monkeypatch.chdir(tmp_path)
        resolved = resolve_scoring_config_path(None)
        assert resolved == default_config_path()
        assert os.path.isabs(resolved)

    def test_empty_env_falls_back_the_same_way(self, monkeypatch, tmp_path):
        monkeypatch.setenv(_ENV_VAR, "")
        monkeypatch.chdir(tmp_path)
        assert resolve_scoring_config_path(None) == default_config_path()


class TestScoringConfigEndToEnd:
    """A full ``ScoringConfig()`` instantiation actually reads from
    ``$FACET_CONFIG``, not just the path-resolution helper in isolation.
    """

    def test_loads_the_env_named_file_with_no_explicit_path(self, monkeypatch, tmp_path):
        from config.scoring_config import ScoringConfig

        custom = tmp_path / "custom.json"
        custom.write_text('{"categories": [{"name": "default", "priority": 999}]}')
        monkeypatch.setenv(_ENV_VAR, str(custom))

        cfg = ScoringConfig(validate=False)

        assert cfg.config_path == str(custom)
        assert cfg.config["categories"][0]["name"] == "default"


class TestTheModuleConstantsHonourTheVariable:
    """The env var has to reach the module-level ``_CONFIG_PATH`` constants.

    Both ``api.config`` and ``db.connection`` resolve their path ONCE at import
    and every later reader takes that constant, so a resolver function that
    honours ``$FACET_CONFIG`` while the constant beside it keeps a hardcoded
    literal is inert exactly where Docker needs it. Only a fresh interpreter
    can see this: the constant in this process was fixed when the suite
    imported it, which is also why ``tests/conftest.py`` clears the variable
    before any project module loads.
    """

    def _resolved_in_a_child(self, module, attribute, env_value, tmp_path):
        env = dict(os.environ)
        env["PYTHONPATH"] = _repo_root()
        if env_value is None:
            env.pop(_ENV_VAR, None)
        else:
            env[_ENV_VAR] = env_value
        probe = subprocess.run(
            [sys.executable, "-c",
             f"import {module} as m; print(m.{attribute})"],
            cwd=tmp_path, capture_output=True, text=True, env=env,
        )
        assert probe.returncode == 0, probe.stderr
        return probe.stdout.strip()

    @pytest.mark.parametrize("module,attribute", [
        ("api.config", "_CONFIG_PATH"),
        ("db.connection", "_CONFIG_PATH"),
    ])
    def test_the_constant_follows_the_variable(self, tmp_path, module, attribute):
        custom = tmp_path / "elsewhere.json"

        resolved = self._resolved_in_a_child(module, attribute, str(custom), tmp_path)

        assert resolved == str(custom)

    @pytest.mark.parametrize("module,attribute", [
        ("api.config", "_CONFIG_PATH"),
        ("db.connection", "_CONFIG_PATH"),
    ])
    def test_an_unset_variable_keeps_the_repo_root_file(self, tmp_path, module, attribute):
        resolved = self._resolved_in_a_child(module, attribute, None, tmp_path)

        assert resolved == _todays_api_config_path()


class TestDbConnectionReusesTheSharedResolver:
    """``db.connection`` resolves the path through ``config_resolve`` too.

    It cannot import ``config``: ``config/__init__.py`` imports
    ``config.percentile_normalizer``, which imports ``db`` -- and this module is
    the first thing ``db/__init__.py`` imports, so the import recurses into a
    half-built ``db``. That is why it used to carry ``_resolve_config_path``, a
    byte-for-byte copy. ``config_resolve`` is stdlib-only and imports nothing
    from this project, so the copy is gone and the reuse is what needs pinning.
    """

    def test_it_no_longer_carries_its_own_copy(self):
        assert not hasattr(db_connection, "_resolve_config_path")

    def test_it_imports_the_shared_resolver(self):
        assert db_connection.default_config_path is default_config_path

    def test_the_constant_is_what_the_shared_resolver_returns(self, monkeypatch):
        monkeypatch.delenv(_ENV_VAR, raising=False)
        assert db_connection._CONFIG_PATH == _todays_api_config_path()

    def test_importing_it_first_does_not_recurse(self):
        """The reason for the copy, asserted rather than assumed.

        Run in a fresh interpreter: importing ``db`` pulls ``db.connection``
        before ``db`` is bound, so a resolver that reached the ``config``
        PACKAGE from here would raise ImportError on a partially initialised
        module. In-process this would pass on a warm ``sys.modules`` no matter
        what, which is exactly how such a regression would slip through.
        """
        result = subprocess.run(
            [sys.executable, "-c", "import db; print(db.connection._CONFIG_PATH)"],
            cwd=_repo_root(), capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip().endswith("scoring_config.json")


class TestAMissingConfigOnlyReadsAsAFreshInstallWhenNobodyNamedIt:
    """A config that is not there means two opposite things.

    Before the path became env-driven it was derived from ``__file__`` and could
    not be misaimed, so "absent" genuinely meant "never configured" and
    :func:`api.config._is_open_install`'s fail-open was sound. ``$FACET_CONFIG``
    broke that: the value is taken verbatim, never checked for existence, and a
    one-character typo in it made a password-protected install read as one that
    was never configured at all.
    """

    def _read_an_absent_config(self, monkeypatch, tmp_path, explicit):
        monkeypatch.setattr(api_config, "_config_load_failed", False)
        monkeypatch.setattr(api_config, "_CONFIG_PATH", str(tmp_path / "nope.json"))
        if explicit is not None:
            monkeypatch.setattr(api_config, "_CONFIG_PATH_IS_EXPLICIT", explicit)
        return api_config._read_config()

    def test_an_unnamed_absent_config_is_still_a_fresh_install(self, monkeypatch, tmp_path):
        """The zero-config first run must keep working exactly as it did.

        The config is no longer empty -- an absent override file resolves to the
        shipped defaults, which is what makes a container with no config file at
        all a working install rather than a broken one. What must NOT move is
        the auth side: ``parsed_ok`` stays False and the defaults must carry no
        password, or this branch would start granting rights off a file the
        operator never wrote.
        """
        assert not os.environ.get(_ENV_VAR, "").strip(), "conftest clears it before import"

        config, parsed_ok = self._read_an_absent_config(monkeypatch, tmp_path, None)

        assert parsed_ok is False
        assert api_config.config_load_failed() is False
        assert config == load_defaults()
        viewer = config.get("viewer", {})
        assert not viewer.get("password")
        assert not viewer.get("edition_password")
        assert not config.get("users")

    def test_an_explicitly_named_absent_config_fails_closed(self, monkeypatch, tmp_path):
        """A NAMED path that is absent gets no defaults either.

        The unnamed branch above hands back the shipped defaults; this one must
        not. Those defaults carry an empty ``viewer.edition_password``, and an
        empty edition password disables edition gating outright -- so returning
        them here would rebuild, through the merge, the exact open install this
        branch exists to refuse.
        """
        config, parsed_ok = self._read_an_absent_config(monkeypatch, tmp_path, True)

        assert (config, parsed_ok) == ({}, False)
        assert api_config.config_load_failed() is True

    def test_it_reports_the_named_path_at_error_level(self, monkeypatch, tmp_path, caplog):
        """``logger.debug`` is invisible under the shipped ``FACET_LOG_LEVEL=INFO``."""
        with caplog.at_level(logging.DEBUG, logger=api_config.__name__):
            self._read_an_absent_config(monkeypatch, tmp_path, True)

        errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert errors, caplog.text
        assert _ENV_VAR in errors[0].getMessage()
        assert "nope.json" in errors[0].getMessage()

    @pytest.mark.parametrize("env_value", ["", "   "])
    def test_an_empty_variable_names_nothing(self, tmp_path, env_value):
        """docker-compose sets ``VAR=`` when the .env value is unset.

        That must stay a fresh install rather than a misaimed one, and it is the
        module-level constant that decides — hence a child interpreter.
        """
        env = dict(os.environ)
        env["PYTHONPATH"] = _repo_root()
        env[_ENV_VAR] = env_value
        probe = subprocess.run(
            [sys.executable, "-c",
             "import api.config as c; print(c._CONFIG_PATH_IS_EXPLICIT)"],
            cwd=tmp_path, capture_output=True, text=True, env=env,
        )

        assert probe.returncode == 0, probe.stderr
        assert probe.stdout.strip() == "False"

    def test_a_named_config_that_is_there_parses_as_before(self, monkeypatch, tmp_path):
        named = tmp_path / "here.json"
        named.write_text('{"viewer": {"edition_password": "s3cret"}}')
        monkeypatch.setattr(api_config, "_config_load_failed", False)
        monkeypatch.setattr(api_config, "_CONFIG_PATH", str(named))
        monkeypatch.setattr(api_config, "_CONFIG_PATH_IS_EXPLICIT", True)

        config, parsed_ok = api_config._read_config()

        assert parsed_ok is True
        assert config["viewer"]["edition_password"] == "s3cret"
        assert api_config.config_load_failed() is False


class TestTheAuthSurfaceSeesAMisaimedConfigPath:
    """What the fail-closed state is actually FOR, end to end.

    ``api.config`` resolves its path once at import, so only a fresh
    interpreter can be pointed somewhere else — the constant in this process was
    fixed when the suite imported it. The probe reads ``api.auth`` rather than
    ``api.config`` alone because the flag is only interesting where it lands: an
    anonymous caller's edition rights.

    Startup is NOT expected to abort here, and no longer can:
    ``api.config.server_scoring_config`` catches the ``FileNotFoundError`` the
    same path raises and falls back to the shipped defaults, so the traceback
    that used to come out of ``create_app`` cannot replace the 503 and the
    logged error an operator needs. These probes still import the auth layer on
    its own, so that no other component's behaviour can stand in for the fix.
    """

    _PROBE = (
        "import json, api.config as c, api.auth as a; "
        "print(json.dumps({"
        "'load_failed': c.config_load_failed(), "
        "'open_edition': a._is_open_install(a.EDITION_PASSWORD_KEY), "
        "'open_viewer': a._is_open_install(a.VIEWER_PASSWORD_KEY), "
        "'anon_edition': a.CurrentUser().is_edition, "
        "'anon_authenticated': a.CurrentUser().is_authenticated}))"
    )

    def _probe(self, tmp_path, env_value):
        env = dict(os.environ)
        env["PYTHONPATH"] = _repo_root()
        env[_ENV_VAR] = env_value
        probe = subprocess.run(
            [sys.executable, "-c", self._PROBE],
            cwd=tmp_path, capture_output=True, text=True, env=env,
        )
        assert probe.returncode == 0, probe.stderr
        return json.loads(probe.stdout.strip().splitlines()[-1])

    def test_a_typod_path_does_not_hand_edition_rights_to_anonymous(self, tmp_path):
        seen = self._probe(tmp_path, str(tmp_path / "scoring_confg.json"))

        assert seen["load_failed"] is True
        assert seen["open_edition"] is False
        assert seen["open_viewer"] is False
        assert seen["anon_edition"] is False
        assert seen["anon_authenticated"] is False

    def test_a_named_password_protected_config_still_gates(self, tmp_path):
        named = tmp_path / "scoring_config.json"
        named.write_text('{"viewer": {"password": "p", "edition_password": "s3cret"}}')

        seen = self._probe(tmp_path, str(named))

        assert seen["load_failed"] is False
        assert seen["open_edition"] is False
        assert seen["anon_edition"] is False

    def test_a_named_open_config_stays_open(self, tmp_path):
        named = tmp_path / "scoring_config.json"
        named.write_text("{}")

        seen = self._probe(tmp_path, str(named))

        assert seen["load_failed"] is False
        assert seen["open_edition"] is True
        assert seen["anon_edition"] is True


class TestTheServerScoresAndAuthenticatesFromOneFile:
    """A config in the WORKING DIRECTORY must not score a library the auth layer
    cannot see.

    ``config.scoring_config.resolve_scoring_config_path`` prefers a
    ``scoring_config.json`` in the process working directory, which is a real
    CLI workflow: run ``facet.py`` from a photo library that carries its own
    config and that config scores it. ``api.config`` has no such step — it
    resolves ``default_config_path()`` once at import — so the two disagreed
    exactly when the install root held no config, which is the ordinary state
    of an install running on the shipped defaults.

    What the disagreement bought: start the viewer from a library holding a
    password-protected config and ``ScoringConfig`` honoured its weights while
    ``VIEWER_CONFIG`` came from the absent install-root path, resolved to the
    shipped defaults, and reported an empty ``viewer.password`` AND an empty
    ``viewer.edition_password``. ``_is_open_install`` then answered True for
    both, so the operator's passwords were ignored and every route, edition
    writes included, was anonymous.

    A subprocess because both resolutions happen at import, and ``cwd`` is what
    the whole defect turns on.
    """

    _CONFIG = '{"viewer": {"password": "librarysecret", "edition_password": "editsecret"}}'

    _PROBE = (
        "import json, api.config as c, api.auth as a; "
        "s = c.server_scoring_config(); "
        "print(json.dumps({"
        "'scoring_path': s.config_path, "
        "'auth_path': c.server_config_path(), "
        "'scoring_password': s.config.get('viewer', {}).get('password', ''), "
        "'auth_password': c.VIEWER_CONFIG.get('password', ''), "
        "'open_viewer': a._is_open_install(a.VIEWER_PASSWORD_KEY), "
        "'open_edition': a._is_open_install(a.EDITION_PASSWORD_KEY)}))"
    )

    def _probe(self, cwd):
        env = dict(os.environ)
        env["PYTHONPATH"] = _repo_root()
        env.pop(_ENV_VAR, None)
        probe = subprocess.run(
            [sys.executable, "-c", self._PROBE],
            cwd=cwd, capture_output=True, text=True, env=env,
        )
        assert probe.returncode == 0, probe.stderr
        return json.loads(probe.stdout.strip().splitlines()[-1])

    def test_a_cwd_config_does_not_score_a_library_auth_cannot_see(self, tmp_path):
        (tmp_path / "scoring_config.json").write_text(self._CONFIG)

        seen = self._probe(tmp_path)

        assert seen["scoring_path"] == seen["auth_path"], (
            "the server scored from a different file than it authenticated from"
        )
        assert seen["scoring_password"] == seen["auth_password"]

    def test_a_cwd_config_never_leaves_the_install_open_on_its_own(self, tmp_path):
        (tmp_path / "scoring_config.json").write_text(self._CONFIG)

        seen = self._probe(tmp_path)

        # Either the server reads that config -- and is then gated by the
        # passwords in it -- or it does not read it at all. What it must never
        # do is score with it while reporting no passwords.
        if seen["scoring_password"] == "librarysecret":
            assert seen["open_viewer"] is False
            assert seen["open_edition"] is False


class TestAMalformedViewerSubBlockFailsClosedInsteadOfCrashing:
    """A `viewer` sub-block written as a scalar must fail the way its parent does.

    ``load_viewer_config`` backfills each shipped sub-block key by key, so a
    config holding ``"viewer": {"features": true}`` reached
    ``if k not in viewer[key]`` with a bool and raised
    ``TypeError: argument of type 'bool' is not iterable`` at IMPORT of
    ``api.config`` — naming neither the file nor the key. The operator got a
    traceback out of a module they never edited.

    The sibling case one level up (``viewer`` itself not a dict) already raised
    a precise ``ValueError`` naming the file, which ``_read_config``'s handler
    turns into ``({}, False)`` plus an armed ``config_load_failed``. These
    tests pin that the level below now behaves identically — same message
    shape, same fail-closed state, no ``TypeError``.

    A secret file is seeded because otherwise a DIFFERENT, deliberate guard
    fires first: an unparseable config with no stored secret refuses to mint an
    in-memory-only one. That guard is pre-existing and fires for the parent
    case too, so seeding around it is what isolates the behaviour under test.
    """

    _PROBE = (
        "import json, api.config as c, api.auth as a; "
        "print(json.dumps({"
        "'load_failed': c.config_load_failed(), "
        "'open_viewer': a._is_open_install(a.VIEWER_PASSWORD_KEY), "
        "'open_edition': a._is_open_install(a.EDITION_PASSWORD_KEY), "
        "'any_feature_on': any(c.VIEWER_CONFIG.get('features', {}).values())}))"
    )

    _MALFORMED = '{"viewer": {"features": true, "password": "x"}}'

    def _probe(self, tmp_path, body):
        config = tmp_path / "scoring_config.json"
        config.write_text(body)
        secret = tmp_path / ".facet_secret"
        secret.write_text("a" * 40 + "\n")
        secret.chmod(0o600)
        env = dict(os.environ)
        env["PYTHONPATH"] = _repo_root()
        env[_ENV_VAR] = str(config)
        return subprocess.run(
            [sys.executable, "-c", self._PROBE],
            cwd=tmp_path, capture_output=True, text=True, env=env,
        )

    def test_it_no_longer_raises_a_typeerror_from_the_backfill(self, tmp_path):
        probe = self._probe(tmp_path, self._MALFORMED)

        assert probe.returncode == 0, probe.stderr
        assert "TypeError" not in probe.stderr

    def test_the_error_names_the_file_and_the_offending_key(self, tmp_path):
        probe = self._probe(tmp_path, self._MALFORMED)

        assert "viewer.features" in probe.stderr
        assert "scoring_config.json" in probe.stderr
        assert "not bool" in probe.stderr

    def test_it_fails_closed_with_every_feature_off(self, tmp_path):
        probe = self._probe(tmp_path, self._MALFORMED)
        seen = json.loads(probe.stdout.strip().splitlines()[-1])

        assert seen["load_failed"] is True
        assert seen["open_viewer"] is False
        assert seen["open_edition"] is False
        assert seen["any_feature_on"] is False

    def test_a_well_formed_sub_block_is_untouched(self, tmp_path):
        probe = self._probe(
            tmp_path, '{"viewer": {"features": {"show_map": false}, "password": "x"}}',
        )
        seen = json.loads(probe.stdout.strip().splitlines()[-1])

        assert seen["load_failed"] is False
        assert seen["open_viewer"] is False

    def test_a_string_valued_key_is_not_treated_as_a_sub_block(self, tmp_path):
        """``viewer.password`` is a string in the shipped defaults and must stay
        one — the check only covers keys the defaults ship as objects."""
        probe = self._probe(tmp_path, '{"viewer": {"password": "hunter2"}}')
        seen = json.loads(probe.stdout.strip().splitlines()[-1])

        assert seen["load_failed"] is False
        assert seen["open_viewer"] is False


class TestALooseConfigModeIsReported:
    """The boot path sweeps the secret store and every backup — but not the one
    file that always exists.

    ``_config_backup_paths`` filters on the backup suffix, and
    ``'scoring_config.json'.startswith('scoring_config.json.backup')`` is
    False, so the live config was excluded by accident. It holds the same
    secrets as the two files that ARE checked, and an install upgrading from
    the tracked-config era got it from a ``git clone`` at the umask default.

    Reported, not tightened: ``config_resolve._replacement_mode`` preserves an
    existing mode on every write precisely so Facet does not overrule an
    operator who chose one. Silence is what made a mode nobody chose permanent.
    """

    def _probe(self, tmp_path, mode):
        config = tmp_path / "scoring_config.json"
        config.write_text('{"viewer": {"password": "topsecret"}}')
        config.chmod(mode)
        secret = tmp_path / ".facet_secret"
        secret.write_text("a" * 40 + "\n")
        secret.chmod(0o600)
        env = dict(os.environ)
        env["PYTHONPATH"] = _repo_root()
        env[_ENV_VAR] = str(config)
        probe = subprocess.run(
            [sys.executable, "-c",
             "import logging; logging.basicConfig(level=logging.WARNING); import api.config"],
            cwd=tmp_path, capture_output=True, text=True, env=env,
        )
        assert probe.returncode == 0, probe.stderr
        return probe.stderr, config

    def test_a_world_readable_config_is_reported(self, tmp_path):
        stderr, _ = self._probe(tmp_path, 0o644)

        assert "readable beyond its owner" in stderr
        assert "scoring_config.json" in stderr

    def test_the_mode_is_left_exactly_as_the_operator_set_it(self, tmp_path):
        _, config = self._probe(tmp_path, 0o644)

        assert stat.S_IMODE(config.stat().st_mode) == 0o644

    def test_an_owner_only_config_says_nothing(self, tmp_path):
        stderr, _ = self._probe(tmp_path, 0o600)

        assert "readable beyond its owner" not in stderr
