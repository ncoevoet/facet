"""Viewer start-up and shutdown: the library-locked schema step and the final checkpoint.

Viewer-API speed spec, Step 11 (``api.schema_startup``: the synchronous migration, the
background index build under the library lock, and the lifespan that starts and stops it) and Step 12 (the shutdown checkpoint no longer depends on
``performance.wal_checkpoint_minutes``, and the change-token sentinels close first).

Every test builds its own DB with ``init_database`` (``.claude/patterns/test-fixtures.md``)
and patches ``api.database.DEFAULT_DB_PATH``, the global the lifespan and the request
connections read, plus ``api.config._FULL_CONFIG`` so no test depends on the operator's
``scoring_config.json``. No auth dependency is patched: the lifespan needs none.
"""

import gc
import logging
import os
import sqlite3
import subprocess
import sys
import textwrap
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import pytest
from fastapi.testclient import TestClient

import api.config as api_config
from api import create_app
from api.change_token import db_change_token
from api.schema_startup import PhotoIndexBuild, migrate_schema_at_startup
from db.schema import init_database
from facet import LIBRARY_JOB_MAINTENANCE, LibraryLock

# The nine photos indexes the viewer build step is responsible for (eight gallery
# covering indexes plus the post-scan idx_post_scan), written out on
# purpose (the registry test lives in tests/test_gallery_indexes.py).
GALLERY_INDEXES = (
    'idx_gallery_aggregate', 'idx_gallery_date_desc', 'idx_date_asc_cover',
    'idx_gallery_category', 'idx_gallery_camera', 'idx_star_rating_path',
    'idx_gallery_iaa_asc', 'idx_stats_categories', 'idx_post_scan',
)


def _make_db(tmp_path, rows=300, name="life.db", drop_gallery_indexes=False):
    path = str(tmp_path / name)
    init_database(path)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executemany(
        "INSERT INTO photos (path, filename, aggregate) VALUES (?, ?, ?)",
        [(f"/{name}/p{i}.jpg", f"p{i}.jpg", float(i % 10)) for i in range(rows)])
    if drop_gallery_indexes:
        for idx in GALLERY_INDEXES:
            conn.execute(f"DROP INDEX IF EXISTS {idx}")
    conn.commit()
    conn.close()
    return path


def _present_indexes(path):
    conn = sqlite3.connect(path)
    try:
        return {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'")}
    finally:
        conn.close()


def _config(wal_minutes):
    return {
        "performance": {"wal_checkpoint_minutes": wal_minutes},
        "viewer": {"features": {"show_capsules": False}},
    }


@contextmanager
def _patched_server(db_path, wal_minutes=0):
    """Point the server globals at a tmp DB and a config the test owns."""
    with mock.patch("api.database.DEFAULT_DB_PATH", db_path), \
            mock.patch.object(api_config, "_FULL_CONFIG", _config(wal_minutes)):
        yield


def init_schema_at_startup(db):
    """What the lifespan does at start, run synchronously: migrate, then the build body."""
    migrate_schema_at_startup(db)
    return PhotoIndexBuild(db).run()


def _ready_change_token(db_path, seconds=5.0):
    """A busy first read has not attached the sentinel to the WAL yet."""
    deadline = time.monotonic() + seconds
    while True:
        token = db_change_token(db_path)
        if not token.startswith("x"):
            return token
        assert time.monotonic() < deadline, "change-token sentinel stayed busy"
        time.sleep(0.01)


def _wait_for_wal_gone(db_path, seconds=5.0):
    wal = db_path + "-wal"
    deadline = time.monotonic() + seconds
    while os.path.exists(wal) and time.monotonic() < deadline:
        time.sleep(0.05)
    return not os.path.exists(wal)


def _row_count_in_db_file_alone(db_path, path):
    """Rows visible when only the main ``.db`` file is read (no WAL, no locks)."""
    uri = Path(db_path).resolve().as_uri() + "?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM photos WHERE path = ?", (path,)).fetchone()[0]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Step 11: init_schema_at_startup
