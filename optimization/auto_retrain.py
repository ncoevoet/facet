"""Auto-retrain trigger for the personal ranker.

The personal ranker (``optimization/personal_ranker.py::train_ranker``) learns a
per-user taste model from pairwise comparisons and writes ``learned_scores``. It
used to run only via the ``--train-ranker`` CLI, so a user's "Picked for you"
sort went stale until they remembered to retrain by hand.

This module closes that gap: every culling confirm and every rating change feeds
a per-user "new comparisons since last train" counter; once it crosses the
configured threshold AND the user has been idle for ``idle_seconds``, we dispatch
``train_ranker`` on a background daemon thread, guarded by a lock so only one
retrain runs at a time. The request thread never blocks and never needs a GPU
(the ranker is CPU sklearn).

Design notes / safety:
- The decision (``should_retrain``) is a small pure function, unit-tested with
  ``train_ranker`` mocked — no DB, no threads.
- The counter is persisted in the ``stats_cache`` (key/value) table so it
  survives restarts; no new schema.
- Crossing the threshold arms an idle timer rather than dispatching outright.
  Every later event pushes the timer back, so the retrain lands when the user
  pauses instead of mid-burst — where its long write would otherwise contend
  with the user's own rating writes and time them out.
- The counter is only zeroed, and the in-flight slot only claimed, at the moment
  the worker actually starts, so a crash inside the idle window cannot discard
  accumulated comparisons.
- The held-out CV gate inside ``train_ranker`` is NOT bypassed: a dispatched
  retrain that fails the gate simply writes nothing, exactly as a manual run
  would. ``force`` is never set here.
- If a retrain is already running, or the threshold isn't met, this does
  nothing. All DB / thread work is best-effort and never raises into the caller.
"""

import json
import logging
import os
import threading

logger = logging.getLogger("facet.auto_retrain")

# New comparisons (culling-derived + rating-derived) a user must accumulate
# before we kick off an automatic ranker retrain. Tuned to amortize the
# (CPU, seconds-to-minutes) train_ranker cost over a meaningful batch of new
# signal rather than retraining on every single click.
DEFAULT_THRESHOLD = 25

# Seconds of no rating/culling activity required before a threshold crossing
# actually dispatches. 0 dispatches inline (the pre-debounce behaviour; used by
# tests).
DEFAULT_IDLE_SECONDS = 60

# stats_cache key prefix for the per-scope "new comparisons since last train"
# counter. Scope is the user_id (multi-user) or the literal "global".
_COUNTER_KEY_PREFIX = "auto_retrain_pending"


def _setting(env_var, configured, fallback, cast):
    """First of env var / config value / built-in default that casts cleanly."""
    for candidate in (os.environ.get(env_var), configured):
        if candidate is None or candidate == '':
            continue
        try:
            return cast(candidate)
        except (TypeError, ValueError):
            continue
    return fallback


def load_settings(config_path=None):
    """(threshold, idle_seconds) from the ``auto_retrain`` block; env overrides.

    Missing file, missing block, or an unparseable value falls back to the next
    source, so a malformed override degrades to the shipped default rather than
    disabling auto-retrain.
    """
    block = {}
    try:
        from config import default_config_path
        with open(config_path or default_config_path()) as f:
            loaded = json.load(f).get('auto_retrain', {})
        if isinstance(loaded, dict):
            block = loaded
    except Exception:  # noqa: BLE001 — config is advisory here, never fatal
        logger.debug("Could not read the auto_retrain config block", exc_info=True)
    return (
        _setting("FACET_RETRAIN_THRESHOLD", block.get('threshold'), DEFAULT_THRESHOLD, int),
        _setting("FACET_RETRAIN_IDLE_S", block.get('idle_seconds'), DEFAULT_IDLE_SECONDS, float),
    )


RETRAIN_THRESHOLD, RETRAIN_IDLE_SECONDS = load_settings()

# One in-flight retrain at a time, process-wide. The scopes that requested a
# retrain while one was running are coalesced — they keep accumulating in the
# persisted counter and trigger on the next crossing.
_retrain_lock = threading.Lock()
_retrain_running = False
# Exposed for tests so a dispatched thread can be awaited deterministically.
_active_threads: "list[threading.Thread]" = []
# scope -> Timer armed by a threshold crossing, awaiting the idle window.
# Guarded by _retrain_lock.
_pending_timers = {}


