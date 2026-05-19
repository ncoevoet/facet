"""
Semantic text-to-image search router (async).

Uses CLIP/SigLIP embeddings to find photos matching a natural language query.
Fully migrated to aiosqlite per the R7 closure batch.
"""

import asyncio
import logging
import sqlite3
from typing import Optional

import numpy as np
from fastapi import APIRouter, Depends, Query, Request

from api.auth import CurrentUser, get_optional_user
from api.config import VIEWER_CONFIG
from api.database import get_async_db
from api.db_helpers import (
    get_visibility_clause, get_photos_from_clause,
    build_photo_select_columns,
    split_photo_tags, attach_person_data_async, format_date, sanitize_float_values,
)
from db.connection import HAS_SQLITE_VEC

router = APIRouter(tags=["search"])
logger = logging.getLogger(__name__)

_text_encoder = None
_embedding_cache = None  # numpy fallback: {'matrix': np.array, 'paths': list, 'count': int}

# Split-TTL availability tracking.
#
# Why split: a uniform 5-min TTL pins False after a single transient failure,
# so the multi-second NumPy fallback runs for 5 minutes even if sqlite-vec
# recovered immediately. Splitting lets successful state stay cached cheaply
# (no per-request probe overhead) while failed state gets re-checked
# aggressively so recovery is detected quickly.
_VEC_SUCCESS_TTL = 300  # 5 min — once known good, no need to re-probe often
_VEC_FAILURE_TTL = 30   # 30 s — once failing, re-probe quickly to catch recovery
_vec_available = None
_vec_success_checked_at = 0.0
_vec_failure_checked_at = 0.0

_FTS_SUCCESS_TTL = 300
_FTS_FAILURE_TTL = 30
_fts_available = None
_fts_success_checked_at = 0.0
_fts_failure_checked_at = 0.0

# Fallback counters — observable via /metrics. Incremented when the NumPy
# fallback path runs instead of sqlite-vec, or when the FTS5 query throws
# OperationalError and returns empty. An operator seeing these climb in
# production has the signal that the intended fast path is silently degraded.
_search_vec_fallback_total = 0
_search_fts_skip_total = 0


async def _check_vec_available(conn):
    """Check if sqlite-vec extension is loaded and photos_vec is populated.

    Caches True for 5 min (cheap re-use), re-probes False every 30 s
    (limits the fallback-pinned window after a transient failure).
    Emits a single WARN on True→False transition; subsequent failures
    within the TTL window are silent so logs don't flood.
    """
    import time
    global _vec_available, _vec_success_checked_at, _vec_failure_checked_at
    now = time.monotonic()
    if _vec_available is True and (now - _vec_success_checked_at) < _VEC_SUCCESS_TTL:
        return True
    if _vec_available is False and (now - _vec_failure_checked_at) < _VEC_FAILURE_TTL:
        return False

    previous = _vec_available

    if not HAS_SQLITE_VEC:
        _vec_available = False
        _vec_failure_checked_at = now
        if previous is True:
            logger.warning("sqlite-vec became unavailable — falling back to NumPy")
        return False

    try:
        cur = await conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='photos_vec'"
        )
        row = await cur.fetchone()
        await cur.close()
        if not row or row[0] == 0:
            _vec_available = False
            _vec_failure_checked_at = now
            if previous is True:
                logger.warning(
                    "sqlite-vec became unavailable (photos_vec missing) — falling back to NumPy"
                )
            return False
        cur = await conn.execute("SELECT 1 FROM photos_vec LIMIT 1")
        exists = await cur.fetchone()
        await cur.close()
        if exists is not None:
            _vec_available = True
            _vec_success_checked_at = now
            if previous is False:
                logger.info("sqlite-vec recovered — /api/search now using vec0 KNN")
            return True
        _vec_available = False
        _vec_failure_checked_at = now
        if previous is True:
            logger.warning(
                "sqlite-vec became unavailable (photos_vec empty) — falling back to NumPy"
            )
        return False
    except sqlite3.Error:
        _vec_available = False
        _vec_failure_checked_at = now
        if previous is True:
            logger.warning(
                "sqlite-vec became unavailable (query error) — falling back to NumPy",
                exc_info=True,
            )
        return False


