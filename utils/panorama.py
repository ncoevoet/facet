"""
Panorama detection by geometric confirmation.

A panorama's source frames were shot to be stitched, not to compete. Burst
detection cannot see that -- the frames arrive seconds apart from one camera at
one focal length -- so it groups them as competing takes and hides all but one
behind a lead chosen on a criterion that means nothing here. On a real library a
33-frame sweep was found shredded across seven burst groups.

Nothing in stored metadata identifies a pan. Exposure is no help: one confirmed
set was shot with locked exposure and another on auto. The evidence has to be
geometric, and it is measured between consecutive frames on the stored 640px
thumbnails -- no original decode, no model, no new dependency:

    SIFT features -> ratio-tested matches -> RANSAC homography on
    centre-shifted coordinates -> the translation (dx, dy) it implies.

What separates a sweep from a burst is *cumulative* drift, not per-frame shift.
Real panoramas here are shot at ~90% overlap, so a single step moves only 5-18%
of the frame -- indistinguishable from camera shake. Over a run the difference is
absolute: a burst wobbles around zero (0.01 frame widths measured), a sweep
marches (0.56-2.83 measured). Requiring instead that every pair show a shift
would reject every HDR panorama, whose frames sit still while the bracket fires.

Thresholds were calibrated against 26 panoramas and 8 non-panoramas confirmed by
eye on a 126k library, not chosen by reasoning. Three plausible rules were
falsified in the process and are recorded in the module so they are not retried:
per-pair shift magnitude, pure-rotation focal recovery (`K R K^-1`, which is
ill-conditioned at these overlaps -- one 33-frame sweep recovered focals from 22
to 2461 px), and exposure lock.

Precision measured ~96%; recall is deliberately incomplete. Vertical low-drift
sweeps and few-position panoramas fall below the drift floor, inside the
distribution of confirmed negatives, and cannot be recovered by any threshold
without admitting reportage. Missing a panorama costs nothing here; mislabelling
reportage costs trust. The sticky per-set override covers both directions.
"""

import logging
import multiprocessing
import os
import sqlite3
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor

import numpy as np

from db.connection import apply_pragmas
from utils.date_utils import parse_date
from utils.sequence import exposure_value

logger = logging.getLogger("facet.panorama")

PANORAMA = 'panorama'
HDR_PANORAMA = 'hdr_panorama'
KINDS = (PANORAMA, HDR_PANORAMA)

DEFAULTS = {
    'enabled': True,
    # Candidate gate -- EXIF only, no pixels touched.
    'max_gap_seconds': 30.0,
    'min_frames': 8,
    # Geometry.
    'min_inliers': 25,
    'min_drift': 0.43,
    'max_step': 0.90,
    'back_tolerance': 0.02,
    'max_ortho': 0.15,
    'ortho_ratio': 0.25,
    'step_ortho_abs': 0.02,
    'step_ortho_ratio': 0.5,
    # Cost controls.
    'sift_features': 400,
    'match_ratio': 0.75,
    'probe_stride': 8,
    'probe_min_drift': 0.05,
    'workers': 0,
    # A sweep never needs this many frames; the cap bounds the per-run
    # feature cache, which holds ~220 KB per frame per worker.
    'max_run_frames': 500,
    # A panorama is HDR when its frames span a real exposure ladder.
    'hdr_min_span_stops': 1.5,
}


def _sift_and_matcher(settings):
    """Build the detector and matcher, importing cv2 lazily.

    Imported inside the call so that the module -- and the config and CLI wiring
    that reference it -- stay importable where OpenCV is unavailable.
    """
    import cv2
    sift = cv2.SIFT_create(nfeatures=settings['sift_features'])
    # FLANN over float descriptors: brute-force knn is the per-pair hot spot and
    # the inlier margins (300-700 against a floor of 25) leave ample room for an
    # approximate index.
    matcher = cv2.FlannBasedMatcher(dict(algorithm=1, trees=4), dict(checks=32))
    return sift, matcher


