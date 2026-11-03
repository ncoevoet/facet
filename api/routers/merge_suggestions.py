"""
Merge suggestions API router -- face merge group analysis.

"""

import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth import CurrentUser, require_authenticated
from api.config import VIEWER_CONFIG, is_multi_user_enabled, server_scoring_config
from api.database import get_db
from api.db_helpers import get_visibility_clause
from api.models.albums import MergeSuggestionsResponse

router = APIRouter(tags=["merge_suggestions"])

# A low threshold can clear tens of thousands of pairs; the response takes the
# most similar ones and leaves the rest to a stricter slider.
MAX_MERGE_SUGGESTIONS = 200


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


def _pairwise_suggestions(threshold, visible=None):
    """Merge suggestions as true pairwise person comparisons.

    Loads every non-hidden person's centroid and emits each person pair whose
    OWN centroid cosine similarity clears ``threshold``, labelled with that
    pair's real similarity. ``visible`` optionally restricts scoring to persons
    the caller may see -- done here, before the quadratic work, not after it.

    Replaces a union-find grouping that emitted the *adjacent* pairs of a
    transitively-connected group and stamped every one with the group's average
    similarity -- so a pair merely linked through a chain (A~B~C, with A and C
    themselves dissimilar) was shown as a confident match and an 'Accept all'
    then merged different people irreversibly.
    """
    import numpy as np
    from db.person_centroids import load_person_centroids

    with get_db() as conn:
        loaded = load_person_centroids(conn, include_hidden=False)

    if visible is not None:
        loaded = [p for p in loaded if p['id'] in visible]

    persons = [{k: p[k] for k in ('id', 'name', 'face_count')} for p in loaded]
    if len(persons) < 2:
        return []

    # One matmul replaces the O(n^2) Python loop of np.dot calls: at a few
    # thousand clusters that loop costs seconds of CPU on every request.
    centroids = np.stack([np.asarray(p['centroid'], dtype=np.float64) for p in loaded])
    similarities = centroids @ centroids.T

    upper_i, upper_j = np.triu_indices(len(persons), k=1)
    pair_similarities = similarities[upper_i, upper_j]
    hits = np.nonzero(pair_similarities >= threshold)[0]
    # Most similar first, capped so a low threshold cannot serialize the whole
    # quadratic hit set into one response.
    hits = hits[np.argsort(-pair_similarities[hits])][:MAX_MERGE_SUGGESTIONS]

    return [
        {
            "person1": persons[upper_i[k]],
            "person2": persons[upper_j[k]],
            "similarity": float(pair_similarities[k]),
        }
        for k in hits
    ]


@router.get(
    "/api/merge_suggestions",
    response_model=MergeSuggestionsResponse,
    response_model_exclude_unset=True,
)
def get_merge_suggestions(
    threshold: Optional[float] = Query(None, ge=0.0, le=1.0),
    user: CurrentUser = Depends(require_authenticated),
):
    """Return merge suggestions as pairwise person comparisons.

    Without ``threshold`` the active embedding model's ``merge_threshold`` from
    ``face_clustering.thresholds_by_model`` applies.
    """
    # Check if feature is enabled
    if not VIEWER_CONFIG.get("features", {}).get("show_merge_suggestions", True):
        raise HTTPException(status_code=403, detail="Merge suggestions feature is disabled")

    if threshold is None:
        threshold = server_scoring_config().get_face_clustering_settings()['merge_threshold']

    # Scoped users only ever see pairs within their visible set: restricting the
    # persons before the quadratic scoring is the difference between scoring the
    # caller's library and scoring the whole installation and throwing most of it
    # away. The post-filter below stays as the contract guard, so a caller keeps
    # its guarantee regardless of what _pairwise_suggestions does with the set.
    visible = _visible_person_ids(user)
    suggestions = _pairwise_suggestions(threshold, visible=visible)
    if visible is not None:
        suggestions = [
            s for s in suggestions
            if s["person1"]["id"] in visible and s["person2"]["id"] in visible
        ]

    # Drop pairs the user has already dismissed so they stop reappearing.
    rejected = _load_rejected_pairs()
    if rejected:
        suggestions = [
            s for s in suggestions
            if tuple(sorted((s["person1"]["id"], s["person2"]["id"]))) not in rejected
        ]

    return {"suggestions": suggestions, "threshold": threshold}
