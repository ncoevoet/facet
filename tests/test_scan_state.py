"""Tests for scan run bookkeeping (processing/scan_state.py) and the
structured progress protocol (processing/progress.py)."""

import sqlite3

import pytest

from db.schema import init_database
from processing.progress import PROGRESS_PREFIX, emit_progress, parse_progress_line
from processing import scan_state
from processing.scan_state import (
    ScanJobLifecycle,
    ScanRun,
    filter_paths_scanned_before,
    filter_paths_scanned_since,
    get_failed_paths,
    get_last_resumable_run,
    scan_in_progress,
)


@pytest.fixture()
def scan_db(tmp_path):
    db_path = str(tmp_path / "scan_state.db")
    init_database(db_path)
    return db_path


class TestScanRunLifecycle:
    def test_start_creates_running_row(self, scan_db):
        run = ScanRun.start(scan_db, 'multi-pass', {'directories': ['/photos']}, 100)
        conn = sqlite3.connect(scan_db)
        row = conn.execute(
            "SELECT status, mode, total_files, args_json FROM scan_runs WHERE id = ?",
            (run.run_id,),
        ).fetchone()
        conn.close()
        assert row[0] == 'running'
        assert row[1] == 'multi-pass'
        assert row[2] == 100
        assert '/photos' in row[3]

    def test_finish_records_status_and_counts(self, scan_db):
        run = ScanRun.start(scan_db, 'multi-pass', {}, 10)
        run.update_progress(7)
        run.record_failure('/p/bad.jpg', 'load', 'corrupt file')
        run.finish('interrupted')

        conn = sqlite3.connect(scan_db)
        status, processed, failed, finished = conn.execute(
            "SELECT status, processed_files, failed_files, finished_at "
            "FROM scan_runs WHERE id = ?", (run.run_id,),
        ).fetchone()
        failures = conn.execute(
            "SELECT path, stage, error FROM scan_failures WHERE scan_run_id = ?",
            (run.run_id,),
        ).fetchall()
        conn.close()
        assert status == 'interrupted'
        assert processed == 7
        assert failed == 1
        assert finished is not None
        assert failures == [('/p/bad.jpg', 'load', 'corrupt file')]

    def test_duplicate_failure_merges_into_one_row(self, scan_db):
        run = ScanRun.start(scan_db, 'multi-pass', {}, 5)
        run.record_failure('/p/x.jpg', 'load', 'first')
        run.record_failure('/p/x.jpg', 'load', 'second')
        run.finish('failed')
        conn = sqlite3.connect(scan_db)
        count = conn.execute(
            "SELECT COUNT(*) FROM scan_failures WHERE scan_run_id = ?", (run.run_id,),
        ).fetchone()[0]
        stage, error = conn.execute(
            "SELECT stage, error FROM scan_failures WHERE scan_run_id = ? AND path = ?",
            (run.run_id, '/p/x.jpg'),
        ).fetchone()
        conn.close()
        assert count == 1
        assert stage == 'load'
        assert 'first' in error
        assert 'second' in error


