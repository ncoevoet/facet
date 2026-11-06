"""Authenticated deliveries and CLI pagination against a loopback Immich server."""
import json
import logging
import os
from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace

import pytest

from api.database import get_db
from db.schema import init_database
from sync.immich import sync_to_immich


@pytest.fixture
def remote():
    state = SimpleNamespace(requests=[], errors=[], route=None)

    class Handler(BaseHTTPRequestHandler):
        def handle_request(self):
            length = int(self.headers.get('Content-Length', '0'))
            payload = json.loads(self.rfile.read(length)) if length else None
            state.requests.append((self.command, self.path, payload))
            try:
                assert self.headers.get('x-api-key') == 'fixture-key'
                result = state.route(self.command, self.path, payload)
                status = 200
            except Exception as error:
                # Surface unexpected transport calls in the test, even when
                # production correctly isolates a remote HTTP failure.
                state.errors.append(error)
                status, result = 500, {'error': 'unexpected fixture request'}
            body = json.dumps(result, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_GET = do_POST = do_PUT = handle_request

        def log_message(self, *_args):
            pass

    server = HTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.01})
    worker.start()
    state.url = f'http://127.0.0.1:{server.server_port}'
    try:
        yield state
        assert not state.errors, state.errors
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)
        assert not worker.is_alive()


def _config(remote, directory):
    return {'immich': {
        'url': remote.url, 'api_key': 'fixture-key', 'timeout_seconds': 3,
        'owner_id': 'owner-a', 'library_id': 'library-a',
        'path_map': [{'facet_prefix': str(directory) + os.sep, 'immich_prefix': '/remote/'}],
        'push': {'ratings': True, 'favorites': True, 'top_picks_album': ''},
        'webhook': {'token_env': 'FACET_TEST_DELIVERY_TOKEN', 'header': 'x-facet-token'},
    }}


def _asset(asset_id, filename):
    return {'id': asset_id, 'originalPath': '/remote/' + filename,
            'ownerId': 'owner-a', 'libraryId': 'library-a'}


def _page(items, cursor=None):
    return {'assets': {'items': items, 'nextPage': cursor}}


def _state(conn):
    row = conn.execute("SELECT value FROM stats_cache WHERE key='immich_synced_paths:global'").fetchone()
    return json.loads(row[0]) if row else {}


@pytest.fixture
def delivery(tmp_path, remote, monkeypatch, seed_photos_prefix):
    from api import config

    directory = tmp_path / 'photos'
    directory.mkdir()
    paths = {name: str(directory / (name + '.jpg')) for name in ('bad', 'good')}
    for path in paths.values():
        Path(path).write_bytes(b'untouched original')
    seed_photos_prefix(str(directory) + os.sep, [dict(path=path, filename=Path(path).name,
                       star_rating=4, is_favorite=1, aggregate=8) for path in paths.values()])
    monkeypatch.setitem(config._FULL_CONFIG, 'immich', _config(remote, directory)['immich'])
    monkeypatch.setenv('FACET_TEST_DELIVERY_TOKEN', 'fixture-webhook-secret')
    original_state = {paths['bad']: {'rating': False, 'favorite': True},
                      '/unrelated.jpg': {'rating': True, 'favorite': False}}
    keys = ('immich_synced_paths:global', 'immich_webhook_pending:global')
    with get_db() as conn, conn:
        previous = [tuple(row) for row in conn.execute(
            'SELECT key,value,updated_at FROM stats_cache WHERE key IN (?,?)', keys)]
        conn.execute('DELETE FROM stats_cache WHERE key IN (?,?)', keys)
        conn.execute("INSERT OR REPLACE INTO stats_cache(key,value,updated_at) VALUES(?,?,1)",
                     ('immich_synced_paths:global', json.dumps(original_state)))
        before = [tuple(row) for row in conn.execute('SELECT path,star_rating,is_favorite FROM photos ORDER BY path')]
    try:
        yield paths, original_state, before
    finally:
        with get_db() as conn, conn:
            conn.execute('DELETE FROM stats_cache WHERE key IN (?,?)', keys)
            conn.executemany('INSERT INTO stats_cache(key,value,updated_at) VALUES(?,?,?)', previous)


