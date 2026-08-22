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
from utils import system_memory


def _fake_effective_memory(monkeypatch, total_gb):
    """Point ``suggest_vram_profile``'s memory read at a synthetic reading.

    ``suggest_vram_profile`` resolves ``effective_memory`` with a
    function-local import, so patching the ``utils.system_memory`` module
    attribute -- not ``sys.modules["psutil"]`` -- is what actually reaches it:
    ``system_memory`` binds the real ``psutil`` at its own first import, and a
    later ``sys.modules`` swap never reaches that already-bound name.
    """
    reading = system_memory.EffectiveMemory(
        total=int(total_gb * 1024**3), used=0,
        available=int(total_gb * 1024**3), percent=0.0,
    )
    monkeypatch.setattr(system_memory, "effective_memory", lambda: reading)
    return reading


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


def _make_mps_torch():
    """torch stand-in whose Apple Metal backend is available."""
    mock_torch = _make_mock_torch_module()
    mock_torch.__version__ = "2.6.0"
    mock_torch.version = types.SimpleNamespace(cuda=None)
    mock_torch.backends = types.SimpleNamespace(
        cudnn=types.SimpleNamespace(version=lambda: None),
        mps=types.SimpleNamespace(is_available=lambda: True),
    )
    mock_torch.cuda = types.SimpleNamespace(is_available=lambda: False)
    return mock_torch


