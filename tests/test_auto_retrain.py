"""Tests for the personal-ranker auto-retrain trigger (optimization/auto_retrain.py).

The trigger fires after culling confirms and rating changes: it accumulates a
per-scope "new comparisons since last train" counter in stats_cache and, once it
crosses a threshold, dispatches train_ranker on a background daemon thread,
guarded so only one retrain runs at a time.

These tests mock train_ranker entirely — no real training, no GPU, no sklearn.
They cover the pure decision function and the counter/threshold/lock/dispatch
behavior of maybe_retrain.
"""

import sqlite3
import threading
from unittest import mock

import pytest

from db.schema import init_database
from optimization import auto_retrain as ar


@pytest.fixture()
def db_path(tmp_path):
    p = str(tmp_path / "ar.db")
    init_database(p)
    return p


@pytest.fixture(autouse=True)
def _reset_module_state():
    """Each test starts with the lock released and no tracked threads."""
    with ar._retrain_lock:
        ar._retrain_running = False
    ar._active_threads.clear()
    yield
    # Join any threads a test dispatched so state doesn't leak across tests.
    for t in list(ar._active_threads):
        t.join(timeout=5)
    with ar._retrain_lock:
        ar._retrain_running = False
    ar._active_threads.clear()


# --- pure decision function ------------------------------------------------- #

def test_should_retrain_threshold_met_and_idle():
    assert ar.should_retrain(25, 25, is_running=False) is True
    assert ar.should_retrain(100, 25, is_running=False) is True


def test_should_retrain_below_threshold():
    assert ar.should_retrain(24, 25, is_running=False) is False
    assert ar.should_retrain(0, 25, is_running=False) is False


def test_should_retrain_blocked_when_running():
    # Even far past threshold, a running retrain blocks a new dispatch.
    assert ar.should_retrain(1000, 25, is_running=True) is False


# --- maybe_retrain: counter + threshold + dispatch -------------------------- #

def _counter(db_path, scope):
    conn = sqlite3.connect(db_path)
    try:
        return ar._read_counter(conn, scope)
    finally:
        conn.close()


def test_below_threshold_accumulates_and_does_not_dispatch(db_path):
    with mock.patch("optimization.personal_ranker.train_ranker") as train:
        dispatched = ar.maybe_retrain(db_path, user_id=None, added=10, threshold=25)
        assert dispatched is False
        dispatched = ar.maybe_retrain(db_path, user_id=None, added=10, threshold=25)
        assert dispatched is False
    train.assert_not_called()
    # Counter persisted across the two calls.
    assert _counter(db_path, None) == 20


def test_crossing_threshold_dispatches_and_resets_counter(db_path):
    done = threading.Event()

    def fake_train(db_path=None, user_id=None, **kwargs):
        done.set()
        return {"gated": False, "written": 5, "cv_accuracy": 88.0}

    with mock.patch("optimization.personal_ranker.train_ranker", side_effect=fake_train) as train:
        dispatched = ar.maybe_retrain(db_path, user_id=None, added=30, threshold=25)
        assert dispatched is True
        assert done.wait(timeout=5), "train_ranker was not invoked on the background thread"

    for t in list(ar._active_threads):
        t.join(timeout=5)

    train.assert_called_once()
    # Dispatched with the right scope and WITHOUT force (CV gate left intact).
    _, kwargs = train.call_args
    assert kwargs.get("user_id") is None
    assert "force" not in kwargs or kwargs["force"] is False
    # Counter reset on dispatch.
    assert _counter(db_path, None) == 0
    # Lock released after the worker finished.
    assert ar._retrain_running is False


def test_does_not_dispatch_while_one_is_running(db_path):
    # Hold a retrain "running" by blocking train_ranker on an event.
    release = threading.Event()
    started = threading.Event()

    def blocking_train(db_path=None, user_id=None, **kwargs):
        started.set()
        release.wait(timeout=5)
        return {"gated": False, "written": 1, "cv_accuracy": 90.0}

    with mock.patch("optimization.personal_ranker.train_ranker", side_effect=blocking_train) as train:
        # First crossing dispatches and the worker blocks (running == True).
        assert ar.maybe_retrain(db_path, user_id=None, added=30, threshold=25) is True
        assert started.wait(timeout=5)
        assert ar._retrain_running is True

        # A second crossing while running must NOT dispatch; it keeps the count.
        assert ar.maybe_retrain(db_path, user_id=None, added=30, threshold=25) is False
        assert _counter(db_path, None) == 30  # accumulated, not reset

        release.set()  # let the first worker finish

    for t in list(ar._active_threads):
        t.join(timeout=5)
    train.assert_called_once()
    assert ar._retrain_running is False


