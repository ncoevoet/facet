"""Tests for the scan endpoint (api/routers/scan.py)."""

import json
import os
import signal
import subprocess
import sys
from collections import deque
from datetime import timedelta
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from api import create_app
from api.auth import CurrentUser, create_access_token, require_authenticated
from api.routers.scan import SCAN_STREAM_PURPOSE

_AUTH_MODULE = "api.auth"
_ROUTER_MODULE = "api.routers.scan"


def _viewer_config_with_scan(enabled=True):
    """Return a viewer config with scan feature flag."""
    return {"password": "", "edition_password": "", "features": {"show_scan_button": enabled}}


def _make_superadmin_app(viewer_cfg=None):
    """Create app + client with superadmin overrides."""
    viewer_cfg = viewer_cfg or _viewer_config_with_scan()
    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)
    sa = CurrentUser(user_id="sa1", role="superadmin")
    app.dependency_overrides[require_authenticated] = lambda: sa
    return app, client, sa


class TestStartScan:
    """Tests for POST /api/scan/start."""

    def test_start_scan_requires_superadmin(self):
        """Admin role (not superadmin) gets 403."""
        viewer_cfg = _viewer_config_with_scan()
        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", viewer_cfg),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=True),
        ):
            app = create_app()
            client = TestClient(app, raise_server_exceptions=False)
            admin = CurrentUser(user_id="a1", role="admin")
            app.dependency_overrides[require_authenticated] = lambda: admin
            resp = client.post("/api/scan/start", json={"directories": ["/photos"]})

        assert resp.status_code == 403

    def test_start_scan_feature_disabled(self):
        """When show_scan_button is False, superadmin gets 403."""
        viewer_cfg = _viewer_config_with_scan(enabled=False)
        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", viewer_cfg),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=True),
            mock.patch(f"{_ROUTER_MODULE}.VIEWER_CONFIG", viewer_cfg),
        ):
            app, client, _ = _make_superadmin_app(viewer_cfg)
            resp = client.post("/api/scan/start", json={"directories": ["/photos"]})

        assert resp.status_code == 403
        assert "not enabled" in resp.json()["detail"].lower()

    def test_start_scan_empty_directories(self):
        """Empty directories list returns 400."""
        viewer_cfg = _viewer_config_with_scan()
        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", viewer_cfg),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=True),
            mock.patch(f"{_ROUTER_MODULE}.VIEWER_CONFIG", viewer_cfg),
            mock.patch(f"{_ROUTER_MODULE}.get_all_scan_directories", return_value=[]),
        ):
            app, client, _ = _make_superadmin_app(viewer_cfg)
            resp = client.post("/api/scan/start", json={"directories": []})

        assert resp.status_code == 400


