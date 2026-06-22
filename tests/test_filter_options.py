"""Tests for /filter_options/persons endpoint — focusing on the `ids` force-include logic."""

import sqlite3
from unittest import mock

from fastapi.testclient import TestClient

from api import create_app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(path: str, persons: list, faces: list):
    """Create a minimal test DB with persons, faces, and photos tables."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE persons (id INTEGER PRIMARY KEY, name TEXT, is_hidden INTEGER DEFAULT 0);
        CREATE TABLE faces (id INTEGER PRIMARY KEY, person_id INTEGER, photo_path TEXT);
        CREATE TABLE photos (path TEXT PRIMARY KEY);
    """)
    conn.executemany("INSERT INTO persons (id, name) VALUES (?, ?)", persons)
    conn.executemany("INSERT INTO faces VALUES (?, ?, ?)", faces)
    photos = {f[2] for f in faces}
    conn.executemany("INSERT INTO photos VALUES (?)", [(p,) for p in photos])
    conn.commit()
    conn.close()


def _build_app_with(db_path: str, viewer_cfg: dict):
    """Create the FastAPI app with the test DB and config patches in place.

    The filter_options router has been migrated to ``async def`` + aiosqlite,
    so we point ``api.database.DEFAULT_DB_PATH`` at the temp file and let the
    real async code run against it. ``_cached_filter_query`` is bypassed via
    the ``is_multi_user_enabled=True`` branch (multi-user always skips the
    cache lookup) so the tests do not depend on the offline ``stats_cache``
    table being populated.
    """
    patches = [
        mock.patch("api.database.DEFAULT_DB_PATH", db_path),
        mock.patch("api.routers.filter_options.VIEWER_CONFIG", viewer_cfg),
        mock.patch("api.routers.filter_options.is_multi_user_enabled", return_value=True),
        mock.patch("api.db_helpers.is_multi_user_enabled", return_value=True),
    ]
    for p in patches:
        p.start()
    app = create_app()
    return app, patches


