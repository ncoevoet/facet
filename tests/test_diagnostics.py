"""Tests for the diagnostics module (--doctor command)."""

import importlib.util
import json
import sqlite3
import sys
import types
from unittest import mock

import pytest

from config.scoring_config import ScoringConfig
from diagnostics import _info, _ok, _section, _warn, run_doctor


def _make_mock_torch_module():
    """Build a torch stand-in with a proper __spec__ so importlib.import_module(...)
    on dependents like transformers/accelerate doesn't raise
    ``ValueError: torch.__spec__ is None``."""
    mod = types.ModuleType("torch")
    mod.__spec__ = importlib.util.spec_from_loader("torch", loader=None)
    return mod


class _StdoutProxy:
    """Proxy that always writes to the current sys.stdout (respects capsys patching)."""
    def write(self, msg):
        sys.stdout.write(msg)
    def flush(self):
        sys.stdout.flush()


@pytest.fixture(autouse=True)
def _configure_diagnostics_logger():
    """Route diagnostics logger output to stdout so capsys can capture it."""
    import logging
    logger = logging.getLogger("facet.diagnostics")
    handler = logging.StreamHandler(_StdoutProxy())
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    yield
    logger.removeHandler(handler)


class TestOutputHelpers:
    """Test the formatted output helpers."""

    def test_section(self, capsys):
        _section("Test Section")
        out = capsys.readouterr().out
        assert "Test Section" in out
        assert "=" * 50 in out

    def test_ok(self, capsys):
        _ok("Label", "value")
        assert "[OK] Label: value" in capsys.readouterr().out

    def test_warn(self, capsys):
        _warn("Label", "value")
        assert "[!!] Label: value" in capsys.readouterr().out

    def test_info(self, capsys):
        _info("Label", "value")
        assert "[--] Label: value" in capsys.readouterr().out


class TestRunDoctorNoPaths:
    """Test run_doctor with missing config and database files."""

    def test_missing_config_and_db(self, capsys, tmp_path):
        config = str(tmp_path / "nonexistent.json")
        db = str(tmp_path / "nonexistent.db")
        run_doctor(config_path=config, db_path=db)
        out = capsys.readouterr().out
        assert "not found" in out
        assert "Python" in out

    def test_defaults(self, capsys):
        """run_doctor uses default paths when called with None."""
        run_doctor(config_path="/tmp/_facet_test_no_such_config.json",
                   db_path="/tmp/_facet_test_no_such_db.db")
        out = capsys.readouterr().out
        assert "Python / Platform" in out
        assert "PyTorch" in out


