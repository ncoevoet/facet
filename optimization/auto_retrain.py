"""Auto-retrain trigger for the personal ranker.

The personal ranker (``optimization/personal_ranker.py::train_ranker``) learns a
per-user taste model from pairwise comparisons and writes ``learned_scores``. It
used to run only via the ``--train-ranker`` CLI, so a user's "Picked for you"
sort went stale until they remembered to retrain by hand.

This module closes that gap: every culling confirm and every rating change feeds
a per-user "new comparisons since last train" counter; once it crosses
``RETRAIN_THRESHOLD`` we dispatch ``train_ranker`` on a background daemon thread,
guarded by a lock so only one retrain runs at a time. The request thread never
blocks and never needs a GPU (the ranker is CPU sklearn).

Design notes / safety:
- The decision (``should_retrain``) is a small pure function, unit-tested with
  ``train_ranker`` mocked — no DB, no threads.
- The counter is persisted in the ``stats_cache`` (key/value) table so it
  survives restarts; no new schema.
- The held-out CV gate inside ``train_ranker`` is NOT bypassed: a dispatched
  retrain that fails the gate simply writes nothing, exactly as a manual run
  would. ``force`` is never set here.
- If a retrain is already running, or the threshold isn't met, this does
  nothing. All DB / thread work is best-effort and never raises into the caller.
"""

import logging
import threading

logger = logging.getLogger("facet.auto_retrain")

# New comparisons (culling-derived + rating-derived) a user must accumulate
# before we kick off an automatic ranker retrain. Tuned to amortize the
# (CPU, seconds-to-minutes) train_ranker cost over a meaningful batch of new
# signal rather than retraining on every single click.
RETRAIN_THRESHOLD = 25

# stats_cache key prefix for the per-scope "new comparisons since last train"
# counter. Scope is the user_id (multi-user) or the literal "global".
_COUNTER_KEY_PREFIX = "auto_retrain_pending"

# One in-flight retrain at a time, process-wide. The scopes that requested a
# retrain while one was running are coalesced — they keep accumulating in the
# persisted counter and trigger on the next crossing.
_retrain_lock = threading.Lock()
_retrain_running = False
# Exposed for tests so a dispatched thread can be awaited deterministically.
_active_threads: "list[threading.Thread]" = []


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
    except Exception:  # noqa: BLE001 — background worker must never propagate
        logger.warning("Auto-retrain (scope=%s) failed", scope, exc_info=True)
    finally:
        with _retrain_lock:
            _retrain_running = False


def maybe_retrain(db_path, user_id, added: int = 1, threshold: int = RETRAIN_THRESHOLD):
    """Record new comparisons for a scope and dispatch a retrain if warranted.

    Call this AFTER a culling confirm or rating change has committed. It:
      1. increments the persisted per-scope pending counter by ``added``,
      2. if the counter crosses ``threshold`` and no retrain is running, resets
         the counter and dispatches ``train_ranker`` on a daemon thread.

    Non-blocking and best-effort: DB errors are swallowed (the user's action
    already succeeded and must not be rolled back by this).

    Args:
        db_path: Path to the SQLite DB.
        user_id: Per-user scope (None / falsy -> global pooled ranker).
        added: How many new comparisons this event contributed.
        threshold: Override for ``RETRAIN_THRESHOLD`` (tests pass a small value).

    Returns:
        True if a retrain was dispatched, else False.
    """
    global _retrain_running
    scope = user_id or None

    import sqlite3
    dispatch = False
    try:
        conn = sqlite3.connect(db_path)
        try:
            # Read-modify-write the counter UNDER the lock so two concurrent
            # events can't both read the same value and lose an increment, and
            # can't double-dispatch. Reset + claim the slot atomically on cross.
            with _retrain_lock:
                pending = _read_counter(conn, scope) + max(0, int(added))
                dispatch = should_retrain(pending, threshold, _retrain_running)
                if dispatch:
                    _retrain_running = True
                    _write_counter(conn, scope, 0)
                else:
                    _write_counter(conn, scope, pending)
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error:
        # The commit (or a read/write) failed AFTER we may have claimed the
        # in-flight slot under the lock. Release it here, otherwise
        # _retrain_running stays True for the whole process lifetime and
        # auto-retrain silently never runs again (the worker that would clear
        # it is never dispatched). "database is locked" is realistic because
        # this runs right after a culling/rating write on another connection.
        if dispatch:
            with _retrain_lock:
                _retrain_running = False
        logger.warning("Auto-retrain counter update failed (scope=%s)", scope, exc_info=True)
        return False

    if not dispatch:
        return False

    # Prune finished threads so the tracking list can't grow without bound.
    _active_threads[:] = [t for t in _active_threads if t.is_alive()]
    t = threading.Thread(
        target=_run_retrain, args=(db_path, scope), name=f"auto-retrain-{scope}", daemon=True,
    )
    try:
        t.start()
    except Exception:  # noqa: BLE001 — releasing the claimed slot is the point
        # Thread failed to start (e.g. resource exhaustion). We already claimed
        # the slot and reset the counter, so release the slot so the next event
        # can dispatch again instead of being blocked forever.
        with _retrain_lock:
            _retrain_running = False
        logger.warning("Auto-retrain dispatch failed to start (scope=%s)", scope, exc_info=True)
        return False
    _active_threads.append(t)
    return True
