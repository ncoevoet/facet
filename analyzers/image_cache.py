"""
Image cache for pre-computed transformations.
"""

import cv2

class ImageCache:
    """
    Pre-computes and caches commonly needed image transformations.

    Creating grayscale/HSV conversions and Laplacian variance once per image
    avoids redundant computation across multiple analyzer methods.

    Usage:
        cache = ImageCache(img_cv)
        sharpness_data = tech_analyzer.get_sharpness_data(img_cv, cache=cache)
        color_data = tech_analyzer.get_color_harmony_data(img_cv, cache=cache)
    """
    __slots__ = ['gray', 'hsv', 'laplacian_variance', 'height', 'width']

    def __init__(self, img_cv):
        """
        Initialize cache with pre-computed transformations.

        Args:
            img_cv: OpenCV BGR image array
        """
        self.height, self.width = img_cv.shape[:2]
        self.gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
        self.hsv = cv2.cvtColor(img_cv, cv2.COLOR_BGR2HSV)
        self.laplacian_variance = cv2.Laplacian(self.gray, cv2.CV_64F).var()

