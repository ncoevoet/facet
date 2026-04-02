"""
Semantic text-to-image search router.

Uses CLIP/SigLIP embeddings to find photos matching a natural language query.
"""

import logging
import sqlite3
from typing import Optional

import numpy as np
from fastapi import APIRouter, Depends, Query, Request

from api.auth import CurrentUser, get_optional_user
from api.config import VIEWER_CONFIG
from api.database import get_db_connection
from api.db_helpers import (
    get_existing_columns, get_visibility_clause, get_photos_from_clause,
    get_preference_columns, PHOTO_BASE_COLS, PHOTO_OPTIONAL_COLS,
    split_photo_tags, attach_person_data, format_date, sanitize_float_values,
)
from db.connection import HAS_SQLITE_VEC

router = APIRouter(tags=["search"])
logger = logging.getLogger(__name__)

_text_encoder = None
_embedding_cache = None  # numpy fallback: {'matrix': np.array, 'paths': list, 'count': int}
_vec_available = None
_vec_checked_at = 0.0


def _check_vec_available(conn):
    """Check if the photos_vec virtual table exists and has rows (TTL cached)."""
    import time
    global _vec_available, _vec_checked_at
    now = time.monotonic()
    if _vec_available is not None and (now - _vec_checked_at) < 300:
        return _vec_available
    if not HAS_SQLITE_VEC:
        _vec_available = False
        _vec_checked_at = now
        return False
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='photos_vec'"
        ).fetchone()
        if not row or row[0] == 0:
            _vec_available = False
            _vec_checked_at = now
            return False
        exists = conn.execute("SELECT 1 FROM photos_vec LIMIT 1").fetchone()
        _vec_available = exists is not None
    except sqlite3.Error:
        _vec_available = False
    _vec_checked_at = now
    return _vec_available


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

    device = 'cuda' if torch.cuda.is_available() else 'cpu'
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
    """Encode a text query into a normalized embedding vector."""
    import torch

    enc = _load_text_encoder()

    with torch.no_grad():
        if enc['backend'] == 'transformers':
            inputs = enc['tokenizer']([query], padding=True, return_tensors="pt").to(enc['device'])
            text_features = enc['model'].get_text_features(**inputs)
            if not isinstance(text_features, torch.Tensor):
                text_features = text_features.pooler_output
        else:
            tokens = enc['tokenizer']([query]).to(enc['device'])
            text_features = enc['model'].encode_text(tokens)

        text_features = text_features / text_features.norm(dim=-1, keepdim=True)
        return text_features.cpu().numpy().flatten().astype(np.float32)


def _search_vec(conn, text_emb, limit, threshold, vis_sql, vis_params):
    """KNN search via sqlite-vec, filtered by visibility.

    sqlite-vec vec_distance_cosine returns distance (0 = identical, 2 = opposite).
    Similarity = 1 - distance.
    """
    # sqlite-vec MATCH queries don't support WHERE clauses directly,
    # so we fetch more candidates and post-filter by visibility
    k = min(limit * 4, 1000)
    query_bytes = text_emb.tobytes()

    rows = conn.execute(
        '''
        SELECT v.path, v.distance
        FROM photos_vec v
        WHERE v.embedding MATCH ? AND k = ?
        ''',
        [query_bytes, k]
    ).fetchall()

    if not rows:
        return {}

    # Post-filter by visibility and threshold
    candidate_paths = [r['path'] for r in rows]
    candidate_dist = {r['path']: r['distance'] for r in rows}

    if vis_sql != '1=1':
        placeholders = ','.join(['?'] * len(candidate_paths))
        visible = conn.execute(
            f"SELECT path FROM photos WHERE path IN ({placeholders}) AND {vis_sql}",
            candidate_paths + vis_params
        ).fetchall()
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


def _load_embedding_matrix(conn, vis_sql, vis_params, user_id):
    """Fallback: load all photo embeddings into a numpy matrix."""
    global _embedding_cache
    from utils.embedding import bytes_to_normalized_embedding, filter_uniform_embeddings

    row = conn.execute(
        f"SELECT COUNT(*) FROM photos WHERE clip_embedding IS NOT NULL AND {vis_sql}",
        vis_params
    ).fetchone()
    count = row[0] if row else 0

    if _embedding_cache and _embedding_cache['count'] == count and _embedding_cache['user_id'] == user_id:
        return _embedding_cache['matrix'], _embedding_cache['paths']

    rows = conn.execute(
        f"SELECT path, clip_embedding FROM photos WHERE clip_embedding IS NOT NULL AND {vis_sql}",
        vis_params
    ).fetchall()

    paths = []
    embeddings = []
    for row in rows:
        emb = bytes_to_normalized_embedding(row['clip_embedding'])
        if emb is not None:
            paths.append(row['path'])
            embeddings.append(emb)

    # Filter to uniform embedding dimension (CLIP 768 vs SigLIP 1152)
    embeddings, paths = filter_uniform_embeddings(embeddings, paths)

    if not embeddings:
        _embedding_cache = None
        return None, []

    matrix = np.stack(embeddings, axis=0)
    _embedding_cache = {'matrix': matrix, 'paths': paths, 'count': count, 'user_id': user_id}
    return matrix, paths


