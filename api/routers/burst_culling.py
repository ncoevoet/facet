"""
Burst culling router — burst group listing and selection for culling mode,
plus similarity-based group culling using CLIP/SigLIP embeddings.

Uses precomputed burst_group_id from the database (populated by --recompute-burst).
Groups marked as burst_reviewed=1 are skipped so confirmed decisions persist.
"""

import logging
import random
import sqlite3
import time
from collections import Counter
from itertools import groupby
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.auth import CurrentUser, get_optional_user, require_edition
from api.database import get_db
from api.db_helpers import (
    get_visibility_clause, paginate, is_multi_user_enabled, get_photos_from_clause,
    trigger_auto_retrain, set_photos_rejected, album_filter_clause, time_window_clauses,
)
from api.similarity_groups import compute_similarity_groups
from api.routers.scenes import compute_scenes, apply_scene_cull, SceneConfirmBody
from comparison.comparison_manager import record_culling_pairs
from utils.date_utils import parse_date

logger = logging.getLogger(__name__)


def _rejected_clause(user_id):
    """Return (from_clause, from_params, is_rejected_col) for filtering rejected photos."""
    from_clause, from_params = get_photos_from_clause(user_id)
    if user_id and is_multi_user_enabled():
        is_rejected_col = "COALESCE(up.is_rejected, 0)"
    else:
        is_rejected_col = "COALESCE(photos.is_rejected, 0)"
    return from_clause, from_params, is_rejected_col


router = APIRouter(tags=["burst_culling"])


# --- Request models ---

class BurstSelectionBody(BaseModel):
    burst_id: int
    keep_paths: list[str]
    seed: int = 0


class SimilarSelectionBody(BaseModel):
    paths: list[str]
    keep_paths: list[str]


class CullingConfirmBody(BaseModel):
    group_id: int
    type: Literal['burst', 'similar', 'scene']
    paths: list[str]
    keep_paths: list[str]


class CullingFacesBody(BaseModel):
    paths: list[str]


# --- Helpers ---

def _get_burst_weights():
    """Read burst_scoring weights from scoring_config.json.

    Returns (aggregate, aesthetic, sharpness, blink, eyes, expression). The eyes
    and expression weights default to 0 so behavior is unchanged unless they are
    configured; when a photo has faces, they let open-eyes / composed-expression
    frames win near-ties within a burst.
    """
    try:
        from api.config import _FULL_CONFIG
        bs = _FULL_CONFIG.get('burst_scoring', {})
        return (
            bs.get('weight_aggregate', 0.4),
            bs.get('weight_aesthetic', 0.25),
            bs.get('weight_sharpness', 0.2),
            bs.get('weight_blink', 0.15),
            bs.get('weight_eyes', 0.0),
            bs.get('weight_expression', 0.0),
        )
    except (KeyError, TypeError, ValueError):
        return (0.4, 0.25, 0.2, 0.15, 0.0, 0.0)


def _compute_burst_score(photo):
    """Compute burst culling score for ranking photos within a group."""
    w_agg, w_aes, w_sharp, w_blink, w_eyes, w_expr = _get_burst_weights()
    aggregate = photo.get('aggregate') or 0
    aesthetic = photo.get('aesthetic') or 0
    sharpness = photo.get('tech_sharpness') or 0
    is_blink = photo.get('is_blink') or 0
    blink_score = 0 if is_blink else 10
    score = (aggregate * w_agg + aesthetic * w_aes
             + sharpness * w_sharp + blink_score * w_blink)
    # Eyes/expression only apply to photos with faces; default weights are 0.
    if (photo.get('face_count') or 0) > 0:
        eyes = photo.get('eyes_open_score')
        expr = photo.get('expression_score')
        if eyes is not None:
            score += eyes * w_eyes
        if expr is not None:
            score += expr * w_expr
    return score


# Thresholds for deriving a plain-language cull reason from already-loaded
# signals. Kept conservative so reasons only appear when clearly meaningful.
_CULL_EYES_CLOSED_MAX = 4.0       # eyes_open_score (0-10) at/below this = closed
_CULL_EXPRESSION_MIN = 4.0        # expression_score (0-10) below this = poor expression
_CULL_SHARP_DELTA = 1.0           # tech_sharpness gap vs best before flagging "soft"
_CULL_AESTHETIC_DELTA = 0.5       # aesthetic gap vs best before flagging "lower aesthetic"
_CULL_AGGREGATE_DELTA = 0.3       # aggregate gap vs best before flagging "lower overall"


