"""
Burst culling router — burst group listing and selection for culling mode,
plus similarity-based group culling using CLIP/SigLIP embeddings.

Uses precomputed burst_group_id from the database (populated by --recompute-burst).
Groups marked as burst_reviewed=1 are skipped so confirmed decisions persist.
"""

import logging
import math
import random
from itertools import groupby
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.auth import CurrentUser, get_optional_user, require_edition
from api.database import get_db_connection
from api.db_helpers import get_visibility_clause
from api.similarity_groups import compute_similarity_groups
from utils.date_utils import parse_date

logger = logging.getLogger(__name__)

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
    type: Literal['burst', 'similar']
    paths: list[str]
    keep_paths: list[str]


# --- Helpers ---

def _get_burst_weights():
    """Read burst_scoring weights from scoring_config.json."""
    try:
        from api.config import _FULL_CONFIG
        bs = _FULL_CONFIG.get('burst_scoring', {})
        return (
            bs.get('weight_aggregate', 0.4),
            bs.get('weight_aesthetic', 0.25),
            bs.get('weight_sharpness', 0.2),
            bs.get('weight_blink', 0.15),
        )
    except Exception:
        return (0.4, 0.25, 0.2, 0.15)


def _compute_burst_score(photo):
    """Compute burst culling score for ranking photos within a group."""
    w_agg, w_aes, w_sharp, w_blink = _get_burst_weights()
    aggregate = photo.get('aggregate') or 0
    aesthetic = photo.get('aesthetic') or 0
    sharpness = photo.get('tech_sharpness') or 0
    is_blink = photo.get('is_blink') or 0
    blink_score = 0 if is_blink else 10
    return (aggregate * w_agg + aesthetic * w_aes
            + sharpness * w_sharp + blink_score * w_blink)


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
            'is_burst_lead': p.get('is_burst_lead') or 0,
            'date_taken': p.get('date_taken'),
            'burst_score': round(_compute_burst_score(p), 2),
        })

    scored.sort(key=lambda x: x['burst_score'], reverse=True)
    best_path = scored[0]['path'] if scored else None

    return {
        'burst_id': burst_group_id,
        'photos': scored,
        'best_path': best_path,
        'count': len(scored),
    }


# --- Shared burst query logic ---

def _query_burst_groups(conn, vis_sql, vis_params, page=None, per_page=None):
    """Query unreviewed burst groups and their photos.

    If page/per_page are given, returns (groups, total_groups, total_pages) with
    pagination applied.  Otherwise returns (groups, total_groups, 1) for all groups.
    Each group is a dict from ``_format_group`` keyed by burst_group_id.
    """
    count_row = conn.execute(
        f"""SELECT COUNT(DISTINCT burst_group_id) as cnt
            FROM photos
            WHERE burst_group_id IS NOT NULL
              AND burst_reviewed = 0
              AND {vis_sql}""",
        vis_params,
    ).fetchone()
    total_groups = count_row['cnt'] if count_row else 0

    if page is not None and per_page is not None:
        total_pages = max(1, math.ceil(total_groups / per_page))
        offset = (page - 1) * per_page
        group_ids = conn.execute(
            f"""SELECT DISTINCT burst_group_id
                FROM photos
                WHERE burst_group_id IS NOT NULL
                  AND burst_reviewed = 0
                  AND {vis_sql}
                ORDER BY burst_group_id
                LIMIT ? OFFSET ?""",
            vis_params + [per_page, offset],
        ).fetchall()
    else:
        total_pages = 1
        group_ids = conn.execute(
            f"""SELECT DISTINCT burst_group_id
                FROM photos
                WHERE burst_group_id IS NOT NULL
                  AND burst_reviewed = 0
                  AND {vis_sql}
                ORDER BY burst_group_id""",
            vis_params,
        ).fetchall()

    gid_list = [row['burst_group_id'] for row in group_ids]
    formatted = []
    if gid_list:
        placeholders = ','.join('?' * len(gid_list))
        all_photos = conn.execute(
            f"""SELECT path, filename, date_taken, aggregate, aesthetic,
                       tech_sharpness, is_blink, is_burst_lead, burst_group_id
                FROM photos
                WHERE burst_group_id IN ({placeholders}) AND {vis_sql}
                ORDER BY burst_group_id, date_taken""",
            gid_list + vis_params,
        ).fetchall()

        for gid, group_photos in groupby(all_photos, key=lambda p: p['burst_group_id']):
            photos_list = [dict(p) for p in group_photos]
            if len(photos_list) >= 2:
                formatted.append(_format_group(photos_list, gid))

    return formatted, total_groups, total_pages


