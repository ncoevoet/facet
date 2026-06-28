"""Automatic weight snapshots replace loose config backups (Phase 2).

Every weight-mutating path records a weight_config_snapshots row of the previous
weights before overwriting scoring_config.json. Pure-weight writers no longer drop a
loose ``scoring_config.json.backup.<ts>`` file; mixed writers (modifiers/filters) keep
it. Recompute no longer snapshots the whole DB; ``database.py --backup`` does.
"""

import glob
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from api import create_app
from api.auth import CurrentUser, require_authenticated
from db import init_database, record_weight_snapshot, get_connection

_AUTH_MODULE = "api.auth"
_CMP_MODULE = "api.routers.comparison"
_STATS_MODULE = "api.routers.stats"
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_VIEWER_CONFIG = {
    "password": "",
    "edition_password": "secret",
    "features": {},
    "display": {"image_jpeg_quality": 96},
}


@pytest.fixture(autouse=True)
def _patch_config():
    with (
        mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", _VIEWER_CONFIG),
        mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=False),
    ):
        yield


@pytest.fixture
def env(tmp_path):
    db = str(tmp_path / "t.db")
    init_database(db)
    cfg = tmp_path / "scoring_config.json"
    cfg.write_text(json.dumps({
        "categories": [
            {
                "name": "portrait",
                "weights": {"aesthetic_percent": 40, "composition_percent": 60},
                "modifiers": {"bonus": 0.0},
            },
        ],
    }))
    return {"db": db, "cfg": cfg}


def _edition_client():
    app = create_app()
    app.dependency_overrides[require_authenticated] = lambda: CurrentUser(
        user_id="u1", role="admin", edition_authenticated=True
    )
    return TestClient(app)


def _real_db_cm(db_path):
    @contextmanager
    def _ctx():
        with get_connection(db_path) as conn:
            yield conn
    return _ctx


def _loose_backups(cfg):
    return glob.glob(f"{cfg}.backup.*")


def _snapshots(db, created_by=None):
    sql = "SELECT category, weights, created_by FROM weight_config_snapshots"
    params = ()
    if created_by is not None:
        sql += " WHERE created_by = ?"
        params = (created_by,)
    with get_connection(db) as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


class TestHelper:
    def test_insert_path_mode_opens_and_commits(self, env):
        sid = record_weight_snapshot(
            "portrait", {"aesthetic_percent": 40}, created_by="manual", db=env["db"]
        )
        rows = _snapshots(env["db"])
        assert len(rows) == 1
        assert rows[0]["category"] == "portrait"
        assert json.loads(rows[0]["weights"]) == {"aesthetic_percent": 40}
        assert rows[0]["created_by"] == "manual"
        assert isinstance(sid, int)

    def test_insert_conn_mode_caller_commits(self, env):
        with get_connection(env["db"]) as conn:
            record_weight_snapshot("x", {"a_percent": 1}, created_by="auto:edit", db=conn)
            conn.commit()
        assert len(_snapshots(env["db"])) == 1


class TestUpdateWeights:
    ENDPOINT = "/api/config/update_weights"

    def test_weights_only_records_snapshot_no_loose_file(self, env):
        client = _edition_client()
        with (
            mock.patch(f"{_CMP_MODULE}._CONFIG_PATH", str(env["cfg"])),
            mock.patch(f"{_CMP_MODULE}.reload_config", lambda: None),
            mock.patch(f"{_CMP_MODULE}.get_db", _real_db_cm(env["db"])),
        ):
            resp = client.post(self.ENDPOINT, json={
                "category": "portrait",
                "weights": {"aesthetic_percent": 50, "composition_percent": 50},
            })
        assert resp.status_code == 200, resp.text
        assert resp.json()["backup"] is None
        rows = _snapshots(env["db"], created_by="auto:edit")
        assert len(rows) == 1
        assert json.loads(rows[0]["weights"]) == {"aesthetic_percent": 40, "composition_percent": 60}
        assert _loose_backups(env["cfg"]) == []
        cfg = json.loads(env["cfg"].read_text())
        assert cfg["categories"][0]["weights"]["aesthetic_percent"] == 50

    def test_with_modifiers_keeps_loose_file(self, env):
        client = _edition_client()
        with (
            mock.patch(f"{_CMP_MODULE}._CONFIG_PATH", str(env["cfg"])),
            mock.patch(f"{_CMP_MODULE}.reload_config", lambda: None),
            mock.patch(f"{_CMP_MODULE}.get_db", _real_db_cm(env["db"])),
        ):
            resp = client.post(self.ENDPOINT, json={
                "category": "portrait",
                "weights": {"aesthetic_percent": 50, "composition_percent": 50},
                "modifiers": {"bonus": 0.5},
            })
        assert resp.status_code == 200, resp.text
        assert resp.json()["backup"] is not None
        assert len(_snapshots(env["db"], created_by="auto:edit")) == 1
        assert len(_loose_backups(env["cfg"])) == 1


