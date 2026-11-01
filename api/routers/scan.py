"""
Scan router — trigger and monitor photo scanning.

"""

import asyncio
import json
import logging
import secrets
import sqlite3
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import timedelta
from typing import Optional, Any

from fastapi import APIRouter, Depends, HTTPException, Path as ApiPath, Query, Request
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from api.auth import CurrentUser, _trusted_local_editing_enabled, create_access_token, decode_access_token, require_edition, require_scan_access, scan_feature_enabled, trusted_local_for
from api.config import VIEWER_CONFIG, FACET_SCRIPT, _CONFIG_PATH, get_all_scan_directories, get_user_directories, invalidate_stats_cache, server_scoring_config, _photo_types_cache
from api.models.scan import (
    ScanRunHistoryResponse,
    ScanJobRecordResponse,
    LibraryJobStartResponse,
    RecomputeStatusResponse,
    ScanDirectoriesResponse,
    ScanStartResponse,
    ScanCancelRequest,
    ScanCancelResponse,
    ScanRetryPreviewRequest,
    ScanRetryApplyRequest,
    ScanRetryPreviewResponse,
    ScanRetryReceiptResponse,
    ScanStatusResponse,
    ScanStreamTokenResponse,
    FaceUpdateStartRequest,
    FaceUpdateRecord,
    FaceUpdatePreview,
)
from processing.progress import parse_progress_line
from processing.scan_retry import RetryPlanError
from api.database import get_db

router = APIRouter(prefix="/api/scan", tags=["scan"])
logger = logging.getLogger(__name__)

SCAN_STREAM_PURPOSE = 'scan_stream'
# Set on a stream token minted for a caller the trusted-local boundary waived the scan flag for.
SCAN_STREAM_LOCAL_CLAIM = 'trusted_local'
SCAN_STREAM_TOKEN_TTL_SECONDS = 60

JOB_KIND_SCAN = 'scan'
JOB_KIND_RECOMPUTE = 'recompute'
JOB_KIND_PANORAMAS = 'panoramas'
JOB_KIND_FACES = 'faces'

# Global scan state (only one scan or recompute job at a time)
_scan_lock = threading.Lock()
_scan_state: dict[str, Any] = {
    'running': False,
    'kind': None,
    'process': None,
    'output_lines': deque(maxlen=500),
    'started_at': None,
    'directories': [],
    'exit_code': None,
    'progress': None,
    # What a recompute was asked for: 'all' or 'category:<name>' (None for any other job).
    'scope': None,
    'job_id': None,
    'cancel_requested': False,
}


def _library_job_conflict_detail():
    """Message naming the process cross-process-locking the DB, or None.

    Checks the ``facet.LibraryLock`` next to the DB, which every
    library-rewriting run holds for its whole run -- a scan (scoring loop AND
    post-processing tail), a ``--recompute-average``/``--recompute-category``,
    and the other ``facet.LIBRARY_JOB_ARGS`` jobs, whether started from a
    terminal or from a subprocess spawned by this router. The message names
    the holder's own kind; it is never assumed.
    """
    from db.connection import DEFAULT_DB_PATH
    from facet import library_job_conflict_message, library_job_holder

    holder = library_job_holder(DEFAULT_DB_PATH)
    return library_job_conflict_message(holder) if holder else None


def _configured_scan_stale_seconds():
    """``processing.scan_stale_seconds``, read fresh so a reload is honoured."""
    from api.config import _FULL_CONFIG
    from facet import scan_stale_seconds

    return scan_stale_seconds(_FULL_CONFIG)


def _recompute_conflict_detail():
    """Like ``_library_job_conflict_detail`` but also refuses on a live scan.

    A scan started by a build that predates the library lock is only visible
    through ``scan_runs`` (heartbeat, also used by ``--resume``), so that
    check is kept as a second line of defence -- honouring the configured
    staleness bound rather than the function default, like every other caller.
    """
    conflict = _library_job_conflict_detail()
    if conflict:
        return conflict
    from db.connection import DEFAULT_DB_PATH
    from processing.scan_state import scan_in_progress

    if scan_in_progress(DEFAULT_DB_PATH, _configured_scan_stale_seconds()):
        return "A scan is already running from the command line."
    return None


def _cross_process_job_env():
    """Subprocess env marking a spawned job as viewer-origin for LibraryLock."""
    from facet import JOB_ORIGIN_ENV_VAR, JOB_ORIGIN_VIEWER

    from api.config import child_process_env

    return child_process_env({JOB_ORIGIN_ENV_VAR: JOB_ORIGIN_VIEWER})


