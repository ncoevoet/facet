"""Tests for the diagnostics module (--doctor command)."""

import importlib.util
import json
import logging
import os
import platform
import sqlite3
import sys
import types
import warnings
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
        device_count=lambda: 1,
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


def _make_blackwell_torch():
    """torch stand-in for a CUDA build that ships no kernels for the local GPU.

    ``is_available()`` is True and the VRAM reads back fine -- exactly what an
    RTX 50-series card (``sm_120``) on a CUDA 12.6 wheel reports right up to
    the first real tensor op, which dies with "no kernel image is available
    for execution on the device" (issue #119).
    """
    mock_torch = _make_mock_torch_module()
    mock_torch.__version__ = "2.6.0+cu126"
    mock_torch.version = types.SimpleNamespace(cuda="12.6")
    mock_torch.backends = types.SimpleNamespace(
        cudnn=types.SimpleNamespace(version=lambda: 90100)
    )
    mock_torch.cuda = types.SimpleNamespace(
        is_available=lambda: True,
        device_count=lambda: 1,
        get_device_name=lambda idx: "NVIDIA GeForce RTX 5070 Ti",
        get_device_properties=lambda idx: types.SimpleNamespace(
            total_memory=16 * 1024**3, major=12, minor=0,
        ),
        get_device_capability=lambda idx=0: (12, 0),
        get_arch_list=lambda: [
            "sm_50", "sm_60", "sm_70", "sm_75", "sm_80", "sm_86", "sm_90",
        ],
    )
    return mock_torch


def _make_busy_gpu_torch():
    """torch stand-in for a supported card that is momentarily unusable.

    The arch list covers the device, so nothing is wrong with the build --
    another process simply holds the card. Reading that as "no kernels for
    this device" would demote a whole scan to CPU and blame the install.
    """
    mock_torch = _make_cuda_torch()
    mock_torch.cuda.get_device_capability = lambda idx=0: (8, 6)
    mock_torch.cuda.get_arch_list = lambda: [
        "sm_50", "sm_60", "sm_70", "sm_75", "sm_80", "sm_86", "sm_90",
    ]

    def _busy(*args, **kwargs):
        raise RuntimeError("CUDA error: all CUDA-capable devices are busy or unavailable")

    mock_torch.zeros = _busy
    return mock_torch


class TestDoctorBlackwellArchMismatch:
    """--doctor must not read all-green on a GPU no kernel can launch on.

    Before issue #119 every check here passed -- CUDA compiled, cuDNN found,
    is_available() True, VRAM and compute capability printed -- and the scan
    then crashed on its first batch.
    """

    def _run(self, capsys, tmp_path, monkeypatch):
        monkeypatch.delenv("FACET_DEVICE", raising=False)
        _fake_effective_memory(monkeypatch, 31)
        with mock.patch.dict("sys.modules", {"torch": _make_blackwell_torch()}), \
             mock.patch("diagnostics.subprocess.run"):
            run_doctor(
                config_path=str(tmp_path / "no.json"),
                db_path=str(tmp_path / "no.db"),
            )
        return capsys.readouterr().out

    def test_reports_the_mismatch_instead_of_an_ok_gpu(self, capsys, tmp_path, monkeypatch):
        out = self._run(capsys, tmp_path, monkeypatch)
        assert "GPU Troubleshooting" in out
        assert "sm_120" in out
        assert "[OK] torch.cuda.is_available(): True" not in out
        assert "[OK] VRAM" not in out

    def test_the_rendered_diagnosis_reaches_the_user(self, capsys, tmp_path, monkeypatch):
        """The label alone renders identically whatever the diagnosis says.

        ``[!!] GPU unusable by this PyTorch build`` prints even when the
        status carries an empty reason, and ``sm_120`` is already satisfied
        by the separate compute-capability line -- so neither pins the one
        thing this block exists to tell the user, which architectures the
        installed wheel actually ships.
        """
        out = self._run(capsys, tmp_path, monkeypatch)
        assert "[!!] GPU unusable by this PyTorch build: device sm_120" in out
        assert "is not covered by this PyTorch build's architectures" in out
        assert "sm_90" in out

    def test_names_the_image_tag_to_switch_to(self, capsys, tmp_path, monkeypatch):
        """The card here is sm_120, so latest-cuda and cu128 are the FIX.

        latest-cuda-legacy (sm_50-sm_90) and cu126 are the fallback lines for
        older cards; asserting only those let the two recommendations that
        actually resolve issue #119 be deleted with the suite green.
        """
        out = self._run(capsys, tmp_path, monkeypatch)
        assert "ghcr.io/ncoevoet/facet:latest-cuda " in out
        assert "whl/cu128" in out
        assert "ghcr.io/ncoevoet/facet:latest-cuda-legacy" in out
        assert "whl/cu126" in out

    def test_runtime_device_falls_back_to_cpu(self, capsys, tmp_path, monkeypatch):
        out = self._run(capsys, tmp_path, monkeypatch)
        assert "[OK] Facet runtime device: cpu" in out

    def test_does_not_blame_a_cpu_only_pytorch_build(self, capsys, tmp_path, monkeypatch):
        out = self._run(capsys, tmp_path, monkeypatch)
        assert "PyTorch was built without CUDA support" not in out

    def test_the_profile_section_agrees_with_the_diagnosis(self, capsys, tmp_path, monkeypatch):
        """One --doctor run must not both explain the card and deny it exists."""
        out = self._run(capsys, tmp_path, monkeypatch)
        assert "[OK] Recommended: GPU unusable by this PyTorch build" in out
        assert "No GPU detected" not in out


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
            device_count=lambda: 1,
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

    def test_unusable_gpu(self):
        """A card this build ships no kernels for must not size a profile.

        This is the line that decides whether a GPU profile gets committed,
        and it reports VRAM perfectly happily on an RTX 50-series card that
        cannot launch a kernel (issue #119). Asserted directly here because
        every other suite mocks this method out.
        """
        with mock.patch.dict("sys.modules", {"torch": _make_blackwell_torch()}):
            result = ScoringConfig.detect_gpu_vram_gb()
        assert result is None

    def test_busy_gpu_still_reports_its_vram(self):
        """A transient failure must not look like an unusable card."""
        with mock.patch.dict("sys.modules", {"torch": _make_busy_gpu_torch()}):
            result = ScoringConfig.detect_gpu_vram_gb()
        assert result == 24.0


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

    def test_unusable_gpu_is_not_reported_as_an_absent_one(self, monkeypatch):
        """A present-but-unusable card must not read as "No GPU detected".

        --doctor prints this line one section below the arch-mismatch
        diagnosis, so the old wording made one run contradict itself: the
        troubleshooting block explains the card while the profile block
        denies it exists (issue #119).
        """
        _fake_effective_memory(monkeypatch, 31)
        monkeypatch.delenv("FACET_DEVICE", raising=False)
        with mock.patch.dict("sys.modules", {"torch": _make_blackwell_torch()}), \
             mock.patch.object(ScoringConfig, 'detect_gpu_vram_gb', return_value=None):
            profile, vram, msg = ScoringConfig.suggest_vram_profile()
        assert profile == 'legacy'
        assert vram is None
        assert 'No GPU detected' not in msg
        assert 'GPU unusable by this PyTorch build' in msg
        assert 'sm_120' in msg
        assert '31GB RAM' in msg

    def test_a_busy_gpu_is_not_reported_as_an_unusable_build(self, monkeypatch):
        """A momentarily busy card must not read as a wrong PyTorch build.

        detect_gpu_vram_gb sees the card, so this never reaches the no-VRAM
        branch at all -- which is the point: the scan keeps its GPU profile
        instead of silently falling to a CPU run of the whole library.
        """
        _fake_effective_memory(monkeypatch, 31)
        monkeypatch.delenv("FACET_DEVICE", raising=False)
        with mock.patch.dict("sys.modules", {"torch": _make_busy_gpu_torch()}):
            profile, vram, msg = ScoringConfig.suggest_vram_profile()
        assert profile == '24gb'
        assert vram == 24.0
        assert 'unusable' not in msg
        assert 'No GPU detected' not in msg

    def test_absent_gpu_keeps_the_no_gpu_wording(self, monkeypatch):
        """The genuinely absent case is untouched -- only the present one moves."""
        _fake_effective_memory(monkeypatch, 31)
        monkeypatch.delenv("FACET_DEVICE", raising=False)
        no_cuda = _make_mock_torch_module()
        no_cuda.cuda = types.SimpleNamespace(is_available=lambda: False)
        no_cuda.backends = types.SimpleNamespace(
            cudnn=types.SimpleNamespace(version=lambda: None)
        )
        with mock.patch.dict("sys.modules", {"torch": no_cuda}), \
             mock.patch.object(ScoringConfig, 'detect_gpu_vram_gb', return_value=None):
            profile, _, msg = ScoringConfig.suggest_vram_profile()
        assert profile == 'legacy'
        assert 'No GPU detected' in msg
        assert 'unusable' not in msg

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
            self, monkeypatch, fake_cgroup):
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
        fake_cgroup(v2_limit=f"{16 * 1024**3}\n")
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

    def test_auto_no_gpu(self, config_file, monkeypatch):
        config = config_file('auto')
        # "No GPU" must also mean no Metal: on a Mac mps_available() is True and
        # auto resolves through unified memory instead of falling to legacy,
        # which made these tests fail on any machine that runs the viewer.
        monkeypatch.setattr('utils.device.mps_available', lambda: False)
        with mock.patch.object(ScoringConfig, 'detect_gpu_vram_gb', return_value=None):
            ok, profile, msg = config.check_vram_profile_compatibility(verbose=False)
        assert ok is True
        assert profile == 'legacy'

    def test_mismatch_16gb_no_gpu(self, config_file, monkeypatch):
        config = config_file('16gb')
        monkeypatch.setattr('utils.device.mps_available', lambda: False)
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

    def test_unusable_gpu_is_not_reported_as_an_absent_one(self, config_file, monkeypatch):
        """An explicit 16gb profile on a card the wheel cannot run must say so.

        The card is physically present and the driver sees it, so "No GPU
        detected" sends the user hunting for the wrong problem (issue #119).
        """
        monkeypatch.delenv("FACET_DEVICE", raising=False)
        config = config_file('16gb')
        with mock.patch.dict("sys.modules", {"torch": _make_blackwell_torch()}), \
             mock.patch.object(ScoringConfig, 'detect_gpu_vram_gb', return_value=None):
            ok, profile, msg = config.check_vram_profile_compatibility(verbose=False)
        assert ok is False
        assert profile == 'legacy'
        assert "No GPU detected" not in msg
        assert "sm_120" in msg

    def test_verbose_mismatch_warning_names_the_reason(self, config_file, monkeypatch, caplog):
        """verbose=True is the branch a real ``python facet.py`` run takes.

        Every other test here passes verbose=False and asserts the returned
        string, so the logger.warning block could be broken, deleted, or made
        to raise -- which would abort startup -- with the suite green.
        """
        monkeypatch.delenv("FACET_DEVICE", raising=False)
        config = config_file('16gb')
        with caplog.at_level(logging.WARNING), \
             mock.patch.dict("sys.modules", {"torch": _make_blackwell_torch()}), \
             mock.patch.object(ScoringConfig, 'detect_gpu_vram_gb', return_value=None):
            ok, profile, msg = config.check_vram_profile_compatibility(verbose=True)
        assert ok is False
        assert "GPU present but unusable by this PyTorch build" in caplog.text
        assert "sm_120" in caplog.text
        assert "No GPU does not support" not in caplog.text


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


