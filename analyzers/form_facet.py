"""
Form facet + Matsuda colour harmony for Facet (CPU-only, opt-in weights).

Five explainable 0-10 metrics computed with numpy/scipy/scikit-learn from a
PIL image:

- ``form_symmetry``     left-right mirror symmetry of the grayscale image
- ``form_balance``      visual balance (edge-energy centroid vs frame centre)
- ``form_edge_entropy`` entropy of the edge-orientation histogram
- ``form_fractal``      box-counting fractal dimension of the edge map
- ``color_harmony``     Matsuda hue-template harmony of the dominant palette

All metrics are computed on a fixed working copy (long side resized to
``WORKING_LONG_SIDE``) so scan-time (full decode) and backfill (640px stored
thumbnail) produce comparable values.

``color_harmony`` lives here rather than in ``analyzers/color_facet.py``
because it shares the fixed working-size pipeline and 0-10 score semantics of
the form metrics; ``color_facet.py`` produces categorical gallery facets
(dominant hue bucket / warm-cool label), which is a different contract.

``compute_form_metrics`` never raises — a malformed image returns a dict of
None values and the caller simply stores NULL for that photo. ``color_harmony``
is None for monochrome images (mirroring the ``is_monochrome`` neutral guard
in ``processing.scorer.build_metric_vector``).
"""

import logging

import numpy as np

logger = logging.getLogger("facet.form_facet")

FORM_METRIC_COLUMNS = (
    'form_symmetry', 'form_balance', 'form_edge_entropy', 'form_fractal',
    'color_harmony',
)

# Fixed working size (long side, px). Both the scan path (full decode) and the
# backfill path (640px thumbnail) resize to this before computing anything, so
# scale-sensitive metrics (fractal, edges) stay comparable.
WORKING_LONG_SIDE = 512

# Mirrors analyzers.technical.TechnicalAnalyzer.detect_monochrome: images whose
# mean saturation sits below this are monochrome -> color_harmony is NULL.
_MONO_SATURATION_THRESHOLD = 0.10

_ORIENTATION_BINS = 16
_KMEANS_CLUSTERS = 5
_KMEANS_MAX_SAMPLES = 20000
_ROTATION_STEP_DEG = 2.0

# Matsuda hue-harmony templates as tuples of (sector centre offset deg, sector
# width deg). Widths follow Matsuda (1995) / Cohen-Or et al. (2006): narrow
# sector = 18deg, wide sector = 93.6deg, half wheel = 180deg. Each template is
# rotated to its best fit before scoring.
_MATSUDA_TEMPLATES = {
    'i': ((0.0, 18.0),),
    'V': ((0.0, 93.6),),
    'L': ((0.0, 18.0), (90.0, 79.2)),
    'I': ((0.0, 18.0), (180.0, 18.0)),
    'T': ((0.0, 180.0),),
    'Y': ((0.0, 93.6), (180.0, 18.0)),
    'X': ((0.0, 93.6), (180.0, 93.6)),
}

# The X template leaves two (180 - 93.6) = 86.4deg gaps, so after minimizing
# over all templates no hue can sit further than half a gap (43.2deg) from a
# sector. Normalizing by it maps the theoretical worst fit to score 0.
_MAX_TEMPLATE_DISTANCE_DEG = (360.0 - 2 * 93.6) / 4.0


def _working_image(pil_image):
    """Resize to the fixed working size and return (rgb, hsv) float32 0-1 arrays."""
    from PIL import Image

    img = pil_image.convert('RGB')
    w, h = img.size
    scale = WORKING_LONG_SIDE / max(w, h)
    img = img.resize(
        (max(1, round(w * scale)), max(1, round(h * scale))),
        Image.Resampling.LANCZOS,
        reducing_gap=2.0,
    )
    rgb = np.asarray(img, dtype=np.float32) / 255.0
    hsv = np.asarray(img.convert('HSV'), dtype=np.float32) / 255.0
    return rgb, hsv


def _mirror_symmetry(gray):
    """1 - normalized mean |I - mirror(I)|, scaled to 0-10.

    gray is in [0, 1]; a mean absolute mirror error of 0.5 (e.g. a frame whose
    halves swap black and white) already maps to 0.
    """
    err = float(np.mean(np.abs(gray - gray[:, ::-1])))
    return round(10.0 * (1.0 - min(1.0, err / 0.5)), 2)


def _visual_balance(gray, energy):
    """Inverted, normalized distance of the edge-energy centroid from centre.

    Distance is normalized by sqrt(0.5) (centre -> corner), so a perfectly
    centred mass scores 10 and mass concentrated in a corner scores 0. Flat
    images fall back to the intensity centroid.
    """
    total = float(energy.sum())
    if total <= 1e-6:
        energy = gray + 1e-6
        total = float(energy.sum())
    h, w = gray.shape
    ys, xs = np.mgrid[0:h, 0:w]
    cx = float((energy * xs).sum()) / total / max(w - 1, 1)
    cy = float((energy * ys).sum()) / total / max(h - 1, 1)
    dist = float(np.hypot(cx - 0.5, cy - 0.5))
    return round(10.0 * (1.0 - min(1.0, dist / np.sqrt(0.5))), 2)


