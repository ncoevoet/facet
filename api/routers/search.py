"""
Semantic text-to-image search router (async).

Uses CLIP/SigLIP embeddings to find photos matching a natural language query.
Fully migrated to aiosqlite per the R7 closure batch.
"""

import asyncio
import logging
import sqlite3
import threading
from typing import Optional

import numpy as np
from fastapi import APIRouter, Depends, Query, Request

from api.auth import CurrentUser, get_optional_user
from api.config import VIEWER_CONFIG, server_scoring_config
from api.database import get_async_db
from api.db_helpers import (
    get_visibility_clause, get_photos_from_clause,
    build_photo_select_columns, is_manual_tags_available,
    split_photo_tags, attach_person_data_async, format_date, sanitize_float_values,
)
from api.models.discovery import PhotoSearchResponse
from db.connection import HAS_SQLITE_VEC
from db.manual_tags import ManualTagError, normalize_manual_tag

router = APIRouter(tags=["search"])
logger = logging.getLogger(__name__)

_text_encoder = None
# (stored embedding dim, torch-free resolved models.clip[_legacy] block). Keyed
# rather than bare, which is what lets the embedding-less answer be cached too --
# see _resolve_clip_config.
_clip_config_cache = None
_clip_config_lock = threading.Lock()
# Rows sampled to decide the stored embedding dimension; see _stored_embedding_dim.
_EMBEDDING_DIM_SAMPLE = 1000
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


def _stored_embedding_dim() -> Optional[int]:
    """Majority embedding dimension among the first embedded rows (None if none).

    SAMPLED, not exhaustive. The unbounded form -- `GROUP BY` over every row --
    plans as `SCAN photos` plus two temp b-trees and took 1.0s warm (far worse
    cold) on a 126k-row library, and `/api/config` reaches this on anonymous
    client bootstrap. Only a MIXED-dimension library can answer differently
    from a full count, and `_EMBEDDING_DIM_SAMPLE` rows settle that vote long
    before the tail matters.

    `LENGTH()` is computed INSIDE the subquery so the sample never materializes
    the embedding blobs themselves.
    """
    from api.database import get_db

    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT n FROM ("
                " SELECT LENGTH(clip_embedding) AS n FROM photos"
                " WHERE clip_embedding IS NOT NULL LIMIT ?"
                ") GROUP BY n ORDER BY COUNT(*) DESC LIMIT 1",
                (_EMBEDDING_DIM_SAMPLE,),
            ).fetchone()
    except sqlite3.Error:
        return None
    return row[0] // 4 if row and row[0] else None


def _reset_clip_config_cache():
    """Drop the resolved `models.clip`/`clip_legacy` block.

    The block is derived from `scoring_config.json`, so `api.config.reload_config`
    calls this. Without it a reload that changes `models.*` keeps serving the
    pre-reload search threshold from `/api/config` and `/api/search` until the
    process restarts, while every other key of the same file goes live at once --
    the exact stale-generation split `reload_config` refills its dicts in place
    to avoid.

    The loaded encoder is deliberately left alone: most reloads (a password
    change, a weight edit) cannot invalidate it, and dropping it would re-pay a
    model load for nothing.
    """
    global _clip_config_cache
    with _clip_config_lock:
        _clip_config_cache = None


def _reset_text_encoder_cache():
    """Clear the loaded text encoder and the resolved-config cache together.

    Must be called wherever `_text_encoder` itself is reset, so a
    `_resolve_clip_config()` answer never outlives the encoder it was
    resolved for.
    """
    global _text_encoder
    _text_encoder = None
    _reset_clip_config_cache()