def _compute_cull_reason(photo, best):
    """Return a stable machine reason key for why ``photo`` ranks below ``best``.

    Returns a dict ``{'key': <str>, 'value': <float|None>}`` translated client-side
    via the i18n ``culling.reason.*`` keys. ``best`` is the group's auto-best photo
    dict (same photo when called on the best one, yielding the 'best' key).

    Derived only from fields already loaded for the group (no full critique call).
    Ordering matches user priority: blink/eyes first, then sharpness, aesthetic,
    overall. Falls back to 'lower_overall' when the photo simply scores lower.
    """
    if photo is best or (best is not None and photo.get('path') == best.get('path')):
        return {'key': 'best', 'value': None}

    has_face = (photo.get('face_count') or 0) > 0

    # 1. Blink / eyes closed (face photos only) — highest-priority defect.
    if photo.get('is_blink'):
        return {'key': 'eyes_closed', 'value': None}
    if has_face:
        eyes = photo.get('eyes_open_score')
        if eyes is not None and eyes <= _CULL_EYES_CLOSED_MAX:
            return {'key': 'eyes_closed', 'value': None}

    # 2. Softer than the best frame.
    sharp = photo.get('tech_sharpness')
    best_sharp = best.get('tech_sharpness') if best else None
    if sharp is not None and best_sharp is not None and (best_sharp - sharp) >= _CULL_SHARP_DELTA:
        return {'key': 'soft', 'value': None}

    # 3. Poorer expression than the best frame (face photos only).
    if has_face:
        expr = photo.get('expression_score')
        best_expr = best.get('expression_score') if best else None
        if (expr is not None and best_expr is not None
                and expr < _CULL_EXPRESSION_MIN and best_expr - expr >= 1.0):
            return {'key': 'expression', 'value': None}

    # 4. Lower aesthetic appeal.
    aes = photo.get('aesthetic')
    best_aes = best.get('aesthetic') if best else None
    if aes is not None and best_aes is not None and (best_aes - aes) >= _CULL_AESTHETIC_DELTA:
        return {'key': 'lower_aesthetic', 'value': None}

    # 5. Catch-all: lower overall score.
    agg = photo.get('aggregate')
    best_agg = best.get('aggregate') if best else None
    if agg is not None and best_agg is not None and (best_agg - agg) >= _CULL_AGGREGATE_DELTA:
        return {'key': 'lower_overall', 'value': None}

    return {'key': 'near_duplicate', 'value': None}


def _dominant_category(photos, best_path):
    """Representative content category for a group.

    Burst/similar groups are near-duplicates, so the keeper (best_path) defines
    the category; falls back to the most common category when the keeper has none.
    Returns None when no photo carries a category.
    """
    by_path = {p.get('path'): p.get('category') for p in photos}
    keeper = by_path.get(best_path)
    if keeper:
        return keeper
    present = [p.get('category') for p in photos if p.get('category')]
    if not present:
        return None
    return Counter(present).most_common(1)[0][0]


def _format_group(photos, burst_group_id):
    """Format a burst group for the API response."""
    scored = []
    for p in photos:
        scored.append({
            'path': p['path'],
            'filename': p['filename'],
            'aggregate': p.get('aggregate'),
            'aesthetic': p.get('aesthetic'),
            'tech_sharpness': p.get('tech_sharpness'),
            'is_blink': p.get('is_blink') or 0,
            'eyes_open_score': p.get('eyes_open_score'),
            'expression_score': p.get('expression_score'),
            'face_count': p.get('face_count') or 0,
            'is_burst_lead': p.get('is_burst_lead') or 0,
            'date_taken': p.get('date_taken'),
            'burst_score': round(_compute_burst_score(p), 2),
        })

    scored.sort(key=lambda x: x['burst_score'], reverse=True)
    best_path = scored[0]['path'] if scored else None

    best = scored[0] if scored else None
    for p in scored:
        p['cull_reason'] = _compute_cull_reason(p, best)

    return {
        'burst_id': burst_group_id,
        'photos': scored,
        'best_path': best_path,
        'count': len(scored),
        'category': _dominant_category(photos, best_path),
    }


# --- Shared burst query logic ---

