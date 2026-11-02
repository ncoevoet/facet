"""Durable scan identity and complete-pipeline outcome, with no ML models."""

from contextlib import contextmanager
from contextlib import closing
import sqlite3
import json
import os
import subprocess
import sys

from fastapi.testclient import TestClient
import pytest

import facet
from api import create_app
from api.auth import CurrentUser, require_scan_access
from api.routers import scan
from config import ScoringConfig
from db.schema import init_database
from processing.scan_state import VIEWER_JOB_ID_ENV

JOB = 'a' * 32

# Scanner bookkeeping schema at 8c97dbee, before whole-pipeline metadata.
# Use the actual prior DDL, not DROP COLUMN (SQLite >=3.35 only).
RELEASED_SCAN_SCHEMA = """
CREATE TABLE scan_runs (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 started_at TEXT DEFAULT (datetime('now')), finished_at TEXT,
 status TEXT NOT NULL DEFAULT 'running', mode TEXT, args_json TEXT,
 total_files INTEGER, processed_files INTEGER DEFAULT 0,
 failed_files INTEGER DEFAULT 0, heartbeat_at TEXT
);
CREATE TABLE scan_failures (
 scan_run_id INTEGER NOT NULL REFERENCES scan_runs(id) ON DELETE CASCADE,
 path TEXT NOT NULL, stage TEXT, error TEXT,
 timestamp TEXT DEFAULT (datetime('now')), PRIMARY KEY (scan_run_id,path)
);
CREATE INDEX idx_scan_runs_status ON scan_runs(status);
CREATE INDEX idx_scan_failures_run ON scan_failures(scan_run_id);
"""


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    db = tmp_path / 'job.db'
    init_database(str(db))
    photo = tmp_path / 'one.jpg'
    photo.write_bytes(b'fixture')
    observations = []
    class Scorer:
        def __init__(self, db_path, config_path, **kwargs):
            self.db_path = db_path
            self.config = ScoringConfig(config_path)
        def filter_unscanned_paths(self, paths):
            return set(paths)
        def commit(self):
            pass
    class Processor:
        def __init__(self, *args, **kwargs):
            self.metrics = {'photos_saved': 0}
        def process_directory(self, paths):
            assert paths == [str(photo)]
            self.metrics['photos_saved'] += len(paths)
    def bursts(*args):
        with sqlite3.connect(db) as conn:
            observations.append(conn.execute('SELECT status,job_status,job_phase FROM scan_runs').fetchone())
    monkeypatch.setattr('processing.scorer.Facet', Scorer)
    monkeypatch.setattr('processing.multi_pass.ChunkedMultiPassProcessor', Processor)
    monkeypatch.setattr('models.model_manager.ModelManager', lambda *a, **k: object())
    monkeypatch.setattr('plugins.init_global_plugin_manager', lambda **kwargs: None)
    monkeypatch.setattr('processing.scorer.process_bursts', bursts)
    monkeypatch.setattr(facet, 'detect_all_sequences', lambda *a, **k: None)
    monkeypatch.setattr('tag_existing.tagging_enabled', lambda *a: False)
    monkeypatch.setattr('db.vec.populate_vec_table', lambda *a: None)
    monkeypatch.setattr(facet, 'run_moment_detection', lambda *a, **k: {})
    monkeypatch.setattr(facet, 'run_junk_detection', lambda *a, **k: {})
    monkeypatch.setattr(facet, '_print_scan_summary', lambda *a: None)
    monkeypatch.setenv(VIEWER_JOB_ID_ENV, JOB)
    monkeypatch.setattr(sys, 'argv', ['facet.py', str(photo), '--db', str(db)])
    return db, observations


def test_job_identity_and_completion_persist_only_after_the_full_tail(pipeline):
    db, observed = pipeline
    facet.main()
    assert observed == [('completed', 'running', 'bursts')]
    with sqlite3.connect(db) as conn:
        row = conn.execute('SELECT viewer_job_id,status,job_status,job_phase,job_finished_at FROM scan_runs').fetchone()
    assert row[:4] == (JOB, 'completed', 'completed', 'done')
    assert row[4] is not None
    with sqlite3.connect(db) as conn:
        plan = conn.execute('EXPLAIN QUERY PLAN SELECT id FROM scan_runs WHERE viewer_job_id=?', (JOB,)).fetchall()
    assert any('idx_scan_runs_viewer_job' in item[3] for item in plan)


def test_tail_failure_does_not_relabel_scoring_as_failed_or_pipeline_as_complete(pipeline, monkeypatch):
    db, _ = pipeline
    def fail(*args):
        raise RuntimeError('Finalization failed')
    monkeypatch.setattr('processing.scorer.process_bursts', fail)
    with pytest.raises(RuntimeError, match='Finalization failed'):
        facet.main()
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT status,job_status,job_phase FROM scan_runs').fetchone() == ('completed', 'failed', 'bursts')


def test_scoring_interruption_records_both_lifetimes_and_skips_tail(pipeline, monkeypatch):
    db, observed = pipeline
    class Interrupted:
        def __init__(self, *args, **kwargs):
            pass
        def process_directory(self, paths):
            raise KeyboardInterrupt()
    monkeypatch.setattr('processing.multi_pass.ChunkedMultiPassProcessor', Interrupted)
    facet.main()
    assert not observed
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT status,job_status,job_phase FROM scan_runs').fetchone() == ('interrupted', 'interrupted', 'scoring')


