"""
Deliberate multi-frame sequence detection (exposure brackets).

A bracket is one subject captured at several exposures to cover a scene's
dynamic range. Burst detection cannot tell it apart from a run of competing
takes -- same subject, same second, near-identical framing -- so it groups the
set and promotes whichever frame happens to score highest, which for a bracket
is arbitrary: the under- and over-exposed frames were never candidates for
"best", they exist to be merged later. With the shipped `hide_bursts` default
that also means two frames in three vanish behind a representative chosen on the
wrong criterion.

This pass names those sets. The signal is the exposure ladder itself, derived
from values already stored per photo:

    EV = log2(N^2 / t) - log2(ISO / 100)

so no EXIF re-read and no rescan is needed -- an existing library is labelled by
arithmetic over columns it already has. A run qualifies as a bracket when it is
long enough, its EV steps all point the same way, they span a real difference,
and they are evenly sized: a hand-held sequence through changing light drifts,
it does not step by a clean 1 or 2 stops each time.

Panoramas are detected separately, in `utils.panorama`, on geometric evidence
rather than on exposure. Both passes share the `sequence_*` columns but own
disjoint sets of rows, each clearing and rewriting only its own
`sequence_kind`, and each numbering its own sets from 1 -- so the identity of a
set is the pair `(sequence_kind, sequence_group_id)`, and every reader must
filter by kind before grouping by id.
"""

import logging
import math
import sqlite3

from db.connection import apply_pragmas
from utils.date_utils import parse_date
from utils.selection import pick_lead

logger = logging.getLogger("facet.sequence")

BRACKET = 'bracket'

DEFAULTS = {
    'enabled': True,
    'max_gap_seconds': 3.0,
    'max_hamming': 10,
    'min_frames': 3,
    'min_step_stops': 0.5,
    'min_span_stops': 1.0,
    'step_tolerance_stops': 0.34,
}


def _compensation_offset(base_ev, frame_ev):
    """Stops of exposure compensation a frame sits at, relative to the base.

    Negated against raw EV on purpose. Photometric EV runs the other way -- a
    higher EV is a smaller aperture or faster shutter, so a *darker* frame --
    while every photographer reads a bracket the way the camera labels it, with
    -2 the dark frame and +2 the bright one. Storing the photometric sign put a
    "+1 EV" badge on the darker picture.
    """
    return round(base_ev - frame_ev, 2)


def exposure_value(f_stop, shutter_speed, iso):
    """EV for a frame, or None when any of the three values is unusable.

    `shutter_speed` is stored as TEXT holding decimal seconds ('0.0015625'), and
    every one of the three is nullable, so each conversion is guarded rather
    than assumed.
    """
    try:
        aperture = float(f_stop)
        seconds = float(shutter_speed)
        sensitivity = float(iso)
    except (TypeError, ValueError):
        return None
    if aperture <= 0 or seconds <= 0 or sensitivity <= 0:
        return None
    return math.log2(aperture * aperture / seconds) - math.log2(sensitivity / 100.0)


def _hamming(hash_a, hash_b):
    """Bit distance between two hex pHash strings; a large value when either is missing."""
    if not hash_a or not hash_b:
        return 999
    try:
        return bin(int(hash_a, 16) ^ int(hash_b, 16)).count('1')
    except ValueError:
        return 999


def _extends_run(previous, candidate, settings):
    """Whether `candidate` continues the run `previous` ends.

    Same body, taken moments later, framed the same, at a materially different
    exposure. The exposure change is what separates a bracket from a burst: two
    frames of a burst sit at the same EV.
    """
    if candidate['camera_model'] != previous['camera_model']:
        return False
    if previous['captured_at'] is None or candidate['captured_at'] is None:
        return False
    gap = (candidate['captured_at'] - previous['captured_at']).total_seconds()
    if gap < 0 or gap > settings['max_gap_seconds']:
        return False
    if _hamming(previous['phash'], candidate['phash']) > settings['max_hamming']:
        return False
    return abs(candidate['ev'] - previous['ev']) >= settings['min_step_stops']


