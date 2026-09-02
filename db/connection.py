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


_pragma_cache = None


def _config_stamp():
    """Cheap identity of the override file: (mtime_ns, size), or None if absent.

    Absent is a real state to cache, not an error -- an install with no
    override resolves to the shipped defaults on every call and the answer
    never changes -- so None is a legitimate stamp value that compares equal
    to itself.
    """
    try:
        st = os.stat(_CONFIG_PATH)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def get_pragma_values():
    """Read mmap_size and cache_size from scoring_config.json performance section.

    Memoized against the config file's (mtime, size), because this runs once
    per DB connection -- so at least once per API request -- and the two
    integers it returns cost a full resolve to obtain: a ~97 KB parse of the
    shipped defaults plus a deep_merge that deep-copies ~2600 leaves, measured
    at ~1.2 ms per connection once an override file exists. The stamp is what
    keeps this honest as a cache rather than a freeze: an operator editing
    ``performance`` sees it on the next connection, exactly as before, without
    a restart.
    """
    global _pragma_cache
    stamp = _config_stamp()
    if _pragma_cache is not None and _pragma_cache[0] == stamp:
        return _pragma_cache[1]

    mmap_size_mb = 256
    cache_size_mb = 64
    resolved = False
    try:
        perf = load_resolved(_CONFIG_PATH).get('performance') or {}
        mmap_size_mb = perf.get('mmap_size_mb', mmap_size_mb)
        cache_size_mb = perf.get('cache_size_mb', cache_size_mb)
        resolved = True
    except (OSError, ValueError, KeyError, AttributeError, TypeError):
        logger.debug("Could not resolve pragma values from %s", _CONFIG_PATH, exc_info=True)
    values = {
        'mmap_size': mmap_size_mb * 1024 * 1024,
        'cache_size_kb': cache_size_mb * 1000,  # negative KB for PRAGMA cache_size
    }
    if resolved:
        # Only a SUCCESSFUL read is memoized. A transient failure -- EACCES while
        # a chmod is in flight, EMFILE under load, EIO on a network mount -- does
        # not move the file's mtime or size, so caching the fallback under that
        # same stamp would pin every later connection in this process to 256/64
        # with no way back short of a restart.
        _pragma_cache = (stamp, values)
    return values


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
    # Only reach for the config when a caller left something for it to supply.
    pv = get_pragma_values() if mmap_size_mb is None or cache_size_mb is None else None
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
