"""Faces that look like a given person, scored against the person's centroid.

A bounded read: the candidate faces are counted first and refused above ``MAX_FACE_SCAN``,
then streamed in chunks, so a library of any size cannot make one request load every embedding.
"""

import logging
import time
from typing import Literal, Optional

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.auth import CurrentUser, require_authenticated
from api.database import get_db
from api.db_helpers import (
    get_visibility_clause, is_unnamed, person_unnamed_clause, person_visibility_exists, select_in_chunks)
from api.models.culling import PossibleFacesResponse
from db.embedding_space import ARCFACE_MODEL, expected_dim, tag_matches
from db.schema import person_not_hidden_clause

logger = logging.getLogger(__name__)

router = APIRouter(tags=["faces"])

# What one scan may cost: the budget the tool waits for, and the embeddings it may stream.
FACE_SCAN_TIMEOUT_S = 120
FACE_SCAN_ROWS_PER_S = 1600
MAX_FACE_SCAN = int(FACE_SCAN_TIMEOUT_S * FACE_SCAN_ROWS_PER_S)
CHUNK_ROWS = 2000
KEEP_FACTOR = 4
DEFAULT_MIN_SIMILARITY = 0.30
DEFAULT_LIMIT = 30
MAX_LIMIT = 100
FLOAT_BYTES = 4
SCOPES = ("unassigned", "unnamed", "other_persons", "all")
# Who owns a candidate face: in no group, in a group nobody has named, or in a named person.
OWNERS = ("ungrouped", "unnamed_group", "named")
MAX_SIMILAR_GROUPS = 10

# ``unnamed`` is every face without a name: in no cluster, or in a cluster nobody has named
# yet. ``unassigned`` is the narrower "in no cluster at all".
_SCOPE_SQL = {
    "unassigned": "f.person_id IS NULL",
    "unnamed": f"(f.person_id IS NULL OR (f.person_id != ? AND {person_unnamed_clause('pe')}))",
    "other_persons": "f.person_id IS NOT NULL AND f.person_id != ?",
    "all": "(f.person_id IS NULL OR f.person_id != ?)",
}


