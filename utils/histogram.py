"""Packing and decoding for the per-photo histogram BLOB (``photos.histogram_data``).

Two formats coexist on disk and every reader must accept both until a library has
been fully rescanned:

* **legacy, 1024 bytes** — 256 ``float32`` luminance bins already normalised to
  sum 1. Written by every scan before the RGB histogram landed.
* **current, 2048 bytes** — four ``uint16`` channels of 256 bins each, in the
  order luma, R, G, B. Bin counts are scaled by ONE factor shared by all four
  channels, so the height relationship between them survives the round trip;
  per-channel scaling would stretch a near-empty channel to full height and
  invent a colour cast that is not in the photo.

The format is detected by blob length — there is no version byte, because the
legacy blobs already in the wild do not have one.

Both formats are computed from the *metrics* decode of a RAW (see
``utils.image_loading.load_image_from_path``), never from the embedded camera
preview: the preview carries a baked-in tone curve and in-camera DR/HTP/ALO
modes lift dark frames non-linearly, which is fine for display and wrong for
measuring exposure.
"""

import numpy as np

HISTOGRAM_BINS = 256
HISTOGRAM_CHANNELS = ('luma', 'r', 'g', 'b')
LEGACY_HISTOGRAM_BLOB_SIZE = HISTOGRAM_BINS * 4
HISTOGRAM_BLOB_SIZE = HISTOGRAM_BINS * len(HISTOGRAM_CHANNELS) * 2

# "Clipped" is the pixel that reached the end of the scale and lost its value:
# exactly bin 0 or exactly bin 255, never a band around them. That is a
# different measurement from ``photos.shadow_clipped`` /
# ``highlight_clipped``, which are binary flags over the luminance bands 0-30
# and 225-255 and feed exposure_score and redundant-bracket culling. The two
# must not be read as versions of each other.
SHADOW_CLIP_BIN = 0
HIGHLIGHT_CLIP_BIN = HISTOGRAM_BINS - 1

# Channels a clipping percentage is measured on. Luma is excluded from the
# per-photo maximum: it is a weighted mix, so it only saturates once the real
# channels already have, and including it could never raise the answer.
CLIP_MEASURED_CHANNELS = ('r', 'g', 'b')

_UINT16_MAX = 65535


def pack_histogram(luma, red, green, blue):
    """Pack four 256-bin count arrays into the 2048-byte ``uint16`` BLOB.

    Counts are scaled by ``65535 / peak`` where ``peak`` is the largest bin
    across all four channels, so the packed values stay directly comparable
    between channels.
    """
    stacked = np.stack([
        np.asarray(c, dtype=np.float64).reshape(HISTOGRAM_BINS)
        for c in (luma, red, green, blue)
    ])
    peak = float(stacked.max())
    if peak > 0:
        stacked = stacked * (_UINT16_MAX / peak)
    return np.rint(stacked).astype('<u2').tobytes()


def unpack_histogram(blob):
    """Decode a stored BLOB into ``{'luma': ndarray, 'rgb': (r, g, b) | None}``.

    ``rgb`` is ``None`` for a legacy blob, which only ever held luminance.
    Returns ``None`` for a missing blob or one whose length matches neither
    format. Values are the stored magnitudes, not a distribution: callers
    normalise for their own purpose (by sum for histogram intersection, by the
    global max for drawing).
    """
    if not blob:
        return None
    size = len(blob)
    if size == HISTOGRAM_BLOB_SIZE:
        channels = np.frombuffer(blob, dtype='<u2').astype(np.float64)
        channels = channels.reshape(len(HISTOGRAM_CHANNELS), HISTOGRAM_BINS)
        return {'luma': channels[0], 'rgb': (channels[1], channels[2], channels[3])}
    if size == LEGACY_HISTOGRAM_BLOB_SIZE:
        return {'luma': np.frombuffer(blob, dtype='<f4').astype(np.float64), 'rgb': None}
    return None


