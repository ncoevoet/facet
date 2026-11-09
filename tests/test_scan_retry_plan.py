"""Exact retry scope and refusal before scanner/model/database initialization."""

import os
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import sys

import pytest

import facet
from config import ScoringConfig
from db.schema import init_database
from processing.scan_retry import (
    RetryPlanError, capture_retry_plan, read_retry_manifest, retry_plan_paths,
    write_retry_manifest,
)


@pytest.fixture
def failed_run(tmp_path):
    db = str(tmp_path / 'scan.db')
    init_database(db)
    first = tmp_path / ('café one.jpg' if os.name == 'nt' else 'café "one".jpg')
    second = tmp_path / 'two.jpg'
    first.write_bytes(b'first')
    second.write_bytes(b'second')
    with sqlite3.connect(db) as conn:
        for run_id, path in enumerate((first, second), 1):
            conn.execute(
                "INSERT INTO scan_runs (id, mode, args_json, status, finished_at) "
                "VALUES (?, 'multi-pass', '{}', 'completed', datetime('now'))", (run_id,),
            )
            conn.execute(
                "INSERT INTO scan_failures (scan_run_id, path, stage, error) VALUES (?, ?, 'load', 'failed')",
                (run_id, str(path)),
            )
    conn.close()
    return db, first, second


@pytest.fixture
def scanner_spies(monkeypatch):
    calls = {'initialized': 0, 'paths': [], 'bursts': 0}

    class FakeFacet:
        def __init__(self, db_path, config_path, multi_pass):
            calls['initialized'] += 1
            self.db_path = db_path
            self.config = ScoringConfig(config_path)

        def commit(self):
            pass

        def filter_unscanned_paths(self, paths):
            return set(paths)

    class Processor:
        def __init__(self, *args, **kwargs):
            self.db_path = args[0].db_path
            self.metrics = {'photos_saved': 0}

        def process_directory(self, paths):
            assert facet.library_job_holder(self.db_path) is not None
            calls['paths'] += paths
            self.metrics['photos_saved'] += len(paths) if calls.get('save', True) else 0

    def bursts(*args):
        calls['bursts'] += 1

    monkeypatch.setattr('processing.scorer.Facet', FakeFacet)
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
    return calls


def test_numeric_retry_scope_does_not_select_newer_run(failed_run, scanner_spies, monkeypatch):
    db, first, second = failed_run
    monkeypatch.setattr(sys, 'argv', ['facet.py', '--retry-failed', '1', '--db', db])
    facet.main()
    assert scanner_spies['paths'] == [str(first)]
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT path FROM scan_failures').fetchall() == [(str(second),)]


def test_manifest_scores_only_captured_files_without_library_tail(failed_run, scanner_spies, monkeypatch):
    db, first, second = failed_run
    plan = capture_retry_plan(db, None, 1)
    filename, digest = write_retry_manifest(plan, first.parent)
    try:
        # POSIX mode bits do not describe access-control lists on Windows.
        if os.name != 'nt':
            assert os.stat(filename).st_mode & 0o077 == 0
        monkeypatch.setattr(sys, 'argv', [
            'facet.py', '--retry-plan', filename, '--retry-plan-sha256', digest, '--db', db,
        ])
        facet.main()
        assert scanner_spies['paths'] == [str(first)]
        assert scanner_spies['bursts'] == 0
        with sqlite3.connect(db) as conn:
            assert conn.execute('SELECT path FROM scan_failures').fetchall() == [(str(second),)]
            args = conn.execute('SELECT args_json FROM scan_runs ORDER BY id DESC LIMIT 1').fetchone()[0]
            assert 'retry_of' in args and 'skip_library_passes' in args
    finally:
        Path(filename).unlink()


@pytest.mark.parametrize('captured', [True, False])
def test_zero_saved_retry_retains_source_failure_receipts(failed_run, scanner_spies, monkeypatch, captured):
    db, first, second = failed_run
    scanner_spies['save'] = False
    filename, digest = write_retry_manifest(capture_retry_plan(db, None, 1), first.parent)
    try:
        command = (['--retry-plan', filename, '--retry-plan-sha256', digest]
                   if captured else ['--retry-failed', '1'])
        monkeypatch.setattr(sys, 'argv', ['facet.py', *command, '--db', db])
        with pytest.raises(SystemExit) as error:
            facet.main()
        assert error.value.code == 4
        with sqlite3.connect(db) as conn:
            assert conn.execute('SELECT path FROM scan_failures ORDER BY scan_run_id').fetchall() == [
                (str(first),), (str(second),),
            ]
            assert conn.execute('SELECT status FROM scan_runs ORDER BY id DESC LIMIT 1').fetchone()[0] == 'failed'
    finally:
        Path(filename).unlink()


