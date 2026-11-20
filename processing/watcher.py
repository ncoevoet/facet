"""
Watch mode: monitor scan directories and re-run incremental scans on changes.

Each settled batch of filesystem events triggers a fresh `facet.py` scan
subprocess - that reuses the whole pipeline unchanged (incremental detection,
scan_runs bookkeeping, structured progress) and guarantees GPU/RAM are fully
released between scans. Requires the optional `watchdog` package.
"""

import logging
import os
import subprocess
import sys
import threading
import time

from utils.exit_codes import LIBRARY_LOCK_HELD_EXIT_CODE, SAVED_NOTHING_EXIT_CODE
from utils.image_loading import SCANNABLE_IMAGE_EXTENSIONS, WATCHABLE_IMAGE_EXTENSIONS

logger = logging.getLogger("facet.watcher")

# Derived from the shared extension table (see utils/image_loading.py) so watch
# mode and the scan collector cannot drift apart again — this list used to be a
# hard-coded copy that still omitted Canon .HIF.
WATCH_SUFFIXES = WATCHABLE_IMAGE_EXTENSIONS

MAX_CONSECUTIVE_FAILURES = 3
# A change-triggered watch scan that outlives this timeout is considered hung
# (a dead NFS handle, an uncovered decode deadlock): it is killed and counted as
# one failure, so the consecutive-failure give-up can fire instead of the
# watcher silently never returning from a scan. Killing the subprocess orphans
# its stay-open exiftool session (the parent held its watchdog timer), which
# sits idle on stdin until the process exits — bounded by the give-up at three
# strikes. The initial scan is exempt: a first watch over a large library, or an
# initial --force, legitimately runs for longer, and a killed initial scan is
# never retried — the rest of the library would wait for an unrelated file event.
WATCH_SCAN_TIMEOUT_SECONDS = 6 * 60 * 60
# _run_scan outcome for a scan skipped because another job holds the library lock.
_LIBRARY_BUSY = object()


class _PendingChanges:
    """Thread-safe accumulator of changed paths with a settle timestamp."""

    def __init__(self):
        self._lock = threading.Lock()
        self._paths = set()
        self._last_event = 0.0

    def add(self, path):
        if os.path.splitext(path)[1].lower() not in WATCH_SUFFIXES:
            return
        with self._lock:
            self._paths.add(path)
            self._last_event = time.monotonic()

    def take_if_settled(self, debounce_seconds):
        """Return and clear the pending set once no event arrived for the debounce window."""
        with self._lock:
            if not self._paths:
                return None
            if time.monotonic() - self._last_event < debounce_seconds:
                return None
            paths = self._paths
            self._paths = set()
            return paths


def _has_scannable_path(paths):
    """Return True if any path's extension is one the scan collector decodes.

    ``WATCH_SUFFIXES`` deliberately observes every HEIF container regardless of
    whether this install can decode one, so a library that gains pillow-heif
    later still sees files it already holds (see WATCHABLE_IMAGE_EXTENSIONS).
    But the rescan subprocess derives its own list from
    SCANNABLE_IMAGE_EXTENSIONS, which drops HEIF entirely without pillow-heif
    -- so a batch made up only of paths that scan provably cannot collect
    would spawn a scan for nothing, every debounce window, forever.
    """
    return any(os.path.splitext(path)[1].lower() in SCANNABLE_IMAGE_EXTENSIONS for path in paths)


def _build_scan_command(directories, db_path, config_path, extra_scan_args=None):
    facet_script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'facet.py')
    cmd = [sys.executable, facet_script, *directories, '--db', db_path]
    if config_path:
        cmd += ['--config', config_path]
    # The modifier flags the user started --watch with ride along: a watched
    # scan that quietly ignored them broke a promise nobody could see.
    if extra_scan_args:
        cmd += list(extra_scan_args)
    return cmd