def _read_scan_output(proc, cleanup=None, on_exit=None):
    """Background thread to read subprocess output.

    Structured @FACET_PROGRESS lines are parsed into _scan_state['progress']
    and kept out of the human-readable log ring buffer.
    """
    try:
        for line in proc.stdout:
            line = line.rstrip('\n')
            event = parse_progress_line(line)
            with _scan_lock:
                if _scan_state.get('process') is not proc:
                    continue
                if event is not None:
                    _scan_state['progress'] = event
                else:
                    _scan_state['output_lines'].append(line)
        proc.wait()
        with _scan_lock:
            if _scan_state.get('process') is not proc:
                return
            _scan_state['exit_code'] = proc.returncode
            _scan_state['running'] = False
        _photo_types_cache['expires'] = 0
        invalidate_stats_cache()
    finally:
        try:
            if on_exit is not None and proc.poll() is not None:
                on_exit(proc)
        finally:
            if cleanup is not None:
                cleanup()


class ScanStartRequest(BaseModel):
    directories: list[str] = []


class RecomputeRequest(BaseModel):
    confirm: bool


class RecomputeScoresRequest(BaseModel):
    """Body of ``POST /recompute``: ``category`` narrows the run to one category.

    A model of its own so ``/detect_panoramas``, which shares ``RecomputeRequest``, cannot be handed a category.
    """

    confirm: bool
    category: Optional[str] = None


def scan_feature_refusal(user) -> Optional[str]:
    """The 403 detail when scanning is off for ``user``, else None.

    ``features.show_scan_button`` is the operator's switch, waived only for a caller that passed the
    ``viewer.trusted_local_editing`` boundary: the human browser request, or the agent carrying the
    signed ``mcp_local`` claim. Both share one rule, ``user.trusted_local_editing``.
    """
    if scan_feature_enabled(user.trusted_local_editing, VIEWER_CONFIG):
        return None
    return "Scan feature not enabled"


def _spawn_scan(cmd, directories, cleanup=None, *, kind=JOB_KIND_SCAN, job_id=None, on_exit=None):
    """Caller holds _scan_lock. One observer for normal and captured scans."""
    job_id = job_id or secrets.token_hex(16)
    env = _cross_process_job_env()
    from processing.scan_state import VIEWER_JOB_ID_ENV
    env[VIEWER_JOB_ID_ENV] = job_id
    ready = threading.Event()
    proc = None

    def observe():
        ready.wait()
        if proc is not None:
            _read_scan_output(proc, cleanup, on_exit)

    # Reserve the observer before creating a child. Resource exhaustion cannot
    # leave an accepted scan without a reader, then delete its startup manifest.
    threading.Thread(target=observe, args=(), daemon=True).start()
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, env=env, encoding='utf-8', errors='replace',
        )
        _scan_state.update(
            running=True, kind=kind, process=proc,
            output_lines=deque(maxlen=500), started_at=time.time(), directories=directories,
            exit_code=None, progress=None, scope=None, job_id=job_id, cancel_requested=False,
        )
        return {
            'success': True, 'message': 'Scan spawned; poll /api/scan/status to see it run',
            'directories': directories, 'pid': proc.pid, 'job_id': job_id,
        }
    finally:
        ready.set()


def _require_face_update_access(user):
    if refusal := scan_feature_refusal(user):
        raise HTTPException(403, refusal)


def _face_update_record(job_id, user):
    from faces.update import owner_key
    with get_db() as conn:
        row = conn.execute('SELECT * FROM face_update_jobs WHERE job_id=? AND owner=?',
                           (job_id, owner_key(user.user_id))).fetchone()
    if row is None:
        raise HTTPException(404, 'Face update not found')
    result = dict(row)
    result.pop('owner')
    with _scan_lock:
        proc = _scan_state.get('process')
        result['controlled_by_worker'] = bool(
            _scan_state.get('job_id') == job_id and _scan_state.get('kind') == JOB_KIND_FACES
            and _scan_state['running'] and proc is not None and proc.poll() is None)
    return result


def _close_face_update_receipt(job_id, proc):
    # Called after stdout observation. Only an observed process exit permits a
    # terminal repair; a disconnected reader is not evidence the child stopped.
    if proc.poll() is not None:
        with get_db() as conn:
            conn.execute("UPDATE face_update_jobs SET state='failed',error_code='worker_exited',"
                         "finished_at=CURRENT_TIMESTAMP WHERE job_id=? AND state IN ('queued','running')", (job_id,))
            conn.commit()


@router.get('/faces/preview', response_model=FaceUpdatePreview)
def preview_face_update(user: CurrentUser = Depends(require_scan_access)):
    from db.embedding_space import active_embedding_model
    _require_face_update_access(user)
    with get_db() as conn:
        count = conn.execute('''SELECT COUNT(*) FROM photos p WHERE NOT EXISTS
            (SELECT 1 FROM faces f WHERE f.photo_path=p.path AND f.is_manual=0)''').fetchone()[0]
    return {'eligible_photos': count, 'model': active_embedding_model(server_scoring_config())}


