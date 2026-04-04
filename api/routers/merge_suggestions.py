"""
Merge suggestions API router -- face merge group analysis.

"""

from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth import CurrentUser, require_authenticated
from api.config import VIEWER_CONFIG
from db import DEFAULT_DB_PATH

router = APIRouter(tags=["merge_suggestions"])


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

    return {"suggestions": suggestions}