class TestDoctorMPS:
    def test_reports_mps_as_active_without_nvidia_warning(self, capsys, tmp_path, monkeypatch):
        monkeypatch.delenv("FACET_DEVICE", raising=False)
        with mock.patch.dict("sys.modules", {"torch": _make_mps_torch()}), \
             mock.patch("diagnostics.subprocess.run") as run:
            run_doctor(
                config_path=str(tmp_path / "no.json"),
                db_path=str(tmp_path / "no.db"),
            )

        out = capsys.readouterr().out
        assert "[OK] Apple Silicon (MPS): available" in out
        assert "[OK] Facet runtime device: mps" in out
        assert "Apple Metal Performance Shaders" in out
        assert "InsightFace: ONNX Runtime CPU provider" in out
        assert "GPU Troubleshooting" not in out
        assert all(call.args[0][0] != "nvidia-smi" for call in run.call_args_list)


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

    def test_no_gpu_with_ram(self, monkeypatch):
        """No GPU, sufficient RAM → legacy profile with RAM info."""
        _fake_effective_memory(monkeypatch, 31)
        with mock.patch.object(ScoringConfig, 'detect_gpu_vram_gb', return_value=None), \
             mock.patch("utils.device.mps_available", return_value=False):
            profile, vram, msg = ScoringConfig.suggest_vram_profile()
        assert profile == 'legacy'
        assert vram is None
        assert '31GB RAM' in msg

    def test_no_gpu_large_ram_stays_legacy(self, monkeypatch):
        """Plenty of RAM without an accelerator is still the legacy profile."""
        _fake_effective_memory(monkeypatch, 128)
        with mock.patch.object(ScoringConfig, 'detect_gpu_vram_gb', return_value=None), \
             mock.patch("utils.device.mps_available", return_value=False):
            profile, vram, msg = ScoringConfig.suggest_vram_profile()
        assert profile == 'legacy'
        assert vram is None
        assert 'No GPU detected' in msg

    def test_no_gpu_low_ram(self, monkeypatch):
        """No GPU, low RAM → legacy with limited CPU mode."""
        _fake_effective_memory(monkeypatch, 4)
        with mock.patch.object(ScoringConfig, 'detect_gpu_vram_gb', return_value=None), \
             mock.patch("utils.device.mps_available", return_value=False):
            profile, vram, msg = ScoringConfig.suggest_vram_profile()
        assert profile == 'legacy'
        assert 'limited CPU mode' in msg

    @staticmethod
    def _suggest_on_mps(monkeypatch, total_memory_gb):
        """Run the suggestion on a simulated Metal machine of a given size."""
        _fake_effective_memory(monkeypatch, total_memory_gb)
        monkeypatch.delenv("FACET_DEVICE", raising=False)
        with mock.patch.object(ScoringConfig, 'detect_gpu_vram_gb', return_value=None), \
             mock.patch("utils.device.mps_available", return_value=True):
            return ScoringConfig.suggest_vram_profile()

    def test_mps_sizes_the_profile_from_unified_memory(self, monkeypatch):
        """A large Mac gets a real profile, not the weakest tier."""
        profile, vram, msg = self._suggest_on_mps(monkeypatch, 128)
        assert profile == '24gb'
        assert vram is None
        assert 'MPS' in msg
        assert '128GB unified memory' in msg
        assert 'sized from total unified memory' in msg
        assert 'Torch models accelerated' in msg

    def test_mps_48gb_reaches_the_richest_profile(self, monkeypatch):
        profile, _, _ = self._suggest_on_mps(monkeypatch, 48)
        assert profile == '24gb'

    def test_mps_36gb_stays_on_the_16gb_profile(self, monkeypatch):
        profile, _, _ = self._suggest_on_mps(monkeypatch, 36)
        assert profile == '16gb'

    def test_mps_32gb_reaches_the_16gb_profile(self, monkeypatch):
        profile, _, _ = self._suggest_on_mps(monkeypatch, 32)
        assert profile == '16gb'

    def test_mps_24gb_stays_on_the_8gb_profile(self, monkeypatch):
        profile, _, _ = self._suggest_on_mps(monkeypatch, 24)
        assert profile == '8gb'

    def test_mps_16gb_reaches_the_8gb_profile(self, monkeypatch):
        profile, _, _ = self._suggest_on_mps(monkeypatch, 16)
        assert profile == '8gb'

    def test_mps_small_mac_still_uses_legacy(self, monkeypatch):
        """8GB of unified memory has no headroom for a richer profile."""
        profile, _, msg = self._suggest_on_mps(monkeypatch, 8)
        assert profile == 'legacy'
        assert '8GB unified memory' in msg

    def test_mps_falls_back_to_legacy_when_memory_is_unreadable(self, monkeypatch):
        """Unified memory that cannot be measured must not be assumed large.

        ``UNKNOWN_MEMORY`` (a zero total) is what ``effective_memory()``
        reports when neither psutil nor a cgroup file could be read -- this
        covers that degradation, not psutil's absence specifically, since
        ``suggest_vram_profile`` no longer imports psutil itself.
        """
        monkeypatch.delenv("FACET_DEVICE", raising=False)
        monkeypatch.setattr(system_memory, "effective_memory", lambda: system_memory.UNKNOWN_MEMORY)
        with mock.patch.object(ScoringConfig, 'detect_gpu_vram_gb', return_value=None), \
             mock.patch("utils.device.mps_available", return_value=True):
            profile, vram, msg = ScoringConfig.suggest_vram_profile()
        assert profile == 'legacy'
        assert vram is None
        assert 'MPS' in msg

    def test_mps_cpu_override_is_reported(self, monkeypatch):
        _fake_effective_memory(monkeypatch, 48)
        monkeypatch.setenv("FACET_DEVICE", "cpu")
        with mock.patch.object(ScoringConfig, 'detect_gpu_vram_gb', return_value=None), \
             mock.patch("utils.device.mps_available", return_value=True):
            profile, _, msg = ScoringConfig.suggest_vram_profile()
        assert profile == 'legacy'
        assert 'FACET_DEVICE=cpu' in msg

    def test_container_memory_limit_sizes_the_profile_not_the_host_total(
            self, monkeypatch, tmp_path):
        """Inside a memory-limited container the profile must be sized from
        the cgroup limit, not the idle host's total -- the whole reason
        ``suggest_vram_profile`` was rewired onto ``effective_memory()``
        (issue #111). The host here is a 128GB Mac, which alone would reach
        the richest profile; a 16GB cgroup limit must pull it down instead.
        """
        host_reading = system_memory.EffectiveMemory(
            total=128 * 1024**3, used=8 * 1024**3, available=120 * 1024**3, percent=6.0,
        )
        monkeypatch.setattr(system_memory, "_host_memory", lambda: host_reading)
        monkeypatch.setattr(
            system_memory, "CGROUP_V2_LIMIT_PATH", str(tmp_path / "memory.max"))
        (tmp_path / "memory.max").write_text(f"{16 * 1024**3}\n")
        monkeypatch.setattr(
            system_memory, "CGROUP_V1_LIMIT_PATH", str(tmp_path / "absent-v1-limit"))
        monkeypatch.setattr(
            system_memory, "CGROUP_V2_USAGE_PATH", str(tmp_path / "absent-v2-usage"))
        monkeypatch.setattr(
            system_memory, "CGROUP_V1_USAGE_PATH", str(tmp_path / "absent-v1-usage"))
        monkeypatch.setattr(
            system_memory, "CGROUP_V2_STAT_PATH", str(tmp_path / "absent-v2-stat"))
        monkeypatch.delenv("FACET_DEVICE", raising=False)

        with mock.patch.object(ScoringConfig, 'detect_gpu_vram_gb', return_value=None), \
             mock.patch("utils.device.mps_available", return_value=True):
            profile, vram, msg = ScoringConfig.suggest_vram_profile()

        assert profile == '8gb'
        assert vram is None
        assert '16GB unified memory' in msg


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

    def test_full_doctor_output(self, capsys, tmp_path, monkeypatch):
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

        _fake_effective_memory(monkeypatch, 31)

        with mock.patch.dict("sys.modules", {"torch": mock_torch}), \
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