class TestScanStatus:
    """Tests for GET /api/scan/status."""

    def test_scan_status_returns_state(self):
        """Mock scan state is returned correctly."""
        viewer_cfg = _viewer_config_with_scan()
        mock_state = {
            'running': True,
            'process': None,
            'output_lines': deque(["Processing photo 1/10", "Processing photo 2/10"], maxlen=500),
            'started_at': 1000.0,
            'directories': ["/photos"],
            'exit_code': None,
        }

        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", viewer_cfg),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=True),
            mock.patch(f"{_ROUTER_MODULE}.VIEWER_CONFIG", viewer_cfg),
            mock.patch(f"{_ROUTER_MODULE}._scan_state", mock_state),
        ):
            app, client, _ = _make_superadmin_app(viewer_cfg)
            resp = client.get("/api/scan/status")

        assert resp.status_code == 200
        body = resp.json()
        assert body["running"] is True
        assert len(body["output"]) == 2
        assert body["directories"] == ["/photos"]
        assert body["elapsed_seconds"] is not None

    def test_scan_status_idle(self):
        """When no scan is running, returns idle state."""
        viewer_cfg = _viewer_config_with_scan()
        mock_state = {
            'running': False,
            'process': None,
            'output_lines': deque(maxlen=500),
            'started_at': None,
            'directories': [],
            'exit_code': None,
        }

        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", viewer_cfg),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=True),
            mock.patch(f"{_ROUTER_MODULE}.VIEWER_CONFIG", viewer_cfg),
            mock.patch(f"{_ROUTER_MODULE}._scan_state", mock_state),
        ):
            app, client, _ = _make_superadmin_app(viewer_cfg)
            resp = client.get("/api/scan/status")

        assert resp.status_code == 200
        body = resp.json()
        assert body["running"] is False
        assert body["output"] == []
        assert body["elapsed_seconds"] is None

    def test_scan_status_feature_disabled(self):
        """When scan feature is disabled, status returns 403."""
        viewer_cfg = _viewer_config_with_scan(enabled=False)
        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", viewer_cfg),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=True),
            mock.patch(f"{_ROUTER_MODULE}.VIEWER_CONFIG", viewer_cfg),
        ):
            app, client, _ = _make_superadmin_app(viewer_cfg)
            resp = client.get("/api/scan/status")

        assert resp.status_code == 403


class TestScanStreamToken:
    """F8': /stream_token mints a short-lived, single-purpose token so the
    long-lived superadmin JWT no longer needs to travel in the stream URL."""

    def test_requires_superadmin(self):
        viewer_cfg = _viewer_config_with_scan()
        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", viewer_cfg),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=True),
            mock.patch(f"{_ROUTER_MODULE}.VIEWER_CONFIG", viewer_cfg),
        ):
            app = create_app()
            client = TestClient(app, raise_server_exceptions=False)
            admin = CurrentUser(user_id="a1", role="admin")
            app.dependency_overrides[require_authenticated] = lambda: admin
            resp = client.get("/api/scan/stream_token")

        assert resp.status_code == 403

    def test_feature_disabled(self):
        viewer_cfg = _viewer_config_with_scan(enabled=False)
        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", viewer_cfg),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=True),
            mock.patch(f"{_ROUTER_MODULE}.VIEWER_CONFIG", viewer_cfg),
        ):
            app, client, _ = _make_superadmin_app(viewer_cfg)
            resp = client.get("/api/scan/stream_token")

        assert resp.status_code == 403

    def test_superadmin_gets_short_lived_purpose_token(self):
        viewer_cfg = _viewer_config_with_scan()
        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", viewer_cfg),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=True),
            mock.patch(f"{_ROUTER_MODULE}.VIEWER_CONFIG", viewer_cfg),
        ):
            app, client, _ = _make_superadmin_app(viewer_cfg)
            resp = client.get("/api/scan/stream_token")

        assert resp.status_code == 200
        from api.auth import decode_access_token
        from api.routers.scan import SCAN_STREAM_PURPOSE, _verify_superadmin_token
        token = resp.json()["token"]
        payload = decode_access_token(token)
        assert payload["purpose"] == SCAN_STREAM_PURPOSE
        assert payload["role"] == "superadmin"
        # The minted token is a valid credential for the stream endpoint.
        _verify_superadmin_token(token)