def downsample_bins(values, bins):
    """Sum adjacent bins down to ``bins`` buckets. ``bins`` must divide 256."""
    if bins == HISTOGRAM_BINS:
        return np.asarray(values, dtype=np.float64)
    if HISTOGRAM_BINS % bins:
        raise ValueError(f"bins must divide {HISTOGRAM_BINS}, got {bins}")
    return np.asarray(values, dtype=np.float64).reshape(bins, HISTOGRAM_BINS // bins).sum(axis=1)


def clip_percents(decoded, decimals=4):
    """Percentage of pixels sitting exactly on bin 0 / bin 255, per channel.

    Returns ``{'shadow': {...}, 'highlight': {...}}`` keyed by luma/r/g/b, or
    ``None`` for a legacy blob — which never held the channels, so its answer
    is *unknown* and must never be rendered as zero.

    Derivable from the stored BLOB with no image decode because
    ``pack_histogram`` scales all four channels by ONE factor: it cancels in
    ``bin / total``, so the ratio survives the uint16 round trip even though
    the counts themselves do not.
    """
    if decoded is None or decoded['rgb'] is None:
        return None
    channels = dict(zip(HISTOGRAM_CHANNELS, (decoded['luma'],) + tuple(decoded['rgb'])))
    out = {'shadow': {}, 'highlight': {}}
    for name, counts in channels.items():
        total = float(np.asarray(counts, dtype=np.float64).sum())
        for direction, index in (('shadow', SHADOW_CLIP_BIN), ('highlight', HIGHLIGHT_CLIP_BIN)):
            share = float(counts[index]) / total * 100.0 if total > 0 else 0.0
            out[direction][name] = round(share, decimals)
    return out


def max_clip_percents(decoded, decimals=4):
    """``(shadow_pct, highlight_pct)`` for the worst of R/G/B in each direction.

    ``(None, None)`` for a legacy blob. Max-across-channels is what the stored
    columns hold: a single channel blowing out is the case luminance alone
    cannot see, and "any channel above N%" needs no more than the worst one.
    """
    percents = clip_percents(decoded, decimals=decimals)
    if percents is None:
        return None, None
    return tuple(
        round(max(percents[direction][c] for c in CLIP_MEASURED_CHANNELS), decimals)
        for direction in ('shadow', 'highlight')
    )


def _interior_bins(counts):
    """The counts with both clipping bins zeroed, for drawing.

    A clipped frame puts a large share of its pixels in one bin, and that spike
    becomes the global maximum — normalising against it flattens the whole
    tonal curve into a hairline at the baseline and destroys the only thing the
    curve is for. The spikes are reported separately as clipping percentages
    and drawn as end markers instead.
    """
    interior = np.asarray(counts, dtype=np.float64).copy()
    interior[SHADOW_CLIP_BIN] = 0.0
    interior[HIGHLIGHT_CLIP_BIN] = 0.0
    return interior


def display_channels(decoded, bins=HISTOGRAM_BINS, decimals=4):
    """Turn a decoded histogram into draw-ready lists in ``[0, 1]``.

    Scaled over the interior bins (1..254) only, and every channel is divided
    by the single largest interior bin across all channels — per-channel
    maxima would stretch a near-empty channel to full height and invent a
    colour cast the photo does not have. Returns
    ``{'luma': [...], 'r': [...] | None, 'g': ..., 'b': ...}``.
    """
    rgb = decoded['rgb']
    channels = [decoded['luma']] if rgb is None else [decoded['luma'], *rgb]
    series = [downsample_bins(_interior_bins(c), bins) for c in channels]
    peak = max(float(s.max()) for s in series)
    if peak > 0:
        series = [s / peak for s in series]
    rounded = [np.round(s, decimals).tolist() for s in series]
    if rgb is None:
        return {'luma': rounded[0], 'r': None, 'g': None, 'b': None}
    return dict(zip(HISTOGRAM_CHANNELS, rounded))
