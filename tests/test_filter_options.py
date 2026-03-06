"""Tests for /filter_options/persons endpoint — focusing on the `ids` force-include logic."""

import sqlite3
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from api import create_app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(path: str, persons: list, faces: list):
    """Create a minimal test DB with persons, faces, and photos tables."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE persons (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE faces (id INTEGER PRIMARY KEY, person_id INTEGER, photo_path TEXT);
        CREATE TABLE photos (path TEXT PRIMARY KEY);
    """)
    conn.executemany("INSERT INTO persons VALUES (?, ?)", persons)
    conn.executemany("INSERT INTO faces VALUES (?, ?, ?)", faces)
    photos = {f[2] for f in faces}
    conn.executemany("INSERT INTO photos VALUES (?)", [(p,) for p in photos])
    conn.commit()
    conn.close()


def _conn_factory(db_path: str):
    """Return a factory that opens a new thread-safe connection each call."""
    def factory():
        return sqlite3.connect(db_path, check_same_thread=False)
    return factory



# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPersonsEndpoint:
    def test_no_ids_excludes_below_min_photos(self, tmp_path):
        """Without ids, persons below min_photos threshold are excluded."""
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, [(1, "Alice"), (2, "Bob")], [
            *[(i, 1, f"/p1_{i}.jpg") for i in range(5)],  # Alice: 5 photos
            (100, 2, "/p2_1.jpg"),                         # Bob: 1 photo, below threshold
        ])
        conn_factory = _conn_factory(db_path)
        app = create_app()
        with (
            mock.patch("api.routers.filter_options.get_db_connection", conn_factory),
            mock.patch("api.routers.filter_options.VIEWER_CONFIG", {
                "dropdowns": {"min_photos_for_person": 2, "max_persons": 100}
            }),
            mock.patch("api.routers.filter_options.is_multi_user_enabled", return_value=False),
            mock.patch("api.routers.filter_options._cached_filter_query",
                       side_effect=lambda _ck, rk, fn: {rk: fn(conn_factory()), "cached": False}),
        ):
            resp = TestClient(app).get("/api/filter_options/persons")
        assert resp.status_code == 200
        ids = [p[0] for p in resp.json()["persons"]]
        assert 1 in ids
        assert 2 not in ids

    def test_ids_forces_below_threshold_person(self, tmp_path):
        """Person below min_photos threshold appears when requested via `ids`."""
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, [(1, "Alice"), (2, None)], [
            *[(i, 1, f"/p1_{i}.jpg") for i in range(5)],
            (100, 2, "/p2_1.jpg"),  # unnamed, 1 photo — below threshold
        ])
        conn_factory = _conn_factory(db_path)
        app = create_app()
        with (
            mock.patch("api.routers.filter_options.get_db_connection", conn_factory),
            mock.patch("api.routers.filter_options.VIEWER_CONFIG", {
                "dropdowns": {"min_photos_for_person": 2, "max_persons": 100}
            }),
            mock.patch("api.routers.filter_options.is_multi_user_enabled", return_value=False),
            mock.patch("api.routers.filter_options._cached_filter_query",
                       side_effect=lambda _ck, rk, fn: {rk: fn(conn_factory()), "cached": False}),
        ):
            resp = TestClient(app).get("/api/filter_options/persons?ids=2")
        assert resp.status_code == 200
        ids = [p[0] for p in resp.json()["persons"]]
        assert 2 in ids   # forced in despite 1 photo < threshold
        assert 1 in ids   # Alice still present via normal query

    def test_ids_forced_person_prepended(self, tmp_path):
        """Forced person (below threshold) appears before the regular list."""
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, [(1, "Alice"), (99, "Forced")], [
            *[(i, 1, f"/p1_{i}.jpg") for i in range(10)],
            (100, 99, "/p99_1.jpg"),  # Forced: 1 photo, below threshold
        ])
        conn_factory = _conn_factory(db_path)
        app = create_app()
        with (
            mock.patch("api.routers.filter_options.get_db_connection", conn_factory),
            mock.patch("api.routers.filter_options.VIEWER_CONFIG", {
                "dropdowns": {"min_photos_for_person": 3, "max_persons": 100}
            }),
            mock.patch("api.routers.filter_options.is_multi_user_enabled", return_value=False),
            mock.patch("api.routers.filter_options._cached_filter_query",
                       side_effect=lambda _ck, rk, fn: {rk: fn(conn_factory()), "cached": False}),
        ):
            resp = TestClient(app).get("/api/filter_options/persons?ids=99")
        persons = resp.json()["persons"]
        assert persons[0][0] == 99

    def test_ids_already_in_regular_list_not_duplicated(self, tmp_path):
        """A person already meeting the threshold is not duplicated when also in `ids`."""
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, [(1, "Alice")], [(i, 1, f"/p_{i}.jpg") for i in range(5)])
        conn_factory = _conn_factory(db_path)
        app = create_app()
        with (
            mock.patch("api.routers.filter_options.get_db_connection", conn_factory),
            mock.patch("api.routers.filter_options.VIEWER_CONFIG", {
                "dropdowns": {"min_photos_for_person": 1, "max_persons": 100}
            }),
            mock.patch("api.routers.filter_options.is_multi_user_enabled", return_value=False),
            mock.patch("api.routers.filter_options._cached_filter_query",
                       side_effect=lambda _ck, rk, fn: {rk: fn(conn_factory()), "cached": False}),
        ):
            resp = TestClient(app).get("/api/filter_options/persons?ids=1")
        persons = resp.json()["persons"]
        assert len([p for p in persons if p[0] == 1]) == 1

    def test_non_numeric_ids_silently_ignored(self, tmp_path):
        """Non-numeric values in `ids` are silently dropped — no 500 error."""
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, [(1, "Alice")], [(i, 1, f"/p_{i}.jpg") for i in range(3)])
        conn_factory = _conn_factory(db_path)
        app = create_app()
        with (
            mock.patch("api.routers.filter_options.get_db_connection", conn_factory),
            mock.patch("api.routers.filter_options.VIEWER_CONFIG", {
                "dropdowns": {"min_photos_for_person": 1, "max_persons": 100}
            }),
            mock.patch("api.routers.filter_options.is_multi_user_enabled", return_value=False),
            mock.patch("api.routers.filter_options._cached_filter_query",
                       side_effect=lambda _ck, rk, fn: {rk: fn(conn_factory()), "cached": False}),
        ):
            resp = TestClient(app).get("/api/filter_options/persons?ids=abc,1drop,;DELETE")
        assert resp.status_code == 200

    def test_ids_bypasses_cache(self, tmp_path):
        """When `ids` is provided, _cached_filter_query is not called."""
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, [(1, "Alice")], [(i, 1, f"/p_{i}.jpg") for i in range(3)])
        conn_factory = _conn_factory(db_path)
        app = create_app()
        cache_mock = mock.MagicMock()
        with (
            mock.patch("api.routers.filter_options.get_db_connection", conn_factory),
            mock.patch("api.routers.filter_options.VIEWER_CONFIG", {
                "dropdowns": {"min_photos_for_person": 1, "max_persons": 100}
            }),
            mock.patch("api.routers.filter_options.is_multi_user_enabled", return_value=False),
            mock.patch("api.routers.filter_options._cached_filter_query", cache_mock),
        ):
            resp = TestClient(app).get("/api/filter_options/persons?ids=1")
        assert resp.status_code == 200
        cache_mock.assert_not_called()