def _edge_orientation_entropy(gx, gy, energy):
    """Shannon entropy of the magnitude-weighted edge-orientation histogram.

    Orientations are undirected (mod pi), binned into _ORIENTATION_BINS buckets
    and normalized by the maximum entropy log2(bins) to 0-10.
    """
    if float(energy.sum()) <= 1e-6:
        return 0.0
    theta = np.mod(np.arctan2(gy, gx), np.pi)
    hist, _ = np.histogram(
        theta, bins=_ORIENTATION_BINS, range=(0.0, np.pi), weights=energy
    )
    p = hist / hist.sum()
    p = p[p > 0]
    entropy = float(-np.sum(p * np.log2(p)))
    return round(10.0 * entropy / np.log2(_ORIENTATION_BINS), 2)


def _fractal_dimension(energy):
    """2D box-counting dimension of the thresholded edge map, mapped to 0-10.

    The binary edge map (energy > mean + std) is embedded in a fixed
    WORKING_LONG_SIDE square; N(s) is counted for power-of-two box sizes and D
    is the slope of log N vs log(1/s). D in [1, 2] maps linearly to [0, 10].
    """
    edges = energy > (float(energy.mean()) + float(energy.std()))
    if int(edges.sum()) < 64:
        return 0.0
    size = WORKING_LONG_SIDE
    canvas = np.zeros((size, size), dtype=bool)
    canvas[:edges.shape[0], :edges.shape[1]] = edges[:size, :size]
    box_sizes = np.array([2, 4, 8, 16, 32, 64, 128, 256])
    counts = []
    for s in box_sizes:
        view = canvas.reshape(size // s, s, size // s, s)
        counts.append(int(view.any(axis=(1, 3)).sum()))
    dimension = float(np.polyfit(np.log(1.0 / box_sizes), np.log(counts), 1)[0])
    return round(10.0 * min(1.0, max(0.0, dimension - 1.0)), 2)


def _template_fit_distance(cluster_hues, cluster_weights):
    """Weighted mean hue distance to the best-fitting rotated Matsuda template.

    For every template and every rotation the distance of each palette hue to
    the nearest sector (0 inside a sector, arc distance to the closest border
    outside) is averaged with the cluster weights; the minimum over rotations
    and templates is returned (degrees).
    """
    rotations = np.arange(0.0, 360.0, _ROTATION_STEP_DEG)
    total_weight = float(cluster_weights.sum())
    best = float('inf')
    for sectors in _MATSUDA_TEMPLATES.values():
        dist = np.full((rotations.size, cluster_hues.size), np.inf)
        for offset, width in sectors:
            centers = (rotations[:, None] + offset) % 360.0
            diff = np.abs((cluster_hues[None, :] - centers + 180.0) % 360.0 - 180.0)
            dist = np.minimum(dist, np.maximum(0.0, diff - width / 2.0))
        fit = (dist * cluster_weights[None, :]).sum(axis=1) / total_weight
        best = min(best, float(fit.min()))
    return best


def _color_harmony(hsv):
    """Matsuda hue-harmony score of the saturation*value-weighted palette.

    Returns None for (near-)monochrome images. The palette is a weighted
    k-means over hue angles on the unit circle (scikit-learn); the score is
    10 * (1 - best_fit_distance / worst_possible_distance).
    """
    hue = hsv[..., 0].ravel() * 360.0
    sat = hsv[..., 1].ravel()
    val = hsv[..., 2].ravel()
    if float(sat.mean()) < _MONO_SATURATION_THRESHOLD:
        return None
    weights = sat * val
    idx = np.flatnonzero(weights > 0.01)
    if idx.size < 100:
        return None
    rng = np.random.default_rng(0)
    if idx.size > _KMEANS_MAX_SAMPLES:
        idx = rng.choice(idx, _KMEANS_MAX_SAMPLES, replace=False)
    angles = np.deg2rad(hue[idx])
    points = np.column_stack([np.cos(angles), np.sin(angles)])
    sample_weights = weights[idx]
    from sklearn.cluster import KMeans

    km = KMeans(n_clusters=_KMEANS_CLUSTERS, n_init=4, random_state=0)
    labels = km.fit_predict(points, sample_weight=sample_weights)
    centers = km.cluster_centers_
    cluster_hues = np.rad2deg(np.arctan2(centers[:, 1], centers[:, 0])) % 360.0
    cluster_weights = np.array([
        float(sample_weights[labels == i].sum()) for i in range(_KMEANS_CLUSTERS)
    ])
    keep = cluster_weights > 0
    if not keep.any():
        return None
    best = _template_fit_distance(cluster_hues[keep], cluster_weights[keep])
    return round(10.0 * (1.0 - min(1.0, best / _MAX_TEMPLATE_DISTANCE_DEG)), 2)


def compute_form_metrics(pil_image):
    """Return the five form/harmony metrics for a PIL image.

    Returns {column: 0-10 float or None}; all values are None on failure and
    color_harmony alone is None for monochrome images. Never raises.
    """
    none_result = {col: None for col in FORM_METRIC_COLUMNS}
    if pil_image is None:
        return none_result
    try:
        from scipy import ndimage

        rgb, hsv = _working_image(pil_image)
        gray = (
            0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
        ).astype(np.float32)
        gx = ndimage.sobel(gray, axis=1)
        gy = ndimage.sobel(gray, axis=0)
        energy = np.hypot(gx, gy)
        return {
            'form_symmetry': _mirror_symmetry(gray),
            'form_balance': _visual_balance(gray, energy),
            'form_edge_entropy': _edge_orientation_entropy(gx, gy, energy),
            'form_fractal': _fractal_dimension(energy),
            'color_harmony': _color_harmony(hsv),
        }
    except Exception:
        logger.debug("Form facet extraction failed", exc_info=True)
        return none_result
