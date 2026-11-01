"""Real retry HTTP contracts with temporary receipts/files and owned fake workers."""

from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from api import create_app
from api.auth import CurrentUser, require_scan_access
from api import scan_retry
from api.routers import scan
from db.schema import init_database
from processing.scan_state import VIEWER_JOB_ID_ENV


@pytest.fixture
def retry_api(tmp_path, monkeypatch):
    db = tmp_path / 'scan.db'
    init_database(str(db))
    root = tmp_path / 'photos'
    root.mkdir()
    photo = root / 'café.jpg'
    photo.write_bytes(b'private fixture')
    config = tmp_path / 'config.json'
    config.write_text('{}', encoding='utf-8')
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO scan_runs(id,status,mode,args_json) VALUES (1,'completed','multi-pass','{}')")
        conn.execute("INSERT INTO scan_failures(scan_run_id,path,stage,error) VALUES (1,?,'load','private diagnostic')", (str(photo),))
    conn.close()
    monkeypatch.setattr(scan_retry, 'DEFAULT_DB_PATH', str(db))
    monkeypatch.setattr(scan_retry, '_CONFIG_PATH', str(config))
    monkeypatch.setattr(scan, '_CONFIG_PATH', str(config))
    monkeypatch.setattr(scan_retry, 'get_all_scan_directories', lambda: [str(root)])
    monkeypatch.setattr(scan, '_library_job_conflict_detail', lambda: None)
    monkeypatch.setattr(scan, '_cross_process_job_env', lambda: {})
    monkeypatch.setitem(scan.VIEWER_CONFIG, 'features', {'show_scan_button': True})
    monkeypatch.setattr(scan_retry, '_previews', {})
    monkeypatch.setattr(scan_retry, '_manifests', set())
    monkeypatch.setattr(scan, '_scan_state', {
        'running': False, 'process': None, 'kind': None, 'output_lines': deque(maxlen=500),
        'started_at': None, 'directories': [], 'exit_code': None, 'progress': None,
        'scope': None, 'job_id': None, 'cancel_requested': False,
    })
    threads = []
    def thread(**kwargs):
        threads.append(kwargs)
        return SimpleNamespace(start=lambda: None)
    monkeypatch.setattr(scan, 'threading', SimpleNamespace(Thread=thread, Event=scan.threading.Event))
    proc = SimpleNamespace(pid=42, stdout=[], returncode=0, wait=Mock(), poll=Mock(return_value=None))
    popen = Mock(return_value=proc)
    monkeypatch.setattr(scan, 'subprocess', SimpleNamespace(
        Popen=popen, PIPE=scan.subprocess.PIPE, STDOUT=scan.subprocess.STDOUT,
        SubprocessError=scan.subprocess.SubprocessError,
    ))
    app = create_app()
    app.dependency_overrides[require_scan_access] = lambda: CurrentUser(user_id='root', role='superadmin', edition_authenticated=True)
    client = TestClient(app, headers={'authorization': 'Bearer session-a'})
    yield SimpleNamespace(client=client, photo=photo, root=root, db=db, config=config, popen=popen, threads=threads, proc=proc, app=app)
    scan_retry._cleanup_manifests()
    app.dependency_overrides.clear()


def preview(ctx):
    response = ctx.client.post('/api/scan/retry/preview', json={'run_id': 1})
    assert response.status_code == 200, response.text
    return response.json()


def test_preview_is_read_only_apply_is_captured_and_idempotent_and_exit_cleans_transport(retry_api):
    ctx = retry_api
    before = ctx.db.read_bytes()
    plan = preview(ctx)
    assert plan['files'] == [str(ctx.photo)] and plan['omissions'] == []
    assert 'diagnostic' not in str(plan) and 'args_json' not in str(plan)
    assert ctx.db.read_bytes() == before and not scan_retry._manifests
    assert not ctx.popen.called
    body = {'plan_id': plan['plan_id'], 'confirm': True}
    result = ctx.client.post('/api/scan/retry/apply', json=body)
    assert result.status_code == 200, result.text
    assert ctx.popen.call_args.kwargs['env'][VIEWER_JOB_ID_ENV] == result.json()['job_id']
    command = ctx.popen.call_args.args[0]
    assert '--retry-failed' not in command and '--retry-plan' in command
    manifest = Path(command[command.index('--retry-plan') + 1])
    assert manifest.exists() and manifest.stat().st_mode & 0o077 == 0
    assert str(ctx.photo) not in command
    again = ctx.client.post('/api/scan/retry/apply', json=body)
    assert again.json() == result.json() and ctx.popen.call_count == 1
    receipt = ctx.client.get('/api/scan/retry/' + plan['plan_id']).json()
    assert receipt == {'state': 'spawned', 'job_id': result.json()['job_id']}
    reader = ctx.threads[-1]
    reader['target'](*reader['args'])
    assert not manifest.exists() and not scan_retry._manifests
    assert not scan._scan_state['running']


