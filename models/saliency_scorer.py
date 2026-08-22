"""BiRefNet-based subject saliency detection for Facet.

Uses BiRefNet_dynamic (Bilateral Reference Network, multi-resolution variant)
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

BYTES_PER_GB = 1024 ** 3

# Lazy imports
torch = None
cv2 = None


def bbox_from_mask(mask, min_subject_pixels: int = 50):
    """Extract the subject bounding box from a binary saliency mask.

    Args:
        mask: Binary mask (H, W) with foreground pixels > 128.
        min_subject_pixels: Minimum foreground pixel count to report a box.

    Returns:
        ``[x0, y0, x1, y1]`` normalized to 0..1 (rounded to 4 decimals), or None
        when the mask holds fewer than ``min_subject_pixels`` foreground pixels.
    """
    h, w = mask.shape[:2]
    if h == 0 or w == 0:
        return None
    ys, xs = np.nonzero(mask > 128)
    if xs.size < min_subject_pixels:
        return None
    x0 = float(xs.min()) / w
    y0 = float(ys.min()) / h
    x1 = float(xs.max() + 1) / w
    y1 = float(ys.max() + 1) / h
    return [round(x0, 4), round(y0, 4), round(min(x1, 1.0), 4), round(min(y1, 1.0), 4)]


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
    DEFAULT_BATCH_SIZE = 8
    MIN_BATCH_SIZE = 1
    ACTIVATION_GB_PER_IMAGE = 2.4
    USABLE_MEMORY_FRACTION = 0.8
    DEDICATED_VRAM_DEVICE = 'cuda'

    def __init__(self, device: Optional[str] = None, model_name: Optional[str] = None,
                 resolution: Optional[int] = None, mask_threshold: Optional[float] = None,
                 min_subject_pixels: Optional[int] = None):
        """Initialize saliency scorer.

        Args:
            device: Device to use ('cuda', 'cpu', or None for auto)
            model_name: HuggingFace model ID (default: ZhengPeng7/BiRefNet_dynamic)
            resolution: Input resolution for BiRefNet (default: 1024)
            mask_threshold: Sigmoid threshold for binary mask (default: 0.3)
            min_subject_pixels: Minimum pixels to consider a subject detected (default: 50)
        """
        _ensure_imports()
        if device is None:
            from utils.device import get_device
            device = get_device()
        self.device = device
        self.model_name = model_name or self.DEFAULT_MODEL
        self.resolution = resolution or self.DEFAULT_RESOLUTION
        self.mask_threshold = mask_threshold if mask_threshold is not None else self.DEFAULT_MASK_THRESHOLD
        self.min_subject_pixels = min_subject_pixels if min_subject_pixels is not None else self.DEFAULT_MIN_SUBJECT_PIXELS
        self.model = None
        self.transform = None
        self._loaded = False

    def load(self):
        """Load BiRefNet, in float32 anywhere without a dedicated GPU.

        The published checkpoint is stored as F16 and its config carries no
        ``torch_dtype``, so transformers loads it half-precision. CPU kernels
        have no fp16 path and fall back to an unvectorised one: measured in a
        container, a 256x256 forward takes 49.97s in fp16 against 1.10s in
        float32, and a single 1024x1024 forward ran for 28 minutes. Casting
        doubles activation memory, which is why the batch size derived in
        :meth:`_affordable_batch_size` is sized from the float32 slope.
        """
        if self._loaded:
            return

        from transformers import AutoModelForImageSegmentation
        import torchvision.transforms as T

        self.model = AutoModelForImageSegmentation.from_pretrained(
            self.model_name, trust_remote_code=True
        )
        if not self.device.startswith(self.DEDICATED_VRAM_DEVICE):
            self.model = self.model.float()
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
        from utils.device import clear_device_cache
        clear_device_cache(self.device)
        logger.info("  BiRefNet unloaded")

    def get_saliency_mask(self, pil_img):
        """Generate binary saliency mask from PIL image.

        Args:
            pil_img: PIL Image (RGB)

        Returns:
            numpy.ndarray: Binary mask (H, W) with values 0 or 255
        """
        return self.get_saliency_masks([pil_img])[0]

    def _affordable_batch_size(self, requested):
        """How many images one forward pass may hold, given where they land.

        BiRefNet's activations dwarf its weights. Measured inside a container
        against cgroup ``anon``, at the default 1024x1024 on CPU, one image
        peaks at 2.60 GB and each further image adds 2.32 GB (fp32; the fp16
        checkpoint costs about three quarters of that) -- against weights of
        0.36 GB. A fixed batch of 8 therefore asks for roughly 18 GB whatever
        the budget says, which is how an 8 GiB container was still OOM-killed
        after the pass planner had been taught to read its real limit
        (issue #111): the planner prices declared model weight, and none of
        this is weight. ``ACTIVATION_GB_PER_IMAGE`` takes the larger, fp32
        figure so that the dtype a checkpoint happens to carry is not what
        decides whether the container survives.

        ``requested`` is a ceiling, never a floor. The defect being fixed is
        a batch size that ignores the budget, so an explicit argument may
        only narrow the batch -- which is also all the parameter has ever
        claimed to be, a maximum per forward pass.

        Only a dedicated-VRAM device escapes the bound. On CUDA the
        activations are allocated in VRAM, which no cgroup limit governs, so
        sizing that batch against host RAM would throttle a GPU run for
        memory it never touches. CPU and Apple's unified memory both spend
        the very RAM ``effective_memory`` reports, container limit included.

        The fifth of the reading left unclaimed is not a round number picked
        for comfort. What this call adds beyond the activations is one mask
        per image of the WHOLE chunk, held until every sub-batch is done --
        about 18 MB per 18 MP photo, so roughly a sixth of what the chunk's
        decoded pixels already cost. That cost is proportional to memory
        already spent, which a proportional margin tracks and a fixed reserve
        does not. Measured on the 8 GiB container, same 12 photos: claiming
        all of the reading peaks at 7.24 GB, 90.5% of the limit; claiming
        four fifths peaks at 4.85 GB.

        ``UNKNOWN_MEMORY`` -- neither psutil nor the cgroup files readable --
        reports nothing available and so yields ``MIN_BATCH_SIZE``, because
        the absence of an answer is not headroom. That minimum is a floor,
        not a promise: one 1024x1024 image needs about 2.6 GB and there is
        nothing smaller to fall back to but a lower ``resolution``, which is
        the caller's setting to make. The figures above are for that default
        resolution, the only one measured, so a smaller one is merely
        budgeted conservatively rather than wrongly.
        """
        ceiling = self.DEFAULT_BATCH_SIZE if requested is None else max(self.MIN_BATCH_SIZE, requested)
        if self.device.startswith(self.DEDICATED_VRAM_DEVICE):
            return ceiling
        from utils.system_memory import effective_memory
        spare_gb = effective_memory().available * self.USABLE_MEMORY_FRACTION / BYTES_PER_GB
        affordable = int(spare_gb // self.ACTIVATION_GB_PER_IMAGE)
        return max(self.MIN_BATCH_SIZE, min(ceiling, affordable))

    def get_saliency_masks(self, pil_images, batch_size=None):
        """Generate binary saliency masks for a batch of PIL images.

        Args:
            pil_images: List of PIL Images (RGB)
            batch_size: Ceiling on images per forward pass. None asks for the
                default ceiling; either way the answer is bounded by the
                memory the activations land in -- see
                :meth:`_affordable_batch_size`.

        Returns:
            List of numpy.ndarray: Binary masks (H, W) with values 0 or 255
        """
        if not self._loaded:
            self.load()

        batch_size = self._affordable_batch_size(batch_size)
        logger.debug("  Saliency batch size %d for %d image(s) on %s",
                     batch_size, len(pil_images), self.device)

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

    def get_saliency_soft(self, pil_img):
        """Return the pre-threshold saliency map (float32 0..1) sized to the image.

        Unlike get_saliency_mask (binarized), this exposes the soft sigmoid so the
        viewer can render a smooth heatmap overlay.
        """
        if not self._loaded:
            self.load()

        orig_w, orig_h = pil_img.size
        batch_tensor = torch.stack([self.transform(pil_img)]).to(
            self.device, dtype=next(self.model.parameters()).dtype)
        with torch.no_grad():
            pred = self.model(batch_tensor)[-1].sigmoid()[0]
        soft = pred.squeeze().cpu().numpy().astype(np.float32)
        if soft.shape[0] != orig_h or soft.shape[1] != orig_w:
            soft = cv2.resize(soft, (orig_w, orig_h), interpolation=cv2.INTER_LINEAR)
        return soft

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
                'subject_bbox': None,
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
            'subject_bbox': bbox_from_mask(mask, self.min_subject_pixels),
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
            'subject_bbox': None,
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
