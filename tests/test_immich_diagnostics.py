"""Read-only diagnostics use temporary data and a real local fake server."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import sqlite3
import threading

import pytest

from api.routers import immich_diagnostics as diagnostics
from db.schema import init_database


@pytest.fixture
def local_db(tmp_path, monkeypatch):
    import db
    path = tmp_path / 'diagnostics.db'
    init_database(str(path))
    with sqlite3.connect(path) as conn:
        conn.executemany('INSERT INTO photos (path) VALUES (?)', [('/photos/a.jpg',), ('/elsewhere/b.jpg',)])
        conn.execute("INSERT INTO stats_cache (key, value, updated_at) VALUES ('immich_synced_paths:global', '{}', 1700000000)")
    monkeypatch.setattr(db, 'DEFAULT_DB_PATH', str(path))
    return path


@contextmanager
def remote(responses, *, truncated_path=None):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append((self.command, self.path, self.headers.get('x-api-key')))
            status, payload = responses[self.path]
            self.send_response(status)
            if status == 302:
                self.send_header('Location', '/redirect-target')
            if self.path == truncated_path:
                self.send_header('Transfer-Encoding', 'chunked')
                self.end_headers()
                self.wfile.write(b'100\r\nprivate-provider-text')
                self.close_connection = True
                return
            self.end_headers()
            if callable(payload):
                payload = payload()
            try:
                self.wfile.write(payload if isinstance(payload, bytes) else json.dumps(payload).encode('utf-8'))
            except BrokenPipeError:
                pass

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', calls
    finally:
        server.shutdown()
        worker.join()
        server.server_close()


def config(url):
    return {'immich': {'url': url, 'api_key': 'private-api-key',
                       'path_map': [{'facet_prefix': '/photos/', 'immich_prefix': '/remote/'}]}}


def test_local_status_is_read_only_and_does_not_contact_remote(local_db):
    before = local_db.read_bytes()
    value = diagnostics._diagnose(config('http://127.0.0.1:1'), False)
    assert value['configured'] is True
    assert value['connection'] == 'not_checked'
    assert value['sampled_photos'] == 2
    assert value['mapped_photos'] == 1
    assert value['last_push_at'] == '2023-11-14T22:13:20+00:00'
    assert local_db.read_bytes() == before
    assert 'private-api-key' not in json.dumps(value)
    assert '/photos/' not in json.dumps(value)


def test_sample_is_bounded(local_db):
    with sqlite3.connect(local_db) as conn:
        conn.executemany('INSERT INTO photos (path) VALUES (?)', [(f'/photos/{i:04}.jpg',) for i in range(400)])
    value = diagnostics._diagnose(config(''), False)
    assert value['sampled_photos'] == value['sample_limit'] == 200


def test_real_read_only_connection_and_version(local_db):
    replies = {'/api/server/version': (200, {'major': 3, 'minor': 2, 'patch': 1}),
               '/api/users/me': (200, {'id': 'remote-user', 'email': 'private@example.test'})}
    with remote(replies) as (url, calls):
        value = diagnostics._diagnose(config(url), True)
    assert value['connection'] == 'connected'
    assert value['version'] == '3.2.1'
    assert value['stack_version_supported'] is True
    assert calls == [('GET', '/api/server/version', 'private-api-key'),
                     ('GET', '/api/users/me', 'private-api-key')]
    assert 'remote-user' not in json.dumps(value)
    assert 'private@example.test' not in json.dumps(value)


@pytest.mark.parametrize(('code', 'payload', 'expected'), [
    (401, {'error': 'private-api-key'}, 'access_denied'),
    (403, b'private-provider-text', 'access_denied'),
    (503, b'private-provider-text', 'unreachable'),
    (302, b'', 'unreachable'),
    (200, b'not-json private-api-key', 'invalid_response'),
    pytest.param(200, b'x' * 65537, 'invalid_response', id='oversized-body'),
    (200, {'major': True, 'minor': 1, 'patch': 0}, 'invalid_response'),
])
def test_remote_errors_are_safe_and_release_admission(local_db, code, payload, expected):
    with remote({'/api/server/version': (code, payload)}) as (url, calls):
        value = diagnostics._diagnose(config(url), True)
    assert value['connection'] == expected
    assert len(calls) == 1
    assert 'private' not in json.dumps(value)
    assert diagnostics._connection_test.acquire(blocking=False)
    diagnostics._connection_test.release()


@pytest.mark.parametrize('truncated_path', ['/api/server/version', '/api/users/me'])
def test_interrupted_chunked_response_is_safe_and_retryable(local_db, monkeypatch, truncated_path):
    import api.auth
    import api.config
    from api import create_app
    from api.auth import CurrentUser, require_authenticated
    from fastapi.testclient import TestClient

    monkeypatch.setattr(api.auth, 'is_multi_user_enabled', lambda: True)
    app = create_app()
    app.dependency_overrides[require_authenticated] = lambda: CurrentUser(
        user_id='test', role='superadmin', edition_authenticated=True)
    replies = {'/api/server/version': (200, {'major': 3, 'minor': 2, 'patch': 1}),
               '/api/users/me': (200, {'id': 'private-remote-user'})}
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            with remote(replies, truncated_path=truncated_path) as (url, calls):
                monkeypatch.setitem(api.config._FULL_CONFIG, 'immich', config(url)['immich'])
                response = client.get('/api/immich/diagnostics?check_connection=true')
            assert response.status_code == 200
            assert response.json()['connection'] == 'invalid_response'
            assert response.headers['cache-control'] == 'no-store'
            assert 'private' not in response.text
            assert calls[-1] == ('GET', truncated_path, 'private-api-key')
            assert diagnostics._connection_test.acquire(blocking=False)
            diagnostics._connection_test.release()

            with remote(replies) as (url, calls):
                monkeypatch.setitem(api.config._FULL_CONFIG, 'immich', config(url)['immich'])
                retry = client.get('/api/immich/diagnostics?check_connection=true')
            assert retry.status_code == 200
            assert retry.json()['connection'] == 'connected'
            assert retry.json()['version'] == '3.2.1'
            assert retry.headers['cache-control'] == 'no-store'
            assert 'private' not in retry.text
            assert [path for _, path, _ in calls] == ['/api/server/version', '/api/users/me']
    finally:
        app.dependency_overrides.clear()


def test_incomplete_config_does_not_make_requests(local_db):
    value = diagnostics._diagnose({'immich': {}}, True)
    assert value['configured'] is False
    assert value['connection'] == 'not_configured'


def test_busy_test_does_not_contact_remote(local_db):
    from fastapi import HTTPException
    diagnostics._connection_test.acquire()
    try:
        with pytest.raises(HTTPException) as exc:
            diagnostics._diagnose(config('http://127.0.0.1:1'), True)
        assert exc.value.status_code == 429
    finally:
        diagnostics._connection_test.release()


def test_api_success_has_no_store(superadmin_client, local_db, monkeypatch):
    import api.config
    import api.auth
    monkeypatch.setattr(api.auth, 'is_multi_user_enabled', lambda: True)
    monkeypatch.setitem(api.config._FULL_CONFIG, 'immich', {})
    response = superadmin_client.get('/api/immich/diagnostics')
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert response.json()['configured'] is False


def test_regular_user_cannot_probe_global_key(regular_client, monkeypatch):
    reached = []
    monkeypatch.setattr(diagnostics, '_diagnose', lambda *_: reached.append(True))
    response = regular_client.get('/api/immich/diagnostics?check_connection=true')
    assert response.status_code == 403
    assert response.headers['cache-control'] == 'no-store'
    assert reached == []


@pytest.mark.parametrize(('multi', 'role', 'locked', 'trusted', 'expected'), [
    (True, 'superadmin', True, False, 200),
    (True, 'admin', True, False, 403),
    (True, 'user', True, False, 403),
    (False, 'admin', True, False, 200),
    (False, 'admin', False, False, 403),
    (False, 'admin', False, True, 200),
])
def test_actual_administrator_boundary(local_db, monkeypatch, multi, role, locked, trusted, expected):
    import api.auth
    import api.config
    from api import create_app
    from api.auth import CurrentUser, require_authenticated
    from fastapi.testclient import TestClient
    monkeypatch.setattr(api.auth, 'is_multi_user_enabled', lambda: multi)
    monkeypatch.setattr(api.auth, 'VIEWER_CONFIG', {'edition_password': 'locked' if locked else ''})
    monkeypatch.setitem(api.config._FULL_CONFIG, 'immich', {})
    app = create_app()
    app.dependency_overrides[require_authenticated] = lambda: CurrentUser(
        user_id='test', role=role, edition_authenticated=True, trusted_local_editing=trusted)
    try:
        response = TestClient(app).get('/api/immich/diagnostics')
        assert response.status_code == expected
        assert response.headers['cache-control'] == 'no-store'
    finally:
        app.dependency_overrides.clear()


def test_superadmin_sample_is_visibility_scoped_before_limit(local_db, monkeypatch):
    import api.config
    monkeypatch.setitem(api.config._FULL_CONFIG, 'users', {
        'root': {'role': 'superadmin', 'directories': ['/photos']},
        'other': {'role': 'user', 'directories': ['/elsewhere']},
    })
    with sqlite3.connect(local_db) as conn:
        conn.executemany('INSERT INTO photos (path) VALUES (?)', [(f'/aaa-hidden/{i}.jpg',) for i in range(250)])
        conn.execute("INSERT INTO stats_cache (key, value, updated_at) VALUES ('immich_synced_paths:other', '{}', 1900000000)")
    value = diagnostics._diagnose(config(''), False, 'root')
    assert value['sampled_photos'] == 1
    assert value['mapped_photos'] == 1
    assert value['last_push_at'] is None
    other = diagnostics._diagnose(config(''), False, 'other')
    assert other['sampled_photos'] == 1
    assert other['mapped_photos'] == 0
    assert other['last_push_at'] is not None
    assert diagnostics._diagnose(config(''), False, 'nobody')['sampled_photos'] == 0


def test_actual_socket_timeout_releases_admission(local_db, monkeypatch):
    started = threading.Event()
    release = threading.Event()
    def stalled():
        started.set()
        release.wait(5)
        return b'{}'
    monkeypatch.setattr(diagnostics, '_TIMEOUT', 1)
    result = []
    with remote({'/api/server/version': (200, stalled)}) as (url, calls):
        worker = threading.Thread(target=lambda: result.append(diagnostics._diagnose(config(url), True)))
        worker.start()
        try:
            assert started.wait(5)
            worker.join(3)
            assert not worker.is_alive()
            assert result[0]['connection'] == 'unreachable'
            assert calls == [('GET', '/api/server/version', 'private-api-key')]
        finally:
            release.set()
            worker.join(5)
    assert diagnostics._connection_test.acquire(blocking=False)
    diagnostics._connection_test.release()


def test_invalid_query_is_not_cached(superadmin_client, monkeypatch):
    import api.auth
    monkeypatch.setattr(api.auth, 'is_multi_user_enabled', lambda: True)
    response = superadmin_client.get('/api/immich/diagnostics?check_connection=garbage')
    assert response.status_code == 422
    assert response.headers['cache-control'] == 'no-store'


@pytest.mark.parametrize('cfg', [{'immich': [1]}, {'immich': {'url': 123, 'api_key': 'private'}},
                                {'immich': {'url': 'http://localhost', 'api_key': 'private\nheader'}},
                                {'immich': {'path_map': [{'facet_prefix': 42}]}}])
def test_invalid_configuration_never_contacts_server(local_db, cfg):
    value = diagnostics._diagnose(cfg, True)
    assert value['connection'] == 'invalid_config'
    assert 'private' not in json.dumps(value)


def test_connection_uses_one_configuration_snapshot(local_db, monkeypatch):
    responses = {'/api/server/version': (200, {'major': 3, 'minor': 0, 'patch': 0}),
                 '/api/users/me': (200, {'id': 'account'})}
    original_status = diagnostics._local_status
    with remote(responses) as (url, calls):
        original = config(url)
        def replace_live_config(snapshot, user_id=None):
            value = original_status(snapshot, user_id)
            original['immich'] = {'url': 'http://127.0.0.1:1', 'api_key': 'different-private-key'}
            return value
        monkeypatch.setattr(diagnostics, '_local_status', replace_live_config)
        value = diagnostics._diagnose(original, True)
    assert value['connection'] == 'connected'
    assert len(calls) == 2
    assert all(call[2] == 'private-api-key' for call in calls)


def test_sample_spans_the_library_not_the_first_paths(local_db):
    with sqlite3.connect(local_db) as conn:
        conn.executemany('INSERT INTO photos (path) VALUES (?)',
                         [(f'/photos/{i:04}.jpg',) for i in range(300)] + [(f'/zzz/{i:04}.jpg',) for i in range(300)])
    value = diagnostics._diagnose(config(''), False)
    assert value['sampled_photos'] == 200
    # Half the library is mapped. Sorted by path, the sample would be the first
    # 200 rows, nearly all under the one mapped root.
    assert 20 < value['mapped_photos'] < 180


@pytest.mark.parametrize(('code', 'payload', 'expected'), [
    (401, b'private-provider-text', 'access_denied'),
    (403, b'private-provider-text', 'access_denied'),
    (200, {'email': 'private@example.test'}, 'invalid_response'),
    (200, {'id': ''}, 'invalid_response'),
])
def test_key_check_failures_after_a_public_version_read(local_db, code, payload, expected):
    replies = {'/api/server/version': (200, {'major': 3, 'minor': 0, 'patch': 0}),
               '/api/users/me': (code, payload)}
    with remote(replies) as (url, calls):
        value = diagnostics._diagnose(config(url), True)
    assert value['connection'] == expected
    assert value['version'] is None
    assert [path for _, path, _ in calls] == ['/api/server/version', '/api/users/me']
    assert 'private' not in json.dumps(value)


@pytest.mark.parametrize(('version', 'expected'), [
    ({'major': 2, 'minor': 9, 'patch': 9}, False),
    ({'major': 3, 'minor': 0, 'patch': 0}, True),
    ({'major': 10001, 'minor': 0, 'patch': 0}, None),
    ({'major': -1, 'minor': 0, 'patch': 0}, None),
])
def test_stack_version_support_and_version_range(local_db, version, expected):
    replies = {'/api/server/version': (200, version), '/api/users/me': (200, {'id': 'remote-user'})}
    with remote(replies) as (url, _):
        value = diagnostics._diagnose(config(url), True)
    assert value['stack_version_supported'] is expected
    assert value['connection'] == ('connected' if expected is not None else 'invalid_response')


def test_route_errors_keep_no_store(superadmin_client, local_db, monkeypatch):
    import api.auth
    from fastapi import HTTPException
    monkeypatch.setattr(api.auth, 'is_multi_user_enabled', lambda: True)

    def unreadable(*_):
        raise sqlite3.DatabaseError('file is not a database')
    monkeypatch.setattr(diagnostics, '_diagnose', unreadable)
    unavailable = superadmin_client.get('/api/immich/diagnostics')
    assert unavailable.status_code == 503
    assert unavailable.headers['cache-control'] == 'no-store'
    assert 'not a database' not in unavailable.text

    def busy(*_):
        raise HTTPException(429, 'busy', headers={'Retry-After': '3'})
    monkeypatch.setattr(diagnostics, '_diagnose', busy)
    throttled = superadmin_client.get('/api/immich/diagnostics?check_connection=true')
    assert throttled.status_code == 429
    assert throttled.headers['retry-after'] == '3'
    assert throttled.headers['cache-control'] == 'no-store'
