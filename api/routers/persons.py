"""
Persons API router -- person management.

"""

import logging
import sqlite3
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

from api.auth import CurrentUser, require_edition, require_authenticated
from api.config import VIEWER_CONFIG, invalidate_stats_cache
from api.database import get_async_db, get_db
from api.db_helpers import (
    assert_faces_visible, get_visibility_clause, reassign_faces_to_person, person_visibility_exists,
    person_unnamed_clause, select_in_chunks,
)
from db import person_not_hidden_clause
from db.embedding_space import ARCFACE_MODEL, active_embedding_model, tag_matches
from db.person_centroids import recompute_person_centroid
from api.models.culling import PersonsListResponse, PersonsNeedsNamingResponse, RenamePersonResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["persons"])

# Client-side cap: RECENT_LIMIT in person-assignment-history.service.ts.
MAX_RECENT_IDS = 12

_SORT_CLAUSES = {
    "name_asc": "ORDER BY COALESCE(p.name, '') ASC, p.face_count DESC",
    "name_desc": "ORDER BY COALESCE(p.name, '') DESC, p.face_count DESC",
    "count_asc": "ORDER BY p.face_count ASC, p.id",
    "count_desc": "ORDER BY p.face_count DESC, p.id",
    "quality_asc": "ORDER BY rep_quality ASC, p.id",
    "quality_desc": "ORDER BY rep_quality DESC, p.id",
}


# A person still waiting for a name: none, or only spaces. Shared by the
# needs-naming list and the persons list's ``named_only`` filter so the two
# partition the persons exactly.
_UNNAMED_SQL = person_unnamed_clause('p')

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
    # Additive, for the assistant tool: ``tolerant`` reports what it skipped instead of failing the
    # whole call, ``only_unassigned`` leaves faces another person already owns alone.
    only_unassigned: bool = False
    tolerant: bool = False

    @model_validator(mode='after')
    def _only_unassigned_needs_tolerant(self):
        if self.only_unassigned and not self.tolerant:
            raise ValueError("only_unassigned requires tolerant=true: the strict path moves every listed face")
        return self


class SplitPersonRequest(BaseModel):
    face_ids: List[int] = Field(min_length=1, max_length=500)
    name: Optional[str] = None


# --- Visibility guard ---

