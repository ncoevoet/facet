"""Recorded scan history reads existing bookkeeping without writes or private diagnostics."""

from contextlib import contextmanager
import hashlib
import sqlite3

from fastapi.testclient import TestClient
import pytest

from api import create_app
from api.auth import CurrentUser, require_authenticated, require_scan_access
from api.routers import scan
from db.schema import init_database


@pytest.fixture()
def history(tmp_path, monkeypatch):
    path = tmp_path / 'history.db'
    init_database(str(path))
    with sqlite3.connect(path) as conn:
        conn.executemany('INSERT INTO scan_runs(id,status,mode,args_json,total_files,processed_files,failed_files,started_at,heartbeat_at) VALUES (?,?,?,?,?,?,?,?,?)', [
            (1, 'completed', 'single-pass', '{"secret":"private-command"}', 10, 10, 0, '2026-10-31 12:00:00', '2026-10-31 12:01:00'),
            (2, 'completed', 'multi-pass', 'private-command', 4, 3, 2, '2026-11-01 12:00:00', '2026-11-01 12:01:00'),
            (3, 'running', 'pass:quality', 'private-command', None, None, None, '2020-01-01 00:00:00', '2020-01-01 00:00:00'),
        ])
        conn.executemany('INSERT INTO scan_failures(scan_run_id,path,stage,error) VALUES (?,?,?,?)', [
            (2, '/private/first.jpg', 'load', 'secret-file-diagnostic'),
            (2, '/private/second.jpg', 'private-stage-value', 'secret-file-diagnostic'),
        ])
    @contextmanager
    def read_db():
        conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    monkeypatch.setattr(scan, 'get_db', read_db)
    monkeypatch.setitem(scan.VIEWER_CONFIG, 'features', {'show_scan_button': True})
    app = create_app()
    app.dependency_overrides[require_scan_access] = lambda: CurrentUser(user_id='root', role='superadmin', edition_authenticated=True)
    yield TestClient(app), path
    app.dependency_overrides.clear()


def test_history_is_bounded_ordered_recorded_state_and_private_diagnostics_are_absent(history):
    client, path = history
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    first = client.get('/api/scan/runs', params={'limit': 2})
    assert first.status_code == 200, first.text
    data = first.json()
    assert [row['id'] for row in data['runs']] == [3, 2]
    assert data['next_before'] == 2
    assert data['runs'][0]['status'] == 'running'  # stale heartbeat must not be rewritten to failed/interrupted
    assert data['runs'][0]['total_files'] is None
    assert data['runs'][1]['started_at'] == '2026-11-01T12:00:00Z'
    assert data['runs'][1]['retained_failure_records'] == 2
    assert data['runs'][1]['failure_stages'] == [{'stage': 'load', 'count': 1}, {'stage': 'other', 'count': 1}]
    assert 'private' not in first.text and 'secret' not in first.text and 'args_json' not in first.text
    last = client.get('/api/scan/runs', params={'limit': 2, 'before': data['next_before']})
    assert [row['id'] for row in last.json()['runs']] == [1]
    assert last.json()['next_before'] is None
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


@pytest.mark.parametrize('params', [{'limit': 0}, {'limit': 51}, {'before': 0}, {'before': '1 OR 1=1'}])
def test_history_refuses_invalid_boundaries(history, params):
    assert history[0].get('/api/scan/runs', params=params).status_code == 422


def test_missing_history_schema_is_unavailable_not_empty_and_is_not_migrated(history):
    client, path = history
    with sqlite3.connect(path) as conn:
        conn.execute('DROP TABLE scan_runs')
    result = client.get('/api/scan/runs')
    assert result.status_code == 503, result.text
    assert '/private/' not in result.text
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='scan_runs'").fetchone() is None


def test_history_uses_scan_permission_and_feature_gate(history, monkeypatch):
    client, _ = history
    monkeypatch.setitem(scan.VIEWER_CONFIG, 'features', {'show_scan_button': False})
    assert client.get('/api/scan/runs').status_code == 403
    app = create_app()
    app.dependency_overrides[require_authenticated] = lambda: CurrentUser(user_id='ordinary', role='user')
    monkeypatch.setattr('api.auth.is_multi_user_enabled', lambda: True)
    try:
        assert TestClient(app).get('/api/scan/runs').status_code == 403
    finally:
        app.dependency_overrides.clear()
