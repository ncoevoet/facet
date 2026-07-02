"""Tests for the one-button auto-cull endpoint (POST /api/culling/auto).

Covers the dry-run default (no writes, correct preview), the strictness
keeper-budget margins, the min_keep_per_group floor, the apply path
(rejections + reviewed flags + per-group source='culling' comparison rows +
single auto-retrain nudge), edition gating, the Highlights album (created,
idempotent re-runs), scene groups ranked by burst_score, and cache
invalidation. Auth goes through the conftest fixtures (edition_client /
regular_client / anonymous_client) — never mock.patch on auth dependencies.
"""

import sqlite3
import time
from contextlib import contextmanager
from unittest import mock

import pytest

from api.routers.burst_culling import (
    _auto_keep_split,
    _culling_groups_cache,
)

_SCHEMA = """
    CREATE TABLE photos (
        path TEXT PRIMARY KEY, filename TEXT, date_taken TEXT, aggregate REAL,
        aesthetic REAL, tech_sharpness REAL, is_blink INTEGER, is_burst_lead INTEGER,
        burst_group_id INTEGER, burst_reviewed INTEGER DEFAULT 0,
        similarity_reviewed INTEGER DEFAULT 0, eyes_open_score REAL,
        expression_score REAL, face_count INTEGER DEFAULT 0, category TEXT,
        is_rejected INTEGER DEFAULT 0
    );
    CREATE TABLE albums (
        id INTEGER PRIMARY KEY, user_id TEXT, name TEXT, description TEXT,
        cover_photo_path TEXT, is_smart INTEGER DEFAULT 0, smart_filter_json TEXT,
        share_token TEXT, created_at TEXT, updated_at TEXT
    );
    CREATE TABLE album_photos (
        id INTEGER PRIMARY KEY, album_id INTEGER, photo_path TEXT,
        position INTEGER, added_at TEXT,
        UNIQUE(album_id, photo_path)
    );
    CREATE TABLE comparisons (
        id INTEGER PRIMARY KEY, photo_a_path TEXT, photo_b_path TEXT, winner TEXT,
        category TEXT, session_id TEXT, user_id TEXT, source TEXT,
        UNIQUE(photo_a_path, photo_b_path)
    );
    CREATE TABLE stats_cache (key TEXT PRIMARY KEY, value TEXT, updated_at REAL);
"""

# Burst group 1: burst_score 9.15 / 8.30 / 4.05 (weights .4/.25/.2/.15, no blink).
# Burst group 2: burst_score 7.45 / 7.025 (0.425 apart — near-tie).
_BURST_PHOTOS = [
    ("/g1a.jpg", "2024:06:15 10:00:00", 9.0, 1),
    ("/g1b.jpg", "2024:06:15 10:00:01", 8.0, 1),
    ("/g1c.jpg", "2024:06:15 10:00:02", 3.0, 1),
    ("/g2a.jpg", "2024:06:15 12:00:00", 7.0, 2),
    ("/g2b.jpg", "2024:06:15 12:00:01", 6.5, 2),
]


def _cm(conn):
    @contextmanager
    def _ctx():
        yield conn
    return _ctx()


def _db(photos=None):
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    for path, dt, score, gid in (photos if photos is not None else _BURST_PHOTOS):
        conn.execute(
            "INSERT INTO photos (path, filename, date_taken, aggregate, aesthetic, "
            "tech_sharpness, is_blink, is_burst_lead, burst_group_id) "
            "VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?)",
            (path, path.lstrip('/'), dt, score, score, score, gid),
        )
    conn.commit()
    return conn


@contextmanager
def _patched(conn):
    with (
        mock.patch("api.routers.burst_culling.get_db", lambda: _cm(conn)),
        mock.patch("api.routers.burst_culling.trigger_auto_retrain") as retrain,
    ):
        yield retrain


def _post(client, conn, body):
    with _patched(conn) as retrain:
        resp = client.post("/api/culling/auto", json=body)
    return resp, retrain