@pytest.mark.parametrize('change', ['file', 'config', 'roots', 'token'])
def test_changed_preview_never_spawns_or_writes(retry_api, monkeypatch, change):
    ctx = retry_api
    plan = preview(ctx)
    if change == 'file':
        ctx.photo.write_bytes(b'changed')
    elif change == 'config':
        ctx.config.write_text('{"processing":{"mode":"single-pass"}}', encoding='utf-8')
    elif change == 'roots':
        monkeypatch.setattr(scan_retry, 'get_all_scan_directories', lambda: [])
    else:
        ctx.client.headers['authorization'] = 'Bearer session-b'
    result = ctx.client.post('/api/scan/retry/apply', json={'plan_id': plan['plan_id'], 'confirm': True})
    assert result.status_code in (403, 409), result.text
    assert not ctx.popen.called and not scan_retry._manifests


def test_preview_refuses_outside_root_and_symlink_escape_without_disclosure(retry_api):
    ctx = retry_api
    outside = ctx.root.parent / 'outside.jpg'
    outside.write_bytes(b'outside')
    ctx.photo.unlink()
    ctx.photo.symlink_to(outside)
    result = ctx.client.post('/api/scan/retry/preview', json={'run_id': 1})
    assert result.status_code == 409
    assert str(outside) not in result.text and 'diagnostic' not in result.text
    assert not scan_retry._previews and not ctx.popen.called


def test_permission_confirmation_expiry_capacity_and_failed_spawn_are_explicit(retry_api, monkeypatch):
    ctx = retry_api
    plan = preview(ctx)
    refused = ctx.client.post('/api/scan/retry/apply', json={'plan_id': plan['plan_id'], 'confirm': False})
    assert refused.status_code == 400 and not ctx.popen.called
    ctx.popen.side_effect = OSError('start refused')
    failure = ctx.client.post('/api/scan/retry/apply', json={'plan_id': plan['plan_id'], 'confirm': True})
    assert failure.status_code == 503 and not scan_retry._manifests
    assert ctx.client.get('/api/scan/retry/' + plan['plan_id']).json()['state'] == 'refused'
    ctx.client.post('/api/scan/retry/apply', json={'plan_id': plan['plan_id'], 'confirm': True})
    assert ctx.popen.call_count == 1
    monkeypatch.setattr(scan_retry, 'MAX_PREVIEWS', 1)
    assert ctx.client.post('/api/scan/retry/preview', json={'run_id': 1}).status_code == 429
    scan_retry._previews[plan['plan_id']].expires = 0
    assert ctx.client.get('/api/scan/retry/' + plan['plan_id']).status_code == 410
    monkeypatch.setitem(scan.VIEWER_CONFIG, 'features', {'show_scan_button': False})
    assert ctx.client.post('/api/scan/retry/preview', json={'run_id': 1}).status_code == 403
    monkeypatch.setitem(scan.VIEWER_CONFIG, 'features', {'show_scan_button': True})
    def deny():
        raise HTTPException(403, 'No scan access')
    ctx.app.dependency_overrides[require_scan_access] = deny
    assert ctx.client.post('/api/scan/retry/preview', json={'run_id': 1}).status_code == 403


