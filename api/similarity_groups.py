"""Similarity group computation using CLIP/SigLIP embeddings."""

import logging
import time
import json
import numpy as np
from collections import defaultdict

from api.database import get_db_connection
from utils.embedding import bytes_to_normalized_embedding, filter_uniform_embeddings
from utils.union_find import UnionFind

logger = logging.getLogger(__name__)


def _get_similarity_config():
    """Read similarity_groups settings from scoring_config.json."""
    try:
        from api.config import _FULL_CONFIG
        sg = _FULL_CONFIG.get('similarity_groups', {})
        return {
            'default_threshold': sg.get('default_threshold', 0.85),
            'min_group_size': sg.get('min_group_size', 2),
            'max_photos': sg.get('max_photos', 10000),
            'max_group_size': sg.get('max_group_size', 50),
        }
    except Exception:
        return {'default_threshold': 0.85, 'min_group_size': 2, 'max_photos': 10000, 'max_group_size': 50}


def compute_similarity_groups(conn=None, threshold=None, min_size=None, user_id=None):
    """
    Compute groups of visually similar photos using stored CLIP/SigLIP embeddings.

    Uses cosine similarity on embeddings, then connected components to form groups.
    Results cached in stats_cache table with TTL.

    Args:
        conn: SQLite connection (creates one if None)
        threshold: Minimum cosine similarity to consider photos as similar (0.0-1.0).
                   Defaults to scoring_config similarity_groups.default_threshold.
        min_size: Minimum group size. Defaults to scoring_config similarity_groups.min_group_size.
        user_id: Optional user ID for visibility filtering in multi-user mode.

    Returns:
        List of groups, each: { paths: [...], best_path: str, count: int }
    """
    from api.db_helpers import get_visibility_clause

    sg_config = _get_similarity_config()
    if threshold is None:
        threshold = sg_config['default_threshold']
    if min_size is None:
        min_size = sg_config['min_group_size']
    max_photos = sg_config['max_photos']
    max_group_size = sg_config['max_group_size']
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    try:
        vis_sql, vis_params = get_visibility_clause(user_id)

        # Check cache first
        cache_key = f"similarity_groups_{threshold}_{min_size}_{user_id}_10k"
        cached = conn.execute(
            "SELECT value, updated_at FROM stats_cache WHERE key = ?",
            (cache_key,)
        ).fetchone()
        if cached and (time.time() - cached['updated_at']) < 3600:  # 1 hour TTL
            try:
                return json.loads(cached['value'])
            except (json.JSONDecodeError, TypeError):
                pass  # Cache corrupted, recompute

        # Load embeddings — cap for performance (O(n²) computation)
        # Exclude burst non-leads to avoid overlap with burst culling
        # Exclude similarity_reviewed photos so reviewed groups don't reappear
        rows = conn.execute(
            f"""SELECT path, clip_embedding, aggregate FROM photos
               WHERE clip_embedding IS NOT NULL
                 AND (is_burst_lead = 1 OR is_burst_lead IS NULL)
                 AND (similarity_reviewed IS NULL OR similarity_reviewed = 0)
                 AND {vis_sql}
               ORDER BY date_taken DESC
               LIMIT ?""",
            vis_params + [max_photos]
        ).fetchall()

        if len(rows) < 2:
            return []

        paths = [r['path'] for r in rows]
        aggregates = {r['path']: r['aggregate'] or 0 for r in rows}

        # Parse embeddings
        embeddings = []
        valid_indices = []
        for i, row in enumerate(rows):
            emb = bytes_to_normalized_embedding(row['clip_embedding'])
            if emb is not None:
                embeddings.append(emb)
                valid_indices.append(i)

        # Filter to uniform embedding dimension (CLIP 768 vs SigLIP 1152)
        embeddings, valid_indices = filter_uniform_embeddings(embeddings, valid_indices)

        if len(embeddings) < 2:
            return []

        emb_matrix = np.stack(embeddings)
        valid_paths = [paths[i] for i in valid_indices]

        # Compute cosine similarity matrix (chunked to avoid OOM for large datasets)
        n = len(emb_matrix)

        # Union-Find for connected components
        uf = UnionFind(n)

        # Compute similarities in chunks
        chunk_size = 500
        for i in range(0, n, chunk_size):
            chunk = emb_matrix[i:i+chunk_size]
            sims = chunk @ emb_matrix.T  # (chunk_size, n)
            for ci in range(len(chunk)):
                for j in range(i + ci + 1, n):
                    if sims[ci, j] >= threshold:
                        uf.union(i + ci, j)

        # Build groups
        groups_map = defaultdict(list)
        for idx in range(n):
            groups_map[uf.find(idx)].append(valid_paths[idx])

        groups = []
        for group_paths in groups_map.values():
            if min_size <= len(group_paths) <= max_group_size:
                best_path = max(group_paths, key=lambda p: aggregates.get(p, 0))
                groups.append({
                    'paths': group_paths,
                    'best_path': best_path,
                    'count': len(group_paths),
                })

        groups.sort(key=lambda g: g['count'], reverse=True)

        # Cache results
        try:
            conn.execute(
                "INSERT OR REPLACE INTO stats_cache (key, value, updated_at) VALUES (?, ?, ?)",
                (cache_key, json.dumps(groups), time.time())
            )
            conn.commit()
        except Exception as e:
            logger.debug("Failed to cache similarity groups: %s", e)

        return groups
    finally:
        if close_conn:
            conn.close()