# --- Endpoints ---

@router.get("/api/burst-groups")
async def get_burst_groups(
    user: Optional[CurrentUser] = Depends(get_optional_user),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """Return unreviewed burst groups for culling mode.

    Uses precomputed burst_group_id. Groups where burst_reviewed=1 are excluded.
    """
    conn = get_db_connection()
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
    except Exception:
        logger.exception("Failed to fetch burst groups")
        raise HTTPException(status_code=500, detail='Internal server error')
    finally:
        conn.close()


@router.post("/api/burst-groups/select")
async def select_burst_photos(
    body: BurstSelectionBody,
    user: CurrentUser = Depends(require_edition),
):
    """Mark selected photos as 'kept' and others as burst rejects.

    Sets is_burst_lead=1 for kept photos, is_rejected=1 for non-kept,
    and burst_reviewed=1 for all photos in the group.
    """
    conn = get_db_connection()
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
                f"UPDATE photos SET is_burst_lead = 0, is_rejected = 1, burst_reviewed = 1 WHERE path IN ({placeholders})",
                reject_paths,
            )

        conn.commit()
        return {'status': 'ok', 'kept': len(keep_set), 'rejected': len(group_paths - keep_set)}

    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to select burst photos")
        raise HTTPException(status_code=500, detail='Internal server error')
    finally:
        conn.close()


# --- Similar Groups (AI Culling) ---

@router.get("/api/similar-groups")
async def get_similar_groups(
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
    conn = get_db_connection()
    try:
        user_id = user.user_id if user else None
        all_groups = compute_similarity_groups(conn, threshold=threshold, user_id=user_id)

        # Shuffle so the user sees different groups each session
        shuffled = list(all_groups)
        random.Random(seed).shuffle(shuffled)

        total_groups = len(shuffled)
        total_pages = max(1, math.ceil(total_groups / per_page))
        offset = (page - 1) * per_page
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
    except Exception:
        logger.exception("Failed to fetch similar groups")
        raise HTTPException(status_code=500, detail='Internal server error')
    finally:
        conn.close()


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
    conn = get_db_connection()
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

        # Mark non-kept photos as rejected (batch UPDATE with visibility check)
        reject_paths = list(group_paths - keep_set)
        if reject_paths:
            placeholders = ','.join('?' * len(reject_paths))
            conn.execute(
                f"UPDATE photos SET is_rejected = 1 WHERE path IN ({placeholders}) AND {vis_sql}",
                reject_paths + vis_params,
            )

        # Mark ALL photos in the group as similarity_reviewed
        all_paths = list(group_paths)
        if all_paths:
            placeholders = ','.join('?' * len(all_paths))
            conn.execute(
                f"UPDATE photos SET similarity_reviewed = 1 WHERE path IN ({placeholders}) AND {vis_sql}",
                all_paths + vis_params,
            )

        conn.commit()
        return {'status': 'ok', 'kept': len(keep_set), 'rejected': len(reject_paths)}

    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to select similar photos")
        raise HTTPException(status_code=500, detail='Internal server error')
    finally:
        conn.close()


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
        'time_delta_seconds': time_delta_seconds,
    }


def _count_unreviewed_burst_groups(conn, vis_sql, vis_params):
    """Return the count of unreviewed burst groups."""
    row = conn.execute(
        f"""SELECT COUNT(DISTINCT burst_group_id) as cnt
            FROM photos
            WHERE burst_group_id IS NOT NULL
              AND burst_reviewed = 0
              AND {vis_sql}""",
        vis_params,
    ).fetchone()
    return row['cnt'] if row else 0


def _fetch_unreviewed_burst_groups(conn, vis_sql, vis_params, page=None, per_page=None):
    """Fetch unreviewed burst groups with enriched data for unified culling.

    When page/per_page are given, only fetches that page's worth of groups.
    """
    groups, _, _ = _query_burst_groups(conn, vis_sql, vis_params, page=page, per_page=per_page)
    return [_enrich_burst_group(g) for g in groups]