def _query_burst_groups(conn, vis_sql, vis_params, page=None, per_page=None, exclude_rejected=False,
                        user_id=None, album_id=None, date_from=None, date_to=None):
    """Query unreviewed burst groups and their photos.

    If page/per_page are given, returns (groups, total_groups, total_pages) with
    pagination applied.  Otherwise returns (groups, total_groups, 1) for all groups.
    Each group is a dict from ``_format_group`` keyed by burst_group_id.

    ``album_id``/``date_from``/``date_to`` scope which groups qualify (the
    selection queries). The capture-time window is intentionally NOT applied to
    the member fetch, so a burst whose lead sits at a scene boundary still
    returns all of its tail frames; only album membership scopes the members.
    """
    album_sql, album_params = album_filter_clause(album_id)
    window_clauses, window_params = time_window_clauses(date_from, date_to)
    sel_sql = f" AND {album_sql}" + "".join(f" AND {c}" for c in window_clauses)
    sel_params = album_params + window_params
    member_sql = f" AND {album_sql}"
    member_params = album_params

    if exclude_rejected:
        from_clause, from_params, is_rejected_col = _rejected_clause(user_id)
        sel_where = (f"burst_group_id IS NOT NULL AND burst_reviewed = 0 "
                     f"AND {vis_sql} AND {is_rejected_col} = 0{sel_sql}")
        sel_base_params = from_params + vis_params + sel_params
        count_row = conn.execute(
            f"SELECT COUNT(*) as cnt FROM (SELECT burst_group_id FROM {from_clause} "
            f"WHERE {sel_where} GROUP BY burst_group_id HAVING COUNT(*) >= 2)",
            sel_base_params,
        ).fetchone()
        total_groups = count_row['cnt'] if count_row else 0
        order_sql = (f"SELECT burst_group_id FROM {from_clause} WHERE {sel_where} "
                     f"GROUP BY burst_group_id HAVING COUNT(*) >= 2 ORDER BY burst_group_id")
    else:
        sel_where = f"burst_group_id IS NOT NULL AND burst_reviewed = 0 AND {vis_sql}{sel_sql}"
        sel_base_params = vis_params + sel_params
        count_row = conn.execute(
            f"SELECT COUNT(DISTINCT burst_group_id) as cnt FROM photos WHERE {sel_where}",
            sel_base_params,
        ).fetchone()
        total_groups = count_row['cnt'] if count_row else 0
        order_sql = (f"SELECT DISTINCT burst_group_id FROM photos WHERE {sel_where} "
                     f"ORDER BY burst_group_id")

    if page is not None and per_page is not None:
        total_pages, offset = paginate(total_groups, page, per_page)
        group_ids = conn.execute(order_sql + " LIMIT ? OFFSET ?",
                                 sel_base_params + [per_page, offset]).fetchall()
    else:
        total_pages = 1
        group_ids = conn.execute(order_sql, sel_base_params).fetchall()

    gid_list = [row['burst_group_id'] for row in group_ids]
    formatted = []
    if gid_list:
        placeholders = ','.join('?' * len(gid_list))
        if exclude_rejected:
            from_clause, from_params, is_rejected_col = _rejected_clause(user_id)
            all_photos = conn.execute(
                f"""SELECT photos.path, filename, date_taken, aggregate, aesthetic,
                           tech_sharpness, is_blink, is_burst_lead, burst_group_id,
                           eyes_open_score, expression_score, face_count, category
                    FROM {from_clause}
                    WHERE burst_group_id IN ({placeholders}) AND {vis_sql}
                      AND {is_rejected_col} = 0{member_sql}
                    ORDER BY burst_group_id, date_taken""",
                from_params + gid_list + vis_params + member_params,
            ).fetchall()
        else:
            all_photos = conn.execute(
                f"""SELECT path, filename, date_taken, aggregate, aesthetic,
                           tech_sharpness, is_blink, is_burst_lead, burst_group_id,
                           eyes_open_score, expression_score, face_count, category
                    FROM photos
                    WHERE burst_group_id IN ({placeholders}) AND {vis_sql}{member_sql}
                    ORDER BY burst_group_id, date_taken""",
                gid_list + vis_params + member_params,
            ).fetchall()

        for gid, group_photos in groupby(all_photos, key=lambda p: p['burst_group_id']):
            photos_list = [dict(p) for p in group_photos]
            if len(photos_list) >= 2:
                formatted.append(_format_group(photos_list, gid))

    return formatted, total_groups, total_pages


# --- Endpoints ---

@router.get("/api/burst-groups")
def get_burst_groups(
    user: Optional[CurrentUser] = Depends(get_optional_user),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """Return unreviewed burst groups for culling mode.

    Uses precomputed burst_group_id. Groups where burst_reviewed=1 are excluded.
    """
    with get_db() as conn:
        try:
            user_id = user.user_id if user else None
            vis_sql, vis_params = get_visibility_clause(user_id)
            formatted, total_groups, total_pages = _query_burst_groups(
                conn, vis_sql, vis_params, page=page, per_page=per_page,
            )
            return {
                'groups': formatted,
                'total_groups': total_groups,
                'page': page,
                'per_page': per_page,
                'total_pages': total_pages,
            }
        except sqlite3.Error:
            logger.exception("Failed to fetch burst groups")
            raise HTTPException(status_code=500, detail='Internal server error')


@router.post("/api/burst-groups/select")
async def select_burst_photos(
    body: BurstSelectionBody,
    user: CurrentUser = Depends(require_edition),
):
    """Mark selected photos as 'kept' and others as burst rejects.

    Sets is_burst_lead=1 for kept photos, is_rejected=1 for non-kept,
    and burst_reviewed=1 for all photos in the group.
    """
    with get_db() as conn:
        try:
            user_id = user.user_id if user else None
            vis_sql, vis_params = get_visibility_clause(user_id)

            # Fetch photos in this burst group
            photos = conn.execute(
                f"""SELECT path FROM photos
                    WHERE burst_group_id = ? AND {vis_sql}""",
                [body.burst_id] + vis_params,
            ).fetchall()

            if not photos:
                raise HTTPException(status_code=404, detail='Burst group not found')

            group_paths = {p['path'] for p in photos}
            keep_set = set(body.keep_paths)

            # Validate that all keep_paths are in the burst group
            invalid = keep_set - group_paths
            if invalid:
                raise HTTPException(
                    status_code=400,
                    detail=f'Paths not in burst group: {list(invalid)[:3]}',
                )

            # Batch update burst lead status and mark as reviewed
            keep_paths = list(keep_set)
            reject_paths = list(group_paths - keep_set)
            if keep_paths:
                placeholders = ','.join('?' * len(keep_paths))
                conn.execute(
                    f"UPDATE photos SET is_burst_lead = 1, burst_reviewed = 1 WHERE path IN ({placeholders})",
                    keep_paths,
                )
            if reject_paths:
                placeholders = ','.join('?' * len(reject_paths))
                conn.execute(
                    f"UPDATE photos SET is_burst_lead = 0, burst_reviewed = 1 WHERE path IN ({placeholders})",
                    reject_paths,
                )
                set_photos_rejected(conn, reject_paths, user_id)

            record_culling_pairs(
                conn, keep_paths, reject_paths,
                user_id=user_id, group_type='burst',
            )

            conn.commit()
            _invalidate_culling_groups_cache()
            from db import DEFAULT_DB_PATH
            trigger_auto_retrain(DEFAULT_DB_PATH, user_id, len(keep_paths) * len(reject_paths), conn=conn)
            return {'status': 'ok', 'kept': len(keep_set), 'rejected': len(group_paths - keep_set)}

        except HTTPException:
            raise
        except sqlite3.Error:
            logger.exception("Failed to select burst photos")
            raise HTTPException(status_code=500, detail='Internal server error')


# --- Similar Groups (AI Culling) ---

@router.get("/api/similar-groups")
def get_similar_groups(
    user: Optional[CurrentUser] = Depends(get_optional_user),
    threshold: float = Query(0.85, ge=0.5, le=0.99),
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=50),
    seed: int = Query(0, ge=0),
):
    """Return groups of visually similar photos for AI culling.

    Uses CLIP/SigLIP embeddings to find visually similar photos across the
    entire library (not limited to temporal bursts). Groups are shuffled
    randomly using the provided seed for consistent pagination.
    """
    with get_db() as conn:
        try:
            user_id = user.user_id if user else None
            all_groups = compute_similarity_groups(conn, threshold=threshold, user_id=user_id)

            # Shuffle so the user sees different groups each session
            shuffled = list(all_groups)
            random.Random(seed).shuffle(shuffled)

            total_groups = len(shuffled)
            total_pages, offset = paginate(total_groups, page, per_page)
            page_groups = shuffled[offset:offset + per_page]

            # Batch-fetch all photos for this page in a single query
            vis_sql, vis_params = get_visibility_clause(user_id)
            photos_by_group = _fetch_similar_group_photos(conn, page_groups, vis_sql, vis_params)

            formatted = []
            for group_idx, group in enumerate(page_groups):
                photo_list = photos_by_group.get(group_idx, [])
                formatted.append({
                    'burst_id': offset + group_idx,
                    'photos': photo_list,
                    'best_path': group['best_path'],
                    'count': group['count'],
                })

            return {
                'groups': formatted,
                'total_groups': total_groups,
                'page': page,
                'per_page': per_page,
                'total_pages': total_pages,
            }
        except sqlite3.Error:
            logger.exception("Failed to fetch similar groups")
            raise HTTPException(status_code=500, detail='Internal server error')


