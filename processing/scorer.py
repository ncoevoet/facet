"""
Facet scoring engine.

Facet class and supporting functions extracted from facet.py.
"""
from typing import Any
import os
import sys
import time
import sqlite3
import math

# Ensure the script's directory is in Python path for local imports
# This allows running the script from any directory
_project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)

import numpy as np
import warnings
import json
import logging
import functools
import re as _re
from pathlib import Path
import licensing
from int_affinity import storable_int
from licensing import LicenceError
from db import init_database, get_connection
from db.render_version import DISPLAY_RENDER_VERSION
from db.embedding_space import SFACE_MODEL, active_embedding_model
from db.person_carry_over import replace_photo_faces
from db.person_centroids import recompute_person_centroid
from db.schema import FACES_UPSERT_SQL, IQA_SCAN_FINGERPRINT_SQL, face_upsert_row
from db.scoring_overrides import get_photo_scoring_overrides
from db.tags import sync_photo_tags
from db.vec import sync_vec_batch
from processing.progress import emit_progress
from utils.histogram import unpack_histogram
from utils.image_bounds import LIQE_MIN_SHORT_SIDE, liqe_input_too_small


@functools.lru_cache(maxsize=8)
def _photos_upsert(insert_sql):
    """Turn an ``INSERT OR REPLACE INTO photos (...)`` into an UPSERT.

    A re-scan (``--force``) must not destroy user data. ``INSERT OR REPLACE`` is
    DELETE-then-INSERT on a PK conflict, so with foreign keys ON it cascade-deletes
    the photo's faces, tags, comparisons, learned_scores and user_preferences, and
    the re-inserted row NULLs every column absent from the INSERT list (ratings,
    captions, moments, vlm_critique, …). The REPLACE-delete also desyncs the FTS
    index (its delete trigger only fires under recursive_triggers, which is off).

    Rewriting to ``INSERT … ON CONFLICT(path) DO UPDATE SET <scored columns>``
    keeps the row alive: no cascade, preserved columns survive, and the UPDATE
    fires the FTS update trigger correctly. The SET clause is derived from the
    INSERT's own column list, so it can never drift from it.
    """
    cols_match = _re.search(r'INTO\s+photos\s*\((.*?)\)\s*VALUES', insert_sql, _re.S | _re.I)
    columns = [c.strip() for c in cols_match.group(1).split(',')]
    updates = ', '.join(
        (f"{c}=CASE WHEN photos.gps_manually_set=1 THEN photos.{c} ELSE excluded.{c} END"
         if c in ('gps_latitude', 'gps_longitude') else
         f"{c}=CASE WHEN photos.date_manually_set=1 THEN photos.{c} ELSE excluded.{c} END"
         if c in ('date_taken', 'date_manually_set') else f"{c}=excluded.{c}")
        for c in columns if c != 'path'
    )
    base = _re.sub(r'INSERT\s+OR\s+REPLACE\s+INTO\s+photos', 'INSERT INTO photos', insert_sql, flags=_re.I)
    return f"{base}\nON CONFLICT(path) DO UPDATE SET {updates}"


# Identity/EXIF columns inserted for a genuinely new file but never updated on
# conflict, so a restricted pass on an existing row leaves them (and scanned_at,
# thumbnail) alone.
_PARTIAL_CORE_COLUMNS = (
    'path', 'filename', 'image_width', 'image_height', 'date_taken',
    'camera_model', 'lens_model', 'iso', 'f_stop', 'shutter_speed',
    'focal_length', 'focal_length_35mm', 'gps_latitude', 'gps_longitude',
    'phash', 'config_version', 'thumbnail',
)


@functools.lru_cache(maxsize=64)
def _photos_partial_upsert(computed_columns):
    """Build a partial UPSERT that writes ONLY the columns a restricted pass computed.

    A ``--pass X`` / ``--recompute-*`` backfill runs one model, so only its
    columns should change. New identity/EXIF, ``thumbnail``, ``scanned_at`` and
    ``render_version`` are inserted for a genuinely new file but excluded from the
    conflict update, so an existing row keeps everything the pass did not touch —
    no reset of ``scanned_at`` (``--force-since`` reads it), no thumbnail
    re-encode, no NULLing of another pass's data, and no stamp claiming a
    thumbnail this pass never rebuilt.
    """
    insert_cols = list(_PARTIAL_CORE_COLUMNS) + list(computed_columns)
    placeholders = [f":{c}" for c in insert_cols] + ["datetime('now')", str(DISPLAY_RENDER_VERSION)]
    all_cols = insert_cols + ['scanned_at', 'render_version']
    updates = ', '.join(
        (f"{c}=CASE WHEN photos.gps_manually_set=1 THEN photos.{c} ELSE excluded.{c} END"
         if c in ('gps_latitude', 'gps_longitude') else
         f"{c}=CASE WHEN photos.date_manually_set=1 THEN photos.{c} ELSE excluded.{c} END"
         if c in ('date_taken', 'date_manually_set') else f"{c}=excluded.{c}")
        for c in computed_columns
    )
    return (
        f"INSERT INTO photos ({', '.join(all_cols)}) "
        f"VALUES ({', '.join(placeholders)}) "
        f"ON CONFLICT(path) DO UPDATE SET {updates}"
    )

# Optional tqdm for progress bars
try:
    from tqdm import tqdm
except ImportError:
    # Fallback: simple pass-through iterator
    def tqdm(iterable, **kwargs):
        desc = kwargs.get('desc', '')
        if desc:
            logging.getLogger("facet.scorer").info("%s...", desc)
        return iterable

# Suppress standard warnings to keep the CLI output clean
warnings.filterwarnings('ignore')
logging.getLogger('exifread').setLevel(logging.ERROR)

# Import config module (lightweight, no cv2/torch dependency)
from config import ScoringConfig
from config.category_filter import _to_float, with_face_defaults

logger = logging.getLogger("facet.scorer")

# Import shared utilities (lightweight, no cv2/torch dependency)
from utils import (
    get_tag_params, detect_silhouette, tags_to_string,
    load_image_from_path, thumbnail_source,
)
from utils.image_transforms import generate_photo_thumbnail

# Lazy imports for image processing modules
cv2: Any = None
imagehash: Any = None
Image: Any = None
ExifTags: Any = None
BytesIO: Any = None
ThreadPoolExecutor: Any = None
as_completed: Any = None
TechnicalAnalyzer: Any = None
CompositionAnalyzer: Any = None
ImageCache: Any = None

# Lazy imports for GPU-dependent modules (torch, open_clip, batch_processor)
torch: Any = None
F: Any = None
open_clip: Any = None
BatchProcessor: Any = None
load_aesthetic_head: Any = None
score_aesthetic: Any = None

# Lazy imports for new model manager
ModelManager: Any = None
VLMCompositionAnalyzer: Any = None
SAMPNetScorer: Any = None

def _load_image_modules():
    """Load image processing modules only when needed."""
    global cv2, imagehash, Image, ExifTags, BytesIO, ThreadPoolExecutor, as_completed
    global TechnicalAnalyzer, CompositionAnalyzer, ImageCache
    if cv2 is None:
        import cv2 as _cv2
        import imagehash as _imagehash
        from PIL import Image as _Image, ExifTags as _ExifTags
        from io import BytesIO as _BytesIO
        from concurrent.futures import ThreadPoolExecutor as _ThreadPoolExecutor, as_completed as _as_completed
        from analyzers import TechnicalAnalyzer as _TechnicalAnalyzer
        from analyzers import CompositionAnalyzer as _CompositionAnalyzer
        from analyzers import ImageCache as _ImageCache
        cv2 = _cv2
        imagehash = _imagehash
        Image = _Image
        ExifTags = _ExifTags
        BytesIO = _BytesIO
        ThreadPoolExecutor = _ThreadPoolExecutor
        as_completed = _as_completed
        TechnicalAnalyzer = _TechnicalAnalyzer
        CompositionAnalyzer = _CompositionAnalyzer
        ImageCache = _ImageCache

def _load_gpu_modules():
    """Load torch and related modules only when needed."""
    global torch, F, open_clip, BatchProcessor, load_aesthetic_head, score_aesthetic
    if torch is None:
        # Import device policy first so the MPS fallback environment variable
        # is present before torch initialises its Metal backend.
        import utils.device  # noqa: F401
        import torch as _torch
        import torch.nn.functional as _F
        import open_clip as _open_clip
        from processing.batch_processor import BatchProcessor as _BatchProcessor
        from models.aesthetic_head import load_aesthetic_head as _load_aesthetic_head_fn
        from models.aesthetic_head import score_aesthetic as _score_aesthetic
        torch = _torch
        F = _F
        open_clip = _open_clip
        BatchProcessor = _BatchProcessor
        load_aesthetic_head = _load_aesthetic_head_fn
        score_aesthetic = _score_aesthetic


def _load_model_manager_modules():
    """Load model manager and related modules."""
    global ModelManager, VLMCompositionAnalyzer
    if ModelManager is None:
        from models.model_manager import ModelManager as _ModelManager
        from models.vlm_composition import VLMCompositionAnalyzer as _VLMCompositionAnalyzer
        ModelManager = _ModelManager
        VLMCompositionAnalyzer = _VLMCompositionAnalyzer


def _load_samp_net_module():
    """Load SAMP-Net composition scorer module."""
    global SAMPNetScorer
    if SAMPNetScorer is None:
        from models.samp_net import SAMPNetScorer as _SAMPNetScorer
        SAMPNetScorer = _SAMPNetScorer


# EXIF orientation to PIL transpose mapping
# See: https://exiftool.org/TagNames/EXIF.html#Orientation
EXIF_ROTATIONS = {
    2: 'FLIP_LEFT_RIGHT',       # Mirror horizontal
    3: 'ROTATE_180',            # Rotate 180°
    4: 'FLIP_TOP_BOTTOM',       # Mirror vertical
    5: ('FLIP_LEFT_RIGHT', 'ROTATE_90'),   # Mirror horizontal + 90° CW
    6: 'ROTATE_270',            # Rotate 90° CW (270° CCW)
    7: ('FLIP_LEFT_RIGHT', 'ROTATE_270'),  # Mirror horizontal + 270° CW
    8: 'ROTATE_90',             # Rotate 270° CW (90° CCW)
}


def _get_exif_orientation(photo_path):
    """Read EXIF orientation tag without loading full image.

    Uses exifread for fast header-only reading.

    Args:
        photo_path: Path to the image file

    Returns:
        int: EXIF orientation value (1-8), or None if not found
    """
    try:
        import exifread
        with open(photo_path, 'rb') as f:
            tags = exifread.process_file(f, stop_tag='Orientation', details=False)
            if 'Image Orientation' in tags:
                return tags['Image Orientation'].values[0]
    except ImportError:
        # exifread not installed, try PIL
        try:
            from PIL import Image
            img = Image.open(photo_path)
            exif = img.getexif()
            if exif:
                orientation = exif.get(0x0112)  # Orientation tag
                if orientation:
                    return orientation
        except Exception:
            pass
    except Exception:
        pass
    return None


def _apply_exif_rotation(img, orientation):
    """Apply rotation based on EXIF orientation tag value.

    Args:
        img: PIL Image
        orientation: EXIF orientation value (1-8)

    Returns:
        PIL Image: Rotated image (or original if no rotation needed)
    """
    from PIL import Image

    if orientation not in EXIF_ROTATIONS:
        return img

    transform = EXIF_ROTATIONS[orientation]
    if isinstance(transform, tuple):
        for t in transform:
            img = img.transpose(getattr(Image.Transpose, t))
    else:
        img = img.transpose(getattr(Image.Transpose, transform))
    return img


_EXIF_NUMERIC_FIELDS = (
    'iso', 'f_stop', 'focal_length', 'focal_length_35mm',
    'gps_latitude', 'gps_longitude',
)

_EXIF_INT_FIELDS = ('iso',)


def _sanitize_exif_numeric(exif_data):
    """Null out non-finite or unparseable numeric EXIF fields before they reach the database.

    A lens without electronic contacts reports FNumber as N/0, which parses to
    inf; storing it poisons MIN/MAX aggregates (np.histogram rejects a non-finite
    range). A value that does not parse as a float at all (e.g. an ``iso`` of
    ``"Auto"``) is nulled the same way, rather than left in place as TEXT in an
    INTEGER/REAL-affinity column. Guards the exifread/Pillow/subprocess parse
    paths; the persistent ExifTool path rounds ``iso`` the same way in
    exiftool_batch.parse_exif_data (#142).
    """
    for key in _EXIF_NUMERIC_FIELDS:
        value = exif_data.get(key)
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            exif_data[key] = None
            continue
        if not np.isfinite(number):
            exif_data[key] = None
        elif key in _EXIF_INT_FIELDS:
            exif_data[key] = storable_int(number)
    return exif_data


def fix_thumbnail_rotation(db_path):
    """
    Fix thumbnail rotation by reading EXIF orientation from original files
    and rotating existing thumbnails in the database.

    This is a lightweight operation - it does not re-read full images, only the EXIF
    header from each file and the thumbnail from the database.

    Args:
        db_path: Path to the SQLite database
    """
    from PIL import Image
    from io import BytesIO

    logger.info("Fixing thumbnail rotation using EXIF orientation data...")

    with get_connection(db_path) as conn:
        # Get all photos with thumbnails
        cursor = conn.execute(
            "SELECT path, thumbnail FROM photos WHERE thumbnail IS NOT NULL"
        )
        photos = cursor.fetchall()

        logger.info("Found %d photos with thumbnails", len(photos))

        updated = 0
        skipped = 0
        missing = 0
        errors = 0

        try:
            for row in tqdm(photos, desc="Fixing rotations"):
                photo_path = row['path']
                thumbnail_bytes = row['thumbnail']

                if not thumbnail_bytes:
                    skipped += 1
                    continue

                # Check if original file exists
                if not os.path.exists(photo_path):
                    missing += 1
                    continue

                try:
                    # Read EXIF orientation from original file (fast - just reads header)
                    orientation = _get_exif_orientation(photo_path)

                    if orientation in (1, None):
                        # No rotation needed (1 = normal orientation, None = no tag)
                        skipped += 1
                        continue

                    # Load thumbnail from DB
                    thumb_img = Image.open(BytesIO(thumbnail_bytes))

                    # Apply rotation based on EXIF orientation tag
                    rotated = _apply_exif_rotation(thumb_img, orientation)

                    if rotated is not thumb_img:
                        # Save rotated thumbnail back to DB
                        buf = BytesIO()
                        rotated.save(buf, format='JPEG', quality=80)
                        conn.execute(
                            "UPDATE photos SET thumbnail = ? WHERE path = ?",
                            (buf.getvalue(), photo_path)
                        )
                        # A rotated thumbnail is a different image, but this writer
                        # leaves scanned_at alone: a decline of the old one would
                        # still match its fingerprint, so drop it explicitly.
                        conn.execute(
                            "DELETE FROM iqa_declined WHERE photo_path = ?", (photo_path,)
                        )
                        updated += 1
                    else:
                        skipped += 1

                except Exception as e:
                    errors += 1
                    if errors <= 5:
                        logger.error("Error processing %s: %s", photo_path, e)
                    elif errors == 6:
                        logger.error("(Suppressing further error messages...)")

        except KeyboardInterrupt:
            logger.info("Interrupted by user. Saving progress...")

        conn.commit()

    logger.info("Results:")
    logger.info("  Fixed: %d thumbnails", updated)
    logger.info("  Skipped (no rotation needed): %d", skipped)
    if missing > 0:
        logger.info("  Missing original files: %d", missing)
    if errors > 0:
        logger.info("  Errors: %d", errors)


# ============================================
# HELPER FUNCTIONS
# ============================================

# Population std-dev of 0-255 luminance cannot exceed 127.5 (half the range, all mass at both ends).
MAX_HISTOGRAM_SPREAD = 127.5


