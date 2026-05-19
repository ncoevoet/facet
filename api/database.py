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
        # Issue pragmas via the async connection so they run on its worker
        # thread (aiosqlite owns the underlying sqlite3.Connection there).
        await conn.execute("PRAGMA journal_mode = WAL")
        await conn.execute("PRAGMA synchronous = NORMAL")
        await conn.execute("PRAGMA temp_store = MEMORY")
        mmap_size_mb = _viewer_perf.get('mmap_size_mb')
        if mmap_size_mb:
            await conn.execute(f"PRAGMA mmap_size = {int(mmap_size_mb) * 1024 * 1024}")
        cache_size_mb = _viewer_perf.get('cache_size_mb')
        if cache_size_mb:
            # Negative cache_size = kibibytes; convert MB -> KB.
            await conn.execute(f"PRAGMA cache_size = -{int(cache_size_mb) * 1024}")
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