def _candidate_filter(person_id: int, scope: str, user_id, path_prefix: Optional[str],
                      date_from: Optional[str], date_to: Optional[str]) -> tuple[str, str, list]:
    """``(from_sql, where_sql, params)`` selecting the faces a scan may count and read.

    The caller's photo visibility and the hidden-person rule are part of the SQL, so the counts
    reported only ever cover faces the caller may see. Without a join the plain scopes are
    answered from ``idx_faces_person`` (and ``idx_faces_person_photo`` for ``path_prefix``) alone.
    """
    clauses = [_SCOPE_SQL[scope]]
    params: list = [person_id] if scope != "unassigned" else []
    from_sql = "faces f"
    if scope != "unassigned":
        from_sql += " LEFT JOIN persons pe ON pe.id = f.person_id"
        clauses.append(f"(pe.id IS NULL OR {person_not_hidden_clause('pe')})")
    if path_prefix:
        norm = path_prefix.replace('\\', '/').rstrip('/') + '/'
        clauses.append("REPLACE(f.photo_path, '\\', '/') LIKE ? ESCAPE '\\'")
        params.append(norm.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%')
    vis_sql, vis_params = get_visibility_clause(user_id, 'ph')
    if date_from or date_to or vis_sql != '1=1':
        from_sql += " JOIN photos ph ON ph.path = f.photo_path"
        if vis_sql != '1=1':
            clauses.append(vis_sql)
            params.extend(vis_params)
    if date_from or date_to:
        expr = "DATE(REPLACE(SUBSTR(ph.date_taken,1,10),':','-'))"
        for bound, op in ((date_from, ">="), (date_to, "<=")):
            if bound:
                clauses.append(f"{expr} {op} ?")
                params.append(bound)
    return from_sql, " AND ".join(clauses), params


def _named_person_ids(conn) -> np.ndarray:
    """Ids of every person with a non-blank name: the ``named`` owner class."""
    return np.fromiter(
        (row[0] for row in conn.execute(
            f"SELECT id FROM persons WHERE NOT {person_unnamed_clause('persons')}")),
        dtype=np.int64)


def _owner_codes(person_ids: np.ndarray, named_ids: np.ndarray) -> np.ndarray:
    """Index into ``OWNERS`` per face; a NULL ``person_id`` arrives as -1."""
    codes = np.where(person_ids < 0, 0, 1)
    codes[np.isin(person_ids, named_ids)] = 2
    return codes


def _top_indices(sims: np.ndarray, indices: np.ndarray, keep: int) -> np.ndarray:
    """The ``keep`` entries of ``indices`` with the highest ``sims``."""
    if len(indices) <= keep:
        return indices
    return indices[np.argpartition(-sims[indices], keep - 1)[:keep]]


def _scan(conn, from_sql: str, where_sql: str, params: list, centroid: np.ndarray, dim: int,
          min_similarity: float, keep: int, owners: frozenset = frozenset(OWNERS), per_owner: bool = False) -> dict:
    """Stream the candidates and score them against ``centroid``.

    Returns ``scanned``, the best ``keep`` ``ids`` / ``sims`` among faces whose owner is in
    ``owners`` (filtered here, before the keep cut, so a narrow owner set is never starved by
    better faces it excludes; with ``per_owner`` the cut is ``keep`` per owner class instead of
    overall), the per-owner ``counts`` over every scanned face at or above
    ``min_similarity`` whatever ``owners`` says, and ``best``, the top similarity of all.
    """
    named_ids = _named_person_ids(conn)
    allowed = np.array([OWNERS.index(o) for o in owners], dtype=np.int64)
    cursor = conn.execute(
        f"SELECT f.id, f.embedding, f.person_id FROM {from_sql} WHERE {where_sql} "
        "AND length(f.embedding) = ?",
        [*params, dim * FLOAT_BYTES])
    best_ids = np.empty(0, dtype=np.int64)
    best_sims = np.empty(0, dtype=np.float32)
    best_codes = np.empty(0, dtype=np.int64)
    counts = np.zeros(len(OWNERS), dtype=np.int64)
    best = None
    scanned = 0
    while True:
        chunk = cursor.fetchmany(CHUNK_ROWS)
        if not chunk:
            break
        scanned += len(chunk)
        ids = np.fromiter((row[0] for row in chunk), dtype=np.int64, count=len(chunk))
        person_ids = np.fromiter((-1 if row[2] is None else row[2] for row in chunk),
                                 dtype=np.int64, count=len(chunk))
        matrix = np.frombuffer(b"".join(row[1] for row in chunk), dtype=np.float32).reshape(len(chunk), dim)
        sims = (matrix @ centroid) / (np.linalg.norm(matrix, axis=1) + 1e-10)
        chunk_best = float(sims.max())
        best = chunk_best if best is None else max(best, chunk_best)
        codes = _owner_codes(person_ids, named_ids)
        above = sims >= min_similarity
        counts += np.bincount(codes[above], minlength=len(OWNERS))
        hit = above & np.isin(codes, allowed)
        best_ids = np.concatenate([best_ids, ids[hit]])
        best_sims = np.concatenate([best_sims, sims[hit].astype(np.float32)])
        best_codes = np.concatenate([best_codes, codes[hit]])
        if per_owner:
            kept = np.concatenate([_top_indices(best_sims, np.flatnonzero(best_codes == code), keep)
                                   for code in allowed]).astype(np.int64)
            best_ids, best_sims, best_codes = best_ids[kept], best_sims[kept], best_codes[kept]
        elif len(best_ids) > keep:
            top = np.argpartition(-best_sims, keep - 1)[:keep]
            best_ids, best_sims, best_codes = best_ids[top], best_sims[top], best_codes[top]
    return {"scanned": scanned, "ids": best_ids, "sims": best_sims,
            "counts": dict(zip(OWNERS, (int(c) for c in counts))), "best": best}


def _parse_owners(owners: Optional[str]) -> frozenset:
    if owners is None:
        return frozenset(OWNERS)
    tokens = [token.strip() for token in owners.split(",")]
    if not tokens or any(token not in OWNERS for token in tokens):
        raise HTTPException(status_code=422, detail=f"owners must be a comma list drawn from {', '.join(OWNERS)}")
    return frozenset(tokens)


def _similar_groups(conn, person_id: int, user_id, model: str, dim: int,
                    centroid: np.ndarray, min_similarity: float) -> list[dict]:
    """Other visible, non-hidden persons whose centroid looks like this one's, best first.

    Centroid against centroid, read from ``persons`` alone, so it costs one row per person
    rather than one per face. Only centroids of the same embedding model compare.
    """
    fragment, params = person_visibility_exists(user_id, 'p.id')
    rows = conn.execute(
        "SELECT p.id, p.name, p.face_count, p.centroid, p.centroid_model FROM persons p "
        f"WHERE p.id != ? AND p.centroid IS NOT NULL AND length(p.centroid) = ? "
        f"AND {person_not_hidden_clause('p')}" + (f" AND {fragment}" if fragment else ""),
        [person_id, dim * FLOAT_BYTES, *params]).fetchall()
    groups = []
    for row in rows:
        if (row[4] or ARCFACE_MODEL) != model:
            continue
        other = np.frombuffer(row[3], dtype=np.float32)
        similarity = float(other @ centroid / (np.linalg.norm(other) + 1e-10))
        if similarity >= min_similarity:
            name = None if is_unnamed(row[1]) else row[1].strip()
            groups.append({"person_id": row[0], "name": name, "face_count": row[2] or 0,
                           "similarity": round(similarity, 4)})
    groups.sort(key=lambda group: (-group["similarity"], group["person_id"]))
    return groups[:MAX_SIMILAR_GROUPS]


@router.get("/api/person/{person_id}/possible_faces", response_model=PossibleFacesResponse,
            response_model_exclude_unset=True,
            responses={404: {"description": "Person not found"},
                       412: {"description": "No usable centroid, or the scan is over MAX_FACE_SCAN faces"}})
def api_person_possible_faces(
    person_id: int,
    scope: Literal["unassigned", "unnamed", "other_persons", "all"] = "unassigned",
    min_similarity: float = Query(DEFAULT_MIN_SIMILARITY, ge=0.0, le=1.0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    path_prefix: Optional[str] = Query(None, max_length=4096),
    date_from: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    date_to: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    owners: Optional[str] = Query(
        None, max_length=64,
        description="Comma list drawn from ungrouped, unnamed_group, named: keep only faces with "
                    "such an owner. Applied before the limit; counts ignore it."),
    per_owner: bool = Query(
        False,
        description="Apply ``limit`` to each owner class (ungrouped, unnamed_group, named) instead "
                    "of to the whole list: up to ``limit`` faces of each class, the combined list "
                    "sorted by similarity, descending. ``owners`` still selects the classes."),
    user: CurrentUser = Depends(require_authenticated),
):
    """Faces most like ``person_id``'s centroid, best first (same embedding model only).

    Besides the faces, the response says why the list looks the way it does: ``counts`` of
    the qualifying faces per owner class, ``best_similarity`` over everything scanned (so an
    empty list can say how close the closest face came), and ``similar_groups``, other persons
    whose centroid is close enough to merge wholesale. With ``per_owner`` the ``limit`` caps each
    owner class separately, so one scan can serve a client that filters by owner.
    """
    owner_set = _parse_owners(owners)
    user_id = user.user_id if user else None
    started = time.monotonic()
    with get_db() as conn:
        row = conn.execute(
            "SELECT centroid, centroid_model FROM persons WHERE id = ?", (person_id,)).fetchone()
        fragment, frag_params = person_visibility_exists(user_id, 'persons.id')
        visible = row is not None and (not fragment or conn.execute(
            f"SELECT 1 FROM persons WHERE id = ? AND {fragment}", [person_id, *frag_params]).fetchone())
        if not visible:
            raise HTTPException(status_code=404, detail="Person not found")
        if not row[0]:
            raise HTTPException(status_code=412, detail="This person has no centroid yet; run face clustering first")
        model = row[1] or ARCFACE_MODEL
        try:
            dim = expected_dim(model)
        except ValueError:
            raise HTTPException(status_code=412, detail="This person's centroid uses an unknown embedding model")
        centroid = np.frombuffer(row[0], dtype=np.float32)
        if len(centroid) != dim:
            raise HTTPException(status_code=412, detail="This person's centroid does not match its embedding model")
        centroid = centroid / (np.linalg.norm(centroid) + 1e-10)
        from_sql, where_sql, params = _candidate_filter(
            person_id, scope, user_id, path_prefix, date_from, date_to)
        candidates = conn.execute(
            f"SELECT COUNT(*) FROM {from_sql} WHERE {where_sql}", params).fetchone()[0]
        if candidates > MAX_FACE_SCAN:
            raise HTTPException(
                status_code=status.HTTP_412_PRECONDITION_FAILED,
                detail=(f"{candidates} faces would be scanned, over the ceiling of {MAX_FACE_SCAN}; "
                        "narrow the scan with scope, path_prefix, date_from or date_to"))
        scan = _scan(conn, from_sql, where_sql, params, centroid, dim,
                     min_similarity, KEEP_FACTOR * limit, owner_set, per_owner)
        similarity = {int(i): float(s) for i, s in zip(scan["ids"], scan["sims"])}
        faces = _resolve(conn, model, similarity)
        similar_groups = _similar_groups(conn, person_id, user_id, model, dim, centroid, min_similarity)
    faces.sort(key=lambda face: -face["similarity"])
    if per_owner:
        taken = dict.fromkeys(OWNERS, 0)
        capped = []
        for face in faces:
            if taken[face["owner"]] < limit:
                taken[face["owner"]] += 1
                capped.append(face)
        faces = capped
    logger.info("possible_faces person=%d scanned=%d kept=%d ms=%d", person_id, scan["scanned"], len(faces),
                (time.monotonic() - started) * 1000)
    best = scan["best"]
    return {"faces": faces if per_owner else faces[:limit], "faces_scanned": scan["scanned"], "candidates": candidates,
            "counts": scan["counts"], "best_similarity": None if best is None else round(best, 4),
            "similar_groups": similar_groups}


def _resolve(conn, model: str, similarity: dict[int, float]) -> list[dict]:
    """Attach photo, owner and model to the best faces; drop what is hidden."""
    if not similarity:
        return []
    rows = list(select_in_chunks(
        conn,
        "SELECT f.id, f.photo_path, f.person_id, f.embedding_model, pe.name "
        "FROM faces f LEFT JOIN persons pe ON pe.id = f.person_id "
        f"WHERE f.id IN ({{placeholders}}) AND (pe.id IS NULL OR {person_not_hidden_clause('pe')})",
        list(similarity)))
    return [{"face_id": r[0], "photo_path": r[1], "person_id": r[2], "person_name": r[4],
             "owner": _owner_of(r[2], r[4]),
             "similarity": round(similarity[r[0]], 4), "distance": round(1.0 - similarity[r[0]], 4)}
            for r in rows if tag_matches(r[3], model)]


def _owner_of(person_id, name) -> str:
    """The ``OWNERS`` class of one resolved face; the same rule as ``_owner_codes``."""
    if person_id is None:
        return "ungrouped"
    return "unnamed_group" if is_unnamed(name) else "named"