def _load_text_encoder():
    """Load and cache the text encoder matching the VRAM profile."""
    global _text_encoder
    if _text_encoder is not None:
        return _text_encoder

    import torch
    from config.scoring_config import ScoringConfig

    config = ScoringConfig(validate=False)
    config.check_vram_profile_compatibility(verbose=False)
    clip_config = config.get_clip_config()

    from utils.device import get_device
    device = get_device()
    backend = clip_config.get('backend', 'open_clip')
    model_name = clip_config.get('model_name')

    if backend == 'transformers':
        from transformers import AutoModel, AutoTokenizer
        logger.info(f"Loading SigLIP text encoder: {model_name}")
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = AutoModel.from_pretrained(model_name, torch_dtype=torch.float32).to(device)
        model.eval()
        _text_encoder = {
            'backend': 'transformers',
            'model': model,
            'tokenizer': tokenizer,
            'device': device,
        }
    else:
        import open_clip
        pretrained = clip_config.get('pretrained', 'openai')
        logger.info(f"Loading CLIP text encoder: {model_name}")
        model, _, _ = open_clip.create_model_and_transforms(model_name, pretrained=pretrained, device=device)
        model.eval()
        tokenizer = open_clip.get_tokenizer(model_name)
        _text_encoder = {
            'backend': 'open_clip',
            'model': model,
            'tokenizer': tokenizer,
            'device': device,
        }

    return _text_encoder


def _encode_text(query: str) -> np.ndarray:
    """Encode a single text query into a normalized embedding vector (1D)."""
    return _encode_texts([query])[0]


def _encode_texts(queries: list[str]) -> np.ndarray:
    """Encode a batch of text queries into normalized embeddings.

    Returns a (N, D) float32 array, L2-normalized along the last axis.
    """
    import torch

    enc = _load_text_encoder()

    with torch.no_grad():
        if enc['backend'] == 'transformers':
            inputs = enc['tokenizer'](list(queries), padding=True, return_tensors="pt").to(enc['device'])
            text_features = enc['model'].get_text_features(**inputs)
            if not isinstance(text_features, torch.Tensor):
                text_features = text_features.pooler_output
        else:
            tokens = enc['tokenizer'](list(queries)).to(enc['device'])
            text_features = enc['model'].encode_text(tokens)

        text_features = text_features / text_features.norm(dim=-1, keepdim=True)
        return text_features.cpu().numpy().astype(np.float32)


async def _search_vec(conn, text_emb, limit, threshold, vis_sql, vis_params):
    """KNN search via sqlite-vec, filtered by visibility (async).

    sqlite-vec vec_distance_cosine returns distance (0 = identical, 2 = opposite).
    Similarity = 1 - distance.
    """
    # sqlite-vec MATCH queries don't support WHERE clauses directly,
    # so we fetch more candidates and post-filter by visibility
    k = min(limit * 4, 1000)
    query_bytes = text_emb.tobytes()

    cur = await conn.execute(
        '''
        SELECT v.path, v.distance
        FROM photos_vec v
        WHERE v.embedding MATCH ? AND k = ?
        ''',
        [query_bytes, k]
    )
    rows = await cur.fetchall()
    await cur.close()

    if not rows:
        return {}

    # Post-filter by visibility and threshold
    candidate_paths = [r['path'] for r in rows]
    candidate_dist = {r['path']: r['distance'] for r in rows}

    if vis_sql != '1=1':
        placeholders = ','.join(['?'] * len(candidate_paths))
        cur = await conn.execute(
            f"SELECT path FROM photos WHERE path IN ({placeholders}) AND {vis_sql}",
            candidate_paths + vis_params
        )
        visible = await cur.fetchall()
        await cur.close()
        visible_paths = {r['path'] for r in visible}
    else:
        visible_paths = set(candidate_paths)

    scores = {}
    for path in candidate_paths:
        if path not in visible_paths:
            continue
        similarity = 1.0 - candidate_dist[path]
        if similarity >= threshold:
            scores[path] = similarity
        if len(scores) >= limit:
            break

    return scores


