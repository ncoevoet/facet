"""
Image loading utilities for Facet.

Handles RAW (CR2/CR3), JPEG, and HEIC/HEIF loading with EXIF transpose.
"""

import threading
from io import BytesIO
from pathlib import Path

import numpy as np

# Register HEIC/HEIF support via pillow-heif (optional dependency)
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass

# Lazy imports for heavy modules
_cv2 = None
_Image = None
_ImageOps = None


def _ensure_cv2():
    """Lazy load cv2."""
    global _cv2
    if _cv2 is None:
        import cv2
        _cv2 = cv2
    return _cv2


def _ensure_pil():
    """Lazy load PIL."""
    global _Image, _ImageOps
    if _Image is None:
        from PIL import Image, ImageOps
        _Image = Image
        _ImageOps = ImageOps
    return _Image, _ImageOps


# Module-level lock for rawpy thread-safety
# libraw (underlying C library) has internal state that isn't thread-safe
# when extract_thumb() fails and falls back to postprocess() on the same raw object
_rawpy_lock = threading.Lock()


def load_image_from_path(photo_path, lock=None, use_thumbnail=False):
    """
    Load image from path, handling RAW files (CR2/CR3) and JPEGs.

    For RAW files, uses full demosaic by default for maximum quality.
    Set use_thumbnail=True for faster loading when lower quality is acceptable.
    Applies EXIF transpose for proper orientation.

    Args:
        photo_path: Path to image file (str or Path)
        lock: Optional threading.Lock for rawpy (uses module lock if None)
        use_thumbnail: If True, extract embedded thumbnail from RAW (faster, lower quality).
                      If False (default), use full demosaic for RAW (slower, best quality).

    Returns:
        tuple: (pil_img, img_cv) - PIL Image and OpenCV BGR array
               Returns (None, None) on error
    """
    Image, ImageOps = _ensure_pil()
    cv2 = _ensure_cv2()

    if lock is None:
        lock = _rawpy_lock

    try:
        photo = Path(photo_path)
        pil_img = None

        # Handle RAW files
        if photo.suffix.lower() in ['.cr2', '.cr3']:
            import rawpy
            with lock:  # Serialize rawpy access to prevent libraw state corruption
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
        else:
            pil_img = Image.open(photo)
            pil_img = ImageOps.exif_transpose(pil_img)
            if pil_img.mode != 'RGB':
                pil_img = pil_img.convert('RGB')

        # Convert to OpenCV BGR format
        img_cv = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

        return pil_img, img_cv

    except Exception as e:
        print(f"Error loading image {photo_path}: {e}")
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

        if photo.suffix.lower() in ['.cr2', '.cr3']:
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
