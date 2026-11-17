"""
Image cache for pre-computed transformations.
"""

import cv2
import numpy as np


# ``cv2.calcHist`` counts in float32, which stops being exact at 2**24 pixels in one bin
# (a 17 MP frame of a single grey level is realistic: a lens-cap shot, a clipped sky).
# Counting row bands of at most this many pixels keeps every partial count exact.
_HIST_BAND_PIXELS = 1 << 22


def gray_histogram(gray):
    """Exact 256-bin int64 histogram of a uint8 grey image (any strides)."""
    height, width = gray.shape[:2]
    rows = max(1, _HIST_BAND_PIXELS // max(width, 1))
    hist = np.zeros(256, dtype=np.int64)
    for top in range(0, height, rows):
        band = cv2.calcHist([gray[top:top + rows]], [0], None, [256], [0, 256])
        hist += band.ravel().astype(np.int64)
    return hist


def laplacian_variance(gray):
    """Population variance of the 3x3 Laplacian of a uint8 grey image.

    Computed from a 16-bit signed Laplacian (exact: +-1020 at most) and ``cv2.meanStdDev``,
    instead of a float64 Laplacian plus ``.var()``: ~5x faster and no 8 byte/pixel buffer.
    Agrees with the float64 pipeline to ~6e-15 relative; it is not bit-identical.
    Returns a Python ``float``.
    """
    _, std = cv2.meanStdDev(cv2.Laplacian(gray, cv2.CV_16S))
    return float(std[0][0]) ** 2


class ImageCache:
    """
    Pre-computes and caches commonly needed image transformations.

    Creating grayscale/HSV conversions, the exact grey histogram and the
    Laplacian variance once per image avoids redundant computation across
    multiple analyzer methods.

    Usage:
        cache = ImageCache(img_cv)
        sharpness_data = tech_analyzer.get_sharpness_data(img_cv, cache=cache)
        color_data = tech_analyzer.get_color_harmony_data(img_cv, cache=cache)
    """
    __slots__ = ['gray', 'gray_histogram', 'hsv', 'laplacian_variance', 'height', 'width']

    def __init__(self, img_cv):
        """
        Initialize cache with pre-computed transformations.

        Args:
            img_cv: OpenCV BGR image array
        """
        self.height, self.width = img_cv.shape[:2]
        self.gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
        # One exact 256-bin histogram per image: the exposure, dynamic-range and
        # contrast analyzers each used to walk the same 20 MP frame again.
        self.gray_histogram = gray_histogram(self.gray)
        self.hsv = cv2.cvtColor(img_cv, cv2.COLOR_BGR2HSV)
        self.laplacian_variance = laplacian_variance(self.gray)

