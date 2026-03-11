"""
Semantic text-to-image search router.

Uses CLIP/SigLIP embeddings to find photos matching a natural language query.
"""

import logging
import math
from typing import Optional

import numpy as np
from fastapi import APIRouter, Depends, Query, Request

from api.auth import CurrentUser, get_optional_user
from api.config import VIEWER_CONFIG
from api.database import get_db_connection
from api.db_helpers import (
    get_existing_columns, get_visibility_clause, get_photos_from_clause,
    get_preference_columns, PHOTO_BASE_COLS, PHOTO_OPTIONAL_COLS,
    split_photo_tags, attach_person_data, format_date,
)

router = APIRouter(tags=["search"])
logger = logging.getLogger(__name__)

# Module-level cache for text encoder and embedding matrix
_text_encoder = None
_embedding_cache = None  # {'matrix': np.array, 'paths': list, 'count': int}


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


def _load_embedding_matrix(conn, vis_sql, vis_params, user_id):
    """Load all photo embeddings into a numpy matrix for fast similarity search."""
    global _embedding_cache
    from utils.embedding import bytes_to_normalized_embedding

    count = conn.execute(
        f"SELECT COUNT(*) FROM photos WHERE clip_embedding IS NOT NULL AND {vis_sql}",
        vis_params
    ).fetchone()[0]

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

    if not embeddings:
        _embedding_cache = None
        return None, []

    matrix = np.stack(embeddings, axis=0)
    _embedding_cache = {'matrix': matrix, 'paths': paths, 'count': count, 'user_id': user_id}
    return matrix, paths


@router.get("/api/search")
async def api_search(
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

        # Load embedding matrix
        matrix, paths = _load_embedding_matrix(conn, vis_sql, vis_params, user_id)
        if matrix is None or len(paths) == 0:
            return {'photos': [], 'total': 0, 'query': q}

        # Encode text query
        text_emb = _encode_text(q)

        # Check dimension match
        if text_emb.shape[0] != matrix.shape[1]:
            return {'photos': [], 'total': 0, 'query': q,
                    'error': 'Embedding dimension mismatch — re-scan photos with current VRAM profile'}

        # Compute cosine similarities (single matrix multiply)
        similarities = matrix @ text_emb

        # Filter by threshold and get top-N
        mask = similarities >= threshold
        if not mask.any():
            return {'photos': [], 'total': 0, 'query': q}

        indices = np.where(mask)[0]
        sims = similarities[indices]
        top_indices = indices[np.argsort(-sims)[:limit]]
        top_sims = similarities[top_indices]

        # Fetch full photo data for matching paths
        matching_paths = [paths[i] for i in top_indices]
        sim_by_path = {paths[i]: float(similarities[i]) for i in top_indices}

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

        # Sanitize floats
        for photo in photos:
            for key, value in photo.items():
                if isinstance(value, float) and (math.isinf(value) or math.isnan(value)):
                    photo[key] = None

        return {
            'photos': photos,
            'total': int(mask.sum()),
            'query': q,
        }

    except Exception:
        import traceback
        traceback.print_exc()
        return {'photos': [], 'total': 0, 'query': q, 'error': 'Search failed'}
    finally:
        conn.close()
