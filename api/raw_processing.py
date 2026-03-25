"""RAW-to-JPEG conversion backends for the download and thumbnail endpoints.

- Display (``/image``) always uses rawpy (``convert_raw_to_jpeg``).
- Downloads can use named darktable profiles (``convert_raw_darktable``).
"""

from __future__ import annotations

import asyncio
import functools
import logging
import os
import shutil
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path

from api.config import VIEWER_CONFIG

logger = logging.getLogger(__name__)


def _get_raw_config() -> dict:
    """Read raw_processor config at call time (survives config reloads)."""
    return VIEWER_CONFIG.get('raw_processor', {})


# ---------------------------------------------------------------------------
# Display conversion (always rawpy)
# ---------------------------------------------------------------------------

def convert_raw_to_jpeg(file_path: str, quality: int = 96) -> bytes:
    """Convert a RAW file to JPEG bytes via rawpy/libraw.

    Used by the ``/image`` display endpoint.  Always uses rawpy so that the
    browser preview is independent of any darktable style configuration.
    """
    return _convert_rawpy(file_path, quality)


# ---------------------------------------------------------------------------
# Darktable profile conversion (for downloads only)
# ---------------------------------------------------------------------------

def convert_raw_darktable(file_path: str, profile_name: str, quality: int = 96) -> bytes:
    """Convert a RAW file to JPEG using a named darktable profile (sync).

    Raises ``ValueError`` if the profile is not found in the config.
    Raises ``RuntimeError`` if darktable-cli fails.
    """
    raw_config = _get_raw_config()
    dt_config = raw_config.get('darktable', {})
    profiles = dt_config.get('profiles', [])

    profile = next((p for p in profiles if p.get('name') == profile_name), None)
    if profile is None:
        raise ValueError(f"Unknown darktable profile: {profile_name}")

    return _convert_darktable(file_path, quality, dt_config, profile)


async def convert_raw_darktable_async(file_path: str, profile_name: str, quality: int = 96) -> bytes:
    """Convert a RAW file to JPEG using a named darktable profile (async).

    Non-blocking version that uses asyncio subprocess to avoid blocking
    the FastAPI event loop during darktable-cli execution.
    """
    raw_config = _get_raw_config()
    dt_config = raw_config.get('darktable', {})
    profiles = dt_config.get('profiles', [])

    profile = next((p for p in profiles if p.get('name') == profile_name), None)
    if profile is None:
        raise ValueError(f"Unknown darktable profile: {profile_name}")

    return await _convert_darktable_async(file_path, quality, dt_config, profile)


@functools.lru_cache(maxsize=1)
def is_darktable_available() -> bool:
    """Check whether the configured darktable-cli executable exists."""
    dt_config = _get_raw_config().get('darktable', {})
    executable = dt_config.get('executable', 'darktable-cli')
    resolved = shutil.which(executable) if not os.path.isabs(executable) else executable
    return bool(resolved and os.path.isfile(resolved))


def get_darktable_profiles() -> list[str]:
    """Return the list of configured darktable profile names.

    Returns an empty list when the darktable-cli executable is not found,
    so that download options never advertise unavailable profiles.
    """
    if not is_darktable_available():
        return []
    raw_config = _get_raw_config()
    profiles = raw_config.get('darktable', {}).get('profiles', [])
    return [p['name'] for p in profiles if 'name' in p]


# ---------------------------------------------------------------------------
# Companion RAW detection
# ---------------------------------------------------------------------------

def find_companion_raw(disk_path: str) -> str | None:
    """Find a companion RAW file for a given photo on disk.

    Checks for files with the same stem and any supported RAW extension
    in the same directory.  Returns the absolute path of the first match,
    or ``None`` if no companion RAW exists.

    If *disk_path* is itself a RAW file, returns that path directly.
    """
    from utils.image_loading import RAW_EXTENSIONS

    p = Path(disk_path)
    if p.suffix.lower() in RAW_EXTENSIONS:
        return disk_path

    return _find_companion_raw_cached(p.stem, str(p.parent), RAW_EXTENSIONS)


_companion_raw_cache: dict[tuple[str, str], tuple[float, str | None]] = {}
_COMPANION_RAW_TTL = 300  # 5 minutes
_COMPANION_RAW_MAX = 2048


