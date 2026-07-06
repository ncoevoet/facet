"""
Scan router — trigger and monitor photo scanning.

"""

import asyncio
import json
import logging
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

from api.auth import CurrentUser, create_access_token, decode_access_token, require_superadmin
from api.config import VIEWER_CONFIG, FACET_SCRIPT, get_all_scan_directories, get_user_directories, _photo_types_cache, _stats_cache
from processing.progress import parse_progress_line

router = APIRouter(prefix="/api/scan", tags=["scan"])
logger = logging.getLogger(__name__)

SCAN_STREAM_PURPOSE = 'scan_stream'
SCAN_STREAM_TOKEN_TTL_SECONDS = 60

# Global scan state (only one scan at a time)
_scan_lock = threading.Lock()
_scan_state = {
    'running': False,
    'process': None,
    'output_lines': deque(maxlen=500),
    'started_at': None,
    'directories': [],
    'exit_code': None,
    'progress': None,
}


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


@router.post("/start")
def start_scan(
    body: ScanStartRequest,
    user: CurrentUser = Depends(require_superadmin),
):
    """Trigger a photo scan as a background subprocess."""
    if not VIEWER_CONFIG.get('features', {}).get('show_scan_button', False):
        raise HTTPException(status_code=403, detail="Scan feature not enabled")

    if not _scan_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A scan is already running")

    try:
        if _scan_state['running']:
            _scan_lock.release()
            raise HTTPException(status_code=409, detail="A scan is already running")

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
        )

        _scan_state['running'] = True
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
            'message': 'Scan started',
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
    if not payload or payload.get('role') != 'superadmin':
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
    # JWT passed as query param because EventSource cannot set custom headers.
    # This is a known limitation; the token is validated server-side and the
    # endpoint is superadmin-only.
    token: Optional[str] = Query(None),
    lines: int = Query(20),
):
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
