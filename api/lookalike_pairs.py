"""Look-alike pairs: a second look at near-duplicates the grouped feeds never put side by side.

The Burst and Similar feeds cluster photos, and skip anything already reviewed or folded into a
burst, so a new shot that resembles an earlier keeper never meets it. This module scores PAIRS
instead, from three signals (how alike the pictures look, near-identical file content, and how
close in time they were taken), so each result is one comparison a person can judge at a glance.
"""

import json
import logging
import math
import sqlite3
import time

import numpy as np

from api.similarity_groups import _candidate_fingerprint
from db.stats_cache import cache_stats_best_effort
from utils.date_utils import parse_date
from utils.embedding import bytes_to_normalized_embedding, filter_uniform_embeddings

# Embedding cosine below this is never a look-alike, whatever the other signals say.
CANDIDATE_COSINE = 0.82
# Neighbours examined per photo: bounds the pair list on a library full of similar shots.
NEIGHBOURS = 5
# Neighbours kept per photo in the persisted lists, so rejecting a few still leaves NEIGHBOURS.
_STORED_NEIGHBOURS = 3 * NEIGHBOURS
_CACHE_TTL_SECONDS = 3600
MIN_CONFIDENCE = 0.30
# Visual dominates; the hash confirms re-saves and resizes; time lifts retakes.
_W_VISUAL, _W_HASH, _W_TIME = 0.60, 0.25, 0.15
_CHUNK = 500
# (date_taken, path) pairs per phash read: two binds each, under SQLite's 999-variable floor.
_PHASH_CHUNK = 400
# Within this gap two frames count as one moment; the time signal fades to zero at six hours.
_FULL_TIME_SECONDS, _ZERO_TIME_SECONDS = 60, 6 * 3600


def _clamp(value):
    return max(0.0, min(1.0, value))


def _hash_bits(text):
    try:
        return int(text, 16), len(text) * 4
    except (TypeError, ValueError):
        return None


def pair_signals(visual, a, b):
    """Score one pair; ``a`` and ``b`` are rows carrying phash, camera_model and date_taken.

    Returns the confidence (0-1) plus the evidence the card shows: ``hash`` is the perceptual-hash
    similarity (None when either photo has none), ``seconds_apart`` is None when a capture time is
    missing, and ``same_camera`` is None when a camera is unknown.
    """
    hash_similarity = None
    bits_a, bits_b = _hash_bits(a['phash']), _hash_bits(b['phash'])
    if bits_a and bits_b and bits_a[1] == bits_b[1]:
        hash_similarity = 1 - bin(bits_a[0] ^ bits_b[0]).count('1') / bits_a[1]
    taken_a, taken_b = parse_date(a['date_taken']), parse_date(b['date_taken'])
    seconds_apart = abs((taken_a - taken_b).total_seconds()) if taken_a and taken_b else None
    same_camera = (a['camera_model'] == b['camera_model']) if a['camera_model'] and b['camera_model'] else None

    time_score = 0.0
    if seconds_apart is not None and same_camera is not False:
        if seconds_apart <= _FULL_TIME_SECONDS:
            time_score = 1.0
        else:
            time_score = _clamp(1 - math.log(seconds_apart / _FULL_TIME_SECONDS)
                                / math.log(_ZERO_TIME_SECONDS / _FULL_TIME_SECONDS))
    confidence = (_W_VISUAL * _clamp((visual - 0.80) / 0.18)
                  + _W_HASH * (_clamp((hash_similarity - 0.80) / 0.15) if hash_similarity is not None else 0.0)
                  + _W_TIME * time_score)
    return {'confidence': confidence, 'visual': visual, 'hash': hash_similarity,
            'seconds_apart': seconds_apart, 'same_camera': same_camera}


