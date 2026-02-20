"""
Persons API router -- person management and person photo browsing.

"""

import math
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.auth import CurrentUser, require_edition, require_authenticated, get_optional_user
from api.config import VIEWER_CONFIG, invalidate_filter_cache
from api.database import get_db_connection
from api.db_helpers import (
    get_existing_columns, split_photo_tags,
    PHOTO_BASE_COLS, PHOTO_OPTIONAL_COLS,
    HIDE_BLINKS_SQL, HIDE_BURSTS_SQL, get_visibility_clause,
)
from api.types import SORT_OPTIONS, VALID_SORT_COLS

router = APIRouter(tags=["persons"])

# Map valid sort column names to their SQL column strings (provably server-origin)
_SORT_COL_MAP: dict[str, str] = {col: col for col in VALID_SORT_COLS}


# --- Pydantic request bodies ---

class RenamePersonRequest(BaseModel):
    name: str = ""


class MergeRequest(BaseModel):
    source_id: int
    target_id: int


class MergeBatchRequest(BaseModel):
    source_ids: List[int]
    target_id: int


class DeleteBatchRequest(BaseModel):
    person_ids: List[int]


# --- Helpers ---

def _format_date(date_str):
    """Format EXIF date string to DD/MM/YYYY HH:MM."""
    if not date_str or not isinstance(date_str, str):
        return ""
    try:
        parts = date_str[:19].split(" ")
        date_parts = parts[0].split(":")
        time_parts = parts[1].split(":") if len(parts) > 1 else ["00", "00"]
        return f"{date_parts[2]}/{date_parts[1]}/{date_parts[0]} {time_parts[0]}:{time_parts[1]}"
    except (ValueError, TypeError, IndexError):
        return date_str.split(" ")[0].replace(":", "/")


def _get_person_info(person_id: int):
    """Fetch person details including photo count."""
    conn = get_db_connection()
    try:
        row = conn.execute("""
            SELECT p.id, p.name, p.representative_face_id,
                   COUNT(DISTINCT f.photo_path) as photo_count
            FROM persons p
            LEFT JOIN faces f ON f.person_id = p.id
            WHERE p.id = ?
            GROUP BY p.id
        """, (person_id,)).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return {
        "id": row["id"],
        "name": row["name"] or f"Person {row['id']}",
        "photo_count": row["photo_count"],
        "representative_face_id": row["representative_face_id"],
    }


def _query_person_photos(person_id: int, *, page: int, per_page: int,
                         sort: str, direction: str, hide_blinks: str,
                         hide_bursts: str, date_from: str, date_to: str,
                         user_id: Optional[str] = None):
    """Shared query logic for person photo listing.

    Returns (photos, page, total_pages, total_count, sort_col).
    """
    offset = (page - 1) * per_page

    # Validate sort column — use dict lookup so interpolated value is a server-origin constant
    sort_col = _SORT_COL_MAP.get(sort, "aggregate")
    sort_dir = "ASC" if direction == "ASC" else "DESC"

    # Build query with person filter
    where_clauses = ["path IN (SELECT photo_path FROM faces WHERE person_id = ?)"]
    sql_params: list = [person_id]

    # Multi-user visibility
    if user_id:
        vis_sql, vis_params = get_visibility_clause(user_id)
        where_clauses.append(vis_sql)
        sql_params.extend(vis_params)

    if hide_blinks == "1":
        where_clauses.append(HIDE_BLINKS_SQL)
    if hide_bursts == "1":
        where_clauses.append(HIDE_BURSTS_SQL)
    if date_from:
        date_from_sql = date_from.replace("-", ":")
        where_clauses.append("date_taken >= ?")
        sql_params.append(date_from_sql)
    if date_to:
        date_to_sql = date_to.replace("-", ":") + " 23:59:59"
        where_clauses.append("date_taken <= ?")
        sql_params.append(date_to_sql)

    where_sql = " AND ".join(where_clauses)

    conn = get_db_connection()
    try:
        total_count = conn.execute(
            f"SELECT COUNT(*) FROM photos WHERE {where_sql}", sql_params
        ).fetchone()[0]
        total_pages = max(1, math.ceil(total_count / per_page))

        existing_cols = get_existing_columns(conn)
        select_cols = list(PHOTO_BASE_COLS) + [
            c for c in PHOTO_OPTIONAL_COLS if c in existing_cols
        ]

        query = f"""
            SELECT {', '.join(select_cols)}
            FROM photos
            WHERE {where_sql}
            ORDER BY {sort_col} {sort_dir}
            LIMIT ? OFFSET ?
        """
        rows = conn.execute(query, sql_params + [per_page, offset]).fetchall()

        tags_limit = VIEWER_CONFIG["display"]["tags_per_photo"]
        photos = split_photo_tags(rows, tags_limit)
    finally:
        conn.close()

    return photos, page, total_pages, total_count, sort_col


