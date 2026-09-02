"""Facet diagnostic tool — checks Python, PyTorch, GPU, dependencies, config, and database."""

import importlib.metadata
import logging
import os
import platform
import shutil
import sqlite3
import subprocess
import sys

logger = logging.getLogger("facet.diagnostics")


def _section(title):
    logger.info("=" * 50)
    logger.info("  %s", title)
    logger.info("=" * 50)


def _ok(label, value):
    logger.info("  [OK] %s: %s", label, value)


def _warn(label, value):
    logger.warning("  [!!] %s: %s", label, value)


def _info(label, value):
    logger.info("  [--] %s: %s", label, value)


_CUDA_INDEX_URL = "https://download.pytorch.org/whl/"


def _log_pytorch_reinstall_hint(lead):
    """Print the wheel-index advice, from the one place that knows the indexes.

    Three call sites reach the same dead end by different routes -- a CPU-only
    build, a driver torch cannot use, and a build with no kernels for this card
    -- and all three end with the same two pip commands. They were copies until
    a cu124 -> cu126 bump had to touch each of them separately.
    """
    logger.warning(lead)
    logger.warning("    pip install torch torchvision --index-url %scu128", _CUDA_INDEX_URL)
    logger.warning("  For older GPUs (pre-Blackwell), cu126 may also work:")
    logger.warning("    pip install torch torchvision --index-url %scu126", _CUDA_INDEX_URL)


def _cuda_is_usable(torch_module):
    """True when torch reports CUDA *and* a kernel really runs on this GPU."""
    from utils.device import is_device_available
    return is_device_available("cuda", torch_module=torch_module)


def _report_cuda_arch_mismatch(status):
    """Explain a GPU torch can see but ships no kernels for (issue #119).

    ``torch.cuda.is_available()`` is True here, so every other check would
    read green while the first real tensor op dies with "no kernel image is
    available for execution on the device".
    """
    from utils.device import GPU_UNUSABLE_LABEL, sm_name
    capability = (
        f"{status.capability[0]}.{status.capability[1]} ({sm_name(status.capability)})"
        if status.capability else "unknown"
    )
    _warn(GPU_UNUSABLE_LABEL, status.reason)
    _warn("Device compute capability", capability)
    _warn("PyTorch architectures", ", ".join(status.arch_list) or "unknown")
    logger.warning("  This PyTorch build ships no kernels for your GPU architecture.")
    logger.warning("  Docker — switch to the image built for your card:")
    logger.warning("    ghcr.io/ncoevoet/facet:latest-cuda         Turing through Blackwell, incl. RTX 50-series (sm_75-sm_120)")
    logger.warning("    ghcr.io/ncoevoet/facet:latest-cuda-legacy  Maxwell through Hopper (sm_50-sm_90)")
    _log_pytorch_reinstall_hint("  Bare metal — reinstall PyTorch from the matching CUDA index:")