def should_retrain(new_count: int, threshold: int, is_running: bool) -> bool:
    """Pure decision: should we dispatch a retrain right now?

    Args:
        new_count: Accumulated new comparisons for this scope since last train.
        threshold: Minimum new comparisons required to retrain.
        is_running: Whether a retrain is already in flight (process-wide).

    Returns:
        True iff a retrain is warranted (threshold met and none running).
    """
    if is_running:
        return False
    return new_count >= threshold


def _scope_key(scope) -> str:
    """stats_cache key for a scope's pending counter ('global' when scope is None)."""
    return f"{_COUNTER_KEY_PREFIX}:{scope if scope is not None else 'global'}"


def _read_counter(conn, scope) -> int:
    row = conn.execute(
        "SELECT value FROM stats_cache WHERE key = ?", (_scope_key(scope),)
    ).fetchone()
    if not row or row[0] is None:
        return 0
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return 0


def _write_counter(conn, scope, value: int) -> None:
    import time
    conn.execute(
        "INSERT OR REPLACE INTO stats_cache (key, value, updated_at) VALUES (?, ?, ?)",
        (_scope_key(scope), str(int(value)), time.time()),
    )


def _run_retrain(db_path, scope):
    """Background worker: run train_ranker for one scope, then release the lock.

    Best-effort: any failure is logged and swallowed so a broken train never
    takes down the server thread that spawned it. The held-out CV gate inside
    train_ranker is left intact (force is not passed).
    """
    global _retrain_running
    try:
        from optimization.personal_ranker import train_ranker
        result = train_ranker(db_path=db_path, user_id=scope)
        if result.get("error"):
            logger.info("Auto-retrain (scope=%s) skipped: %s", scope, result["error"])
        elif result.get("gated"):
            logger.info(
                "Auto-retrain (scope=%s) gated by held-out CV (no improvement); "
                "learned_scores unchanged.", scope,
            )
        else:
            logger.info(
                "Auto-retrain (scope=%s) wrote %s learned_scores (held-out %.1f%%).",
                scope, result.get("written"), result.get("cv_accuracy", 0.0),
            )
        # Culling confirms accumulate source='culling' pairs; refresh the keeper
        # head on the same trigger (best-effort — its own gate is intact).
        try:
            from optimization.keeper_head import train_keeper_head
            kr = train_keeper_head(db_path=db_path, user_id=scope)
            if kr.get("error"):
                logger.info("Auto-retrain keeper (scope=%s) skipped: %s", scope, kr["error"])
            elif kr.get("gated"):
                logger.info("Auto-retrain keeper (scope=%s) gated (no improvement).", scope)
            else:
                logger.info(
                    "Auto-retrain keeper (scope=%s) wrote head (held-out %.1f%%).",
                    scope, kr.get("cv_accuracy", 0.0),
                )
        except Exception:  # noqa: BLE001 — keeper refresh must not break the ranker path
            logger.warning("Auto-retrain keeper (scope=%s) failed", scope, exc_info=True)
    except Exception:  # noqa: BLE001 — background worker must never propagate
        logger.warning("Auto-retrain (scope=%s) failed", scope, exc_info=True)
    finally:
        with _retrain_lock:
            _retrain_running = False