def _safe_float(val, default=5.0, *, min_value=-100.0, max_value=100.0):
    """Parse a finite number with caller-specific inclusive bounds.

    The legacy default score policy is retained. None disables only that bound;
    raw measurements and EXIF must declare their physical domain explicitly.
    Unsupported/invalid values return the supplied default, never a new clamp.
    """
    if not isinstance(val, (int, float, str)):
        return default
    try:
        number = float(val)
    except (ValueError, OverflowError):
        return default
    if not math.isfinite(number):
        return default
    if min_value is not None and number < min_value:
        return default
    if max_value is not None and number > max_value:
        return default
    return number


def _positive_float(val):
    """A positive finite EXIF value; zero means missing, not a valid exposure."""
    if not isinstance(val, (int, float, str)):
        return None
    number = _to_float(val)
    return number if number is not None and number > 0 else None


def _calculate_scoring_penalties(metrics, config):
    """Calculate penalty adjustments for scoring.

    Args:
        metrics: Dict with noise_sigma, mean_saturation, leading_lines_score keys.
        config: ScoringConfig instance (or None).

    Returns:
        dict with: noise_penalty, noise_sigma, oversaturation_penalty, leading_lines, leading_lines_blend
    """
    penalty_settings = config.get_penalty_settings() if config else {}

    noise_sigma = _safe_float(metrics.get('noise_sigma'), 0, min_value=0, max_value=None)
    noise_threshold = penalty_settings.get('noise_sigma_threshold', 4.0)
    noise_penalty_max = penalty_settings.get('noise_max_penalty_points', 1.5)
    noise_penalty_rate = penalty_settings.get('noise_penalty_per_sigma', 0.3)
    noise_penalty = 0
    if noise_sigma > noise_threshold:
        noise_penalty = min(noise_penalty_max, (noise_sigma - noise_threshold) * noise_penalty_rate)

    mean_saturation = _safe_float(metrics.get('mean_saturation'), 0, min_value=0, max_value=1)
    oversat_threshold = penalty_settings.get('oversaturation_threshold', 0.9)
    oversat_penalty_amount = penalty_settings.get('oversaturation_penalty_points', 0.5)
    oversaturation_penalty = oversat_penalty_amount if mean_saturation > oversat_threshold else 0

    leading_lines = min(10.0, _safe_float(metrics.get('leading_lines_score'), 0) * 1.77)
    leading_lines_blend = penalty_settings.get('leading_lines_blend_percent', 30) / 100

    return {
        'noise_penalty': noise_penalty,
        'noise_sigma': noise_sigma,
        'oversaturation_penalty': oversaturation_penalty,
        'leading_lines': leading_lines,
        'leading_lines_blend': leading_lines_blend,
    }


# Metric keys that calculate_aggregate_logic weights. Single source of truth for
# the scoring feature space, shared with the weight optimizer so training and
# serving use the exact same metrics. 'quality' is intentionally excluded from
# the optimizable set: it is always 0 here (folded into 'aesthetic' by
# fold_quality_weight before the weights are applied).
SCORING_METRIC_KEYS = (
    'aesthetic', 'face_quality', 'face_sharpness', 'eye_sharpness', 'tech_sharpness',
    'composition', 'power_point', 'leading_lines',
    'exposure', 'color', 'contrast', 'dynamic_range', 'saturation', 'noise',
    'isolation',
    'aesthetic_iaa', 'face_quality_iqa', 'liqe',
    'subject_sharpness', 'subject_prominence', 'subject_placement', 'bg_separation',
)


def build_metric_vector(m, cfg, category, penalties=None, unavailable=()):
    """Build the per-metric 0-10 scoring vector (pre-weighting).

    Single source of truth for the metric values that feed the weighted
    aggregate. Used by calculate_aggregate_logic for scoring and by the weight
    optimizer for training, so both share the exact same feature space. Returns
    {metric_key: value}; values sit in each metric's natural 0-10 range and
    'noise' is pre-inverted (higher = less noise = better).

    penalties: precomputed _calculate_scoring_penalties result, to avoid a second
               pass when the caller already has it.
    unavailable: metric keys to leave out instead of substituting the neutral
                 5.0 (commercial mode). Only scoring passes it; the optimizer
                 keeps the default () and so sees every metric.
    """
    safe_float = _safe_float
    exif_settings = cfg.get_exif_adjustments() if cfg else {}

    # ISO-aware sharpness compensation
    adjusted_sharpness = safe_float(m.get('tech_sharpness'), 5.0)
    if exif_settings.get('iso_sharpness_compensation', True):
        iso = _positive_float(m.get('iso'))
        if iso and iso > 800:
            adjusted_sharpness = min(10.0, adjusted_sharpness + 0.5 * np.log2(iso / 800))

    # Aperture-based isolation boost, normalized to 0-10
    effective_isolation = safe_float(m.get('isolation_bonus'), 1.0, min_value=1, max_value=None)
    if exif_settings.get('aperture_isolation_boost', True):
        f_stop = _positive_float(m.get('f_stop'))
        if f_stop and f_stop <= 2.8:
            multiplier = 1.5 if f_stop <= 2.0 else 1.3
            effective_isolation = min(3.0, effective_isolation * multiplier)
    isolation_score = min(10.0, (effective_isolation - 1.0) * 5.0)

    dynamic_range_score = min(10.0, safe_float(m.get('histogram_spread'), 0, min_value=0, max_value=MAX_HISTOGRAM_SPREAD) / 6.0)

    if penalties is None:
        penalties = _calculate_scoring_penalties(m, cfg)
    noise_sigma = penalties['noise_sigma']
    leading_lines = penalties['leading_lines']
    leading_lines_blend = penalties['leading_lines_blend']

    aes = safe_float(m.get('aesthetic'), 5.0)
    exp = safe_float(m.get('exposure_score'), 5.0)
    col = safe_float(m.get('color_score'), 5.0)
    if m.get('is_monochrome', 0):
        col = 5.0  # Neutral - don't penalize B&W for low color entropy
    comp_raw = safe_float(m.get('comp_score'), 5.0)
    contrast = safe_float(m.get('contrast_score'), 5.0)
    face_qual = safe_float(m.get('face_quality'), 5.0)
    eye_sharp = safe_float(m.get('eye_sharpness'), 5.0)

    # Leading-lines bonus only for non-portrait categories
    if category not in ('portrait', 'group_portrait') and leading_lines > 0:
        comp = min(10.0, comp_raw + (leading_lines * leading_lines_blend))
    else:
        comp = comp_raw

    face_sharp = safe_float(m.get('face_sharpness'), 5.0, min_value=0, max_value=None)
    power_point = safe_float(m.get('power_point_score'), 5.0)
    saturation = min(10.0, safe_float(m.get('mean_saturation'), 0.5, min_value=0, max_value=1) * 10.0)
    noise_score = max(0.0, min(10.0, 10.0 - noise_sigma * 0.7))

    result = {
        'aesthetic': aes,
        'face_quality': face_qual,
        'face_sharpness': face_sharp,
        'eye_sharpness': eye_sharp,
        'tech_sharpness': adjusted_sharpness,
        'composition': comp,
        'power_point': power_point,
        'leading_lines': leading_lines,
        'exposure': exp,
        'color': col,
        'contrast': contrast,
        'dynamic_range': dynamic_range_score,
        'saturation': saturation,
        'noise': noise_score,
        'isolation': isolation_score,
        'aesthetic_iaa': safe_float(m.get('aesthetic_iaa'), 5.0),
        'face_quality_iqa': safe_float(m.get('face_quality_iqa'), 5.0),
        'liqe': safe_float(m.get('liqe_score'), 5.0),
        'subject_sharpness': safe_float(m.get('subject_sharpness'), 5.0),
        'subject_prominence': safe_float(m.get('subject_prominence'), 5.0),
        'subject_placement': safe_float(m.get('subject_placement'), 5.0),
        'bg_separation': safe_float(m.get('bg_separation'), 5.0),
        # Form facet + Matsuda color harmony (weights default to 0 in every
        # category, so the aggregate is byte-identical until a user adds them)
        'symmetry': safe_float(m.get('form_symmetry'), 5.0),
        'balance': safe_float(m.get('form_balance'), 5.0),
        'edge_entropy': safe_float(m.get('form_edge_entropy'), 5.0),
        'fractal': safe_float(m.get('form_fractal'), 5.0),
        # Neutral for B&W, mirroring the color_score monochrome guard above
        'color_harmony': 5.0 if m.get('is_monochrome', 0) else safe_float(m.get('color_harmony'), 5.0),
    }

    # Extended IQA tier (config-gated OFF by default). Each metric is exposed to
    # the weighted aggregate only when its column is enabled; its weight defaults
    # to 0, so the aggregate is byte-identical until a weight is configured. When
    # disabled the keys are absent, leaving the feature space identical to before.
    if cfg is not None:
        try:
            ext = cfg.get_extended_iqa_settings()
        except Exception:
            ext = {}
        if ext.get('qrealign'):
            result['qrealign'] = safe_float(m.get('qrealign_score'), 5.0)
        if ext.get('aesthetic_v25'):
            result['aesthetic_v25'] = safe_float(m.get('aesthetic_v25'), 5.0)
        if ext.get('deqa'):
            result['deqa'] = safe_float(m.get('deqa_score'), 5.0)

    for key in unavailable:
        result.pop(key, None)
    return result


# Every key of a weights dict that names a scored metric (the rest are bonus,
# penalty multipliers and underscore flags). 'quality' is folded into
# 'aesthetic' by fold_quality_weight but still carries weight in the raw config.
_WEIGHTED_METRIC_KEYS = frozenset(SCORING_METRIC_KEYS) | {
    'quality', 'symmetry', 'balance', 'edge_entropy', 'fractal', 'color_harmony',
    'qrealign', 'aesthetic_v25', 'deqa',
}


def fold_quality_weight(w):
    """Fold the ``quality`` weight into ``aesthetic``: the scorer's contract that
    ``quality_percent`` is "redistributed into aesthetic" (docs/SCORING.md).

    There is no separate quality signal, so the weight is served by the aesthetic
    metric: ``(aesthetic + quality) * aesthetic_value``. Applied to the raw category
    weights BEFORE :func:`renormalise_weights`, so a commercial install whose
    aesthetic metric is unavailable drops the folded weight with it. Returns a copy.
    """
    return {**w, 'aesthetic': w.get('aesthetic', 0.0) + w.get('quality', 0.0), 'quality': 0.0}


def weighted_metric_contribution(value, weight):
    """Native weighted-sum term shared by scoring and score explanations."""
    return max(0.0, min(10.0, value)) * weight


# The photo columns the scorer reads to recompute an aggregate and a category from
# a stored row (--recompute-average), without the clip_embedding BLOB. Shared with
# the weight optimizer, which re-serves a category's rows to measure what an apply
# does to its mean score.
SERVED_ROW_COLUMNS = (
    'path', 'aesthetic', 'face_count', 'face_quality', 'eye_sharpness', 'face_sharpness',
    'face_ratio', 'tech_sharpness', 'color_score', 'exposure_score', 'comp_score',
    'isolation_bonus', 'is_blink', 'iso', 'f_stop', 'focal_length', 'shadow_clipped', 'highlight_clipped',
    'is_silhouette', 'histogram_spread', 'is_monochrome', 'contrast_score', 'tags',
    'leading_lines_score', 'histogram_bimodality',
    'raw_sharpness_variance', 'raw_color_entropy', 'raw_eye_sharpness',
    'shutter_speed', 'is_group_portrait', 'mean_luminance', 'scoring_model', 'quality_score',
    'noise_sigma', 'mean_saturation', 'power_point_score', 'dynamic_range_stops',
    'histogram_data', 'topiq_score',
    'aesthetic_iaa', 'face_quality_iqa', 'liqe_score',
    'qrealign_score', 'aesthetic_v25', 'deqa_score',
    'subject_sharpness', 'subject_prominence', 'subject_placement', 'bg_separation',
    'form_symmetry', 'form_balance', 'form_edge_entropy', 'form_fractal', 'color_harmony',
)


def unavailable_for_config(cfg):
    """Metric keys this install cannot compute, memoised on the config object.

    Keyed on the env override and the file's mode so a mode change is seen
    without recomputing the policy per photo.
    """
    if cfg is None:
        return frozenset()
    import licensing
    key = (os.environ.get(licensing.LICENSING_MODE_ENV, ''),
           ((getattr(cfg, 'config', None) or {}).get('licensing') or {}).get('mode'))
    cache = cfg.__dict__.setdefault('_unavailable_metrics_cache', {})
    if key not in cache:
        cache[key] = frozenset(licensing.unavailable_metrics(licensing.resolve_policy(cfg.config)))
    return cache[key]


def renormalise_weights(weights, unavailable):
    """Scoring-time weights with ``unavailable`` metrics dropped and the rest summing to 1.

    Returns a copy; ``weights`` (the raw config values) is never modified.
    """
    out = dict(weights)
    for key in unavailable:
        out[key] = 0.0
    remaining = sum(v for k, v in out.items()
                    if k in _WEIGHTED_METRIC_KEYS and isinstance(v, (int, float)) and v > 0)
    if remaining > 0:
        for k in list(out):
            v = out[k]
            if k in _WEIGHTED_METRIC_KEYS and isinstance(v, (int, float)) and v > 0:
                out[k] = v / remaining
    return out


def build_scoring_metrics(
    *,
    aesthetic,
    face_count, face_quality, eye_sharpness, face_sharpness, face_ratio,
    is_group_portrait, is_blink, isolation_bonus,
    sharpness_data, color_data, histogram_data, mono_data, noise_data, contrast_data,
    comp_score, power_point_score, leading_lines_score,
    is_silhouette, tags,
    iso, f_stop, shutter_speed=None,
    quality_score=None, scoring_model='clip-mlp',
    topiq_score=None, aesthetic_iaa=None, face_quality_iqa=None, liqe_score=None,
    qrealign_score=None, aesthetic_v25=None, deqa_score=None,
    subject_sharpness=None, subject_prominence=None,
    subject_placement=None, bg_separation=None,
    form_data=None,
    scoring_context=None, category_override=None,
):
    """Build the metrics dict consumed by :meth:`Facet.calculate_aggregate_logic`.

    Single source of truth for the scoring feature space at scan time, shared by
    the single-pass batch processor, the single-image PIL scorer, and the
    multi-pass aggregate step, so all three feed calculate_aggregate_logic the
    exact same keys. A key silently dropped from one path (tags, is_monochrome,
    mean_luminance, is_group_portrait, face_sharpness, power_point_score,
    contrast_score, noise_sigma, mean_saturation, ...) makes whole categories
    unreachable and zeroes penalties for that path only. Technical sub-dicts are
    read with the same defaults the multi-pass path uses so a partially computed
    chunk degrades identically everywhere.
    """
    form = form_data or {}
    return {
        'aesthetic': aesthetic,
        'quality_score': quality_score,
        'scoring_model': scoring_model,
        'comp_score': comp_score,
        'face_count': face_count,
        'face_quality': face_quality,
        'eye_sharpness': eye_sharpness,
        'face_sharpness': face_sharpness,
        'tech_sharpness': sharpness_data.get('normalized', 5.0),
        'color_score': color_data.get('normalized', 5.0),
        'exposure_score': histogram_data.get('exposure_score', 5.0),
        'face_ratio': face_ratio,
        'tags': tags,
        'isolation_bonus': isolation_bonus,
        'is_blink': is_blink,
        'is_group_portrait': is_group_portrait,
        'shadow_clipped': histogram_data.get('shadow_clipped', 0),
        'highlight_clipped': histogram_data.get('highlight_clipped', 0),
        'is_silhouette': is_silhouette,
        'histogram_spread': histogram_data.get('spread', 0),
        'histogram_bimodality': histogram_data.get('bimodality', 0),
        'mean_luminance': histogram_data.get('mean_luminance', 0.5),
        'is_monochrome': mono_data.get('is_monochrome', 0),
        'mean_saturation': mono_data.get('mean_saturation', 0),
        'contrast_score': contrast_data.get('contrast_score', 5.0),
        'noise_sigma': noise_data.get('noise_sigma', 0),
        'leading_lines_score': leading_lines_score,
        'power_point_score': power_point_score,
        'topiq_score': topiq_score,
        'aesthetic_iaa': aesthetic_iaa,
        'face_quality_iqa': face_quality_iqa,
        'liqe_score': liqe_score,
        'qrealign_score': qrealign_score,
        'aesthetic_v25': aesthetic_v25,
        'deqa_score': deqa_score,
        'subject_sharpness': subject_sharpness,
        'subject_prominence': subject_prominence,
        'subject_placement': subject_placement,
        'bg_separation': bg_separation,
        'form_symmetry': form.get('form_symmetry'),
        'form_balance': form.get('form_balance'),
        'form_edge_entropy': form.get('form_edge_entropy'),
        'form_fractal': form.get('form_fractal'),
        'color_harmony': form.get('color_harmony'),
        'iso': iso,
        'f_stop': f_stop,
        'shutter_speed': shutter_speed,
        'scoring_context': scoring_context,
        'category_override': category_override,
    }


