"""Tests for the one-way Immich push (sync/immich.py) — HTTP transport fully mocked."""

import json
import sqlite3
import threading
import urllib.error

import pytest

from db.schema import init_database
from sync import immich as sync_immich
from sync.immich import (
    RESULT_FAILED, RESULT_PUSHED, RESULT_SKIPPED, RESULT_UNKNOWN,
    RESULT_UNMATCHED, ImmichClient, _effective_rating, load_pending_paths,
    map_facet_path, map_immich_path, push_photo_update, push_photo_updates,
    record_pending_path, record_pending_paths, sync_to_immich,
)


class FakeTransport:
    def __init__(self, assets_by_path=None, albums=None, bulk_assets=None, album_assets=None):
        self.assets_by_path = assets_by_path or {}
        # What the bulk-listing pass returns; None => same as assets_by_path.
        self.bulk_assets = bulk_assets
        self.albums = albums or []
        # Current member ids per album id, as the GET /api/albums/:id read
        # returns them; an album missing here reads as empty.
        self.album_assets = album_assets
        self.requests = []

    def __call__(self, method, path, payload=None):
        self.requests.append((method, path, payload))
        if method == "POST" and path == "/api/search/metadata":
            if "albumIds" in payload:
                members = self.album_assets.get(payload["albumIds"][0]) if self.album_assets else []
                items = [{"id": aid} for aid in members or []]
                return {"assets": {"items": items, "nextPage": None}}
            if "originalPath" in payload:
                asset_id = self.assets_by_path.get(payload["originalPath"])
                items = [{"id": asset_id, "originalPath": payload["originalPath"]}] if asset_id else []
                return {"assets": {"items": items, "nextPage": None}}
            source = self.bulk_assets if self.bulk_assets is not None else self.assets_by_path
            items = [{"id": aid, "originalPath": p} for p, aid in source.items()]
            return {"assets": {"items": items, "nextPage": None}}
        if method == "GET" and path.startswith("/api/assets/"):
            asset_id = path.rsplit("/", 1)[-1]
            return next(({"id": aid, "originalPath": p}
                         for p, aid in self.assets_by_path.items() if aid == asset_id), {})
        if method == "PUT" and path == "/api/assets":
            return None
        if method == "GET" and path == "/api/albums":
            return self.albums
        if method == "POST" and path == "/api/albums":
            return {"id": "album-new"}
        if method == "GET" and path.startswith("/api/albums/"):
            album_id = path[len("/api/albums/"):]
            members = self.album_assets.get(album_id) if self.album_assets is not None else []
            return {"id": album_id, "assets": [{"id": aid} for aid in members or []]}
        if method == "DELETE" and path.startswith("/api/albums/"):
            return []
        if method == "PUT" and path.startswith("/api/albums/"):
            return []
        raise AssertionError(f"Unexpected request: {method} {path}")

    def writes(self):
        return [r for r in self.requests
                if r[0] == "PUT" or (r[0] == "POST" and r[1] == "/api/albums")]

    def asset_updates(self):
        return [payload for method, path, payload in self.requests
                if method == "PUT" and path == "/api/assets"]

    def searched_paths(self):
        return [payload["originalPath"] for method, path, payload in self.requests
                if path == "/api/search/metadata" and "originalPath" in payload]

    def bulk_listings(self):
        return sum(1 for method, path, payload in self.requests
                   if path == "/api/search/metadata" and "originalPath" not in payload)


def make_db(tmp_path, rows, user_rows=()):
    db_path = str(tmp_path / "immich.db")
    init_database(db_path)
    conn = sqlite3.connect(db_path)
    conn.executemany(
        "INSERT INTO photos (path, filename, star_rating, is_favorite, is_rejected) "
        "VALUES (?, ?, ?, ?, ?)",
        [(p, p.rsplit('/', 1)[-1], s, f, r) for p, s, f, r in rows],
    )
    if user_rows:
        conn.executemany(
            "INSERT INTO user_preferences (user_id, photo_path, star_rating, "
            "is_favorite, is_rejected) VALUES (?, ?, ?, ?, ?)",
            user_rows,
        )
    conn.commit()
    conn.close()
    return db_path


def make_config(**immich_overrides):
    immich = {
        "url": "http://immich.local:2283",
        "api_key": "test-key",
        "path_map": [],
        "push": {"ratings": True, "favorites": True, "top_picks_album": ""},
        "timeout_seconds": 5,
    }
    immich.update(immich_overrides)
    return {"immich": immich}


@pytest.fixture()
def transport(monkeypatch):
    fake = FakeTransport()
    monkeypatch.setattr(ImmichClient, "_request", fake)
    return fake


class TestPathMapping:
    def test_multiple_prefixes_and_unmapped(self, tmp_path, transport):
        db_path = make_db(tmp_path, [
            ('/photos/a.jpg', 5, 0, 0),
            ('/mnt/other/b.jpg', 4, 0, 0),
            ('/elsewhere/c.jpg', 3, 0, 0),
        ])
        transport.assets_by_path = {
            '/usr/src/app/upload/a.jpg': 'id-a',
            '/data/b.jpg': 'id-b',
        }
        config = make_config(path_map=[
            {"facet_prefix": "/photos/", "immich_prefix": "/usr/src/app/upload/"},
            {"facet_prefix": "/mnt/other/", "immich_prefix": "/data/"},
        ])
        summary = sync_to_immich(db_path, config)
        assert summary["matched"] == 2
        assert summary["unmatched"] == 1
        # One bulk pass resolves both mapped paths; no per-path fallback needed.
        assert transport.bulk_listings() == 1
        assert transport.searched_paths() == []

    def test_empty_or_placeholder_map_is_identity(self):
        assert map_facet_path('/x/y.jpg', []) == '/x/y.jpg'
        assert map_facet_path('/x/y.jpg', [{"facet_prefix": "", "immich_prefix": ""}]) == '/x/y.jpg'

    def test_search_miss_counts_unmatched(self, tmp_path, transport):
        db_path = make_db(tmp_path, [('/photos/gone.jpg', 5, 0, 0)])
        summary = sync_to_immich(db_path, make_config())
        assert summary == {"matched": 0, "unmatched": 1, "updated": 0,
                           "skipped_unrated": 0, "albums_created": 0,
                           "webhook_pending": 0, "identity_conflicts": 0,
                           "album_added": 0, "album_removed": 0,
                           "album_remove_failed": 0}


class TestPayloadGrouping:
    def test_groups_by_identical_rating_and_favorite(self, tmp_path, transport):
        db_path = make_db(tmp_path, [
            ('/p/a.jpg', 5, 1, 0),
            ('/p/b.jpg', 5, 1, 0),
            ('/p/c.jpg', 3, 0, 0),
        ])
        transport.assets_by_path = {'/p/a.jpg': 'id-a', '/p/b.jpg': 'id-b', '/p/c.jpg': 'id-c'}
        summary = sync_to_immich(db_path, make_config())
        updates = transport.asset_updates()
        assert len(updates) == 2
        by_key = {(u.get("rating"), u.get("isFavorite")): sorted(u["ids"]) for u in updates}
        assert by_key[(5, True)] == ['id-a', 'id-b']
        assert by_key[(3, False)] == ['id-c']
        assert summary["updated"] == 3


class TestRatingPolicy:
    def test_zero_never_pushed_and_favorite_only_has_no_rating_key(self, tmp_path, transport):
        db_path = make_db(tmp_path, [
            ('/p/fav.jpg', 0, 1, 0),
            ('/p/plain.jpg', 0, 0, 0),
        ])
        transport.assets_by_path = {'/p/fav.jpg': 'id-fav'}
        summary = sync_to_immich(db_path, make_config())
        updates = transport.asset_updates()
        assert len(updates) == 1
        assert "rating" not in updates[0]
        assert updates[0]["isFavorite"] is True
        assert summary["matched"] == 1

    def test_rejected_photo_is_skipped_never_minus_one(self, tmp_path, transport):
        db_path = make_db(tmp_path, [('/p/rej.jpg', 0, 0, 1)])
        summary = sync_to_immich(db_path, make_config())
        # Pure-rejected rows are excluded at fetch — no dead iterations, no requests.
        assert transport.requests == []
        assert summary["skipped_unrated"] == 0

    def test_effective_rating_bounds(self):
        assert _effective_rating(-1) is None
        assert _effective_rating(0) is None
        assert _effective_rating(6) is None
        assert _effective_rating(None) is None
        assert _effective_rating(1) == 1
        assert _effective_rating(5) == 5


class TestDryRun:
    def test_dry_run_resolves_but_never_writes(self, tmp_path, transport):
        db_path = make_db(tmp_path, [
            ('/p/a.jpg', 5, 0, 0),
            ('/p/b.jpg', 4, 1, 0),
        ])
        transport.assets_by_path = {'/p/a.jpg': 'id-a', '/p/b.jpg': 'id-b'}
        config = make_config(push={"ratings": True, "favorites": True,
                                   "top_picks_album": "Facet Top Picks"})
        summary = sync_to_immich(db_path, config, dry_run=True)
        assert transport.writes() == []
        # dry-run still resolves via the read-only bulk pass, just never writes.
        assert transport.bulk_listings() == 1
        assert summary["matched"] == 2
        assert summary["updated"] == 2
        assert summary["albums_created"] == 0


class TestUserPreferencesSource:
    def test_user_overlay_replaces_global_columns(self, tmp_path, transport):
        db_path = make_db(
            tmp_path,
            [('/p/a.jpg', 1, 0, 0), ('/p/b.jpg', 4, 0, 0)],
            user_rows=[('alice', '/p/a.jpg', 5, 1, 0)],
        )
        transport.assets_by_path = {'/p/a.jpg': 'id-a', '/p/b.jpg': 'id-b'}
        config = make_config()
        config["users"] = {"alice": {"role": "regular"}}
        summary = sync_to_immich(db_path, config, user_id="alice")
        updates = transport.asset_updates()
        assert len(updates) == 1
        assert updates[0]["ids"] == ['id-a']
        assert updates[0]["rating"] == 5
        assert updates[0]["isFavorite"] is True
        assert summary["matched"] == 1

    def test_without_user_id_reads_global_columns(self, tmp_path, transport):
        db_path = make_db(
            tmp_path,
            [('/p/a.jpg', 1, 0, 0)],
            user_rows=[('alice', '/p/a.jpg', 5, 1, 0)],
        )
        transport.assets_by_path = {'/p/a.jpg': 'id-a'}
        summary = sync_to_immich(db_path, make_config())
        updates = transport.asset_updates()
        assert updates[0]["rating"] == 1
        assert summary["matched"] == 1


