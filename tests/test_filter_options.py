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
        # These tests exercise the persons/colors dropdown LOGIC (min_photos,
        # ids force-include, colour buckets), not visibility gating — which is
        # covered by test_filter_options_visibility.py. Open the visibility
        # clause so an unauthenticated TestClient reaches the rows under test;
        # otherwise get_visibility_clause(None) fails closed to 0=1 under the
        # multi-user patch above.
        mock.patch("api.routers.filter_options.get_visibility_clause", return_value=("1=1", [])),
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

    def test_non_numeric_ids_are_refused(self, tmp_path):
        """Non-numeric `ids` tokens are refused with 422, not silently swallowed.

        Person 1 is kept below `min_photos_for_person` so the only way it could
        appear in the response is via the `ids` force-include path; a silent
        empty list would read as "no forced persons" instead of the client's
        mistake.
        """
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, [(1, "Alice")], [(i, 1, f"/p_{i}.jpg") for i in range(3)])
        app, patches = _build_app_with(db_path, {
            "dropdowns": {"min_photos_for_person": 5, "max_persons": 100}
        })
        try:
            resp = TestClient(app).get("/api/filter_options/persons?ids=abc,1drop,;DELETE")
        finally:
            _stop_patches(patches)
        assert resp.status_code == 422

    def test_empty_ids_tokens_are_refused_too(self, tmp_path):
        """An empty token (e.g. a trailing comma) is bad input, not a skippable one."""
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, [(1, "Alice")], [(i, 1, f"/p_{i}.jpg") for i in range(3)])
        app, patches = _build_app_with(db_path, {
            "dropdowns": {"min_photos_for_person": 5, "max_persons": 100}
        })
        try:
            resp = TestClient(app).get("/api/filter_options/persons?ids=1,")
        finally:
            _stop_patches(patches)
        assert resp.status_code == 422

    def test_mixed_valid_and_invalid_ids_refuse_the_whole_request(self, tmp_path):
        """One bad token refuses the request: partial acceptance would hide the mistake."""
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, [(1, "Alice")], [(i, 1, f"/p_{i}.jpg") for i in range(3)])
        app, patches = _build_app_with(db_path, {
            "dropdowns": {"min_photos_for_person": 5, "max_persons": 100}
        })
        try:
            resp = TestClient(app).get("/api/filter_options/persons?ids=abc,1")
        finally:
            _stop_patches(patches)
        assert resp.status_code == 422

    def test_ids_over_the_person_group_limit_are_refused(self, tmp_path):
        """More distinct ids than a `person` filter may hold draw a 422.

        The same PERSON_FILTER_LIMIT ceiling a gallery `person` filter enforces
        keeps the forced-include IN clause far under SQLite's variable limit;
        past it the pre-fix route answered a silent empty list (unknown ids) or
        tripped the IN clause and swallowed the error into one.
        """
        from api.models.gallery import PERSON_FILTER_LIMIT
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, [(1, "Alice")], [(i, 1, f"/p_{i}.jpg") for i in range(3)])
        app, patches = _build_app_with(db_path, {
            "dropdowns": {"min_photos_for_person": 5, "max_persons": 100}
        })
        try:
            resp = TestClient(app).get(
                "/api/filter_options/persons",
                params={"ids": ",".join(str(i) for i in range(1, PERSON_FILTER_LIMIT + 2))})
        finally:
            _stop_patches(patches)
        assert resp.status_code == 422

    def test_ids_at_the_person_group_limit_are_accepted(self, tmp_path):
        """Exactly PERSON_FILTER_LIMIT distinct ids still parses (the cap is inclusive)."""
        from api.models.gallery import PERSON_FILTER_LIMIT
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, [(1, "Alice")], [(i, 1, f"/p_{i}.jpg") for i in range(3)])
        app, patches = _build_app_with(db_path, {
            "dropdowns": {"min_photos_for_person": 5, "max_persons": 100}
        })
        try:
            resp = TestClient(app).get(
                "/api/filter_options/persons",
                params={"ids": ",".join(str(i) for i in range(1, PERSON_FILTER_LIMIT + 1))})
        finally:
            _stop_patches(patches)
        assert resp.status_code == 200
        # Only person 1 exists; the other 199 ids are unknown and stay absent.
        assert [p[0] for p in resp.json()["persons"]] == [1]

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


