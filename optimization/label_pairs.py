"""
Synthetic preference pairs from user ratings and favorites.

Star ratings, favorites and rejections are free training signal that the
pairwise weight optimizer cannot consume directly. This module materializes
them into the comparisons table with source='rating', preserving the ordinal
semantics (favorite beats rejected, 5 stars beat 3) without inventing a fake
cardinal target. Re-syncing is idempotent: all source='rating' rows are
derived data and get rebuilt from the current labels on every run.
"""

import logging
import random
import json

from db import get_connection

logger = logging.getLogger("facet.label_pairs")

SESSION_ID = 'rating-sync'

# Pair-generation rules, strongest signal first
MIN_STAR_GAP = 2          # skip adjacent-star pairs - too noisy
PER_PHOTO_CAP = 6         # max pairs any single photo participates in
DEFAULT_MAX_PAIRS = 2000  # global cap per sync run
RNG_SEED = 42


def _agent_left(conn, user_id):
    """``{path: (star_rating, is_favorite, is_rejected)}`` an assistant left for this scope."""
    return {r[0]: (r[1], r[2], r[3]) for r in conn.execute(
        "SELECT photo_path, star_rating, is_favorite, is_rejected FROM rating_provenance WHERE user_id = ?",
        (user_id or '',))}


def _fetch_labels(conn, user_id=None):
    """Load labeled photos: (path, category, star_rating, is_favorite, is_rejected).

    Single-user mode reads the photos columns; multi-user mode overlays
    user_preferences for the given user.
    """
    if user_id:
        rows = conn.execute(
            """SELECT p.path, p.category,
                      COALESCE(up.star_rating, 0) AS star_rating,
                      COALESCE(up.is_favorite, 0) AS is_favorite,
                      COALESCE(up.is_rejected, 0) AS is_rejected
               FROM photos p
               JOIN user_preferences up ON up.photo_path = p.path AND up.user_id = ?
               WHERE p.aggregate IS NOT NULL""",
            (user_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT path, category, COALESCE(star_rating, 0) AS star_rating,
                      COALESCE(is_favorite, 0) AS is_favorite,
                      COALESCE(is_rejected, 0) AS is_rejected
               FROM photos
               WHERE aggregate IS NOT NULL
                 AND (star_rating > 0 OR is_favorite = 1 OR is_rejected = 1)""",
        ).fetchall()
    left = _agent_left(conn, user_id)
    # A label an assistant left is not the user's taste; one the user changed since counts again.
    return [dict(r) for r in rows
            if left.get(r['path']) != (r['star_rating'] or 0, r['is_favorite'] or 0, r['is_rejected'] or 0)]


def generate_rating_pairs(conn, user_id=None, max_pairs=DEFAULT_MAX_PAIRS,
                          per_photo_cap=PER_PHOTO_CAP, rng_seed=RNG_SEED):
    """Generate (winner_path, loser_path, category) tuples from labels.

    Rules, in priority order, all within the same category:
    1. favorite > rejected (strongest signal)
    2. star s1 > star s2 where s1 - s2 >= MIN_STAR_GAP
    3. favorite > unlabeled same-category photo (sampled)

    Per-photo participation is capped so a handful of heavily-labeled photos
    can't dominate the synthetic set.
    """
    labels = _fetch_labels(conn, user_id)
    if not labels:
        return []

    rng = random.Random(rng_seed)
    by_category = {}
    for row in labels:
        by_category.setdefault(row['category'] or 'others', []).append(row)

    usage = {}
    pairs = []
    seen_pairs = set()

    def _try_add(winner, loser, category):
        key = tuple(sorted((winner, loser)))
        if winner == loser or key in seen_pairs:
            return True
        if len(pairs) >= max_pairs:
            return False
        if usage.get(winner, 0) >= per_photo_cap or usage.get(loser, 0) >= per_photo_cap:
            return True
        pairs.append((winner, loser, category))
        seen_pairs.add(key)
        usage[winner] = usage.get(winner, 0) + 1
        usage[loser] = usage.get(loser, 0) + 1
        return True

    for category, rows in sorted(by_category.items()):
        favorites = [r['path'] for r in rows if r['is_favorite']]
        rejected = [r['path'] for r in rows if r['is_rejected']]
        rated = [(r['path'], r['star_rating']) for r in rows
                 if r['star_rating'] and not r['is_rejected']]

        # Rule 1: favorite > rejected
        reject_head = 0
        for fav in favorites:
            for index in range(reject_head, len(rejected)):
                if usage.get(fav, 0) >= per_photo_cap:
                    break
                rej = rejected[index]
                if usage.get(rej, 0) >= per_photo_cap:
                    if index == reject_head:
                        reject_head += 1
                    continue
                if not _try_add(fav, rej, category):
                    return pairs
                if usage.get(rej, 0) >= per_photo_cap and index == reject_head:
                    reject_head += 1

        # Rule 2: clear star gaps
        rated_sorted = sorted(rated, key=lambda x: -x[1])
        buckets = {}
        for path, stars in rated_sorted:
            if usage.get(path, 0) < per_photo_cap:
                buckets.setdefault(stars, []).append(path)
        heads = dict.fromkeys(buckets, 0)
        for high_path, high_stars in rated_sorted:
            if usage.get(high_path, 0) >= per_photo_cap:
                continue
            for low_stars, candidates in buckets.items():
                if high_stars - low_stars < MIN_STAR_GAP:
                    continue
                index = heads[low_stars]
                while index < len(candidates) and usage.get(high_path, 0) < per_photo_cap:
                    low_path = candidates[index]
                    if usage.get(low_path, 0) < per_photo_cap:
                        if not _try_add(high_path, low_path, category):
                            return pairs
                    if usage.get(low_path, 0) >= per_photo_cap and index == heads[low_stars]:
                        heads[low_stars] += 1
                    index += 1

        # Rule 3: favorite > random unlabeled same-category photo
        if favorites:
            unlabeled = [r[0] for r in conn.execute(
                """SELECT path FROM photos
                   WHERE COALESCE(category, 'others') = ? AND aggregate IS NOT NULL
                     AND COALESCE(is_favorite, 0) = 0 AND COALESCE(is_rejected, 0) = 0
                     AND COALESCE(star_rating, 0) = 0
                   ORDER BY path LIMIT 500""",
                (category,),
            ).fetchall()]
            if unlabeled:
                for fav in favorites:
                    for loser in rng.sample(unlabeled, min(2, len(unlabeled))):
                        if not _try_add(fav, loser, category):
                            return pairs

    return pairs


def sync_label_comparisons(db_path, user_id=None, max_pairs=DEFAULT_MAX_PAIRS):
    """Rebuild source='rating' comparisons from current labels.

    Replaces only this owner's synthetic rows so retracted ratings disappear.
    Explicit votes and culling pairs in that scope take precedence, including
    the NULL owner where SQLite's UNIQUE constraint does not deduplicate.

    Returns:
        Number of comparison rows inserted
    """
    with get_connection(db_path) as conn:
        conn.execute('BEGIN IMMEDIATE')
        pairs = generate_rating_pairs(conn, user_id=user_id, max_pairs=max_pairs)
        candidates = {}
        for winner, loser, category in pairs:
            if winner == loser:
                continue
            a, b = sorted((winner, loser))
            # Generation rules run strongest first. Keep the first signal for
            # a pair instead of counting the same evidence several times.
            candidates.setdefault((a, b), (winner, category))
        protected = set()
        if candidates:
            protected = {tuple(row) for row in conn.execute(
                "SELECT c.photo_a_path,c.photo_b_path FROM comparisons c JOIN json_each(?) candidate "
                "ON c.photo_a_path=json_extract(candidate.value,'$[0]') "
                "AND c.photo_b_path=json_extract(candidate.value,'$[1]') "
                "WHERE c.user_id IS ? AND COALESCE(c.source,'vote') <> 'rating'",
                (json.dumps(list(candidates)), user_id))}
        conn.execute("DELETE FROM comparisons WHERE source = 'rating' AND user_id IS ?", (user_id,))
        before = conn.total_changes
        conn.executemany(
            """INSERT OR IGNORE INTO comparisons
               (photo_a_path, photo_b_path, winner, category, session_id, user_id, source)
               VALUES (?, ?, ?, ?, ?, ?, 'rating')""",
            [
                (a, b,
                 'a' if a == winner else 'b',
                 category, SESSION_ID, user_id)
                for (a, b), (winner, category) in candidates.items() if (a, b) not in protected
            ],
        )
        inserted = conn.total_changes - before
        conn.commit()
    logger.info("Synced %d rating-derived comparison pairs (from %d candidates)",
                inserted, len(pairs))
    return inserted
