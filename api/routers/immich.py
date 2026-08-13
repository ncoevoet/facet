"""Inbound Immich webhook receiver (static token auth, anonymous).

Immich v3's workflow "webhook" action POSTs an asset payload to a URL with a
caller-chosen auth header. This endpoint is the receiving half of Facet's
outbound push (``sync/immich.py``): an asset Facet already knows and has scored
gets its rating/favorite pushed straight back through the same client, and one
Facet has never seen is remembered in a bounded, deduplicated pending list
(``stats_cache``) so the next ``--immich-sync`` reports the gap.

It never triggers a scan. A webhook is an unauthenticated-by-session HTTP call
from another daemon; letting one spawn GPU work would hand any token holder a
denial-of-service lever, so the pending list is deliberately inert data.

Access is a shared secret read from the environment: ``immich.webhook.token_env``
names the variable and an unset or empty variable disables the endpoint (404),
the same "empty means the whole feature 404s" idiom as ``frame.tokens`` and
``upload.username``. The secret itself never appears in ``scoring_config.json``.
"""

import logging
import os

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from api.token_auth import require_static_token

logger = logging.getLogger(__name__)

router = APIRouter(tags=["immich"])

WEBHOOK_PATH = "/api/immich/webhook"

_FEATURE = "Immich webhook"

_DEFAULT_HEADER = "x-facet-token"
_BEARER_SCHEME = "bearer"
_MAX_NESTING = 4
_SHAPE_KEY_LIMIT = 10
# One delivery may cost at most this many outbound Immich calls. Immich fires
# one asset per workflow run, so this only ever trips on a malformed or hostile
# body — and it is the server, not the caller, that decides the ceiling.
_MAX_ASSETS_PER_DELIVERY = 100

_ASSET_CONTAINER_KEYS = ("asset", "assets", "data", "items")
_ORIGINAL_PATH_KEY = "originalPath"

_STATUS_ACCEPTED = 202
_STATUS_NO_CONTENT = 204


def _immich_config() -> dict:
    from api.config import _FULL_CONFIG

    return _FULL_CONFIG.get("immich", {}) or {}


def _full_config() -> dict:
    from api.config import _FULL_CONFIG

    return _FULL_CONFIG


def _expected_token(webhook_cfg: dict) -> str:
    """The configured secret, read from the environment at request time.

    ``token_env`` holds the *name* of the variable, never the value — so the
    secret stays out of ``scoring_config.json`` (which is world-readable and
    rewritten in place by several endpoints).
    """
    env_name = str(webhook_cfg.get("token_env", "") or "").strip()
    if not env_name:
        return ""
    return os.environ.get(env_name, "").strip()


def _provided_token(request: Request, webhook_cfg: dict) -> str:
    """Read the caller's token from the configured header or a Bearer header.

    Immich lets the workflow action name its own auth header, so the header
    name is configurable; ``Authorization: Bearer`` is accepted too for
    proxies and UIs that only offer that one.
    """
    header_name = str(webhook_cfg.get("header", "") or _DEFAULT_HEADER)
    token = (request.headers.get(header_name) or "").strip()
    if token:
        return token
    scheme, _, param = (request.headers.get("authorization") or "").partition(" ")
    if scheme.lower() == _BEARER_SCHEME:
        return param.strip()
    return ""


def _iter_assets(payload, depth: int = 0):
    """Yield the asset dicts out of whatever shape the workflow action posted.

    Immich's webhook body is not a stable published contract, so anything
    carrying an ``originalPath`` counts: a bare asset, ``{"asset": {...}}``, a
    list of assets, or any of those nested under ``data`` / ``items`` /
    ``assets``. Recursion is depth-capped so a deeply nested body cannot
    exhaust the stack.
    """
    if depth > _MAX_NESTING:
        return
    if isinstance(payload, list):
        for entry in payload:
            yield from _iter_assets(entry, depth + 1)
        return
    if not isinstance(payload, dict):
        return
    if payload.get(_ORIGINAL_PATH_KEY):
        yield payload
        return
    for key in _ASSET_CONTAINER_KEYS:
        if key in payload:
            yield from _iter_assets(payload[key], depth + 1)


def _describe_shape(payload) -> str:
    """A loggable summary of an unrecognised body — keys only, never values."""
    if isinstance(payload, dict):
        return f"object keys={sorted(payload)[:_SHAPE_KEY_LIMIT]}"
    if isinstance(payload, list):
        return f"array of {len(payload)}"
    return type(payload).__name__


