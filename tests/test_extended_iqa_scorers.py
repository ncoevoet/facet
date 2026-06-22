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


# --------------------------------------------------------------------------- #
# Defensive _predict_mos / score_image (Part D hardening) — no weights, no GPU.
# A fake model object stands in for the remote-code checkpoint; we only need it
# to exercise the success path and each failure mode of _predict_mos.
# --------------------------------------------------------------------------- #

from PIL import Image  # noqa: E402


def _ready_scorer(model):
    """A DeQAScorer with a fake model wired in, marked loaded (no real load())."""
    scorer = DeQAScorer(device="cpu")
    scorer.model = model
    scorer._loaded = True
    return scorer


class _ScoreModel:
    """Fake model exposing the preferred `.score()` API."""

    def __init__(self, ret):
        self._ret = ret

    def score(self, images, task_=None, input_=None):
        if callable(self._ret):
            return self._ret()
        return self._ret


def test_deqa_predict_mos_score_api_success():
    pytest.importorskip("torch")
    # .score() returns a plain MOS list -> first element, normalized later.
    scorer = _ready_scorer(_ScoreModel([4.0]))
    raw = scorer._predict_mos(Image.new("RGB", (8, 8)))
    assert raw == pytest.approx(4.0)
    # score_image normalizes (1,5)->(0,10): 4.0 -> 7.5
    assert scorer.score_image(Image.new("RGB", (8, 8))) == pytest.approx(7.5)


def test_deqa_predict_mos_returns_none_on_exception():
    pytest.importorskip("torch")
    # A model whose .score() raises must NOT crash — _predict_mos returns None.
    def boom():
        raise RuntimeError("forward signature changed in this revision")

    scorer = _ready_scorer(_ScoreModel(boom))
    assert scorer._predict_mos(Image.new("RGB", (8, 8))) is None
    # score_image propagates the None (column left NULL), never raises.
    assert scorer.score_image(Image.new("RGB", (8, 8))) is None


def test_deqa_predict_mos_returns_none_on_empty_output():
    pytest.importorskip("torch")
    # Empty list output -> None rather than an IndexError.
    scorer = _ready_scorer(_ScoreModel([]))
    assert scorer._predict_mos(Image.new("RGB", (8, 8))) is None


def test_deqa_score_batch_substitutes_none_for_failures():
    pytest.importorskip("torch")
    # One good, one failing image: batch returns [score, None], never raises.
    calls = {"n": 0}

    class _FlakyModel:
        def score(self, images, task_=None, input_=None):
            calls["n"] += 1
            if calls["n"] == 1:
                return [3.0]
            raise RuntimeError("bad image")

    scorer = _ready_scorer(_FlakyModel())
    out = scorer.score_batch([Image.new("RGB", (8, 8)), Image.new("RGB", (8, 8))])
    assert out[0] == pytest.approx(5.0)  # MOS 3.0 -> 0-10 midpoint
    assert out[1] is None
