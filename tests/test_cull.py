"""Tests for POST /api/cull/apply (api/routers/export.py).

Data-safety is the whole point: copy is additive and dry-run by default;
move/trash are destructive and pass through the same validated allow-list;
trashing is OS-trash gated behind viewer.cull.allow_trash; and the op is bounded
server-side to the action's actual reject state (copy=keeps, move/trash=rejects)
so a buggy client can never act outside the user's reject set. A real temp DB
backs get_db; real files under tmp_path let resolve_photo_disk_path resolve to
disk (no scan dirs in tests -> file-exists check only).
"""

import os
import sqlite3
from contextlib import contextmanager
from unittest import mock

import pytest

from db.schema import init_database
from api.routers import gallery as gallery_module

_EXPORT_MODULE = "api.routers.export"
_GALLERY_MODULE = "api.routers.gallery"


@pytest.fixture()
def client(edition_client):
    return edition_client


def _db_cm(db_path):
    @contextmanager
    def _cm():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    return _cm


def _db(tmp_path, photos):
    """photos: list of (path, is_rejected) or (path, is_rejected, extra).

    ``extra`` is an optional dict of sequence columns (sequence_kind,
    sequence_group_id, is_sequence_lead, sequence_ev_offset, date_taken) for
    bracket/panorama fixtures.

    The schema comes from ``db.schema.init_database``, never a hand-rolled
    CREATE TABLE: ``build_photo_select_columns`` intersects the optional column
    list with the columns the database actually has, so a short fixture makes
    the endpoint legitimately drop a field and the assertion pass vacuously --
    the test stops testing instead of failing. ``date_taken`` used to be one
    such omission here, and only surfaced as an OperationalError.
    """
    db = str(tmp_path / "t.db")
    init_database(db)
    conn = sqlite3.connect(db)
    for entry in photos:
        path, rejected = entry[0], entry[1]
        extra = entry[2] if len(entry) > 2 else {}
        conn.execute(
            "INSERT INTO photos (path, filename, is_rejected, sequence_kind, "
            "sequence_group_id, is_sequence_lead, sequence_ev_offset, date_taken) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (path, path.split("/")[-1], rejected,
             extra.get("sequence_kind"), extra.get("sequence_group_id"),
             extra.get("is_sequence_lead", 0), extra.get("sequence_ev_offset"),
             extra.get("date_taken")),
        )
    conn.commit()
    conn.close()
    return db


def _lead_paths(db, kind, group_id):
    """Paths carrying ``is_sequence_lead = 1`` for a (kind, group_id) pair."""
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            "SELECT path FROM photos WHERE sequence_kind = ? AND sequence_group_id = ? "
            "AND is_sequence_lead = 1",
            (kind, group_id),
        ).fetchall()
    finally:
        conn.close()
    return [r[0] for r in rows]


def _make_file(tmp_path, name, content=b"DATA"):
    p = tmp_path / name
    p.write_bytes(content)
    return str(p)