# ---------------------------------------------------------------------------

def test_lock_held_defers_then_builds_after_release(tmp_path, caplog):
    """Verify 4: a held library lock defers the index build; releasing it allows it."""
    db = _make_db(tmp_path, drop_gallery_indexes=True)
    holder = LibraryLock(db, kind=LIBRARY_JOB_MAINTENANCE).acquire()
    # An earlier test can leave the "facet" logger at INFO, so _make_db's own
    # "Creating index" records may already be captured; only this call's count.
    caplog.clear()
    try:
        with caplog.at_level(logging.INFO):
            result = init_schema_at_startup(db)
        assert result == 'deferred'
        assert not set(GALLERY_INDEXES) & _present_indexes(db)
        warnings = [r.getMessage() for r in caplog.records
                    if r.levelno == logging.WARNING and "Library lock" in r.getMessage()]
        assert len(warnings) == 1
        # The warning names the holder: its kind and pid come from the lock payload.
        assert f"pid {os.getpid()}" in warnings[0]
        assert "maintenance is already running" in warnings[0]
        assert not [r for r in caplog.records if "Creating index" in r.getMessage()]
    finally:
        holder.release()

    assert init_schema_at_startup(db) == 'built'
    assert set(GALLERY_INDEXES) <= _present_indexes(db)


def test_lock_held_by_another_process_defers(tmp_path):
    """The real case: a different process (a scan) holds the lock."""
    db = _make_db(tmp_path, drop_gallery_indexes=True)
    script = tmp_path / "hold_lock.py"
    script.write_text(textwrap.dedent("""
        import sys, time
        sys.path.insert(0, sys.argv[1])
        from facet import LibraryLock, LIBRARY_JOB_SCAN
        lock = LibraryLock(sys.argv[2], kind=LIBRARY_JOB_SCAN).acquire()
        print("held", flush=True)
        sys.stdin.readline()
        lock.release()
    """))
    root = str(Path(__file__).resolve().parent.parent)
    child = subprocess.Popen(
        [sys.executable, "-I", str(script), root, db],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "held"
        assert init_schema_at_startup(db) == 'deferred'
        assert not set(GALLERY_INDEXES) & _present_indexes(db)
    finally:
        child.stdin.write("\n")
        child.stdin.flush()
        child.wait(timeout=30)
    assert init_schema_at_startup(db) == 'built'
    assert set(GALLERY_INDEXES) <= _present_indexes(db)


def test_deferred_still_migrates_tables_and_columns(tmp_path):
    """A deferred start is not a no-op: the schema the endpoints read is still current."""
    db = _make_db(tmp_path, drop_gallery_indexes=True)
    conn = sqlite3.connect(db)
    conn.execute("DROP TABLE iqa_declined")
    conn.commit()
    conn.close()
    holder = LibraryLock(db, kind=LIBRARY_JOB_MAINTENANCE).acquire()
    try:
        assert init_schema_at_startup(db) == 'deferred'
    finally:
        holder.release()
    conn = sqlite3.connect(db)
    try:
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'iqa_declined'").fetchone()
    finally:
        conn.close()


def test_migration_failure_is_logged_and_returns_false(tmp_path, caplog):
    db = _make_db(tmp_path)
    with mock.patch("db.schema.init_database", side_effect=RuntimeError("boom")), \
            caplog.at_level(logging.WARNING):
        assert migrate_schema_at_startup(db) is False
    assert "Schema migration on startup failed" in caplog.text


def test_build_failure_returns_failed_and_releases_lock(tmp_path, caplog):
    db = _make_db(tmp_path, drop_gallery_indexes=True)
    with mock.patch("db.schema.create_photo_indexes", side_effect=RuntimeError("boom")), \
            caplog.at_level(logging.WARNING):
        assert PhotoIndexBuild(db).run() == 'failed'
    assert "Gallery index build failed" in caplog.text
    # The lock was released in the finally: it can be taken again straight away.
    LibraryLock(db, kind=LIBRARY_JOB_MAINTENANCE).acquire().release()


def test_concurrent_starts(tmp_path, caplog):
    """Verify 5: two simultaneous starts on an upgraded DB; nobody raises, someone builds.

    Review M1: the start that loses the lock must not fail its migration on the SQLite
    write lock the builder holds, and must not log a warning about the other worker.
    """
    db = _make_db(tmp_path, rows=3000, drop_gallery_indexes=True)
    barrier = threading.Barrier(2)
    results, errors = [], []

    def start():
        try:
            barrier.wait(timeout=10)
            results.append(init_schema_at_startup(db))
        except BaseException as ex:  # noqa: BLE001 - the test reports whatever escapes
            errors.append(ex)

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="api.schema_startup"):
        threads = [threading.Thread(target=start) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=120)
    assert not any(t.is_alive() for t in threads)
    assert errors == []
    assert len(results) == 2
    assert set(results) <= {'built', 'deferred', 'current'}
    assert 'built' in results
    assert not [r for r in caplog.records
                if r.name == "api.schema_startup" and r.levelno >= logging.WARNING]
    assert set(GALLERY_INDEXES) <= _present_indexes(db)
    # Nothing is left for a later start.
    assert init_schema_at_startup(db) == 'current'


