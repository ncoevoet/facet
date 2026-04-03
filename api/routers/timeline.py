"""
Timeline router — date-grouped photo browsing and calendar heatmap.

"""

import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth import CurrentUser, get_optional_user
from api.config import VIEWER_CONFIG
from api.database import get_db
from api.db_helpers import (
    build_hide_clauses, build_date_range_clauses,
    build_photo_select_columns, sanitize_float_values,
    split_photo_tags, attach_person_data,
    get_visibility_clause, get_photos_from_clause,
    format_date,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["timeline"])

def _get_photos_per_group():
    """Read timeline.photos_per_group from scoring_config.json."""
    try:
        from api.config import _FULL_CONFIG
        return _FULL_CONFIG.get('timeline', {}).get('photos_per_group', 30)
    except (KeyError, TypeError, ValueError):
        return 30


def _fetch_grouped_summaries(conn, from_clause, where_clauses, sql_params, group_expr, order='ASC'):
    """Return (group_key, count, hero_photo_path) rows in one query (no N+1)."""
    where_str = " WHERE " + " AND ".join(where_clauses)
    query = (
        f"SELECT group_key, cnt, path as hero_photo_path FROM ("
        f"  SELECT "
        f"    {group_expr} as group_key, "
        f"    COUNT(*) OVER (PARTITION BY {group_expr}) as cnt, "
        f"    path, "
        f"    ROW_NUMBER() OVER ("
        f"      PARTITION BY {group_expr} "
        f"      ORDER BY COALESCE(aggregate, 0) DESC"
        f"    ) as rn "
        f"  FROM {from_clause}{where_str}"
        f") WHERE rn = 1 "
        f"ORDER BY group_key {order}"
    )
    return conn.execute(query, sql_params).fetchall()



