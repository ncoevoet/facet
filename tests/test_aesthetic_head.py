"""Tests for ``models.aesthetic_head`` — the CLIP-MLP aesthetic predictor.

The bug these lock out: the scorer built its own 768->256->1 stub and loaded the
published checkpoint into it with ``strict=False``. Not one tensor matched, the
mismatch was swallowed, and ``legacy``/``8gb`` scans scored every photo with an
untrained head (measured: a near-constant 5.01, sd 0.03). A test that merely
called the loader and checked it did not raise would have passed throughout.

So these assert the three things that were actually wrong: the architecture is
the checkpoint's, a mismatch fails loudly, and the scores are the trained head's
rather than a random head's.
"""

from __future__ import annotations

from unittest import mock

import pytest

pytest.importorskip("torch")

import torch  # noqa: E402
import torch.nn as nn  # noqa: E402

from models.aesthetic_head import (  # noqa: E402
    AestheticMLP,
    load_aesthetic_head,
    score_aesthetic,
)

# Key -> shape of the published checkpoint
# (sac+logos+ava1-l14-linearMSE.pth, LAION improved-aesthetic-predictor).
# Ground truth for the architecture: the head must be loadable from exactly this.
PUBLISHED_CHECKPOINT_SHAPES = {
    'layers.0.weight': (1024, 768),
    'layers.0.bias': (1024,),
    'layers.2.weight': (128, 1024),
    'layers.2.bias': (128,),
    'layers.4.weight': (64, 128),
    'layers.4.bias': (64,),
    'layers.6.weight': (16, 64),
    'layers.6.bias': (16,),
    'layers.7.weight': (1, 16),
    'layers.7.bias': (1,),
}

# The head the scorer used to build. Every one of its keys is unexpected and
# every checkpoint key is missing -- which strict=False silently tolerated.
LEGACY_STUB_SHAPES = {
    '0.weight': (256, 768),
    '0.bias': (256,),
    '2.weight': (1, 256),
    '2.bias': (1,),
}


def _state_dict(shapes, seed=0):
    generator = torch.Generator().manual_seed(seed)
    return {
        key: torch.rand(shape, generator=generator) * 0.01
        for key, shape in shapes.items()
    }


@pytest.fixture
def weights_dir(tmp_path, monkeypatch):
    """Redirect the weights directory so no test touches the real checkout."""
    from models import aesthetic_head, weights
    directory = tmp_path / "pretrained_models"
    directory.mkdir()
    monkeypatch.setattr(weights, 'PRETRAINED_MODELS_DIR', directory)
    monkeypatch.setattr(
        aesthetic_head, 'download_weights',
        mock.Mock(side_effect=AssertionError("test must not download weights")))
    return directory


def _write_checkpoint(weights_dir, shapes, seed=0):
    from models.aesthetic_head import AESTHETIC_HEAD_WEIGHTS_FILENAME
    state_dict = _state_dict(shapes, seed=seed)
    torch.save(state_dict, weights_dir / AESTHETIC_HEAD_WEIGHTS_FILENAME)
    return state_dict


class TestArchitectureMatchesTheCheckpoint:
    """The single most direct guard: the model's own keys ARE the checkpoint's."""

    def test_parameter_names_and_shapes_are_the_published_ones(self):
        actual = {key: tuple(tensor.shape) for key, tensor in AestheticMLP().state_dict().items()}
        assert actual == PUBLISHED_CHECKPOINT_SHAPES

    def test_the_old_stub_shape_is_not_what_we_build(self):
        assert set(AestheticMLP().state_dict()) != set(LEGACY_STUB_SHAPES)


class TestStrictLoading:
    def test_loads_every_tensor_from_a_matching_checkpoint(self, weights_dir):
        state_dict = _write_checkpoint(weights_dir, PUBLISHED_CHECKPOINT_SHAPES)

        head = load_aesthetic_head('cpu')
        missing, unexpected = head.load_state_dict(state_dict, strict=False)

        assert list(missing) == []
        assert list(unexpected) == []
        for key, tensor in head.state_dict().items():
            assert torch.equal(tensor, state_dict[key]), key

    def test_scores_come_from_the_checkpoint_not_from_random_init(self, weights_dir):
        state_dict = _write_checkpoint(weights_dir, PUBLISHED_CHECKPOINT_SHAPES, seed=3)
        reference = AestheticMLP()
        reference.load_state_dict(state_dict, strict=True)
        reference.eval()
        untrained = AestheticMLP().eval()
        features = torch.nn.functional.normalize(torch.randn(8, 768), dim=-1)

        head = load_aesthetic_head('cpu')
        loaded_scores = score_aesthetic(head, features)

        assert loaded_scores == pytest.approx(score_aesthetic(reference, features))
        assert loaded_scores != pytest.approx(score_aesthetic(untrained, features))

    def test_a_mismatched_checkpoint_raises_with_both_key_lists(self, weights_dir):
        _write_checkpoint(weights_dir, LEGACY_STUB_SHAPES)

        with pytest.raises(RuntimeError) as excinfo:
            load_aesthetic_head('cpu')

        message = str(excinfo.value)
        assert 'Missing key(s)' in message and 'layers.0.weight' in message
        assert 'Unexpected key(s)' in message and '0.weight' in message


