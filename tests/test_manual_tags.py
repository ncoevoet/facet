"""Manual (user-authored) photo tags: normalizer, write routes, caps, access."""

import sqlite3
import subprocess
import sys
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from api import create_app
from api.auth import CurrentUser, get_optional_user
from api.db_helpers import (
    MANUAL_TAGS_SELECT, _add_tag_filter, build_photo_select_columns, split_photo_tags,
)
from db import DEFAULT_DB_PATH, init_database
from db.manual_tags import (
    MAX_TAGS_PER_PHOTO,
    ManualTagError,
    normalize_manual_tag,
)

PREFIX = "/mt-"
PHOTO = PREFIX + "a/one.jpg"
PHOTO_B = PREFIX + "a/two.jpg"
PHOTO_C = PREFIX + "a/three.jpg"
PHOTO_D = PREFIX + "a/four.jpg"
CAMERA = "Manual Tag Cam"
SEED_PATHS = [PHOTO, PHOTO_B, PHOTO_C, PHOTO_D]
ALL_FILTERS = {"camera": CAMERA}

PUT = "/api/photo/manual_tags"
BATCH = "/api/photos/batch_manual_tags"
_LOCKED_CFG = {"password": "", "edition_password": "x", "features": {}}


def _rows(path=None):
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        if path is None:
            return conn.execute(
                "SELECT photo_path, tag, source FROM photo_manual_tags "
                "WHERE photo_path LIKE ?", (PREFIX + "%",)
            ).fetchall()
        return [r[0] for r in conn.execute(
            "SELECT tag FROM photo_manual_tags WHERE photo_path = ? ORDER BY tag", (path,)
        )]


@pytest.fixture()
def seeded(seed_photos_prefix):
    seed_photos_prefix(PREFIX, [
        {"path": p, "filename": p.rsplit("/", 1)[-1], "camera_model": CAMERA}
        for p in SEED_PATHS
    ])
    yield
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.execute("DELETE FROM photo_manual_tags WHERE photo_path LIKE ?", (PREFIX + "%",))


def _set_ai_tags(path, tags):
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.execute("UPDATE photos SET tags = ? WHERE path = ?", (tags, path))


class TestNormalize:
    @pytest.mark.parametrize("raw,expected", [
        ("  Sunset ", "sunset"),
        ("Golden   Hour", "golden hour"),
        ("Café", "café"),
    ])
    def test_canonical_form(self, raw, expected):
        assert normalize_manual_tag(raw) == expected

    @pytest.mark.parametrize("raw", [
        "  Sunset, Golden Hour ", "", "   ", "a" * 65, "a\x1fb", "a\tb", "a\nb", 5,
    ])
    def test_rejected(self, raw):
        with pytest.raises(ManualTagError):
            normalize_manual_tag(raw)

    def test_boundary_length_accepted(self):
        assert normalize_manual_tag("a" * 64) == "a" * 64

    def test_module_is_stdlib_only(self):
        """Importing db.manual_tags must not pull in ``api`` (processing imports it)."""
        code = (
            "import sys; sys.modules['api'] = None; "
            "import db.manual_tags as m; print(m.normalize_manual_tag(' X '))"
        )
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        assert out.returncode == 0, out.stderr
        assert out.stdout.strip() == "x"


