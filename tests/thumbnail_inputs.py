"""Deterministic scan inputs shared by the thumbnail golden capture and its tests.

The goldens in ``tests/fixtures/thumbnail_goldens_master.json`` were written by
driving master's ``save_photos_batch`` over exactly these inputs; the decode-time
thumbnail tests rebuild the same inputs here and compare against that file.
RAW inputs go through a rawpy stand-in (no RAW file is committed), built so every
byte it returns is a pure function of the case name.
"""
import hashlib
import io
import shutil
import sqlite3
import sys
import types
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

from utils import image_loading

FIXTURES = Path(__file__).parent / 'fixtures'
GOLDENS_PATH = FIXTURES / 'thumbnail_goldens_master.json'

DEMOSAIC_SIZE = (2000, 1500)

NONRAW_CASES = {
    'jpeg_exif_rotated': None,
    'heic_gainmap': 'apple_iphone13pro_gainmap.heic',
    'hif_pq': 'canon_eos_r8_hdr_pq.hif',
    'hif_pq_rotated': 'canon_eos_r8_hdr_pq_rotated.hif',
    'hif_sony_sdr': 'sony_a7sm3_sdr.hif',
    'hif_pq_ramp': 'pq_gradient_ramp.hif',
    'jxl': None,
}
RAW_CASES = (
    'raw_preview_usable',          # (i)
    'raw_preview_usable_rotated',  # (i) with LibRaw flip=6
    'raw_preview_too_small',       # (ii)
    'raw_preview_missing',         # (ii)
    'raw_unsupported_fallback',    # (iii)
    'raw_prefer_preview_off',      # (iv)
)
ALL_CASES = tuple(NONRAW_CASES) + RAW_CASES


class LibRawError(Exception):
    pass


class LibRawFileUnsupportedError(LibRawError):
    pass


class LibRawIOError(LibRawError):
    pass


def _gradient(width, height, seed):
    x = np.linspace(0, 255, width, dtype=np.float64)[None, :]
    y = np.linspace(0, 255, height, dtype=np.float64)[:, None]
    r = (x + seed * 37) % 256
    g = (y * 0.8 + seed * 11) % 256
    b = ((x + y) / 2 + seed * 71) % 256
    return np.stack(
        [np.broadcast_to(r, (height, width)), np.broadcast_to(g, (height, width)),
         np.broadcast_to(b, (height, width))], axis=-1).astype(np.uint8)


def gradient_image(width, height, seed=0):
    return Image.fromarray(_gradient(width, height, seed))


def _jpeg_bytes(size, seed):
    buf = io.BytesIO()
    gradient_image(size[0], size[1], seed).save(buf, format='JPEG', quality=90)
    return buf.getvalue()


class _StubRaw:
    def __init__(self, thumb, flip):
        self._thumb = thumb
        self.sizes = types.SimpleNamespace(
            width=DEMOSAIC_SIZE[0], height=DEMOSAIC_SIZE[1], flip=flip)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_thumb(self):
        if isinstance(self._thumb, Exception):
            raise self._thumb
        return self._thumb

    def postprocess(self, **kwargs):
        return _gradient(DEMOSAIC_SIZE[0], DEMOSAIC_SIZE[1], 5)


_RAW_SPECS = {
    'raw_preview_usable': dict(thumb=('jpeg', (1960, 1470), 1), flip=0),
    'raw_preview_usable_rotated': dict(thumb=('jpeg', (1960, 1470), 2), flip=6),
    'raw_preview_too_small': dict(thumb=('jpeg', (320, 240), 3), flip=0),
    'raw_preview_missing': dict(thumb=LibRawError('no thumb'), flip=0),
    'raw_unsupported_fallback': dict(thumb=None, flip=0, unsupported=True),
    'raw_prefer_preview_off': dict(thumb=('jpeg', (1960, 1470), 4), flip=0),
}


def _fallback_preview():
    return gradient_image(1600, 1200, 9)


@contextmanager
def _stub_rawpy(name):
    spec = _RAW_SPECS[name]
    counter = {'opens': 0}
    thumb = spec['thumb']
    if isinstance(thumb, tuple):
        thumb = types.SimpleNamespace(format='jpeg', data=_jpeg_bytes(thumb[1], thumb[2]))
    raw = _StubRaw(thumb, spec['flip'])

    def imread(path):
        counter['opens'] += 1
        if spec.get('unsupported'):
            raise LibRawFileUnsupportedError('floating-point DNG')
        return raw

    stub = types.ModuleType('rawpy')
    stub.imread = imread
    stub.ThumbFormat = types.SimpleNamespace(JPEG='jpeg', BITMAP='bitmap')
    stub.ColorSpace = types.SimpleNamespace(sRGB='srgb')
    stub.LibRawError = LibRawError
    stub.LibRawFileUnsupportedError = LibRawFileUnsupportedError
    stub.LibRawIOError = LibRawIOError
    previous = sys.modules.get('rawpy')
    sys.modules['rawpy'] = stub
    old_timeout = image_loading._decode_timeout
    old_settings = image_loading._raw_decode_settings
    image_loading._decode_timeout = 0.0
    image_loading.configure_raw_decode_profile(
        {'prefer_embedded_preview': name != 'raw_prefer_preview_off'})
    try:
        with mock.patch.object(image_loading, 'extract_exiftool_preview',
                               side_effect=lambda p: _fallback_preview()):
            yield counter
    finally:
        image_loading._decode_timeout = old_timeout
        image_loading._raw_decode_settings = old_settings
        if previous is None:
            sys.modules.pop('rawpy', None)
        else:
            sys.modules['rawpy'] = previous


def _write_nonraw(name, workdir):
    workdir = Path(workdir)
    if name == 'jpeg_exif_rotated':
        path = workdir / 'rotated.jpg'
        img = gradient_image(1200, 800, 6)
        exif = img.getexif()
        exif[0x0112] = 6
        img.save(path, format='JPEG', quality=90, exif=exif)
        return path
    if name == 'jxl':
        import imagecodecs
        path = workdir / 'frame.jxl'
        path.write_bytes(imagecodecs.jpegxl_encode(_gradient(900, 600, 7)))
        return path
    src = FIXTURES / NONRAW_CASES[name]
    path = workdir / src.name
    shutil.copyfile(src, path)
    return path


def jxl_available():
    try:
        import imagecodecs
        return bool(imagecodecs.JPEGXL.available)
    except Exception:
        return False


@contextmanager
def scan_input(name, workdir):
    """Yield ``(path, opens)`` for a case; ``opens`` counts ``rawpy.imread`` calls."""
    if name in RAW_CASES:
        with _stub_rawpy(name) as counter:
            yield Path(workdir) / f'{name}.CR3', counter
    else:
        yield _write_nonraw(name, workdir), {'opens': 0}


def base_result(path):
    """A minimal scored-photo dict with no thumbnail (the scan supplies it)."""
    from tests.test_rescan_preservation import _base_result
    res = _base_result(Path(path).as_posix(), 7.0)
    res.pop('thumbnail', None)
    return res


def make_facet(db_path):
    from db.schema import init_database
    from processing.scorer import Facet
    init_database(db_path)
    facet = Facet.__new__(Facet)
    facet._pending_centroid_persons = set()
    facet.db_path = db_path
    return facet


def stored_thumbnail(db_path, path):
    conn = sqlite3.connect(db_path)
    try:
        blob, version = conn.execute(
            "SELECT thumbnail, render_version FROM photos WHERE path = ?",
            (Path(path).as_posix(),)).fetchone()
    finally:
        conn.close()
    return hashlib.sha256(blob).hexdigest(), version
