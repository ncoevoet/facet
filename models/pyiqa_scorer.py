"""PyIQA-based image quality assessment models.

Wrapper for pyiqa library models including TOPIQ, TOPIQ-IAA, TOPIQ-NR-Face,
HyperIQA, DBCNN, MUSIQ, and LIQE.
These models provide excellent quality assessment with low VRAM usage.
"""

import logging
import torch
import numpy as np
from PIL import Image
from typing import Optional

logger = logging.getLogger("facet.pyiqa")

# Lazy import to avoid loading pyiqa unless needed
pyiqa = None


def _ensure_pyiqa():
    """Lazy load pyiqa library."""
    global pyiqa
    if pyiqa is None:
        try:
            # imgaug (pyiqa dep) uses np.sctypes removed in NumPy 2.0
            if not hasattr(np, 'sctypes'):
                np.sctypes = {
                    'float': [np.float16, np.float32, np.float64],
                    'int': [np.int8, np.int16, np.int32, np.int64],
                    'uint': [np.uint8, np.uint16, np.uint32, np.uint64],
                    'complex': [np.complex64, np.complex128],
                    'others': [bool, object, bytes, str, np.void],
                }
            import pyiqa as _pyiqa
            pyiqa = _pyiqa
        except ImportError:
            raise ImportError(
                "pyiqa is required for TOPIQ/HyperIQA/DBCNN/MUSIQ models. "
                "Install with: pip install pyiqa"
            )
    return pyiqa


# Model info: name, pyiqa_id, vram_gb, lower_is_better, score_range
PYIQA_MODELS = {
    'topiq': {
        'pyiqa_id': 'topiq_nr',
        'vram_gb': 2,
        'lower_better': False,
        'score_range': (0, 1),  # Normalized 0-1
        'description': 'TOPIQ NR - Best accuracy, ResNet50 backbone',
    },
    'hyperiqa': {
        'pyiqa_id': 'hyperiqa',
        'vram_gb': 2,
        'lower_better': False,
        'score_range': (0, 1),
        'description': 'HyperIQA - Very efficient, good accuracy',
    },
    'dbcnn': {
        'pyiqa_id': 'dbcnn',
        'vram_gb': 2,
        'lower_better': False,
        'score_range': (0, 1),
        'description': 'DBCNN - Dual-branch CNN',
    },
    'musiq': {
        'pyiqa_id': 'musiq',
        'vram_gb': 2,
        'lower_better': False,
        'score_range': (0, 100),  # MUSIQ outputs 0-100
        'description': 'MUSIQ - Multi-scale, handles any resolution',
    },
    'musiq-koniq': {
        'pyiqa_id': 'musiq-koniq',
        'vram_gb': 2,
        'lower_better': False,
        'score_range': (0, 100),
        'description': 'MUSIQ trained on KonIQ-10k',
    },
    'clipiqa+': {
        'pyiqa_id': 'clipiqa+',
        'vram_gb': 4,
        'lower_better': False,
        'score_range': (0, 1),
        'description': 'CLIP-IQA+ with learned prompts',
    },
    'topiq_iaa': {
        'pyiqa_id': 'topiq_iaa',
        'vram_gb': 2,
        'lower_better': False,
        'score_range': (1, 10),  # AVA MOS scale (1-10)
        'description': 'TOPIQ IAA - AVA-trained aesthetic merit scoring',
    },
    'topiq_nr_face': {
        'pyiqa_id': 'topiq_nr-face',
        'vram_gb': 2,
        'lower_better': False,
        'score_range': (0, 1),
        'description': 'TOPIQ NR-Face - Purpose-built face quality scoring',
    },
    'liqe': {
        'pyiqa_id': 'liqe',
        'vram_gb': 2,
        'lower_better': False,
        'score_range': (0, 5),  # LIQE outputs 0-5 quality score
        'description': 'LIQE - Quality score + distortion type diagnosis',
        'has_distortion': True,
    },
    # Q-Align (LLM-based IQA, q-future/one-align — mPLUG-Owl2 base).
    # Three variants by quantisation; the 4-bit fits an 8GB card, the 8-bit
    # fits 12-14GB, full precision wants 16GB+. The score is on the AVA MOS
    # scale (1-5 typically), so it benchmarks naturally against AVA.txt.
    'qalign': {
        'pyiqa_id': 'qalign',
        'vram_gb': 14,
        'lower_better': False,
        'score_range': (1, 5),
        'description': 'Q-Align — full precision (16GB+ VRAM, ~13.6GB weights)',
    },
    'qalign_8bit': {
        'pyiqa_id': 'qalign_8bit',
        'vram_gb': 8,
        'lower_better': False,
        'score_range': (1, 5),
        'description': 'Q-Align — 8-bit quantised (~12-14GB VRAM, ~7GB weights)',
    },
    'qalign_4bit': {
        'pyiqa_id': 'qalign_4bit',
        'vram_gb': 5,
        'lower_better': False,
        'score_range': (1, 5),
        'description': 'Q-Align — 4-bit quantised (~6-8GB VRAM, ~4GB weights)',
    },
}


