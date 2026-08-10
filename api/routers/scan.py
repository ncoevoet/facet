"""
Scan router — trigger and monitor photo scanning.

"""

import asyncio
import json
import logging
import os
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from api.auth import CurrentUser, create_access_token, decode_access_token, require_edition, require_superadmin
from api.config import VIEWER_CONFIG, FACET_SCRIPT, _CONFIG_PATH, get_all_scan_directories, get_user_directories, _photo_types_cache, _stats_cache
from processing.progress import parse_progress_line

router = APIRouter(prefix="/api/scan", tags=["scan"])
logger = logging.getLogger(__name__)

SCAN_STREAM_PURPOSE = 'scan_stream'
SCAN_STREAM_TOKEN_TTL_SECONDS = 60

JOB_KIND_SCAN = 'scan'
JOB_KIND_RECOMPUTE = 'recompute'
JOB_KIND_PANORAMAS = 'panoramas'

# Global scan state (only one scan or recompute job at a time)
_scan_lock = threading.Lock()
_scan_state = {
    'running': False,
    'kind': None,
    'process': None,
    'output_lines': deque(maxlen=500),
    'started_at': None,
    'directories': [],
    'exit_code': None,
    'progress': None,
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
    from facet import JOB_ORIGIN_ENV_VAR

    return {**os.environ, JOB_ORIGIN_ENV_VAR: 'viewer'}


def _read_scan_output(proc):
    """Background thread to read subprocess output.

    Structured @FACET_PROGRESS lines are parsed into _scan_state['progress']
    and kept out of the human-readable log ring buffer.
    """
    for line in proc.stdout:
        line = line.rstrip('\n')
        event = parse_progress_line(line)
        if event is not None:
            _scan_state['progress'] = event
        else:
            _scan_state['output_lines'].append(line)
    proc.wait()
    _scan_state['exit_code'] = proc.returncode
    _scan_state['running'] = False
    # Invalidate caches after scan adds/updates photos
    _photo_types_cache['expires'] = 0
    _stats_cache.clear()


class ScanStartRequest(BaseModel):
    directories: list[str] = []


class RecomputeRequest(BaseModel):
    confirm: bool


@router.post("/start")
def start_scan(
    body: ScanStartRequest,
    user: CurrentUser = Depends(require_superadmin),
):
    """Spawn a photo scan as a background subprocess.

    The conflict check below and the child's own ``LibraryLock`` acquire are
    seconds apart, so a job that starts between them makes the child exit
    before it scores anything. That fails safe -- the child refuses rather
    than corrupting a concurrent run -- so what is reported here is only what
    this process can vouch for: the subprocess was spawned. Whether it went on
    to hold the lock and run is what ``GET /api/scan/status`` reports.
    """
    if not VIEWER_CONFIG.get('features', {}).get('show_scan_button', False):
        raise HTTPException(status_code=403, detail="Scan feature not enabled")

    if not _scan_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A scan is already running")

    try:
        if _scan_state['running']:
            _scan_lock.release()
            raise HTTPException(status_code=409, detail="A scan is already running")

        conflict = _library_job_conflict_detail()
        if conflict:
            _scan_lock.release()
            raise HTTPException(status_code=409, detail=conflict)

        directories = body.directories

        all_configured = set(get_all_scan_directories())
        for d in directories:
            if d not in all_configured:
                _scan_lock.release()
                raise HTTPException(status_code=400, detail=f"Directory not configured: {d}")

        if not directories:
            _scan_lock.release()
            raise HTTPException(status_code=400, detail="No directories specified")

        # Rebuild from canonical server-side list so subprocess args are provably server-origin
        validated_dirs = [d for d in get_all_scan_directories() if d in set(directories)]
        cmd = [sys.executable, FACET_SCRIPT] + validated_dirs

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=_cross_process_job_env(),
        )

        _scan_state['running'] = True
        _scan_state['kind'] = JOB_KIND_SCAN
        _scan_state['process'] = proc
        _scan_state['output_lines'] = deque(maxlen=500)
        _scan_state['started_at'] = time.time()
        _scan_state['directories'] = directories
        _scan_state['exit_code'] = None
        _scan_state['progress'] = None

        reader = threading.Thread(target=_read_scan_output, args=(proc,), daemon=True)
        reader.start()

        _scan_lock.release()
        return {
            'success': True,
            'message': 'Scan spawned; poll /api/scan/status to see it run',
            'directories': directories,
            'pid': proc.pid,
        }

    except HTTPException:
        raise
    except (subprocess.SubprocessError, OSError):
        logger.exception("Scan failed to start")
        _scan_state['running'] = False
        _scan_lock.release()
        raise HTTPException(status_code=500, detail='Scan failed to start')