@router.post("/api/similar-groups/select")
async def select_similar_photos(
    body: SimilarSelectionBody,
    user: CurrentUser = Depends(require_edition),
):
    """Mark selected photos as 'kept' and others as rejected within a similarity group.

    Accepts the full list of group photo paths and keep paths directly from the
    client, avoiding an expensive recomputation of all similarity groups.
    Non-kept photos are marked as is_rejected=1.
    """
    with get_db() as conn:
        try:
            user_id = user.user_id if user else None
            vis_sql, vis_params = get_visibility_clause(user_id)

            group_paths = set(body.paths)
            keep_set = set(body.keep_paths)

            # Validate that all keep_paths are in the group
            invalid = keep_set - group_paths
            if invalid:
                raise HTTPException(
                    status_code=400,
                    detail=f'Paths not in similarity group: {list(invalid)[:3]}',
                )

            # Mark non-kept photos as rejected (per-user in multi-user mode, visibility-checked)
            reject_paths = list(group_paths - keep_set)
            set_photos_rejected(conn, reject_paths, user_id)

            # Mark ALL photos in the group as similarity_reviewed. The column
            # is guaranteed present by the lifespan-time init_database() migration
            # (see api/__init__.py:lifespan and db/schema.py:PHOTOS_COLUMNS).
            all_paths = list(group_paths)
            if all_paths:
                placeholders = ','.join('?' * len(all_paths))
                conn.execute(
                    f"UPDATE photos SET similarity_reviewed = 1 WHERE path IN ({placeholders}) AND {vis_sql}",
                    all_paths + vis_params,
                )

            # Invalidate similarity-groups cache: the kept photos now carry
            # similarity_reviewed=1 and must be excluded from subsequent group
            # computations. Read-time _filter_similar_groups only handles
            # is_rejected, so without this DELETE the cache may show kept
            # photos as still-unreviewed for up to the 1h TTL.
            conn.execute("DELETE FROM stats_cache WHERE key LIKE 'similarity_groups_%'")

            record_culling_pairs(
                conn, list(keep_set), reject_paths,
                user_id=user_id, group_type='similar',
            )

            conn.commit()
            _invalidate_culling_groups_cache()
            from db import DEFAULT_DB_PATH
            trigger_auto_retrain(DEFAULT_DB_PATH, user_id, len(keep_set) * len(reject_paths), conn=conn)
            return {'status': 'ok', 'kept': len(keep_set), 'rejected': len(reject_paths)}

        except HTTPException:
            raise
        except sqlite3.Error:
            logger.exception("Failed to select similar photos")
            raise HTTPException(status_code=500, detail='Internal server error')


# --- Unified Culling Groups ---

