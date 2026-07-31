"""Tests for the scan endpoint (api/routers/scan.py)."""

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

    def test_conflict_when_a_job_is_running(self, edition_client):
        from api.routers.scan import _scan_state
        _scan_state['running'] = True

        resp = edition_client.post(self.ENDPOINT)

        assert resp.status_code == 409

    def test_starts_recompute_with_fixed_server_origin_argv(self, edition_client):
        from api.routers import scan as scan_router

        mock_proc = mock.MagicMock()
        mock_proc.pid = 4242
        mock_proc.stdout = iter([])
        mock_proc.wait.return_value = 0

        with mock.patch.object(scan_router.subprocess, "Popen", return_value=mock_proc) as mock_popen:
            resp = edition_client.post(self.ENDPOINT)

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
