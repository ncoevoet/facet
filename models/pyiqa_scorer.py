"""PyIQA-based image quality assessment models.

Wrapper for pyiqa library models including TOPIQ, TOPIQ-IAA, TOPIQ-NR-Face,
HyperIQA, DBCNN, MUSIQ, and LIQE.
These models provide excellent quality assessment with low VRAM usage.
"""

import torch
import numpy as np
from PIL import Image
from typing import Optional

# Lazy import to avoid loading pyiqa unless needed
pyiqa = None


def _ensure_pyiqa():
    """Lazy load pyiqa library."""
    global pyiqa
    if pyiqa is None:
        try:
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
        'score_range': (0, 1),
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
}


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
        self.device = device or ('cuda' if torch.cuda.is_available() else 'cpu')
        self.model = None
        self._loaded = False

    def load(self):
        """Load model to GPU/CPU."""
        if self._loaded:
            return

        _ensure_pyiqa()

        pyiqa_id = self.model_info['pyiqa_id']
        print(f"Loading {self.model_name} ({pyiqa_id})...")

        self.model = pyiqa.create_metric(
            pyiqa_id,
            device=torch.device(self.device)
        )
        self._loaded = True
        print(f"  {self.model_name} loaded on {self.device}")

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
        print(f"  {self.model_name} unloaded")

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

        # Ensure Python float
        raw_score = float(raw_score)

        # Handle lower_better models (invert score)
        if self.model_info['lower_better']:
            min_val, max_val = self.model_info['score_range']
            raw_score = float(max_val) - raw_score + float(min_val)

        return self._normalize_score(raw_score)

    def score_batch(self, images: list[Image.Image]) -> list[float]:
        """Score a batch of images.

        Args:
            images: List of PIL Images

        Returns:
            List of quality scores normalized to 0-10 as Python floats
        """
        if not self._loaded:
            self.load()

        scores = []
        for image in images:
            try:
                score = self.score_image(image)
                # Ensure Python float
                scores.append(float(score))
            except Exception as e:
                print(f"  Warning: Failed to score image: {e}")
                scores.append(5.0)  # Default middle score as float

        return scores

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
