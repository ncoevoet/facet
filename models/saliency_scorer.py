"""BiRefNet-based subject saliency detection for Facet.

Uses BiRefNet-dynamic (Bilateral Reference Network, multi-resolution variant)
via HuggingFace transformers to generate binary subject masks, then derives
subject-aware quality metrics:
  - subject_sharpness: Laplacian variance on subject vs background
  - subject_prominence: Subject area as fraction of total frame
  - subject_placement: Rule-of-thirds score for subject centroid
  - bg_separation: Subject/background sharpness ratio
"""

import logging
import numpy as np
from typing import Optional

logger = logging.getLogger("facet.saliency")

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
    """Wrapper around BiRefNet for subject saliency detection."""

    DEFAULT_MODEL = 'ZhengPeng7/BiRefNet_dynamic'
    DEFAULT_RESOLUTION = 1024
    DEFAULT_MASK_THRESHOLD = 0.3
    DEFAULT_MIN_SUBJECT_PIXELS = 50

    def __init__(self, device: Optional[str] = None, model_name: Optional[str] = None,
                 resolution: Optional[int] = None, mask_threshold: Optional[float] = None,
                 min_subject_pixels: Optional[int] = None):
        """Initialize saliency scorer.

        Args:
            device: Device to use ('cuda', 'cpu', or None for auto)
            model_name: HuggingFace model ID (default: ZhengPeng7/BiRefNet-dynamic)
            resolution: Input resolution for BiRefNet (default: 1024)
            mask_threshold: Sigmoid threshold for binary mask (default: 0.3)
            min_subject_pixels: Minimum pixels to consider a subject detected (default: 50)
        """
        _ensure_imports()
        self.device = device or ('cuda' if torch.cuda.is_available() else 'cpu')
        self.model_name = model_name or self.DEFAULT_MODEL
        self.resolution = resolution or self.DEFAULT_RESOLUTION
        self.mask_threshold = mask_threshold if mask_threshold is not None else self.DEFAULT_MASK_THRESHOLD
        self.min_subject_pixels = min_subject_pixels if min_subject_pixels is not None else self.DEFAULT_MIN_SUBJECT_PIXELS
        self.model = None
        self.transform = None
        self._loaded = False

    def load(self):
        """Load BiRefNet model."""
        if self._loaded:
            return

        from transformers import AutoModelForImageSegmentation
        import torchvision.transforms as T

        self.model = AutoModelForImageSegmentation.from_pretrained(
            self.model_name, trust_remote_code=True
        )
        self.model.to(self.device).eval()

        self.transform = T.Compose([
            T.Resize((self.resolution, self.resolution)),
            T.ToTensor(),
            T.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
        ])

        self._loaded = True
        logger.info("BiRefNet saliency model loaded on %s: %s", self.device, self.model_name)

    def unload(self):
        """Unload model to free VRAM."""
        if not self._loaded:
            return

        if self.model is not None:
            del self.model
            self.model = None
        self.transform = None

        self._loaded = False
        _ensure_imports()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        logger.info("  BiRefNet unloaded")

    def get_saliency_mask(self, pil_img):
        """Generate binary saliency mask from PIL image.

        Args:
            pil_img: PIL Image (RGB)

        Returns:
            numpy.ndarray: Binary mask (H, W) with values 0 or 255
        """
        return self.get_saliency_masks([pil_img])[0]

    def get_saliency_masks(self, pil_images, batch_size=8):
        """Generate binary saliency masks for a batch of PIL images.

        Args:
            pil_images: List of PIL Images (RGB)
            batch_size: Max images per GPU forward pass

        Returns:
            List of numpy.ndarray: Binary masks (H, W) with values 0 or 255
        """
        if not self._loaded:
            self.load()

        orig_sizes = [(img.size[0], img.size[1]) for img in pil_images]
        results = []

        for start in range(0, len(pil_images), batch_size):
            chunk = pil_images[start:start + batch_size]
            batch_tensor = torch.stack([self.transform(img) for img in chunk]).to(self.device, dtype=next(self.model.parameters()).dtype)

            with torch.no_grad():
                preds = self.model(batch_tensor)[-1].sigmoid()

            for i, pred in enumerate(preds):
                idx = start + i
                orig_w, orig_h = orig_sizes[idx]
                mask = pred.squeeze().cpu().numpy()
                binary_mask = (mask > self.mask_threshold).astype(np.uint8) * 255

                if binary_mask.shape[0] != orig_h or binary_mask.shape[1] != orig_w:
                    binary_mask = cv2.resize(binary_mask, (orig_w, orig_h), interpolation=cv2.INTER_LINEAR)
                    binary_mask = (binary_mask > 128).astype(np.uint8) * 255

                results.append(binary_mask)

        return results

    def score_image(self, pil_img, img_cv):
        """Compute all saliency-derived metrics for an image.

        Args:
            pil_img: PIL Image (RGB)
            img_cv: OpenCV BGR image array

        Returns:
            dict with keys: subject_sharpness, subject_prominence,
                          subject_placement, bg_separation
        """
        mask = self.get_saliency_mask(pil_img)
        return self._score_from_mask(mask, img_cv)

    def _score_from_mask(self, mask, img_cv):
        """Compute saliency metrics from a pre-computed binary mask.

        Args:
            mask: Binary mask (H, W) with values 0 or 255
            img_cv: OpenCV BGR image array

        Returns:
            dict with keys: subject_sharpness, subject_prominence,
                          subject_placement, bg_separation
        """
        _ensure_imports()

        h, w = mask.shape[:2]
        total_pixels = h * w

        # Subject area ratio
        subject_pixels = np.count_nonzero(mask)
        subject_prominence = subject_pixels / total_pixels if total_pixels > 0 else 0

        # If no subject detected, return defaults
        if subject_pixels < self.min_subject_pixels:  # Minimum subject size
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
            # Multiplier 2.0: ratio >= 5x subject/bg sharpness -> score 10.0.
            # Portraits with shallow DoF typically reach 3-8x ratio; landscapes 0.5-2x.
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
        """Score a batch of images using batched GPU inference.

        Args:
            pil_images: List of PIL Images
            cv_images: List of OpenCV BGR image arrays

        Returns:
            List of score dicts
        """
        if not self._loaded:
            self.load()

        default_scores = {
            'subject_sharpness': 5.0,
            'subject_prominence': 0.0,
            'subject_placement': 5.0,
            'bg_separation': 5.0,
        }

        # Batch mask generation (single GPU forward pass per sub-batch)
        try:
            masks = self.get_saliency_masks(pil_images)
        except Exception as e:
            logger.warning("  Batch saliency mask generation failed: %s", e)
            return [dict(default_scores) for _ in pil_images]

        results = []
        for mask, img_cv in zip(masks, cv_images):
            try:
                result = self._score_from_mask(mask, img_cv)
                results.append(result)
            except Exception as e:
                logger.warning("  Saliency scoring failed: %s", e)
                results.append(dict(default_scores))

        return results

    @property
    def vram_gb(self) -> float:
        """Get estimated VRAM requirement in GB."""
        return 2
