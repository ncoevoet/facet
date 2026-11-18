"""has_fts_table's TTL cache: keyed on the probed file, conn-free when warm."""

import sqlite3

import pytest

from db import fts


@pytest.fixture(autouse=True)
def clean_fts_cache():
    fts.invalidate_fts_cache()
    yield
    fts.invalidate_fts_cache()


def _library(tmp_path, name, with_fts):
    path = str(tmp_path / name)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE photos (path TEXT)")
    if with_fts:
        conn.execute("CREATE TABLE photos_fts (rowid INTEGER)")
    conn.commit()
    return conn


def test_each_library_gets_its_own_answer(tmp_path):
    with_fts = _library(tmp_path, "with.db", True)
    without_fts = _library(tmp_path, "without.db", False)
    try:
        assert fts.has_fts_table(with_fts) is True
        assert fts.has_fts_table(without_fts) is False
        assert fts.has_fts_table(with_fts) is True
    finally:
        with_fts.close()
        without_fts.close()


def test_warm_path_opens_no_connection_for_a_non_sqlite3_caller(monkeypatch):
    """The gallery passes an aiosqlite connection from the event loop: a warm
    answer must come from the cache, never from a fresh blocking connect."""
    monkeypatch.setattr(fts, "_fts_available", True)
    monkeypatch.setattr(fts, "_fts_checked_path", fts.DEFAULT_DB_PATH)
    monkeypatch.setattr(fts, "_fts_checked_at", fts.time.monotonic())

    def refuse(*args, **kwargs):
        raise AssertionError("has_fts_table opened a connection on a warm cache")

    monkeypatch.setattr(fts.sqlite3, "connect", refuse)
    assert fts.has_fts_table(object()) is True
    assert fts.has_fts_table() is True