class TestSinglePhoto:
    def test_put_stores_normalized_tag(self, edition_client, seeded):
        resp = edition_client.put(PUT, json={"path": PHOTO, "tag": "  Sunset "})
        assert resp.status_code == 200
        assert resp.json()["tag"] == "sunset"
        assert resp.json()["skipped_existing"] is False
        assert _rows() == [(PHOTO, "sunset", "user")]

    def test_put_twice_is_idempotent(self, edition_client, seeded):
        for _ in range(2):
            assert edition_client.put(PUT, json={"path": PHOTO, "tag": "x"}).status_code == 200
        assert _rows(PHOTO) == ["x"]

    @pytest.mark.parametrize("tag", ["Sunset, Golden Hour", "", "a" * 65, "a\x1fb",
                                     "a\u202eb", "a\u200bb", "\u2066a", "a\ufeffb"])
    def test_invalid_tag_is_422_and_writes_nothing(self, edition_client, seeded, tag):
        assert edition_client.put(PUT, json={"path": PHOTO, "tag": tag}).status_code == 422
        assert _rows() == []

    def test_unknown_path_is_404(self, edition_client, seeded):
        resp = edition_client.put(PUT, json={"path": PREFIX + "nowhere.jpg", "tag": "x"})
        assert resp.status_code == 404
        assert _rows() == []

    def test_per_photo_cap(self, edition_client, seeded):
        for i in range(MAX_TAGS_PER_PHOTO):
            assert edition_client.put(PUT, json={"path": PHOTO, "tag": f"t{i}"}).status_code == 200
        assert edition_client.put(PUT, json={"path": PHOTO, "tag": "one-too-many"}).status_code == 422
        assert len(_rows(PHOTO)) == MAX_TAGS_PER_PHOTO
        # An existing tag at the cap is still an idempotent no-op, not a 422.
        assert edition_client.put(PUT, json={"path": PHOTO, "tag": "t0"}).status_code == 200

    def test_duplicate_of_ai_tag_is_skipped(self, edition_client, seeded):
        _set_ai_tags(PHOTO, "sunset, golden hour")
        resp = edition_client.put(PUT, json={"path": PHOTO, "tag": "Golden  Hour"})
        assert resp.status_code == 200
        assert resp.json()["skipped_existing"] is True
        assert _rows(PHOTO) == []

    def test_substring_of_ai_tag_is_not_a_duplicate(self, edition_client, seeded):
        _set_ai_tags(PHOTO, "golden hour glow")
        resp = edition_client.put(PUT, json={"path": PHOTO, "tag": "golden hour"})
        assert resp.json()["skipped_existing"] is False
        assert _rows(PHOTO) == ["golden hour"]

    def test_delete_removes_whichever_source(self, edition_client, seeded):
        with sqlite3.connect(DEFAULT_DB_PATH) as conn:
            conn.execute(
                "INSERT INTO photo_manual_tags (photo_path, tag, source) VALUES (?, 'kw', 'xmp')",
                (PHOTO,),
            )
        resp = edition_client.request("DELETE", PUT, json={"path": PHOTO, "tag": " KW "})
        assert resp.status_code == 200
        assert resp.json()["removed"] is True
        assert _rows(PHOTO) == []

    def test_delete_unknown_path_is_404(self, edition_client, seeded):
        resp = edition_client.request("DELETE", PUT, json={"path": PREFIX + "nowhere.jpg", "tag": "x"})
        assert resp.status_code == 404

    def test_write_invalidates_the_tags_cache_row(self, edition_client, seeded):
        with sqlite3.connect(DEFAULT_DB_PATH) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO stats_cache (key, value, updated_at) "
                "VALUES ('tags', '[]', strftime('%s','now'))"
            )
        assert edition_client.put(PUT, json={"path": PHOTO, "tag": "x"}).status_code == 200
        with sqlite3.connect(DEFAULT_DB_PATH) as conn:
            assert conn.execute("SELECT 1 FROM stats_cache WHERE key = 'tags'").fetchone() is None