class TestTransientBookkeepingFailures:
    """A locked bookkeeping write is retried; only a failure record that never
    reaches the database may fail the scan (the retry plan reads them)."""

    @staticmethod
    def _lock_calls(monkeypatch, failing):
        real, calls = scan_state.get_connection, {'n': 0}
        def flaky(*args, **kwargs):
            calls['n'] += 1
            if calls['n'] in failing:
                raise sqlite3.OperationalError('database is locked')
            return real(*args, **kwargs)
        monkeypatch.setattr(scan_state, 'get_connection', flaky)

    @staticmethod
    def _row(scan_db, run_id):
        with sqlite3.connect(scan_db) as conn:
            return (conn.execute('SELECT status, processed_files, failed_files FROM scan_runs WHERE id = ?',
                                 (run_id,)).fetchone(),
                    conn.execute('SELECT path, stage, error FROM scan_failures WHERE scan_run_id = ?',
                                 (run_id,)).fetchall())

    def test_locked_heartbeat_does_not_fail_the_scan(self, scan_db, monkeypatch):
        run = ScanRun.start(scan_db, 'multi-pass', {}, 10)
        self._lock_calls(monkeypatch, {1})
        run.update_progress(5)
        assert run.finish('completed') is True
        assert self._row(scan_db, run.run_id) == (('completed', 5, 0), [])

    def test_locked_failure_flush_is_retried_by_a_later_flush(self, scan_db, monkeypatch):
        run = ScanRun.start(scan_db, 'multi-pass', {}, 10)
        self._lock_calls(monkeypatch, {1})
        run.record_failure('/p/bad.jpg', 'load', 'corrupt file')
        run.update_progress(10)
        assert run.finish('completed') is True
        assert self._row(scan_db, run.run_id) == (('completed', 10, 1), [('/p/bad.jpg', 'load', 'corrupt file')])

    def test_failure_records_that_never_persist_still_fail_the_scan(self, scan_db, monkeypatch):
        run = ScanRun.start(scan_db, 'multi-pass', {}, 10)
        self._lock_calls(monkeypatch, {1, 2})  # the record's flush and finish's final flush
        run.record_failure('/p/bad.jpg', 'load', 'corrupt file')
        assert run.finish('completed') is False
        assert self._row(scan_db, run.run_id) == (('failed', 0, 0), [])

    def test_failure_after_commit_is_not_requeued(self, scan_db, monkeypatch):
        real = scan_state.get_connection
        calls = {'n': 0}

        class ExitRaises:
            def __init__(self, *args, **kwargs):
                self._inner = real(*args, **kwargs)

            def __enter__(self):
                return self._inner.__enter__()

            def __exit__(self, *exc):
                self._inner.__exit__(*exc)
                calls['n'] += 1
                if calls['n'] == 1:
                    raise sqlite3.OperationalError('disk I/O error')
                return False

        run = ScanRun.start(scan_db, 'multi-pass', {}, 10)
        monkeypatch.setattr(scan_state, 'get_connection', ExitRaises)
        run.record_failure('/p/bad.jpg', 'load', 'corrupt file')
        assert run.finish('completed') is True
        assert self._row(scan_db, run.run_id) == (('completed', 0, 1), [('/p/bad.jpg', 'load', 'corrupt file')])

    def test_requeue_is_capped_and_a_dropped_failure_fails_the_scan(self, scan_db, monkeypatch):
        monkeypatch.setattr(scan_state, 'MAX_PENDING_FAILURES', 2)
        run = ScanRun.start(scan_db, 'multi-pass', {}, 10)
        self._lock_calls(monkeypatch, {1, 2})
        run.record_failure('/p/a.jpg', 'load', 'a')  # flush 1 fails
        run.record_failure('/p/b.jpg', 'load', 'b')  # throttled
        run.record_failure('/p/c.jpg', 'load', 'c')  # throttled
        run._maybe_flush(force=True)  # flush 2 fails: three queued, capped to two
        assert len(run._pending_failures) == 2
        assert run.finish('completed') is False
        assert self._row(scan_db, run.run_id) == (
            ('failed', 0, 2), [('/p/a.jpg', 'load', 'a'), ('/p/b.jpg', 'load', 'b')])

    def test_locked_phase_write_is_retried_and_does_not_fail_the_job(self, scan_db, monkeypatch):
        run = ScanRun.start(scan_db, 'multi-pass', {}, 1)
        assert run.finish('completed') is True
        lifecycle = ScanJobLifecycle()
        lifecycle.attach(run)
        self._lock_calls(monkeypatch, {1, 2})  # 'bursts' and 'done'; finish retries the phase it ends on
        lifecycle.progress('bursts')
        lifecycle.progress('done')
        assert lifecycle.finish('completed') is True
        with sqlite3.connect(scan_db) as conn:
            assert conn.execute('SELECT status, job_status, job_phase FROM scan_runs').fetchone() == (
                'completed', 'completed', 'done')