IQA_PASS_VRAM_MARGIN_GB = 2
CPU_DEVICE_LABEL = "CPU"

# Supplementary IQA columns whose model can decline a photo on purpose, mapped to
# the model name stored in ``iqa_declined.model``. --recompute-iqa remembers such
# a decline (against the photo's scan fingerprint) instead of re-attempting it on
# every run. A map rather than a constant so the selector (_iqa_needs_score_sql)
# and the writer (_run_iqa_pass._flush) stay symmetric if another model ever gains
# a deterministic decline. aesthetic_iaa scores any image; liqe_score's refusal is
# a function of the stored thumbnail's geometry and is checked before decoding;
# qrealign has no expected skip. None of those belongs here.
_IQA_DECLINING_MODELS = {'face_quality_iqa': 'topiq_nr_face'}


def describe_scoring_device(accelerator, vram_gb, ram_gb):
    """Human label for the device a recompute will actually run models on.

    Reads the detected accelerator rather than inferring one from dedicated
    VRAM: Apple Metal reports 0.0GB of VRAM while genuinely running the models
    on the GPU, so a VRAM-derived label called an accelerated Mac "CPU". A
    unified-memory accelerator is labelled with the system RAM it draws from,
    since that pool IS its memory budget.

    Args:
        accelerator: 'cuda', 'mps', or None (see ModelManager.detect_accelerator)
        vram_gb: Dedicated VRAM in GB (0.0 off CUDA)
        ram_gb: Total system RAM in GB

    Returns:
        Label string for the scan log.
    """
    from models.model_manager import UNIFIED_MEMORY_ACCELERATOR

    if accelerator is None:
        return CPU_DEVICE_LABEL
    if accelerator == UNIFIED_MEMORY_ACCELERATOR:
        return "%s accelerator, unified memory (%.0fGB)" % (accelerator, ram_gb)
    return "GPU (%.0fGB)" % vram_gb


# Raised by the batch aesthetic scorer when no CLIP+MLP head is loaded outside
# commercial mode. Path-neutral on purpose: BatchProcessor records it once per
# photo of the failed batch.
_NO_AESTHETIC_HEAD_ERROR = (
    "no aesthetic head loaded: no CLIP+MLP aesthetic head is available for this "
    "profile (SigLIP embeddings, a TOPIQ profile or an embedding_dim other than 768), "
    "so single-pass cannot score aesthetics; run multi-pass"
)


# MAIN SCORER CLASS
# ============================================