def _resolve_clip_config() -> dict:
    """Resolve the `models.clip`/`clip_legacy` block matching the stored embeddings.

    Model-free, and torch-free on every path a real library takes.

    Query vectors must live in the SAME space as the stored ones, so the
    stored embedding dimension -- not the box's hardware -- is the primary
    key for this lookup: a CLIP-768 library on a 16gb/SigLIP box must still
    be searched with the 768-dim tower. When exactly one configured model
    block carries that dimension, it wins outright and nothing else needs
    resolving.

    Only when the dimension cannot decide -- an empty library, or a stored
    dimension that zero or several blocks claim -- does this fall back to
    the active VRAM profile. That fallback is why the import below is local:
    `vram_profile` ships as "auto", whose resolution probes the GPU and
    therefore imports torch. `/api/config` reads this through
    `search_threshold_default()` on anonymous client bootstrap and was
    torch-free before; keeping the common path off that branch is what stops
    a ~8s first-paint stall and torch's RSS on CPU-only installs.

    The cache is KEYED ON THE STORED DIMENSION rather than holding a bare
    block, and that is what lets the embedding-less answer be cached too: it
    is reused only while the library still has no embeddings, and re-resolves
    the moment the first one lands. Caching it unkeyed would freeze the
    profile's default for the life of a process whose `/api/config` was hit
    before any scan; not caching it at all -- the first shape this took --
    put the torch branch on EVERY anonymous bootstrap of a fresh install,
    which is the one library guaranteed to have no embeddings yet.

    The double-checked lock matters because `/api/config` is a sync `def`, so
    FastAPI dispatches it to a 40-thread pool: an unguarded check-then-set let
    a reload storm start one independent resolution per thread.
    """
    global _clip_config_cache

    stored_dim = _stored_embedding_dim()
    cached = _clip_config_cache
    if cached is not None and cached[0] == stored_dim:
        return cached[1]

    with _clip_config_lock:
        cached = _clip_config_cache
        if cached is not None and cached[0] == stored_dim:
            return cached[1]
        resolved = _resolve_clip_config_uncached(stored_dim)
        _clip_config_cache = (stored_dim, resolved)
        return resolved


def _resolve_clip_config_uncached(stored_dim: Optional[int]) -> dict:
    """The resolution itself; `_resolve_clip_config` owns the caching rules."""
    config = server_scoring_config()

    matches = []
    if stored_dim:
        model_config = config.get_model_config()
        matches = [block for block in model_config.values()
                   if isinstance(block, dict) and block.get('embedding_dim') == stored_dim]
        if len(matches) == 1:
            return matches[0]

    config.check_vram_profile_compatibility(verbose=False)
    clip_config = config.get_clip_config()

    if stored_dim and clip_config.get('embedding_dim') != stored_dim:
        logger.warning(
            "Stored embeddings are %d-dim but %s configured model block matches; "
            "semantic search will likely return nothing",
            stored_dim, "no" if not matches else "more than one",
        )
    return clip_config


def search_threshold_default() -> float:
    """The active encoder's calibrated semantic-search cosine threshold, as a 0-1 fraction.

    Distinct from `similarity_threshold_percent` (the tag-match threshold) --
    no fallback to it under any circumstance. The `15` here is not a silent
    paper-over of a broken config: it is the value `get_model_config()`'s
    in-code default `clip` block (ViT-L-14) already carries, so a config with
    no `models` section at all -- `MINIMAL_SCORING_CONFIG` in tests, or a
    hand-written minimal install -- keeps gating exactly where it does today
    instead of raising from a request handler.

    `search_threshold_percent` (on both `models.clip` and `models.clip_legacy`)
    is meant to be a WHOLE NUMBER 0-50 and is never validated -- there is no
    `models` property in `config/scoring_config.schema.json` at all -- so this
    coerces rather than trusts. `null` or a quoted `"5"` are both plausible
    hand-edits, and a bare `/ 100` raised `TypeError` from inside
    `/api/config`, which has no `try` of its own: a config typo that should
    have broken only semantic search 500'd the whole anonymous bootstrap.

    A fractional value (e.g. `7.5`) resolves and gates exactly here, and
    reaches the server unrounded as long as the gallery's slider is untouched
    -- the client seeds `Math.round(... * 100)` for DISPLAY but sends nothing
    until the value differs from that seed. Once dragged, the percent the user
    chose is what gates, so a fractional default is observable only until the
    first drag. A value above 50 is likewise unreachable from the slider once
    the user touches it.
    """
    raw = _resolve_clip_config().get('search_threshold_percent', 15)
    try:
        percent = float(raw)
    except (TypeError, ValueError):
        logger.warning(
            "models.*.search_threshold_percent is %r, not a number; gating at 15%% instead", raw,
        )
        percent = 15.0
    return min(max(percent, 0.0), 100.0) / 100