class TestScoreMapping:
    """The head emits an AVA-style 1-10 rating, so Facet's column is it, clamped.

    The old call sites applied ``(raw + 1) * 5``, which on the correctly loaded
    head pins 100% of real photos at exactly 10.0 (measured on 2000 library
    embeddings: raw mean 5.47, range 3.59-7.11).
    """

    class _ConstantHead(nn.Module):
        def __init__(self, value):
            super().__init__()
            self.value = value

        def forward(self, x):
            return torch.full((x.shape[0], 1), self.value)

    def test_a_rating_passes_through_unscaled(self):
        assert score_aesthetic(self._ConstantHead(5.47), torch.zeros(1, 768)) == pytest.approx([5.47], abs=1e-5)

    def test_scores_are_clamped_to_the_zero_ten_scale(self):
        assert score_aesthetic(self._ConstantHead(19.0), torch.zeros(2, 768)) == pytest.approx([10.0, 10.0])
        assert score_aesthetic(self._ConstantHead(-4.0), torch.zeros(2, 768)) == pytest.approx([0.0, 0.0])


class TestMultiPassFeedsNormalizedFeatures:
    """The default scan path must hand the head unit-norm embeddings.

    Raw ViT-L-14 features have an L2 norm around 19; feeding those to the trained
    head saturated 52% of a real sample at 10.0.
    """

    class _SpyHead(nn.Module):
        def __init__(self):
            super().__init__()
            self.seen_norms = []

        def forward(self, x):
            self.seen_norms.extend(x.norm(dim=-1).tolist())
            return torch.full((x.shape[0], 1), 6.25)

    def test_pass_clip_normalizes_before_scoring_and_stores_the_rating(self):
        from processing.multi_pass import ChunkedMultiPassProcessor

        spy_head = self._SpyHead()
        scorer = mock.MagicMock()
        scorer.aesthetic_head = spy_head
        model_manager = mock.MagicMock()
        model_manager.detect_vram.return_value = 8.0
        model_manager.device = 'cpu'
        proc = ChunkedMultiPassProcessor(scorer=scorer, model_manager=model_manager, config={})

        clip_model = mock.MagicMock()
        clip_model.encode_image.return_value = torch.tensor([[3.0, 4.0], [0.0, 19.0]])
        model_dict = {
            'model': clip_model,
            'preprocess': lambda img: torch.zeros(3, 2, 2),
            'backend': 'open_clip',
        }
        images = {'a.jpg': {'pil': object()}, 'b.jpg': {'pil': object()}}
        results = {'a.jpg': {}, 'b.jpg': {}}

        proc._pass_clip(model_dict, images, results)

        assert spy_head.seen_norms == pytest.approx([1.0, 1.0])
        assert results['a.jpg']['aesthetic'] == pytest.approx(6.25)
        assert results['b.jpg']['aesthetic'] == pytest.approx(6.25)


class TestPublishedCheckpointIfPresent:
    """Runs against the real file when it has been downloaded; skips otherwise."""

    def test_real_checkpoint_loads_strictly_and_scores_non_degenerately(self):
        from models.aesthetic_head import AESTHETIC_HEAD_WEIGHTS_FILENAME
        from models.weights import pretrained_model_path

        weights_path = pretrained_model_path(AESTHETIC_HEAD_WEIGHTS_FILENAME)
        if not weights_path.exists():
            pytest.skip("published aesthetic checkpoint not downloaded")

        head = load_aesthetic_head('cpu')
        missing, unexpected = head.load_state_dict(
            torch.load(weights_path, map_location='cpu'), strict=False)
        assert list(missing) == [] and list(unexpected) == []

        torch.manual_seed(0)
        scores = score_aesthetic(head, torch.nn.functional.normalize(torch.randn(32, 768), dim=-1))
        assert scores.std() > 0.05
        assert 1.0 < scores.mean() < 9.0