class TestDoctorListsWhatIsRouted:
    """The doctor reports the components a scan loads, not those merely configured."""

    DEFAULT_IDS = {
        'legacy': ['clip_mlp_head', 'clip', 'topiq_iaa', 'topiq_nr_face', 'liqe', 'samp_net',
                   'u2netp', 'birefnet', 'insightface', 'mediapipe_face_landmarker'],
        '8gb': ['clip_mlp_head', 'clip', 'topiq_iaa', 'topiq_nr_face', 'liqe', 'samp_net',
                'u2netp', 'birefnet', 'insightface', 'mediapipe_face_landmarker',
                'qrealign_native'],
        '12gb': ['topiq', 'siglip2', 'qwen3_5_2b', 'topiq_iaa', 'topiq_nr_face', 'liqe',
                 'samp_net', 'u2netp', 'birefnet', 'insightface', 'mediapipe_face_landmarker',
                 'qrealign_native'],
        '16gb': ['topiq', 'siglip2', 'qwen3_5_2b', 'topiq_iaa', 'topiq_nr_face', 'liqe',
                 'samp_net', 'u2netp', 'birefnet', 'insightface', 'mediapipe_face_landmarker',
                 'qrealign_native'],
        '24gb': ['topiq', 'siglip2', 'qwen3_5_4b', 'topiq_iaa', 'topiq_nr_face', 'liqe',
                 'samp_net', 'u2netp', 'birefnet', 'insightface', 'mediapipe_face_landmarker',
                 'qrealign_native'],
    }

    @staticmethod
    def _cfg():
        import config_resolve
        return config_resolve.load_resolved(None)

    @pytest.mark.parametrize('profile', ['legacy', '8gb', '12gb', '16gb', '24gb'])
    def test_default_mode_ids_are_unchanged(self, profile):
        import licensing
        from diagnostics import _components_in_use
        ids = _components_in_use(self._cfg(), profile, licensing.Policy('default', False))
        assert ids == self.DEFAULT_IDS[profile]

    @pytest.mark.parametrize('profile', ['legacy', '8gb', '12gb', '16gb', '24gb'])
    def test_commercial_mode_lists_the_permissive_stack_and_nothing_refused(self, profile):
        import licensing
        from diagnostics import _components_in_use
        ids = _components_in_use(self._cfg(), profile, licensing.Policy('commercial', False))
        assert {'yunet', 'sface', 'qrealign_native'} <= set(ids)
        for refused in ('topiq', 'insightface', 'liqe', 'topiq_iaa', 'topiq_nr_face', 'clip_mlp_head'):
            assert refused not in ids
        assert all(licensing.allowed(i, licensing.Policy('commercial', False)) for i in ids)

    def test_the_wrapper_and_the_doctor_share_one_router(self):
        """_select_models is a thin wrapper: both answer from route_models."""
        import inspect

        from processing import multi_pass
        assert 'route_models(' in inspect.getsource(multi_pass.ChunkedMultiPassProcessor._select_models)