def _enrich_burst_group(group):
    """Add time_delta_seconds and a human-readable reason to a burst group."""
    dates = [p.get('date_taken') for p in group['photos'] if p.get('date_taken')]
    time_delta_seconds = None
    reason = 'burst'
    if len(dates) >= 2:
        dates.sort()
        first = parse_date(dates[0])
        last = parse_date(dates[-1])
        if first and last:
            time_delta_seconds = round((last - first).total_seconds(), 1)
            if time_delta_seconds < 60:
                reason = f'{time_delta_seconds}s burst'
            else:
                reason = f'{round(time_delta_seconds / 60, 1)}m burst'
    return {
        'group_id': group['burst_id'],
        'type': 'burst',
        'reason': reason,
        'photos': group['photos'],
        'best_path': group['best_path'],
        'count': group['count'],
        'category': group.get('category'),
        'time_delta_seconds': time_delta_seconds,
    }


def _count_unreviewed_burst_groups(conn, vis_sql, vis_params, exclude_rejected=False, user_id=None):
    """Return the count of unreviewed burst groups."""
    if exclude_rejected:
        from_clause, from_params, is_rejected_col = _rejected_clause(user_id)
        row = conn.execute(
            f"""SELECT COUNT(*) as cnt FROM (
                    SELECT burst_group_id
                    FROM {from_clause}
                    WHERE burst_group_id IS NOT NULL
                      AND burst_reviewed = 0
                      AND {vis_sql}
                      AND {is_rejected_col} = 0
                    GROUP BY burst_group_id
                    HAVING COUNT(*) >= 2
                )""",
            from_params + vis_params,
        ).fetchone()
        return row['cnt'] if row else 0
    else:
        row = conn.execute(
            f"""SELECT COUNT(DISTINCT burst_group_id) as cnt
                FROM photos
                WHERE burst_group_id IS NOT NULL
                  AND burst_reviewed = 0
                  AND {vis_sql}""",
            vis_params,
        ).fetchone()
        return row['cnt'] if row else 0


def _fetch_unreviewed_burst_groups(conn, vis_sql, vis_params, page=None, per_page=None, exclude_rejected=False,
                                   user_id=None, album_id=None, date_from=None, date_to=None):
    """Fetch unreviewed burst groups with enriched data for unified culling.

    When page/per_page are given, only fetches that page's worth of groups.
    """
    groups, _, _ = _query_burst_groups(
        conn, vis_sql, vis_params, page=page, per_page=per_page,
        exclude_rejected=exclude_rejected, user_id=user_id,
        album_id=album_id, date_from=date_from, date_to=date_to,
    )
    return [_enrich_burst_group(g) for g in groups]


def _fetch_similar_group_photos(conn, groups, vis_sql="1=1", vis_params=None, max_per_group=20, exclude_rejected=False, user_id=None):
    """Batch-fetch photos for multiple similar groups in a single query.

    Returns a dict mapping group index to list of photo dicts.
    """
    if vis_params is None:
        vis_params = []
    # Collect all unique paths across groups
    all_paths = []
    for group in groups:
        all_paths.extend(group['paths'])
    if not all_paths:
        return {}

    unique_paths = list(set(all_paths))
    placeholders = ','.join('?' * len(unique_paths))

    if exclude_rejected:
        from_clause, from_params, is_rejected_col = _rejected_clause(user_id)
        rows = conn.execute(
            f"""SELECT photos.path, filename, date_taken, aggregate, aesthetic,
                       tech_sharpness, is_blink, eyes_open_score, expression_score, face_count, category
                FROM {from_clause}
                WHERE photos.path IN ({placeholders}) AND {vis_sql}
                  AND {is_rejected_col} = 0""",
            from_params + unique_paths + vis_params,
        ).fetchall()
    else:
        rows = conn.execute(
            f"""SELECT path, filename, date_taken, aggregate, aesthetic,
                       tech_sharpness, is_blink, eyes_open_score, expression_score, face_count, category
                FROM photos
                WHERE path IN ({placeholders}) AND {vis_sql}""",
            unique_paths + vis_params,
        ).fetchall()

    # Index by path for O(1) lookup
    photo_by_path = {r['path']: dict(r) for r in rows}

    result = {}
    for idx, group in enumerate(groups):
        photos = []
        for p in group['paths']:
            if p in photo_by_path:
                photos.append(dict(photo_by_path[p]))
        # Sort by aggregate DESC and limit
        photos.sort(key=lambda x: x.get('aggregate') or 0, reverse=True)
        photos = photos[:max_per_group]
        best = photos[0] if photos else None
        for pd in photos:
            pd['is_blink'] = pd.get('is_blink') or 0
            pd['is_burst_lead'] = 0
            pd['burst_score'] = round(_compute_burst_score(pd), 2)
            pd['cull_reason'] = _compute_cull_reason(pd, best)
        result[idx] = photos
    return result


