"""
Scan run bookkeeping: run records, per-file failures, and resume filtering.

The photos table itself is the checkpoint (batch commits land every chunk);
this module adds what was missing around it - failed files become visible
and retryable, interrupted runs are recorded, and --resume / --retry-failed /
--force-since get their data source.
"""

import json
import logging
import threading
import time

from db import get_connection

logger = logging.getLogger("facet.scan_state")


class ScanRun:
    """One row in scan_runs, updated as the scan progresses.

    Failure recording and progress updates are buffered and flushed together
    (throttled to about one write per second) so the bookkeeping never
    competes with photo batch commits for the write lock.
    """

    def __init__(self, db_path, run_id):
        self.db_path = db_path
        self.run_id = run_id
        self._lock = threading.Lock()
        self._pending_failures = []
        self._processed = 0
        self._failed = 0
        self._last_flush = 0.0

    @classmethod
    def start(cls, db_path, mode, args_dict, total_files):
        """Insert a new running scan_runs row and return its ScanRun."""
        with get_connection(db_path, row_factory=False) as conn:
            cursor = conn.execute(
                "INSERT INTO scan_runs (mode, args_json, total_files) VALUES (?, ?, ?)",
                (mode, json.dumps(args_dict), total_files),
            )
            conn.commit()
            run_id = cursor.lastrowid
        logger.info("Scan run #%d started (%s, %d files)", run_id, mode, total_files)
        return cls(db_path, run_id)

    def record_failure(self, path, stage, error):
        """Buffer a per-file failure; flushed with the next progress write."""
        with self._lock:
            self._pending_failures.append((self.run_id, str(path), stage, str(error)[:500]))
            self._failed += 1
        self._maybe_flush()

    def update_progress(self, processed):
        """Record processed-file count; throttled to one DB write per second."""
        with self._lock:
            self._processed = processed
        self._maybe_flush()

    def _maybe_flush(self, force=False):
        now = time.monotonic()
        with self._lock:
            if not force and now - self._last_flush < 1.0:
                return
            self._last_flush = now
            failures = self._pending_failures
            self._pending_failures = []
            processed, failed = self._processed, self._failed
        try:
            with get_connection(self.db_path, row_factory=False) as conn:
                if failures:
                    conn.executemany(
                        "INSERT OR REPLACE INTO scan_failures "
                        "(scan_run_id, path, stage, error) VALUES (?, ?, ?, ?)",
                        failures,
                    )
                conn.execute(
                    "UPDATE scan_runs SET processed_files = ?, failed_files = ?, "
                    "heartbeat_at = datetime('now') WHERE id = ?",
                    (processed, failed, self.run_id),
                )
                conn.commit()
        except Exception as e:
            logger.warning("Scan bookkeeping flush failed: %s", e)

    def finish(self, status='completed'):
        """Flush buffers and close the run with the given status."""
        self._maybe_flush(force=True)
        try:
            with get_connection(self.db_path, row_factory=False) as conn:
                conn.execute(
                    "UPDATE scan_runs SET status = ?, finished_at = datetime('now') WHERE id = ?",
                    (status, self.run_id),
                )
                conn.commit()
        except Exception as e:
            logger.warning("Could not close scan run #%d: %s", self.run_id, e)
        logger.info("Scan run #%d finished: %s", self.run_id, status)


def get_last_resumable_run(db_path, stale_seconds=120):
    """Return the most recent resumable run as a dict, or None.

    Resumable = an interrupted/failed run (clean exit recorded a status), OR a
    hard-crashed run still marked 'running' whose heartbeat has gone stale
    (SIGKILL/OOM/power-loss never reach finish()). COALESCE falls back to
    started_at for runs that died before their first heartbeat write.
    """
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT id, started_at, mode, args_json, total_files, processed_files, heartbeat_at, status "
            "FROM scan_runs WHERE status IN ('interrupted', 'failed') "
            "OR (status = 'running' AND finished_at IS NULL "
            "AND COALESCE(heartbeat_at, started_at) < datetime('now', ?)) "
            "ORDER BY id DESC LIMIT 1",
            (f'-{int(stale_seconds)} seconds',),
        ).fetchone()
        return dict(row) if row else None


def scan_in_progress(db_path, stale_seconds=120):
    """True if a scan_runs row looks live (running, fresh heartbeat).

    Used as a concurrency guard before adopting/reclaiming a run, so --resume
    never hijacks a genuinely concurrent scan.
    """
    with get_connection(db_path, row_factory=False) as conn:
        row = conn.execute(
            "SELECT id FROM scan_runs WHERE status = 'running' AND finished_at IS NULL "
            "AND COALESCE(heartbeat_at, started_at) > datetime('now', ?) "
            "ORDER BY id DESC LIMIT 1",
            (f'-{int(stale_seconds)} seconds',),
        ).fetchone()
        return row is not None


def get_failed_paths(db_path, scope='last'):
    """Paths recorded in scan_failures.

    Args:
        scope: 'last' (failures of the most recent run that had any),
               'all' (distinct failures across every run), or a run id
    """
    with get_connection(db_path, row_factory=False) as conn:
        if scope == 'all':
            rows = conn.execute("SELECT DISTINCT path FROM scan_failures").fetchall()
        elif scope == 'last':
            rows = conn.execute(
                "SELECT DISTINCT path FROM scan_failures WHERE scan_run_id = "
                "(SELECT MAX(scan_run_id) FROM scan_failures)"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT DISTINCT path FROM scan_failures WHERE scan_run_id = ?", (scope,)
            ).fetchall()
        return [r[0] for r in rows]


def filter_paths_scanned_before(db_path, paths, before_iso, chunk=450):
    """Return paths last scanned before the given date (or never scanned).

    Used by --force-since: everything scanned at/after the date is dropped
    from the worklist.
    """
    paths = [str(p) for p in paths]
    keep = set(paths)
    with get_connection(db_path, row_factory=False) as conn:
        for i in range(0, len(paths), chunk):
            batch = paths[i:i + chunk]
            placeholders = ','.join('?' * len(batch))
            rows = conn.execute(
                f"SELECT path FROM photos WHERE path IN ({placeholders}) "
                f"AND scanned_at >= ?",
                batch + [before_iso],
            ).fetchall()
            keep.difference_update(r[0] for r in rows)
    return keep


def filter_paths_scanned_since(db_path, paths, since_iso, config_version, chunk=450):
    """Return paths that should still be processed for a resumed --force run.

    Drops paths already scored with the current config at or after the given
    timestamp; everything else (older, different config, or never scanned)
    stays in the worklist.
    """
    paths = [str(p) for p in paths]
    keep = set(paths)
    with get_connection(db_path, row_factory=False) as conn:
        for i in range(0, len(paths), chunk):
            batch = paths[i:i + chunk]
            placeholders = ','.join('?' * len(batch))
            rows = conn.execute(
                f"SELECT path FROM photos WHERE path IN ({placeholders}) "
                f"AND config_version = ? AND scanned_at >= ?",
                batch + [config_version, since_iso],
            ).fetchall()
            keep.difference_update(r[0] for r in rows)
    return keep
