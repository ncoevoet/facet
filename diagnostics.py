"""Facet diagnostic tool — checks Python, PyTorch, GPU, dependencies, config, and database."""

import importlib.metadata
import os
import platform
import shutil
import sqlite3
import subprocess
import sys


def _section(title):
    print(f"\n{'=' * 50}")
    print(f"  {title}")
    print(f"{'=' * 50}")


def _ok(label, value):
    print(f"  [OK] {label}: {value}")


def _warn(label, value):
    print(f"  [!!] {label}: {value}")


def _info(label, value):
    print(f"  [--] {label}: {value}")


def run_doctor(config_path=None, db_path=None):
    """Run full diagnostic report."""
    config_path = config_path or 'scoring_config.json'
    db_path = db_path or 'photo_scores_pro.db'

    # --- Python / Platform ---
    _section("Python / Platform")
    _ok("Python", sys.version.split('\n')[0])
    _ok("Platform", platform.platform())

    # --- Facet version ---
    _section("Facet")
    try:
        version = importlib.metadata.version('facet-photo')
        _ok("Version", version)
    except importlib.metadata.PackageNotFoundError:
        _info("Version", "not installed as package (running from source)")

    # --- PyTorch ---
    _section("PyTorch")
    try:
        import torch
        _ok("torch", torch.__version__)
        cuda_version = torch.version.cuda or "None (CPU-only build)"
        if torch.version.cuda:
            _ok("CUDA (compiled)", cuda_version)
        else:
            _warn("CUDA (compiled)", cuda_version)

        try:
            cudnn = torch.backends.cudnn.version()
            _ok("cuDNN", cudnn)
        except Exception:
            _info("cuDNN", "not available")

        if torch.cuda.is_available():
            _ok("torch.cuda.is_available()", "True")
        else:
            _warn("torch.cuda.is_available()", "False")
    except ImportError:
        _warn("torch", "NOT INSTALLED")
        print("\n  Install PyTorch: pip install torch torchvision")
        torch = None

    # --- GPU ---
    if torch is not None and torch.cuda.is_available():
        _section("GPU")
        name = torch.cuda.get_device_name(0)
        props = torch.cuda.get_device_properties(0)
        vram_gb = props.total_mem / (1024 ** 3)
        _ok("Device", name)
        _ok("VRAM", f"{vram_gb:.1f} GB")
        _ok("Compute capability", f"{props.major}.{props.minor}")

        # Driver version via nvidia-smi
        try:
            result = subprocess.run(
                ['nvidia-smi', '--query-gpu=driver_version', '--format=csv,noheader'],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                _ok("Driver", result.stdout.strip())
        except Exception:
            pass

    elif torch is not None:
        _section("GPU Troubleshooting")
        # Check if nvidia-smi sees a GPU even though PyTorch can't use it
        try:
            result = subprocess.run(
                ['nvidia-smi', '--query-gpu=name,driver_version', '--format=csv,noheader'],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                gpu_info = result.stdout.strip()
                _warn("GPU found by driver", gpu_info)
                print()
                print("  !! PyTorch was built without CUDA support for your GPU.")
                print("  !! Your PyTorch CUDA version:", torch.version.cuda or "None (CPU-only)")
                print("  !!")
                print("  !! Reinstall with the correct CUDA version:")
                print("  !!   pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128")
                print("  !!")
                print("  !! For older GPUs (pre-Blackwell), cu124 may also work:")
                print("  !!   pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124")
            else:
                _info("nvidia-smi", "no GPU found — is a GPU installed?")
        except FileNotFoundError:
            _warn("nvidia-smi", "not found — NVIDIA driver may not be installed")
            print("  Install the NVIDIA driver for your GPU, then reinstall PyTorch with CUDA.")
        except Exception as e:
            _warn("nvidia-smi", f"error: {e}")

    # --- VRAM Profile ---
    _section("VRAM Profile")
    try:
        from config.scoring_config import ScoringConfig
        suggested, vram_gb, msg = ScoringConfig.suggest_vram_profile()
        _ok("Recommended", msg)

        if os.path.exists(config_path):
            config = ScoringConfig(config_path, validate=False)
            current = config.get_model_config().get('vram_profile', 'legacy')
            _ok("Configured", current)
            if current == 'auto':
                _info("Note", "auto mode will select the recommended profile at runtime")
            elif current != suggested:
                _warn("Mismatch", f"configured '{current}' but recommended '{suggested}'")
    except Exception as e:
        _warn("Profile detection", str(e))

    # --- Optional Dependencies ---
    _section("Optional Dependencies")
    optional_deps = [
        ('transformers', 'VLM tagging (16gb/24gb profiles)'),
        ('accelerate', 'VLM tagging (16gb/24gb profiles)'),
        ('transparent_background', 'Subject saliency (InSPyReNet)'),
        ('rawpy', 'RAW file support'),
    ]
    for module, purpose in optional_deps:
        try:
            mod = importlib.import_module(module)
            version = getattr(mod, '__version__', 'installed')
            _ok(module, f"{version} — {purpose}")
        except ImportError:
            _info(module, f"not installed — {purpose}")

    # exiftool
    exiftool_path = shutil.which('exiftool')
    if exiftool_path:
        try:
            result = subprocess.run(
                ['exiftool', '-ver'], capture_output=True, text=True, timeout=5,
            )
            _ok("exiftool", f"{result.stdout.strip()} ({exiftool_path})")
        except Exception:
            _ok("exiftool", exiftool_path)
    else:
        _warn("exiftool", "not found in PATH — EXIF extraction will be limited")

    # --- Config & Database ---
    _section("Config / Database")
    if os.path.exists(config_path):
        size_kb = os.path.getsize(config_path) / 1024
        _ok("Config", f"{config_path} ({size_kb:.1f} KB)")
    else:
        _warn("Config", f"{config_path} not found")

    if os.path.exists(db_path):
        size_mb = os.path.getsize(db_path) / (1024 * 1024)
        _ok("Database", f"{db_path} ({size_mb:.1f} MB)")
        try:
            conn = sqlite3.connect(db_path)
            count = conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
            _ok("Photos", f"{count:,}")
            conn.close()
        except Exception as e:
            _warn("Database query", str(e))
    else:
        _info("Database", f"{db_path} not found (will be created on first scan)")

    print()


def main():
    """Entry point for facet-doctor CLI."""
    import argparse
    parser = argparse.ArgumentParser(description='Facet diagnostic tool')
    parser.add_argument('--config', type=str, default=None,
                        help='Path to scoring config JSON file')
    parser.add_argument('--db', type=str, default='photo_scores_pro.db',
                        help='Path to database file')
    args = parser.parse_args()
    run_doctor(config_path=args.config, db_path=args.db)


if __name__ == '__main__':
    main()
