"""InSPyReNet-based subject saliency detection for Facet.

Uses the transparent-background library (InSPyReNet) to generate binary
subject masks, then derives subject-aware quality metrics:
  - subject_sharpness: Laplacian variance on subject vs background
  - subject_prominence: Subject area as fraction of total frame
  - subject_placement: Rule-of-thirds score for subject centroid
  - bg_separation: Subject/background sharpness ratio
"""

import numpy as np
from typing import Optional

# Lazy imports
torch = None
cv2 = None


def _ensure_imports():
    global torch, cv2
    if torch is None:
        import torch as _torch
        import cv2 as _cv2
        torch = _torch
        cv2 = _cv2


class SaliencyScorer:
    """Wrapper around InSPyReNet for subject saliency detection."""

    def __init__(self, device: Optional[str] = None):
        """Initialize saliency scorer.

        Args:
            device: Device to use ('cuda', 'cpu', or None for auto)
        """
        _ensure_imports()
        self.device = device or ('cuda' if torch.cuda.is_available() else 'cpu')
        self.remover = None
        self._loaded = False

    def load(self):
        """Load InSPyReNet model."""
        if self._loaded:
            return

        try:
            from transparent_background import Remover
            self.remover = Remover(mode='base', device=self.device)
            self._loaded = True
            print(f"InSPyReNet saliency model loaded on {self.device}")
        except ImportError:
            raise ImportError(
                "transparent-background is required for saliency detection. "
                "Install with: pip install transparent-background"
            )

    def unload(self):
        """Unload model to free VRAM."""
        if not self._loaded:
            return

        if self.remover is not None:
            del self.remover
            self.remover = None

        self._loaded = False
        _ensure_imports()
        torch.cuda.empty_cache()
        print("  InSPyReNet unloaded")

    def get_saliency_mask(self, pil_img):
        """Generate binary saliency mask from PIL image.

        Args:
            pil_img: PIL Image (RGB)

        Returns:
            numpy.ndarray: Binary mask (H, W) with values 0 or 255
        """
        if not self._loaded:
            self.load()

        # transparent-background returns RGBA image with alpha as mask
        result = self.remover.process(pil_img, type='map')
        # result is a PIL Image in grayscale (saliency map)
        mask = np.array(result)
        if mask.ndim == 3:
            mask = mask[:, :, 0]  # Take first channel if RGB

        # Binarize at 128 threshold
        binary_mask = (mask > 128).astype(np.uint8) * 255
        return binary_mask

    def score_image(self, pil_img, img_cv):
        """Compute all saliency-derived metrics for an image.

        Args:
            pil_img: PIL Image (RGB)
            img_cv: OpenCV BGR image array

        Returns:
            dict with keys: subject_sharpness, subject_prominence,
                          subject_placement, bg_separation
        """
        _ensure_imports()

        mask = self.get_saliency_mask(pil_img)
        h, w = mask.shape[:2]
        total_pixels = h * w

        # Subject area ratio
        subject_pixels = np.count_nonzero(mask)
        subject_prominence = subject_pixels / total_pixels if total_pixels > 0 else 0

        # If no subject detected, return defaults
        if subject_pixels < 100:  # Minimum subject size
            return {
                'subject_sharpness': 5.0,
                'subject_prominence': 0.0,
                'subject_placement': 5.0,
                'bg_separation': 5.0,
            }

        # Convert to grayscale for Laplacian
        if img_cv.ndim == 3:
            gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
        else:
            gray = img_cv

        # Resize gray to mask dimensions if needed
        if gray.shape[:2] != mask.shape[:2]:
            gray = cv2.resize(gray, (w, h))

        # Compute Laplacian (edge/sharpness detector)
        laplacian = cv2.Laplacian(gray, cv2.CV_64F)

        # Subject sharpness: Laplacian variance on subject region
        subject_mask_bool = mask > 128
        bg_mask_bool = ~subject_mask_bool

        subject_laplacian = laplacian[subject_mask_bool]
        subject_variance = float(np.var(subject_laplacian)) if len(subject_laplacian) > 0 else 0

        # Background sharpness for separation metric
        bg_laplacian = laplacian[bg_mask_bool]
        bg_variance = float(np.var(bg_laplacian)) if len(bg_laplacian) > 0 else 0

        # Normalize subject sharpness to 0-10 (typical range 0-5000)
        subject_sharpness = min(10.0, (subject_variance ** 0.5) / 7.0)

        # Background separation: ratio of subject to background sharpness
        # Higher ratio = better bokeh/subject isolation
        if bg_variance > 0:
            separation_ratio = subject_variance / (bg_variance + 1e-6)
            # Multiplier 2.0: ratio >= 5× subject/bg sharpness → score 10.0.
            # Portraits with shallow DoF typically reach 3-8× ratio; landscapes 0.5-2×.
            # Adjust multiplier here if scores cluster at the ceiling after calibration runs.
            bg_separation = min(10.0, separation_ratio * 2.0)
        else:
            bg_separation = 10.0  # Perfect separation (no background detail)

        # Subject placement: rule-of-thirds scoring for subject centroid
        subject_placement = self._compute_placement_score(mask, h, w)

        # Normalize prominence to 0-10 scale
        prominence_score = min(10.0, subject_prominence * 20.0)  # 50% coverage = 10.0

        return {
            'subject_sharpness': round(subject_sharpness, 2),
            'subject_prominence': round(prominence_score, 2),
            'subject_placement': round(subject_placement, 2),
            'bg_separation': round(bg_separation, 2),
        }

    def _compute_placement_score(self, mask, h, w):
        """Compute rule-of-thirds placement score for subject centroid.

        Args:
            mask: Binary mask (H, W)
            h: Image height
            w: Image width

        Returns:
            float: Placement score 0-10 (10 = centroid on power point)
        """
        # Find subject centroid
        ys, xs = np.nonzero(mask > 128)
        if len(xs) == 0:
            return 5.0

        cx = float(np.mean(xs)) / w
        cy = float(np.mean(ys)) / h

        # Rule-of-thirds power points
        thirds_x = [1/3, 2/3]
        thirds_y = [1/3, 2/3]

        # Find minimum distance to any power point
        min_dist = float('inf')
        for tx in thirds_x:
            for ty in thirds_y:
                dist = ((cx - tx) ** 2 + (cy - ty) ** 2) ** 0.5
                min_dist = min(min_dist, dist)

        # Max possible distance from a power point is ~0.47 (corner to center third)
        # Score: closer to power point = higher score
        max_dist = 0.47
        score = max(0.0, 10.0 * (1.0 - min_dist / max_dist))

        return score

    def score_batch(self, pil_images, cv_images):
        """Score a batch of images.

        Args:
            pil_images: List of PIL Images
            cv_images: List of OpenCV BGR image arrays

        Returns:
            List of score dicts
        """
        if not self._loaded:
            self.load()

        results = []
        for pil_img, img_cv in zip(pil_images, cv_images):
            try:
                result = self.score_image(pil_img, img_cv)
                results.append(result)
            except Exception as e:
                print(f"  Warning: Saliency scoring failed: {e}")
                results.append({
                    'subject_sharpness': 5.0,
                    'subject_prominence': 0.0,
                    'subject_placement': 5.0,
                    'bg_separation': 5.0,
                })

        return results

    @property
    def vram_gb(self) -> float:
        """Get estimated VRAM requirement in GB."""
        return 2
