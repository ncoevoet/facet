"""Personal ranker ("My Taste") status — surfaces training confidence + coverage.

Reads the metrics snapshot written by ``optimization.personal_ranker.train_ranker``
to ``stats_cache`` and pairs it with live coverage (how many embedded photos have
a global-scope ``learned_score``). Powers the gallery's "My Taste" confidence
indicator; the model, training and auto-retrain all live elsewhere.
"""

import json
from typing import Optional

from fastapi import APIRouter, Depends

from api.auth import CurrentUser, get_optional_user
from api.database import get_db
from optimization.personal_ranker import ranker_metrics_key

router = APIRouter(tags=["ranker"])


@router.get("/api/ranker/status")
async def api_ranker_status(user: Optional[CurrentUser] = Depends(get_optional_user)):
    """Training status for the global pooled personal ranker ("My Taste").

    ``coverage`` is the share of embedded photos that carry a global-scope
    ``learned_score`` (the sort the gallery exposes). The accuracy fields come
    from the last train's ``stats_cache`` snapshot and are ``null`` until the
    ranker has trained at least once.
    """
    with get_db() as conn:
        row = conn.execute(
            "SELECT value FROM stats_cache WHERE key = ?",
            (ranker_metrics_key(None, None),),
        ).fetchone()
        scored = conn.execute(
            "SELECT COUNT(*) FROM learned_scores WHERE user_id IS NULL AND category IS NULL"
        ).fetchone()[0]
        embedded = conn.execute(
            "SELECT COUNT(*) FROM photos WHERE clip_embedding IS NOT NULL"
        ).fetchone()[0]

    coverage = round(scored / embedded, 4) if embedded else 0.0
    metrics = {}
    if row and row[0]:
        try:
            metrics = json.loads(row[0])
        except (ValueError, TypeError):
            metrics = {}

    return {
        'trained': bool(metrics.get('trained')) and scored > 0,
        'gated': bool(metrics.get('gated')),
        'comparison_count': int(metrics.get('comparison_count') or 0),
        'coverage': coverage,
        'scored': scored,
        'embedded': embedded,
        'cv_accuracy': metrics.get('cv_accuracy'),
        'baseline_accuracy': metrics.get('baseline_accuracy'),
        'improvement_pp': metrics.get('improvement_pp'),
        'updated_at': metrics.get('updated_at'),
    }
