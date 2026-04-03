"""
Database connection management for FastAPI.

Wraps synchronous sqlite3 calls in run_in_executor for async compatibility.
"""

import asyncio
import sqlite3
from contextlib import contextmanager
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


async def run_sync(fn, *args, **kwargs):
    """Run a synchronous function in the default executor."""
    loop = asyncio.get_running_loop()
    if kwargs:
        return await loop.run_in_executor(None, partial(fn, *args, **kwargs))
    return await loop.run_in_executor(None, partial(fn, *args))