class TestTopPicksAlbum:
    def test_creates_album_above_min_rating(self, tmp_path, transport):
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0), ('/p/b.jpg', 3, 0, 0)])
        transport.assets_by_path = {'/p/a.jpg': 'id-a', '/p/b.jpg': 'id-b'}
        config = make_config(push={"ratings": True, "favorites": True,
                                   "top_picks_album": "Facet Top Picks",
                                   "top_picks_min_rating": 4})
        summary = sync_to_immich(db_path, config)
        assert summary["albums_created"] == 1
        creates = [p for m, path, p in transport.requests
                   if m == "POST" and path == "/api/albums"]
        assert creates == [{"albumName": "Facet Top Picks", "assetIds": ['id-a']}]

    def test_reuses_existing_album(self, tmp_path, transport):
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0)])
        transport.assets_by_path = {'/p/a.jpg': 'id-a'}
        transport.albums = [{"albumName": "Facet Top Picks", "id": "album-old"}]
        config = make_config(push={"ratings": True, "favorites": True,
                                   "top_picks_album": "Facet Top Picks"})
        summary = sync_to_immich(db_path, config)
        assert summary["albums_created"] == 0
        adds = [(path, p) for m, path, p in transport.requests
                if m == "PUT" and path.startswith("/api/albums/")]
        assert adds == [("/api/albums/album-old/assets", {"ids": ['id-a']})]


class TestClientValidation:
    def test_rejects_bad_scheme_and_missing_url(self):
        with pytest.raises(ValueError):
            ImmichClient("ftp://immich.local", "key")
        with pytest.raises(ValueError):
            ImmichClient("", "key")

    def test_strips_trailing_slash(self):
        assert ImmichClient("http://immich.local:2283/", "key").base_url == "http://immich.local:2283"

    def test_missing_api_key_raises(self, tmp_path):
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0)])
        config = make_config(api_key="")
        with pytest.raises(ValueError):
            sync_to_immich(db_path, config)


class TestBulkResolution:
    def test_bulk_pass_resolves_and_misses_fall_back(self, tmp_path, transport):
        db_path = make_db(tmp_path, [
            ('/p/a.jpg', 5, 0, 0),
            ('/p/b.jpg', 4, 0, 0),
            ('/p/c.jpg', 3, 0, 0),
        ])
        transport.assets_by_path = {'/p/a.jpg': 'id-a', '/p/b.jpg': 'id-b', '/p/c.jpg': 'id-c'}
        # The bulk listing only knows a and b; c is resolvable per-path only.
        transport.bulk_assets = {'/p/a.jpg': 'id-a', '/p/b.jpg': 'id-b'}
        summary = sync_to_immich(db_path, make_config())
        assert summary["matched"] == 3
        assert summary["unmatched"] == 0
        assert transport.bulk_listings() == 1
        assert transport.searched_paths() == ['/p/c.jpg']


class TestUpdateBatching:
    def test_over_500_assets_split_into_two_puts(self, tmp_path, transport):
        rows = [(f'/p/{i}.jpg', 5, 0, 0) for i in range(501)]
        db_path = make_db(tmp_path, rows)
        transport.assets_by_path = {f'/p/{i}.jpg': f'id-{i}' for i in range(501)}
        summary = sync_to_immich(db_path, make_config())
        updates = transport.asset_updates()
        assert len(updates) == 2
        assert len(updates[0]["ids"]) == 500
        assert len(updates[1]["ids"]) == 1
        assert summary["updated"] == 501


class TestPushConfig:
    def test_ratings_false_skips_rating_writes(self, tmp_path, transport):
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 1, 0)])
        transport.assets_by_path = {'/p/a.jpg': 'id-a'}
        config = make_config(push={"ratings": False, "favorites": True, "top_picks_album": ""})
        sync_to_immich(db_path, config)
        updates = transport.asset_updates()
        assert len(updates) == 1
        assert "rating" not in updates[0]
        assert updates[0]["isFavorite"] is True

    def test_favorites_false_skips_favorite_writes(self, tmp_path, transport):
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 1, 0)])
        transport.assets_by_path = {'/p/a.jpg': 'id-a'}
        config = make_config(push={"ratings": True, "favorites": False, "top_picks_album": ""})
        sync_to_immich(db_path, config)
        updates = transport.asset_updates()
        assert len(updates) == 1
        assert updates[0]["rating"] == 5
        assert "isFavorite" not in updates[0]


class TestClearingPreviouslySyncedState:
    """A rating/favorite that gets reset to 0/false must still reach Immich.

    Regression: _fetch_rating_rows only ever selected currently-active rows,
    so a photo pushed with rating=5 and then un-rated in Facet fell out of the
    WHERE clause entirely — Immich kept the stale rating=5 forever.
    """

    def test_reset_rating_and_favorite_are_pushed_as_a_clear(self, tmp_path, transport):
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 1, 0)])
        transport.assets_by_path = {'/p/a.jpg': 'id-a'}

        # First sync: establishes id-a as having an active rating + favorite.
        summary1 = sync_to_immich(db_path, make_config())
        assert summary1["matched"] == 1
        updates1 = transport.asset_updates()
        assert updates1[-1]["rating"] == 5
        assert updates1[-1]["isFavorite"] is True

        # User clears the star rating and un-favorites.
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE photos SET star_rating = 0, is_favorite = 0 WHERE path = ?",
                    ('/p/a.jpg',))
        conn.commit()
        conn.close()

        summary2 = sync_to_immich(db_path, make_config())
        updates2 = transport.asset_updates()
        # The clear must actually reach Immich, not be silently dropped — and
        # as null, not 0, which Immich v3 rejects (aborting the whole sync).
        assert summary2["matched"] == 1
        assert "rating" in updates2[-1]
        assert updates2[-1]["rating"] is None
        assert updates2[-1]["isFavorite"] is False

        # Once the clear is confirmed pushed, the row drops out of tracking
        # entirely (no longer active, no longer in synced state) so it falls
        # outside the fetch WHERE clause: a third sync must not re-touch it.
        requests_before = len(transport.requests)
        summary3 = sync_to_immich(db_path, make_config())
        assert summary3["matched"] == 0
        assert summary3["skipped_unrated"] == 0
        assert len(transport.requests) == requests_before

    def test_never_synced_zero_rating_still_never_pushed(self, tmp_path, transport):
        # A photo with no history in synced state and no active rating/favorite
        # must keep costing zero requests, exactly as before this fix (excluded
        # at the fetch WHERE, same as a pure-rejected row).
        db_path = make_db(tmp_path, [('/p/untouched.jpg', 0, 0, 0)])
        summary = sync_to_immich(db_path, make_config())
        assert transport.requests == []
        assert summary["skipped_unrated"] == 0

    def test_dry_run_does_not_persist_synced_state(self, tmp_path, transport):
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0)])
        transport.assets_by_path = {'/p/a.jpg': 'id-a'}
        # A dry run must not confirm state that was never actually written.
        sync_to_immich(db_path, make_config(), dry_run=True)

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT value FROM stats_cache WHERE key = 'immich_synced_paths:global'"
        ).fetchone()
        conn.close()
        assert row is None


class TestPartialProgress:
    def test_network_error_carries_partial_summary(self, tmp_path, monkeypatch):
        import urllib.error

        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0), ('/p/b.jpg', 4, 0, 0)])

        def failing(_self, method, path, payload=None):
            if method == "POST" and path == "/api/search/metadata" and "originalPath" not in payload:
                return {"assets": {"items": [
                    {"id": "id-a", "originalPath": "/p/a.jpg"},
                    {"id": "id-b", "originalPath": "/p/b.jpg"},
                ], "nextPage": None}}
            if method == "PUT" and path == "/api/assets":
                raise urllib.error.HTTPError(path, 500, "boom", {}, None)
            return None

        monkeypatch.setattr(ImmichClient, "_request", failing)
        with pytest.raises(urllib.error.URLError) as excinfo:
            sync_to_immich(db_path, make_config())
        assert excinfo.value.partial_summary["matched"] == 2
        assert excinfo.value.partial_summary["updated"] == 0


def _set_rejected(db_path, path, rejected=1):
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE photos SET is_rejected = ? WHERE path = ?", (rejected, path))
    conn.commit()
    conn.close()


def _rejecting_config(**overrides):
    push = {"ratings": True, "favorites": True, "rejected": True, "top_picks_album": ""}
    push.update(overrides)
    return make_config(push=push)