def _reset_side_table_caches():
    """Empty the process-wide side-table availability caches a tmp DB warmed.

    ``is_photo_tags_available`` / ``is_manual_tags_available`` TTL-cache their answer
    (5 minutes) regardless of which database answered it: a vocab DB without the
    manual-tags tables would leave ``False`` behind for every later test that reads
    the shared session database. Same idea as test_async_routes_do_not_block's
    ``_cold_caches``.
    """
    import api.db_helpers as db_helpers
    from api import config as _config

    db_helpers.invalidate_existing_columns_cache()
    with _config._photo_tags_lock:
        _config._photo_tags_available = None
        _config._photo_tags_checked_at = 0.0
    db_helpers._photo_tags_available = None


class TestQueryPushdown:
    """`query` narrows a vocabulary read in SQL, before the route's own LIMIT.

    The agent-facing filter_options tool passes its needle down instead of pulling the
    whole vocabulary and trimming afterwards, so the match set is bounded upstream.
    """

    def _make_vocab_db(self, path: str, categories: list, tags: tuple = (), cameras: tuple = ()):
        conn = sqlite3.connect(path)
        conn.executescript(
            "CREATE TABLE photos (path TEXT PRIMARY KEY, category TEXT, camera_model TEXT);\n"
            "CREATE TABLE photo_tags (photo_path TEXT, tag TEXT);")
        rows = len(categories) or len(cameras)
        conn.executemany(
            "INSERT INTO photos (path, category, camera_model) VALUES (?, ?, ?)",
            [(f"/c{i}.jpg",
              categories[i] if i < len(categories) else None,
              cameras[i] if i < len(cameras) else None) for i in range(rows)])
        conn.executemany("INSERT INTO photo_tags VALUES (?, ?)",
                         [(f"/t{i}.jpg", tag) for i, tag in enumerate(tags)])
        conn.commit()
        conn.close()

    def _get(self, db_path: str, endpoint: str, params: dict, *,
             photo_tags: bool = True, visibility: tuple = ("1=1", [])):
        app, patches = _build_app_with(db_path, {
            "dropdowns": {"min_photos_for_person": 1, "max_persons": 100,
                          "max_tags": 20, "max_cameras": 50, "max_lenses": 50}
        })
        # The availability probes are TTL-cached process-wide (a sibling test's answer
        # would stick for 5 minutes), so pin them to what the vocab DB actually holds.
        overrides = [
            mock.patch("api.routers.filter_options.is_photo_tags_available", return_value=photo_tags),
            mock.patch("api.routers.filter_options.is_manual_tags_available", return_value=False),
            mock.patch("api.routers.filter_options.get_visibility_clause", return_value=visibility),
        ]
        for p in overrides:
            p.start()
        try:
            return TestClient(app).get(f"/api/filter_options/{endpoint}", params=params)
        finally:
            # The visibility override sits on top of _build_app_with's own patch of
            # the same name, so it must unwind first.
            _stop_patches(reversed(overrides))
            _stop_patches(patches)
            _reset_side_table_caches()

    def test_query_filters_the_vocabulary_case_insensitively(self, tmp_path):
        db_path = str(tmp_path / "vocab.db")
        self._make_vocab_db(db_path, ["Red Apples", "Crimson Red", "Blue Sky"])
        resp = self._get(db_path, "categories", {"query": "red"})
        assert resp.status_code == 200
        assert [row[0] for row in resp.json()["categories"]] == ["Red Apples", "Crimson Red"]

    def test_an_underscore_needle_is_a_literal_too(self, tmp_path):
        db_path = str(tmp_path / "vocab.db")
        self._make_vocab_db(db_path, ["a_b", "axb", "Plain"])
        resp = self._get(db_path, "categories", {"query": "a_b"})
        assert resp.status_code == 200
        assert [row[0] for row in resp.json()["categories"]] == ["a_b"]

    def test_no_query_returns_every_option(self, tmp_path):
        db_path = str(tmp_path / "vocab.db")
        self._make_vocab_db(db_path, ["Red Apples", "Crimson Red", "Blue Sky"])
        resp = self._get(db_path, "categories", {})
        assert resp.status_code == 200
        assert {row[0] for row in resp.json()["categories"]} == {"Red Apples", "Crimson Red", "Blue Sky"}

    def test_a_non_ascii_needle_matches_unicode_case_insensitively(self, tmp_path):
        # A category named Été must be found by été: SQLite's LIKE folds ASCII
        # only, so the non-ASCII needle switches to the Unicode-folding
        # comparison (the old Python trim matched via str.lower).
        db_path = str(tmp_path / "vocab.db")
        self._make_vocab_db(db_path, ["Été", "Hiver", "Étang"])
        resp = self._get(db_path, "categories", {"query": "été"})
        assert resp.status_code == 200
        assert [row[0] for row in resp.json()["categories"]] == ["Été"]

    def test_query_is_a_literal_substring_not_a_wildcard(self, tmp_path):
        db_path = str(tmp_path / "vocab.db")
        self._make_vocab_db(db_path, ["100%", "100x", "Plain"])
        resp = self._get(db_path, "categories", {"query": "100%"})
        assert resp.status_code == 200
        assert [row[0] for row in resp.json()["categories"]] == ["100%"]

    def test_a_filtered_read_is_capped_upstream(self, tmp_path):
        from api.routers.filter_options import QUERY_MATCH_LIMIT
        db_path = str(tmp_path / "vocab.db")
        self._make_vocab_db(db_path, [f"cat{value:04}" for value in range(QUERY_MATCH_LIMIT + 1)])
        resp = self._get(db_path, "categories", {"query": "cat"})
        assert resp.status_code == 200
        rows = resp.json()["categories"]
        assert len(rows) == QUERY_MATCH_LIMIT and all(row[0].startswith("cat") for row in rows)

    def test_tags_query_filters_before_the_dropdown_limit(self, tmp_path):
        db_path = str(tmp_path / "vocab.db")
        self._make_vocab_db(db_path, [], tags=["Sunset", "sunset beach", "Mountain"])
        resp = self._get(db_path, "tags", {"query": "sunset"})
        assert resp.status_code == 200
        assert {row[0] for row in resp.json()["tags"]} == {"Sunset", "sunset beach"}

    @pytest.mark.parametrize("photo_tags", [True, False], ids=["photo_tags", "split_fallback"])
    def test_tags_query_runs_under_a_visibility_clause(self, tmp_path, photo_tags):
        # A restricted caller takes the pair-level branch (or the recursive split
        # when photo_tags is missing); both bind the visibility params before the
        # needle, so a wrong order would surface here as a 500 or an empty list.
        db_path = str(tmp_path / "vocab.db")
        self._make_vocab_db(db_path, [], tags=["sunset", "sunrise", "mountain"])
        conn = sqlite3.connect(db_path)
        conn.execute("ALTER TABLE photos ADD COLUMN tags TEXT")
        conn.executemany("INSERT INTO photos (path, tags) VALUES (?, ?)",
                         [("/t0.jpg", "sunset"), ("/t1.jpg", "sunrise"), ("/t2.jpg", "mountain")])
        conn.commit()
        conn.close()
        resp = self._get(db_path, "tags", {"query": "sun"}, photo_tags=photo_tags,
                         visibility=("photos.path != ?", ["/t1.jpg"]))
        assert resp.status_code == 200
        assert [row[0] for row in resp.json()["tags"]] == ["sunset"]

    def test_cameras_query_filters_the_models(self, tmp_path):
        db_path = str(tmp_path / "vocab.db")
        self._make_vocab_db(db_path, [], cameras=["X100VI", "X-T5", "R6 Mark II"])
        resp = self._get(db_path, "cameras", {"query": "x100"})
        assert resp.status_code == 200
        assert [row[0] for row in resp.json()["cameras"]] == ["X100VI"]

    def test_a_non_ascii_tag_needle_matches_chinese_tags(self, tmp_path):
        # The tags route runs its queries on its own connection: the Unicode
        # folding helper must be registered there too, or even an EXACT
        # Chinese tag search returns an empty list (no such function).
        db_path = str(tmp_path / "vocab.db")
        self._make_vocab_db(db_path, ["Red Apples"], tags=("风景", "城市"))
        resp = self._get(db_path, "tags", {"query": "风景"})
        assert resp.status_code == 200
        assert [row[0] for row in resp.json()["tags"]] == ["风景"]

    def test_persons_query_filters_the_names_but_ids_stay_forced(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        _make_db(db_path, [(1, "Alice"), (2, "Bob")], [
            *[(i, 1, f"/p1_{i}.jpg") for i in range(5)],
            *[(10 + i, 2, f"/p2_{i}.jpg") for i in range(5)],
        ])
        resp = self._get(db_path, "persons", {"query": "ali"})
        assert resp.status_code == 200
        assert [row[0] for row in resp.json()["persons"]] == [1]
        # The ids force-include is independent of the name filter.
        resp = self._get(db_path, "persons", {"query": "nomatch", "ids": "2"})
        assert resp.status_code == 200
        assert [row[0] for row in resp.json()["persons"]] == [2]

    def test_query_bypasses_the_whole_library_cache(self, tmp_path):
        """A filtered read cannot come from the cache: its rows are already LIMIT-cut."""
        db_path = str(tmp_path / "vocab.db")
        self._make_vocab_db(db_path, ["Red Apples", "Blue Sky"])
        cache_mock = mock.AsyncMock()
        patches = [
            mock.patch("api.database.DEFAULT_DB_PATH", db_path),
            mock.patch("api.routers.filter_options.VIEWER_CONFIG", {
                "dropdowns": {"min_photos_for_person": 1, "max_persons": 100}
            }),
            mock.patch("api.routers.filter_options.is_multi_user_enabled", return_value=False),
            mock.patch("api.db_helpers.is_multi_user_enabled", return_value=False),
            mock.patch("api.routers.filter_options._cached_filter_query", cache_mock),
        ]
        for p in patches:
            p.start()
        try:
            app = create_app()
            resp = TestClient(app).get("/api/filter_options/categories", params={"query": "red"})
        finally:
            _stop_patches(patches)
            _reset_side_table_caches()
        assert resp.status_code == 200
        cache_mock.assert_not_called()


class TestMetricRangesAuth:
    """F9': /metric_ranges is no longer unauthenticated on a locked deployment."""

    def test_denied_for_unidentified_caller(self, anonymous_client):
        resp = anonymous_client.get("/api/filter_options/metric_ranges")
        assert resp.status_code == 401

    def test_allowed_for_authenticated(self, edition_client):
        resp = edition_client.get("/api/filter_options/metric_ranges")
        assert resp.status_code == 200
        assert "ranges" in resp.json()


class TestLocationNameAuth:
    """F9': /location_name no longer serves an open reverse-geocoder."""

    def test_denied_for_unidentified_caller(self, anonymous_client):
        resp = anonymous_client.get(
            "/api/filter_options/location_name", params={"lat": 48.8, "lng": 2.3}
        )
        assert resp.status_code == 401

    def test_allowed_for_authenticated(self, edition_client):
        with mock.patch(
            "analyzers.capsule_generator.geocode_grid", return_value="Paris, France"
        ):
            resp = edition_client.get(
                "/api/filter_options/location_name", params={"lat": 48.8, "lng": 2.3}
            )
        assert resp.status_code == 200
        assert resp.json()["display_name"] == "Paris, France"


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