# --- Endpoints ---

@router.get("/api/persons")
async def list_persons(
    page: int = Query(1, ge=1),
    per_page: int = Query(48, ge=1, le=200),
    search: str = Query(""),
    sort: str = Query("count_desc", pattern="^(count_asc|count_desc|quality_asc|quality_desc)$"),
    user: CurrentUser = Depends(require_authenticated),
):
    """List all persons with pagination and search."""
    if sort == "count_asc":
        order_clause = "ORDER BY p.face_count ASC, p.id"
    elif sort == "quality_asc":
        order_clause = "ORDER BY rep_quality ASC, p.id"
    elif sort == "quality_desc":
        order_clause = "ORDER BY rep_quality DESC, p.id"
    else:  # count_desc (default)
        order_clause = "ORDER BY p.face_count DESC, p.id"

    where_clause = ""
    params: list = []
    if search.strip():
        where_clause = "WHERE p.name LIKE ?"
        params.append(f"%{search.strip()}%")

    conn = get_db_connection()
    try:
        total = conn.execute(
            f"SELECT COUNT(*) FROM persons p {where_clause}", params
        ).fetchone()[0]

        offset = (page - 1) * per_page
        persons = conn.execute(f"""
            SELECT p.id, p.name, p.representative_face_id, p.face_count,
                   CASE WHEN p.face_thumbnail IS NOT NULL THEN 1 ELSE 0 END as face_thumbnail,
                   (COALESCE(photos.eye_sharpness, 0) / 10.0 * 0.7 +
                    (COALESCE(photos.face_quality, 6.5) - 6.5) / 3.0 * 0.3) as rep_quality
            FROM persons p
            LEFT JOIN faces f ON p.representative_face_id = f.id
            LEFT JOIN photos ON f.photo_path = photos.path
            {where_clause}
            {order_clause}
            LIMIT ? OFFSET ?
        """, params + [per_page, offset]).fetchall()
        persons = [dict(row) for row in persons]
    finally:
        conn.close()

    return {"persons": persons, "total": total, "sort": sort}


@router.post("/api/persons/{person_id}/rename")
async def rename_person(
    person_id: int,
    body: RenamePersonRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Rename a person (set or update their name)."""
    name = body.name.strip()
    conn = get_db_connection()
    try:
        conn.execute("UPDATE persons SET name = ? WHERE id = ?", (name or None, person_id))
        conn.commit()
    finally:
        conn.close()
    invalidate_filter_cache()
    return {"success": True, "name": name or f"Person {person_id}"}


@router.post("/api/persons/merge")
async def merge_persons_json(
    body: MergeRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Merge source person into target person (JSON body)."""
    return await _do_merge(body.source_id, body.target_id)


@router.post("/api/persons/merge/{source_id}/{target_id}")
async def merge_persons(
    source_id: int,
    target_id: int,
    user: CurrentUser = Depends(require_edition),
):
    """Merge source person into target person (path params)."""
    return await _do_merge(source_id, target_id)


async def _do_merge(source_id: int, target_id: int):
    """Shared merge logic."""
    if source_id == target_id:
        raise HTTPException(status_code=400, detail="Cannot merge a person into itself")

    conn = get_db_connection()
    try:
        # 1. Move all faces from source to target
        conn.execute("UPDATE faces SET person_id = ? WHERE person_id = ?",
                     (target_id, source_id))

        # 2. Update target face_count
        count = conn.execute("SELECT COUNT(*) FROM faces WHERE person_id = ?",
                             (target_id,)).fetchone()[0]
        conn.execute("UPDATE persons SET face_count = ? WHERE id = ?",
                     (count, target_id))

        # 3. Delete source person
        conn.execute("DELETE FROM persons WHERE id = ?", (source_id,))

        conn.commit()
        invalidate_filter_cache()
        return {"success": True, "new_count": count}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail='Internal server error')
    finally:
        conn.close()