def _features(conn, path, sift, cache):
    """SIFT keypoints and descriptors for a photo's stored thumbnail."""
    import cv2
    if path in cache:
        return cache[path]
    row = conn.execute("SELECT thumbnail FROM photos WHERE path = ?", (path,)).fetchone()
    result = None
    if row is not None and row[0]:
        image = cv2.imdecode(np.frombuffer(row[0], np.uint8), cv2.IMREAD_GRAYSCALE)
        if image is not None:
            keypoints, descriptors = sift.detectAndCompute(image, None)
            if descriptors is not None and len(descriptors) >= 10:
                result = (keypoints, descriptors, image.shape)
    cache[path] = result
    return result


def _translation(first, second, sift, matcher, settings):
    """Translation between two frames as a fraction of frame width and height.

    Coordinates are shifted to put the origin at the image centre before the
    homography is estimated, which is what OpenCV's own stitching matcher does
    and what keeps the recovered translation meaningful.
    """
    import cv2
    if not first or not second:
        return None
    keys_a, desc_a, (height, width) = first
    keys_b, desc_b, _ = second
    knn = matcher.knnMatch(desc_a, desc_b, k=2)
    good = [m for m, n in (pair for pair in knn if len(pair) == 2)
            if m.distance < settings['match_ratio'] * n.distance]
    if len(good) < 8:
        return {'inliers': 0, 'dx': 0.0, 'dy': 0.0}
    source = np.float32([[keys_a[m.queryIdx].pt[0] - width / 2,
                          keys_a[m.queryIdx].pt[1] - height / 2] for m in good]).reshape(-1, 1, 2)
    target = np.float32([[keys_b[m.trainIdx].pt[0] - width / 2,
                          keys_b[m.trainIdx].pt[1] - height / 2] for m in good]).reshape(-1, 1, 2)
    homography, mask = cv2.findHomography(source, target, cv2.RANSAC, 3.0)
    if homography is None:
        return {'inliers': 0, 'dx': 0.0, 'dy': 0.0}
    homography = homography / homography[2, 2]
    return {'inliers': int(mask.sum()),
            'dx': float(homography[0, 2] / width),
            'dy': float(homography[1, 2] / height)}


def _is_static_run(conn, paths, sift, matcher, settings, cache):
    """Whether a run holds still from end to end, probed at a stride.

    Most candidate runs are ordinary bursts, so most of the cost would go into
    proving a burst is a burst. Probing every `probe_stride` frames costs a
    fraction of the pairs.

    Deliberately not probed on consecutive frames: an HDR panorama opens with
    bracket frames, so its first consecutive pairs are static by construction --
    one measured 0.01 drift over four pairs against a real total of 0.87. A probe
    that fails to match means large motion and escalates; only a confident static
    match at every probe abandons the run.
    """
    # Floored: a hand-edited config bypasses the API's bounds, and the sibling
    # keys use 0 as a "pick for me" sentinel, so `probe_stride: 0` is a
    # plausible edit. It would make this loop never advance -- and the scan
    # would hang holding the library lock, which no exception guard catches.
    stride = max(1, int(settings['probe_stride']))
    if len(paths) < stride + 1:
        return False
    index = 0
    while index < len(paths) - 1:
        nxt = min(index + stride, len(paths) - 1)
        step = _translation(_features(conn, paths[index], sift, cache),
                            _features(conn, paths[nxt], sift, cache),
                            sift, matcher, settings)
        if step is None or step['inliers'] < settings['min_inliers']:
            return False
        if (abs(step['dx']) >= settings['probe_min_drift']
                or abs(step['dy']) >= settings['probe_min_drift']):
            return False
        index = nxt
    return True


def _extend(steps, start, axis, sign, settings):
    """How far a monotone sweep along `axis` continues from `start`."""
    end = start
    while end < len(steps):
        step = steps[end]
        if step is None or step['inliers'] < settings['min_inliers']:
            break
        dominant = step['dx'] if axis == 'x' else step['dy']
        orthogonal = step['dy'] if axis == 'x' else step['dx']
        if abs(dominant) > settings['max_step']:
            break
        if dominant * sign < -settings['back_tolerance']:
            break
        # A sweep step moves along one axis. A step moving substantially in both
        # is the photographer recomposing between two activities and belongs to
        # neither: one measured dy of +0.255 against <=0.004 on every genuine
        # step of the same panorama.
        if abs(orthogonal) > max(settings['step_ortho_abs'],
                                 settings['step_ortho_ratio'] * abs(dominant)):
            break
        end += 1
    return end