def run_doctor(config_path=None, db_path=None, simulate_gpu=None, simulate_vram=None):
    """Run full diagnostic report.

    Args:
        config_path: Path to scoring config JSON file
        db_path: Path to database file
        simulate_gpu: Simulate a GPU name (e.g., "RTX 5070 Ti") for testing
        simulate_vram: Simulate VRAM in GB (e.g., 16.0) for testing
    """
    from config.scoring_config import resolve_scoring_config_path
    config_path = resolve_scoring_config_path(config_path)
    db_path = db_path or 'photo_scores_pro.db'
    simulating = simulate_gpu is not None
    torch = None
    selected_device = None
    has_mps = False
    arch_mismatch = None

    if simulating:
        vram_str = f", {simulate_vram:.0f}GB VRAM" if simulate_vram else ""
        logger.info("  [SIM] Simulation mode: %s%s", simulate_gpu, vram_str)

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
    if simulating:
        _info("torch", "skipped (simulation mode)")
        _info("CUDA", "skipped (simulation mode)")
    else:
        try:
            from utils.device import cuda_arch_mismatch, get_device, mps_available
            import torch
            has_mps = mps_available()
            arch_mismatch = cuda_arch_mismatch(torch_module=torch)
            _ok("torch", torch.__version__)
            cuda_version = torch.version.cuda or "None (CPU-only build)"
            if torch.version.cuda:
                _ok("CUDA (compiled)", cuda_version)
            elif has_mps:
                _info("CUDA (compiled)", "not applicable on Apple Metal")
            else:
                _warn("CUDA (compiled)", cuda_version)

            try:
                cudnn = torch.backends.cudnn.version()
                _ok("cuDNN", cudnn)
            except Exception:
                _info("cuDNN", "not available")

            if arch_mismatch is not None:
                _warn("torch.cuda.is_available()",
                      f"True, but no kernel can run on this GPU — {arch_mismatch.reason}")
            elif torch.cuda.is_available():
                _ok("torch.cuda.is_available()", "True")
            elif has_mps:
                _info("torch.cuda.is_available()", "False (using MPS)")
            else:
                _warn("torch.cuda.is_available()", "False")

            if has_mps:
                _ok("Apple Silicon (MPS)", "available")
            else:
                hint = " — Facet will run on CPU on this Mac" if sys.platform == "darwin" else ""
                _info("Apple Silicon (MPS)", f"not available{hint}")
            try:
                selected_device = get_device()
                _ok("Facet runtime device", selected_device)
                if selected_device == 'mps':
                    fallback = os.environ.get('PYTORCH_ENABLE_MPS_FALLBACK', '0')
                    _info("MPS operator fallback", "enabled" if fallback == '1' else "disabled")
            except (RuntimeError, ValueError) as e:
                _warn("Facet runtime device", str(e))
        except ImportError:
            _warn("torch", "NOT INSTALLED")
            logger.warning("  Install PyTorch: pip install torch torchvision")
            torch = None

    # --- GPU ---
    if simulating:
        if simulate_vram is not None:
            _section("GPU (simulated)")
            _ok("Device", f"{simulate_gpu} (simulated)")
            _ok("VRAM", f"{simulate_vram:.1f} GB")
        else:
            # Simulate "driver sees GPU but torch doesn't" scenario
            _section("GPU Troubleshooting")
            _warn("GPU found by driver", f"{simulate_gpu} (simulated)")
            logger.warning("  PyTorch was built without CUDA support for your GPU.")
            logger.warning("  Your PyTorch CUDA version: None (CPU-only)")
            _log_pytorch_reinstall_hint("  Reinstall with the correct CUDA version:")
    elif torch is not None and selected_device == 'mps':
        _section("GPU")
        _ok("Device", "Apple Metal Performance Shaders (MPS)")
        _info("Memory", "unified with system RAM")
        _info("InsightFace", "ONNX Runtime CPU provider")

    elif torch is not None and _cuda_is_usable(torch):
        _section("GPU")
        name = torch.cuda.get_device_name(0)
        props = torch.cuda.get_device_properties(0)
        vram_gb = props.total_memory / (1024 ** 3)
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

        from utils.device import torch_compile_status
        compile_enabled, compile_reason = torch_compile_status()
        if compile_enabled:
            _ok("torch.compile", "enabled (C compiler available)")
        elif os.environ.get('TORCH_COMPILE_DISABLE'):
            _info("torch.compile", "disabled — TORCH_COMPILE_DISABLE is set; eager CUDA inference")
        else:
            _warn("torch.compile", f"disabled — {compile_reason}; eager CUDA inference")
            logger.warning("    This is expected and fine in minimal Docker images; torch.compile is auto-disabled.")

    elif torch is not None and arch_mismatch is not None:
        _section("GPU Troubleshooting")
        _report_cuda_arch_mismatch(arch_mismatch)

    elif torch is not None and not has_mps:
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
                logger.warning("  PyTorch was built without CUDA support for your GPU.")
                logger.warning("  Your PyTorch CUDA version: %s", torch.version.cuda or "None (CPU-only)")
                _log_pytorch_reinstall_hint("  Reinstall with the correct CUDA version:")
            else:
                _info("nvidia-smi", "no GPU found — is a GPU installed?")
        except FileNotFoundError:
            _warn("nvidia-smi", "not found — NVIDIA driver may not be installed")
            logger.warning("  Install the NVIDIA driver for your GPU, then reinstall PyTorch with CUDA.")
        except Exception as e:
            _warn("nvidia-smi", f"error: {e}")

    # --- VRAM Profile ---
    _section("VRAM Profile")
    try:
        from config.scoring_config import ScoringConfig
        profile_vram = simulate_vram if simulating else None
        suggested, vram_gb, msg = ScoringConfig.suggest_vram_profile(vram_gb=profile_vram)
        _ok("Recommended", msg)

        # No os.path.exists guard: an absent override is an install running on
        # the shipped defaults, and ScoringConfig resolves that fine. Guarding
        # on the file dropped the configured profile, the auto note and the
        # mismatch warning on exactly the install whose profile nobody has
        # inspected yet.
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
        ('transformers', 'BiRefNet saliency, SigLIP 2 NaFlex, VLM tagging'),
        ('accelerate', 'VLM tagging (16gb/24gb profiles)'),
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

    # darktable-cli (only checked when configured as RAW processor)
    try:
        from config_resolve import load_resolved
        raw_proc = load_resolved(config_path).get('viewer', {}).get('raw_processor', {})
    except Exception:
        raw_proc = {}

    if raw_proc.get('backend') == 'darktable':
        dt_exec = raw_proc.get('darktable', {}).get('executable', 'darktable-cli')
        dt_path = shutil.which(dt_exec) if not os.path.isabs(dt_exec) else dt_exec
        if dt_path and os.path.isfile(dt_path):
            try:
                result = subprocess.run(
                    [dt_path, '--version'], capture_output=True, text=True, timeout=5,
                )
                version = result.stdout.strip().split('\n')[0] if result.stdout else ''
                _ok("darktable-cli", f"{version} ({dt_path})" if version else dt_path)
            except Exception:
                _ok("darktable-cli", dt_path)
        else:
            _warn("darktable-cli", f"not found ({dt_exec}) — RAW downloads will fail")

    # --- Config & Database ---
    _section("Config / Database")
    from config_resolve import path_is_named
    if os.path.exists(config_path):
        size_kb = os.path.getsize(config_path) / 1024
        _ok("Config", f"{config_path} ({size_kb:.1f} KB)")
    elif path_is_named(config_path):
        # A path a human named cannot be missing by accident, and reading it as
        # "no overrides" is what the rest of the toolchain refuses to do.
        _warn("Config", f"{config_path} was named explicitly but does not exist")
    else:
        _ok("Config", f"no override at {config_path} — running on the shipped defaults")
    try:
        from config.scoring_config import ScoringConfig
        schema_errors = ScoringConfig(config_path, validate=False).validate_schema()
        if not schema_errors:
            _ok("Config schema", "valid")
        else:
            for err in schema_errors[:5]:
                _warn("Config schema", err)
    except Exception as e:
        _warn("Config schema", str(e))

    if os.path.exists(db_path):
        size_mb = os.path.getsize(db_path) / (1024 * 1024)
        _ok("Database", f"{db_path} ({size_mb:.1f} MB)")
        try:
            with sqlite3.connect(db_path) as conn:
                count = conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
            _ok("Photos", f"{count:,}")
        except Exception as e:
            _warn("Database query", str(e))

        try:
            with sqlite3.connect(db_path) as conn:
                rows = conn.execute("PRAGMA quick_check").fetchall()
            if len(rows) == 1 and rows[0][0] == "ok":
                _ok("Integrity", "ok")
            else:
                detail = "; ".join(str(r[0]) for r in rows[:3])
                _warn("Integrity", detail or "corruption detected")
        except Exception as e:
            _warn("Integrity", str(e))

        try:
            from db.info import get_user_version
            from db.schema import SCHEMA_VERSION
            db_version = get_user_version(db_path)
            if db_version == SCHEMA_VERSION:
                _ok("Schema version", str(db_version))
            else:
                _warn("Schema version",
                      f"{db_version} (code expects {SCHEMA_VERSION}) — run database.py to upgrade")
        except Exception as e:
            _warn("Schema version", str(e))

        # --- Fast-path Availability ---
        check_fast_paths(db_path)
    else:
        _info("Database", f"{db_path} not found (will be created on first scan)")


