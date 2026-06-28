"""Scenes View — chronological scene grouping for culling in story order.

Groups burst leads (and standalone, non-burst photos) into "scenes" by
capture-time gaps, so culling follows the shoot's narrative (ceremony →
reception) above the burst/duplicate level. Cache-only — no schema: the computed
scene list is cached in ``stats_cache`` with a 1h TTL. Scene culling reuses the
comparison feed (``group_type='scene'``) so it trains the personal ranker exactly
like burst/similar culling.
"""

import json
import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.auth import CurrentUser, get_optional_user, require_edition
from api.database import get_db
from api.db_helpers import (
    get_visibility_clause, trigger_auto_retrain, set_photos_rejected,
    album_filter_clause, time_window_clauses,
)
from comparison.comparison_manager import record_culling_pairs
from utils.date_utils import parse_date

logger = logging.getLogger(__name__)

router = APIRouter(tags=["scenes"])

_DEFAULT_GAP_MINUTES = 20.0
_DEFAULT_MIN_SIZE = 2
_DEFAULT_MAX_PHOTOS = 5000
_DEFAULT_MAX_SCENE_SIZE = 60
_DEFAULT_ADAPTIVE = True
_DEFAULT_ADAPTIVE_K = 6.0
_CACHE_TTL_SECONDS = 3600


class SceneConfirmBody(BaseModel):
    paths: list[str]
    keep_paths: list[str]


def _scene_config():
    """Read scenes settings from scoring_config.json (with safe defaults)."""
    try:
        from api.config import _FULL_CONFIG
        sc = _FULL_CONFIG.get('scenes', {}) or {}
    except (ImportError, AttributeError):
        sc = {}
    return {
        'gap_minutes': float(sc.get('gap_minutes', _DEFAULT_GAP_MINUTES)),
        'min_size': int(sc.get('min_size', _DEFAULT_MIN_SIZE)),
        'max_photos': int(sc.get('max_photos', _DEFAULT_MAX_PHOTOS)),
        'max_scene_size': int(sc.get('max_scene_size', _DEFAULT_MAX_SCENE_SIZE)),
        'adaptive': bool(sc.get('adaptive', _DEFAULT_ADAPTIVE)),
        'adaptive_k': float(sc.get('adaptive_k', _DEFAULT_ADAPTIVE_K)),
    }