def job_client(db, monkeypatch):
    @contextmanager
    def read_db():
        conn = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    monkeypatch.setattr(scan, 'get_db', read_db)
    monkeypatch.setitem(scan.VIEWER_CONFIG, 'features', {'show_scan_button': True})
    app = create_app()
    app.dependency_overrides[require_scan_access] = lambda: CurrentUser(user_id='root', role='superadmin', edition_authenticated=True)
    return TestClient(app)


def test_fresh_viewer_reads_exact_durable_job_without_assuming_process_liveness(pipeline, monkeypatch):
    db, _ = pipeline
    facet.main()
    # The scanner's committed WAL can checkpoint on a later connection close;
    # settle that before comparing the read-only handler's physical DB bytes.
    with closing(sqlite3.connect(db)) as conn:
        conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    before = db.read_bytes()
    client = job_client(db, monkeypatch)
    response = client.get('/api/scan/jobs/' + JOB)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['job_id'] == JOB and body['liveness'] == 'not_checked'
    assert body['recorded']['job_status'] == 'completed'
    assert body['recorded']['job_phase'] == 'done'
    assert str(db.parent) not in response.text and 'args_json' not in response.text
    assert db.read_bytes() == before
    assert client.get('/api/scan/jobs/' + 'b' * 32).status_code == 404
    assert client.get('/api/scan/jobs/not-a-job').status_code == 422
    monkeypatch.setitem(scan.VIEWER_CONFIG, 'features', {'show_scan_button': False})
    assert client.get('/api/scan/jobs/' + JOB).status_code == 403


def test_ambiguous_job_identity_never_selects_a_newer_run(pipeline, monkeypatch):
    db, _ = pipeline
    facet.main()
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO scan_runs(viewer_job_id,status) VALUES (?,'failed')", (JOB,))
    response = job_client(db, monkeypatch).get('/api/scan/jobs/' + JOB)
    assert response.status_code == 409


def test_partial_job_schema_read_is_unavailable_and_never_migrates(pipeline, monkeypatch):
    db, _ = pipeline
    with sqlite3.connect(db) as conn:
        conn.execute('ALTER TABLE scan_runs RENAME COLUMN job_status TO unavailable_job_status')
    conn.close()
    before = db.read_bytes()
    assert job_client(db, monkeypatch).get('/api/scan/jobs/' + JOB).status_code == 503
    assert db.read_bytes() == before


def test_new_process_reads_job_without_the_original_viewer_memory(pipeline, tmp_path):
    db, _ = pipeline
    facet.main()
    config = tmp_path / 'viewer.json'
    config.write_text('{}', encoding='utf-8')
    script = '''
import json, sys
from fastapi.testclient import TestClient
from api import create_app
from api.auth import CurrentUser, require_scan_access
from api.routers import scan
scan.VIEWER_CONFIG['features'] = {'show_scan_button': True}
app = create_app()
app.dependency_overrides[require_scan_access] = lambda: CurrentUser(user_id='root',role='superadmin',edition_authenticated=True)
response = TestClient(app).get('/api/scan/jobs/' + sys.argv[1])
print(json.dumps({'status':response.status_code, 'body':response.json()}))
'''
    env = dict(os.environ, DB_PATH=str(db), FACET_CONFIG=str(config))
    child = subprocess.run([sys.executable, '-c', script, JOB], env=env, capture_output=True, encoding='utf-8', timeout=20, check=True)
    result = json.loads(child.stdout.splitlines()[-1])
    assert result['status'] == 200
    assert result['body']['job_id'] == JOB
    assert result['body']['recorded']['job_status'] == 'completed'
    assert result['body']['liveness'] == 'not_checked'


def test_explicit_schema_upgrade_preserves_old_scoring_records_without_inventing_job_outcomes(tmp_path, monkeypatch):
    db = tmp_path / 'old.db'
    with sqlite3.connect(db) as conn:
        conn.executescript(RELEASED_SCAN_SCHEMA)
        conn.execute("INSERT INTO scan_runs(status,args_json,processed_files) VALUES ('completed','{}',7)")
    conn.close()
    before = db.read_bytes()
    client = job_client(db, monkeypatch)
    history = client.get('/api/scan/runs')
    assert history.status_code == 200, history.text
    assert history.json()['runs'][0]['processed_files'] == 7
    assert history.json()['runs'][0]['job_status'] is None
    assert client.get('/api/scan/jobs/' + JOB).status_code == 503
    assert db.read_bytes() == before
    init_database(str(db))
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT status,processed_files,viewer_job_id,job_status,job_phase,job_finished_at FROM scan_runs').fetchone() == ('completed', 7, None, None, None, None)


def test_invalid_job_environment_refuses_before_scorer_initialization(pipeline, monkeypatch):
    db, _ = pipeline
    monkeypatch.setenv(VIEWER_JOB_ID_ENV, 'not-a-job')
    def forbidden(*args, **kwargs):
        pytest.fail('Scorer initialized with malformed job identity')
    monkeypatch.setattr('processing.scorer.Facet', forbidden)
    with pytest.raises(ValueError, match='Invalid viewer scan job identity'):
        facet.main()
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT COUNT(*) FROM scan_runs').fetchone()[0] == 0