def check_fast_paths(db_path):
    """Probe each perf-critical fast path against the DB on disk.

    Reports the same fast paths /metrics exposes (sqlite-vec, FTS5,
    photo_tags, stats_cache). This is the one-command verification an
    operator can run before deploying — answers "is the production
    deploy going to actually use the intended fast paths?" without
    starting the API.
    """
    _section("Fast-path Availability")

    # sqlite-vec extension installable
    try:
        import sqlite_vec
        vec_version = getattr(sqlite_vec, "__version__", "unknown")
        _ok("sqlite-vec installable", f"v{vec_version}")
        sqlite_vec_module = sqlite_vec
    except ImportError:
        _warn("sqlite-vec installable", "package not installed — /api/search will use NumPy fallback")
        sqlite_vec_module = None

    # Direct DB probes — use a fresh connection so we measure on-disk state,
    # not anything cached by a running API.
    try:
        with sqlite3.connect(db_path) as conn:
            # photos_vec table populated?
            # Extension load can raise NotSupportedError on CPython builds
            # compiled without --enable-loadable-sqlite-extensions (common on
            # Windows/macOS stock binaries). Catch broadly and continue so
            # the photos_fts / photo_tags / stats_cache probes that follow
            # remain independent.
            try:
                if sqlite_vec_module is not None:
                    conn.enable_load_extension(True)
                    sqlite_vec_module.load(conn)
                    conn.enable_load_extension(False)
            except Exception as e:
                _warn("sqlite-vec load", str(e))
            try:
                row = conn.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='photos_vec'"
                ).fetchone()
                if row and row[0]:
                    n = conn.execute("SELECT COUNT(*) FROM photos_vec").fetchone()[0]
                    if n > 0:
                        _ok("photos_vec populated", f"{n:,} embeddings")
                    else:
                        _warn("photos_vec populated", "table exists but empty — run database.py --populate-vec")
                else:
                    _warn("photos_vec populated", "table missing — run database.py --populate-vec")
            except sqlite3.OperationalError as e:
                _warn("photos_vec query", str(e))

            # photos_fts table indexed?
            try:
                row = conn.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='photos_fts'"
                ).fetchone()
                if row and row[0]:
                    n = conn.execute("SELECT COUNT(*) FROM photos_fts").fetchone()[0]
                    _ok("photos_fts indexed", f"{n:,} rows")
                else:
                    _warn("photos_fts indexed", "table missing — run database.py --rebuild-fts")
            except sqlite3.OperationalError as e:
                _warn("photos_fts query", str(e))

            # photo_tags lookup table?
            try:
                row = conn.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='photo_tags'"
                ).fetchone()
                if row and row[0]:
                    n = conn.execute("SELECT COUNT(*) FROM photo_tags").fetchone()[0]
                    if n > 0:
                        _ok("photo_tags populated", f"{n:,} entries")
                    else:
                        _warn(
                            "photo_tags populated",
                            "table exists but empty — run database.py --migrate-tags",
                        )
                else:
                    _warn("photo_tags populated", "table missing — run database.py --migrate-tags")
            except sqlite3.OperationalError as e:
                _warn("photo_tags query", str(e))

            # stats_cache age — read the table directly instead of the
            # in-memory cache (we're not in the API process).
            try:
                row = conn.execute(
                    "SELECT COUNT(*), MAX(strftime('%s','now') - strftime('%s', updated_at)) "
                    "FROM stats_cache"
                ).fetchone()
                if row and row[0]:
                    n, max_age = row[0], row[1] or 0
                    hours = max_age / 3600.0
                    if hours > 5:
                        _info("stats_cache",
                              f"{n} entries, oldest {hours:.1f}h (stale — run database.py --refresh-stats)")
                    else:
                        _ok("stats_cache", f"{n} entries, oldest {hours:.1f}h")
                else:
                    _info("stats_cache", "empty — run database.py --refresh-stats")
            except sqlite3.OperationalError:
                _info("stats_cache", "table missing — run database.py --refresh-stats")
    except sqlite3.Error as e:
        _warn("Fast-path probe", str(e))


def main():
    """Entry point for facet-doctor CLI."""
    import argparse

    from utils.cli_logging import configure_cli_logging
    configure_cli_logging()

    parser = argparse.ArgumentParser(description='Facet diagnostic tool')
    parser.add_argument('--config', type=str, default=None,
                        help='Path to scoring config JSON file')
    parser.add_argument('--db', type=str, default='photo_scores_pro.db',
                        help='Path to database file')
    parser.add_argument('--simulate-gpu', type=str, default=None, metavar='NAME',
                        help='Simulate GPU (e.g., "RTX 5070 Ti")')
    parser.add_argument('--simulate-vram', type=float, default=None, metavar='GB',
                        help='Simulate VRAM in GB (e.g., 16)')
    args = parser.parse_args()
    run_doctor(config_path=args.config, db_path=args.db,
               simulate_gpu=args.simulate_gpu, simulate_vram=args.simulate_vram)


if __name__ == '__main__':
    main()