class TestBatch:
    def test_body_needs_exactly_one_target(self, edition_client, seeded):
        both = {"photo_paths": [PHOTO], "filters": ALL_FILTERS, "tag": "x", "action": "add"}
        neither = {"tag": "x", "action": "add"}
        assert edition_client.post(BATCH, json=both).status_code == 422
        assert edition_client.post(BATCH, json=neither).status_code == 422
        assert _rows() == []

    def test_unknown_action_is_422(self, edition_client, seeded):
        body = {"photo_paths": [PHOTO], "tag": "x", "action": "toggle"}
        assert edition_client.post(BATCH, json=body).status_code == 422

    def test_invalid_tag_is_422(self, edition_client, seeded):
        body = {"photo_paths": [PHOTO], "tag": "a,b", "action": "add"}
        assert edition_client.post(BATCH, json=body).status_code == 422

    def test_add_by_paths_drops_unknown_and_counts_written(self, edition_client, seeded):
        body = {"photo_paths": [PHOTO, PHOTO_B, PREFIX + "nowhere.jpg"], "tag": "Trip", "action": "add"}
        resp = edition_client.post(BATCH, json=body)
        assert resp.status_code == 200
        assert resp.json()["count"] == 2
        assert sorted(r[0] for r in _rows()) == [PHOTO, PHOTO_B]

    def test_add_by_filters_with_exclude(self, edition_client, seeded):
        body = {"filters": ALL_FILTERS, "exclude": [PHOTO_D], "tag": "trip", "action": "add"}
        resp = edition_client.post(BATCH, json=body)
        assert resp.status_code == 200
        assert resp.json()["count"] == 3
        assert PHOTO_D not in [r[0] for r in _rows()]

    def test_second_add_counts_only_new_rows(self, edition_client, seeded):
        body = {"photo_paths": [PHOTO, PHOTO_B], "tag": "trip", "action": "add"}
        assert edition_client.post(BATCH, json=body).json()["count"] == 2
        assert edition_client.post(BATCH, json=body).json()["count"] == 0

    def test_at_cap_photo_is_excluded_not_fatal(self, edition_client, seeded):
        with sqlite3.connect(DEFAULT_DB_PATH) as conn:
            conn.executemany(
                "INSERT INTO photo_manual_tags (photo_path, tag, source) VALUES (?, ?, 'user')",
                [(PHOTO, f"t{i}") for i in range(MAX_TAGS_PER_PHOTO)],
            )
        body = {"filters": ALL_FILTERS, "tag": "newtag", "action": "add"}
        resp = edition_client.post(BATCH, json=body)
        assert resp.status_code == 200
        assert resp.json()["count"] == 3
        assert len(_rows(PHOTO)) == MAX_TAGS_PER_PHOTO
        assert "newtag" not in _rows(PHOTO)
        assert _rows(PHOTO_B) == ["newtag"]

    def test_ai_duplicates_are_skipped_by_exact_token(self, edition_client, seeded):
        _set_ai_tags(PHOTO, "sunset, golden hour")        # exact token: skipped
        _set_ai_tags(PHOTO_B, "golden hour glow")          # longer tag: NOT a duplicate
        _set_ai_tags(PHOTO_C, "golden hours, beach")       # near miss: NOT a duplicate
        body = {"filters": ALL_FILTERS, "tag": "golden hour", "action": "add"}
        resp = edition_client.post(BATCH, json=body)
        assert resp.status_code == 200
        assert resp.json()["count"] == 3
        assert _rows(PHOTO) == []
        assert _rows(PHOTO_B) == ["golden hour"]
        assert _rows(PHOTO_C) == ["golden hour"]
        assert _rows(PHOTO_D) == ["golden hour"]

    def test_ai_duplicate_check_escapes_like_wildcards(self, edition_client, seeded):
        _set_ai_tags(PHOTO, "axb, 50 x")
        body = {"photo_paths": [PHOTO], "tag": "a_b", "action": "add"}
        assert edition_client.post(BATCH, json=body).json()["count"] == 1
        body = {"photo_paths": [PHOTO], "tag": "50%", "action": "add"}
        assert edition_client.post(BATCH, json=body).json()["count"] == 1

    def test_delete(self, edition_client, seeded):
        add = {"filters": ALL_FILTERS, "tag": "trip", "action": "add"}
        edition_client.post(BATCH, json=add)
        delete = {"photo_paths": [PHOTO, PHOTO_B], "tag": "TRIP", "action": "delete"}
        resp = edition_client.post(BATCH, json=delete)
        assert resp.status_code == 200
        assert resp.json()["count"] == 2
        assert sorted(r[0] for r in _rows()) == sorted([PHOTO_C, PHOTO_D])


class TestAccess:
    ROUTES = [
        ("PUT", PUT, {"path": PHOTO, "tag": "x"}),
        ("DELETE", PUT, {"path": PHOTO, "tag": "x"}),
        ("POST", BATCH, {"photo_paths": [PHOTO], "tag": "x", "action": "add"}),
    ]

    def test_all_three_routes_are_edition_gated(self):
        from tests.test_open_install_refusal import EDITION_ROUTES
        found = set(EDITION_ROUTES)
        for method, path, _ in self.ROUTES:
            assert (method, path) in found

    @pytest.mark.parametrize("method,path,body", ROUTES)
    def test_locked_install_without_session_is_refused(self, seeded, method, path, body):
        app = create_app()
        app.dependency_overrides[get_optional_user] = lambda: None
        with (
            mock.patch("api.auth.VIEWER_CONFIG", dict(_LOCKED_CFG)),
            mock.patch("api.auth.is_multi_user_enabled", return_value=False),
        ):
            resp = TestClient(app, raise_server_exceptions=False).request(method, path, json=body)
        assert resp.status_code in (401, 403)
        assert _rows() == []

    @pytest.mark.parametrize("method,path,body", ROUTES[:1] + ROUTES[2:])
    def test_locked_install_with_edition_session_writes(self, seeded, method, path, body):
        app = create_app()
        app.dependency_overrides[get_optional_user] = lambda: CurrentUser(
            user_id="_legacy", role="user", edition_authenticated=True
        )
        with (
            mock.patch("api.auth.VIEWER_CONFIG", dict(_LOCKED_CFG)),
            mock.patch("api.auth.is_multi_user_enabled", return_value=False),
        ):
            resp = TestClient(app).request(method, path, json=body)
        assert resp.status_code == 200
        assert len(_rows()) == 1

    @pytest.mark.parametrize("method,path,body", ROUTES)
    def test_multi_user_non_edition_is_refused(self, seeded, method, path, body):
        app = create_app()
        app.dependency_overrides[get_optional_user] = lambda: CurrentUser(user_id="u1", role="user")
        with (
            mock.patch("api.auth.VIEWER_CONFIG", dict(_LOCKED_CFG)),
            mock.patch("api.auth.is_multi_user_enabled", return_value=True),
        ):
            resp = TestClient(app, raise_server_exceptions=False).request(method, path, json=body)
        assert resp.status_code == 403
        assert _rows() == []


