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
from tests.conftest import initialize_photo_database
import time
from contextlib import contextmanager
from unittest import mock

import pytest

from api.routers.burst_culling import (
    _auto_keep_split,
    _culling_groups_cache,
)


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
    initialize_photo_database(conn)
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
        assert body["next_cursor"] is None
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
        assert {r["path"] for r in conn.execute("SELECT path FROM photos WHERE is_kept = 1")} == {
            "/g1a.jpg", "/g1b.jpg", "/g2a.jpg", "/g2b.jpg"}
        assert conn.execute("SELECT is_kept FROM photos WHERE path='/g1c.jpg'").fetchone()[0] == 0
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
        photos = [(f"/p{i:02d}.jpg", f"2024:06:15 10:00:{i:02d}", float(25 - i) / 2.5, None)
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


class TestCullProfiles:
    """Genre-aware profiles feed strictness + keeper budget into the split,
    with the explicit body always winning over the profile."""

    def test_profile_supplies_strictness_and_keep_min(self, edition_client):
        conn = _db()
        with mock.patch(
            "api.routers.burst_culling._resolve_cull_profile",
            return_value={"strictness": 100, "keep_min_per_group": 2},
        ):
            resp, _ = _post(edition_client, conn, {"group_by": "burst", "profile": "wedding"})
        preview = {p["group_id"]: p for p in resp.json()["preview"]}
        # strictness 100 keeps only the best, keep_min 2 floors each group to two.
        assert preview[1]["keep_paths"] == ["/g1a.jpg", "/g1b.jpg"]
        assert preview[2]["keep_paths"] == ["/g2a.jpg", "/g2b.jpg"]

    def test_explicit_body_overrides_profile(self, edition_client):
        conn = _db()
        with mock.patch(
            "api.routers.burst_culling._resolve_cull_profile",
            return_value={"strictness": 100, "keep_min_per_group": 3},
        ):
            resp, _ = _post(edition_client, conn, {
                "group_by": "burst", "profile": "wedding",
                "strictness": 0, "min_keep_per_group": 1,
            })
        preview = {p["group_id"]: p for p in resp.json()["preview"]}
        # explicit 0/1 win over the profile's 100/3: margin 5 keeps a+b, rejects c.
        assert preview[1]["keep_paths"] == ["/g1a.jpg", "/g1b.jpg"]
        assert preview[1]["reject_paths"] == ["/g1c.jpg"]

    def test_unknown_profile_falls_back_to_config_default(self, edition_client):
        conn = _db()
        resp, _ = _post(edition_client, conn, {"group_by": "burst", "profile": "does-not-exist"})
        body = resp.json()
        # An unresolved profile behaves exactly like no profile (config default 50).
        assert body["kept"] == 4 and body["rejected"] == 1


class TestTrimBrackets:
    """Redundant-bracket trimming. Opt-in, keeps the base exposure regardless of
    score, and deliberately records no comparison pairs."""

    @staticmethod
    def _bracket_db(shadow=0, highlight=0, kind='bracket'):
        conn = _db(photos=[])
        # The +2 EV frame scores highest, so a score-based split would keep the
        # wrong rung; the base must win on its exposure offset alone.
        rungs = (('/k0.jpg', -2.0, 4.0), ('/k1.jpg', 0.0, 5.0), ('/k2.jpg', 2.0, 9.0))
        for path, ev, score in rungs:
            conn.execute(
                "INSERT INTO photos (path, filename, date_taken, aggregate, aesthetic, "
                "tech_sharpness, is_blink, is_burst_lead, sequence_group_id, sequence_kind, "
                "sequence_ev_offset, shadow_clipped, highlight_clipped) "
                "VALUES (?, ?, '2025:04:15 19:59:05', ?, ?, ?, 0, 0, 1, ?, ?, ?, ?)",
                (path, path.lstrip('/'), score, score, score, kind, ev,
                 shadow if ev == 0 else 0, highlight if ev == 0 else 0),
            )
        conn.commit()
        return conn

    def test_off_by_default(self, edition_client):
        conn = self._bracket_db()
        resp, _ = _post(edition_client, conn, {"group_by": "burst"})
        assert resp.json()["groups_processed"] == 0

    def test_keeps_the_base_exposure_not_the_best_scoring_frame(self, edition_client):
        conn = self._bracket_db()
        resp, _ = _post(edition_client, conn, {"group_by": "burst", "trim_brackets": True})
        body = resp.json()
        assert body["groups_processed"] == 1
        group = body["preview"][0]
        assert group["type"] == "bracket"
        assert group["keep_paths"] == ["/k1.jpg"]
        assert set(group["reject_paths"]) == {"/k0.jpg", "/k2.jpg"}

    def test_strictness_does_not_widen_the_keep(self, edition_client):
        conn = self._bracket_db()
        resp, _ = _post(edition_client, conn, {
            "group_by": "burst", "trim_brackets": True, "strictness": 0, "min_keep_per_group": 3,
        })
        assert resp.json()["preview"][0]["keep_paths"] == ["/k1.jpg"]

    def test_a_clipped_base_still_needs_its_flanking_exposures(self, edition_client):
        conn = self._bracket_db(highlight=1)
        resp, _ = _post(edition_client, conn, {"group_by": "burst", "trim_brackets": True})
        assert resp.json()["groups_processed"] == 0

    def test_an_unmeasured_base_is_left_alone(self, edition_client):
        conn = self._bracket_db()
        conn.execute("UPDATE photos SET highlight_clipped = NULL WHERE sequence_ev_offset = 0")
        conn.commit()
        resp, _ = _post(edition_client, conn, {"group_by": "burst", "trim_brackets": True})
        assert resp.json()["groups_processed"] == 0

    def test_apply_rejects_the_extras_without_recording_comparison_pairs(self, edition_client):
        conn = self._bracket_db()
        resp, retrain = _post(edition_client, conn, {
            "group_by": "burst", "trim_brackets": True, "dry_run": False,
        })
        assert resp.status_code == 200
        rejected = {r["path"] for r in conn.execute(
            "SELECT path FROM photos WHERE is_rejected = 1")}
        assert rejected == {"/k0.jpg", "/k2.jpg"}
        # An exposure ladder is not a taste signal: no pairs, so no ranker nudge.
        pairs = conn.execute("SELECT COUNT(*) FROM comparisons").fetchone()[0]
        assert pairs == 0
        assert retrain.call_args.args[2] == 0


class TestProfileEndpoints:
    def test_list_returns_the_shipped_presets(self, edition_client):
        conn = _db()
        with mock.patch("api.routers.burst_culling.get_db", lambda: _cm(conn)):
            resp = edition_client.get("/api/culling/profiles")
        assert resp.status_code == 200
        body = resp.json()
        ids = {p["id"] for p in body["profiles"]}
        assert {"balanced", "wedding", "sports", "concert", "wildlife"} <= ids
        assert body["default"] == "balanced"


class TestAutoCullMixedSequenceGroup:
    """A group mixing sequence frames with ordinary ones must pair neither frame.

    ``_group_sequence_kind`` returns ``None`` unless EVERY frame shares a kind,
    so ``_apply_auto_cull_group``'s group-level ``keep_whole`` guard does not
    fire here — it only ever protected wholly-sequence groups. The sweep
    therefore wrote "pan tile beat pan tile" pairs, teaching the ranker how the
    set was shot, which is exactly what the three manual confirm feeds were
    fixed for. The per-frame filter in ``record_culling_decision`` is what
    closes it.
    """

    GROUP_ID = 7
    PAN_A = "/mix-pan-a.jpg"
    PAN_B = "/mix-pan-b.jpg"
    PLAIN_BEST = "/mix-plain-best.jpg"
    PLAIN_WEAK = "/mix-plain-weak.jpg"

    ROWS = [
        # path, date_taken, score, sequence_kind
        (PLAIN_BEST, "2024:07:01 09:00:00", 9.0, None),
        (PAN_A, "2024:07:01 09:00:01", 6.0, "panorama"),
        (PAN_B, "2024:07:01 09:00:02", 5.0, "panorama"),
        (PLAIN_WEAK, "2024:07:01 09:00:03", 2.0, None),
    ]

    def _conn(self):
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.row_factory = sqlite3.Row
        initialize_photo_database(conn)
        for path, dt, score, kind in self.ROWS:
            conn.execute(
                "INSERT INTO photos (path, filename, date_taken, aggregate, aesthetic, "
                "tech_sharpness, is_blink, is_burst_lead, burst_group_id, "
                "sequence_kind, sequence_group_id) "
                "VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?)",
                (path, path.lstrip('/'), dt, score, score, score, self.GROUP_ID,
                 kind, 1 if kind else None),
            )
        conn.commit()
        return conn

    def _pairs(self, conn):
        return conn.execute(
            "SELECT photo_a_path, photo_b_path FROM comparisons"
        ).fetchall()

    def test_the_group_is_genuinely_mixed(self):
        """Guard the guard: if this stops being mixed the test proves nothing."""
        from api.routers.burst_culling import _group_sequence_kind

        photos = [{"sequence_kind": kind} for _, _, _, kind in self.ROWS]
        assert _group_sequence_kind(photos) is None, (
            "the fixture is no longer a mixed group, so the group-level "
            "keep_whole guard would fire and this test would pass vacuously"
        )

    def test_no_pair_ever_references_a_sequence_frame(self, edition_client):
        conn = self._conn()
        resp, _ = _post(edition_client, conn, {"dry_run": False, "group_by": "burst"})
        assert resp.status_code == 200, resp.text

        paired = {p for row in self._pairs(conn) for p in row}
        assert self.PAN_A not in paired, (
            f"a panorama frame entered the ranker's training pairs: {paired}"
        )
        assert self.PAN_B not in paired, (
            f"a panorama frame entered the ranker's training pairs: {paired}"
        )

    def test_the_ordinary_frames_still_pair(self, edition_client):
        """Positive control: the filter must not silence the whole group."""
        conn = self._conn()
        resp, _ = _post(edition_client, conn, {"dry_run": False, "group_by": "burst"})
        assert resp.status_code == 200, resp.text

        paired = {p for row in self._pairs(conn) for p in row}
        assert paired == {self.PLAIN_BEST, self.PLAIN_WEAK}, (
            f"expected exactly the two ordinary frames to pair, got {paired}"
        )


def _many_groups(n, size=3, prefix="/m"):
    """``n`` burst groups of ``size`` photos, best first, one second apart per group."""
    rows = []
    for g in range(1, n + 1):
        for i in range(size):
            rows.append((f"{prefix}{g:03d}_{i}.jpg", f"2024:07:01 {g // 60:02d}:{g % 60:02d}:{i:02d}",
                         9.0 - 3 * i, g))
    return rows


def _pages(client, conn, body):
    """Follow ``next_cursor`` to the end; returns the list of response bodies."""
    pages, cursor = [], 0
    while True:
        resp, _ = _post(client, conn, {**body, "cursor": cursor})
        assert resp.status_code == 200, resp.text
        pages.append(resp.json())
        cursor = pages[-1]["next_cursor"]
        if cursor is None:
            return pages
        assert len(pages) < 50


class TestPaging:
    BODY = {"group_by": "burst", "strictness": 100}

    def test_auto_cull_pages_whole_groups(self, edition_client):
        conn = _db(_many_groups(100))
        pages = _pages(edition_client, conn, self.BODY)
        assert len(pages) == 2
        numbers = [row["number"] for page in pages for row in page["preview"]]
        assert numbers == list(range(1, 101))
        ids = [row["group_id"] for page in pages for row in page["preview"]]
        assert len(set(ids)) == 100
        for page in pages:
            photos = sum(len(r["keep_paths"]) + len(r["reject_paths"]) for r in page["preview"])
            assert 0 < photos <= 200
            assert all(len(r["keep_paths"]) + len(r["reject_paths"]) == 3 for r in page["preview"])
            assert page["groups_processed"] == 100 and page["kept"] == 100 and page["rejected"] == 200
        assert pages[0]["next_cursor"] == len(pages[0]["preview"])
        assert len({page["plan_digest"] for page in pages}) == 1 and pages[0]["plan_digest"]

    def test_a_group_over_the_page_limit_gets_a_page_of_its_own(self, edition_client):
        rows = _many_groups(2, size=3) + [
            (f"/big{i:03d}.jpg", f"2024:08:01 10:{i // 60:02d}:{i % 60:02d}", 9.0 - i / 100, 900)
            for i in range(230)]
        conn = _db(rows)
        pages = _pages(edition_client, conn, self.BODY)
        sizes = [[len(r["keep_paths"]) + len(r["reject_paths"]) for r in p["preview"]] for p in pages]
        assert [230] in sizes and sum(map(len, sizes)) == 3

    def test_cursor_past_the_end_is_an_empty_final_page(self, edition_client):
        conn = _db()
        resp, _ = _post(edition_client, conn, {**self.BODY, "cursor": 99})
        assert resp.status_code == 200
        assert resp.json()["preview"] == [] and resp.json()["next_cursor"] is None


class TestAtomicApply:
    def test_auto_cull_apply_digest_mismatch_writes_nothing(self, edition_client):
        conn = _db()
        resp, retrain = _post(edition_client, conn, {
            "group_by": "burst", "strictness": 50, "dry_run": False, "expected_digest": "0" * 64})
        assert resp.status_code == 412, resp.text
        assert conn.execute("SELECT COUNT(*) FROM photos WHERE is_rejected = 1").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM photos WHERE burst_reviewed = 1").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM comparisons").fetchone()[0] == 0
        retrain.assert_not_called()

    def test_a_matching_digest_applies(self, edition_client):
        conn = _db()
        body = {"group_by": "burst", "strictness": 50}
        digest = _post(edition_client, conn, body)[0].json()["plan_digest"]
        resp, _ = _post(edition_client, conn, {**body, "dry_run": False, "expected_digest": digest})
        assert resp.status_code == 200, resp.text
        assert [r["path"] for r in conn.execute("SELECT path FROM photos WHERE is_rejected = 1")] == ["/g1c.jpg"]

    def test_a_changed_plan_changes_the_digest(self, edition_client):
        conn = _db()
        body = {"group_by": "burst", "strictness": 50}
        before = _post(edition_client, conn, body)[0].json()["plan_digest"]
        conn.execute("UPDATE photos SET aggregate = 9.9, aesthetic = 9.9, tech_sharpness = 9.9 "
                     "WHERE path = '/g1c.jpg'")
        conn.commit()
        assert _post(edition_client, conn, body)[0].json()["plan_digest"] != before


