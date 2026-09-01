"""
Database connection utilities for Facet.

Provides connection creation, PRAGMA configuration, and context manager.
"""

import logging
import os
import sqlite3
from contextlib import contextmanager

from config_resolve import default_config_path, load_resolved

DEFAULT_DB_PATH = os.environ.get('DB_PATH', 'photo_scores_pro.db')


# ``config_resolve`` rather than ``config``: the latter's ``__init__`` imports
# ``config.percentile_normalizer``, which imports ``db`` — and this module is the
# first thing ``db/__init__.py`` imports, so that import would recurse back into
# a ``db`` package that has not finished initializing yet. ``config_resolve``
# is stdlib-only and exists precisely so this module needs no private copy of
# the path resolution and defaults merge.
_CONFIG_PATH = default_config_path()

logger = logging.getLogger("facet.db_connection")

try:
    import sqlite_vec
    HAS_SQLITE_VEC = True
except ImportError:
    HAS_SQLITE_VEC = False


def get_pragma_values():
    """Read mmap_size and cache_size from scoring_config.json performance section."""
    mmap_size_mb = 256
    cache_size_mb = 64
    try:
        perf = load_resolved(_CONFIG_PATH).get('performance', {})
        mmap_size_mb = perf.get('mmap_size_mb', mmap_size_mb)
        cache_size_mb = perf.get('cache_size_mb', cache_size_mb)
    except (OSError, ValueError, KeyError):
        pass
    return {
        'mmap_size': mmap_size_mb * 1024 * 1024,
        'cache_size_kb': cache_size_mb * 1000,  # negative KB for PRAGMA cache_size
    }


def load_sqlite_vec(conn):
    if not HAS_SQLITE_VEC:
        return
    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
    except Exception as e:
        logger.debug("Could not load sqlite-vec extension: %s", e)


def apply_pragmas(conn, mmap_size_mb=None, cache_size_mb=None):
    """Apply standard PRAGMA settings to a connection.

    Args:
        conn: SQLite connection
        mmap_size_mb: Override mmap_size (MB). None = use config default.
        cache_size_mb: Override cache_size (MB). None = use config default.
    """
    pv = get_pragma_values()
    mmap_bytes = mmap_size_mb * 1024 * 1024 if mmap_size_mb is not None else pv['mmap_size']
    cache_kb = cache_size_mb * 1000 if cache_size_mb is not None else pv['cache_size_kb']
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute(f"PRAGMA cache_size = -{cache_kb}")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute(f"PRAGMA mmap_size = {mmap_bytes}")
    conn.execute("PRAGMA journal_size_limit = 67108864")  # 64MB WAL size limit
    load_sqlite_vec(conn)


@contextmanager
def get_connection(db_path=DEFAULT_DB_PATH, row_factory=True):
    """
    Context manager for database connections with WAL mode.

    Args:
        db_path: Path to the SQLite database file
        row_factory: If True, set row_factory to sqlite3.Row for dict-like access

    Yields:
        sqlite3.Connection configured with WAL mode and busy timeout
    """
    conn = sqlite3.connect(db_path)
    apply_pragmas(conn)
    if row_factory:
        conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()