def _fetch_scene_groups(conn, user_id=None, album_id=None, date_from=None, date_to=None,
                        exclude_rejected=True):
    """Build culling groups from chronological scenes (``group_by='scene'``).

    Reuses ``compute_scenes`` for the adaptive time-gap segmentation, then
    enriches each scene's member photos with the same burst_score + cull_reason
    shape the burst/similar feeds use. Scenes stay chronological (the feed's
    ``sort`` is ignored for this mode) and are paginated by the caller, so the
    full list is returned here. ``max_per_group`` is sized to the largest scene
    so a 60-photo scene returns all 60 enriched members (the burst/similar
    default of 20 would truncate it).
    """
    scenes = compute_scenes(
        conn, user_id=user_id, album_id=album_id, date_from=date_from, date_to=date_to,
    )
    if not scenes:
        return []
    vis_sql, vis_params = get_visibility_clause(user_id)
    max_per_group = max((s['count'] for s in scenes), default=1)
    photos_by_idx = _fetch_similar_group_photos(
        conn,
        [{'paths': [p['path'] for p in s['photos']]} for s in scenes],
        vis_sql, vis_params, max_per_group=max_per_group,
        exclude_rejected=exclude_rejected, user_id=user_id,
    )
    groups = []
    for idx, scene in enumerate(scenes):
        photos = photos_by_idx.get(idx, [])
        if not photos:
            continue
        present = {p['path'] for p in photos}
        best_path = scene['best_path'] if scene.get('best_path') in present else photos[0]['path']
        moment = scene.get('moment')
        reason = moment if (moment and moment != 'other') else f"{len(photos)} photos"
        groups.append({
            'group_id': scene['scene_id'],
            'type': 'scene',
            'reason': reason,
            'photos': photos,
            'best_path': best_path,
            'count': len(photos),
            'category': _dominant_category(photos, best_path),
            'start': scene.get('start'),
            'end': scene.get('end'),
            'moment': moment,
            'moment_confidence': scene.get('moment_confidence'),
        })
    return groups


def _get_rejected_paths(conn, user_id):
    """Fetch set of rejected paths for the current user."""
    from_clause, from_params, is_rejected_col = _rejected_clause(user_id)
    rows = conn.execute(
        f"SELECT photos.path FROM {from_clause} WHERE {is_rejected_col} = 1",
        from_params
    ).fetchall()
    return {r['path'] for r in rows}


def _filter_similar_groups(conn, all_groups, user_id):
    """Filter out rejected photos from precomputed similarity groups on read.

    best_path may still point to a rejected path after this filter; the
    rejected photo is excluded from the visible photo list downstream by
    _fetch_similar_group_photos (exclude_rejected=True), and
    _fetch_unreviewed_similar_groups then falls back to the aggregate-top
    of the visible set.
    """
    rejected_paths = _get_rejected_paths(conn, user_id)
    if not rejected_paths:
        return all_groups

    filtered = []
    for g in all_groups:
        paths = [p for p in g['paths'] if p not in rejected_paths]
        if len(paths) >= 2:
            filtered.append({
                'paths': paths,
                'best_path': g['best_path'],
                'count': len(paths),
            })
    return filtered


def _count_unreviewed_similar_groups(conn, threshold, user_id, seed, exclude_rejected=False,
                                     album_id=None, date_from=None, date_to=None):
    """Return (count, shuffled_groups) for unreviewed similar groups.

    The shuffled groups list is lightweight (paths only, no photo data).
    """
    all_groups = compute_similarity_groups(
        conn, threshold=threshold, user_id=user_id,
        album_id=album_id, date_from=date_from, date_to=date_to,
    )
    if exclude_rejected:
        all_groups = _filter_similar_groups(conn, all_groups, user_id)
    if not all_groups:
        return 0, []
    shuffled = list(all_groups)
    random.Random(seed).shuffle(shuffled)
    return len(shuffled), shuffled


def _fetch_unreviewed_similar_groups(conn, threshold, vis_sql, vis_params, seed, user_id,
                                     page_groups=None, offset=0, exclude_rejected=False,
                                     album_id=None, date_from=None, date_to=None):
    """Fetch similar groups with photo data for a page slice.

    Args:
        page_groups: Pre-sliced list of groups to enrich. If None, fetches all.
        offset: The global offset of the first group in page_groups (for group_id assignment).
    """
    if page_groups is None:
        all_groups = compute_similarity_groups(
            conn, threshold=threshold, user_id=user_id,
            album_id=album_id, date_from=date_from, date_to=date_to,
        )
        if exclude_rejected:
            all_groups = _filter_similar_groups(conn, all_groups, user_id)
        if not all_groups:
            return []
        shuffled = list(all_groups)
        random.Random(seed).shuffle(shuffled)
        page_groups = shuffled
        offset = 0

    if not page_groups:
        return []

    # Batch-fetch photos only for this page's groups
    photos_by_group = _fetch_similar_group_photos(conn, page_groups, vis_sql, vis_params, exclude_rejected=exclude_rejected, user_id=user_id)

    sim_pct = round(threshold * 100)
    reason = f'{sim_pct}% similar'

    results = []
    for group_idx, group in enumerate(page_groups):
        photo_list = photos_by_group.get(group_idx, [])
        best_path = group['best_path']
        # When page_groups are pre-sliced by the caller, _filter_similar_groups
        # already fixed best_path. But _fetch_similar_group_photos may have
        # further filtered photos (e.g. visibility), so a final check is needed.
        if photo_list and best_path not in {p['path'] for p in photo_list}:
            best_path = photo_list[0]['path']

        results.append({
            'group_id': offset + group_idx,
            'type': 'similar',
            'reason': reason,
            'photos': photo_list,
            'best_path': best_path,
            'count': group['count'],
            'category': _dominant_category(photo_list, best_path),
            'similarity_percent': sim_pct,
        })

    return results