class Facet:
    """Core engine for scoring photos and maintaining the persistent database."""

    def __init__(self, db_path='photo_scores_pro.db', config_path=None, lightweight=False, multi_pass=False):
        """
        Initialize the photo scorer.

        Args:
            db_path: Path to SQLite database
            config_path: Path to scoring config JSON
            lightweight: If True, skip loading GPU models (for recalculate-only mode)
            multi_pass: If True, skip heavy GPU models (CLIP, SAMP-Net, tagger).
                        Multi-pass loads its own models via ModelManager per pass,
                        the face analyzer included.
                        Still loads aesthetic_head, tech_analyzer, model_manager.
        """
        self.db_path = db_path
        self.lightweight = lightweight
        self._face_analyzer = None
        # Named persons whose centroid a rescan batch left stale; rebuilt once per
        # scan by flush_person_centroids() instead of once per batch.
        self._pending_centroid_persons = set()

        # Load scoring configuration
        self.config = ScoringConfig(config_path)
        logger.info("Config version: %s", self.config.version_hash)

        if not lightweight:
            # Load image processing and GPU-dependent modules
            _load_image_modules()
            from utils.device import get_device
            _load_gpu_modules()
            self.device = get_device()
            logger.info("Using %s", self.device)

            # Check VRAM compatibility with configured profile
            self.config.check_vram_profile_compatibility(verbose=True)

            # Initialize model manager for VRAM-based model selection
            _load_model_manager_modules()
            self.model_manager = ModelManager(self.config)

            # Check if we should use advanced models (non-legacy profile)
            self.use_advanced_models = not self.model_manager.is_legacy_mode()

            # Default CLIP config (updated below if not multi_pass)
            self._clip_model_name = 'ViT-L-14'
            self._clip_backend = 'open_clip'

            if multi_pass:
                # Multi-pass mode: skip heavy GPU models, they'll be loaded per-pass
                logger.info("Multi-pass mode: skipping eager GPU model loading (profile: %s)", self.model_manager.profile)
                self.vlm_composition = None
                self.samp_scorer = None
                self.model = None
                self.preprocess = None
                self.tagger = None
            elif self.use_advanced_models:
                logger.info("Using advanced scoring models (profile: %s)", self.model_manager.profile)

                # Try to load Qwen2-VL for composition (24GB profile only)
                if self.model_manager.is_using_qwen_composition():
                    try:
                        from models.vlm_composition import create_composition_analyzer
                        self.vlm_composition = create_composition_analyzer(self.model_manager)
                        if self.vlm_composition:
                            logger.info("Qwen2-VL composition analyzer initialized")
                    except Exception as e:
                        licensing.reraise_if_refused()
                        logger.info("Qwen2-VL not available: %s", e)
                        self.vlm_composition = None
                else:
                    self.vlm_composition = None

                # Try to load SAMP-Net for composition (8GB profile)
                samp_config = self.config.get_samp_net_config()
                if self.config.is_using_samp_net() and licensing.allowed('samp_net'):
                    try:
                        model_path = samp_config['model_path']
                        _load_samp_net_module()
                        self.samp_scorer = SAMPNetScorer(
                            model_path=model_path,
                            device=self.device
                        )
                        # Eagerly load U2-Net-P saliency model to avoid loading during batch workers
                        self.samp_scorer.ensure_loaded()
                        logger.info("SAMP-Net composition scorer initialized")
                    except Exception as e:
                        licensing.reraise_if_refused()
                        logger.info("SAMP-Net not available: %s", e)
                        self.samp_scorer = None
                else:
                    self.samp_scorer = None
            else:
                self.vlm_composition = None
                self.samp_scorer = None

            if not multi_pass:
                # Load CLIP/SigLIP model from config (profile selects model variant)
                clip_config = self.config.get_clip_config()
                self._clip_model_name = clip_config.get('model_name', 'ViT-L-14')
                self._clip_backend = clip_config.get('backend', 'open_clip')

                if self._clip_backend == 'transformers':
                    from transformers import AutoProcessor

                    from utils.siglip import load_siglip_model
                    self.model = load_siglip_model(self._clip_model_name, self.device)
                    if self.device == 'cuda':
                        logger.info("SigLIP 2 NaFlex loaded (FP16): %s", self._clip_model_name)
                    else:
                        logger.info("SigLIP 2 NaFlex loaded: %s", self._clip_model_name)
                    self.preprocess = AutoProcessor.from_pretrained(
                        self._clip_model_name, trust_remote_code=True
                    )
                else:
                    clip_pretrained = clip_config.get('pretrained', 'laion2b_s32b_b82k')
                    self.model, _, self.preprocess = open_clip.create_model_and_transforms(
                        self._clip_model_name, pretrained=clip_pretrained
                    )
                    self.model = self.model.to(self.device).eval()

                    # Enable FP16 mode on CUDA for ~20% faster inference and ~2GB VRAM savings
                    if self.device == 'cuda':
                        self.model = self.model.half()
                        logger.info("CLIP model converted to FP16: %s", self._clip_model_name)

            self._load_aesthetic_head()

            if not multi_pass:
                # Apply torch.compile() for faster inference on PyTorch 2.0+
                # Skip on Windows as Triton (required by inductor backend) is not supported
                if hasattr(torch, 'compile') and self.device == 'cuda' and sys.platform != 'win32':
                    from utils.device import torch_compile_status
                    compile_enabled, compile_reason = torch_compile_status()
                    if not compile_enabled:
                        logger.info("Skipping torch.compile(): %s; using eager CUDA inference", compile_reason)
                    else:
                        try:
                            self.model = torch.compile(self.model, mode='reduce-overhead')
                            self.aesthetic_head = torch.compile(self.aesthetic_head, mode='reduce-overhead')
                            logger.info("Models compiled with torch.compile()")
                        except Exception as e:
                            logger.info("torch.compile() not available: %s", e)
                elif self.device == 'cuda' and sys.platform == 'win32':
                    logger.info("Skipping torch.compile() on Windows (Triton not supported)")

            self.tech_analyzer = TechnicalAnalyzer()

            if not multi_pass:
                # Initialize tagger if enabled
                tagging_settings = self.config.get_tagging_settings()
                if tagging_settings.get('enabled', True):
                    from models.tagger import CLIPTagger
                    self.tagger = CLIPTagger(
                        self.model, self.device, config=self.config,
                        model_name=self._clip_model_name,
                        backend=self._clip_backend
                    )
                else:
                    self.tagger = None
        else:
            logger.info("Lightweight mode: skipping main model pipeline")
            self.device = None
            self.model = None
            self.preprocess = None
            self.aesthetic_head = None
            self.face_analyzer = None
            self.tech_analyzer = None
            self.tagger = None
            self.model_manager = None
            self.use_advanced_models = False
            self.vlm_composition = None
            self.samp_scorer = None

        init_database(self.db_path)

    def _load_aesthetic_head(self):
        """Loads the MLP weights that sit on top of CLIP to predict 'Aesthetic' scores.

        Only loaded for ViT-L-14 (768-dim embeddings). SigLIP 2 (1152-dim) uses
        TOPIQ for aesthetics instead.
        """
        # Check if current CLIP model is compatible with the MLP head (768-dim only)
        clip_config = self.config.get_clip_config()
        embedding_dim = clip_config.get('embedding_dim', 768)

        if embedding_dim != 768:
            self.aesthetic_head = None
            return

        # Commercial mode: the LAION head is not permitted, the native Q-ReAlign
        # scorer provides the aesthetic score instead.
        if not licensing.allowed('clip_mlp_head'):
            self.aesthetic_head = None
            return

        self.aesthetic_head = load_aesthetic_head(self.device)

    @property
    def face_analyzer(self):
        """The face analyzer, built on first use instead of at construction.

        InsightFace costs a declared 2.0 GB, and building it here eagerly meant
        a multi-pass scan carried it from startup to the last chunk even though
        that path never reads this attribute: there the analyzer is a model the
        pass planner budgets for and ``ModelManager.unload_model`` releases at
        the end of its pass. Every other pass therefore held 2.0 GB more than
        the plan allowed for it. Deferring the build leaves the single-pass
        scan and the face-extraction commands, which do read it, unchanged.

        Lightweight mode has no device and loads no model, so it has no
        analyzer either; assigning one directly still overrides the build,
        which is how the scan paths are tested with a stand-in.
        """
        if self._face_analyzer is None and not self.lightweight:
            from models.model_manager import build_face_analyzer, build_permissive_face_analyzer
            if licensing.loader_allowed('insightface'):
                self._face_analyzer = build_face_analyzer(self.config, self.device)
            else:
                self._face_analyzer = build_permissive_face_analyzer(self.config)
        return self._face_analyzer

    @face_analyzer.setter
    def face_analyzer(self, analyzer):
        self._face_analyzer = analyzer

    def preflight_models(self):
        """Resolve the lazily built scan models once, before any per-image work.

        The single-pass and dry-run paths otherwise build the face analyzer and
        the commercial aesthetic scorer inside a per-image handler, so a startup
        refusal (a licence gate, a missing package) would be recorded as one
        failure per photo after the GPU had already worked. Raising here stops
        the scan before the first image.
        """
        analyzer = self.face_analyzer
        ensure_models = getattr(analyzer, 'ensure_models', None)
        if ensure_models is not None and not ensure_models():
            raise RuntimeError(
                "The permissive face models (YuNet, SFace) could not be loaded -- the "
                "first run downloads them into pretrained_models/, so check the network "
                "connection, or this OpenCV build lacks FaceDetectorYN/FaceRecognizerSF. "
                "Stopping the scan: it would otherwise record every photo as having no faces.")
        if licensing.is_commercial() and self.aesthetic_head is None:
            self._commercial_aesthetic_scorer()

    @property
    def uses_transformers_backend(self):
        """Check if using transformers backend for CLIP/SigLIP."""
        return self._clip_backend == 'transformers'

    def _encode_images(self, pil_images, clip_inputs=None):
        """Encode one or more images through the CLIP/SigLIP model.

        Args:
            pil_images: Single PIL Image or list of PIL Images
            clip_inputs: Optional pre-processed CLIP tensors (open_clip only)

        Returns:
            Tuple of (features, features_normalized) tensors
        """
        if self.uses_transformers_backend:
            imgs = pil_images if isinstance(pil_images, list) else [pil_images]
            inputs = self.preprocess(images=imgs, return_tensors="pt", padding=True)
            inputs = {k: v.to(self.device) for k, v in inputs.items()}
            with torch.no_grad():
                features = self.model.get_image_features(**inputs)
                if not isinstance(features, torch.Tensor):
                    features = features.pooler_output
                features_normalized = F.normalize(features, dim=-1)
            return features, features_normalized

        if clip_inputs is not None:
            inputs = clip_inputs
        elif isinstance(pil_images, list):
            inputs = torch.stack([self.preprocess(img) for img in pil_images]).to(self.device)
        else:
            inputs = self.preprocess(pil_images).unsqueeze(0).to(self.device)
        if self.device == 'cuda' and next(self.model.parameters()).dtype == torch.float16:
            inputs = inputs.half()
        with torch.no_grad():
            features = self.model.encode_image(inputs)
            features_normalized = F.normalize(features, dim=-1)
        return features, features_normalized

    def get_aesthetic_with_embedding(self, image_pil):
        """Calculate aesthetic score and return CLIP/SigLIP embedding for storage.

        The score is ``None`` when no MLP head is loaded (SigLIP mode): the
        aesthetic then comes from TOPIQ or Q-ReAlign, never a neutral 5.0.
        """
        _, features_normalized = self._encode_images(image_pil)

        if self.aesthetic_head is not None:
            aesthetic_score = float(score_aesthetic(self.aesthetic_head, features_normalized)[0])
        else:
            aesthetic_score = None

        embedding_bytes = features_normalized.cpu().numpy()[0].astype(np.float32).tobytes()
        return aesthetic_score, embedding_bytes

    def score_from_embedding(self, embedding_bytes):
        """Recalculate aesthetic score from stored CLIP embedding.

        Returns None if aesthetic head is not available (SigLIP embeddings
        are incompatible with the ViT-L-14 MLP head).
        """
        if self.aesthetic_head is None:
            return None

        # Convert bytes back to tensor
        embedding = np.frombuffer(embedding_bytes, dtype=np.float32)
        # Only works with 768-dim embeddings (ViT-L-14)
        if len(embedding) != 768:
            return None
        # Stored embeddings are already L2-normalized, which is what the head expects
        features = torch.tensor(embedding).unsqueeze(0).to(self.device)
        return float(score_aesthetic(self.aesthetic_head, features)[0])

    def get_aesthetic_and_quality(self, pil_img):
        """
        Single-image aesthetic/quality scoring via CLIP+MLP.

        Reached only by ``--dry-run``. With no aesthetic head outside commercial
        mode the aesthetic is ``None`` (the report prints ``n/a``), never a
        neutral 5.0 labelled ``clip-mlp``.

        Returns: (aesthetic, clip_embedding_bytes, quality_score, scoring_model)
        """
        clip_aesthetic, clip_embedding = self.get_aesthetic_with_embedding(pil_img)
        if self.aesthetic_head is None:
            if licensing.is_commercial():
                # No head to fall back on: the commercial scorer decides, exactly as
                # in the batch path.
                return self._commercial_aesthetic_result(pil_img, clip_embedding)
            return None, clip_embedding, None, 'topiq'
        return clip_aesthetic, clip_embedding, None, 'clip-mlp'

    def get_aesthetic_and_quality_batch(self, pil_images, clip_inputs=None):
        """
        Batch aesthetic/quality scoring via CLIP+MLP.

        Args:
            pil_images: List of PIL Images
            clip_inputs: Optional pre-processed CLIP tensors (from batch_processor, open_clip only)

        Returns: List of (aesthetic, clip_embedding_bytes, quality_score, scoring_model) tuples

        Raises:
            RuntimeError: No aesthetic head is loaded and the mode is not
                commercial. Single-pass cannot score aesthetics then, and a
                neutral 5.0 would be stored as if it were a score.
        """
        # Guard first: no GPU encode is spent on a batch that cannot succeed.
        if self.aesthetic_head is None and not licensing.is_commercial():
            raise RuntimeError(_NO_AESTHETIC_HEAD_ERROR)

        n = len(pil_images)

        _, features_normalized = self._encode_images(pil_images, clip_inputs)
        embeddings = features_normalized.cpu().numpy()

        if self.aesthetic_head is not None:
            clip_scores = score_aesthetic(self.aesthetic_head, features_normalized)
            results = []
            for i in range(n):
                clip_aesthetic = float(clip_scores[i])
                clip_embedding = embeddings[i].astype(np.float32).tobytes()
                results.append((clip_aesthetic, clip_embedding, None, 'clip-mlp'))
        else:
            results = [
                self._commercial_aesthetic_result(pil, embeddings[i].astype(np.float32).tobytes())
                for i, pil in enumerate(pil_images)
            ]

        return results

    def _commercial_aesthetic_result(self, pil_img, clip_embedding):
        """One ``(aesthetic, embedding, quality, scoring_model)`` tuple from native Q-ReAlign."""
        scored = self._commercial_aesthetic_scorer().score_tasks(pil_img, ('aesthetic', 'quality'))
        return scored['aesthetic'], clip_embedding, scored['quality'], 'qrealign'

    def _commercial_aesthetic_scorer(self):
        """The native Q-ReAlign scorer the single-pass path uses in commercial mode."""
        scorer = getattr(self, '_qrealign_native', None)
        if scorer is None:
            licensing.require('qrealign_native')
            from models.qrealign_native import QReAlignNativeScorer
            scorer = QReAlignNativeScorer(size=self.config.get_qrealign_size(), device=self.device)
            scorer.load()
            self._qrealign_native = scorer
        return scorer

    def get_composition_scores(self, pil_img, img_cv, base_comp_data):
        """
        Unified composition scoring - SAMP-Net and/or VLM.

        Args:
            pil_img: PIL Image for VLM analysis
            img_cv: OpenCV image for SAMP-Net
            base_comp_data: Dict with base composition data (modified in place)

        Returns: (pattern, vlm_explanation)
        """
        pattern = None
        vlm_explanation = None

        if self.samp_scorer:
            try:
                result = self.samp_scorer.score(img_cv)
                base_comp_data['score'] = result['comp_score']
                # Keep rule-based power_point_score (SAMP-Net's is just comp_score/2 approximation)
                pattern = result.get('pattern', 'unknown')
            except Exception as e:
                logger.error("SAMP-Net failed: %s", e)

        if self.vlm_composition:
            try:
                result = self.vlm_composition.analyze_composition(pil_img)
                if result.get('composition_score') is not None:
                    base_comp_data['score'] = result['composition_score']
                    vlm_explanation = result.get('explanation')
            except Exception as e:
                logger.error("VLM failed: %s", e)

        return pattern, vlm_explanation

    @staticmethod
    def _parse_shutter_speed(val):
        """Parse a positive finite duration, including fractional strings."""
        return _positive_float(val)

    @staticmethod
    def _determine_photo_category(m, cfg):
        """
        Determine which weight category applies to this photo.
        Honors a sticky per-photo category override first, then delegates to
        config-driven filter rules evaluated in priority order within the
        photo's scoring context.

        Args:
            m: Dict with photo metrics (tags, face_count, face_ratio, etc.),
               plus optional 'category_override' and 'scoring_context' keys.
            cfg: ScoringConfig instance

        Returns: category string (e.g., 'portrait', 'wildlife', 'default')
        """
        # Safe float extraction helper
        def safe_float(val, default=0.0, **bounds):
            if not isinstance(val, (int, float)):
                return default
            return _safe_float(val, default, **bounds)

        if cfg is None:
            # Fallback if no config (shouldn't happen in practice)
            from config import ScoringConfig
            cfg = ScoringConfig(validate=False)

        category_override = m.get('category_override')
        if category_override:
            known_categories = {c['name'] for c in cfg.get_categories()}
            if category_override in known_categories:
                return category_override

        # Build photo_data dict for config-driven category determination
        photo_data = with_face_defaults({
            'tags': m.get('tags', '') or '',
            'face_count': int(safe_float(m.get('face_count'), 0, min_value=0, max_value=None)),
            'face_ratio': safe_float(m.get('face_ratio'), 0, min_value=0, max_value=None),
            'is_silhouette': m.get('is_silhouette', 0),
            'is_group_portrait': m.get('is_group_portrait', 0),
            'is_monochrome': m.get('is_monochrome', 0),
            'mean_luminance': safe_float(m.get('mean_luminance'), 0.5, min_value=0, max_value=1),
            'iso': _positive_float(m.get('iso')),
            'shutter_speed': Facet._parse_shutter_speed(m.get('shutter_speed')),
            'focal_length': _positive_float(m.get('focal_length')),
            'f_stop': _positive_float(m.get('f_stop')),
        })
        scoring_context = m.get('scoring_context')

        # Delegate to config-driven category determination
        return cfg.determine_category(photo_data, context=scoring_context)

    def calculate_aggregate_logic(self, m, config=None):
        """
        THE BRAIN: Centralized math for the final score.
        Uses config weights if provided, otherwise uses instance config or defaults.
        """
        cfg = config or self.config if hasattr(self, 'config') else None

        # Get scoring limits from config
        scoring_limits = cfg.get_scoring_limits() if cfg else {}
        score_min = scoring_limits.get('score_min', 0.0)
        score_max = scoring_limits.get('score_max', 10.0)

        # Blink penalty multiplier (stored as percentage)
        blink_penalty = (cfg.get_threshold('blink_penalty_percent') or 50) / 100 if cfg else 0.5

        # Get exposure settings for clipping penalty
        exposure_settings = cfg.get_exposure_settings() if cfg else {}

        # Calculate clipping penalty if clipping data available
        clipping_penalty = 0
        if exposure_settings.get('silhouette_detection', True):
            is_silhouette = m.get('is_silhouette', 0)
        else:
            is_silhouette = False

        if not is_silhouette:
            shadow_clipped = m.get('shadow_clipped') or 0
            highlight_clipped = m.get('highlight_clipped') or 0
            if shadow_clipped or highlight_clipped:
                clipping_penalty = (shadow_clipped * 0.5) + (highlight_clipped * 1.0)

        # Calculate penalties from extracted helper
        penalties = _calculate_scoring_penalties(m, cfg)
        noise_penalty = penalties['noise_penalty']
        oversaturation_penalty = penalties['oversaturation_penalty']

        # Determine photo category and load weights
        category = self._determine_photo_category(m, cfg)
        w = fold_quality_weight(cfg.get_weights(category) if cfg else {})
        unavailable = unavailable_for_config(cfg)
        if unavailable:
            w = renormalise_weights(w, unavailable)

        # =================================================================
        # DATA-DRIVEN SCORING: weighted sum over the shared metric vector
        # (same feature space used by the weight optimizer for training)
        # =================================================================
        metric_values = build_metric_vector(m, cfg, category, penalties=penalties,
                                            unavailable=unavailable)

        # Get category flags from config (with sensible defaults)
        # Face categories get blink penalty by default
        face_categories = ('portrait', 'portrait_bw', 'group_portrait')
        apply_blink_penalty = w.get('_apply_blink_penalty', category in face_categories)

        # Silhouette skips clipping penalty by default
        skip_clipping_penalty = w.get('_skip_clipping_penalty', category == 'silhouette')

        # Noise tolerance multiplier (1.0 = full penalty, 0.0 = no penalty)
        noise_tolerance = w.get('noise_tolerance_multiplier', 1.0)

        # Clipping penalty multiplier (default category gets 1.5x by default)
        default_categories = ('default',)
        clipping_multiplier = w.get('_clipping_multiplier', 1.5 if category in default_categories else 1.0)

        # Skip oversaturation penalty for certain categories
        skip_oversaturation = w.get('_skip_oversaturation_penalty', category in ('night', 'astro', 'concert'))

        # Calculate weighted sum from config (all metrics share the 0-10 range)
        score = 0.0
        for metric_name, metric_value in metric_values.items():
            weight = w.get(metric_name, 0.0)
            if weight > 0:
                score += weighted_metric_contribution(metric_value, weight)

        # Apply blink penalty (multiplier on the whole score)
        if apply_blink_penalty and m.get('is_blink'):
            score *= blink_penalty

        # Add bonus
        score += w.get('bonus', 0.0)

        # Apply penalties
        if not skip_clipping_penalty:
            score -= clipping_penalty * clipping_multiplier

        score -= noise_penalty * noise_tolerance

        if not skip_oversaturation:
            score -= oversaturation_penalty

        return min(score_max, max(score_min, score)), category

    def score_photo_from_pil(self, pil_img, img_cv, original_path, cache=None):
        """
        AI engine that processes images already loaded into memory.
        Now collects and stores raw metrics for later recalculation.

        Args:
            pil_img: PIL Image
            img_cv: OpenCV BGR image array
            original_path: Path to original image for EXIF extraction
            cache: Optional ImageCache with pre-computed transformations
        """
        try:
            metadata_source = original_path
            img_h, img_w = img_cv.shape[:2]

            # Create ImageCache once for this image (avoids redundant conversions)
            if cache is None:
                cache = ImageCache(img_cv)

            # 1. Perceptual Hashing (for de-duplication)
            phash = str(imagehash.phash(pil_img))

            # 2. AI Aesthetics scoring via CLIP+MLP
            aesthetic, clip_embedding, quality_score, scoring_model = self.get_aesthetic_and_quality(pil_img)

            # 3. Technical Analysis with raw data (pass cache to avoid redundant conversions)
            sharpness_data = self.tech_analyzer.get_sharpness_data(img_cv, cache=cache)
            color_data = self.tech_analyzer.get_color_harmony_data(img_cv, cache=cache)
            exposure_settings = self.config.get_exposure_settings()
            histogram_data = self.tech_analyzer.get_histogram_data(
                img_cv,
                shadow_threshold=exposure_settings.get('shadow_clip_threshold_percent', 15) / 100,
                highlight_threshold=exposure_settings.get('highlight_clip_threshold_percent', 10) / 100,
                cache=cache
            )

            # 3b. B&W detection
            mono_settings = self.config.get_monochrome_settings()
            mono_data = self.tech_analyzer.detect_monochrome(
                img_cv, threshold=mono_settings.get('saturation_threshold_percent', 10) / 100,
                cache=cache
            )

            # 3c. Additional metrics (dynamic range, noise, contrast) - with cache
            dynamic_range_data = self.tech_analyzer.get_dynamic_range(img_cv, cache=cache)
            noise_data = self.tech_analyzer.get_noise_estimate(img_cv, cache=cache)
            contrast_data = self.tech_analyzer.get_contrast_score(img_cv, cache=cache)

            # 3d. Form facet + Matsuda color harmony (CPU, fixed 512px working size)
            from analyzers.form_facet import compute_form_metrics
            form_data = compute_form_metrics(pil_img)

            # 4. Facial Analysis (now handles multiple faces with confidence filtering)
            face_res = self.face_analyzer.analyze_faces(img_cv)

            # 5. Composition with power points and leading lines
            face_ratio = face_res.get('face_area', 0) / (img_h * img_w)
            comp_data = CompositionAnalyzer.get_placement_data(
                face_res.get('bbox'), img_w, img_h, self.config, img_cv
            )

            # Leading lines detection (for landscapes) - with cache
            leading_lines_data = CompositionAnalyzer.detect_leading_lines(img_cv, cache=cache)

            # 5b. Advanced composition analysis (SAMP-Net and/or VLM via shared method)
            composition_pattern, vlm_comp_explanation = self.get_composition_scores(pil_img, img_cv, comp_data)
            if vlm_comp_explanation:
                comp_data['vlm_explanation'] = vlm_comp_explanation

            isolation_bonus = 1.0
            is_blink = 0

            if face_res['face_count'] > 0:
                # isolation_bonus rewards 'Bokeh' (sharp subject vs blurry background)
                # Reuse laplacian_variance from cache instead of recalculating
                full_variance = cache.laplacian_variance
                isolation_bonus = max(1.0, face_res['face_sharpness'] / (full_variance + 1))
                is_blink = face_res.get('is_blink', 0)

            # 6. Get EXIF data first so we can use it in scoring
            exif_data = self.get_exif_data(metadata_source)

            resolved_path = str(Path(metadata_source).resolve())
            photo_override = get_photo_scoring_overrides(self.db_path, paths=[resolved_path]).get(resolved_path, {})

            # 7. Generate semantic tags from CLIP embedding
            tags = None
            if self.tagger is not None and clip_embedding is not None:
                threshold, max_tags = get_tag_params(self.config)
                tag_list = self.tagger.get_tags_from_embedding(
                    clip_embedding,
                    threshold=threshold,
                    max_tags=max_tags
                )
                if tag_list:
                    tags = tags_to_string(tag_list)

            # 8. Determine silhouette using shared function (face-aware, pixel-only)
            is_silhouette = detect_silhouette(cache.gray, face_res.get('face_details'))

            # 9. Use base comp_score - leading lines are added in calculate_aggregate_logic
            # to avoid double-counting (integrate_leading_lines was adding bonus here,
            # then calculate_aggregate_logic was adding it again via leading_lines_blend)
            final_comp = comp_data['score']

            # Pack ingredients for the score calculation via the shared builder so
            # this path feeds calculate_aggregate_logic the same feature space as
            # the batch and multi-pass paths (tags, is_monochrome, mean_luminance,
            # is_group_portrait, face_sharpness, power_point_score, noise_sigma,
            # mean_saturation — all previously dropped here).
            metrics = build_scoring_metrics(
                aesthetic=aesthetic,
                face_count=face_res['face_count'],
                face_quality=face_res['face_quality'],
                eye_sharpness=face_res['eye_sharpness'],
                face_sharpness=face_res['face_sharpness'],
                face_ratio=face_ratio,
                is_group_portrait=face_res.get('is_group_portrait', 0),
                is_blink=is_blink,
                isolation_bonus=isolation_bonus,
                sharpness_data=sharpness_data,
                color_data=color_data,
                histogram_data=histogram_data,
                mono_data=mono_data,
                noise_data=noise_data,
                contrast_data=contrast_data,
                comp_score=final_comp,
                power_point_score=comp_data.get('power_point_score', 5.0),
                leading_lines_score=leading_lines_data.get('leading_lines_score', 0),
                is_silhouette=is_silhouette,
                tags=tags,
                iso=exif_data.get('iso'),
                f_stop=exif_data.get('f_stop'),
                shutter_speed=exif_data.get('shutter_speed'),
                quality_score=quality_score,
                scoring_model=scoring_model,
                face_quality_iqa=face_res.get('face_quality_iqa'),
                form_data=form_data,
                scoring_context=photo_override.get('scoring_context'),
                category_override=photo_override.get('category_override'),
            )

            # Calculate final aggregate score and category using the centralized logic
            aggregate, category = self.calculate_aggregate_logic(metrics)

            # 9. Prepare the final row for the database with raw data
            res = {
                'path': resolved_path,
                'filename': Path(metadata_source).name,
                'category': category,
                'image_width': img_w,
                'image_height': img_h,
                'aesthetic': None if aesthetic is None else round(aesthetic, 2),
                'face_count': face_res['face_count'],
                'face_quality': face_res['face_quality'],
                'eye_sharpness': face_res['eye_sharpness'],
                'face_sharpness': face_res['face_sharpness'],
                'face_ratio': face_ratio,
                'tech_sharpness': round(sharpness_data['normalized'], 2),
                'color_score': round(color_data['normalized'], 2),
                'exposure_score': round(histogram_data['exposure_score'], 2),
                'comp_score': round(final_comp, 2),
                'isolation_bonus': round(isolation_bonus, 2),
                'is_blink': is_blink,
                'phash': phash,
                'aggregate': round(aggregate, 2),
                # Raw data columns
                'clip_embedding': clip_embedding,
                'raw_sharpness_variance': float(sharpness_data['raw_variance']),
                'histogram_data': histogram_data['histogram_bytes'],
                'histogram_spread': float(histogram_data['spread']),
                'mean_luminance': float(histogram_data['mean_luminance']),
                'histogram_bimodality': float(histogram_data['bimodality']),
                # None (no subject box) is stored as NULL, never as a made-up 5.0
                'power_point_score': (None if comp_data['power_point_score'] is None
                                      else float(comp_data['power_point_score'])),
                'raw_color_entropy': float(color_data['raw_entropy']),
                'raw_eye_sharpness': float(face_res.get('raw_eye_sharpness', 0)),
                'config_version': self.config.version_hash,
                # New columns for scoring improvements
                'shadow_clipped': histogram_data.get('shadow_clipped', 0),
                'highlight_clipped': histogram_data.get('highlight_clipped', 0),
                'channel_clip_shadow_pct': histogram_data.get('channel_clip_shadow_pct'),
                'channel_clip_highlight_pct': histogram_data.get('channel_clip_highlight_pct'),
                'is_silhouette': is_silhouette,
                'is_group_portrait': face_res.get('is_group_portrait', 0),
                'leading_lines_score': leading_lines_data.get('leading_lines_score', 0),
                # Face detection confidence
                'face_confidence': face_res.get('max_face_confidence', 0),
                # Black & white detection
                'is_monochrome': mono_data['is_monochrome'],
                'mean_saturation': mono_data['mean_saturation'],
                # Additional metrics
                'dynamic_range_stops': dynamic_range_data['dynamic_range_stops'],
                'noise_sigma': noise_data['noise_sigma'],
                'contrast_score': contrast_data['contrast_score'],
                # Form facet + Matsuda color harmony
                'form_symmetry': form_data.get('form_symmetry'),
                'form_balance': form_data.get('form_balance'),
                'form_edge_entropy': form_data.get('form_edge_entropy'),
                'form_fractal': form_data.get('form_fractal'),
                'color_harmony': form_data.get('color_harmony'),
                # Semantic tags
                'tags': tags,
                # Advanced model outputs
                'quality_score': quality_score,
                'topiq_score': None,  # Populated by --score-topiq or multi-pass TOPIQ
                'composition_explanation': comp_data.get('vlm_explanation'),
                'scoring_model': scoring_model,
                # SAMP-Net composition pattern
                'composition_pattern': composition_pattern,
                # OFIQ face quality (permissive analyzer only; None otherwise)
                'face_quality_iqa': face_res.get('face_quality_iqa'),
                # Face details for face recognition
                'face_details': face_res.get('face_details', []),
            }

            res.update(exif_data)

            return res
        except Exception as e:
            licensing.reraise_if_refused()
            logger.error("Error scoring %s: %s", original_path, e)
            return None

    @staticmethod
    def prepare_scoring_row(row_dict, cfg, normalizer, category=None):
        """Rewrite a stored photo row into the row the scorer actually scores.

        ``update_all_aggregates`` never persists these rewrites, so a stored row
        is not what ``calculate_aggregate_logic`` weights: sharpness, colour and
        eye sharpness are re-derived from their ``raw_*`` columns with the
        percentile ``normalizer`` (per category when it is configured to be),
        ``is_group_portrait`` follows the current ``min_faces_for_group`` and
        ``exposure_score`` is rebuilt from the stored histogram. The single place
        that transform lives: the recompute, the model evaluation and the weight
        optimizer's training features all call it, so none can drift from it.

        Mutates and returns ``row_dict``. ``category`` None means the photo's own
        category (``category_override`` / ``scoring_context`` honoured).
        """
        # Apply percentile normalization if available
        if normalizer:
            # The category the photo is normalized in: the caller's when it supplies
            # one (the weight optimizer serves a comparison's photos as that
            # category), else the photo's own
            if category is None:
                category = Facet._determine_photo_category(row_dict, cfg)
            per_category_enabled = bool(normalizer.per_category)
            raw_sharp = row_dict.get('raw_sharpness_variance')
            if raw_sharp is not None and isinstance(raw_sharp, (int, float)):
                if per_category_enabled:
                    normalized = normalizer.normalize_with_category('raw_sharpness_variance', raw_sharp, category)
                else:
                    normalized = normalizer.normalize('raw_sharpness_variance', raw_sharp)
                if normalized is not None:
                    row_dict['tech_sharpness'] = normalized

            raw_color = row_dict.get('raw_color_entropy')
            if raw_color is not None and isinstance(raw_color, (int, float)):
                if per_category_enabled:
                    normalized = normalizer.normalize_with_category('raw_color_entropy', raw_color, category)
                else:
                    normalized = normalizer.normalize('raw_color_entropy', raw_color)
                if normalized is not None:
                    row_dict['color_score'] = normalized

            raw_eye = row_dict.get('raw_eye_sharpness')
            if raw_eye is not None and isinstance(raw_eye, (int, float)):
                if per_category_enabled:
                    normalized = normalizer.normalize_with_category('raw_eye_sharpness', raw_eye, category)
                else:
                    normalized = normalizer.normalize('raw_eye_sharpness', raw_eye)
                if normalized is not None:
                    row_dict['eye_sharpness'] = normalized

        # Recompute is_group_portrait based on current config threshold
        face_count = row_dict.get('face_count') or 0
        min_faces_for_group = cfg.get_face_detection_settings().get('min_faces_for_group', 4)
        new_is_group = 1 if face_count >= min_faces_for_group else 0
        row_dict['is_group_portrait'] = new_is_group

        # Recompute exposure_score from stored histogram if available
        decoded_histogram = unpack_histogram(row_dict.get('histogram_data'))
        if decoded_histogram is not None:
            hist = decoded_histogram['luma']
            total = float(hist.sum())
            if total > 0:
                # Back to plain floats: the per-bin loops below are far
                # slower over NumPy scalars, and this runs per row.
                norm_hist = (hist / total).tolist()
                mean_luminance = sum(i * norm_hist[i] for i in range(256)) / 255.0
                variance = sum(((i / 255.0 - mean_luminance) ** 2) * norm_hist[i] for i in range(256))
                spread = (variance ** 0.5) * 255.0
                shadow_mass = sum(norm_hist[i] for i in range(30))    # 0-29 (matches get_histogram_data)
                highlight_mass = sum(norm_hist[i] for i in range(225, 256))  # 225-255 (matches get_histogram_data)
                bimodality = row_dict.get('histogram_bimodality') or 0
                is_sil = row_dict.get('is_silhouette', 0)
                luminance_penalty = abs(mean_luminance - 0.5) * 8
                spread_bonus = min(4.0, spread / 20.0)
                bimodality_penalty = max(0, bimodality - 1.0) * 0.6
                clip_pen = 0
                if not is_sil:
                    clip_pen = shadow_mass * 4.0 + highlight_mass * 5.0
                row_dict['exposure_score'] = max(0, min(10.0, 7.0 - luminance_penalty + spread_bonus - bimodality_penalty - clip_pen))

        return row_dict

    def update_all_aggregates(self, use_embeddings=True, normalizer=None, category_filter=None):
        """
        RE-CALCULATION FEATURE: Updates scores using existing DB data (no images needed).

        Args:
            use_embeddings: If True and CLIP embedding exists, recalculate aesthetic from embedding
                           (requires GPU models, ignored in lightweight mode)
            normalizer: Optional PercentileNormalizer for dataset-aware normalization
                       (supports per-category normalization if configured)
            category_filter: If set, only recompute photos currently in this category
        """
        if category_filter:
            logger.info("Recalculating scores for category '%s'...", category_filter)
        else:
            logger.info("Recalculating all scores based on current config...")
        logger.info("Config version: %s", self.config.version_hash)

        # In lightweight mode, we can't recalculate from embeddings (no aesthetic_head)
        if self.lightweight and use_embeddings:
            logger.debug("Note: Skipping embedding recalculation in lightweight mode (using stored aesthetic scores)")
            use_embeddings = False

        # Check if per-category normalization is enabled
        per_category_enabled = normalizer and normalizer.per_category
        if per_category_enabled:
            logger.info("Using per-category percentile normalization")
            normalizer.compute_percentiles_per_category()

        recalc_from_embedding = 0
        recalc_standard = 0
        categories_updated = 0

        with get_connection(self.db_path) as conn:
            # Columns needed for recalculation and category determination, built
            # conditionally: clip_embedding is the largest per-row BLOB, so it is
            # fetched only when aesthetic will actually be recomputed from it —
            # otherwise a 127k library streams ~0.5GB of embeddings into RAM only
            # to discard them (honours the BLOB-exclusion invariant). histogram_data
            # stays: it is decoded below to recompute exposure_score.
            recalc_cols = list(SERVED_ROW_COLUMNS)
            if use_embeddings:
                recalc_cols.append('clip_embedding')
            cols_sql = ', '.join(recalc_cols)

            if category_filter:
                row_count = conn.execute(
                    "SELECT COUNT(*) FROM photos WHERE category = ?", (category_filter,)
                ).fetchone()[0]
                cursor = conn.execute(f"SELECT {cols_sql} FROM photos WHERE category = ?", (category_filter,))
            else:
                row_count = conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
                cursor = conn.execute(f"SELECT {cols_sql} FROM photos")

            # Loaded once up front (not columns in recalc_cols — they live in
            # photo_scoring_overrides) so a rescore preserves any sticky
            # per-photo context/override instead of silently dropping it.
            overrides = get_photo_scoring_overrides(conn)

            # Stream the read cursor and buffer only the small UPDATE tuples: the
            # photos.category index makes updating rows still being scanned a
            # Halloween-problem hazard, so every write lands after the cursor is
            # fully drained. Streaming also keeps the histogram BLOBs transient
            # instead of materialising the whole table in RAM.
            def _stream_rows():
                while True:
                    fetched = cursor.fetchmany(1000)
                    if not fetched:
                        return
                    yield from fetched

            updates = []
            emit_progress('recompute', 0, row_count, force=True)
            recompute_t0 = time.time()
            for i, row in enumerate(tqdm(_stream_rows(), total=row_count, desc="Updating DB")):
                row_dict = dict(row)
                photo_override = overrides.get(row_dict['path'], {})
                row_dict['scoring_context'] = photo_override.get('scoring_context')
                row_dict['category_override'] = photo_override.get('category_override')

                # Try to recalculate aesthetic from stored embedding
                if use_embeddings and row_dict.get('clip_embedding'):
                    try:
                        new_aesthetic = self.score_from_embedding(row_dict['clip_embedding'])
                        if new_aesthetic is not None:
                            row_dict['aesthetic'] = new_aesthetic
                            recalc_from_embedding += 1
                    except Exception as e:
                        logger.warning("Embedding recalculation failed for %s: %s", row_dict.get('path', 'unknown'), e)

                # The row exactly as the scorer serves it: category, percentile-normalized
                # sharpness/colour/eye, group-portrait flag and histogram exposure
                Facet.prepare_scoring_row(row_dict, self.config, normalizer)
                new_is_group = row_dict['is_group_portrait']

                # Recalculate aggregate and category with current config
                new_score, category = self.calculate_aggregate_logic(row_dict)
                recalc_standard += 1
                categories_updated += 1

                # Unknown stays unknown: a NULL exposure_score with no histogram to
                # derive one from is written back as NULL, never a fabricated 5.0.
                stored_exposure = row_dict.get('exposure_score')
                new_exposure = round(stored_exposure, 4) if stored_exposure is not None else None
                updates.append(
                    (round(new_score, 2), self.config.version_hash, category,
                     new_is_group, new_exposure, row_dict['path'])
                )

                processed = i + 1
                elapsed = time.time() - recompute_t0
                emit_progress('recompute', processed, row_count,
                              eta_seconds=(row_count - processed) * elapsed / processed)

            # Apply every buffered update now that the read cursor is drained, so
            # an in-flight category UPDATE never perturbs the scan (Halloween
            # problem) and the whole rescore commits in one transaction.
            try:
                conn.executemany(
                    "UPDATE photos SET aggregate = ?, config_version = ?, category = ?, is_group_portrait = ?, exposure_score = ? WHERE path = ?",
                    updates,
                )
            except sqlite3.DatabaseError as e:
                # Updating `category` fires the photos_fts_au trigger; a corrupt
                # FTS5 index surfaces here as "database disk image is malformed"
                # even though PRAGMA integrity_check passes (it doesn't validate
                # FTS shadow tables). Point at the fix instead of crashing with a
                # misleading disk-image error.
                if 'malformed' in str(e).lower():
                    raise RuntimeError(
                        "Aggregate update failed with 'database disk image is malformed'. "
                        "This is almost always a corrupt FTS5 search index (the photos_fts "
                        "trigger fires on category changes), not actual data corruption. "
                        "Run 'python database.py --rebuild-fts' and retry --recompute-average."
                    ) from e
                raise

            conn.commit()

        emit_progress('recompute', row_count, row_count, force=True)
        logger.info("Updated %s photos", recalc_standard)
        logger.info("Stored categories for %s photos", categories_updated)
        if use_embeddings:
            logger.info("Recalculated %s aesthetics from stored embeddings", recalc_from_embedding)

    def recompute_composition_scores(self):
        """
        Re-run composition analysis using stored thumbnails.

        This allows updating comp_score after changes to detect_subject_region()
        without re-processing original images (much faster).
        """
        # Load image modules (cv2, CompositionAnalyzer) - needed even in lightweight mode
        _load_image_modules()

        logger.info("Recomputing composition scores from stored thumbnails...")

        with get_connection(self.db_path) as conn:
            cursor = conn.execute("SELECT path, thumbnail, face_count FROM photos WHERE thumbnail IS NOT NULL")
            rows = list(cursor.fetchall())

            logger.info("Found %s photos with thumbnails", len(rows))

            updated = 0
            decode_failed = 0
            for row in tqdm(rows, desc="Recomputing composition"):
                path = row['path']
                thumbnail_blob = row['thumbnail']
                row['face_count'] or 0

                if not thumbnail_blob:
                    continue

                # Decode thumbnail from BLOB
                try:
                    img_array = np.frombuffer(thumbnail_blob, dtype=np.uint8)
                    img_cv = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                    if img_cv is None:
                        decode_failed += 1
                        continue
                except Exception:
                    decode_failed += 1
                    continue

                img_h, img_w = img_cv.shape[:2]

                # Re-run composition analysis (without face bbox - let it detect subject)
                # For portraits, we'd need face detection, but for landscapes this is fine
                comp_data = CompositionAnalyzer.get_placement_data(
                    None, img_w, img_h, self.config, img_cv
                )

                # Get leading lines score
                leading_lines_data = CompositionAnalyzer.detect_leading_lines(img_cv)

                # Use base comp_score - leading lines are added in calculate_aggregate_logic
                # to avoid double-counting
                new_comp_score = comp_data['score']
                # None = no subject box: stored as NULL (this is the one writer that
                # also replaces the legacy 5.0 placeholders)
                new_power_point = comp_data.get('power_point_score', 5.0)

                conn.execute(
                    """UPDATE photos
                       SET comp_score = ?, power_point_score = ?, leading_lines_score = ?
                       WHERE path = ?""",
                    (round(new_comp_score, 2),
                     None if new_power_point is None else round(new_power_point, 2),
                     round(leading_lines_data.get('leading_lines_score', 0), 2), path)
                )
                updated += 1

            conn.commit()

        logger.info("Updated composition scores for %s photos", updated)
        if decode_failed > 0:
            logger.error("Failed to decode %s thumbnails", decode_failed)
        logger.info("Run --recompute-average to update aggregate scores with new comp_score values")

    @staticmethod
    def _foreach_face_landmark(db_path, select_cols, desc, compute, where_extra=""):
        """Shared scaffold for the landmark-only face recompute passes.

        Selects ``select_cols`` from every face with a stored 106-pt landmark
        blob (optionally narrowed by ``where_extra``, an extra SQL fragment
        appended to the WHERE clause), decodes each to a (106, 2) float32 array
        (undecodable blobs are skipped and counted), and calls
        ``compute(row, landmarks)`` per face. Returns
        ``(results, total_faces, no_landmark_count, decode_errors)``.
        """
        import numpy as np
        from tqdm import tqdm

        with get_connection(db_path) as conn:
            rows = conn.execute(
                f"SELECT {select_cols} FROM faces "
                f"WHERE landmark_2d_106 IS NOT NULL{where_extra}"
            ).fetchall()
            no_landmark_count = conn.execute(
                "SELECT COUNT(*) FROM faces WHERE landmark_2d_106 IS NULL"
            ).fetchone()[0]

        results = []
        decode_errors = 0
        for row in tqdm(rows, desc=desc):
            try:
                landmarks = np.frombuffer(
                    row['landmark_2d_106'], dtype=np.float32).reshape(106, 2)
            except (ValueError, TypeError):
                decode_errors += 1
                continue
            results.append(compute(row, landmarks))
        return results, len(rows), no_landmark_count, decode_errors

    def recompute_blink_detection(self):
        """
        Re-compute blink detection using stored landmarks from the faces table.

        Optimized version:
        - Uses stored landmark_2d_106 to calculate EAR directly (no AI inference)
        - Falls back to thumbnail-based detection for faces without stored landmarks
        - ~100x faster than thumbnail-based detection when landmarks are available
        """
        from analyzers import FaceAnalyzer as _FaceAnalyzer

        face_detection = self.config.config.get('face_detection', {})
        blink_threshold = face_detection.get('blink_ear_threshold', 0.21)

        def _compute(row, landmarks):
            avg_ear = _FaceAnalyzer.compute_avg_ear(landmarks)
            return row['photo_path'], 1 if avg_ear < blink_threshold else 0

        per_face, total, no_landmark_count, _ = Facet._foreach_face_landmark(
            self.db_path, "photo_path, landmark_2d_106", "EAR from landmarks", _compute)

        if total:
            logger.info("Computing blinks from stored landmarks for %s faces...", total)

        photo_blink_status = {}  # {path: is_blink}
        for path, is_blink in per_face:
            # If ANY face is blinking, the photo is marked as blink
            if path not in photo_blink_status:
                photo_blink_status[path] = is_blink
            elif is_blink:
                photo_blink_status[path] = 1

        if no_landmark_count > 0:
            logger.debug("Note: %s faces lack stored landmarks.", no_landmark_count)
            logger.info("  Run '--batch' scan on new photos to store landmarks,")
            logger.info("  or run '--extract-faces-gpu' to backfill landmarks.")

        logger.info("Saving results to database...")
        with get_connection(self.db_path) as conn:
            # Master's reset, kept for every default-mode / ArcFace row: all photos
            # with a face go back to non-blink, then the re-derived values are
            # written. The one exemption is a photo whose faces are ALL SFace rows
            # (commercial mode): they carry no 106-point landmarks to re-derive
            # from, so zeroing would overwrite the scan's measured (possibly NULL =
            # unknown) blink with a false "not a blink".
            conn.execute(
                "UPDATE photos SET is_blink = 0 WHERE face_count >= 1 AND NOT ("
                "EXISTS (SELECT 1 FROM faces f WHERE f.photo_path = photos.path) "
                "AND NOT EXISTS (SELECT 1 FROM faces f WHERE f.photo_path = photos.path "
                "AND COALESCE(f.embedding_model, '') <> ?))", (SFACE_MODEL,))
            update_data = [(status, path) for path, status in photo_blink_status.items()]
            conn.executemany("UPDATE photos SET is_blink = ? WHERE path = ?", update_data)
            conn.commit()

        blink_count = sum(1 for v in photo_blink_status.values() if v == 1)
        logger.info("Finished. Updated %s photos (%s with blinks).", len(photo_blink_status), blink_count)

    def recompute_eyes_expression(self):
        """Re-compute eyes-open and expression scores from stored 106-pt landmarks.

        Mirrors :meth:`recompute_blink_detection` — reads the stored
        ``landmark_2d_106`` blob for each face, computes a continuous eyes-open
        score (aggregated as the worst/min across a photo's faces) and a
        mouth-state expression score (mean across faces), and writes them to
        ``photos.eyes_open_score`` / ``photos.expression_score``. No InsightFace
        re-run — pure geometry on stored landmarks.
        """
        from collections import defaultdict
        from analyzers import FaceAnalyzer as _FaceAnalyzer

        def _compute(row, landmarks):
            return (row['photo_path'],
                    _FaceAnalyzer.compute_eyes_open_score(landmarks),
                    _FaceAnalyzer.compute_expression_score(landmarks))

        per_face, total, no_landmark_count, _ = Facet._foreach_face_landmark(
            self.db_path, "photo_path, landmark_2d_106",
            "Eyes/expression from landmarks", _compute)

        if not total:
            logger.info("No faces with stored landmarks — nothing to compute.")
            if no_landmark_count:
                logger.info("  %s faces lack landmarks; re-scan to store them.", no_landmark_count)
            return 0

        logger.info("Computing eyes/expression from stored landmarks for %s faces...", total)

        per_photo_eyes = defaultdict(list)
        per_photo_expr = defaultdict(list)
        for path, eyes, expr in per_face:
            per_photo_eyes[path].append(eyes)
            per_photo_expr[path].append(expr)

        update_data = []
        for path in per_photo_eyes:
            eyes = _FaceAnalyzer.aggregate_eyes_open(per_photo_eyes[path])
            expr = _FaceAnalyzer.aggregate_expression(per_photo_expr[path])
            update_data.append((eyes, expr, path))

        logger.info("Saving results to database...")
        with get_connection(self.db_path) as conn:
            conn.executemany(
                "UPDATE photos SET eyes_open_score = ?, expression_score = ? WHERE path = ?",
                update_data,
            )
            conn.commit()

        if no_landmark_count:
            logger.info("Note: %s faces lack stored landmarks (skipped).", no_landmark_count)
        logger.info("Finished. Updated %s photos with eyes/expression scores.", len(update_data))
        return len(update_data)

    def recompute_face_signals(self, force=False):
        """Backfill per-face eyes-open and smile scores from stored 106-pt landmarks.

        Mirrors :meth:`recompute_eyes_expression` but writes the per-face
        ``faces.eyes_open_score`` / ``faces.smile_score`` columns (the canonical
        source for the culling face panel) instead of the photo-level
        aggregates. No InsightFace re-run — pure geometry on stored landmarks,
        so no pixels are needed.

        By default this is a *backfill*: only faces still missing a signal
        (``eyes_open_score IS NULL OR smile_score IS NULL``) are recomputed, so a
        richer MediaPipe blendshape value already stored for a face is never
        overwritten by the cruder landmark-geometry estimate — and a turned head,
        where the geometry gate returns NULL, is not blanked. Pass ``force=True``
        to rewrite every face with a landmark from geometry.
        """
        from analyzers import FaceAnalyzer as _FaceAnalyzer

        def _compute(row, landmarks):
            return (_FaceAnalyzer.compute_eyes_open_score(landmarks),
                    _FaceAnalyzer.compute_smile_score(landmarks),
                    row['id'])

        where_extra = "" if force else " AND (eyes_open_score IS NULL OR smile_score IS NULL)"
        update_data, total, no_landmark_count, decode_errors = Facet._foreach_face_landmark(
            self.db_path, "id, landmark_2d_106",
            "Per-face signals from landmarks", _compute, where_extra=where_extra)

        if not total:
            logger.info("No faces with stored landmarks — nothing to compute.")
            if no_landmark_count:
                logger.info("  %s faces lack landmarks; re-scan to store them.", no_landmark_count)
            return 0

        logger.info("Computing per-face eyes/smile signals for %s faces...", total)
        logger.info("Saving results to database...")
        with get_connection(self.db_path) as conn:
            conn.executemany(
                "UPDATE faces SET eyes_open_score = ?, smile_score = ? WHERE id = ?",
                update_data,
            )
            conn.commit()

        if no_landmark_count:
            logger.info("Note: %s faces lack stored landmarks (skipped).", no_landmark_count)
        if decode_errors:
            logger.warning("%s faces had undecodable landmarks (skipped).", decode_errors)
        logger.info("Finished. Updated %s faces with eyes/smile signals.", len(update_data))
        return len(update_data)

    def rescan_samp_composition(self, batch_size: int = 16):
        """
        Rescan composition scores using SAMP-Net from stored thumbnails.

        This requires:
        - GPU for SAMP-Net inference
        - Thumbnails of at least 384x384 (SAMP-Net input size)
        - SAMP-Net weights (downloaded automatically)

        Updates comp_score, composition_pattern, and power_point_score columns.
        """
        # Load image modules (cv2, Image) - needed even in lightweight mode
        _load_image_modules()
        from models.samp_net import SAMPNetScorer

        logger.info("Rescanning composition with SAMP-Net from stored thumbnails...")

        # Initialize SAMP-Net scorer (requires GPU)
        scorer = SAMPNetScorer()

        with get_connection(self.db_path) as conn:
            cursor = conn.execute("SELECT path, thumbnail FROM photos WHERE thumbnail IS NOT NULL")
            rows = list(cursor.fetchall())

            logger.info("Found %s photos with thumbnails", len(rows))

            # Check thumbnail sizes for a sample to warn user
            if rows:
                sample_blob = rows[0]['thumbnail']
                img_array = np.frombuffer(sample_blob, dtype=np.uint8)
                img_cv = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                if img_cv is not None:
                    h, w = img_cv.shape[:2]
                    if min(h, w) < 384:
                        logger.warning("WARNING: Thumbnails are %sx%s, but SAMP-Net requires 384x384 minimum.", w, h)
                        logger.info("         Run a full rescan with --force to generate larger thumbnails.")
                        logger.info("         Proceeding with upscaling (results may be less accurate)...")

            updated = 0
            decode_failed = 0
            batched_paths = []
            batched_images = []

            for row in tqdm(rows, desc="Processing SAMP-Net"):
                path = row['path']
                thumbnail_blob = row['thumbnail']

                if not thumbnail_blob:
                    continue

                # Decode thumbnail from BLOB
                try:
                    img_array = np.frombuffer(thumbnail_blob, dtype=np.uint8)
                    img_cv = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                    if img_cv is None:
                        decode_failed += 1
                        continue
                except Exception:
                    decode_failed += 1
                    continue

                # Convert BGR to RGB for PIL
                img_rgb = cv2.cvtColor(img_cv, cv2.COLOR_BGR2RGB)
                pil_img = Image.fromarray(img_rgb)

                batched_paths.append(path)
                batched_images.append(pil_img)

                # Process batch when full
                if len(batched_images) >= batch_size:
                    results = scorer.score_batch(batched_images)
                    for i, result in enumerate(results):
                        # Only update comp_score and composition_pattern
                        # Keep rule-based power_point_score (SAMP-Net's is just comp_score/2 approximation)
                        conn.execute(
                            """UPDATE photos
                               SET comp_score = ?, composition_pattern = ?
                               WHERE path = ?""",
                            (result['comp_score'], result['pattern'], batched_paths[i])
                        )
                        updated += 1
                    conn.commit()
                    batched_paths = []
                    batched_images = []

            # Process remaining images
            if batched_images:
                results = scorer.score_batch(batched_images)
                for i, result in enumerate(results):
                    conn.execute(
                        """UPDATE photos
                           SET comp_score = ?, composition_pattern = ?
                           WHERE path = ?""",
                        (result['comp_score'], result['pattern'], batched_paths[i])
                    )
                    updated += 1
                conn.commit()

        logger.info("Updated SAMP-Net composition scores for %s photos", updated)
        if decode_failed > 0:
            logger.error("Failed to decode %s thumbnails", decode_failed)
        logger.info("Run --recompute-average to update aggregate scores with new comp_score values")

    # Model name -> DB column for supplementary IQA metrics
    # Always-on supplementary IQA models (pyiqa-backed, ~2GB each).
    _BASE_IQA_MODELS = [
        ('topiq_iaa', 'aesthetic_iaa'),
        ('topiq_nr_face', 'face_quality_iqa'),
        ('liqe', 'liqe_score'),
    ]

    @property
    def _IQA_MODELS(self):
        """Base IQA models plus any config-enabled extended pyiqa models.

        Q-ReAlign is a native ``transformers`` scorer (no pyiqa); when
        ``iqa_extended.qrealign`` resolves to enabled it slots into the same
        VRAM-aware multi-pass scoring as the base models (writing the
        qrealign_score column). Its default is ``"auto"``,
        which is on for every profile but legacy — at ~3GB it fits from the 8gb
        profile up. Non-pyiqa extended scorers (Aesthetic V2.5, DeQA) have their
        own loaders and are not part of this list.
        """
        # Commercial mode keeps only the models the registry allows (none of the
        # pyiqa-backed base models); a refused model must not even be listed.
        models = [(m, c) for m, c in self._BASE_IQA_MODELS if licensing.loader_allowed(m)]
        try:
            if self.config.get_extended_iqa_settings().get('qrealign'):
                models.append(('qrealign', 'qrealign_score'))
        except Exception:
            pass
        return models

    def recompute_iqa_from_thumbnails(self, batch_size: int = 64):
        """Recompute supplementary IQA metrics from stored thumbnails.

        Auto-detects the accelerator and groups models into passes:
        - >=8GB dedicated VRAM: all 3 models at once (~6GB), single DB pass
        - <8GB dedicated VRAM: one model at a time (~2GB each), 3 DB passes
        - Apple Metal: one model at a time — deliberately conservative, because
          its memory IS system RAM shared with macOS and every other running
          application, so co-loading models there is not the same bet as
          co-loading them in a dedicated VRAM budget
        - CPU-only: one model at a time

        Incremental: skips columns already populated per photo.
        Skips face_quality_iqa for photos without faces, and for a photo TOPIQ
        NR-Face already declined on its current scan (``iqa_declined``).
        Skips liqe_score for a photo whose stored thumbnail is too small for
        LIQE (decided from its header, before any decode; nothing is recorded).
        An out-of-memory error or any other failure is not remembered: that
        photo is selected again next run.
        """
        import time
        from models.model_manager import ModelManager

        columns = [col for _, col in self._IQA_MODELS]
        if not columns:
            raise LicenceError(
                "No IQA model is available to recompute under the active licensing policy: "
                "the pyiqa models are refused in commercial mode and iqa_extended.qrealign is off.")

        start_time = time.time()

        # Count work per column. A column that stays NULL by design for a photo
        # (face_quality_iqa without a face) is not work, or a library whose only
        # NULLs are faceless photos would never reach "nothing to do".
        with get_connection(self.db_path) as conn:
            for model_name, column in self._IQA_MODELS:
                count = conn.execute(
                    f"SELECT COUNT(*) FROM photos WHERE {self._iqa_needs_score_sql(column)} "
                    "AND thumbnail IS NOT NULL"
                ).fetchone()[0]
                logger.info("  %s -> %s: %s NULL", model_name, column, count)

            where_any_null = " OR ".join(self._iqa_needs_score_sql(c) for c in columns)
            total = conn.execute(
                f"SELECT COUNT(*) FROM photos WHERE ({where_any_null}) AND thumbnail IS NOT NULL"
            ).fetchone()[0]

        if total == 0:
            logger.info("All IQA columns already populated, nothing to do.")
            return

        # Auto-detect VRAM and group models into passes
        vram_gb = ModelManager.detect_vram()
        model_names = [m for m, _ in self._IQA_MODELS]
        total_model_vram = sum(self._iqa_model_vram_gb(m) for m in model_names)

        if vram_gb >= total_model_vram + IQA_PASS_VRAM_MARGIN_GB:
            passes = [model_names]  # all at once
        else:
            passes = [[m] for m in model_names]  # one at a time

        device = describe_scoring_device(
            ModelManager.detect_accelerator(), vram_gb, ModelManager.detect_system_ram_gb()
        )
        logger.info("%d photos to score | %s | %d pass(es): %s",
                    total, device, len(passes), ", ".join("+".join(p) for p in passes))

        # Mutable counters shared across passes
        counters: dict[str, Any] = {'updated': {col: 0 for col in columns}, 'errors': 0,
                    'declined': 0, 'liqe_too_small': 0}

        for pass_models in passes:
            self._run_iqa_pass(pass_models, batch_size, counters)

        elapsed = time.time() - start_time
        minutes = elapsed / 60
        logger.info("\nIQA recompute complete in %.1f minutes:", minutes)
        for model_name, column in self._IQA_MODELS:
            logger.info("  %s: %s photos scored", column, counters['updated'][column])
        if counters['liqe_too_small']:
            logger.info("  liqe_score: %d photo(s) skipped, short side under %d px (stay NULL)",
                        counters['liqe_too_small'], LIQE_MIN_SHORT_SIDE)
        if counters['declined']:
            logger.info("  face_quality_iqa: %d photo(s) the model declined (no face found in "
                        "the thumbnail); not retried until the photo is rescanned",
                        counters['declined'])
        if counters['errors']:
            logger.error("  %s thumbnail decode errors", counters['errors'])
        logger.info("Run --recompute-average to update aggregate scores with new IQA metrics.")

    @staticmethod
    def _iqa_needs_score_sql(column):
        """SQL predicate: this photo still needs ``column`` computed by --recompute-iqa.

        ``face_quality_iqa`` is scored only for photos with a face (a faceless one
        is left NULL by design), so the same ``face_count`` condition applies to the
        up-front work count and to the rows each pass selects. A column in
        ``_IQA_DECLINING_MODELS`` is also not work for a photo its model declined
        on the photo's CURRENT scan (``iqa_declined`` row whose fingerprint still
        matches). Columns are qualified with ``photos.`` so the predicate works in
        the unaliased count queries and in the pass selector alike.
        """
        if column == 'face_quality_iqa':
            needs = f"photos.{column} IS NULL AND COALESCE(photos.face_count, 0) > 0"
        else:
            needs = f"photos.{column} IS NULL"
        model = _IQA_DECLINING_MODELS.get(column)
        if model is None:
            return f"({needs})"
        return (
            f"({needs} AND NOT EXISTS (SELECT 1 FROM iqa_declined d "
            f"WHERE d.photo_path = photos.path AND d.model = '{model}' "
            f"AND d.scan_fingerprint = {IQA_SCAN_FINGERPRINT_SQL}))"
        )

    def _iqa_model_vram_gb(self, model_name):
        """VRAM budget of one recompute-iqa model: pyiqa table, or the native Q-ReAlign size."""
        from models.model_manager import ModelManager
        if model_name == 'qrealign':
            return (ModelManager.QREALIGN_LITE_VRAM_GB if self.config.get_qrealign_size() == 'lite'
                    else ModelManager.MODEL_VRAM_REQUIREMENTS['qrealign'])
        from models.pyiqa_scorer import PYIQA_MODELS
        return PYIQA_MODELS[model_name]['vram_gb']

    def _make_iqa_scorer(self, model_name):
        """Loaded scorer for one recompute-iqa model; Q-ReAlign is native, the rest pyiqa."""
        if model_name == 'qrealign':
            licensing.require('qrealign_native')
            from models.qrealign_native import QReAlignNativeScorer
            scorer = QReAlignNativeScorer(size=self.config.get_qrealign_size(), device=self.device)
        else:
            from models.pyiqa_scorer import PyIQAScorer
            scorer = PyIQAScorer(model_name=model_name)
        scorer.load()
        return scorer

    def _run_iqa_pass(self, model_names, batch_size, counters):
        """Run one IQA pass with the given models loaded simultaneously."""
        from io import BytesIO
        from PIL import Image

        col_map = dict(self._IQA_MODELS)  # model_name -> column
        pass_columns = [col_map[m] for m in model_names]

        # Load models for this pass
        scorers = {}
        for model_name in model_names:
            column = col_map[model_name]
            scorers[column] = self._make_iqa_scorer(model_name)

        where_null = " OR ".join(self._iqa_needs_score_sql(c) for c in pass_columns)
        # One flag per column: whether THIS photo still needs it. The predicate is the
        # selector's own (face_count, a prior decline), so the loop below never
        # re-derives it in Python.
        need_flags = ", ".join(
            f"({self._iqa_needs_score_sql(c)}) AS need_{c}" for c in pass_columns)

        with get_connection(self.db_path) as conn:
            cursor = conn.execute(
                f"""SELECT path, thumbnail, {need_flags}
                    FROM photos
                    WHERE ({where_null}) AND thumbnail IS NOT NULL"""
            )
            rows = list(cursor.fetchall())

            if not rows:
                for scorer in scorers.values():
                    scorer.unload()
                return

            label = "+".join(model_names) if len(model_names) > 1 else model_names[0]
            batched_paths = []
            batched_images = []
            batched_null_cols = []

            def _flush(conn, batched_paths, batched_images, batched_null_cols):
                for column, scorer in scorers.items():
                    indices = [i for i, nulls in enumerate(batched_null_cols) if column in nulls]
                    if not indices:
                        continue
                    batch_imgs = [batched_images[i] for i in indices]
                    batch_pths = [batched_paths[i] for i in indices]
                    scores = scorer.score_batch(batch_imgs)
                    written = 0
                    for i, score in enumerate(scores):
                        if score is None:
                            # The model could not score this photo: leave the column
                            # NULL (not counted) so the next run selects it again,
                            # unless it declined on purpose (below).
                            continue
                        conn.execute(
                            f"UPDATE photos SET {column} = ? WHERE path = ?",
                            (round(score, 2), batch_pths[i])
                        )
                        written += 1
                    counters['updated'][column] += written
                    decline_model = _IQA_DECLINING_MODELS.get(column)
                    if decline_model is not None:
                        # Only a column of THIS pass, and only the positions the model
                        # itself declined: an OOM or any other failure stays unrecorded
                        # so the next run retries it. SELECT ... WHERE (not VALUES) so
                        # the fingerprint is computed from the stored row, and so the
                        # parser does not read ON CONFLICT as part of a join.
                        for i in scorer.last_declined:
                            conn.execute(
                                "INSERT INTO iqa_declined (photo_path, model, scan_fingerprint) "
                                f"SELECT photos.path, ?, {IQA_SCAN_FINGERPRINT_SQL} "
                                "FROM photos WHERE photos.path = ? "
                                "ON CONFLICT(photo_path, model) DO UPDATE SET "
                                "scan_fingerprint = excluded.scan_fingerprint",
                                (decline_model, batch_pths[i])
                            )
                            counters['declined'] += 1
                conn.commit()

            for row in tqdm(rows, desc=f"Scoring {label}"):
                # Which columns still need scoring for this photo? Decided by the
                # selector's own predicate, before the thumbnail is decoded, so a
                # photo with nothing to score costs no decode.
                null_cols = [col for col in pass_columns if row[f'need_{col}']]
                if not null_cols:
                    continue

                # Decode lazily: Image.open reads the header only, which is enough to
                # tell that LIQE would refuse this thumbnail. Everything lazy stays
                # inside the try so a corrupt thumbnail still counts as an error.
                try:
                    img = Image.open(BytesIO(row['thumbnail']))
                    skip_liqe = 'liqe_score' in null_cols and liqe_input_too_small(*img.size)
                    scorable = [c for c in null_cols if not (skip_liqe and c == 'liqe_score')]
                    pil_img = img.convert('RGB') if scorable else None
                except Exception:
                    counters['errors'] += 1
                    continue
                if skip_liqe:
                    counters['liqe_too_small'] += 1
                if not scorable:
                    continue
                null_cols = scorable

                batched_paths.append(row['path'])
                batched_images.append(pil_img)
                batched_null_cols.append(null_cols)

                if len(batched_images) >= batch_size:
                    _flush(conn, batched_paths, batched_images, batched_null_cols)
                    batched_paths = []
                    batched_images = []
                    batched_null_cols = []

            if batched_images:
                _flush(conn, batched_paths, batched_images, batched_null_cols)

        for scorer in scorers.values():
            scorer.unload()

    def get_exif_data(self, image_path):
        """Extracts camera metadata using ExifTool (fallback to Pillow).

        Uses persistent ExifTool process when available for better performance.
        """
        exif_data = {
            'date_taken': None, 'camera_model': None, 'lens_model': None,
            'iso': None, 'f_stop': None, 'shutter_speed': None, 'focal_length': None,
            'focal_length_35mm': None, 'gps_latitude': None, 'gps_longitude': None
        }

        # 1. Try persistent ExifTool (fastest - no subprocess spawn)
        try:
            from exiftool import get_exif_single
            result = get_exif_single(image_path)
            if result.get('camera_model'):
                return result
        except ImportError:
            pass
        except Exception:
            pass

        # 2. Fallback to subprocess ExifTool (Best for CR3/RAW)
        import subprocess
        try:
            result = subprocess.run(
                ['exiftool', '-j', '-n', str(image_path)],
                capture_output=True, text=True, check=True, timeout=30
            )
            data = json.loads(result.stdout)[0]
            exif_data['date_taken'] = data.get('DateTimeOriginal') or data.get('CreateDate')
            exif_data['camera_model'] = data.get('Model')
            exif_data['lens_model'] = data.get('LensModel') or data.get('LensID')
            exif_data['iso'] = data.get('ISO')
            exif_data['f_stop'] = data.get('Aperture')
            exposure = data.get('ExposureTime')
            exif_data['shutter_speed'] = str(exposure) if exposure else None
            exif_data['focal_length'] = data.get('FocalLength')
            exif_data['focal_length_35mm'] = data.get('FocalLengthIn35mmFilm')
            exif_data['gps_latitude'] = data.get('GPSLatitude')
            exif_data['gps_longitude'] = data.get('GPSLongitude')

            if exif_data['camera_model']:
                return _sanitize_exif_numeric(exif_data)
        except Exception:
            pass

        # 3. Fallback to exifread (works with DNG, ARW, and most RAW formats)
        try:
            import exifread
            with open(image_path, 'rb') as f:
                tags = exifread.process_file(f, details=False)
            if tags:
                if 'EXIF DateTimeOriginal' in tags:
                    exif_data['date_taken'] = str(tags['EXIF DateTimeOriginal'])
                elif 'Image DateTimeOriginal' in tags:
                    exif_data['date_taken'] = str(tags['Image DateTimeOriginal'])
                if 'Image Model' in tags:
                    exif_data['camera_model'] = str(tags['Image Model'])
                if 'EXIF LensModel' in tags:
                    exif_data['lens_model'] = str(tags['EXIF LensModel'])
                try:
                    if 'EXIF ISOSpeedRatings' in tags:
                        exif_data['iso'] = int(tags['EXIF ISOSpeedRatings'].values[0])
                except (ValueError, IndexError, ZeroDivisionError):
                    pass
                try:
                    if 'EXIF FNumber' in tags:
                        exif_data['f_stop'] = float(tags['EXIF FNumber'].values[0])
                except (ValueError, IndexError, ZeroDivisionError):
                    pass
                if 'EXIF ExposureTime' in tags:
                    exif_data['shutter_speed'] = str(tags['EXIF ExposureTime'])
                try:
                    if 'EXIF FocalLength' in tags:
                        exif_data['focal_length'] = float(tags['EXIF FocalLength'].values[0])
                except (ValueError, IndexError, ZeroDivisionError):
                    pass
                try:
                    if 'EXIF FocalLengthIn35mmFilm' in tags:
                        exif_data['focal_length_35mm'] = float(tags['EXIF FocalLengthIn35mmFilm'].values[0])
                except (ValueError, IndexError, ZeroDivisionError):
                    pass
                if exif_data['camera_model']:
                    return _sanitize_exif_numeric(exif_data)
        except Exception:
            pass

        # 4. Fallback to Pillow (JPEG and TIFF/DNG via modern getexif API)
        try:
            with Image.open(image_path) as img:
                exif = img.getexif()
                all_tags = dict(exif.items())
                exif_ifd = exif.get_ifd(0x8769)
                if exif_ifd:
                    all_tags.update(exif_ifd)
            if all_tags:
                for tag, value in all_tags.items():
                    decoded = ExifTags.TAGS.get(tag, tag)
                    if decoded == 'DateTimeOriginal':
                        exif_data['date_taken'] = str(value)
                    elif decoded == 'Model':
                        exif_data['camera_model'] = str(value)
                    elif decoded == 'LensModel':
                        exif_data['lens_model'] = str(value)
                    elif decoded == 'ISOSpeedRatings':
                        exif_data['iso'] = int(value[0]) if isinstance(value, tuple) else int(value)
                    elif decoded == 'FNumber':
                        exif_data['f_stop'] = float(value)
                    elif decoded == 'ExposureTime':
                        exif_data['shutter_speed'] = str(value)
                    elif decoded == 'FocalLength':
                        exif_data['focal_length'] = float(value)
                    elif decoded == 'FocalLengthIn35mmFilm':
                        exif_data['focal_length_35mm'] = float(value)
        except Exception as e:
            logger.warning("EXIF extraction failed for %s: %s", image_path, e)
        return _sanitize_exif_numeric(exif_data)

    def save_photos_batch(self, results_with_images):
        """
        Batch insert multiple photos in a single transaction for better performance.

        Args:
            results_with_images: List of (result_dict, pil_img) tuples
        """
        if not results_with_images:
            return

        # Phase 1: Pre-generate thumbnails (CPU work, no DB lock held)
        for res, pil_img in results_with_images:
            res['thumbnail'] = generate_photo_thumbnail(
                thumbnail_source(res['path'], pil_img))

        # Phase 2: Collect all face records for batch insert (including thumbnails,
        # landmarks and per-face quality signals — shared upsert: see db.schema)
        face_records = []
        embedding_model = active_embedding_model()
        for res, _ in results_with_images:
            # face_details None = faces unknown (the face pass failed): not []
            face_details = res.get('face_details') or []
            for face in face_details:
                if face.get('embedding'):
                    face_records.append(face_upsert_row(res['path'], face, embedding_model))

        # Phase 3: Fast DB inserts (short transaction)
        from analyzers.form_facet import FORM_METRIC_COLUMNS
        with get_connection(self.db_path, row_factory=False) as conn:
            # Batch insert photos
            for res, _ in results_with_images:
                # Optional extended-IQA columns default to NULL for callers/passes
                # that did not compute them (named-param INSERT needs every key).
                res.setdefault('qrealign_score', None)
                res.setdefault('aesthetic_v25', None)
                res.setdefault('deqa_score', None)
                res.setdefault('subject_bbox', None)
                res.setdefault('channel_clip_shadow_pct', None)
                res.setdefault('channel_clip_highlight_pct', None)
                for form_col in FORM_METRIC_COLUMNS:
                    res.setdefault(form_col, None)
                conn.execute(_photos_upsert(f'''
                    INSERT OR REPLACE INTO photos (
                        path, filename, category, image_width, image_height,
                        date_taken, camera_model, lens_model, iso, f_stop,
                        shutter_speed, focal_length, focal_length_35mm, aesthetic, face_count, face_quality,
                        eye_sharpness, face_sharpness, face_ratio, tech_sharpness, color_score,
                        exposure_score, comp_score, isolation_bonus, is_blink, phash, aggregate, thumbnail,
                        clip_embedding, raw_sharpness_variance, histogram_data, histogram_spread,
                        mean_luminance, histogram_bimodality, power_point_score, raw_color_entropy,
                        raw_eye_sharpness, config_version,
                        shadow_clipped, highlight_clipped,
                        channel_clip_shadow_pct, channel_clip_highlight_pct,
                        is_silhouette, is_group_portrait, leading_lines_score,
                        face_confidence, is_monochrome, mean_saturation,
                        dynamic_range_stops, noise_sigma, contrast_score, tags,
                        quality_score, topiq_score, composition_explanation, scoring_model, composition_pattern,
                        aesthetic_iaa, face_quality_iqa, liqe_score,
                        qrealign_score, aesthetic_v25, deqa_score,
                        subject_sharpness, subject_prominence, subject_placement, bg_separation, subject_bbox,
                        form_symmetry, form_balance, form_edge_entropy, form_fractal, color_harmony,
                        gps_latitude, gps_longitude, scanned_at, render_version
                    )
                    VALUES (
                        :path, :filename, :category, :image_width, :image_height,
                        :date_taken, :camera_model, :lens_model, :iso, :f_stop,
                        :shutter_speed, :focal_length, :focal_length_35mm, :aesthetic, :face_count, :face_quality,
                        :eye_sharpness, :face_sharpness, :face_ratio, :tech_sharpness, :color_score,
                        :exposure_score, :comp_score, :isolation_bonus, :is_blink, :phash, :aggregate, :thumbnail,
                        :clip_embedding, :raw_sharpness_variance, :histogram_data, :histogram_spread,
                        :mean_luminance, :histogram_bimodality, :power_point_score, :raw_color_entropy,
                        :raw_eye_sharpness, :config_version,
                        :shadow_clipped, :highlight_clipped,
                        :channel_clip_shadow_pct, :channel_clip_highlight_pct,
                        :is_silhouette, :is_group_portrait, :leading_lines_score,
                        :face_confidence, :is_monochrome, :mean_saturation,
                        :dynamic_range_stops, :noise_sigma, :contrast_score, :tags,
                        :quality_score, :topiq_score, :composition_explanation, :scoring_model, :composition_pattern,
                        :aesthetic_iaa, :face_quality_iqa, :liqe_score,
                        :qrealign_score, :aesthetic_v25, :deqa_score,
                        :subject_sharpness, :subject_prominence, :subject_placement, :bg_separation, :subject_bbox,
                        :form_symmetry, :form_balance, :form_edge_entropy, :form_fractal, :color_harmony,
                        :gps_latitude, :gps_longitude, datetime('now'), {DISPLAY_RENDER_VERSION}
                    )
                '''), res)

            # Refresh faces for every photo we just wrote (the UPSERT no longer
            # cascade-deletes them) — this also clears stale faces on a photo
            # that lost all its faces on re-scan — then batch-insert the fresh rows.
            # A photo whose face analysis failed (face_details is None) keeps its
            # stored faces: unknown is not "lost all its faces".
            # Named persons keep their faces across the replacement: the new rows
            # are re-attached by box overlap (db.person_carry_over).
            replace_photo_faces(
                conn,
                [res['path'] for res, _ in results_with_images
                 if not ('face_details' in res and res['face_details'] is None)],
                face_records, FACES_UPSERT_SQL,
                defer_centroids=self._pending_centroid_persons)

            # Sync clip embeddings to photos_vec for vector search
            vec_records = [
                (res['path'], res['clip_embedding'])
                for res, _ in results_with_images
                if res.get('clip_embedding')
            ]
            sync_vec_batch(conn, vec_records)

            # Every row above rewrote `tags`; keep an in-use photo_tags lookup in step.
            sync_photo_tags(conn, [res['path'] for res, _ in results_with_images])

            # Commit the entire batch in one transaction
            conn.commit()

        # Emit plugin events
        from plugins import get_plugin_manager
        pm = get_plugin_manager()
        if pm:
            for res, _ in results_with_images:
                event_data = {
                    'path': res.get('path'),
                    'filename': res.get('filename'),
                    'aggregate': res.get('aggregate', 0),
                    'aesthetic': res.get('aesthetic', 0),
                    'comp_score': res.get('comp_score', 0),
                    'category': res.get('category', ''),
                    'tags': res.get('tags', ''),
                }
                pm.emit('on_score_complete', event_data)
                if (res.get('aggregate') or 0) >= pm.high_score_threshold:
                    pm.emit('on_high_score', event_data)

    # ============================================
    # PARTIAL UPDATE METHODS (for multi-pass mode)
    # ============================================

    def save_photos_partial(self, batch, refresh_faces):
        """Persist a restricted single-pass chunk, updating only its own columns.

        ``batch`` is a list of ``(res, pil_img, computed_columns)`` where
        ``computed_columns`` names the DB columns the executed pass produced.
        Only those columns are written on an existing row. A thumbnail is
        generated only for a genuinely new file. ``refresh_faces`` gates the
        faces delete+reinsert so a non-face pass keeps person assignments,
        thumbnails and landmarks intact.
        """
        if not batch:
            return

        new_paths = self.filter_unscanned_paths([res['path'] for res, _, _ in batch])
        for res, pil_img, _ in batch:
            if res['path'] in new_paths:
                res['thumbnail'] = generate_photo_thumbnail(
                    thumbnail_source(res['path'], pil_img))
            else:
                res['thumbnail'] = None

        face_records = []
        if refresh_faces:
            embedding_model = active_embedding_model()
            for res, _, _ in batch:
                for face in res.get('face_details') or []:
                    if face.get('embedding'):
                        face_records.append(face_upsert_row(res['path'], face, embedding_model))

        with get_connection(self.db_path, row_factory=False) as conn:
            for res, _, computed_columns in batch:
                conn.execute(_photos_partial_upsert(computed_columns), res)

            if refresh_faces:
                replace_photo_faces(
                    conn,
                    [res['path'] for res, _, _ in batch
                     if not ('face_details' in res and res['face_details'] is None)],
                    face_records, FACES_UPSERT_SQL,
                    defer_centroids=self._pending_centroid_persons)

            sync_vec_batch(conn, [
                (res['path'], res['clip_embedding'])
                for res, _, computed_columns in batch
                if 'clip_embedding' in computed_columns and res.get('clip_embedding')
            ])

            sync_photo_tags(conn, [
                res['path'] for res, _, computed_columns in batch
                if 'tags' in computed_columns
            ])

            conn.commit()

    def filter_unscanned_paths(self, paths, chunk=900):
        """Return the subset of paths not yet present in the photos table.

        Uses chunked IN() probes against the path primary key instead of
        loading the entire path column into memory, so memory stays O(chunk)
        regardless of library size.

        Args:
            paths: Iterable of resolved path strings
            chunk: Paths per query (SQLite parameter limit is 999)

        Returns:
            Set of paths from the input that are NOT in the database
        """
        paths = list(paths)
        unscanned = set(paths)
        with get_connection(self.db_path, row_factory=False) as conn:
            for i in range(0, len(paths), chunk):
                batch = paths[i:i + chunk]
                placeholders = ','.join('?' * len(batch))
                cursor = conn.execute(
                    f'SELECT path FROM photos WHERE path IN ({placeholders})',
                    batch,
                )
                unscanned.difference_update(row[0] for row in cursor.fetchall())
        return unscanned

    def commit(self):
        with get_connection(self.db_path, row_factory=False) as conn:
            conn.commit()

    def flush_person_centroids(self):
        """Rebuild the centroid of every person a rescan batch re-attached faces to.

        ``save_photos_batch`` / ``save_photos_partial`` defer this (a person with
        thousands of faces would otherwise have every embedding re-read per
        batch). Call it once when the scan ends, in a ``finally`` and after the
        worker threads are joined. Returns the number of persons rebuilt.
        """
        pending = self._pending_centroid_persons
        if not pending:
            return 0
        person_ids = sorted(pending)
        with get_connection(self.db_path, row_factory=False) as conn:
            for person_id in person_ids:
                recompute_person_centroid(conn, person_id)
            conn.commit()
        pending.difference_update(person_ids)
        return len(person_ids)