@pytest.mark.parametrize('bad', ['empty-get', 'owner', 'library', 'non-dict-item', 'invalid-cursor'])
@pytest.mark.parametrize('bad_first', [True, False])
def test_rejected_hint_keeps_its_state_while_another_entry_pushes(
        client, remote, delivery, bad, bad_first):
    paths, original_state, before = delivery

    def route(method, path, payload):
        if method == 'GET':
            name = path.rsplit('/', 1)[-1]
            item = _asset(name, name + '.jpg')
            if name == 'bad':
                if bad == 'empty-get':
                    return {}
                if bad in ('owner', 'library'):
                    item['ownerId' if bad == 'owner' else 'libraryId'] = 'outside-scope'
            return item
        if method == 'POST':
            name = Path(payload['originalPath']).stem
            item = _asset(name, name + '.jpg')
            if name == 'bad' and bad == 'non-dict-item':
                return _page([item, None])
            return _page([item], 'invalid' if name == 'bad' and bad == 'invalid-cursor' else None)
        assert (method, path) == ('PUT', '/api/assets')
        return None

    remote.route = route
    names = ['bad', 'good'] if bad_first else ['good', 'bad']
    body = [{'originalPath': '/remote/' + name + '.jpg', 'id': name} for name in names]
    denied = client.post('/api/immich/webhook', headers={'x-facet-token': 'wrong'}, json=body)
    assert denied.status_code == 403
    assert remote.requests == []
    response = client.post('/api/immich/webhook', headers={'x-facet-token': 'fixture-webhook-secret'}, json=body)
    assert response.status_code == 202, response.text
    assert response.json() == dict(received=2, pushed=1, failed=1, pending=0, skipped=0, unmatched=0)
    assert [payload for method, _, payload in remote.requests if method == 'PUT'] == [
        {'ids': ['good'], 'rating': 4, 'isFavorite': True}]
    with get_db() as conn:
        assert _state(conn) == {**original_state, paths['good']: {'rating': True, 'favorite': True}}
        assert [tuple(row) for row in conn.execute('SELECT path,star_rating,is_favorite FROM photos ORDER BY path')] == before
        assert conn.execute("SELECT value FROM stats_cache WHERE key='immich_webhook_pending:global'").fetchone() is None
    assert all(Path(path).read_bytes() == b'untouched original' for path in paths.values())


def test_hinted_id_is_quoted_in_the_actual_http_target(client, remote, delivery):
    paths, original_state, _ = delivery
    asset_id = 'id/ ?#%+雪'
    expected_target = '/api/assets/id%2F%20%3F%23%25%2B%E9%9B%AA'

    def route(method, path, _payload):
        if method == 'GET':
            assert path == expected_target
            return _asset(asset_id, 'good.jpg')
        if method == 'POST':
            return _page([_asset(asset_id, 'good.jpg')])
        assert (method, path) == ('PUT', '/api/assets')
        return None

    remote.route = route
    response = client.post('/api/immich/webhook', headers={'x-facet-token': 'fixture-webhook-secret'},
                           json={'id': asset_id, 'originalPath': '/remote/good.jpg'})
    assert response.status_code == 202
    assert response.json()['pushed'] == 1
    assert remote.requests[0] == ('GET', expected_target, None)
    assert remote.requests[-1] == ('PUT', '/api/assets', {'ids': [asset_id], 'rating': 4, 'isFavorite': True})
    with get_db() as conn:
        assert _state(conn) == {**original_state, paths['good']: {'rating': True, 'favorite': True}}


@pytest.fixture
def cli_library(tmp_path, remote):
    directory = tmp_path / 'photos'
    directory.mkdir()
    photo = directory / 'a.jpg'
    photo.write_bytes(b'untouched CLI original')
    db = tmp_path / 'library.db'
    init_database(str(db))
    with closing(sqlite3.connect(db)) as conn:
        conn.execute('INSERT INTO photos(path,filename,star_rating,is_favorite) VALUES(?,?,4,1)',
                     (str(photo), photo.name))
        conn.commit()
        # The library is in WAL mode: fold the row into library.db so a byte snapshot
        # taken before the CLI runs is not changed by the CLI's own checkpoint on close.
        conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    config = tmp_path / 'scoring_config.json'
    config.write_text(json.dumps(_config(remote, directory)), encoding='utf-8')
    return db, photo, config


def _cli(library, *flags):
    db, _, config = library
    env = {**os.environ, 'FACET_CONFIG': str(config)}
    for key in ('DB_PATH', 'FACET_JWT_SECRET', 'FACET_SCORE_LOG', 'FACET_NO_CONFIG_MIGRATION'):
        env.pop(key, None)
    return subprocess.run([sys.executable, 'facet.py', '--immich-sync', '--db', str(db),
                           '--config', str(config), *flags], cwd=Path(__file__).resolve().parents[1],
                          env=env, capture_output=True, text=True, encoding='utf-8', timeout=30)


@pytest.mark.parametrize('stage', ['bulk', 'fallback'])
@pytest.mark.parametrize('cursor', [2.0, True, {}, [], '', '+2', '２', '1'])
def test_cli_rejects_invalid_shared_cursors_before_any_update(cli_library, remote, stage, cursor):
    db, photo, config = cli_library
    before = {path: path.read_bytes() for path in (db, photo, config)}

    def route(method, path, payload):
        assert (method, path) == ('POST', '/api/search/metadata')
        if stage == 'fallback' and 'originalPath' not in payload:
            return _page([])
        return _page([_asset('one', 'a.jpg')], cursor)

    remote.route = route
    result = _cli(cli_library)
    output = result.stdout + result.stderr
    assert result.returncode == (1 if stage == 'bulk' else 0), output
    assert ('pagination' if stage == 'bulk' else '1 identity conflict(s)') in output
    assert [payload['page'] for method, _, payload in remote.requests if method == 'POST'] == (
        [1] if stage == 'bulk' else [1, 1])
    with sqlite3.connect(db) as conn:
        assert _state(conn) == {}
    assert all(path.read_bytes() == value for path, value in before.items())


