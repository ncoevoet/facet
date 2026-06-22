"""
Persons API router -- person management.

"""

import logging
import sqlite3
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.auth import CurrentUser, require_edition, require_authenticated
from api.config import VIEWER_CONFIG, invalidate_stats_cache
from api.database import get_async_db, get_db
from api.db_helpers import reassign_faces_to_person
from db import person_not_hidden_clause

logger = logging.getLogger(__name__)

router = APIRouter(tags=["persons"])

_SORT_CLAUSES = {
    "name_asc": "ORDER BY COALESCE(p.name, '') ASC, p.face_count DESC",
    "name_desc": "ORDER BY COALESCE(p.name, '') DESC, p.face_count DESC",
    "count_asc": "ORDER BY p.face_count ASC, p.id",
    "count_desc": "ORDER BY p.face_count DESC, p.id",
    "quality_asc": "ORDER BY rep_quality ASC, p.id",
    "quality_desc": "ORDER BY rep_quality DESC, p.id",
}


# --- Pydantic request bodies ---

class RenamePersonRequest(BaseModel):
    name: str = ""


class MergeRequest(BaseModel):
    source_id: int
    target_id: int


class MergeBatchRequest(BaseModel):
    # Arbitrary (source -> target) pairs, as produced by the "Accept all" UI.
    # Different pairs may have different targets; chains are resolved server-side.
    merges: List[MergeRequest]


class RejectMergeRequest(BaseModel):
    person1_id: int
    person2_id: int


class DeleteBatchRequest(BaseModel):
    person_ids: List[int]


class CreatePersonRequest(BaseModel):
    name: str
    face_ids: List[int] = Field(default_factory=list, max_length=500)


class AssignFacesRequest(BaseModel):
    face_ids: List[int] = Field(min_length=1, max_length=500)


class SplitPersonRequest(BaseModel):
    face_ids: List[int] = Field(min_length=1, max_length=500)
    name: Optional[str] = None


# --- Endpoints ---

@router.get("/api/persons")
async def list_persons(
    page: int = Query(1, ge=1),
    per_page: int = Query(48, ge=1, le=200),
    search: str = Query(""),
    sort: str = Query("count_desc", pattern="^(count_asc|count_desc|quality_asc|quality_desc|name_asc|name_desc)$"),
    include_hidden: bool = Query(False),
    user: CurrentUser = Depends(require_authenticated),
):
    """List all persons with pagination and search.

    Hidden persons (``is_hidden = 1``) are excluded by default; pass
    ``include_hidden=true`` to surface them.
    """
    order_clause = _SORT_CLAUSES.get(sort, _SORT_CLAUSES["count_desc"])

    where_parts: list = []
    params: list = []
    if not include_hidden:
        where_parts.append(person_not_hidden_clause('p'))
    if search.strip():
        term = search.strip()
        if term.isdigit():
            where_parts.append("(p.id = ? OR p.name LIKE ?)")
            params.extend([int(term), f"%{term}%"])
        else:
            where_parts.append("p.name LIKE ?")
            params.append(f"%{term}%")
    where_clause = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

    async with get_async_db() as conn:
        cur = await conn.execute(
            f"SELECT COUNT(*) FROM persons p {where_clause}", params
        )
        row = await cur.fetchone()
        await cur.close()
        total = row[0] if row else 0

        offset = (page - 1) * per_page
        cur = await conn.execute(f"""
            SELECT p.id, p.name, p.representative_face_id, p.face_count,
                   COALESCE(p.is_hidden, 0) as is_hidden,
                   CASE WHEN p.face_thumbnail IS NOT NULL THEN 1 ELSE 0 END as face_thumbnail,
                   (COALESCE(photos.eye_sharpness, 0) / 10.0 * 0.7 +
                    (COALESCE(photos.face_quality, 6.5) - 6.5) / 3.0 * 0.3) as rep_quality
            FROM persons p
            LEFT JOIN faces f ON p.representative_face_id = f.id
            LEFT JOIN photos ON f.photo_path = photos.path
            {where_clause}
            {order_clause}
            LIMIT ? OFFSET ?
        """, params + [per_page, offset])
        rows = await cur.fetchall()
        await cur.close()
        persons = [dict(row) for row in rows]

    return {"persons": persons, "total": total, "sort": sort}


