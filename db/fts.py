"""
FTS5 full-text search management for Facet.

Rebuilds the photos_fts index from the covering schema (filename, caption,
caption_translated, tags, camera_model, lens_model, category).
"""

import logging
import os
import sqlite3
import threading
import time

from db.connection import get_connection, DEFAULT_DB_PATH
from db.schema import (
    PHOTOS_FTS_COLUMNS,
    PHOTOS_FTS_CREATE,
    PHOTOS_FTS_TRIGGERS,
    fts_schema_is_current,
)

logger = logging.getLogger("facet.db_fts")

# Module-level cache for has_fts_table. Same TTL pattern as
# api.db_helpers.is_photo_tags_available: warm path is conn-free and safe to
# call from an async context with an aiosqlite Connection.
_FTS_CACHE_TTL = 300.0
# The file the cached answer was probed against (invalidated when it changes).
_fts_checked_path = None
_fts_available: bool | None = None
_fts_checked_at: float = 0.0
_fts_lock = threading.Lock()


def rebuild_fts(db_path='photo_scores_pro.db'):
    """Rebuild the FTS5 index from existing photos data.

    Drops the table if its schema doesn't match the covering set, recreates
    it, reinstalls triggers, then runs a full rebuild from the content table.
    """
    with get_connection(db_path, row_factory=False) as conn:
        if not fts_schema_is_current(conn):
            logger.info("photos_fts schema outdated — dropping for recreate")
            for trigger in ('photos_fts_ai', 'photos_fts_ad', 'photos_fts_au'):
                conn.execute(f"DROP TRIGGER IF EXISTS {trigger}")
            conn.execute("DROP TABLE IF EXISTS photos_fts")
        conn.execute(PHOTOS_FTS_CREATE)
        for trigger_sql in PHOTOS_FTS_TRIGGERS:
            conn.execute(trigger_sql)

        conn.execute("INSERT INTO photos_fts(photos_fts) VALUES('rebuild')")
        conn.commit()

        not_null = " OR ".join(f"{c} IS NOT NULL" for c in PHOTOS_FTS_COLUMNS)
        count = conn.execute(
            f"SELECT COUNT(*) FROM photos WHERE {not_null}"
        ).fetchone()[0]

    # If a viewer process had cached a previous `has_fts_table` result —
    # particularly False when the table didn't yet exist — that result would
    # be served for up to _FTS_CACHE_TTL seconds, so gallery search would
    # keep using the LIKE fallback despite FTS5 now being ready. Invalidate
    # so the next request re-probes.
    invalidate_fts_cache()

    logger.info("FTS index rebuilt: %d photos indexed (covering schema)", count)
    return count


def _probe_fts(conn):
    """Whether ``conn``'s schema has the ``photos_fts`` table."""
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='photos_fts'"
        ).fetchone()
    except sqlite3.OperationalError:
        return False
    return row is not None


_resolved_default = (None, None)


def _resolved_default_path():
    """``realpath(DEFAULT_DB_PATH)``, memoised: the warm path runs on the event
    loop and must not make a filesystem call each time."""
    global _resolved_default
    raw, resolved = _resolved_default
    if raw != DEFAULT_DB_PATH:
        resolved = os.path.realpath(DEFAULT_DB_PATH)
        _resolved_default = (DEFAULT_DB_PATH, resolved)
    return resolved


def has_fts_table(conn=None):
    """Check if the photos_fts virtual table exists.

    TTL-cached so the warm path is conn-free and safe to call from an async
    context. Cold path opens a sync sqlite3 connection if ``conn`` is not a
    plain sqlite3.Connection (e.g. when called with an aiosqlite Connection
    from a gallery handler).
    """
    global _fts_available, _fts_checked_path, _fts_checked_at
    # Determine the connection's OWN database file FIRST -- the cached answer
    # is keyed on it, so a caller with an explicit --db (or a test on a temp
    # library) gets its own schema's answer instead of the import-time
    # default's. An aiosqlite connection cannot run this sync probe, so that
    # caller probes the import-time default (the viewer's own database --
    # correct in production; the debug line notes the guess).
    probe_conn = conn if isinstance(conn, sqlite3.Connection) else None
    # DEFAULT_DB_PATH is relative unless DB_PATH is absolute, while
    # PRAGMA database_list reports an absolute path: compare both resolved, or
    # a sync caller and an aiosqlite one evict each other's cache entry and the
    # async one reopens the database on the event loop every time.
    default_path = _resolved_default_path()
    probe_path = default_path
    if probe_conn is not None:
        try:
            row = probe_conn.execute('PRAGMA database_list').fetchall()
            main_path = next((r[2] for r in row if r[1] == 'main'), default_path)
            # An in-memory or temp database reports '' -- keep that as its key.
            probe_path = os.path.realpath(main_path) if main_path else main_path
        except sqlite3.Error:
            pass

    if probe_path == '' and probe_conn is not None:
        # Every in-memory or temp database reports '': a shared key would hand
        # one such database another's answer. The probe on a live sqlite3
        # connection is cheap, so these are never cached.
        return _probe_fts(probe_conn)

    now = time.monotonic()
    with _fts_lock:
        if (_fts_available is not None and _fts_checked_path == probe_path
                and (now - _fts_checked_at) < _FTS_CACHE_TTL):
            return _fts_available

    # Cold path only: the warm one above must stay connection-free, since the
    # gallery calls this from the event loop with an aiosqlite connection.
    close_conn = False
    if probe_conn is None:
        probe_conn = sqlite3.connect(probe_path)
        close_conn = True
        logger.debug("FTS availability probed against the import-time DB_PATH: "
                     "the caller passed a non-sqlite3 connection whose file is unknown")

    try:
        result = _probe_fts(probe_conn)
    finally:
        if close_conn:
            probe_conn.close()

    with _fts_lock:
        _fts_available = result
        _fts_checked_at = now
        _fts_checked_path = probe_path
    return result


def invalidate_fts_cache():
    """Clear the cached has_fts_table result. Call after rebuild_fts."""
    global _fts_available, _fts_checked_path
    with _fts_lock:
        _fts_available = None
        _fts_checked_path = None
