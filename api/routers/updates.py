"""Upstream release check, for the viewer's "a newer Facet is out" notice.

Edition-gated: knowing an upgrade is available is only actionable for whoever
administers the install, and everyone else would only be nagged about something
they cannot do. The check itself, its caching and its failure handling live in
``api.updates``.
"""

from fastapi import APIRouter, Depends, Query

from api.auth import CurrentUser, require_edition
from api.database import get_db
from api.updates import check_for_update

router = APIRouter(tags=["updates"])


@router.get("/api/updates/check")
async def api_check_updates(
    force: bool = Query(False),
    user: CurrentUser = Depends(require_edition),
):
    """Whether a newer Facet release exists than the one running.

    Answers from the cached result within the configured interval, so polling
    this endpoint cannot turn into polling GitHub. `force` re-checks now, for the
    operator who has just upgraded and wants the banner to go away.
    """
    with get_db() as conn:
        return check_for_update(conn, force=force)