_UNSET = object()
_REPAIR_COMMAND = 'pip uninstall -y onnxruntime onnxruntime-gpu && pip install "onnxruntime-gpu>=1.19.0,<1.27"'
_CPU_REPAIR_COMMAND = 'pip uninstall -y onnxruntime onnxruntime-gpu && pip install "onnxruntime>=1.15.0"'
# The shape of onnxruntime-gpu's file descriptor 2 output when the CUDA provider cannot load (RTX 4070 Ti SUPER,
# 1.31.0 beside a cu128 PyTorch): the C++ logger colours each line with ANSI escapes, the [E:...] line runs to about
# 500 characters and the library name only starts after the first 400, and nothing reaches Python's warnings.
_CUDA13_LOAD_FAILURE = (
    b"\x1b[1;31m2026-10-21 17:49:09.661651736 [E:onnxruntime:Default, provider_bridge_ort.cc:2369 TryGetProviderInfo_CUDA] "
    b"/onnxruntime_src/onnxruntime/core/session/provider_bridge_ort.cc:1962 onnxruntime::Provider& "
    b"onnxruntime::ProviderLibrary::Get() [ONNXRuntimeError] : 1 : FAIL : Failed to load library "
    b"/home/ncoevoet/.cache/venvs/gpu/lib/python3.12/site-packages/onnxruntime/capi/libonnxruntime_providers_cuda.so with error: "
    b"libcublasLt.so.13: cannot open shared object file: No such file or directory\n\x1b[m\n"
    b"\x1b[0;93m2026-10-21 17:49:09.661683285 [W:onnxruntime:Default, onnxruntime_pybind_state.cc:1295 "
    b"CreateExecutionProviderFactoryInstance] Failed to create CUDAExecutionProvider. Require cuDNN 9.* and CUDA 13.*.\n"
    b"\x1b[m\n"
)
# What the Python layer prints on STDOUT, not stderr, when the provider loads but the session fails at runtime
# (a CUDA runtime the driver is too old for), before it retries on the CPU.
_EP_ERROR_STDOUT = (
    "*************** EP Error ***************\n"
    "EP Error /onnxruntime_src/onnxruntime/core/providers/cuda/cuda_call.cc:122 std::conditional_t<THRW, void, "
    "onnxruntime::common::Status> onnxruntime::CudaCall(ERRTYPE, const char*, const char*, SUCCTYPE, const char*, "
    "const char*, int) [with ERRTYPE = cudaError; bool THRW = true; SUCCTYPE = cudaError; "
    "std::conditional_t<THRW, void, common::Status> = void] CUDA failure 35: CUDA driver version is insufficient "
    "for CUDA runtime version ; GPU=-1 ; hostname=8b1f54bc5fd4 ; file=/onnxruntime_src/onnxruntime/core/providers/"
    "cuda/cuda_execution_provider.cc ; line=336 ; expr=cudaSetDevice(info_.device_id); \n\n"
    " when using ['CUDAExecutionProvider', 'CPUExecutionProvider']\n"
    "Falling back to ['CPUExecutionProvider'] and retrying.\n"
    "****************************************\n"
)


def _session_on_cuda(requested):
    return ["CUDAExecutionProvider", "CPUExecutionProvider"]


def _session_cuda_behind_cpu(requested):
    """CUDA is offered, but the CPU provider is first: the nodes run on the CPU."""
    return ["CPUExecutionProvider", "CUDAExecutionProvider"]


def _session_falls_back_to_cpu(requested):
    """What ONNX Runtime does with a CUDA 13 build beside CUDA 12 libraries: the C++ logger names the library."""
    os.write(2, _CUDA13_LOAD_FAILURE)
    return ["CPUExecutionProvider"]


def _session_prints_ep_error(requested):
    print(_EP_ERROR_STDOUT, end="")
    return ["CPUExecutionProvider"]


def _session_prints_then_raises(requested):
    print(_EP_ERROR_STDOUT, end="")
    raise RuntimeError("Failed to create the session")


def _session_only_warns(requested):
    """A build that does not offer the provider: ONNX Runtime raises a Python warning and writes nothing."""
    warnings.warn("Specified provider 'CUDAExecutionProvider' is not in available provider names."
                  "Available providers: 'AzureExecutionProvider, CPUExecutionProvider'")
    return ["CPUExecutionProvider"]


def _session_raises(requested):
    raise RuntimeError("Failed to create the session: CUDA driver version is insufficient")


def _fake_onnxruntime(available, session, built, cuda_version=_UNSET):
    """onnxruntime stand-in; every InferenceSession built is recorded in ``built``."""
    ort = types.ModuleType("onnxruntime")
    ort.__version__ = "1.26.0"
    ort.get_device = lambda: "GPU"
    ort.get_available_providers = lambda: list(available)
    ort.SessionOptions = types.SimpleNamespace
    if cuda_version is not _UNSET:
        ort.cuda_version = cuda_version

    class InferenceSession:
        def __init__(self, model, sess_options=None, providers=None):
            built.append(list(providers))
            self._providers = session(providers)

        def get_providers(self):
            return self._providers

    ort.InferenceSession = InferenceSession
    return ort


def _fake_onnx():
    """onnx stand-in with just the model-building calls the probe makes."""
    onnx = types.ModuleType("onnx")
    onnx.TensorProto = types.SimpleNamespace(FLOAT=1)

    class _Model:
        ir_version = 0

        def SerializeToString(self):
            return b"model"

    onnx.helper = types.SimpleNamespace(
        make_node=lambda *args, **kwargs: None,
        make_graph=lambda *args, **kwargs: None,
        make_tensor_value_info=lambda *args, **kwargs: None,
        make_opsetid=lambda domain, version: None,
        make_model=lambda graph, opset_imports=None: _Model(),
    )
    return onnx


def _ort_section(out):
    """The text of the ONNX Runtime section of a doctor run."""
    return out.split("  ONNX Runtime\n", 1)[1].split("  VRAM Profile", 1)[0]