class TestFailureCounting:
    """scan_runs.failed_files is the number of DISTINCT (run, path) rows in
    scan_failures, however often a path fails and however the failures
    straddle the throttled flushes."""

    def _failed_files(self, scan_db, run_id):
        conn = sqlite3.connect(scan_db)
        try:
            return conn.execute(
                "SELECT failed_files FROM scan_runs WHERE id = ?", (run_id,),
            ).fetchone()[0]
        finally:
            conn.close()

    def _rows(self, scan_db, run_id):
        conn = sqlite3.connect(scan_db)
        try:
            return conn.execute(
                "SELECT path, stage, error FROM scan_failures "
                "WHERE scan_run_id = ? ORDER BY path", (run_id,),
            ).fetchall()
        finally:
            conn.close()

    def test_cross_flush_duplicate_counts_once(self, scan_db):
        run = ScanRun.start(scan_db, 'multi-pass', {}, 5)
        # The first record_failure flushes immediately; the second is held back
        # by the one-write-per-second throttle and lands in a LATER flush.
        run.record_failure('/p/x.jpg', 'load', 'first')
        run.record_failure('/p/x.jpg', 'load', 'second')
        run.finish('failed')
        assert len(self._rows(scan_db, run.run_id)) == 1
        assert self._failed_files(scan_db, run.run_id) == 1

    def test_same_flush_duplicates_count_once(self, scan_db):
        run = ScanRun.start(scan_db, 'multi-pass', {}, 5)
        run.record_failure('/p/a.jpg', 'load', 'a1')   # flushes immediately
        run.record_failure('/p/b.jpg', 'load', 'e1')   # both b failures pending
        run.record_failure('/p/b.jpg', 'score', 'e2')  # for the same flush
        run.finish('failed')
        assert self._failed_files(scan_db, run.run_id) == 2
        rows = self._rows(scan_db, run.run_id)
        assert [r[0] for r in rows] == ['/p/a.jpg', '/p/b.jpg']
        # The first stage wins; the new error text is appended.
        assert rows[1] == ('/p/b.jpg', 'load', 'e1 | e2')

    def test_failed_files_tracks_distinct_paths(self, scan_db):
        run = ScanRun.start(scan_db, 'multi-pass', {}, 5)
        for path in ('/p/a.jpg', '/p/b.jpg', '/p/a.jpg', '/p/c.jpg', '/p/b.jpg'):
            run.record_failure(path, 'load', 'boom')
        run.finish('failed')
        assert self._failed_files(scan_db, run.run_id) == 3
        assert len(self._rows(scan_db, run.run_id)) == 3

    def test_failed_files_is_scoped_to_its_own_run(self, scan_db):
        run1 = ScanRun.start(scan_db, 'multi-pass', {}, 2)
        run1.record_failure('/p/a.jpg', 'load', 'x')
        run1.record_failure('/p/b.jpg', 'load', 'x')
        run1.finish('failed')
        run2 = ScanRun.start(scan_db, 'multi-pass', {}, 2)
        run2.record_failure('/p/a.jpg', 'load', 'y')
        run2.finish('failed')
        assert self._failed_files(scan_db, run1.run_id) == 2
        assert self._failed_files(scan_db, run2.run_id) == 1

    def test_merged_error_is_bounded(self, scan_db):
        run = ScanRun.start(scan_db, 'multi-pass', {}, 5)
        messages = [chr(ord('a') + i) * 500 for i in range(10)]
        for message in messages:
            run.record_failure('/p/x.jpg', 'load', message)
        run.finish('failed')
        conn = sqlite3.connect(scan_db)
        (error,) = conn.execute(
            "SELECT error FROM scan_failures WHERE scan_run_id = ? AND path = ?",
            (run.run_id, '/p/x.jpg'),
        ).fetchone()
        conn.close()
        assert len(error) <= 2000
        assert error.startswith(messages[0])
        assert self._failed_files(scan_db, run.run_id) == 1

    def test_get_last_resumable_run(self, scan_db):
        ScanRun.start(scan_db, 'multi-pass', {}, 1).finish('completed')
        run2 = ScanRun.start(scan_db, 'multi-pass', {'directories': ['/d2']}, 2)
        run2.finish('interrupted')
        resumable = get_last_resumable_run(scan_db)
        assert resumable is not None
        assert resumable['id'] == run2.run_id

    def test_no_resumable_run_returns_none(self, scan_db):
        ScanRun.start(scan_db, 'multi-pass', {}, 1).finish('completed')
        assert get_last_resumable_run(scan_db) is None


