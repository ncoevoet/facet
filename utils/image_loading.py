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


def configure_raw_decoding(concurrency=None, timeout_seconds=None):
    """Configure RAW decode concurrency and timeout for a scan run.

    Args:
        concurrency: Max simultaneous RAW decodes (None/0 = keep auto value,
                     1 = fully serialized, matching the historical global lock)
        timeout_seconds: Abandon a decode after this many seconds
                         (None = keep current, 0 = disabled)
    """
    global _decode_concurrency, _raw_semaphore, _decode_timeout, _decode_executor, _hung_decodes
    with _state_lock:
        if concurrency:
            _decode_concurrency = max(1, int(concurrency))
            _raw_semaphore = threading.BoundedSemaphore(_decode_concurrency)
            _hung_decodes = 0
            if _decode_executor is not None:
                _decode_executor.shutdown(wait=False)
                _decode_executor = None
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


def _decode_raw(photo, use_thumbnail, started_event=None):
    """Decode a RAW file to a PIL image. Runs under the decode semaphore.

    started_event, when supplied, is set the moment the semaphore is acquired
    so the caller can time only the decode, never the queue wait for a slot.
    """
    import rawpy
    Image, ImageOps = _ensure_pil()
    pil_img = None
    with _raw_semaphore:
        if started_event is not None:
            started_event.set()
        if use_thumbnail:
            # Try thumbnail extraction first (faster, lower quality)
            with rawpy.imread(str(photo)) as raw:
                try:
                    thumb = raw.extract_thumb()
                    if thumb.format == rawpy.ThumbFormat.JPEG:
                        pil_img = Image.open(BytesIO(thumb.data))
                        pil_img = ImageOps.exif_transpose(pil_img)
                    else:
                        pil_img = Image.fromarray(thumb.data)
                except Exception:
                    pass  # Will fall back to demosaic below

        # Full demosaic (default, best quality)
        if pil_img is None:
            with rawpy.imread(str(photo)) as raw:
                rgb = raw.postprocess(
                    use_camera_wb=True,
                    no_auto_bright=False,
                    output_color=rawpy.ColorSpace.sRGB,
                    output_bps=8
                )
                pil_img = Image.fromarray(rgb)
    return pil_img


def _on_hung_decode_done(_future):
    """Drop the hung-slot count once an abandoned decode finally returns."""
    global _hung_decodes
    with _state_lock:
        _hung_decodes = max(0, _hung_decodes - 1)


def _decode_raw_with_timeout(photo, use_thumbnail):
    """Decode a RAW file, timing only the decode itself.

    The wait for a free decode slot (semaphore/executor queueing) is excluded
    from the timeout, so legitimate congestion is never mistaken for a stall.
    Once a decode has started it must finish within the timeout or it is
    abandoned, keeping its slot until it eventually returns. When every slot is
    wedged by such hung decodes the scan fails fast instead of blocking forever.
    """
    global _abandoned_decodes, _hung_decodes
    started = threading.Event()
    future = _get_decode_executor().submit(_decode_raw, photo, use_thumbnail, started)
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


def load_image_from_path(photo_path, use_thumbnail=False):
    """
    Load image from path, handling RAW files (CR2/CR3) and JPEGs.

    For RAW files, uses full demosaic by default for maximum quality.
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
            if _decode_timeout > 0:
                pil_img = _decode_raw_with_timeout(photo, use_thumbnail)
            else:
                pil_img = _decode_raw(photo, use_thumbnail)
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
    Load image for face cropping, handling RAW files with bbox coordinate scaling.

    For RAW files, extracts embedded thumbnail dimensions (which face bboxes were
    calculated on), then loads the full demosaiced image for higher quality cropping.
    Returns the scale factors needed to map bbox coordinates from thumbnail to
    processed image dimensions.

    Args:
        photo_path: Path to image file (str or Path)

    Returns:
        tuple: (img_cv, scale_x, scale_y) where img_cv is OpenCV BGR array,
               and scale factors map thumbnail-space bboxes to img_cv space.
               Returns (None, 1.0, 1.0) on error.
    """
    cv2 = _ensure_cv2()
    Image, ImageOps = _ensure_pil()

    try:
        photo = Path(photo_path)
        img_cv = None
        scale_x, scale_y = 1.0, 1.0

        if photo.suffix.lower() in RAW_EXTENSIONS:
            import rawpy
            try:
                with rawpy.imread(str(photo)) as raw:
                    # Get embedded thumb dimensions (bboxes were calculated on this)
                    original_width = None
                    original_height = None
                    try:
                        thumb = raw.extract_thumb()
                        if thumb.format == rawpy.ThumbFormat.JPEG:
                            thumb_img = Image.open(BytesIO(thumb.data))
                            thumb_img = ImageOps.exif_transpose(thumb_img)
                            original_width = thumb_img.width
                            original_height = thumb_img.height
                    except Exception:
                        pass

                    # Use full RAW processing for higher quality
                    rgb = raw.postprocess(use_camera_wb=True)
                    img_cv = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

                    # Compute scale factors from thumb to processed dimensions
                    if original_width and img_cv.shape[1] != original_width:
                        scale_x = img_cv.shape[1] / original_width
                        scale_y = img_cv.shape[0] / original_height
            except Exception:
                return None, 1.0, 1.0
        else:
            # Always use PIL to properly handle EXIF rotation
            # cv2.imread() ignores EXIF orientation tags
            pil_img = Image.open(photo)
            pil_img = ImageOps.exif_transpose(pil_img)
            if pil_img.mode != 'RGB':
                pil_img = pil_img.convert('RGB')
            img_cv = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

        if img_cv is None:
            return None, 1.0, 1.0

        return img_cv, scale_x, scale_y

    except Exception:
        return None, 1.0, 1.0