@router.post("/api/persons/{person_id}/rename")
def rename_person(
    person_id: int,
    body: RenamePersonRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Rename a person (set or update their name)."""
    name = body.name.strip()
    with get_db() as conn:
        conn.execute("UPDATE persons SET name = ? WHERE id = ?", (name or None, person_id))
        conn.commit()
    invalidate_stats_cache()
    return {"success": True, "name": name or f"Person {person_id}"}


@router.post("/api/persons/merge")
def merge_persons_json(
    body: MergeRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Merge source person into target person (JSON body)."""
    return _do_merge(body.source_id, body.target_id)


@router.post("/api/persons/merge/{source_id}/{target_id}")
def merge_persons(
    source_id: int,
    target_id: int,
    user: CurrentUser = Depends(require_edition),
):
    """Merge source person into target person (path params)."""
    return _do_merge(source_id, target_id)


def _do_merge(source_id: int, target_id: int):
    """Shared merge logic."""
    if source_id == target_id:
        raise HTTPException(status_code=400, detail="Cannot merge a person into itself")

    with get_db() as conn:
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
            invalidate_stats_cache()

            return {"success": True, "new_count": count}
        except HTTPException:
            raise
        except sqlite3.Error:
            logger.exception("Database error merging person %d into %d", source_id, target_id)
            conn.rollback()
            raise HTTPException(status_code=500, detail='Internal server error')


def _resolve_merge_chains(pairs):
    """Collapse (source -> target) pairs into {final_target: set(ids_to_fold)}.

    Follows chains transitively (e.g. 2->1 and 1->4 means both 1 and 2 fold into
    4) and is cycle-safe — a visited set breaks any accidental loop.
    """
    direct = {}
    for source_id, target_id in pairs:
        if source_id != target_id:
            direct[source_id] = target_id

    def final_target(node):
        seen = set()
        cur = node
        while cur in direct and cur not in seen:
            seen.add(cur)
            cur = direct[cur]
        return cur

    groups = {}
    for source_id in direct:
        target = final_target(source_id)
        if target != source_id:
            groups.setdefault(target, set()).add(source_id)
    return groups


@router.post("/api/persons/merge_batch")
def merge_persons_batch(
    body: MergeBatchRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Merge arbitrary (source -> target) person pairs in one transaction.

    The "Accept all" UI sends pairs that may target different persons and may
    chain (2->1, 1->4); chains are collapsed to their final target so every
    folded person ends up under the surviving one.
    """
    pairs = [(m.source_id, m.target_id) for m in body.merges]
    groups = _resolve_merge_chains(pairs)
    if not groups:
        raise HTTPException(status_code=400, detail="No valid merges")

    with get_db() as conn:
        try:
            merged_total = 0
            for target_id, source_ids in groups.items():
                ids = sorted(source_ids)
                placeholders = ",".join("?" * len(ids))
                # Move every folded person's faces onto the surviving target
                conn.execute(
                    f"UPDATE faces SET person_id = ? WHERE person_id IN ({placeholders})",
                    [target_id, *ids],
                )
                # Refresh the target's face_count from the faces table
                row = conn.execute(
                    "SELECT COUNT(*) FROM faces WHERE person_id = ?", (target_id,)
                ).fetchone()
                conn.execute(
                    "UPDATE persons SET face_count = ? WHERE id = ?",
                    (row[0] if row else 0, target_id),
                )
                # Delete the folded persons
                conn.execute(
                    f"DELETE FROM persons WHERE id IN ({placeholders})", ids
                )
                merged_total += len(ids)

            conn.commit()
            invalidate_stats_cache()
            return {
                "success": True,
                "targets": sorted(groups),
                "merged_count": merged_total,
            }
        except sqlite3.Error:
            logger.exception("Database error in batch merge (%d pairs)", len(pairs))
            conn.rollback()
            raise HTTPException(status_code=500, detail='Internal server error')


@router.post("/api/persons/merge_suggestions/reject")
def reject_merge_suggestion(
    body: RejectMergeRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Remember a dismissed merge suggestion so it is not proposed again."""
    person_a, person_b = sorted((body.person1_id, body.person2_id))
    if person_a == person_b:
        raise HTTPException(status_code=400, detail="Cannot reject a person against itself")
    with get_db() as conn:
        try:
            conn.execute(
                "INSERT OR IGNORE INTO rejected_merge_suggestions "
                "(person_a_id, person_b_id) VALUES (?, ?)",
                (person_a, person_b),
            )
            conn.commit()
            return {"success": True}
        except sqlite3.Error:
            logger.exception("Database error rejecting merge %d/%d", person_a, person_b)
            conn.rollback()
            raise HTTPException(status_code=500, detail='Internal server error')


@router.post("/api/persons/{person_id}/delete")
def delete_person(
    person_id: int,
    user: CurrentUser = Depends(require_edition),
):
    """Delete a person and unassign all their faces."""
    with get_db() as conn:
        try:
            # 1. Unassign all faces from this person (set person_id to NULL)
            conn.execute("UPDATE faces SET person_id = NULL WHERE person_id = ?", (person_id,))

            # 2. Delete the person
            conn.execute("DELETE FROM persons WHERE id = ?", (person_id,))

            conn.commit()
            invalidate_stats_cache()

            return {"success": True}
        except sqlite3.Error:
            logger.exception("Database error deleting person %d", person_id)
            conn.rollback()
            raise HTTPException(status_code=500, detail='Internal server error')


@router.post("/api/persons/delete_batch")
def delete_persons_batch(
    body: DeleteBatchRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Delete multiple persons and unassign all their faces."""
    if not body.person_ids:
        raise HTTPException(status_code=400, detail="No person_ids provided")

    with get_db() as conn:
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
            invalidate_stats_cache()

            return {"success": True, "deleted_count": len(body.person_ids)}
        except sqlite3.Error:
            logger.exception("Database error in batch delete persons")
            conn.rollback()
            raise HTTPException(status_code=500, detail='Internal server error')


@router.get("/api/persons/needs_naming")
async def api_persons_needs_naming(
    min_faces: Optional[int] = Query(None, ge=0),
    user: CurrentUser = Depends(require_authenticated),
):
    """List unnamed auto-clustered persons with face_count >= min_faces (default from config)."""
    if min_faces is None:
        try:
            min_faces = int(VIEWER_CONFIG.get('persons', {}).get('needs_naming_min_faces', 5))
        except (TypeError, ValueError):
            min_faces = 5

    async with get_async_db() as conn:
        cur = await conn.execute("""
            SELECT p.id, p.name, p.representative_face_id, p.face_count,
                   CASE WHEN p.face_thumbnail IS NOT NULL THEN 1 ELSE 0 END as face_thumbnail
            FROM persons p
            WHERE p.name IS NULL AND p.auto_clustered = 1 AND p.face_count >= ?
            ORDER BY p.face_count DESC, p.id
        """, (min_faces,))
        rows = await cur.fetchall()
        await cur.close()

    return {
        "persons": [dict(r) for r in rows],
        "min_faces": min_faces,
        "total": len(rows),
    }


@router.post("/api/persons")
def api_create_person(
    body: CreatePersonRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Create a new person, optionally assigning a set of existing faces to them."""
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")

    with get_db() as conn:
        try:
            cursor = conn.execute(
                "INSERT INTO persons (name, auto_clustered, face_count) VALUES (?, 0, 0)",
                (name,),
            )
            person_id = cursor.lastrowid

            face_count = 0
            if body.face_ids:
                result = reassign_faces_to_person(conn, person_id, body.face_ids)
                face_count = result["face_count"]

            conn.commit()
            invalidate_stats_cache()
            return {"id": person_id, "name": name, "face_count": face_count}
        except LookupError as e:
            conn.rollback()
            raise HTTPException(status_code=404, detail=str(e))
        except HTTPException:
            raise
        except sqlite3.Error:
            logger.exception("Database error creating person '%s'", name)
            conn.rollback()
            raise HTTPException(status_code=500, detail='Internal server error')


@router.post("/api/persons/{person_id}/assign_faces")
def api_assign_faces_batch(
    person_id: int,
    body: AssignFacesRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Bulk-assign a set of faces to a person. Empties old persons are auto-deleted."""
    with get_db() as conn:
        try:
            target = conn.execute(
                "SELECT id FROM persons WHERE id = ?", (person_id,)
            ).fetchone()
            if not target:
                raise HTTPException(status_code=404, detail="Target person not found")

            result = reassign_faces_to_person(conn, person_id, body.face_ids)
            face_count = result["face_count"]
            deleted_persons = result["deleted_persons"]

            conn.commit()
            invalidate_stats_cache()
            return {
                "success": True,
                "person_id": person_id,
                "assigned_count": len(body.face_ids),
                "face_count": face_count,
                "deleted_persons": deleted_persons,
            }
        except LookupError as e:
            conn.rollback()
            raise HTTPException(status_code=404, detail=str(e))
        except HTTPException:
            raise
        except sqlite3.Error:
            logger.exception("Database error assigning faces to person %d", person_id)
            conn.rollback()
            raise HTTPException(status_code=500, detail='Internal server error')


@router.post("/api/persons/{person_id}/split")
def api_split_person(
    person_id: int,
    body: SplitPersonRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Split a subset of a person's faces off into a brand-new person.

    Every ``face_id`` must currently belong to ``person_id``; any that don't
    are rejected with 400. The source person's face_count is recomputed and,
    if it drops to zero, the source person is deleted.
    """
    # Dedup so the membership check isn't tripped by repeated ids.
    face_ids = list(dict.fromkeys(body.face_ids))
    name = body.name.strip() if body.name else None

    with get_db() as conn:
        try:
            placeholders = ",".join("?" * len(face_ids))
            rows = conn.execute(
                f"SELECT id FROM faces WHERE id IN ({placeholders}) AND person_id = ?",
                [*face_ids, person_id],
            ).fetchall()
            owned = {row["id"] for row in rows}
            foreign = [fid for fid in face_ids if fid not in owned]
            if foreign:
                raise HTTPException(
                    status_code=400,
                    detail=f"face_ids do not belong to person {person_id}: {foreign}",
                )

            # Create the destination person, then move the faces onto it.
            # reassign_faces_to_person recomputes both new and source counts and
            # auto-deletes the source if it is emptied.
            cursor = conn.execute(
                "INSERT INTO persons (name, auto_clustered, face_count) VALUES (?, 0, 0)",
                (name,),
            )
            new_person_id = cursor.lastrowid
            result = reassign_faces_to_person(conn, new_person_id, face_ids)
            new_count = result["face_count"]
            source_deleted = person_id in result["deleted_persons"]

            if source_deleted:
                source_count = 0
            else:
                row = conn.execute(
                    "SELECT face_count FROM persons WHERE id = ?", (person_id,)
                ).fetchone()
                source_count = row[0] if row else 0

            conn.commit()
            invalidate_stats_cache()
            return {
                "success": True,
                "new_person_id": new_person_id,
                "name": name,
                "new_count": new_count,
                "source_count": source_count,
            }
        except HTTPException:
            conn.rollback()
            raise
        except sqlite3.Error:
            logger.exception("Database error splitting person %d", person_id)
            conn.rollback()
            raise HTTPException(status_code=500, detail='Internal server error')


@router.post("/api/persons/{person_id}/hide")
def api_hide_person(
    person_id: int,
    user: CurrentUser = Depends(require_edition),
):
    """Hide a person cluster from the persons list, filters, and merge suggestions."""
    return _set_person_hidden(person_id, True)


@router.post("/api/persons/{person_id}/unhide")
def api_unhide_person(
    person_id: int,
    user: CurrentUser = Depends(require_edition),
):
    """Unhide a previously hidden person cluster."""
    return _set_person_hidden(person_id, False)


def _set_person_hidden(person_id: int, hidden: bool):
    """Shared hide/unhide logic: flip the is_hidden flag on a person row."""
    with get_db() as conn:
        try:
            conn.execute(
                "UPDATE persons SET is_hidden = ? WHERE id = ?",
                (1 if hidden else 0, person_id),
            )
            conn.commit()
            invalidate_stats_cache()
            return {"success": True, "is_hidden": hidden}
        except sqlite3.Error:
            logger.exception("Database error setting is_hidden on person %d", person_id)
            conn.rollback()
            raise HTTPException(status_code=500, detail='Internal server error')