class TestCullApply:
    def test_copy_keeps_dry_run_writes_nothing(self, client, tmp_path):
        path = _make_file(tmp_path, "a.jpg")
        db = _db(tmp_path, [(path, 0)])
        target = str(tmp_path / "keepers")
        with (
            mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)),
            mock.patch(f"{_EXPORT_MODULE}._allowed_export_roots", return_value=[str(tmp_path)]),
        ):
            resp = client.post("/api/cull/apply", json={
                "paths": [path], "action": "copy_keeps", "target_dir": target,
                "dry_run": True, "include_companions": False,
            })
        assert resp.status_code == 200
        body = resp.json()
        assert body["dry_run"] is True
        assert body["would_copy"] == [path]
        assert body["excluded_by_state"] == 0
        assert not os.path.exists(target)

    def test_copy_keeps_real_copies_and_keeps_original(self, client, tmp_path):
        path = _make_file(tmp_path, "a.jpg")
        db = _db(tmp_path, [(path, 0)])
        target = str(tmp_path / "keepers")
        with (
            mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)),
            mock.patch(f"{_EXPORT_MODULE}._allowed_export_roots", return_value=[str(tmp_path)]),
        ):
            resp = client.post("/api/cull/apply", json={
                "paths": [path], "action": "copy_keeps", "target_dir": target,
                "dry_run": False, "include_companions": False,
            })
        assert resp.status_code == 200
        assert resp.json()["copied"] == 1
        assert os.path.isfile(os.path.join(target, "a.jpg"))
        assert os.path.isfile(path)  # original untouched

    def test_companions_included_in_preview(self, client, tmp_path):
        path = _make_file(tmp_path, "a.jpg")
        raw = _make_file(tmp_path, "a.cr2")
        sidecar = _make_file(tmp_path, "a.jpg.xmp")
        db = _db(tmp_path, [(path, 0)])
        with (
            mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)),
            mock.patch(f"{_EXPORT_MODULE}._allowed_export_roots", return_value=[str(tmp_path)]),
        ):
            resp = client.post("/api/cull/apply", json={
                "paths": [path], "action": "copy_keeps", "target_dir": str(tmp_path / "k"),
                "dry_run": True, "include_companions": True,
            })
        assert resp.status_code == 200
        would = set(resp.json()["would_copy"])
        assert {path, raw, sidecar} <= would

    def test_copy_keeps_excludes_rejected_photos(self, client, tmp_path):
        keep = _make_file(tmp_path, "keep.jpg")
        reject = _make_file(tmp_path, "reject.jpg")
        db = _db(tmp_path, [(keep, 0), (reject, 1)])
        with (
            mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)),
            mock.patch(f"{_EXPORT_MODULE}._allowed_export_roots", return_value=[str(tmp_path)]),
        ):
            resp = client.post("/api/cull/apply", json={
                "paths": [keep, reject], "action": "copy_keeps", "target_dir": str(tmp_path / "k"),
                "dry_run": True, "include_companions": False,
            })
        body = resp.json()
        assert body["would_copy"] == [keep]  # the rejected one is excluded
        assert body["excluded_by_state"] == 1

    def test_move_only_acts_on_rejected_photos(self, client, tmp_path):
        keep = _make_file(tmp_path, "keep.jpg")
        reject = _make_file(tmp_path, "reject.jpg")
        db = _db(tmp_path, [(keep, 0), (reject, 1)])
        with (
            mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)),
            mock.patch(f"{_EXPORT_MODULE}._allowed_export_roots", return_value=[str(tmp_path)]),
        ):
            resp = client.post("/api/cull/apply", json={
                "paths": [keep, reject], "action": "move_rejects",
                "target_dir": str(tmp_path / "out"), "dry_run": True,
            })
        body = resp.json()
        assert body["would_move"] == [reject]  # the kept one is never moved
        assert body["excluded_by_state"] == 1

    def test_move_outside_allowlist_403(self, client, tmp_path):
        """The 403 names the config key and the resolved roots so a container
        user hitting 'Cull to folder' can fix their own config instead of
        getting a bare 'Access denied' (see discussion #106)."""
        path = _make_file(tmp_path, "a.jpg")
        db = _db(tmp_path, [(path, 1)])
        allowed = str(tmp_path / "allowed")
        evil = str(tmp_path / "evil")
        with (
            mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)),
            mock.patch(f"{_EXPORT_MODULE}._allowed_export_roots", return_value=[allowed]),
        ):
            resp = client.post("/api/cull/apply", json={
                "paths": [path], "action": "move_rejects", "target_dir": evil,
                "dry_run": False,
            })
        assert resp.status_code == 403
        assert os.path.isfile(path)  # never moved
        detail = resp.json()["detail"]
        assert "viewer.export.allowed_target_dirs" in detail
        assert allowed in detail

    def test_move_requires_target_dir(self, client, tmp_path):
        path = _make_file(tmp_path, "a.jpg")
        db = _db(tmp_path, [(path, 1)])
        with mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)):
            resp = client.post("/api/cull/apply", json={
                "paths": [path], "action": "move_rejects", "dry_run": True,
            })
        assert resp.status_code == 400

    def test_trash_disabled_by_default_403(self, client, tmp_path):
        path = _make_file(tmp_path, "a.jpg")
        db = _db(tmp_path, [(path, 1)])
        with (
            mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)),
            mock.patch(f"{_EXPORT_MODULE}.VIEWER_CONFIG", {"cull": {"allow_trash": False}}),
        ):
            resp = client.post("/api/cull/apply", json={
                "paths": [path], "action": "trash_rejects", "dry_run": True,
            })
        assert resp.status_code == 403
        assert os.path.isfile(path)

    def test_trash_without_send2trash_400(self, client, tmp_path):
        path = _make_file(tmp_path, "a.jpg")
        db = _db(tmp_path, [(path, 1)])
        with (
            mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)),
            mock.patch(f"{_EXPORT_MODULE}.VIEWER_CONFIG", {"cull": {"allow_trash": True}}),
            mock.patch.dict("sys.modules", {"send2trash": None}),
        ):
            resp = client.post("/api/cull/apply", json={
                "paths": [path], "action": "trash_rejects", "dry_run": True,
            })
        assert resp.status_code == 400
        assert os.path.isfile(path)
        # Fix 8: pin the remedy text, not just the status code, so a
        # regression to a stale or broken message is visible -- export.py's
        # restart guidance (Fix 9) depends on this substring surviving.
        assert "pip install send2trash" in resp.json()["detail"]

    def test_requires_paths_or_filters(self, client, tmp_path):
        db = _db(tmp_path, [])
        with mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)):
            resp = client.post("/api/cull/apply", json={"action": "copy_keeps"})
        assert resp.status_code == 400

    def test_not_visible_paths_are_counted_separately_from_excluded_by_state(self, client, tmp_path):
        """A5#4: a path that isn't in the DB at all (or isn't visible to this
        user) used to vanish from every count -- neither acted on nor
        reported, so matching + excluded_by_state never reconciled with
        len(paths). It must show up as not_visible instead."""
        keep = _make_file(tmp_path, "keep.jpg")
        reject = _make_file(tmp_path, "reject.jpg")
        missing = str(tmp_path / "never_scanned.jpg")  # not in the DB at all
        db = _db(tmp_path, [(keep, 0), (reject, 1)])
        with (
            mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)),
            mock.patch(f"{_EXPORT_MODULE}._allowed_export_roots", return_value=[str(tmp_path)]),
        ):
            resp = client.post("/api/cull/apply", json={
                "paths": [keep, reject, missing], "action": "copy_keeps",
                "target_dir": str(tmp_path / "k"), "dry_run": True,
                "include_companions": False,
            })
        body = resp.json()
        assert body["would_copy"] == [keep]
        assert body["excluded_by_state"] == 1  # reject
        assert body["not_visible"] == 1  # missing
        # The three counts now reconcile with the request's own path count.
        assert len(body["would_copy"]) + body["excluded_by_state"] + body["not_visible"] == 3


_BRACKET = "bracket"
_PANORAMA = "panorama"


