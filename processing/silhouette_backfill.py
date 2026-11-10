"""Database-only backfill of ``photos.is_silhouette`` for the face-aware rule.

``detect_silhouette`` judges the largest face against its surround, in the pixel space of
the image the boxes were measured on. A library scanned before the rule changed carries the
old whole-frame flag, and ``--recompute-average`` never refreshes the flag (it reads the
stored one), so this pass re-derives it from what the database already holds: the stored
640 px ``photos.thumbnail`` and the ``faces`` rows. It decodes no source image and calls the
SAME ``detect_silhouette`` the scan calls.

The one hard part is the coordinate space. ``faces.bbox_*`` is not reliably in the space of
``photos.image_width x image_height``: a photo scanned on a 640 px preview whose faces were
later re-extracted at full resolution stores boxes ~8x larger than that image (63% of the
measured library). So every photo's boxes are classified, and mapped into the thumbnail grid
with an explicit scale, never trusted raw:

* ``exact``: ``sum(bbox areas) / (w * h) / face_ratio`` is 0.97-1.03, so the box space is
  ``image_width x image_height``.
* ``scaled``: one face row per counted face and an implied width
  ``W = sqrt(area / face_ratio * aspect)`` at least 3% above ``image_width`` that holds
  every box. ``W`` is refined by a +-12% search in 1% steps, keeping the width at which the
  thumbnail's face core luma matches the stored ``face_thumbnail`` core (geometry-free) to
  within 0.03.
* ``count_mismatch`` / ``other``: the same search over a wide width range. The
  ``count_mismatch`` refinement is UNVERIFIED (the ``scaled`` one was validated on exact
  rows at precision 0.91, recall 0.92); it is reported apart for that reason.

A photo whose geometry cannot be resolved is written 0 (no evidence of a silhouette).
"""

import io
import logging
import math

import numpy as np
from PIL import Image

from db.connection import get_connection
from utils.detection import detect_silhouette, silhouette_core_luma

logger = logging.getLogger("facet.silhouette_backfill")

DEFAULT_BATCH_SIZE = 500

# Geometry classification (silhouette study a08_geometry).
EXACT_AREA_RATIO_RANGE = (0.97, 1.03)
SCALED_MIN_SCALE = 1.03              # implied width / image_width at which a box space is "scaled"
SCALED_BOX_FIT = 1.03                # every box must end within this factor of the implied frame
CLASS_EXACT = 'exact'
CLASS_SCALED = 'scaled'
CLASS_COUNT_MISMATCH = 'count_mismatch'
CLASS_OTHER = 'other'
GEOMETRY_CLASSES = (CLASS_EXACT, CLASS_SCALED, CLASS_COUNT_MISMATCH, CLASS_OTHER)

# Width refinement (silhouette study a20_refine).
SCALED_WIDTH_FACTORS = np.arange(0.88, 1.125, 0.01)      # +-12% around the implied width, 1% steps
WIDE_WIDTH_GRID = np.arange(2500, 7600, 50.0)            # plausible camera widths, no implied width
GRID_FIT_SLACK = 0.98                                    # a candidate frame may be 2% narrower than the box
CORE_MATCH_TOLERANCE = 0.03                              # accepted |thumbnail core - face_thumbnail core|
NEGATIVE_CORE_LUMA = 0.25                                # a face_thumbnail core this bright cannot pass
# The face_thumbnail is the face box padded by crop_padding (0.3 per side), so the box
# occupies 0.5 +- 0.3125 of it and the rule's central 60% of the box is 0.5 +- 0.1875.
FACE_THUMB_CORE_SPAN = (0.3125, 0.6875)

OUTCOME_RULE = 'rule'                # geometry resolved, detect_silhouette applied
OUTCOME_NEGATIVE = 'negative_by_core'  # not exact and the face_thumbnail core is too bright
OUTCOME_UNRESOLVED = 'unresolved'    # geometry could not be resolved -> flag 0

_DECODE_ERRORS = (OSError, ValueError, SyntaxError, Image.DecompressionBombError)


