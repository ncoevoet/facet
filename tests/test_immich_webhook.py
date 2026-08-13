"""Tests for the inbound Immich webhook (api/routers/immich.py).

Covers the env-sourced token auth (unset ⇒ 404, missing ⇒ 401, wrong /
non-ASCII ⇒ 403), the liberal payload parsing (unknown shape ⇒ 204, non-JSON
⇒ 400), the immediate single-asset push for a known scored photo, the bounded
pending list for one Facet has never scored, and the hard rule that a webhook
never spawns a scan.

The ``immich`` config block is patched in place on ``api.config._FULL_CONFIG``
(the object the router reads at call time) and the outbound HTTP transport is
replaced on ``ImmichClient._request`` — never ``mock.patch`` on an auth
dependency, and never a real socket.
"""

import os
import sqlite3

import pytest

from sync.immich import ImmichClient, load_pending_paths

DB_PATH = os.environ["DB_PATH"]

TOKEN = "immich-webhook-secret-abcdefghijklmnop"
NON_ASCII_TOKEN = "jeton-de-webhook-privé-é"
TOKEN_ENV = "FACET_TEST_IMMICH_WEBHOOK_TOKEN"
HEADER = "x-facet-token"

FACET_PREFIX = "/immichhook/"
IMMICH_PREFIX = "/usr/src/app/upload/"

WEBHOOK_URL = "/api/immich/webhook"

SCORED = FACET_PREFIX + "scored.jpg"
UNSCORED = FACET_PREFIX + "unscored.jpg"
MISSING = FACET_PREFIX + "never-scanned.jpg"

_MAX_PENDING = 3


def _immich_path(facet_path):
    return IMMICH_PREFIX + facet_path[len(FACET_PREFIX):]


class FakeTransport:
    """Stand-in for ``ImmichClient._request`` — records every call, opens no socket."""

    def __init__(self):
        self.assets_by_path = {_immich_path(SCORED): "asset-scored"}
        self.requests = []

    def __call__(self, method, path, payload=None):
        self.requests.append((method, path, payload))
        if method == "POST" and path == "/api/search/metadata":
            asset_id = self.assets_by_path.get(payload.get("originalPath"))
            items = [{"id": asset_id}] if asset_id else []
            return {"assets": {"items": items, "nextPage": None}}
        if method == "PUT" and path == "/api/assets":
            return None
        raise AssertionError(f"Unexpected request: {method} {path}")

    def asset_updates(self):
        return [payload for method, path, payload in self.requests
                if method == "PUT" and path == "/api/assets"]

    def searches(self):
        return [payload for method, path, payload in self.requests
                if path == "/api/search/metadata"]


def _seed_photos():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM photos WHERE path LIKE ?", (FACET_PREFIX + "%",))
    conn.executemany(
        "INSERT INTO photos (path, filename, star_rating, is_favorite, is_rejected, aggregate) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            (SCORED, "scored.jpg", 4, 1, 0, 8.2),
            (UNSCORED, "unscored.jpg", 5, 0, 0, None),
        ],
    )
    conn.commit()
    conn.close()


def _seed_extra_scored(names):
    """Seed extra scored rows under FACET_PREFIX; returns their Facet paths.

    The ``immich_cfg`` fixture's teardown drops everything under the prefix, so
    these need no cleanup of their own.
    """
    paths = [FACET_PREFIX + f"{name}.jpg" for name in names]
    conn = sqlite3.connect(DB_PATH)
    conn.executemany(
        "INSERT INTO photos (path, filename, star_rating, is_favorite, is_rejected, aggregate) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [(p, p.rsplit("/", 1)[-1], 3, 0, 0, 7.5) for p in paths],
    )
    conn.commit()
    conn.close()
    return paths


def _clear_side_state():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM stats_cache WHERE key LIKE 'immich_%'")
    conn.execute("DELETE FROM photos WHERE path LIKE ?", (FACET_PREFIX + "%",))
    conn.commit()
    conn.close()