class TestCullApplyFilterScope:
    """The ``filters`` branch must resolve the rows the gallery would show.

    The client used to send an explicit path list here, so this branch was
    never exercised and its resolver skipped ``_prepare_gallery_params`` -- the
    step that expands the Photo Type presets. ``type=aerial`` therefore reached
    ``_build_gallery_where`` as an unknown key, was dropped, and the cull
    resolved to the WHOLE library view on an endpoint that moves and trashes
    files.
    """

    @staticmethod
    def _categorised_db(tmp_path, rows):
        """``rows``: (path, category) pairs. Schema from ``init_database``."""
        db = str(tmp_path / "cat.db")
        init_database(db)
        conn = sqlite3.connect(db)
        for path, category in rows:
            conn.execute(
                "INSERT INTO photos (path, filename, category, is_rejected) "
                "VALUES (?, ?, ?, 0)",
                (path, os.path.basename(path), category),
            )
        conn.commit()
        conn.close()
        return db

    def test_a_photo_type_preset_narrows_the_cull(self, client, tmp_path):
        aerial = _make_file(tmp_path, "aerial.jpg")
        field = _make_file(tmp_path, "field.jpg")
        street = _make_file(tmp_path, "street.jpg")
        db = self._categorised_db(tmp_path, [
            (aerial, "aerial"), (field, "landscape"), (street, "street"),
        ])
        with (
            mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)),
            mock.patch(f"{_EXPORT_MODULE}._allowed_export_roots", return_value=[str(tmp_path)]),
        ):
            resp = client.post("/api/cull/apply", json={
                "filters": {"type": "aerial"}, "action": "copy_keeps",
                "target_dir": str(tmp_path / "k"), "dry_run": True,
            })
        assert resp.status_code == 200
        body = resp.json()
        assert body["would_copy"] == [aerial]
        assert body["matched"] == 1

    def test_a_filter_the_where_builder_knows_still_narrows(self, client, tmp_path):
        aerial = _make_file(tmp_path, "aerial.jpg")
        field = _make_file(tmp_path, "field.jpg")
        db = self._categorised_db(tmp_path, [(aerial, "aerial"), (field, "landscape")])
        with (
            mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)),
            mock.patch(f"{_EXPORT_MODULE}._allowed_export_roots", return_value=[str(tmp_path)]),
        ):
            resp = client.post("/api/cull/apply", json={
                "filters": {"category": "landscape"}, "action": "copy_keeps",
                "target_dir": str(tmp_path / "k"), "dry_run": True,
            })
        assert resp.status_code == 200
        assert resp.json()["would_copy"] == [field]

    def test_exclude_narrows_the_filter_set(self, client, tmp_path):
        keep = _make_file(tmp_path, "keep.jpg")
        drop = _make_file(tmp_path, "drop.jpg")
        db = self._categorised_db(tmp_path, [(keep, "aerial"), (drop, "aerial")])
        with (
            mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)),
            mock.patch(f"{_EXPORT_MODULE}._allowed_export_roots", return_value=[str(tmp_path)]),
        ):
            resp = client.post("/api/cull/apply", json={
                "filters": {"type": "aerial"}, "exclude": [drop],
                "action": "copy_keeps", "target_dir": str(tmp_path / "k"),
                "dry_run": True,
            })
        assert resp.status_code == 200
        assert resp.json()["would_copy"] == [keep]

    def test_exclude_can_only_narrow_a_destructive_action(self, client, tmp_path):
        rejected = _make_file(tmp_path, "r.jpg")
        db = self._categorised_db(tmp_path, [(rejected, "aerial")])
        conn = sqlite3.connect(db)
        conn.execute("UPDATE photos SET is_rejected = 1")
        conn.commit()
        conn.close()
        with (
            mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)),
            mock.patch(f"{_EXPORT_MODULE}._allowed_export_roots", return_value=[str(tmp_path)]),
        ):
            resp = client.post("/api/cull/apply", json={
                "filters": {"type": "aerial"}, "exclude": [rejected],
                "action": "move_rejects", "target_dir": str(tmp_path / "k"),
                "dry_run": False,
            })
        assert resp.status_code == 200
        assert resp.json()["moved"] == 0
        assert os.path.isfile(rejected)

    def test_a_malformed_filter_set_is_422_not_500(self, client, tmp_path):
        photo = _make_file(tmp_path, "a.jpg")
        db = self._categorised_db(tmp_path, [(photo, "aerial")])
        with (
            mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)),
            mock.patch(f"{_EXPORT_MODULE}._allowed_export_roots", return_value=[str(tmp_path)]),
        ):
            resp = client.post("/api/cull/apply", json={
                "filters": {"per_page": "99999"}, "action": "copy_keeps",
                "target_dir": str(tmp_path / "k"), "dry_run": True,
            })
        assert resp.status_code == 422

    @staticmethod
    def _album_db(tmp_path, member_paths, other_paths):
        """Photos split between album 1 and no album at all."""
        db = str(tmp_path / "album.db")
        init_database(db)
        conn = sqlite3.connect(db)
        for path in member_paths + other_paths:
            conn.execute(
                "INSERT INTO photos (path, filename, is_rejected) VALUES (?, ?, 0)",
                (path, os.path.basename(path)),
            )
        conn.execute("INSERT INTO albums (id, user_id, name) VALUES (1, NULL, 'trip')")
        conn.executemany(
            "INSERT INTO album_photos (album_id, photo_path) VALUES (1, ?)",
            [(p,) for p in member_paths],
        )
        conn.commit()
        conn.close()
        return db

    def test_an_album_scoped_cull_is_narrowed_to_its_members(self, client, tmp_path):
        """The album filter must scope the destructive path like it scopes the grid."""
        inside = _make_file(tmp_path, "inside.jpg")
        outside = _make_file(tmp_path, "outside.jpg")
        db = self._album_db(tmp_path, [inside], [outside])
        with (
            mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)),
            mock.patch(f"{_EXPORT_MODULE}._allowed_export_roots", return_value=[str(tmp_path)]),
        ):
            resp = client.post("/api/cull/apply", json={
                "filters": {"album_id": "1"}, "action": "copy_keeps",
                "target_dir": str(tmp_path / "k"), "dry_run": True,
            })
        assert resp.status_code == 200, resp.text
        assert resp.json()["would_copy"] == [inside]

    def test_an_unknown_album_is_404_like_the_gallery_get(self, client, tmp_path):
        """The album access check guarded the READ paths only.

        ``gallery_scope_sql`` was reached here directly, so a POST body naming
        an album the caller cannot open resolved its rows anyway -- on the
        endpoint that moves and trashes files. Same status as
        ``GET /api/photos?album_id=99`` (tests/test_gallery.py), and no file
        touched.
        """
        inside = _make_file(tmp_path, "inside.jpg")
        db = self._album_db(tmp_path, [inside], [])
        with (
            mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)),
            mock.patch(f"{_EXPORT_MODULE}._allowed_export_roots", return_value=[str(tmp_path)]),
        ):
            resp = client.post("/api/cull/apply", json={
                "filters": {"album_id": "99"}, "action": "move_rejects",
                "target_dir": str(tmp_path / "k"), "dry_run": False,
            })
        assert resp.status_code == 404, resp.text
        assert os.path.isfile(inside)
        assert not os.path.exists(str(tmp_path / "k"))


class TestCullApplyFilterScopeIsBounded:
    """The ``filters`` branch must be bounded, like the sidecar export branch.

    ``_selected_paths`` was called here with no cap at all, so a whole-library
    filter set resolved to every path the library holds on an endpoint that
    moves and trashes files. Mirrors
    ``tests.test_export.TestExportSidecarsFilterScopeIsBounded``, with its own
    cap constant (``_CULL_FILTER_MAX``) rather than reusing the sidecar one:
    the per-photo cost that justifies a cap differs (cull does one
    ``shutil.move``/``copy2`` or ``send2trash`` call per photo rather than two
    ``exiftool`` subprocesses), even though both caps are 10000 today.
    """

    def test_the_cap_matches_the_explicit_path_limit(self):
        """Both request forms bound the same work, so both bound it the same."""
        from api.routers.export import CullApplyRequest, _CULL_FILTER_MAX

        paths_max = CullApplyRequest.model_fields["paths"].metadata[0].max_length
        assert _CULL_FILTER_MAX == paths_max == 10000

    def test_a_view_over_the_cap_is_refused_even_as_a_dry_run(self, client, tmp_path):
        paths = [_make_file(tmp_path, f"cap{i}.jpg") for i in range(3)]
        db = TestCullApplyFilterScope._categorised_db(
            tmp_path, [(p, "capped") for p in paths]
        )
        with (
            mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)),
            mock.patch(f"{_EXPORT_MODULE}._allowed_export_roots", return_value=[str(tmp_path)]),
            mock.patch(f"{_EXPORT_MODULE}._CULL_FILTER_MAX", 2),
        ):
            # dry_run True (the endpoint's own default) so an over-cap preview
            # cannot be used to do the unbounded work the real run is refused for.
            resp = client.post("/api/cull/apply", json={
                "filters": {"category": "capped"}, "action": "copy_keeps",
                "target_dir": str(tmp_path / "k"), "dry_run": True,
            })
        assert resp.status_code == 412, resp.text
        detail = resp.json()["detail"]
        # Names the count AND the limit: "too many" alone leaves the user with
        # no idea how far to narrow.
        assert "3" in detail and "2" in detail
        # Refused before any I/O, dry-run or not.
        assert not os.path.exists(str(tmp_path / "k"))

    def test_a_view_at_the_cap_still_proceeds(self, client, tmp_path):
        paths = [_make_file(tmp_path, f"cap{i}.jpg") for i in range(2)]
        db = TestCullApplyFilterScope._categorised_db(
            tmp_path, [(p, "capped") for p in paths]
        )
        with (
            mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)),
            mock.patch(f"{_EXPORT_MODULE}._allowed_export_roots", return_value=[str(tmp_path)]),
            mock.patch(f"{_EXPORT_MODULE}._CULL_FILTER_MAX", 2),
        ):
            resp = client.post("/api/cull/apply", json={
                "filters": {"category": "capped"}, "action": "copy_keeps",
                "target_dir": str(tmp_path / "k"), "dry_run": True,
            })
        assert resp.status_code == 200, resp.text
        assert sorted(resp.json()["would_copy"]) == sorted(paths)


