"""
Image loading utilities for Facet.

Handles RAW (via rawpy/libraw) and JPEG loading with EXIF transpose.
"""

import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from io import BytesIO
from pathlib import Path

import numpy as np

from config.scoring_config import RAW_DECODE_DEFAULTS
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

# All RAW formats supported via rawpy/libraw
RAW_EXTENSIONS = {'.cr2', '.cr3', '.nef', '.arw', '.raf', '.rw2', '.dng', '.orf', '.srw', '.pef'}

# HEIF/HEIC formats (iPhone default since iOS 11) — empty when pillow-heif is missing
HEIF_EXTENSIONS = {'.heic', '.heif'} if _heif_available else set()


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
        logger.debug("No usable embedded preview in %s: %s", photo_path, ex)
        return None

    preview = _upright_preview(preview, flip)
    long_edge = max(preview.size)
    if long_edge < min_long_edge:
        return None
    if sensor_long_edge > 0 and long_edge < min_sensor_ratio * sensor_long_edge:
        return None
    return preview if preview.mode == 'RGB' else preview.convert('RGB')


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
    cpu = os.cpu_count() or 2
    limit = max(1, min(4, cpu // 2))
    try:
        import psutil
        available_gb = psutil.virtual_memory().available / 2 ** 30
        limit = max(1, min(limit, int(available_gb // 3)))
    except ImportError:
        limit = min(limit, 2)
    return limit


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
            with rawpy.imread(str(photo)) as raw:
                pil_img = Image.fromarray(raw.postprocess(**raw_postprocess_kwargs(bright=bright)))
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
            _decode_timeout, abandoned, photo,
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
    Image, ImageOps = _ensure_pil()
    try:
        photo = Path(photo_path)
        if photo.suffix.lower() in RAW_EXTENSIONS:
            if renders_faithfully(sequence_kind):
                return _decode_raw_bounded(photo, decode_budget=decode_budget,
                                           bright=FAITHFUL_BRIGHT)
            preview = _display_preview(photo, min_preview_sensor_ratio)
            return preview if preview is not None else _decode_raw_bounded(photo, decode_budget=decode_budget)
        pil_img = ImageOps.exif_transpose(Image.open(photo))
        return pil_img if pil_img.mode == 'RGB' else pil_img.convert('RGB')
    except RuntimeError:
        raise
    except Exception as e:
        logger.error("Error loading display image %s: %s", photo_path, e)
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
    Image, ImageOps = _ensure_pil()
    cv2 = _ensure_cv2()

    try:
        photo = Path(photo_path)

        if photo.suffix.lower() in RAW_EXTENSIONS:
            pil_img = _decode_raw_bounded(photo, use_thumbnail)
            if pil_img is None:
                return None, None
        else:
            pil_img = Image.open(photo)
            pil_img = ImageOps.exif_transpose(pil_img)
            if pil_img.mode != 'RGB':
                pil_img = pil_img.convert('RGB')

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
