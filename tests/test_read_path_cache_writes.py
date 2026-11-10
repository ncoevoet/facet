"""A GET handler's cache write must never queue behind the gallery index build.

The build's CREATE INDEX holds the SQLite write lock for up to ~80 s. The promise is
that READS keep working at normal speed meanwhile, but several GET handlers persist
their answer into ``stats_cache`` on the way out: that write waited out
``busy_timeout`` (5 s) and then either answered 503 ``library_busy`` on a read or
added seconds to it. ``db.stats_cache.cache_stats_best_effort`` skips the write while
this process builds, and otherwise gives up after 50 ms.

Two ways to make the write impossible, each run against every endpoint:
``lock`` -- another connection holds ``BEGIN IMMEDIATE`` (a scan, a CLI job, another
worker); ``build`` -- this process reports the index build as running.
"""

import json
import os
import sqlite3
import threading
import time

import pytest

from api import schema_startup
from api.config import invalidate_stats_cache
from db.stats_cache import (
    METRIC_RANGES_KEY, PENDING_RENDER_KEY,
    cache_stats_best_effort,
)

DB_PATH = os.environ["DB_PATH"]
# Far under the 5 s busy_timeout the unpatched write waited out, with headroom for a
# slow CI box.
MAX_SECONDS = 1.5
CACHE_KEY_PATTERNS = ("scenes_%", "color_%", "shoot_type_evidence_%", "update_check",
                      METRIC_RANGES_KEY, PENDING_RENDER_KEY)


def _cache_keys():
    conn = sqlite3.connect(DB_PATH)
    try:
        where = " OR ".join("key LIKE ?" for _ in CACHE_KEY_PATTERNS)
        return sorted(r[0] for r in conn.execute(
            f"SELECT key FROM stats_cache WHERE {where}", CACHE_KEY_PATTERNS))
    finally:
        conn.close()


def _clear_cache_rows():
    conn = sqlite3.connect(DB_PATH)
    try:
        where = " OR ".join("key LIKE ?" for _ in CACHE_KEY_PATTERNS)
        conn.execute(f"DELETE FROM stats_cache WHERE {where}", CACHE_KEY_PATTERNS)
        conn.commit()
    finally:
        conn.close()
    invalidate_stats_cache()


@pytest.fixture(autouse=True)
def _no_stale_cache_rows():
    _clear_cache_rows()
    yield
    _clear_cache_rows()


@pytest.fixture(params=["lock", "build"])
def write_blocked(request):
    """Make a cache write impossible, as the gallery index build does."""
    holder = None
    if request.param == "lock":
        holder = sqlite3.connect(DB_PATH, timeout=0, isolation_level=None)
        holder.execute("BEGIN IMMEDIATE")
    else:
        schema_startup._set_status(state=schema_startup.STATE_BUILDING, done=1, total=8)
    try:
        yield request.param
    finally:
        if holder is not None:
            holder.execute("ROLLBACK")
            holder.close()


def _timed_get(client, path):
    started = time.monotonic()
    resp = client.get(path)
    return resp, time.monotonic() - started


@pytest.mark.parametrize("path", [
    "/api/filter_options/metric_ranges",
    "/api/config",
    "/api/scenes",
    "/api/filter_options/colors",
])
def test_a_read_is_fast_and_writes_no_cache_row_while_writes_are_blocked(
        edition_client, seeded_photos, write_blocked, path):
    # The first request of a process pays one-off imports and config resolution
    # (1.6 s for /api/config), which is not what is measured here.
    edition_client.get(path)
    resp, elapsed = _timed_get(edition_client, path)
    assert resp.status_code == 200, resp.text
    assert elapsed < MAX_SECONDS, f"{path} took {elapsed:.1f}s with writes blocked ({write_blocked})"
    assert _cache_keys() == []