class TestCullApplyTargetIsExactlyOne:
    """``paths`` and ``filters`` name the same set two ways; never both.

    Both-are-set used to resolve silently in ``paths``' favour --
    ``_selected_paths`` returns before ``filters`` is read -- so a stale path
    list alongside a whole-view filter set dropped the scope on an endpoint
    that moves and trashes files. The twin of ``TestBatchTargetIsExactlyOne``
    in tests/test_batch_photo_writes.py. ``exclude`` is no longer part of this
    pair: it narrows whichever target is sent (see
    ``TestCullApplyExcludeNarrowsEitherTarget``).
    """

    def test_both_targets_is_422(self, client, tmp_path):
        named = _make_file(tmp_path, "named.jpg")
        filtered = _make_file(tmp_path, "filtered.jpg")
        db = _db(tmp_path, [(named, 1), (filtered, 1)])
        with (
            mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)),
            mock.patch(f"{_EXPORT_MODULE}._allowed_export_roots", return_value=[str(tmp_path)]),
        ):
            resp = client.post("/api/cull/apply", json={
                "paths": [named], "filters": {"category": "aerial"},
                "exclude": [filtered],
                "action": "move_rejects", "target_dir": str(tmp_path / "k"),
                "dry_run": False,
            })
        assert resp.status_code == 422, resp.text
        assert os.path.isfile(named)
        assert os.path.isfile(filtered)

    def test_neither_target_is_still_400(self, client, tmp_path):
        """The pre-existing status for a request with no target at all."""
        db = _db(tmp_path, [])
        with mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)):
            resp = client.post("/api/cull/apply", json={"action": "copy_keeps"})
        assert resp.status_code == 400, resp.text


class TestCullApplyExcludeNarrowsEitherTarget:
    """``exclude`` narrows a named path list too, not only a filter set.

    ``_selected_paths`` returned ``body.paths`` before ``body.exclude`` was
    ever read, so a ``{paths, exclude}`` request moved or OS-trashed the very
    files the caller had listed as exceptions -- silently, on the project's
    most destructive endpoint, and the only thing bounding it was the client
    (cull-dialog.component.ts sends ``exclude`` only alongside ``filters``).
    The bound belongs server-side: "destructive endpoints are bounded
    server-side, not by the client."
    """

    def _rejected_pair(self, tmp_path):
        doomed = _make_file(tmp_path, "doomed.jpg")
        spared = _make_file(tmp_path, "spared.jpg")
        return doomed, spared, _db(tmp_path, [(doomed, 1), (spared, 1)])

    def test_an_excluded_path_is_not_moved(self, client, tmp_path):
        """The real, destructive run — not a dry run: the files must survive."""
        doomed, spared, db = self._rejected_pair(tmp_path)
        target = str(tmp_path / "out")
        with (
            mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)),
            mock.patch(f"{_EXPORT_MODULE}._allowed_export_roots", return_value=[str(tmp_path)]),
        ):
            resp = client.post("/api/cull/apply", json={
                "paths": [doomed, spared], "exclude": [spared],
                "action": "move_rejects", "target_dir": target, "dry_run": False,
            })
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["moved"] == 1
        # The counts have to reflect the narrowing too, or the response says a
        # photo was considered when it never was.
        assert body["matched"] == 1
        assert body["excluded_by_state"] == 0
        assert os.path.isfile(spared), "the excluded file was moved anyway"
        assert not os.path.exists(doomed)
        assert os.path.isfile(os.path.join(target, "doomed.jpg"))
        assert not os.path.exists(os.path.join(target, "spared.jpg"))

    def test_an_excluded_path_is_not_previewed_either(self, client, tmp_path):
        """A preview that lists a spared file is a preview the user cannot trust."""
        doomed, spared, db = self._rejected_pair(tmp_path)
        with (
            mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)),
            mock.patch(f"{_EXPORT_MODULE}._allowed_export_roots", return_value=[str(tmp_path)]),
        ):
            resp = client.post("/api/cull/apply", json={
                "paths": [doomed, spared], "exclude": [spared],
                "action": "move_rejects", "target_dir": str(tmp_path / "out"),
                "dry_run": True,
            })
        assert resp.status_code == 200, resp.text
        assert resp.json()["would_move"] == [doomed]

    def test_an_empty_exclude_is_a_no_op(self, client, tmp_path):
        """The client sends ``exclude: []`` freely; it must not narrow anything."""
        doomed, spared, db = self._rejected_pair(tmp_path)
        with (
            mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)),
            mock.patch(f"{_EXPORT_MODULE}._allowed_export_roots", return_value=[str(tmp_path)]),
        ):
            resp = client.post("/api/cull/apply", json={
                "paths": [doomed, spared], "exclude": [],
                "action": "move_rejects", "target_dir": str(tmp_path / "out"),
                "dry_run": True,
            })
        assert resp.status_code == 200, resp.text
        assert sorted(resp.json()["would_move"]) == sorted([doomed, spared])

    def test_excluding_every_named_path_acts_on_nothing(self, client, tmp_path):
        """Still a target set, simply an empty one — not the no-target 400."""
        doomed, spared, db = self._rejected_pair(tmp_path)
        with (
            mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)),
            mock.patch(f"{_EXPORT_MODULE}._allowed_export_roots", return_value=[str(tmp_path)]),
        ):
            resp = client.post("/api/cull/apply", json={
                "paths": [doomed, spared], "exclude": [doomed, spared],
                "action": "move_rejects", "target_dir": str(tmp_path / "out"),
                "dry_run": False,
            })
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["moved"] == 0
        assert body["matched"] == 0
        assert os.path.isfile(doomed) and os.path.isfile(spared)

    def _rejected_bracket(self, tmp_path):
        """Two rejected frames of one bracket group, both on disk."""
        a = _make_file(tmp_path, "frame_a.jpg")
        b = _make_file(tmp_path, "frame_b.jpg")
        db = _db(tmp_path, [
            (a, 1, {"sequence_kind": _BRACKET, "sequence_group_id": 7,
                    "is_sequence_lead": 1, "sequence_ev_offset": 0.0}),
            (b, 1, {"sequence_kind": _BRACKET, "sequence_group_id": 7,
                    "sequence_ev_offset": 2.0}),
        ])
        return a, b, db

    def test_an_excluded_frame_is_not_re_added_as_a_sequence_sibling(self, client, tmp_path):
        """``exclude`` narrowed the target set and the sibling pass then
        widened it straight back: ``_sequence_siblings`` re-derived every frame
        sharing ``(sequence_kind, sequence_group_id)`` with a matching frame and
        subtracted only ``matching``, so an excluded frame of the same bracket
        returned as a sibling, passed the reject-state check and was moved --
        while the response counted it as a sibling rather than as excluded.
        "Only ever narrows" has to hold through the sibling pass too."""
        a, b, db = self._rejected_bracket(tmp_path)
        with (
            mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)),
            mock.patch(f"{_EXPORT_MODULE}._allowed_export_roots", return_value=[str(tmp_path)]),
        ):
            resp = client.post("/api/cull/apply", json={
                "paths": [a, b], "exclude": [b],
                "action": "move_rejects", "target_dir": str(tmp_path / "out"),
                "dry_run": True, "include_sequence_siblings": True,
            })
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["would_move"] == [a], "the excluded frame came back as a sibling"
        # An excluded frame is not a sibling for this request at all, so it is
        # counted nowhere rather than double-counted as excluded_by_state.
        assert body["sequence_siblings"] == 0
        assert body["excluded_by_state"] == 0

    def test_an_excluded_frame_is_not_a_sibling_on_the_filter_branch_either(self, client, tmp_path):
        """Same widening through the branch the client actually sends: the cull
        dialog pairs ``exclude`` with ``filters``, and the sibling checkbox is
        only reachable once the user turns off hide_brackets/hide_panoramas."""
        a, b, db = self._rejected_bracket(tmp_path)
        with (
            mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)),
            mock.patch(f"{_EXPORT_MODULE}._allowed_export_roots", return_value=[str(tmp_path)]),
        ):
            resp = client.post("/api/cull/apply", json={
                "filters": {"hide_brackets": "0", "hide_panoramas": "0"},
                "exclude": [b],
                "action": "move_rejects", "target_dir": str(tmp_path / "out"),
                "dry_run": True, "include_sequence_siblings": True,
            })
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["would_move"] == [a], "the excluded frame came back as a sibling"
        assert body["sequence_siblings"] == 0