class TestPushRejected:
    """``immich.push.rejected`` — Immich v3's rating -1 means "rejected"."""

    def test_off_by_default_a_rejected_photo_pushes_its_stars(self, tmp_path, transport):
        db_path = make_db(tmp_path, [('/p/rej.jpg', 5, 0, 1)])
        transport.assets_by_path = {'/p/rej.jpg': 'id-rej'}
        sync_to_immich(db_path, make_config())
        assert transport.asset_updates()[0]["rating"] == 5

    def test_rejected_photo_with_no_stars_pushes_minus_one(self, tmp_path, transport):
        db_path = make_db(tmp_path, [('/p/rej.jpg', 0, 0, 1)])
        transport.assets_by_path = {'/p/rej.jpg': 'id-rej'}
        summary = sync_to_immich(db_path, _rejecting_config())
        updates = transport.asset_updates()
        assert len(updates) == 1
        assert updates[0] == {"ids": ['id-rej'], "rating": -1, "isFavorite": False}
        assert summary["matched"] == 1

    def test_rejection_outranks_stars(self, tmp_path, transport):
        db_path = make_db(tmp_path, [('/p/rej.jpg', 5, 0, 1)])
        transport.assets_by_path = {'/p/rej.jpg': 'id-rej'}
        sync_to_immich(db_path, _rejecting_config())
        assert transport.asset_updates()[0]["rating"] == -1

    def test_unrejecting_clears_a_previously_pushed_minus_one(self, tmp_path, transport):
        db_path = make_db(tmp_path, [('/p/rej.jpg', 0, 0, 1)])
        transport.assets_by_path = {'/p/rej.jpg': 'id-rej'}
        sync_to_immich(db_path, _rejecting_config())
        assert transport.asset_updates()[-1]["rating"] == -1

        _set_rejected(db_path, '/p/rej.jpg', 0)
        summary = sync_to_immich(db_path, _rejecting_config())
        # The clear must reach Immich as null — 0 is rejected by Immich v3.
        assert summary["matched"] == 1
        assert transport.asset_updates()[-1]["rating"] is None

        # Once cleared, the row drops out of tracking and costs nothing more.
        before = len(transport.requests)
        sync_to_immich(db_path, _rejecting_config())
        assert len(transport.requests) == before

    def test_unrejecting_a_starred_photo_restores_its_stars(self, tmp_path, transport):
        db_path = make_db(tmp_path, [('/p/rej.jpg', 4, 0, 1)])
        transport.assets_by_path = {'/p/rej.jpg': 'id-rej'}
        sync_to_immich(db_path, _rejecting_config())
        assert transport.asset_updates()[-1]["rating"] == -1

        _set_rejected(db_path, '/p/rej.jpg', 0)
        sync_to_immich(db_path, _rejecting_config())
        assert transport.asset_updates()[-1]["rating"] == 4

    def test_ratings_disabled_suppresses_the_minus_one(self, tmp_path, transport):
        db_path = make_db(tmp_path, [('/p/rej.jpg', 0, 0, 1)])
        transport.assets_by_path = {'/p/rej.jpg': 'id-rej'}
        # -1 IS a rating write: push.ratings=false must not smuggle one back in.
        sync_to_immich(db_path, _rejecting_config(ratings=False))
        assert transport.requests == []

    def test_rejected_photo_never_joins_the_top_picks_album(self, tmp_path, transport):
        db_path = make_db(tmp_path, [('/p/rej.jpg', 5, 0, 1), ('/p/keep.jpg', 5, 0, 0)])
        transport.assets_by_path = {'/p/rej.jpg': 'id-rej', '/p/keep.jpg': 'id-keep'}
        config = _rejecting_config(top_picks_album="Facet Top Picks", top_picks_min_rating=4)
        sync_to_immich(db_path, config)
        creates = [p for m, path, p in transport.requests
                   if m == "POST" and path == "/api/albums"]
        assert creates == [{"albumName": "Facet Top Picks", "assetIds": ['id-keep']}]

    def test_user_overlay_rejection_drives_the_minus_one(self, tmp_path, transport):
        db_path = make_db(
            tmp_path,
            [('/p/a.jpg', 5, 0, 0)],
            user_rows=[('alice', '/p/a.jpg', 0, 0, 1)],
        )
        transport.assets_by_path = {'/p/a.jpg': 'id-a'}
        config = _rejecting_config()
        config["users"] = {"alice": {"role": "regular"}}
        sync_to_immich(db_path, config, user_id="alice")
        assert transport.asset_updates()[0]["rating"] == -1


class TestWebhookPendingReporting:
    """The sync reports (and prunes) what the inbound webhook queued."""

    def test_pending_paths_are_reported_and_scored_ones_pruned(self, tmp_path, transport):
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0)])
        transport.assets_by_path = {'/p/a.jpg': 'id-a'}
        record_pending_path(db_path, '/p/a.jpg')
        record_pending_path(db_path, '/p/gone.jpg')
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE photos SET aggregate = 8.0 WHERE path = '/p/a.jpg'")
        conn.commit()
        conn.close()

        summary = sync_to_immich(db_path, make_config())
        assert summary["webhook_pending"] == 1
        assert load_pending_paths(db_path) == ['/p/gone.jpg']

    def test_dedup_and_bound(self, tmp_path):
        db_path = make_db(tmp_path, [])
        for path in ('/p/1.jpg', '/p/1.jpg', '/p/2.jpg', '/p/3.jpg'):
            record_pending_path(db_path, path, max_pending=2)
        assert load_pending_paths(db_path) == ['/p/2.jpg', '/p/3.jpg']

    def test_dry_run_does_not_prune(self, tmp_path, transport):
        db_path = make_db(tmp_path, [])
        record_pending_path(db_path, '/p/a.jpg')
        conn = sqlite3.connect(db_path)
        conn.execute("INSERT INTO photos (path, filename, aggregate) VALUES ('/p/a.jpg', 'a.jpg', 8.0)")
        conn.commit()
        conn.close()
        summary = sync_to_immich(db_path, make_config(), dry_run=True)
        assert summary["webhook_pending"] == 0
        assert load_pending_paths(db_path) == ['/p/a.jpg']


class TestBatchedPush:
    """``push_photo_updates`` — the webhook's whole delivery in one DB pass."""

    def test_one_result_per_entry_in_order(self, tmp_path, transport):
        db_path = make_db(tmp_path, [('/p/push.jpg', 5, 0, 0),
                                     ('/p/quiet.jpg', 0, 0, 0),
                                     ('/p/gone.jpg', 4, 0, 0)])
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE photos SET aggregate = 8.0 WHERE path LIKE '/p/%'")
        conn.commit()
        conn.close()
        transport.assets_by_path = {'/p/push.jpg': 'id-push'}
        results = push_photo_updates(db_path, make_config(), [
            ('/p/push.jpg', 'id-push'),
            ('/p/quiet.jpg', None),      # nothing worth sending
            ('/p/gone.jpg', None),       # no Immich asset resolvable
            ('/p/unscanned.jpg', None),  # not in the library at all
        ])
        assert [r for r, _ in results] == [
            RESULT_PUSHED, RESULT_SKIPPED, RESULT_UNMATCHED, RESULT_UNKNOWN]
        assert all(err is None for _, err in results)

    def test_unscored_row_is_unknown_not_pushed(self, tmp_path, transport):
        # aggregate IS NULL: scanned but never scored is indistinguishable from
        # never scanned — both belong on the pending list, neither is pushable.
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0)])
        transport.assets_by_path = {'/p/a.jpg': 'id-a'}
        results = push_photo_updates(db_path, make_config(), [('/p/a.jpg', 'id-a')])
        assert results == [(RESULT_UNKNOWN, None)]
        assert transport.requests == []

    def test_a_failing_asset_is_isolated_from_the_rest(self, tmp_path, monkeypatch):
        import urllib.error

        db_path = make_db(tmp_path, [('/p/boom.jpg', 5, 0, 0), ('/p/ok.jpg', 4, 0, 0)])
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE photos SET aggregate = 8.0 WHERE path LIKE '/p/%'")
        conn.commit()
        conn.close()

        def flaky(_self, method, path, payload=None):
            if method == "GET":
                asset_id = path.rsplit("/", 1)[-1]
                return {"id": asset_id, "originalPath": "/p/" + asset_id[3:] + ".jpg"}
            if method == "POST" and path == "/api/search/metadata":
                original_path = payload["originalPath"]
                return {"assets": {"items": [{"id": "id-" + original_path.rsplit('/', 1)[-1][:-4],
                                                "originalPath": original_path}], "nextPage": None}}
            if method == "PUT" and payload["ids"] == ['id-boom']:
                raise urllib.error.URLError("connection refused")
            return None

        monkeypatch.setattr(ImmichClient, "_request", flaky)
        results = push_photo_updates(db_path, make_config(),
                                     [('/p/boom.jpg', 'id-boom'), ('/p/ok.jpg', 'id-ok')])
        assert results[0][0] == RESULT_FAILED
        assert isinstance(results[0][1], urllib.error.URLError)
        assert results[1] == (RESULT_PUSHED, None)
        # Only the asset that actually reached Immich is tracked as pushed, so
        # the failed one retries (and can still push its clear) next time.
        conn = sqlite3.connect(db_path)
        state = conn.execute(
            "SELECT value FROM stats_cache WHERE key = 'immich_synced_paths:global'"
        ).fetchone()[0]
        conn.close()
        assert '/p/ok.jpg' in state
        assert '/p/boom.jpg' not in state

    def test_no_entries_touches_nothing(self, tmp_path, transport):
        db_path = make_db(tmp_path, [])
        assert push_photo_updates(db_path, make_config(), []) == []
        assert transport.requests == []


class TestSingleAssetPush:
    """``push_photo_update`` — one entry through the batch, exceptions re-raised."""

    def test_returns_the_single_result(self, tmp_path, transport):
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0)])
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE photos SET aggregate = 8.0 WHERE path = '/p/a.jpg'")
        conn.commit()
        conn.close()
        transport.assets_by_path = {'/p/a.jpg': 'id-a'}
        assert push_photo_update(db_path, make_config(), '/p/a.jpg') == RESULT_PUSHED
        assert transport.asset_updates() == [{"ids": ['id-a'], "rating": 5, "isFavorite": False}]

    def test_a_failure_is_raised_not_returned(self, tmp_path):
        # The batch isolates failures into a result pair; the one-shot caller
        # gets the exception back, which is the contract it already had.
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0)])
        with pytest.raises(ValueError):
            push_photo_update(db_path, make_config(api_key=""), '/p/a.jpg')


class TestConcurrentStateWrites:
    """Two deliveries mutating a side-table blob at once must lose nothing.

    Regression: load-mutate-save on the whole JSON document with no lock and no
    transaction. Two webhook deliveries in the FastAPI threadpool both read the
    same blob and the second save overwrote the first's entry.

    The barrier forces exactly that interleaving. Serialized, the second thread
    cannot enter while the first holds the lock, so it never joins the barrier;
    the first times out (harmlessly, that is the whole point of the timeout),
    commits, and the second then reads the committed blob. Unserialized, both
    threads meet at the barrier with the same stale copy and one entry is lost.
    """

    def _barrier_on_load(self, monkeypatch, attr):
        barrier = threading.Barrier(2)
        original = getattr(sync_immich, attr)

        def load_at_the_barrier(*args, **kwargs):
            try:
                barrier.wait(timeout=0.3)
            except threading.BrokenBarrierError:
                pass  # already broken (or timed out): proceed, serialized
            return original(*args, **kwargs)

        monkeypatch.setattr(sync_immich, attr, load_at_the_barrier)

    @staticmethod
    def _run_both(target, args_a, args_b):
        threads = [threading.Thread(target=target, args=args_a),
                   threading.Thread(target=target, args=args_b)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        assert not any(thread.is_alive() for thread in threads)

    def test_concurrent_pending_records_keep_both_paths(self, tmp_path, monkeypatch):
        db_path = make_db(tmp_path, [])
        self._barrier_on_load(monkeypatch, "_load_pending")
        self._run_both(record_pending_paths,
                       (db_path, ['/p/first.jpg']), (db_path, ['/p/second.jpg']))
        assert sorted(load_pending_paths(db_path)) == ['/p/first.jpg', '/p/second.jpg']

    def test_concurrent_pushes_keep_both_synced_entries(self, tmp_path, transport,
                                                        monkeypatch):
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0), ('/p/b.jpg', 4, 0, 0)])
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE photos SET aggregate = 8.0 WHERE path LIKE '/p/%'")
        conn.commit()
        conn.close()
        transport.assets_by_path = {'/p/a.jpg': 'id-a', '/p/b.jpg': 'id-b'}
        self._barrier_on_load(monkeypatch, "_load_synced_state")
        self._run_both(
            lambda db, entry: push_photo_updates(db, make_config(), [entry]),
            (db_path, ('/p/a.jpg', 'id-a')), (db_path, ('/p/b.jpg', 'id-b')))
        conn = sqlite3.connect(db_path)
        state = conn.execute(
            "SELECT value FROM stats_cache WHERE key = 'immich_synced_paths:global'"
        ).fetchone()[0]
        conn.close()
        assert '/p/a.jpg' in state
        assert '/p/b.jpg' in state


