"""Part B: the colour-facet extractor computes a dominant hue + warm/cool/neutral
classification from a PIL image, and never crashes on bad input.
"""

import numpy as np
import pytest
from PIL import Image

from analyzers.color_facet import classify_color_temp, extract_color_facet


def _solid(rgb, size=(64, 64)):
    return Image.new("RGB", size, rgb)


# --- classification helper -------------------------------------------------- #

@pytest.mark.parametrize(
    "hue,sat,expected",
    [
        (10.0, 0.8, "warm"),     # red
        (40.0, 0.8, "warm"),     # orange
        (210.0, 0.8, "cool"),    # blue
        (180.0, 0.8, "cool"),    # cyan
        (120.0, 0.8, "neutral"), # green band -> neutral
        (10.0, 0.05, "neutral"), # low saturation -> neutral regardless of hue
        (None, None, "neutral"),
    ],
)
def test_classify_color_temp(hue, sat, expected):
    assert classify_color_temp(hue, sat) == expected


# --- extraction ------------------------------------------------------------- #

def test_red_image_is_warm():
    hue, temp = extract_color_facet(_solid((220, 20, 20)))
    assert temp == "warm"
    # Red sits near 0/360 degrees.
    assert hue is not None and (hue <= 30 or hue >= 330)


def test_blue_image_is_cool():
    hue, temp = extract_color_facet(_solid((20, 40, 220)))
    assert temp == "cool"
    assert hue is not None and 195 <= hue <= 270


def test_grey_image_is_neutral_with_no_hue():
    # A flat grey has no saturated pixels -> no dominant hue, neutral temp.
    hue, temp = extract_color_facet(_solid((128, 128, 128)))
    assert hue is None
    assert temp == "neutral"


def test_none_image_returns_none_pair():
    assert extract_color_facet(None) == (None, None)


def test_malformed_input_never_raises():
    # A non-image object falls into the guarded except -> (None, None).
    class NotAnImage:
        def convert(self, _mode):
            raise ValueError("not an image")

    assert extract_color_facet(NotAnImage()) == (None, None)


def test_hue_is_in_degrees_range():
    # A green-ish image still yields a hue inside [0, 360).
    img = Image.fromarray(np.full((32, 32, 3), (30, 200, 60), dtype=np.uint8))
    hue, _temp = extract_color_facet(img)
    assert hue is not None
    assert 0.0 <= hue < 360.0