class TestCullApplySequences:
    def test_copy_keeps_bracket_siblings_reported_and_included_when_flag_on(self, client, tmp_path):
        """A5#1: a 5-frame bracket contributes ONE selected path (the gallery
        hides the rest by default), so 'Copy keeps to folder' used to copy one
        file and the sibling count went unreported. It must always be
        reported, and only pulled into the copy when the flag is set."""
        lead = _make_file(tmp_path, "lead.jpg")
        siblings = [_make_file(tmp_path, f"sib{i}.jpg") for i in range(4)]
        photos = [(lead, 0, {"sequence_kind": _BRACKET, "sequence_group_id": 1,
                              "sequence_ev_offset": 0.0})]
        for i, sib in enumerate(siblings):
            photos.append((sib, 0, {"sequence_kind": _BRACKET, "sequence_group_id": 1,
                                     "sequence_ev_offset": float(i + 1)}))
        db = _db(tmp_path, photos)
        with (
            mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)),
            mock.patch(f"{_EXPORT_MODULE}._allowed_export_roots", return_value=[str(tmp_path)]),
        ):
            resp_off = client.post("/api/cull/apply", json={
                "paths": [lead], "action": "copy_keeps", "target_dir": str(tmp_path / "k"),
                "dry_run": True, "include_companions": False,
                "include_sequence_siblings": False,
            })
            resp_on = client.post("/api/cull/apply", json={
                "paths": [lead], "action": "copy_keeps", "target_dir": str(tmp_path / "k"),
                "dry_run": True, "include_companions": False,
                "include_sequence_siblings": True,
            })
        body_off = resp_off.json()
        assert body_off["would_copy"] == [lead]
        assert body_off["sequence_siblings"] == 4  # reported even though flag is off

        body_on = resp_on.json()
        assert set(body_on["would_copy"]) == {lead, *siblings}
        assert len(body_on["would_copy"]) == 5
        assert body_on["sequence_siblings"] == 4

    def test_move_rejects_panorama_lead_reassigns_surviving_frame(self, client, tmp_path):
        """A5#2 + #3: move/trash never wrote to the DB, so a moved panorama
        lead kept satisfying HIDE_PANORAMAS_SQL (and kept serving its stored
        thumbnail) until a rescan pruned it -- at which point every surviving
        frame had is_sequence_lead = 0 and the whole set vanished. A surviving
        frame must be promoted instead, and the two un-moved siblings must be
        reported rather than silently orphaned."""
        lead = _make_file(tmp_path, "lead.jpg")
        f1 = _make_file(tmp_path, "f1.jpg")
        f2 = _make_file(tmp_path, "f2.jpg")
        db = _db(tmp_path, [
            (lead, 1, {"sequence_kind": _PANORAMA, "sequence_group_id": 1, "is_sequence_lead": 1}),
            (f1, 0, {"sequence_kind": _PANORAMA, "sequence_group_id": 1, "is_sequence_lead": 0}),
            (f2, 0, {"sequence_kind": _PANORAMA, "sequence_group_id": 1, "is_sequence_lead": 0}),
        ])
        target = str(tmp_path / "out")
        with (
            mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)),
            mock.patch(f"{_EXPORT_MODULE}._allowed_export_roots", return_value=[str(tmp_path)]),
        ):
            resp = client.post("/api/cull/apply", json={
                "paths": [lead], "action": "move_rejects", "target_dir": target,
                "dry_run": False, "include_companions": False,
                "include_sequence_siblings": False,
            })
        assert resp.status_code == 200
        body = resp.json()
        assert body["moved"] == 1
        assert body["sequence_siblings"] == 2  # f1, f2 reported, not silently orphaned
        leads = _lead_paths(db, _PANORAMA, 1)
        assert len(leads) == 1
        assert leads[0] in (f1, f2)  # exactly one surviving frame promoted

    def test_promoted_lead_is_the_middle_surviving_frame_not_the_first(self, client, tmp_path):
        """The detector marks the MIDDLE frame of a sweep as its representative
        (utils/panorama.py: "a sweep has no best frame, and the middle one is
        the likeliest to hold the subject"), so a replacement picked off the
        edge would represent the set in the gallery by its least
        representative tile. Ordered by capture time, the way the detector saw
        the segment -- promoting by path happened to pass a 3-frame fixture
        where the only survivor was also the middle one.
        """
        frames = []
        for i in range(5):
            f = _make_file(tmp_path, f"pan_{i}.jpg")
            frames.append(f)
        # Lead is the middle frame, as the detector would have left it.
        db = _db(tmp_path, [
            (f, 1 if i == 2 else 0,
             {"sequence_kind": _PANORAMA, "sequence_group_id": 1,
              "is_sequence_lead": 1 if i == 2 else 0,
              "date_taken": f"2026:03:01 12:00:0{i}"})
            for i, f in enumerate(frames)
        ])
        with (
            mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)),
            mock.patch(f"{_EXPORT_MODULE}._allowed_export_roots", return_value=[str(tmp_path)]),
        ):
            resp = client.post("/api/cull/apply", json={
                "paths": [frames[2]], "action": "move_rejects",
                "target_dir": str(tmp_path / "out"), "dry_run": False,
                "include_companions": False, "include_sequence_siblings": False,
            })
        assert resp.status_code == 200
        # Survivors in capture order are 0,1,3,4 -- the middle of four is index 2,
        # i.e. frame 3. Frame 0 is what a first-survivor promotion would pick.
        assert _lead_paths(db, _PANORAMA, 1) == [frames[3]]

    def test_sequence_groups_scoped_by_kind_not_just_group_id(self, client, tmp_path):
        """A5 invariant: sequence_group_id is renumbered from 1 independently
        by the bracket and panorama passes, so two sets sharing group_id=1 but
        a different sequence_kind must never bleed into each other, either
        when collecting siblings or when re-picking a lead."""
        bracket_lead = _make_file(tmp_path, "bracket_lead.jpg")
        bracket_sib = _make_file(tmp_path, "bracket_sib.jpg")
        pano_lead = _make_file(tmp_path, "pano_lead.jpg")
        pano_f1 = _make_file(tmp_path, "pano_f1.jpg")
        db = _db(tmp_path, [
            (bracket_lead, 0, {"sequence_kind": _BRACKET, "sequence_group_id": 1,
                                "sequence_ev_offset": 0.0}),
            (bracket_sib, 0, {"sequence_kind": _BRACKET, "sequence_group_id": 1,
                               "sequence_ev_offset": 2.0}),
            (pano_lead, 1, {"sequence_kind": _PANORAMA, "sequence_group_id": 1,
                             "is_sequence_lead": 1}),
            (pano_f1, 0, {"sequence_kind": _PANORAMA, "sequence_group_id": 1,
                           "is_sequence_lead": 0}),
        ])
        target = str(tmp_path / "out")
        with (
            mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)),
            mock.patch(f"{_EXPORT_MODULE}._allowed_export_roots", return_value=[str(tmp_path)]),
        ):
            copy_resp = client.post("/api/cull/apply", json={
                "paths": [bracket_lead], "action": "copy_keeps",
                "target_dir": str(tmp_path / "k"), "dry_run": True,
                "include_companions": False, "include_sequence_siblings": True,
            })
            move_resp = client.post("/api/cull/apply", json={
                "paths": [pano_lead], "action": "move_rejects",
                "target_dir": target, "dry_run": False,
                "include_companions": False, "include_sequence_siblings": False,
            })
        copy_body = copy_resp.json()
        assert copy_body["sequence_siblings"] == 1
        assert set(copy_body["would_copy"]) == {bracket_lead, bracket_sib}  # never pano_*

        assert move_resp.json()["moved"] == 1
        assert _lead_paths(db, _PANORAMA, 1) == [pano_f1]  # only the pano group reassigned
        assert _lead_paths(db, _BRACKET, 1) == []  # the bracket group must stay untouched

    def test_include_sequence_siblings_never_moves_a_photo_the_user_kept(self, client, tmp_path):
        """Finding 1 (2026-08-17 review): the sibling query has no is_rejected
        predicate, so include_sequence_siblings widened move/trash to every
        frame in the group regardless of its OWN reject state -- rejecting one
        tile of a panorama destroyed the sibling the user explicitly kept,
        while the same response claimed it was excluded_by_state."""
        lead = _make_file(tmp_path, "lead.jpg")
        keeper = _make_file(tmp_path, "keeper.jpg")
        db = _db(tmp_path, [
            (lead, 1, {"sequence_kind": _PANORAMA, "sequence_group_id": 1, "is_sequence_lead": 1}),
            (keeper, 0, {"sequence_kind": _PANORAMA, "sequence_group_id": 1, "is_sequence_lead": 0}),
        ])
        target = str(tmp_path / "out")
        with (
            mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)),
            mock.patch(f"{_EXPORT_MODULE}._allowed_export_roots", return_value=[str(tmp_path)]),
        ):
            resp = client.post("/api/cull/apply", json={
                "paths": [lead], "action": "move_rejects", "target_dir": target,
                "dry_run": False, "include_companions": False,
                "include_sequence_siblings": True,
            })
        assert resp.status_code == 200
        body = resp.json()
        assert os.path.isfile(keeper), "the kept sibling must still be on disk"
        assert body["moved"] == 1
        assert body["excluded_by_state"] == 1

    def test_include_sequence_siblings_never_trashes_a_photo_the_user_kept(self, client, tmp_path):
        """Finding 1, trash_rejects direction: identical want_rejected=True
        filtering as move_rejects, exercised through the OS-trash branch
        specifically since it duplicates the lead-reassignment/action-paths
        wiring rather than sharing it with move_rejects."""
        lead = _make_file(tmp_path, "lead.jpg")
        keeper = _make_file(tmp_path, "keeper.jpg")
        db = _db(tmp_path, [
            (lead, 1, {"sequence_kind": _PANORAMA, "sequence_group_id": 1, "is_sequence_lead": 1}),
            (keeper, 0, {"sequence_kind": _PANORAMA, "sequence_group_id": 1, "is_sequence_lead": 0}),
        ])
        fake_send2trash = mock.MagicMock()
        fake_module = mock.Mock(send2trash=fake_send2trash)
        with (
            mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)),
            mock.patch(f"{_EXPORT_MODULE}.VIEWER_CONFIG", {"cull": {"allow_trash": True}}),
            mock.patch.dict("sys.modules", {"send2trash": fake_module}),
        ):
            resp = client.post("/api/cull/apply", json={
                "paths": [lead], "action": "trash_rejects",
                "dry_run": False, "include_companions": False,
                "include_sequence_siblings": True,
            })
        assert resp.status_code == 200
        body = resp.json()
        assert fake_send2trash.call_args_list == [mock.call(lead)], "the kept sibling must never be trashed"
        assert body["trashed"] == 1
        assert body["excluded_by_state"] == 1

    def test_include_sequence_siblings_never_copies_a_rejected_sibling_as_a_keep(self, client, tmp_path):
        """Finding 1, copy_keeps direction: want_rejected is False there, so a
        sibling must be NOT rejected to be pulled in as a keep."""
        lead = _make_file(tmp_path, "lead.jpg")
        rejected_sib = _make_file(tmp_path, "rejected_sib.jpg")
        db = _db(tmp_path, [
            (lead, 0, {"sequence_kind": _PANORAMA, "sequence_group_id": 1, "is_sequence_lead": 1}),
            (rejected_sib, 1, {"sequence_kind": _PANORAMA, "sequence_group_id": 1, "is_sequence_lead": 0}),
        ])
        with (
            mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)),
            mock.patch(f"{_EXPORT_MODULE}._allowed_export_roots", return_value=[str(tmp_path)]),
        ):
            resp = client.post("/api/cull/apply", json={
                "paths": [lead], "action": "copy_keeps", "target_dir": str(tmp_path / "k"),
                "dry_run": True, "include_companions": False,
                "include_sequence_siblings": True,
            })
        body = resp.json()
        assert body["would_copy"] == [lead]
        assert rejected_sib not in body["would_copy"]

    def test_removing_whole_panorama_leaves_lead_flag_intact(self, client, tmp_path):
        """Finding 2 (2026-08-17 review): the is_sequence_lead=0 demotion ran
        unconditionally while the promotion was guarded by `if survivors:`.
        Trashing/moving every frame of a set together (recoverable via OS
        trash) used to leave it with NO lead at all -- permanently invisible
        under hide_panoramas until a rescan reruns --detect-sequences."""
        frames = [_make_file(tmp_path, f"f{i}.jpg") for i in range(3)]
        db = _db(tmp_path, [
            (frames[0], 1, {"sequence_kind": _PANORAMA, "sequence_group_id": 1, "is_sequence_lead": 1}),
            (frames[1], 1, {"sequence_kind": _PANORAMA, "sequence_group_id": 1, "is_sequence_lead": 0}),
            (frames[2], 1, {"sequence_kind": _PANORAMA, "sequence_group_id": 1, "is_sequence_lead": 0}),
        ])
        target = str(tmp_path / "out")
        with (
            mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)),
            mock.patch(f"{_EXPORT_MODULE}._allowed_export_roots", return_value=[str(tmp_path)]),
        ):
            resp = client.post("/api/cull/apply", json={
                "paths": frames, "action": "move_rejects", "target_dir": target,
                "dry_run": False, "include_companions": False,
            })
        assert resp.status_code == 200
        assert resp.json()["moved"] == 3
        assert _lead_paths(db, _PANORAMA, 1) == [frames[0]], (
            "removing the whole group together must leave the lead flag untouched, "
            "not demote it with nothing to promote"
        )

    def test_trash_rejects_panorama_lead_reassigns_surviving_frame(self, client, tmp_path):
        """Finding 8 (2026-08-17 review): the trash_rejects copy of the
        move_rejects lead-reassignment logic was never exercised by a test --
        only the 403/400 gates, both dry_run. Mirrors
        test_move_rejects_panorama_lead_reassigns_surviving_frame with
        action='trash_rejects', allow_trash=True, and send2trash.send2trash
        patched to a recording no-op."""
        lead = _make_file(tmp_path, "lead.jpg")
        f1 = _make_file(tmp_path, "f1.jpg")
        f2 = _make_file(tmp_path, "f2.jpg")
        db = _db(tmp_path, [
            (lead, 1, {"sequence_kind": _PANORAMA, "sequence_group_id": 1, "is_sequence_lead": 1}),
            (f1, 0, {"sequence_kind": _PANORAMA, "sequence_group_id": 1, "is_sequence_lead": 0}),
            (f2, 0, {"sequence_kind": _PANORAMA, "sequence_group_id": 1, "is_sequence_lead": 0}),
        ])
        fake_send2trash = mock.MagicMock()
        fake_module = mock.Mock(send2trash=fake_send2trash)
        with (
            mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)),
            mock.patch(f"{_EXPORT_MODULE}.VIEWER_CONFIG", {"cull": {"allow_trash": True}}),
            mock.patch.dict("sys.modules", {"send2trash": fake_module}),
        ):
            resp = client.post("/api/cull/apply", json={
                "paths": [lead], "action": "trash_rejects",
                "dry_run": False, "include_companions": False,
                "include_sequence_siblings": False,
            })
        assert resp.status_code == 200
        body = resp.json()
        assert body["trashed"] == 1
        assert body["sequence_siblings"] == 2
        assert fake_send2trash.call_args_list == [mock.call(lead)]
        leads = _lead_paths(db, _PANORAMA, 1)
        assert len(leads) == 1
        assert leads[0] in (f1, f2)

    def test_all_paths_excluded_by_state_is_distinguishable(self, client, tmp_path):
        """A5#4: a response with copied/moved == 0 used to give no way to tell
        'nothing here qualified for this action' apart from 'it qualified but
        every file op failed'. `matched` makes that explicit."""
        rejected_a = _make_file(tmp_path, "a.jpg")
        rejected_b = _make_file(tmp_path, "b.jpg")
        db = _db(tmp_path, [(rejected_a, 1), (rejected_b, 1)])
        with (
            mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)),
            mock.patch(f"{_EXPORT_MODULE}._allowed_export_roots", return_value=[str(tmp_path)]),
        ):
            resp = client.post("/api/cull/apply", json={
                "paths": [rejected_a, rejected_b], "action": "copy_keeps",
                "target_dir": str(tmp_path / "k"), "dry_run": True,
                "include_companions": False,
            })
        body = resp.json()
        assert body["would_copy"] == []
        assert body["matched"] == 0
        assert body["excluded_by_state"] == 2