class TestReversePathMapping:
    def test_round_trips_through_the_configured_pairs(self):
        pairs = [{"facet_prefix": "/photos/", "immich_prefix": "/usr/src/app/upload/"},
                 {"facet_prefix": "/mnt/other/", "immich_prefix": "/data/"}]
        assert map_immich_path('/usr/src/app/upload/a.jpg', pairs) == '/photos/a.jpg'
        assert map_immich_path('/data/b.jpg', pairs) == '/mnt/other/b.jpg'
        assert map_facet_path(map_immich_path('/data/b.jpg', pairs), pairs) == '/data/b.jpg'

    def test_empty_or_placeholder_map_is_identity(self):
        assert map_immich_path('/x/y.jpg', []) == '/x/y.jpg'
        assert map_immich_path('/x/y.jpg', [{"facet_prefix": "", "immich_prefix": ""}]) == '/x/y.jpg'

    def test_unmapped_prefix_returns_none(self):
        pairs = [{"facet_prefix": "/photos/", "immich_prefix": "/usr/src/app/upload/"}]
        assert map_immich_path('/somewhere/else.jpg', pairs) is None

    def test_a_pair_without_an_immich_prefix_never_shadows_a_later_one(self):
        # Regression: inbound mapping filtered on facet_prefix but matched on
        # ``pair.get("immich_prefix", "")`` — and ''.startswith is true of every
        # path, so the first such pair swallowed the whole map and every asset
        # came back rewritten under /nas/.
        pairs = [{"facet_prefix": "/nas/", "immich_prefix": ""},
                 {"facet_prefix": "/photos/", "immich_prefix": "/usr/src/app/upload/"}]
        assert map_immich_path('/usr/src/app/upload/a.jpg', pairs) == '/photos/a.jpg'

    def test_only_uninvertible_pairs_passes_through(self):
        # A pair with no immich_prefix maps OUTBOUND onto a bare relative path;
        # nothing can invert that. With no invertible pair left the path passes
        # through unchanged, matching map_facet_path's own "no configured pairs
        # ⇒ identity" rule — it is None that means "pairs exist, none matched".
        pairs = [{"facet_prefix": "/nas/", "immich_prefix": ""}]
        assert map_immich_path('/usr/src/app/upload/a.jpg', pairs) == '/usr/src/app/upload/a.jpg'


class PagedIdentityTransport(FakeTransport):
    """Official search response fields, isolated from HTTP/server state."""
    def __init__(self, bulk=(), fallback=()):
        super().__init__()
        self.bulk_pages = list(bulk) or [[]]
        self.fallback_pages = list(fallback) or [[]]

    def __call__(self, method, path, payload=None):
        if method == "POST" and path == "/api/search/metadata":
            self.requests.append((method, path, payload))
            pages = self.fallback_pages if "originalPath" in payload else self.bulk_pages
            page = payload["page"]
            return {"assets": {"items": pages[page - 1],
                               "nextPage": str(page + 1) if page < len(pages) else None}}
        return super().__call__(method, path, payload)


def _remote_asset(asset_id, path='/p/a.jpg', owner='owner-a', library='library-a'):
    return {"id": asset_id, "originalPath": path, "ownerId": owner, "libraryId": library}


