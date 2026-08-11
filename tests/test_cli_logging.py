"""Standalone CLIs must install a log handler, and --tag-untagged must work.

Four entry points (tag_existing, calibrate, diagnostics, validate_db) created a
module logger and then never configured logging, so every logger.info they
emitted was dropped. tag_existing.py tagged 26,451 photos in one run and printed
nothing at all.
"""

import logging
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

SILENT_CLIS = ["tag_existing.py", "calibrate.py", "diagnostics.py", "validate_db.py"]


@pytest.fixture(autouse=True)
def _restore_root_logging():
    """configure_cli_logging mutates the root logger; put it back."""
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


class TestConfigureCliLogging:
    def test_installs_a_handler_when_there_is_none(self):
        from utils.cli_logging import configure_cli_logging

        root = logging.getLogger()
        root.handlers[:] = []
        assert configure_cli_logging() == logging.INFO
        assert root.handlers

    def test_is_a_no_op_when_logging_is_already_set_up(self):
        """These modules are imported by facet.py mid-scan; reconfiguring there
        would drop the scan's own format and its tqdm-aware handler."""
        from utils.cli_logging import configure_cli_logging

        root = logging.getLogger()
        existing = logging.NullHandler()
        root.handlers[:] = [existing]

        assert configure_cli_logging() is None
        assert root.handlers == [existing]

    def test_honours_facet_log_level(self, monkeypatch):
        from utils.cli_logging import configure_cli_logging

        monkeypatch.setenv("FACET_LOG_LEVEL", "warning")
        logging.getLogger().handlers[:] = []
        assert configure_cli_logging() == logging.WARNING

    def test_unknown_level_falls_back_to_info(self, monkeypatch):
        from utils.cli_logging import configure_cli_logging

        monkeypatch.setenv("FACET_LOG_LEVEL", "chatty")
        logging.getLogger().handlers[:] = []
        assert configure_cli_logging() == logging.INFO


class TestEveryStandaloneCliConfiguresLogging:
    @pytest.mark.parametrize("script", SILENT_CLIS)
    def test_script_calls_configure_cli_logging(self, script):
        source = (REPO / script).read_text(encoding="utf-8")
        assert "configure_cli_logging()" in source, (
            f"{script} logs but never installs a handler, so it runs silently")


class TestTagUntaggedFlag:
    """--tag-untagged lived only in tag_existing.py, where it went unfound."""

    def test_flag_is_registered_and_documented(self):
        result = subprocess.run(
            [sys.executable, "facet.py", "--help"],
            cwd=REPO, capture_output=True, text=True, timeout=180,
        )
        assert result.returncode == 0, result.stderr[-2000:]
        assert "--tag-untagged" in result.stdout

    def test_handler_has_no_unresolved_names(self):
        """The handler body imports get_tag_params locally -- facet.py does not
        import it at module scope, so a missing import is a NameError that only
        shows up when the flag is actually used."""
        source = (REPO / "facet.py").read_text(encoding="utf-8")
        start = source.index("if args.tag_untagged:")
        block = source[start:start + 1600]
        assert "from utils import get_tag_params" in block
        assert "from tag_existing import" in block

    def test_flag_takes_the_library_lock(self):
        """It rewrites photos.tags, so it must be in LIBRARY_JOB_ARGS."""
        import facet

        assert "tag_untagged" in facet.LIBRARY_JOB_ARGS
