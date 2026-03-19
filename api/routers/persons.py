"""
Persons API router -- person management.

"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.auth import CurrentUser, require_edition, require_authenticated
from api.database import get_db_connection

router = APIRouter(tags=["persons"])


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


# --- Endpoints ---

@router.get("/api/persons")
async def list_persons(
    page: int = Query(1, ge=1),
    per_page: int = Query(48, ge=1, le=200),
    search: str = Query(""),
    sort: str = Query("count_desc", pattern="^(count_asc|count_desc|quality_asc|quality_desc|name_asc|name_desc)$"),
    user: CurrentUser = Depends(require_authenticated),
):
    """List all persons with pagination and search."""
    if sort == "name_asc":
        order_clause = "ORDER BY COALESCE(p.name, '') ASC, p.face_count DESC"
    elif sort == "name_desc":
        order_clause = "ORDER BY COALESCE(p.name, '') DESC, p.face_count DESC"
    elif sort == "count_asc":
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
        row = conn.execute(
            f"SELECT COUNT(*) FROM persons p {where_clause}", params
        ).fetchone()
        total = row[0] if row else 0

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
        row = conn.execute("SELECT COUNT(*) FROM faces WHERE person_id = ?",
                           (target_id,)).fetchone()
        count = row[0] if row else 0
        conn.execute("UPDATE persons SET face_count = ? WHERE id = ?",
                     (count, target_id))

        # 3. Delete source person
        conn.execute("DELETE FROM persons WHERE id = ?", (source_id,))

        conn.commit()

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
        row = conn.execute(
            "SELECT COUNT(*) FROM faces WHERE person_id = ?",
            (body.target_id,),
        ).fetchone()
        new_count = row[0] if row else 0
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

        return {"success": True, "deleted_count": len(body.person_ids)}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail='Internal server error')
    finally:
        conn.close()
