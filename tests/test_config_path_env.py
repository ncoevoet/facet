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
    """``ScoringConfig.__init__``'s bare default is ``default_config_path()``,
    the same ABSOLUTE install-root path the other two sites resolve.

    It used to be the relative literal ``'scoring_config.json'``, which was
    harmless only while an absent config still raised: the failure was loud
    wherever you ran from. Once an absent config became a supported state —
    an install running purely on the shipped defaults — the relative name made
    the two indistinguishable, so ``python /opt/facet/facet.py`` run from any
    other directory read its own cwd's absent file as the inherited default
    and scored silently on shipped defaults while the operator's real config
    sat unread in the install root. ``config_resolve.path_is_named`` already
    refuses to compare against the relative name for that exact reason.

    The two spellings only ever differed where the relative one was wrong:
    when cwd IS the install root they name the same file.
    """

    def test_explicit_argument_wins_over_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv(_ENV_VAR, str(tmp_path / "env.json"))
        assert resolve_scoring_config_path(str(tmp_path / "explicit.json")) == str(tmp_path / "explicit.json")

    def test_unset_env_and_no_argument_resolves_the_install_root(self, monkeypatch):
        monkeypatch.delenv(_ENV_VAR, raising=False)
        resolved = resolve_scoring_config_path(None)
        assert resolved == default_config_path()
        assert os.path.isabs(resolved), "a cwd-relative default reads the wrong file from any other directory"

    def test_env_overrides_the_relative_default(self, monkeypatch, tmp_path):
        custom = tmp_path / "custom.json"
        monkeypatch.setenv(_ENV_VAR, str(custom))
        assert resolve_scoring_config_path(None) == str(custom)

    def test_empty_env_falls_back_to_the_install_root(self, monkeypatch):
        monkeypatch.setenv(_ENV_VAR, "")
        assert resolve_scoring_config_path(None) == default_config_path()

    def test_the_default_is_read_from_any_working_directory(self, monkeypatch, tmp_path):
        """The regression the absolute default exists to prevent."""
        monkeypatch.delenv(_ENV_VAR, raising=False)
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

    Startup is NOT expected to abort here. ``create_app`` separately builds a
    ``ScoringConfig`` that raises ``FileNotFoundError`` on the same path, but
    that is an unrelated component's accident, not a decision the auth layer
    makes — these probes import the auth layer on its own precisely so that
    accident cannot stand in for the fix.
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