def _load_text_encoder():
    """Load and cache the text encoder matching the stored embeddings."""
    global _text_encoder
    if _text_encoder is not None:
        return _text_encoder

    import torch

    clip_config = _resolve_clip_config()

    from utils.device import get_device
    device = get_device()
    backend = clip_config.get('backend', 'open_clip')
    model_name = clip_config.get('model_name')

    if backend == 'transformers':
        from transformers import AutoModel
        logger.info(f"Loading SigLIP text encoder: {model_name}")
        model = AutoModel.from_pretrained(model_name, dtype=torch.float32).to(device)
        model.eval()
        _text_encoder = {
            'backend': 'transformers',
            'model': model,
            'model_name': model_name,
            'device': device,
        }
    else:
        import open_clip
        pretrained = clip_config.get('pretrained', 'openai')
        logger.info(f"Loading CLIP text encoder: {model_name}")
        model, _, _ = open_clip.create_model_and_transforms(model_name, pretrained=pretrained, device=device)
        model.eval()
        _text_encoder = {
            'backend': 'open_clip',
            'model': model,
            'model_name': model_name,
            'device': device,
        }

    return _text_encoder


def _encode_text(query: str) -> np.ndarray:
    """Encode a single text query into a normalized embedding vector (1D)."""
    return _encode_texts([query])[0]


def _encode_texts(queries: list[str]) -> np.ndarray:
    """Encode a batch of text queries into normalized embeddings.

    Returns a (N, D) float32 array, L2-normalized along the last axis.
    Delegates entirely to `models.tagger.encode_text_prompts` — the single
    place the SigLIP `max_length=64` padding rule (dynamic padding collapses
    similarities to noise) is allowed to live, per that function's own
    docstring. No partial re-implementation is kept here "for speed."
    """
    from models.tagger import encode_text_prompts

    enc = _load_text_encoder()
    text_features = encode_text_prompts(
        enc['model'], enc['model_name'], enc['backend'], enc['device'], list(queries)
    )
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


