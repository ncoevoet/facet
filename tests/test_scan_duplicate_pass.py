"""The scan-end duplicate pass is opt-in (duplicate_detection.enabled)."""

import logging
from types import SimpleNamespace

import pytest

from facet import _maybe_detect_duplicates


def _scorer(settings):
    config = SimpleNamespace(
        get_duplicate_detection_settings=lambda: settings, config_path="cfg.json")
    return SimpleNamespace(config=config, db_path="photos.db")


@pytest.fixture
def calls(monkeypatch):
    seen = []
    monkeypatch.setattr(
        "utils.duplicate.detect_duplicates",
        lambda db_path, config_path=None: seen.append((db_path, config_path)))
    return seen


@pytest.mark.parametrize("settings", [{}, {"similarity_threshold_percent": 90}, {"enabled": False}])
def test_pass_does_not_run_unless_enabled(calls, settings):
    _maybe_detect_duplicates(_scorer(settings))
    assert calls == []


def test_pass_runs_when_enabled(calls):
    _maybe_detect_duplicates(_scorer({"enabled": True}))
    assert calls == [("photos.db", "cfg.json")]


def test_failure_is_logged_and_does_not_raise(monkeypatch, caplog):
    def boom(db_path, config_path=None):
        raise RuntimeError("boom")

    monkeypatch.setattr("utils.duplicate.detect_duplicates", boom)
    with caplog.at_level(logging.WARNING):
        _maybe_detect_duplicates(_scorer({"enabled": True}))
    assert "Duplicate detection failed" in caplog.text


def test_shipped_defaults_leave_the_pass_off():
    from config.scoring_config import ScoringConfig
    from config_resolve import defaults_path

    settings = ScoringConfig(str(defaults_path()), validate=False).get_duplicate_detection_settings()
    assert settings.get("enabled", False) is False
