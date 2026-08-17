"""Tests for the scan endpoint (api/routers/scan.py)."""

import ast
import contextlib
import errno
import inspect
import json
import os
import signal
import subprocess
import sys
import threading
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
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FACET_SCRIPT = os.path.join(_REPO_ROOT, "facet.py")


@contextlib.contextmanager
def _library_lock_held(db_path, kind="recompute", origin="cli"):
    """Hold a real library lock the way a running job holds it.

    The lock is the OS lock on the file, not the file's existence, so tests
    that need a *live* holder must actually take it — hand-writing a JSON
    payload only ever simulates a leftover (dead) lock.
    """
    from facet import LibraryLock

    lock = LibraryLock(db_path, kind=kind)
    lock.origin = origin
    lock.acquire()
    try:
        yield lock
    finally:
        lock.release()


def _write_leftover_lock_file(db_path, pid, kind="recompute", origin="cli", started_at=0):
    """Write an unlocked lock file: what a crashed or rebooted holder leaves."""
    from facet import _library_lock_path

    lock_path = _library_lock_path(db_path)
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    with open(lock_path, "w") as f:
        json.dump({"pid": pid, "kind": kind, "origin": origin, "started_at": started_at}, f)
    return lock_path


def _spawn_lock_holder(db_path, kind="recompute"):
    """Start a separate process holding the lock; returns once it is held."""
    script = (
        "import sys, time\n"
        f"sys.path.insert(0, {_REPO_ROOT!r})\n"
        "from facet import LibraryLock\n"
        "LibraryLock(sys.argv[1], kind=sys.argv[2]).acquire()\n"
        "print('held', flush=True)\n"
        "time.sleep(60)\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", script, db_path, kind],
        stdout=subprocess.PIPE, text=True,
    )
    assert proc.stdout.readline().strip() == "held"
    return proc


def _run_facet(*argv):
    return subprocess.run(
        [sys.executable, _FACET_SCRIPT, *argv],
        capture_output=True, text=True, timeout=120,
    )