@router.get('/faces/jobs', response_model=list[FaceUpdateRecord])
def face_update_jobs(user: CurrentUser = Depends(require_scan_access)):
    from faces.update import owner_key
    _require_face_update_access(user)
    with get_db() as conn:
        ids = conn.execute('SELECT job_id FROM face_update_jobs WHERE owner=? ORDER BY created_at DESC,job_id DESC LIMIT 10',
                           (owner_key(user.user_id),)).fetchall()
    return [_face_update_record(row[0], user) for row in ids]


@router.get('/faces/jobs/{job_id}', response_model=FaceUpdateRecord)
def face_update_status(job_id: str = ApiPath(pattern=r'^[0-9a-f]{32}$'), user: CurrentUser = Depends(require_scan_access)):
    _require_face_update_access(user)
    return _face_update_record(job_id, user)


@router.post('/faces/start', response_model=FaceUpdateRecord)
def start_face_update(body: FaceUpdateStartRequest, user: CurrentUser = Depends(require_scan_access)):
    from db.connection import DEFAULT_DB_PATH
    from db.embedding_space import active_embedding_model
    from faces.update import capture_job, owner_key
    _require_face_update_access(user)
    if not body.confirm:
        raise HTTPException(400, 'Face update requires confirmation')
    # A lost Start response can be retried with exactly the same request ID.
    # It retrieves the original receipt; it never starts a replacement job.
    def existing_job(conn):
        row = conn.execute('SELECT owner,model FROM face_update_jobs WHERE job_id=?', (body.job_id,)).fetchone()
        if row is not None:
            if row[0] != owner_key(user.user_id):
                raise HTTPException(404, 'Face update not found')
            if row[1] != body.expected_model:
                raise HTTPException(409, 'This request ID belongs to another face-update model')
        return row is not None
    with get_db() as conn:
        exists = existing_job(conn)
    if exists:
        return _face_update_record(body.job_id, user)
    model = active_embedding_model(server_scoring_config())
    if body.expected_model != model:
        raise HTTPException(409, 'Recognition model changed; preview again')
    if not _scan_lock.acquire(blocking=False):
        raise HTTPException(409, 'A library job is already running')
    job_id = body.job_id
    captured = False
    try:
        if _scan_state['running'] or _recompute_conflict_detail():
            raise HTTPException(409, 'A library job is already running')
        with get_db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            # A different viewer worker may have captured this request after
            # the fast read above. Serialize before deciding to spawn.
            exists = existing_job(conn)
            if not exists:
                capture_job(conn, job_id, owner_key(user.user_id), model)
                captured = True
            conn.commit()
        if captured:
            cmd = [sys.executable, FACET_SCRIPT, '--update-faces-job', job_id,
                   '--db', DEFAULT_DB_PATH, '--config', str(_CONFIG_PATH)]
            _spawn_scan(cmd, [], kind=JOB_KIND_FACES, job_id=job_id,
                        on_exit=lambda proc: _close_face_update_receipt(job_id, proc))
    except HTTPException:
        raise
    except (OSError, RuntimeError, subprocess.SubprocessError, sqlite3.Error):
        if captured:
            with get_db() as conn:
                conn.execute("UPDATE face_update_jobs SET state='failed',error_code='spawn_failed',finished_at=CURRENT_TIMESTAMP WHERE job_id=?", (job_id,))
                conn.commit()
        logger.exception('Face update could not start')
        raise HTTPException(503, 'Face update could not start; reload its receipt') from None
    finally:
        _scan_lock.release()
    return _face_update_record(job_id, user)


@router.post('/faces/jobs/{job_id}/cancel', response_model=FaceUpdateRecord)
def cancel_face_update(body: ScanCancelRequest, job_id: str = ApiPath(pattern=r'^[0-9a-f]{32}$'),
                       user: CurrentUser = Depends(require_scan_access)):
    from faces.update import owner_key
    _require_face_update_access(user)
    if not body.confirm or body.job_id != job_id:
        raise HTTPException(400, 'Stopping requires the captured face-update identity')
    # Cooperative cancellation targets this durable job, never a PID, current
    # scan or inferred lock owner. Another worker can acknowledge the same job.
    with get_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT state FROM face_update_jobs WHERE job_id=? AND owner=?',
                           (job_id, owner_key(user.user_id))).fetchone()
        if row is None:
            raise HTTPException(404, 'Face update not found')
        if row[0] == 'queued':
            conn.execute("UPDATE face_update_jobs SET stop_requested=1,state='cancelled',finished_at=CURRENT_TIMESTAMP WHERE job_id=?", (job_id,))
        elif row[0] == 'running':
            conn.execute('UPDATE face_update_jobs SET stop_requested=1 WHERE job_id=?', (job_id,))
        conn.commit()
    return _face_update_record(job_id, user)