class TestScanStreamAuth:
    """GET /api/scan/stream rejects unidentified / non-superadmin callers."""

    def test_missing_token_401(self):
        viewer_cfg = _viewer_config_with_scan()
        with mock.patch(f"{_ROUTER_MODULE}.VIEWER_CONFIG", viewer_cfg):
            app = create_app()
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/api/scan/stream")
        assert resp.status_code == 401

    def test_garbage_token_403(self):
        viewer_cfg = _viewer_config_with_scan()
        with mock.patch(f"{_ROUTER_MODULE}.VIEWER_CONFIG", viewer_cfg):
            app = create_app()
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/api/scan/stream", params={"token": "garbage"})
        assert resp.status_code == 403

    def test_plain_superadmin_jwt_rejected(self):
        """The long-lived session JWT (no scan_stream purpose) must not work here."""
        viewer_cfg = _viewer_config_with_scan()
        token = create_access_token({"sub": "sa1", "role": "superadmin"})
        with mock.patch(f"{_ROUTER_MODULE}.VIEWER_CONFIG", viewer_cfg):
            app = create_app()
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/api/scan/stream", params={"token": token})
        assert resp.status_code == 403

    def test_minted_stream_token_accepted(self):
        viewer_cfg = _viewer_config_with_scan()
        mock_state = {
            'running': False,
            'process': None,
            'output_lines': deque(maxlen=500),
            'started_at': None,
            'directories': [],
            'exit_code': None,
            'progress': None,
        }
        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", viewer_cfg),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=True),
            mock.patch(f"{_ROUTER_MODULE}.VIEWER_CONFIG", viewer_cfg),
            mock.patch(f"{_ROUTER_MODULE}._scan_state", mock_state),
        ):
            app, client, _ = _make_superadmin_app(viewer_cfg)
            token = client.get("/api/scan/stream_token").json()["token"]
            resp = client.get("/api/scan/stream", params={"token": token})
        assert resp.status_code == 200

    def test_expired_minted_token_rejected(self):
        viewer_cfg = _viewer_config_with_scan()
        token = create_access_token(
            {"sub": "sa1", "role": "superadmin", "purpose": SCAN_STREAM_PURPOSE},
            expires_delta=timedelta(seconds=-1),
        )
        with mock.patch(f"{_ROUTER_MODULE}.VIEWER_CONFIG", viewer_cfg):
            app = create_app()
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/api/scan/stream", params={"token": token})
        assert resp.status_code == 403


class TestScanDirectories:
    """Tests for GET /api/scan/directories."""

    def test_scan_directories_returns_list(self):
        """Configured directories are returned."""
        viewer_cfg = _viewer_config_with_scan()
        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", viewer_cfg),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=True),
            mock.patch(f"{_ROUTER_MODULE}.VIEWER_CONFIG", viewer_cfg),
            mock.patch(f"{_ROUTER_MODULE}.get_all_scan_directories", return_value=["/photos", "/backup"]),
            mock.patch(f"{_ROUTER_MODULE}.get_user_directories", return_value=["/photos"]),
        ):
            app, client, _ = _make_superadmin_app(viewer_cfg)
            resp = client.get("/api/scan/directories")

        assert resp.status_code == 200
        body = resp.json()
        dirs = body["directories"]
        assert len(dirs) == 2
        # /photos is owned by the user, /backup is shared
        paths = [d["path"] for d in dirs]
        assert "/photos" in paths
        assert "/backup" in paths

    def test_scan_directories_feature_disabled(self):
        """When scan feature is disabled, directories returns 403."""
        viewer_cfg = _viewer_config_with_scan(enabled=False)
        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", viewer_cfg),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=True),
            mock.patch(f"{_ROUTER_MODULE}.VIEWER_CONFIG", viewer_cfg),
        ):
            app, client, _ = _make_superadmin_app(viewer_cfg)
            resp = client.get("/api/scan/directories")

        assert resp.status_code == 403