async def _fts_search(conn, query, limit, scope=None):
    """Run FTS5 search and return {path: normalized_score} dict (async).

    BM25 rank values are negative (lower = better match).
    Scores are normalized to 0..1 range relative to the best match.

    When ``scope == 'text'`` the MATCH is restricted to the text-bearing
    columns (OCR text + AI captions) using FTS5 column filters, so a query
    only hits words found *in* the image or its caption — not filenames,
    camera models, or tags.
    """
    # Sanitize the raw user text into a safe FTS5 expression (shared with the
    # gallery search): unbalanced parens/quotes or a bare NOT would otherwise
    # raise OperationalError and silently degrade the endpoint. ``None`` means
    # no safe token survived, so match nothing.
    from api.routers.gallery import _fts5_query_from
    safe_query = _fts5_query_from(query)
    if not safe_query:
        return {}
    if scope == 'text':
        # FTS5 column-filter syntax: {col1 col2} : query
        match_expr = f"{{caption caption_translated ocr_text}} : ({safe_query})"
    else:
        match_expr = safe_query
    try:
        cur = await conn.execute(
            "SELECT path, rank FROM photos_fts WHERE photos_fts MATCH ? "
            "ORDER BY rank LIMIT ?",
            (match_expr, limit)
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


async def _manual_tag_search(conn, query, limit, vis_sql, vis_params):
    """Photos whose manual tag equals the whole normalized query, as {path: 1.0}.

    Manual tags are not in the FTS index, so this runs as its own query and
    never depends on FTS5 being available. A hit takes the top score: a 0.0
    would be cut by the blend/truncation in ``api_search``. The match is phrase
    equality (the stored form of a tag), a documented limitation next to the
    token-AND FTS match. Visibility-scoped like every other count or list.
    """
    if not is_manual_tags_available(conn):
        return {}
    try:
        tag = normalize_manual_tag(query)
    except ManualTagError:
        return {}
    cur = await conn.execute(
        "SELECT DISTINCT photo_path FROM photo_manual_tags "
        f"WHERE tag = ? AND photo_path IN (SELECT path FROM photos WHERE {vis_sql}) LIMIT ?",
        [tag, *vis_params, limit],
    )
    rows = await cur.fetchall()
    await cur.close()
    return {row[0]: 1.0 for row in rows}


@router.get("/api/search", response_model=PhotoSearchResponse, response_model_exclude_unset=True)
async def api_search(
    request: Request,
    q: str = Query(..., min_length=1, max_length=500),
    limit: int = Query(50, ge=1, le=200),
    threshold: Optional[float] = Query(None, ge=0.0, le=1.0),
    scope: str = Query('', description="'text' restricts to OCR/caption text only"),
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Semantic text-to-image search using CLIP/SigLIP cosine similarity (async).

    Text encoding (`_encode_text`) is a synchronous GPU/CPU call; we run it in
    a worker thread so it never blocks the event loop. All DB I/O uses
    aiosqlite via get_async_db().

    ``scope='text'`` restricts results to FTS5 matches in the OCR/caption text
    columns and skips the embedding search entirely, so the query behaves as a
    literal "find words in the image / its caption" lookup.

    ``threshold`` is optional: omitted, it resolves to the active encoder's
    `models.*.search_threshold_percent` (via `search_threshold_default()`) —
    never to a single global constant. An explicit value (including `0.0`)
    always overrides the resolved default. The resolution itself only runs
    when an embedding search actually happens (``scope != 'text'``), so a
    text-only query never pays for the stored-embedding-dim scan.
    """
    text_only = scope == 'text'
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
                fts_scores = await _fts_search(conn, q, limit, scope='text' if text_only else None)

            # --- Manual-tag companion (outside the FTS path so it works without FTS5;
            # skipped for scope='text', which excludes tags by design) ---
            if not text_only:
                for path, score in (await _manual_tag_search(conn, q, limit, vis_sql, vis_params)).items():
                    fts_scores[path] = max(fts_scores.get(path, 0.0), score)

            # --- Embedding-based search (skipped in text-only scope) ---
            if not text_only:
                # Resolved here, not before the `if`, so a text-scope query
                # never pays for `_resolve_clip_config()`'s stored-embedding-dim
                # lookup on a path that does no embedding search -- and in a
                # worker thread, because that lookup hits SQLite and, on a
                # library with no embeddings yet, imports torch. It sat on the
                # event loop one line above the `to_thread` that exists for
                # exactly this reason.
                resolved_threshold = (
                    await asyncio.to_thread(search_threshold_default)
                    if threshold is None else threshold
                )

                # Text encoding is GPU/CPU work — push to a worker thread so the
                # event loop stays responsive during the typically 5-30ms encode.
                text_emb = await asyncio.to_thread(_encode_text, q)

                if await _check_vec_available(conn):
                    embedding_scores = await _search_vec(conn, text_emb, limit, resolved_threshold, vis_sql, vis_params)
                else:
                    global _search_vec_fallback_total
                    _search_vec_fallback_total += 1
                    embedding_scores = await _search_numpy(conn, text_emb, limit, resolved_threshold, vis_sql, vis_params, user_id)

            # --- Merge results ---
            # Embedding weight 0.7, FTS weight 0.3 (text-only scope: FTS at full weight)
            all_paths = set(embedding_scores) | set(fts_scores)
            sim_by_path = {}
            for path in all_paths:
                emb_score = embedding_scores.get(path, 0.0)
                fts_score = fts_scores.get(path, 0.0)
                if text_only:
                    sim_by_path[path] = fts_score
                else:
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
                f"WHERE photos.path IN ({placeholders}) AND ({vis_sql})",
                from_params + matching_paths + vis_params
            )
            rows = await cur.fetchall()
            await cur.close()

            tags_limit = VIEWER_CONFIG['display']['tags_per_photo']
            photos = split_photo_tags(rows, tags_limit)
            for photo in photos:
                photo['date_formatted'] = format_date(photo.get('date_taken'))
                photo['similarity'] = round(sim_by_path.get(photo['path'], 0), 4)
                # Present only when an embedding score was actually computed
                # for this path (per `exclude_unset`) — never written as
                # `None`, which would put a `null` on the wire instead of
                # omitting the key entirely for FTS-only / scope=text hits.
                if photo['path'] in embedding_scores:
                    photo['embedding_similarity'] = round(embedding_scores[photo['path']], 4)

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