class TestHardCrashResume:
    def _insert_run(self, scan_db, status='running', finished=False,
                    heartbeat_offset=None, started_offset=0):
        conn = sqlite3.connect(scan_db)
        cur = conn.execute(
            "INSERT INTO scan_runs (status, mode, args_json, total_files) "
            "VALUES (?, 'multi-pass', '{\"directories\": [\"/d\"]}', 5)",
            (status,),
        )
        rid = cur.lastrowid
        conn.execute(
            f"UPDATE scan_runs SET started_at = datetime('now', '{int(started_offset)} seconds') "
            "WHERE id = ?", (rid,))
        if finished:
            conn.execute("UPDATE scan_runs SET finished_at = datetime('now') WHERE id = ?", (rid,))
        if heartbeat_offset is not None:
            conn.execute(
                f"UPDATE scan_runs SET heartbeat_at = datetime('now', '{int(heartbeat_offset)} seconds') "
                "WHERE id = ?", (rid,))
        conn.commit()
        conn.close()
        return rid

    def test_stale_running_run_is_resumable(self, scan_db):
        rid = self._insert_run(scan_db, status='running', heartbeat_offset=-300)
        resumable = get_last_resumable_run(scan_db, stale_seconds=120)
        assert resumable is not None
        assert resumable['id'] == rid
        assert resumable['status'] == 'running'

    def test_fresh_running_run_not_resumable(self, scan_db):
        self._insert_run(scan_db, status='running', heartbeat_offset=-1)
        assert get_last_resumable_run(scan_db, stale_seconds=120) is None

    def test_fresh_running_run_is_in_progress(self, scan_db):
        self._insert_run(scan_db, status='running', heartbeat_offset=-1)
        assert scan_in_progress(scan_db, stale_seconds=120) is True

    def test_completed_run_not_in_progress(self, scan_db):
        ScanRun.start(scan_db, 'multi-pass', {}, 1).finish('completed')
        assert scan_in_progress(scan_db, stale_seconds=120) is False

    def test_crashed_before_first_heartbeat_uses_started_at(self, scan_db):
        rid = self._insert_run(scan_db, status='running', heartbeat_offset=None,
                               started_offset=-300)
        resumable = get_last_resumable_run(scan_db, stale_seconds=120)
        assert resumable is not None and resumable['id'] == rid

    def test_heartbeat_written_on_progress(self, scan_db):
        run = ScanRun.start(scan_db, 'multi-pass', {}, 5)
        run.update_progress(3)
        run.finish('interrupted')
        conn = sqlite3.connect(scan_db)
        heartbeat = conn.execute(
            "SELECT heartbeat_at FROM scan_runs WHERE id = ?", (run.run_id,)).fetchone()[0]
        conn.close()
        assert heartbeat is not None