@router.post("/start", response_model=ScanStartResponse, response_model_exclude_unset=True)
def start_scan(
    body: ScanStartRequest,
    user: CurrentUser = Depends(require_scan_access),
):
    """Spawn a photo scan as a background subprocess.

    The conflict check below and the child's own ``LibraryLock`` acquire are
    seconds apart, so a job that starts between them makes the child exit
    before it scores anything. That fails safe -- the child refuses rather
    than corrupting a concurrent run -- so what is reported here is only what
    this process can vouch for: the subprocess was spawned. Whether it went on
    to hold the lock and run is what ``GET /api/scan/status`` reports.
    """
    if (refusal := scan_feature_refusal(user)) is not None:
        raise HTTPException(status_code=403, detail=refusal)

    if not _scan_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A scan is already running")

    try:
        if _scan_state['running']:
            raise HTTPException(status_code=409, detail="A scan is already running")

        conflict = _library_job_conflict_detail()
        if conflict:
            raise HTTPException(status_code=409, detail=conflict)

        directories = body.directories

        all_configured = set(get_all_scan_directories())
        for d in directories:
            if d not in all_configured:
                raise HTTPException(status_code=400, detail=f"Directory not configured: {d}")

        if not directories:
            raise HTTPException(status_code=400, detail="No directories specified")

        # Rebuild from canonical server-side list so subprocess args are provably server-origin
        validated_dirs = [d for d in get_all_scan_directories() if d in set(directories)]
        cmd = [sys.executable, FACET_SCRIPT] + validated_dirs

        return _spawn_scan(cmd, directories)

    except HTTPException:
        raise
    except (subprocess.SubprocessError, OSError, RuntimeError):
        logger.exception("Scan failed to start")
        _scan_state['running'] = False
        raise HTTPException(status_code=500, detail='Scan failed to start')
    finally:
        _scan_lock.release()


@router.post('/retry/preview', response_model=ScanRetryPreviewResponse)
def preview_failed_retry(body: ScanRetryPreviewRequest, request: Request, user: CurrentUser = Depends(require_scan_access)):
    if refusal := scan_feature_refusal(user):
        raise HTTPException(403, refusal)
    from api.scan_retry import preview_retry
    return preview_retry(body.run_id, request, user)


@router.get('/retry/{plan_id}', response_model=ScanRetryReceiptResponse)
def failed_retry_receipt(plan_id: str, request: Request, user: CurrentUser = Depends(require_scan_access)):
    if refusal := scan_feature_refusal(user):
        raise HTTPException(403, refusal)
    from api.scan_retry import retry_receipt
    return retry_receipt(plan_id, request, user)


@router.post('/retry/apply', response_model=ScanStartResponse)
def apply_failed_retry(body: ScanRetryApplyRequest, request: Request, user: CurrentUser = Depends(require_scan_access)):
    if refusal := scan_feature_refusal(user):
        raise HTTPException(403, refusal)
    if not body.confirm:
        raise HTTPException(400, 'Confirm the captured failed-file retry')
    from api.scan_retry import begin_retry, create_manifest, finish_retry, remove_manifest
    preview = begin_retry(body.plan_id, request, user)
    if preview.receipt is not None:
        return preview.receipt
    filename = None
    try:
        if not _scan_lock.acquire(blocking=False):
            raise HTTPException(409, 'A library job is already running')
        try:
            if _scan_state['running'] or _library_job_conflict_detail():
                raise HTTPException(409, 'A library job is already running')
            filename, digest = create_manifest(preview)
            from api.scan_retry import DEFAULT_DB_PATH
            cmd = [sys.executable, FACET_SCRIPT, '--db', DEFAULT_DB_PATH,
                   '--config', _CONFIG_PATH, '--retry-plan', filename, '--retry-plan-sha256', digest]
            receipt = _spawn_scan(cmd, [], lambda path=filename: remove_manifest(path))
            finish_retry(preview, receipt)
            return receipt
        finally:
            _scan_lock.release()
    except BaseException as exc:
        finish_retry(preview, None)
        if filename is not None:
            remove_manifest(filename)
        if isinstance(exc, RetryPlanError):
            raise HTTPException(409, 'Retry preview is no longer usable; create a new preview') from exc
        if isinstance(exc, (OSError, subprocess.SubprocessError, RuntimeError)):
            logger.exception('Captured retry could not start')
            raise HTTPException(503, 'Retry could not start; inspect scan status before creating a new preview') from exc
        raise


