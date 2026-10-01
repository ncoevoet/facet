"""Manual tags on the read side (C2) and hidden from share links (C-SH1)."""

import json
import sqlite3
import uuid
from unittest import mock

import numpy as np
import pytest

from db import DEFAULT_DB_PATH

PREFIX = "/mtr-"
MANUAL_ONLY = PREFIX + "a/manual_only.jpg"
AI_ONLY = PREFIX + "a/ai_only.jpg"
BOTH = PREFIX + "a/both.jpg"
PLAIN = PREFIX + "a/plain.jpg"
TAG = "trip-norway-2026"
CAMERA = "Readers Cam"
ALBUM_ID = 987654
SHARE_TOKEN = "readers-share-token"


def _db():
    return sqlite3.connect(DEFAULT_DB_PATH)


def _photo(path, tags=None):
    return {"path": path, "filename": path.rsplit("/", 1)[-1], "camera_model": CAMERA,
            "aggregate": 5.0, "tags": tags}


@pytest.fixture()
def seeded(seed_photos_prefix):
    seed_photos_prefix(PREFIX, [
        _photo(MANUAL_ONLY),
        _photo(AI_ONLY, "alpine glow"),
        _photo(BOTH, f"{TAG}, alpine glow"),
        _photo(PLAIN),
    ])
    with _db() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO photo_manual_tags (photo_path, tag, source) VALUES (?, ?, 'user')",
            [(MANUAL_ONLY, TAG), (BOTH, TAG), (PLAIN, "other note")],
        )
        conn.execute("DELETE FROM stats_cache WHERE key = 'tags'")
    yield
    with _db() as conn:
        conn.execute("DELETE FROM photo_manual_tags WHERE photo_path LIKE ?", (PREFIX + "%",))
        conn.execute("DELETE FROM photo_tags WHERE photo_path LIKE ?", (PREFIX + "%",))
        conn.execute("DELETE FROM stats_cache WHERE key = 'tags'")


def _listed(client, **params):
    resp = client.get("/api/photos", params={"camera": CAMERA, "per_page": 50, **params})
    assert resp.status_code == 200, resp.text
    return {p["path"] for p in resp.json()["photos"]}


class TestGalleryTextSearch:
    def test_fts_branch_matches_manual_tag(self, edition_client, seeded):
        found = _listed(edition_client, search=TAG)
        assert found == {MANUAL_ONLY, BOTH}

    def test_like_fallback_matches_manual_tag(self, edition_client, seeded):
        with mock.patch("db.fts.has_fts_table", return_value=False):
            found = _listed(edition_client, search=TAG)
        assert found == {MANUAL_ONLY, BOTH}

    def test_photo_with_ai_and_manual_tag_listed_once(self, edition_client, seeded):
        resp = edition_client.get("/api/photos", params={"camera": CAMERA, "search": TAG})
        paths = [p["path"] for p in resp.json()["photos"]]
        assert sorted(paths) == sorted({MANUAL_ONLY, BOTH})


class TestGalleryTagFilter:
    def test_tag_filter_matches_manual_tag(self, edition_client, seeded):
        assert _listed(edition_client, tag=TAG) == {MANUAL_ONLY, BOTH}

    def test_exclude_tags_drops_manual_only_photo(self, edition_client, seeded):
        assert _listed(edition_client, exclude_tags=TAG) == {AI_ONLY, PLAIN}


class TestApiSearchCompanion:
    def _search(self, client, **params):
        with (
            mock.patch("api.routers.search._has_fts", mock.AsyncMock(return_value=False)),
            mock.patch("api.routers.search._encode_text", return_value=np.zeros(4, dtype=np.float32)),
            mock.patch("api.routers.search._check_vec_available", mock.AsyncMock(return_value=False)),
            mock.patch("api.routers.search._search_numpy", mock.AsyncMock(return_value={})),
            mock.patch("api.routers.search.search_threshold_default", return_value=0.0),
        ):
            resp = client.get("/api/search", params={"q": TAG, "limit": 50, **params})
        assert resp.status_code == 200, resp.text
        return resp.json()

    def test_manual_tag_hit_without_fts_available(self, edition_client, seeded):
        body = self._search(edition_client)
        hits = {p["path"]: p["similarity"] for p in body["photos"] if p["path"].startswith(PREFIX)}
        assert set(hits) == {MANUAL_ONLY, BOTH}
        assert all(score > 0 for score in hits.values())

    def test_text_scope_skips_companion(self, edition_client, seeded):
        body = self._search(edition_client, scope="text")
        assert [p for p in body["photos"] if p["path"].startswith(PREFIX)] == []