async def _load_embedding_matrix(conn, vis_sql, vis_params, user_id):
    """Fallback: load all photo embeddings into a numpy matrix (async)."""
    global _embedding_cache
    from utils.embedding import bytes_to_normalized_embedding, filter_uniform_embeddings

    cur = await conn.execute(
        f"SELECT COUNT(*) FROM photos WHERE clip_embedding IS NOT NULL AND {vis_sql}",
        vis_params
    )
    row = await cur.fetchone()
    await cur.close()
    count = row[0] if row else 0

    if _embedding_cache and _embedding_cache['count'] == count and _embedding_cache['user_id'] == user_id:
        return _embedding_cache['matrix'], _embedding_cache['paths']

    cur = await conn.execute(
        f"SELECT path, clip_embedding FROM photos WHERE clip_embedding IS NOT NULL AND {vis_sql}",
        vis_params
    )
    rows = await cur.fetchall()
    await cur.close()

    # Numpy work below is CPU-bound — push it off the event loop. For 100k photos
    # this can be ~50ms which is meaningful at moderate concurrency.
    def _build_matrix(rows):
        paths_ = []
        embeddings_ = []
        for r in rows:
            emb = bytes_to_normalized_embedding(r['clip_embedding'])
            if emb is not None:
                paths_.append(r['path'])
                embeddings_.append(emb)
        embeddings_, paths_ = filter_uniform_embeddings(embeddings_, paths_)
        if not embeddings_:
            return None, []
        return np.stack(embeddings_, axis=0), paths_

    matrix, paths = await asyncio.to_thread(_build_matrix, rows)
    if matrix is None:
        _embedding_cache = None
        return None, []

    _embedding_cache = {'matrix': matrix, 'paths': paths, 'count': count, 'user_id': user_id}
    return matrix, paths


async def _search_numpy(conn, text_emb, limit, threshold, vis_sql, vis_params, user_id):
    """Fallback: brute-force cosine similarity search via NumPy (async)."""
    matrix, paths = await _load_embedding_matrix(conn, vis_sql, vis_params, user_id)
    if matrix is None or len(paths) == 0:
        return {}

    if text_emb.shape[0] != matrix.shape[1]:
        return {}

    # Matmul is CPU-bound; offload from event loop.
    def _compute():
        similarities = matrix @ text_emb
        mask = similarities >= threshold
        if not mask.any():
            return {}
        indices = np.where(mask)[0]
        top_indices = indices[np.argsort(-similarities[indices])[:limit]]
        return {paths[i]: float(similarities[i]) for i in top_indices}

    return await asyncio.to_thread(_compute)


async def _has_fts(conn):
    """Check if the photos_fts table exists, split-TTL cached.

    Caches True for 5 min, False for 30 s. Emits a single WARN on
    True→False transition so the first failure is loud.
    """
    import time
    global _fts_available, _fts_success_checked_at, _fts_failure_checked_at
    now = time.monotonic()
    if _fts_available is True and (now - _fts_success_checked_at) < _FTS_SUCCESS_TTL:
        return True
    if _fts_available is False and (now - _fts_failure_checked_at) < _FTS_FAILURE_TTL:
        return False

    previous = _fts_available

    try:
        cur = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='photos_fts'"
        )
        row = await cur.fetchone()
        await cur.close()
        if row is not None:
            _fts_available = True
            _fts_success_checked_at = now
            if previous is False:
                logger.info("photos_fts table recovered — BM25 text search re-enabled")
            return True
        _fts_available = False
        _fts_failure_checked_at = now
        if previous is True:
            logger.warning("photos_fts table missing — text search will skip BM25")
        return False
    except sqlite3.OperationalError:
        _fts_available = False
        _fts_failure_checked_at = now
        if previous is True:
            logger.warning(
                "photos_fts query error — text search will skip BM25",
                exc_info=True,
            )
        return False


async def _fts_search(conn, query, limit):
    """Run FTS5 search and return {path: normalized_score} dict (async).

    BM25 rank values are negative (lower = better match).
    Scores are normalized to 0..1 range relative to the best match.
    """
    try:
        cur = await conn.execute(
            "SELECT path, rank FROM photos_fts WHERE photos_fts MATCH ? "
            "ORDER BY rank LIMIT ?",
            (query, limit)
        )
        rows = await cur.fetchall()
        await cur.close()
    except sqlite3.OperationalError:
        global _search_fts_skip_total
        _search_fts_skip_total += 1
        return {}

    if not rows:
        return {}

    best_rank = rows[0]['rank']
    worst_rank = rows[-1]['rank'] if len(rows) > 1 else best_rank - 1.0

    scores = {}
    for row in rows:
        if best_rank == worst_rank:
            normalized = 1.0
        else:
            normalized = (worst_rank - row['rank']) / (worst_rank - best_rank)
        scores[row['path']] = normalized

    return scores