def test_migration_on_a_current_schema_needs_no_write_lock(tmp_path):
    """Review M1 root cause: the migration's unconditional `UPDATE persons` took the write
    lock, so a worker starting while another held it for a CREATE INDEX waited out
    busy_timeout (5 s) and failed. On a current schema the migration now writes nothing.
    """
    db = _make_db(tmp_path)
    holder = sqlite3.connect(db, isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")  # what a CREATE INDEX holds for its duration
    try:
        started = time.monotonic()
        assert migrate_schema_at_startup(db) is True
        elapsed = time.monotonic() - started
    finally:
        holder.execute("ROLLBACK")
        holder.close()
    assert elapsed < 4.0, f"the migration waited {elapsed:.1f}s on the write lock"


def test_held_lock_with_nothing_missing_is_silent_and_never_takes_the_lock(tmp_path, caplog):
    """The deferred warning is logged only when indexes are actually missing."""
    db = _make_db(tmp_path)
    with sqlite3.connect(db) as conn:
        conn.execute("ANALYZE photos")
    holder = LibraryLock(db, kind=LIBRARY_JOB_MAINTENANCE).acquire()
    caplog.clear()
    try:
        with caplog.at_level(logging.INFO, logger="api.schema_startup"):
            assert init_schema_at_startup(db) == 'current'
    finally:
        holder.release()
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_the_viewer_lock_records_its_origin(tmp_path):
    """Review M2: a scan refused during the build names the viewer, not 'cli'."""
    from facet import library_job_holder
    db = _make_db(tmp_path, drop_gallery_indexes=True)
    seen = {}
    real_build = PhotoIndexBuild._build

    def spy(self):
        seen.update(library_job_holder(db) or {})
        return real_build(self)

    with mock.patch.object(PhotoIndexBuild, "_build", spy):
        assert PhotoIndexBuild(db).run() == 'built'
    assert seen.get('origin') == 'viewer'
    assert seen.get('kind') == LIBRARY_JOB_MAINTENANCE


def test_unusable_lock_path_gets_viewer_advice(tmp_path, caplog):
    """Review M2: no `--force-library-lock` (a facet.py flag) and no "next start" promise."""
    db = _make_db(tmp_path, drop_gallery_indexes=True)
    with mock.patch("facet.LibraryLock._open_and_hold",
                    side_effect=PermissionError(13, "Permission denied")), \
            caplog.at_level(logging.INFO, logger="api.schema_startup"):
        assert init_schema_at_startup(db) == 'deferred'
    text = caplog.text
    assert "Cannot use the library lock file" in text
    assert "--force-library-lock" not in text
    assert "next start" not in text
    assert not set(GALLERY_INDEXES) & _present_indexes(db)


# ---------------------------------------------------------------------------
# Step 11: the lifespan starts the build in the background
# ---------------------------------------------------------------------------

def _wait_for_build(app, seconds=60.0):
    build = app.state.index_build
    deadline = time.monotonic() + seconds
    while build.is_running() and time.monotonic() < deadline:
        time.sleep(0.05)
    return build


def test_lifespan_migrates_once_and_builds_in_the_background(tmp_path):
    """Verify 6: the app still starts, the migration runs once, the build completes."""
    db = _make_db(tmp_path, drop_gallery_indexes=True)
    with _patched_server(db), \
            mock.patch("api.schema_startup.migrate_schema_at_startup",
                       wraps=migrate_schema_at_startup) as spy:
        app = create_app()
        with TestClient(app):
            build = _wait_for_build(app)
            assert build.result == 'built'
    spy.assert_called_once_with(db)
    assert set(GALLERY_INDEXES) <= _present_indexes(db)


def _slow_build_patches(monkeypatch, delay=0.01):
    """Make the last index of the build slow: a deterministic SQL function that sleeps per row.

    The function is registered on the build's own connection only, and its index is
    appended to the registry: the gallery indexes before it finish, and an interrupted
    build must keep them and leave the slow one absent.
    """
    import db.schema as schema
    real_open = PhotoIndexBuild._open

    def slow_key(value):
        time.sleep(delay)
        return value

    def open_with_slow_key(self):
        conn = real_open(self)
        conn.create_function("zz_slow_key", 1, slow_key, deterministic=True)
        return conn

    monkeypatch.setattr(PhotoIndexBuild, "_open", open_with_slow_key)
    monkeypatch.setattr(schema, "INDEXES",
                        list(schema.INDEXES) + [('idx_zz_slow', 'photos', 'zz_slow_key(path)')])


def test_requests_are_answered_while_the_build_runs_and_shutdown_interrupts_it(
        tmp_path, monkeypatch, caplog):
    """B1: the port answers during the build; shutdown interrupts and joins, keeping every
    index already finished; the next start finishes the build."""
    db = _make_db(tmp_path, rows=3000, drop_gallery_indexes=True)
    # 3000 rows x 10 ms: about 30 s if never interrupted.
    _slow_build_patches(monkeypatch)
    caplog.clear()
    _serve_during_slow_build(db, caplog)
    present = _present_indexes(db)
    assert 'idx_zz_slow' not in present, "the interrupted index must roll back"
    assert set(GALLERY_INDEXES) <= present, "the finished indexes must be kept"
    n = len(GALLERY_INDEXES)
    assert f"stopped by shutdown after {n} of {n + 1} index(es)" in caplog.text

    # The next start resumes: it analyzes what the interrupted one could not.
    monkeypatch.undo()
    assert PhotoIndexBuild(db).run() == 'built'
    with sqlite3.connect(db) as conn:
        assert conn.execute(
            "SELECT 1 FROM sqlite_stat1 WHERE idx = 'idx_gallery_aggregate'").fetchone()


def _serve_during_slow_build(db, caplog):
    from api.auth import CurrentUser, get_optional_user

    with _patched_server(db), caplog.at_level(logging.INFO, logger="api.schema_startup"):
        app = create_app()
        app.dependency_overrides[get_optional_user] = lambda: CurrentUser(
            user_id="t", role="admin", edition_authenticated=True)
        with TestClient(app) as client:
            build = app.state.index_build
            deadline = time.monotonic() + 30
            while (not set(GALLERY_INDEXES) <= _present_indexes(db)
                   and time.monotonic() < deadline):
                time.sleep(0.05)
            time.sleep(0.2)  # inside the slow CREATE INDEX, the last one
            assert build.is_running()
            started = time.monotonic()
            assert client.get("/health").status_code == 200
            photos = client.get("/api/photos?per_page=5")
            assert photos.status_code == 200, photos.text
            assert photos.json()["total"] == 3000
            assert time.monotonic() - started < 5.0
            assert build.is_running(), "the build ended before the requests were checked"
            shutdown_started = time.monotonic()
        shutdown_seconds = time.monotonic() - shutdown_started
        app.dependency_overrides.clear()
    assert not build.is_running()
    assert build.result == 'interrupted'
    assert shutdown_seconds < 15.0, shutdown_seconds
    assert "stopped by shutdown" in caplog.text


def test_stop_before_the_thread_reaches_the_build_stops_it(tmp_path):
    db = _make_db(tmp_path, drop_gallery_indexes=True)
    build = PhotoIndexBuild(db)
    build._stop.set()
    assert build.run() == 'interrupted'
    assert not set(GALLERY_INDEXES) & _present_indexes(db)


def test_an_interrupt_landing_on_the_read_only_probe_is_a_shutdown(tmp_path, caplog):
    """M4: stop() re-interrupts every 0.1 s, so the interrupt can land on any statement
    of the thread, the pending-work probe that runs before the build included. That is
    a shutdown, never a failure with a traceback."""
    db = _make_db(tmp_path, drop_gallery_indexes=True)
    build = PhotoIndexBuild(db)
    build._stop.set()
    interrupted = sqlite3.OperationalError("interrupted")
    with mock.patch("db.schema.missing_photo_indexes", side_effect=interrupted), \
            caplog.at_level(logging.INFO, logger="api.schema_startup"):
        assert build.run() == 'interrupted'
    assert "stopped by shutdown" in caplog.text
    assert "Gallery index build failed" not in caplog.text


# ---------------------------------------------------------------------------
# The build status that /health and the write-retry decorator read
# ---------------------------------------------------------------------------

def test_a_real_build_reports_building_then_progress_then_ready(tmp_path, monkeypatch):
    """start() reports ``building`` before the thread runs; each index built by
    create_photo_indexes advances ``done`` through on_built; the end is ``ready``."""
    from api import schema_startup
    db = _make_db(tmp_path, drop_gallery_indexes=True)
    real_set_status = schema_startup._set_status
    updates = []

    def recording_set_status(**fields):
        updates.append(dict(fields))
        real_set_status(**fields)

    monkeypatch.setattr(schema_startup, "_set_status", recording_set_status)
    build = PhotoIndexBuild(db).start()
    build._thread.join(60)
    assert not build.is_running()

    n = len(GALLERY_INDEXES)
    assert updates[0] == {"state": schema_startup.STATE_BUILDING, "done": 0, "total": 0}
    progress = [(u["done"], u["total"]) for u in updates[1:-1]]
    assert progress == [(k, n) for k in range(n + 1)]
    assert updates[-1] == {"state": schema_startup.STATE_READY, "done": n, "total": n}
    assert schema_startup.index_build_status() == {
        "state": schema_startup.STATE_READY, "done": n, "total": n}


@pytest.mark.parametrize("result, state", [
    ("built", "ready"), ("current", "ready"), ("deferred", "deferred"),
    ("interrupted", "stopped"), ("failed", "failed"),
])
def test_each_run_result_ends_in_its_state(tmp_path, monkeypatch, result, state):
    from api import schema_startup
    seen_while_running = []

    def run(self):
        seen_while_running.append(schema_startup.index_build_status()["state"])
        self._progress(2, 3)
        return result

    monkeypatch.setattr(PhotoIndexBuild, "run", run)
    build = PhotoIndexBuild(str(tmp_path / "unused.db")).start()
    build._thread.join(10)
    assert seen_while_running == [schema_startup.STATE_BUILDING]
    assert schema_startup.index_build_status() == {"state": state, "done": 2, "total": 3}


def test_a_run_that_raises_never_leaves_building(tmp_path, monkeypatch):
    """run() catches Exception itself, but anything escaping it (a BaseException, a
    bug) must not leave ``building`` behind: writes would never retry again and
    /health would report a build that is over. Driven on this thread, so the raise
    reaches the test instead of the thread excepthook."""
    from api import schema_startup

    def run(self):
        self._progress(1, 4)
        raise RuntimeError("escaped run()")

    monkeypatch.setattr(PhotoIndexBuild, "run", run)
    build = PhotoIndexBuild(str(tmp_path / "unused.db"))
    schema_startup._set_status(state=schema_startup.STATE_BUILDING, done=0, total=0)
    with pytest.raises(RuntimeError, match="escaped run"):
        build._thread_main()
    assert schema_startup.index_build_status() == {
        "state": schema_startup.STATE_FAILED, "done": 1, "total": 4}


# ---------------------------------------------------------------------------
# Step 12: the shutdown checkpoint
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("wal_minutes", [0, 30])
def test_shutdown_checkpoint_leaves_db_file_complete(tmp_path, wal_minutes):
    """Verify 1 (wal_checkpoint_minutes = 0) and 2 (= 30, the regression guard).

    The change-token sentinel is a read-only connection; if it were the last closer
    the ``-wal`` would stay behind holding commits the ``.db`` alone lacks.
    """
    db = _make_db(tmp_path)
    marker = "/life.db/committed-while-running.jpg"
    with _patched_server(db, wal_minutes):
        with TestClient(create_app()) as client:
            # The build's first ANALYZE creates sqlite_stat1, a schema change: an INSERT
            # whose prepare spans it (FTS5 connects photos_fts inside the prepare) fails
            # "no such table: photos". Let it finish before anything writes.
            client.app.state.index_build.wait()
            # Collect unrelated connection cycles before establishing the sentinel.
            # Startup writers may briefly make its first read busy: a miss token
            # does not mean the read-only connection has joined the WAL yet.
            gc.collect()
            _ready_change_token(db)
            other = sqlite3.connect(db)
            other.execute("INSERT INTO photos (path, filename) VALUES (?, ?)",
                          (marker, "committed-while-running.jpg"))
            other.commit()
            other.close()
            # While the app runs, the commit lives in the WAL.
            assert os.path.exists(db + "-wal")
    assert _wait_for_wal_gone(db), "the -wal outlived shutdown"
    assert _row_count_in_db_file_alone(db, marker) == 1


def test_wal_setup_retries_a_real_busy_first_sentinel_read(tmp_path):
    db = _make_db(tmp_path)
    blocker = sqlite3.connect(db)
    blocker.execute("PRAGMA locking_mode=EXCLUSIVE")
    blocker.execute("BEGIN EXCLUSIVE")
    blocker.execute("INSERT INTO photos (path, filename) VALUES (?, ?)",
                    ("/busy.jpg", "busy.jpg"))
    real_token = db_change_token
    observed = []

    def release_after_busy_read(path):
        token = real_token(path)
        observed.append(token)
        if token.startswith("x"):
            blocker.commit()
            blocker.close()
        return token

    try:
        with mock.patch(__name__ + ".db_change_token", side_effect=release_after_busy_read):
            token = _ready_change_token(db)
        assert observed[0].startswith("x")
        assert not token.startswith("x")
        other = sqlite3.connect(db)
        try:
            other.execute("INSERT INTO photos (path, filename) VALUES (?, ?)",
                          ("/after-busy.jpg", "after-busy.jpg"))
            other.commit()
        finally:
            other.close()
        assert os.path.exists(db + "-wal")
    finally:
        blocker.close()


def test_shutdown_closes_sentinels_before_the_final_checkpoint(tmp_path):
    """Verify 3: ordering."""
    db = _make_db(tmp_path)
    calls = []
    with _patched_server(db, wal_minutes=0), \
            mock.patch("api.change_token.close_change_token_sentinels",
                       side_effect=lambda: calls.append("close_sentinels")), \
            mock.patch("api._final_wal_checkpoint",
                       side_effect=lambda: calls.append("checkpoint")):
        with TestClient(create_app()):
            assert calls == []
    assert calls == ["close_sentinels", "checkpoint"]