def _cli_flag_dests():
    """Every long flag the facet.py parser defines, as its argparse dest.

    Read off the parser's own ``add_argument`` calls rather than copied, so a
    flag added later turns up here whether or not anyone remembers this file.
    """
    with open(_FACET_SCRIPT, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    dests = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"):
            continue
        flags = [a.value for a in node.args
                 if isinstance(a, ast.Constant) and str(a.value).startswith("--")]
        if not flags:
            continue
        dest = next((kw.value.value for kw in node.keywords if kw.arg == "dest"), None)
        dests.add(dest or flags[0][2:].replace("-", "_"))
    return dests


def _peek_concurrently(db_path, peekers=16):
    """What ``peekers`` simultaneous ``library_job_holder`` calls each saw."""
    from facet import library_job_holder

    seen = []
    ready = threading.Barrier(peekers)

    def peek():
        ready.wait()
        seen.append(library_job_holder(db_path))

    threads = [threading.Thread(target=peek) for _ in range(peekers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return seen


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

    def test_lock_is_released_when_spawn_raises_uncaught_exception(self):
        """A5#1: an exception type the narrow ``except`` clause does not name
        (e.g. a RuntimeError from Thread.start under resource exhaustion)
        must still release the shared job lock -- it is the try/finally, not
        the except clause, that has to guarantee that. Without it this wedges
        every later /api/scan/start and /api/scan/recompute behind a
        permanent 409 until the process restarts."""
        from api.routers import scan as scan_router

        scan_router._scan_state['running'] = False
        viewer_cfg = _viewer_config_with_scan()
        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", viewer_cfg),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=True),
            mock.patch(f"{_ROUTER_MODULE}.VIEWER_CONFIG", viewer_cfg),
            mock.patch(f"{_ROUTER_MODULE}.get_all_scan_directories", return_value=["/photos"]),
            mock.patch.object(scan_router.subprocess, "Popen", side_effect=RuntimeError("boom")),
        ):
            app, client, _ = _make_superadmin_app(viewer_cfg)
            resp = client.post("/api/scan/start", json={"directories": ["/photos"]})

        assert resp.status_code == 500
        assert not scan_router._scan_lock.locked()

        # And the lock being free actually means a following start can run --
        # not just that .locked() reports False.
        with (
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", viewer_cfg),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=True),
            mock.patch(f"{_ROUTER_MODULE}.VIEWER_CONFIG", viewer_cfg),
            mock.patch(f"{_ROUTER_MODULE}.get_all_scan_directories", return_value=["/photos"]),
        ):
            scan_router._scan_state['running'] = False
            mock_proc = mock.MagicMock()
            mock_proc.pid = 4242
            mock_proc.stdout = iter([])
            mock_proc.wait.return_value = 0
            with mock.patch.object(scan_router.subprocess, "Popen", return_value=mock_proc):
                app, client, _ = _make_superadmin_app(viewer_cfg)
                resp = client.post("/api/scan/start", json={"directories": ["/photos"]})

        assert resp.status_code == 200


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

    def test_genuinely_failed_job_reads_as_failed_on_the_spawning_worker(self, edition_client):
        """The worker that actually ran the job still reports its real,
        non-zero exit code -- the fix must not turn every failure into an
        indeterminate result."""
        from api.routers.scan import _scan_state
        _scan_state.update({
            'running': False, 'kind': 'recompute', 'exit_code': 1, 'progress': None,
        })

        resp = edition_client.get(self.ENDPOINT)

        assert resp.status_code == 200
        data = resp.json()
        assert data["running"] is False
        assert data["kind"] == "recompute"
        assert data["exit_code"] == 1

    def test_local_scan_running_still_reports_running(self, edition_client):
        """A locally running job of ANY kind must still surface as running
        here -- this is the in-process mutual-exclusion signal that stops a
        client from retrying a recompute while a scan occupies the same
        job slot (``start_recompute`` 409s on ``_scan_state['running']``
        regardless of kind)."""
        from api.routers.scan import _scan_state
        _scan_state.update({
            'running': True, 'kind': 'scan', 'exit_code': None, 'progress': None,
        })

        resp = edition_client.get(self.ENDPOINT)

        assert resp.status_code == 200
        data = resp.json()
        assert data["running"] is True
        assert data["kind"] == "scan"

    def test_stale_local_scan_result_does_not_leak_into_recompute_status(self, edition_client):
        """A worker whose last local job was a finished *scan* must not
        report that scan's exit code as if it were a recompute result."""
        from api.routers.scan import _scan_state
        _scan_state.update({
            'running': False, 'kind': 'scan', 'exit_code': 0, 'progress': None,
        })

        resp = edition_client.get(self.ENDPOINT)

        assert resp.status_code == 200
        data = resp.json()
        assert data["running"] is False
        assert data["kind"] is None
        assert data["exit_code"] is None


class TestRecomputeStatusCrossProcess:
    """A worker that never saw the POST still answers truthfully, using
    ``facet.LibraryLock`` (held by the recompute subprocess for its whole
    run, visible to every worker) as the cross-process running signal --
    proving the fix for the false-failure defect described in THE DEFECT."""

    ENDPOINT = "/api/scan/recompute_status"

    @pytest.fixture(autouse=True)
    def _reset_scan_state(self):
        from api.routers.scan import _scan_state
        original = dict(_scan_state)
        yield
        _scan_state.clear()
        _scan_state.update(original)

    @pytest.fixture(autouse=True)
    def _cleanup_lock_file(self):
        from db.connection import DEFAULT_DB_PATH
        from facet import _library_lock_path

        lock_path = _library_lock_path(DEFAULT_DB_PATH)
        yield
        if os.path.exists(lock_path):
            os.remove(lock_path)

    def _clear_local_state(self):
        from api.routers.scan import _scan_state
        _scan_state.clear()
        _scan_state.update({
            'running': False, 'kind': None, 'process': None,
            'output_lines': deque(maxlen=500), 'started_at': None,
            'directories': [], 'exit_code': None, 'progress': None,
        })

    def test_worker_with_no_local_state_reports_running_not_failed(self, edition_client):
        """A poll landing on a worker that never handled the POST -- the
        exact scenario THE DEFECT describes -- must read as running, not as
        a false 'Recompute failed'."""
        from db.connection import DEFAULT_DB_PATH

        self._clear_local_state()
        with _library_lock_held(DEFAULT_DB_PATH, kind="recompute", origin="viewer"):
            resp = edition_client.get(self.ENDPOINT)

        assert resp.status_code == 200
        data = resp.json()
        assert data["running"] is True
        assert data["kind"] == "recompute"
        assert data["exit_code"] is None

    def test_a_scan_holding_the_lock_is_reported_as_a_scan_not_a_recompute(self, edition_client):
        """A scan holds the same lock, so the holder's own kind is what gets
        reported -- assuming 'recompute' would mislabel a running scan."""
        from db.connection import DEFAULT_DB_PATH

        self._clear_local_state()
        with _library_lock_held(DEFAULT_DB_PATH, kind="scan", origin="cli"):
            resp = edition_client.get(self.ENDPOINT)

        assert resp.status_code == 200
        data = resp.json()
        assert data["running"] is True
        assert data["kind"] == "scan"

    def test_worker_with_no_local_state_and_no_lock_reads_as_indeterminate(self, edition_client):
        """Nothing is running anywhere this worker can see: an honest
        idle-shaped response, never a false failure."""
        self._clear_local_state()

        resp = edition_client.get(self.ENDPOINT)

        assert resp.status_code == 200
        data = resp.json()
        assert data["running"] is False
        assert data["kind"] is None
        assert data["exit_code"] is None

    def test_stale_lock_from_a_dead_pid_does_not_report_running(self, edition_client):
        """A crashed holder's lock file must not make a fresh worker claim
        a job is still running."""
        from db.connection import DEFAULT_DB_PATH

        self._clear_local_state()
        _write_leftover_lock_file(DEFAULT_DB_PATH, pid=999999, origin="viewer")

        resp = edition_client.get(self.ENDPOINT)

        assert resp.status_code == 200
        data = resp.json()
        assert data["running"] is False

    def test_leftover_lock_naming_a_live_unrelated_pid_does_not_report_running(self, edition_client):
        """The recycled-PID case: after a power cut the file survives and its
        PID is handed to some unrelated process. It must still read as free."""
        from db.connection import DEFAULT_DB_PATH

        self._clear_local_state()
        _write_leftover_lock_file(DEFAULT_DB_PATH, pid=os.getpid(), origin="viewer")

        resp = edition_client.get(self.ENDPOINT)

        assert resp.status_code == 200
        assert resp.json()["running"] is False


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
        forever: the OS drops the lock with the process, so the leftover file
        reads as free and the next acquire simply succeeds."""
        from facet import LibraryLock, library_job_holder

        db_path = str(tmp_path / "photos.db")
        dead_proc = subprocess.Popen([sys.executable, "-c", "pass"])
        dead_proc.wait()
        _write_leftover_lock_file(db_path, pid=dead_proc.pid)

        assert library_job_holder(db_path) is None
        lock = LibraryLock(db_path, kind="recompute")
        lock.acquire()
        assert library_job_holder(db_path)["pid"] == os.getpid()
        lock.release()
        assert library_job_holder(db_path) is None

    def test_a_killed_holder_frees_the_lock_without_any_cleanup(self, tmp_path):
        """The real crash: a live holder is SIGKILLed, so nothing of its own
        runs. The kernel drops the lock, so no staleness heuristic is needed
        and the next job is never wedged."""
        from facet import LibraryLock, library_job_holder

        db_path = str(tmp_path / "photos.db")
        holder = _spawn_lock_holder(db_path, kind="recompute")
        assert library_job_holder(db_path)["pid"] == holder.pid
        holder.kill()
        holder.wait()

        assert library_job_holder(db_path) is None
        LibraryLock(db_path, kind="scan").acquire().release()

    def test_leftover_lock_naming_a_live_unrelated_pid_does_not_wedge(self, tmp_path):
        """Power cut mid-job: the file survives the reboot and its PID gets
        recycled by an unrelated (possibly root-owned) process. PID liveness
        would call that "held forever"; the OS lock calls it free."""
        from facet import LibraryLock, library_job_holder

        db_path = str(tmp_path / "photos.db")
        unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        try:
            _write_leftover_lock_file(db_path, pid=unrelated.pid, started_at=1)
            assert library_job_holder(db_path) is None
            LibraryLock(db_path, kind="recompute").acquire().release()
        finally:
            unrelated.kill()
            unrelated.wait()

    def test_a_half_written_lock_file_still_reads_as_held(self, tmp_path):
        """The payload is descriptive, the OS lock is the mutex: an empty or
        corrupt file under a live holder must never read as free, or two
        processes would both believe they own the library."""
        from facet import LibraryLock, LibraryLockError, _library_lock_path, library_job_holder

        db_path = str(tmp_path / "photos.db")
        first = LibraryLock(db_path, kind="recompute")
        first.acquire()
        try:
            with open(_library_lock_path(db_path), "w"):
                pass
            assert library_job_holder(db_path) is not None
            with pytest.raises(LibraryLockError):
                LibraryLock(db_path, kind="scan").acquire()
        finally:
            first.release()

    def test_release_leaves_no_identity_behind(self, tmp_path):
        """A finished job's payload is what a losing probe would read as a live
        holder, so ``release`` empties the file before unlocking it."""
        from facet import LibraryLock, _library_lock_path

        db_path = str(tmp_path / "photos.db")
        LibraryLock(db_path, kind="recompute").acquire().release()

        assert os.path.getsize(_library_lock_path(db_path)) == 0

    def test_concurrent_peeks_never_manufacture_a_holder(self, tmp_path):
        """Peeking used to take the *exclusive* lock, so two overlapping peeks
        made one of them fail and read the finished job's leftover payload --
        a spurious 409 / ``running: true`` in the viewer. Probing shared (and
        against an emptied file) makes peeks invisible to each other."""
        from facet import LibraryLock

        db_path = str(tmp_path / "photos.db")
        LibraryLock(db_path, kind="recompute").acquire().release()

        assert [holder for holder in _peek_concurrently(db_path) if holder is not None] == []

    def test_concurrent_peeks_all_still_see_a_live_holder(self, tmp_path):
        """The counter-check: a probe that never reports anything would pass
        the test above and let two jobs rewrite the library at once."""
        from facet import LibraryLock

        db_path = str(tmp_path / "photos.db")
        lock = LibraryLock(db_path, kind="scan")
        lock.acquire()
        try:
            seen = _peek_concurrently(db_path)
        finally:
            lock.release()

        assert [holder for holder in seen if holder is None] == []
        assert {holder["pid"] for holder in seen} == {os.getpid()}

    def test_a_full_disk_while_describing_the_holder_is_a_clear_error(self, tmp_path, monkeypatch):
        """ENOSPC/EDQUOT on the payload write used to escape as the raw OSError
        traceback the lock was meant to replace."""
        import facet

        db_path = str(tmp_path / "photos.db")
        monkeypatch.setattr(
            facet.LibraryLock, "_write_payload",
            mock.Mock(side_effect=OSError(errno.ENOSPC, "No space left on device")),
        )
        lock = facet.LibraryLock(db_path, kind="recompute")
        try:
            with pytest.raises(facet.LibraryLockError) as exc_info:
                lock.acquire()
            message = str(exc_info.value)
            assert facet._library_lock_path(db_path) in message
            assert facet.LIBRARY_LOCK_OVERRIDE_FLAG in message
        finally:
            lock.release()

    def test_a_failed_payload_write_keeps_the_lock_itself(self, tmp_path, monkeypatch):
        """The payload is descriptive only -- the OS lock is the mutex, and it
        is already held by then, so losing it over the description would let a
        second job in."""
        import facet

        db_path = str(tmp_path / "photos.db")
        monkeypatch.setattr(
            facet.LibraryLock, "_write_payload",
            mock.Mock(side_effect=OSError(errno.EDQUOT, "Disk quota exceeded")),
        )
        lock = facet.LibraryLock(db_path, kind="recompute", force=True)
        lock.acquire()
        try:
            assert facet.library_job_holder(db_path) is not None
        finally:
            lock.release()

        assert facet.library_job_holder(db_path) is None

    def test_windows_selects_a_real_lock_backend(self, monkeypatch):
        """Without an msvcrt branch the lock is a no-op on Windows: every
        acquire succeeds and every peek reports the library free."""
        import facet

        monkeypatch.setattr(facet, "fcntl", None)
        monkeypatch.setattr(facet, "msvcrt", mock.Mock(LK_NBLCK=1, LK_UNLCK=0))

        assert facet._select_os_lock_backend() is facet._MsvcrtBackend

    def test_the_windows_backend_locks_a_byte_past_the_payload(self, tmp_path, monkeypatch):
        """A Windows range lock is mandatory, not advisory: locking byte 0
        would make the holder's own JSON unreadable to the peek that has to
        name it."""
        import facet

        locked = []
        fake_msvcrt = mock.Mock(LK_NBLCK=1, LK_UNLCK=0)
        fake_msvcrt.locking.side_effect = lambda fd, mode, nbytes: locked.append(
            (os.lseek(fd, 0, os.SEEK_CUR), mode, nbytes))
        monkeypatch.setattr(facet, "msvcrt", fake_msvcrt)
        fd = os.open(str(tmp_path / "library.lock"), os.O_CREAT | os.O_RDWR, 0o644)
        try:
            facet._MsvcrtBackend.take_exclusive(fd)
            facet._MsvcrtBackend.unlock(fd)
            position_after = os.lseek(fd, 0, os.SEEK_CUR)
        finally:
            os.close(fd)

        assert locked == [
            (facet.LIBRARY_LOCK_WINDOWS_OFFSET, fake_msvcrt.LK_NBLCK, facet.LIBRARY_LOCK_WINDOWS_BYTES),
            (facet.LIBRARY_LOCK_WINDOWS_OFFSET, fake_msvcrt.LK_UNLCK, facet.LIBRARY_LOCK_WINDOWS_BYTES),
        ]
        assert position_after == 0

    def test_a_platform_without_any_file_locking_runs_unguarded(self, tmp_path, monkeypatch, caplog):
        """The only remaining warn-and-continue case, and it must say so."""
        import facet

        monkeypatch.setattr(facet, "fcntl", None)
        monkeypatch.setattr(facet, "msvcrt", None)
        monkeypatch.setattr(facet, "_OS_LOCK", facet._select_os_lock_backend())
        db_path = str(tmp_path / "photos.db")
        with caplog.at_level("WARNING"):
            facet.LibraryLock(db_path, kind="scan").acquire().release()

        assert "unguarded" in caplog.text
        assert facet.library_job_holder(db_path) is None

    def test_concurrent_acquires_never_produce_two_holders(self, tmp_path):
        """Four processes hammering the same lock: each one that acquires
        creates an O_EXCL marker, so any overlap is counted, not inferred."""
        db_path = str(tmp_path / "photos.db")
        marker = str(tmp_path / "holder.marker")
        script = (
            "import os, sys\n"
            f"sys.path.insert(0, {_REPO_ROOT!r})\n"
            "from facet import LibraryLock, LibraryLockError\n"
            "db_path, marker, iterations = sys.argv[1], sys.argv[2], int(sys.argv[3])\n"
            "violations = 0\n"
            "for _ in range(iterations):\n"
            "    lock = LibraryLock(db_path, kind='stress')\n"
            "    try:\n"
            "        lock.acquire()\n"
            "    except LibraryLockError:\n"
            "        continue\n"
            "    try:\n"
            "        fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY)\n"
            "        os.close(fd)\n"
            "        os.remove(marker)\n"
            "    except FileExistsError:\n"
            "        violations += 1\n"
            "    finally:\n"
            "        lock.release()\n"
            "print(violations)\n"
        )
        procs = [
            subprocess.Popen(
                [sys.executable, "-c", script, db_path, marker, "200"],
                stdout=subprocess.PIPE, text=True,
            )
            for _ in range(4)
        ]
        violations = [int(p.communicate(timeout=120)[0].strip()) for p in procs]

        assert violations == [0, 0, 0, 0]
        assert all(p.returncode == 0 for p in procs)

    def test_acquire_retries_before_declaring_a_conflict(self, tmp_path, monkeypatch):
        """Reading the holder also takes the lock for a few microseconds, so a
        viewer poll landing on an acquire must not refuse the job outright.

        Patched at the backend seam rather than at ``fcntl.flock``: ``fcntl`` is
        None on Windows, so patching it there made this assert the retry only on
        POSIX and raise AttributeError everywhere else.
        """
        import facet

        calls = []
        real_take_exclusive = facet._OS_LOCK.take_exclusive

        def flaky_take_exclusive(fd):
            calls.append(fd)
            if len(calls) == 1:
                raise BlockingIOError(11, "Resource temporarily unavailable")
            return real_take_exclusive(fd)

        monkeypatch.setattr(
            facet._OS_LOCK, "take_exclusive", staticmethod(flaky_take_exclusive)
        )
        lock = facet.LibraryLock(str(tmp_path / "photos.db"), kind="recompute")
        lock.acquire()
        lock.release()

        assert len(calls) >= 2

    def test_release_on_exception_frees_the_lock(self, tmp_path):
        from facet import LibraryLock, library_job_holder

        db_path = str(tmp_path / "photos.db")
        with pytest.raises(RuntimeError):
            with LibraryLock(db_path, kind="recompute"):
                raise RuntimeError("boom")

        assert library_job_holder(db_path) is None

    @pytest.mark.skipif(
        os.name == "nt",
        reason="os.kill on Windows maps every signal except CTRL_C_EVENT/"
               "CTRL_BREAK_EVENT to TerminateProcess, so this would kill the "
               "test runner outright instead of unwinding into the context "
               "manager. test_sigterm_handler_is_restored_after_release still "
               "covers the handler there.",
    )
    def test_release_on_sigterm_frees_the_lock(self, tmp_path):
        from facet import LibraryLock, library_job_holder

        db_path = str(tmp_path / "photos.db")
        with pytest.raises(KeyboardInterrupt):
            with LibraryLock(db_path, kind="recompute"):
                os.kill(os.getpid(), signal.SIGTERM)

        assert library_job_holder(db_path) is None

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

    def test_conflict_message_names_the_lock_file(self, tmp_path):
        """Without the path in the message a wedged lock is undiagnosable."""
        from facet import LibraryLock, LibraryLockError, _library_lock_path

        db_path = str(tmp_path / "photos.db")
        first = LibraryLock(db_path, kind="recompute")
        first.acquire()
        try:
            with pytest.raises(LibraryLockError) as exc_info:
                LibraryLock(db_path, kind="scan").acquire()
        finally:
            first.release()

        assert _library_lock_path(db_path) in str(exc_info.value)

    def test_force_flag_runs_anyway_when_the_lock_is_held(self, tmp_path):
        """The escape hatch: the user can always get their job to run."""
        from facet import LibraryLock

        db_path = str(tmp_path / "photos.db")
        first = LibraryLock(db_path, kind="recompute")
        first.acquire()
        try:
            forced = LibraryLock(db_path, kind="scan", force=True)
            forced.acquire()
            forced.release()
        finally:
            first.release()

    @pytest.mark.skipif(
        os.name == "nt" or getattr(os, "geteuid", lambda: -1)() == 0,
        reason="root ignores directory permissions, and Windows has neither "
               "geteuid nor a chmod that can make a directory unwritable for "
               "its owner. Evaluated at import, so an unguarded os.geteuid "
               "made this whole module uncollectable on Windows.",
    )
    def test_unwritable_cache_dir_raises_a_clear_error(self, tmp_path):
        """New failure mode introduced by the lock: the cache dir may be owned
        by the other user in a viewer/CLI split. It must name the path and the
        way out, not raise PermissionError from inside os.open."""
        from facet import LibraryLock, LibraryLockError, LIBRARY_LOCK_OVERRIDE_FLAG, _library_lock_path

        db_dir = tmp_path / "library"
        db_dir.mkdir()
        cache_dir = db_dir / ".facet_cache"
        cache_dir.mkdir()
        os.chmod(cache_dir, 0o500)
        db_path = str(db_dir / "photos.db")
        try:
            with pytest.raises(LibraryLockError) as exc_info:
                LibraryLock(db_path, kind="recompute").acquire()
        finally:
            os.chmod(cache_dir, 0o700)

        message = str(exc_info.value)
        assert _library_lock_path(db_path) in message
        assert LIBRARY_LOCK_OVERRIDE_FLAG in message

    def test_cache_dir_occupied_by_a_regular_file_raises_a_clear_error(self, tmp_path):
        from facet import LibraryLock, LibraryLockError, LIBRARY_LOCK_OVERRIDE_FLAG

        db_dir = tmp_path / "library"
        db_dir.mkdir()
        (db_dir / ".facet_cache").write_text("not a directory")

        with pytest.raises(LibraryLockError) as exc_info:
            LibraryLock(str(db_dir / "photos.db"), kind="recompute").acquire()

        assert LIBRARY_LOCK_OVERRIDE_FLAG in str(exc_info.value)

    def test_an_unusable_lock_path_is_a_clear_cli_error_not_a_traceback(self, tmp_path):
        from facet import LIBRARY_LOCK_OVERRIDE_FLAG

        db_dir = tmp_path / "library"
        db_dir.mkdir()
        (db_dir / ".facet_cache").write_text("not a directory")

        result = _run_facet("--recompute-average", "--db", str(db_dir / "photos.db"))

        assert result.returncode == 1
        output = result.stdout + result.stderr
        assert "Traceback" not in output
        assert LIBRARY_LOCK_OVERRIDE_FLAG in output


def _fake_mount_table(tmp_path, entries):
    """A ``/proc/mounts``-shaped file from ``(mount point, filesystem)`` pairs.

    Mount points are written verbatim, so a test can pass the octal escapes the
    kernel itself uses for a mount point containing a space.
    """
    table = tmp_path / "mounts"
    table.write_text(
        "".join(f"//server/share {point} {filesystem} rw,relatime 0 0\n"
                for point, filesystem in entries)
    )
    return str(table)


@pytest.mark.skipif(
    os.name == "nt",
    reason="Reads /proc/mounts and feeds POSIX mount points through "
           "os.path.abspath, which on Windows rewrites '/mnt/nas' to "
           "'<drive>:\\mnt\\nas' and can never match. The warning is Linux-only "
           "by design: it exists because flock over SMB is arbitrated host-side, "
           "whereas Windows byte-range locks over SMB2 are server-arbitrated.",
)
class TestHostLocalLockWarning:
    """``flock`` is arbitrated by the kernel that took it, so on an SMB/CIFS
    mount two machines each believe they hold the library lock. The lock cannot
    fix that, but it must not promise an exclusion it does not deliver."""

    @pytest.fixture(autouse=True)
    def _forget_earlier_warnings(self):
        import facet

        facet._host_local_lock_warned.clear()
        yield
        facet._host_local_lock_warned.clear()

    def test_a_cifs_mounted_library_warns_that_the_lock_is_local_to_this_host(
            self, tmp_path, monkeypatch, caplog):
        import facet

        db_dir = tmp_path / "library"
        db_dir.mkdir()
        db_path = str(db_dir / "photos.db")
        monkeypatch.setattr(
            facet, "LIBRARY_LOCK_MOUNTS_PATH",
            _fake_mount_table(tmp_path, [("/", "ext4"), (str(db_dir), "cifs")]))
        lock = facet.LibraryLock(db_path, kind="recompute")
        with caplog.at_level("WARNING"):
            lock.acquire()
        try:
            assert facet.library_job_holder(db_path) is not None
        finally:
            lock.release()

        assert "cifs" in caplog.text
        assert "another machine" in caplog.text
        assert facet._library_lock_path(db_path) in caplog.text

    def test_the_warning_is_emitted_once_per_lock_path(self, tmp_path, monkeypatch, caplog):
        import facet

        db_dir = tmp_path / "library"
        db_dir.mkdir()
        db_path = str(db_dir / "photos.db")
        monkeypatch.setattr(
            facet, "LIBRARY_LOCK_MOUNTS_PATH",
            _fake_mount_table(tmp_path, [("/", "ext4"), (str(db_dir), "smb3")]))
        with caplog.at_level("WARNING"):
            for _ in range(3):
                facet.LibraryLock(db_path, kind="recompute").acquire().release()

        assert caplog.text.count("local to this host") == 1

    def test_nfs_does_not_warn_because_its_locks_do_cross_hosts(
            self, tmp_path, monkeypatch, caplog):
        """Linux implements flock on NFS as a POSIX record lock the server
        arbitrates, so warning there would be a false alarm on the most common
        remote-library setup."""
        import facet

        db_dir = tmp_path / "library"
        db_dir.mkdir()
        monkeypatch.setattr(
            facet, "LIBRARY_LOCK_MOUNTS_PATH",
            _fake_mount_table(tmp_path, [("/", "ext4"), (str(db_dir), "nfs4")]))
        with caplog.at_level("WARNING"):
            facet.LibraryLock(str(db_dir / "photos.db"), kind="recompute").acquire().release()

        assert caplog.text == ""

    def test_an_unreadable_mount_table_locks_silently(self, tmp_path, monkeypatch, caplog):
        """Detection is advisory: no /proc (any non-Linux host) must neither
        raise, nor warn, nor stop the lock from being taken."""
        import facet

        db_dir = tmp_path / "library"
        db_dir.mkdir()
        db_path = str(db_dir / "photos.db")
        monkeypatch.setattr(facet, "LIBRARY_LOCK_MOUNTS_PATH", str(tmp_path / "absent"))
        lock = facet.LibraryLock(db_path, kind="recompute")
        with caplog.at_level("WARNING"):
            lock.acquire()
        try:
            assert facet.library_job_holder(db_path) is not None
        finally:
            lock.release()

        assert caplog.text == ""

    def test_the_longest_matching_mount_point_wins(self, tmp_path, monkeypatch):
        """A shorter prefix must not shadow the mount the path actually sits on
        -- in either direction, or the check either misses or cries wolf."""
        import facet

        monkeypatch.setattr(
            facet, "LIBRARY_LOCK_MOUNTS_PATH",
            _fake_mount_table(tmp_path, [("/", "ext4"), ("/mnt/nas", "cifs")]))

        assert facet._filesystem_type("/mnt/nas/photos/.facet_cache/library.lock") == "cifs"
        assert facet._filesystem_type("/home/user/photos/.facet_cache/library.lock") == "ext4"
        assert facet._filesystem_type("/mnt/nasty/photos") == "ext4"

    def test_a_mount_point_containing_a_space_is_unescaped(self, tmp_path, monkeypatch):
        """The kernel writes it as \\040; matching the raw field would silently
        miss the SMB share and skip the warning."""
        import facet

        monkeypatch.setattr(
            facet, "LIBRARY_LOCK_MOUNTS_PATH",
            _fake_mount_table(tmp_path, [("/", "ext4"), (r"/mnt/my\040nas", "cifs")]))

        assert facet._filesystem_type("/mnt/my nas/photos") == "cifs"


class TestUpgradeDbSchemaLock:
    """``--upgrade-db`` ALTERs the photos table before its locked steps run.
    Unlocked, that DDL landing inside a recompute's long write transaction
    fails and aborts the upgrade at step 0 -- but the lock must be gone again
    before the subprocess chain, whose every step takes it."""

    def _upgrade_args(self, db_path):
        return mock.Mock(db=db_path, force_library_lock=False)

    def test_the_ddl_runs_locked_and_the_chain_runs_unlocked(self, tmp_path, monkeypatch):
        import facet

        db_path = str(tmp_path / "photos.db")
        during_ddl, during_chain = [], []

        def recording_init_database(path):
            during_ddl.append(facet.library_job_holder(db_path))

        def recording_run(cmd, *args, **kwargs):
            during_chain.append(facet.library_job_holder(db_path))
            return subprocess.CompletedProcess(cmd, 0)

        monkeypatch.setattr(facet, "init_database", recording_init_database)
        monkeypatch.setattr(subprocess, "run", recording_run)
        monkeypatch.setattr(sys, "argv", ["facet.py", "--upgrade-db", "--db", db_path])

        with pytest.raises(SystemExit) as exit_info:
            facet.main()

        assert exit_info.value.code == 0
        assert len(during_ddl) == 1
        assert during_ddl[0] is not None, "the schema migration ran without the library lock"
        assert during_ddl[0]["kind"] == facet.LIBRARY_JOB_MAINTENANCE
        assert during_ddl[0]["pid"] == os.getpid()
        assert during_chain, "the backfill chain never ran"
        assert all(holder is None for holder in during_chain), (
            "the chain inherited the parent's lock and would deadlock on it")

    def test_a_running_recompute_defers_the_migration_instead_of_altering_into_it(
            self, tmp_path, monkeypatch):
        import facet

        db_path = str(tmp_path / "photos.db")
        migrated = []
        monkeypatch.setattr(facet, "init_database", lambda path: migrated.append(path))

        with _library_lock_held(db_path, kind="recompute"):
            with pytest.raises(SystemExit) as exit_info:
                facet._upgrade_db_schema(self._upgrade_args(db_path), db_path)

        assert exit_info.value.code == 1
        assert migrated == []

    def test_the_lock_is_released_even_when_the_migration_raises(self, tmp_path, monkeypatch):
        import facet

        db_path = str(tmp_path / "photos.db")
        monkeypatch.setattr(
            facet, "init_database", mock.Mock(side_effect=RuntimeError("migration boom")))

        with pytest.raises(RuntimeError):
            facet._upgrade_db_schema(self._upgrade_args(db_path), db_path)

        assert facet.library_job_holder(db_path) is None


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

    def test_recompute_refused_when_a_cli_recompute_holds_the_lock(self, edition_client):
        from db.connection import DEFAULT_DB_PATH

        with _library_lock_held(DEFAULT_DB_PATH, kind="recompute", origin="cli"):
            resp = edition_client.post("/api/scan/recompute", json={"confirm": True})

        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert "recompute" in detail
        assert "cli" in detail

    def test_scan_refused_when_a_recompute_holds_the_lock(self):
        from db.connection import DEFAULT_DB_PATH

        viewer_cfg = _viewer_config_with_scan()
        with (
            _library_lock_held(DEFAULT_DB_PATH, kind="recompute", origin="viewer"),
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

    def test_scan_refused_when_another_scan_holds_the_lock(self):
        """A scan now holds the same lock, so /start refuses a second one
        cross-process instead of only checking a 120s heartbeat."""
        from db.connection import DEFAULT_DB_PATH

        viewer_cfg = _viewer_config_with_scan()
        with (
            _library_lock_held(DEFAULT_DB_PATH, kind="scan", origin="cli"),
            mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", viewer_cfg),
            mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=True),
            mock.patch(f"{_ROUTER_MODULE}.VIEWER_CONFIG", viewer_cfg),
        ):
            app, client, _ = _make_superadmin_app(viewer_cfg)
            resp = client.post("/api/scan/start", json={"directories": ["/photos"]})

        assert resp.status_code == 409
        assert "scan" in resp.json()["detail"]

    def test_recompute_refused_when_a_cli_scan_holds_the_lock(self, edition_client):
        from db.connection import DEFAULT_DB_PATH

        with _library_lock_held(DEFAULT_DB_PATH, kind="scan", origin="cli"):
            resp = edition_client.post("/api/scan/recompute", json={"confirm": True})

        assert resp.status_code == 409
        assert "scan" in resp.json()["detail"]

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


class TestScanHoldsTheLibraryLock:
    """The scan is the other half of the collision the lock exists for: it
    dies on SQLITE_BUSY inside a recompute's single long transaction. Before
    this it never took the lock at all and was only ever detected through a
    120s heartbeat that goes stale during model loading."""

    def test_scan_holds_the_lock_for_the_whole_scan(self, tmp_path, monkeypatch):
        import facet

        db_path = str(tmp_path / "photos.db")
        photos_dir = tmp_path / "photos"
        photos_dir.mkdir()
        seen = {}

        def fake_run_scan(args, resumed_run):
            seen['holder'] = facet.library_job_holder(db_path)

        monkeypatch.setattr(facet, "_run_scan", fake_run_scan)
        monkeypatch.setattr(sys, "argv", ["facet.py", str(photos_dir), "--db", db_path])

        facet.main()

        assert seen['holder']["kind"] == facet.LIBRARY_JOB_SCAN
        assert seen['holder']["pid"] == os.getpid()
        assert facet.library_job_holder(db_path) is None

    def test_a_dry_run_scan_does_not_take_the_lock(self, tmp_path, monkeypatch):
        """A --dry-run preview scores a sample and saves nothing, so taking the
        exclusive lock only refused the preview while any job ran, and blocked
        a legitimate recompute for as long as the preview took."""
        import facet

        db_path = str(tmp_path / "photos.db")
        photos_dir = tmp_path / "photos"
        photos_dir.mkdir()
        seen = {}

        def fake_run_scan(args, resumed_run):
            seen['holder'] = facet.library_job_holder(db_path)

        monkeypatch.setattr(facet, "_run_scan", fake_run_scan)
        monkeypatch.setattr(sys, "argv",
                            ["facet.py", str(photos_dir), "--db", db_path, "--dry-run"])

        facet.main()

        assert seen['holder'] is None

    def test_a_recompute_started_mid_scan_is_refused(self, tmp_path, monkeypatch):
        """The collision the lock exists to stop, end to end: a real
        ``--recompute-average`` process launched while the scan body runs."""
        import facet

        db_path = str(tmp_path / "photos.db")
        photos_dir = tmp_path / "photos"
        photos_dir.mkdir()
        seen = {}

        def fake_run_scan(args, resumed_run):
            seen['result'] = _run_facet("--recompute-average", "--db", db_path)

        monkeypatch.setattr(facet, "_run_scan", fake_run_scan)
        monkeypatch.setattr(sys, "argv", ["facet.py", str(photos_dir), "--db", db_path])

        facet.main()

        result = seen['result']
        assert result.returncode == 1
        output = result.stdout + result.stderr
        assert "A scan is already running" in output
        assert "Traceback" not in output

    def test_a_scan_started_mid_recompute_is_refused_before_it_enumerates(self, tmp_path):
        """And the other direction -- refused before the directory walk, so a
        126k-photo library costs nothing on a conflict."""
        db_path = str(tmp_path / "photos.db")
        photos_dir = tmp_path / "photos"
        photos_dir.mkdir()
        holder = _spawn_lock_holder(db_path, kind="recompute")
        try:
            result = _run_facet(str(photos_dir), "--db", db_path)
        finally:
            holder.kill()
            holder.wait()

        assert result.returncode == 1
        output = result.stdout + result.stderr
        assert "recompute is already running" in output
        assert "Found 0 total" not in output
        assert "Traceback" not in output

    def test_the_post_processing_tail_is_inside_the_locked_region(self):
        """``scan_run.finish('completed')`` fires before bursts, tagging,
        moments, junk and the vec population -- all whole-library writers. The
        lock wraps ``_run_scan``, so they are covered by construction rather
        than by a heartbeat that has already stopped."""
        import facet

        scan_source = inspect.getsource(facet._run_scan)
        for tail_call in (
            "process_bursts(",
            "run_tagging(",
            "run_moment_detection(",
            "run_junk_detection(",
            "populate_vec_table(",
        ):
            assert tail_call in scan_source, tail_call

        main_source = inspect.getsource(facet.main)
        assert "_acquire_library_lock(args, LIBRARY_JOB_SCAN)" in main_source
        assert "_run_scan(args, resumed_run)" in main_source
        assert "lock.release()" in main_source


_LOCK_EXEMPT_WRITERS = {
    "upgrade_db": "runs the locked jobs as subprocesses; holding the lock in the parent "
                  "would deadlock every one of them",
    "watch": "a supervisor that spawns scans; the scan it spawns takes the lock, and the "
             "daemon itself must not hold it for days",
}

_JOB_MODIFIERS = frozenset({
    "apply_recommendations", "config", "db", "discover_min_cluster_size", "dry_run",
    "dry_run_count", "embed_originals", "force", "force_library_lock", "force_low_space",
    "force_since", "limit", "merge_threshold", "optimize_category", "optimize_force",
    "optimize_sources", "ranker_category", "refresh_thumbnails_workers", "resume",
    "retry_failed", "score_to_stars",
    "simulate", "simulate_gpu", "simulate_vram", "single_pass", "single_pass_name",
    "train_keeper_force", "train_ranker_force", "user", "verbose", "watch_debounce",
})

_READ_ONLY_LIBRARY_COMMANDS = frozenset({
    "auto_tune_categories", "check_raw_rendering", "comparison_stats", "doctor",
    "eval_iqa_srcc", "export_csv",
    "export_json", "export_manifest", "immich_sync", "immich_test", "list_models",
    "mine_insights", "report_unreviewed_bursts", "suggest_person_merges",
    "sweep_dedup_thresholds", "validate_categories",
})

_NON_LIBRARY_WRITERS = frozenset({
    "compute_recommendations", "discover_moments", "export_sidecars", "optimize_weights",
})


class TestLibraryJobCoverage:
    """Which entry points participate in the lock, and which deliberately
    do not."""

    def test_every_cli_flag_is_classified_for_the_library_lock(self):
        """The inverse direction of the test below: a flag whose handler
        rewrites the library must be in ``LIBRARY_JOB_ARGS``, or the class
        invariant ("every library-rewriting entry point of this module holds
        this lock") is quietly false. Nothing can decide that automatically,
        so every flag the parser defines is classified here instead -- a new
        one fails this test until someone says which bucket it belongs in.
        ``LIBRARY_JOB_ARGS`` may be a superset: locking a job that only writes
        ``comparisons`` or ``stats_cache`` costs a conflict message, while
        missing a real writer costs a SQLITE_BUSY crash."""
        from facet import LIBRARY_JOB_ARGS

        classified = (set(LIBRARY_JOB_ARGS) | set(_LOCK_EXEMPT_WRITERS) | _JOB_MODIFIERS
                      | _READ_ONLY_LIBRARY_COMMANDS | _NON_LIBRARY_WRITERS)

        assert sorted(_cli_flag_dests() - classified) == []

    def test_the_lock_classification_names_no_dead_flags(self):
        """A rename that leaves a stale name behind would silently un-classify
        the renamed flag while this file still looked complete."""
        from facet import LIBRARY_JOB_ARGS

        classified = (set(LIBRARY_JOB_ARGS) | set(_LOCK_EXEMPT_WRITERS) | _JOB_MODIFIERS
                      | _READ_ONLY_LIBRARY_COMMANDS | _NON_LIBRARY_WRITERS)

        assert sorted(classified - _cli_flag_dests()) == []

    def test_the_trainers_and_the_label_sync_take_the_lock(self):
        """``--train-ranker`` mirrors the learned scores into
        ``photos.learned_score`` (``optimization/personal_ranker.py``), so it
        is a whole-library rewriter that used to run unguarded;
        ``--train-keeper`` and ``--sync-label-comparisons`` are the long DB
        writers it runs alongside."""
        from facet import LIBRARY_JOB_ARGS

        for name in ("train_ranker", "train_keeper", "sync_label_comparisons"):
            assert name in LIBRARY_JOB_ARGS, name

    def test_every_library_job_arg_is_a_real_cli_flag(self):
        from facet import LIBRARY_JOB_ARGS

        help_text = _run_facet("--help").stdout

        missing = [name for name in LIBRARY_JOB_ARGS
                   if f"--{name.replace('_', '-')}" not in help_text]
        assert missing == []

    def test_upgrade_db_does_not_take_the_lock(self):
        """It runs the locked jobs as subprocesses; holding the lock in the
        parent would deadlock every step."""
        from facet import LIBRARY_JOB_ARGS

        assert "upgrade_db" not in LIBRARY_JOB_ARGS

    def test_watch_mode_does_not_take_the_lock(self):
        """The watcher is a supervisor that spawns scans; the spawned scan
        takes the lock, the daemon must not hold it for days."""
        from facet import LIBRARY_JOB_ARGS

        assert "watch" not in LIBRARY_JOB_ARGS

    def test_a_recompute_flag_is_refused_while_another_job_holds_the_lock(self, tmp_path):
        db_path = str(tmp_path / "photos.db")
        holder = _spawn_lock_holder(db_path, kind="scan")
        try:
            result = _run_facet("--recompute-tags", "--db", db_path)
        finally:
            holder.kill()
            holder.wait()

        assert result.returncode == 1
        assert "scan is already running" in result.stdout + result.stderr

    def test_a_read_only_command_is_not_blocked_by_the_lock(self, tmp_path):
        db_path = str(tmp_path / "photos.db")
        holder = _spawn_lock_holder(db_path, kind="recompute")
        try:
            result = _run_facet("--validate-categories", "--db", db_path)
        finally:
            holder.kill()
            holder.wait()

        assert result.returncode == 0