_CULLING_SORTS = ('easiest', 'redundant', 'best', 'recent', 'needs_comparisons')
_CULLING_GROUP_BY = ('all', 'burst', 'similar', 'scene')

# Memo of the fully-enriched + globally-sorted culling groups, keyed by the
# request params that determine the set. Pagination over the same set then
# reuses one enrichment instead of re-materializing + re-scoring every group on
# every page. Invalidated on any confirm (the unreviewed set shrinks); the short
# TTL is a backstop for changes the invalidation can't see (a fresh scan).
_culling_groups_cache: dict = {}
_CULLING_GROUPS_CACHE_TTL = 45.0
_CULLING_GROUPS_CACHE_MAX = 16


def _invalidate_culling_groups_cache():
    """Drop the enriched culling-groups memo after a confirm changes the set."""
    _culling_groups_cache.clear()


def _category_comparison_needs(conn):
    """Map category -> comparisons still needed before weight optimization unlocks.

    Used by the `needs_comparisons` sort so groups in under-trained categories
    surface first. Returns (needs_by_category, default_need) where default_need
    is the full threshold for categories with no comparisons yet.
    """
    from api.config import get_comparison_mode_settings
    threshold = get_comparison_mode_settings().get('min_comparisons_for_optimization', 30)
    rows = conn.execute(
        "SELECT category, COUNT(*) AS cnt FROM comparisons WHERE category IS NOT NULL GROUP BY category"
    ).fetchall()
    needs = {r['category']: max(0, threshold - r['cnt']) for r in rows}
    return needs, threshold


def _culling_sort_key(group, sort, cat_needs, default_need):
    """Descending sort key for a culling group under the selected mode.

    All modes sort largest-first. `easiest` ranks by the burst_score gap between
    the best photo and the runner-up (a clear winner = a fast confirm).
    """
    photos = group.get('photos') or []
    if sort == 'redundant':
        return (group.get('count') or 0,)
    if sort == 'best':
        return (max((p.get('aggregate') or 0) for p in photos) if photos else 0,)
    if sort == 'recent':
        dates = [p.get('date_taken') for p in photos if p.get('date_taken')]
        return (max(dates) if dates else '',)
    if sort == 'needs_comparisons':
        category = group.get('category') or ''
        return (cat_needs.get(category, default_need), group.get('count') or 0)
    scores = sorted((p.get('burst_score') or 0) for p in photos)
    gap = scores[-1] - scores[-2] if len(scores) >= 2 else 0
    return (gap,)