@router.post("/api/persons/merge_batch")
async def merge_persons_batch(
    body: MergeBatchRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Merge multiple persons into a target person."""
    if not body.source_ids:
        raise HTTPException(status_code=400, detail="Missing source_ids")
    if body.target_id in body.source_ids:
        raise HTTPException(status_code=400, detail="Target cannot be in source list")

    conn = get_db_connection()
    try:
        # Move all faces from sources to target
        placeholders = ",".join("?" * len(body.source_ids))
        conn.execute(
            f"UPDATE faces SET person_id = ? WHERE person_id IN ({placeholders})",
            [body.target_id] + body.source_ids,
        )

        # Update target face_count
        new_count = conn.execute(
            "SELECT COUNT(*) FROM faces WHERE person_id = ?",
            (body.target_id,),
        ).fetchone()[0]
        conn.execute(
            "UPDATE persons SET face_count = ? WHERE id = ?",
            (new_count, body.target_id),
        )

        # Delete source persons
        conn.execute(
            f"DELETE FROM persons WHERE id IN ({placeholders})",
            body.source_ids,
        )
        conn.commit()

        invalidate_filter_cache()
        return {
            "success": True,
            "target_id": body.target_id,
            "merged_count": len(body.source_ids),
            "new_count": new_count,
        }
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail='Internal server error')
    finally:
        conn.close()


@router.post("/api/persons/{person_id}/delete")
async def delete_person(
    person_id: int,
    user: CurrentUser = Depends(require_edition),
):
    """Delete a person and unassign all their faces."""
    conn = get_db_connection()
    try:
        # 1. Unassign all faces from this person (set person_id to NULL)
        conn.execute("UPDATE faces SET person_id = NULL WHERE person_id = ?", (person_id,))

        # 2. Delete the person
        conn.execute("DELETE FROM persons WHERE id = ?", (person_id,))

        conn.commit()
        invalidate_filter_cache()
        return {"success": True}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail='Internal server error')
    finally:
        conn.close()


@router.post("/api/persons/delete_batch")
async def delete_persons_batch(
    body: DeleteBatchRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Delete multiple persons and unassign all their faces."""
    if not body.person_ids:
        raise HTTPException(status_code=400, detail="No person_ids provided")

    conn = get_db_connection()
    try:
        placeholders = ",".join("?" * len(body.person_ids))
        # 1. Unassign all faces from these persons
        conn.execute(
            f"UPDATE faces SET person_id = NULL WHERE person_id IN ({placeholders})",
            body.person_ids,
        )

        # 2. Delete the persons
        conn.execute(
            f"DELETE FROM persons WHERE id IN ({placeholders})",
            body.person_ids,
        )

        conn.commit()
        invalidate_filter_cache()
        return {"success": True, "deleted_count": len(body.person_ids)}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail='Internal server error')
    finally:
        conn.close()


@router.get("/api/persons/{person_id}/photos")
async def person_photos(
    person_id: int,
    page: int = Query(1, ge=1),
    per_page: Optional[int] = None,
    sort: str = Query("aggregate"),
    dir: str = Query("DESC"),
    hide_blinks: str = Query(""),
    hide_bursts: str = Query(""),
    date_from: str = Query(""),
    date_to: str = Query(""),
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Get photos for a specific person with pagination (infinite scroll)."""
    person_info = _get_person_info(person_id)
    if person_info is None:
        raise HTTPException(status_code=404, detail="Person not found")

    if per_page is None:
        per_page = VIEWER_CONFIG["pagination"]["default_per_page"]

    user_id = user.user_id if user else None

    try:
        photos, current_page, total_pages, total_count, sort_col = _query_person_photos(
            person_id,
            page=page,
            per_page=per_page,
            sort=sort,
            direction=dir,
            hide_blinks=hide_blinks,
            hide_bursts=hide_bursts,
            date_from=date_from,
            date_to=date_to,
            user_id=user_id,
        )
    except Exception:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail='Internal server error')

    # Add formatted date for client rendering
    for photo in photos:
        photo["date_formatted"] = _format_date(photo.get("date_taken"))

    return {
        "person": person_info,
        "photos": photos,
        "page": current_page,
        "total_pages": total_pages,
        "total": total_count,
        "has_more": current_page < total_pages,
        "sort_col": sort_col,
    }
