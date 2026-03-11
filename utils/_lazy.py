"""
Shared lazy imports for heavy imaging modules.

Avoids importing cv2 and PIL at module load time.
"""

import threading

_lock = threading.Lock()
_cv2 = None
_Image = None
_ImageOps = None


def ensure_cv2():
    """Lazy load cv2."""
    global _cv2
    if _cv2 is None:
        with _lock:
            if _cv2 is None:
                import cv2
                _cv2 = cv2
    return _cv2


def ensure_pil():
    """Lazy load PIL.

    Returns:
        tuple: (Image, ImageOps)
    """
    global _Image, _ImageOps
    if _Image is None:
        with _lock:
            if _Image is None:
                from PIL import Image, ImageOps
                _Image = Image
                _ImageOps = ImageOps
    return _Image, _ImageOps
