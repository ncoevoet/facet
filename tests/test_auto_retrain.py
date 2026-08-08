"""Tests for the personal-ranker auto-retrain trigger (optimization/auto_retrain.py).

The trigger fires after culling confirms and rating changes: it accumulates a
per-scope "new comparisons since last train" counter in stats_cache and, once it
crosses a threshold, arms an idle timer that dispatches train_ranker on a
background daemon thread once the user stops — guarded so only one retrain runs
at a time.

These tests mock train_ranker entirely — no real training, no GPU, no sklearn.
They cover the pure decision function, the counter/threshold/lock/dispatch
behavior of maybe_retrain, the idle debounce, and the settings resolution.
"""

import os
import sqlite3
import threading
import time
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
def _reset_module_state(monkeypatch):
    """Each test starts with the lock released and no tracked threads.

    Idle debouncing is off by default here so these tests exercise the
    counter/threshold/lock behaviour directly; the debounce itself is covered by
    its own tests below, which set an explicit idle_seconds.
    """
    monkeypatch.setattr(ar, "RETRAIN_IDLE_SECONDS", 0.0)
    with ar._retrain_lock:
        ar._retrain_running = False
        for timer, _, _ in ar._pending_timers.values():
            timer.cancel()
        ar._pending_timers.clear()
    ar._active_threads.clear()
    yield
    # Join any threads a test dispatched so state doesn't leak across tests.
    for t in list(ar._active_threads):
        t.join(timeout=5)
    with ar._retrain_lock:
        ar._retrain_running = False
        for timer, _, _ in ar._pending_timers.values():
            timer.cancel()
        ar._pending_timers.clear()
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


# --- keeper-head refresh on the same retrain trigger ------------------------ #

def test_keeper_head_refreshed_on_retrain_with_scope(db_path):
    """The keeper head trains on the SAME dispatch, scoped to the retrain's user."""
    done = threading.Event()
    captured = {}

    def ok_ranker(db_path=None, user_id=None, **kwargs):
        return {"gated": False, "written": 3, "cv_accuracy": 88.0}

    def fake_keeper(db_path=None, user_id=None, **kwargs):
        captured["db_path"] = db_path
        captured["user_id"] = user_id
        done.set()
        return {"gated": False, "written": 1, "cv_accuracy": 90.0}

    with (
        mock.patch("optimization.personal_ranker.train_ranker", side_effect=ok_ranker),
        mock.patch("optimization.keeper_head.train_keeper_head", side_effect=fake_keeper) as keeper,
    ):
        assert ar.maybe_retrain(db_path, user_id="alice", added=30, threshold=25) is True
        assert done.wait(timeout=5), "train_keeper_head was not invoked on the background thread"

    for t in list(ar._active_threads):
        t.join(timeout=5)
    keeper.assert_called_once()
    assert captured["user_id"] == "alice"
    assert captured["db_path"] == db_path
    assert ar._retrain_running is False


def test_keeper_refresh_failure_does_not_block_ranker(db_path):
    """A keeper-head refresh that raises must not fail the ranker path or leak the lock."""
    ranker_done = threading.Event()

    def ok_ranker(db_path=None, user_id=None, **kwargs):
        ranker_done.set()
        return {"gated": False, "written": 2, "cv_accuracy": 88.0}

    def boom_keeper(db_path=None, user_id=None, **kwargs):
        raise RuntimeError("keeper training blew up")

    with (
        mock.patch("optimization.personal_ranker.train_ranker", side_effect=ok_ranker) as ranker,
        mock.patch("optimization.keeper_head.train_keeper_head", side_effect=boom_keeper) as keeper,
    ):
        assert ar.maybe_retrain(db_path, user_id=None, added=30, threshold=25) is True

    for t in list(ar._active_threads):
        t.join(timeout=5)
    ranker.assert_called_once()
    keeper.assert_called_once()
    assert ranker_done.is_set()
    assert ar._retrain_running is False


