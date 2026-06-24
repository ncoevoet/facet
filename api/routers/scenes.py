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
from api.db_helpers import get_visibility_clause, trigger_auto_retrain, set_photos_rejected
from comparison.comparison_manager import record_culling_pairs
from utils.date_utils import parse_date

logger = logging.getLogger(__name__)

router = APIRouter(tags=["scenes"])

_DEFAULT_GAP_HOURS = 4.0
_DEFAULT_MIN_SIZE = 2
_DEFAULT_MAX_PHOTOS = 5000
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
        'gap_hours': float(sc.get('gap_hours', _DEFAULT_GAP_HOURS)),
        'min_size': int(sc.get('min_size', _DEFAULT_MIN_SIZE)),
        'max_photos': int(sc.get('max_photos', _DEFAULT_MAX_PHOTOS)),
    }


def compute_scenes(conn, user_id=None, gap_hours=None, min_size=None):
    """Group chronological burst-leads into scenes by capture-time gaps.

    Reuses the time-gap splitting idea from the capsule journey generator over
    the subject set the similarity culling uses (burst leads + standalone, minus
    rejected). Results are cached in ``stats_cache`` with a 1h TTL.

    Returns a list of scenes: ``{scene_id, start, end, count, best_path, photos}``.
    """
    cfg = _scene_config()
    gap_hours = cfg['gap_hours'] if gap_hours is None else gap_hours
    min_size = cfg['min_size'] if min_size is None else min_size
    vis_sql, vis_params = get_visibility_clause(user_id)

    cache_key = f"scenes_{gap_hours}_{min_size}_{user_id}"
    cached = conn.execute(
        "SELECT value, updated_at FROM stats_cache WHERE key = ?", (cache_key,)
    ).fetchone()
    if cached and (time.time() - cached['updated_at']) < _CACHE_TTL_SECONDS:
        try:
            return json.loads(cached['value'])
        except (json.JSONDecodeError, TypeError):
            pass

    rows = conn.execute(
        f"""SELECT path, filename, aggregate, date_taken
           FROM photos
           WHERE date_taken IS NOT NULL
             AND (is_burst_lead = 1 OR is_burst_lead IS NULL)
             AND (is_rejected IS NULL OR is_rejected = 0)
             AND {vis_sql}
           ORDER BY date_taken ASC
           LIMIT ?""",
        vis_params + [cfg['max_photos']],
    ).fetchall()

    scenes = []
    current = []
    prev_dt = None
    gap_seconds = gap_hours * 3600

    def _flush():
        if len(current) < min_size:
            return
        best = max(current, key=lambda p: p['aggregate'] if p['aggregate'] is not None else -1.0)
        scenes.append({
            'scene_id': len(scenes),
            'start': current[0]['date_taken'],
            'end': current[-1]['date_taken'],
            'count': len(current),
            'best_path': best['path'],
            'photos': [
                {'path': p['path'], 'filename': p['filename'], 'aggregate': p['aggregate'],
                 'date_taken': p['date_taken']}
                for p in current
            ],
        })

    for row in rows:
        dt = parse_date(row['date_taken'])
        if prev_dt is not None and dt is not None and (dt - prev_dt).total_seconds() > gap_seconds:
            _flush()
            current = []
        current.append(row)
        if dt is not None:
            prev_dt = dt
    _flush()

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
    gap_hours: Optional[float] = None,
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Paginated chronological scenes for culling in story order."""
    user_id = user.user_id if user else None
    with get_db() as conn:
        scenes = compute_scenes(conn, user_id=user_id, gap_hours=gap_hours)
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
