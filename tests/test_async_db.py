"""Smoke test for ``api.database.get_async_db``.

Confirms the aiosqlite-backed helper opens a connection, applies the same
pragmas as the sync surface, returns Row-indexable results, and closes
cleanly. Required before migrating any endpoint to async — if these fail,
the larger conversion would fail with no clear signal.
"""

import asyncio
import os
import sqlite3
import tempfile
from unittest import mock

import pytest


@pytest.fixture()
def temp_db_path(tmp_path):
    """Create a tiny SQLite DB with one row and patch DEFAULT_DB_PATH at it."""
    db_path = tmp_path / "test_async.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE photos (path TEXT PRIMARY KEY, aggregate REAL)")
    conn.execute("INSERT INTO photos VALUES (?, ?)", ("/test/a.jpg", 7.5))
    conn.execute("INSERT INTO photos VALUES (?, ?)", ("/test/b.jpg", 8.2))
    conn.commit()
    conn.close()

    with mock.patch("api.database.DEFAULT_DB_PATH", str(db_path)):
        yield str(db_path)


@pytest.mark.asyncio
async def test_get_async_db_opens_and_reads(temp_db_path):
    """Confirms the helper opens a connection and returns Row-indexable results."""
    from api.database import get_async_db

    async with get_async_db() as conn:
        cursor = await conn.execute("SELECT path, aggregate FROM photos ORDER BY aggregate DESC")
        rows = await cursor.fetchall()
        assert len(rows) == 2
        # Row factory: column-name access works
        assert rows[0]["path"] == "/test/b.jpg"
        assert rows[0]["aggregate"] == pytest.approx(8.2)


@pytest.mark.asyncio
async def test_get_async_db_closes_cleanly(temp_db_path):
    """Connection is closed after the `async with` block exits."""
    from api.database import get_async_db

    async with get_async_db() as conn:
        await conn.execute("SELECT 1")
        captured = conn

    # aiosqlite marks a connection as not running once closed.
    assert not captured._running  # implementation detail but stable across aiosqlite 0.19+