def _dispatch(db_path, scope, threshold):
    """Claim the in-flight slot, zero the counter, and start the worker.

    Re-checks the counter against the threshold on its own connection, because
    this also runs from the idle timer — long after the crossing that armed it.

    Returns True when the worker thread started.
    """
    global _retrain_running
    import sqlite3
    conn = None
    claimed = False
    try:
        conn = sqlite3.connect(db_path)
        with _retrain_lock:
            _pending_timers.pop(scope, None)
            pending = _read_counter(conn, scope)
            if not should_retrain(pending, threshold, _retrain_running):
                return False
            _retrain_running = True
            claimed = True
            _write_counter(conn, scope, 0)
            conn.commit()

        # Prune finished threads so the tracking list can't grow unbounded.
        _active_threads[:] = [t for t in _active_threads if t.is_alive()]
        t = threading.Thread(
            target=_run_retrain, args=(db_path, scope), name=f"auto-retrain-{scope}", daemon=True,
        )
        try:
            t.start()
        except Exception:  # noqa: BLE001 — releasing the claimed slot is the point
            # Thread failed to start (e.g. resource exhaustion). Release the
            # slot so the next event can dispatch again, and restore the
            # counter to `pending` — the reset to 0 above assumed a training
            # run that never happened, so without this the accumulated
            # comparisons would be silently discarded.
            with _retrain_lock:
                _retrain_running = False
            _write_counter(conn, scope, pending)
            conn.commit()
            logger.warning("Auto-retrain dispatch failed to start (scope=%s)", scope, exc_info=True)
            return False
        _active_threads.append(t)
        return True
    except sqlite3.Error:
        # A read/write/commit failed AFTER we may have claimed the in-flight
        # slot under the lock. Release it here, otherwise _retrain_running stays
        # True for the whole process lifetime and auto-retrain silently never
        # runs again (the worker that would clear it is never dispatched).
        # "database is locked" is realistic because this runs right after a
        # culling/rating write on another connection.
        if claimed:
            with _retrain_lock:
                _retrain_running = False
        logger.warning("Auto-retrain dispatch failed (scope=%s)", scope, exc_info=True)
        return False
    finally:
        if conn is not None:
            conn.close()


def _schedule(db_path, scope, threshold, idle_seconds):
    """(Re)arm the idle timer for a scope. Each new event pushes it back."""
    with _retrain_lock:
        existing = _pending_timers.get(scope)
        if existing is not None:
            existing[0].cancel()
        timer = threading.Timer(idle_seconds, _dispatch, args=(db_path, scope, threshold))
        timer.daemon = True
        _pending_timers[scope] = (timer, db_path, threshold)
        timer.start()


def flush_pending_retrain():
    """Fire any armed idle timers immediately (tests / shutdown)."""
    with _retrain_lock:
        pending = list(_pending_timers.items())
        _pending_timers.clear()
    for scope, (timer, db_path, threshold) in pending:
        timer.cancel()
        _dispatch(db_path, scope, threshold)


def maybe_retrain(db_path, user_id, added: int = 1, threshold: int = None, conn=None,
                  idle_seconds: float = None):
    """Record new comparisons for a scope and arm a retrain if warranted.

    Call this AFTER a culling confirm or rating change has committed. It:
      1. increments the persisted per-scope pending counter by ``added``,
      2. if the counter crosses ``threshold`` and no retrain is running, arms an
         idle timer; every later event pushes that timer back, so ``train_ranker``
         only starts once the user has stopped for ``idle_seconds``.

    Non-blocking and best-effort: DB errors are swallowed (the user's action
    already succeeded and must not be rolled back by this).

    Args:
        db_path: Path to the SQLite DB.
        user_id: Per-user scope (None / falsy -> global pooled ranker).
        added: How many new comparisons this event contributed.
        threshold: Override for ``RETRAIN_THRESHOLD`` (tests pass a small value).
        conn: An already-open connection from the calling request to reuse for
            the counter update (avoids a second connection on the hot culling
            path). ``None`` opens a short-lived one and closes it.
        idle_seconds: Override for ``RETRAIN_IDLE_SECONDS``. <= 0 dispatches
            inline instead of arming a timer.

    Returns:
        True if a retrain was dispatched or armed, else False.
    """
    scope = user_id or None
    if threshold is None:
        threshold = RETRAIN_THRESHOLD
    if idle_seconds is None:
        idle_seconds = RETRAIN_IDLE_SECONDS

    import sqlite3
    own_conn = conn is None
    try:
        if own_conn:
            conn = sqlite3.connect(db_path)
        try:
            # Read-modify-write the counter UNDER the lock so two concurrent
            # events can't both read the same value and lose an increment.
            with _retrain_lock:
                pending = _read_counter(conn, scope) + max(0, int(added))
                _write_counter(conn, scope, pending)
                conn.commit()
                ready = should_retrain(pending, threshold, _retrain_running)
        finally:
            if own_conn:
                conn.close()
    except sqlite3.Error:
        logger.warning("Auto-retrain counter update failed (scope=%s)", scope, exc_info=True)
        return False

    if not ready:
        return False
    if idle_seconds <= 0:
        return _dispatch(db_path, scope, threshold)
    _schedule(db_path, scope, threshold, idle_seconds)
    return True