@router.post('/cancel', response_model=ScanCancelResponse)
def cancel_scan(body: ScanCancelRequest, user: CurrentUser = Depends(require_scan_access)):
    """Request stop of this worker's matching owned scan only.

    This acknowledges a signal, not completion or rollback. Keep the process
    running until its own reader observes exit; never infer a PID from history.
    """
    if refusal := scan_feature_refusal(user):
        raise HTTPException(status_code=403, detail=refusal)
    if not body.confirm:
        raise HTTPException(status_code=400, detail='Stopping a scan requires confirmation')
    with _scan_lock:
        proc = _scan_state.get('process')
        if (_scan_state.get('kind') != JOB_KIND_SCAN or not _scan_state['running']
                or _scan_state.get('job_id') != body.job_id or proc is None
                or proc.poll() is not None):
            raise HTTPException(status_code=409, detail='This scan is no longer controlled by this viewer worker')
        if not _scan_state.get('cancel_requested'):
            try:
                proc.terminate()
            except OSError:
                logger.exception('Could not request scan stop')
                raise HTTPException(status_code=503, detail='Scan stop could not be confirmed') from None
            _scan_state['cancel_requested'] = True
        return {'job_id': body.job_id, 'stop_requested': True}


@router.get("/status", response_model=ScanStatusResponse, response_model_exclude_unset=True)
def scan_status(
    lines: int = Query(20),
    user: CurrentUser = Depends(require_scan_access),
):
    """Poll scan progress. Returns last N lines of output."""
    if (refusal := scan_feature_refusal(user)) is not None:
        raise HTTPException(status_code=403, detail=refusal)

    return _build_scan_snapshot(lines)


_SCAN_RUN_BASE_COLUMNS = (
    "SELECT id, strftime('%Y-%m-%dT%H:%M:%SZ', started_at) AS started_at, "
    "strftime('%Y-%m-%dT%H:%M:%SZ', finished_at) AS finished_at, "
    "strftime('%Y-%m-%dT%H:%M:%SZ', heartbeat_at) AS heartbeat_at, "
    "status, substr(mode, 1, 120) AS mode, total_files, processed_files, failed_files"
)
_SCAN_RUN_JOB_COLUMNS = (
    "CASE WHEN length(viewer_job_id)=32 AND viewer_job_id NOT GLOB '*[^0-9a-f]*' "
    "THEN viewer_job_id END AS viewer_job_id, "
    "CASE WHEN job_status IN ('running','completed','interrupted','failed') THEN job_status END AS job_status, "
    "CASE WHEN job_phase IN ('scoring','bursts','sequences','tagging','moments','junk','vec','done') "
    "THEN job_phase END AS job_phase, "
    "strftime('%Y-%m-%dT%H:%M:%SZ', job_finished_at) AS job_finished_at"
)


def _scan_run_projection(conn, require_job=False):
    """Feature-gate optional new metadata without migrating a read-only DB.

    Old scoring records stay readable. Partial job schemas are unavailable,
    not repaired or mapped onto unrelated historical fields.
    """
    fields = {'viewer_job_id', 'job_status', 'job_phase', 'job_finished_at'}
    present = fields & {row[1] for row in conn.execute('PRAGMA table_info(scan_runs)')}
    if present == fields:
        return _SCAN_RUN_BASE_COLUMNS + ', ' + _SCAN_RUN_JOB_COLUMNS
    if require_job or present:
        raise sqlite3.OperationalError('Scan job metadata schema is unavailable')
    return _SCAN_RUN_BASE_COLUMNS


def _project_scan_runs(conn, rows):
    runs = [dict(row) for row in rows]
    if runs:
        ids = [row['id'] for row in runs]
        placeholders = ','.join('?' for _ in ids)
        # A small vocabulary keeps unexpected diagnostic strings out
        # of this overview and bounds the number of stage groups.
        stages = conn.execute(
            "SELECT scan_run_id, CASE WHEN stage IN "
            "('load','decode_timeout','score','save','composition','embedding') "
            "THEN stage ELSE 'other' END AS stage, COUNT(*) AS count "
            f'FROM scan_failures WHERE scan_run_id IN ({placeholders}) '
            'GROUP BY scan_run_id, 2 ORDER BY scan_run_id DESC, stage', ids,
        ).fetchall()
        by_run: dict[int, list[dict[str, str | int]]] = {run['id']: [] for run in runs}
        for stage in stages:
            by_run[stage['scan_run_id']].append({'stage': stage['stage'], 'count': stage['count']})
        for run in runs:
            run['failure_stages'] = by_run[run['id']]
            run['retained_failure_records'] = sum(stage['count'] for stage in run['failure_stages'])
    return runs


