"""Real-file coverage for non-Canon RAW brands (ARW/DNG/NEF/ORF/PEF/RAF/RW2/SRW).

The maintainer's library is 100% Canon CR2/CR3, so every other brand is
normally exercised only through ``tests/test_raw_decode.py``'s stubbed rawpy.
This module decodes eight real fixture files instead, to catch anything
brand-specific the stubs cannot: an unusual preview codec, a sensor that
needs a 90-degree rotation, a LibRaw quirk on truncated input.

Fixtures live at the repo root (``sample.arw`` etc.), are gitignored, and are
not present in CI or a fresh clone — every test below skips (never fails)
when its file is missing. Point ``FACET_RAW_SAMPLE_DIR`` elsewhere to use a
different fixture location.

Runtime: ~15-20s. ``TestMetricsProfileIsBrandAgnostic`` and
``TestPreviewOrientationMatchesTheDemosaic`` share one cached full demosaic
per brand; ``TestPreviewGateSplitsBrandsAtTheConfiguredDefault``'s
above-the-ratio case forces a second, uncached demosaic per brand to prove
the fallback actually lands on the sensor-sized image. Every other class
works from the embedded preview or a cheap ``rawpy.imread`` header read. Run
just this module with ``pytest tests/test_raw_brands.py``, or exclude it
with ``pytest -m "not raw_brand_samples"``.
"""

import functools
import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

# rawpy is an optional dependency; skip this whole module (rather than
# error collection) on environments that don't install it.
rawpy = pytest.importorskip("rawpy")

from utils.image_loading import (  # noqa: E402
    DISPLAY_PREVIEW_MIN_LONG_EDGE,
    extract_raw_preview,
    load_display_image,
    load_image_from_path,
    thumbnail_source,
)

pytestmark = pytest.mark.raw_brand_samples

BRAND_SAMPLE_FILES = [
    "sample.arw", "sample.dng", "sample.nef", "sample.orf",
    "sample.pef", "sample.raf", "sample.rw2", "sample.srw",
]

# Measured with rawpy 0.26.1 against the fixtures this module targets
# (embedded-preview long edge / sensor long edge). Recorded so a future
# LibRaw/rawpy upgrade shows up as an intentional diff here instead of a
# silent behaviour change elsewhere in the decode path.
_MEASURED_PREVIEW_RATIOS = {
    "sample.nef": 0.995,
    "sample.pef": 0.994,
    "sample.srw": 0.980,
    "sample.rw2": 0.524,
    "sample.orf": 0.488,
    "sample.raf": 0.389,
    "sample.arw": 0.294,
    "sample.dng": 0.295,
}
# LibRaw's choice of which embedded IFD to read as "the" preview is an
# implementation detail that can shift release to release. This only needs
# to catch a gross regression (a preview collapsing to an icon, or jumping
# to full-size), not pin the exact figure.
_RATIO_TOLERANCE = 0.15

_DEFAULT_MIN_SENSOR_RATIO = 0.5  # raw_decode.preview_min_sensor_ratio's shipped default
# ORF (~0.49) and RW2 (~0.52) sit inside this margin of the default, so a
# LibRaw/rawpy upgrade could flip either — do not assert either side of the
# split for them; the ratio-straddle test below still covers the gate
# mechanism itself for both.
_BOUNDARY_SAFETY_MARGIN = 0.03
_STRADDLE_MARGIN = 0.1


def _sample_dir():
    return Path(os.environ.get("FACET_RAW_SAMPLE_DIR", Path(__file__).resolve().parent.parent))


def _require_sample(filename):
    path = _sample_dir() / filename
    if not path.exists():
        pytest.skip(f"{filename} not found under {path.parent} (set FACET_RAW_SAMPLE_DIR)")
    return path


def _sensor_dims(path):
    with rawpy.imread(str(path)) as raw:
        return raw.sizes.width, raw.sizes.height


def _measure_preview_ratio(path):
    preview = extract_raw_preview(path)
    assert preview is not None, f"expected an embedded preview in {path}"
    return max(preview.size) / max(_sensor_dims(path))


def _is_portrait(size):
    width, height = size
    return height > width


@functools.lru_cache(maxsize=None)
def _decode_metrics_cached(path_str):
    """Full metrics-profile demosaic, cached so the two classes that both
    need it (dimensions, orientation) pay for it only once per brand."""
    return load_image_from_path(path_str)


class TestMetricsProfileIsBrandAgnostic:
    """load_image_from_path is the pixel space stored face bboxes and
    image_width/image_height are expressed in — the most important
    invariant here is that it never drifts to the preview's size."""

    @pytest.mark.parametrize("filename", BRAND_SAMPLE_FILES)
    def test_demosaic_matches_sensor_dimensions_not_the_preview(self, filename):
        path = _require_sample(filename)
        sensor_dims = sorted(_sensor_dims(path))

        pil_img, img_cv = _decode_metrics_cached(str(path))

        assert pil_img is not None, f"{filename} failed to decode"
        assert pil_img.mode == 'RGB'
        # Sorted rather than positional: LibRaw rotates 90/270-degree sensors
        # (sizes.flip in {5, 6}) during postprocess, swapping width/height —
        # sample.nef is one such case. The set of edges must still match the
        # sensor's, never the preview's (see the ratio table above: none of
        # our 8 previews is pixel-identical to its sensor).
        assert sorted(pil_img.size) == sensor_dims
        assert sorted((img_cv.shape[1], img_cv.shape[0])) == sensor_dims