@router.get("/api/search")
async def api_search(
    request: Request,
    q: str = Query(..., min_length=1, max_length=500),
    limit: int = Query(50, ge=1, le=200),
    threshold: float = Query(0.15, ge=0.0, le=1.0),
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Semantic text-to-image search using CLIP/SigLIP cosine similarity (async).

    Text encoding (`_encode_text`) is a synchronous GPU/CPU call; we run it in
    a worker thread so it never blocks the event loop. All DB I/O uses
    aiosqlite via get_async_db().
    """
    if not VIEWER_CONFIG.get('features', {}).get('show_semantic_search', True):
        return {'photos': [], 'total': 0, 'query': q, 'error': 'Semantic search is disabled'}

    try:
        async with get_async_db() as conn:
            user_id = user.user_id if user else None
            vis_sql, vis_params = get_visibility_clause(user_id)
            from_clause, from_params = get_photos_from_clause(user_id)
            # build_photo_select_columns(conn=None) reads the lifespan-warmed
            # cache, safe to call from this aiosqlite context.
            select_cols = build_photo_select_columns(conn=None, user_id=user_id)

            embedding_scores: dict[str, float] = {}
            fts_scores: dict[str, float] = {}

            # --- FTS5 text search ---
            if await _has_fts(conn):
                fts_scores = await _fts_search(conn, q, limit)

            # --- Embedding-based search ---
            # Text encoding is GPU/CPU work — push to a worker thread so the
            # event loop stays responsive during the typically 5-30ms encode.
            text_emb = await asyncio.to_thread(_encode_text, q)

            if await _check_vec_available(conn):
                embedding_scores = await _search_vec(conn, text_emb, limit, threshold, vis_sql, vis_params)
            else:
                global _search_vec_fallback_total
                _search_vec_fallback_total += 1
                embedding_scores = await _search_numpy(conn, text_emb, limit, threshold, vis_sql, vis_params, user_id)

            # --- Merge results ---
            # Embedding weight 0.7, FTS weight 0.3
            all_paths = set(embedding_scores) | set(fts_scores)
            sim_by_path = {}
            for path in all_paths:
                emb_score = embedding_scores.get(path, 0.0)
                fts_score = fts_scores.get(path, 0.0)
                sim_by_path[path] = emb_score * 0.7 + fts_score * 0.3

            if not sim_by_path:
                return {'photos': [], 'total': 0, 'query': q}

            # Keep only the top results after merging
            if len(sim_by_path) > limit:
                top_paths = sorted(sim_by_path, key=sim_by_path.get, reverse=True)[:limit]
                sim_by_path = {p: sim_by_path[p] for p in top_paths}

            # Fetch full photo data for all matching paths
            matching_paths = list(sim_by_path.keys())
            placeholders = ','.join(['?'] * len(matching_paths))
            cur = await conn.execute(
                f"SELECT {', '.join(select_cols)} FROM {from_clause} "
                f"WHERE photos.path IN ({placeholders})",
                from_params + matching_paths
            )
            rows = await cur.fetchall()
            await cur.close()

            tags_limit = VIEWER_CONFIG['display']['tags_per_photo']
            photos = split_photo_tags(rows, tags_limit)
            for photo in photos:
                photo['date_formatted'] = format_date(photo.get('date_taken'))
                photo['similarity'] = round(sim_by_path.get(photo['path'], 0), 4)

            await attach_person_data_async(photos, conn)

            # Sort by similarity (descending)
            photos.sort(key=lambda p: p.get('similarity', 0), reverse=True)

            sanitize_float_values(photos)

            return {
                'photos': photos,
                'total': len(photos),
                'query': q,
            }

    except Exception:
        logger.exception("Semantic search failed for query: %s", q)
        return {'photos': [], 'total': 0, 'query': q, 'error': 'Search failed'}
