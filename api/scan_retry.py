"""Bounded, account-bound retry previews and worker-owned private transports."""

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import logging
from pathlib import Path
import secrets
import sqlite3
import threading
import time
from typing import Any, Iterator

from fastapi import HTTPException, Request

from api.auth import CurrentUser
from api.config import get_all_scan_directories, _CONFIG_PATH
from db.connection import DEFAULT_DB_PATH
from db.schema import SCAN_RETRY_RECEIPTS_COLUMNS, _build_create_table_sql
from processing.scan_retry import capture_retry_plan, RetryPlanError, retry_manifest_bytes, retry_plan_paths

PREVIEW_TTL_SECONDS = 600
MAX_PREVIEWS = 32
MAX_RECEIPTS = 1000
RECEIPT_TTL_SECONDS = 7 * 86400
_lock = threading.Lock()


@dataclass
class RetryPreview:
    actor: str
    plan: dict[str, Any]
    expires: float
    applying: bool = False
    receipt: dict[str, Any] | None = None
    refused: bool = False
    plan_id: str | None = None


_previews: dict[str, RetryPreview] = {}
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


@contextmanager
def _receipt_db() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(Path(DEFAULT_DB_PATH).resolve().as_uri() + '?mode=rw', uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def _recover_receipt(plan_id: str) -> RetryPreview | None:
    try:
        with _receipt_db() as conn:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='scan_retry_receipts'").fetchone():
                return None
            row = conn.execute('SELECT * FROM scan_retry_receipts WHERE plan_id=? AND expires_at>?',
                               (plan_id, time.time())).fetchone()
            if row is None:
                return None
            return RetryPreview(row['actor'], {}, float('inf'),
                                applying=row['state'] == 'submitting',
                                receipt=json.loads(row['receipt']) if row['receipt'] else None,
                                refused=row['state'] == 'refused', plan_id=plan_id)
    except sqlite3.Error:
        raise HTTPException(503, 'Retry receipt storage is unavailable; inspect scan history before retrying') from None


def _claim_receipt(plan_id: str, preview: RetryPreview) -> bool:
    try:
        with _receipt_db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute(_build_create_table_sql('scan_retry_receipts', SCAN_RETRY_RECEIPTS_COLUMNS))
            conn.execute('DELETE FROM scan_retry_receipts WHERE expires_at<=?', (time.time(),))
            if conn.execute('SELECT 1 FROM scan_retry_receipts WHERE plan_id=?', (plan_id,)).fetchone():
                return False
            if conn.execute('SELECT COUNT(*) FROM scan_retry_receipts').fetchone()[0] >= MAX_RECEIPTS:
                raise HTTPException(429, 'Retry receipt capacity reached; inspect existing scan history')
            result = conn.execute("INSERT OR IGNORE INTO scan_retry_receipts VALUES (?,?,'submitting',NULL,?)",
                                  (plan_id, preview.actor, time.time() + RECEIPT_TTL_SECONDS))
            return result.rowcount == 1
    except sqlite3.Error:
        raise HTTPException(503, 'Retry receipt storage is unavailable; no retry was started') from None


def _owned(plan_id: str, request: Request, user: CurrentUser) -> RetryPreview:
    _prune()
    preview = _recover_receipt(plan_id) or _previews.get(plan_id)
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
        if not _claim_receipt(plan_id, preview):
            raise HTTPException(409, 'Retry submission already exists; read its receipt')
        preview.plan_id = plan_id
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
        if preview.plan_id is not None:
            try:
                with _receipt_db() as conn:
                    conn.execute('UPDATE scan_retry_receipts SET state=?, receipt=? WHERE plan_id=? AND actor=?',
                                 ('spawned' if receipt else 'refused', json.dumps(receipt) if receipt else None,
                                  preview.plan_id, preview.actor))
            except sqlite3.Error:
                # The durable submitting claim must remain uncertain and must
                # never become permission to launch another process.
                logger.exception('Could not settle retry receipt; inspect scan history')
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