def phash_sql(count):
    """Read ``phash`` for ``count`` (date_taken, path) rows through ``idx_date_asc_cover``.

    ``phash`` is stored right after the ~46 KB thumbnail BLOB, so selecting it in the candidate
    scan walked the overflow pages of every candidate row. Seeking the covering index on its
    leading (date_taken, path) reads it without touching the table.
    """
    values = ', '.join(['(?, ?)'] * count)
    return (f"WITH want(date_taken, path) AS (VALUES {values}) "
            "SELECT photos.path, photos.phash FROM want JOIN photos "
            "ON photos.date_taken IS want.date_taken AND photos.path = want.path")


def _read_phashes(conn, rows):
    """``{path: phash}`` for ``rows``, which carry ``path`` and ``date_taken``."""
    phashes = {}
    for start in range(0, len(rows), _PHASH_CHUNK):
        chunk = rows[start:start + _PHASH_CHUNK]
        params = [value for row in chunk for value in (row['date_taken'], row['path'])]
        phashes.update((r[0], r[1]) for r in conn.execute(phash_sql(len(chunk)), params))
    return phashes


logger = logging.getLogger(__name__)


def _neighbour_lists(matrix):
    """Each photo's closest neighbours at or above CANDIDATE_COSINE, as ``[j, cosine]``, closest first."""
    count = len(matrix)
    take = min(_STORED_NEIGHBOURS, count - 1)
    lists = []
    for start in range(0, count, _CHUNK):
        sims = matrix[start:start + _CHUNK] @ matrix.T
        for offset in range(len(sims)):
            sims[offset, start + offset] = -1.0
            top = np.argpartition(sims[offset], -take)[-take:]
            top = top[np.argsort(-sims[offset, top], kind='stable')]
            lists.append([[int(j), float(sims[offset, j])] for j in top if sims[offset, j] >= CANDIDATE_COSINE])
    return lists


def _cached_neighbour_lists(conn, cache_key, fingerprint, matrix):
    """The O(n^2) neighbour search, persisted in ``stats_cache`` for the exact candidate set.

    The lists are computed over every candidate, rejected or not, so a rejection (what each
    confirm writes) filters them per request instead of invalidating them.
    """
    cached = conn.execute("SELECT value, updated_at FROM stats_cache WHERE key = ?", (cache_key,)).fetchone()
    if cached and time.time() - cached['updated_at'] < _CACHE_TTL_SECONDS:
        try:
            payload = json.loads(cached['value'])
            if payload.get('fingerprint') == fingerprint and isinstance(payload.get('neighbours'), list):
                return payload['neighbours']
        except (json.JSONDecodeError, TypeError, AttributeError):
            pass  # Corrupted entry: recompute.
    lists = _neighbour_lists(matrix)
    try:
        cache_stats_best_effort(conn, [(cache_key, json.dumps({'fingerprint': fingerprint, 'neighbours': lists}))])
    except sqlite3.Error as e:
        logger.debug("Failed to cache look-alike neighbours: %s", e)
    return lists


def _neighbour_pairs(lists, excluded):
    """``{(i, j): cosine}`` from each kept photo's NEIGHBOURS closest kept neighbours."""
    pairs = {}
    for i, neighbours in enumerate(lists):
        if i in excluded:
            continue
        kept = [(j, cosine) for j, cosine in neighbours if j not in excluded][:NEIGHBOURS]
        for j, cosine in kept:
            pairs[(min(i, j), max(i, j))] = cosine
    return pairs