class TestDoctorOnnxRuntime:
    """--doctor proves ONNX Runtime really runs on CUDA, not only that the wheel lists the provider (issue #229)."""

    @pytest.fixture(autouse=True)
    def _x86_64_cuda_host(self, monkeypatch):
        monkeypatch.delenv("FACET_DEVICE", raising=False)
        monkeypatch.setattr(platform, "machine", lambda: "x86_64")
        _fake_effective_memory(monkeypatch, 31)

    def _run(self, capsys, tmp_path, ort, *, torch=None, onnx=_UNSET, distributions=None, config=None,
             **doctor_kwargs):
        """Run the doctor and return the ONNX Runtime section's text.

        ``ort`` None leaves the real onnxruntime in place; the string "missing" makes it unimportable.
        """
        modules = {"torch": torch if torch is not None else _make_cuda_torch()}
        if ort == "missing":
            modules["onnxruntime"] = None
        elif ort is not None:
            modules["onnxruntime"] = ort
        modules["onnx"] = _fake_onnx() if onnx is _UNSET else onnx
        config_path = tmp_path / "no.json"
        if config is not None:
            config_path.write_text(json.dumps(config), encoding="utf-8")
        smi_result = types.SimpleNamespace(returncode=0, stdout="565.77\n")
        with mock.patch.dict("sys.modules", modules), \
             mock.patch("diagnostics.subprocess.run", return_value=smi_result), \
             mock.patch("utils.device.detect_c_compiler", return_value="/usr/bin/cc"), \
             mock.patch("utils.onnx_runtime.installed_distributions",
                        return_value=distributions if distributions is not None else ["onnxruntime-gpu"]):
            run_doctor(config_path=str(config_path), db_path=str(tmp_path / "no.db"), **doctor_kwargs)
        return _ort_section(capsys.readouterr().out)

    def test_a_cpu_only_wheel_is_reported_with_the_repair_command_and_builds_no_session(self, capsys, tmp_path):
        built = []
        ort = _fake_onnxruntime(["CPUExecutionProvider"], _session_on_cuda, built)
        section = self._run(capsys, tmp_path, ort, distributions=["onnxruntime"])
        assert "[!!] CUDAExecutionProvider: missing" in section
        assert _REPAIR_COMMAND in section
        assert "CUDA session" not in section
        assert built == []

    def test_a_session_on_cuda_is_the_only_ok_verdict(self, capsys, tmp_path):
        """The version line is information: it prints before the checks that decide whether the install is healthy."""
        built = []
        ort = _fake_onnxruntime(["CUDAExecutionProvider", "CPUExecutionProvider"], _session_on_cuda, built)
        section = self._run(capsys, tmp_path, ort)
        assert "[OK] CUDA session: a test InferenceSession runs on CUDAExecutionProvider" in section
        assert "[--] onnxruntime: 1.26.0 (onnxruntime-gpu)" in section
        assert section.count("[OK]") == 1
        assert "[!!]" not in section
        assert built == [["CUDAExecutionProvider", "CPUExecutionProvider"]]

    def test_a_listed_provider_that_falls_back_reports_ort_own_reason(self, capsys, tmp_path):
        """The CUDA 13 wheel lists the provider beside CUDA 12 torch, then fails to load it."""
        ort = _fake_onnxruntime(["CUDAExecutionProvider", "CPUExecutionProvider"], _session_falls_back_to_cpu, [])
        section = self._run(capsys, tmp_path, ort)
        assert ("[!!] CUDA session: fell back to ['CPUExecutionProvider']: "
                "libcublasLt.so.13: cannot open shared object file: No such file or directory") in section
        assert _REPAIR_COMMAND in section
        assert "[OK] CUDA session" not in section

    def test_the_reason_is_the_cause_not_the_log_line(self, capsys, tmp_path):
        """The line is ANSI-coloured and hides the library name behind 400 characters of log prefix and path."""
        assert _CUDA13_LOAD_FAILURE.index(b"libcublasLt") > 400
        assert b"\x1b[1;31m" in _CUDA13_LOAD_FAILURE
        ort = _fake_onnxruntime(["CUDAExecutionProvider", "CPUExecutionProvider"], _session_falls_back_to_cpu, [])
        section = self._run(capsys, tmp_path, ort)
        assert "provider_bridge_ort.cc" not in section
        assert "[E:onnxruntime" not in section
        assert "site-packages" not in section
        assert "\x1b" not in section

    def test_a_runtime_failure_printed_on_stdout_gives_a_short_reason_and_is_not_echoed(self, capsys, tmp_path):
        """Driver too old for the CUDA runtime: the provider loads, the Python layer prints the reason on stdout."""
        ort = _fake_onnxruntime(["CUDAExecutionProvider", "CPUExecutionProvider"], _session_prints_ep_error, [])
        section = self._run(capsys, tmp_path, ort)
        assert ("[!!] CUDA session: fell back to ['CPUExecutionProvider']: "
                "CUDA failure 35: CUDA driver version is insufficient for CUDA runtime version\n") in section
        assert _REPAIR_COMMAND in section
        assert "EP Error" not in section
        assert "*****" not in section
        assert "cuda_call.cc" not in section

    @pytest.mark.parametrize("session", [_session_prints_ep_error, _session_prints_then_raises])
    def test_the_probe_gives_stdout_back_whether_the_session_returns_or_raises(self, capsys, tmp_path, session):
        ort = _fake_onnxruntime(["CUDAExecutionProvider", "CPUExecutionProvider"], session, [])
        stdout = sys.stdout
        self._run(capsys, tmp_path, ort)
        assert sys.stdout is stdout
        print("after the doctor")
        assert capsys.readouterr().out == "after the doctor\n"

    def test_a_warning_alone_is_reported_when_nothing_reaches_stderr(self, capsys, tmp_path):
        ort = _fake_onnxruntime(["CUDAExecutionProvider", "CPUExecutionProvider"], _session_only_warns, [])
        section = self._run(capsys, tmp_path, ort)
        assert "[!!] CUDA session: fell back to ['CPUExecutionProvider']: Specified provider 'CUDAExecutionProvider'" in section

    def test_the_reporters_end_state_reports_the_build_mismatch_and_the_failed_session(self, capsys, tmp_path):
        """onnxruntime-gpu 1.31.0 beside cu12 torch: still listed as a provider, never loadable."""
        ort = _fake_onnxruntime(["CUDAExecutionProvider", "CPUExecutionProvider"], _session_falls_back_to_cpu, [],
                                cuda_version="13.0")
        section = self._run(capsys, tmp_path, ort)
        assert "[!!] ONNX Runtime CUDA build: onnxruntime is built for CUDA 13.0 but PyTorch uses CUDA 12.6" in section
        assert "[!!] CUDA session: fell back to" in section

    def test_the_clobbered_state_is_reported_from_the_listing_alone(self, capsys, tmp_path):
        """CPU onnxruntime over the GPU wheel: empty cuda_version, no CUDA provider, so no session is built."""
        built = []
        ort = _fake_onnxruntime(["AzureExecutionProvider", "CPUExecutionProvider"], _session_only_warns, built,
                                cuda_version="")
        section = self._run(capsys, tmp_path, ort, distributions=["onnxruntime", "onnxruntime-gpu"])
        assert "ONNX Runtime CUDA build" not in section
        assert "[!!] CUDAExecutionProvider: missing" in section
        assert "[!!] ONNX Runtime packages" in section
        assert built == []

    def test_a_session_that_cannot_be_created_reports_the_error_and_the_repair_command(self, capsys, tmp_path):
        ort = _fake_onnxruntime(["CUDAExecutionProvider", "CPUExecutionProvider"], _session_raises, [])
        section = self._run(capsys, tmp_path, ort)
        assert "[!!] CUDA session: could not be created: Failed to create the session" in section
        assert _REPAIR_COMMAND in section

    def test_the_failed_probe_leaves_stderr_attached_to_the_real_descriptor(self, capsys, tmp_path):
        """The probe redirects descriptor 2 for the length of the session build and must give it back."""
        ort = _fake_onnxruntime(["CUDAExecutionProvider"], _session_raises, [])
        saved = os.dup(2)
        try:
            before = os.fstat(2)
            self._run(capsys, tmp_path, ort)
            after = os.fstat(2)
        finally:
            os.close(saved)
        assert (after.st_dev, after.st_ino) == (before.st_dev, before.st_ino)

    def test_without_the_onnx_package_the_session_is_not_probed(self, capsys, tmp_path):
        built = []
        ort = _fake_onnxruntime(["CUDAExecutionProvider", "CPUExecutionProvider"], _session_on_cuda, built)
        section = self._run(capsys, tmp_path, ort, onnx=None)
        assert "[--] CUDA session: not probed: the 'onnx' package is not installed" in section
        assert "[!!]" not in section
        assert built == []

    def test_a_cpu_runtime_device_never_probes(self, capsys, tmp_path, monkeypatch):
        monkeypatch.setenv("FACET_DEVICE", "cpu")
        built = []
        ort = _fake_onnxruntime(["CUDAExecutionProvider", "CPUExecutionProvider"], _session_raises, built)
        section = self._run(capsys, tmp_path, ort)
        assert "[--] onnxruntime: 1.26.0" in section
        assert "CUDA session" not in section
        assert built == []

    def test_commercial_mode_neither_probes_nor_warns(self, capsys, tmp_path):
        built = []
        ort = _fake_onnxruntime(["CPUExecutionProvider"], _session_raises, built)
        section = self._run(capsys, tmp_path, ort, config={"licensing": {"mode": "commercial"}})
        assert "[--] ONNX Runtime: not used in commercial mode" in section
        assert "[!!]" not in section
        assert built == []

    def test_simulation_never_probes(self, capsys, tmp_path):
        built = []
        ort = _fake_onnxruntime(["CUDAExecutionProvider", "CPUExecutionProvider"], _session_raises, built)
        section = self._run(capsys, tmp_path, ort, simulate_gpu="RTX 5070 Ti", simulate_vram=16.0)
        assert "[--] onnxruntime: 1.26.0" in section
        assert "CUDA session" not in section
        assert "CUDAExecutionProvider: missing" not in section
        assert built == []

    @pytest.mark.parametrize("ort_cuda", ["13.0", "11.8"])
    def test_a_different_cuda_major_is_reported_without_a_gpu(self, capsys, tmp_path, ort_cuda):
        ort = _fake_onnxruntime(["CPUExecutionProvider"], _session_on_cuda, [], cuda_version=ort_cuda)
        section = self._run(capsys, tmp_path, ort)
        assert f"[!!] ONNX Runtime CUDA build: onnxruntime is built for CUDA {ort_cuda} but PyTorch uses CUDA 12.6" in section

    @pytest.mark.parametrize("ort_cuda", ["", _UNSET, "12.2"])
    def test_an_unknown_or_matching_cuda_major_is_not_a_mismatch(self, capsys, tmp_path, ort_cuda):
        """The CPU wheel has an empty cuda_version and an old build has none."""
        ort = _fake_onnxruntime(["CPUExecutionProvider"], _session_on_cuda, [], cuda_version=ort_cuda)
        assert "ONNX Runtime CUDA build" not in self._run(capsys, tmp_path, ort)

    def test_both_distributions_installed_is_a_warning_with_a_fix(self, capsys, tmp_path):
        ort = _fake_onnxruntime(["CPUExecutionProvider"], _session_on_cuda, [])
        section = self._run(capsys, tmp_path, ort, distributions=["onnxruntime", "onnxruntime-gpu"])
        assert "[!!] ONNX Runtime packages: onnxruntime and onnxruntime-gpu are both installed" in section
        assert _REPAIR_COMMAND in section

    def test_both_distributions_installed_never_print_a_green_version_line(self, capsys, tmp_path):
        """'[OK] onnxruntime: 1.31.0 (onnxruntime, onnxruntime-gpu)' above the warning that says it is broken."""
        ort = _fake_onnxruntime(["CPUExecutionProvider"], _session_on_cuda, [])
        section = self._run(capsys, tmp_path, ort, distributions=["onnxruntime", "onnxruntime-gpu"])
        assert "[--] onnxruntime: 1.26.0 (onnxruntime, onnxruntime-gpu)" in section
        assert "[OK]" not in section

    def test_both_distributions_with_a_cpu_torch_get_the_cpu_fix(self, capsys, tmp_path):
        cpu_torch = _make_mock_torch_module()
        cpu_torch.__version__ = "2.6.0+cpu"
        cpu_torch.version = types.SimpleNamespace(cuda=None)
        cpu_torch.cuda = types.SimpleNamespace(is_available=lambda: False)
        cpu_torch.backends = types.SimpleNamespace(cudnn=types.SimpleNamespace(version=lambda: None))
        ort = _fake_onnxruntime(["CPUExecutionProvider"], _session_on_cuda, [])
        section = self._run(capsys, tmp_path, ort, torch=cpu_torch,
                            distributions=["onnxruntime", "onnxruntime-gpu"])
        assert "[!!] ONNX Runtime packages" in section
        assert _CPU_REPAIR_COMMAND in section
        assert "onnxruntime-gpu>=" not in section

    def test_an_installed_but_unimportable_runtime_is_a_broken_install_with_a_fix(self, capsys, tmp_path):
        section = self._run(capsys, tmp_path, "missing", distributions=["onnxruntime-gpu"])
        assert "[!!] onnxruntime: installed (onnxruntime-gpu) but cannot be imported" in section
        assert _REPAIR_COMMAND in section

    def test_an_empty_namespace_package_is_a_broken_install_not_a_working_one(self, capsys, tmp_path):
        """What `pip uninstall onnxruntime` leaves beside a recorded onnxruntime-gpu: the import succeeds, empty."""
        namespace = types.ModuleType("onnxruntime")
        section = self._run(capsys, tmp_path, namespace, distributions=["onnxruntime-gpu"])
        assert ("[!!] onnxruntime: installed (onnxruntime-gpu) but cannot be imported: "
                "module 'onnxruntime' has no attribute 'InferenceSession'") in section
        assert _REPAIR_COMMAND in section
        assert "[OK] onnxruntime" not in section
        assert "CUDA session" not in section

    def test_an_empty_namespace_package_without_a_distribution_is_not_installed(self, capsys, tmp_path):
        section = self._run(capsys, tmp_path, types.ModuleType("onnxruntime"), distributions=[])
        assert "[!!] onnxruntime: NOT INSTALLED" in section

    def test_no_runtime_at_all_is_not_installed_not_broken(self, capsys, tmp_path):
        section = self._run(capsys, tmp_path, "missing", distributions=[])
        assert "[!!] onnxruntime: NOT INSTALLED" in section
        assert "cannot be imported" not in section

    def test_a_rocm_torch_has_no_cuda_version_so_nothing_is_advised_or_probed(self, capsys, tmp_path):
        rocm_torch = _make_cuda_torch()
        rocm_torch.version = types.SimpleNamespace(cuda=None)
        built = []
        ort = _fake_onnxruntime(["CUDAExecutionProvider", "CPUExecutionProvider"], _session_on_cuda, built)
        section = self._run(capsys, tmp_path, ort, torch=rocm_torch)
        assert "[--] ONNX Runtime CUDA: not applicable" in section
        assert "pip install" not in section
        assert built == []

    def test_aarch64_gets_an_explanation_instead_of_an_impossible_range(self, capsys, tmp_path, monkeypatch):
        monkeypatch.setattr(platform, "machine", lambda: "aarch64")
        ort = _fake_onnxruntime(["CPUExecutionProvider"], _session_on_cuda, [])
        section = self._run(capsys, tmp_path, ort)
        assert "[!!] CUDAExecutionProvider: missing" in section
        assert "no onnxruntime-gpu wheel built for CUDA 12 exists for aarch64" in section
        assert "<1.27" not in section

    def test_only_a_session_that_puts_cuda_first_counts_as_running_on_cuda(self, capsys, tmp_path):
        """A session listing CUDA behind the CPU provider runs its nodes on the CPU: ``in`` is not the verdict."""
        ort = _fake_onnxruntime(["CUDAExecutionProvider", "CPUExecutionProvider"], _session_cuda_behind_cpu, [])
        section = self._run(capsys, tmp_path, ort)
        assert "[!!] CUDA session: fell back to ['CPUExecutionProvider', 'CUDAExecutionProvider']" in section
        assert "[OK] CUDA session" not in section
        assert _REPAIR_COMMAND in section

    def test_a_cuda_11_torch_is_told_why_no_gpu_build_applies_and_gets_the_cpu_repair(self, capsys, tmp_path):
        cuda11 = _make_cuda_torch()
        cuda11.version = types.SimpleNamespace(cuda="11.8")
        ort = _fake_onnxruntime(["CPUExecutionProvider"], _session_on_cuda, [])
        section = self._run(capsys, tmp_path, ort, torch=cuda11, distributions=["onnxruntime"])
        assert "[!!] CUDAExecutionProvider: missing" in section
        assert "cuDNN 9" in section
        assert _CPU_REPAIR_COMMAND in section
        assert "onnxruntime-gpu>=" not in section

    def test_an_unexpected_failure_in_the_section_is_one_warning_and_the_doctor_carries_on(self, capsys, tmp_path):
        with mock.patch("diagnostics._report_onnx_runtime", side_effect=RuntimeError("boom")):
            section = self._run(capsys, tmp_path, None)
        assert [line for line in section.splitlines() if "[!!]" in line] == [
            "  [!!] ONNX Runtime check: failed unexpectedly: boom"]