# ---------------------------------------------------------------------------
# Keeper-budget unit tests
# ---------------------------------------------------------------------------

class TestAutoKeepSplit:
    _PHOTOS = [
        {'path': '/a.jpg', 'burst_score': 9.0},
        {'path': '/b.jpg', 'burst_score': 8.6},
        {'path': '/c.jpg', 'burst_score': 3.5},
    ]

    def test_strictness_100_keeps_only_best(self):
        keep, reject = _auto_keep_split(self._PHOTOS, 100, 1)
        assert [p['path'] for p in keep] == ['/a.jpg']
        assert [p['path'] for p in reject] == ['/b.jpg', '/c.jpg']

    def test_strictness_0_keeps_all_within_five_points(self):
        keep, reject = _auto_keep_split(self._PHOTOS, 0, 1)
        assert [p['path'] for p in keep] == ['/a.jpg', '/b.jpg']
        assert [p['path'] for p in reject] == ['/c.jpg']  # 5.5 below best

    def test_min_keep_floor_extends_by_rank(self):
        keep, reject = _auto_keep_split(self._PHOTOS, 100, 2)
        assert [p['path'] for p in keep] == ['/a.jpg', '/b.jpg']
        assert [p['path'] for p in reject] == ['/c.jpg']

    def test_min_keep_capped_at_group_size(self):
        keep, reject = _auto_keep_split(self._PHOTOS, 100, 10)
        assert len(keep) == 3
        assert reject == []


# ---------------------------------------------------------------------------
# Endpoint tests (in-memory SQLite, real conftest auth fixtures)
# ---------------------------------------------------------------------------

class TestDryRun:
    def test_dry_run_is_the_default_and_writes_nothing(self, edition_client):
        conn = _db()
        resp, retrain = _post(edition_client, conn, {"group_by": "burst", "strictness": 50})
        assert resp.status_code == 200
        body = resp.json()
        assert body["dry_run"] is True
        # margin 2.5: g1 keeps a+b rejects c; g2 keeps both.
        assert body["groups_processed"] == 2
        assert body["kept"] == 4
        assert body["rejected"] == 1
        assert body["preview_truncated"] is False
        # No writes of any kind.
        assert conn.execute("SELECT COUNT(*) FROM photos WHERE is_rejected = 1").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM photos WHERE burst_reviewed = 1").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM comparisons").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM albums").fetchone()[0] == 0
        retrain.assert_not_called()

    def test_preview_carries_the_split_per_group(self, edition_client):
        conn = _db()
        resp, _ = _post(edition_client, conn, {"group_by": "burst", "strictness": 50})
        preview = {p["group_id"]: p for p in resp.json()["preview"]}
        assert set(preview) == {1, 2}
        g1 = preview[1]
        assert g1["type"] == "burst"
        assert g1["best_path"] == "/g1a.jpg"
        assert g1["keep_paths"] == ["/g1a.jpg", "/g1b.jpg"]
        assert g1["reject_paths"] == ["/g1c.jpg"]
        g2 = preview[2]
        assert g2["keep_paths"] == ["/g2a.jpg", "/g2b.jpg"]
        assert g2["reject_paths"] == []

    def test_already_rejected_photos_are_excluded(self, edition_client):
        conn = _db()
        conn.execute("UPDATE photos SET is_rejected = 1 WHERE path = '/g1b.jpg'")
        conn.commit()
        resp, _ = _post(edition_client, conn, {"group_by": "burst", "strictness": 0})
        preview = {p["group_id"]: p for p in resp.json()["preview"]}
        g1_paths = preview[1]["keep_paths"] + preview[1]["reject_paths"]
        assert "/g1b.jpg" not in g1_paths