def _assert_person_visible(conn, user_id, person_id):
    """Raise 404 when ``person_id`` has no face on a photo the caller may see.

    A no-op outside multi-user mode. In multi-user mode it enforces the same
    per-directory isolation as the persons read surface so a directory-scoped
    edition user cannot rename, merge, delete or hide a person whose faces all
    live outside their directories. Returns 404 (never 403) so it never leaks
    the existence of an out-of-scope person, matching the read endpoints.
    """
    fragment, params = person_visibility_exists(user_id, 'p.id')
    if not fragment:
        return
    row = conn.execute(
        f"SELECT 1 FROM persons p WHERE p.id = ? AND {fragment}",
        [person_id, *params],
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Person not found")


def _assert_person_assignable(conn, user_id, person_id):
    """Guard an assign *target*: allow an empty person (one being populated), but
    reject a non-empty person with no face in the caller's directories, so a
    directory-scoped edition user cannot inject faces into a cluster they cannot
    see. A no-op outside multi-user mode. Returns 404 (never 403) to avoid leaking
    the existence of an out-of-scope person.
    """
    fragment, params = person_visibility_exists(user_id, 'p.id')
    if not fragment:
        return
    if not conn.execute(
        "SELECT 1 FROM faces WHERE person_id = ? LIMIT 1", (person_id,)
    ).fetchone():
        return
    row = conn.execute(
        f"SELECT 1 FROM persons p WHERE p.id = ? AND {fragment}",
        [person_id, *params],
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Person not found")


# --- Endpoints ---

@router.get("/api/persons", response_model=PersonsListResponse, response_model_exclude_unset=True)
async def list_persons(
    page: int = Query(1, ge=1),
    per_page: int = Query(48, ge=1, le=200),
    search: str = Query(""),
    sort: str = Query("count_desc", pattern="^(count_asc|count_desc|quality_asc|quality_desc|name_asc|name_desc|assignment)$"),
    include_hidden: bool = Query(False),
    recent_ids: str = Query("", max_length=MAX_RECENT_IDS * 16 + MAX_RECENT_IDS - 1),
    named_only: bool = Query(False),
    hidden_only: bool = Query(False),
    user: CurrentUser = Depends(require_authenticated),
):
    """List all persons with pagination and search.

    Hidden persons (``is_hidden = 1``) are excluded by default; pass
    ``include_hidden=true`` to surface them.

    ``sort=assignment`` orders named candidates by the supplied recent IDs (at
    most 12), then by face count in visible photos, then name and ID. Recent IDs
    confer no visibility: hidden (even with include_hidden), deleted and
    inaccessible candidates stay out. In assignment order, ``face_count`` is
    computed from visible photos; other orders return the stored library count.
    ``named_only=true`` leaves out persons without a name, which the needs-naming
    list already shows.
    ``hidden_only=true`` returns the hidden ones alone (the persons page's Ignored
    section). It is ignored under ``sort=assignment``: the assignment rule wins,
    so hidden persons never become assignment candidates.
    """
    recent = []
    if recent_ids:
        tokens = recent_ids.split(',')
        if sort != 'assignment' or len(tokens) > MAX_RECENT_IDS or any(
            not token.isascii() or not token.isdecimal() or not 0 < int(token) <= 9007199254740991
            for token in tokens
        ):
            raise HTTPException(status_code=422, detail="recent_ids requires assignment order and at most 12 positive safe integer IDs")
        recent = list(dict.fromkeys(map(int, tokens)))
    order_params = []
    prefix = ''
    from_clause = 'FROM persons p'
    count_column = 'p.face_count'
    order_clause = _SORT_CLAUSES.get(sort, _SORT_CLAUSES["count_desc"])

    where_parts: list = []
    params: list = []
    visibility_params: list = []
    if sort == 'assignment':
        visibility, visibility_params = get_visibility_clause(user.user_id if user else None, 'visible_photos')
        prefix = f"""WITH visible_counts AS (
            SELECT visible_faces.person_id, COUNT(*) AS face_count
            FROM faces visible_faces JOIN photos visible_photos ON visible_faces.photo_path = visible_photos.path
            WHERE visible_faces.person_id IS NOT NULL AND {visibility}
            GROUP BY visible_faces.person_id
        ) """
        from_clause += ' LEFT JOIN visible_counts ON visible_counts.person_id = p.id'
        count_column = 'COALESCE(visible_counts.face_count, 0)'
        where_parts.append(f"NOT {_UNNAMED_SQL}")
        recent_order = ('CASE p.id ' + ' '.join(f'WHEN ? THEN {rank}' for rank in range(len(recent)))
                        + f' ELSE {len(recent)} END, ') if recent else ''
        order_params = recent
        order_clause = f"ORDER BY {recent_order}COALESCE(visible_counts.face_count, 0) DESC, p.name COLLATE NOCASE ASC, p.name ASC, p.id ASC"
    if hidden_only and sort != 'assignment':
        where_parts.append(f"NOT {person_not_hidden_clause('p')}")
    elif not include_hidden or sort == 'assignment':
        where_parts.append(person_not_hidden_clause('p'))
    if named_only:
        where_parts.append(f"NOT {_UNNAMED_SQL}")
    if search.strip():
        term = search.strip()
        numeric_id = int(term) if term.isascii() and term.isdecimal() and len(term) <= 19 else None
        if numeric_id is not None and numeric_id <= 9223372036854775807:
            where_parts.append("(p.id = ? OR p.name LIKE ?)")
            params.extend([numeric_id, f"%{term}%"])
        else:
            where_parts.append("p.name LIKE ?")
            params.append(f"%{term}%")
    vis_fragment, vis_params = person_visibility_exists(user.user_id if user else None, 'p.id')
    if vis_fragment:
        where_parts.append(vis_fragment)
        params.extend(vis_params)
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
            {prefix}SELECT p.id, p.name, p.representative_face_id, {count_column} AS face_count,
                   COALESCE(p.is_hidden, 0) as is_hidden,
                   CASE WHEN p.face_thumbnail IS NOT NULL THEN 1 ELSE 0 END as face_thumbnail,
                   (COALESCE(photos.eye_sharpness, 0) / 10.0 * 0.7 +
                    (COALESCE(photos.face_quality, 6.5) - 6.5) / 3.0 * 0.3) as rep_quality
            {from_clause}
            LEFT JOIN faces f ON p.representative_face_id = f.id
            LEFT JOIN photos ON f.photo_path = photos.path
            {where_clause}
            {order_clause}
            LIMIT ? OFFSET ?
        """, visibility_params + params + order_params + [per_page, offset])
        rows = await cur.fetchall()
        await cur.close()
        persons = [dict(row) for row in rows]

    return {"persons": persons, "total": total, "sort": sort}


@router.post("/api/persons/{person_id}/rename", response_model=RenamePersonResponse)
def rename_person(
    person_id: int,
    body: RenamePersonRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Rename a person (set or update their name).

    ``face_count`` is this person's own stored count, the same measure as each
    entry of ``same_name_persons``, so the viewer picks the largest merge target
    like with like. ``same_name_persons`` lists the other visible, non-hidden persons whose name is
    the same ignoring case and surrounding spaces, largest first, so the viewer can
    offer to merge clusters of one person that clustering split apart. Nothing is
    merged here: two different people may share a name.
    """
    user_id = user.user_id if user else None
    name = body.name.strip()
    with get_db() as conn:
        _assert_person_visible(conn, user_id, person_id)
        conn.execute("UPDATE persons SET name = ? WHERE id = ?", (name or None, person_id))
        conn.commit()
        same_name = _same_name_persons(conn, user_id, person_id, name) if name else []
        row = conn.execute("SELECT face_count FROM persons WHERE id = ?", (person_id,)).fetchone()
    invalidate_stats_cache()
    return {"success": True, "name": name or f"Person {person_id}",
            "face_count": (row[0] if row else 0) or 0, "same_name_persons": same_name}


def _same_name_persons(conn, user_id, person_id, name):
    """Other visible, non-hidden persons named ``name`` ignoring case, largest first.

    Compared with ``str.casefold`` in Python rather than SQLite's ``LOWER``, which
    folds ASCII only and would miss "ÉLODIE" against "élodie".
    """
    fragment, params = person_visibility_exists(user_id, 'p.id')
    rows = conn.execute(
        "SELECT p.id, p.name, p.face_count FROM persons p "
        f"WHERE p.id != ? AND p.name IS NOT NULL AND {person_not_hidden_clause('p')}"
        + (f" AND {fragment}" if fragment else ""),
        [person_id, *params],
    ).fetchall()
    key = name.casefold()
    matches = [
        {"id": r[0], "name": r[1], "face_count": r[2] or 0}
        for r in rows if r[1].strip().casefold() == key
    ]
    matches.sort(key=lambda m: (-m["face_count"], m["id"]))
    return matches


@router.post("/api/persons/merge")
def merge_persons_json(
    body: MergeRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Merge source person into target person (JSON body)."""
    return _do_merge(body.source_id, body.target_id, user.user_id if user else None)


@router.post("/api/persons/merge/{source_id}/{target_id}")
def merge_persons(
    source_id: int,
    target_id: int,
    user: CurrentUser = Depends(require_edition),
):
    """Merge source person into target person (path params)."""
    return _do_merge(source_id, target_id, user.user_id if user else None)


def _do_merge(source_id: int, target_id: int, user_id):
    """Shared merge logic."""
    if source_id == target_id:
        raise HTTPException(status_code=400, detail="Cannot merge a person into itself")

    with get_db() as conn:
        try:
            # faces.person_id has no foreign key, so a stale suggestion targeting
            # a deleted person would silently move faces to a dangling id and make
            # them vanish from the gallery. Validate both persons exist first.
            for pid in (source_id, target_id):
                if not conn.execute(
                    "SELECT 1 FROM persons WHERE id = ?", (pid,)
                ).fetchone():
                    raise HTTPException(status_code=404, detail="Person not found")
            _assert_person_visible(conn, user_id, source_id)
            _assert_person_visible(conn, user_id, target_id)
            # 1. Move all faces from source to target
            conn.execute("UPDATE faces SET person_id = ? WHERE person_id = ?",
                         (target_id, source_id))

            # 2. Update target face_count
            row = conn.execute("SELECT COUNT(*) FROM faces WHERE person_id = ?",
                               (target_id,)).fetchone()
            count = row[0] if row else 0
            conn.execute("UPDATE persons SET face_count = ? WHERE id = ?",
                         (count, target_id))

            # 3. Recompute the target's centroid from its now-larger face set so
            #    clustering and future merge suggestions match the merged person.
            recompute_person_centroid(conn, target_id)

            # 4. Delete source person
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

    user_id = user.user_id if user else None
    with get_db() as conn:
        try:
            for target_id, source_ids in groups.items():
                # No FK on faces.person_id: a stale suggestion could target a
                # deleted person and strand every folded face. Validate first.
                if not conn.execute(
                    "SELECT 1 FROM persons WHERE id = ?", (target_id,)
                ).fetchone():
                    raise HTTPException(status_code=404, detail=f"Person {target_id} not found")
                _assert_person_visible(conn, user_id, target_id)
                for source_id in source_ids:
                    if not conn.execute(
                        "SELECT 1 FROM persons WHERE id = ?", (source_id,)
                    ).fetchone():
                        raise HTTPException(status_code=404, detail=f"Person {source_id} not found")
                    _assert_person_visible(conn, user_id, source_id)
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
                # Recompute the surviving target's centroid over its merged faces.
                recompute_person_centroid(conn, target_id)
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
            _assert_person_visible(conn, user.user_id if user else None, person_id)
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

    user_id = user.user_id if user else None
    with get_db() as conn:
        try:
            for person_id in body.person_ids:
                _assert_person_visible(conn, user_id, person_id)
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


@router.get("/api/persons/needs_naming", response_model=PersonsNeedsNamingResponse, response_model_exclude_unset=True)
async def api_persons_needs_naming(
    min_faces: Optional[int] = Query(None, ge=0),
    user: CurrentUser = Depends(require_authenticated),
):
    """List unnamed, non-hidden persons with face_count >= min_faces (default from config).

    Unnamed means no name or a blank one, whether the person came from clustering or
    from a split, so every person still waiting for a name is listed here once.
    """
    if min_faces is None:
        try:
            min_faces = int(VIEWER_CONFIG.get('persons', {}).get('needs_naming_min_faces', 5))
        except (TypeError, ValueError):
            min_faces = 5

    vis_fragment, vis_params = person_visibility_exists(user.user_id if user else None, 'p.id')
    extra = f" AND {vis_fragment}" if vis_fragment else ""
    async with get_async_db() as conn:
        cur = await conn.execute(f"""
            SELECT p.id, p.name, p.representative_face_id, p.face_count,
                   CASE WHEN p.face_thumbnail IS NOT NULL THEN 1 ELSE 0 END as face_thumbnail
            FROM persons p
            WHERE {_UNNAMED_SQL} AND {person_not_hidden_clause('p')} AND p.face_count >= ?{extra}
            ORDER BY p.face_count DESC, p.id
        """, [min_faces, *vis_params])
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
                assert_faces_visible(conn, user.user_id if user else None, body.face_ids)
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


def _assign_tolerant(conn, user_id, person_id, body):
    """Assign what may be assigned and say what was not, inside the caller's transaction.

    An unknown id and a face on a photo the caller cannot see are both ``missing`` (answering
    differently would be an existence oracle). The rest are skipped by reason, and only the
    remainder is reassigned, so ``assigned_count`` is what really moved.
    """
    face_ids = list(dict.fromkeys(body.face_ids))
    vis_sql, vis_params = get_visibility_clause(user_id, table_alias='ph')
    found = {
        row[0]: row for row in select_in_chunks(
            conn,
            "SELECT f.id, f.person_id, f.embedding_model, pe.is_hidden FROM faces f "
            "JOIN photos ph ON ph.path = f.photo_path LEFT JOIN persons pe ON pe.id = f.person_id "
            f"WHERE f.id IN ({{placeholders}}) AND {vis_sql}", face_ids, after=vis_params)
    }
    target = conn.execute(
        "SELECT centroid, centroid_model FROM persons WHERE id = ?", (person_id,)).fetchone()
    model = (target[1] or ARCFACE_MODEL) if target and target[0] else active_embedding_model()
    report = {"missing": [], "already": [], "skipped_model": [], "skipped_hidden": [], "skipped_assigned": []}
    eligible = []
    for face_id in face_ids:
        row = found.get(face_id)
        if row is None:
            report["missing"].append(face_id)
        elif row[1] == person_id:
            report["already"].append(face_id)
        elif not tag_matches(row[2], model):
            report["skipped_model"].append(face_id)
        elif row[1] is not None and row[3]:
            report["skipped_hidden"].append(face_id)
        elif row[1] is not None and body.only_unassigned:
            report["skipped_assigned"].append(face_id)
        else:
            eligible.append(face_id)
    if eligible:
        moved = reassign_faces_to_person(conn, person_id, eligible)
        face_count, deleted = moved["face_count"], moved["deleted_persons"]
    else:
        row = conn.execute("SELECT face_count FROM persons WHERE id = ?", (person_id,)).fetchone()
        face_count, deleted = (row[0] if row else 0), []
    return {"assigned_count": len(eligible), "face_count": face_count, "deleted_persons": deleted, **report}


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

            _assert_person_assignable(conn, user.user_id if user else None, person_id)
            if body.tolerant:
                report = _assign_tolerant(conn, user.user_id if user else None, person_id, body)
                conn.commit()
                invalidate_stats_cache()
                return {"success": True, "person_id": person_id, **report}
            assert_faces_visible(conn, user.user_id if user else None, body.face_ids)
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
            _assert_person_visible(conn, user.user_id if user else None, person_id)
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
    return _set_person_hidden(person_id, True, user.user_id if user else None)


@router.post("/api/persons/{person_id}/unhide")
def api_unhide_person(
    person_id: int,
    user: CurrentUser = Depends(require_edition),
):
    """Unhide a previously hidden person cluster."""
    return _set_person_hidden(person_id, False, user.user_id if user else None)


def _set_person_hidden(person_id: int, hidden: bool, user_id):
    """Shared hide/unhide logic: flip the is_hidden flag on a person row."""
    with get_db() as conn:
        try:
            _assert_person_visible(conn, user_id, person_id)
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
