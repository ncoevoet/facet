"""
Merge suggestions API router -- face merge group analysis.

"""

import sqlite3
from collections import defaultdict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth import CurrentUser, require_authenticated
from api.config import VIEWER_CONFIG, is_multi_user_enabled, server_scoring_config
from api.database import get_db
from api.db_helpers import get_visibility_clause
from api.models.albums import MergeSuggestionsResponse

router = APIRouter(tags=["merge_suggestions"])

# A low threshold can clear tens of thousands of pairs; the response takes the
# most similar ones and reports whether any eligible pairs were omitted.
MAX_MERGE_SUGGESTIONS = 200
_SCORE_BLOCK_ROWS = 64


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
    """Return the top eligible pairs and whether the list was truncated.

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
        return [], False

    indices = {person["id"]: i for i, person in enumerate(persons)}
    dismissed_by_row = defaultdict(list)
    for a, b in _load_rejected_pairs():
        if a < b and a in indices and b in indices:
            i, j = sorted((indices[a], indices[b]))
            dismissed_by_row[i].append(j)

    centroids = np.stack([p["centroid"] for p in loaded]).astype(np.float64)
    limit = MAX_MERGE_SUGGESTIONS
    best = []
    eligible = 0
    # Score only the remaining suffix for each block. Scratch space grows
    # linearly with the visible set, and we retain at most two blocks' worth
    # of top results (2 * limit) while combining them.
    for start in range(0, len(persons) - 1, _SCORE_BLOCK_ROWS):
        stop = min(start + _SCORE_BLOCK_ROWS, len(persons) - 1)
        scores = centroids[start:stop] @ centroids[start + 1:].T
        hits = scores >= threshold
        for row, i in enumerate(range(start, stop)):
            hits[row, :row] = False  # Keep only pairs with j > i.
            if i in dismissed_by_row:
                hits[row, np.asarray(dismissed_by_row[i]) - start - 1] = False

        rows, cols = np.nonzero(hits)
        eligible += len(rows)
        values = scores[rows, cols]
        # Stable ordering within this block, then row/column order across
        # blocks for ties. A block's lower-ranked hits cannot enter the top K.
        for k in np.argsort(-values, kind="stable")[:limit]:
            best.append((-float(values[k]), start + rows[k], start + 1 + cols[k]))
        best.sort()
        del best[limit:]

    return [
        {"person1": persons[i], "person2": persons[j], "similarity": -score}
        for score, i, j in best
    ], eligible > limit


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
    suggestions, truncated = _pairwise_suggestions(threshold, visible=visible)
    if visible is not None:
        suggestions = [
            s for s in suggestions
            if s["person1"]["id"] in visible and s["person2"]["id"] in visible
        ]

    return {"suggestions": suggestions, "threshold": threshold, "truncated": truncated}
