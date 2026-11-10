"""Fresh interpreter and forced-process-exit checks, only disposable catalogs/files."""
import json
import os
from pathlib import Path
import queue
import sqlite3
import subprocess
import sys
import threading

from api import sidecar_jobs
from db import logical_assets, logical_history, logical_review
from db.schema import init_database
from tests._sidecar_helpers import settle_sidecar_job


def process_env(tmp_path, database):
    config = tmp_path / 'restart-config.json'
    config.write_text('{"viewer":{"password":"fixture-only","edition_password":"fixture-only"}}', encoding='utf-8')
    return {**os.environ, 'DB_PATH': str(database), 'FACET_CONFIG': str(config),
            'FACET_NO_CONFIG_MIGRATION': '1', 'PYTHONIOENCODING': 'utf-8',
            'PYTHONPATH': str(Path(__file__).resolve().parents[1])}


def test_logical_history_restores_in_a_fresh_interpreter(tmp_path):
    database = tmp_path / 'logical.db'
    init_database(str(database))
    labels = {'/library/婚礼/café.jpg': dict(star_rating=5, is_favorite=0, is_rejected=0, is_kept=0),
              '/library/婚礼/café.CR2': dict(star_rating=2, is_favorite=0, is_rejected=0, is_kept=0)}
    with sqlite3.connect(database) as conn:
        conn.executemany('INSERT INTO photos(path,star_rating,is_favorite,is_rejected,is_kept) VALUES (?,?,?,?,?)',
                         [(path, *values.values()) for path, values in labels.items()])
        key = logical_assets.create(conn, list(labels), next(iter(labels)), visibility_sql='1=1')
        logical_review.seed(conn, key, next(iter(labels)), 1, visibility_sql='1=1')
        before = logical_history.capture(conn, key, 'alice', labels)
        logical_review.set_fields(conn, key, 'alice', 1, before['revision'], {'star_rating': 4},
            origin='user', visibility_sql='1=1', file_labels=labels, input_token=before['input_token'])
        after = logical_history.capture(conn, key, 'alice', labels)
        entry = logical_history.record(conn, 'alice', 'alice', {key: before}, {key: after})[0]
    script = """
import json, sqlite3, sys
from db import logical_history, logical_review, logical_assets
body = json.load(sys.stdin)
with sqlite3.connect(body['database']) as conn:
    conn.execute('BEGIN IMMEDIATE')
    fields = ('star_rating', 'is_favorite', 'is_rejected', 'is_kept')
    labels = {row[0]: dict(zip(fields, row[1:])) for row in conn.execute('SELECT path,' + ','.join(fields) + ' FROM photos')}
    refused = False
    try:
        logical_history.restore(conn, 'bob', 'alice', body['entry'], labels, visibility_sql='1=1')
    except logical_assets.AssetConflict:
        refused = True
    changed = logical_history.restore(conn, 'alice', 'alice', body['entry'], labels, visibility_sql='1=1')
    state = logical_review.read(conn, body['key'], 'alice', labels)
    print(json.dumps({'refused': refused, 'changed': changed, 'rating': state['values']['star_rating'],
                      'origin': state['origins']['star_rating']}))
"""
    result = subprocess.run([sys.executable, '-c', script], input=json.dumps(dict(database=str(database), key=key, entry=entry)),
                            encoding='utf-8', capture_output=True, check=True, timeout=30,
                            cwd=tmp_path, env=process_env(tmp_path, database))
    assert json.loads(result.stdout) == {'refused': True, 'changed': 1, 'rating': 5, 'origin': 'file'}
    with sqlite3.connect(database) as conn:
        assert conn.execute('SELECT COUNT(*) FROM organization_history').fetchone()[0] == 2
        assert conn.execute('SELECT reverted FROM organization_history WHERE id=?', (entry,)).fetchone()[0] == 1
        assert dict(conn.execute('SELECT path,star_rating FROM photos')) == {path: value['star_rating'] for path, value in labels.items()}


def test_confirmed_job_survives_forced_worker_exit_and_recovers_exact_unfinished_unit(tmp_path):
    database = tmp_path / 'jobs.db'
    init_database(str(database))
    source = tmp_path / 'source'
    target = tmp_path / 'delivery'
    source.mkdir()
    target.mkdir()
    paths = [str(source / 'first.jpg'), str(source / 'second.jpg')]
    for index, path in enumerate(paths):
        Path(path).write_bytes(bytes([index + 1]))
    script = """
import json, pathlib, sys, threading
from api import sidecar_jobs as jobs
body = json.loads(sys.stdin.readline())
entered = threading.Event()
release = threading.Event()
def work(path):
    if path == body['paths'][1]:
        entered.set()
        release.wait(60)
    pathlib.Path(body['target'], pathlib.Path(path).name).write_bytes(pathlib.Path(path).read_bytes())
    return {'written': 1, 'skipped': 0, 'errors': 0}
files = [{'photo_path': path, 'source': path, 'target': str(pathlib.Path(body['target'], pathlib.Path(path).name))} for path in body['paths']]
state = jobs.start(body['database'], 'alice', body['paths'], work, confirmation_digest='fixture-confirmation', operation='copy',
                   request={'paths': body['paths'], 'mode': 'copy', 'target_dir': body['target']},
                   preflight=lambda: {'files': files, 'missing': [], 'photo_sources': {}})
assert entered.wait(10)
print(json.dumps({'id': state['id']}), flush=True)
sys.stdin.read()
"""
    env = process_env(tmp_path, database)
    process = subprocess.Popen([sys.executable, '-c', script], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, encoding='utf-8', cwd=tmp_path, env=env)
    messages = queue.Queue()
    reader = threading.Thread(target=lambda: messages.put(process.stdout.readline()), daemon=True)
    reader.start()
    try:
        process.stdin.write(json.dumps(dict(database=str(database), paths=paths, target=str(target))) + '\n')
        process.stdin.flush()
        message = json.loads(messages.get(timeout=20))
        assert (target / 'first.jpg').read_bytes() == b'\x01'
        assert not (target / 'second.jpg').exists()
    finally:
        process.kill()
        process.communicate(timeout=10)
        reader.join(5)
    recovery = """
import json, sys
from api import sidecar_jobs as jobs
body = json.load(sys.stdin)
state = jobs.status(body['database'], body['id'], 'alice')
retry = jobs.retry_preview_scope(body['database'], body['id'], 'alice')
refused = False
try:
    jobs.status(body['database'], body['id'], 'bob')
except jobs.JobNotFound:
    refused = True
print(json.dumps({'state': state, 'request': retry['request'], 'units': retry['units'], 'refused': refused}))
"""
    result = subprocess.run([sys.executable, '-c', recovery], input=json.dumps(dict(database=str(database), id=message['id'])),
                            capture_output=True, text=True, encoding='utf-8', check=True, timeout=30, cwd=tmp_path, env=env)
    recovered = json.loads(result.stdout)
    assert recovered['refused'] is True
    assert recovered['state']['state'] == 'interrupted'
    assert recovered['state']['processed'] == recovered['state']['written'] == 1
    assert recovered['request']['paths'] == [paths[1]]
    assert [unit['photo_path'] for unit in recovered['units']] == [paths[1]]
    assert not (target / 'second.jpg').exists()
    # A fresh admission proves the terminated worker's OS lock was released.
    next_job = sidecar_jobs.start(str(database), 'alice', [], lambda path: None)
    assert settle_sidecar_job(str(database), next_job['id'], 'alice')['state'] == 'completed'