@router.get("/api/timeline")
def api_timeline(
    cursor: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    direction: str = Query("older"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    hide_blinks: str = Query('0'),
    hide_bursts: str = Query('0'),
    hide_duplicates: str = Query('0'),
    photos_per_group: Optional[int] = Query(None, ge=1, le=100),
    sort_by: str = Query('aggregate'),
    granularity: str = Query('day'),
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Return photos grouped by date for timeline view.

    Uses cursor-based pagination on DATE(date_taken).
    """
    # Validate sort_by to prevent injection
    if sort_by not in ('aggregate', 'date_taken', 'filename'):
        sort_by = 'aggregate'
    if granularity not in ('day', 'week', 'month'):
        granularity = 'day'

    # Build date expression based on granularity
    if granularity == 'week':
        # ISO week: group by year + week number (Monday-based)
        date_expr = "STRFTIME('%Y-W%W', REPLACE(SUBSTR(date_taken,1,10),':','-'))"
    elif granularity == 'month':
        date_expr = "SUBSTR(REPLACE(SUBSTR(date_taken,1,10),':','-'),1,7)"
    else:
        date_expr = "DATE(REPLACE(SUBSTR(date_taken,1,10),':','-'))"

    user_id = user.user_id if user else None
    with get_db() as conn:
        try:
            from_clause, from_params = get_photos_from_clause(user_id)
            vis_sql, vis_params = get_visibility_clause(user_id)

            where_clauses = [vis_sql, "date_taken IS NOT NULL", "date_taken != ''"]
            sql_params = list(from_params) + list(vis_params)

            where_clauses.extend(build_hide_clauses(hide_blinks, hide_bursts, hide_duplicates))

            if date_from:
                where_clauses.append(f"{date_expr} >= ?")
                sql_params.append(date_from)
            if date_to:
                where_clauses.append(f"{date_expr} <= ?")
                sql_params.append(date_to)

            if cursor:
                if direction == "newer":
                    where_clauses.append(f"{date_expr} > ?")
                else:
                    where_clauses.append(f"{date_expr} < ?")
                sql_params.append(cursor)

            where_str = " WHERE " + " AND ".join(where_clauses)

            date_order = "ASC" if direction == "newer" else "DESC"

            # Fetch distinct date groups with counts
            date_query = (
                f"SELECT {date_expr} as photo_date, COUNT(*) as cnt "
                f"FROM {from_clause}{where_str} "
                f"GROUP BY photo_date "
                f"ORDER BY photo_date {date_order} "
                f"LIMIT ?"
            )
            # Fetch one extra to detect has_more
            date_rows = conn.execute(date_query, sql_params + [limit + 1]).fetchall()

            has_more = len(date_rows) > limit
            date_rows = date_rows[:limit]

            # Build select columns
            select_cols = build_photo_select_columns(conn, user_id)

            tags_limit = VIEWER_CONFIG['display']['tags_per_photo']
            groups = []
            next_cursor = None

            if date_rows:
                # Collect date list and counts
                date_list = [row['photo_date'] for row in date_rows]
                date_counts = {row['photo_date']: row['cnt'] for row in date_rows}

                # Single query: fetch top photos for ALL dates using ROW_NUMBER()
                ppg = photos_per_group if photos_per_group is not None else _get_photos_per_group()
                placeholders = ','.join('?' * len(date_list))

                # Sort order within each group
                if sort_by == 'date_taken':
                    inner_order = "date_taken ASC, path ASC"
                elif sort_by == 'filename':
                    inner_order = "filename ASC, path ASC"
                else:
                    inner_order = "aggregate DESC, path ASC"

                batch_where = [vis_sql, "date_taken IS NOT NULL", "date_taken != ''"]
                batch_params = list(from_params) + list(vis_params)
                batch_where.extend(build_hide_clauses(hide_blinks, hide_bursts, hide_duplicates))
                batch_where.append(f"{date_expr} IN ({placeholders})")
                batch_params.extend(date_list)

                batch_where_str = " WHERE " + " AND ".join(batch_where)

                photo_query = (
                    f"SELECT * FROM ("
                    f"  SELECT {', '.join(select_cols)}, "
                    f"    {date_expr} AS _photo_date, "
                    f"    ROW_NUMBER() OVER ("
                    f"      PARTITION BY {date_expr} "
                    f"      ORDER BY {inner_order}"
                    f"    ) AS _rn "
                    f"  FROM {from_clause}{batch_where_str}"
                    f") WHERE _rn <= ?"
                )
                batch_params.append(ppg)

                rows = conn.execute(photo_query, batch_params).fetchall()
                all_photos = split_photo_tags(rows, tags_limit)

                for photo in all_photos:
                    photo['date_formatted'] = format_date(photo.get('date_taken'))

                attach_person_data(all_photos, conn)
                sanitize_float_values(all_photos)

                # Group photos by date, preserving the paginated date order
                photos_by_date: dict[str, list] = {d: [] for d in date_list}
                for photo in all_photos:
                    pd = photo.pop('_photo_date', None)
                    photo.pop('_rn', None)
                    if pd in photos_by_date:
                        photos_by_date[pd].append(photo)

                for photo_date in date_list:
                    groups.append({
                        'date': photo_date,
                        'count': date_counts[photo_date],
                        'photos': photos_by_date[photo_date],
                    })

                next_cursor = date_list[-1]

        except HTTPException:
            raise
        except Exception:
            logger.exception("Failed to fetch timeline")
            return {'groups': [], 'next_cursor': None, 'has_more': False}

    return {
        'groups': groups,
        'next_cursor': next_cursor if has_more else None,
        'has_more': has_more,
    }


@router.get("/api/timeline/dates")
def api_timeline_dates(
    year: int = Query(..., ge=1900, le=2100),
    month: Optional[int] = Query(None, ge=1, le=12),
    hide_blinks: str = Query('0'),
    hide_bursts: str = Query('0'),
    hide_duplicates: str = Query('0'),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Return date counts for a calendar heatmap.

    Returns dates with photo counts for the given year (and optionally month).
    """
    user_id = user.user_id if user else None
    with get_db() as conn:
        try:
            from_clause, from_params = get_photos_from_clause(user_id)
            vis_sql, vis_params = get_visibility_clause(user_id)

            where_clauses = [vis_sql, "date_taken IS NOT NULL", "date_taken != ''"]
            sql_params = list(from_params) + list(vis_params)

            where_clauses.extend(build_hide_clauses(hide_blinks, hide_bursts, hide_duplicates))

            date_clauses, date_params = build_date_range_clauses(date_from, date_to)
            where_clauses.extend(date_clauses)
            sql_params.extend(date_params)

            # Filter by year (EXIF format: YYYY:MM:DD)
            year_prefix = str(year)
            if month is not None:
                date_prefix = f"{year}:{month:02d}"
                where_clauses.append("SUBSTR(date_taken,1,7) = ?")
                sql_params.append(date_prefix)
            else:
                where_clauses.append("SUBSTR(date_taken,1,4) = ?")
                sql_params.append(year_prefix)

            date_expr = "DATE(REPLACE(SUBSTR(date_taken,1,10),':','-'))"
            rows = _fetch_grouped_summaries(conn, from_clause, where_clauses, sql_params, date_expr, 'ASC')

            dates = [
                {'date': row['group_key'], 'count': row['cnt'], 'hero_photo_path': row['hero_photo_path']}
                for row in rows
            ]

        except HTTPException:
            raise
        except Exception:
            logger.exception("Failed to fetch timeline dates")
            return {'dates': []}

    return {'dates': dates}


@router.get("/api/timeline/years")
def api_timeline_years(
    hide_blinks: str = Query('0'),
    hide_bursts: str = Query('0'),
    hide_duplicates: str = Query('0'),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Return year summaries with photo counts and hero thumbnails."""
    user_id = user.user_id if user else None
    with get_db() as conn:
        try:
            from_clause, from_params = get_photos_from_clause(user_id)
            vis_sql, vis_params = get_visibility_clause(user_id)

            where_clauses = [vis_sql, "date_taken IS NOT NULL", "date_taken != ''"]
            sql_params = list(from_params) + list(vis_params)

            where_clauses.extend(build_hide_clauses(hide_blinks, hide_bursts, hide_duplicates))

            date_clauses, date_params = build_date_range_clauses(date_from, date_to)
            where_clauses.extend(date_clauses)
            sql_params.extend(date_params)

            year_expr = "SUBSTR(REPLACE(SUBSTR(date_taken,1,10),':','-'),1,4)"
            rows = _fetch_grouped_summaries(conn, from_clause, where_clauses, sql_params, year_expr, 'DESC')

            years = [
                {'year': row['group_key'], 'count': row['cnt'], 'hero_photo_path': row['hero_photo_path']}
                for row in rows
            ]

        except HTTPException:
            raise
        except Exception:
            logger.exception("Failed to fetch timeline years")
            return {'years': []}

    return {'years': years}


@router.get("/api/timeline/months")
def api_timeline_months(
    year: int = Query(..., ge=1900, le=2100),
    hide_blinks: str = Query('0'),
    hide_bursts: str = Query('0'),
    hide_duplicates: str = Query('0'),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Return month summaries for a given year with photo counts and hero thumbnails."""
    user_id = user.user_id if user else None
    with get_db() as conn:
        try:
            from_clause, from_params = get_photos_from_clause(user_id)
            vis_sql, vis_params = get_visibility_clause(user_id)

            where_clauses = [vis_sql, "date_taken IS NOT NULL", "date_taken != ''",
                             "SUBSTR(date_taken,1,4) = ?"]
            sql_params = list(from_params) + list(vis_params) + [str(year)]

            where_clauses.extend(build_hide_clauses(hide_blinks, hide_bursts, hide_duplicates))

            date_clauses, date_params = build_date_range_clauses(date_from, date_to)
            where_clauses.extend(date_clauses)
            sql_params.extend(date_params)

            month_expr = "SUBSTR(REPLACE(SUBSTR(date_taken,1,7),':','-'),1,7)"
            rows = _fetch_grouped_summaries(conn, from_clause, where_clauses, sql_params, month_expr, 'ASC')

            months = [
                {'month': row['group_key'], 'count': row['cnt'], 'hero_photo_path': row['hero_photo_path']}
                for row in rows
            ]

        except HTTPException:
            raise
        except Exception:
            logger.exception("Failed to fetch timeline months")
            return {'months': []}

    return {'months': months}
