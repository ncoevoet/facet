"""
FTS5 full-text search management for Facet.

Rebuilds the photos_fts index from the covering schema (filename, caption,
caption_translated, tags, camera_model, lens_model, category).
"""

import logging
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

    logger.info("FTS index rebuilt: %d photos indexed (covering schema)", count)
    return count


def has_fts_table(conn=None):
    """Check if the photos_fts virtual table exists.

    TTL-cached so the warm path is conn-free and safe to call from an async
    context. Cold path opens a sync sqlite3 connection if ``conn`` is not a
    plain sqlite3.Connection (e.g. when called with an aiosqlite Connection
    from a gallery handler).
    """
    global _fts_available, _fts_checked_at
    now = time.monotonic()
    with _fts_lock:
        if _fts_available is not None and (now - _fts_checked_at) < _FTS_CACHE_TTL:
            return _fts_available

    probe_conn = conn if isinstance(conn, sqlite3.Connection) else None
    close_conn = False
    if probe_conn is None:
        probe_conn = sqlite3.connect(DEFAULT_DB_PATH)
        close_conn = True

    try:
        row = probe_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='photos_fts'"
        ).fetchone()
        result = row is not None
    except sqlite3.OperationalError:
        result = False
    finally:
        if close_conn:
            probe_conn.close()

    with _fts_lock:
        _fts_available = result
        _fts_checked_at = now
    return result


def invalidate_fts_cache():
    """Clear the cached has_fts_table result. Call after rebuild_fts."""
    global _fts_available
    with _fts_lock:
        _fts_available = None
