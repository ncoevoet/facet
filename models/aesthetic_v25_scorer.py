"""Aesthetic Predictor V2.5 scorer for Facet.

Aesthetic Predictor V2.5 is a SigLIP-based aesthetic head that predicts a
photographic aesthetic Mean Opinion Score (MOS) on roughly a 1-10 scale.
Unlike the CLIP+MLP aesthetic head used in the legacy/8gb profiles, this model
ships its OWN SigLIP backbone and image processor, so it must run its own
preprocessing and forward pass rather than reusing any stored CLIP/SigLIP
embedding from the database.

Model: https://huggingface.co/discus0434/aesthetic-predictor-v2-5-siglip

This scorer is optional and config-gated (defaults OFF). It is designed to be
importable and unit-testable on a CPU machine without downloading any weights:
all heavy imports (torch, transformers) and any network access happen lazily
inside ``load()`` / ``score_*`` — never in the constructor.
"""

import logging
from typing import Optional

from PIL import Image

logger = logging.getLogger("facet.aesthetic_v25")


class AestheticV25Scorer:
    """Wrapper around Aesthetic Predictor V2.5 (SigLIP-based aesthetic MOS).

    Mirrors the :class:`models.pyiqa_scorer.PyIQAScorer` interface so downstream
    code can treat every IQA scorer uniformly: ``load()`` / ``unload()`` /
    ``score_image()`` (0-10) / ``score_batch()`` (list of 0-10) and a
    ``_normalize_score()`` that maps the model's ``score_range`` to 0-10.
    """

    # HuggingFace model id. The V2.5 SigLIP head outputs an aesthetic MOS on
    # roughly the 1-10 scale (AVA-style). discus0434's repo bundles the SigLIP
    # backbone + linear aesthetic head and is the commonly used distribution.
    MODEL_ID = "discus0434/aesthetic-predictor-v2-5-siglip"

    # MOS scale the raw head outputs; normalized to 0-10 by ``_normalize_score``.
    score_range = (1, 10)

    # Higher score = more aesthetically pleasing.
    lower_better = False

    # Approximate VRAM footprint (GB) for the SigLIP backbone + head.
    vram_gb = 2

    def __init__(self, device: Optional[str] = None):
        """Initialize the scorer.

        Cheap by design: stores configuration only. No torch/transformers
        import and no network access happen here — the device string is
        resolved lazily in :meth:`load` so the constructor stays importable on
        a CPU-only machine without any GPU/torch dependency loaded.

        Args:
            device: Device to use ('cuda', 'cpu', or None for auto-detect at load).
        """
        self._device = device
        self.device = device  # resolved to a concrete string in load()
        self.model = None
        self.processor = None
        self._loaded = False

    def load(self):
        """Load the SigLIP backbone + aesthetic head to the target device.

        Aesthetic Predictor V2.5 is NOT a plain HuggingFace AutoModel repo — it is
        distributed via the ``aesthetic-predictor-v2-5`` package, which assembles
        the SigLIP backbone (``google/siglip-so400m-patch14-384``) with the linear
        aesthetic head. We use its ``convert_v2_5_from_siglip`` factory; torch and
        the package are imported lazily here so the constructor stays CPU-clean.
        """
        if self._loaded:
            return

        import torch  # noqa: F401  (lazy heavy import)
        from aesthetic_predictor_v2_5 import convert_v2_5_from_siglip

        if self._device is None:
            from utils.device import get_device
            self.device = get_device()
        else:
            self.device = self._device

        logger.info("Loading Aesthetic Predictor V2.5 (%s)", self.MODEL_ID)
        # Factory downloads the aesthetic head + the SigLIP encoder on first use.
        model, processor = convert_v2_5_from_siglip(low_cpu_mem_usage=True)
        self.model = model.to(self.device).eval()
        self.processor = processor
        self._loaded = True

    def _model_dtype(self):
        """Parameter dtype of the loaded model (to match pixel_values)."""
        import torch  # noqa: F401
        try:
            return next(self.model.parameters()).dtype
        except StopIteration:
            return None

    def unload(self):
        """Free the model/processor and release VRAM."""
        if not self._loaded:
            return

        import torch

        if self.model is not None:
            if hasattr(self.model, "cpu"):
                try:
                    self.model.cpu()
                except NotImplementedError:
                    pass
            del self.model
            self.model = None
        self.processor = None
        self._loaded = False
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        logger.info("Aesthetic Predictor V2.5 unloaded")

    def _normalize_score(self, raw_score) -> float:
        """Normalize a raw aesthetic score to the 0-10 range.

        Maps ``score_range`` (1, 10) linearly onto (0, 10) so endpoints land at
        0.0 and 10.0 — identical in style to PyIQAScorer so all IQA scorers
        share one downstream convention.

        Args:
            raw_score: Raw score (tensor, numpy scalar, or Python number).

        Returns:
            Normalized score in 0-10 as a Python float.
        """
        if hasattr(raw_score, "item"):
            raw_score = raw_score.item()
        raw_score = float(raw_score)

        min_val, max_val = self.score_range

        # Clamp to expected range before normalizing.
        raw_score = max(float(min_val), min(float(max_val), raw_score))

        if max_val > min_val:
            normalized = (raw_score - min_val) / (max_val - min_val)
        else:
            normalized = raw_score

        result = float(normalized * 10.0)
        return max(0.0, min(10.0, result))

    def _extract_raw(self, output) -> float:
        """Pull a single scalar aesthetic score out of a model forward result."""
        import torch

        # Aesthetic V2.5 returns a logits-like tensor (or an object exposing
        # ``.logits``). Reduce to a single scalar defensively.
        if hasattr(output, "logits"):
            output = output.logits
        if isinstance(output, (list, tuple)):
            output = output[0]
        if isinstance(output, torch.Tensor):
            if output.numel() == 1:
                return float(output.item())
            return float(output.flatten()[0].item())
        if hasattr(output, "item"):
            return float(output.item())
        return float(output)

    def score_image(self, image: Image.Image) -> float:
        """Score a single PIL image, normalized to 0-10.

        Runs the model's OWN SigLIP preprocessing + forward pass; does not reuse
        any externally stored embedding.
        """
        if not self._loaded:
            self.load()

        import torch

        if image.mode != "RGB":
            image = image.convert("RGB")

        pixel_values = self.processor(images=image, return_tensors="pt").pixel_values
        pixel_values = pixel_values.to(self.device)
        dtype = self._model_dtype()
        if dtype is not None:
            pixel_values = pixel_values.to(dtype)

        with torch.no_grad():
            output = self.model(pixel_values)

        raw = self._extract_raw(output)
        return self._normalize_score(raw)

    def score_batch(self, images: list[Image.Image]) -> list[float]:
        """Score a list of PIL images, each normalized to 0-10.

        The SigLIP processor can batch, so same-shaped inputs are processed in a
        single forward pass. Any failure falls back to per-image scoring so one
        bad image never fails the whole batch.
        """
        if not self._loaded:
            self.load()

        if not images:
            return []

        import torch

        try:
            rgb = [im.convert("RGB") if im.mode != "RGB" else im for im in images]
            pixel_values = self.processor(images=rgb, return_tensors="pt").pixel_values
            pixel_values = pixel_values.to(self.device)
            dtype = self._model_dtype()
            if dtype is not None:
                pixel_values = pixel_values.to(dtype)
            with torch.no_grad():
                output = self.model(pixel_values)

            logits = output.logits if hasattr(output, "logits") else output
            if isinstance(logits, (list, tuple)):
                logits = logits[0]
            flat = logits.detach().cpu().flatten()
            if flat.numel() == len(images):
                return [self._normalize_score(float(x)) for x in flat.tolist()]
            raise ValueError(
                f"batched output has {flat.numel()} elements, expected {len(images)}"
            )
        except Exception as e:  # noqa: BLE001 — defensive per-image fallback
            logger.debug("Aesthetic V2.5 batch fell back to serial: %s", e)
            scores: list[float] = []
            for im in images:
                try:
                    scores.append(self.score_image(im))
                except Exception as e2:  # noqa: BLE001
                    logger.warning("Aesthetic V2.5 skipped an image: %s", e2)
                    scores.append(5.0)
            return scores
