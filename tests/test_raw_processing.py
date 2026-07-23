"""Tests for darktable-cli command construction (api/raw_processing.py).

Exercises the pure ``_build_darktable_cmd`` assembler — no darktable binary
needed — so the profile flags (style, apply-custom-presets, sizing) are verified
deterministically in CI.
"""

import sys

from api import raw_processing
from api.raw_processing import _build_darktable_cmd


def _cmd(profile, quality=96):
    return _build_darktable_cmd("/usr/bin/darktable-cli", "in.cr2", "in.cr2.xmp",
                                "out.jpg", quality, profile)


def _flag_value(cmd, flag):
    return cmd[cmd.index(flag) + 1]


class TestBuildDarktableCmd:
    def test_positional_order(self):
        cmd = _cmd({})
        assert cmd[:4] == ["/usr/bin/darktable-cli", "in.cr2", "in.cr2.xmp", "out.jpg"]

    def test_quality_conf(self):
        cmd = _cmd({}, quality=88)
        assert "--core" in cmd
        assert "plugins/imageio/format/jpeg/quality=88" in cmd

    def test_no_style_by_default(self):
        cmd = _cmd({})
        assert "--style" not in cmd
        assert "--apply-custom-presets" not in cmd

    def test_style_flag(self):
        cmd = _cmd({"style": "Velvia look"})
        assert _flag_value(cmd, "--style") == "Velvia look"

    def test_apply_custom_presets_false(self):
        cmd = _cmd({"style": "S", "apply_custom_presets": False})
        assert _flag_value(cmd, "--apply-custom-presets") == "false"

    def test_apply_custom_presets_true_is_omitted(self):
        # Only the explicit "false" emits the flag; true is darktable's default.
        cmd = _cmd({"apply_custom_presets": True})
        assert "--apply-custom-presets" not in cmd

    def test_sizing_and_extra_args(self):
        cmd = _cmd({"width": 2048, "height": 1536, "extra_args": ["--verbose"]})
        assert _flag_value(cmd, "--width") == "2048"
        assert _flag_value(cmd, "--height") == "1536"
        assert "--verbose" in cmd

    def test_hq_default_true(self):
        assert _flag_value(_cmd({}), "--hq") == "true"

    def test_empty_xmp_positional_omitted(self):
        # darktable-cli rejects an empty XMP positional ("can't open XMP file"),
        # so an absent sidecar must drop the positional, not pass "".
        cmd = _build_darktable_cmd("/usr/bin/darktable-cli", "in.cr2", "", "out.jpg", 96, {})
        assert cmd[:3] == ["/usr/bin/darktable-cli", "in.cr2", "out.jpg"]
        assert "" not in cmd


class TestIsDarktableAvailable:
    def setup_method(self):
        raw_processing._darktable_available_cache = None

    def teardown_method(self):
        raw_processing._darktable_available_cache = None

    def test_reflects_executable_change_without_restart(self, monkeypatch):
        monkeypatch.setitem(
            raw_processing.VIEWER_CONFIG, "raw_processor",
            {"darktable": {"executable": "/no/such/darktable-cli"}})
        assert raw_processing.is_darktable_available() is False

        monkeypatch.setitem(
            raw_processing.VIEWER_CONFIG, "raw_processor",
            {"darktable": {"executable": sys.executable}})
        assert raw_processing.is_darktable_available() is True

    def test_ttl_expiry_picks_up_config_fix_on_same_executable(self, monkeypatch):
        monkeypatch.setitem(
            raw_processing.VIEWER_CONFIG, "raw_processor",
            {"darktable": {"executable": sys.executable}})
        import time
        raw_processing._darktable_available_cache = (time.monotonic() - 1000, sys.executable, False)
        assert raw_processing.is_darktable_available() is True