class TestAssetIdentity:
    @pytest.mark.parametrize("dry_run", [False, True])
    def test_duplicate_bulk_path_is_refused_across_pages(self, tmp_path, monkeypatch, dry_run):
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0)])
        fake = PagedIdentityTransport(bulk=[[_remote_asset('one')], [_remote_asset('two', owner='owner-b')]])
        monkeypatch.setattr(ImmichClient, '_request', fake)
        summary = sync_to_immich(db_path, make_config(), dry_run=dry_run)
        assert summary['identity_conflicts'] == 1
        assert summary['matched'] == summary['updated'] == summary['unmatched'] == 0
        assert fake.writes() == []
        assert fake.searched_paths() == []  # fallback must not hide known ambiguity
        with sqlite3.connect(db_path) as conn:
            assert conn.execute("SELECT value FROM stats_cache WHERE key LIKE 'immich_synced_paths:%'").fetchone() is None

    def test_duplicate_remote_path_does_not_block_unique_photo(self, tmp_path, monkeypatch):
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0), ('/p/b.jpg', 4, 0, 0)])
        fake = PagedIdentityTransport(bulk=[[_remote_asset('one'), _remote_asset('two'),
                                                  _remote_asset('safe', '/p/b.jpg')]])
        monkeypatch.setattr(ImmichClient, '_request', fake)
        summary = sync_to_immich(db_path, make_config())
        assert summary['identity_conflicts'] == 1
        assert summary['updated'] == 1
        assert fake.asset_updates()[0]['ids'] == ['safe']

    def test_fallback_checks_all_pages_before_writing(self, tmp_path, monkeypatch):
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0)])
        fake = PagedIdentityTransport(fallback=[[_remote_asset('one')], [_remote_asset('two')]])
        monkeypatch.setattr(ImmichClient, '_request', fake)
        summary = sync_to_immich(db_path, make_config())
        assert summary['identity_conflicts'] == 1
        assert fake.writes() == []
        assert fake.searched_paths() == ['/p/a.jpg', '/p/a.jpg']

    def test_fallback_requires_exact_original_path(self, tmp_path, monkeypatch):
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0)])
        fake = PagedIdentityTransport(fallback=[[_remote_asset('wrong', '/p/a.jpg.backup')], [_remote_asset('exact')]])
        monkeypatch.setattr(ImmichClient, '_request', fake)
        summary = sync_to_immich(db_path, make_config())
        assert summary['updated'] == 1
        assert fake.asset_updates()[0]['ids'] == ['exact']

    def test_repeat_same_identity_is_not_ambiguous(self, tmp_path, monkeypatch):
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0)])
        fake = PagedIdentityTransport(bulk=[[_remote_asset('one')], [_remote_asset('one')]])
        monkeypatch.setattr(ImmichClient, '_request', fake)
        assert sync_to_immich(db_path, make_config())['updated'] == 1

    def test_owner_and_library_scope_disambiguate(self, tmp_path, monkeypatch):
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0)])
        fake = PagedIdentityTransport(bulk=[[_remote_asset('wrong-owner', owner='owner-b'),
                                          _remote_asset('wrong-library', library='library-b'),
                                          _remote_asset('selected')]])
        monkeypatch.setattr(ImmichClient, '_request', fake)
        config = make_config(owner_id='owner-a', library_id='library-a')
        assert sync_to_immich(db_path, config)['updated'] == 1
        assert fake.asset_updates()[0]['ids'] == ['selected']

    def test_missing_scope_fields_cannot_satisfy_selection(self, tmp_path, monkeypatch):
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0)])
        incomplete = {"id": "one", "originalPath": "/p/a.jpg"}
        fake = PagedIdentityTransport(bulk=[[incomplete]], fallback=[[incomplete]])
        monkeypatch.setattr(ImmichClient, '_request', fake)
        summary = sync_to_immich(db_path, make_config(owner_id='owner-a'))
        assert summary['unmatched'] == 1
        assert fake.writes() == []

    def test_two_facet_roots_mapping_onto_one_path_are_refused(self, tmp_path, transport):
        db_path = make_db(tmp_path, [('/one/a.jpg', 5, 0, 0), ('/two/a.jpg', 4, 0, 0)])
        transport.assets_by_path = {'/remote/a.jpg': 'one'}
        config = make_config(path_map=[
            {'facet_prefix': '/one/', 'immich_prefix': '/remote/'},
            {'facet_prefix': '/two/', 'immich_prefix': '/remote/'},
        ])
        summary = sync_to_immich(db_path, config)
        assert summary['identity_conflicts'] == 2
        assert transport.writes() == []

    def test_legacy_prefix_mapping_remains_literal_and_first_match(self):
        pairs = [{'facet_prefix': '/photos/a', 'immich_prefix': '/remote/a'},
                 {'facet_prefix': '/photos/ab/', 'immich_prefix': '/narrow/'}]
        assert map_facet_path('/photos/ab/p.jpg', pairs) == '/remote/ab/p.jpg'
        assert map_immich_path('/remote/ab/p.jpg', pairs) == '/photos/ab/p.jpg'

    @pytest.mark.parametrize('response', [
        {'id': 'wrong', 'originalPath': '/p/a.jpg'},
        {'id': 'one', 'originalPath': '/p/other.jpg'},
        {'id': 'one', 'originalPath': '/p/a.jpg', 'ownerId': 'other'},
    ])
    def test_webhook_id_is_verified_on_configured_server(self, tmp_path, monkeypatch, response):
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0)])
        with sqlite3.connect(db_path) as conn:
            conn.execute('UPDATE photos SET aggregate=8')
        writes = []

        def request(_self, method, path, payload=None):
            if method == 'GET':
                assert path == '/api/assets/one'
                assert _self.base_url == 'http://immich.local:2283'
                return response
            writes.append((method, path, payload))

        monkeypatch.setattr(ImmichClient, '_request', request)
        results = push_photo_updates(db_path, make_config(owner_id='owner-a'), [('/p/a.jpg', 'one')])
        assert results[0][0] == RESULT_FAILED
        assert isinstance(results[0][1], sync_immich.AssetIdentityError)
        assert writes == []

    def test_ambiguous_clear_preserves_state_for_later_retry(self, tmp_path, monkeypatch, transport):
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0)])
        transport.assets_by_path = {'/p/a.jpg': 'one'}
        sync_to_immich(db_path, make_config())
        with sqlite3.connect(db_path) as conn:
            conn.execute('UPDATE photos SET star_rating=0')
        fake = PagedIdentityTransport(bulk=[[_remote_asset('one'), _remote_asset('two')]])
        monkeypatch.setattr(ImmichClient, '_request', fake)
        assert sync_to_immich(db_path, make_config())['identity_conflicts'] == 1
        assert fake.writes() == []
        monkeypatch.setattr(ImmichClient, '_request', transport)
        assert sync_to_immich(db_path, make_config())['updated'] == 1
        assert transport.asset_updates()[-1]['rating'] is None

    def test_non_advancing_page_refuses_any_write(self, tmp_path, monkeypatch):
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0)])
        writes = []

        def request(_self, method, path, payload=None):
            if method == 'POST':
                return {'assets': {'items': [_remote_asset('one')], 'nextPage': '1'}}
            writes.append((method, path, payload))

        monkeypatch.setattr(ImmichClient, '_request', request)
        with pytest.raises(sync_immich.AssetIdentityError, match='non-advancing'):
            sync_to_immich(db_path, make_config())
        assert writes == []


    def test_same_id_with_inconsistent_paths_refuses_both(self, tmp_path, monkeypatch):
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0), ('/p/b.jpg', 4, 0, 0)])
        fake = PagedIdentityTransport(bulk=[[_remote_asset('same'), _remote_asset('same', '/p/b.jpg')]])
        monkeypatch.setattr(ImmichClient, '_request', fake)
        summary = sync_to_immich(db_path, make_config())
        assert summary['identity_conflicts'] == 2
        assert fake.writes() == []

    @pytest.mark.parametrize('response', [
        {'assets': {'items': [{'id': 'one'}], 'nextPage': None}},
        {'assets': {'items': {'id': 'one'}, 'nextPage': None}},
        {'assets': 'unexpected'},
        ['unexpected'],
    ])
    def test_malformed_search_identity_fails_closed(self, tmp_path, monkeypatch, response):
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0)])
        writes = []

        def request(_self, method, path, payload=None):
            if method == 'POST':
                return response
            writes.append((method, path, payload))

        monkeypatch.setattr(ImmichClient, '_request', request)
        with pytest.raises(sync_immich.AssetIdentityError):
            sync_to_immich(db_path, make_config())
        assert writes == []


    @pytest.mark.parametrize('asset_id', [None, 123, {'id': 'one'}])
    def test_invalid_webhook_id_is_an_isolated_identity_error(self, asset_id):
        client = ImmichClient('http://immich.test', 'key')
        with pytest.raises(sync_immich.AssetIdentityError, match='nonempty string'):
            client.verify_asset_id(asset_id, '/p/a.jpg')


    def test_fallback_refuses_id_aliased_to_broad_search_hit(self, tmp_path, monkeypatch):
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0)])
        fake = PagedIdentityTransport(fallback=[[_remote_asset('same')],
                                                [_remote_asset('same', '/p/a.jpg.backup')]])
        monkeypatch.setattr(ImmichClient, '_request', fake)
        summary = sync_to_immich(db_path, make_config())
        assert summary['identity_conflicts'] == 1
        assert summary['updated'] == 0
        assert fake.writes() == []

    @pytest.mark.parametrize('with_hints', [False, True])
    def test_webhook_batch_refuses_all_mapping_collisions_before_writes(
            self, tmp_path, transport, with_hints):
        db_path = make_db(tmp_path, [('/one/a.jpg', 5, 0, 0),
                                     ('/two/a.jpg', 4, 0, 0),
                                     ('/safe/b.jpg', 3, 0, 0)])
        with sqlite3.connect(db_path) as conn:
            conn.execute('UPDATE photos SET aggregate=8')
        transport.assets_by_path = {'/remote/a.jpg': 'conflict', '/safe/b.jpg': 'safe'}
        config = make_config(path_map=[
            {'facet_prefix': '/one/', 'immich_prefix': '/remote/'},
            {'facet_prefix': '/two/', 'immich_prefix': '/remote/'},
            {'facet_prefix': '/safe/', 'immich_prefix': '/safe/'},
        ])
        results = push_photo_updates(db_path, config, [
            ('/one/a.jpg', 'conflict' if with_hints else None),
            ('/two/a.jpg', 'conflict' if with_hints else None),
            ('/safe/b.jpg', 'safe' if with_hints else None),
        ])
        assert [r for r, _ in results] == [RESULT_FAILED, RESULT_FAILED, RESULT_PUSHED]
        assert all(isinstance(error, sync_immich.AssetIdentityError) for _, error in results[:2])
        assert transport.asset_updates() == [{'ids': ['safe'], 'rating': 3, 'isFavorite': False}]
        assert '/remote/a.jpg' not in transport.searched_paths()
        with sqlite3.connect(db_path) as conn:
            state = conn.execute("SELECT value FROM stats_cache WHERE key='immich_synced_paths:global'").fetchone()[0]
        assert '/safe/b.jpg' in state
        assert '/one/a.jpg' not in state
        assert '/two/a.jpg' not in state

    def test_webhook_batch_refuses_same_hint_for_distinct_paths(self, tmp_path, transport):
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0), ('/p/b.jpg', 4, 0, 0)])
        with sqlite3.connect(db_path) as conn:
            conn.execute('UPDATE photos SET aggregate=8')
        results = push_photo_updates(db_path, make_config(), [('/p/a.jpg', 'same'), ('/p/b.jpg', 'same')])
        assert [result for result, _ in results] == [RESULT_FAILED, RESULT_FAILED]
        assert transport.requests == []


    def test_webhook_resolves_all_ids_before_updating_any_alias(self, tmp_path, transport):
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0), ('/p/b.jpg', 4, 0, 0)])
        with sqlite3.connect(db_path) as conn:
            conn.execute('UPDATE photos SET aggregate=8')
        # Each exact search appears unique, but the complete delivery proves
        # the same UUID has contradictory paths. Neither may be written first.
        transport.assets_by_path = {'/p/a.jpg': 'same', '/p/b.jpg': 'same'}
        results = push_photo_updates(db_path, make_config(), [('/p/a.jpg', None), ('/p/b.jpg', None)])
        assert [result for result, _ in results] == [RESULT_FAILED, RESULT_FAILED]
        assert transport.asset_updates() == []


    def test_full_sync_resolves_all_fallback_ids_before_grouping_aliases(self, tmp_path, transport):
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0), ('/p/b.jpg', 4, 0, 0), ('/p/c.jpg', 3, 0, 0)])
        transport.bulk_assets = {}
        transport.assets_by_path = {'/p/a.jpg': 'same', '/p/b.jpg': 'same', '/p/c.jpg': 'safe'}
        summary = sync_to_immich(db_path, make_config())
        assert summary['identity_conflicts'] == 2
        assert summary['matched'] == summary['updated'] == 1
        assert transport.asset_updates() == [{'ids': ['safe'], 'rating': 3, 'isFavorite': False}]
        with sqlite3.connect(db_path) as conn:
            state = conn.execute("SELECT value FROM stats_cache WHERE key='immich_synced_paths:global'").fetchone()[0]
        assert '/p/c.jpg' in state
        assert '/p/a.jpg' not in state and '/p/b.jpg' not in state


    def test_fallback_id_must_agree_with_unselected_bulk_identity(self, tmp_path, transport):
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0), ('/p/safe.jpg', 3, 0, 0)])
        transport.bulk_assets = {'/p/different.jpg': 'same', '/p/safe.jpg': 'safe'}
        transport.assets_by_path = {'/p/a.jpg': 'same', '/p/safe.jpg': 'safe'}
        summary = sync_to_immich(db_path, make_config())
        assert summary['identity_conflicts'] == 1
        assert summary['updated'] == 1
        assert transport.asset_updates() == [{'ids': ['safe'], 'rating': 3, 'isFavorite': False}]
        with sqlite3.connect(db_path) as conn:
            state = conn.execute("SELECT value FROM stats_cache WHERE key='immich_synced_paths:global'").fetchone()[0]
        assert '/p/a.jpg' not in state and '/p/safe.jpg' in state

    def test_later_fallback_alias_also_refuses_earlier_bulk_candidate(self, tmp_path, transport):
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0), ('/p/b.jpg', 4, 0, 0), ('/p/safe.jpg', 3, 0, 0)])
        transport.bulk_assets = {'/p/a.jpg': 'same', '/p/safe.jpg': 'safe'}
        transport.assets_by_path = {'/p/b.jpg': 'same', '/p/safe.jpg': 'safe'}
        summary = sync_to_immich(db_path, make_config())
        assert summary['identity_conflicts'] == 2
        assert summary['updated'] == 1
        assert transport.asset_updates() == [{'ids': ['safe'], 'rating': 3, 'isFavorite': False}]

    def test_same_webhook_path_with_distinct_remote_ids_refuses_both(self, tmp_path, monkeypatch):
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0), ('/p/safe.jpg', 3, 0, 0)])
        with sqlite3.connect(db_path) as conn:
            conn.execute('UPDATE photos SET aggregate=8')
        writes = []

        def request(_self, method, path, payload=None):
            if method == 'GET':
                asset_id = path.rsplit('/', 1)[-1]
                return {'id': asset_id, 'originalPath': '/p/safe.jpg' if asset_id == 'safe' else '/p/a.jpg'}
            if method == 'POST' and path == '/api/search/metadata':
                original_path = payload['originalPath']
                ids = ['safe'] if original_path == '/p/safe.jpg' else ['one', 'two']
                return {'assets': {'items': [{'id': asset_id, 'originalPath': original_path} for asset_id in ids],
                                   'nextPage': None}}
            writes.append((method, path, payload))

        monkeypatch.setattr(ImmichClient, '_request', request)
        results = push_photo_updates(db_path, make_config(), [
            ('/p/a.jpg', 'one'), ('/p/a.jpg', 'two'), ('/p/safe.jpg', 'safe')])
        assert [result for result, _ in results] == [RESULT_FAILED, RESULT_FAILED, RESULT_PUSHED]
        assert writes == [('PUT', '/api/assets', {'ids': ['safe'], 'rating': 3, 'isFavorite': False})]
        with sqlite3.connect(db_path) as conn:
            state = conn.execute("SELECT value FROM stats_cache WHERE key='immich_synced_paths:global'").fetchone()[0]
        assert '/p/a.jpg' not in state and '/p/safe.jpg' in state


    def test_broad_fallback_repeating_valid_bulk_edge_is_harmless(self, tmp_path, monkeypatch):
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0), ('/p/b.jpg', 4, 0, 0)])
        fake = PagedIdentityTransport(bulk=[[_remote_asset('x', '/p/b.jpg')]],
                                      fallback=[[_remote_asset('x', '/p/b.jpg'), _remote_asset('y')]])
        monkeypatch.setattr(ImmichClient, '_request', fake)
        summary = sync_to_immich(db_path, make_config())
        assert summary['identity_conflicts'] == 0
        assert summary['updated'] == 2
        assert {asset for update in fake.asset_updates() for asset in update['ids']} == {'x', 'y'}

    def test_unmatched_fallback_can_disprove_earlier_bulk_edge(self, tmp_path, monkeypatch):
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0), ('/p/b.jpg', 4, 0, 0), ('/p/safe.jpg', 3, 0, 0)])
        fake = PagedIdentityTransport(bulk=[[_remote_asset('x'), _remote_asset('safe', '/p/safe.jpg')]],
                                      fallback=[[_remote_asset('y')]])  # no exact b match, but a now has two IDs
        monkeypatch.setattr(ImmichClient, '_request', fake)
        summary = sync_to_immich(db_path, make_config())
        assert summary['identity_conflicts'] == 1
        assert summary['unmatched'] == 1
        assert summary['updated'] == 1
        assert fake.asset_updates() == [{'ids': ['safe'], 'rating': 3, 'isFavorite': False}]

    def test_webhook_hint_and_later_fallback_share_identity_registry(self, tmp_path, transport):
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0), ('/p/b.jpg', 4, 0, 0)])
        with sqlite3.connect(db_path) as conn:
            conn.execute('UPDATE photos SET aggregate=8')
        transport.assets_by_path = {'/p/a.jpg': 'x', '/p/b.jpg': 'x'}
        results = push_photo_updates(db_path, make_config(), [('/p/a.jpg', 'x'), ('/p/b.jpg', None)])
        assert [result for result, _ in results] == [RESULT_FAILED, RESULT_FAILED]
        assert transport.asset_updates() == []

    def test_repeated_identical_webhook_edge_remains_safe(self, tmp_path, transport):
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0)])
        with sqlite3.connect(db_path) as conn:
            conn.execute('UPDATE photos SET aggregate=8')
        transport.assets_by_path = {'/p/a.jpg': 'x'}
        results = push_photo_updates(db_path, make_config(), [('/p/a.jpg', 'x'), ('/p/a.jpg', 'x')])
        assert [result for result, _ in results] == [RESULT_PUSHED, RESULT_PUSHED]
        assert all(update['ids'] == ['x'] for update in transport.asset_updates())

    def test_out_of_scope_broad_hits_do_not_poison_bulk_identity(self, tmp_path, monkeypatch):
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0), ('/p/b.jpg', 4, 0, 0)])
        fake = PagedIdentityTransport(bulk=[[_remote_asset('x')]],
                                      fallback=[[_remote_asset('x', '/different.jpg', owner='other')]])
        monkeypatch.setattr(ImmichClient, '_request', fake)
        summary = sync_to_immich(db_path, make_config(owner_id='owner-a'))
        assert summary['identity_conflicts'] == 0
        assert summary['unmatched'] == summary['updated'] == 1
        assert fake.asset_updates() == [{'ids': ['x'], 'rating': 5, 'isFavorite': False}]