_OPENCV_FIX = ('pip uninstall -y opencv-python opencv-python-headless && '
               'pip install --no-deps "opencv-python-headless==5.0.0.93"')
_LIBGL_ERROR = "libGL.so.1: cannot open shared object file: No such file or directory"


def _opencv_section(out):
    """The text of the OpenCV section of a doctor run."""
    return out.split("  OpenCV\n", 1)[1].split("  ONNX Runtime\n", 1)[0]


class TestDoctorOpenCV:
    """--doctor reports cv2 and the OpenCV distributions behind it: the GUI wheel fails to import without libGL."""

    def _run(self, capsys, tmp_path, monkeypatch, cv2, distributions, *, config=None):
        """Run the doctor and return the OpenCV section's text.

        ``cv2`` is the module ``import cv2`` yields, or an exception it raises. ``distributions`` is the
        ``{name: version}`` pip metadata knows, so a missing name raises ``PackageNotFoundError``.
        """
        real_import_module = importlib.import_module
        real_version = importlib.metadata.version

        def import_module(name, *args, **kwargs):
            if name == "cv2":
                if isinstance(cv2, Exception):
                    raise cv2
                return cv2
            return real_import_module(name, *args, **kwargs)

        def version(name):
            if name.startswith("opencv-python"):
                if name not in distributions:
                    raise importlib.metadata.PackageNotFoundError(name)
                return distributions[name]
            return real_version(name)

        monkeypatch.delenv("FACET_DEVICE", raising=False)
        monkeypatch.setattr(importlib, "import_module", import_module)
        monkeypatch.setattr(importlib.metadata, "version", version)
        config_path = tmp_path / "no.json"
        if config is not None:
            config_path.write_text(json.dumps(config), encoding="utf-8")
        with mock.patch.dict("sys.modules", {"torch": None}):
            run_doctor(config_path=str(config_path), db_path=str(tmp_path / "no.db"))
        self.output = capsys.readouterr().out
        return _opencv_section(self.output)

    @staticmethod
    def _cv2(version="5.0.0"):
        module = types.ModuleType("cv2")
        module.__version__ = version
        return module

    @pytest.mark.parametrize("distributions, shown", [
        ({"opencv-python-headless": "5.0.0.93"}, "opencv-python-headless"),
        ({"opencv-python": "5.0.0.93"}, "opencv-python"),
    ])
    def test_a_cv2_that_imports_from_one_distribution_is_ok(self, capsys, tmp_path, monkeypatch, distributions, shown):
        section = self._run(capsys, tmp_path, monkeypatch, self._cv2(), distributions)
        assert f"[OK] cv2: 5.0.0 ({shown})" in section
        assert "[!!]" not in section

    def test_both_distributions_with_a_working_import_are_information_not_a_warning(self, capsys, tmp_path,
                                                                                    monkeypatch):
        """The Docker images ship both, with libgl1: nothing is broken, so nothing may say so."""
        section = self._run(capsys, tmp_path, monkeypatch, self._cv2(),
                            {"opencv-python": "5.0.0.93", "opencv-python-headless": "5.0.0.93"})
        assert "[--] cv2: 5.0.0 (opencv-python, opencv-python-headless)" in section
        assert "[--] OpenCV packages: both are installed and share cv2/; the one installed last provides it" in section
        assert "[!!]" not in section
        assert "[OK]" not in section
        assert "Fix:" not in section

    def test_a_cv2_that_imports_without_any_distribution_metadata_says_so(self, capsys, tmp_path, monkeypatch):
        section = self._run(capsys, tmp_path, monkeypatch, self._cv2(), {})
        assert "[OK] cv2: 5.0.0 (distribution unknown)" in section

    def test_the_libgl_failure_is_a_warning_with_the_headless_repair(self, capsys, tmp_path, monkeypatch):
        section = self._run(capsys, tmp_path, monkeypatch, ImportError(_LIBGL_ERROR),
                            {"opencv-python": "5.0.0.93", "opencv-python-headless": "5.0.0.93"})
        assert f"[!!] cv2: cannot be imported: ImportError: {_LIBGL_ERROR}" in section
        assert f"Fix: {_OPENCV_FIX}" in section
        assert "[OK]" not in section

    @pytest.mark.parametrize("distributions", [
        {"opencv-python": "5.0.0.93"},
        {"opencv-python-headless": "5.0.0.93"},
        {"opencv-python": "4.9.0.80", "opencv-python-headless": "5.0.0.93"},
    ])
    def test_the_repair_pins_the_installed_version_preferring_the_headless_one(self, capsys, tmp_path, monkeypatch,
                                                                                distributions):
        section = self._run(capsys, tmp_path, monkeypatch, ImportError(_LIBGL_ERROR), distributions)
        assert f"Fix: {_OPENCV_FIX}" in section

    def test_with_no_metadata_the_repair_is_a_plain_headless_install(self, capsys, tmp_path, monkeypatch):
        section = self._run(capsys, tmp_path, monkeypatch, ImportError("No module named 'cv2'"), {})
        assert "[!!] cv2: cannot be imported: ImportError: No module named 'cv2'" in section
        assert "Fix: pip install opencv-python-headless" in section
        assert "uninstall" not in section
        assert "--no-deps" not in section

    def test_an_empty_namespace_package_is_a_broken_install_not_a_working_one(self, capsys, tmp_path, monkeypatch):
        """GUI build over the headless one, then the headless one uninstalled, leaves only cv2/qt/: it imports, empty."""
        section = self._run(capsys, tmp_path, monkeypatch, types.ModuleType("cv2"),
                            {"opencv-python-headless": "5.0.0.93"})
        assert "[!!] cv2: cannot be imported: module 'cv2' has no attribute '__version__'" in section
        assert f"Fix: {_OPENCV_FIX}" in section
        assert "[OK]" not in section

    def test_commercial_mode_checks_opencv_too(self, capsys, tmp_path, monkeypatch):
        """OpenCV is core: requirements.txt installs it in every mode."""
        section = self._run(capsys, tmp_path, monkeypatch, ImportError(_LIBGL_ERROR),
                            {"opencv-python": "5.0.0.93"}, config={"licensing": {"mode": "commercial"}})
        assert "[!!] cv2: cannot be imported" in section
        assert f"Fix: {_OPENCV_FIX}" in section

    def test_an_unexpected_failure_in_the_section_is_one_warning_and_the_doctor_carries_on(self, capsys, tmp_path,
                                                                                           monkeypatch):
        with mock.patch("diagnostics._report_opencv", side_effect=RuntimeError("boom")):
            section = self._run(capsys, tmp_path, monkeypatch, self._cv2(), {})
        assert [line for line in section.splitlines() if "[!!]" in line] == [
            "  [!!] OpenCV check: failed unexpectedly: boom"]
        assert "  ONNX Runtime\n" in self.output
        assert "  Config / Database\n" in self.output


