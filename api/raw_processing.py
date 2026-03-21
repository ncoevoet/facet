"""RAW-to-JPEG conversion backends for the download and thumbnail endpoints.

Supports two backends configured via ``viewer.raw_processor.backend``:

- ``rawpy`` (default) — in-process conversion via libraw.
- ``darktable`` — shells out to ``darktable-cli``, honouring XMP sidecars.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from io import BytesIO

from api.config import VIEWER_CONFIG

logger = logging.getLogger(__name__)


def _get_raw_config() -> dict:
    """Read raw_processor config at call time (survives config reloads)."""
    return VIEWER_CONFIG.get('raw_processor', {})


def convert_raw_to_jpeg(file_path: str, quality: int = 96) -> bytes:
    """Convert a RAW file to JPEG bytes using the configured backend.

    Parameters
    ----------
    file_path:
        Absolute path to the RAW file on disk.
    quality:
        JPEG quality (1-100).

    Returns
    -------
    bytes
        The JPEG file contents.

    Raises
    ------
    RuntimeError
        If the configured backend fails (binary not found, conversion error).
    """
    raw_config = _get_raw_config()
    backend = raw_config.get('backend', 'rawpy')
    if backend == 'darktable':
        return _convert_darktable(file_path, quality, raw_config)
    return _convert_rawpy(file_path, quality)


def _convert_rawpy(file_path: str, quality: int) -> bytes:
    """Convert via rawpy/libraw (default backend)."""
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


def _convert_darktable(file_path: str, quality: int, raw_config: dict) -> bytes:
    """Convert via darktable-cli, honouring XMP sidecars."""
    dt_config = raw_config.get('darktable', {})
    executable = dt_config.get('executable', 'darktable-cli')

    # Resolve executable
    resolved = shutil.which(executable) if not os.path.isabs(executable) else executable
    if not resolved or not os.path.isfile(resolved):
        raise RuntimeError(f"darktable-cli not found: {executable}")

    fd, tmp_output = tempfile.mkstemp(suffix='.jpg')
    os.close(fd)
    os.unlink(tmp_output)  # darktable-cli refuses to overwrite existing files

    try:
        cmd: list[str] = [resolved, file_path]

        # XMP sidecar: darktable-cli accepts it as 2nd positional arg
        xmp_path = file_path + '.xmp'
        cmd.append(xmp_path if os.path.isfile(xmp_path) else '')

        cmd.append(tmp_output)

        # Optional flags
        if dt_config.get('hq', True):
            cmd.extend(['--hq', 'true'])

        width = dt_config.get('width')
        if width:
            cmd.extend(['--width', str(int(width))])

        height = dt_config.get('height')
        if height:
            cmd.extend(['--height', str(int(height))])

        extra = dt_config.get('extra_args', [])
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
