"""
Burst culling router — burst group listing and selection for culling mode.

Uses precomputed burst_group_id from the database (populated by --recompute-burst).
Groups marked as burst_reviewed=1 are skipped so confirmed decisions persist.
"""

import logging
import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.auth import CurrentUser, get_optional_user, require_edition
from api.database import get_db_connection
from api.db_helpers import get_visibility_clause

logger = logging.getLogger(__name__)

router = APIRouter(tags=["burst_culling"])


# --- Request models ---

class BurstSelectionBody(BaseModel):
    burst_id: int
    keep_paths: list[str]


# --- Helpers ---

BURST_WEIGHT_AGGREGATE = 0.4
BURST_WEIGHT_AESTHETIC = 0.25
BURST_WEIGHT_SHARPNESS = 0.2
BURST_WEIGHT_BLINK = 0.15


def _compute_burst_score(photo):
    """Compute burst culling score for ranking photos within a group."""
    aggregate = photo.get('aggregate') or 0
    aesthetic = photo.get('aesthetic') or 0
    sharpness = photo.get('tech_sharpness') or 0
    is_blink = photo.get('is_blink') or 0
    blink_score = 0 if is_blink else 10
    return (aggregate * BURST_WEIGHT_AGGREGATE + aesthetic * BURST_WEIGHT_AESTHETIC
            + sharpness * BURST_WEIGHT_SHARPNESS + blink_score * BURST_WEIGHT_BLINK)


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

        # Count distinct unreviewed burst groups
        count_row = conn.execute(
            f"""SELECT COUNT(DISTINCT burst_group_id) as cnt
                FROM photos
                WHERE burst_group_id IS NOT NULL
                  AND burst_reviewed = 0
                  AND {vis_sql}""",
            vis_params,
        ).fetchone()
        total_groups = count_row['cnt'] if count_row else 0
        total_pages = max(1, math.ceil(total_groups / per_page))

        # Get the distinct group IDs for this page
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

            # Group photos by burst_group_id
            from itertools import groupby
            for gid, group_photos in groupby(all_photos, key=lambda p: p['burst_group_id']):
                photos_list = [dict(p) for p in group_photos]
                if len(photos_list) >= 2:
                    formatted.append(_format_group(photos_list, gid))

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

        # Update burst lead status and mark as reviewed
        for path in group_paths:
            if path in keep_set:
                conn.execute(
                    "UPDATE photos SET is_burst_lead = 1, burst_reviewed = 1 WHERE path = ?",
                    (path,),
                )
            else:
                conn.execute(
                    "UPDATE photos SET is_burst_lead = 0, is_rejected = 1, burst_reviewed = 1 WHERE path = ?",
                    (path,),
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