def _search_numpy(conn, text_emb, limit, threshold, vis_sql, vis_params, user_id):
    """Fallback: brute-force cosine similarity search via NumPy."""
    matrix, paths = _load_embedding_matrix(conn, vis_sql, vis_params, user_id)
    if matrix is None or len(paths) == 0:
        return {}

    if text_emb.shape[0] != matrix.shape[1]:
        return {}

    similarities = matrix @ text_emb
    mask = similarities >= threshold
    if not mask.any():
        return {}

    indices = np.where(mask)[0]
    top_indices = indices[np.argsort(-similarities[indices])[:limit]]
    return {paths[i]: float(similarities[i]) for i in top_indices}


_fts_available = None
_fts_checked_at = 0.0


def _has_fts(conn):
    """Check if the photos_fts table exists (TTL cached, 5 min)."""
    import time
    global _fts_available, _fts_checked_at
    now = time.monotonic()
    if _fts_available is not None and (now - _fts_checked_at) < 300:
        return _fts_available
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='photos_fts'"
        ).fetchone()
        _fts_available = row is not None
    except sqlite3.OperationalError:
        _fts_available = False
    _fts_checked_at = now
    return _fts_available


def _fts_search(conn, query, limit):
    """Run FTS5 search and return {path: normalized_score} dict.

    BM25 rank values are negative (lower = better match).
    Scores are normalized to 0..1 range relative to the best match.
    """
    try:
        rows = conn.execute(
            "SELECT path, rank FROM photos_fts WHERE photos_fts MATCH ? "
            "ORDER BY rank LIMIT ?",
            (query, limit)
        ).fetchall()
    except sqlite3.OperationalError:
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
def api_search(
    request: Request,
    q: str = Query(..., min_length=1, max_length=500),
    limit: int = Query(50, ge=1, le=200),
    threshold: float = Query(0.15, ge=0.0, le=1.0),
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Semantic text-to-image search using CLIP/SigLIP cosine similarity."""
    if not VIEWER_CONFIG.get('features', {}).get('show_semantic_search', True):
        return {'photos': [], 'total': 0, 'query': q, 'error': 'Semantic search is disabled'}

    conn = get_db_connection()
    try:
        user_id = user.user_id if user else None
        vis_sql, vis_params = get_visibility_clause(user_id)
        existing_cols = get_existing_columns(conn)
        from_clause, from_params = get_photos_from_clause(user_id)
        pref_cols = get_preference_columns(user_id)
        pref_col_names = {'star_rating', 'is_favorite', 'is_rejected'}
        select_cols = list(PHOTO_BASE_COLS)
        for c in PHOTO_OPTIONAL_COLS:
            if c in existing_cols:
                if c in pref_col_names:
                    select_cols.append(f"{pref_cols[c]} as {c}")
                else:
                    select_cols.append(c)

        embedding_scores = {}
        fts_scores = {}

        # --- FTS5 text search ---
        if _has_fts(conn):
            fts_scores = _fts_search(conn, q, limit)

        # --- Embedding-based search ---
        text_emb = _encode_text(q)

        if _check_vec_available(conn):
            embedding_scores = _search_vec(conn, text_emb, limit, threshold, vis_sql, vis_params)
        else:
            embedding_scores = _search_numpy(conn, text_emb, limit, threshold, vis_sql, vis_params, user_id)

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
        rows = conn.execute(
            f"SELECT {', '.join(select_cols)} FROM {from_clause} "
            f"WHERE photos.path IN ({placeholders})",
            from_params + matching_paths
        ).fetchall()

        tags_limit = VIEWER_CONFIG['display']['tags_per_photo']
        photos = split_photo_tags(rows, tags_limit)
        for photo in photos:
            photo['date_formatted'] = format_date(photo.get('date_taken'))
            photo['similarity'] = round(sim_by_path.get(photo['path'], 0), 4)

        attach_person_data(photos, conn)

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
    finally:
        conn.close()