class TestRestoreWeights:
    ENDPOINT = "/api/config/restore_weights"

    def test_records_pre_restore_snapshot_no_loose_file(self, env):
        sid = record_weight_snapshot(
            "portrait", {"aesthetic_percent": 10, "composition_percent": 90},
            created_by="manual", db=env["db"],
        )
        client = _edition_client()
        with (
            mock.patch(f"{_CMP_MODULE}._CONFIG_PATH", str(env["cfg"])),
            mock.patch(f"{_CMP_MODULE}.reload_config", lambda: None),
            mock.patch(f"{_CMP_MODULE}.get_db", _real_db_cm(env["db"])),
        ):
            resp = client.post(self.ENDPOINT, json={"snapshot_id": sid})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["category"] == "portrait"
        assert "backup_path" not in data
        cfg = json.loads(env["cfg"].read_text())
        assert cfg["categories"][0]["weights"] == {"aesthetic_percent": 10, "composition_percent": 90}
        pre = _snapshots(env["db"], created_by="auto:pre_restore")
        assert len(pre) == 1
        assert json.loads(pre[0]["weights"]) == {"aesthetic_percent": 40, "composition_percent": 60}
        assert _loose_backups(env["cfg"]) == []


class TestStatsCategoryUpdate:
    ENDPOINT = "/api/stats/categories/update"

    def test_weights_only_records_snapshot_no_loose_file(self, env):
        client = _edition_client()
        with (
            mock.patch(f"{_STATS_MODULE}._CONFIG_PATH", str(env["cfg"])),
            mock.patch(f"{_STATS_MODULE}.reload_config", lambda: None),
            mock.patch(f"{_STATS_MODULE}.get_db", _real_db_cm(env["db"])),
        ):
            resp = client.post(self.ENDPOINT, json={
                "category": "portrait",
                "weights": {"aesthetic_percent": 70, "composition_percent": 30},
            })
        assert resp.status_code == 200, resp.text
        assert resp.json()["backup"] is None
        rows = _snapshots(env["db"], created_by="auto:cat_edit")
        assert len(rows) == 1
        assert json.loads(rows[0]["weights"]) == {"aesthetic_percent": 40, "composition_percent": 60}
        assert _loose_backups(env["cfg"]) == []

    def test_with_modifiers_keeps_loose_file(self, env):
        client = _edition_client()
        with (
            mock.patch(f"{_STATS_MODULE}._CONFIG_PATH", str(env["cfg"])),
            mock.patch(f"{_STATS_MODULE}.reload_config", lambda: None),
            mock.patch(f"{_STATS_MODULE}.get_db", _real_db_cm(env["db"])),
        ):
            resp = client.post(self.ENDPOINT, json={
                "category": "portrait",
                "modifiers": {"bonus": 1.0},
            })
        assert resp.status_code == 200, resp.text
        assert resp.json()["backup"] is not None
        assert len(_snapshots(env["db"], created_by="auto:cat_edit")) == 1
        assert len(_loose_backups(env["cfg"])) == 1


class TestCli:
    def test_recompute_takes_no_db_backup(self, tmp_path):
        db = str(tmp_path / "rc.db")
        init_database(db)
        result = subprocess.run(
            [sys.executable, "facet.py", "--recompute-category", "portrait",
             "--db", db, "--config", "scoring_config.json"],
            capture_output=True, text=True, cwd=_ROOT,
        )
        assert result.returncode == 0, result.stderr
        assert glob.glob(f"{db}.backup-*") == []

    def test_database_backup_creates_snapshot(self, tmp_path):
        db = str(tmp_path / "b.db")
        init_database(db)
        result = subprocess.run(
            [sys.executable, "database.py", "--db", db, "--backup"],
            capture_output=True, text=True, cwd=_ROOT,
        )
        assert result.returncode == 0, result.stderr
        assert len(glob.glob(f"{db}.backup-*")) == 1
