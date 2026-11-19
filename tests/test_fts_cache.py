"""has_fts_table's TTL cache: keyed on the probed file, conn-free when warm."""

import os
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
    monkeypatch.setattr(fts, "_fts_checked_path", os.path.realpath(fts.DEFAULT_DB_PATH))
    monkeypatch.setattr(fts, "_fts_checked_at", fts.time.monotonic())

    def refuse(*args, **kwargs):
        raise AssertionError("has_fts_table opened a connection on a warm cache")

    monkeypatch.setattr(fts.sqlite3, "connect", refuse)
    assert fts.has_fts_table(object()) is True
    assert fts.has_fts_table() is True


def test_a_relative_default_path_shares_the_sync_callers_cache_entry(tmp_path, monkeypatch):
    """DB_PATH unset leaves DEFAULT_DB_PATH relative while PRAGMA database_list
    is absolute: alternating sync and async callers must not evict each other,
    or the async gallery reopens the database on the event loop every time."""
    library = _library(tmp_path, "photo_scores_pro.db", True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(fts, "DEFAULT_DB_PATH", "photo_scores_pro.db")
    connects = []
    real_connect = fts.sqlite3.connect
    monkeypatch.setattr(fts.sqlite3, "connect",
                        lambda *args, **kwargs: connects.append(args) or real_connect(*args, **kwargs))
    try:
        for _ in range(5):
            assert fts.has_fts_table(library) is True
            assert fts.has_fts_table(object()) is True
    finally:
        library.close()
    assert connects == []


def test_in_memory_databases_never_share_an_answer():
    """Every in-memory database reports '' as its file: those answers are
    probed live, never cached under a shared key."""
    with_fts = sqlite3.connect(":memory:")
    without_fts = sqlite3.connect(":memory:")
    with_fts.execute("CREATE TABLE photos_fts (rowid INTEGER)")
    try:
        assert fts.has_fts_table(with_fts) is True
        assert fts.has_fts_table(without_fts) is False
        assert fts.has_fts_table(with_fts) is True
    finally:
        with_fts.close()
        without_fts.close()