def run_watch_loop(directories, db_path, config_path=None, debounce_seconds=30,
                   initial_scan=True, extra_scan_args=None, initial_scan_args=None):
    """Re-scan whenever directory contents settle, until Ctrl+C or a give-up.

    Returns True when the user stopped watching (Ctrl+C) and False when
    MAX_CONSECUTIVE_FAILURES consecutive scans failed, so the caller can exit
    non-zero on the give-up.

    Args:
        directories: Directories to watch (recursive)
        db_path: Database path passed through to scans
        config_path: Optional scoring config path passed through to scans
        debounce_seconds: Quiet period required before a scan fires
        initial_scan: Run one incremental scan immediately on startup
        extra_scan_args: Scan modifier flags (``--single-pass`` and friends)
            forwarded verbatim to every scan this loop spawns
        initial_scan_args: Flags added to the initial scan only, after
            ``extra_scan_args`` -- ``--force``, which would otherwise re-score
            the whole library on every change
    """
    try:
        from watchdog.observers import Observer
        from watchdog.observers.polling import PollingObserver
        from watchdog.events import FileSystemEventHandler
    except ImportError:
        logger.error("Watch mode requires the optional 'watchdog' package: pip install watchdog")
        raise SystemExit(1)

    pending = _PendingChanges()

    class _Handler(FileSystemEventHandler):
        def on_created(self, event):
            if not event.is_directory:
                pending.add(event.src_path)

        def on_moved(self, event):
            if not event.is_directory:
                pending.add(event.dest_path)

        def on_modified(self, event):
            if not event.is_directory:
                pending.add(event.src_path)

    def _start_observer(observer_cls):
        observer = observer_cls()
        for directory in directories:
            observer.schedule(_Handler(), directory, recursive=True)
        observer.start()
        return observer

    try:
        observer = _start_observer(Observer)
        logger.info("Watching %d directories (inotify)", len(directories))
    except OSError as e:
        # inotify limits or network mounts (NAS) - fall back to polling
        logger.warning("Native observer failed (%s), falling back to polling", e)
        observer = _start_observer(PollingObserver)
        logger.info("Watching %d directories (polling)", len(directories))

    cmd = _build_scan_command(directories, db_path, config_path, extra_scan_args)
    initial_cmd = cmd + list(initial_scan_args or ())

    def _run_scan(reason, scan_cmd=cmd, timeout=WATCH_SCAN_TIMEOUT_SECONDS):
        logger.info("Starting scan (%s)...", reason)
        try:
            result = subprocess.run(scan_cmd, timeout=timeout)
        except subprocess.TimeoutExpired:
            logger.warning("Scan hung past the %d s watch timeout and was killed; "
                           "counting it as a failure.", WATCH_SCAN_TIMEOUT_SECONDS)
            return False
        if result.returncode == 0:
            logger.info("Scan finished.")
            return True
        if result.returncode == SAVED_NOTHING_EXIT_CODE:
            # Neither a success nor a crash: the failure counter is left exactly as it was, so a
            # 4 between real crashes neither hides the streak nor adds to it.
            logger.warning("Scan saved 0 photos (exit code %d); see the scan log for the cause. "
                           "Watching continues.", result.returncode)
            return None
        if result.returncode == LIBRARY_LOCK_HELD_EXIT_CODE:
            # Another job holds the library lock: transient by definition, so a busy
            # stretch must not accumulate toward giving up. The caller re-queues the
            # batch, which is otherwise already drained and would never be scanned.
            logger.warning("Scan skipped: the library lock is held by another job (exit code %d). "
                           "Retrying after the next quiet period.", result.returncode)
            return _LIBRARY_BUSY
        logger.warning("Scan exited with code %d", result.returncode)
        return False

    consecutive_failures = 0
    gave_up = False
    initial_retry_at: float | None = None
    try:
        if initial_scan:
            # A failing initial scan counts as the streak's first failure, so a
            # broken install cannot watch forever while every scan crashes.
            outcome = _run_scan('initial', initial_cmd, timeout=None)
            if outcome is _LIBRARY_BUSY:
                initial_retry_at = time.monotonic() + debounce_seconds
            elif outcome is False:
                consecutive_failures = 1
        logger.info("Watch mode active - new files trigger a scan after %ds of quiet "
                    "(Ctrl+C to stop)", debounce_seconds)
        while True:
            time.sleep(1)
            if initial_retry_at is not None:
                if time.monotonic() < initial_retry_at:
                    continue
                outcome = _run_scan('initial retry', initial_cmd, timeout=None)
                if outcome is _LIBRARY_BUSY:
                    initial_retry_at = time.monotonic() + debounce_seconds
                    continue
                initial_retry_at = None
                # Do not drain events queued during the initial scan: those
                # still need an incremental scan after the initial attempt.
            else:
                batch = pending.take_if_settled(debounce_seconds)
                if not batch:
                    continue
                if not _has_scannable_path(batch):
                    logger.info(
                        "Skipping scan: %d changed file(s) have no extension this "
                        "install can decode (likely HEIF without pillow-heif)",
                        len(batch),
                    )
                    continue
                outcome = _run_scan(f'{len(batch)} changed files')
                if outcome is _LIBRARY_BUSY:
                    for path in batch:
                        pending.add(path)
                    continue
            if outcome is None:
                continue
            if outcome:
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    logger.error(
                        "Stopping watch mode: %d consecutive scans failed. Fix the "
                        "underlying error and restart.", consecutive_failures)
                    gave_up = True
                    break
    except KeyboardInterrupt:
        logger.info("Watch mode stopped.")
    finally:
        observer.stop()
        observer.join(timeout=5)
    return not gave_up