@router.get('/runs', response_model=ScanRunHistoryResponse)
def recorded_scan_runs(
    limit: int = Query(20, ge=1, le=50),
    before: Optional[int] = Query(None, ge=1),
    user: CurrentUser = Depends(require_scan_access),
):
    """Bounded scanner bookkeeping, not a claim that a process is still live.

    Never return args_json, failure paths or free-form error text. These may
    contain private filenames or command arguments unrelated to this overview.
    Reads never migrate, reconcile or change a recorded status.
    """
    if refusal := scan_feature_refusal(user):
        raise HTTPException(status_code=403, detail=refusal)
    try:
        with get_db() as conn:
            conn.execute('BEGIN')
            where = 'WHERE id < ?' if before is not None else ''
            args = [before] if before is not None else []
            rows = conn.execute(
                _scan_run_projection(conn) + f' FROM scan_runs {where} ORDER BY id DESC LIMIT ?',
                [*args, limit + 1],
            ).fetchall()
            more = len(rows) > limit
            runs = _project_scan_runs(conn, rows[:limit])
            return {'runs': runs, 'next_before': runs[-1]['id'] if more else None}
    except sqlite3.Error:
        logger.exception('Could not read recorded scan runs')
        raise HTTPException(status_code=503, detail='Recorded scan history is unavailable') from None


@router.get('/jobs/{job_id}', response_model=ScanJobRecordResponse)
def recorded_scan_job(
    job_id: str = ApiPath(pattern=r'^[0-9a-f]{32}$'),
    user: CurrentUser = Depends(require_scan_access),
):
    """Exact durable pipeline record. It is not process liveness or stop authority.

    Startup can fail before ScanRun is created. Absence therefore means the
    outcome is unknown, not that no process was started. Duplicate correlation
    IDs refuse instead of choosing the newest run.
    """
    if refusal := scan_feature_refusal(user):
        raise HTTPException(403, refusal)
    try:
        with get_db() as conn:
            conn.execute('BEGIN')
            rows = conn.execute(_scan_run_projection(conn, require_job=True) + ' FROM scan_runs WHERE viewer_job_id=? LIMIT 2', (job_id,)).fetchall()
            if not rows:
                raise HTTPException(404, 'No scan run was recorded for this job; startup or early outcome is unknown')
            if len(rows) != 1:
                raise HTTPException(409, 'Scan job identity is ambiguous; inspect recorded history')
            return {'job_id': job_id, 'recorded': _project_scan_runs(conn, rows)[0], 'liveness': 'not_checked'}
    except sqlite3.Error:
        logger.exception('Could not read recorded scan job')
        raise HTTPException(503, 'Recorded scan job is unavailable') from None


@router.get("/stream_token", response_model=ScanStreamTokenResponse, response_model_exclude_unset=True)
def scan_stream_token(
    user: CurrentUser = Depends(require_scan_access),
):
    """Mint a short-lived, single-purpose token for opening the SSE stream.

    Header-authenticated (require_scan_access), so the long-lived JWT never
    travels in a URL. The stream URL then carries only this 60-second token.
    """
    if (refusal := scan_feature_refusal(user)) is not None:
        raise HTTPException(status_code=403, detail=refusal)
    token = create_access_token(
        {'sub': user.user_id or '_legacy', 'purpose': SCAN_STREAM_PURPOSE,
         SCAN_STREAM_LOCAL_CLAIM: bool(user.trusted_local_editing)},
        expires_delta=timedelta(seconds=SCAN_STREAM_TOKEN_TTL_SECONDS),
    )
    return {'token': token}


def _verify_scan_stream_token(token: Optional[str]) -> dict:
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    payload = decode_access_token(token)
    if not payload or payload.get('purpose') != SCAN_STREAM_PURPOSE:
        raise HTTPException(status_code=403, detail="Invalid or expired scan stream token")
    return payload


def _build_scan_snapshot(lines: int) -> dict:
    with _scan_lock:
        output_lines = list(_scan_state['output_lines'])[-lines:]
        elapsed = None
        if _scan_state['started_at']:
            elapsed = round(time.time() - _scan_state['started_at'], 1)
        return {
            'running': _scan_state['running'],
            'directories': _scan_state['directories'],
            'output': output_lines,
            'elapsed_seconds': elapsed,
            'exit_code': _scan_state['exit_code'],
            'progress': _scan_state.get('progress'),
            'job_id': _scan_state.get('job_id'),
            'kind': _scan_state.get('kind'),
            'cancel_requested': bool(_scan_state.get('cancel_requested')),
        }


