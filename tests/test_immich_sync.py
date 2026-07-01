"""Tests for the one-way Immich push (sync/immich.py) — HTTP transport fully mocked."""

import sqlite3

import pytest

from db.schema import init_database
from sync.immich import ImmichClient, _effective_rating, map_facet_path, sync_to_immich


class FakeTransport:
    def __init__(self, assets_by_path=None, albums=None):
        self.assets_by_path = assets_by_path or {}
        self.albums = albums or []
        self.requests = []

    def __call__(self, method, path, payload=None):
        self.requests.append((method, path, payload))
        if method == "POST" and path == "/api/search/metadata":
            asset_id = self.assets_by_path.get(payload["originalPath"])
            items = [{"id": asset_id}] if asset_id else []
            return {"assets": {"items": items, "nextPage": None}}
        if method == "PUT" and path == "/api/assets":
            return None
        if method == "GET" and path == "/api/albums":
            return self.albums
        if method == "POST" and path == "/api/albums":
            return {"id": "album-new"}
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
                if path == "/api/search/metadata"]


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
        assert set(transport.searched_paths()) == {
            '/usr/src/app/upload/a.jpg', '/data/b.jpg',
        }

    def test_empty_or_placeholder_map_is_identity(self):
        assert map_facet_path('/x/y.jpg', []) == '/x/y.jpg'
        assert map_facet_path('/x/y.jpg', [{"facet_prefix": "", "immich_prefix": ""}]) == '/x/y.jpg'

    def test_search_miss_counts_unmatched(self, tmp_path, transport):
        db_path = make_db(tmp_path, [('/photos/gone.jpg', 5, 0, 0)])
        summary = sync_to_immich(db_path, make_config())
        assert summary == {"matched": 0, "unmatched": 1, "updated": 0,
                           "skipped_unrated": 0, "albums_created": 0}


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
        assert transport.requests == []
        assert summary["skipped_unrated"] == 1

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
        assert len(transport.searched_paths()) == 2
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
