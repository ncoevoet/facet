"""Upstream release check, for the viewer's "a newer Facet is out" notice.

Edition-gated: knowing an upgrade is available is only actionable for whoever
administers the install, and everyone else would only be nagged about something
they cannot do. The check itself, its caching and its failure handling live in
``api.updates``.
"""

import asyncio

from fastapi import APIRouter, Depends, Query

from api.auth import CurrentUser, require_edition
from api.database import get_db
from api.models.scan import UpdateCheckResponse
from api.updates import check_for_update

router = APIRouter(tags=["updates"])


def _check_off_the_loop(force):
    """Open the connection and run the check on the calling worker thread.

    ``get_db`` hands back a plain ``sqlite3`` connection, which belongs to the
    thread that created it, so the whole block is offloaded rather than the
    check alone.
    """
    with get_db() as conn:
        return check_for_update(conn, force=force)


@router.get("/api/updates/check", response_model=UpdateCheckResponse, response_model_exclude_unset=True)
async def api_check_updates(
    force: bool = Query(False),
    user: CurrentUser = Depends(require_edition),
):
    """Whether a newer Facet release exists than the one running.

    Answers from the cached result within the configured interval, so polling
    this endpoint cannot turn into polling GitHub. `force` re-checks now, for the
    operator who has just upgraded and wants the banner to go away.

    Run off the event loop: a cache miss makes a blocking outbound request, and
    holding the loop for its timeout would stall every other request the viewer
    is serving.
    """
    return await asyncio.to_thread(_check_off_the_loop, force)