# --- idle debounce ---------------------------------------------------------- #

def test_crossing_threshold_arms_a_timer_instead_of_dispatching(db_path):
    """The crossing must not train while the user is still clicking."""
    with mock.patch("optimization.personal_ranker.train_ranker") as train:
        assert ar.maybe_retrain(db_path, user_id=None, added=30, threshold=25,
                                idle_seconds=30) is True
        train.assert_not_called()
        assert None in ar._pending_timers
        # The counter is NOT consumed until the worker actually starts, so a
        # crash inside the idle window cannot discard accumulated comparisons.
        assert _counter(db_path, None) == 30


def test_further_events_push_the_idle_window_back(db_path):
    with mock.patch("optimization.personal_ranker.train_ranker") as train:
        ar.maybe_retrain(db_path, user_id=None, added=30, threshold=25, idle_seconds=30)
        first = ar._pending_timers[None][0]
        ar.maybe_retrain(db_path, user_id=None, added=1, threshold=25, idle_seconds=30)
        second = ar._pending_timers[None][0]

    assert second is not first, "a later event must re-arm the timer"
    assert not first.is_alive(), "the superseded timer must be cancelled"
    train.assert_not_called()
    assert _counter(db_path, None) == 31


def test_timer_dispatches_once_the_window_elapses(db_path):
    done = threading.Event()

    def fake_train(db_path=None, user_id=None, **kwargs):
        done.set()
        return {"gated": False, "written": 5, "cv_accuracy": 88.0}

    with mock.patch("optimization.personal_ranker.train_ranker", side_effect=fake_train) as train:
        for _ in range(30):
            ar.maybe_retrain(db_path, user_id=None, added=1, threshold=25, idle_seconds=0.05)
        assert done.wait(timeout=5), "the idle timer never dispatched the retrain"
        # The worker is registered in _active_threads only after it starts, so on
        # the timer path joining that list can race. Wait on the slot itself.
        deadline = time.time() + 5
        while ar._retrain_running and time.time() < deadline:
            time.sleep(0.01)

    # A whole burst collapses into exactly one retrain.
    train.assert_called_once()
    assert _counter(db_path, None) == 0
    assert ar._retrain_running is False


def test_flush_pending_retrain_fires_an_armed_timer(db_path):
    done = threading.Event()

    def fake_train(db_path=None, user_id=None, **kwargs):
        done.set()
        return {"gated": False, "written": 1, "cv_accuracy": 88.0}

    with mock.patch("optimization.personal_ranker.train_ranker", side_effect=fake_train):
        ar.maybe_retrain(db_path, user_id=None, added=30, threshold=25, idle_seconds=300)
        ar.flush_pending_retrain()
        assert done.wait(timeout=5), "flush did not dispatch the armed retrain"
        for t in list(ar._active_threads):
            t.join(timeout=5)

    assert ar._pending_timers == {}
    assert _counter(db_path, None) == 0


def test_dispatch_commit_failure_releases_the_claimed_slot(db_path, monkeypatch):
    """The claim-then-commit window now lives in _dispatch; it must not wedge.

    _dispatch sets _retrain_running under the lock and only then commits the
    counter reset. If that commit raises ("database is locked" is realistic —
    this runs right after a rating write on another connection), the slot has to
    be released or auto-retrain never runs again for the process lifetime.
    """
    real_connect = sqlite3.connect

    class _FailingCommitConn:
        def __init__(self, conn):
            self._conn = conn

        def __getattr__(self, name):
            return getattr(self._conn, name)

        def commit(self):
            raise sqlite3.OperationalError("database is locked")

    # Let maybe_retrain's own counter commit succeed, then fail inside _dispatch.
    conn = real_connect(db_path)
    ar._write_counter(conn, None, 30)
    conn.commit()
    conn.close()
    monkeypatch.setattr(sqlite3, "connect", lambda p, *a, **k: _FailingCommitConn(real_connect(p, *a, **k)))

    with mock.patch("optimization.personal_ranker.train_ranker") as train:
        assert ar._dispatch(db_path, None, 25) is False

    train.assert_not_called()
    assert ar._active_threads == []
    assert ar._retrain_running is False


