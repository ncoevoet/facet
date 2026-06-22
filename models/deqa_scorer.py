"""DeQA-Score scorer for Facet.

DeQA-Score (arXiv:2501.11561, "Teaching Large Multimodal Models to Recognize
and Reason about Real-World Image Quality") is a large VLM-based image quality
assessment model that predicts a quality Mean Opinion Score (MOS) on a 1-5
scale by reasoning over the image with a multimodal LLM backbone.

Model: https://huggingface.co/zhiyuanyou/DeQA-Score-Mix3

Because it is a large VLM, this scorer is HEAVY: it needs a sizeable GPU and is
per-image only (no real tensor batching — ``score_batch`` simply loops). It is
optional and config-gated (defaults OFF), gated further at runtime by
:meth:`can_run` so a low-VRAM host skips loading and leaves the column NULL
instead of OOM-ing.

It is importable and unit-testable on a CPU machine without downloading any
weights: all heavy imports (torch, transformers) and any network access happen
lazily inside ``load()`` / ``score_image`` — never in the constructor.
"""

import logging
from typing import Optional

from PIL import Image

logger = logging.getLogger("facet.deqa")


class DeQAScorer:
    """Wrapper around DeQA-Score (large VLM image-quality MOS predictor).

    Mirrors the :class:`models.pyiqa_scorer.PyIQAScorer` interface for uniform
    downstream handling: ``load()`` / ``unload()`` / ``score_image()`` (0-10) /
    ``score_batch()`` (list of 0-10) and a ``_normalize_score()`` mapping the
    model's ``score_range`` to 0-10.
    """

    # HuggingFace model id. DeQA-Score-Mix3 is the released checkpoint trained
    # on a mixture of IQA datasets; it outputs a MOS on the 1-5 scale.
    MODEL_ID = "zhiyuanyou/DeQA-Score-Mix3"

    # MOS scale the model outputs; normalized to 0-10 by ``_normalize_score``.
    score_range = (1, 5)

    # Higher score = better quality.
    lower_better = False

    # Approximate VRAM footprint (GB) for the VLM backbone.
    vram_gb = 16

    # Minimum VRAM (GB) required by default for the model to run.
    DEFAULT_MIN_VRAM_GB = 16.0

    def __init__(self, device: Optional[str] = None):
        """Initialize the scorer.

        Cheap by design: stores configuration only. No torch/transformers
        import and no network access happen here — the device string is
        resolved lazily in :meth:`load`.

        Args:
            device: Device to use ('cuda', 'cpu', or None for auto-detect at load).
        """
        self._device = device
        self.device = device  # resolved to a concrete string in load()
        self.model = None
        self.processor = None
        self._loaded = False

    def can_run(self, min_vram_gb: float = DEFAULT_MIN_VRAM_GB) -> bool:
        """Return whether enough VRAM is available to run DeQA-Score.

        Queries available VRAM via
        :meth:`models.model_manager.ModelManager.detect_vram` and compares it to
        ``min_vram_gb``. Used to gate loading so a low-VRAM host can log a
        "skipped" message and leave the score column NULL.

        Args:
            min_vram_gb: Minimum VRAM in GB required to run (default 16.0).

        Returns:
            True if detected VRAM >= ``min_vram_gb``, else False.
        """
        from models.model_manager import ModelManager
        available = ModelManager.detect_vram()
        return float(available) >= float(min_vram_gb)

    def load(self):
        """Load the DeQA-Score VLM to the target device.

        Raises:
            RuntimeError: if :meth:`can_run` is False (insufficient VRAM), so the
                caller can log a "skipped" message and leave the column NULL.
        """
        if self._loaded:
            return

        if not self.can_run():
            raise RuntimeError(
                f"DeQA-Score requires at least {self.DEFAULT_MIN_VRAM_GB:.0f}GB VRAM; "
                "skipping load (score will be left NULL)."
            )

        import torch  # noqa: F401  (lazy heavy import)
        from transformers import AutoModelForCausalLM, AutoProcessor

        if self._device is None:
            from utils.device import get_device
            self.device = get_device()
        else:
            self.device = self._device

        logger.info("Loading DeQA-Score: %s", self.MODEL_ID)
        self.model = AutoModelForCausalLM.from_pretrained(
            self.MODEL_ID, trust_remote_code=True
        )
        self.model = self.model.to(self.device).eval()
        self.processor = AutoProcessor.from_pretrained(self.MODEL_ID, trust_remote_code=True)
        self._loaded = True

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
        logger.info("DeQA-Score unloaded")

    def _normalize_score(self, raw_score) -> float:
        """Normalize a raw MOS to the 0-10 range.

        Maps ``score_range`` (1, 5) linearly onto (0, 10) so endpoints land at
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

        raw_score = max(float(min_val), min(float(max_val), raw_score))

        if max_val > min_val:
            normalized = (raw_score - min_val) / (max_val - min_val)
        else:
            normalized = raw_score

        result = float(normalized * 10.0)
        return max(0.0, min(10.0, result))

    def _predict_mos(self, image: Image.Image) -> Optional[float]:
        """Run the VLM and return a raw MOS in the model's ``score_range``.

        DeQA-Score exposes a quality-scoring head; we call it through the
        model's documented ``score`` API when present, falling back to a logits
        reduction. Heavy work is wrapped in ``torch.no_grad``.

        Defensive by design: this model loads remote ``trust_remote_code`` code
        whose forward / ``.score()`` signature varies across checkpoint
        revisions. Any failure (wrong signature, unexpected output shape,
        device mismatch, OOM) is caught and surfaced as ``None`` so the scan
        leaves the column NULL for this image rather than crashing the batch.
        Never raises.

        Returns:
            Raw MOS as a float, or ``None`` if prediction failed.
        """
        import torch

        if image.mode != "RGB":
            image = image.convert("RGB")

        try:
            with torch.no_grad():
                # Preferred path: DeQA-Score models expose a `.score()` helper
                # that returns the MOS directly for a list of images.
                if hasattr(self.model, "score"):
                    out = self.model.score([image], task_="quality", input_="image")
                    if isinstance(out, (list, tuple)):
                        out = out[0] if out else None
                    if out is None:
                        return None
                    if isinstance(out, torch.Tensor):
                        return float(out.flatten()[0].item()) if out.numel() else None
                    return float(out)

                # Fallback: processor + forward, reduce logits to a scalar.
                inputs = self.processor(images=image, return_tensors="pt")
                inputs = {k: v.to(self.device) for k, v in inputs.items()}
                output = self.model(**inputs)
                logits = output.logits if hasattr(output, "logits") else output
                if isinstance(logits, (list, tuple)):
                    logits = logits[0] if logits else None
                if logits is None or not hasattr(logits, "flatten") or logits.numel() == 0:
                    return None
                return float(logits.flatten()[0].item())
        except Exception as e:  # noqa: BLE001 — never crash the scan on a bad forward
            logger.warning("DeQA-Score prediction failed: %s", e)
            return None

    def score_image(self, image: Image.Image) -> Optional[float]:
        """Score a single PIL image, normalized to 0-10.

        Returns ``None`` if the underlying prediction failed (the column is
        then left NULL); a successful prediction is normalized to 0-10.
        """
        if not self._loaded:
            self.load()

        raw = self._predict_mos(image)
        if raw is None:
            return None
        return self._normalize_score(raw)

    def score_batch(self, images: list[Image.Image]) -> list[Optional[float]]:
        """Score a list of PIL images, each normalized to 0-10.

        DeQA-Score is a VLM with no meaningful tensor batching, so this simply
        loops :meth:`score_image`. A per-image failure yields ``None`` (the
        column is left NULL for that image) so one bad image never fails the
        whole batch. ``score_image`` is already defensive and returns ``None``
        on failure; the extra guard here also catches a load() failure raised
        mid-batch.
        """
        if not self._loaded:
            self.load()

        scores: list[Optional[float]] = []
        for im in images:
            try:
                scores.append(self.score_image(im))
            except Exception as e:  # noqa: BLE001 — defensive per-image fallback
                logger.warning("DeQA-Score skipped an image: %s", e)
                scores.append(None)
        return scores
