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

from db import get_connection

logger = logging.getLogger("facet.label_pairs")

SESSION_ID = 'rating-sync'

# Pair-generation rules, strongest signal first
MIN_STAR_GAP = 2          # skip adjacent-star pairs - too noisy
PER_PHOTO_CAP = 6         # max pairs any single photo participates in
DEFAULT_MAX_PAIRS = 2000  # global cap per sync run
RNG_SEED = 42


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
    return [dict(r) for r in rows]


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

    def _try_add(winner, loser, category):
        if len(pairs) >= max_pairs:
            return False
        if usage.get(winner, 0) >= per_photo_cap or usage.get(loser, 0) >= per_photo_cap:
            return True
        pairs.append((winner, loser, category))
        usage[winner] = usage.get(winner, 0) + 1
        usage[loser] = usage.get(loser, 0) + 1
        return True

    for category, rows in sorted(by_category.items()):
        favorites = [r['path'] for r in rows if r['is_favorite']]
        rejected = [r['path'] for r in rows if r['is_rejected']]
        rated = [(r['path'], r['star_rating']) for r in rows
                 if r['star_rating'] and not r['is_rejected']]

        # Rule 1: favorite > rejected
        for fav in favorites:
            for rej in rejected:
                if not _try_add(fav, rej, category):
                    return pairs

        # Rule 2: clear star gaps
        rated_sorted = sorted(rated, key=lambda x: -x[1])
        for i, (high_path, high_stars) in enumerate(rated_sorted):
            for low_path, low_stars in rated_sorted[i + 1:]:
                if high_stars - low_stars < MIN_STAR_GAP:
                    continue
                if not _try_add(high_path, low_path, category):
                    return pairs

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

    Deletes previous synthetic rows first so retracted ratings disappear,
    then inserts the regenerated set with INSERT OR IGNORE - explicit votes
    and culling pairs on the same photo pair always take precedence.

    Returns:
        Number of comparison rows inserted
    """
    with get_connection(db_path) as conn:
        pairs = generate_rating_pairs(conn, user_id=user_id, max_pairs=max_pairs)
        conn.execute("DELETE FROM comparisons WHERE source = 'rating'")
        before = conn.total_changes
        conn.executemany(
            """INSERT OR IGNORE INTO comparisons
               (photo_a_path, photo_b_path, winner, category, session_id, user_id, source)
               VALUES (?, ?, ?, ?, ?, ?, 'rating')""",
            [
                (*sorted((winner, loser)),
                 'a' if sorted((winner, loser))[0] == winner else 'b',
                 category, SESSION_ID, user_id)
                for winner, loser, category in pairs
            ],
        )
        inserted = conn.total_changes - before
        conn.commit()
    logger.info("Synced %d rating-derived comparison pairs (from %d candidates)",
                inserted, len(pairs))
    return inserted