def test_scopes_are_independent(db_path):
    with mock.patch("optimization.personal_ranker.train_ranker") as train:
        ar.maybe_retrain(db_path, user_id="alice", added=20, threshold=25)
        ar.maybe_retrain(db_path, user_id="bob", added=20, threshold=25)
    train.assert_not_called()
    assert _counter(db_path, "alice") == 20
    assert _counter(db_path, "bob") == 20
    # Neither crossed alone, so the global scope is untouched too.
    assert _counter(db_path, None) == 0


def test_worker_failure_releases_lock(db_path):
    def boom(db_path=None, user_id=None, **kwargs):
        raise RuntimeError("training blew up")

    with mock.patch("optimization.personal_ranker.train_ranker", side_effect=boom):
        assert ar.maybe_retrain(db_path, user_id=None, added=30, threshold=25) is True

    for t in list(ar._active_threads):
        t.join(timeout=5)
    # A failing worker must still release the lock so future retrains can run.
    assert ar._retrain_running is False


def test_commit_failure_after_claim_releases_slot(db_path, monkeypatch):
    """A commit failure right after the slot is claimed must release it.

    Regression: the slot was claimed (``_retrain_running = True``) under the lock
    BEFORE ``conn.commit()``, but only ever cleared by the dispatched worker. If
    the commit raised (e.g. SQLite "database is locked" under concurrent writes),
    the function returned before dispatching the worker and the slot stayed True
    for the whole process lifetime — auto-retrain silently never ran again.
    """
    real_connect = sqlite3.connect

    class _FailingCommitConn:
        def __init__(self, conn):
            self._conn = conn

        def __getattr__(self, name):
            return getattr(self._conn, name)

        def commit(self):
            raise sqlite3.OperationalError("database is locked")

    def fake_connect(path, *args, **kwargs):
        return _FailingCommitConn(real_connect(path, *args, **kwargs))

    monkeypatch.setattr(sqlite3, "connect", fake_connect)

    with mock.patch("optimization.personal_ranker.train_ranker") as train:
        # Crossing the threshold claims the slot, then commit blows up.
        assert ar.maybe_retrain(db_path, user_id=None, added=30, threshold=25) is False

    # No worker was dispatched...
    train.assert_not_called()
    assert ar._active_threads == []
    # ...and the slot was released so future retrains are not blocked forever.
    assert ar._retrain_running is False


def test_thread_start_failure_releases_slot(db_path, monkeypatch):
    """If the daemon thread can't start, the claimed slot must still be released."""
    def boom_start(self):
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(threading.Thread, "start", boom_start)

    with mock.patch("optimization.personal_ranker.train_ranker"):
        assert ar.maybe_retrain(db_path, user_id=None, added=30, threshold=25) is False

    assert ar._retrain_running is False
    # The reset-to-0 must be rolled back since the worker never ran, so the
    # accumulated comparisons are not silently discarded.
    assert _counter(db_path, None) == 30


def test_gated_result_logged_and_lock_released(db_path):
    """A retrain that fails the held-out CV gate writes nothing but releases cleanly."""
    def gated_train(db_path=None, user_id=None, **kwargs):
        # force must not be set, so the gate stays active.
        assert kwargs.get("force") in (None, False)
        return {"gated": True, "written": 0, "cv_accuracy": 60.0, "baseline_accuracy": 60.0}

    with mock.patch("optimization.personal_ranker.train_ranker", side_effect=gated_train) as train:
        assert ar.maybe_retrain(db_path, user_id=None, added=30, threshold=25) is True

    for t in list(ar._active_threads):
        t.join(timeout=5)
    train.assert_called_once()
    assert ar._retrain_running is False