class TestRunDoctorWithDatabase:
    """Test run_doctor database inspection."""

    def test_valid_database(self, capsys, tmp_path):
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE photos (path TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO photos VALUES ('/a.jpg')")
        conn.execute("INSERT INTO photos VALUES ('/b.jpg')")
        conn.commit()
        conn.close()

        run_doctor(config_path=str(tmp_path / "no.json"), db_path=db_path)
        out = capsys.readouterr().out
        assert "[OK] Photos: 2" in out
        assert "[OK] Integrity: ok" in out

    def test_corrupt_database(self, capsys, tmp_path):
        db_path = str(tmp_path / "corrupt.db")
        with open(db_path, "w") as f:
            f.write("not a database")

        run_doctor(config_path=str(tmp_path / "no.json"), db_path=db_path)
        out = capsys.readouterr().out
        assert "[!!] Database query" in out

    def test_database_missing_table(self, capsys, tmp_path):
        db_path = str(tmp_path / "empty.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE other (id INTEGER)")
        conn.commit()
        conn.close()

        run_doctor(config_path=str(tmp_path / "no.json"), db_path=db_path)
        out = capsys.readouterr().out
        assert "[!!] Database query" in out


class TestRunDoctorConfigFile:
    """Test run_doctor config file inspection."""

    def test_valid_config(self, capsys, tmp_path):
        config_path = str(tmp_path / "scoring_config.json")
        with open(config_path, "w") as f:
            f.write("{}")

        run_doctor(config_path=config_path, db_path=str(tmp_path / "no.db"))
        out = capsys.readouterr().out
        assert "[OK] Config" in out
        assert "KB" in out


def _make_cuda_torch():
    """torch stand-in whose CUDA is available, to drive run_doctor's GPU branch."""
    mock_torch = _make_mock_torch_module()
    mock_torch.__version__ = "2.6.0+cu126"
    mock_torch.version = types.SimpleNamespace(cuda="12.6")
    mock_torch.backends = types.SimpleNamespace(
        cudnn=types.SimpleNamespace(version=lambda: 90100)
    )
    mock_torch.cuda = types.SimpleNamespace(
        is_available=lambda: True,
        get_device_name=lambda idx: "NVIDIA GeForce RTX 3090",
        get_device_properties=lambda idx: types.SimpleNamespace(
            total_memory=24 * 1024**3, major=8, minor=6,
        ),
    )
    return mock_torch


class TestDoctorTorchCompileStatus:
    """--doctor reports torch.compile status on a CUDA host (issue #15)."""

    def _run_with_compiler(self, capsys, tmp_path, compiler, env):
        smi_result = types.SimpleNamespace(returncode=0, stdout="565.77\n")
        with mock.patch.dict("sys.modules", {"torch": _make_cuda_torch()}), \
             mock.patch("diagnostics.subprocess.run", return_value=smi_result), \
             mock.patch("utils.device.detect_c_compiler", return_value=compiler), \
             mock.patch.dict("os.environ", env, clear=False):
            run_doctor(
                config_path=str(tmp_path / "no.json"),
                db_path=str(tmp_path / "no.db"),
            )
        return capsys.readouterr().out

    def test_enabled_when_compiler_present(self, capsys, tmp_path, monkeypatch):
        monkeypatch.delenv("TORCH_COMPILE_DISABLE", raising=False)
        out = self._run_with_compiler(capsys, tmp_path, "/usr/bin/cc", {})
        assert "[OK] torch.compile: enabled" in out

    def test_disabled_when_no_compiler(self, capsys, tmp_path, monkeypatch):
        monkeypatch.delenv("TORCH_COMPILE_DISABLE", raising=False)
        out = self._run_with_compiler(capsys, tmp_path, None, {})
        assert "[!!] torch.compile: disabled" in out
        assert "no C compiler" in out

    def test_disabled_when_env_set(self, capsys, tmp_path):
        out = self._run_with_compiler(
            capsys, tmp_path, "/usr/bin/cc", {"TORCH_COMPILE_DISABLE": "1"})
        assert "torch.compile: disabled" in out
        assert "TORCH_COMPILE_DISABLE" in out


class TestGpuTroubleshooting:
    """Test GPU troubleshooting branch when torch exists but CUDA unavailable."""

    def test_nvidia_smi_finds_gpu(self, capsys, tmp_path):
        """When nvidia-smi sees a GPU but PyTorch can't, show pip install hint."""
        mock_torch = _make_mock_torch_module()
        mock_torch.__version__ = "2.5.0"
        mock_torch.version = types.SimpleNamespace(cuda=None)
        mock_torch.cuda = types.SimpleNamespace(is_available=lambda: False)
        mock_torch.backends = types.SimpleNamespace(
            cudnn=types.SimpleNamespace(version=lambda: None)
        )

        smi_result = types.SimpleNamespace(
            returncode=0, stdout="NVIDIA RTX 5070 Ti, 565.77\n"
        )

        with mock.patch.dict("sys.modules", {"torch": mock_torch}), \
             mock.patch("diagnostics.subprocess.run", return_value=smi_result):
            run_doctor(
                config_path=str(tmp_path / "no.json"),
                db_path=str(tmp_path / "no.db"),
            )

        out = capsys.readouterr().out
        assert "GPU found by driver" in out
        assert "pip install torch torchvision" in out
        assert "cu128" in out

    def test_nvidia_smi_not_found(self, capsys, tmp_path):
        """When nvidia-smi is missing, suggest driver installation."""
        mock_torch = _make_mock_torch_module()
        mock_torch.__version__ = "2.5.0"
        mock_torch.version = types.SimpleNamespace(cuda=None)
        mock_torch.cuda = types.SimpleNamespace(is_available=lambda: False)
        mock_torch.backends = types.SimpleNamespace(
            cudnn=types.SimpleNamespace(version=lambda: None)
        )

        with mock.patch.dict("sys.modules", {"torch": mock_torch}), \
             mock.patch("diagnostics.subprocess.run", side_effect=FileNotFoundError):
            run_doctor(
                config_path=str(tmp_path / "no.json"),
                db_path=str(tmp_path / "no.db"),
            )

        out = capsys.readouterr().out
        assert "nvidia-smi" in out
        assert "not found" in out

    def test_nvidia_smi_no_gpu(self, capsys, tmp_path):
        """When nvidia-smi runs but finds no GPU."""
        mock_torch = _make_mock_torch_module()
        mock_torch.__version__ = "2.5.0"
        mock_torch.version = types.SimpleNamespace(cuda=None)
        mock_torch.cuda = types.SimpleNamespace(is_available=lambda: False)
        mock_torch.backends = types.SimpleNamespace(
            cudnn=types.SimpleNamespace(version=lambda: None)
        )

        smi_result = types.SimpleNamespace(returncode=1, stdout="")

        with mock.patch.dict("sys.modules", {"torch": mock_torch}), \
             mock.patch("diagnostics.subprocess.run", return_value=smi_result):
            run_doctor(
                config_path=str(tmp_path / "no.json"),
                db_path=str(tmp_path / "no.db"),
            )

        out = capsys.readouterr().out
        assert "no GPU found" in out


# --- VRAM Profile Method Tests ---


class TestDetectGpuVramGb:
    """Test ScoringConfig.detect_gpu_vram_gb()."""

    def test_gpu_detected(self):
        """When CUDA is available, return VRAM in GB."""
        mock_torch = _make_mock_torch_module()
        mock_torch.cuda = types.SimpleNamespace(
            is_available=lambda: True,
            get_device_properties=lambda idx: types.SimpleNamespace(
                total_memory=16 * 1024**3,
            ),
        )
        with mock.patch.dict("sys.modules", {"torch": mock_torch}):
            result = ScoringConfig.detect_gpu_vram_gb()
        assert result == 16.0

    def test_no_gpu(self):
        """When CUDA is not available, return None."""
        mock_torch = _make_mock_torch_module()
        mock_torch.cuda = types.SimpleNamespace(is_available=lambda: False)
        with mock.patch.dict("sys.modules", {"torch": mock_torch}):
            result = ScoringConfig.detect_gpu_vram_gb()
        assert result is None

    def test_torch_import_error(self):
        """When torch import fails, return None."""
        with mock.patch.dict("sys.modules", {"torch": None}):
            result = ScoringConfig.detect_gpu_vram_gb()
        assert result is None


class TestSuggestVramProfile:
    """Test ScoringConfig.suggest_vram_profile() with explicit vram_gb."""

    def test_24gb(self):
        profile, vram, msg = ScoringConfig.suggest_vram_profile(vram_gb=24.0)
        assert profile == '24gb'
        assert vram == 24.0
        assert '24gb' in msg

    def test_24gb_boundary(self):
        profile, _, _ = ScoringConfig.suggest_vram_profile(vram_gb=20.0)
        assert profile == '24gb'

    def test_16gb(self):
        profile, vram, msg = ScoringConfig.suggest_vram_profile(vram_gb=16.0)
        assert profile == '16gb'
        assert '16gb' in msg

    def test_16gb_boundary(self):
        profile, _, _ = ScoringConfig.suggest_vram_profile(vram_gb=14.0)
        assert profile == '16gb'

    def test_8gb(self):
        profile, vram, msg = ScoringConfig.suggest_vram_profile(vram_gb=8.0)
        assert profile == '8gb'
        assert '8gb' in msg

    def test_8gb_boundary(self):
        profile, _, _ = ScoringConfig.suggest_vram_profile(vram_gb=6.0)
        assert profile == '8gb'

    def test_legacy(self):
        profile, vram, msg = ScoringConfig.suggest_vram_profile(vram_gb=4.0)
        assert profile == 'legacy'
        assert 'legacy' in msg

    def test_no_gpu_with_ram(self):
        """No GPU, sufficient RAM → legacy profile with RAM info."""
        mock_psutil = types.ModuleType("psutil")
        mock_psutil.virtual_memory = lambda: types.SimpleNamespace(total=31 * 1024**3)
        with mock.patch.object(ScoringConfig, 'detect_gpu_vram_gb', return_value=None), \
             mock.patch.dict("sys.modules", {"psutil": mock_psutil}):
            profile, vram, msg = ScoringConfig.suggest_vram_profile()
        assert profile == 'legacy'
        assert vram is None
        assert '31GB RAM' in msg

    def test_no_gpu_low_ram(self):
        """No GPU, low RAM → legacy with limited CPU mode."""
        mock_psutil = types.ModuleType("psutil")
        mock_psutil.virtual_memory = lambda: types.SimpleNamespace(total=4 * 1024**3)
        with mock.patch.object(ScoringConfig, 'detect_gpu_vram_gb', return_value=None), \
             mock.patch.dict("sys.modules", {"psutil": mock_psutil}):
            profile, vram, msg = ScoringConfig.suggest_vram_profile()
        assert profile == 'legacy'
        assert 'limited CPU mode' in msg


class TestCheckVramProfileCompatibility:
    """Test ScoringConfig.check_vram_profile_compatibility()."""

    @pytest.fixture()
    def config_file(self, tmp_path):
        """Create a minimal config file and return a factory for ScoringConfig."""
        path = tmp_path / "scoring_config.json"

        def _make(vram_profile='auto'):
            data = {"models": {"vram_profile": vram_profile}, "categories": []}
            path.write_text(json.dumps(data))
            return ScoringConfig(str(path), validate=False)

        return _make

    def test_auto_with_gpu(self, config_file):
        config = config_file('auto')
        with mock.patch.object(ScoringConfig, 'detect_gpu_vram_gb', return_value=16.0):
            ok, profile, msg = config.check_vram_profile_compatibility(verbose=False)
        assert ok is True
        assert profile == '16gb'
        assert config.config['models']['vram_profile'] == '16gb'

    def test_auto_no_gpu(self, config_file):
        config = config_file('auto')
        with mock.patch.object(ScoringConfig, 'detect_gpu_vram_gb', return_value=None):
            ok, profile, msg = config.check_vram_profile_compatibility(verbose=False)
        assert ok is True
        assert profile == 'legacy'

    def test_mismatch_16gb_no_gpu(self, config_file):
        config = config_file('16gb')
        with mock.patch.object(ScoringConfig, 'detect_gpu_vram_gb', return_value=None):
            ok, profile, msg = config.check_vram_profile_compatibility(verbose=False)
        assert ok is False
        assert profile == 'legacy'

    def test_legacy_no_gpu(self, config_file):
        config = config_file('legacy')
        with mock.patch.object(ScoringConfig, 'detect_gpu_vram_gb', return_value=None):
            ok, profile, msg = config.check_vram_profile_compatibility(verbose=False)
        assert ok is True
        assert profile == 'legacy'


# --- End-to-End Simulation Tests ---


class TestRtx5070TiScenario:
    """End-to-end tests simulating RTX 5070 Ti detection issue."""

    def test_full_doctor_output(self, capsys, tmp_path):
        """Simulate RTX 5070 Ti with no CUDA support — full doctor run."""
        mock_torch = _make_mock_torch_module()
        mock_torch.__version__ = "2.5.0"
        mock_torch.version = types.SimpleNamespace(cuda=None)
        mock_torch.cuda = types.SimpleNamespace(is_available=lambda: False)
        mock_torch.backends = types.SimpleNamespace(
            cudnn=types.SimpleNamespace(version=lambda: None)
        )

        smi_result = types.SimpleNamespace(
            returncode=0, stdout="NVIDIA RTX 5070 Ti, 565.77\n"
        )

        mock_psutil = types.ModuleType("psutil")
        mock_psutil.virtual_memory = lambda: types.SimpleNamespace(total=31 * 1024**3)

        with mock.patch.dict("sys.modules", {"torch": mock_torch, "psutil": mock_psutil}), \
             mock.patch("diagnostics.subprocess.run", return_value=smi_result), \
             mock.patch.object(ScoringConfig, 'detect_gpu_vram_gb', return_value=None):
            run_doctor(
                config_path=str(tmp_path / "no.json"),
                db_path=str(tmp_path / "no.db"),
            )

        out = capsys.readouterr().out
        assert "GPU Troubleshooting" in out
        assert "GPU found by driver" in out
        assert "RTX 5070 Ti" in out
        assert "cu128" in out
        assert "legacy" in out
        assert "31GB RAM" in out

    def test_simulate_gpu_no_vram(self, capsys, tmp_path):
        """--simulate-gpu without --simulate-vram → troubleshooting output."""
        run_doctor(
            config_path=str(tmp_path / "no.json"),
            db_path=str(tmp_path / "no.db"),
            simulate_gpu="RTX 5070 Ti",
        )

        out = capsys.readouterr().out
        assert "[SIM] Simulation mode: RTX 5070 Ti" in out
        assert "GPU Troubleshooting" in out
        assert "GPU found by driver" in out
        assert "RTX 5070 Ti" in out
        assert "cu128" in out

    def test_simulate_gpu_with_vram(self, capsys, tmp_path):
        """--simulate-gpu with --simulate-vram → shows GPU info and suggests profile."""
        run_doctor(
            config_path=str(tmp_path / "no.json"),
            db_path=str(tmp_path / "no.db"),
            simulate_gpu="RTX 5070 Ti",
            simulate_vram=16.0,
        )

        out = capsys.readouterr().out
        assert "[SIM] Simulation mode: RTX 5070 Ti, 16GB VRAM" in out
        assert "GPU (simulated)" in out
        assert "16.0 GB" in out
        assert "16gb" in out
