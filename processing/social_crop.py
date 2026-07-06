"""Deterministic saliency-aware crop geometry for social-export presets.

Given the original image dimensions, a target aspect ratio and an optional
normalized subject box, ``compute_crop_rect`` returns the largest crop window of
that aspect that fits fully inside the image, positioned to best contain the
subject (expanded by a margin) and centered on the subject, clamped at the
edges. When the padded subject is larger than the maximal crop it cannot fit
fully; the window then covers as much as possible centered on the subject.

Pure geometry: no model, no image decode, fully deterministic and unit-tested.
"""

from typing import Optional, Sequence, Tuple


def parse_aspect(aspect: str) -> Tuple[float, float]:
    """Parse a ``"w:h"`` aspect string into a ``(width, height)`` float pair.

    Raises ValueError on a malformed or non-positive aspect.
    """
    parts = aspect.split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid aspect ratio: {aspect!r}")
    try:
        w = float(parts[0])
        h = float(parts[1])
    except ValueError:
        raise ValueError(f"Invalid aspect ratio: {aspect!r}") from None
    if w <= 0 or h <= 0:
        raise ValueError(f"Aspect ratio components must be positive: {aspect!r}")
    return w, h


def compute_crop_rect(
    img_w: int,
    img_h: int,
    aspect_w: float,
    aspect_h: float,
    subject_norm: Optional[Sequence[float]] = None,
    margin_frac: float = 0.0,
) -> Tuple[int, int, int, int]:
    """Return the pixel crop rectangle ``(x0, y0, x1, y1)`` for a target aspect.

    Args:
        img_w, img_h: Original image dimensions in pixels (must be positive).
        aspect_w, aspect_h: Target aspect ratio components (width:height).
        subject_norm: Optional ``[x0, y0, x1, y1]`` subject box normalized 0..1.
            None centers the crop on the image (center-crop fallback).
        margin_frac: Fraction of the subject box size added as breathing room on
            each side before centering (e.g. 0.08 for an 8% margin).

    Returns:
        Integer ``(x0, y0, x1, y1)`` with ``0 <= x0 < x1 <= img_w`` and
        ``0 <= y0 < y1 <= img_h``, whose aspect matches the target within
        rounding.
    """
    if img_w <= 0 or img_h <= 0:
        raise ValueError("Image dimensions must be positive")
    if aspect_w <= 0 or aspect_h <= 0:
        raise ValueError("Aspect ratio components must be positive")

    target_ar = aspect_w / aspect_h
    img_ar = img_w / img_h

    if img_ar >= target_ar:
        crop_h = float(img_h)
        crop_w = crop_h * target_ar
    else:
        crop_w = float(img_w)
        crop_h = crop_w / target_ar

    if subject_norm is not None:
        sx0 = min(subject_norm[0], subject_norm[2]) * img_w
        sy0 = min(subject_norm[1], subject_norm[3]) * img_h
        sx1 = max(subject_norm[0], subject_norm[2]) * img_w
        sy1 = max(subject_norm[1], subject_norm[3]) * img_h
        pad_w = (sx1 - sx0) * margin_frac
        pad_h = (sy1 - sy0) * margin_frac
        center_x = (sx0 - pad_w + sx1 + pad_w) / 2
        center_y = (sy0 - pad_h + sy1 + pad_h) / 2
    else:
        center_x = img_w / 2
        center_y = img_h / 2

    x0 = center_x - crop_w / 2
    y0 = center_y - crop_h / 2
    x0 = max(0.0, min(x0, img_w - crop_w))
    y0 = max(0.0, min(y0, img_h - crop_h))

    x0i = int(round(x0))
    y0i = int(round(y0))
    x1i = x0i + int(round(crop_w))
    y1i = y0i + int(round(crop_h))

    if x1i > img_w:
        x0i = max(0, x0i - (x1i - img_w))
        x1i = img_w
    if y1i > img_h:
        y0i = max(0, y0i - (y1i - img_h))
        y1i = img_h

    return x0i, y0i, x1i, y1i