@router.post("/api/culling-group/faces")
async def api_culling_group_faces(
    body: CullingFacesBody,
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Per-face metrics for every photo in a culling group, in one batch call.

    Returns ``{faces_by_path: {path: [{id, face_index, bbox_*, confidence,
    eyes_open_score, expression_score, is_blink}]}}``. Eyes-open and expression
    are recomputed on the fly from each face's stored 106-point landmarks (no
    model load); ``is_blink`` thresholds the eyes-open score at the same cutoff
    used for cull reasons. Replaces the per-photo ``/api/photo/faces`` fan-out so
    the culling lightbox can show true per-face badges.
    """
    paths = [p for p in (body.paths or []) if p]
    if not paths:
        return {'faces_by_path': {}}

    import numpy as np

    from analyzers import FaceAnalyzer

    user_id = user.user_id if user else None
    vis_sql, vis_params = get_visibility_clause(user_id)
    faces_by_path: dict[str, list] = {p: [] for p in paths}
    placeholders = ",".join("?" * len(paths))
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT photo_path, id, face_index, bbox_x1, bbox_y1, bbox_x2, bbox_y2, "
            f"confidence, landmark_2d_106 FROM faces WHERE photo_path IN ({placeholders}) "
            f"AND photo_path IN (SELECT path FROM photos WHERE {vis_sql}) "
            f"ORDER BY photo_path, face_index",
            paths + vis_params,
        ).fetchall()

    for row in rows:
        eyes = expr = None
        blob = row['landmark_2d_106']
        if blob is not None:
            try:
                landmarks = np.frombuffer(blob, dtype=np.float32).reshape(106, 2)
                eyes = FaceAnalyzer.compute_eyes_open_score(landmarks)
                expr = FaceAnalyzer.compute_expression_score(landmarks)
            except (ValueError, TypeError):
                pass
        faces_by_path[row['photo_path']].append({
            'id': row['id'],
            'face_index': row['face_index'],
            'bbox_x1': row['bbox_x1'], 'bbox_y1': row['bbox_y1'],
            'bbox_x2': row['bbox_x2'], 'bbox_y2': row['bbox_y2'],
            'confidence': row['confidence'],
            'eyes_open_score': eyes,
            'expression_score': expr,
            'is_blink': eyes is not None and eyes <= _CULL_EYES_CLOSED_MAX,
        })

    return {'faces_by_path': faces_by_path}


@router.get("/api/culling-groups")
async def api_culling_groups(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    similarity_threshold: float = Query(0.85, ge=0.5, le=1.0),
    seed: int = Query(0),
    exclude_rejected: bool = Query(True),
    sort: str = Query('easiest'),
    group_by: str = Query('all'),
    album_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Return a list of culling groups for one granularity.

    `group_by` selects the grouping: `all` (today's merged burst+similar feed),
    `burst`, `similar`, or `scene`. Burst/similar groups are enriched + globally
    ordered by `sort` (easiest | redundant | best | recent | needs_comparisons)
    and memoized; `scene` groups come from `compute_scenes`, stay chronological
    (`sort` is ignored), and bypass the memo (compute_scenes has its own cache).
    Each group includes a `type` field ("burst" | "similar" | "scene") and a
    human-readable `reason`. Optionally scoped to an album and/or an EXIF
    capture-time window (used by "Cull this scene").
    """
    if sort not in _CULLING_SORTS:
        sort = 'easiest'
    if group_by not in _CULLING_GROUP_BY:
        group_by = 'all'
    with get_db() as conn:
        try:
            user_id = user.user_id if user else None
            vis_sql, vis_params = get_visibility_clause(user_id)

            if album_id is not None:
                from api.routers.albums import _check_album_access
                _check_album_access(conn, album_id, user_id)

            if group_by == 'scene':
                # Scenes carry their own stats_cache; bypass the burst/similar memo
                # and stay chronological (sort is ignored for this mode).
                all_groups = _fetch_scene_groups(
                    conn, user_id=user_id, album_id=album_id,
                    date_from=date_from, date_to=date_to, exclude_rejected=exclude_rejected,
                )
            else:
                # Enriching + globally sorting the whole unreviewed set is identical
                # across pages, so memo it and let pagination reuse one enrichment
                # instead of re-materializing + re-scoring every group per page.
                cache_key = (round(similarity_threshold, 3), seed, sort, exclude_rejected, user_id,
                             album_id, date_from, date_to, group_by)
                cached = _culling_groups_cache.get(cache_key)
                now = time.time()
                if cached is not None and now - cached[0] < _CULLING_GROUPS_CACHE_TTL:
                    all_groups = cached[1]
                else:
                    burst_groups = []
                    if group_by in ('all', 'burst'):
                        burst_groups = _fetch_unreviewed_burst_groups(
                            conn, vis_sql, vis_params,
                            page=None, per_page=None,
                            exclude_rejected=exclude_rejected, user_id=user_id,
                            album_id=album_id, date_from=date_from, date_to=date_to,
                        )
                    similar_groups = []
                    if group_by in ('all', 'similar'):
                        _, similar_shuffled = _count_unreviewed_similar_groups(
                            conn, similarity_threshold, user_id, seed, exclude_rejected=exclude_rejected,
                            album_id=album_id, date_from=date_from, date_to=date_to,
                        )
                        if similar_shuffled:
                            similar_groups = _fetch_unreviewed_similar_groups(
                                conn, similarity_threshold, vis_sql, vis_params, seed, user_id,
                                page_groups=similar_shuffled, offset=0,
                                exclude_rejected=exclude_rejected,
                                album_id=album_id, date_from=date_from, date_to=date_to,
                            )
                            # Keep similar IDs distinct from burst IDs only when both
                            # feeds are present; the type suffix the client appends
                            # ('<id>_<type>') already disambiguates the rest.
                            if burst_groups:
                                for g in similar_groups:
                                    g['group_id'] += len(burst_groups)

                    all_groups = burst_groups + similar_groups

                    cat_needs, default_need = ({}, 0)
                    if sort == 'needs_comparisons':
                        cat_needs, default_need = _category_comparison_needs(conn)
                    all_groups.sort(key=lambda g: _culling_sort_key(g, sort, cat_needs, default_need), reverse=True)

                    if len(_culling_groups_cache) >= _CULLING_GROUPS_CACHE_MAX:
                        _culling_groups_cache.clear()
                    _culling_groups_cache[cache_key] = (now, all_groups)

            total_groups = len(all_groups)
            total_pages, offset = paginate(total_groups, page, per_page)
            page_groups = all_groups[offset:offset + per_page]

            return {
                'groups': page_groups,
                'total_groups': total_groups,
                'page': page,
                'per_page': per_page,
                'total_pages': total_pages,
            }
        except sqlite3.Error:
            logger.exception("Failed to fetch culling groups")
            raise HTTPException(status_code=500, detail='Internal server error')


@router.post("/api/culling-groups/confirm")
async def confirm_culling_group(
    body: CullingConfirmBody,
    user: CurrentUser = Depends(require_edition),
):
    """Confirm culling selection for a burst, similar, or scene group.

    Delegates to the existing burst/similar/scene confirm logic based on `type`.
    """
    if body.type == 'burst':
        burst_body = BurstSelectionBody(
            burst_id=body.group_id,
            keep_paths=body.keep_paths,
        )
        return await select_burst_photos(burst_body, user)
    elif body.type == 'similar':
        similar_body = SimilarSelectionBody(
            paths=body.paths,
            keep_paths=body.keep_paths,
        )
        return await select_similar_photos(similar_body, user)
    elif body.type == 'scene':
        scene_body = SceneConfirmBody(
            paths=body.paths,
            keep_paths=body.keep_paths,
        )
        return await apply_scene_cull(scene_body, user)
    else:
        raise HTTPException(status_code=400, detail=f'Unknown group type: {body.type}')