@pytest.fixture()
def immich_cfg(monkeypatch):
    """Install an enabled ``immich`` block + its env secret, restoring the prior one."""
    from api import config

    prev = config._FULL_CONFIG.get("immich")
    config._FULL_CONFIG["immich"] = {
        "url": "http://immich.test:2283",
        "api_key": "test-key",
        "path_map": [{"facet_prefix": FACET_PREFIX, "immich_prefix": IMMICH_PREFIX}],
        "push": {"ratings": True, "favorites": True, "rejected": False,
                 "top_picks_album": "", "top_picks_min_rating": 4},
        "webhook": {"token_env": TOKEN_ENV, "header": HEADER, "max_pending": _MAX_PENDING},
        "timeout_seconds": 5,
    }
    monkeypatch.setenv(TOKEN_ENV, TOKEN)
    _seed_photos()
    yield config._FULL_CONFIG["immich"]
    _clear_side_state()
    if prev is None:
        config._FULL_CONFIG.pop("immich", None)
    else:
        config._FULL_CONFIG["immich"] = prev


@pytest.fixture()
def transport(monkeypatch):
    fake = FakeTransport()
    monkeypatch.setattr(ImmichClient, "_request", fake)
    return fake


def _post(client, body, token=TOKEN, header=HEADER, **kwargs):
    headers = {header: token} if token else {}
    return client.post(WEBHOOK_URL, headers=headers, **({"json": body} if body is not None else kwargs))


def _asset(facet_path, asset_id=None):
    asset = {"originalPath": _immich_path(facet_path)}
    if asset_id:
        asset["id"] = asset_id
    return {"event": "asset.upload", "asset": asset}


class TestShippedDefaults:
    def test_endpoint_is_off_with_the_shipped_config(self, client):
        # No immich_cfg fixture: this is scoring_config.json as it ships, whose
        # webhook.token_env is empty. An open install must not accept webhooks.
        assert client.post(WEBHOOK_URL, json={"originalPath": "/x.jpg"}).status_code == 404

    def test_get_never_reaches_the_handler(self, client, immich_cfg):
        # POST-only: a GET falls through to the SPA catch-all as a 404. The
        # point is that it is a client error, never a 5xx from the handler.
        assert client.get(WEBHOOK_URL).status_code in (404, 405)


class TestAuth:
    def test_unset_token_env_disables_the_endpoint(self, client, immich_cfg, monkeypatch):
        monkeypatch.delenv(TOKEN_ENV, raising=False)
        assert _post(client, _asset(SCORED)).status_code == 404

    def test_empty_token_env_name_disables_the_endpoint(self, client, immich_cfg):
        immich_cfg["webhook"]["token_env"] = ""
        assert _post(client, _asset(SCORED)).status_code == 404

    def test_missing_token_is_unauthorized(self, client, immich_cfg):
        assert client.post(WEBHOOK_URL, json=_asset(SCORED)).status_code == 401

    def test_wrong_token_is_forbidden(self, client, immich_cfg):
        assert _post(client, _asset(SCORED), token="nope").status_code == 403

    def test_non_ascii_configured_token_rejects_cleanly(self, client, immich_cfg, monkeypatch):
        # A header value is ASCII by protocol, so a non-ASCII secret can only
        # ever come from the config side; comparing it must be a 403, not the
        # 500 a str-vs-bytes compare_digest would raise.
        monkeypatch.setenv(TOKEN_ENV, NON_ASCII_TOKEN)
        assert _post(client, _asset(SCORED), token="whatever").status_code == 403

    def test_bearer_header_is_accepted(self, client, immich_cfg, transport):
        resp = client.post(WEBHOOK_URL, json=_asset(SCORED),
                           headers={"Authorization": f"Bearer {TOKEN}"})
        assert resp.status_code == 202

    def test_custom_header_name_is_honored(self, client, immich_cfg, transport):
        immich_cfg["webhook"]["header"] = "x-immich-signature"
        assert _post(client, _asset(SCORED), header="x-immich-signature").status_code == 202
        # The default header no longer carries the token, so it must be rejected.
        assert _post(client, _asset(SCORED), header=HEADER).status_code == 401

    def test_auth_is_checked_before_the_body_is_parsed(self, client, immich_cfg, transport):
        resp = client.post(WEBHOOK_URL, content=b"not json", headers={HEADER: "nope"})
        assert resp.status_code == 403
        assert transport.requests == []