@router.get("/stream")
async def scan_stream(
    request: Request,
    token: Optional[str] = Query(None),
    lines: int = Query(20),
):
    """SSE progress stream. Requires a short-lived scan_stream-purpose token
    minted by GET /stream_token; the long-lived session JWT is rejected."""
    payload = _verify_scan_stream_token(token)
    # The claim only counts while THIS request also passes the boundary: a replayed token from elsewhere is not local.
    local = payload.get(SCAN_STREAM_LOCAL_CLAIM) is True and _trusted_local_editing_enabled() \
        and trusted_local_for(request)
    if not scan_feature_enabled(local, VIEWER_CONFIG):
        raise HTTPException(status_code=403, detail="Scan feature not enabled")

    async def event_generator():
        import time as _time
        last_snapshot = None
        was_running = None
        # Emit a comment-line heartbeat every HEARTBEAT_SECONDS so reverse
        # proxies (nginx, Cloudflare, ingress controllers) don't close the
        # connection on an idle scan. SSE comments (lines starting with ":")
        # are silently dropped by EventSource clients, so heartbeats don't
        # surface to the UI. Use time.monotonic() rather than the event
        # loop's clock so the cadence stays stable even if the loop changes.
        HEARTBEAT_SECONDS = 15
        last_heartbeat = _time.monotonic()
        while True:
            snapshot = await asyncio.to_thread(_build_scan_snapshot, lines)
            # One captured state, including stop requests/job changes and ring
            # buffer rotation. Elapsed time alone does not generate an event.
            comparable = {key: value for key, value in snapshot.items() if key != 'elapsed_seconds'}
            current_running = snapshot['running']
            now = _time.monotonic()
            changed = comparable != last_snapshot
            if changed:
                yield f"data: {json.dumps(snapshot)}\n\n"
                last_snapshot = comparable
                if not current_running and was_running in (True, None):
                    break
                was_running = current_running
                last_heartbeat = now
            elif now - last_heartbeat >= HEARTBEAT_SECONDS:
                yield ": keepalive\n\n"
                last_heartbeat = now
            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/directories", response_model=ScanDirectoriesResponse, response_model_exclude_unset=True)
def scan_directories(
    user: CurrentUser = Depends(require_scan_access),
):
    """List all configured directories available for scanning."""
    if (refusal := scan_feature_refusal(user)) is not None:
        raise HTTPException(status_code=403, detail=refusal)

    all_dirs = get_all_scan_directories()
    user_dirs = get_user_directories(user.user_id) if user.user_id else []

    return {
        'directories': [
            {'path': d, 'owner': 'shared' if d not in user_dirs else user.user_id}
            for d in all_dirs
        ]
    }


