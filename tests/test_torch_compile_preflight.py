"""Tests for the torch.compile C-compiler preflight (issue #15).

torch.compile's inductor backend compiles lazily at first inference, so a
missing ``gcc``/``g++`` only blows up once per image instead of at startup.
``utils.device.torch_compile_status`` probes for a usable C compiler (and
honours ``TORCH_COMPILE_DISABLE``) so callers fall back to eager CUDA
inference with an honest log line instead of the misleading
"Models compiled with torch.compile()" success message.
"""

from unittest import mock

from utils.device import detect_c_compiler, torch_compile_status


class TestDetectCCompiler:
    def test_finds_cc(self, monkeypatch):
        monkeypatch.delenv("CC", raising=False)

        def which(name):
            return "/usr/bin/cc" if name == "cc" else None

        with mock.patch("utils.device.shutil.which", side_effect=which):
            assert detect_c_compiler() == "/usr/bin/cc"

    def test_falls_back_to_gcc(self, monkeypatch):
        monkeypatch.delenv("CC", raising=False)

        def which(name):
            return "/usr/bin/gcc" if name == "gcc" else None

        with mock.patch("utils.device.shutil.which", side_effect=which):
            assert detect_c_compiler() == "/usr/bin/gcc"

    def test_honours_cc_env(self, monkeypatch):
        monkeypatch.setenv("CC", "clang")

        def which(name):
            return "/usr/bin/clang" if name == "clang" else None

        with mock.patch("utils.device.shutil.which", side_effect=which):
            assert detect_c_compiler() == "/usr/bin/clang"

    def test_returns_none_when_absent(self, monkeypatch):
        monkeypatch.delenv("CC", raising=False)
        with mock.patch("utils.device.shutil.which", return_value=None):
            assert detect_c_compiler() is None


class TestTorchCompileStatus:
    def test_enabled_when_compiler_present(self, monkeypatch):
        monkeypatch.delenv("TORCH_COMPILE_DISABLE", raising=False)
        with mock.patch("utils.device.detect_c_compiler", return_value="/usr/bin/cc"):
            enabled, reason = torch_compile_status()
        assert enabled is True
        assert "C compiler available" in reason

    def test_disabled_when_no_compiler(self, monkeypatch):
        monkeypatch.delenv("TORCH_COMPILE_DISABLE", raising=False)
        with mock.patch("utils.device.detect_c_compiler", return_value=None):
            enabled, reason = torch_compile_status()
        assert enabled is False
        assert "no C compiler" in reason

    def test_disabled_when_env_set(self, monkeypatch):
        monkeypatch.setenv("TORCH_COMPILE_DISABLE", "1")
        # Env wins even when a compiler is present.
        with mock.patch("utils.device.detect_c_compiler", return_value="/usr/bin/cc"):
            enabled, reason = torch_compile_status()
        assert enabled is False
        assert "TORCH_COMPILE_DISABLE" in reason