def _decode_gray(blob):
    """uint8 gray plane of an encoded image, or None when it cannot be decoded."""
    if not blob:
        return None
    try:
        with Image.open(io.BytesIO(blob)) as image:
            return np.asarray(image.convert('L'))
    except _DECODE_ERRORS:
        return None


def _face_thumbnail_core_luma(blob):
    """Mean luma (0-1) of the centre of a stored ``face_thumbnail``, or None."""
    gray = _decode_gray(blob)
    if gray is None:
        return None
    height, width = gray.shape
    lo, hi = FACE_THUMB_CORE_SPAN
    core = gray[int(height * lo):math.ceil(height * hi), int(width * lo):math.ceil(width * hi)]
    if core.size == 0:
        return None
    return float(core.sum(dtype=np.float64)) / core.size / 255.0


def _number(value):
    """``value`` as a float, or None when it is NULL or not numeric."""
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _finite_positive(value):
    return value is not None and math.isfinite(value) and value > 0


def classify_geometry(photo, faces):
    """Geometry class of a photo's stored face boxes and, for ``scaled``, the implied frame.

    ``photo`` carries ``image_width``, ``image_height``, ``face_ratio``, ``face_count``;
    ``faces`` are dicts with ``x1, y1, x2, y2`` (rows with a NULL box already dropped).
    Returns ``(class, implied_width)``; the width is None unless the class is ``scaled``.
    """
    width, height = photo['image_width'], photo['image_height']
    ratio = photo['face_ratio']
    if not (_finite_positive(width) and _finite_positive(height) and _finite_positive(ratio)):
        return (CLASS_COUNT_MISMATCH if len(faces) != photo['face_count'] else CLASS_OTHER), None
    area = sum((f['x2'] - f['x1']) * (f['y2'] - f['y1']) for f in faces)
    if not _finite_positive(area):
        return (CLASS_COUNT_MISMATCH if len(faces) != photo['face_count'] else CLASS_OTHER), None
    q_exact = area / (width * height) / ratio
    if EXACT_AREA_RATIO_RANGE[0] <= q_exact <= EXACT_AREA_RATIO_RANGE[1]:
        return CLASS_EXACT, None
    implied_w = math.sqrt(area / ratio * (width / height))
    implied_h = implied_w * height / width
    fits = (max(f['x2'] for f in faces) <= implied_w * SCALED_BOX_FIT
            and max(f['y2'] for f in faces) <= implied_h * SCALED_BOX_FIT)
    if len(faces) == photo['face_count'] and implied_w / width >= SCALED_MIN_SCALE and fits:
        return CLASS_SCALED, implied_w
    return (CLASS_COUNT_MISMATCH if len(faces) != photo['face_count'] else CLASS_OTHER), None


def _mapped(faces, scale_x, scale_y):
    return [{'bbox': [f['x1'] * scale_x, f['y1'] * scale_y, f['x2'] * scale_x, f['y2'] * scale_y]}
            for f in faces]


def _refine_width(gray, largest, target_core, widths):
    """The candidate frame width whose mapped core luma best matches ``target_core``.

    Returns ``(width, error)`` or ``(None, None)``. Candidates too narrow to hold the
    largest box are dropped; ties keep the narrowest.
    """
    thumb_h, thumb_w = gray.shape
    floor = max(largest['x2'], largest['y2'] * thumb_w / thumb_h) * GRID_FIT_SLACK
    best_width, best_error = None, math.inf
    for width in widths:
        if width < floor:
            continue
        scale = thumb_w / width
        core = silhouette_core_luma(gray, (largest['x1'] * scale, largest['y1'] * scale,
                                           largest['x2'] * scale, largest['y2'] * scale))
        if core is None:
            continue
        error = abs(core - target_core)
        if error < best_error:
            best_width, best_error = float(width), error
    return (None, None) if best_width is None else (best_width, best_error)