class TestThumbnailSourcing:
    """All 8 fixture previews exceed the 640px thumbnail gate, so every
    brand should yield a usable preview-sourced image without a second
    full demosaic."""

    @pytest.mark.parametrize("filename", BRAND_SAMPLE_FILES)
    def test_every_brand_yields_a_usable_preview_sourced_image(self, filename):
        path = _require_sample(filename)
        placeholder = Image.new('RGB', (8, 8))

        result = thumbnail_source(path, placeholder)

        assert result is not placeholder
        assert result.mode == 'RGB'
        assert max(result.size) > DISPLAY_PREVIEW_MIN_LONG_EDGE
        assert min(result.size) > 0
        assert np.asarray(result).std() > 0


class TestPreviewGateSplitsBrandsAtTheConfiguredDefault:
    """The /image route reads raw_decode.preview_min_sensor_ratio (default
    0.5, see api/raw_processing.py) and passes it straight through to
    load_display_image. Checked two ways: directly, at the real default,
    for whichever brands are unambiguously on one side of it; and via a
    ratio-straddle that exercises the gate mechanism itself for every
    brand, including the two that sit close enough to 0.5 to be brittle."""

    @pytest.mark.parametrize("filename", BRAND_SAMPLE_FILES)
    def test_matches_the_shipped_default_away_from_the_boundary(self, filename):
        path = _require_sample(filename)
        ratio = _measure_preview_ratio(path)
        if abs(ratio - _DEFAULT_MIN_SENSOR_RATIO) < _BOUNDARY_SAFETY_MARGIN:
            pytest.skip(f"{filename} ratio={ratio:.3f} is within "
                       f"{_BOUNDARY_SAFETY_MARGIN} of the {_DEFAULT_MIN_SENSOR_RATIO} "
                       "default; covered by the straddle test instead")
        sensor_dims = sorted(_sensor_dims(path))

        display = load_display_image(path, min_preview_sensor_ratio=_DEFAULT_MIN_SENSOR_RATIO)

        serves_preview = sorted(display.size) != sensor_dims
        assert serves_preview == (ratio > _DEFAULT_MIN_SENSOR_RATIO)

    @pytest.mark.parametrize("filename", BRAND_SAMPLE_FILES)
    def test_gate_straddles_each_files_own_measured_ratio(self, filename):
        """Drives the ratio explicitly per file instead of asserting a fixed
        side of 0.5, so a LibRaw/rawpy change to any one brand's preview
        size — not just ORF/RW2's — cannot turn into a spurious failure."""
        path = _require_sample(filename)
        ratio = _measure_preview_ratio(path)
        sensor_dims = sorted(_sensor_dims(path))
        below = max(0.0, ratio - _STRADDLE_MARGIN)
        above = min(1.0, ratio + _STRADDLE_MARGIN)

        serves_preview = load_display_image(path, min_preview_sensor_ratio=below)
        falls_back = load_display_image(path, min_preview_sensor_ratio=above)

        assert sorted(falls_back.size) == sensor_dims
        assert sorted(serves_preview.size) != sensor_dims


class TestPreviewOrientationMatchesTheDemosaic:
    """unpack_thumb performs no rotation and some previews carry no EXIF —
    a genuine risk that a preview-sourced display image ends up sideways
    relative to the demosaic. sample.nef (flip=5, rotated 90 degrees by
    LibRaw during postprocess) is the one fixture among these 8 that
    actually exercises a non-trivial rotation."""

    @pytest.mark.parametrize("filename", BRAND_SAMPLE_FILES)
    def test_portrait_stays_portrait(self, filename):
        path = _require_sample(filename)
        pil_img, _ = _decode_metrics_cached(str(path))
        assert pil_img is not None

        display = load_display_image(path)

        assert display is not None
        assert _is_portrait(display.size) == _is_portrait(pil_img.size)


class TestDegeneratePaths:
    @pytest.mark.parametrize("filename", BRAND_SAMPLE_FILES)
    def test_truncated_file_never_raises(self, filename, tmp_path):
        path = _require_sample(filename)
        truncated = tmp_path / f"truncated{path.suffix}"
        truncated.write_bytes(path.read_bytes()[:4096])

        result = load_display_image(str(truncated))

        if result is not None:
            assert result.mode == 'RGB'
            assert result.size[0] > 0 and result.size[1] > 0

    def test_severely_truncated_rw2_degrades_to_a_black_frame_not_none(self, tmp_path):
        """Unlike the other 7 brands (which return None at this truncation
        size — see test_truncated_file_never_raises), RW2 does not error on
        either extract_thumb or postprocess: LibRaw opens the header fine,
        finds no thumbnail, then silently zero-fills the demosaic instead of
        raising. Documented explicitly so a future "RW2 truncation -> None"
        assumption doesn't sneak in unverified."""
        path = _require_sample("sample.rw2")
        truncated = tmp_path / "truncated.rw2"
        truncated.write_bytes(path.read_bytes()[:4096])

        result = load_display_image(str(truncated))

        assert result is not None
        assert np.asarray(result).max() == 0

    @pytest.mark.parametrize("filename", BRAND_SAMPLE_FILES)
    def test_missing_file_returns_none(self, filename, tmp_path):
        _require_sample(filename)  # only run brands actually available on this host
        missing = tmp_path / f"gone{Path(filename).suffix}"

        assert load_display_image(str(missing)) is None


class TestMeasuredPreviewRatios:
    @pytest.mark.parametrize("filename, expected", list(_MEASURED_PREVIEW_RATIOS.items()))
    def test_ratio_is_in_the_ballpark_of_the_recorded_value(self, filename, expected):
        path = _require_sample(filename)

        ratio = _measure_preview_ratio(path)

        assert abs(ratio - expected) < _RATIO_TOLERANCE, (
            f"{filename}: measured ratio {ratio:.3f} drifted more than "
            f"{_RATIO_TOLERANCE} from the recorded {expected}"
        )