def _map_entries(assets: list, path_map: list, counts: dict) -> list:
    """``[(facet_path, asset_id)]`` for the assets this map can place.

    One that maps nowhere is tallied as unmatched right here and never reaches
    the push — it has no Facet path to push to.
    """
    from sync.immich import map_immich_path

    entries = []
    for asset in assets:
        original_path = str(asset.get(_ORIGINAL_PATH_KEY) or "")
        facet_path = map_immich_path(original_path, path_map)
        if not facet_path:
            counts["unmatched"] += 1
            logger.warning("Immich webhook: %s matches no immich.path_map prefix",
                           original_path)
            continue
        asset_id = asset.get("id") if isinstance(asset.get("id"), str) else None
        entries.append((facet_path, asset_id))
    return entries


def _process_assets(assets: list) -> dict:
    """Push what Facet knows, remember what it does not. Blocking; runs off-loop.

    The whole delivery goes through ONE :func:`~sync.immich.push_photo_updates`
    call and at most one pending-list write: the per-asset variants each opened
    their own connections and re-read the whole synced-state blob, so an N-asset
    delivery cost O(N) round trips of a document that grows with the library.

    Failure isolation survives that batching — the primitive returns a result
    per asset, so one dropped socket or unreadable row is counted, logged with
    its traceback, and the rest of the delivery still lands. Returns
    per-delivery counts: every key tallies assets from *this* request, never
    the size of the persisted pending list.
    """
    from db import DEFAULT_DB_PATH
    from sync.immich import (
        DEFAULT_MAX_PENDING, PUSH_ERRORS, RESULT_FAILED, RESULT_PUSHED,
        RESULT_SKIPPED, RESULT_UNKNOWN, push_photo_updates, record_pending_paths,
    )

    config = _full_config()
    immich_cfg = config.get("immich", {}) or {}
    webhook_cfg = immich_cfg.get("webhook", {}) or {}
    path_map = immich_cfg.get("path_map", []) or []
    max_pending = int(webhook_cfg.get("max_pending", DEFAULT_MAX_PENDING) or DEFAULT_MAX_PENDING)
    counts = {"received": len(assets), "pushed": 0, "skipped": 0,
              "pending": 0, "unmatched": 0, "failed": 0}
    entries = _map_entries(assets, path_map, counts)
    pending_paths = []
    for (facet_path, _), (result, error) in zip(
            entries, push_photo_updates(DEFAULT_DB_PATH, config, entries)):
        if result == RESULT_FAILED:
            counts["failed"] += 1
            logger.warning("Immich webhook: push failed for %s: %s", facet_path, error,
                           exc_info=error)
        elif result == RESULT_UNKNOWN:
            pending_paths.append(facet_path)
            counts["pending"] += 1
            logger.info("Immich webhook: %s is not scored yet, queued for the next sync",
                        facet_path)
        elif result == RESULT_PUSHED:
            counts["pushed"] += 1
        elif result == RESULT_SKIPPED:
            counts["skipped"] += 1
        else:
            counts["unmatched"] += 1
            logger.warning("Immich webhook: no Immich asset resolvable for %s", facet_path)
    if pending_paths:
        try:
            record_pending_paths(DEFAULT_DB_PATH, pending_paths, max_pending=max_pending)
        except PUSH_ERRORS as e:
            # The queue is a hint for the next sync, not the delivery's result:
            # losing it must not 500 a request whose pushes already landed.
            logger.warning("Immich webhook: could not queue %d pending path(s): %s",
                           len(pending_paths), e, exc_info=True)
    return counts


@router.post(WEBHOOK_PATH)
async def immich_webhook(request: Request):
    """Receive an Immich workflow webhook and mirror the rating back.

    202 with a per-asset tally when the body held assets, 204 when it held
    none Facet could recognise (logged, never an error — the action's payload
    shape is Immich's to change), 400 when the body is not JSON at all.
    """
    webhook_cfg = _immich_config().get("webhook", {}) or {}
    require_static_token(_expected_token(webhook_cfg),
                         _provided_token(request, webhook_cfg), _FEATURE)
    try:
        payload = await request.json()
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Body is not valid JSON")
    assets = list(_iter_assets(payload))
    if not assets:
        logger.info("Immich webhook: no asset in payload (%s)", _describe_shape(payload))
        return Response(status_code=_STATUS_NO_CONTENT)
    if len(assets) > _MAX_ASSETS_PER_DELIVERY:
        logger.warning("Immich webhook: %d assets in one delivery, handling the first %d",
                       len(assets), _MAX_ASSETS_PER_DELIVERY)
        assets = assets[:_MAX_ASSETS_PER_DELIVERY]
    counts = await run_in_threadpool(_process_assets, assets)
    return JSONResponse(status_code=_STATUS_ACCEPTED, content=counts)