@router.post("/recompute", response_model=LibraryJobStartResponse, response_model_exclude_unset=True)
def start_recompute(
    body: RecomputeScoresRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Spawn an aggregate recompute (the whole library, or one ``category``) as a background subprocess.

    ``category`` runs ``--recompute-category``: only that category's scores are rewritten, and burst and
    sequence detection are skipped (the whole-library run does them). Either way the run persists the
    library's percentile snapshot, which every category's next normalisation reads. An unknown category is
    a 400 before anything is spawned.

    Reuses the scan job machinery (``_scan_lock``, ``_scan_state``,
    ``_read_scan_output``) so a scan and a recompute stay mutually exclusive
    *within this process*. Cross-process (a CLI ``--recompute-average`` or
    scan running from a terminal) is caught by ``_recompute_conflict_detail``,
    which checks ``facet.LibraryLock`` -- the subprocess spawned below holds
    that same lock for its whole run, marked ``origin=viewer`` via
    ``_cross_process_job_env`` so the conflict message names where it came
    from. The argv is fixed and entirely server-origin, so unlike ``/start``
    it is edition-gated rather than superadmin-only.

    That conflict check and the child's acquire are seconds apart, so a job
    starting in between makes the child refuse and exit. The check therefore
    buys a clean 409 for the common case, not a guarantee, and the response
    claims only what this process can vouch for: the subprocess was spawned.
    ``GET /api/scan/recompute_status`` is what says whether it is running.

    ``confirm`` is required rather than decorative: a body-less POST is a CORS
    "simple request" and never preflights, so any page the user happens to open
    could otherwise start a multi-hour rewrite of the whole photos table on a
    password-less install. Requiring a JSON body forces the preflight that the
    other write endpoints get for free.
    """
    if not body.confirm:
        raise HTTPException(status_code=400, detail="This job must be explicitly confirmed")
    if body.category is None:
        return _spawn_fixed_library_job(
            body, '--recompute-average', JOB_KIND_RECOMPUTE,
            'Recompute spawned; poll /api/scan/recompute_status to see it run', scope='all')
    if body.category not in {c.get('name') for c in server_scoring_config().get_categories()}:
        raise HTTPException(status_code=400, detail=f"Unknown category: {body.category}")
    return _spawn_fixed_library_job(
        body, '--recompute-category', JOB_KIND_RECOMPUTE,
        'Recompute spawned; poll /api/scan/recompute_status to see it run',
        flag_args=(body.category,), scope=f'category:{body.category}')


def _spawn_fixed_library_job(body, flag, kind, message, flag_args=(), scope=None):
    """Spawn a library-rewriting facet.py job whose argv is fixed server-side.

    Shared by every endpoint of this shape so the locking, the cross-process
    conflict check and the state bookkeeping cannot drift apart between them.
    ``flag_args`` follow the flag in the argv and are server-validated by the caller; ``scope`` names
    what the job was asked for so a poller can tell its own job from another.
    """
    if not body.confirm:
        raise HTTPException(status_code=400, detail="This job must be explicitly confirmed")

    if not _scan_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A job is already running")

    try:
        if _scan_state['running']:
            raise HTTPException(status_code=409, detail="A job is already running")

        conflict = _recompute_conflict_detail()
        if conflict:
            raise HTTPException(status_code=409, detail=conflict)

        cmd = [sys.executable, FACET_SCRIPT, flag, *flag_args, '--config', str(_CONFIG_PATH)]

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=_cross_process_job_env(),
        )

        _scan_state['running'] = True
        _scan_state['kind'] = kind
        _scan_state['process'] = proc
        _scan_state['output_lines'] = deque(maxlen=500)
        _scan_state['started_at'] = time.time()
        _scan_state['directories'] = []
        _scan_state['exit_code'] = None
        _scan_state['progress'] = None
        _scan_state['scope'] = scope
        _scan_state['job_id'] = secrets.token_hex(16)
        _scan_state['cancel_requested'] = False

        reader = threading.Thread(target=_read_scan_output, args=(proc,), daemon=True)
        reader.start()

        started = {'success': True, 'message': message, 'pid': proc.pid, 'started_at': _scan_state['started_at']}
        return {**started, 'scope': scope} if scope else started

    except HTTPException:
        raise
    except Exception:
        logger.exception("Library job %s failed to start", flag)
        _scan_state['running'] = False
        raise HTTPException(status_code=500, detail='Job failed to start')
    finally:
        _scan_lock.release()

@router.post("/detect_panoramas", response_model=LibraryJobStartResponse, response_model_exclude_unset=True)
def start_detect_panoramas(
    body: RecomputeRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Spawn a whole-library panorama re-detection as a background subprocess.

    Editing a threshold changes nothing on its own: detection is a batch pass
    that writes ``sequence_kind``, not a live query, so the gallery and the
    culling feed keep serving the labels the last run produced until this is
    called. It exists so the settings surface can offer that re-run rather than
    leaving the user to find a terminal.

    Shares ``_scan_lock``/``_scan_state`` and the ``facet.LibraryLock`` conflict
    check with the scan and recompute jobs, so no two library-rewriting jobs run
    at once. Like ``/recompute`` the argv is fixed and entirely server-origin,
    so it is edition-gated rather than superadmin-only, and ``confirm`` is
    required for the same reason: a body-less POST never preflights.
    """
    return _spawn_fixed_library_job(
        body, '--detect-panoramas', JOB_KIND_PANORAMAS,
        'Panorama detection spawned; poll /api/scan/recompute_status to see it run')



def _cross_process_job_holder():
    """The live ``facet.LibraryLock`` holder, if any.

    A scan holds it too, not just a recompute, so the holder's recorded
    ``kind`` is reported as-is. Peeking it here is what lets a worker that
    never handled the POST still answer ``running`` truthfully instead of
    mistaking silence for failure.
    """
    from db.connection import DEFAULT_DB_PATH
    from facet import library_job_holder

    return library_job_holder(DEFAULT_DB_PATH)


@router.get("/recompute_status", response_model=RecomputeStatusResponse, response_model_exclude_unset=True)
def recompute_status(
    user: CurrentUser = Depends(require_edition),
):
    """Poll recompute progress.

    ``_scan_state`` is a per-process global, so a worker other than the one
    that handled the POST has none of it. ``_cross_process_job_holder`` fills
    that gap for ``running`` so a fresh worker reports "running, progress
    unknown" rather than a false "failed", and reports the holder's own
    ``kind`` -- a scan holds the same lock, so assuming ``recompute`` here
    would mislabel it. ``progress`` and a terminal ``exit_code`` still require
    having watched the subprocess directly, so they stay null unless this
    worker's own state is the one that pertains to a recompute -- never
    leaked from a stale scan.

    Deliberately excludes ``output_lines`` -- the superadmin-only log stream
    served by ``/status`` and ``/stream`` is not widened to edition users.
    """
    local_running = _scan_state['running']
    holder = None if local_running else _cross_process_job_holder()

    if local_running:
        return {
            'running': True,
            'kind': _scan_state.get('kind'),
            'progress': _scan_state.get('progress'),
            'exit_code': None,
            'started_at': _scan_state.get('started_at'),
            'scope': _scan_state.get('scope'),
        }
    if holder is not None:
        return {
            'running': True,
            'kind': holder.get('kind'),
            'progress': None,
            'exit_code': None,
        }

    if _scan_state.get('kind') not in (JOB_KIND_RECOMPUTE, JOB_KIND_PANORAMAS):
        return {'running': False, 'kind': None, 'progress': None, 'exit_code': None}

    return {
        'running': False,
        'kind': _scan_state.get('kind'),
        'progress': _scan_state.get('progress'),
        'exit_code': _scan_state.get('exit_code'),
        'started_at': _scan_state.get('started_at'),
        'scope': _scan_state.get('scope'),
    }