class TestRecompute:
    """Tests for POST /api/scan/recompute.

    Uses the shared ``edition_client`` / ``regular_client`` / ``anonymous_client``
    fixtures from ``tests/conftest.py`` for RBAC, per the project rule against
    ``mock.patch`` on auth dependencies.
    """

    ENDPOINT = "/api/scan/recompute"

    @pytest.fixture(autouse=True)
    def _reset_scan_state(self):
        from api.routers.scan import _scan_state
        original = dict(_scan_state)
        yield
        _scan_state.clear()
        _scan_state.update(original)

    def test_requires_edition_403(self, regular_client):
        resp = regular_client.post(self.ENDPOINT)
        assert resp.status_code == 403

    def test_anonymous_401(self, anonymous_client):
        resp = anonymous_client.post(self.ENDPOINT)
        assert resp.status_code == 401

    def test_bodyless_post_is_rejected_without_spawning(self, edition_client):
        """A body-less POST is a CORS simple request and never preflights, so it
        would let any page the user opens start a full-library rewrite."""
        from api.routers import scan as scan_router

        with mock.patch.object(scan_router.subprocess, "Popen") as mock_popen:
            resp = edition_client.post(self.ENDPOINT)

        assert resp.status_code == 422
        mock_popen.assert_not_called()

    def test_confirm_false_is_rejected_without_spawning(self, edition_client):
        from api.routers import scan as scan_router

        with mock.patch.object(scan_router.subprocess, "Popen") as mock_popen:
            resp = edition_client.post(self.ENDPOINT, json={"confirm": False})

        assert resp.status_code == 400
        mock_popen.assert_not_called()

    def test_lock_is_released_when_spawn_fails(self, edition_client):
        """An unexpected error must not leave the shared job lock held, which
        would wedge every later scan and recompute behind a permanent 409."""
        from api.routers import scan as scan_router

        with mock.patch.object(scan_router.subprocess, "Popen", side_effect=RuntimeError("boom")):
            resp = edition_client.post(self.ENDPOINT, json={"confirm": True})

        assert resp.status_code == 500
        assert not scan_router._scan_lock.locked()

    def test_conflict_when_a_job_is_running(self, edition_client):
        from api.routers.scan import _scan_state
        _scan_state['running'] = True

        resp = edition_client.post(self.ENDPOINT, json={"confirm": True})

        assert resp.status_code == 409

    def test_starts_recompute_with_fixed_server_origin_argv(self, edition_client):
        from api.routers import scan as scan_router

        mock_proc = mock.MagicMock()
        mock_proc.pid = 4242
        mock_proc.stdout = iter([])
        mock_proc.wait.return_value = 0

        with mock.patch.object(scan_router.subprocess, "Popen", return_value=mock_proc) as mock_popen:
            resp = edition_client.post(self.ENDPOINT, json={"confirm": True})

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["pid"] == 4242

        cmd = mock_popen.call_args[0][0]
        assert cmd[0] == scan_router.sys.executable
        assert scan_router.FACET_SCRIPT in cmd
        assert "--recompute-average" in cmd
        assert "--config" in cmd

        assert scan_router._scan_state["kind"] == scan_router.JOB_KIND_RECOMPUTE


class TestRecomputeStatus:
    """Tests for GET /api/scan/recompute_status."""

    ENDPOINT = "/api/scan/recompute_status"

    @pytest.fixture(autouse=True)
    def _reset_scan_state(self):
        from api.routers.scan import _scan_state
        original = dict(_scan_state)
        yield
        _scan_state.clear()
        _scan_state.update(original)

    def test_requires_edition_403(self, regular_client):
        resp = regular_client.get(self.ENDPOINT)
        assert resp.status_code == 403

    def test_anonymous_401(self, anonymous_client):
        resp = anonymous_client.get(self.ENDPOINT)
        assert resp.status_code == 401

    def test_returns_only_the_minimal_fields(self, edition_client):
        from api.routers.scan import _scan_state
        _scan_state.update({
            'running': True,
            'kind': 'recompute',
            'progress': {'phase': 'recompute', 'current': 10, 'total': 100},
            'exit_code': None,
            'output_lines': deque(['a log line the recompute status must not leak'], maxlen=500),
        })

        resp = edition_client.get(self.ENDPOINT)

        assert resp.status_code == 200
        data = resp.json()
        assert set(data.keys()) == {"running", "kind", "progress", "exit_code"}
        assert data["running"] is True
        assert data["kind"] == "recompute"
        assert data["progress"]["current"] == 10
        assert data["exit_code"] is None