class TestFilterOptionsTags:
    def _tags(self, client):
        resp = client.get("/api/filter_options/tags")
        assert resp.status_code == 200, resp.text
        return dict(tuple(t) if not isinstance(t, dict) else (t["value"], t["count"])
                    for t in resp.json()["tags"])

    def _add_ai_rows(self):
        with _db() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO photo_tags (photo_path, tag) VALUES (?, ?)",
                [(AI_ONLY, "alpine glow"), (BOTH, TAG), (BOTH, "alpine glow")],
            )

    def test_photo_tags_branch_counts_distinct_photo_per_tag(self, edition_client, seeded):
        self._add_ai_rows()
        with mock.patch("api.routers.filter_options.is_photo_tags_available", return_value=True):
            counts = self._tags(edition_client)
        # BOTH carries TAG as AI and manual: one photo, counted once.
        assert counts[TAG] == 2
        assert counts["other note"] == 1

    def test_split_fallback_includes_manual_tags(self, edition_client, seeded):
        with mock.patch("api.routers.filter_options.is_photo_tags_available", return_value=False):
            counts = self._tags(edition_client)
        assert counts[TAG] == 2
        assert counts["other note"] == 1

    def test_cached_branch_comes_from_union_build(self, edition_client, seeded):
        from db import refresh_stats_cache
        self._add_ai_rows()
        refresh_stats_cache(str(DEFAULT_DB_PATH), verbose=False)
        with (
            mock.patch("api.routers.filter_options.is_multi_user_enabled", return_value=False),
            mock.patch("api.routers.filter_options._vis_where", return_value=("", [])),
        ):
            counts = self._tags(edition_client)
        assert counts[TAG] == 2
        assert counts["other note"] == 1

    def test_cache_build_with_manual_only_library(self, seeded):
        from db import refresh_stats_cache
        assert self._photo_tags_rows() == 0
        refresh_stats_cache(str(DEFAULT_DB_PATH), verbose=False)
        with _db() as conn:
            row = conn.execute("SELECT value FROM stats_cache WHERE key = 'tags'").fetchone()
        assert row is not None
        assert dict((t[0], t[1]) for t in json.loads(row[0]))[TAG] == 2

    @staticmethod
    def _photo_tags_rows():
        with _db() as conn:
            return conn.execute("SELECT COUNT(*) FROM photo_tags").fetchone()[0]


class TestStatsTotalTags:
    def _total(self, client):
        resp = client.get("/api/stats/overview", params={"category": "x-" + uuid.uuid4().hex})
        assert resp.status_code == 200, resp.text
        return resp.json()["total_tags"]

    def test_total_tags_counts_distinct_union(self, edition_client, seeded):
        with _db() as conn:
            conn.execute("INSERT OR IGNORE INTO photo_tags (photo_path, tag) VALUES (?, ?)", (BOTH, TAG))
            expected = conn.execute(
                "SELECT COUNT(*) FROM (SELECT tag FROM photo_tags UNION SELECT tag FROM photo_manual_tags)"
            ).fetchone()[0]
        assert self._total(edition_client) == expected

    def test_total_tags_includes_manual_when_photo_tags_unavailable(self, edition_client, seeded):
        with (
            mock.patch("api.db_helpers.is_photo_tags_available", return_value=False),
            _db() as conn,
        ):
            expected = conn.execute("SELECT COUNT(DISTINCT tag) FROM photo_manual_tags").fetchone()[0]
            assert self._total(edition_client) == expected


