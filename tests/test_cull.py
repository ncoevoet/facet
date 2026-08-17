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

_EXPORT_MODULE = "api.routers.export"


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
    bracket/panorama fixtures. Creates a photos table + rows.

    ``date_taken`` is here because the lead reassignment orders survivors by
    capture order, the way the detector picked the original lead. A fixture
    missing a column the code under test selects fails as an OperationalError,
    not as a wrong answer -- which is how this column came to be added.
    """
    db = str(tmp_path / "t.db")
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE photos ("
        "path TEXT PRIMARY KEY, filename TEXT, is_rejected INTEGER DEFAULT 0, "
        "sequence_kind TEXT, sequence_group_id INTEGER, "
        "is_sequence_lead INTEGER DEFAULT 0, sequence_ev_offset REAL, "
        "date_taken TEXT)"
    )
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