def _stop_patches(patches):
    for p in patches:
        p.stop()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPersonsEndpoint:
    def test_no_ids_excludes_below_min_photos(self, tmp_path):
        """Without ids, persons below min_photos threshold are excluded."""
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, [(1, "Alice"), (2, "Bob")], [
            *[(i, 1, f"/p1_{i}.jpg") for i in range(5)],
            (100, 2, "/p2_1.jpg"),
        ])
        app, patches = _build_app_with(db_path, {
            "dropdowns": {"min_photos_for_person": 2, "max_persons": 100}
        })
        try:
            resp = TestClient(app).get("/api/filter_options/persons")
        finally:
            _stop_patches(patches)
        assert resp.status_code == 200
        ids = [p[0] for p in resp.json()["persons"]]
        assert 1 in ids
        assert 2 not in ids

    def test_ids_forces_below_threshold_person(self, tmp_path):
        """Person below min_photos threshold appears when requested via `ids`."""
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, [(1, "Alice"), (2, None)], [
            *[(i, 1, f"/p1_{i}.jpg") for i in range(5)],
            (100, 2, "/p2_1.jpg"),
        ])
        app, patches = _build_app_with(db_path, {
            "dropdowns": {"min_photos_for_person": 2, "max_persons": 100}
        })
        try:
            resp = TestClient(app).get("/api/filter_options/persons?ids=2")
        finally:
            _stop_patches(patches)
        assert resp.status_code == 200
        ids = [p[0] for p in resp.json()["persons"]]
        assert 2 in ids
        assert 1 in ids

    def test_ids_forced_person_prepended(self, tmp_path):
        """Forced person (below threshold) appears before the regular list."""
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, [(1, "Alice"), (99, "Forced")], [
            *[(i, 1, f"/p1_{i}.jpg") for i in range(10)],
            (100, 99, "/p99_1.jpg"),
        ])
        app, patches = _build_app_with(db_path, {
            "dropdowns": {"min_photos_for_person": 3, "max_persons": 100}
        })
        try:
            resp = TestClient(app).get("/api/filter_options/persons?ids=99")
        finally:
            _stop_patches(patches)
        persons = resp.json()["persons"]
        assert persons[0][0] == 99

    def test_ids_already_in_regular_list_not_duplicated(self, tmp_path):
        """A person already meeting the threshold is not duplicated when also in `ids`."""
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, [(1, "Alice")], [(i, 1, f"/p_{i}.jpg") for i in range(5)])
        app, patches = _build_app_with(db_path, {
            "dropdowns": {"min_photos_for_person": 1, "max_persons": 100}
        })
        try:
            resp = TestClient(app).get("/api/filter_options/persons?ids=1")
        finally:
            _stop_patches(patches)
        persons = resp.json()["persons"]
        assert len([p for p in persons if p[0] == 1]) == 1

    def test_non_numeric_ids_silently_ignored(self, tmp_path):
        """Non-numeric values in `ids` are silently dropped — no 500 error."""
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, [(1, "Alice")], [(i, 1, f"/p_{i}.jpg") for i in range(3)])
        app, patches = _build_app_with(db_path, {
            "dropdowns": {"min_photos_for_person": 1, "max_persons": 100}
        })
        try:
            resp = TestClient(app).get("/api/filter_options/persons?ids=abc,1drop,;DELETE")
        finally:
            _stop_patches(patches)
        assert resp.status_code == 200

    def test_ids_bypasses_cache(self, tmp_path):
        """When `ids` is provided, _cached_filter_query is not called."""
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, [(1, "Alice")], [(i, 1, f"/p_{i}.jpg") for i in range(3)])
        cache_mock = mock.AsyncMock()
        patches = [
            mock.patch("api.database.DEFAULT_DB_PATH", db_path),
            mock.patch("api.routers.filter_options.VIEWER_CONFIG", {
                "dropdowns": {"min_photos_for_person": 1, "max_persons": 100}
            }),
            mock.patch("api.routers.filter_options.is_multi_user_enabled", return_value=True),
            mock.patch("api.db_helpers.is_multi_user_enabled", return_value=True),
            mock.patch("api.routers.filter_options._cached_filter_query", cache_mock),
        ]
        for p in patches:
            p.start()
        try:
            app = create_app()
            resp = TestClient(app).get("/api/filter_options/persons?ids=1")
        finally:
            _stop_patches(patches)
        assert resp.status_code == 200
        cache_mock.assert_not_called()


class TestColorsEndpoint:
    """Tests for /filter_options/colors (Part B color facet)."""

    @staticmethod
    def _make_color_db(path):
        conn = sqlite3.connect(path)
        conn.execute(
            "CREATE TABLE photos (path TEXT PRIMARY KEY, dominant_hue REAL, color_temp TEXT)"
        )
        rows = [
            ("/a.jpg", 10.0, "warm"),     # red bucket
            ("/b.jpg", 40.0, "warm"),     # orange bucket
            ("/c.jpg", 220.0, "cool"),    # blue bucket
            ("/d.jpg", None, "neutral"),  # no hue
        ]
        conn.executemany("INSERT INTO photos VALUES (?, ?, ?)", rows)
        conn.commit()
        conn.close()

    def test_colors_returns_temps_and_hue_buckets(self, tmp_path):
        db_path = str(tmp_path / "colors.db")
        self._make_color_db(db_path)
        app, patches = _build_app_with(db_path, {
            "dropdowns": {"min_photos_for_person": 1, "max_persons": 100}
        })
        try:
            resp = TestClient(app).get("/api/filter_options/colors")
        finally:
            _stop_patches(patches)
        assert resp.status_code == 200
        body = resp.json()
        temps = dict(body["temps"])
        assert temps["warm"] == 2
        assert temps["cool"] == 1
        assert temps["neutral"] == 1
        buckets = dict(body["hue_buckets"])
        # Each non-empty bucket is present; the NULL-hue photo contributes none.
        assert buckets.get("red") == 1
        assert buckets.get("orange") == 1
        assert buckets.get("blue") == 1
        assert "green" not in buckets  # no green photos