class TestCapturedStderrFd:
    def test_the_temp_file_is_closed_when_the_descriptor_cannot_be_duplicated(self, monkeypatch):
        import diagnostics
        opened = []
        real_temporary_file = diagnostics.tempfile.TemporaryFile

        def tracking_temporary_file():
            handle = real_temporary_file()
            opened.append(handle)
            return handle

        def refuse(fd):
            raise OSError("too many open files")

        monkeypatch.setattr(diagnostics.tempfile, "TemporaryFile", tracking_temporary_file)
        monkeypatch.setattr(diagnostics.os, "dup", refuse)
        with diagnostics._captured_stderr_fd() as captured:
            pass
        assert captured == []
        assert len(opened) == 1
        assert opened[0].closed

    def test_the_block_runs_uncaptured_when_there_is_no_temp_file(self, monkeypatch):
        import diagnostics

        def refuse():
            raise OSError("no space left on device")

        monkeypatch.setattr(diagnostics.tempfile, "TemporaryFile", refuse)
        ran = []
        with diagnostics._captured_stderr_fd() as captured:
            ran.append(True)
        assert ran == [True]
        assert captured == []


class TestVerifyOnnxRuntime:
    """install.sh's final check: the doctor's real CUDA session, with 'could not run' kept apart from 'not on CUDA'."""

    def _verify(self, capsys, ort, *, torch=None, onnx=_UNSET, distributions=None):
        import diagnostics
        modules = {"torch": torch if torch is not None else _make_cuda_torch(),
                   "onnx": _fake_onnx() if onnx is _UNSET else onnx}
        if ort == "missing":
            modules["onnxruntime"] = None
        else:
            modules["onnxruntime"] = ort
        with mock.patch.dict("sys.modules", modules), \
             mock.patch("utils.onnx_runtime.installed_distributions",
                        return_value=distributions if distributions is not None else ["onnxruntime-gpu"]):
            code = diagnostics.verify_onnx_runtime()
        return code, capsys.readouterr().out

    @staticmethod
    def _no_gpu_torch():
        torch = _make_cuda_torch()
        torch.cuda.is_available = lambda: False
        return torch

    def test_a_session_on_cuda_is_the_only_clean_pass(self, capsys):
        built = []
        ort = _fake_onnxruntime(["CUDAExecutionProvider", "CPUExecutionProvider"], _session_on_cuda, built)
        code, out = self._verify(capsys, ort)
        assert code == 0
        assert out == "onnxruntime-gpu 1.26.0: a CUDA test session runs on CUDAExecutionProvider\n"
        assert built == [["CUDAExecutionProvider", "CPUExecutionProvider"]]

    def test_a_listed_provider_that_falls_back_is_not_on_cuda(self, capsys):
        """The case a provider listing cannot see: CUDA 13 wheel beside CUDA 12 libraries."""
        ort = _fake_onnxruntime(["CUDAExecutionProvider", "CPUExecutionProvider"], _session_falls_back_to_cpu, [])
        code, out = self._verify(capsys, ort)
        assert code == 1
        assert "the CUDA test session fell back to ['CPUExecutionProvider']: libcublasLt.so.13" in out
        assert _REPAIR_COMMAND in out

    def test_cuda_behind_the_cpu_provider_is_not_on_cuda(self, capsys):
        ort = _fake_onnxruntime(["CUDAExecutionProvider", "CPUExecutionProvider"], _session_cuda_behind_cpu, [])
        code, out = self._verify(capsys, ort)
        assert code == 1
        assert "fell back to ['CPUExecutionProvider', 'CUDAExecutionProvider']" in out

    def test_without_a_gpu_visible_to_torch_only_the_listing_is_checked_and_it_says_so(self, capsys):
        built = []
        ort = _fake_onnxruntime(["CUDAExecutionProvider", "CPUExecutionProvider"], _session_falls_back_to_cpu, built)
        code, out = self._verify(capsys, ort, torch=self._no_gpu_torch())
        assert code == 3
        assert "onnxruntime-gpu 1.26.0, CUDAExecutionProvider listed" in out
        assert "no CUDA session was created: PyTorch sees no GPU" in out
        assert built == []

    def test_without_the_onnx_package_only_the_listing_is_checked_and_it_says_so(self, capsys):
        ort = _fake_onnxruntime(["CUDAExecutionProvider", "CPUExecutionProvider"], _session_on_cuda, [])
        code, out = self._verify(capsys, ort, onnx=None)
        assert code == 3
        assert "the 'onnx' package is not installed" in out

    def test_a_cpu_only_wheel_is_not_on_cuda_even_without_a_gpu(self, capsys):
        ort = _fake_onnxruntime(["CPUExecutionProvider"], _session_on_cuda, [])
        code, out = self._verify(capsys, ort, torch=self._no_gpu_torch())
        assert code == 1
        assert "does not offer CUDAExecutionProvider" in out
        assert _REPAIR_COMMAND in out

    def test_both_distributions_installed_are_not_on_cuda(self, capsys):
        ort = _fake_onnxruntime(["CUDAExecutionProvider", "CPUExecutionProvider"], _session_on_cuda, [])
        code, out = self._verify(capsys, ort, distributions=["onnxruntime", "onnxruntime-gpu"])
        assert code == 1
        assert "expected onnxruntime-gpu alone" in out

    def test_an_unimportable_onnxruntime_is_not_on_cuda(self, capsys):
        code, out = self._verify(capsys, types.ModuleType("onnxruntime"))
        assert code == 1
        assert "onnxruntime cannot be imported" in out
        assert "InferenceSession" in out

    def test_a_session_that_cannot_be_built_is_the_check_failing_not_a_verdict(self, capsys):
        ort = _fake_onnxruntime(["CUDAExecutionProvider", "CPUExecutionProvider"], _session_raises, [])
        code, out = self._verify(capsys, ort)
        assert code == 2
        assert "RuntimeError: Failed to create the session" in out
        assert "fell back" not in out

    def test_a_torch_that_cannot_be_imported_is_the_check_failing_not_a_verdict(self, capsys):
        ort = _fake_onnxruntime(["CUDAExecutionProvider", "CPUExecutionProvider"], _session_on_cuda, [])
        import diagnostics
        with mock.patch.dict("sys.modules", {"torch": None, "onnxruntime": ort}):
            code = diagnostics.verify_onnx_runtime()
        assert code == 2
        assert "ModuleNotFoundError" in capsys.readouterr().out


