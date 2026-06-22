"""
Color facet extraction for Facet (opt-in).

Computes a cheap dominant hue (0-360) and a warm/cool/neutral colour-temperature
classification from the stored 640px thumbnail using only PIL + numpy (no GPU,
no new heavy dependency). Used by the ``--recompute-colors`` pass; the resulting
``dominant_hue`` / ``color_temp`` columns power an always-on gallery facet.

Every public function is guarded so a malformed image returns (None, None)
rather than raising — the recompute pass simply skips that photo.
"""

import logging

logger = logging.getLogger("facet.color_facet")

# Warm hues straddle the 0/360 wrap (reds/oranges/yellows), cool hues are the
# cyan/blue/violet band. Greens and very low-saturation pixels fall through to
# 'neutral'. Saturation/value floors drop near-grey and near-black pixels so a
# dim background doesn't dominate the hue histogram.
_MIN_SATURATION = 0.15
_MIN_VALUE = 0.10


def classify_color_temp(hue, saturation):
    """Map a dominant hue + mean saturation to 'warm' | 'cool' | 'neutral'.

    Low overall saturation -> 'neutral' regardless of hue. Otherwise warm =
    red/orange/yellow band (hue <= 60 or hue >= 300), cool = cyan/blue/violet
    band (150 <= hue <= 270); the green transition bands resolve to 'neutral'.
    """
    if hue is None or saturation is None or saturation < _MIN_SATURATION:
        return "neutral"
    if hue <= 60 or hue >= 300:
        return "warm"
    if 150 <= hue <= 270:
        return "cool"
    return "neutral"


def extract_color_facet(pil_image):
    """Return (dominant_hue, color_temp) for a PIL image, or (None, None).

    dominant_hue is the mode of the hue histogram over saturated, non-dark
    pixels, in degrees [0, 360). color_temp is the warm/cool/neutral label.
    Never raises — returns (None, None) on any failure or empty image.
    """
    if pil_image is None:
        return None, None
    try:
        import numpy as np

        # HSV in PIL: H,S,V are uint8 [0,255]; H wraps 0..255 -> 0..360 deg.
        hsv = pil_image.convert("RGB").convert("HSV")
        arr = np.asarray(hsv, dtype=np.float32)
        if arr.ndim != 3 or arr.shape[2] != 3 or arr.size == 0:
            return None, None

        h = arr[..., 0].ravel() / 255.0  # 0..1
        s = arr[..., 1].ravel() / 255.0
        v = arr[..., 2].ravel() / 255.0

        mask = (s >= _MIN_SATURATION) & (v >= _MIN_VALUE)
        if not mask.any():
            # Effectively monochrome / very dark — no meaningful dominant hue.
            return None, "neutral"

        h_sel = h[mask]
        # 36 buckets of 10 degrees; take the densest bucket's centre as the mode.
        hist, edges = np.histogram(h_sel, bins=36, range=(0.0, 1.0))
        peak = int(np.argmax(hist))
        hue_deg = float((edges[peak] + edges[peak + 1]) / 2.0 * 360.0)
        hue_deg = hue_deg % 360.0

        mean_sat = float(s[mask].mean())
        return round(hue_deg, 1), classify_color_temp(hue_deg, mean_sat)
    except Exception:
        logger.debug("Color facet extraction failed", exc_info=True)
        return None, None