class TestOverrides:
    BODY = {"group_by": "burst", "strictness": 50}

    def _plan(self, client, conn, **extra):
        resp, _ = _post(client, conn, {**self.BODY, **extra})
        return resp

    def test_auto_cull_overrides_applied(self, edition_client):
        conn = _db()
        base = self._plan(edition_client, conn).json()
        resp = self._plan(edition_client, conn, remove_paths=["/g1b.jpg"], keep_paths=["/g1c.jpg"])
        body = resp.json()
        rows = {r["group_id"]: r for r in body["preview"]}
        assert rows[1]["keep_paths"] == ["/g1a.jpg", "/g1c.jpg"]
        assert rows[1]["reject_paths"] == ["/g1b.jpg"]
        assert body["kept"] == base["kept"] and body["rejected"] == base["rejected"]
        applied, _ = _post(edition_client, conn, {
            **self.BODY, "dry_run": False, "remove_paths": ["/g1b.jpg"], "keep_paths": ["/g1c.jpg"],
            "expected_digest": body["plan_digest"]})
        assert applied.status_code == 200, applied.text
        assert [r["path"] for r in conn.execute("SELECT path FROM photos WHERE is_rejected = 1")] == ["/g1b.jpg"]

    def test_auto_cull_overrides_ignored(self, edition_client):
        conn = _db()
        base = self._plan(edition_client, conn).json()
        body = self._plan(edition_client, conn, remove_paths=["/gone.jpg"],
                          keep_paths=["/also-gone.jpg"]).json()
        assert sorted(body["ignored_overrides"]) == ["/also-gone.jpg", "/gone.jpg"]
        assert body["plan_digest"] == base["plan_digest"]
        assert base["ignored_overrides"] == []

    def test_an_override_equal_to_the_plan_is_a_no_op(self, edition_client):
        conn = _db()
        base = self._plan(edition_client, conn).json()
        body = self._plan(edition_client, conn, keep_paths=["/g1a.jpg"], remove_paths=["/g1c.jpg"]).json()
        assert body["plan_digest"] == base["plan_digest"] and body["ignored_overrides"] == []

    def test_auto_cull_overrides_keep_whole_removal_names_the_path(self, edition_client):
        conn = _db(photos=[])
        for i in range(3):
            conn.execute(
                "INSERT INTO photos (path, filename, date_taken, aggregate, aesthetic, tech_sharpness, "
                "is_blink, is_burst_lead, burst_group_id, sequence_kind, sequence_group_id) "
                "VALUES (?, ?, ?, 5, 5, 5, 0, 0, 5, 'panorama', 1)",
                (f"/pan{i}.jpg", f"pan{i}.jpg", f"2024:09:01 10:00:0{i}"))
        conn.commit()
        resp = self._plan(edition_client, conn, remove_paths=["/pan1.jpg"])
        assert resp.status_code == 400 and "/pan1.jpg" in resp.text, resp.text

    def test_auto_cull_overrides_zero_keeper_names_the_group(self, edition_client):
        conn = _db()
        resp = self._plan(edition_client, conn, remove_paths=["/g2a.jpg", "/g2b.jpg"])
        assert resp.status_code == 400, resp.text
        assert "group 2" in resp.text and "burst" in resp.text

    def test_auto_cull_overrides_both_lists_refused(self, edition_client):
        conn = _db()
        resp = self._plan(edition_client, conn, remove_paths=["/g1a.jpg"], keep_paths=["/g1a.jpg"])
        assert resp.status_code == 400 and "/g1a.jpg" in resp.text

    def test_auto_cull_overrides_change_the_digest(self, edition_client):
        conn = _db()
        base = self._plan(edition_client, conn).json()["plan_digest"]
        one = self._plan(edition_client, conn, remove_paths=["/g1b.jpg"]).json()["plan_digest"]
        two = self._plan(edition_client, conn, keep_paths=["/g1c.jpg"]).json()["plan_digest"]
        assert len({base, one, two}) == 3

    def test_override_lists_are_capped_at_1000(self, edition_client):
        conn = _db()
        resp = self._plan(edition_client, conn, remove_paths=[f"/x{i}" for i in range(1001)])
        assert resp.status_code == 422
