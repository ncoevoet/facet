"""Form facet + Matsuda colour harmony (analyzers/form_facet.py).

Synthetic-image unit tests: symmetry ranks mirror-symmetric over asymmetric
frames, balance ranks centred over off-centre mass, edge entropy ranks noise
over a single-orientation gradient, harmony is NULL for monochrome and ranks a
complementary palette over a clashing one, and every metric is stable across
input resolutions (fixed 512px working size).
"""

import numpy as np
import pytest
from PIL import Image

from concurrent.futures import ThreadPoolExecutor

from analyzers.form_facet import FORM_METRIC_COLUMNS, compute_form_metrics, warmup


def _to_image(arr):
    return Image.fromarray(arr.astype(np.uint8), mode="RGB")


def _vertical_gradient(size=256):
    """Top-to-bottom luminance ramp: left-right symmetric, single edge orientation."""
    ramp = np.linspace(0, 255, size, dtype=np.uint8)
    arr = np.repeat(ramp[:, None], size, axis=1)
    return _to_image(np.stack([arr] * 3, axis=-1))


def _half_black_half_white(size=256):
    """Left half black, right half white: maximally left-right asymmetric."""
    arr = np.zeros((size, size, 3), dtype=np.uint8)
    arr[:, size // 2:] = 255
    return _to_image(arr)


def _blob(cx, cy, size=256, radius=30):
    """White disc on black at (cx, cy) in relative coordinates."""
    ys, xs = np.mgrid[0:size, 0:size]
    mask = (xs - cx * size) ** 2 + (ys - cy * size) ** 2 <= radius ** 2
    arr = np.zeros((size, size, 3), dtype=np.uint8)
    arr[mask] = 255
    return _to_image(arr)


def _noise(size=256, seed=42):
    rng = np.random.default_rng(seed)
    return _to_image(rng.integers(0, 256, (size, size, 3)))


def _hue_stripes(hues_deg, size=256, sat=255, val=230):
    """Vertical stripes of the given HSV hues (degrees), fully saturated."""
    arr = np.zeros((size, size, 3), dtype=np.uint8)
    stripe = size // len(hues_deg)
    for i, hue in enumerate(hues_deg):
        arr[:, i * stripe:(i + 1) * stripe] = (round(hue / 360.0 * 255), sat, val)
    return Image.fromarray(arr, mode="HSV").convert("RGB")


def test_returns_all_columns_in_range():
    metrics = compute_form_metrics(_noise())
    assert set(metrics) == set(FORM_METRIC_COLUMNS)
    for col, value in metrics.items():
        assert value is not None, col
        assert 0.0 <= value <= 10.0, (col, value)


def test_none_image_returns_all_none():
    metrics = compute_form_metrics(None)
    assert set(metrics) == set(FORM_METRIC_COLUMNS)
    assert all(v is None for v in metrics.values())


def test_symmetric_scores_higher_than_asymmetric():
    symmetric = compute_form_metrics(_vertical_gradient())["form_symmetry"]
    asymmetric = compute_form_metrics(_half_black_half_white())["form_symmetry"]
    assert symmetric > asymmetric
    assert symmetric > 9.0
    assert asymmetric < 1.0


def test_centered_blob_more_balanced_than_corner_blob():
    centered = compute_form_metrics(_blob(0.5, 0.5))["form_balance"]
    corner = compute_form_metrics(_blob(0.15, 0.15))["form_balance"]
    assert centered > corner
    assert centered > 9.0


def test_gradient_edge_entropy_below_noise():
    gradient = compute_form_metrics(_vertical_gradient())["form_edge_entropy"]
    noise = compute_form_metrics(_noise())["form_edge_entropy"]
    assert gradient < noise
    assert noise > 8.0


def test_noise_fractal_dimension_above_single_line():
    line = compute_form_metrics(_half_black_half_white())["form_fractal"]
    noise = compute_form_metrics(_noise())["form_fractal"]
    assert noise > line


def test_monochrome_harmony_is_none():
    gray = _to_image(np.full((256, 256, 3), 128))
    assert compute_form_metrics(gray)["color_harmony"] is None
    assert compute_form_metrics(_vertical_gradient())["color_harmony"] is None


def test_complementary_palette_beats_clashing_palette():
    complementary = compute_form_metrics(_hue_stripes([30, 210]))["color_harmony"]
    clashing = compute_form_metrics(_hue_stripes([0, 72, 144, 216, 288]))["color_harmony"]
    assert complementary is not None and clashing is not None
    assert complementary >= clashing
    assert complementary > 9.0


def test_working_size_consistency_across_input_resolutions():
    """Scan (full decode) and backfill (640px thumbnail) must agree.

    The same synthetic scene rendered large and thumbnail-sized goes through
    the fixed 512px working size, so every metric stays within tolerance.
    """
    rng = np.random.default_rng(7)
    size = 2048
    ys, xs = np.mgrid[0:size, 0:size]
    base = (xs / size * 120 + ys / size * 80).astype(np.float32)
    mask = (xs - size * 0.55) ** 2 + (ys - size * 0.45) ** 2 <= (size * 0.15) ** 2
    scene = np.stack([
        base + mask * 90,
        base * 0.6 + (~mask) * 40,
        255 - base,
    ], axis=-1)
    scene += rng.normal(0, 6, scene.shape)
    img = _to_image(np.clip(scene, 0, 255))

    large = compute_form_metrics(img.resize((1024, 1024), Image.Resampling.LANCZOS))
    thumb = compute_form_metrics(img.resize((640, 640), Image.Resampling.LANCZOS))
    for col in FORM_METRIC_COLUMNS:
        assert large[col] is not None and thumb[col] is not None, col
        assert large[col] == pytest.approx(thumb[col], abs=1.0), col


def test_warmup_is_idempotent():
    warmup()
    warmup()


def test_concurrent_color_harmony_does_not_deadlock():
    """Regression guard for issue #55.

    Several worker threads compute form metrics (hence KMeans) at once. warmup()
    pre-initializes the native thread pools and _color_harmony serializes the fit
    under a lock, so the concurrent KMeans path completes instead of deadlocking
    in libgomp init. The deadlock is a race, so this is a functional smoke guard
    (it times out loudly rather than deterministically reproducing the hang).
    """
    warmup()
    images = [_hue_stripes([0, 72, 144, 216, 288]) for _ in range(8)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(compute_form_metrics, img) for img in images]
        results = [f.result(timeout=60) for f in futures]
    for metrics in results:
        assert metrics["color_harmony"] is not None
