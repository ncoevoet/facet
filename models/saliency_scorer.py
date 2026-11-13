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

from utils.system_memory import BYTES_PER_GB

logger = logging.getLogger("facet.saliency")

# Lazy imports
torch = None
cv2 = None


def _is_u8_plane(mask) -> bool:
    """True for a non-empty 2-D ``uint8`` ndarray, the only mask the cv2 integer path serves.

    Floats, bools, 3-D masks and empty planes keep the numpy code, whose behaviour on them is
    whatever numpy does and is not worth re-deriving.
    """
    return (isinstance(mask, np.ndarray) and mask.dtype == np.uint8 and mask.ndim == 2
            and mask.shape[0] > 0 and mask.shape[1] > 0)


def _foreground_projections(fg):
    """Per-column and per-row foreground pixel counts of a 0/255 ``uint8`` plane.

    ``cv2.reduce`` into ``CV_32S`` sums exact integers, so the counts, their total and the centroid
    derived from them are the same integers ``np.nonzero`` would yield, without materialising two
    int64 index arrays of one entry per foreground pixel.
    """
    colsum = cv2.reduce(fg, 0, cv2.REDUCE_SUM, dtype=cv2.CV_32S).ravel().astype(np.int64) // 255
    rowsum = cv2.reduce(fg, 1, cv2.REDUCE_SUM, dtype=cv2.CV_32S).ravel().astype(np.int64) // 255
    return colsum, rowsum


def _bbox_from_projections(colsum, rowsum, min_subject_pixels):
    """The ``bbox_from_mask`` result from foreground projections (first/last non-empty column and row)."""
    if int(colsum.sum()) < min_subject_pixels:
        return None
    h, w = rowsum.size, colsum.size
    nzx = np.flatnonzero(colsum)
    nzy = np.flatnonzero(rowsum)
    x0 = float(nzx[0]) / w
    y0 = float(nzy[0]) / h
    x1 = float(nzx[-1] + 1) / w
    y1 = float(nzy[-1] + 1) / h
    return [round(x0, 4), round(y0, 4), round(min(x1, 1.0), 4), round(min(y1, 1.0), 4)]


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
    if _is_u8_plane(mask):
        _ensure_cv2()
        assert cv2 is not None
        fg = cv2.threshold(mask, 128, 255, cv2.THRESH_BINARY)[1]
        colsum, rowsum = _foreground_projections(fg)
        return _bbox_from_projections(colsum, rowsum, min_subject_pixels)
    ys, xs = np.nonzero(mask > 128)
    if xs.size < min_subject_pixels:
        return None
    x0 = float(xs.min()) / w
    y0 = float(ys.min()) / h
    x1 = float(xs.max() + 1) / w
    y1 = float(ys.max() + 1) / h
    return [round(x0, 4), round(y0, 4), round(min(x1, 1.0), 4), round(min(y1, 1.0), 4)]


