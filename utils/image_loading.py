"""
Image loading utilities for Facet.

Handles RAW (via rawpy/libraw) and JPEG loading with EXIF transpose.
"""

import json
import logging
import os
import re
import struct
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import features as _pil_features

from config.scoring_config import (
    RAW_DECODE_DEFAULTS,
    HDR_PQ_TONEMAP_DEFAULTS,
    merge_hdr_pq_tonemap_settings,
)
from utils._lazy import ensure_cv2 as _ensure_cv2, ensure_pil as _ensure_pil

logger = logging.getLogger("facet.image_loading")

# Register HEIF/HEIC opener with PIL (soft dependency)
_heif_available = False
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    _heif_available = True
except ImportError:
    logger.warning("pillow-heif not installed — HEIF/HEIC files will be skipped")

# AVIF codec availability (soft dependency, native in Pillow >= 11.3). Checked
# eagerly, at import time, for the same reason pillow-heif is registered
# eagerly above rather than through utils/_lazy.py's lazy PIL loader:
# SCANNABLE_IMAGE_EXTENSIONS / WATCHABLE_IMAGE_EXTENSIONS are themselves
# computed at import time, so a lazy check would leave both wrong until the
# first decode. PIL.features.check() warns rather than raises when the AVIF
# codec is missing from the underlying libavif build.
_avif_available = bool(_pil_features.check('avif'))

# All RAW formats supported via rawpy/libraw
RAW_EXTENSIONS = frozenset({'.cr2', '.cr3', '.nef', '.arw', '.raf', '.rw2', '.dng', '.orf', '.srw', '.pef'})

# JPEG stills
JPEG_EXTENSIONS = frozenset({'.jpg', '.jpeg'})

# Every HEIF container extension Facet recognises, whether or not this install can
# decode one. '.hif' is Canon's extension for the HDR PQ render; iPhone writes
# '.heic'. Readers that need to know what the CONTAINER is use this set.
KNOWN_HEIF_EXTENSIONS = frozenset({'.heic', '.heif', '.hif'})

# The subset this install can actually open — empty when pillow-heif is missing.
# Readers that need to know what can be DECODED use this one.
HEIF_EXTENSIONS = KNOWN_HEIF_EXTENSIONS if _heif_available else frozenset()

# PNG/GIF/WebP/BMP/TIFF decode with no optional Pillow plugin, so unlike HEIF/AVIF
# there is no availability gate for any of these five.
PNG_EXTENSIONS = frozenset({'.png'})
GIF_EXTENSIONS = frozenset({'.gif'})
WEBP_EXTENSIONS = frozenset({'.webp'})
BMP_EXTENSIONS = frozenset({'.bmp'})
TIFF_EXTENSIONS = frozenset({'.tif', '.tiff'})

# The single-channel Pillow modes whose samples are 16-bit and therefore need
# scaling down to 8-bit rather than convert('RGB')'s clip. 32-bit 'I' and 'F'
# are excluded on purpose -- see open_nonraw_image.
_SIXTEEN_BIT_MODES = frozenset({'I;16', 'I;16B', 'I;16L'})

# AVIF follows the exact two-tier KNOWN/decodable pattern HEIF uses above: the
# container extension is always known, but the decodable subset is empty on a
# Pillow build without the AVIF codec (native only from Pillow 11.3).
KNOWN_AVIF_EXTENSIONS = frozenset({'.avif'})
AVIF_EXTENSIONS = KNOWN_AVIF_EXTENSIONS if _avif_available else frozenset()

# Every still-image extension the scan collector (facet.py) accepts. HEIF/AVIF
# drop out when their decoder is missing, because a scan would have nothing to
# decode them with.
SCANNABLE_IMAGE_EXTENSIONS = (
    JPEG_EXTENSIONS | HEIF_EXTENSIONS | RAW_EXTENSIONS
    | PNG_EXTENSIONS | GIF_EXTENSIONS | WEBP_EXTENSIONS | BMP_EXTENSIONS
    | TIFF_EXTENSIONS | AVIF_EXTENSIONS
)

# What watch mode observes. Deliberately the KNOWN sets rather than the decodable
# ones: a filesystem event is only a note that the path changed, and dropping
# HEIF/AVIF events on an install missing the matching decoder would mean a
# library that gains the dependency later never sees the files it already holds.
WATCHABLE_IMAGE_EXTENSIONS = (
    JPEG_EXTENSIONS | KNOWN_HEIF_EXTENSIONS | RAW_EXTENSIONS
    | PNG_EXTENSIONS | GIF_EXTENSIONS | WEBP_EXTENSIONS | BMP_EXTENSIONS
    | TIFF_EXTENSIONS | KNOWN_AVIF_EXTENSIONS
)


# A bracket exists to capture highlight headroom in its +EV frames, and an HDR
# panorama is bracketed at every position. Both the camera preview's tone curve
# and the uniform `bright` gain compress those highlights — which is exactly the
# information the user is trying to judge — so a frame of one of these kinds
# renders with neither. A plain 'panorama' is not bracketed and is excluded.
BRACKETED_SEQUENCE_KINDS = frozenset({'bracket', 'hdr_panorama'})

# No gain at all: LibRaw's own output level, the rendering a bracketed frame gets.
FAITHFUL_BRIGHT = 1.0

# LibRaw replaces the camera white level with the frame's own maximum when that
# maximum lands above this fraction of it. Restored only to reproduce the
# pre-fix rendering side by side.
_LIBRAW_AUTO_BRIGHT_MAXIMUM_THR = 0.75

# Smallest embedded preview worth serving: the stored thumbnail's long edge.
DISPLAY_PREVIEW_MIN_LONG_EDGE = 640

_EXIF_ORIENTATION_TAG = 274

# LibRaw sizes.flip -> counter-clockwise degrees that make the frame upright.
_LIBRAW_FLIP_ROTATIONS = {3: 180, 5: 90, 6: 270}

# EXIF Orientation -> PIL Transpose op(s) that make the frame upright. Mirrors
# PIL.ImageOps.exif_transpose's own table; used for the exiftool preview
# fallback, whose bytes carry no EXIF of their own to hand to that helper.
_EXIF_ORIENTATION_TRANSPOSES = {
    2: ('FLIP_LEFT_RIGHT',),
    3: ('ROTATE_180',),
    4: ('FLIP_TOP_BOTTOM',),
    5: ('FLIP_LEFT_RIGHT', 'ROTATE_90'),
    6: ('ROTATE_270',),
    7: ('FLIP_LEFT_RIGHT', 'ROTATE_270'),
    8: ('ROTATE_90',),
}

# LibRaw rejects some Lightroom-merged DNGs (floating-point HDR/panorama
# merges) outright, raising rawpy.LibRawFileUnsupportedError. exiftool can
# still pull the camera-embedded preview those files carry, so the timeout
# and size floor below bound that fallback.
EXIFTOOL_PREVIEW_TIMEOUT_SECONDS = 20
EXIFTOOL_PREVIEW_MIN_LONG_EDGE = 1024

# exiftool -n renders a binary tag as this placeholder; group is captured to
# resolve which group-qualified tag name to pass back to -b.
_EXIFTOOL_BINARY_SIZE_RE = re.compile(r'Binary data (\d+) bytes')
_EXIFTOOL_PREVIEW_TAG_NAMES = ('PreviewImage', 'JpgFromRaw', 'OtherImage')

# --- HDR PQ HEIF -> SDR sRGB tone mapping ---------------------------------
# Canon HDR PQ HEIF (.HIF) stores 10-bit pixels encoded with the SMPTE ST 2084
# (PQ) transfer function and BT.2020 primaries (NCLX: colour_primaries=9,
# transfer_characteristics=16). The matrix field varies — the vendored Canon
# EOS R8 fixture writes matrix_coefficients=1 (BT.709), since an HDR PQ HEIF
# does not have to carry BT.2020 non-constant luminance — so nothing here may
# gate on that field. pillow-heif hands those encoded values straight to us, so
# displaying or scoring them as ordinary sRGB makes every frame look dark and
# washed out.
#
# Pipeline, applied only when the decoder reports PQ (transfer==16):
#   1. PQ EOTF           S -> absolute linear light in nits   (SMPTE ST 2084:2014)
#   2. BT.2020 -> sRGB   primaries, D65 -> D65                 (ITU-R BT.2020 / BT.709)
#   3. scale to 100 nit SDR reference white                    (BT.2408 / ffmpeg)
#   4. Hable filmic tone map                                   (Hable 2010)
#   5. sRGB OETF                                               (IEC 61966-2-1)
#
# Gating is by the decoder's NCLX transfer field, NOT by file extension:
# SDR HEIC (transfer 1/13/17) and HLG (transfer 18) reach the loader with
# is_pq=False and are passed through untouched. A file carrying no NCLX box at
# all is is_pq=False too, so it is treated as ordinary sRGB rather than guessed
# at — that is the Apple case, not an exotic one: an iPhone HDR still is an 8-bit
# SDR base image plus a `...aux:hdrgainmap` auxiliary, a different HDR mechanism
# from PQ entirely, and its base image is already the right thing to display.

