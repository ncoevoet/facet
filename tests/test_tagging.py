"""Tests for the scan auto-tagging path.

These lock in the fix for "scan produces zero tags on the 16gb/24gb (SigLIP)
profiles":

1. ``CLIPTagger`` must encode tag-vocabulary text with SigLIP's trained
   ``max_length`` padding (64 tokens). Dynamic padding collapses every tag
   similarity to noise so nothing clears the threshold.
2. ``build_clip_tagger`` must resolve the model identity from the *active
   profile* (``get_clip_config``) so the vocabulary is encoded by the same
   model that produced the stored image embeddings.
3. ``resolve_scan_tagger`` must reload the profile model when the scorer has no
   resident tagger (multi-pass mode), instead of building a tagger from
   ``scorer.model is None`` (which silently yields zero tags).
"""

import sys
import types
from unittest import mock

import pytest


class _FakeConfig:
    """Minimal ScoringConfig double for the tagger/builders."""

    def __init__(self, clip_config):
        self._clip_config = clip_config

    def get_clip_config(self):
        return self._clip_config

    def get_tag_vocabulary(self):
        return {"sky": ["sky", "blue sky"], "macro": ["macro shot"]}

    def get_art_tags(self):
        return set()


# ---------------------------------------------------------------------------
# 1. SigLIP text padding
# ---------------------------------------------------------------------------

class TestSiglipTextPadding:
    def test_transformers_backend_pads_to_max_length(self):
        """SigLIP text must be tokenized with padding='max_length', max_length=64."""
        torch = pytest.importorskip("torch")
        from models.tagger import CLIPTagger

        recorded = {}

        class _Encoding(dict):
            def to(self, *_a, **_k):
                return self

        class _FakeTokenizer:
            def __call__(self, _texts, **kwargs):
                recorded.update(kwargs)
                return _Encoding()

        class _FakeModel:
            def get_text_features(self, **_kw):
                # Two prompts in the fake vocab -> shape (2, 4); values irrelevant.
                return torch.ones(2, 4)

        cfg = _FakeConfig({"model_name": "google/siglip2-so400m-patch16-naflex",
                           "backend": "transformers"})

        with mock.patch("transformers.AutoTokenizer.from_pretrained",
                        return_value=_FakeTokenizer()):
            CLIPTagger(
                clip_model=_FakeModel(), device="cpu", config=cfg,
                model_name="google/siglip2-so400m-patch16-naflex",
                backend="transformers",
            )

        assert recorded.get("padding") == "max_length"
        assert recorded.get("max_length") == 64
        assert recorded.get("truncation") is True


# ---------------------------------------------------------------------------
# 2. build_clip_tagger resolves the active profile's model
# ---------------------------------------------------------------------------

class TestBuildClipTagger:
    def test_transformers_profile_loads_siglip(self):
        import tag_existing

        cfg = _FakeConfig({"model_name": "google/siglip2-so400m-patch16-naflex",
                           "backend": "transformers"})
        fake_model = mock.MagicMock(name="siglip_model")
        # model.to(device).eval() chaining must return a model
        fake_model.to.return_value.eval.return_value = fake_model

        with (
            mock.patch("transformers.AutoModel.from_pretrained",
                       return_value=fake_model) as auto_model,
            mock.patch.object(tag_existing, "CLIPTagger") as CLIPTaggerMock,
        ):
            tag_existing.build_clip_tagger(cfg, device="cpu")

        auto_model.assert_called_once()
        assert auto_model.call_args.args[0] == "google/siglip2-so400m-patch16-naflex"
        _, kwargs = CLIPTaggerMock.call_args
        assert kwargs["model_name"] == "google/siglip2-so400m-patch16-naflex"
        assert kwargs["backend"] == "transformers"

    def test_open_clip_profile_loads_vit(self):
        import tag_existing

        cfg = _FakeConfig({"model_name": "ViT-L-14", "backend": "open_clip",
                           "pretrained": "laion2b_s32b_b82k"})
        fake_open_clip = types.ModuleType("open_clip")
        fake_model = mock.MagicMock(name="clip_model")
        fake_model.to.return_value.eval.return_value = fake_model
        fake_open_clip.create_model_and_transforms = mock.MagicMock(
            return_value=(fake_model, None, None))

        with (
            mock.patch.dict(sys.modules, {"open_clip": fake_open_clip}),
            mock.patch.object(tag_existing, "CLIPTagger") as CLIPTaggerMock,
        ):
            tag_existing.build_clip_tagger(cfg, device="cpu")

        fake_open_clip.create_model_and_transforms.assert_called_once_with(
            "ViT-L-14", pretrained="laion2b_s32b_b82k")
        _, kwargs = CLIPTaggerMock.call_args
        assert kwargs["model_name"] == "ViT-L-14"
        assert kwargs["backend"] == "open_clip"


# ---------------------------------------------------------------------------
# 3. resolve_scan_tagger — multi-pass reload guard
# ---------------------------------------------------------------------------

class TestResolveScanTagger:
    def test_reuses_resident_tagger(self):
        import tag_existing

        sentinel = object()
        scorer = types.SimpleNamespace(tagger=sentinel, model=object(),
                                       config=_FakeConfig({}), device="cpu")
        with mock.patch.object(tag_existing, "build_clip_tagger") as build:
            result = tag_existing.resolve_scan_tagger(scorer)

        assert result is sentinel
        build.assert_not_called()

    def test_builds_when_tagger_missing(self):
        """Multi-pass: scorer.tagger/model are None -> reload the profile model."""
        import tag_existing

        cfg = _FakeConfig({})
        scorer = types.SimpleNamespace(tagger=None, model=None,
                                       config=cfg, device="cuda")
        built = object()
        with mock.patch.object(tag_existing, "build_clip_tagger",
                               return_value=built) as build:
            result = tag_existing.resolve_scan_tagger(scorer)

        assert result is built
        build.assert_called_once_with(cfg, device="cuda")