def _effective_gap_seconds(items, cfg):
    """Resolve the time gap (seconds) that separates two scenes.

    Floors at ``gap_minutes`` and, when ``adaptive`` is on, widens to
    ``adaptive_k × median`` of the shoot's positive consecutive deltas. A
    continuously-shot wedding (tiny median) keeps the tight floor; a sparse
    holiday set (large median) loosens so a 30-minute café stop doesn't split.
    """
    gap_seconds = cfg['gap_minutes'] * 60
    if not cfg['adaptive']:
        return gap_seconds
    deltas = []
    prev = None
    for _, dt in items:
        if prev is not None and dt is not None:
            d = (dt - prev).total_seconds()
            if d > 0:
                deltas.append(d)
        if dt is not None:
            prev = dt
    if deltas:
        deltas.sort()
        median = deltas[len(deltas) // 2]
        gap_seconds = max(gap_seconds, cfg['adaptive_k'] * median)
    return gap_seconds


def _split_oversized(run, max_scene_size):
    """Recursively split a run at its largest internal gap until each chunk fits.

    Guarantees no scene exceeds ``max_scene_size``, so a 997-photo continuous
    run (no inter-scene time gap) still breaks into reviewable scenes. ``run``
    is a list of ``(row, datetime)`` tuples. Among equal-largest gaps (e.g. a
    burst shot at a steady cadence) the split nearest the midpoint is chosen so
    the halves stay balanced instead of peeling off one frame at a time.
    """
    if len(run) <= max_scene_size:
        return [run]
    gaps = []
    for i in range(1, len(run)):
        a, b = run[i - 1][1], run[i][1]
        gaps.append(((b - a).total_seconds() if (a is not None and b is not None) else 0.0, i))
    mid = len(run) / 2
    max_gap = max(g for g, _ in gaps)
    split_i = min((i for g, i in gaps if g >= max_gap - 1e-6), key=lambda i: abs(i - mid))
    return (_split_oversized(run[:split_i], max_scene_size)
            + _split_oversized(run[split_i:], max_scene_size))


def compute_scenes(conn, user_id=None, album_id=None, date_from=None, date_to=None):
    """Group chronological burst-leads into scenes by capture-time gaps.

    Splits the subject set (burst leads + standalone, minus rejected) on an
    adaptive time gap, then sub-splits any run larger than ``max_scene_size`` so
    a whole wedding never collapses into a single scene. Optionally scoped to an
    album and/or an EXIF capture-time window (used by "Cull this scene"). Results
    are cached in ``stats_cache`` with a 1h TTL.

    Returns a list of scenes: ``{scene_id, start, end, count, best_path, photos}``.
    """
    cfg = _scene_config()
    vis_sql, vis_params = get_visibility_clause(user_id)
    album_sql, album_params = album_filter_clause(album_id)
    window_clauses, window_params = time_window_clauses(date_from, date_to)

    cache_key = (
        f"scenes_{cfg['gap_minutes']}_{cfg['min_size']}_{cfg['max_scene_size']}"
        f"_{cfg['adaptive']}_{cfg['adaptive_k']}_{album_id}_{date_from}_{date_to}_{user_id}"
    )
    cached = conn.execute(
        "SELECT value, updated_at FROM stats_cache WHERE key = ?", (cache_key,)
    ).fetchone()
    if cached and (time.time() - cached['updated_at']) < _CACHE_TTL_SECONDS:
        try:
            return json.loads(cached['value'])
        except (json.JSONDecodeError, TypeError):
            pass

    where = [
        "date_taken IS NOT NULL",
        "(is_burst_lead = 1 OR is_burst_lead IS NULL)",
        "(is_rejected IS NULL OR is_rejected = 0)",
        vis_sql,
        album_sql,
    ] + window_clauses
    rows = conn.execute(
        f"""SELECT path, filename, aggregate, date_taken
           FROM photos
           WHERE {' AND '.join(where)}
           ORDER BY date_taken ASC
           LIMIT ?""",
        vis_params + album_params + window_params + [cfg['max_photos']],
    ).fetchall()

    items = [(row, parse_date(row['date_taken'])) for row in rows]
    gap_seconds = _effective_gap_seconds(items, cfg)

    runs = []
    current = []
    prev_dt = None
    for row, dt in items:
        if prev_dt is not None and dt is not None and (dt - prev_dt).total_seconds() > gap_seconds:
            if current:
                runs.append(current)
            current = []
        current.append((row, dt))
        if dt is not None:
            prev_dt = dt
    if current:
        runs.append(current)

    scenes = []
    for run in runs:
        for chunk in _split_oversized(run, cfg['max_scene_size']):
            if len(chunk) < cfg['min_size']:
                continue
            chunk_rows = [r for r, _ in chunk]
            best = max(chunk_rows, key=lambda p: p['aggregate'] if p['aggregate'] is not None else -1.0)
            scenes.append({
                'scene_id': len(scenes),
                'start': chunk_rows[0]['date_taken'],
                'end': chunk_rows[-1]['date_taken'],
                'count': len(chunk_rows),
                'best_path': best['path'],
                'photos': [
                    {'path': p['path'], 'filename': p['filename'], 'aggregate': p['aggregate'],
                     'date_taken': p['date_taken']}
                    for p in chunk_rows
                ],
            })

    conn.execute(
        "INSERT OR REPLACE INTO stats_cache (key, value, updated_at) VALUES (?, ?, ?)",
        (cache_key, json.dumps(scenes), time.time()),
    )
    conn.commit()
    return scenes


@router.get("/api/scenes")
async def api_scenes(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    album_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Paginated chronological scenes for culling in story order."""
    user_id = user.user_id if user else None
    with get_db() as conn:
        scenes = compute_scenes(
            conn, user_id=user_id, album_id=album_id, date_from=date_from, date_to=date_to,
        )
    total = len(scenes)
    start = max(0, (page - 1) * per_page)
    return {
        'scenes': scenes[start:start + per_page],
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': (total + per_page - 1) // per_page if per_page else 1,
    }


@router.post("/api/scenes/confirm")
async def confirm_scene(
    body: SceneConfirmBody,
    user: CurrentUser = Depends(require_edition),
):
    """Cull a scene: reject the non-kept photos and feed the comparison signal.

    Marks non-kept photos as rejected, records culling pairs with
    ``group_type='scene'`` (so the personal ranker learns from the decision),
    invalidates the scenes cache and nudges an auto-retrain.
    """
    with get_db() as conn:
        try:
            user_id = user.user_id if user else None

            group_paths = set(body.paths)
            keep_set = set(body.keep_paths)
            invalid = keep_set - group_paths
            if invalid:
                raise HTTPException(status_code=400, detail=f'Paths not in scene: {list(invalid)[:3]}')

            reject_paths = list(group_paths - keep_set)
            set_photos_rejected(conn, reject_paths, user_id)

            conn.execute("DELETE FROM stats_cache WHERE key LIKE 'scenes_%'")
            record_culling_pairs(
                conn, list(keep_set), reject_paths, user_id=user_id, group_type='scene',
            )
            conn.commit()

            from db import DEFAULT_DB_PATH
            trigger_auto_retrain(DEFAULT_DB_PATH, user_id, len(keep_set) * len(reject_paths), conn=conn)
            return {'status': 'ok', 'kept': len(keep_set), 'rejected': len(reject_paths)}

        except HTTPException:
            raise
        except Exception:
            conn.rollback()
            logger.exception("Failed to confirm scene")
            raise HTTPException(status_code=500, detail='Internal server error')