class TestLibraryLock:
    """``facet.LibraryLock`` -- the cross-process mutex that keeps a
    recompute's single long transaction from colliding with another
    recompute or a scan (see facet.py, api/routers/scan.py)."""

    def test_second_acquire_is_refused_while_first_holds_it(self, tmp_path):
        from facet import LibraryLock, LibraryLockError

        db_path = str(tmp_path / "photos.db")
        first = LibraryLock(db_path, kind="recompute")
        first.acquire()
        try:
            with pytest.raises(LibraryLockError):
                LibraryLock(db_path, kind="recompute").acquire()
        finally:
            first.release()

    def test_conflict_message_names_kind_pid_and_origin(self, tmp_path, monkeypatch):
        from facet import JOB_ORIGIN_ENV_VAR, LibraryLock, LibraryLockError

        monkeypatch.setenv(JOB_ORIGIN_ENV_VAR, "viewer")
        db_path = str(tmp_path / "photos.db")
        first = LibraryLock(db_path, kind="recompute")
        first.acquire()
        try:
            with pytest.raises(LibraryLockError) as exc_info:
                LibraryLock(db_path, kind="recompute").acquire()
        finally:
            first.release()

        message = str(exc_info.value)
        assert "recompute" in message
        assert "viewer" in message
        assert str(os.getpid()) in message

    def test_stale_lock_from_a_dead_pid_self_heals(self, tmp_path):
        """A holder that crashed without releasing must not wedge the lock
        forever: the next acquire steals it once the recorded PID is dead."""
        from facet import LibraryLock, _library_lock_path

        db_path = str(tmp_path / "photos.db")
        dead_proc = subprocess.Popen([sys.executable, "-c", "pass"])
        dead_proc.wait()

        lock_path = _library_lock_path(db_path)
        os.makedirs(os.path.dirname(lock_path), exist_ok=True)
        with open(lock_path, "w") as f:
            json.dump(
                {"pid": dead_proc.pid, "kind": "recompute", "origin": "cli", "started_at": 0},
                f,
            )

        lock = LibraryLock(db_path, kind="recompute")
        lock.acquire()
        assert os.path.exists(lock_path)
        lock.release()
        assert not os.path.exists(lock_path)

    def test_release_on_exception_frees_the_lock(self, tmp_path):
        from facet import LibraryLock, _library_lock_path

        db_path = str(tmp_path / "photos.db")
        with pytest.raises(RuntimeError):
            with LibraryLock(db_path, kind="recompute"):
                raise RuntimeError("boom")

        assert not os.path.exists(_library_lock_path(db_path))

    def test_release_on_sigterm_frees_the_lock(self, tmp_path):
        from facet import LibraryLock, _library_lock_path

        db_path = str(tmp_path / "photos.db")
        with pytest.raises(KeyboardInterrupt):
            with LibraryLock(db_path, kind="recompute"):
                os.kill(os.getpid(), signal.SIGTERM)

        assert not os.path.exists(_library_lock_path(db_path))

    def test_sigterm_handler_is_restored_after_release(self, tmp_path):
        from facet import LibraryLock

        db_path = str(tmp_path / "photos.db")
        previous_handler = signal.getsignal(signal.SIGTERM)
        lock = LibraryLock(db_path, kind="recompute")
        lock.acquire()
        assert signal.getsignal(signal.SIGTERM) is signal.default_int_handler
        lock.release()
        assert signal.getsignal(signal.SIGTERM) is previous_handler

    def test_holder_is_none_when_no_lock_file(self, tmp_path):
        from facet import library_job_holder

        db_path = str(tmp_path / "photos.db")
        assert library_job_holder(db_path) is None

    def test_holder_reports_live_process_info(self, tmp_path):
        from facet import LibraryLock, library_job_holder

        db_path = str(tmp_path / "photos.db")
        lock = LibraryLock(db_path, kind="scan")
        lock.acquire()
        try:
            holder = library_job_holder(db_path)
            assert holder["pid"] == os.getpid()
            assert holder["kind"] == "scan"
            assert holder["origin"] == "cli"
        finally:
            lock.release()