# --- settings: config block + env override ---------------------------------- #

def test_settings_fall_back_to_builtin_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv("FACET_RETRAIN_THRESHOLD", raising=False)
    monkeypatch.delenv("FACET_RETRAIN_IDLE_S", raising=False)
    missing = str(tmp_path / "nope.json")
    assert ar.load_settings(missing) == (ar.DEFAULT_THRESHOLD, ar.DEFAULT_IDLE_SECONDS)


def test_settings_read_the_config_block(tmp_path, monkeypatch):
    monkeypatch.delenv("FACET_RETRAIN_THRESHOLD", raising=False)
    monkeypatch.delenv("FACET_RETRAIN_IDLE_S", raising=False)
    cfg = tmp_path / "c.json"
    cfg.write_text('{"auto_retrain": {"threshold": 100, "idle_seconds": 120}}')
    assert ar.load_settings(str(cfg)) == (100, 120.0)


def test_env_overrides_the_config_block(tmp_path, monkeypatch):
    cfg = tmp_path / "c.json"
    cfg.write_text('{"auto_retrain": {"threshold": 100, "idle_seconds": 120}}')
    monkeypatch.setenv("FACET_RETRAIN_THRESHOLD", "7")
    monkeypatch.setenv("FACET_RETRAIN_IDLE_S", "1.5")
    assert ar.load_settings(str(cfg)) == (7, 1.5)


def test_malformed_env_falls_back_to_the_config_value(tmp_path, monkeypatch):
    cfg = tmp_path / "c.json"
    cfg.write_text('{"auto_retrain": {"threshold": 100, "idle_seconds": 120}}')
    monkeypatch.setenv("FACET_RETRAIN_THRESHOLD", "not-a-number")
    monkeypatch.delenv("FACET_RETRAIN_IDLE_S", raising=False)
    assert ar.load_settings(str(cfg)) == (100, 120.0)


def test_malformed_config_block_falls_back_to_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv("FACET_RETRAIN_THRESHOLD", raising=False)
    monkeypatch.delenv("FACET_RETRAIN_IDLE_S", raising=False)
    cfg = tmp_path / "c.json"
    cfg.write_text('{"auto_retrain": {"threshold": "eleventy", "idle_seconds": null}}')
    assert ar.load_settings(str(cfg)) == (ar.DEFAULT_THRESHOLD, ar.DEFAULT_IDLE_SECONDS)


def test_shipped_config_block_matches_the_builtin_defaults():
    """scoring_config.json must not silently drift from the module defaults."""
    from config import default_config_path
    monkey = dict(os.environ)
    for key in ("FACET_RETRAIN_THRESHOLD", "FACET_RETRAIN_IDLE_S"):
        monkey.pop(key, None)
    with mock.patch.dict(os.environ, monkey, clear=True):
        assert ar.load_settings(default_config_path()) == (
            ar.DEFAULT_THRESHOLD, ar.DEFAULT_IDLE_SECONDS)


def test_empty_env_falls_through_to_the_config_block(tmp_path, monkeypatch):
    """docker-compose sets `VAR=` when the .env value is unset.

    An empty string must be treated as "not configured", not as a parse failure
    or a zero — otherwise a stock Docker deployment would silently lose the
    config block's values.
    """
    cfg = tmp_path / "c.json"
    cfg.write_text('{"auto_retrain": {"threshold": 100, "idle_seconds": 120}}')
    monkeypatch.setenv("FACET_RETRAIN_THRESHOLD", "")
    monkeypatch.setenv("FACET_RETRAIN_IDLE_S", "")
    assert ar.load_settings(str(cfg)) == (100, 120.0)