def test_oversized_manifest_is_refused_at_preview_and_apply_without_internal_error(retry_api, monkeypatch):
    ctx = retry_api
    plan = preview(ctx)
    monkeypatch.setattr('processing.scan_retry.MAX_MANIFEST_BYTES', 1)
    refused = ctx.client.post('/api/scan/retry/preview', json={'run_id': 1})
    assert refused.status_code == 409 and str(ctx.photo) not in refused.text
    result = ctx.client.post('/api/scan/retry/apply', json={'plan_id': plan['plan_id'], 'confirm': True})
    assert result.status_code == 409
    assert ctx.client.get('/api/scan/retry/' + plan['plan_id']).json()['state'] == 'refused'
    assert not ctx.popen.called and not scan_retry._manifests


def test_concurrent_apply_does_not_create_a_second_worker(retry_api):
    ctx = retry_api
    plan = preview(ctx)
    entered = threading.Event()
    release = threading.Event()
    def spawning(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return ctx.proc
    ctx.popen.side_effect = spawning
    body = {'plan_id': plan['plan_id'], 'confirm': True}
    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(ctx.client.post, '/api/scan/retry/apply', json=body)
        try:
            assert entered.wait(5)
            second = ctx.client.post('/api/scan/retry/apply', json=body)
            assert second.status_code == 409
            assert ctx.client.get('/api/scan/retry/' + plan['plan_id']).json()['state'] == 'submitting'
            assert ctx.popen.call_count == 1
        finally:
            release.set()
        assert first.result(timeout=5).status_code == 200


def test_real_worker_reads_utf8_manifest_and_owned_exit_removes_it(retry_api, monkeypatch):
    """Actual private child transport, no scorer/model or library write."""
    ctx = retry_api
    def safe_worker(command, **kwargs):
        script = (
            'import sys; from processing.scan_retry import read_retry_manifest; '
            'a=sys.argv; p=read_retry_manifest(a[a.index("--retry-plan")+1], '
            'a[a.index("--retry-plan-sha256")+1], a[a.index("--db")+1], a[a.index("--config")+1]); '
            'print("captured="+str(len(p["files"])))'
        )
        return subprocess.Popen([sys.executable, '-c', script, *command[2:]], **kwargs)
    ctx.popen.side_effect = safe_worker
    plan = preview(ctx)
    before = ctx.db.read_bytes()
    result = ctx.client.post('/api/scan/retry/apply', json={'plan_id': plan['plan_id'], 'confirm': True})
    assert result.status_code == 200, result.text
    filename = next(iter(scan_retry._manifests))
    reader = ctx.threads[-1]
    reader['target'](*reader['args'])
    assert scan._scan_state['exit_code'] == 0
    assert 'captured=1' in scan._scan_state['output_lines']
    assert not Path(filename).exists() and not scan_retry._manifests
    assert ctx.db.read_bytes() == before


def test_actual_child_records_the_job_id_returned_by_the_viewer(retry_api):
    """Correlation crosses real Popen/env/SQLite, without scoring any image."""
    ctx = retry_api
    def recording_worker(command, **kwargs):
        script = (
            'import sys; from processing.scan_retry import read_retry_manifest; '
            'from processing.scan_state import ScanRun, viewer_job_id; '
            'a=sys.argv; db=a[a.index("--db")+1]; '
            'p=read_retry_manifest(a[a.index("--retry-plan")+1], '
            'a[a.index("--retry-plan-sha256")+1],db,a[a.index("--config")+1]); '
            'r=ScanRun.start(db,"multi-pass",{},1,job_id=viewer_job_id()); '
            'r.update_progress(1); r.finish("completed"); r.finish_job("completed"); '
            'print("recorded="+viewer_job_id())'
        )
        return subprocess.Popen([sys.executable, '-c', script, *command[2:]], **kwargs)
    ctx.popen.side_effect = recording_worker
    plan = preview(ctx)
    before = ctx.photo.read_bytes()
    response = ctx.client.post('/api/scan/retry/apply', json={'plan_id': plan['plan_id'], 'confirm': True})
    assert response.status_code == 200, response.text
    reader = ctx.threads[-1]
    reader['target'](*reader['args'])
    assert scan._scan_state['exit_code'] == 0
    with sqlite3.connect(ctx.db) as conn:
        assert conn.execute('SELECT viewer_job_id,job_status FROM scan_runs WHERE id=2').fetchone() == (response.json()['job_id'], 'completed')
    assert ctx.photo.read_bytes() == before
    assert not scan_retry._manifests
