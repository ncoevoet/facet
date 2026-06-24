"""
Pair selection strategies for pairwise photo comparison.
"""

import random
from typing import Optional, Dict

from db import DEFAULT_DB_PATH, get_connection


class PairSelector:
    """Selects pairs of photos for human comparison using various strategies."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH, candidate_pool_size: int = 200):
        self.db_path = db_path
        self.candidate_pool_size = candidate_pool_size

    def get_next_pair(
        self,
        strategy: str = 'learning',
        category: Optional[str] = None,
        exclude_compared: bool = True
    ) -> Optional[Dict]:
        """
        Select the next pair of photos for comparison.

        Args:
            strategy: Selection strategy - 'learning', 'uncertainty', 'boundary',
                'active', 'random'
            category: Filter photos by category (e.g., 'portrait', 'others')
            exclude_compared: Skip pairs that have already been compared

        Returns:
            Dict with 'a' and 'b' photo paths, or None if no pairs available
        """
        strategies = {
            'learning': self._select_learning_value,
            'uncertainty': self._select_uncertainty,
            'boundary': self._select_boundary,
            'active': self._select_active_learning,
            'random': self._select_random,
        }

        selector = strategies.get(strategy, self._select_learning_value)
        return selector(category, exclude_compared)

    def _select_learning_value(
        self,
        category: Optional[str],
        exclude_compared: bool
    ) -> Optional[Dict]:
        """Select the pair with the highest learning value.

        The ranker trains on ``[embedding + metric_vector]``, so score-adjacent
        photos (what ``uncertainty`` picks) are near-duplicates in feature space
        and add almost no gradient. Instead:

        - Cold start (no ``learned_scores`` yet): prefer embedding-distant pairs,
          so each comparison covers new feature-space territory.
        - Warm (ranker trained): prefer pairs whose ``aggregate`` ordering
          disagrees with their ``learned_score`` ordering — the pairs the current
          model would get wrong, i.e. maximum information.

        Stays O(pool) by sampling a bounded set of pairs within a random
        candidate pool and choosing stochastically by weight (so it never
        degenerates into always the same extreme pair). Falls back to the
        ``uncertainty`` strategy when embeddings are unavailable.
        """
        import numpy as np

        from utils.embedding import bytes_to_normalized_embedding

        with get_connection(self.db_path) as conn:
            compared_pairs = self._get_compared_pairs(conn) if exclude_compared else set()

            learned_where = "WHERE learned_score IS NOT NULL"
            learned_params = []
            if category:
                learned_where += " AND category = ?"
                learned_params.append(category)
            learned = {
                row[0]: row[1] for row in conn.execute(
                    f"SELECT photo_path, learned_score FROM learned_scores {learned_where}",
                    learned_params,
                )
            }

            where_clause = "WHERE aggregate IS NOT NULL AND clip_embedding IS NOT NULL"
            params = []
            if category:
                where_clause += " AND category = ?"
                params.append(category)
            rows = conn.execute(
                f"SELECT path, aggregate, clip_embedding FROM photos {where_clause} "
                "ORDER BY RANDOM() LIMIT ?",
                params + [self.candidate_pool_size],
            ).fetchall()

        candidates = []
        for row in rows:
            emb = bytes_to_normalized_embedding(row['clip_embedding'])
            if emb is None:
                continue
            candidates.append({
                'path': row['path'], 'score': row['aggregate'],
                'emb': emb, 'learned': learned.get(row['path']),
            })

        if len(candidates) < 2:
            return self._select_uncertainty(category, exclude_compared)

        # A DB can hold mixed embedding dimensions (e.g. 768-dim CLIP and 1152-dim
        # SigLIP after a profile switch). np.dot on a mismatched pair raises, so
        # keep only the dominant dimension before any cosine math.
        from collections import Counter
        dominant_dim = Counter(c['emb'].shape[0] for c in candidates).most_common(1)[0][0]
        candidates = [c for c in candidates if c['emb'].shape[0] == dominant_dim]
        if len(candidates) < 2:
            return self._select_uncertainty(category, exclude_compared)

        warm = sum(1 for c in candidates if c['learned'] is not None) >= 2
        n = len(candidates)
        target = min(500, n * (n - 1) // 2)
        seen_idx = set()
        scored = []
        guard = 0
        while len(scored) < target and guard < target * 5:
            guard += 1
            i, j = random.sample(range(n), 2)
            key = (min(i, j), max(i, j))
            if key in seen_idx:
                continue
            seen_idx.add(key)
            a, b = candidates[i], candidates[j]
            if exclude_compared and tuple(sorted([a['path'], b['path']])) in compared_pairs:
                continue
            cos = float(np.dot(a['emb'], b['emb']))
            distance = 1.0 - cos  # 0 (identical) .. 2 (opposite)
            if warm and a['learned'] is not None and b['learned'] is not None:
                disagree = (a['score'] - b['score'] > 0) != (a['learned'] - b['learned'] > 0)
                weight = (2.0 if disagree else 0.5) + distance
            else:
                weight = distance
            scored.append((max(weight, 1e-6), a, b))

        if not scored:
            return self._select_uncertainty(category, exclude_compared)

        total = sum(w for w, _, _ in scored)
        threshold = random.uniform(0, total)
        acc = 0.0
        chosen = scored[-1]
        for entry in scored:
            acc += entry[0]
            if acc >= threshold:
                chosen = entry
                break
        _, a, b = chosen
        return {'a': a['path'], 'b': b['path'], 'score_a': a['score'], 'score_b': b['score']}

    def _get_compared_pairs(self, conn) -> set:
        """Get set of already-compared pairs (normalized as tuples)."""
        cursor = conn.execute("""
            SELECT photo_a_path, photo_b_path FROM comparisons
        """)
        pairs = set()
        for row in cursor:
            # Normalize to (min, max) to avoid duplicate comparisons in reverse order
            pair = tuple(sorted([row[0], row[1]]))
            pairs.add(pair)
        return pairs

    def _select_uncertainty(
        self,
        category: Optional[str],
        exclude_compared: bool
    ) -> Optional[Dict]:
        """
        Select pairs with similar aggregate scores (high uncertainty).

        Pairs with similar scores are harder to rank, so human input is most valuable.
        """
        with get_connection(self.db_path) as conn:
            compared_pairs = self._get_compared_pairs(conn) if exclude_compared else set()

            # Get photos with aggregate scores, ordered by score
            where_clause = "WHERE aggregate IS NOT NULL"
            params = []
            if category:
                where_clause += " AND category = ?"
                params.append(category)

            cursor = conn.execute(f"""
                SELECT path, aggregate FROM photos
                {where_clause}
                ORDER BY aggregate DESC
            """, params)

            photos = [(row['path'], row['aggregate']) for row in cursor]

            if len(photos) < 2:
                return None

            # Find pairs with smallest score difference
            best_pair = None
            best_diff = float('inf')

            # Sample adjacent pairs in sorted order (most similar scores)
            for i in range(len(photos) - 1):
                path_a, score_a = photos[i]
                path_b, score_b = photos[i + 1]

                # Skip if already compared
                normalized = tuple(sorted([path_a, path_b]))
                if exclude_compared and normalized in compared_pairs:
                    continue

                diff = abs(score_a - score_b)
                if diff < best_diff:
                    best_diff = diff
                    best_pair = {'a': path_a, 'b': path_b, 'score_a': score_a, 'score_b': score_b}

            return best_pair

    def _select_boundary(
        self,
        category: Optional[str],
        exclude_compared: bool
    ) -> Optional[Dict]:
        """
        Select pairs around the score boundary (6-8 range).

        These photos are in the "ambiguous" quality zone where scoring
        precision matters most.
        """
        with get_connection(self.db_path) as conn:
            compared_pairs = self._get_compared_pairs(conn) if exclude_compared else set()

            # Get photos in the 6-8 aggregate range
            where_clause = "WHERE aggregate BETWEEN 5.5 AND 8.5"
            params = []
            if category:
                where_clause += " AND category = ?"
                params.append(category)

            cursor = conn.execute(f"""
                SELECT path, aggregate FROM photos
                {where_clause}
                ORDER BY RANDOM()
                LIMIT 100
            """, params)

            photos = [(row['path'], row['aggregate']) for row in cursor]

            if len(photos) < 2:
                # Fallback to uncertainty selection
                return self._select_uncertainty(category, exclude_compared)

            # Try to find an uncomparied pair
            for _ in range(50):  # Max attempts
                idx_a, idx_b = random.sample(range(len(photos)), 2)
                path_a, score_a = photos[idx_a]
                path_b, score_b = photos[idx_b]

                normalized = tuple(sorted([path_a, path_b]))
                if not exclude_compared or normalized not in compared_pairs:
                    return {'a': path_a, 'b': path_b, 'score_a': score_a, 'score_b': score_b}

            return None

    def _select_active_learning(
        self,
        category: Optional[str],
        exclude_compared: bool
    ) -> Optional[Dict]:
        """
        Select photos with low comparison counts (active learning).

        Prioritizes photos that have been compared fewer times to ensure
        all photos contribute to the learned scores.
        """
        with get_connection(self.db_path) as conn:
            compared_pairs = self._get_compared_pairs(conn) if exclude_compared else set()

            # Get comparison counts per photo
            cursor = conn.execute("""
                SELECT photo_path, comparison_count FROM learned_scores
                ORDER BY comparison_count ASC
            """)
            comparison_counts = {row[0]: row[1] for row in cursor}

            # Get photos, prefer those with low comparison counts
            where_clause = "WHERE aggregate IS NOT NULL"
            params = []
            if category:
                where_clause += " AND category = ?"
                params.append(category)

            cursor = conn.execute(f"""
                SELECT path, aggregate FROM photos
                {where_clause}
            """, params)

            photos = [(row['path'], row['aggregate']) for row in cursor]

            if len(photos) < 2:
                return None

            # Sort by comparison count (ascending)
            photos_with_counts = [
                (path, score, comparison_counts.get(path, 0))
                for path, score in photos
            ]
            photos_with_counts.sort(key=lambda x: x[2])

            # Select from the least-compared photos
            candidates = photos_with_counts[:min(50, len(photos_with_counts))]

            for _ in range(50):
                idx_a, idx_b = random.sample(range(len(candidates)), 2)
                path_a, score_a, _ = candidates[idx_a]
                path_b, score_b, _ = candidates[idx_b]

                normalized = tuple(sorted([path_a, path_b]))
                if not exclude_compared or normalized not in compared_pairs:
                    return {'a': path_a, 'b': path_b, 'score_a': score_a, 'score_b': score_b}

            return None

    def _select_random(
        self,
        category: Optional[str],
        exclude_compared: bool
    ) -> Optional[Dict]:
        """
        Select a random pair of photos.
        """
        with get_connection(self.db_path) as conn:
            compared_pairs = self._get_compared_pairs(conn) if exclude_compared else set()

            where_clause = "WHERE aggregate IS NOT NULL"
            params = []
            if category:
                where_clause += " AND category = ?"
                params.append(category)

            cursor = conn.execute(f"""
                SELECT path, aggregate FROM photos
                {where_clause}
                ORDER BY RANDOM()
                LIMIT 100
            """, params)

            photos = [(row['path'], row['aggregate']) for row in cursor]

            if len(photos) < 2:
                return None

            for _ in range(50):
                idx_a, idx_b = random.sample(range(len(photos)), 2)
                path_a, score_a = photos[idx_a]
                path_b, score_b = photos[idx_b]

                normalized = tuple(sorted([path_a, path_b]))
                if not exclude_compared or normalized not in compared_pairs:
                    return {'a': path_a, 'b': path_b, 'score_a': score_a, 'score_b': score_b}

            return None