def find_segments(paths, steps, settings):
    """The stretches of a run that qualify as panoramas.

    A run is segmented rather than accepted or rejected whole: a sweep is often
    followed by other frames, two sweeps in opposite directions arrive as one
    run, and a long panorama must not die on a single unmatched pair.
    """
    segments = []
    index = 0
    while index < len(steps):
        if steps[index] is None or steps[index]['inliers'] < settings['min_inliers']:
            index += 1
            continue
        # Axis and sign cannot be read off the first step: in an HDR panorama it
        # sits inside a bracket, where the translation is pure noise. Every
        # orientation is tried and ranked by drift -- ranking by length instead
        # always picks the axis with no motion, whose extension never breaks.
        best = None
        for axis in ('x', 'y'):
            for sign in (1, -1):
                end = _extend(steps, index, axis, sign, settings)
                span = steps[index:end]
                if len(span) + 1 < settings['min_frames']:
                    continue
                drift = abs(sum((s['dx'] if axis == 'x' else s['dy']) for s in span))
                orthogonal = abs(sum((s['dy'] if axis == 'x' else s['dx']) for s in span))
                if best is None or (drift, end) > (best[0], best[1]):
                    best = (drift, end, axis, orthogonal, span)
        if best is None:
            index += 1
            continue
        drift, end, axis, orthogonal, span = best
        # The orthogonal budget scales with the sweep: a long pan accumulates
        # more vertical wander than a short one, so a flat cap rejects real sets.
        cap = max(settings['max_ortho'], settings['ortho_ratio'] * drift)
        if drift >= settings['min_drift'] and orthogonal <= cap:
            segments.append({
                'paths': paths[index:end + 1],
                'axis': axis,
                'drift': round(drift, 4),
                'ortho': round(orthogonal, 4),
            })
        index = max(end, index + 1)
    return segments


def _load_candidates(conn, settings):
    """Runs of consecutive frames that could hold a sweep.

    Same camera and same focal length -- nobody zooms mid-pan -- within
    `max_gap_seconds`. Cheap, EXIF only, and it is what keeps the geometry off
    the vast majority of the library.
    """
    rows = conn.execute(
        "SELECT path, date_taken, camera_model, focal_length, f_stop, shutter_speed, iso "
        "FROM photos WHERE date_taken IS NOT NULL AND focal_length IS NOT NULL"
    ).fetchall()
    photos = []
    for row in rows:
        captured_at = parse_date(row['date_taken'])
        if captured_at is None:
            continue
        photos.append({
            'path': row['path'],
            'captured_at': captured_at,
            'camera_model': row['camera_model'],
            'focal_length': row['focal_length'],
            'ev': exposure_value(row['f_stop'], row['shutter_speed'], row['iso']),
        })
    photos.sort(key=lambda p: (p['camera_model'] or '', p['captured_at'], p['path']))

    runs, current = [], []
    for photo in photos:
        if current:
            previous = current[-1]
            gap = (photo['captured_at'] - previous['captured_at']).total_seconds()
            continues = (photo['camera_model'] == previous['camera_model']
                         and photo['focal_length'] == previous['focal_length']
                         and 0 <= gap <= settings['max_gap_seconds'])
            if continues and len(current) < settings['max_run_frames']:
                current.append(photo)
                continue
        if len(current) >= settings['min_frames']:
            runs.append(current)
        current = [photo]
    if len(current) >= settings['min_frames']:
        runs.append(current)
    return runs