@pytest.mark.parametrize('change', ['file', 'failures', 'config', 'database', 'digest'])
def test_stale_manifest_refuses_before_scanner_initialization(
    failed_run, scanner_spies, monkeypatch, change,
):
    db, first, _ = failed_run
    config = first.parent / 'config.json'
    config.write_text('{}', encoding='utf-8')
    plan = capture_retry_plan(db, str(config), 1)
    filename, digest = write_retry_manifest(plan, first.parent)
    try:
        if change == 'file':
            first.write_bytes(b'replaced file')
        elif change == 'failures':
            with sqlite3.connect(db) as conn:
                conn.execute("UPDATE scan_failures SET error='another failure' WHERE scan_run_id=1")
        elif change == 'config':
            config.write_text('{"processing":{"mode":"single-pass"}}', encoding='utf-8')
        elif change == 'database':
            # Same rows at the same pathname, different database identity.
            with sqlite3.connect(db) as src, sqlite3.connect(db + '.new') as dest:
                src.backup(dest)
            src.close()
            dest.close()
            os.replace(db + '.new', db)
        else:
            digest = '0' * 64
        monkeypatch.setattr(sys, 'argv', [
            'facet.py', '--retry-plan', filename, '--retry-plan-sha256', digest,
            '--db', db, '--config', str(config),
        ])
        with pytest.raises(SystemExit) as error:
            facet.main()
        assert error.value.code == 2
        assert scanner_spies['initialized'] == 0
        with sqlite3.connect(db) as conn:
            assert conn.execute('SELECT COUNT(*) FROM scan_runs').fetchone()[0] == 2
    finally:
        Path(filename).unlink()


def test_preview_discloses_missing_and_raw_pair_without_reading_or_writing_photos(failed_run):
    db, first, _ = failed_run
    raw = first.with_suffix('.CR2')
    raw.write_bytes(b'raw')
    missing = first.parent / 'missing.jpg'
    with sqlite3.connect(db) as conn:
        conn.executemany(
            "INSERT INTO scan_failures (scan_run_id, path, stage) VALUES (1, ?, 'load')",
            [(str(raw),), (str(missing),)],
        )
    plan = capture_retry_plan(db, None, 1)
    assert retry_plan_paths(plan) == [first]
    assert {item['omission'] for item in plan['files']} == {None, 'raw_paired', 'missing'}
    filename, digest = write_retry_manifest(plan, first.parent)
    try:
        missing.write_bytes(b'now present')
        with pytest.raises(RetryPlanError, match='changed'):
            read_retry_manifest(filename, digest, db, None)
    finally:
        Path(filename).unlink()


@pytest.mark.parametrize('extra', [['--force'], ['--recompute-average'], ['--retry-failed'], ['--dry-run']])
def test_retry_manifest_cannot_mix_other_commands(failed_run, scanner_spies, monkeypatch, extra):
    db, first, _ = failed_run
    filename, digest = write_retry_manifest(capture_retry_plan(db, None, 1), first.parent)
    try:
        monkeypatch.setattr(sys, 'argv', [
            'facet.py', '--retry-plan', filename, '--retry-plan-sha256', digest, '--db', db, *extra,
        ])
        with pytest.raises(SystemExit) as error:
            facet.main()
        assert error.value.code == 2
        assert scanner_spies['initialized'] == 0
    finally:
        Path(filename).unlink()


def test_retry_preview_never_migrates_an_old_database(tmp_path):
    db = tmp_path / 'old.db'
    with sqlite3.connect(db) as conn:
        conn.execute('CREATE TABLE old_schema (value TEXT)')
    conn.close()
    before = db.read_bytes()
    with pytest.raises(RetryPlanError, match='could not read'):
        capture_retry_plan(str(db), None, 1)
    assert db.read_bytes() == before


def test_preview_refuses_active_and_oversize_runs_without_truncation(failed_run, monkeypatch):
    db, _, _ = failed_run
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE scan_runs SET status='running', finished_at=NULL WHERE id=1")
    with pytest.raises(RetryPlanError, match='ended scan'):
        capture_retry_plan(db, None, 1)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE scan_runs SET status='interrupted' WHERE id=1")
    monkeypatch.setattr('processing.scan_retry.MAX_RETRY_FILES', 0)
    with pytest.raises(RetryPlanError, match='at most'):
        capture_retry_plan(db, None, 1)


def test_interrupted_captured_retry_preserves_source_failures(failed_run, scanner_spies, monkeypatch):
    db, first, second = failed_run

    class InterruptedProcessor:
        def __init__(self, *args, **kwargs):
            pass

        def process_directory(self, paths):
            raise KeyboardInterrupt()

    monkeypatch.setattr('processing.multi_pass.ChunkedMultiPassProcessor', InterruptedProcessor)
    filename, digest = write_retry_manifest(capture_retry_plan(db, None, 1), first.parent)
    try:
        monkeypatch.setattr(sys, 'argv', [
            'facet.py', '--retry-plan', filename, '--retry-plan-sha256', digest, '--db', db,
        ])
        with pytest.raises(SystemExit) as exit_info:
            facet.main()
        assert exit_info.value.code == facet.INTERRUPTED_EXIT_CODE
        assert scanner_spies['bursts'] == 0
        with sqlite3.connect(db) as conn:
            assert conn.execute('SELECT path FROM scan_failures ORDER BY scan_run_id').fetchall() == [
                (str(first),), (str(second),),
            ]
            assert conn.execute('SELECT status FROM scan_runs ORDER BY id DESC LIMIT 1').fetchone()[0] == 'interrupted'
    finally:
        Path(filename).unlink()