class TestCullAuth:
    def test_regular_user_forbidden(self, regular_client, tmp_path):
        resp = regular_client.post("/api/cull/apply", json={
            "paths": ["/a.jpg"], "action": "copy_keeps", "target_dir": "/x",
        })
        assert resp.status_code in (401, 403)


class TestCullCapabilities:
    """GET /api/config's `cull` key (api.models.discovery.CullCapabilities).

    It mirrors /api/cull/apply's own two-part refusal on `trash_rejects` --
    403 when `viewer.cull.allow_trash` is off, 400 when `send2trash` is
    missing -- as two separate booleans, so a client can tell "an operator
    disabled this" apart from "this environment is missing a package" without
    calling the destructive endpoint just to read its error.

    `gallery.py` reads the package's importability off the module-scope
    `HAS_SEND2TRASH` constant (set once, at import time, via a plain
    `try: import send2trash / except ImportError` -- the same idiom
    `db.connection` uses for `HAS_SQLITE_VEC`), not a per-request probe. A
    process-wide `mock.patch.dict("sys.modules", {"send2trash": None})`
    would do nothing to it, since it is read once at import and never
    consulted again, so these tests patch `HAS_SEND2TRASH` itself instead --
    the only thing `_cull_capabilities` actually reads for the package half
    of the answer. `allow_trash` goes through the shared
    `api.config.cull_allow_trash` helper, which coerces with plain Python
    truthiness -- see `test_ambiguous_allow_trash_values_never_500_or_disagree`
    below for the values that made this matter (Fix 2).
    """

    def _cull_payload(self, client, allow_trash, package_present):
        # Merge onto the real VIEWER_CONFIG rather than replacing it outright:
        # /api/config also reads 'defaults', 'pagination', 'display', etc.,
        # and a bare {"cull": {...}} would 500 on a KeyError for those.
        config = {**gallery_module.VIEWER_CONFIG, "cull": {"allow_trash": allow_trash}}
        with (
            mock.patch(f"{_GALLERY_MODULE}.VIEWER_CONFIG", config),
            mock.patch(f"{_GALLERY_MODULE}.HAS_SEND2TRASH", package_present),
        ):
            resp = client.get("/api/config")
        assert resp.status_code == 200
        return resp.json()["cull"]

    def test_trash_off_package_present(self, client):
        assert self._cull_payload(client, allow_trash=False, package_present=True) == {
            "allow_trash": False, "trash_available": False,
        }

    def test_trash_on_package_absent(self, client):
        assert self._cull_payload(client, allow_trash=True, package_present=False) == {
            "allow_trash": True, "trash_available": False,
        }

    def test_trash_on_package_present(self, client):
        assert self._cull_payload(client, allow_trash=True, package_present=True) == {
            "allow_trash": True, "trash_available": True,
        }

    def test_trash_off_package_absent(self, client):
        assert self._cull_payload(client, allow_trash=False, package_present=False) == {
            "allow_trash": False, "trash_available": False,
        }

    def test_cull_null_in_config_is_treated_as_absent(self, client):
        """`"cull": null` is valid JSON an operator can write; `allow_trash`
        must fall back to False rather than raising on `None.get(...)`."""
        config = {**gallery_module.VIEWER_CONFIG, "cull": None}
        with (
            mock.patch(f"{_GALLERY_MODULE}.VIEWER_CONFIG", config),
            mock.patch(f"{_GALLERY_MODULE}.HAS_SEND2TRASH", True),
        ):
            resp = client.get("/api/config")
        assert resp.status_code == 200
        assert resp.json()["cull"] == {"allow_trash": False, "trash_available": False}

    def test_the_real_probe_finds_the_installed_package(self):
        """Every other test in this class patches `HAS_SEND2TRASH` directly,
        so none of them ever exercise the real `import send2trash` that sets
        it -- a misspelled module name (`send_2_trash`, `send2Trash`) or an
        inverted `try`/`except` would still pass all of them, and
        `/api/config` would report `trash_available: false` on a perfectly
        good install with nothing red.

        `HAS_SEND2TRASH` is set once, at import time, so there is no
        per-request probe left to re-run -- it replaced the old
        `_send2trash_available` memo (primed lazily via
        `importlib.util.find_spec`, benchmarked slower than a plain import
        with no memo at all) with a plain module-scope constant, the same
        idiom `db.connection` uses for `HAS_SQLITE_VEC`. What this test can
        still do is assert the UNPATCHED value directly: a typo'd import
        name flips it to `False` immediately at import, with no mock
        involved. `send2trash` is a base dependency (`requirements.txt` and
        both lock files, and CI installs it in every job that collects this
        file), not an extra, so asserting it resolves `True` in this venv is
        not environment-fragile; it is exactly the packaging guarantee that
        keeps this assertion meaningful.
        """
        assert gallery_module.HAS_SEND2TRASH is True