def test_the_metric_ranges_answer_is_unchanged_by_the_skipped_write(edition_client, seeded_photos):
    """The skipped write costs nothing but the next call's recompute."""
    free = edition_client.get("/api/filter_options/metric_ranges").json()
    assert METRIC_RANGES_KEY in _cache_keys(), "the control write must land when nothing blocks it"
    _clear_cache_rows()
    schema_startup._set_status(state=schema_startup.STATE_BUILDING, done=1, total=8)
    assert edition_client.get("/api/filter_options/metric_ranges").json() == free


def test_the_other_cached_readers_skip_their_write_during_the_build(seeded_photos):
    from api.routers.burst_culling import _shoot_type_evidence
    from api.updates import CACHE_KEY, check_for_update
    from unittest import mock

    schema_startup._set_status(state=schema_startup.STATE_BUILDING, done=1, total=8)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        started = time.monotonic()
        assert isinstance(_shoot_type_evidence(conn, None, None, None, None), list)
        with mock.patch("api.updates._fetch_latest",
                        return_value={"latest": "9.9.9", "release_url": ""}), \
                mock.patch("api.updates.get_update_settings",
                           return_value={"enabled": True, "check_url": "x", "interval_days": 1}):
            assert check_for_update(conn)["latest"] == "9.9.9"
        assert time.monotonic() - started < MAX_SECONDS
        assert conn.execute("SELECT COUNT(*) FROM stats_cache WHERE key = ? OR key LIKE "
                            "'shoot_type_evidence_%'", (CACHE_KEY,)).fetchone()[0] == 0
    finally:
        conn.close()


class TestCacheStatsBestEffort:

    def _conn(self):
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    def test_it_writes_and_restores_the_connections_busy_timeout(self):
        conn = self._conn()
        try:
            conn.execute("PRAGMA busy_timeout = 4321")
            assert cache_stats_best_effort(conn, [("update_check", json.dumps({"a": 1}))]) is True
            assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 4321
            assert conn.execute("SELECT value FROM stats_cache WHERE key = 'update_check'"
                                ).fetchone()[0] == '{"a": 1}'
        finally:
            conn.close()

    def test_a_held_write_lock_is_skipped_after_the_short_wait(self):
        holder = sqlite3.connect(DB_PATH, timeout=0, isolation_level=None)
        holder.execute("BEGIN IMMEDIATE")
        conn = self._conn()
        try:
            conn.execute("PRAGMA busy_timeout = 4321")
            started = time.monotonic()
            assert cache_stats_best_effort(conn, [("update_check", "{}")]) is False
            assert time.monotonic() - started < MAX_SECONDS
            assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 4321
        finally:
            conn.close()
            holder.execute("ROLLBACK")
            holder.close()

    def test_an_error_that_is_not_a_lock_still_raises(self, tmp_path):
        conn = sqlite3.connect(tmp_path / "no_cache_table.db")
        try:
            with pytest.raises(sqlite3.OperationalError, match="no such table"):
                cache_stats_best_effort(conn, [("update_check", "{}")])
            # sqlite3.connect's default timeout (5 s) is restored even when it raises.
            assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        finally:
            conn.close()


def test_the_capsule_precompute_can_wait_for_the_index_build(monkeypatch, tmp_path):
    """``PhotoIndexBuild.wait`` is what holds the start-up capsule scan back."""
    release = threading.Event()

    def run(self):
        release.wait(5)
        return "built"

    monkeypatch.setattr(schema_startup.PhotoIndexBuild, "run", run)
    build = schema_startup.PhotoIndexBuild(str(tmp_path / "unused.db"))
    assert build.wait() is None, "a build that never started has nothing to wait for"
    build.start()
    waiter = threading.Thread(target=build.wait)
    waiter.start()
    waiter.join(0.2)
    assert waiter.is_alive(), "wait() returned while the build still ran"
    release.set()
    waiter.join(5)
    assert not waiter.is_alive()
    assert build.wait() == "built"


