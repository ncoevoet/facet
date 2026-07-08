"""
Merge suggestions API router -- face merge group analysis.

"""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth import CurrentUser, require_authenticated
from api.config import VIEWER_CONFIG, is_multi_user_enabled
from api.database import get_db
from api.db_helpers import get_visibility_clause
from db import DEFAULT_DB_PATH

router = APIRouter(tags=["merge_suggestions"])


def _visible_person_ids(user: CurrentUser):
    """Set of person ids the caller may see, or None when no scoping applies.

    Returns None outside multi-user mode (an authenticated user sees the whole
    library); in multi-user mode it restricts to persons with a face in a photo
    within the caller's directories.
    """
    if not is_multi_user_enabled():
        return None
    vis_sql, vis_params = get_visibility_clause(
        user.user_id if user else None, table_alias='p'
    )
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT DISTINCT f.person_id FROM faces f "
            f"JOIN photos p ON p.path = f.photo_path "
            f"WHERE f.person_id IS NOT NULL AND {vis_sql}",
            vis_params,
        ).fetchall()
    return {r[0] for r in rows}


def _load_rejected_pairs():
    """Return the set of (a, b) person pairs (a < b) the user has dismissed.

    Defensive: returns an empty set if the table is absent so suggestions are
    simply unfiltered rather than erroring.
    """
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT person_a_id, person_b_id FROM rejected_merge_suggestions"
            ).fetchall()
        return {(row[0], row[1]) for row in rows}
    except sqlite3.Error:
        return set()


@router.get("/api/merge_suggestions")
def get_merge_suggestions(
    threshold: float = Query(0.6, ge=0.0, le=1.0),
    user: CurrentUser = Depends(require_authenticated),
):
    """Return merge suggestions as pairwise person comparisons."""
    # Check if feature is enabled
    if not VIEWER_CONFIG.get("features", {}).get("show_merge_suggestions", True):
        raise HTTPException(status_code=403, detail="Merge suggestions feature is disabled")

    # Lazy import only when feature is used
    from faces import get_merge_groups

    groups = get_merge_groups(DEFAULT_DB_PATH, threshold)

    # Convert groups to pairwise suggestions for the Angular component
    suggestions = []
    for group in groups:
        persons = group.get("persons", [])
        similarity = group.get("avg_similarity", 0.0)
        # Create a pairwise suggestion for each adjacent pair in the group
        for i in range(len(persons) - 1):
            suggestions.append({
                "person1": {
                    "id": persons[i]["id"],
                    "name": persons[i].get("name"),
                    "face_count": persons[i].get("face_count", 0),
                },
                "person2": {
                    "id": persons[i + 1]["id"],
                    "name": persons[i + 1].get("name"),
                    "face_count": persons[i + 1].get("face_count", 0),
                },
                "similarity": similarity,
            })

    # Drop pairs the user has already dismissed so they stop reappearing.
    rejected = _load_rejected_pairs()
    if rejected:
        suggestions = [
            s for s in suggestions
            if tuple(sorted((s["person1"]["id"], s["person2"]["id"]))) not in rejected
        ]

    visible = _visible_person_ids(user)
    if visible is not None:
        suggestions = [
            s for s in suggestions
            if s["person1"]["id"] in visible and s["person2"]["id"] in visible
        ]

    return {"suggestions": suggestions}