class TestProbeReason:
    """The one-line reason extracted from what a failed CUDA session left on the three output channels."""

    LOAD_ERROR = "libcublasLt.so.13: cannot open shared object file: No such file or directory"

    def test_escape_codes_inside_the_line_are_stripped_before_the_cause_is_cut_out(self):
        from diagnostics import _probe_reason
        line = ("\x1b[1;31m" + "x" * 450 + " Failed to load library /p/libonnxruntime_providers_cuda.so with error: "
                "\x1b[0;93m" + self.LOAD_ERROR + "\x1b[m")
        assert _probe_reason([line]) == self.LOAD_ERROR

    def test_the_library_name_far_into_a_long_line_is_not_cut(self):
        from diagnostics import _probe_reason
        line = "[E:onnxruntime] " + "p" * 600 + " Failed to load library /p.so with error: " + self.LOAD_ERROR
        assert _probe_reason([line]) == self.LOAD_ERROR

    def test_a_load_failure_wins_over_a_runtime_failure_and_a_banner(self):
        from diagnostics import _probe_reason
        lines = ["*************** EP Error ***************", "EP Error ... CUDA failure 35: too old ; GPU=-1",
                 "Failed to load library /p.so with error: " + self.LOAD_ERROR]
        assert _probe_reason(lines) == self.LOAD_ERROR

    def test_a_runtime_failure_keeps_only_the_failure(self):
        from diagnostics import _probe_reason
        lines = ["*************** EP Error ***************",
                 "EP Error /src/cuda_call.cc:122 [with E = cudaError; bool T = true] CUDA failure 35: "
                 "CUDA driver version is insufficient for CUDA runtime version ; GPU=-1 ; line=336"]
        assert _probe_reason(lines) == "CUDA failure 35: CUDA driver version is insufficient for CUDA runtime version"

    def test_nothing_captured_gives_no_reason(self):
        from diagnostics import _probe_reason
        assert _probe_reason(["", "   ", "****"]) == ""


