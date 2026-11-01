"""Bounded, account-bound retry previews and worker-owned private transports."""

import atexit
from dataclasses import dataclass
import hashlib
import json
import logging
import os
from pathlib import Path
import secrets
import threading
import time
from typing import Any

from fastapi import HTTPException, Request

from api.auth import CurrentUser
from api.config import get_all_scan_directories, _CONFIG_PATH
from db.connection import DEFAULT_DB_PATH
from processing.scan_retry import capture_retry_plan, RetryPlanError, retry_manifest_bytes, retry_plan_paths, write_retry_manifest

PREVIEW_TTL_SECONDS = 600
MAX_PREVIEWS = 32
_lock = threading.Lock()


@dataclass
class RetryPreview:
    actor: str
    plan: dict[str, Any]
    expires: float
    applying: bool = False
    receipt: dict[str, Any] | None = None
    refused: bool = False


_previews: dict[str, RetryPreview] = {}
_manifests: set[str] = set()
logger = logging.getLogger(__name__)


def _actor(request: Request, user: CurrentUser) -> str:
    # Both preview and Apply are POST/Bearer authenticated by the normal
    # dependency. Keep no credential itself in this worker's plan cache.
    data = [user.user_id, user.role, user.edition_authenticated, user.trusted_local_editing,
            user.agent, request.headers.get('authorization', '')]
    return hashlib.sha256(json.dumps(data).encode('utf-8')).hexdigest()


def _capture_allowed(run_id: int) -> dict[str, Any]:
    try:
        plan = capture_retry_plan(DEFAULT_DB_PATH, _CONFIG_PATH, run_id)
        roots = [Path(root).resolve() for root in get_all_scan_directories()]
        # A failed decode may have no photos row. Scan administrators can only
        # retry configured scan roots; no membership is inferred from a path
        # supplied by the browser or from stored args_json.
        if not roots or any(not any(Path(item['path']).is_relative_to(root) for root in roots)
                            for item in plan['files']):
            raise RetryPlanError('Retry run includes files outside current scan directories')
        if not retry_plan_paths(plan):
            raise RetryPlanError('No eligible failed files remain')
        retry_manifest_bytes(plan)
        return plan
    except (RetryPlanError, OSError, ValueError) as exc:
        raise HTTPException(409, 'Retry preview is unavailable or changed; check the run and scan directories') from exc


def _prune() -> None:
    now = time.monotonic()
    for key in list(_previews):
        if not _previews[key].applying and _previews[key].expires <= now:
            del _previews[key]


def _owned(plan_id: str, request: Request, user: CurrentUser) -> RetryPreview:
    _prune()
    preview = _previews.get(plan_id)
    if preview is None:
        raise HTTPException(410, 'Retry preview expired; create a new preview')
    if preview.actor != _actor(request, user):
        raise HTTPException(403, 'Retry preview belongs to another scan session')
    return preview


def preview_retry(run_id: int, request: Request, user: CurrentUser) -> dict[str, Any]:
    plan = _capture_allowed(run_id)
    with _lock:
        _prune()
        if len(_previews) >= MAX_PREVIEWS:
            raise HTTPException(429, 'Too many retry previews; wait for an existing preview to expire')
        plan_id = secrets.token_hex(16)
        _previews[plan_id] = RetryPreview(_actor(request, user), plan, time.monotonic() + PREVIEW_TTL_SECONDS)
    omitted: dict[str, int] = {}
    for item in plan['files']:
        if item['omission']:
            reason = item['omission']
            omitted[reason] = omitted.get(reason, 0) + 1
    return {
        'plan_id': plan_id, 'run_id': run_id, 'expires_in_seconds': PREVIEW_TTL_SECONDS,
        'files': [str(path) for path in retry_plan_paths(plan)],
        'omissions': [{'reason': reason, 'count': count} for reason, count in sorted(omitted.items())],
    }


def begin_retry(plan_id: str, request: Request, user: CurrentUser) -> RetryPreview:
    with _lock:
        preview = _owned(plan_id, request, user)
        if preview.receipt is not None:
            return preview
        if preview.applying or preview.refused:
            raise HTTPException(409, 'Retry was already submitted; read its receipt or create a new preview')
        preview.applying = True
    try:
        if _capture_allowed(preview.plan['run_id']) != preview.plan:
            raise HTTPException(409, 'Retry targets or settings changed; create a new preview')
        return preview
    except BaseException:
        finish_retry(preview, None)
        raise


def finish_retry(preview: RetryPreview, receipt: dict[str, Any] | None) -> None:
    with _lock:
        preview.applying = False
        preview.receipt = receipt
        preview.refused = receipt is None


def retry_receipt(plan_id: str, request: Request, user: CurrentUser) -> dict[str, Any]:
    with _lock:
        preview = _owned(plan_id, request, user)
        return {
            'state': 'spawned' if preview.receipt else 'refused' if preview.refused else 'submitting' if preview.applying else 'preview',
            'job_id': preview.receipt['job_id'] if preview.receipt else None,
        }


def create_manifest(preview: RetryPreview) -> tuple[str, str]:
    filename, digest = write_retry_manifest(preview.plan)
    with _lock:
        _manifests.add(filename)
    return filename, digest


def remove_manifest(filename: str) -> None:
    with _lock:
        if filename not in _manifests:
            return
    try:
        os.unlink(filename)
    except FileNotFoundError:
        pass
    except OSError:
        # Keep ownership for shutdown retry; never let cleanup turn an
        # accepted process into a fictitious start failure.
        logger.warning('Could not remove a private retry manifest')
        return
    with _lock:
        _manifests.discard(filename)


def _cleanup_manifests() -> None:
    with _lock:
        paths = list(_manifests)
    for path in paths:
        remove_manifest(path)


atexit.register(_cleanup_manifests)