@router.get("/status")
def scan_status(
    lines: int = Query(20),
    user: CurrentUser = Depends(require_superadmin),
):
    """Poll scan progress. Returns last N lines of output."""
    if not VIEWER_CONFIG.get('features', {}).get('show_scan_button', False):
        raise HTTPException(status_code=403, detail="Scan feature not enabled")

    return _build_scan_snapshot(lines)


@router.get("/stream_token")
def scan_stream_token(
    user: CurrentUser = Depends(require_superadmin),
):
    """Mint a short-lived, single-purpose token for opening the SSE stream.

    Header-authenticated (superadmin), so the long-lived JWT never travels in a
    URL. The stream URL then carries only this 60-second token.
    """
    if not VIEWER_CONFIG.get('features', {}).get('show_scan_button', False):
        raise HTTPException(status_code=403, detail="Scan feature not enabled")
    token = create_access_token(
        {'sub': user.user_id, 'role': 'superadmin', 'purpose': SCAN_STREAM_PURPOSE},
        expires_delta=timedelta(seconds=SCAN_STREAM_TOKEN_TTL_SECONDS),
    )
    return {'token': token}


def _verify_superadmin_token(token: Optional[str]) -> None:
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    payload = decode_access_token(token)
    if (
        not payload
        or payload.get('role') != 'superadmin'
        or payload.get('purpose') != SCAN_STREAM_PURPOSE
    ):
        raise HTTPException(status_code=403, detail="Superadmin access required")


def _build_scan_snapshot(lines: int) -> dict:
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
    }


@router.get("/stream")
async def scan_stream(
    token: Optional[str] = Query(None),
    lines: int = Query(20),
):
    """SSE progress stream. Requires a short-lived scan_stream-purpose token
    minted by GET /stream_token; the long-lived session JWT is rejected."""
    if not VIEWER_CONFIG.get('features', {}).get('show_scan_button', False):
        raise HTTPException(status_code=403, detail="Scan feature not enabled")
    _verify_superadmin_token(token)

    async def event_generator():
        import time as _time
        last_output_len = -1
        last_progress = None
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
            snapshot = _build_scan_snapshot(lines)
            current_output_len = len(_scan_state['output_lines'])
            current_progress = _scan_state.get('progress')
            current_running = snapshot['running']
            now = _time.monotonic()
            changed = (current_output_len != last_output_len
                       or current_progress != last_progress
                       or current_running != was_running)
            if changed:
                yield f"data: {json.dumps(snapshot)}\n\n"
                last_output_len = current_output_len
                last_progress = current_progress
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


@router.get("/directories")
def scan_directories(
    user: CurrentUser = Depends(require_superadmin),
):
    """List all configured directories available for scanning."""
    if not VIEWER_CONFIG.get('features', {}).get('show_scan_button', False):
        raise HTTPException(status_code=403, detail="Scan feature not enabled")

    all_dirs = get_all_scan_directories()
    user_dirs = get_user_directories(user.user_id) if user.user_id else []

    return {
        'directories': [
            {'path': d, 'owner': 'shared' if d not in user_dirs else user.user_id}
            for d in all_dirs
        ]
    }


@router.post("/recompute")
def start_recompute(
    body: RecomputeRequest,
    user: CurrentUser = Depends(require_edition),
):
    """Spawn a full-library aggregate recompute as a background subprocess.

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
    return _spawn_fixed_library_job(
        body, '--recompute-average', JOB_KIND_RECOMPUTE,
        'Recompute spawned; poll /api/scan/recompute_status to see it run')


def _spawn_fixed_library_job(body, flag, kind, message):
    """Spawn a library-rewriting facet.py job whose argv is fixed server-side.

    Shared by every endpoint of this shape so the locking, the cross-process
    conflict check and the state bookkeeping cannot drift apart between them.
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

        cmd = [sys.executable, FACET_SCRIPT, flag, '--config', str(_CONFIG_PATH)]

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

        reader = threading.Thread(target=_read_scan_output, args=(proc,), daemon=True)
        reader.start()

        return {'success': True, 'message': message, 'pid': proc.pid}

    except HTTPException:
        raise
    except Exception:
        logger.exception("Library job %s failed to start", flag)
        _scan_state['running'] = False
        raise HTTPException(status_code=500, detail='Job failed to start')
    finally:
        _scan_lock.release()

@router.post("/detect_panoramas")
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


@router.get("/recompute_status")
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

    if local_running or holder is not None:
        return {
            'running': True,
            'kind': _scan_state.get('kind') if local_running else holder.get('kind'),
            'progress': _scan_state.get('progress') if local_running else None,
            'exit_code': None,
        }

    if _scan_state.get('kind') not in (JOB_KIND_RECOMPUTE, JOB_KIND_PANORAMAS):
        return {'running': False, 'kind': None, 'progress': None, 'exit_code': None}

    return {
        'running': False,
        'kind': _scan_state.get('kind'),
        'progress': _scan_state.get('progress'),
        'exit_code': _scan_state.get('exit_code'),
    }