# SMPTE ST 2084:2014 section 7 EOTF constants. Signal S in [0,1] -> linear
# light L in nits via  n = S^(1/M2);  L = 10000 * ((n-C1)/(C2-C3*n))^(1/M1).
_PQ_M1 = 0.1593017578125          # 1305/8192
_PQ_M2 = 78.84375                 # 2523/32
_PQ_C1 = 0.8359375                # C3 - C2 + 1
_PQ_C2 = 18.8515625               # 2413/128
_PQ_C3 = 18.6875                  # 2392/128
_PQ_PEAK_NITS = 10000.0           # ST 2084 reference display peak

# Linear BT.2020 -> linear sRGB (BT.709) primaries. Both gamuts share the D65
# white point, so no chromatic-adaptation step is needed; this is the standard
# 3x3 primary-conversion matrix (e.g. Bruce Lindbloom's RGB Working Spaces).
_BT2020_TO_SRGB = np.array([
    [1.660491, -0.5876411, -0.0728499],
    [-0.1245505, 1.1328999, -0.0083494],
    [-0.0181508, -0.1005789, 1.1187297],
], dtype=np.float32)

# SDR reference white in nits. PQ is display-referred (absolute luminance):
# linear light is expressed in units of this 100 nit level (x = nits / 100),
# the nominal SDR peak used by ffmpeg's zscale+tonemap pipeline and a match for
# in-camera HDR-still SDR output. It is NOT the tone-map white point - that is
# measured per image (see _hdr_pq_white_point); normalising at a fixed 100 nit
# white clipped every bright still to pure white. The BT.2408 mastering
# reference of 203 nits looked dark for these stills.
_PQ_SDR_REFERENCE_NITS = 100.0

# Hable filmic (Uncharted 2) tone-map operator:
#   f(x) = (x*(a*x + c*b) + d*e) / (x*(a*x + b) + d*f) - e/f
# Source: John Hable, "Filmic Tonemapping Operators" (2010), section 5.
# Coefficients and the divide-by-hable(peak) normalisation match ffmpeg's
# hable tone-map (libavfilter/vf_tonemap.c), which divides by hable(peak)
# rather than by hable(1).
_HABLE_A, _HABLE_B, _HABLE_C, _HABLE_D, _HABLE_E, _HABLE_F = (
    0.15, 0.50, 0.10, 0.20, 0.02, 0.30)

# ISO/IEC 23001-8 / ITU-T H.273 colour table: transfer_characteristics == 16 is PQ.
_NCLX_PQ_TRANSFER = 16


def _pq_eotf(signal):
    """SMPTE ST 2084:2014 section 7 EOTF: PQ signal in [0,1] -> linear light nits."""
    n = np.clip(signal, 0.0, 1.0) ** (1.0 / _PQ_M2)
    numer = np.maximum(n - _PQ_C1, 0.0)
    denom = _PQ_C2 - _PQ_C3 * n
    return _PQ_PEAK_NITS * (numer / denom) ** (1.0 / _PQ_M1)


def _hable(x):
    return ((x * (_HABLE_A * x + _HABLE_C * _HABLE_B) + _HABLE_D * _HABLE_E)
            / (x * (_HABLE_A * x + _HABLE_B) + _HABLE_D * _HABLE_F)) - _HABLE_E / _HABLE_F


# The decoder hands back RGB at either 8 bits (the PIL plugin's hardcoded
# convert_hdr_to_8bit path) or its native depth (the pillow-heif path used by
# _decode_pq_native, left-shifted to 16 bits by the decoder -- see
# _decode_pq_native for the shift back down). The EOTF therefore has exactly
# ``1 << bit_depth`` possible inputs per channel at whichever depth is in
# play: tabulating it is EXACT, not an approximation, at any depth, and it
# replaces the four frame-sized float temporaries _pq_eotf builds (the power,
# the numerator, the denominator and the result) with one lookup table -- 256
# entries (1 KiB) at 8 bits, 1024 entries (4 KiB) at 10.
_PQ_EOTF_LUTS: dict[int, np.ndarray] = {}


def _pq_eotf_lut(bit_depth):
    """Memoised EOTF table for ``bit_depth``, exact at every code that depth has."""
    lut = _PQ_EOTF_LUTS.get(bit_depth)
    if lut is None:
        size = 1 << bit_depth
        lut = _pq_eotf(np.arange(size, dtype=np.float32) / (size - 1)).astype(np.float32)
        _PQ_EOTF_LUTS[bit_depth] = lut
    return lut


# The pinned 8-bit table, kept as a module-level name because it is exactly
# _pq_eotf_lut(8) -- the table every decode used before this depth-aware form
# existed, and what _tonemap_pq_to_srgb's PIL wrapper still uses today.
_PQ_EOTF_LUT = _pq_eotf_lut(8)


# Pixels per band. Sized for cache rather than for the frame: it is the float32
# INTERMEDIATES that stay band-bound however large the still is, not the peak
# itself. The peak still grows with the frame, at a measured ~6.6 bytes/pixel --
# the uint8 output plus the per-pixel channel maxima the white point reads --
# rather than at the ~8 full-size float32 copies the whole-array form cost.
# Measured against 1 << 20, this is 19-32% faster and ~18% lighter, bit-identical
# out. The native path's uint16 decoder buffer is twice the width of the 8-bit
# one, but it does NOT make the frame more expensive: see open_nonraw_image.
_TONEMAP_BAND_PIXELS = 1 << 16