def classify_kind(evs, settings):
    """Whether a set is a plain sweep or an HDR one, from its exposure spread.

    Measured on confirmed sets, plain panoramas span 0.0-0.7 stops and HDR ones
    2.0-4.4, so the gap is wide and the threshold is not delicate. Deliberately
    not derived from how many steps hold still: that cannot tell "static because
    bracketing" from "static because barely moving", and it misclassified six
    low-drift non-panoramas as HDR at 80-90% static.
    """
    usable = [ev for ev in evs if ev is not None]
    if len(usable) < 2:
        return PANORAMA
    span = max(usable) - min(usable)
    return HDR_PANORAMA if span >= settings['hdr_min_span_stops'] else PANORAMA


def _analyse(conn, run, sift, matcher, settings):
    """Panorama segments within one candidate run."""
    paths = [photo['path'] for photo in run]
    cache = {}
    if _is_static_run(conn, paths, sift, matcher, settings, cache):
        return []
    steps, previous = [], _features(conn, paths[0], sift, cache)
    for path in paths[1:]:
        current = _features(conn, path, sift, cache)
        steps.append(_translation(previous, current, sift, matcher, settings))
        previous = current
    by_path = {photo['path']: photo for photo in run}
    segments = find_segments(paths, steps, settings)
    for segment in segments:
        segment['kind'] = classify_kind(
            [by_path[p]['ev'] for p in segment['paths']], settings)
    return segments


def load_overrides(conn):
    """Sticky per-set overrides: the suppressed paths, and the forced sets by key.

    Keyed on member paths rather than on `sequence_group_id`, because group ids
    are renumbered from 1 on every pass -- an override keyed on one would attach
    itself to an unrelated set the next time this runs. They live in their own
    table for the same reason the category overrides do: this pass clears and
    rewrites `photos.sequence_*`, so a correction stored there would not survive
    its next run.
    """
    rows = conn.execute(
        "SELECT photo_path, sequence_kind, override_group_key "
        "FROM photo_sequence_overrides ORDER BY photo_path"
    ).fetchall()
    suppressed = {row['photo_path'] for row in rows if row['sequence_kind'] is None}
    forced = defaultdict(list)
    for row in rows:
        if row['sequence_kind'] in KINDS:
            forced[row['override_group_key']].append((row['sequence_kind'], row['photo_path']))
    return suppressed, forced


def resolve_segments(segments, suppressed, forced):
    """Detector output reconciled with the user's overrides.

    The single choke point where the two meet, so the scan path and a manual
    re-run cannot disagree about what a set is. A manual decision always wins: a
    suppressed member drops the set the detector proposed, and a forced set
    displaces any detected set it overlaps.
    """
    forced_sets = []
    for key in sorted(forced):
        members = forced[key]
        paths = sorted(path for _, path in members)
        if len(paths) >= 2:
            forced_sets.append({'paths': paths, 'kind': members[0][0], 'axis': 'x',
                                'drift': 0.0, 'ortho': 0.0, 'source': 'override'})
    forced_paths = {path for segment in forced_sets for path in segment['paths']}

    resolved = []
    for segment in segments:
        if any(path in suppressed for path in segment['paths']):
            continue
        if any(path in forced_paths for path in segment['paths']):
            continue
        resolved.append(dict(segment, source='detector'))
    return resolved + forced_sets


_WORKER = {}


def _init_worker(db_path, settings):
    """Give each worker its own read-only connection, matcher and thread budget."""
    import cv2
    _WORKER['conn'] = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    apply_pragmas(_WORKER['conn'])
    _WORKER['conn'].row_factory = sqlite3.Row
    _WORKER['sift'], _WORKER['matcher'] = _sift_and_matcher(settings)
    _WORKER['settings'] = settings
    # Each worker is already a process; letting OpenCV thread inside them as
    # well oversubscribes the machine and makes the pool slower than serial.
    cv2.setNumThreads(1)


def _analyse_in_worker(run):
    return _analyse(_WORKER['conn'], run, _WORKER['sift'], _WORKER['matcher'],
                    _WORKER['settings'])


