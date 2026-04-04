"""
Memories router — "On This Day" feature showing photos from previous years.

Queries photos taken on the same month-day in prior years, grouped by year,
returning the top photos by aggregate score for each year.
"""

import logging
import sqlite3
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth import CurrentUser, get_optional_user
from api.database import get_db
from api.db_helpers import (
    build_photo_select_columns, sanitize_float_values,
    get_visibility_clause, get_photos_from_clause,
    split_photo_tags, attach_person_data, format_date,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["memories"])


def _get_top_per_year():
    from api.config import VIEWER_CONFIG
    return VIEWER_CONFIG.get('memories', {}).get('top_per_year', 5)


@router.get("/api/memories/check")
def check_memories(
    user: Optional[CurrentUser] = Depends(get_optional_user),
    date_str: Optional[str] = Query(None, alias="date"),
):
    """Lightweight check: are there any memories for this calendar date?

    Returns {"has_memories": true/false} without loading photo data.
    """
    if date_str:
        try:
            target = date.fromisoformat(date_str)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format, expected YYYY-MM-DD")
    else:
        target = date.today()

    month_day = target.strftime("%m-%d")
    target_year = target.strftime("%Y")

    with get_db() as conn:
        try:
            user_id = user.user_id if user else None
            vis_sql, vis_params = get_visibility_clause(user_id)
            from_clause, from_params = get_photos_from_clause(user_id)

            query = f"""
                SELECT 1 FROM {from_clause}
                WHERE strftime('%m-%d', date_taken) = ?
                  AND strftime('%Y', date_taken) < ?
                  AND date_taken IS NOT NULL
                  AND {vis_sql}
                LIMIT 1
            """
            params = from_params + [month_day, target_year] + vis_params
            row = conn.execute(query, params).fetchone()
            return {'has_memories': row is not None}

        except HTTPException:
            raise
        except sqlite3.Error:
            logger.exception("Failed to check memories")
            return {'has_memories': False}


@router.get("/api/memories")
def get_memories(
    user: Optional[CurrentUser] = Depends(get_optional_user),
    date_str: Optional[str] = Query(None, alias="date"),
):
    """Return top photos from the same day in previous years.

    Groups by year, returns up to TOP_PER_YEAR photos per year sorted by
    aggregate score descending.  Uses ROW_NUMBER() to limit rows at the
    database level instead of fetching all and trimming in Python.
    """
    # Parse target date
    if date_str:
        try:
            target = date.fromisoformat(date_str)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format, expected YYYY-MM-DD")
    else:
        target = date.today()

    month_day = target.strftime("%m-%d")
    target_year = target.strftime("%Y")

    with get_db() as conn:
        try:
            user_id = user.user_id if user else None
            vis_sql, vis_params = get_visibility_clause(user_id)

            select_cols = build_photo_select_columns(conn, user_id)

            from_clause, from_params = get_photos_from_clause(user_id)

            top_per_year = _get_top_per_year()

            # Use ROW_NUMBER() to keep only top N per year at the DB level,
            # plus a total count per year via a window COUNT.
            # Safety cap: 50 years * top_per_year photos.
            safety_limit = 50 * top_per_year

            inner_cols = ', '.join(select_cols)
            query = f"""
                SELECT * FROM (
                    SELECT {inner_cols},
                        strftime('%Y', date_taken) AS _year,
                        ROW_NUMBER() OVER (
                            PARTITION BY strftime('%Y', date_taken)
                            ORDER BY aggregate DESC, path ASC
                        ) AS _rn,
                        COUNT(*) OVER (
                            PARTITION BY strftime('%Y', date_taken)
                        ) AS _year_total
                    FROM {from_clause}
                    WHERE strftime('%m-%d', date_taken) = ?
                      AND strftime('%Y', date_taken) < ?
                      AND date_taken IS NOT NULL
                      AND {vis_sql}
                ) WHERE _rn <= ?
                ORDER BY _year DESC, aggregate DESC
                LIMIT ?
            """
            params = from_params + [month_day, target_year] + vis_params + [top_per_year, safety_limit]
            rows = conn.execute(query, params).fetchall()

            # Group by year
            from api.config import VIEWER_CONFIG
            tags_limit = VIEWER_CONFIG.get('display', {}).get('tags_per_photo', 10)
            all_photos = split_photo_tags(rows, tags_limit)

            for photo in all_photos:
                photo['date_formatted'] = format_date(photo.get('date_taken'))

            attach_person_data(all_photos, conn)

            # Build year groups from the pre-limited results
            year_groups: dict[str, dict] = {}
            for photo in all_photos:
                year = photo.pop('_year', None)
                photo.pop('_rn', None)
                year_total = photo.pop('_year_total', 0)
                if not year:
                    continue
                if year not in year_groups:
                    year_groups[year] = {'photos': [], 'total_count': year_total}
                year_groups[year]['photos'].append(photo)

            years = []
            for year in sorted(year_groups.keys(), key=int, reverse=True):
                group = year_groups[year]
                sanitize_float_values(group['photos'])
                years.append({
                    'year': year,
                    'photos': group['photos'],
                    'total_count': group['total_count'],
                })

            return {
                'years': years,
                'has_memories': len(years) > 0,
                'date': target.isoformat(),
            }

        except HTTPException:
            raise
        except sqlite3.Error:
            logger.exception("Failed to fetch memories")
            raise HTTPException(status_code=500, detail="Internal server error")
