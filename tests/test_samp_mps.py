"""Regression tests for SAMP-Net's non-divisible adaptive pooling on MPS."""

import pytest

torch = pytest.importorskip("torch")
F = torch.nn.functional

from models.samp_net import _adaptive_avg_pool2d  # noqa: E402


def test_adaptive_pool_helper_matches_torch_on_cpu():
    tensor = torch.randn(2, 3, 7, 7)
    expected = F.adaptive_avg_pool2d(tensor, (4, 4))
    actual = _adaptive_avg_pool2d(tensor, (4, 4))
    torch.testing.assert_close(actual, expected)


@pytest.mark.skipif(
    not torch.backends.mps.is_available(),
    reason="requires an Apple Metal device",
)
@pytest.mark.parametrize("output_size", [(3, 3), (4, 4), (8, 8)])
def test_non_divisible_mps_pool_matches_cpu(output_size):
    tensor = torch.randn(2, 3, 7, 7)
    expected = F.adaptive_avg_pool2d(tensor, output_size)
    actual = _adaptive_avg_pool2d(tensor.to("mps"), output_size).cpu()
    torch.testing.assert_close(actual, expected, rtol=1e-5, atol=1e-6)
