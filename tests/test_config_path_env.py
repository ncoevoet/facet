"""Tests for the ``$FACET_CONFIG`` env var and its three resolution sites:
``api.config._resolve_config_path`` (feeding the module-level ``_CONFIG_PATH``),
``config.default_config_path``, and ``config.scoring_config._resolve_scoring_config_path``
(feeding ``ScoringConfig.__init__``'s default). All three must agree that an
unset variable resolves to exactly the path each already resolved to before
``$FACET_CONFIG`` existed, and a set variable overrides every one of them.
"""

import os

import api.config as api_config
from config import default_config_path
from config.scoring_config import _resolve_scoring_config_path

_ENV_VAR = "FACET_CONFIG"


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
        assert _resolve_scoring_config_path(str(tmp_path / "explicit.json")) == str(tmp_path / "explicit.json")

    def test_unset_env_and_no_argument_keeps_the_relative_default(self, monkeypatch):
        monkeypatch.delenv(_ENV_VAR, raising=False)
        assert _resolve_scoring_config_path(None) == "scoring_config.json"

    def test_env_overrides_the_relative_default(self, monkeypatch, tmp_path):
        custom = tmp_path / "custom.json"
        monkeypatch.setenv(_ENV_VAR, str(custom))
        assert _resolve_scoring_config_path(None) == str(custom)

    def test_empty_env_falls_back_to_the_relative_default(self, monkeypatch):
        monkeypatch.setenv(_ENV_VAR, "")
        assert _resolve_scoring_config_path(None) == "scoring_config.json"


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