def evaluate_photo(photo, faces, thumbnail_gray, load_face_thumbnail):
    """``(geometry class, outcome, is_silhouette)`` for one photo with faces.

    ``thumbnail_gray`` is the decoded ``photos.thumbnail``; ``load_face_thumbnail()``
    returns the stored ``face_thumbnail`` of the largest face and is called only for a
    non-exact class.
    """
    faces = [f for f in faces if None not in (f['x1'], f['y1'], f['x2'], f['y2'])]
    if not faces:
        return CLASS_OTHER, OUTCOME_UNRESOLVED, 0
    geometry, implied_w = classify_geometry(photo, faces)
    thumb_h, thumb_w = thumbnail_gray.shape

    if geometry == CLASS_EXACT:
        mapped = _mapped(faces, thumb_w / photo['image_width'], thumb_h / photo['image_height'])
        return geometry, OUTCOME_RULE, detect_silhouette(thumbnail_gray, mapped)

    # The stored box space is unknown. Calibrate it against the geometry-free face_thumbnail.
    target = _face_thumbnail_core_luma(load_face_thumbnail())
    if target is None:
        return geometry, OUTCOME_UNRESOLVED, 0
    if target >= NEGATIVE_CORE_LUMA:
        return geometry, OUTCOME_NEGATIVE, 0
    largest = max(faces, key=lambda f: (f['x2'] - f['x1']) * (f['y2'] - f['y1']))
    widths = implied_w * SCALED_WIDTH_FACTORS if geometry == CLASS_SCALED else WIDE_WIDTH_GRID
    width, error = _refine_width(thumbnail_gray, largest, target, widths)
    if width is None or error > CORE_MATCH_TOLERANCE:
        return geometry, OUTCOME_UNRESOLVED, 0
    scale = thumb_w / width
    return geometry, OUTCOME_RULE, detect_silhouette(thumbnail_gray, _mapped(faces, scale, scale))


def _new_stats():
    return {
        'rows': 0,
        'face_count_zero': 0,
        'skipped_face_count_null': 0,
        'skipped_no_thumbnail': 0,
        'skipped_unreadable_thumbnail': 0,
        'classes': {name: 0 for name in GEOMETRY_CLASSES},
        'unresolved': {name: 0 for name in GEOMETRY_CLASSES},
        'negative_by_core': {name: 0 for name in GEOMETRY_CLASSES},
        'flagged': {name: 0 for name in GEOMETRY_CLASSES},
        'flagged_total': 0,
        'set': 0,
        'cleared': 0,
        'unchanged': 0,
    }


def _load_faces(conn, paths):
    """``{photo_path: [face dicts]}`` for ``paths`` (boxes only, no BLOBs)."""
    faces = {}
    rows = conn.execute(
        "SELECT photo_path, face_index, bbox_x1, bbox_y1, bbox_x2, bbox_y2 FROM faces "
        f"WHERE photo_path IN ({','.join('?' * len(paths))}) ORDER BY photo_path, face_index",
        paths)
    for row in rows:
        faces.setdefault(row['photo_path'], []).append({
            'index': row['face_index'], 'x1': row['bbox_x1'], 'y1': row['bbox_y1'],
            'x2': row['bbox_x2'], 'y2': row['bbox_y2']})
    return faces


def _largest_face_thumbnail(conn, path, faces):
    valid = [f for f in faces if None not in (f['x1'], f['y1'], f['x2'], f['y2'])]
    if not valid:
        return None
    largest = max(valid, key=lambda f: (f['x2'] - f['x1']) * (f['y2'] - f['y1']))
    row = conn.execute("SELECT face_thumbnail FROM faces WHERE photo_path = ? AND face_index = ?",
                       (path, largest['index'])).fetchone()
    return row['face_thumbnail'] if row else None