class TestStrictnessMargins:
    def test_strictness_100_keeps_only_the_best_per_group(self, edition_client):
        conn = _db()
        resp, _ = _post(edition_client, conn, {"group_by": "burst", "strictness": 100})
        body = resp.json()
        assert body["kept"] == 2  # one keeper per group
        assert body["rejected"] == 3
        preview = {p["group_id"]: p for p in body["preview"]}
        assert preview[1]["keep_paths"] == ["/g1a.jpg"]
        assert preview[2]["keep_paths"] == ["/g2a.jpg"]

    def test_strictness_0_keeps_everything_within_five(self, edition_client):
        conn = _db()
        resp, _ = _post(edition_client, conn, {"group_by": "burst", "strictness": 0})
        preview = {p["group_id"]: p for p in resp.json()["preview"]}
        # g1c is 5.1 below the best — outside the 5.0 margin even at strictness 0.
        assert preview[1]["keep_paths"] == ["/g1a.jpg", "/g1b.jpg"]
        assert preview[1]["reject_paths"] == ["/g1c.jpg"]
        assert preview[2]["reject_paths"] == []

    def test_min_keep_per_group_floor(self, edition_client):
        conn = _db()
        resp, _ = _post(edition_client, conn, {
            "group_by": "burst", "strictness": 100, "min_keep_per_group": 2,
        })
        preview = {p["group_id"]: p for p in resp.json()["preview"]}
        assert preview[1]["keep_paths"] == ["/g1a.jpg", "/g1b.jpg"]
        assert preview[2]["keep_paths"] == ["/g2a.jpg", "/g2b.jpg"]