def test_preview_preserves_delete_journal_and_pending_state(tmp_path, transport):
    from pathlib import Path

    db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0)])
    transport.assets_by_path = {'/p/a.jpg': 'id-a'}
    record_pending_path(db_path, '/p/a.jpg')
    with sqlite3.connect(db_path) as conn:
        conn.execute('UPDATE photos SET aggregate=8')
        conn.commit()
        conn.execute('PRAGMA journal_mode=DELETE')
    before = Path(db_path).read_bytes()

    summary = sync_to_immich(db_path, make_config(), dry_run=True)
    assert summary['updated'] == 1 and summary['webhook_pending'] == 0
    assert transport.writes() == []
    assert Path(db_path).read_bytes() == before

    summary = sync_to_immich(db_path, make_config())
    assert summary['updated'] == 1
    assert transport.asset_updates() == [{'ids': ['id-a'], 'isFavorite': False, 'rating': 5}]
    assert load_pending_paths(db_path) == []


def _variable_limit(db_path):
    """SQLite's compile-time host-parameter ceiling; the tracked-state tests
    size their fixtures just past it. Skips on pythons without ``getlimit``."""
    conn = sqlite3.connect(db_path)
    try:
        return conn.getlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER)
    except AttributeError:
        pytest.skip("sqlite3.Connection.getlimit unavailable")
    finally:
        conn.close()


class TestLargeSyncedState:
    """Every read of the tracked synced state chunks its path list.

    Regression: ``_fetch_rating_rows`` built ONE ``IN (...)`` over the whole tracked
    state. That state grows with the pushed half of the library and only
    shrinks through a sync itself, so past SQLite's host-parameter limit the
    sync raised before any network work — wedging every later run.
    """

    def test_fetch_rating_rows_chunks_past_the_host_parameter_limit(self, tmp_path):
        db_path = make_db(tmp_path, [('/p/star.jpg', 5, 0, 0), ('/p/reset.jpg', 0, 0, 0)])
        limit = _variable_limit(db_path)
        stale = ['/p/reset.jpg'] + [f'/gone/{i}' for i in range(limit)]
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = sync_immich._fetch_rating_rows(conn, None, extra_paths=stale)
        finally:
            conn.close()
        by_path = {row["path"]: row for row in rows}
        assert len(rows) == 2
        assert by_path["/p/star.jpg"]["star_rating"] == 5
        # The reset photo is inactive in every clause; only the chunked
        # stale-path reads can still see it, which keeps its clear pushable.
        assert by_path["/p/reset.jpg"]["star_rating"] == 0

    def test_the_whole_tracked_state_flows_through_the_chunked_fetch(
            self, tmp_path, transport, monkeypatch):
        db_path = make_db(tmp_path, [(f'/p/{i}.jpg', 5, 0, 0) for i in range(5)])
        transport.assets_by_path = {f'/p/{i}.jpg': f'id-{i}' for i in range(5)}
        sync_to_immich(db_path, make_config())

        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE photos SET star_rating = 0")
        conn.commit()
        conn.close()

        # A chunk size smaller than the state forces the chunked path; before
        # the fix the whole state went out as one IN (...) regardless.
        monkeypatch.setattr(sync_immich, "PATH_QUERY_CHUNK", 2)
        summary = sync_to_immich(db_path, make_config())
        assert summary["updated"] == 5
        clears = [u for u in transport.asset_updates()
                  if "rating" in u and u["rating"] is None]
        assert len(clears) == 1
        assert sorted(clears[0]["ids"]) == [f'id-{i}' for i in range(5)]

    def test_gone_paths_are_pruned_from_the_tracked_state(self, tmp_path, transport):
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0)])
        transport.assets_by_path = {'/p/a.jpg': 'id-a'}
        sync_to_immich(db_path, make_config())

        # The photo leaves the library, a new one arrives in the same run.
        conn = sqlite3.connect(db_path)
        conn.execute("DELETE FROM photos WHERE path = '/p/a.jpg'")
        conn.execute(
            "INSERT INTO photos (path, filename, star_rating) VALUES ('/p/b.jpg', 'b.jpg', 4)")
        conn.commit()
        conn.close()
        transport.assets_by_path['/p/b.jpg'] = 'id-b'

        summary = sync_to_immich(db_path, make_config())
        assert summary["updated"] == 1
        with sqlite3.connect(db_path) as conn:
            blob = conn.execute(
                "SELECT value FROM stats_cache WHERE key = 'immich_synced_paths:global'"
            ).fetchone()[0]
        # The dead entry is gone; the live one is untouched.
        assert json.loads(blob) == {'/p/b.jpg': {'rating': True, 'favorite': False}}

    def test_dry_run_never_prunes_the_tracked_state(self, tmp_path, transport):
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0)])
        transport.assets_by_path = {'/p/a.jpg': 'id-a'}
        sync_to_immich(db_path, make_config())
        conn = sqlite3.connect(db_path)
        conn.execute("DELETE FROM photos WHERE path = '/p/a.jpg'")
        conn.commit()
        conn.close()

        sync_to_immich(db_path, make_config(), dry_run=True)
        with sqlite3.connect(db_path) as conn:
            blob = conn.execute(
                "SELECT value FROM stats_cache WHERE key = 'immich_synced_paths:global'"
            ).fetchone()[0]
        assert json.loads(blob) == {'/p/a.jpg': {'rating': True, 'favorite': False}}


class TestPendingBeyondTheHostParameterLimit:
    """The webhook pending list is config-capped, but ``max_pending: 0`` means
    unbounded — and ``_report_pending`` read it as one ``IN (...)`` too."""

    def test_report_pending_chunks_a_growing_list(self, tmp_path):
        db_path = make_db(tmp_path, [('/p/scored.jpg', 0, 0, 0)])
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE photos SET aggregate = 8.0 WHERE path = '/p/scored.jpg'")
        conn.commit()
        limit = _variable_limit(db_path)
        conn.close()
        record_pending_paths(db_path, ['/p/scored.jpg'] + [f'/x{i}' for i in range(limit)],
                             max_pending=0)

        remaining = sync_immich._report_pending(db_path, dry_run=False)

        assert remaining == limit
        kept = load_pending_paths(db_path)
        assert len(kept) == limit
        assert '/p/scored.jpg' not in kept