def _fetch_similar_group_photos(conn, groups, vis_sql="1=1", vis_params=None, max_per_group=20):
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
    rows = conn.execute(
        f"""SELECT path, filename, date_taken, aggregate, aesthetic,
                   tech_sharpness, is_blink
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
        for pd in photos:
            pd['is_blink'] = pd.get('is_blink') or 0
            pd['is_burst_lead'] = 0
            pd['burst_score'] = round(_compute_burst_score(pd), 2)
        result[idx] = photos
    return result


def _count_unreviewed_similar_groups(conn, threshold, user_id, seed):
    """Return (count, shuffled_groups) for unreviewed similar groups.

    The shuffled groups list is lightweight (paths only, no photo data).
    """
    all_groups = compute_similarity_groups(conn, threshold=threshold, user_id=user_id)
    if not all_groups:
        return 0, []
    shuffled = list(all_groups)
    random.Random(seed).shuffle(shuffled)
    return len(shuffled), shuffled


def _fetch_unreviewed_similar_groups(conn, threshold, vis_sql, vis_params, seed, user_id,
                                     page_groups=None, offset=0):
    """Fetch similar groups with photo data for a page slice.

    Args:
        page_groups: Pre-sliced list of groups to enrich. If None, fetches all.
        offset: The global offset of the first group in page_groups (for group_id assignment).
    """
    if page_groups is None:
        all_groups = compute_similarity_groups(conn, threshold=threshold, user_id=user_id)
        if not all_groups:
            return []
        shuffled = list(all_groups)
        random.Random(seed).shuffle(shuffled)
        page_groups = shuffled
        offset = 0

    if not page_groups:
        return []

    # Batch-fetch photos only for this page's groups
    photos_by_group = _fetch_similar_group_photos(conn, page_groups, vis_sql, vis_params)

    sim_pct = round(threshold * 100)
    reason = f'{sim_pct}% similar'

    results = []
    for group_idx, group in enumerate(page_groups):
        photo_list = photos_by_group.get(group_idx, [])
        results.append({
            'group_id': offset + group_idx,
            'type': 'similar',
            'reason': reason,
            'photos': photo_list,
            'best_path': group['best_path'],
            'count': group['count'],
            'similarity_percent': sim_pct,
        })

    return results


@router.get("/api/culling-groups")
async def api_culling_groups(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    similarity_threshold: float = Query(0.85, ge=0.5, le=1.0),
    seed: int = Query(0),
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Return a unified list of burst + similar groups for culling.

    Merges unreviewed burst groups and unreviewed similar groups into a single
    paginated response. Burst groups come first (more urgent), then similar groups.
    Each group includes a `type` field ("burst" or "similar") and a human-readable
    `reason` string.
    """
    conn = get_db_connection()
    try:
        user_id = user.user_id if user else None
        vis_sql, vis_params = get_visibility_clause(user_id)

        # Count both types to compute total without fetching all data
        burst_count = _count_unreviewed_burst_groups(conn, vis_sql, vis_params)
        similar_count, similar_shuffled = _count_unreviewed_similar_groups(
            conn, similarity_threshold, user_id, seed,
        )

        total_groups = burst_count + similar_count
        total_pages = max(1, math.ceil(total_groups / per_page))
        offset = (page - 1) * per_page

        # Determine which groups fall in this page (bursts first, then similar)
        page_groups = []
        remaining = per_page

        if offset < burst_count:
            # Page includes some burst groups
            burst_page = (offset // per_page) + 1 if per_page else 1
            burst_offset_in_page = offset % per_page if per_page else 0
            burst_slice = _fetch_unreviewed_burst_groups(
                conn, vis_sql, vis_params,
                page=burst_page, per_page=per_page,
            )
            # If the offset doesn't align with burst pagination, slice manually
            if burst_offset_in_page > 0:
                burst_slice = burst_slice[burst_offset_in_page:]
            page_groups.extend(burst_slice[:remaining])
            remaining -= len(page_groups)

        if remaining > 0 and similar_shuffled:
            # Page includes some similar groups
            similar_offset = max(0, offset - burst_count)
            similar_slice = similar_shuffled[similar_offset:similar_offset + remaining]
            similar_enriched = _fetch_unreviewed_similar_groups(
                conn, similarity_threshold, vis_sql, vis_params, seed, user_id,
                page_groups=similar_slice, offset=similar_offset,
            )
            page_groups.extend(similar_enriched)

        # Sort by photo count descending so largest groups appear first
        page_groups.sort(key=lambda g: g['count'], reverse=True)

        return {
            'groups': page_groups,
            'total_groups': total_groups,
            'page': page,
            'per_page': per_page,
            'total_pages': total_pages,
        }
    except Exception:
        logger.exception("Failed to fetch culling groups")
        raise HTTPException(status_code=500, detail='Internal server error')
    finally:
        conn.close()


@router.post("/api/culling-groups/confirm")
async def confirm_culling_group(
    body: CullingConfirmBody,
    user: CurrentUser = Depends(require_edition),
):
    """Confirm culling selection for a burst or similar group.

    Delegates to the existing burst or similar confirm logic based on `type`.
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
    else:
        raise HTTPException(status_code=400, detail=f'Unknown group type: {body.type}')