class TestCullAllowTrashCoercion:
    """Fix 2: `cull_allow_trash` (api/config.py) coerces the raw config value
    with plain Python truthiness before either reader (export.py's guard,
    gallery.py's `/api/config` report) sees it, so an ambiguous stored value
    can no longer make `/api/config` 500 (Pydantic strict-bool validation on
    a non-bool) or report a self-contradictory pair (`trash_available: true`
    while `allow_trash: false`, the "false" string case: `"false" and True`
    is `True` in Python, but Pydantic's lax bool parsing coerced the OLD raw
    `allow_trash` field to `False`).

    Verifies the fix through a real `/api/config` request (not a unit test of
    the helper in isolation), because the defect was end-to-end: it lived in
    the response model's field type meeting an uncoerced value on the wire.
    """

    def _cull_payload(self, client, raw_allow_trash, package_present):
        config = {**gallery_module.VIEWER_CONFIG, "cull": {"allow_trash": raw_allow_trash}}
        with (
            mock.patch(f"{_GALLERY_MODULE}.VIEWER_CONFIG", config),
            mock.patch(f"{_GALLERY_MODULE}.HAS_SEND2TRASH", package_present),
        ):
            resp = client.get("/api/config")
        return resp

    @pytest.mark.parametrize("raw_allow_trash", [None, "enabled", "false"])
    def test_ambiguous_allow_trash_values_never_500_or_disagree(self, client, raw_allow_trash):
        """None (a config with `"cull": {"allow_trash": null}`), a non-boolean
        string ("enabled"), and the ambiguous quoted-boolean string ("false",
        which Python truthiness reads as ENABLED, matching export.py's own
        `and`-based check) must all still return 200 with a payload where
        `trash_available` is exactly `allow_trash and <package present>` --
        never a 500, and never a pair where `trash_available` is true while
        `allow_trash` is false or vice versa.
        """
        for package_present in (True, False):
            resp = self._cull_payload(client, raw_allow_trash, package_present)
            assert resp.status_code == 200
            cull = resp.json()["cull"]
            expected_allow_trash = bool(raw_allow_trash)
            assert cull["allow_trash"] == expected_allow_trash
            assert cull["trash_available"] == (expected_allow_trash and package_present)