def _is_bracket(run, settings):
    """Whether a run's exposure ladder looks deliberate rather than incidental."""
    if len(run) < settings['min_frames']:
        return False
    steps = [b['ev'] - a['ev'] for a, b in zip(run, run[1:])]
    if not (all(s > 0 for s in steps) or all(s < 0 for s in steps)):
        return False
    if abs(run[-1]['ev'] - run[0]['ev']) < settings['min_span_stops']:
        return False
    sizes = [abs(s) for s in steps]
    return max(sizes) - min(sizes) <= settings['step_tolerance_stops']


def _find_bracket_runs(photos, settings):
    """Split a chronological photo list into the runs that qualify as brackets."""
    runs = []
    current = []
    for photo in photos:
        if current and _extends_run(current[-1], photo, settings):
            current.append(photo)
            continue
        if _is_bracket(current, settings):
            runs.append(current)
        current = [photo]
    if _is_bracket(current, settings):
        runs.append(current)
    return runs


def _base_frame(run):
    """The frame a bracket is centred on: the middle rung of its EV ladder.

    Chosen by position rather than by score. The base is a property of how the
    set was shot, not of how the frames came out -- picking the best-scoring one
    would reintroduce exactly the arbitrariness this pass exists to remove.
    """
    return sorted(run, key=lambda p: p['ev'])[len(run) // 2]


def _load_photos(conn):
    """Every photo that can carry an EV, in capture order."""
    rows = conn.execute(
        "SELECT path, date_taken, camera_model, f_stop, shutter_speed, iso, phash "
        "FROM photos WHERE date_taken IS NOT NULL ORDER BY date_taken, path"
    ).fetchall()
    photos = []
    for row in rows:
        ev = exposure_value(row['f_stop'], row['shutter_speed'], row['iso'])
        if ev is None:
            continue
        captured_at = parse_date(row['date_taken'])
        if captured_at is None:
            continue
        photos.append({
            'path': row['path'],
            'camera_model': row['camera_model'],
            'phash': row['phash'],
            'captured_at': captured_at,
            'ev': ev,
        })
    return photos


def _wholly_bracketed_groups(conn):
    """Burst groups whose members are exactly one bracket.

    The condition a promotion is made under, so asking it before and after a
    relabel says which groups were centred on a base frame and which still are.
    A group that merely *contains* a bracket was never promoted -- its lead stays
    where scoring put it -- so answering that with "any member is bracketed"
    would demote a group nothing had touched, every re-run.
    """
    return {
        row['burst_group_id'] for row in conn.execute(
            "SELECT burst_group_id, COUNT(*) AS members, "
            "       COUNT(DISTINCT sequence_group_id) AS sequences, "
            "       SUM(CASE WHEN sequence_kind = ? THEN 1 ELSE 0 END) AS bracketed "
            "FROM photos WHERE burst_group_id IS NOT NULL "
            "GROUP BY burst_group_id HAVING sequences = 1 AND bracketed = members",
            (BRACKET,),
        ).fetchall()
    }


def _restore_scored_lead(conn, burst_group_id):
    """Give a burst group back the lead scoring would have chosen for it.

    Candidates are read in capture order, the order `process_bursts` builds its
    own list in, so a group whose frames tie on every scored term resolves to
    the same frame a rescan would have picked rather than to whatever the table
    happened to return first.
    """
    members = [dict(row) for row in conn.execute(
        "SELECT path, aggregate, face_count, eyes_open_score, expression_score, "
        "       tech_sharpness, learned_score "
        "FROM photos WHERE burst_group_id = ? ORDER BY date_taken, path",
        (burst_group_id,),
    ).fetchall()]
    conn.execute(
        "UPDATE photos SET is_burst_lead = CASE WHEN path = ? THEN 1 ELSE 0 END "
        "WHERE burst_group_id = ?",
        (pick_lead(members)['path'], burst_group_id),
    )


def _promote_bracket_leads(conn, previously_promoted=frozenset()):
    """Point `is_burst_lead` at the base frame of every wholly-bracketed burst.

    Only touches burst groups whose members are exactly one bracket. Where a
    burst mixes a bracket with other frames the lead stays where scoring put it:
    there the competing takes are real, and the base frame has no claim to
    represent them.

    A group this pass no longer recognises as a bracket -- corrected EXIF, a
    tightened threshold -- has its scored lead restored. Leaving the earlier
    promotion in place would keep pointing "best of burst" at a frame nothing
    now says is the base, and only a full rescan would ever correct it.
    """
    still_bracketed = _wholly_bracketed_groups(conn)
    promoted = 0
    for group_id in sorted(still_bracketed):
        base = conn.execute(
            "SELECT path FROM photos WHERE burst_group_id = ? "
            "ORDER BY ABS(COALESCE(sequence_ev_offset, 0)), path LIMIT 1",
            (group_id,),
        ).fetchone()
        if base is None:
            continue
        conn.execute(
            "UPDATE photos SET is_burst_lead = CASE WHEN path = ? THEN 1 ELSE 0 END "
            "WHERE burst_group_id = ?",
            (base['path'], group_id),
        )
        promoted += 1
    lapsed = sorted(previously_promoted - still_bracketed)
    for group_id in lapsed:
        _restore_scored_lead(conn, group_id)
    return promoted, len(lapsed)


def detect_sequences(db_path, config_path=None):
    """Label exposure brackets across the library and centre each on its base frame.

    Always a whole-library pass: a run is defined by its chronological
    neighbours, so a photo cannot be classified without them and there is no
    honest incremental form. It is cheap enough not to need one -- pure
    arithmetic over stored columns, no image decode and no model.

    Args:
        db_path: Path to the SQLite database
        config_path: Path to scoring_config.json (optional)
    """
    from config import ScoringConfig

    settings = dict(DEFAULTS)
    settings.update(ScoringConfig(config_path, validate=False).get_sequence_detection_settings())
    if not settings.get('enabled', True):
        logger.info("Sequence detection disabled in config.")
        return

    with sqlite3.connect(db_path) as conn:
        apply_pragmas(conn)
        conn.row_factory = sqlite3.Row
        photos = _load_photos(conn)
        if not photos:
            logger.info("No photos with a usable exposure triplet found.")
            return

        logger.info(
            "Sequence detection over %d photos (gap<=%ss, phash<=%d, >=%d frames, "
            "step>=%.2f stops, span>=%.2f, step spread<=%.2f)...",
            len(photos), settings['max_gap_seconds'], settings['max_hamming'],
            settings['min_frames'], settings['min_step_stops'],
            settings['min_span_stops'], settings['step_tolerance_stops'],
        )

        runs = _find_bracket_runs(photos, settings)

        previously_promoted = _wholly_bracketed_groups(conn)
        # Scoped to this pass's own kind. Clearing every labelled row would wipe
        # the panorama pass's labels on each bracket run, and vice versa: the two
        # passes share these columns but own disjoint sets of rows.
        conn.execute(
            "UPDATE photos SET sequence_group_id = NULL, sequence_kind = NULL, "
            "sequence_ev_offset = NULL WHERE sequence_kind = ?",
            (BRACKET,),
        )
        # Numbered from 1 within this kind; see the module docstring on why the
        # set identity is (sequence_kind, sequence_group_id) and not the id alone.
        for group_id, run in enumerate(runs, start=1):
            base_ev = _base_frame(run)['ev']
            conn.executemany(
                "UPDATE photos SET sequence_group_id = ?, sequence_kind = ?, "
                "sequence_ev_offset = ? WHERE path = ?",
                [(group_id, BRACKET, _compensation_offset(base_ev, p['ev']), p['path']) for p in run],
            )

        promoted, demoted = _promote_bracket_leads(conn, previously_promoted)
        conn.commit()

    framed = sum(len(r) for r in runs)
    logger.info(
        "Found %d bracket sets (%d frames); re-centred %d burst groups on their base frame, "
        "handed %d back to scoring", len(runs), framed, promoted, demoted)
    return {'sets': len(runs), 'frames': framed, 'promoted': promoted, 'demoted': demoted}