# ============================================
# HELPER FUNCTIONS
# ============================================

# The one read ``process_bursts`` makes: EVERY row, through the covering index
# ``idx_post_scan`` (db/schema.py ``POST_SCAN_INDEXES``). Its column list IS the contract:
# every non-subquery column named here must be in that index, or this scan walks the table
# (and its thumbnails) again. ``learned_scores`` is probed by its own autoindex. The read has
# no ORDER BY on purpose: the grouping order is pinned in Python (see ``process_bursts``), so
# the result no longer depends on which index the planner picks.
_BURST_ROWS_SQL = (
    "SELECT rowid AS rid, path, date_taken, aggregate, phash, "
    "face_count, eyes_open_score, expression_score, tech_sharpness, "
    "is_burst_lead, burst_group_id, "
    "(SELECT ls.learned_score FROM learned_scores ls "
    " WHERE ls.photo_path = photos.path AND ls.user_id IS NULL "
    " AND ls.category IS NULL) AS learned_score "
    "FROM photos"
)


def process_bursts(db_path, config_path=None):
    """Flags the highest-scoring image in groups of visually similar photos.

    Reads every row once, groups the rows that carry a phash in memory, and writes ONLY the
    rows whose ``(is_burst_lead, burst_group_id)`` pair differs from the stored one, so a
    second run on an unchanged library writes nothing. Rows without a phash take no part in
    grouping: they are standalone (``is_burst_lead = 1``) and keep their ``burst_group_id``.
    """
    # Load burst detection settings from config
    config = ScoringConfig(config_path)
    burst_config = config.get_burst_detection_settings()
    similarity_percent = burst_config.get('similarity_threshold_percent', 88)
    time_window_minutes = burst_config.get('time_window_minutes', 60)
    rapid_burst_seconds = burst_config.get('rapid_burst_seconds', 5)

    # Convert percentage to hamming distance (64-bit phash)
    # 100% = 0 distance, 0% = 64 distance
    max_hamming_distance = int(64 * (1 - similarity_percent / 100))

    logger.info("Processing burst groups (rapid<=%ss, similarity>=%s%%, window=%smin)...", rapid_burst_seconds, similarity_percent, time_window_minutes)

    from utils.date_utils import parse_date
    from utils.selection import pick_lead

    with get_connection(db_path) as conn:
        rows = conn.execute(_BURST_ROWS_SQL).fetchall()

        # Photos without phash are not part of burst detection.
        photos = [dict(r) for r in rows if r['phash'] is not None]
        if not photos:
            return

        # The grouping order. SQLite's ``ORDER BY date_taken`` left the order of equal dates to
        # the plan; the plan the old query used (a backward walk of idx_date_taken_desc) yields
        # NULL dates first and equal dates by DESCENDING rowid, so that is pinned here. ``str()``
        # keeps a stray non-text date from raising TypeError against text (the column is TEXT).
        photos.sort(key=lambda p: (
            p['date_taken'] is not None,
            str(p['date_taken']) if p['date_taken'] is not None else '',
            -p['rid'],
        ))
        # Parsed once per photo, not once per pair.
        for p in photos:
            p['_date'] = parse_date(p['date_taken'])

        # Build person_id lookup only if faces exist
        photo_persons = {}
        has_faces = conn.execute("SELECT 1 FROM faces LIMIT 1").fetchone()
        if has_faces:
            face_data = conn.execute(
                "SELECT photo_path, person_id FROM faces WHERE person_id IS NOT NULL"
            ).fetchall()
            for row in face_data:
                photo_persons.setdefault(row['photo_path'], set()).add(row['person_id'])

        def phash_distance(hash1, hash2):
            """Compute hamming distance between two hex phash strings."""
            if not hash1 or not hash2:
                return 999
            return bin(int(hash1, 16) ^ int(hash2, 16)).count('1')

        def shares_person(path1, path2):
            """Check if two photos share at least one identified person."""
            persons1 = photo_persons.get(path1, set())
            persons2 = photo_persons.get(path2, set())
            # If either has no identified faces, allow grouping
            if not persons1 or not persons2:
                return True
            # Otherwise require at least one shared person
            return bool(persons1 & persons2)

        def is_similar_to_burst(photo, burst, threshold, time_limit, rapid_seconds):
            """Check if photo belongs to burst - rapid shots require face consistency."""
            photo_date = photo['_date']
            if photo_date is None:
                return False

            for b in burst:
                b_date = b['_date']
                if b_date is None:
                    continue

                time_diff = abs((photo_date - b_date).total_seconds())

                # Rapid burst: within N seconds AND face-consistent AND visually similar
                # Use relaxed phash threshold (2x normal) for rapid bursts
                if time_diff <= rapid_seconds:
                    if shares_person(photo['path'], b['path']):
                        if phash_distance(photo['phash'], b['phash']) <= threshold * 2:
                            return True

                # Slow burst: within time window AND visually similar
                if time_diff <= time_limit * 60:
                    if phash_distance(photo['phash'], b['phash']) <= threshold:
                        return True

            return False

        # The state every row should end in: rowid -> (is_burst_lead, burst_group_id).
        # A phash row defaults to "not a lead, in no group"; finalizing its burst overwrites
        # that. A phash-less row is a standalone lead and its group id is left as stored.
        wanted = {}
        for r in rows:
            if r['phash'] is None:
                wanted[r['rid']] = (1, r['burst_group_id'])
        for p in photos:
            wanted[p['rid']] = (0, None)

        burst_groups_for_emit = []

        def finalize_burst(burst, burst_id):
            # Composite best-of: aggregate dominates, eyes-open / expression /
            # sharpness break near-ties toward the better keeper frame.
            winner = pick_lead(burst)
            grouped = len(burst) >= 2
            group_value = burst_id if grouped else None
            wanted[winner['rid']] = (1, group_value)
            if grouped:
                for p in burst:
                    if p is not winner:
                        wanted[p['rid']] = (0, group_value)
                burst_groups_for_emit.append({
                    'burst_group_id': burst_id,
                    'photo_count': len(burst),
                    'best_path': winner['path'],
                    'paths': [p['path'] for p in burst],
                })

        current_burst = [photos[0]]
        group_id = 0
        for i in range(1, len(photos)):
            if is_similar_to_burst(photos[i], current_burst, max_hamming_distance, time_window_minutes, rapid_burst_seconds):
                current_burst.append(photos[i])
            else:
                # Finalize previous burst
                if current_burst:
                    finalize_burst(current_burst, group_id)
                    if len(current_burst) >= 2:
                        group_id += 1
                current_burst = [photos[i]]

        # Handle final burst
        if current_burst:
            finalize_burst(current_burst, group_id)

        # Write only what differs from the stored pair. A row that left a group is written
        # with burst_group_id = NULL explicitly; there is no blanket reset.
        changes = [
            (wanted[r['rid']][0], wanted[r['rid']][1], r['rid'])
            for r in rows
            if (r['is_burst_lead'], r['burst_group_id']) != wanted[r['rid']]
        ]
        if changes:
            conn.executemany(
                "UPDATE photos SET is_burst_lead = ?, burst_group_id = ? WHERE rowid = ?",
                changes,
            )
        conn.commit()
        logger.info("Burst state: %d rows changed", len(changes))
        logger.info("Assigned %d burst groups", group_id + 1 if current_burst and len(current_burst) >= 2 else group_id)

    # Emit plugin events for burst groups
    from plugins import get_plugin_manager
    pm = get_plugin_manager()
    if pm:
        for group_data in burst_groups_for_emit:
            pm.emit('on_burst_detected', group_data)


def process_single_photo(photo_path, scorer):
    """Worker function to handle image loading and metadata extraction.

    Loads through the same metrics-profile decode a scan uses, so a --dry-run
    preview reports the scores the scan would actually store.
    """
    try:
        current_pil, img_cv = load_image_from_path(photo_path)
        if current_pil is None:
            return None, f"could not load {photo_path}"
        # Run the scoring (The AI parts will still use the GPU lock)
        res = scorer.score_photo_from_pil(current_pil, img_cv, str(photo_path))
        return res, current_pil
    except Exception as e:
        licensing.reraise_if_refused()
        return None, str(e)
