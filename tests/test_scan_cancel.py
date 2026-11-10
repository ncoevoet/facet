"""Stop only a confirmed, locally owned Popen; never signal an arbitrary PID."""

from collections import deque
import asyncio
import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi.testclient import TestClient
from starlette.requests import Request
import pytest

from api import create_app
from api.auth import CurrentUser, create_access_token, decode_access_token, require_authenticated, require_scan_access
from api.routers import scan

JOB = '1' * 32


def _edition_stream_payload() -> dict:
    """A live single-user edition stream token: one the per-tick revocation recheck keeps open."""
    return decode_access_token(create_access_token({'purpose': scan.SCAN_STREAM_PURPOSE, 'edition': True}))


@pytest.fixture
def owned_scan(monkeypatch):
    proc = SimpleNamespace(poll=Mock(return_value=None), terminate=Mock(), wait=Mock(),
                           stdout=[], returncode=0)
    state = {'running': True, 'kind': 'scan', 'process': proc, 'job_id': JOB,
             'cancel_requested': False, 'directories': ['/fixture'],
             'output_lines': deque(), 'started_at': None, 'exit_code': None,
             'progress': None, 'scope': None}
    monkeypatch.setattr(scan, '_scan_state', state)
    monkeypatch.setitem(scan.VIEWER_CONFIG, 'features', {'show_scan_button': True})
    app = create_app()
    app.dependency_overrides[require_scan_access] = lambda: CurrentUser(user_id='root', role='superadmin')
    yield TestClient(app), state, proc
    app.dependency_overrides.clear()


def test_stop_is_idempotent_and_does_not_claim_exit_before_owned_reader(owned_scan):
    client, state, proc = owned_scan
    for _ in range(2):
        response = client.post('/api/scan/cancel', json={'job_id': JOB, 'confirm': True})
        assert response.status_code == 200, response.text
        assert response.json() == {'job_id': JOB, 'stop_requested': True}
    proc.terminate.assert_called_once_with()
    snapshot = client.get('/api/scan/status').json()
    assert snapshot['running'] is True
    assert snapshot['cancel_requested'] is True
    assert snapshot['job_id'] == JOB
    scan._read_scan_output(proc)
    assert state['running'] is False
    assert state['exit_code'] == 0  # cooperative interruption may exit zero
    assert state['cancel_requested'] is True


@pytest.mark.parametrize('patch', [
    {'job_id': '2' * 32}, {'kind': 'recompute'}, {'running': False}, {'process': None},
])
def test_old_confirmation_cannot_stop_another_or_unowned_job(owned_scan, patch):
    client, state, proc = owned_scan
    state.update(patch)
    assert client.post('/api/scan/cancel', json={'job_id': JOB, 'confirm': True}).status_code == 409
    proc.terminate.assert_not_called()


def test_exit_or_signal_failure_never_becomes_a_false_success(owned_scan):
    client, state, proc = owned_scan
    proc.poll.return_value = 0
    assert client.post('/api/scan/cancel', json={'job_id': JOB, 'confirm': True}).status_code == 409
    proc.terminate.assert_not_called()
    proc.poll.return_value = None
    proc.terminate.side_effect = PermissionError('fixture')
    assert client.post('/api/scan/cancel', json={'job_id': JOB, 'confirm': True}).status_code == 503
    assert state['cancel_requested'] is False
    assert state['running'] is True


def test_confirmation_feature_and_scan_permission_are_required(owned_scan, monkeypatch):
    client, _, proc = owned_scan
    assert client.post('/api/scan/cancel', json={'job_id': JOB, 'confirm': True, 'pid': 123}).status_code == 422
    assert client.post('/api/scan/cancel', json={'job_id': JOB, 'confirm': False}).status_code == 400
    monkeypatch.setitem(scan.VIEWER_CONFIG, 'features', {'show_scan_button': False})
    assert client.post('/api/scan/cancel', json={'job_id': JOB, 'confirm': True}).status_code == 403
    monkeypatch.setitem(scan.VIEWER_CONFIG, 'features', {'show_scan_button': True})
    monkeypatch.setattr('api.auth.is_multi_user_enabled', lambda: True)
    app = create_app()
    app.dependency_overrides[require_authenticated] = lambda: CurrentUser(user_id='ordinary', role='user')
    try:
        assert TestClient(app).post('/api/scan/cancel', json={'job_id': JOB, 'confirm': True}).status_code == 403
    finally:
        app.dependency_overrides.clear()
    proc.terminate.assert_not_called()


def test_obsolete_reader_cannot_change_a_newer_process_state(owned_scan):
    _, state, old = owned_scan
    old.stdout = ['late private output\n']
    newer = object()
    state.update(process=newer, job_id='2' * 32, progress={'phase': 'new'})
    scan._read_scan_output(old)
    assert state['running'] is True
    assert state['process'] is newer
    assert state['output_lines'] == deque()
    assert state['progress'] == {'phase': 'new'}


@pytest.mark.asyncio
async def test_sse_snapshot_does_not_block_event_loop_while_start_lock_is_held(owned_scan, monkeypatch):
    payload = _edition_stream_payload()
    monkeypatch.setattr(scan, '_verify_scan_stream_token', lambda token: payload)
    entered = threading.Event()
    release = threading.Event()
    released = threading.Event()

    def hold():
        with scan._scan_lock:
            entered.set()
            release.wait(2)  # deadline prevents a broken implementation hanging the suite
        released.set()

    holder = threading.Thread(target=hold)
    holder.start()
    await asyncio.to_thread(entered.wait, 1)
    response = await scan.scan_stream(Request({'type': 'http'}), token='fixture', lines=20)
    pending = asyncio.create_task(anext(response.body_iterator))
    progressed = asyncio.Event()
    asyncio.get_running_loop().call_soon(progressed.set)
    try:
        await asyncio.wait_for(progressed.wait(), 1)
        assert not released.is_set(), 'SSE blocked the event loop until the mutex was released'
    finally:
        release.set()
        await pending
        await response.body_iterator.aclose()
        await asyncio.to_thread(holder.join)


@pytest.mark.asyncio
async def test_sse_emits_a_stop_request_before_exit_even_without_new_output(owned_scan, monkeypatch):
    _, state, _ = owned_scan
    payload = _edition_stream_payload()
    monkeypatch.setattr(scan, '_verify_scan_stream_token', lambda token: payload)
    original_sleep = asyncio.sleep
    calls = 0

    async def advance(_delay):
        nonlocal calls
        calls += 1
        state['cancel_requested'] = True
        if calls > 1:
            state['running'] = False
        await original_sleep(0)

    monkeypatch.setattr(scan.asyncio, 'sleep', advance)
    response = await scan.scan_stream(Request({'type': 'http'}), token='fixture', lines=20)
    await anext(response.body_iterator)
    try:
        event = await anext(response.body_iterator)
        snapshot = json.loads(event.removeprefix('data: ').strip())
        assert snapshot['cancel_requested'] is True
        assert snapshot['running'] is True
    finally:
        await response.body_iterator.aclose()
