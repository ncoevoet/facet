"""Tests for scan run bookkeeping (processing/scan_state.py) and the
structured progress protocol (processing/progress.py)."""

import sqlite3

import pytest

from db.schema import init_database
from processing.progress import PROGRESS_PREFIX, emit_progress, parse_progress_line
from processing.scan_state import (
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

    def test_duplicate_failure_replaced_not_duplicated(self, scan_db):
        run = ScanRun.start(scan_db, 'multi-pass', {}, 5)
        run.record_failure('/p/x.jpg', 'load', 'first')
        run.record_failure('/p/x.jpg', 'load', 'second')
        run.finish('failed')
        conn = sqlite3.connect(scan_db)
        count = conn.execute(
            "SELECT COUNT(*) FROM scan_failures WHERE scan_run_id = ?", (run.run_id,),
        ).fetchone()[0]
        conn.close()
        assert count == 1

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