def _find_companion_raw_cached(stem: str, parent_dir: str, raw_extensions: set[str]) -> str | None:
    import time
    key = (stem, parent_dir)
    now = time.monotonic()
    entry = _companion_raw_cache.get(key)
    if entry and (now - entry[0]) < _COMPANION_RAW_TTL:
        return entry[1]

    parent = Path(parent_dir)
    result: str | None = None
    for ext in raw_extensions:
        for candidate_ext in (ext, ext.upper()):
            candidate = parent / (stem + candidate_ext)
            if candidate.is_file():
                result = str(candidate)
                break
        if result:
            break

    if len(_companion_raw_cache) >= _COMPANION_RAW_MAX:
        _companion_raw_cache.clear()
    _companion_raw_cache[key] = (now, result)
    return result


# ---------------------------------------------------------------------------
# Internal backends
# ---------------------------------------------------------------------------

def _convert_rawpy(file_path: str, quality: int) -> bytes:
    """Convert via rawpy/libraw."""
    import rawpy
    from PIL import Image as PILImage

    with rawpy.imread(file_path) as raw:
        rgb = raw.postprocess(
            use_camera_wb=True,
            no_auto_bright=False,
            output_color=rawpy.ColorSpace.sRGB,
            output_bps=8,
        )
    pil_img = PILImage.fromarray(rgb)
    buffer = BytesIO()
    pil_img.save(buffer, format='JPEG', quality=quality)
    return buffer.getvalue()


def _darktable_path(path: str) -> str:
    """Convert a Windows path for darktable-cli.

    darktable-cli interprets backslashes as escape characters, so internal
    separators are converted to forward slashes.  UNC paths (``\\\\server\\...``)
    keep their ``\\\\`` prefix because ``//server/...`` is not recognised as a
    network path by all Windows subsystems.
    """
    if path.startswith('\\\\'):
        return '\\\\' + path[2:].replace('\\', '/')
    return path.replace('\\', '/')


def _convert_darktable(file_path: str, quality: int, dt_config: dict, profile: dict) -> bytes:
    """Convert via darktable-cli using profile-specific settings."""
    executable = dt_config.get('executable', 'darktable-cli')

    resolved = shutil.which(executable) if not os.path.isabs(executable) else executable
    if not resolved or not os.path.isfile(resolved):
        raise RuntimeError(f"darktable-cli not found: {executable}")

    fd, tmp_output = tempfile.mkstemp(suffix='.jpg')
    os.close(fd)
    os.unlink(tmp_output)  # darktable-cli refuses to overwrite existing files

    try:
        # darktable-cli treats backslashes as escape characters on Windows,
        # so convert paths to forward slashes — but preserve the leading \\
        # for UNC paths (e.g. \\server\share\...) which need it.
        dt_input = _darktable_path(file_path)
        dt_output = _darktable_path(tmp_output)

        cmd: list[str] = [resolved, dt_input]

        # XMP sidecar: darktable-cli accepts it as 2nd positional arg
        xmp_path = file_path + '.xmp'
        cmd.append(_darktable_path(xmp_path) if os.path.isfile(xmp_path) else '')

        cmd.append(dt_output)

        # Profile-specific flags
        if profile.get('hq', True):
            cmd.extend(['--hq', 'true'])

        width = profile.get('width')
        if width:
            cmd.extend(['--width', str(int(width))])

        height = profile.get('height')
        if height:
            cmd.extend(['--height', str(int(height))])

        extra = profile.get('extra_args', [])
        if extra and isinstance(extra, list):
            cmd.extend(str(a) for a in extra)

        # JPEG quality via darktable core conf
        cmd.extend([
            '--core',
            '--conf', f'plugins/imageio/format/jpeg/quality={quality}',
        ])

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"darktable-cli failed (exit {result.returncode}): "
                f"{(result.stderr or result.stdout)[:500]}"
            )

        if not os.path.isfile(tmp_output) or os.path.getsize(tmp_output) == 0:
            raise RuntimeError("darktable-cli produced no output file")

        with open(tmp_output, 'rb') as f:
            return f.read()
    finally:
        if os.path.exists(tmp_output):
            os.unlink(tmp_output)


async def _convert_darktable_async(file_path: str, quality: int, dt_config: dict, profile: dict) -> bytes:
    """Async version of _convert_darktable.

    Uses ``asyncio.to_thread`` to run the blocking darktable-cli subprocess
    off the event loop.  This avoids the ``NotImplementedError`` raised by
    ``asyncio.create_subprocess_exec`` on Windows when the event loop is not
    a ``ProactorEventLoop``.
    """
    return await asyncio.to_thread(_convert_darktable, file_path, quality, dt_config, profile)
