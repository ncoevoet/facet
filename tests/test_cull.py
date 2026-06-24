"""Tests for POST /api/cull/apply (api/routers/export.py).

Data-safety is the whole point: copy is additive and dry-run by default;
move/trash are destructive and pass through the same validated allow-list;
trashing is OS-trash gated behind viewer.cull.allow_trash. A real temp DB backs
get_db; real files under tmp_path let resolve_photo_disk_path resolve to disk
(no scan dirs in tests -> file-exists check only).
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


def _empty_db(tmp_path):
    db = str(tmp_path / "t.db")
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE photos (path TEXT PRIMARY KEY, filename TEXT)")
    conn.commit()
    conn.close()
    return db


def _make_file(tmp_path, name, content=b"DATA"):
    p = tmp_path / name
    p.write_bytes(content)
    return str(p)


class TestCullApply:
    def test_copy_keeps_dry_run_writes_nothing(self, client, tmp_path):
        path = _make_file(tmp_path, "a.jpg")
        db = _empty_db(tmp_path)
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
        assert not os.path.exists(target)

    def test_copy_keeps_real_copies_and_keeps_original(self, client, tmp_path):
        path = _make_file(tmp_path, "a.jpg")
        db = _empty_db(tmp_path)
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
        db = _empty_db(tmp_path)
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

    def test_move_outside_allowlist_403(self, client, tmp_path):
        path = _make_file(tmp_path, "a.jpg")
        db = _empty_db(tmp_path)
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

    def test_move_requires_target_dir(self, client, tmp_path):
        path = _make_file(tmp_path, "a.jpg")
        db = _empty_db(tmp_path)
        with mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)):
            resp = client.post("/api/cull/apply", json={
                "paths": [path], "action": "move_rejects", "dry_run": True,
            })
        assert resp.status_code == 400

    def test_trash_disabled_by_default_403(self, client, tmp_path):
        path = _make_file(tmp_path, "a.jpg")
        db = _empty_db(tmp_path)
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
        db = _empty_db(tmp_path)
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
        db = _empty_db(tmp_path)
        with mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)):
            resp = client.post("/api/cull/apply", json={"action": "copy_keeps"})
        assert resp.status_code == 400


class TestCullAuth:
    def test_regular_user_forbidden(self, regular_client, tmp_path):
        resp = regular_client.post("/api/cull/apply", json={
            "paths": ["/a.jpg"], "action": "copy_keeps", "target_dir": "/x",
        })
        assert resp.status_code in (401, 403)
