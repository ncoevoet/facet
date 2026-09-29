"""Tests for api/routers/lightroom.py (Step 10 of the Lightroom-flow spec).

Covers: edition gating, manifest scope resolution (explicit paths vs
filters+exclude), pending_corrections + attachment header on the manifest
download, and the import endpoint's validation ordering (format/version
before any write), size/count caps, and multi-user scoping.
"""

import json
import sqlite3
from unittest import mock

import pytest

from db import DEFAULT_DB_PATH


PREFIX = "/lr-router-test/"


@pytest.fixture()
def lr_photos(seed_photos_prefix):
    rows = [
        {"path": PREFIX + "a.jpg", "filename": "a.jpg", "aggregate": 8.0,
         "category": "default", "star_rating": 2, "is_favorite": 1, "is_rejected": 0},
        {"path": PREFIX + "b.jpg", "filename": "b.jpg", "aggregate": 5.0,
         "category": "default", "star_rating": 0, "is_favorite": 0, "is_rejected": 0},
    ]
    return seed_photos_prefix(PREFIX, rows)


# --- Auth gating ---

class TestAuthGating:
    def test_manifest_anonymous_401(self, anonymous_client):
        resp = anonymous_client.post("/api/lightroom/manifest", json={"paths": ["/x.jpg"]})
        assert resp.status_code == 401

    def test_manifest_regular_user_403(self, regular_client):
        resp = regular_client.post("/api/lightroom/manifest", json={"paths": ["/x.jpg"]})
        assert resp.status_code == 403

    def test_import_anonymous_401(self, anonymous_client):
        resp = anonymous_client.post(
            "/api/lightroom/import",
            json={"format": "facet-lightroom-state", "version": 1, "photos": []},
        )
        assert resp.status_code == 401

    def test_import_regular_user_403(self, regular_client):
        resp = regular_client.post(
            "/api/lightroom/import",
            json={"format": "facet-lightroom-state", "version": 1, "photos": []},
        )
        assert resp.status_code == 403


# --- Manifest download ---