# Models whose forward pass is per-sample independent in eval mode and accept a
# stacked same-size batch tensor, so real batching gives results bit-identical to
# per-image scoring. Resolution-sensitive multi-scale models (musiq*), the
# variable-output LIQE, and the VLM Q-Align variants stay serial (forced
# fixed-size batching would shift their scores).
_BATCHABLE_MODELS = {'topiq', 'hyperiqa', 'dbcnn', 'topiq_iaa', 'topiq_nr_face', 'clipiqa+'}


class PyIQAScorer:
    """Wrapper for pyiqa image quality assessment models."""

    def __init__(self, model_name: str = 'topiq', device: Optional[str] = None):
        """Initialize PyIQA scorer.

        Args:
            model_name: Model identifier (topiq, hyperiqa, dbcnn, musiq, etc.)
            device: Device to use ('cuda', 'cpu', or None for auto)
        """
        if model_name not in PYIQA_MODELS:
            available = ', '.join(PYIQA_MODELS.keys())
            raise ValueError(f"Unknown model '{model_name}'. Available: {available}")

        self.model_name = model_name
        self.model_info = PYIQA_MODELS[model_name]
        if device is None:
            from utils.device import get_device
            device = get_device()
        self.device = device
        self.model = None
        self._loaded = False

    def load(self):
        """Load model to GPU/CPU."""
        if self._loaded:
            return

        _ensure_pyiqa()

        pyiqa_id = self.model_info['pyiqa_id']

        self.model = pyiqa.create_metric(
            pyiqa_id,
            device=torch.device(self.device)
        )
        self._loaded = True

    def unload(self):
        """Unload model to free VRAM."""
        if not self._loaded:
            return

        if self.model is not None:
            # Move to CPU first if on GPU
            if hasattr(self.model, 'cpu'):
                self.model.cpu()
            del self.model
            self.model = None

        self._loaded = False
        torch.cuda.empty_cache()
        logger.info("  %s unloaded", self.model_name)

    # Max long edge for inference (prevents OOM on CPU with high-res images).
    # PyIQA models are trained on <=1024px images; larger adds no benefit
    # but explodes intermediate activation memory (ResNet50 at 5496x3670
    # uses ~10GB per image in FP32).
    _MAX_INFERENCE_SIZE = 1024

    def _preprocess_image(self, image: Image.Image) -> torch.Tensor:
        """Convert PIL image to tensor for pyiqa.

        Args:
            image: PIL Image (RGB)

        Returns:
            Tensor of shape (1, 3, H, W), normalized to [0, 1]
        """
        # Convert to RGB if needed
        if image.mode != 'RGB':
            image = image.convert('RGB')

        # Resize if larger than max inference size to prevent OOM
        w, h = image.size
        long_edge = max(w, h)
        if long_edge > self._MAX_INFERENCE_SIZE:
            scale = self._MAX_INFERENCE_SIZE / long_edge
            image = image.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

        # Convert to tensor: (H, W, C) -> (C, H, W)
        img_array = np.array(image).astype(np.float32) / 255.0
        img_tensor = torch.from_numpy(img_array).permute(2, 0, 1)

        # Add batch dimension: (C, H, W) -> (1, C, H, W)
        img_tensor = img_tensor.unsqueeze(0)

        return img_tensor.to(self.device)

    def _normalize_score(self, raw_score) -> float:
        """Normalize score to 0-10 range.

        Args:
            raw_score: Raw score from model (may be tensor, numpy, or scalar)

        Returns:
            Normalized score in 0-10 range as Python float
        """
        # Ensure we have a Python float
        if hasattr(raw_score, 'item'):
            raw_score = raw_score.item()
        raw_score = float(raw_score)

        min_val, max_val = self.model_info['score_range']

        # Clamp to expected range
        raw_score = max(float(min_val), min(float(max_val), raw_score))

        # Normalize to 0-1
        if max_val > min_val:
            normalized = (raw_score - min_val) / (max_val - min_val)
        else:
            normalized = raw_score

        # Scale to 0-10 and ensure Python float
        result = float(normalized * 10.0)

        # Clamp final result to valid range
        return max(0.0, min(10.0, result))

    def score_image(self, image: Image.Image) -> float:
        """Score a single image.

        Args:
            image: PIL Image

        Returns:
            Quality score normalized to 0-10 as Python float
        """
        if not self._loaded:
            self.load()

        img_tensor = self._preprocess_image(image)

        with torch.no_grad():
            raw_score = self.model(img_tensor)

        # Extract scalar from tensor - handle various return types
        if isinstance(raw_score, torch.Tensor):
            if raw_score.numel() == 1:
                raw_score = raw_score.item()
            else:
                raw_score = raw_score.mean().item()
        elif hasattr(raw_score, 'item'):
            raw_score = raw_score.item()

        return self._finalize_raw(raw_score)

    def _finalize_raw(self, raw_score) -> float:
        """Apply lower_better inversion then normalize a raw scalar to 0-10."""
        raw_score = float(raw_score)
        if self.model_info['lower_better']:
            min_val, max_val = self.model_info['score_range']
            raw_score = float(max_val) - raw_score + float(min_val)
        return self._normalize_score(raw_score)

    @property
    def supports_batching(self) -> bool:
        """Whether this model can be scored with a stacked same-size batch tensor."""
        return self.model_name in _BATCHABLE_MODELS

    def _extract_batch_raw(self, out, n: int) -> list:
        """Turn a batched model output into a list of n raw scalars.

        Raises ValueError if the output doesn't have n elements so the caller
        falls back to serial scoring rather than silently mis-aligning scores.
        """
        if isinstance(out, torch.Tensor):
            flat = out.detach().cpu().flatten()
            if flat.numel() != n:
                raise ValueError(f"batched output has {flat.numel()} elements, expected {n}")
            return [float(x) for x in flat.tolist()]
        if isinstance(out, (list, tuple)):
            if len(out) != n:
                raise ValueError(f"batched output has {len(out)} elements, expected {n}")
            return [float(x.item()) if hasattr(x, 'item') else float(x) for x in out]
        raise ValueError(f"unbatchable output type: {type(out)}")

    def _score_batch_serial(self, images: list[Image.Image]) -> list[float]:
        """Per-image scoring with skip-aggregation (the original behavior)."""
        scores: list[float] = []
        skipped: dict[str, int] = {}
        for image in images:
            try:
                scores.append(float(self.score_image(image)))
            except Exception as e:
                msg = str(e)
                skipped[msg] = skipped.get(msg, 0) + 1
                scores.append(5.0)
        for msg, count in skipped.items():
            logger.warning("  %s skipped %d image(s): %s", self.model_name, count, msg)
        return scores

    def score_batch(self, images: list[Image.Image]) -> list[float]:
        """Score a batch of images, normalized to 0-10.

        For batchable models, same-size preprocessed images are stacked into a
        single tensor and scored in one forward pass (bit-identical to per-image
        in eval mode). Non-batchable models and any group that errors fall back
        to per-image scoring.
        """
        if not self._loaded:
            self.load()

        if not self.supports_batching or len(images) <= 1:
            return self._score_batch_serial(images)

        from collections import defaultdict

        # Preprocess once; group by tensor shape so each forward is a clean stack.
        try:
            tensors = [self._preprocess_image(img) for img in images]
        except Exception:
            return self._score_batch_serial(images)

        groups: dict = defaultdict(list)
        for idx, t in enumerate(tensors):
            groups[tuple(t.shape[2:])].append(idx)

        scores: list = [None] * len(images)
        skipped: dict[str, int] = {}
        for _shape, idxs in groups.items():
            try:
                with torch.no_grad():
                    out = self.model(torch.cat([tensors[i] for i in idxs], dim=0))
                raws = self._extract_batch_raw(out, len(idxs))
                for k, i in enumerate(idxs):
                    scores[i] = self._finalize_raw(raws[k])
            except Exception as e:
                # Per-group serial fallback keeps a single bad shape from failing all.
                msg = str(e)
                for i in idxs:
                    try:
                        scores[i] = float(self.score_image(images[i]))
                    except Exception as e2:
                        skipped[str(e2)] = skipped.get(str(e2), 0) + 1
                        scores[i] = 5.0
                logger.debug("  %s batch group fell back to serial: %s", self.model_name, msg)

        for msg, count in skipped.items():
            logger.warning("  %s skipped %d image(s): %s", self.model_name, count, msg)
        return [float(s) for s in scores]

    @property
    def vram_gb(self) -> float:
        """Get estimated VRAM requirement in GB."""
        return self.model_info['vram_gb']

    @property
    def description(self) -> str:
        """Get model description."""
        return self.model_info['description']


def get_available_models() -> dict:
    """Get dict of available pyiqa models with their info."""
    return PYIQA_MODELS.copy()


def select_best_model(available_vram_gb: float) -> str:
    """Select best quality model based on available VRAM.

    Args:
        available_vram_gb: Available GPU VRAM in GB

    Returns:
        Model name to use
    """
    # Priority order: best accuracy first
    priority = ['topiq', 'hyperiqa', 'dbcnn', 'musiq-koniq', 'musiq', 'clipiqa+']

    for model_name in priority:
        info = PYIQA_MODELS[model_name]
        if info['vram_gb'] <= available_vram_gb:
            return model_name

    # Fallback to most lightweight
    return 'topiq'
