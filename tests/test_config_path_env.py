"""Tests for the ``$FACET_CONFIG`` env var and its four resolution sites:
``api.config._resolve_config_path`` (feeding the module-level ``_CONFIG_PATH``),
``db.connection._resolve_config_path`` (likewise), ``config.default_config_path``,
and ``config.scoring_config.resolve_scoring_config_path`` (feeding
``ScoringConfig.__init__``'s default). All four must agree that an unset
variable resolves to exactly the path each already resolved to before
``$FACET_CONFIG`` existed, and a set variable overrides every one of them.

The two ``_CONFIG_PATH`` constants are additionally checked in a child
interpreter: they are resolved once at import, so a resolver that honours the
variable while the constant beside it keeps a literal would pass every
in-process test and still ignore the variable in the container.
"""

import os
import subprocess
import sys

import pytest

import api.config as api_config
import db.connection as db_connection
from config import default_config_path
from config.scoring_config import resolve_scoring_config_path

_ENV_VAR = "FACET_CONFIG"


def _repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(api_config.__file__)))


def _todays_api_config_path():
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(api_config.__file__))), "scoring_config.json")


class TestApiConfigResolvePath:
    def test_unset_resolves_to_the_repo_root_file(self, monkeypatch):
        monkeypatch.delenv(_ENV_VAR, raising=False)
        assert api_config._resolve_config_path() == _todays_api_config_path()

    def test_set_overrides_with_the_exact_value(self, monkeypatch, tmp_path):
        custom = tmp_path / "custom.json"
        monkeypatch.setenv(_ENV_VAR, str(custom))
        assert api_config._resolve_config_path() == str(custom)

    def test_set_value_is_stripped(self, monkeypatch, tmp_path):
        custom = tmp_path / "custom.json"
        monkeypatch.setenv(_ENV_VAR, f"  {custom}  ")
        assert api_config._resolve_config_path() == str(custom)

    def test_empty_env_falls_back(self, monkeypatch):
        """docker-compose sets `VAR=` when the .env value is unset."""
        monkeypatch.setenv(_ENV_VAR, "")
        assert api_config._resolve_config_path() == _todays_api_config_path()


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


class TestApiConfigAndDefaultConfigPathStayConsistent:
    """``config.default_config_path``'s docstring promises it resolves what
    ``api.config._CONFIG_PATH`` resolves. Both must move together under
    ``$FACET_CONFIG``, not just when it is unset.
    """

    def test_agree_when_unset(self, monkeypatch):
        monkeypatch.delenv(_ENV_VAR, raising=False)
        assert api_config._resolve_config_path() == default_config_path()

    def test_agree_when_set(self, monkeypatch, tmp_path):
        custom = tmp_path / "custom.json"
        monkeypatch.setenv(_ENV_VAR, str(custom))
        assert api_config._resolve_config_path() == default_config_path()


class TestScoringConfigInitDefault:
    """``ScoringConfig.__init__``'s bare default is the RELATIVE literal
    ``'scoring_config.json'`` (resolved against process cwd, like every
    ``facet.py --config``-less invocation), not the absolute
    ``default_config_path()`` — so its unset case is a different "today's
    path" than the other two sites.
    """

    def test_explicit_argument_wins_over_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv(_ENV_VAR, str(tmp_path / "env.json"))
        assert resolve_scoring_config_path(str(tmp_path / "explicit.json")) == str(tmp_path / "explicit.json")

    def test_unset_env_and_no_argument_keeps_the_relative_default(self, monkeypatch):
        monkeypatch.delenv(_ENV_VAR, raising=False)
        assert resolve_scoring_config_path(None) == "scoring_config.json"

    def test_env_overrides_the_relative_default(self, monkeypatch, tmp_path):
        custom = tmp_path / "custom.json"
        monkeypatch.setenv(_ENV_VAR, str(custom))
        assert resolve_scoring_config_path(None) == str(custom)

    def test_empty_env_falls_back_to_the_relative_default(self, monkeypatch):
        monkeypatch.setenv(_ENV_VAR, "")
        assert resolve_scoring_config_path(None) == "scoring_config.json"


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


class TestDbConnectionResolvePath:
    """``db.connection`` resolves the path a fourth time, on its own.

    It cannot import ``config``: ``config/__init__.py`` imports
    ``config.percentile_normalizer``, which imports ``db`` -- and this module is
    the first thing ``db/__init__.py`` imports. The copy is deliberate, so it
    needs the same tests as the original rather than none.
    """

    def test_unset_resolves_to_the_repo_root_file(self, monkeypatch):
        monkeypatch.delenv(_ENV_VAR, raising=False)
        assert db_connection._resolve_config_path() == _todays_api_config_path()

    def test_set_overrides_with_the_exact_value(self, monkeypatch, tmp_path):
        custom = tmp_path / "custom.json"
        monkeypatch.setenv(_ENV_VAR, str(custom))
        assert db_connection._resolve_config_path() == str(custom)

    def test_set_value_is_stripped(self, monkeypatch, tmp_path):
        custom = tmp_path / "custom.json"
        monkeypatch.setenv(_ENV_VAR, f"  {custom}  ")
        assert db_connection._resolve_config_path() == str(custom)

    def test_empty_env_falls_back(self, monkeypatch):
        monkeypatch.setenv(_ENV_VAR, "")
        assert db_connection._resolve_config_path() == _todays_api_config_path()

    def test_it_agrees_with_the_other_three_sites(self, monkeypatch, tmp_path):
        custom = tmp_path / "custom.json"
        monkeypatch.setenv(_ENV_VAR, str(custom))
        assert db_connection._resolve_config_path() == api_config._resolve_config_path()
        assert db_connection._resolve_config_path() == default_config_path()