class TestWebhookBatchedWrites:
    """Assets sharing one payload write as ONE batched call (chunked like every
    other write); a refused batch falls back to per-asset writes, keeping the
    per-asset isolation the delivery contract promises."""

    def test_identical_payloads_write_as_one_put(self, tmp_path, transport):
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0), ('/p/b.jpg', 5, 0, 0),
                                     ('/p/c.jpg', 5, 0, 0)])
        with sqlite3.connect(db_path) as conn:
            conn.execute("UPDATE photos SET aggregate = 8")
        transport.assets_by_path = {'/p/a.jpg': 'id-a', '/p/b.jpg': 'id-b', '/p/c.jpg': 'id-c'}

        results = push_photo_updates(db_path, make_config(), [
            ('/p/a.jpg', 'id-a'), ('/p/b.jpg', 'id-b'), ('/p/c.jpg', 'id-c')])

        assert [r for r, _ in results] == [RESULT_PUSHED] * 3
        assert transport.asset_updates() == [{'ids': ['id-a', 'id-b', 'id-c'],
                                              'rating': 5, 'isFavorite': False}]

    def test_repeated_identical_entries_share_one_write(self, tmp_path, transport):
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0)])
        with sqlite3.connect(db_path) as conn:
            conn.execute("UPDATE photos SET aggregate = 8")
        transport.assets_by_path = {'/p/a.jpg': 'id-a'}

        results = push_photo_updates(db_path, make_config(),
                                     [('/p/a.jpg', 'id-a'), ('/p/a.jpg', 'id-a')])

        assert [r for r, _ in results] == [RESULT_PUSHED, RESULT_PUSHED]
        assert transport.asset_updates() == [{'ids': ['id-a'], 'rating': 5, 'isFavorite': False}]

    def test_a_refused_batch_falls_back_to_per_asset_writes(self, tmp_path, monkeypatch):
        import urllib.error

        db_path = make_db(tmp_path, [('/p/boom.jpg', 5, 0, 0), ('/p/ok.jpg', 5, 0, 0)])
        with sqlite3.connect(db_path) as conn:
            conn.execute("UPDATE photos SET aggregate = 8")
        puts = []

        def flaky(_self, method, path, payload=None):
            if method == "GET" and path.startswith("/api/assets/"):
                asset_id = path.rsplit("/", 1)[-1]
                return {"id": asset_id, "originalPath": f"/p/{asset_id[3:]}.jpg"}
            if method == "POST" and path == "/api/search/metadata":
                original_path = payload["originalPath"]
                asset_id = 'id-' + original_path.rsplit('/', 1)[-1][:-4]
                return {"assets": {"items": [{"id": asset_id, "originalPath": original_path}],
                                   "nextPage": None}}
            if method == "PUT" and path == "/api/assets":
                puts.append(payload["ids"])
                if len(payload["ids"]) > 1 or payload["ids"] == ['id-boom']:
                    raise urllib.error.HTTPError("http://immich.local", 400, "batch refused", {}, None)
                return None
            raise AssertionError(f"Unexpected request: {method} {path}")

        monkeypatch.setattr(ImmichClient, "_request", flaky)
        results = push_photo_updates(db_path, make_config(), [
            ('/p/boom.jpg', 'id-boom'), ('/p/ok.jpg', 'id-ok'),
            ('/p/ok.jpg', 'id-ok')])

        assert results[2] == (RESULT_PUSHED, None)
        assert results[0][0] == RESULT_FAILED
        assert results[1] == (RESULT_PUSHED, None)
        # The batch went out as ONE call carrying both ids before the fallback.
        assert puts[0] == ['id-boom', 'id-ok']
        assert puts[1:] == [['id-boom'], ['id-ok']]
        with sqlite3.connect(db_path) as conn:
            state = conn.execute(
                "SELECT value FROM stats_cache WHERE key = 'immich_synced_paths:global'"
            ).fetchone()[0]
        assert '/p/ok.jpg' in state
        assert '/p/boom.jpg' not in state


class TestTopPicksMembership:
    """The album mirrors the threshold: an existing member is never re-added,
    members that dropped below it (or the whole album, if none remain) are
    removed, and every album write is chunked."""

    def _album_config(self, **overrides):
        push = {"ratings": True, "favorites": True,
                "top_picks_album": "Facet Top Picks", "top_picks_min_rating": 4}
        push.update(overrides)
        return make_config(push=push)

    def test_existing_members_are_never_readded(self, tmp_path, transport):
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0)])
        transport.assets_by_path = {'/p/a.jpg': 'id-a'}
        transport.albums = [{"albumName": "Facet Top Picks", "id": "al"}]
        transport.album_assets = {'al': ['id-a']}

        summary = sync_to_immich(db_path, self._album_config())

        assert summary["albums_created"] == 0
        assert [r for r in transport.requests
                if r[0] == "PUT" and r[1].startswith("/api/albums/")] == []
        assert [r for r in transport.requests if r[0] == "DELETE"] == []

    def test_members_below_the_threshold_are_removed(self, tmp_path, transport):
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0), ('/p/b.jpg', 5, 0, 0),
                                     ('/p/c.jpg', 3, 0, 0)])
        transport.assets_by_path = {'/p/a.jpg': 'id-a', '/p/b.jpg': 'id-b', '/p/c.jpg': 'id-c'}
        transport.albums = [{"albumName": "Facet Top Picks", "id": "al"}]
        transport.album_assets = {'al': ['id-a', 'id-b', 'id-c']}

        sync_to_immich(db_path, self._album_config())

        removes = [(p, payload) for m, p, payload in transport.requests
                   if m == "DELETE" and p.startswith("/api/albums/")]
        assert removes == [("/api/albums/al/assets", {"ids": ["id-c"]})]
        assert [payload for m, p, payload in transport.requests
                if m == "PUT" and p.startswith("/api/albums/")] == []

    def test_an_album_drains_to_empty_when_nothing_qualifies(self, tmp_path, transport):
        db_path = make_db(tmp_path, [('/p/a.jpg', 3, 0, 0)])
        transport.assets_by_path = {'/p/a.jpg': 'id-a'}
        transport.albums = [{"albumName": "Facet Top Picks", "id": "al"}]
        transport.album_assets = {'al': ['id-a']}

        summary = sync_to_immich(db_path, self._album_config())

        assert summary["albums_created"] == 0
        removes = [(p, payload) for m, p, payload in transport.requests
                   if m == "DELETE" and p.startswith("/api/albums/")]
        assert removes == [("/api/albums/al/assets", {"ids": ["id-a"]})]

    def test_unreadable_membership_degrades_to_add_only(self, tmp_path, transport,
                                                        monkeypatch):
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0)])
        transport.assets_by_path = {'/p/a.jpg': 'id-a'}
        transport.albums = [{"albumName": "Facet Top Picks", "id": "al"}]
        monkeypatch.setattr(ImmichClient, "album_asset_ids", lambda self, album_id: None)

        sync_to_immich(db_path, self._album_config())

        adds = [payload for m, p, payload in transport.requests
                if m == "PUT" and p.startswith("/api/albums/")]
        assert adds == [{"ids": ["id-a"]}]
        assert [r for r in transport.requests if r[0] == "DELETE"] == []

    def test_creation_carries_the_first_chunk_and_adds_the_rest(self, tmp_path, transport):
        count = 600
        db_path = make_db(tmp_path, [(f'/p/{i}.jpg', 5, 0, 0) for i in range(count)])
        transport.assets_by_path = {f'/p/{i}.jpg': f'id-{i}' for i in range(count)}

        summary = sync_to_immich(db_path, self._album_config())

        assert summary["albums_created"] == 1
        creates = [payload for m, p, payload in transport.requests
                   if m == "POST" and p == "/api/albums"]
        assert len(creates) == 1 and len(creates[0]["assetIds"]) == 500
        adds = [(p, payload) for m, p, payload in transport.requests
                if m == "PUT" and p.startswith("/api/albums/")]
        assert [len(payload["ids"]) for _, payload in adds] == [100]
        assert set(creates[0]["assetIds"]) | set(adds[0][1]["ids"]) == {f'id-{i}' for i in range(count)}

    def test_additions_to_an_existing_album_are_chunked(self, tmp_path, transport):
        count = 600
        db_path = make_db(tmp_path, [(f'/p/{i}.jpg', 5, 0, 0) for i in range(count)])
        transport.assets_by_path = {f'/p/{i}.jpg': f'id-{i}' for i in range(count)}
        transport.albums = [{"albumName": "Facet Top Picks", "id": "al"}]
        transport.album_assets = {'al': []}

        summary = sync_to_immich(db_path, self._album_config())

        assert summary["albums_created"] == 0
        adds = [payload for m, p, payload in transport.requests
                if m == "PUT" and p.startswith("/api/albums/")]
        assert [len(payload["ids"]) for payload in adds] == [500, 100]
        assert {a for payload in adds for a in payload["ids"]} == {f'id-{i}' for i in range(count)}

    def test_a_member_facet_cannot_resolve_is_kept(self, tmp_path, transport):
        # The photo still rates 5 in the library, but Immich has no asset for
        # it this run. Removal must not treat "not resolved" as "below the
        # threshold" — an identity problem must not evict a qualifying member.
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0)])
        transport.albums = [{"albumName": "Facet Top Picks", "id": "al"}]
        transport.album_assets = {'al': ['id-a']}

        summary = sync_to_immich(db_path, self._album_config())

        assert summary["unmatched"] == 1
        assert [r for r in transport.requests if r[0] == "DELETE"] == []
        assert [r for r in transport.requests
                if r[0] == "PUT" and r[1].startswith("/api/albums/")] == []

    def test_a_member_whose_push_is_disabled_is_kept(self, tmp_path, transport):
        # push.ratings=false: the 5-star row yields no payload at all, so it
        # never resolves — and it must stay a member rather than drain out.
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0)])
        transport.albums = [{"albumName": "Facet Top Picks", "id": "al"}]
        transport.album_assets = {'al': ['id-a']}

        sync_to_immich(db_path, self._album_config(ratings=False))

        assert [r for r in transport.requests if r[0] == "DELETE"] == []
        assert [r for r in transport.requests
                if r[0] == "PUT" and r[1].startswith("/api/albums/")] == []

    def test_a_member_attributed_to_a_qualifying_row_is_kept(self, tmp_path, monkeypatch):
        # A duplicate upload in Immich makes every resolution of this path an
        # identity conflict, so the member never lands in the resolved
        # qualifying set — but the proof loop can still attribute it (one
        # observed path, mapped back to a row that still rates 5), which is
        # exactly what must keep it in the album.
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0)])
        requests = []

        def request(_self, method, path, payload=None):
            requests.append((method, path, payload))
            if method == "POST" and path == "/api/search/metadata":
                return {"assets": {"items": [
                    {"id": "one", "originalPath": "/p/a.jpg"},
                    {"id": "two", "originalPath": "/p/a.jpg"}], "nextPage": None}}
            if method == "GET" and path == "/api/albums":
                return [{"albumName": "Facet Top Picks", "id": "al"}]
            if method == "GET" and path.startswith("/api/albums/"):
                return {"id": "al", "assets": [{"id": "one"}]}
            return None

        monkeypatch.setattr(ImmichClient, "_request", request)
        summary = sync_to_immich(db_path, self._album_config())

        assert summary["identity_conflicts"] == 1
        assert [r for r in requests if r[0] == "DELETE"] == []
        assert [r for r in requests
                if r[0] == "PUT" and r[1].startswith("/api/albums/")] == []

    def test_a_per_user_sync_never_removes_album_members(self, tmp_path, transport):
        # The album name is global to the config, but a per-user sync's rows
        # are that user's overlay: anything the other users (or the global
        # columns) put in the album is unattributable to those rows, so the
        # run must add only — never prune the others' picks away.
        db_path = make_db(tmp_path, [('/p/a.jpg', 0, 0, 0), ('/p/b.jpg', 0, 0, 0)],
                          user_rows=[('alice', '/p/a.jpg', 5, 1, 0)])
        transport.assets_by_path = {'/p/a.jpg': 'id-a', '/p/b.jpg': 'id-b'}
        transport.albums = [{"albumName": "Facet Top Picks", "id": "al"}]
        transport.album_assets = {'al': ['id-a', 'id-b']}
        config = self._album_config()
        config["users"] = {"alice": {"role": "regular"}}

        summary = sync_to_immich(db_path, config, user_id="alice")

        assert summary["albums_created"] == 0
        assert [r for r in transport.requests if r[0] == "DELETE"] == []
        # id-a is Alice's own qualifying pick and already a member: no re-add.
        assert [r for r in transport.requests
                if r[0] == "PUT" and r[1].startswith("/api/albums/")] == []