def _process_batch(conn, rows, stats):
    """Decide the new flag of every row in the batch; returns ``[(flag, path)]`` to write."""
    faced = [r['path'] for r in rows if (r['face_count'] or 0) > 0 and r['thumbnail']]
    faces_by_path = _load_faces(conn, faced) if faced else {}
    writes = []
    for row in rows:
        stats['rows'] += 1
        face_count = row['face_count']
        if face_count is None:
            # The face evidence is unknown (a failed face pass stores NULL): leave the flag.
            stats['skipped_face_count_null'] += 1
            continue
        if face_count <= 0:
            stats['face_count_zero'] += 1
            new_flag = 0
        else:
            if not row['thumbnail']:
                stats['skipped_no_thumbnail'] += 1
                continue
            gray = _decode_gray(row['thumbnail'])
            if gray is None:
                stats['skipped_unreadable_thumbnail'] += 1
                continue
            faces = faces_by_path.get(row['path'], [])
            photo = {key: _number(row[key])
                     for key in ('image_width', 'image_height', 'face_ratio', 'face_count')}
            geometry, outcome, new_flag = evaluate_photo(
                photo, faces, gray, lambda: _largest_face_thumbnail(conn, row['path'], faces))
            stats['classes'][geometry] += 1
            if outcome == OUTCOME_UNRESOLVED:
                stats['unresolved'][geometry] += 1
            elif outcome == OUTCOME_NEGATIVE:
                stats['negative_by_core'][geometry] += 1
            if new_flag:
                stats['flagged'][geometry] += 1
        stats['flagged_total'] += new_flag
        old_flag = 1 if row['is_silhouette'] else 0
        if new_flag == old_flag:
            stats['unchanged'] += 1
        elif new_flag:
            stats['set'] += 1
            writes.append((1, row['path']))
        else:
            stats['cleared'] += 1
            writes.append((0, row['path']))
    return writes


def recompute_silhouette(db_path='photo_scores_pro.db', dry_run=False, batch_size=DEFAULT_BATCH_SIZE):
    """Re-derive ``photos.is_silhouette`` from the stored thumbnails and face boxes.

    Rewrites only that column, only where the value changes, and commits per batch, so an
    interrupted run keeps what it finished and a re-run converges to the same result (a
    finished library is a no-op write-wise). ``dry_run`` evaluates everything and writes
    nothing. Rows whose ``face_count`` is NULL (face evidence unknown) or that have faces but
    no readable stored thumbnail are skipped and keep their flag.

    Returns the stats dict (also logged).
    """
    stats = _new_stats()
    last_rowid = 0
    while True:
        with get_connection(db_path, read_only=dry_run) as conn:
            rows = conn.execute(
                "SELECT rowid AS rid, path, image_width, image_height, face_ratio, face_count, "
                "is_silhouette, CASE WHEN face_count > 0 THEN thumbnail END AS thumbnail "
                "FROM photos WHERE rowid > ? ORDER BY rowid LIMIT ?",
                (last_rowid, batch_size)).fetchall()
            if not rows:
                break
            last_rowid = rows[-1]['rid']
            writes = _process_batch(conn, rows, stats)
            if writes and not dry_run:
                conn.executemany("UPDATE photos SET is_silhouette = ? WHERE path = ?", writes)
                conn.commit()
        logger.info("Silhouette: %d photos checked...", stats['rows'])
    _log_report(stats, dry_run)
    return stats


def _log_report(stats, dry_run):
    verb = "would be" if dry_run else "are"
    logger.info("Silhouette backfill%s: %d photos checked.", " (dry run, nothing written)" if dry_run else "",
                stats['rows'])
    for name in GEOMETRY_CLASSES:
        logger.info(
            "  geometry %-15s %6d photos: %d flagged, %d too bright to pass, %d unresolved (written 0)%s",
            name, stats['classes'][name], stats['flagged'][name], stats['negative_by_core'][name],
            stats['unresolved'][name],
            "  [UNVERIFIED refinement]" if name == CLASS_COUNT_MISMATCH else "")
    logger.info("  face_count = 0 (written 0): %d", stats['face_count_zero'])
    logger.info("  %d photos %s flagged: %d set, %d cleared, %d unchanged.",
                stats['flagged_total'], verb, stats['set'], stats['cleared'], stats['unchanged'])
    logger.info("  skipped_face_count_null=%d (face evidence unknown, flag left unchanged)",
                stats['skipped_face_count_null'])
    logger.info("  skipped_no_thumbnail=%d (flag left unchanged)", stats['skipped_no_thumbnail'])
    if stats['skipped_unreadable_thumbnail']:
        logger.info("  skipped_unreadable_thumbnail=%d (flag left unchanged)",
                    stats['skipped_unreadable_thumbnail'])
    if dry_run:
        logger.info("Dry run: nothing was written.")
    else:
        logger.info("Run `python facet.py --recompute-average` to apply the new flag to scores and categories.")