class TestManifestDownload:
    def test_scoped_by_explicit_paths(self, edition_client, lr_photos):
        resp = edition_client.post(
            "/api/lightroom/manifest", json={"paths": [PREFIX + "a.jpg"]},
        )
        assert resp.status_code == 200
        body = resp.json()
        paths = [p["path"] for p in body["photos"]]
        assert paths == [PREFIX + "a.jpg"]

    def test_scoped_by_filters_and_exclude(self, edition_client, lr_photos):
        resp = edition_client.post(
            "/api/lightroom/manifest",
            json={
                "filters": {"path_prefix": PREFIX},
                "exclude": [PREFIX + "b.jpg"],
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        paths = {p["path"] for p in body["photos"]}
        assert paths == {PREFIX + "a.jpg"}

    def test_carries_pending_corrections_field(self, edition_client, lr_photos):
        resp = edition_client.post(
            "/api/lightroom/manifest", json={"paths": [PREFIX + "a.jpg"]},
        )
        assert resp.status_code == 200
        assert "pending_corrections" in resp.json()

    def test_attachment_header(self, edition_client, lr_photos):
        resp = edition_client.post(
            "/api/lightroom/manifest", json={"paths": [PREFIX + "a.jpg"]},
        )
        assert resp.headers["content-disposition"] == \
            'attachment; filename="facet_manifest.json"'

    def test_neither_paths_nor_filters_400(self, edition_client):
        resp = edition_client.post("/api/lightroom/manifest", json={})
        assert resp.status_code == 400

    def test_expands_selection_to_full_burst_group(self, edition_client, seed_photos_prefix):
        """I8: a selection that resolves to only a burst's lead must still
        carry every other frame of that burst -- otherwise buildGroupIndex in
        the plug-in sees a group of 1 and pick/reject never fires."""
        prefix = "/lr-router-burst/"
        rows = [
            {"path": prefix + "lead.jpg", "filename": "lead.jpg", "aggregate": 8.0,
             "category": "default", "burst_group_id": 42, "is_burst_lead": 1},
            {"path": prefix + "sib1.jpg", "filename": "sib1.jpg", "aggregate": 7.0,
             "category": "default", "burst_group_id": 42, "is_burst_lead": 0},
            {"path": prefix + "sib2.jpg", "filename": "sib2.jpg", "aggregate": 6.0,
             "category": "default", "burst_group_id": 42, "is_burst_lead": 0},
        ]
        seed_photos_prefix(prefix, rows)

        resp = edition_client.post(
            "/api/lightroom/manifest", json={"paths": [prefix + "lead.jpg"]},
        )
        assert resp.status_code == 200
        paths = {p["path"] for p in resp.json()["photos"]}
        assert paths == {prefix + "lead.jpg", prefix + "sib1.jpg", prefix + "sib2.jpg"}

    def test_expands_selection_to_full_sequence_group(self, edition_client, seed_photos_prefix):
        """I8, sequence (bracket/panorama) side: same expansion, filtered by
        sequence_kind before grouping by sequence_group_id (CLAUDE.md)."""
        prefix = "/lr-router-seq/"
        rows = [
            {"path": prefix + "base.jpg", "filename": "base.jpg", "aggregate": 8.0,
             "category": "default", "sequence_kind": "bracket", "sequence_group_id": 7},
            {"path": prefix + "dark.jpg", "filename": "dark.jpg", "aggregate": 6.0,
             "category": "default", "sequence_kind": "bracket", "sequence_group_id": 7},
            {"path": prefix + "bright.jpg", "filename": "bright.jpg", "aggregate": 6.5,
             "category": "default", "sequence_kind": "bracket", "sequence_group_id": 7},
        ]
        seed_photos_prefix(prefix, rows)

        resp = edition_client.post(
            "/api/lightroom/manifest", json={"paths": [prefix + "base.jpg"]},
        )
        assert resp.status_code == 200
        paths = {p["path"] for p in resp.json()["photos"]}
        assert paths == {prefix + "base.jpg", prefix + "dark.jpg", prefix + "bright.jpg"}

    def test_manifest_scopes_ratings_to_the_calling_user(
        self, monkeypatch, seed_photos_prefix,
    ):
        """I9.6 / G8: a multi-user manifest must carry the CALLER's own
        ratings (user_preferences), never a different or absent user's.

        The ``photos`` row goes through the shared ``seed_photos_prefix``
        fixture (its teardown cleans every table it knows about for the
        prefix) rather than a hand-rolled insert/delete; only the
        ``user_preferences`` row -- which that fixture does not seed -- is
        written and cleaned up here directly."""
        from api.auth import CurrentUser, get_optional_user, require_authenticated, \
            require_edition, require_superadmin
        from starlette.testclient import TestClient

        from api import create_app

        monkeypatch.setattr("api.config.is_multi_user_enabled", lambda: True)

        prefix = "/lr-router-scope/"
        seed_photos_prefix(prefix, [
            {"path": prefix + "a.jpg", "filename": "a.jpg", "aggregate": 8.0,
             "category": "default", "star_rating": 0, "is_favorite": 0, "is_rejected": 0},
        ])
        conn = sqlite3.connect(DEFAULT_DB_PATH)
        conn.execute(
            "INSERT OR REPLACE INTO user_preferences (user_id, photo_path, star_rating, "
            "is_favorite, is_rejected) VALUES ('alice', ?, 5, 1, 0)",
            (prefix + "a.jpg",),
        )
        conn.commit()
        conn.close()
        try:
            user = CurrentUser(user_id="alice", role="user", edition_authenticated=True)
            app = create_app()
            for dep in (require_edition, require_authenticated, require_superadmin,
                        get_optional_user):
                app.dependency_overrides[dep] = lambda u=user: u
            client = TestClient(app)

            resp = client.post(
                "/api/lightroom/manifest", json={"paths": [prefix + "a.jpg"]},
            )
            app.dependency_overrides.clear()
            assert resp.status_code == 200
            photo = resp.json()["photos"][0]
            assert (photo["star_rating"], photo["is_favorite"]) == (5, True)
        finally:
            conn = sqlite3.connect(DEFAULT_DB_PATH)
            conn.execute("DELETE FROM user_preferences WHERE photo_path LIKE ?", (prefix + "%",))
            conn.commit()
            conn.close()

    def test_excluded_path_stays_excluded_after_set_expansion(
        self, edition_client, seed_photos_prefix,
    ):
        """Exclude must "only ever narrow" even across expansion --
        a burst sibling explicitly excluded must not be re-added by
        _expand_to_full_sets pulling in every frame of the lead's burst."""
        prefix = "/lr-router-excl/"
        rows = [
            {"path": prefix + "lead.jpg", "filename": "lead.jpg", "aggregate": 8.0,
             "category": "default", "burst_group_id": 55, "is_burst_lead": 1},
            {"path": prefix + "sib1.jpg", "filename": "sib1.jpg", "aggregate": 7.0,
             "category": "default", "burst_group_id": 55, "is_burst_lead": 0},
        ]
        seed_photos_prefix(prefix, rows)

        resp = edition_client.post(
            "/api/lightroom/manifest",
            json={"paths": [prefix + "lead.jpg", prefix + "sib1.jpg"],
                  "exclude": [prefix + "sib1.jpg"]},
        )
        assert resp.status_code == 200
        paths = {p["path"] for p in resp.json()["photos"]}
        assert paths == {prefix + "lead.jpg"}

    def test_expansion_past_the_cap_is_refused_412(self, edition_client, seed_photos_prefix):
        """The cap must be re-checked AFTER expansion, since a
        burst/sequence expansion can grow a selection well past a cap that
        only bounded it before expansion."""
        from api.routers import lightroom as lr_module
        prefix = "/lr-router-cap/"
        rows = [
            {"path": prefix + "lead.jpg", "filename": "lead.jpg", "aggregate": 8.0,
             "category": "default", "burst_group_id": 77, "is_burst_lead": 1},
            {"path": prefix + "sib1.jpg", "filename": "sib1.jpg", "aggregate": 7.0,
             "category": "default", "burst_group_id": 77, "is_burst_lead": 0},
            {"path": prefix + "sib2.jpg", "filename": "sib2.jpg", "aggregate": 6.0,
             "category": "default", "burst_group_id": 77, "is_burst_lead": 0},
        ]
        seed_photos_prefix(prefix, rows)

        with mock.patch.object(lr_module, "_MANIFEST_EXPANDED_MAX", 2):
            resp = edition_client.post(
                "/api/lightroom/manifest", json={"paths": [prefix + "lead.jpg"]},
            )
        assert resp.status_code == 412
        assert "narrow the selection" in resp.json()["detail"].lower()

    def test_visibility_excludes_invisible_explicit_path(self, edition_client, seed_photos_prefix):
        """The explicit-``paths`` branch is not itself
        visibility-scoped (it returns the caller's list verbatim), so a path
        outside the caller's visibility must be dropped before it ever
        reaches the manifest."""
        prefix = "/lr-router-vis/"
        rows = [
            {"path": prefix + "visible.jpg", "filename": "visible.jpg", "aggregate": 8.0,
             "category": "default"},
            {"path": prefix + "hidden.jpg", "filename": "hidden.jpg", "aggregate": 7.0,
             "category": "default"},
        ]
        seed_photos_prefix(prefix, rows)

        restricted = (f"photos.path LIKE '{prefix}visible%'", [])
        with (
            mock.patch("api.routers.lightroom.get_visibility_clause", return_value=restricted),
            mock.patch("api.routers.export.get_visibility_clause", return_value=restricted),
        ):
            resp = edition_client.post(
                "/api/lightroom/manifest",
                json={"paths": [prefix + "visible.jpg", prefix + "hidden.jpg"]},
            )
        assert resp.status_code == 200
        paths = {p["path"] for p in resp.json()["photos"]}
        assert paths == {prefix + "visible.jpg"}

    def test_expansion_chunking_survives_more_than_one_chunk(
        self, edition_client, seed_photos_prefix, monkeypatch,
    ):
        """Shrink _SQLITE_VAR_LIMIT to force the paths/burst_ids
        chunk loops in _expand_to_full_sets to run more than once, and assert
        the burst is still fully expanded across the chunk boundary."""
        from api.routers import lightroom as lr_module
        monkeypatch.setattr(lr_module, "_SQLITE_VAR_LIMIT", 2)

        prefix = "/lr-router-chunk/"
        # Three bursts, one lead each: the three leads span two path chunks
        # and the three burst ids span two id chunks, so a chunk the loop
        # skipped leaves a whole burst out of the expansion.
        rows = [
            {"path": prefix + f"b{burst}_{i}.jpg", "filename": f"b{burst}_{i}.jpg",
             "aggregate": float(i), "category": "default", "burst_group_id": 910000 + burst,
             "is_burst_lead": 1 if i == 0 else 0}
            for burst in range(3) for i in range(2)
        ]
        seed_photos_prefix(prefix, rows)

        resp = edition_client.post(
            "/api/lightroom/manifest",
            json={"paths": [r["path"] for r in rows if r["is_burst_lead"]]},
        )
        assert resp.status_code == 200
        paths = {p["path"] for p in resp.json()["photos"]}
        assert paths == {r["path"] for r in rows}

    def test_visibility_excludes_invisible_burst_sibling(self, edition_client, seed_photos_prefix):
        """Set expansion must not pull in a burst sibling outside
        the caller's visibility, even though the lead itself is visible."""
        prefix = "/lr-router-vis-burst/"
        rows = [
            {"path": prefix + "lead.jpg", "filename": "lead.jpg", "aggregate": 8.0,
             "category": "default", "burst_group_id": 88, "is_burst_lead": 1},
            {"path": prefix + "hidden_sib.jpg", "filename": "hidden_sib.jpg", "aggregate": 7.0,
             "category": "default", "burst_group_id": 88, "is_burst_lead": 0},
        ]
        seed_photos_prefix(prefix, rows)

        restricted = (f"photos.path LIKE '{prefix}lead%'", [])
        with (
            mock.patch("api.routers.lightroom.get_visibility_clause", return_value=restricted),
            mock.patch("api.routers.export.get_visibility_clause", return_value=restricted),
        ):
            resp = edition_client.post(
                "/api/lightroom/manifest", json={"paths": [prefix + "lead.jpg"]},
            )
        assert resp.status_code == 200
        paths = {p["path"] for p in resp.json()["photos"]}
        assert paths == {prefix + "lead.jpg"}


# --- Import ---

class TestImport:
    def test_wrong_format_400_and_nothing_written(self, edition_client, lr_photos):
        before = _rating(lr_photos[0]["path"])
        resp = edition_client.post(
            "/api/lightroom/import",
            json={"format": "not-a-real-format", "version": 1, "photos": []},
        )
        assert resp.status_code == 400
        assert _rating(lr_photos[0]["path"]) == before

    def test_oversized_photo_count_413(self, edition_client):
        from api.routers import lightroom as lr_module
        photos = [{"path": f"/x/{i}.jpg", "rating": 1} for i in range(lr_module._IMPORT_MAX_PHOTOS + 1)]
        resp = edition_client.post(
            "/api/lightroom/import",
            json={"format": "facet-lightroom-state", "version": 1, "photos": photos},
        )
        assert resp.status_code == 413

    def test_oversized_body_413(self, edition_client, monkeypatch):
        """I9.4 / G3: the raw-body-size guard, distinct from the photo-count
        guard (G2, already covered). Shrink the cap so a tiny valid body
        trips it."""
        from api.routers import lightroom as lr_module
        monkeypatch.setattr(lr_module, "_IMPORT_MAX_BODY_BYTES", 10)
        resp = edition_client.post(
            "/api/lightroom/import",
            json={"format": "facet-lightroom-state", "version": 1, "photos": []},
        )
        assert resp.status_code == 413

    def test_second_record_invalid_rejects_whole_batch_before_write(
        self, edition_client, lr_photos,
    ):
        """I9.3 / G5: per-record validation must run for EVERY record before
        any write -- a valid first record followed by a malformed second must
        400 and leave the first photo's row untouched (previously only
        `photos: []` was exercised, which is vacuous)."""
        before = _rating(lr_photos[0]["path"])
        resp = edition_client.post(
            "/api/lightroom/import",
            json={
                "format": "facet-lightroom-state",
                "version": 1,
                "photos": [
                    {"path": lr_photos[0]["path"], "rating": 3},
                    {"path": PREFIX + "b.jpg", "rating": 9},
                ],
            },
        )
        assert resp.status_code == 400
        assert _rating(lr_photos[0]["path"]) == before

    def test_import_invalidates_stats_cache(self, edition_client, lr_photos):
        """I9.5 / G7: a changed import must clear the primed stats cache."""
        from api import config as api_config
        api_config._stats_cache["probe"] = {"data": "stale", "expires": 1e18}

        resp = edition_client.post(
            "/api/lightroom/import",
            json={
                "format": "facet-lightroom-state",
                "version": 1,
                "photos": [{"path": lr_photos[0]["path"], "rating": 4}],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["changed"] == 1
        assert "probe" not in api_config._stats_cache

    def test_oversized_body_413_without_content_length(self, monkeypatch):
        """A chunked body with no Content-Length header must be refused as
        soon as the streamed byte count crosses the cap, WITHOUT the ASGI
        receive callable being drained to the end -- proving the abort is
        early, not merely that the eventual status is 413 (which
        ``raw = await request.body(); if len(raw) > cap: 413`` also returns,
        after buffering the entire body first).

        Drives the app directly over the raw ASGI ``(scope, receive, send)``
        interface (bypassing TestClient/httpx, whose transport reads a
        generator body to completion into an internal buffer before handing
        anything to the app) with a ``receive()`` that hands out many small
        chunks. Counting the calls made to it before the 413 lets the
        assertion tell an early abort apart from a full drain. Auth is
        satisfied via ``app.dependency_overrides`` on ``require_edition``,
        never ``mock.patch`` on the dependency itself (CLAUDE.md)."""
        import asyncio

        from api.auth import CurrentUser, require_edition
        from api.routers import lightroom as lr_module

        from api import create_app

        monkeypatch.setattr(lr_module, "_IMPORT_MAX_BODY_BYTES", 10)

        app = create_app()
        user = CurrentUser(user_id="test", role="admin", edition_authenticated=True)
        app.dependency_overrides[require_edition] = lambda: user

        # A body many times over the (shrunk) 10-byte cap, split into a large
        # number of tiny chunks -- crossing the cap takes only ~3 chunks, so
        # a handler that stops early consumes a small fraction of them.
        payload = json.dumps({
            "format": "facet-lightroom-state", "version": 1,
            "photos": [{"path": f"/x/{i}.jpg"} for i in range(2000)],
        }).encode()
        chunk_size = 4
        total_chunks = (len(payload) + chunk_size - 1) // chunk_size
        assert total_chunks > 100  # sanity: plenty of chunks to under-consume

        consumed = 0

        async def receive():
            nonlocal consumed
            start = consumed * chunk_size
            piece = payload[start:start + chunk_size]
            consumed += 1
            more_body = consumed * chunk_size < len(payload)
            return {"type": "http.request", "body": piece, "more_body": more_body}

        response = {}

        async def send(message):
            if message["type"] == "http.response.start":
                response["status"] = message["status"]

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/lightroom/import",
            "raw_path": b"/api/lightroom/import",
            "query_string": b"",
            "root_path": "",
            "headers": [(b"content-type", b"application/json")],
            "client": ("testclient", 0),
            "server": ("testserver", 80),
            "state": {},
        }

        try:
            asyncio.run(app(scope, receive, send))
        finally:
            app.dependency_overrides.clear()

        assert response["status"] == 413
        # The proof: the handler stopped far short of draining every chunk.
        # Reverting the handler to `raw = await request.body(); if len(raw) >
        # cap: 413` makes this fail -- request.body() drains `receive()` to
        # `more_body: False` before its length check ever runs, so
        # `consumed` would equal `total_chunks`.
        assert consumed < total_chunks // 10

    def test_visibility_scoped_import_treats_out_of_scope_record_as_unmatched(
        self, edition_client, lr_photos,
    ):
        """A record matching a real, in-DB photo outside the
        caller's visible directories must be counted unmatched and left
        unwritten -- never usable as an existence oracle or a write target."""
        before = _rating(lr_photos[1]["path"])
        restricted = (f"photos.path LIKE '{PREFIX}a%'", [])
        with mock.patch("api.routers.lightroom.get_visibility_clause", return_value=restricted):
            resp = edition_client.post(
                "/api/lightroom/import",
                json={
                    "format": "facet-lightroom-state",
                    "version": 1,
                    "photos": [{"path": lr_photos[1]["path"], "rating": 5}],  # b.jpg, out of scope
                },
            )
        assert resp.status_code == 200
        assert resp.json() == {"matched": 0, "unmatched": 1, "changed": 0}
        assert _rating(lr_photos[1]["path"]) == before

    def test_import_changes_rating_and_returns_counts(self, edition_client, lr_photos):
        resp = edition_client.post(
            "/api/lightroom/import",
            json={
                "format": "facet-lightroom-state",
                "version": 1,
                "photos": [
                    {"path": PREFIX + "a.jpg", "rating": 4, "pick": -1},
                    {"path": "/does/not/exist.jpg", "rating": 1},
                ],
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body == {"matched": 1, "unmatched": 1, "changed": 1}
        assert _rating(PREFIX + "a.jpg") == (4, 0, 1)


def _rating(path):
    import sqlite3
    conn = sqlite3.connect(DEFAULT_DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT star_rating, is_favorite, is_rejected FROM photos WHERE path = ?", (path,),
    ).fetchone()
    conn.close()
    return (row["star_rating"], row["is_favorite"], row["is_rejected"])
