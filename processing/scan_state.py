"""
Scan run bookkeeping: run records, per-file failures, and resume filtering.

The photos table itself is the checkpoint (batch commits land every chunk);
this module adds what was missing around it - failed files become visible
and retryable, interrupted runs are recorded, and --resume / --retry-failed /
--force-since get their data source.
"""

import json
import logging
import os
import re
import threading
import time

from db import get_connection

logger = logging.getLogger("facet.scan_state")
VIEWER_JOB_ID_ENV = 'FACET_SCAN_JOB_ID'
JOB_PHASES = frozenset({'scoring', 'bursts', 'sequences', 'tagging', 'moments', 'junk', 'vec', 'done'})
# Failures kept for retry while the bookkeeping database stays unwritable;
# beyond this the newest are dropped and the run is reported as failed.
MAX_PENDING_FAILURES = 10_000


def viewer_job_id():
    """An internal correlation ID, never permission to signal a process."""
    value = os.environ.get(VIEWER_JOB_ID_ENV)
    if value is not None and not re.fullmatch('[0-9a-f]{32}', value):
        raise ValueError('Invalid viewer scan job identity')
    return value


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
        self._dropped_failures = 0
        self._processed = 0
        self._last_flush = 0.0

    @classmethod
    def start(cls, db_path, mode, args_dict, total_files, job_id=None):
        """Insert a new running scan_runs row and return its ScanRun."""
        with get_connection(db_path, row_factory=False) as conn:
            cursor = conn.execute(
                "INSERT INTO scan_runs (mode, args_json, total_files, heartbeat_at, "
                "viewer_job_id, job_status, job_phase) "
                "VALUES (?, ?, ?, datetime('now'), ?, 'running', 'scoring')",
                (mode, json.dumps(args_dict), total_files, job_id),
            )
            conn.commit()
            run_id = cursor.lastrowid
        logger.info("Scan run #%d started (%s, %d files)", run_id, mode, total_files)
        return cls(db_path, run_id)

    def record_failure(self, path, stage, error):
        """Buffer a per-file failure; flushed with the next progress write."""
        with self._lock:
            self._pending_failures.append((self.run_id, str(path), stage, str(error)[:500]))
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
            processed = self._processed
        committed = False
        try:
            with get_connection(self.db_path, row_factory=False) as conn:
                if failures:
                    # A path can fail more than once in a run (a retry, or
                    # several passes). The row is keyed (scan_run_id, path):
                    # keep the first stage and timestamp, append the new error.
                    conn.executemany(
                        "INSERT INTO scan_failures (scan_run_id, path, stage, error) "
                        "VALUES (?, ?, ?, ?) "
                        "ON CONFLICT(scan_run_id, path) DO UPDATE SET "
                        "error = substr(COALESCE(scan_failures.error || ' | ', '') "
                        "|| excluded.error, 1, 2000)",
                        failures,
                    )
                # Count the table, not the calls: the same connection sees the
                # uncommitted upsert above, and the PRIMARY KEY makes the count
                # one per distinct path whatever the flush timing.
                conn.execute(
                    "UPDATE scan_runs SET processed_files = ?, "
                    "failed_files = (SELECT COUNT(*) FROM scan_failures "
                    "WHERE scan_run_id = ?), "
                    "heartbeat_at = datetime('now') WHERE id = ?",
                    (processed, self.run_id, self.run_id),
                )
                conn.commit()
                committed = True
        except Exception as e:
            if not committed:
                # Re-queue the drained failures ahead of newer ones so a later
                # flush retries them; a lost heartbeat is simply overwritten by
                # the next. Once committed they are stored, and a retry would
                # append their error text a second time.
                with self._lock:
                    self._pending_failures[:0] = failures
                    overflow = len(self._pending_failures) - MAX_PENDING_FAILURES
                    if overflow > 0:
                        del self._pending_failures[MAX_PENDING_FAILURES:]
                        self._dropped_failures += overflow
            logger.warning("Scan bookkeeping flush failed: %s", e)

    def finish(self, status='completed'):
        """Close the run, returning whether all bookkeeping was persisted."""
        self._maybe_flush(force=True)
        # Failure records still pending after the final flush are lost, and a
        # captured retry must not then erase its source receipts.
        with self._lock:
            persisted = not self._pending_failures and not self._dropped_failures
        if status == 'completed' and not persisted:
            status = 'failed'
        try:
            with get_connection(self.db_path, row_factory=False) as conn:
                conn.execute(
                    "UPDATE scan_runs SET status = ?, finished_at = datetime('now') WHERE id = ?",
                    (status, self.run_id),
                )
                conn.commit()
        except Exception as e:
            logger.warning("Could not close scan run #%d: %s", self.run_id, e)
            return False
        logger.info("Scan run #%d finished: %s", self.run_id, status)
        return persisted

    def job_phase(self, phase):
        """Persist one phase transition; the lifecycle suppresses repeats."""
        if phase not in JOB_PHASES:
            raise ValueError('Unknown scan job phase')
        try:
            with get_connection(self.db_path, row_factory=False) as conn:
                cursor = conn.execute('UPDATE scan_runs SET job_phase=? WHERE id=?', (phase, self.run_id))
                if cursor.rowcount != 1:
                    raise RuntimeError('Scan run record disappeared')
                conn.commit()
            return True
        except Exception as exc:
            logger.warning('Could not persist scan job phase: %s', exc)
            return False

    def finish_job(self, status):
        """Terminal pipeline outcome, separate from scoring's finish timestamp."""
        if status not in ('completed', 'interrupted', 'failed'):
            raise ValueError('Unknown scan job outcome')
        try:
            with get_connection(self.db_path, row_factory=False) as conn:
                cursor = conn.execute(
                    "UPDATE scan_runs SET job_status=?, job_finished_at=datetime('now') WHERE id=?",
                    (status, self.run_id),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError('Scan run record disappeared')
                conn.commit()
            return True
        except Exception as exc:
            logger.warning('Could not persist scan job outcome: %s', exc)
            return False


class ScanJobLifecycle:
    """Explicit enclosing scan lifetime; no global/thread-local active run."""

    def __init__(self):
        self.run = None
        self.phase = 'scoring'
        self.phase_recorded = True

    def attach(self, run):
        self.run = run

    def progress(self, phase):
        if phase != self.phase and self.run is not None:
            self.phase = phase
            self.phase_recorded = self.run.job_phase(phase)

    def finish(self, status):
        if self.run is None:
            return True  # No scoring run was created; do not invent a receipt.
        # A missed transition is superseded by the next one; retry the phase the
        # job ends on, but only the terminal outcome write decides the result.
        if not self.phase_recorded:
            self.phase_recorded = self.run.job_phase(self.phase)
        return self.run.finish_job(status)


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