class TestAlbumFailureIsolation:
    """The album step cannot cost the sync its ratings or its tracked state.

    Regression (found by the maintainer running the branch): a key that may
    add to albums but not remove from them answered the membership DELETE
    with 403 AFTER the asset PUTs and BEFORE the tracked-state write — the
    sync aborted, the state never advanced, and every later run re-pushed
    into the same 403 for as long as a removal was due. The state is now
    committed before the album step, and the membership read and the removal
    degrade to counts instead of raising.
    """

    def _album_setup(self, tmp_path, transport):
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0), ('/p/c.jpg', 3, 0, 0)])
        transport.assets_by_path = {'/p/a.jpg': 'id-a', '/p/c.jpg': 'id-c'}
        transport.albums = [{"albumName": "Facet Top Picks", "id": "al"}]
        transport.album_assets = {'al': ['id-a', 'id-c']}
        return db_path

    def test_a_delete_403_no_longer_wedges_the_sync(self, tmp_path, transport, monkeypatch):
        import urllib.error
        db_path = self._album_setup(tmp_path, transport)

        def forbidden_delete(_self, method, path, payload=None):
            if method == "DELETE" and path.startswith("/api/albums/"):
                raise urllib.error.HTTPError(path, 403, "Forbidden", None, None)
            return transport(method, path, payload)

        monkeypatch.setattr(ImmichClient, "_request", forbidden_delete)

        summary = sync_to_immich(db_path, _rejecting_config(top_picks_album="Facet Top Picks"))

        # The sync completes; the ratings reached Immich and the tracked
        # state ADVANCED despite the refused removal.
        assert summary["updated"] == 2
        assert summary["album_removed"] == 0
        assert summary["album_remove_failed"] == 1
        with sqlite3.connect(db_path) as conn:
            state = conn.execute(
                "SELECT value FROM stats_cache WHERE key = 'immich_synced_paths:global'"
            ).fetchone()[0]
        assert '/p/a.jpg' in state and '/p/c.jpg' in state
        # A follow-up sync is not stuck re-pushing into the 403.
        transport.requests.clear()
        summary2 = sync_to_immich(db_path, _rejecting_config(top_picks_album="Facet Top Picks"))
        assert summary2["album_remove_failed"] == 1
        assert summary2["updated"] == 2

    def test_a_membership_read_403_degrades_to_add_only(self, tmp_path, transport, monkeypatch):
        import urllib.error
        db_path = self._album_setup(tmp_path, transport)

        def forbidden_read(_self, method, path, payload=None):
            if method == "POST" and path == "/api/search/metadata" and "albumIds" in payload:
                raise urllib.error.HTTPError(path, 403, "Forbidden", None, None)
            return transport(method, path, payload)

        monkeypatch.setattr(ImmichClient, "_request", forbidden_read)

        summary = sync_to_immich(db_path, _rejecting_config(top_picks_album="Facet Top Picks"))

        assert summary["album_remove_failed"] == 0
        adds = [payload for m, p, payload in transport.requests
                if m == "PUT" and p.startswith("/api/albums/")]
        assert adds == [{"ids": ["id-a"]}]  # add-only: id-c is below the threshold
        with sqlite3.connect(db_path) as conn:
            state = conn.execute(
                "SELECT value FROM stats_cache WHERE key = 'immich_synced_paths:global'"
            ).fetchone()[0]
        assert '/p/a.jpg' in state

    def test_dry_run_previews_album_removals_without_writing(self, tmp_path, transport):
        db_path = self._album_setup(tmp_path, transport)

        summary = sync_to_immich(db_path, _rejecting_config(top_picks_album="Facet Top Picks"),
                                 dry_run=True)

        # id-c provably sits below the threshold: the plan says one removal,
        # and the dry run issues no album writes at all.
        assert summary["album_removed"] == 1
        assert summary["album_added"] == 0
        assert summary["albums_created"] == 0
        assert [r for r in transport.requests if r[0] == "DELETE"] == []
        assert [r for r in transport.requests
                if r[0] == "PUT" and r[1].startswith("/api/albums/")] == []

    def test_summary_counts_album_adds_and_removals(self, tmp_path, transport):
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0), ('/p/b.jpg', 5, 0, 0),
                                     ('/p/c.jpg', 3, 0, 0)])
        transport.assets_by_path = {'/p/a.jpg': 'id-a', '/p/b.jpg': 'id-b', '/p/c.jpg': 'id-c'}
        transport.albums = [{"albumName": "Facet Top Picks", "id": "al"}]
        transport.album_assets = {'al': ['id-a', 'id-c']}

        summary = sync_to_immich(db_path, _rejecting_config(top_picks_album="Facet Top Picks"))

        # id-a stays a member (no re-add), id-b newly qualifies (added),
        # id-c provably dropped below the threshold (removed).
        assert summary["album_added"] == 1
        assert summary["album_removed"] == 1
        assert summary["album_remove_failed"] == 0


class TestAlbumMembershipRead:
    """/albums/:id stopped serving the asset list on current Immich; the
    membership diff must ride the same paged metadata search as everything
    else, filtered by albumIds."""

    def test_membership_read_uses_the_albumids_search(self, tmp_path, transport):
        db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0), ('/p/c.jpg', 3, 0, 0)])
        transport.assets_by_path = {'/p/a.jpg': 'id-a', '/p/c.jpg': 'id-c'}
        transport.albums = [{"albumName": "Facet Top Picks", "id": "al"}]
        transport.album_assets = {'al': ['id-a', 'id-c']}

        sync_to_immich(db_path, _rejecting_config(top_picks_album="Facet Top Picks"))

        searches = [payload for m, p, payload in transport.requests
                    if m == "POST" and p == "/api/search/metadata" and "albumIds" in payload]
        assert searches, "the membership read never hit the albumIds search"
        assert all(s["albumIds"] == ["al"] for s in searches)
        assert all("originalPath" not in s for s in searches)


@pytest.mark.parametrize('dry_run', [False, True])
@pytest.mark.parametrize('overlapping', [False, True])
def test_album_removal_refuses_ambiguous_or_non_roundtrip_paths(
        tmp_path, transport, dry_run, overlapping):
    rows = [('/nas/x.jpg', 2, 0, 0), ('/local/x.jpg', 5, 0, 0)]
    mappings = [
        {'facet_prefix': '/nas/', 'immich_prefix': '/photos/'},
        {'facet_prefix': '/local/', 'immich_prefix': '/photos/'},
    ]
    if overlapping:
        rows = [('/nas/sub/x.jpg', 2, 0, 0), ('/local/x.jpg', 5, 0, 0)]
        mappings[1]['immich_prefix'] = '/photos/sub/'
    db_path = make_db(tmp_path, rows)
    remote_path = '/photos/sub/x.jpg' if overlapping else '/photos/x.jpg'
    transport.assets_by_path = {remote_path: 'id-x'}
    transport.albums = [{'albumName': 'Facet Top Picks', 'id': 'al'}]
    transport.album_assets = {'al': ['id-x']}
    cfg = make_config(push={'ratings': True, 'favorites': True,
                            'top_picks_album': 'Facet Top Picks'})
    cfg['immich']['path_map'] = mappings

    summary = sync_to_immich(db_path, cfg, dry_run=dry_run)

    assert summary['identity_conflicts'] == 2
    assert summary['album_removed'] == 0
    assert not [r for r in transport.requests if r[0] == 'DELETE']


@pytest.mark.parametrize('dry_run', [False, True])
def test_album_removal_requires_forward_path_agreement(tmp_path, transport, dry_run):
    db_path = make_db(tmp_path, [('/nas/sub/x.jpg', 2, 0, 0)])
    transport.assets_by_path = {'/photos/sub/x.jpg': 'id-x'}
    transport.albums = [{'albumName': 'Facet Top Picks', 'id': 'al'}]
    transport.album_assets = {'al': ['id-x']}
    cfg = make_config(push={'ratings': True, 'favorites': True,
                            'top_picks_album': 'Facet Top Picks'})
    cfg['immich']['path_map'] = [
        {'facet_prefix': '/nas/sub/', 'immich_prefix': '/elsewhere/'},
        {'facet_prefix': '/nas/', 'immich_prefix': '/photos/'},
    ]

    summary = sync_to_immich(db_path, cfg, dry_run=dry_run)

    assert summary['album_removed'] == 0
    assert not [r for r in transport.requests if r[0] == 'DELETE']


@pytest.mark.parametrize('error', [urllib.error.URLError('offline'), TimeoutError('timeout')])
def test_webhook_network_failure_does_not_retry_each_asset(tmp_path, transport, monkeypatch, error):
    db_path = make_db(tmp_path, [('/p/a.jpg', 5, 0, 0), ('/p/b.jpg', 5, 0, 0)])
    with sqlite3.connect(db_path) as conn:
        conn.execute('UPDATE photos SET aggregate = 8')
    transport.assets_by_path = {'/p/a.jpg': 'id-a', '/p/b.jpg': 'id-b'}
    original = ImmichClient.update_assets
    calls = []

    def offline(self, ids, fields):
        calls.append(ids)
        raise error

    monkeypatch.setattr(ImmichClient, 'update_assets', offline)
    results = push_photo_updates(db_path, make_config(),
                                 [('/p/a.jpg', 'id-a'), ('/p/b.jpg', 'id-b')])
    assert calls == [['id-a', 'id-b']]
    assert results == [(RESULT_FAILED, error), (RESULT_FAILED, error)]
    monkeypatch.setattr(ImmichClient, 'update_assets', original)


def test_add_album_assets_quotes_album_id(monkeypatch):
    calls = []
    monkeypatch.setattr(ImmichClient, '_request',
                        lambda self, method, path, payload: calls.append((method, path, payload)))
    ImmichClient('http://immich.local', 'key').add_album_assets('a/b?', ['id'])
    assert calls == [('PUT', '/api/albums/a%2Fb%3F/assets', {'ids': ['id']})]