def _tonemap_band_rows(shape):
    """Rows per band for a frame of ``shape``, at least one."""
    return max(1, _TONEMAP_BAND_PIXELS // max(1, int(shape[1]) * int(shape[2])))


def _band_nits(band, lut=_PQ_EOTF_LUT, shift=0):
    """Absolute-nit linear sRGB for one band of PQ/BT.2020 pixels.

    ``lut`` is sized to the band's own bit depth (defaulting to the 8-bit
    table); ``shift`` maps a wider-than-the-LUT code back down to it (0 when
    the band already IS at the LUT's depth, e.g. the decoder's
    16-bit-shifted 10-bit codes on the native path need >>6). The shift
    happens here, band-sized, rather than on the source array: that array is
    a read-only, non-owning view into the still-open HeifFile on the native
    path (see _decode_pq_native), so an in-place ``>>=`` would raise.
    """
    codes = band >> shift if shift else band
    nits = lut[codes] @ _BT2020_TO_SRGB.T
    np.maximum(nits, 0.0, out=nits)
    return nits


def _banded_white_point(src, wp, band_rows, lut=_PQ_EOTF_LUT, shift=0):
    """:func:`_hdr_pq_white_point` without a frame-sized nits array.

    Returns the same value the whole-frame form does. The white point reads
    nothing but the per-pixel channel maxima, which are a third of the size of
    the nits array that would otherwise have to exist all at once -- and in
    ``fixed`` mode it reads no pixels at all.
    """
    mode = wp.get('mode', 'percentile')
    min_nits = float(wp.get('min_nits', 100.0))
    if mode == 'fixed':
        return max(float(wp.get('fixed_nits', 1000.0)), min_nits)
    if mode == 'max':
        peak = 0.0
        for start in range(0, src.shape[0], band_rows):
            peak = max(peak, float(_band_nits(src[start:start + band_rows], lut, shift).max()))
        return max(peak, min_nits)
    per_pixel_max = np.empty(src.shape[:2], dtype=np.float32)
    for start in range(0, src.shape[0], band_rows):
        stop = min(start + band_rows, src.shape[0])
        np.max(_band_nits(src[start:stop], lut, shift), axis=2, out=per_pixel_max[start:stop])
    percentile = float(np.clip(wp.get('percentile', 99.99), 0.0, 100.0))
    max_nits = float(wp.get('max_nits', 1200.0))
    # overwrite_input: per_pixel_max is our own scratch, and the partition
    # np.percentile does otherwise copies the whole thing a second time.
    white = float(np.percentile(per_pixel_max, percentile, overwrite_input=True))
    return float(np.clip(white, min_nits, max_nits))


def _heif_is_pq(pil_img):
    """True only if the freshly opened HEIF reports PQ via its NCLX profile.

    Gates tone mapping on the decoder's colour metadata, not on the file
    extension: a .heic/.heif/.hif that is SDR (transfer 1/13/17) or HLG (18)
    returns False. A missing NCLX profile also returns False (safe SDR fallback).
    """
    nclx = pil_img.info.get('nclx_profile')
    return bool(nclx) and nclx.get('transfer_characteristics') == _NCLX_PQ_TRANSFER


# --- AVIF colr/nclx parsing -------------------------------------------------
# Pillow's native AVIF plugin exposes no colour metadata at all -- a PQ AVIF's
# ``pil_img.info`` was confirmed in-session to contain no CICP/NCLX field, so
# there is nothing here to read the way _heif_is_pq reads pillow-heif's
# 'nclx_profile'. This walks the ISO/IEC 14496-12 (ISO-BMFF) box tree
# ourselves: ftyp/meta/iprp/ipco/colr is the standard MIAF path to an AVIF's
# CICP colour description, and reading only box headers plus the ~12-byte
# colr body (never mdat, the pixel payload) makes the cost negligible even on
# a large file. This resolves the FIRST colr/nclx box under ipco without
# resolving ipma item-to-property associations, which is correct for the
# common single-primary-item AVIF and a known simplification for a multi-item
# file (e.g. primary + thumbnail with different colour info) -- deliberately
# out of scope, per the locked decision to parse the colr/nclx box ourselves
# rather than implement a full MIAF item-property resolver.

def _iter_bmff_boxes(f, end):
    """Yield ``(box_type, payload_start, box_end)`` for each box in ``[f.tell(), end)``.

    ``size == 1`` means an 8-byte 64-bit largesize follows the header;
    ``size == 0`` means the box extends to ``end``. Malformed or truncated
    input simply stops the walk (empty tail) rather than raising here --
    every caller wraps the whole parse in one try/except and treats any
    structural failure as "not PQ".
    """
    while f.tell() < end:
        pos = f.tell()
        header = f.read(8)
        if len(header) < 8:
            return
        size, box_type = struct.unpack('>I4s', header)
        payload_start = pos + 8
        if size == 1:
            largesize_bytes = f.read(8)
            if len(largesize_bytes) < 8:
                return
            size = struct.unpack('>Q', largesize_bytes)[0]
            payload_start = pos + 16
        elif size == 0:
            size = end - pos
        box_end = pos + size
        if size < (payload_start - pos) or box_end > end:
            return
        yield box_type, payload_start, box_end
        f.seek(box_end)


def _find_bmff_box(f, end, target):
    """Return ``(payload_start, box_end)`` of the first direct child box of type ``target``, or None."""
    for box_type, payload_start, box_end in _iter_bmff_boxes(f, end):
        if box_type == target:
            return payload_start, box_end
    return None


def _avif_nclx_transfer_characteristics(photo_path):
    """Parse an AVIF's colr/nclx box for its transfer_characteristics, or None.

    Walks ``meta`` (a FullBox -- its payload starts 4 bytes in, past
    version+flags) -> ``iprp`` -> ``ipco`` (both plain container boxes, no
    FullBox header) -> the first ``colr`` box whose 4-byte colour_type reads
    b'nclx' (as opposed to b'rICC'/b'prof', an ICC profile this does not
    parse), then unpacks ``>HHH`` for colour_primaries/transfer_characteristics/
    matrix_coefficients and returns the transfer field directly.

    Any structural failure -- box not found, truncated read, malformed size --
    is caught and returns None, the same safe-SDR-fallback semantics
    _heif_is_pq already uses for a missing NCLX profile.
    """
    try:
        with open(photo_path, 'rb') as f:
            f.seek(0, os.SEEK_END)
            file_end = f.tell()
            f.seek(0)

            meta = _find_bmff_box(f, file_end, b'meta')
            if meta is None:
                return None
            meta_start, meta_end = meta
            f.seek(meta_start + 4)  # meta is a FullBox: skip version+flags

            iprp = _find_bmff_box(f, meta_end, b'iprp')
            if iprp is None:
                return None
            iprp_start, iprp_end = iprp
            f.seek(iprp_start)

            ipco = _find_bmff_box(f, iprp_end, b'ipco')
            if ipco is None:
                return None
            ipco_start, ipco_end = ipco
            f.seek(ipco_start)

            for box_type, payload_start, box_end in _iter_bmff_boxes(f, ipco_end):
                if box_type != b'colr':
                    continue
                # An nclx payload is 4 bytes colour_type + 3 x uint16 +
                # a full_range byte. Bounding the read by box_end matters:
                # a colr box declaring size 12 (header + colour_type, no
                # body) would otherwise let f.read(6) spill into the NEXT
                # box's header and return its bytes as a transfer
                # characteristic -- verified to yield 16, forcing the PQ
                # tone map onto an SDR image.
                if payload_start + 10 > box_end:
                    continue
                f.seek(payload_start)
                colour_type = f.read(4)
                if colour_type != b'nclx':
                    continue
                body = f.read(6)
                if len(body) < 6:
                    return None
                _primaries, transfer, _matrix = struct.unpack('>HHH', body)
                return transfer
            return None
    except Exception as ex:
        logger.debug("AVIF colr/nclx parse failed for %s: %s",
                     os.path.basename(str(photo_path)), ex)
        return None


def _avif_is_pq(photo_path):
    """True only if the AVIF's colr/nclx box reports PQ (transfer_characteristics == 16)."""
    return _avif_nclx_transfer_characteristics(photo_path) == _NCLX_PQ_TRANSFER


_SRGB_TOE_THRESHOLD = 0.0031308
_SRGB_TOE_SLOPE = 12.92
_SRGB_GAMMA = 2.4
_SRGB_SHOULDER_SCALE = 1.055
_SRGB_SHOULDER_OFFSET = 0.055


def _srgb_oetf_into(linear):
    """IEC 61966-2-1:1999 section 6.1.5 sRGB OETF, evaluated IN PLACE.

    ``linear`` must be a float ndarray; it is overwritten and returned. The
    obvious ``np.where`` form gathers both branches into full-size temporaries,
    which is what made the tone map's working set scale with the frame rather
    than with the band. ``toe`` and ``scaled`` are both computed before
    ``np.power`` overwrites ``linear`` -- reordering them silently returns the
    shoulder for every toe pixel.
    """
    toe = linear <= _SRGB_TOE_THRESHOLD
    scaled = linear * _SRGB_TOE_SLOPE
    np.clip(linear, 0.0, None, out=linear)
    np.power(linear, 1.0 / _SRGB_GAMMA, out=linear)
    linear *= _SRGB_SHOULDER_SCALE
    linear -= _SRGB_SHOULDER_OFFSET
    np.copyto(linear, scaled, where=toe)
    return linear


def _srgb_oetf(linear):
    """IEC 61966-2-1:1999 section 6.1.5 sRGB opto-electronic transfer function."""
    return _srgb_oetf_into(np.array(linear, dtype=np.float32))


def _hdr_pq_white_point(nits, wp):
    """Per-image display white point in nits (the level mapped to SDR white).

    The decode path calls :func:`_banded_white_point` instead, which returns the
    same number without a frame-sized nits array. This whole-frame form is kept
    as the reference the banded one is asserted equal to, so that equality is a
    test rather than an argument.

    A fixed 100 nit white clips every bright still to pure white: real HDR
    stills peak at hundreds-to-thousands of nits, so the normalising peak is
    measured per image. ffmpeg's tonemap filter does the same via
    ff_determine_signal_peak() (vf_tonemap.c); the percentile mode is the
    MaxCLL-style robust form of that, insensitive to a handful of hot pixels
    (e.g. night-scene lights) that would otherwise drag the whole frame dark.
    """
    mode = wp.get('mode', 'percentile')
    min_nits = float(wp.get('min_nits', 100.0))
    per_pixel_max = nits.max(axis=2)
    if mode == 'fixed':
        return max(float(wp.get('fixed_nits', 1000.0)), min_nits)
    if mode == 'max':
        # Single brightest pixel (strict ffmpeg signal peak); no upper clamp.
        return max(float(per_pixel_max.max()), min_nits)
    # percentile (default): a high percentile of the brightest channel.
    percentile = float(np.clip(wp.get('percentile', 99.99), 0.0, 100.0))
    max_nits = float(wp.get('max_nits', 1200.0))
    white = float(np.percentile(per_pixel_max, percentile))
    return float(np.clip(white, min_nits, max_nits))


def _hdr_pq_tone_map(nits, white_nits, settings):
    """Map absolute-nit linear sRGB to [0,1] linear SDR sRGB.

    Linear light is expressed in units of the 100 nit SDR reference white
    (``x = nits / 100``). The Hable curve is normalised at the per-image white
    point so that white maps to 1 - ``hable(x) / hable(white/100)`` - matching
    ffmpeg's hable branch, which divides by ``hable(peak)`` rather than by
    ``hable(1)`` (vf_tonemap.c).
    """
    method = settings.get('method', 'hable')
    x = nits / _PQ_SDR_REFERENCE_NITS
    w = white_nits / _PQ_SDR_REFERENCE_NITS
    if method == 'clip':
        # Linear normalise + hard clip, no filmic shoulder (reference only).
        return np.clip(x / w, 0.0, 1.0)
    if settings.get('chroma_preserve') == 'max_channel':
        # ffmpeg hue-preserving form: one scale from the brightest channel,
        # applied to all three, so a highlight rolls off together instead of
        # per-channel clipping shifting its hue toward white.
        sig = np.maximum(x.max(axis=2), 1e-6)
        scale = (_hable(np.clip(sig, 0.0, w)) / _hable(w)) / sig
        return np.clip(x * scale[..., None], 0.0, 1.0)
    # per_channel (default): each R/G/B channel rolls off independently.
    # Brighter, at the cost of some hue shift in the brightest highlights.
    return np.clip(_hable(x) / _hable(w), 0.0, 1.0)


def _tonemap_codes_to_srgb(codes, lut, shift, settings):
    """Tone-map an array of PQ/BT.2020 codes at any depth to 8-bit sRGB.

    ``codes`` is whatever the decoder produced (8-bit PIL array or the
    16-bit-shifted native-depth array from :func:`_decode_pq_native`); ``lut``
    and ``shift`` describe how to read it (see :func:`_band_nits`). This is
    the shared body behind both :func:`_tonemap_pq_to_srgb` (the 8-bit PIL
    wrapper existing callers use) and the native decode path.
    """
    band_rows = _tonemap_band_rows(codes.shape)

    # Pass 1: the per-image white point. It needs the whole frame's channel
    # maxima before any pixel can be mapped, so it gets its own banded sweep
    # rather than forcing the nits array to exist all at once.
    white_nits = _banded_white_point(codes, settings.get('white_point', {}), band_rows, lut, shift)

    # Pass 2: map band by band. Every intermediate is band-sized, so the peak
    # working set is the band plus the frame-sized decoder buffer and our
    # uint8 output -- not the eight float32 copies of the frame the
    # whole-array form built.
    out = np.empty(codes.shape, dtype=np.uint8)
    for start in range(0, codes.shape[0], band_rows):
        stop = min(start + band_rows, codes.shape[0])
        # 1. PQ EOTF (SMPTE ST 2084) via the exact depth-sized table, then
        #    BT.2020 -> sRGB primaries, keeping absolute nits.
        # 2. Filmic tone map in linear light at the per-image white point.
        mapped = _hdr_pq_tone_map(_band_nits(codes[start:stop], lut, shift), white_nits, settings)
        np.clip(mapped, 0.0, 1.0, out=mapped)
        # 3. sRGB OETF (IEC 61966-2-1), round and quantise to 8-bit.
        _srgb_oetf_into(mapped)
        mapped *= 255.0
        mapped += 0.5
        np.clip(mapped, 0, 255, out=mapped)
        out[start:stop] = mapped.astype(np.uint8)
    return out


def _tonemap_pq_to_srgb(pil_img, settings=None):
    """Tone-map an 8-bit PQ/BT.2020 RGB PIL image to an SDR sRGB PIL image.

    Only called once the freshly opened image has been confirmed as PQ (NCLX
    transfer 16), so SDR/HLG frames never reach this. Behaviour is tunable
    through the ``hdr_pq_tonemap`` config block; setting ``enabled: false``
    returns the decoder's raw PQ values untouched.

    This is the 8-bit path: pillow-heif's PIL plugin hardcodes
    ``convert_hdr_to_8bit=True``, so ``pil_img`` never carries more than 256
    codes per channel. :func:`_decode_pq_native` calls
    :func:`_tonemap_codes_to_srgb` directly with the decoder's native depth
    instead of going through here.
    """
    Image, _ = _ensure_pil()
    if settings is None:
        settings = get_hdr_pq_tonemap_settings()
    if not settings.get('enabled', True):
        return pil_img

    src = np.asarray(pil_img)
    out = _tonemap_codes_to_srgb(src, _pq_eotf_lut(8), 0, settings)
    return Image.fromarray(out, 'RGB')


def _decode_pq_native(photo, settings):
    """Tone-map ``photo`` from its native decoded bit depth, or None on any failure.

    pillow-heif's PIL plugin hardcodes ``convert_hdr_to_8bit=True`` with no
    flag to disable it, so this calls ``pillow_heif.open_heif`` directly
    instead of going through PIL. The decoder reports mode ``RGB;16`` with the
    codes left-shifted to 16 bits (a 10-bit code ``C`` arrives as ``C << 6`` --
    the Canon fixture's max 10-bit code 907 comes back as 58048); ``_band_nits``
    shifts it back down per band rather than here, because ``np.asarray(img)``
    is a read-only, non-owning VIEW into ``img``'s own buffer and cannot be
    modified in place.

    ``img`` -- the ``HeifFile`` -- is kept referenced for the whole tone map:
    that view's buffer dies with it, and letting it be collected early
    produces silently garbled pixels rather than an error.

    Any failure -- pillow-heif missing or erroring, a corrupt file, an
    SDR-depth (<=8 bit) frame slipping through -- returns None so the caller
    falls back to today's 8-bit path; the exception is logged at debug rather
    than swallowed silently.
    """
    try:
        img = pillow_heif.open_heif(photo, convert_hdr_to_8bit=False)
        bit_depth = img.info.get('bit_depth', 8)
        if bit_depth <= 8 or img.mode != 'RGB;16':
            return None
        out = _tonemap_codes_to_srgb(
            np.asarray(img), _pq_eotf_lut(bit_depth), 16 - bit_depth, settings)
        Image, _ = _ensure_pil()
        native_img = Image.fromarray(out, 'RGB')
        exif = img.info.get('exif')
        if exif:
            native_img.info['exif'] = exif
        return native_img
    except Exception as ex:
        logger.debug("Native-depth PQ decode failed for %s, falling back to 8-bit: %s",
                     os.path.basename(str(photo)), ex)
        return None


def open_nonraw_image(photo):
    """Open a non-RAW image with EXIF orientation and HDR PQ tone mapping.

    The single decode for every non-RAW consumer -- the batch scorer, the
    viewer's HEIF-to-JPEG converter -- so the image the models score and the
    image the browser shows cannot disagree on orientation or tone.

    The NCLX profile is read straight after ``Image.open`` because
    ``exif_transpose``/``convert`` may drop ``info``. The source handle is
    closed before returning: ``exif_transpose`` loads the pixels and always
    hands back a new image, so nothing returned here still refers to the file.

    A PQ frame is decoded twice in the worst case: once here (header only --
    ``Image.open`` is lazy) to detect PQ from the NCLX profile, then again by
    :func:`_decode_pq_native` at its native bit depth. The native decode is the
    CHEAPER of the two despite its uint16 buffer, because taking it means PIL
    never decodes the frame at all and ``exif_transpose`` never copies that
    decode: measured on a 12 MP PQ frame, peak RSS is 166.4 MiB native against
    212.3 MiB 8-bit (14.5 vs 18.6 bytes/pixel). That native decode
    replaces the whole rest of this function on success -- its own EXIF
    transpose happens after the tone map, which is safe: the map is per-pixel
    and the white point is a percentile over all pixels, both order-independent.
    Any failure there (including ``hdr_pq_tonemap.enabled: false``, which is
    never even attempted) falls through to the 8-bit path below unchanged.
    :func:`_decode_pq_native` calls ``pillow_heif.open_heif`` and so can never
    serve an AVIF -- only HEIF takes this native-depth branch; a PQ AVIF
    always takes the 8-bit path below.

    Alpha (RGBA/LA, or palette with an ``info['transparency']`` key) is
    composited over white, and a 16-bit single-channel frame (16-bit
    grey PNG/TIFF) is scaled to 8-bit rather than left to clip to white --
    see the inline comments below for the two measured defects this fixes.

    Raises:
        ValueError: the frame exceeds ``Image.MAX_IMAGE_PIXELS``.
    """
    Image, ImageOps = _ensure_pil()
    with Image.open(photo) as source:
        # Pillow only WARNS between MAX_IMAGE_PIXELS and twice that, and hard-errors
        # only above the doubled bound -- a warn-only band nothing here checks or
        # sets. The PQ tone map then adds a measured ~6.6 bytes/pixel on top of
        # the decoded frame, so a frame Pillow would only warn about is already an
        # outsized allocation before tone mapping even starts. Refuse it here, once,
        # on the one decode path every non-RAW consumer shares, rather than let it
        # warn its way into an OOM per request. A None limit is Pillow's documented
        # way to disable the check entirely, and it disables this one too.
        width, height = source.size
        pixel_count = width * height
        if Image.MAX_IMAGE_PIXELS is not None and pixel_count > Image.MAX_IMAGE_PIXELS:
            raise ValueError(
                f"{photo}: {pixel_count} pixels exceeds the "
                f"MAX_IMAGE_PIXELS limit of {Image.MAX_IMAGE_PIXELS}"
            )
        is_heif_pq = _heif_is_pq(source)
        # Pillow's native AVIF plugin exposes no colour metadata (verified
        # in-session: pil_img.info on a PQ AVIF has no CICP field at all), so
        # PQ can only be detected by parsing the container ourselves -- and
        # only for an AVIF container, never for a format this box walk was
        # not written for.
        is_avif_pq = (Path(photo).suffix.lower() in KNOWN_AVIF_EXTENSIONS
                      and _avif_is_pq(photo))
        is_pq = is_heif_pq or is_avif_pq
        if is_heif_pq:
            settings = get_hdr_pq_tonemap_settings()
            if settings.get('enabled', True):
                native_img = _decode_pq_native(photo, settings)
                if native_img is not None:
                    return ImageOps.exif_transpose(native_img)
        pil_img = ImageOps.exif_transpose(source)

    # Palette images carry transparency as an info key rather than a pixel
    # band, and split() on a palette image returns a 'P' band, not alpha
    # (verified: raises ValueError: bad transparency mask). convert('RGBA')
    # is the only leg that produces a real alpha band from one.
    if pil_img.mode == 'P' and 'transparency' in pil_img.info:
        pil_img = pil_img.convert('RGBA')

    # The alpha mask must come from the image AFTER exif_transpose, never
    # from the pre-transpose source: an RGBA image carrying EXIF Orientation 6
    # changes size through the transpose (verified: (40, 20) -> (20, 40)), so
    # a mask split off before it no longer matches pil_img's size and
    # background.paste(mask=...) below would raise ValueError: images do not
    # match.
    has_alpha = pil_img.mode in ('RGBA', 'LA')
    alpha_channel = pil_img.getchannel('A') if has_alpha else None

    if pil_img.mode in _SIXTEEN_BIT_MODES:
        # Bug 2: convert('RGB') on a 16-bit single-channel frame clips to
        # solid white instead of scaling -- verified on a uint16 ramp of
        # source mean 32767.5 decoding to output mean 254.8, max 255.
        # The convert('I') hop is mandatory, not stylistic: a bare
        # pil_img.point(...) RAISES ValueError: point operation not supported
        # for this mode on I;16B/I;16L (the exact mode the source defect was
        # measured on, a big-endian 16-bit TIFF), and normalising via
        # convert('I;16') instead of convert('I') yields mean 0.00 -- silent
        # total corruption. convert('I') + point(i * 1/256) + convert('L') is
        # verified on Pillow 12.3.0 to give mean 127.50 on all three modes.
        #
        # The 32-bit modes 'I' and 'F' are deliberately NOT in this set: a
        # 16-bit source always opens as one of the I;16* modes (verified for
        # both PNG and TIFF on Pillow 12.3.0), while 'I'/'F' carry a 32-bit
        # range this /256 is wrong for -- a float TIFF whose samples are
        # already 0..255 would scale to mean 0.00, i.e. solid black, with no
        # exception and so no scan_failures row. Their pre-existing
        # convert('RGB') clip is left untouched.
        pil_img = pil_img.convert('I').point(lambda i: i * (1 / 256)).convert('L')

    if pil_img.mode != 'RGB':
        pil_img = pil_img.convert('RGB')

    if is_pq:
        pil_img = _tonemap_pq_to_srgb(pil_img)

    if has_alpha:
        # Composited over white only as the FINAL step, after any PQ tone
        # map: AVIF's alpha plane is not transfer-function-encoded, so
        # blending it in before the map would run un-tone-mapped PQ code
        # values through the white background. For the non-PQ majority case
        # this is a one-step composite-then-return with no behavioural
        # difference from doing it earlier.
        background = Image.new('RGB', pil_img.size, (255, 255, 255))
        background.paste(pil_img, mask=alpha_channel)
        pil_img = background

    return pil_img


_raw_decode_settings = None


def configure_raw_decode_profile(settings=None):
    """Set the RAW decode profile for this process; missing keys keep defaults."""
    global _raw_decode_settings
    merged = dict(RAW_DECODE_DEFAULTS)
    merged.update(settings or {})
    _raw_decode_settings = merged
    return merged


def _raw_decode_settings_from_config():
    """Read the profile straight off disk, without validating or rewriting it.

    A decode can run inside a viewer request or a worker thread, where
    ScoringConfig's default validation would re-save a corrected config behind
    the write lock's back. The path is resolved absolutely because a decode
    must not depend on the process's working directory.
    """
    try:
        from config import ScoringConfig, default_config_path
        return ScoringConfig(default_config_path(), validate=False).get_raw_decode_settings()
    except Exception as ex:
        logger.warning("Using default RAW decode settings (%s)", ex)
        return {}


def get_raw_decode_settings():
    """RAW decode profile, read from scoring_config.json on first use."""
    if _raw_decode_settings is None:
        return configure_raw_decode_profile(_raw_decode_settings_from_config())
    return _raw_decode_settings


_hdr_pq_tonemap_settings = None


def configure_hdr_pq_tonemap_profile(settings=None):
    """Set the HDR PQ tone-map profile for this process; missing keys keep defaults."""
    global _hdr_pq_tonemap_settings
    _hdr_pq_tonemap_settings = merge_hdr_pq_tonemap_settings(settings or {})
    return _hdr_pq_tonemap_settings


def _hdr_pq_tonemap_settings_from_config():
    """Read the profile off disk without validating or rewriting it.

    A decode can run on a viewer or worker thread, where ScoringConfig's
    default validation would re-save a corrected config behind the write
    lock's back. Mirrors _raw_decode_settings_from_config.
    """
    try:
        from config import ScoringConfig, default_config_path
        return ScoringConfig(default_config_path(), validate=False).get_hdr_pq_tonemap_settings()
    except Exception as ex:
        logger.warning("Using default HDR PQ tone-map settings (%s)", ex)
        return dict(HDR_PQ_TONEMAP_DEFAULTS)


def get_hdr_pq_tonemap_settings():
    """HDR PQ tone-map profile, read from scoring_config.json on first use."""
    if _hdr_pq_tonemap_settings is None:
        return configure_hdr_pq_tonemap_profile(_hdr_pq_tonemap_settings_from_config())
    return _hdr_pq_tonemap_settings


def raw_postprocess_kwargs(auto_bright=False, bright=None):
    """LibRaw postprocess parameters for a faithful, exposure-preserving demosaic.

    ``no_auto_bright`` and ``adjust_maximum_thr`` are per-frame adaptive terms.
    The first rescales a frame until roughly 1% of *its own* pixels clip; the
    second substitutes that same frame's brightest pixel for the camera white
    level. Together they equalise exposure across a bracket, erasing the very
    ladder the scoring engine measures, so this profile disables both and
    applies one fixed ``bright`` gain to every frame instead.

    ``bright`` overrides that configured gain; ``FAITHFUL_BRIGHT`` renders with
    no gain at all, which is what a bracketed frame gets.

    ``auto_bright=True`` restores LibRaw's adaptive terms so
    ``--check-raw-rendering`` can render the pre-fix result alongside.
    """
    import rawpy
    if auto_bright:
        gain = 1.0
    elif bright is None:
        gain = float(get_raw_decode_settings()['bright'])
    else:
        gain = float(bright)
    return {
        'use_camera_wb': True,
        'no_auto_bright': not auto_bright,
        'adjust_maximum_thr': _LIBRAW_AUTO_BRIGHT_MAXIMUM_THR if auto_bright else 0.0,
        'bright': gain,
        'output_color': rawpy.ColorSpace.sRGB,
        'output_bps': 8,
    }


def renders_faithfully(sequence_kind):
    """Whether a frame of this sequence kind must render with no correction.

    Bracket membership is only known once sequence detection has run, which is
    after a scan — so this is a display-time decision, never a scan-time one.
    """
    if not get_raw_decode_settings()['faithful_bracket_render']:
        return False
    return sequence_kind in BRACKETED_SEQUENCE_KINDS


def _upright_preview(pil_img, libraw_flip):
    """Rotate an embedded preview upright.

    ``unpack_thumb`` hands back the preview exactly as the camera wrote it, so
    nothing has been rotated yet. Most previews carry their own EXIF
    orientation; those that do not inherit the host RAW's, which LibRaw exposes
    as ``sizes.flip`` and applies itself when demosaicing.
    """
    _, ImageOps = _ensure_pil()
    exif = pil_img.getexif()
    if exif and exif.get(_EXIF_ORIENTATION_TAG):
        return ImageOps.exif_transpose(pil_img)
    angle = _LIBRAW_FLIP_ROTATIONS.get(libraw_flip)
    return pil_img.rotate(angle, expand=True) if angle else pil_img


def extract_raw_preview(photo_path, min_long_edge=0, min_sensor_ratio=0.0):
    """Decode the camera-embedded preview of a RAW file, or None if unusable.

    The camera preview carries the model's own tone curve, DR modes and
    exposure, which is what keeps a bracket's frames distinguishable, and reads
    a fraction of the bytes a demosaic does.

    None is returned whenever the preview cannot stand in for a decode: the
    file has none, LibRaw cannot unpack its codec (recent Canon CR3 embed
    H.265), the bytes fail to decode, or it is smaller than the caller accepts.

    Args:
        photo_path: Path to a RAW file (str or Path)
        min_long_edge: Reject a preview whose long edge is under this
        min_sensor_ratio: Reject a preview whose long edge is under this
                          fraction of the sensor's
    """
    import rawpy
    Image, _ = _ensure_pil()
    try:
        with rawpy.imread(str(photo_path)) as raw:
            thumb = raw.extract_thumb()
            sizes = raw.sizes
            sensor_long_edge = max(sizes.width, sizes.height)
            flip = sizes.flip
            if thumb.format == rawpy.ThumbFormat.JPEG:
                preview = Image.open(BytesIO(thumb.data))
                preview.load()
            else:
                preview = Image.fromarray(np.array(thumb.data))
    except Exception as ex:
        logger.debug("No usable embedded preview in %s: %s", os.path.basename(photo_path), ex)
        return None

    preview = _upright_preview(preview, flip)
    long_edge = max(preview.size)
    if long_edge < min_long_edge:
        return None
    if sensor_long_edge > 0 and long_edge < min_sensor_ratio * sensor_long_edge:
        return None
    return preview if preview.mode == 'RGB' else preview.convert('RGB')


def _exiftool_preview_candidates(exe, photo_path):
    """List the file's embedded previews as (byte_size, group_tag) descending.

    Uses -a -G1 -n so duplicate tags across groups (e.g. SubIFD1:PreviewImage
    and IFD0:JpgFromRaw) all surface, group-qualified, with binary values
    rendered as a parseable "(Binary data N bytes, ...)" placeholder rather
    than actually extracted.
    """
    try:
        result = subprocess.run(
            [exe, '-j', '-a', '-G1', '-n', '-Orientation',
             '-PreviewImage', '-JpgFromRaw', '-OtherImage', '--', str(photo_path)],
            capture_output=True, timeout=EXIFTOOL_PREVIEW_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        logger.debug("exiftool preview listing timed out for %s", os.path.basename(photo_path))
        return [], None
    except OSError as ex:
        logger.debug("exiftool preview listing failed for %s: %s", os.path.basename(photo_path), ex)
        return [], None

    stdout = result.stdout.decode('utf-8', errors='replace')
    try:
        records = json.loads(stdout)
    except json.JSONDecodeError:
        logger.debug("exiftool returned unparseable JSON for %s", os.path.basename(photo_path))
        return [], None
    if not records:
        return [], None
    tags = records[0]

    orientation = None
    for key, value in tags.items():
        if key.split(':')[-1] != 'Orientation':
            continue
        if key.startswith('IFD0:') or orientation is None:
            orientation = value

    candidates = []
    for key, value in tags.items():
        tag_name = key.split(':')[-1]
        if tag_name not in _EXIFTOOL_PREVIEW_TAG_NAMES or not isinstance(value, str):
            continue
        match = _EXIFTOOL_BINARY_SIZE_RE.search(value)
        if not match:
            continue
        candidates.append((int(match.group(1)), key))
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates, orientation


def _upright_exiftool_preview(pil_img, orientation):
    """Rotate/flip an exiftool-extracted preview using the host RAW's EXIF
    Orientation, since the extracted preview bytes carry none of their own."""
    Image, _ = _ensure_pil()
    ops = _EXIF_ORIENTATION_TRANSPOSES.get(int(orientation)) if orientation else None
    if not ops:
        return pil_img
    for op_name in ops:
        pil_img = pil_img.transpose(getattr(Image, op_name))
    return pil_img


def extract_exiftool_preview(photo_path):
    """Extract the largest usable embedded preview via exiftool, or None.

    LibRaw outright rejects some Lightroom-merged DNGs — floating-point
    HDR/panorama merges (``*-HDR.dng``, ``*-Pano.dng``) — raising
    ``rawpy.LibRawFileUnsupportedError`` rather than the "no preview" outcomes
    ``extract_raw_preview`` handles. exiftool can still read the
    camera-embedded preview those files carry even though LibRaw cannot open
    the container, so this is the fallback ``_decode_raw`` reaches for after
    rawpy has already failed outright.

    Lightroom Classic 13+ additionally compresses every preview in a DNG 1.7
    merge (HDR/Panorama/Enhance) with JPEG XL, which Pillow cannot
    decode — this function then falls through smaller candidates
    until only the tiny IFD0 thumbnail is left, which usually fails the
    caller's size floor. ``extract_dng_jxl_preview`` is the further fallback
    for that case: it decodes the JPEG XL SubIFD preview directly via
    tifffile/imagecodecs instead of shelling out to exiftool for the bytes.

    This function must never raise: a RuntimeError in particular is the
    signal load_image_from_path/load_display_image use to abort on a hung RAW
    decode slot, and an accidental one here would be mistaken for that.

    Args:
        photo_path: Path to a RAW file (str or Path)

    Returns:
        PIL Image in RGB, or None if no candidate preview decodes and clears
        EXIFTOOL_PREVIEW_MIN_LONG_EDGE.
    """
    try:
        from processing.xmp_export import _resolve_exiftool
        exe = _resolve_exiftool()
        if exe is None:
            logger.debug("exiftool not found; no preview fallback for %s",
                         os.path.basename(str(photo_path)))
            return None

        candidates, orientation = _exiftool_preview_candidates(exe, photo_path)
        if not candidates:
            return None

        Image, _ = _ensure_pil()
        for _size, group_tag in candidates:
            try:
                result = subprocess.run(
                    [exe, '-b', f'-{group_tag}', '--', str(photo_path)],
                    capture_output=True, timeout=EXIFTOOL_PREVIEW_TIMEOUT_SECONDS,
                )
            except subprocess.TimeoutExpired:
                logger.debug("exiftool -b timed out extracting %s from %s",
                             group_tag, os.path.basename(str(photo_path)))
                continue
            except OSError as ex:
                logger.debug("exiftool -b failed extracting %s from %s: %s",
                             group_tag, os.path.basename(str(photo_path)), ex)
                continue
            if not result.stdout:
                continue
            try:
                preview = Image.open(BytesIO(result.stdout))
                preview.load()
            except Exception as ex:
                # Includes PIL.UnidentifiedImageError / DecompressionBombError:
                # Pillow in this venv cannot decode JPEG XL previews, which
                # some cameras embed, so falling through to a smaller
                # candidate matters.
                logger.debug("exiftool preview %s for %s did not decode: %s",
                             group_tag, os.path.basename(str(photo_path)), ex)
                continue

            preview = _upright_exiftool_preview(preview, orientation)
            if max(preview.size) < EXIFTOOL_PREVIEW_MIN_LONG_EDGE:
                continue
            return preview if preview.mode == 'RGB' else preview.convert('RGB')
        return None
    except Exception as ex:
        logger.debug("exiftool preview fallback failed for %s: %s",
                     os.path.basename(str(photo_path)), ex)
        return None


def extract_dng_jxl_preview(photo_path):
    """Decode a Lightroom-merged DNG's JPEG XL SubIFD preview, or None.

    Lightroom Classic 13+ writes "Merge to HDR/Panorama" (and Enhance) output
    as DNG 1.7 with every image — the main raster AND every embedded preview
    — compressed as JPEG XL (TIFF compression 52546). LibRaw rejects the
    container outright (see ``extract_exiftool_preview``), and Pillow cannot
    decode JPEG XL either, so ``extract_exiftool_preview`` falls
    through every real-size candidate down to the tiny IFD0 thumbnail. This
    function reads the same SubIFD preview tifffile/imagecodecs can actually
    decode: it walks IFD0 and its SubIFDs for the largest RGB uint8 page at
    or above ``EXIFTOOL_PREVIEW_MIN_LONG_EDGE`` and decodes it directly,
    bypassing exiftool's ``-b`` extraction (which only hands back bytes
    Pillow must still decode).

    DNG tag 50970 (PreviewColorSpace) on a real Lightroom Classic 13.1
    HDR-merge sample reads 2 (sRGB), so the decoded pixels are treated as
    sRGB without further conversion; this is an assumption, not something
    this function verifies per file.

    This function must never raise, for the same reason as
    ``extract_exiftool_preview``: a RuntimeError here would be mistaken for
    the hung-decode-timeout signal load_image_from_path/load_display_image
    use to abort a RAW decode slot.

    Args:
        photo_path: Path to a DNG file (str or Path)

    Returns:
        PIL Image in RGB, or None if the preview cannot be decoded, the file
        has no eligible SubIFD preview, or nothing clears
        EXIFTOOL_PREVIEW_MIN_LONG_EDGE.
    """
    try:
        import tifffile  # decodes JPEG XL tiles through imagecodecs

        Image, _ = _ensure_pil()
        with tifffile.TiffFile(str(photo_path)) as tif:
            candidates = []
            for page in [tif.pages[0], *(tif.pages[0].pages or [])]:
                if (page.photometric == 2 and page.samplesperpixel == 3
                        and page.dtype == np.uint8):
                    candidates.append(page)
            if not candidates:
                return None
            best = max(candidates, key=lambda p: max(p.shape[0], p.shape[1]))
            if max(best.shape[0], best.shape[1]) < EXIFTOOL_PREVIEW_MIN_LONG_EDGE:
                return None
            preview = Image.fromarray(best.asarray())

            orientation = None
            for tag in tif.pages[0].tags:
                if tag.name == 'Orientation':
                    orientation = tag.value
                    break
        preview = _upright_exiftool_preview(preview, orientation)
        return preview if preview.mode == 'RGB' else preview.convert('RGB')
    except Exception as ex:
        logger.debug("DNG JPEG XL preview fallback failed for %s: %s",
                     os.path.basename(str(photo_path)), ex)
        return None


def _display_preview(photo_path, min_sensor_ratio):
    if not get_raw_decode_settings()['prefer_embedded_preview']:
        return None
    return extract_raw_preview(
        photo_path,
        min_long_edge=DISPLAY_PREVIEW_MIN_LONG_EDGE,
        min_sensor_ratio=min_sensor_ratio,
    )


# RAW decode concurrency. LibRaw is reentrant when each decode uses its own
# rawpy.imread() instance (which every call site here does), so a global mutex
# is unnecessary for correctness. The semaphore acts as a memory governor:
# each 45-60MP demosaic peaks at roughly 200-400MB of intermediates, so
# in-flight decodes must stay bounded.

def _auto_decode_concurrency():
    """Pick a safe default RAW decode concurrency from CPU and available RAM."""
    from utils.system_memory import effective_memory
    cpu = os.cpu_count() or 2
    limit = max(1, min(4, cpu // 2))
    available_gb = effective_memory().available / 2 ** 30
    return max(1, min(limit, int(available_gb // 3)))


# Hung RAW decodes (stalled NAS I/O) cannot be killed; a decode that exceeds
# the timeout after it has actually started is abandoned and keeps its
# semaphore slot until it finishes. When every slot is wedged by such hung
# decodes the scan fails fast instead of blocking forever. _ABANDON_BUDGET is
# the extra executor headroom that lets fresh decodes run past lingering ones.
_ABANDON_BUDGET = 2

_decode_concurrency = _auto_decode_concurrency()
_raw_semaphore = threading.BoundedSemaphore(_decode_concurrency)
_decode_timeout = 0.0  # 0 = disabled; scanners opt in via configure_raw_decoding()
_decode_executor = None
_abandoned_decodes = 0
_hung_decodes = 0
_state_lock = threading.Lock()

# A second, independent budget for the /image viewer path: a viewer request
# must never queue behind library decode work holding _raw_semaphore. Built
# lazily since its size comes from disk config, not a CPU/RAM heuristic.
_viewer_semaphore = None


def configure_raw_decoding(concurrency=None, timeout_seconds=None):
    """Configure RAW decode concurrency and timeout for a scan run.

    Args:
        concurrency: Max simultaneous RAW decodes (None/0 = keep auto value,
                     1 = fully serialized, matching the historical global lock)
        timeout_seconds: Abandon a decode after this many seconds
                         (None = keep current, 0 = disabled)
    """
    global _decode_concurrency, _raw_semaphore, _decode_timeout, _decode_executor, _hung_decodes, _viewer_semaphore
    with _state_lock:
        if concurrency:
            _decode_concurrency = max(1, int(concurrency))
            _raw_semaphore = threading.BoundedSemaphore(_decode_concurrency)
            _hung_decodes = 0
            if _decode_executor is not None:
                _decode_executor.shutdown(wait=False)
                _decode_executor = None
            _viewer_semaphore = threading.BoundedSemaphore(
                max(1, int(get_raw_decode_settings()['viewer_concurrency'])))
        if timeout_seconds is not None:
            _decode_timeout = max(0.0, float(timeout_seconds))
    logger.info(
        "RAW decoding configured: concurrency=%d, timeout=%ss",
        _decode_concurrency, _decode_timeout or 'off',
    )


def _get_decode_executor():
    global _decode_executor
    with _state_lock:
        if _decode_executor is None:
            _decode_executor = ThreadPoolExecutor(
                max_workers=_decode_concurrency + _ABANDON_BUDGET,
                thread_name_prefix='rawdecode',
            )
        return _decode_executor


def _get_viewer_semaphore():
    """Lazily build the viewer decode budget from config on first real use.

    The viewer process never calls configure_raw_decoding, so this is the
    only path that sizes it from the user's scoring_config.json.
    """
    global _viewer_semaphore
    with _state_lock:
        if _viewer_semaphore is None:
            _viewer_semaphore = threading.BoundedSemaphore(
                max(1, int(get_raw_decode_settings()['viewer_concurrency'])))
        return _viewer_semaphore


def _decode_raw(photo, use_thumbnail, started_event=None, decode_budget='library', bright=None):
    """Decode a RAW file to a PIL image. Runs under the given decode budget's semaphore.

    started_event, when supplied, is set the moment the semaphore is acquired
    so the caller can time only the decode, never the queue wait for a slot.
    """
    import rawpy
    Image, _ = _ensure_pil()
    pil_img = None
    semaphore = _get_viewer_semaphore() if decode_budget == 'viewer' else _raw_semaphore
    with semaphore:
        if started_event is not None:
            started_event.set()
        if use_thumbnail:
            pil_img = extract_raw_preview(photo)

        if pil_img is None:
            try:
                with rawpy.imread(str(photo)) as raw:
                    pil_img = Image.fromarray(raw.postprocess(**raw_postprocess_kwargs(bright=bright)))
            except rawpy.LibRawFileUnsupportedError as ex:
                # Lightroom-merged floating-point DNGs (*-HDR.dng, *-Pano.dng)
                # LibRaw refuses to open at all. exiftool can still pull the
                # camera-embedded preview those files carry.
                fallback = extract_exiftool_preview(photo)
                if fallback is None and str(photo).lower().endswith('.dng'):
                    fallback = extract_dng_jxl_preview(photo)
                if fallback is None:
                    raise
                logger.info("Used embedded preview fallback for %s (%dx%d): %s",
                           os.path.basename(str(photo)), fallback.size[0], fallback.size[1], ex)
                pil_img = fallback
    return pil_img


def _on_hung_decode_done(_future):
    """Drop the hung-slot count once an abandoned decode finally returns."""
    global _hung_decodes
    with _state_lock:
        _hung_decodes = max(0, _hung_decodes - 1)


def _decode_raw_with_timeout(photo, use_thumbnail, decode_budget='library', bright=None):
    """Decode a RAW file, timing only the decode itself.

    The wait for a free decode slot (semaphore/executor queueing) is excluded
    from the timeout, so legitimate congestion is never mistaken for a stall.
    Once a decode has started it must finish within the timeout or it is
    abandoned, keeping its slot until it eventually returns. When every slot is
    wedged by such hung decodes the scan fails fast instead of blocking forever.
    """
    global _abandoned_decodes, _hung_decodes
    started = threading.Event()
    future = _get_decode_executor().submit(_decode_raw, photo, use_thumbnail, started,
                                           decode_budget, bright)
    while not started.wait(timeout=_decode_timeout):
        if future.done():
            break
        with _state_lock:
            hung = _hung_decodes
            concurrency = _decode_concurrency
        if hung >= concurrency:
            raise RuntimeError(
                f"{hung} RAW decode slots hung - storage likely stalled"
            )
    try:
        return future.result(timeout=_decode_timeout)
    except FuturesTimeoutError:
        with _state_lock:
            _abandoned_decodes += 1
            _hung_decodes += 1
            abandoned = _abandoned_decodes
        logger.error(
            "RAW decode timed out after %.0fs (%d hung): %s",
            _decode_timeout, abandoned, os.path.basename(photo),
        )
        future.add_done_callback(_on_hung_decode_done)
        return None


def _decode_raw_bounded(photo, use_thumbnail=False, decode_budget='library', bright=None):
    """Decode a RAW file under the configured concurrency and timeout policy."""
    if _decode_timeout > 0:
        return _decode_raw_with_timeout(photo, use_thumbnail, decode_budget, bright)
    return _decode_raw(photo, use_thumbnail, decode_budget=decode_budget, bright=bright)


def load_display_image(photo_path, min_preview_sensor_ratio=0.0, decode_budget='library',
                       sequence_kind=None):
    """Load an image in display space: what a viewer or a thumbnail should show.

    A RAW file renders from its camera-embedded preview when one is usable,
    which keeps the camera's tone curve and exposure — the reason a bracket's
    frames stay distinguishable — and reads far less of the file than a
    demosaic. Anything else, and any RAW whose preview is missing or too small,
    falls back to the metrics-profile demosaic.

    A RAW belonging to a bracketed set is the exception: it demosaics with no
    gain at all (see ``renders_faithfully``), because the preview's tone curve
    and the ``bright`` gain both compress the highlight headroom the bracket
    was shot to capture.

    This is deliberately not ``load_image_from_path``: stored face bboxes and
    ``image_width``/``image_height`` are expressed in the demosaic's pixel
    space, so neither a preview-sourced nor a bracket-specific buffer must ever
    reach them.

    Args:
        photo_path: Path to image file (str or Path)
        min_preview_sensor_ratio: Smallest preview-to-sensor long-edge ratio
                                  worth serving instead of a demosaic
        decode_budget: Which semaphore a demosaic fallback draws from —
                       ``'library'`` (default) for scan/CLI work, ``'viewer'``
                       for the /image endpoint, which must never queue behind it
        sequence_kind: The row's ``photos.sequence_kind``, or None when it
                       belongs to no detected set

    Returns:
        PIL Image in RGB, or None on error.
    """
    try:
        photo = Path(photo_path)
        if photo.suffix.lower() in RAW_EXTENSIONS:
            if renders_faithfully(sequence_kind):
                return _decode_raw_bounded(photo, decode_budget=decode_budget,
                                           bright=FAITHFUL_BRIGHT)
            preview = _display_preview(photo, min_preview_sensor_ratio)
            return preview if preview is not None else _decode_raw_bounded(photo, decode_budget=decode_budget)
        return open_nonraw_image(photo)
    except RuntimeError:
        raise
    except Exception as e:
        logger.error("Error loading display image %s: %s", os.path.basename(photo_path), e)
        return None


def thumbnail_source(photo_path, decoded_img):
    """Pick the buffer a stored thumbnail should be generated from.

    Non-RAW files are already in display space. For RAW the embedded preview is
    preferred, and the caller's own demosaic stands in when there is none — a
    second full decode would cost far more than the thumbnail is worth.
    """
    if Path(photo_path).suffix.lower() not in RAW_EXTENSIONS:
        return decoded_img
    preview = _display_preview(photo_path, 0.0)
    return preview if preview is not None else decoded_img


def load_image_from_path(photo_path, use_thumbnail=False):
    """
    Load image from path, handling RAW files (CR2/CR3) and JPEGs.

    For RAW files, uses the metrics-profile demosaic by default: faithful
    exposure, no per-frame auto-brightness (see raw_postprocess_kwargs). This
    is the pixel space every stored face bbox and image_width/image_height is
    expressed in — display buffers come from load_display_image instead.
    Set use_thumbnail=True for faster loading when lower quality is acceptable.
    Applies EXIF transpose for proper orientation.

    RAW decodes run under a bounded semaphore (see configure_raw_decoding)
    and optionally a per-decode timeout.

    Args:
        photo_path: Path to image file (str or Path)
        use_thumbnail: If True, extract embedded thumbnail from RAW (faster, lower quality).
                      If False (default), use full demosaic for RAW (slower, best quality).

    Returns:
        tuple: (pil_img, img_cv) - PIL Image and OpenCV BGR array
               Returns (None, None) on error
    """
    cv2 = _ensure_cv2()

    try:
        photo = Path(photo_path)

        if photo.suffix.lower() in RAW_EXTENSIONS:
            pil_img = _decode_raw_bounded(photo, use_thumbnail)
            if pil_img is None:
                return None, None
        else:
            pil_img = open_nonraw_image(photo)

        # Convert to OpenCV BGR format
        img_cv = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

        return pil_img, img_cv

    except RuntimeError:
        raise
    except Exception as e:
        logger.error("Error loading image %s: %s", photo_path, e)
        return None, None


def load_image_for_face_crop(photo_path):
    """
    Load an image in the pixel space that stored face bboxes are expressed in.

    Face detection always runs on the array load_image_from_path() returns — the
    full demosaic for RAW, EXIF-transposed for everything else — so a bbox read
    back from the database indexes that array. Cropping therefore decodes through
    the same function: a second, separately parameterised decode is free to
    differ in size, and every stored bbox would then address a different region.

    Args:
        photo_path: Path to image file (str or Path)

    Returns:
        OpenCV BGR array in detection space, or None on error.
    """
    return load_image_from_path(photo_path)[1]