@pytest.mark.parametrize('cursor', [2, '2'])
@pytest.mark.parametrize('dry_run', [False, True])
@pytest.mark.parametrize('stage', ['bulk', 'fallback'])
def test_cli_accepts_integer_and_string_pages_then_pushes_once(cli_library, remote, cursor, dry_run, stage):
    db, photo, config = cli_library
    original, config_before = photo.read_bytes(), config.read_bytes()

    def route(method, path, payload):
        if method == 'POST':
            assert path == '/api/search/metadata'
            if stage == 'fallback' and 'originalPath' not in payload:
                return _page([])
            return _page([_asset('one', 'a.jpg')], cursor if payload['page'] == 1 else None)
        assert (method, path) == ('PUT', '/api/assets')
        return None

    remote.route = route
    result = _cli(cli_library, *(['--dry-run'] if dry_run else []))
    assert result.returncode == 0, result.stderr
    assert '1 matched, 0 unmatched, 1 updated' in result.stdout + result.stderr
    assert [payload['page'] for method, _, payload in remote.requests if method == 'POST'] == (
        [1, 2] if stage == 'bulk' else [1, 1, 2])
    assert [payload for method, _, payload in remote.requests if method == 'PUT'] == (
        [] if dry_run else [{'ids': ['one'], 'rating': 4, 'isFavorite': True}])
    with sqlite3.connect(db) as conn:
        assert _state(conn) == ({} if dry_run else {str(photo): {'rating': True, 'favorite': True}})
    assert photo.read_bytes() == original
    assert config.read_bytes() == config_before


@pytest.mark.parametrize('stage', ['bulk', 'fallback'])
def test_cli_refused_pagination_keeps_a_clear_for_a_later_retry(cli_library, remote, stage):
    db, photo, _ = cli_library
    malformed = False

    def route(method, path, payload):
        if method == 'POST':
            if stage == 'fallback' and 'originalPath' not in payload:
                return _page([])
            return _page([_asset('one', 'a.jpg')], 2.9 if malformed else None)
        assert (method, path) == ('PUT', '/api/assets')
        return None

    remote.route = route
    assert _cli(cli_library).returncode == 0
    with sqlite3.connect(db) as conn:
        saved = _state(conn)
        assert saved == {str(photo): {'rating': True, 'favorite': True}}
        conn.execute('UPDATE photos SET star_rating=0,is_favorite=0')
    remote.requests.clear()
    malformed = True
    refused = _cli(cli_library)
    assert refused.returncode == (1 if stage == 'bulk' else 0), refused.stderr
    assert all(method != 'PUT' for method, _, _ in remote.requests)
    with sqlite3.connect(db) as conn:
        assert _state(conn) == saved
    malformed = False
    remote.requests.clear()
    retried = _cli(cli_library)
    assert retried.returncode == 0, retried.stderr
    assert [payload for method, _, payload in remote.requests if method == 'PUT'] == [
        {'ids': ['one'], 'rating': None, 'isFavorite': False}]
    with sqlite3.connect(db) as conn:
        assert _state(conn) == {}
    assert photo.read_bytes() == b'untouched CLI original'


@pytest.mark.parametrize('count', [20, 23])
def test_conflict_logs_are_bounded_without_undercounting(tmp_path, remote, caplog, count):
    db = tmp_path / 'conflicts.db'
    init_database(str(db))
    paths = [str(tmp_path / f'{index}.jpg') for index in range(count)]
    with sqlite3.connect(db) as conn:
        conn.executemany('INSERT INTO photos(path,star_rating) VALUES(?,4)', [(path,) for path in paths])

    def route(method, path, _payload):
        assert (method, path) == ('POST', '/api/search/metadata')
        return _page([_asset(f'{index}-{duplicate}', f'{index}.jpg')
                      for index in range(count) for duplicate in range(2)])

    remote.route = route
    with caplog.at_level(logging.WARNING, logger='sync.immich'):
        summary = sync_to_immich(str(db), _config(remote, tmp_path))
    assert summary['identity_conflicts'] == count
    assert summary['matched'] == summary['updated'] == summary['albums_created'] == 0
    messages = [record.getMessage() for record in caplog.records if record.name == 'sync.immich']
    assert sum(message.startswith('Immich identity conflict for ') for message in messages) == 20
    assert [message for message in messages if message.startswith('... and ')] == (
        [] if count == 20 else ['... and 3 more identity conflicts'])
    with sqlite3.connect(db) as conn:
        assert _state(conn) == {}
        assert conn.execute('SELECT count(*) FROM photos WHERE star_rating=4').fetchone()[0] == count