def _location_rows():
    conn = sqlite3.connect(DB_PATH)
    try:
        return conn.execute("SELECT COUNT(*) FROM location_names WHERE display_name = ?",
                            (GEOCODED_NAME,)).fetchone()[0]
    finally:
        conn.close()


GEOCODED_NAME = "Testville, Nowhere"


@pytest.fixture()
def geocoder(monkeypatch):
    """A stub reverse geocoder (the real one loads its dataset) and clean cache rows."""
    monkeypatch.setattr("analyzers.reverse_geocode.reverse_geocode",
                        lambda lat, lon: GEOCODED_NAME)

    def purge():
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.execute("DELETE FROM location_names WHERE display_name = ?", (GEOCODED_NAME,))
            conn.commit()
        finally:
            conn.close()

    purge()
    yield
    purge()


def test_location_name_is_fast_and_caches_nothing_while_writes_are_blocked(
        edition_client, geocoder, write_blocked):
    """``geocode_grid`` caches the name it computed; that write must not hold the read."""
    path = "/api/filter_options/location_name?lat=12.34&lng=56.78"
    edition_client.get(path)
    resp, elapsed = _timed_get(edition_client, path)
    assert resp.status_code == 200, resp.text
    assert resp.json()["display_name"] == GEOCODED_NAME
    assert elapsed < MAX_SECONDS, f"took {elapsed:.1f}s with writes blocked ({write_blocked})"
    assert _location_rows() == 0


def test_location_name_is_cached_when_nothing_blocks_the_write(edition_client, geocoder):
    resp = edition_client.get("/api/filter_options/location_name?lat=12.34&lng=56.78")
    assert resp.json()["display_name"] == GEOCODED_NAME
    assert _location_rows() == 1


def test_the_startup_threads_wait_for_the_index_build(monkeypatch):
    """The capsule precompute and the dimension repair must not start under the build."""
    from unittest import mock
    from api import config as api_config, create_app
    from fastapi.testclient import TestClient

    release = threading.Event()
    calls = []

    def blocked_run(self):
        release.wait(20)
        return "built"

    monkeypatch.setattr(schema_startup.PhotoIndexBuild, "run", blocked_run)
    monkeypatch.setattr("api.db_helpers.repair_thumbnail_dimensions",
                        lambda *a, **k: calls.append("repair"))
    monkeypatch.setattr("analyzers.capsule_generator.generate_all_capsules",
                        lambda *a, **k: calls.append("capsules") or [])
    config = {"performance": {"wal_checkpoint_minutes": 0},
              "viewer": {"features": {"show_capsules": True}}}
    try:
        with mock.patch.object(api_config, "_FULL_CONFIG", config), TestClient(create_app()):
            time.sleep(0.6)
            assert calls == [], f"{calls} started while the index build was still running"
            release.set()
            deadline = time.monotonic() + 10
            while len(calls) < 2 and time.monotonic() < deadline:
                time.sleep(0.05)
            assert sorted(calls) == ["capsules", "repair"]
    finally:
        release.set()
        from api.routers.capsules import _capsule_cache
        _capsule_cache.clear()


def test_the_capsule_precompute_is_skipped_on_a_protected_install(monkeypatch):
    """The anonymous startup pass sees nothing there, so it would be a full scan for an empty list."""
    from unittest import mock
    from api import config as api_config, create_app
    from fastapi.testclient import TestClient

    calls = []
    monkeypatch.setattr("api.db_helpers.is_access_controlled_install", lambda: True)
    monkeypatch.setattr("analyzers.capsule_generator.generate_all_capsules",
                        lambda *a, **k: calls.append("capsules") or [])
    config = {"performance": {"wal_checkpoint_minutes": 0},
              "viewer": {"features": {"show_capsules": True}}}
    with mock.patch.object(api_config, "_FULL_CONFIG", config), TestClient(create_app()):
        time.sleep(1.0)
    assert calls == []
