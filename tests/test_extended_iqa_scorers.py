"""Tests for the optional extended IQA scorers (Aesthetic V2.5 + DeQA-Score).

These scorers are config-gated (default OFF) and validated on a GPU host later,
so the tests must run on a CPU machine WITHOUT downloading any model weights.
We therefore:
  - construct instances WITHOUT calling load() (the constructor must not import
    torch/transformers or hit the network),
  - test _normalize_score endpoint mapping directly,
  - test DeQAScorer.can_run gating + load() RuntimeError by patching
    ModelManager.detect_vram (no GPU required).
"""

import pytest

from models.aesthetic_v25_scorer import AestheticV25Scorer
from models.deqa_scorer import DeQAScorer


# --------------------------------------------------------------------------- #
# Construction is cheap and does not load weights
# --------------------------------------------------------------------------- #

def test_aesthetic_construction_no_load():
    scorer = AestheticV25Scorer()
    assert scorer._loaded is False
    assert scorer.model is None
    assert scorer.processor is None
    # Key constants are exposed on the class for uniform downstream handling.
    assert scorer.MODEL_ID == "discus0434/aesthetic-predictor-v2-5-siglip"
    assert scorer.score_range == (1, 10)
    assert scorer.lower_better is False
    assert scorer.vram_gb == 2


def test_deqa_construction_no_load():
    scorer = DeQAScorer()
    assert scorer._loaded is False
    assert scorer.model is None
    assert scorer.processor is None
    assert scorer.MODEL_ID == "zhiyuanyou/DeQA-Score-Mix3"
    assert scorer.score_range == (1, 5)
    assert scorer.lower_better is False
    assert scorer.vram_gb == 16
    assert scorer.DEFAULT_MIN_VRAM_GB == 16.0


# --------------------------------------------------------------------------- #
# _normalize_score endpoint mapping
# --------------------------------------------------------------------------- #

def test_aesthetic_normalize_endpoints():
    scorer = AestheticV25Scorer()
    # score_range (1, 10) -> (0, 10)
    assert scorer._normalize_score(1) == pytest.approx(0.0)
    assert scorer._normalize_score(10) == pytest.approx(10.0)
    assert scorer._normalize_score(5.5) == pytest.approx(5.0)


def test_aesthetic_normalize_clamps_out_of_range():
    scorer = AestheticV25Scorer()
    assert scorer._normalize_score(-3) == pytest.approx(0.0)
    assert scorer._normalize_score(99) == pytest.approx(10.0)


def test_deqa_normalize_endpoints():
    scorer = DeQAScorer()
    # score_range (1, 5) -> (0, 10)
    assert scorer._normalize_score(1) == pytest.approx(0.0)
    assert scorer._normalize_score(5) == pytest.approx(10.0)
    assert scorer._normalize_score(3) == pytest.approx(5.0)


def test_deqa_normalize_clamps_out_of_range():
    scorer = DeQAScorer()
    assert scorer._normalize_score(0) == pytest.approx(0.0)
    assert scorer._normalize_score(42) == pytest.approx(10.0)


# --------------------------------------------------------------------------- #
# DeQAScorer.can_run gating + load() RuntimeError
# --------------------------------------------------------------------------- #

def test_deqa_can_run_low_vram_false(monkeypatch):
    import models.model_manager as mm
    monkeypatch.setattr(mm.ModelManager, "detect_vram", staticmethod(lambda: 8.0))
    scorer = DeQAScorer()
    assert scorer.can_run(16.0) is False


def test_deqa_can_run_high_vram_true(monkeypatch):
    import models.model_manager as mm
    monkeypatch.setattr(mm.ModelManager, "detect_vram", staticmethod(lambda: 24.0))
    scorer = DeQAScorer()
    assert scorer.can_run(16.0) is True


def test_deqa_can_run_uses_default_threshold(monkeypatch):
    import models.model_manager as mm
    # Exactly at the default 16.0 threshold should pass (>=).
    monkeypatch.setattr(mm.ModelManager, "detect_vram", staticmethod(lambda: 16.0))
    scorer = DeQAScorer()
    assert scorer.can_run() is True


def test_deqa_load_raises_when_cannot_run(monkeypatch):
    import models.model_manager as mm
    monkeypatch.setattr(mm.ModelManager, "detect_vram", staticmethod(lambda: 4.0))
    scorer = DeQAScorer()
    with pytest.raises(RuntimeError):
        scorer.load()
    # Failed gating must leave the scorer unloaded.
    assert scorer._loaded is False