def _analyse_runs(db_path, runs, sift, matcher, settings):
    """Geometry over every candidate run, in parallel when it is worth it.

    Each run is independent, so this is embarrassingly parallel. It scales well
    short of the core count rather than with it: the cost is dominated by
    reading thumbnail BLOBs at random offsets out of a multi-gigabyte SQLite
    file, which the workers contend on. Measured at roughly 2.7x on 16 cores.
    """
    workers = settings.get('workers') or 0
    if workers <= 0:
        workers = min(8, os.cpu_count() or 1)
    if workers < 2 or len(runs) < 2:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            return [seg for run in runs for seg in _analyse(conn, run, sift, matcher, settings)]
        finally:
            conn.close()

    found = []
    # 'spawn', never the default 'fork'. This runs inside the scan pipeline,
    # which is multi-threaded, and forking a process that already holds OpenCV
    # and SQLite state deadlocks the children -- the pool simply never returns.
    # Spawn pays a fresh import per worker, which is nothing against a
    # whole-library geometry pass.
    context = multiprocessing.get_context('spawn')
    with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker,
                             initargs=(db_path, settings), mp_context=context) as pool:
        for segments in pool.map(_analyse_in_worker, runs, chunksize=8):
            found.extend(segments)
    return found


def detect_panoramas(db_path, config_path=None):
    """Label panorama sets across the library.

    Whole-library by nature: a set is defined by its chronological neighbours, so
    a photo cannot be classified without them.

    Args:
        db_path: Path to the SQLite database
        config_path: Path to scoring_config.json (optional)
    """
    from config import ScoringConfig

    settings = dict(DEFAULTS)
    settings.update(
        ScoringConfig(config_path, validate=False).get_panorama_detection_settings())
    if not settings.get('enabled', True):
        logger.info("Panorama detection disabled in config.")
        return None

    try:
        sift, matcher = _sift_and_matcher(settings)
    except ImportError:
        logger.warning("OpenCV unavailable; skipping panorama detection.")
        return None

    with sqlite3.connect(db_path) as conn:
        apply_pragmas(conn)
        conn.row_factory = sqlite3.Row
        runs = _load_candidates(conn, settings)
        logger.info(
            "Panorama detection over %d candidate runs (gap<=%ss, >=%d frames, "
            "drift>=%.2f frame widths)...",
            len(runs), settings['max_gap_seconds'], settings['min_frames'],
            settings['min_drift'])

        found = _analyse_runs(db_path, runs, sift, matcher, settings)

        suppressed, forced = load_overrides(conn)
        found = resolve_segments(found, suppressed, forced)

        # `sequence_ev_offset` goes too. An HDR panorama's frames were labelled
        # by the bracket pass first, which wrote an offset the panorama label
        # then superseded; leaving it behind means the row carries an exposure
        # offset for a set that has no base exposure, and the bracket pass's own
        # kind-scoped clear will never reach it again.
        conn.execute(
            "UPDATE photos SET sequence_group_id = NULL, sequence_kind = NULL, "
            "sequence_ev_offset = NULL, is_sequence_lead = 0 "
            "WHERE sequence_kind IN (?, ?)", KINDS)
        for group_id, segment in enumerate(found, start=1):
            paths = segment['paths']
            conn.executemany(
                "UPDATE photos SET sequence_group_id = ?, sequence_kind = ?, "
                "sequence_ev_offset = NULL, is_sequence_lead = 0 WHERE path = ?",
                [(group_id, segment['kind'], path) for path in paths])
            # The middle frame stands for the set: a sweep has no best frame, and
            # the middle one is the likeliest to hold the subject. Marked here so
            # the gallery's hide clause is an indexed equality rather than a
            # window function run over every row of every query.
            conn.execute("UPDATE photos SET is_sequence_lead = 1 WHERE path = ?",
                         (paths[len(paths) // 2],))
        conn.commit()

    frames = sum(len(segment['paths']) for segment in found)
    plain = sum(1 for segment in found if segment['kind'] == PANORAMA)
    logger.info("Found %d panorama sets (%d plain, %d HDR) covering %d frames.",
                len(found), plain, len(found) - plain, frames)
    return {'sets': len(found), 'frames': frames,
            'panorama': plain, 'hdr_panorama': len(found) - plain}