class TestApply:
    def test_apply_writes_rejections_reviewed_flags_and_pairs(self, edition_client):
        conn = _db()
        resp, retrain = _post(edition_client, conn, {
            "group_by": "burst", "strictness": 50, "dry_run": False,
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["dry_run"] is False
        assert body["rejected"] == 1
        rejected = [r["path"] for r in conn.execute(
            "SELECT path FROM photos WHERE is_rejected = 1").fetchall()]
        assert rejected == ["/g1c.jpg"]
        # Every member of both processed groups is marked reviewed.
        assert conn.execute(
            "SELECT COUNT(*) FROM photos WHERE burst_reviewed = 1").fetchone()[0] == 5
        # Keeps become burst leads, rejects don't.
        assert conn.execute(
            "SELECT is_burst_lead FROM photos WHERE path = '/g1a.jpg'").fetchone()[0] == 1
        assert conn.execute(
            "SELECT is_burst_lead FROM photos WHERE path = '/g1c.jpg'").fetchone()[0] == 0
        # Comparison rows recorded per group with source='culling'.
        pairs = conn.execute("SELECT source, session_id, winner FROM comparisons").fetchall()
        assert len(pairs) == 2  # one reject x two kept round-robin picks
        assert all(p["source"] == "culling" for p in pairs)
        assert all(p["session_id"] == "cull-burst" for p in pairs)
        # One retrain nudge with the total pair count.
        retrain.assert_called_once()
        assert retrain.call_args.args[2] == 2

    def test_apply_is_idempotent_reviewed_groups_drop_out(self, edition_client):
        conn = _db()
        _post(edition_client, conn, {"group_by": "burst", "strictness": 50, "dry_run": False})
        resp, retrain = _post(edition_client, conn, {
            "group_by": "burst", "strictness": 50, "dry_run": False,
        })
        body = resp.json()
        assert body["groups_processed"] == 0
        assert body["kept"] == 0 and body["rejected"] == 0
        # trigger_auto_retrain owns the added <= 0 no-op guard.
        assert retrain.call_args.args[2] == 0


class TestEditionGating:
    def test_regular_user_gets_403(self, regular_client):
        conn = _db()
        resp, _ = _post(regular_client, conn, {"group_by": "burst"})
        assert resp.status_code == 403

    def test_anonymous_gets_401(self, anonymous_client):
        conn = _db()
        resp, _ = _post(anonymous_client, conn, {"group_by": "burst"})
        assert resp.status_code == 401


class TestHighlights:
    def test_highlights_album_created_with_top_keeps(self, edition_client):
        conn = _db()
        resp, _ = _post(edition_client, conn, {
            "group_by": "burst", "strictness": 50, "dry_run": False,
            "highlights_album": "Highlights Test",
        })
        body = resp.json()
        # Only g1's top keep (burst_score 9.15) clears highlights_min 8.0.
        assert body["highlights_added"] == 1
        album = conn.execute(
            "SELECT id, is_smart, cover_photo_path FROM albums WHERE name = 'Highlights Test'"
        ).fetchone()
        assert album is not None
        assert album["is_smart"] == 0
        assert album["cover_photo_path"] == "/g1a.jpg"
        rows = conn.execute(
            "SELECT photo_path FROM album_photos WHERE album_id = ?", (album["id"],)
        ).fetchall()
        assert [r["photo_path"] for r in rows] == ["/g1a.jpg"]

    def test_highlights_rerun_appends_nothing_twice(self, edition_client):
        conn = _db()
        _post(edition_client, conn, {
            "group_by": "burst", "strictness": 50, "dry_run": False,
            "highlights_album": "Highlights Test",
        })
        # Re-open the same groups so the second apply re-selects the same keeps.
        conn.execute("UPDATE photos SET burst_reviewed = 0, is_rejected = 0")
        conn.commit()
        resp, _ = _post(edition_client, conn, {
            "group_by": "burst", "strictness": 50, "dry_run": False,
            "highlights_album": "Highlights Test",
        })
        assert resp.json()["highlights_added"] == 0  # INSERT OR IGNORE dedup
        assert conn.execute("SELECT COUNT(*) FROM albums").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM album_photos").fetchone()[0] == 1

    def test_dry_run_counts_highlights_without_creating_album(self, edition_client):
        conn = _db()
        resp, _ = _post(edition_client, conn, {
            "group_by": "burst", "strictness": 50,
            "highlights_album": "Highlights Test",
        })
        assert resp.json()["highlights_added"] == 1
        assert conn.execute("SELECT COUNT(*) FROM albums").fetchone()[0] == 0


class TestSceneGroups:
    # One scene (frames a minute apart): /s1 has the highest aggregate (9.0)
    # but blinks (burst_score 7.65); /s2 wins on burst_score (8.30).
    _SCENE_PHOTOS = [
        ("/s1.jpg", "2024:06:15 10:00:00", 9.0),
        ("/s2.jpg", "2024:06:15 10:01:00", 8.0),
        ("/s3.jpg", "2024:06:15 10:02:00", 2.0),
    ]

    def _scene_db(self):
        conn = _db(photos=[])
        for path, dt, score in self._SCENE_PHOTOS:
            conn.execute(
                "INSERT INTO photos (path, filename, date_taken, aggregate, aesthetic, "
                "tech_sharpness, is_blink, is_burst_lead) VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
                (path, path.lstrip('/'), dt, score, score, score, 1 if path == "/s1.jpg" else 0),
            )
        conn.commit()
        return conn

    def test_scene_groups_ranked_by_burst_score_not_aggregate(self, edition_client):
        conn = self._scene_db()
        resp, _ = _post(edition_client, conn, {"group_by": "scene", "strictness": 100})
        body = resp.json()
        assert body["groups_processed"] == 1
        g = body["preview"][0]
        assert g["type"] == "scene"
        assert g["best_path"] == "/s2.jpg"  # burst_score winner, not max-aggregate
        assert g["keep_paths"] == ["/s2.jpg"]
        assert set(g["reject_paths"]) == {"/s1.jpg", "/s3.jpg"}

    def test_scene_apply_rejects_and_records_scene_pairs(self, edition_client):
        conn = self._scene_db()
        resp, _ = _post(edition_client, conn, {
            "group_by": "scene", "strictness": 100, "dry_run": False,
        })
        assert resp.status_code == 200
        rejected = {r["path"] for r in conn.execute(
            "SELECT path FROM photos WHERE is_rejected = 1").fetchall()}
        assert rejected == {"/s1.jpg", "/s3.jpg"}
        pairs = conn.execute("SELECT session_id FROM comparisons").fetchall()
        assert len(pairs) >= 1
        assert all(p["session_id"] == "cull-scene" for p in pairs)


class TestCacheInvalidation:
    def test_apply_clears_memo_and_stats_cache_rows(self, edition_client):
        conn = _db()
        conn.execute(
            "INSERT INTO stats_cache (key, value, updated_at) VALUES ('scenes_x', '[]', ?)",
            (time.time(),))
        conn.execute(
            "INSERT INTO stats_cache (key, value, updated_at) VALUES ('similarity_groups_x', '[]', ?)",
            (time.time(),))
        conn.commit()
        _culling_groups_cache['sentinel'] = (time.time(), [])
        try:
            resp, _ = _post(edition_client, conn, {
                "group_by": "burst", "strictness": 50, "dry_run": False,
            })
            assert resp.status_code == 200
            assert _culling_groups_cache == {}
            keys = {r["key"] for r in conn.execute("SELECT key FROM stats_cache").fetchall()}
            assert not any(k.startswith("scenes_") for k in keys)
            assert not any(k.startswith("similarity_groups_") for k in keys)
        finally:
            _culling_groups_cache.clear()

    def test_dry_run_leaves_caches_alone(self, edition_client):
        conn = _db()
        conn.execute(
            "INSERT INTO stats_cache (key, value, updated_at) VALUES ('similarity_groups_x', '[]', ?)",
            (time.time(),))
        conn.commit()
        resp, _ = _post(edition_client, conn, {"group_by": "burst", "strictness": 50})
        assert resp.status_code == 200
        assert conn.execute(
            "SELECT COUNT(*) FROM stats_cache WHERE key = 'similarity_groups_x'"
        ).fetchone()[0] == 1


class TestSimilarGroups:
    def test_similar_apply_marks_reviewed_and_records_pairs(self, edition_client):
        conn = _db()
        similar = [{'paths': ['/g1a.jpg', '/g1b.jpg', '/g1c.jpg'],
                    'best_path': '/g1a.jpg', 'count': 3}]
        with mock.patch(
            "api.routers.burst_culling.compute_similarity_groups", return_value=similar,
        ):
            resp, _ = _post(edition_client, conn, {
                "group_by": "similar", "strictness": 100, "dry_run": False,
            })
        assert resp.status_code == 200
        assert resp.json()["preview"][0]["keep_paths"] == ["/g1a.jpg"]
        reviewed = conn.execute(
            "SELECT COUNT(*) FROM photos WHERE similarity_reviewed = 1").fetchone()[0]
        assert reviewed == 3
        rejected = {r["path"] for r in conn.execute(
            "SELECT path FROM photos WHERE is_rejected = 1").fetchall()}
        assert rejected == {"/g1b.jpg", "/g1c.jpg"}
        pairs = conn.execute("SELECT session_id FROM comparisons").fetchall()
        assert all(p["session_id"] == "cull-similar" for p in pairs)


class TestCrossGroupOverlap:
    """F4: a photo an earlier group decides is dropped from later groups so it
    never ends up both kept and rejected, nor writes contradictory pairs."""

    # Burst group 1 keeps /a (lead) and rejects /b, /c at strictness 100. The
    # similar group also contains /a, but a stronger similar-only frame /z would
    # win it — so without the cross-group drop, /a would be rejected there while
    # staying a burst lead (contradiction). /z, /w carry no burst group.
    _PHOTOS = [
        ("/a.jpg", "2024:06:15 10:00:00", 9.0, 1),
        ("/b.jpg", "2024:06:15 10:00:01", 8.0, 1),
        ("/c.jpg", "2024:06:15 10:00:02", 2.0, 1),
        ("/z.jpg", "2024:06:15 12:00:00", 9.5, None),
        ("/w.jpg", "2024:06:15 12:00:01", 4.0, None),
    ]

    def test_overlapping_photo_is_never_both_kept_and_rejected(self, edition_client):
        conn = _db(photos=self._PHOTOS)
        similar = [{'paths': ['/a.jpg', '/z.jpg', '/w.jpg'],
                    'best_path': '/z.jpg', 'count': 3}]
        with mock.patch(
            "api.routers.burst_culling.compute_similarity_groups", return_value=similar,
        ):
            resp, _ = _post(edition_client, conn, {
                "group_by": "all", "strictness": 100, "dry_run": False,
            })
        assert resp.status_code == 200
        body = resp.json()
        assert body["groups_processed"] == 2
        assert body["kept"] == 2 and body["rejected"] == 3

        # No photo ends up flagged as both a burst lead and rejected.
        contradictory = conn.execute(
            "SELECT COUNT(*) FROM photos WHERE is_burst_lead = 1 AND is_rejected = 1"
        ).fetchone()[0]
        assert contradictory == 0
        # /a stays the kept burst lead; the similar group never re-rejected it.
        row = conn.execute(
            "SELECT is_burst_lead, is_rejected FROM photos WHERE path = '/a.jpg'"
        ).fetchone()
        assert row["is_burst_lead"] == 1 and row["is_rejected"] == 0
        assert conn.execute(
            "SELECT is_rejected FROM photos WHERE path = '/c.jpg'").fetchone()[0] == 1

        # No comparison pair contradicts: no path is both a winner and a loser.
        winners, losers = set(), set()
        for a, b, w in conn.execute(
                "SELECT photo_a_path, photo_b_path, winner FROM comparisons"):
            if w == 'a':
                winners.add(a)
                losers.add(b)
            else:
                winners.add(b)
                losers.add(a)
        assert winners.isdisjoint(losers)


class TestLargeSimilarGroup:
    """F5: a similar group larger than the paginated feed's 20-photo cap is
    culled all the way down instead of leaving its worst photos untouched."""

    def test_similar_group_over_twenty_culls_every_photo(self, edition_client):
        photos = [(f"/p{i:02d}.jpg", f"2024:06:15 10:00:{i:02d}", float(25 - i), None)
                  for i in range(25)]
        conn = _db(photos=photos)
        all_paths = [p[0] for p in photos]
        similar = [{'paths': all_paths, 'best_path': '/p00.jpg', 'count': len(all_paths)}]
        with mock.patch(
            "api.routers.burst_culling.compute_similarity_groups", return_value=similar,
        ):
            resp, _ = _post(edition_client, conn, {
                "group_by": "similar", "strictness": 100, "dry_run": False,
            })
        assert resp.status_code == 200
        body = resp.json()
        assert body["kept"] == 1
        assert body["rejected"] == 24  # every photo but the best, not just top 20
        # All 25 members are flagged reviewed (none silently skipped).
        assert conn.execute(
            "SELECT COUNT(*) FROM photos WHERE similarity_reviewed = 1").fetchone()[0] == 25
        # A photo past the old 20-cap (lowest aggregate) is now rejected + reviewed.
        row = conn.execute(
            "SELECT is_rejected, similarity_reviewed FROM photos WHERE path = '/p24.jpg'"
        ).fetchone()
        assert row["is_rejected"] == 1 and row["similarity_reviewed"] == 1
        assert conn.execute(
            "SELECT is_rejected FROM photos WHERE path = '/p00.jpg'").fetchone()[0] == 0


class TestConfigDefaults:
    def test_strictness_defaults_from_config(self, edition_client):
        conn = _db()
        with mock.patch(
            "api.routers.burst_culling._get_auto_cull_config",
            return_value={'default_strictness': 100, 'highlights_min': 8.0},
        ):
            resp, _ = _post(edition_client, conn, {"group_by": "burst"})
        preview = {p["group_id"]: p for p in resp.json()["preview"]}
        assert preview[1]["keep_paths"] == ["/g1a.jpg"]  # strictness 100 behavior


@pytest.mark.parametrize("field,value", [
    ("strictness", -1),
    ("strictness", 101),
    ("min_keep_per_group", 0),
    ("group_by", "bogus"),
])
def test_invalid_body_rejected(edition_client, field, value):
    resp = edition_client.post("/api/culling/auto", json={field: value})
    assert resp.status_code == 422