class TestPayloadShapes:
    def test_non_json_body_is_a_clean_400(self, client, immich_cfg, transport):
        resp = client.post(WEBHOOK_URL, content=b"<<<not json>>>", headers={HEADER: TOKEN})
        assert resp.status_code == 400
        assert "traceback" not in resp.text.lower()
        assert transport.requests == []

    def test_unknown_shape_is_a_silent_204(self, client, immich_cfg, transport):
        resp = _post(client, {"event": "server.start", "payload": {"version": "3.0.0"}})
        assert resp.status_code == 204
        assert resp.content == b""
        assert transport.requests == []

    def test_json_scalar_body_is_a_silent_204(self, client, immich_cfg, transport):
        assert _post(client, "ping").status_code == 204

    @pytest.mark.parametrize("body", [
        {"originalPath": IMMICH_PREFIX + "scored.jpg"},
        {"asset": {"originalPath": IMMICH_PREFIX + "scored.jpg"}},
        {"data": {"assets": [{"originalPath": IMMICH_PREFIX + "scored.jpg"}]}},
        [{"originalPath": IMMICH_PREFIX + "scored.jpg"}],
    ])
    def test_liberal_shapes_all_reach_the_same_asset(self, client, immich_cfg, transport, body):
        resp = _post(client, body)
        assert resp.status_code == 202
        assert resp.json()["pushed"] == 1


class TestKnownScoredAsset:
    def test_pushes_exactly_one_update_with_the_current_rating(self, client, immich_cfg, transport):
        resp = _post(client, _asset(SCORED, asset_id="asset-scored"))
        assert resp.status_code == 202
        assert resp.json() == {"received": 1, "pushed": 1, "skipped": 0,
                               "pending": 0, "unmatched": 0, "failed": 0}
        assert transport.asset_updates() == [
            {"ids": ["asset-scored"], "rating": 4, "isFavorite": True}
        ]

    def test_payload_asset_id_skips_the_search_round_trip(self, client, immich_cfg, transport):
        _post(client, _asset(SCORED, asset_id="asset-scored"))
        assert transport.searches() == []

    def test_missing_asset_id_falls_back_to_a_path_search(self, client, immich_cfg, transport):
        _post(client, _asset(SCORED))
        assert transport.searches() == [{"originalPath": _immich_path(SCORED), "page": 1}]
        assert transport.asset_updates()[0]["ids"] == ["asset-scored"]

    def test_push_records_synced_state_so_a_later_clear_is_detected(self, client, immich_cfg, transport):
        _post(client, _asset(SCORED, asset_id="asset-scored"))
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT value FROM stats_cache WHERE key = 'immich_synced_paths:global'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert SCORED in row[0]

    def test_unresolvable_asset_counts_unmatched_without_pending(self, client, immich_cfg, transport):
        transport.assets_by_path = {}
        resp = _post(client, _asset(SCORED))
        assert resp.json()["unmatched"] == 1
        assert resp.json()["pending"] == 0
        assert load_pending_paths(DB_PATH) == []


