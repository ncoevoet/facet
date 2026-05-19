"""
Database connection management for FastAPI.

Two surfaces:
- `get_db()` / `get_db_connection()` — synchronous sqlite3, the canonical
  surface used by most routers.
- `get_async_db()` — aiosqlite-backed async context manager for read-heavy
  endpoints that want to avoid blocking the event loop. Migration is gradual
  per the merged plan; convert endpoints individually after benchmarking.

Both surfaces honor the same pragmas, mmap, and cache size settings.
"""

import asyncio
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from functools import partial

from db import DEFAULT_DB_PATH, apply_pragmas
from api.config import VIEWER_CONFIG


_viewer_perf = VIEWER_CONFIG.get('performance', {})


def get_db_connection():
    """Get database connection with WAL mode and row factory.

    Uses viewer.performance overrides if configured, otherwise falls back
    to global performance settings from scoring_config.json.
    Returns a plain connection (caller must close).
    """
    conn = sqlite3.connect(DEFAULT_DB_PATH)
    apply_pragmas(conn,
        mmap_size_mb=_viewer_perf.get('mmap_size_mb'),
        cache_size_mb=_viewer_perf.get('cache_size_mb'))
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def get_db():
    """Context manager for database connections."""
    conn = get_db_connection()
    try:
        yield conn
    finally:
        conn.close()


@asynccontextmanager
async def get_async_db():
    """Async context manager yielding an ``aiosqlite.Connection``.

    Issues the same pragmas as the sync surface (WAL mode, mmap, cache size)
    over the aiosqlite worker thread and sets ``row_factory = aiosqlite.Row``,
    so reads return Row objects with column-name indexing — semantics match
    ``get_db()``.

    Usage::

        async with get_async_db() as conn:
            cursor = await conn.execute("SELECT 1")
            row = await cursor.fetchone()
    """
    import aiosqlite

    conn = await aiosqlite.connect(DEFAULT_DB_PATH)
    try:
        # Mirror the full sync pragma set (db/connection.py:apply_pragmas) over
        # the aiosqlite worker thread. We can't call apply_pragmas directly
        # because aiosqlite owns the underlying sqlite3.Connection on its own
        # thread and cross-thread sqlite3 use raises ProgrammingError.
        from db.connection import get_pragma_values
        pv = get_pragma_values()
        mmap_bytes = (
            int(_viewer_perf['mmap_size_mb']) * 1024 * 1024
            if _viewer_perf.get('mmap_size_mb') is not None
            else pv['mmap_size']
        )
        cache_kb = (
            int(_viewer_perf['cache_size_mb']) * 1000
            if _viewer_perf.get('cache_size_mb') is not None
            else pv['cache_size_kb']
        )
        await conn.execute("PRAGMA journal_mode = WAL")
        await conn.execute("PRAGMA busy_timeout = 5000")
        await conn.execute("PRAGMA foreign_keys = ON")
        await conn.execute("PRAGMA synchronous = NORMAL")
        await conn.execute(f"PRAGMA cache_size = -{cache_kb}")
        await conn.execute("PRAGMA temp_store = MEMORY")
        await conn.execute(f"PRAGMA mmap_size = {mmap_bytes}")
        await conn.execute("PRAGMA journal_size_limit = 67108864")
        # Load sqlite-vec on each aiosqlite connection so KNN queries against
        # `photos_vec` work on the async path. sqlite-vec is per-connection —
        # `vec0` and `vec_distance_cosine` are unavailable without this load.
        # Skipping it would silently fall back to a full NumPy matmul on every
        # search.
        from db.connection import HAS_SQLITE_VEC
        if HAS_SQLITE_VEC:
            try:
                import sqlite_vec
                await conn.enable_load_extension(True)
                await conn.load_extension(sqlite_vec.loadable_path())
                await conn.enable_load_extension(False)
            except Exception:
                # Non-fatal: search will fall back to NumPy via _check_vec_available.
                # Log loudly — silent failure here was the root cause of an
                # ~unknown-duration perf regression before c542ff7.
                import logging
                logging.getLogger(__name__).warning(
                    "sqlite-vec load failed on async connection — /api/search will use NumPy fallback",
                    exc_info=True,
                )
        conn.row_factory = aiosqlite.Row
        yield conn
    finally:
        await conn.close()


async def run_sync(fn, *args, **kwargs):
    """Run a synchronous function in the default executor."""
    loop = asyncio.get_running_loop()
    if kwargs:
        return await loop.run_in_executor(None, partial(fn, *args, **kwargs))
    return await loop.run_in_executor(None, partial(fn, *args))