class TestCrossProcessLibraryLock:
    """The viewer endpoints refuse a second job when a CLI-run recompute (or
    scan, for /recompute) already holds ``facet.LibraryLock`` -- proving the
    fix is visible cross-process, not just within the viewer's own state."""

    @pytest.fixture(autouse=True)
    def _cleanup_lock_file(self):
        from db.connection import DEFAULT_DB_PATH
        from facet import _library_lock_path

        lock_path = _library_lock_path(DEFAULT_DB_PATH)
        yield
        if os.path.exists(lock_path):
            os.remove(lock_path)

    @pytest.fixture(autouse=True)
    def _reset_scan_state(self):
        from api.routers.scan import _scan_state

        original = dict(_scan_state)
        yield
        _scan_state.clear()
        _scan_state.update(original)

    def _write_live_lock(self, kind="recompute", origin="cli"):
        from db.connection import DEFAULT_DB_PATH
        from facet import _library_lock_path

        lock_path = _library_lock_path(DEFAULT_DB_PATH)
        os.makedirs(os.path.dirname(lock_path), exist_ok=True)
        with open(lock_path, "w") as f:
            json.dump(
                {"pid": os.getpid(), "kind": kind, "origin": origin, "started_at": 0}, f,
            )

    def test_recompute_refused_when_a_cli_recompute_holds_the_lock(self, edition_client):
        self._write_live_lock(kind="recompute", origin="cli")

        resp = edition_client.post("/api/scan/recompute", json={"confirm": True})

        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert "recompute" in detail
        assert "cli" in detail

    def test_scan_refused_when_a_recompute_holds_the_lock(self):
        self._write_live_lock(kind="recompute", origin="viewer")
        viewer_cfg = _viewer_config_with_scan()
        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", viewer_cfg),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=True),
            mock.patch(f"{_ROUTER_MODULE}.VIEWER_CONFIG", viewer_cfg),
        ):
            app, client, _ = _make_superadmin_app(viewer_cfg)
            resp = client.post("/api/scan/start", json={"directories": ["/photos"]})

        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert "recompute" in detail
        assert "viewer" in detail

    def test_recompute_refused_when_a_cli_scan_is_in_progress(self, edition_client):
        from db.connection import DEFAULT_DB_PATH, get_connection

        with get_connection(DEFAULT_DB_PATH, row_factory=False) as conn:
            conn.execute(
                "INSERT INTO scan_runs (mode, args_json, total_files, heartbeat_at) "
                "VALUES ('multi-pass', '{}', 0, datetime('now'))"
            )
            conn.commit()
        try:
            resp = edition_client.post("/api/scan/recompute", json={"confirm": True})
            assert resp.status_code == 409
            assert "scan" in resp.json()["detail"].lower()
        finally:
            with get_connection(DEFAULT_DB_PATH, row_factory=False) as conn:
                conn.execute("DELETE FROM scan_runs")
                conn.commit()

    def test_recompute_spawns_subprocess_with_viewer_origin_env(self, edition_client):
        from api.routers import scan as scan_router
        from facet import JOB_ORIGIN_ENV_VAR

        mock_proc = mock.MagicMock()
        mock_proc.pid = 4242
        mock_proc.stdout = iter([])
        mock_proc.wait.return_value = 0

        with mock.patch.object(scan_router.subprocess, "Popen", return_value=mock_proc) as mock_popen:
            resp = edition_client.post("/api/scan/recompute", json={"confirm": True})

        assert resp.status_code == 200
        env = mock_popen.call_args.kwargs["env"]
        assert env[JOB_ORIGIN_ENV_VAR] == "viewer"