def compute_lookalike_pairs(conn, user_id, *, album_id=None, date_from=None, date_to=None,
                            max_photos=10000, limit=300):
    """Best-first look-alike pairs, each photo in at most one.

    Unlike the grouped feeds this reads photos that were already reviewed or sit inside a burst.
    A pair is left out when its frames share a burst or a bracket/panorama set, and when BOTH
    photos are already decided (reviewed, or explicitly kept, favourited or rated), because that
    is a comparison the person has already settled. A decided photo that meets an undecided one
    stays: that is the missed case. ``best_path`` prefers a decided photo, so a deliberate keeper
    starts out kept.
    """
    from api.db_helpers import album_filter_clause, get_visibility_clause, time_window_clauses
    from api.logical_collection import album_predicate
    from api.logical_culling import read_culling_labels, standalone_source

    vis_sql, vis_params = get_visibility_clause(user_id)
    window_clauses, window_params = time_window_clauses(date_from, date_to)
    logical = standalone_source(conn, user_id, extra=('clip_embedding', 'camera_model', 'date_taken',
                                                      'burst_reviewed'))
    album_sql, album_params = (album_filter_clause if logical is None else album_predicate)(album_id)
    from_sql, from_params = ('photos', []) if logical is None else (logical.sql, logical.params)
    where = ' AND '.join(['clip_embedding IS NOT NULL', vis_sql, album_sql, *window_clauses])
    rows = conn.execute(
        f"""SELECT path, clip_embedding, camera_model, date_taken, burst_group_id, burst_reviewed,
                   similarity_reviewed, sequence_kind, aggregate
            FROM {from_sql} WHERE {where} ORDER BY date_taken DESC LIMIT ?""",
        from_params + vis_params + album_params + window_params + [max_photos],
    ).fetchall()
    labels = read_culling_labels(conn, user_id, [r['path'] for r in rows], include_kept=True)

    embeddings, indices = [], []
    for i, row in enumerate(rows):
        embedding = bytes_to_normalized_embedding(row['clip_embedding'])
        if embedding is not None:
            embeddings.append(embedding)
            indices.append(i)
    embeddings, indices = filter_uniform_embeddings(embeddings, indices)
    if len(embeddings) < 2:
        return []
    photos = [rows[i] for i in indices]

    def decided(row):
        label = labels[row['path']]
        return bool(row['similarity_reviewed'] or row['burst_reviewed'] or label.kept or label.favorite or label.star)

    fingerprint = _candidate_fingerprint(
        rows, [CANDIDATE_COSINE, _STORED_NEIGHBOURS, max_photos, vis_sql, vis_params,
               album_sql, album_params, window_clauses, window_params, logical is not None])
    lists = _cached_neighbour_lists(
        conn, f"lookalike_neighbours_{user_id}_{album_id}_{date_from}_{date_to}", fingerprint, np.stack(embeddings))
    rejected = {i for i, row in enumerate(photos) if labels[row['path']].rejected}

    candidates = []
    for (i, j), cosine in _neighbour_pairs(lists, rejected).items():
        a, b = photos[i], photos[j]
        if a['burst_group_id'] is not None and a['burst_group_id'] == b['burst_group_id']:
            continue
        if a['sequence_kind'] or b['sequence_kind'] or (decided(a) and decided(b)):
            continue
        candidates.append((cosine, a, b))
    paired = {row['path']: row for _, a, b in candidates for row in (a, b)}
    phashes = _read_phashes(conn, list(paired.values()))

    scored = []
    for cosine, a, b in candidates:
        signals = pair_signals(cosine, {**dict(a), 'phash': phashes.get(a['path'])},
                               {**dict(b), 'phash': phashes.get(b['path'])})
        if signals['confidence'] < MIN_CONFIDENCE:
            continue
        keeper = a if (decided(a), a['aggregate'] or 0) >= (decided(b), b['aggregate'] or 0) else b
        earlier = [row['path'] for row in (a, b) if decided(row)]
        scored.append({**signals, 'paths': [a['path'], b['path']], 'best_path': keeper['path'],
                       'earlier_keeper': earlier[0] if earlier else None})

    scored.sort(key=lambda pair: (-pair['confidence'], pair['paths']))
    used, pairs = set(), []
    for pair in scored:
        if used.isdisjoint(pair['paths']):
            used.update(pair['paths'])
            pairs.append(pair)
            if len(pairs) == limit:
                break
    return pairs