class TestFailedPaths:
    def test_scopes(self, scan_db):
        run1 = ScanRun.start(scan_db, 'multi-pass', {}, 2)
        run1.record_failure('/p/a.jpg', 'load', 'x')
        run1.finish('failed')
        run2 = ScanRun.start(scan_db, 'multi-pass', {}, 2)
        run2.record_failure('/p/b.jpg', 'load', 'y')
        run2.finish('completed')

        assert get_failed_paths(scan_db, 'last') == ['/p/b.jpg']
        assert sorted(get_failed_paths(scan_db, 'all')) == ['/p/a.jpg', '/p/b.jpg']
        assert get_failed_paths(scan_db, run1.run_id) == ['/p/a.jpg']


class TestResumeFilters:
    def _seed_photos(self, scan_db, rows):
        conn = sqlite3.connect(scan_db)
        conn.executemany(
            "INSERT INTO photos (path, filename, config_version, scanned_at) "
            "VALUES (?, ?, ?, ?)",
            rows,
        )
        conn.commit()
        conn.close()

    def test_filter_scanned_since_drops_fresh_current_config(self, scan_db):
        self._seed_photos(scan_db, [
            ('/p/fresh.jpg', 'fresh.jpg', 'v2', '2026-06-10 12:00:00'),
            ('/p/old.jpg', 'old.jpg', 'v2', '2026-06-01 12:00:00'),
            ('/p/stale_cfg.jpg', 'stale_cfg.jpg', 'v1', '2026-06-10 12:00:00'),
        ])
        paths = ['/p/fresh.jpg', '/p/old.jpg', '/p/stale_cfg.jpg', '/p/new.jpg']
        keep = filter_paths_scanned_since(
            scan_db, paths, '2026-06-05 00:00:00', 'v2', chunk=2,
        )
        assert keep == {'/p/old.jpg', '/p/stale_cfg.jpg', '/p/new.jpg'}

    def test_filter_scanned_before_keeps_old_and_unscanned(self, scan_db):
        self._seed_photos(scan_db, [
            ('/p/recent.jpg', 'recent.jpg', 'v2', '2026-06-10 12:00:00'),
            ('/p/ancient.jpg', 'ancient.jpg', 'v2', '2025-01-01 12:00:00'),
            ('/p/never.jpg', 'never.jpg', 'v2', None),
        ])
        keep = filter_paths_scanned_before(
            scan_db, ['/p/recent.jpg', '/p/ancient.jpg', '/p/never.jpg'],
            '2026-01-01', chunk=2,
        )
        assert keep == {'/p/ancient.jpg', '/p/never.jpg'}


class TestProgressProtocol:
    def test_emit_and_parse_round_trip(self, capsys):
        emit_progress('scoring', 5, 100, current_file='/p/x.jpg',
                      eta_seconds=42.7, force=True)
        line = capsys.readouterr().out.strip()
        assert line.startswith(PROGRESS_PREFIX)
        event = parse_progress_line(line)
        assert event == {
            'phase': 'scoring', 'current': 5, 'total': 100,
            'current_file': '/p/x.jpg', 'eta_seconds': 43,
        }

    def test_parse_ignores_normal_lines(self):
        assert parse_progress_line('Processing 5/100 photos...') is None
        assert parse_progress_line(PROGRESS_PREFIX + '{not json') is None

    def test_throttle_suppresses_rapid_emits(self, capsys):
        emit_progress('scoring', 1, 10, force=True)
        emit_progress('scoring', 2, 10)  # within 1s window - suppressed
        out = capsys.readouterr().out.strip().splitlines()
        assert len(out) == 1

    def test_force_bypasses_throttle(self, capsys):
        emit_progress('scoring', 1, 10, force=True)
        emit_progress('bursts', force=True)
        out = capsys.readouterr().out.strip().splitlines()
        assert len(out) == 2

    def test_parse_handles_tqdm_prefixed_line(self):
        line = 'Multi-pass processing: 100%|####| 2/2 [00:04<00:00]' + PROGRESS_PREFIX + '{"phase": "bursts"}'
        assert parse_progress_line(line) == {'phase': 'bursts'}