@pytest.mark.parametrize('captured', [True, False])
def test_failed_bookkeeping_cannot_erase_last_failure_receipt(failed_run, scanner_spies, monkeypatch, captured):
    """A swallowed transient failure-record write must not look like success."""
    from processing import scan_state

    db, first, _ = failed_run
    real_connection = scan_state.get_connection

    class FailedReceiptProcessor:
        def __init__(self, *args, **kwargs):
            self.on_error = kwargs['on_error']
            self.metrics = {'photos_saved': 0}

        def process_directory(self, paths):
            @contextmanager
            def refuse_write(*args, **kwargs):
                # Fail the failure flush, then permit finish's real transaction.
                monkeypatch.setattr(scan_state, 'get_connection', real_connection)
                raise sqlite3.OperationalError('temporary write refusal')
                yield  # pragma: no cover

            monkeypatch.setattr(scan_state, 'get_connection', refuse_write)
            self.on_error(paths[0], 'load', 'still unreadable')

    monkeypatch.setattr('processing.multi_pass.ChunkedMultiPassProcessor', FailedReceiptProcessor)
    filename, digest = write_retry_manifest(capture_retry_plan(db, None, 1), first.parent)
    try:
        command = (['--retry-plan', filename, '--retry-plan-sha256', digest]
                   if captured else ['--retry-failed', '1'])
        monkeypatch.setattr(sys, 'argv', ['facet.py', *command, '--db', db])
        with pytest.raises(SystemExit) as error:
            facet.main()
        assert error.value.code == 1
        with sqlite3.connect(db) as conn:
            assert conn.execute('SELECT path FROM scan_failures WHERE scan_run_id=1').fetchall() == [(str(first),)]
            assert conn.execute('SELECT status FROM scan_runs ORDER BY id DESC LIMIT 1').fetchone()[0] == 'failed'
    finally:
        Path(filename).unlink()


def test_actual_child_reads_captured_utf8_plan_from_pipe_without_private_file(failed_run, tmp_path):
    import hashlib
    import subprocess
    from processing.scan_retry import retry_manifest_bytes
    db, first, _ = failed_run
    config = tmp_path / 'config.json'
    config.write_text('{}', encoding='utf-8')
    plan = capture_retry_plan(db, str(config), 1)
    payload = retry_manifest_bytes(plan)
    digest = hashlib.sha256(payload).hexdigest()
    before = Path(db).read_bytes()
    script = """
import json,sys
sys.stdout.reconfigure(encoding='utf-8')
from processing.scan_retry import read_retry_manifest,retry_plan_paths
plan=read_retry_manifest('-',sys.argv[1],sys.argv[2],sys.argv[3])
print(json.dumps([str(path) for path in retry_plan_paths(plan)],ensure_ascii=False))
"""
    result = subprocess.run([sys.executable, '-c', script, digest, db, str(config)],
                            input=payload, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr.decode('utf-8')
    import json
    assert json.loads(result.stdout.decode('utf-8')) == [str(first)]
    assert not list(tmp_path.glob('.facet-retry-*'))
    assert Path(db).read_bytes() == before
    truncated = subprocess.run([sys.executable, '-c', script, digest, db, str(config)],
                               input=payload[:20], capture_output=True, timeout=20)
    assert truncated.returncode != 0
    assert Path(db).read_bytes() == before


def test_os_owned_input_survives_launcher_death_without_orphan_worklist(failed_run, tmp_path):
    import hashlib
    import json
    import subprocess
    from processing.scan_retry import retry_manifest_bytes
    db, first, _ = failed_run
    config = tmp_path / 'config.json'
    config.write_text('{}', encoding='utf-8')
    payload = retry_manifest_bytes(capture_retry_plan(db, str(config), 1))
    digest = hashlib.sha256(payload).hexdigest()
    before = {path.name for path in tmp_path.iterdir()}
    child = """
import json,sys
sys.stdout.reconfigure(encoding='utf-8')
from processing.scan_retry import read_retry_manifest,retry_plan_paths
plan=read_retry_manifest('-',sys.argv[1],sys.argv[2],sys.argv[3])
print(json.dumps([str(p) for p in retry_plan_paths(plan)],ensure_ascii=False),flush=True)
"""
    parent = """
import os,sys,tempfile,subprocess
transport=tempfile.TemporaryFile(mode='w+b',dir=sys.argv[5])
transport.write(sys.stdin.buffer.read());transport.seek(0)
subprocess.Popen([sys.executable,'-c',sys.argv[1],*sys.argv[2:5]],stdin=transport)
os._exit(0)
"""
    # Captured stdout stays open in the child: communicate waits for its EOF,
    # independently of the launcher's abrupt exit, without timing sleeps.
    result = subprocess.run([sys.executable, '-c', parent, child, digest, db, str(config), str(tmp_path)],
                            input=payload, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr.decode('utf-8')
    assert json.loads(result.stdout.decode('utf-8')) == [str(first)]
    assert {path.name for path in tmp_path.iterdir()} == before