class TestPendingList:
    def test_unscanned_asset_lands_in_the_pending_list(self, client, immich_cfg, transport):
        resp = _post(client, _asset(MISSING, asset_id="asset-new"))
        assert resp.status_code == 202
        assert resp.json()["pending"] == 1
        assert load_pending_paths(DB_PATH) == [MISSING]
        assert transport.asset_updates() == []

    def test_scanned_but_unscored_asset_is_pending_too(self, client, immich_cfg, transport):
        _post(client, _asset(UNSCORED, asset_id="asset-unscored"))
        assert load_pending_paths(DB_PATH) == [UNSCORED]
        assert transport.asset_updates() == []

    def test_repeat_deliveries_dedup(self, client, immich_cfg, transport):
        for _ in range(3):
            _post(client, _asset(MISSING))
        assert load_pending_paths(DB_PATH) == [MISSING]

    def test_pending_list_is_bounded_dropping_the_oldest(self, client, immich_cfg, transport):
        paths = [FACET_PREFIX + f"new-{i}.jpg" for i in range(_MAX_PENDING + 2)]
        for path in paths:
            _post(client, _asset(path))
        assert load_pending_paths(DB_PATH) == paths[-_MAX_PENDING:]

    def test_one_delivery_is_bounded_server_side(self, client, immich_cfg, transport):
        from api.routers.immich import _MAX_ASSETS_PER_DELIVERY

        oversized = [{"originalPath": _immich_path(FACET_PREFIX + f"bulk-{i}.jpg")}
                     for i in range(_MAX_ASSETS_PER_DELIVERY + 5)]
        resp = _post(client, oversized)
        assert resp.json()["received"] == _MAX_ASSETS_PER_DELIVERY

    def test_webhook_never_spawns_a_scan(self, client, immich_cfg, transport, monkeypatch):
        # Popen is the single choke point every subprocess helper (run, call,
        # check_output) funnels through, so patching it catches an
        # attribute-style call from any module — but it cannot see a
        # ``from subprocess import run`` binding, which is why the patch alone
        # would be a guard that can never fire. The real assertion is the
        # second half: an unknown asset leaves the library exactly as it was,
        # queued as inert data. A scan would have to add a photos row or a
        # scan_runs row to be worth anything.
        import subprocess

        def explode(*args, **kwargs):
            raise AssertionError("the webhook must never spawn a process")

        monkeypatch.setattr(subprocess, "Popen", explode)
        conn = sqlite3.connect(DB_PATH)
        scans_before = conn.execute("SELECT COUNT(*) FROM scan_runs").fetchone()[0]
        conn.close()

        assert _post(client, _asset(MISSING)).status_code == 202

        conn = sqlite3.connect(DB_PATH)
        photo_rows = conn.execute(
            "SELECT COUNT(*) FROM photos WHERE path = ?", (MISSING,)).fetchone()[0]
        scans_after = conn.execute("SELECT COUNT(*) FROM scan_runs").fetchone()[0]
        conn.close()
        assert photo_rows == 0
        assert scans_after == scans_before
        assert load_pending_paths(DB_PATH) == [MISSING]


class TestPathMapping:
    def test_path_outside_the_map_is_unmatched(self, client, immich_cfg, transport):
        resp = _post(client, {"asset": {"originalPath": "/somewhere/else/x.jpg"}})
        assert resp.status_code == 202
        assert resp.json()["unmatched"] == 1
        assert load_pending_paths(DB_PATH) == []
        assert transport.requests == []


class TestPushFailures:
    def test_network_error_is_counted_not_raised(self, client, immich_cfg, monkeypatch):
        import urllib.error

        def failing(_self, method, path, payload=None):
            raise urllib.error.URLError("connection refused")

        monkeypatch.setattr(ImmichClient, "_request", failing)
        resp = _post(client, _asset(SCORED))
        assert resp.status_code == 202
        assert resp.json()["failed"] == 1

    def test_unconfigured_api_key_is_counted_not_raised(self, client, immich_cfg, transport):
        immich_cfg["api_key"] = ""
        resp = _post(client, _asset(SCORED))
        assert resp.status_code == 202
        assert resp.json()["failed"] == 1
        assert transport.requests == []

    def test_one_dropped_connection_does_not_abort_the_delivery(
            self, client, immich_cfg, monkeypatch):
        # RemoteDisconnected is an http.client.HTTPException — a class the
        # per-asset handler used to miss entirely, so a keep-alive Immich
        # dropping one connection 500-ed a delivery whose earlier assets had
        # already been pushed.
        from http.client import RemoteDisconnected

        boom, = _seed_extra_scored(["boom"])
        fake = FakeTransport()
        fake.assets_by_path[_immich_path(boom)] = "asset-boom"

        def flaky(_self, method, path, payload=None):
            if method == "PUT" and payload.get("ids") == ["asset-boom"]:
                raise RemoteDisconnected("Remote end closed connection")
            return fake(method, path, payload)

        monkeypatch.setattr(ImmichClient, "_request", flaky)
        resp = _post(client, [{"originalPath": _immich_path(boom), "id": "asset-boom"},
                              {"originalPath": _immich_path(SCORED), "id": "asset-scored"}])
        assert resp.status_code == 202
        assert resp.json()["failed"] == 1
        # The asset after the failure still reached Immich.
        assert resp.json()["pushed"] == 1
        assert fake.asset_updates() == [
            {"ids": ["asset-scored"], "rating": 4, "isFavorite": True}
        ]

    def test_an_unreadable_database_fails_every_asset_cleanly(
            self, client, immich_cfg, transport, monkeypatch):
        # sqlite3.Error was the other class the handler missed: the read phase
        # is delivery-wide, so it must tally every asset as failed rather than
        # escape as a 500.
        from sync import immich as sync_immich

        def unreadable(*args, **kwargs):
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(sync_immich, "_fetch_scored_photos", unreadable)
        resp = _post(client, [_asset(SCORED)["asset"], _asset(UNSCORED)["asset"]])
        assert resp.status_code == 202
        assert resp.json()["failed"] == 2
        assert transport.requests == []