class TestDbHelpers:
    @pytest.fixture()
    def conn(self, tmp_path):
        path = str(tmp_path / "helpers.db")
        init_database(path)
        db = sqlite3.connect(path)
        for p, ai in (("/h/ai-only.jpg", "x"), ("/h/manual-only.jpg", None), ("/h/both.jpg", "trip")):
            db.execute("INSERT INTO photos (path, filename, tags) VALUES (?, 'f', ?)", (p, ai))
            if ai:
                db.execute("INSERT INTO photo_tags (photo_path, tag) VALUES (?, ?)", (p, ai))
        db.execute("INSERT INTO photo_manual_tags (photo_path, tag, source) VALUES ('/h/manual-only.jpg', 'trip', 'user')")
        db.execute("INSERT INTO photo_manual_tags (photo_path, tag, source) VALUES ('/h/both.jpg', 'trip', 'user')")
        db.commit()
        yield db
        db.close()

    @staticmethod
    def _match(db, **kwargs):
        where, params = [], []
        _add_tag_filter(where, params, conn=db, **kwargs)
        sql = "SELECT path FROM photos" + (" WHERE " + " AND ".join(where) if where else "")
        return sorted(r[0] for r in db.execute(sql, params))

    def test_tag_filter_unions_manual_tags(self, conn):
        assert self._match(conn, tag="trip") == ["/h/both.jpg", "/h/manual-only.jpg"]
        assert self._match(conn, tag="Trip") == ["/h/both.jpg", "/h/manual-only.jpg"]

    def test_require_tags_unions_manual_tags(self, conn):
        assert self._match(conn, require_tags="trip, x") == [
            "/h/ai-only.jpg", "/h/both.jpg", "/h/manual-only.jpg"]

    def test_exclude_tags_excludes_a_manual_only_photo(self, conn):
        assert self._match(conn, exclude_tags="trip") == ["/h/ai-only.jpg"]

    def test_include_manual_false_is_ai_only_for_every_clause(self, conn):
        assert self._match(conn, tag="trip", include_manual=False) == ["/h/both.jpg"]
        assert self._match(conn, require_tags="trip", include_manual=False) == ["/h/both.jpg"]
        assert self._match(conn, exclude_tags="trip", include_manual=False) == [
            "/h/ai-only.jpg", "/h/manual-only.jpg"]

    def test_select_and_split(self, conn):
        assert MANUAL_TAGS_SELECT in build_photo_select_columns(conn)
        assert MANUAL_TAGS_SELECT not in build_photo_select_columns(conn, include_manual_tags=False)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"SELECT path, tags, {MANUAL_TAGS_SELECT} FROM photos WHERE path = '/h/manual-only.jpg'"
        ).fetchall()
        photo = split_photo_tags(rows, 3)[0]
        assert photo["manual_tags"] == ["trip"]
        assert "manual_tags_raw" not in photo
        hidden = split_photo_tags(rows, 3, include_manual_tags=False)[0]
        assert hidden["manual_tags"] == []
        assert "manual_tags_raw" not in hidden

    def test_split_never_truncates_manual_tags_and_defaults_to_list(self):
        row = {"tags": "a, b, c, d", "manual_tags_raw": "\x1f".join(f"m{i}" for i in range(4))}
        photo = split_photo_tags([row, {"tags": None}], 3)
        assert photo[0]["tags_list"] == ["a", "b", "c"]
        assert photo[0]["manual_tags"] == ["m0", "m1", "m2", "m3"]
        assert photo[1]["manual_tags"] == []