class TestShareLinksHideManualTags:
    @pytest.fixture()
    def shared_albums(self, seeded):
        with _db() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO albums (id, name, is_smart, share_token) VALUES (?, 'readers', 0, ?)",
                (ALBUM_ID, SHARE_TOKEN),
            )
            conn.executemany(
                "INSERT OR REPLACE INTO album_photos (album_id, photo_path, position) VALUES (?, ?, ?)",
                [(ALBUM_ID, p, i) for i, p in enumerate((MANUAL_ONLY, AI_ONLY, BOTH, PLAIN))],
            )
            conn.execute(
                "INSERT OR REPLACE INTO albums (id, name, is_smart, share_token, smart_filter_json) "
                "VALUES (?, 'readers smart', 1, ?, ?)",
                (ALBUM_ID + 1, SHARE_TOKEN, json.dumps({"tag": TAG, "camera": CAMERA})),
            )
        yield
        with _db() as conn:
            conn.execute("DELETE FROM album_photos WHERE album_id = ?", (ALBUM_ID,))
            conn.execute("DELETE FROM albums WHERE id IN (?, ?)", (ALBUM_ID, ALBUM_ID + 1))

    def _shared(self, client, album_id=ALBUM_ID, **params):
        resp = client.get(f"/api/shared/album/{album_id}", params={"token": SHARE_TOKEN, **params})
        assert resp.status_code == 200, resp.text
        return resp

    def test_edition_user_sees_manual_tags_on_gallery_list(self, edition_client, seeded):
        resp = edition_client.get("/api/photos", params={"camera": CAMERA})
        by_path = {p["path"]: p for p in resp.json()["photos"]}
        assert by_path[MANUAL_ONLY]["manual_tags"] == [TAG]

    def test_shared_album_list_hides_manual_tags(self, edition_client, shared_albums):
        resp = self._shared(edition_client)
        photos = {p["path"]: p for p in resp.json()["photos"]}
        assert photos[MANUAL_ONLY]["manual_tags"] == []
        assert photos[PLAIN]["manual_tags"] == []
        assert "other note" not in resp.text
        # The only occurrence left is BOTH's own AI tag, never MANUAL_ONLY's.
        assert TAG not in json.dumps(photos[MANUAL_ONLY])

    def test_shared_album_filter_options_stay_ai_only(self, edition_client, shared_albums):
        body = self._shared(edition_client).json()
        values = {t["value"] for t in body["filter_options"]["tags"]}
        assert "other note" not in values
        with _db() as conn:
            conn.execute("DELETE FROM photo_tags WHERE photo_path LIKE ?", (PREFIX + "%",))
            conn.execute("INSERT INTO photo_tags (photo_path, tag) VALUES (?, 'alpine glow')", (AI_ONLY,))
        body = self._shared(edition_client).json()
        values = {t["value"] for t in body["filter_options"]["tags"]}
        assert values == {"alpine glow"}
        assert TAG not in json.dumps(body["filter_options"])

    def test_viewer_tag_filter_on_share_request_is_ai_only(self, edition_client, shared_albums):
        resp = self._shared(edition_client, tag=TAG)
        paths = {p["path"] for p in resp.json()["photos"]}
        assert MANUAL_ONLY not in paths
        assert paths <= {BOTH}  # BOTH only if the AI column carries the tag (it does)
        assert paths == {BOTH}

    def test_shared_smart_album_keeps_owner_saved_manual_filter(self, edition_client, shared_albums):
        resp = self._shared(edition_client, album_id=ALBUM_ID + 1)
        photos = {p["path"]: p for p in resp.json()["photos"]}
        assert {MANUAL_ONLY, BOTH} <= set(photos)
        assert photos[MANUAL_ONLY]["manual_tags"] == []

    def test_shared_photo_detail_hides_manual_tags(self, edition_client, seeded):
        owner = edition_client.get("/api/photo", params={"path": MANUAL_ONLY}).json()
        assert owner["manual_tags"] == [TAG]
        shared = edition_client.get("/api/photo", params={"path": MANUAL_ONLY, "token": SHARE_TOKEN})
        assert shared.status_code == 200
        assert shared.json()["manual_tags"] == []
        assert TAG not in shared.text