class TestDeliveryBatching:
    """One delivery costs one pass over the side-table blobs, whatever its size.

    Regression: ``_process_assets`` called ``push_photo_update`` per asset, and
    each call opened two fresh connections and round-tripped the ENTIRE
    ``immich_synced_paths`` blob — a document that grows with the library — so
    an N-asset delivery cost 2N connections and 2N JSON parses, plus a third
    connection per unknown asset for the pending list.
    """

    @staticmethod
    def _instrument(monkeypatch):
        """Count the state round trips a delivery makes; returns the tally dict."""
        from sync import immich as sync_immich

        calls = {"connections": 0, "load_state": 0, "save_state": 0, "save_pending": 0}
        originals = {name: getattr(sync_immich, name) for name in
                     ("get_connection", "_load_synced_state", "_save_synced_state",
                      "_save_pending")}

        def wrap(name, key):
            def counted(*args, **kwargs):
                calls[key] += 1
                return originals[name](*args, **kwargs)
            monkeypatch.setattr(sync_immich, name, counted)

        wrap("get_connection", "connections")
        wrap("_load_synced_state", "load_state")
        wrap("_save_synced_state", "save_state")
        wrap("_save_pending", "save_pending")
        return calls

    @pytest.mark.parametrize("size", [1, 5])
    def test_state_round_trips_do_not_grow_with_the_delivery(
            self, client, immich_cfg, transport, monkeypatch, size):
        paths = _seed_extra_scored([f"batch{i}" for i in range(size)])
        assets = []
        for i, path in enumerate(paths):
            transport.assets_by_path[_immich_path(path)] = f"asset-batch{i}"
            assets.append({"originalPath": _immich_path(path), "id": f"asset-batch{i}"})
        calls = self._instrument(monkeypatch)

        resp = _post(client, {"assets": assets})

        assert resp.json()["pushed"] == size
        # Two connections and two loads for ANY size: one read pass (rows +
        # synced state), then one serialized transaction that re-reads the blob
        # so a delivery landing meanwhile is merged rather than clobbered.
        assert calls["connections"] == 2
        assert calls["load_state"] == 2
        assert calls["save_state"] == 1

    def test_unknown_assets_share_one_pending_write(
            self, client, immich_cfg, transport, monkeypatch):
        unknown = [FACET_PREFIX + f"never-seen-{i}.jpg" for i in range(_MAX_PENDING)]
        calls = self._instrument(monkeypatch)

        resp = _post(client, [{"originalPath": _immich_path(p)} for p in unknown])

        assert resp.json()["pending"] == len(unknown)
        # One read pass + one pending write; nothing was pushed, so the synced
        # state is never written at all. Asserted before the read-back below,
        # which would itself open a (counted) connection.
        assert calls["connections"] == 2
        assert calls["save_pending"] == 1
        assert calls["save_state"] == 0
        assert load_pending_paths(DB_PATH) == unknown