class TestOnnxRuntimeProbeModel:
    """The probe model and session against the real onnx / onnxruntime of the dev venv (CI installs neither)."""

    @pytest.fixture
    def ort(self):
        pytest.importorskip("onnx")
        return pytest.importorskip("onnxruntime")

    def test_the_probe_model_loads_and_runs_on_the_cpu_provider(self, ort):
        import numpy as np

        from diagnostics import _probe_model_bytes
        session = ort.InferenceSession(_probe_model_bytes(), providers=["CPUExecutionProvider"])
        (result,) = session.run(None, {"x": np.array([3.0], dtype=np.float32)})
        assert result.tolist() == [3.0]

    def test_the_probe_model_is_pinned_to_an_ir_and_opset_every_onnxruntime_loads(self, ort):
        """The installed onnx stamps its newest IR version, which an older ONNX Runtime rejects."""
        import onnx

        from diagnostics import _probe_model_bytes
        model = onnx.load_from_string(_probe_model_bytes())
        assert model.ir_version == 8
        assert [(opset.domain, opset.version) for opset in model.opset_import] == [("", 13)]

    def test_asking_a_cpu_only_build_for_cuda_reports_the_fallback_and_why(self, ort):
        if "CUDAExecutionProvider" in ort.get_available_providers():
            pytest.skip("this onnxruntime build lists CUDA; the fallback cannot be observed")
        from diagnostics import _probe_cuda_session
        providers, reason = _probe_cuda_session(ort)
        assert providers == ["CPUExecutionProvider"]
        assert "CUDAExecutionProvider" in reason


class TestDoctorEmbeddingWidthOnAuto:
    """`auto` on an 11.5-14 GiB card now resolves to 12gb (SigLIP, 1152-dim); a library embedded at 768 would silently mix widths."""

    @staticmethod
    def _library(tmp_path, width):
        db = tmp_path / "lib.db"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE photos (path TEXT, clip_embedding BLOB)")
        conn.execute("INSERT INTO photos VALUES ('a', NULL)")
        conn.execute("INSERT INTO photos VALUES ('b', ?)", (b"\0" * (4 * width),))
        conn.commit()
        conn.close()
        return db

    def _doctor(self, capsys, tmp_path, db):
        cfg = tmp_path / "cfg.json"
        cfg.write_text("{}", encoding="utf-8")   # no overrides: vram_profile stays the shipped "auto"
        run_doctor(config_path=str(cfg), db_path=str(db),
                   simulate_gpu="RTX 3060", simulate_vram=11.7)
        return capsys.readouterr().out

    def test_the_resolved_profile_is_printed_and_a_768_library_is_warned_about(self, capsys, tmp_path):
        out = self._doctor(capsys, tmp_path, self._library(tmp_path, 768))
        assert "Resolved profile: 12gb (auto)" in out
        assert "Embedding width" in out and "768-dim" in out and "1152-dim" in out
        assert "vram_profile" in out and "--recompute-embeddings" in out

    def test_a_matching_library_gets_no_warning(self, capsys, tmp_path):
        out = self._doctor(capsys, tmp_path, self._library(tmp_path, 1152))
        assert "Resolved profile: 12gb (auto)" in out
        assert "Embedding width" not in out

    def test_a_missing_or_empty_library_gets_no_warning(self, capsys, tmp_path):
        assert "Embedding width" not in self._doctor(capsys, tmp_path, tmp_path / "absent.db")
        db = tmp_path / "empty.db"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE photos (path TEXT, clip_embedding BLOB)")
        conn.commit()
        conn.close()
        assert "Embedding width" not in self._doctor(capsys, tmp_path, db)

    def test_the_width_is_read_from_one_row_not_a_scan(self):
        import inspect

        from diagnostics import _stored_embedding_dim
        assert "LIMIT 1" in inspect.getsource(_stored_embedding_dim)