def _ensure_cv2():
    """Import cv2 alone: ``bbox_from_mask`` is used by callers that never load torch."""
    global cv2
    if cv2 is None:
        import cv2 as _cv2
        cv2 = _cv2


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
    # Marginal memory one more image adds to a forward pass at the default
    # 1024 resolution: measured 2.4 GiB reserved on CUDA (issue #184) and on
    # CPU fp32 (issue #111). The same figure sizes both the RAM and VRAM batch.
    ACTIVATION_GB_PER_IMAGE = 2.4
    USABLE_MEMORY_FRACTION = 0.8
    DEDICATED_VRAM_DEVICE = 'cuda'
    # Apple Silicon's unified memory: psutil's "available" reading cannot see
    # what the MPS allocator pool itself holds, so the RAM-derived headroom
    # calculation below is not trustworthy there the way it is on CPU. The
    # model also runs fp32 on this device (see load()), at ~2.4-2.6 GB of
    # activations per image at the default resolution -- the same figure
    # measured for CPU fp32 above. A small fixed ceiling is used instead of
    # a memory-derived one.
    UNIFIED_MEMORY_ACCELERATOR = 'mps'
    UNIFIED_MEMORY_MAX_BATCH = 2
    # Devices that run the checkpoint's native fp16 (see load()).
    HALF_PRECISION_DEVICES = ('cuda', 'mps')

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
        self._warned_vram_unreadable = False

    def load(self):
        """Load BiRefNet, in float32 on CPU and the checkpoint's fp16 on CUDA and MPS.

        The published checkpoint is stored as F16 and its config carries no
        ``torch_dtype``, so transformers loads it half-precision. CPU kernels
        have no fp16 path and fall back to an unvectorised one: measured in a
        container, a 256x256 forward takes 49.97s in fp16 against 1.10s in
        float32, and a single 1024x1024 forward ran for 28 minutes. Casting
        raises the activation memory of a CPU forward (about 2.4 GiB per
        image at 1024 px, the figure ``ACTIVATION_GB_PER_IMAGE`` is sized
        from), which is why the batch size derived in
        :meth:`_affordable_batch_size` is sized from the float32 slope. CUDA
        keeps the checkpoint's fp16 and reserves about the same 2.4 GiB per
        image at 1024 px.

        Apple's MPS keeps fp16 too. Float32 there is not merely slower: its
        activations outgrow what the Metal allocator serves quickly, and the
        forward pass falls off a cliff. Measured on an M4 Pro (24 GB) with
        12 MP photos at 1024 px, per image: float32 0.9 s at batch 1, 1.3-1.6 s
        at batch 2, 9.1 s at batch 4, and 15 s for the batch of one that
        followed; fp16 0.74-0.88 s at every batch size. The fp16 mask
        matched the float32 one at IoU 0.994.
        """
        if self._loaded:
            return

        from transformers import AutoModelForImageSegmentation
        import torchvision.transforms as T

        self.model = AutoModelForImageSegmentation.from_pretrained(
            self.model_name, trust_remote_code=True
        )
        if not self.device.startswith(self.HALF_PRECISION_DEVICES):
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
            numpy.ndarray: Binary mask (H, W) with values 0 or 255, or
            ``None`` when the single image cannot fit in memory even alone
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

        A dedicated-VRAM device is sized from free VRAM, not host RAM: on CUDA
        the activations land in VRAM, which no cgroup limit governs. The free
        figure is ``mem_get_info`` plus the torch cache this process already
        holds (reserved minus allocated), which the next forward pass reuses.
        The per-image cost grows with the square of the resolution above 1024
        and is never priced below the measured figure. A 12 GB card capped to
        11.7 GiB OOMs at the old fixed batch of 8 and passes at 2 (issue
        #184). If ``mem_get_info`` itself fails the ceiling is used, with one
        WARNING, because the retry in :meth:`get_saliency_masks` still bounds
        the damage. CPU spends the very RAM ``effective_memory`` reports,
        container limit included. Apple's unified memory (MPS) is sized from
        that reading too, but under a small fixed ceiling,
        ``UNIFIED_MEMORY_MAX_BATCH``: the MPS allocator keeps its own pool
        that psutil's "available" figure cannot see, so a scan can read
        plenty of headroom while the pool itself is already large.

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
            return self._affordable_vram_batch_size(ceiling)
        if self.device.startswith(self.UNIFIED_MEMORY_ACCELERATOR):
            ceiling = min(ceiling, self.UNIFIED_MEMORY_MAX_BATCH)
        from utils.system_memory import effective_memory
        spare_gb = effective_memory().available * self.USABLE_MEMORY_FRACTION / BYTES_PER_GB
        affordable = int(spare_gb // self.ACTIVATION_GB_PER_IMAGE)
        return max(self.MIN_BATCH_SIZE, min(ceiling, affordable))

    def _affordable_vram_batch_size(self, ceiling):
        """Batch size that fits the free VRAM of ``self.device``, bounded by ``ceiling``."""
        try:
            free_bytes = torch.cuda.mem_get_info(self.device)[0]
            cached_bytes = (torch.cuda.memory_reserved(self.device)
                            - torch.cuda.memory_allocated(self.device))
        except Exception as e:
            if not self._warned_vram_unreadable:
                self._warned_vram_unreadable = True
                logger.warning("  Cannot read free VRAM on %s (%s); using saliency batch size %d",
                               self.device, e, ceiling)
            return ceiling
        spare_gb = (free_bytes + max(0, cached_bytes)) * self.USABLE_MEMORY_FRACTION / BYTES_PER_GB
        per_image_gb = self.ACTIVATION_GB_PER_IMAGE * max(1, self.resolution / self.DEFAULT_RESOLUTION) ** 2
        return max(self.MIN_BATCH_SIZE, min(ceiling, int(spare_gb / per_image_gb)))

    def get_saliency_masks(self, pil_images, batch_size=None):
        """Generate binary saliency masks for a batch of PIL images.

        Args:
            pil_images: List of PIL Images (RGB)
            batch_size: Ceiling on images per forward pass. None asks for the
                default ceiling; either way the answer is bounded by the
                memory the activations land in -- see
                :meth:`_affordable_batch_size`.

        An out-of-memory error (CUDA or MPS, see ``is_out_of_memory_error``)
        halves the failing sub-batch and retries, down to one image. An image
        that does not fit even alone gets ``None`` in its slot; every other
        image keeps its mask and the list stays aligned with ``pil_images``.

        Returns:
            List aligned with ``pil_images``: binary masks (H, W) with values
            0 or 255, or ``None`` for an image that ran out of memory alone
        """
        results = []
        for sub_batch in self.iter_mask_batches(pil_images, batch_size):
            results.extend(sub_batch)
        return results

    def iter_mask_batches(self, pil_images, batch_size=None):
        """Yield the masks of ``pil_images`` one sub-batch at a time, in order.

        Same forward passes, in the same order and at the same sub-batch size, as
        :meth:`get_saliency_masks` (which is the concatenation of what this yields);
        the difference is that a caller can score and drop each sub-batch before the
        next forward pass, so a chunk's masks are never all alive at once. Loading the
        model and sizing the sub-batch happen here, once, before the first yield; a
        mask-generation error surfaces from the iterator when the failing sub-batch is
        reached. The "batch reduced" warning is logged when the iterator is exhausted.
        """
        if not self._loaded:
            self.load()

        batch_size = self._affordable_batch_size(batch_size)
        logger.debug("  Saliency batch size %d for %d image(s) on %s",
                     batch_size, len(pil_images), self.device)
        return self._mask_batches(pil_images, batch_size)

    def _mask_batches(self, pil_images, batch_size):
        """The generator behind :meth:`iter_mask_batches` (``batch_size`` already resolved)."""
        orig_sizes = [(img.size[0], img.size[1]) for img in pil_images]
        reduced_to = []

        for start in range(0, len(pil_images), batch_size):
            yield self._masks_with_oom_retry(
                pil_images[start:start + batch_size],
                orig_sizes[start:start + batch_size],
                reduced_to)

        if reduced_to:
            logger.warning("  Saliency batch reduced to %d after out-of-memory", min(reduced_to))

    def _masks_with_oom_retry(self, chunk, sizes, reduced_to):
        """Masks for one chunk, halving it on an out-of-memory error down to one image.

        An image that still does not fit alone yields ``None`` in its slot, so the
        list stays aligned with ``chunk`` and its neighbours keep their masks.
        Any other exception propagates unretried.
        """
        from utils.device import clear_device_cache, is_out_of_memory_error

        try:
            return self._run_chunk(chunk, sizes)
        except Exception as e:
            if not is_out_of_memory_error(e):
                raise
        # Reaching here means the chunk ran out of memory. The cache is cleared and
        # the halves run out here, not inside the handler: the live exception's
        # traceback holds the failed activations, so freeing from within the
        # except block would release nothing.
        clear_device_cache(self.device)
        if len(chunk) == 1:
            return [None]
        half = len(chunk) // 2
        reduced_to.append(half)
        return (self._masks_with_oom_retry(chunk[:half], sizes[:half], reduced_to)
                + self._masks_with_oom_retry(chunk[half:], sizes[half:], reduced_to))

    def _run_chunk(self, chunk, sizes):
        """One forward pass over ``chunk``, returning a binary mask per image at its original size."""
        batch_tensor = torch.stack([self.transform(img) for img in chunk]).to(
            self.device, dtype=next(self.model.parameters()).dtype)

        with torch.no_grad():
            preds = self.model(batch_tensor)[-1].sigmoid()

        masks = []
        for pred, (orig_w, orig_h) in zip(preds, sizes):
            mask = pred.squeeze().cpu().numpy()
            binary_mask = (mask > self.mask_threshold).astype(np.uint8) * 255

            if binary_mask.shape[0] != orig_h or binary_mask.shape[1] != orig_w:
                binary_mask = cv2.resize(binary_mask, (orig_w, orig_h), interpolation=cv2.INTER_LINEAR)
                binary_mask = (binary_mask > 128).astype(np.uint8) * 255

            masks.append(binary_mask)
        return masks

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
        if mask is None:
            return self._failed_scores()
        return self._score_from_mask(mask, img_cv)

    @staticmethod
    def _failed_scores():
        """The all-None result for a photo whose saliency could not be computed."""
        return {
            'subject_sharpness': None,
            'subject_prominence': None,
            'subject_placement': None,
            'bg_separation': None,
            'subject_bbox': None,
        }

    def _score_from_mask(self, mask, img_cv):
        """Compute saliency metrics from a pre-computed binary mask.

        Args:
            mask: Binary mask (H, W) with values 0 or 255
            img_cv: OpenCV BGR image array, or a 2-D gray plane

        Returns:
            dict with keys: subject_sharpness, subject_prominence,
                          subject_placement, bg_separation, subject_bbox

        A 2-D ``uint8`` mask (binary or not) is scored with cv2 integer arithmetic;
        anything else (float, bool, 3-D) takes the numpy code. Both give the same
        dict for the same input. Both keep the thresholds the numpy code has always
        had, and they differ: prominence and the ``min_subject_pixels`` gate count every
        NON-ZERO mask value, while the subject/background regions, the centroid and
        the bounding box use ``mask > 128`` (so a mask holding only values in 1..128
        passes the gate with an empty subject region). Do not unify them: that would
        change stored scores.
        """
        _ensure_imports()

        h, w = mask.shape[:2]
        total_pixels = h * w
        fast_mask = _is_u8_plane(mask)

        # Subject area ratio: any non-zero value counts. int(): since NumPy 2.3,
        # np.count_nonzero returns np.int64, which made prominence an np.float64
        # on the numpy route while cv2's route (and every other metric) is a float.
        subject_pixels = cv2.countNonZero(mask) if fast_mask else int(np.count_nonzero(mask))
        subject_prominence = subject_pixels / total_pixels if total_pixels > 0 else 0

        # No subject detected: prominence 0.0 is a real measurement, the three metrics
        # that need a subject have no value, and None says so (a stored 5.0 was a
        # made-up score that range filters and statistics could not tell from a real one).
        # Not the all-None failure signature: a failed photo has a None prominence too.
        if subject_pixels < self.min_subject_pixels:  # Minimum subject size
            return {
                'subject_sharpness': None,
                'subject_prominence': 0.0,
                'subject_placement': None,
                'bg_separation': None,
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

        if fast_mask and gray.dtype == np.uint8:
            fg = cv2.threshold(mask, 128, 255, cv2.THRESH_BINARY)[1]   # == (mask > 128) as 0/255
            subject_variance, bg_variance = self._region_variances(gray, fg, total_pixels)
            colsum, rowsum = _foreground_projections(fg)
            subject_placement = self._placement_from_projections(colsum, rowsum)
            subject_bbox = _bbox_from_projections(colsum, rowsum, self.min_subject_pixels)
        else:
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

            # Subject placement: rule-of-thirds scoring for subject centroid
            subject_placement = self._compute_placement_score(mask, h, w)
            subject_bbox = bbox_from_mask(mask, self.min_subject_pixels)

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

        # Normalize prominence to 0-10 scale
        prominence_score = min(10.0, subject_prominence * 20.0)  # 50% coverage = 10.0

        return {
            'subject_sharpness': round(subject_sharpness, 2),
            'subject_prominence': round(prominence_score, 2),
            'subject_placement': round(subject_placement, 2),
            'bg_separation': round(bg_separation, 2),
            'subject_bbox': subject_bbox,
        }

    @staticmethod
    def _masked_variance(lap, mask, n):
        """Population variance of the CV_16S plane ``lap`` over the ``n`` pixels set in ``mask``.

        ``cv2.meanStdDev`` multiplies its integer sums by ``1/n`` instead of dividing, so the
        mean of ``n`` equal values is not that value (49 ones give 0.9999999999999999) and a
        constant non-zero region reports a std of about 1e-8 where ``np.var`` gives exactly 0.
        A variance that small is cancellation noise, not signal, and the caller branches on
        ``variance > 0``, so it is recomputed from exact integer sums: ``n * sum(x^2) -
        sum(x)^2`` is zero if and only if the region is constant, and ``sum(x^2)`` stays below
        2**53 (the Laplacian is within +-2040) so every cv2 sum is exact. Any other region keeps
        the fast value, which agrees with ``np.var`` to about 1e-15 relative.
        """
        mean, std = cv2.meanStdDev(lap, mask=mask)
        variance = float(std[0][0]) ** 2
        mean = float(mean[0][0])
        if variance > 1e-13 * (mean * mean + variance) + 1e-12:
            return variance
        inside = cv2.bitwise_and(lap, lap, mask=mask)
        total = int(cv2.sumElems(inside)[0])
        total_sq = int(cv2.sumElems(cv2.multiply(inside, inside, dtype=cv2.CV_32S))[0])
        return (n * total_sq - total * total) / (n * n)

    @staticmethod
    def _region_variances(gray, fg, total_pixels):
        """Laplacian variance over the subject (``fg``) and over everything else.

        The Laplacian of a uint8 plane is an integer in [-2040, 2040], so ``CV_16S`` holds
        exactly the values ``CV_64F`` would; only the summation order of the variance
        differs from ``np.var`` (relative 1e-15, far below the 2-decimal rounding the
        callers apply). A region with no pixels has variance 0, as before, and a constant
        region gives exactly 0.0 (see ``_masked_variance``).
        """
        lap = cv2.Laplacian(gray, cv2.CV_16S)
        n_subject = cv2.countNonZero(fg)
        if n_subject > 0:
            subject_variance = SaliencyScorer._masked_variance(lap, fg, n_subject)
        else:
            subject_variance = 0.0
        if total_pixels - n_subject > 0:
            bg_variance = SaliencyScorer._masked_variance(
                lap, cv2.bitwise_not(fg), total_pixels - n_subject)
        else:
            bg_variance = 0.0
        return subject_variance, bg_variance

    @staticmethod
    def _placement_from_centroid(cx, cy):
        """Rule-of-thirds score for a normalised centroid (0-10, 10 = on a power point)."""
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
        return max(0.0, 10.0 * (1.0 - min_dist / max_dist))

    def _placement_from_projections(self, colsum, rowsum):
        """Placement score from foreground column/row counts; 5.0 when there is no foreground.

        ``sum(count * index)`` is the exact integer sum ``np.mean`` accumulates (it stays far
        below 2**53, so the float64 sum was exact too) and the division is the same single
        correctly-rounded one, so the centroid is bit-identical to the numpy one.
        """
        n = int(colsum.sum())
        if n == 0:
            return 5.0
        w, h = colsum.size, rowsum.size
        sum_x = int(np.dot(colsum, np.arange(w, dtype=np.int64)))
        sum_y = int(np.dot(rowsum, np.arange(h, dtype=np.int64)))
        return self._placement_from_centroid(float(sum_x / n) / w, float(sum_y / n) / h)

    def _compute_placement_score(self, mask, h, w):
        """Compute rule-of-thirds placement score for subject centroid (numpy path).

        Args:
            mask: Mask (H, W); foreground is ``mask > 128``
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
        return self._placement_from_centroid(cx, cy)

    def score_batch(self, pil_images, cv_images):
        """Score a batch of images using batched GPU inference.

        Args:
            pil_images: List of PIL Images
            cv_images: One entry per image: an OpenCV BGR array, a 2-D gray plane, or a
                zero-argument callable returning either. A callable is invoked only when
                that image has a mask, immediately before it is scored, and its result is
                dropped right after, so a caller that rebuilds the plane from the retained
                PIL image never holds more than one at a time.

        Masks are scored as each sub-batch arrives and released before the next forward
        pass, so at most one sub-batch of masks is alive.

        Returns:
            List of score dicts. A photo whose saliency could not be computed
            gets a dict of ``None`` values: a failure is never stored as a score.
        """
        if not self._loaded:
            self.load()

        failed = self._failed_scores()
        n = len(pil_images)

        results = []
        try:
            batches = self.iter_mask_batches(pil_images)
            offset = 0
            while True:
                # next() must run with no sub-batch of masks still referenced from here
                sub_batch = next(batches, None)
                if sub_batch is None:
                    break
                count = len(sub_batch)
                self._score_sub_batch(sub_batch, cv_images[offset:offset + count],
                                      results, failed, n)
                offset += count
                sub_batch = None
        except Exception as e:
            # A mask-generation failure fails the whole call, including sub-batches already scored
            logger.error("  Batch saliency mask generation failed for batch size %d: %s", n, e)
            return [dict(failed) for _ in pil_images]

        # The failure signature is all-None; a no-subject photo has prominence 0.0
        lost = sum(1 for r in results if r['subject_prominence'] is None)
        if lost:
            logger.error("  Saliency failed for %d of %d image(s) in this batch (batch size %d); "
                         "their saliency columns are left unset", lost, n, n)
        return results

    def _score_sub_batch(self, masks, cv_images, results, failed, n):
        """Score one sub-batch's masks into ``results``, emptying ``masks`` as it goes."""
        for i, img_cv in enumerate(cv_images):
            mask, masks[i] = masks[i], None
            if mask is None:
                results.append(dict(failed))
                continue
            try:
                if callable(img_cv):
                    img_cv = img_cv()
                results.append(self._score_from_mask(mask, img_cv))
            except Exception as e:
                logger.error("  Saliency scoring failed for batch size %d: %s", n, e)
                results.append(dict(failed))
            mask = img_cv = None
        masks.clear()

    @property
    def vram_gb(self) -> float:
        """Get estimated VRAM requirement in GB."""
        return 3
