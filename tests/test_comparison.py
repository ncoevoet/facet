"""
Tests for the comparison API router -- pairwise ranking, stats, history, snapshots.

Uses mock-based approach (no real DB). Follows patterns from test_faces.py.
"""

import json
from contextlib import contextmanager
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from api import create_app
from api.auth import CurrentUser, require_authenticated

_AUTH_MODULE = "api.auth"
_ROUTER_MODULE = "api.routers.comparison"

# edition_password must be set so require_edition rejects non-admin users
_VIEWER_CONFIG = {
    "password": "",
    "edition_password": "secret",
    "features": {},
    "display": {"image_jpeg_quality": 96},
}

_COMPARISON_SETTINGS = {
    "min_comparisons_for_optimization": 30,
    "pair_selection_strategy": "uncertainty",
    "show_current_scores": False,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cm(conn):
    """Wrap a mock connection in a context manager compatible with get_db()."""
    @contextmanager
    def _ctx():
        yield conn
    return _ctx


def _make_app_and_client(raise_server_exceptions=True):
    app = create_app()
    client = TestClient(app, raise_server_exceptions=raise_server_exceptions)
    return app, client


def _override_auth(app, user):
    """Override auth to return the given user."""
    app.dependency_overrides[require_authenticated] = lambda: user
    return app


def _edition_user():
    return CurrentUser(user_id="u1", role="admin", edition_authenticated=True)


def _regular_user():
    return CurrentUser(user_id="u2", role="user", edition_authenticated=False)


def _make_comparison_module(manager):
    """Create a mock 'comparison' module with ComparisonManager returning manager."""
    mod = mock.MagicMock()
    mod.ComparisonManager = lambda *a, **k: manager
    return mod


class _DictRow(dict):
    """A dict subclass that also supports attribute-style key access via keys()."""
    pass


@pytest.fixture(autouse=True)
def _patch_config():
    """Patch auth config so require_edition can evaluate without real config."""
    with (
        mock.patch(f"{_AUTH_MODULE}.VIEWER_CONFIG", _VIEWER_CONFIG),
        mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=False),
    ):
        yield


# ---------------------------------------------------------------------------
# TestComparisonSubmit
# ---------------------------------------------------------------------------

class TestComparisonSubmit:
    """POST /api/comparison/submit"""

    ENDPOINT = "/api/comparison/submit"

    def test_submit_success(self):
        mock_manager = mock.MagicMock()
        mock_manager.submit_comparison.return_value = True
        mock_manager.get_statistics.return_value = {"total": 1}

        app, client = _make_app_and_client()
        _override_auth(app, _edition_user())

        with mock.patch.dict("sys.modules", {"comparison": _make_comparison_module(mock_manager)}):
            resp = client.post(self.ENDPOINT, json={
                "photo_a": "/a.jpg",
                "photo_b": "/b.jpg",
                "winner": "/a.jpg",
                "category": "portrait",
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "stats" in data

    def test_submit_missing_fields(self):
        app, client = _make_app_and_client(raise_server_exceptions=False)
        _override_auth(app, _edition_user())

        mock_manager = mock.MagicMock()
        with mock.patch.dict("sys.modules", {"comparison": _make_comparison_module(mock_manager)}):
            resp = client.post(self.ENDPOINT, json={
                "photo_a": "/a.jpg",
                "photo_b": "/b.jpg",
                "winner": "",
            })

        assert resp.status_code == 400

    def test_submit_requires_edition(self):
        app, client = _make_app_and_client(raise_server_exceptions=False)
        _override_auth(app, _regular_user())

        resp = client.post(self.ENDPOINT, json={
            "photo_a": "/a.jpg",
            "photo_b": "/b.jpg",
            "winner": "/a.jpg",
        })

        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# TestComparisonStats
# ---------------------------------------------------------------------------

class TestComparisonStats:
    """GET /api/comparison/stats"""

    ENDPOINT = "/api/comparison/stats"

    def test_stats_returns_data(self):
        mock_manager = mock.MagicMock()
        mock_manager.get_statistics.return_value = {
            "total_comparisons": 42,
            "unique_photos": 15,
            "categories": {"portrait": 20, "landscape": 22},
        }

        app, client = _make_app_and_client()
        _override_auth(app, _edition_user())

        with (
            mock.patch.dict("sys.modules", {"comparison": _make_comparison_module(mock_manager)}),
            mock.patch(f"{_ROUTER_MODULE}.get_comparison_mode_settings", return_value=_COMPARISON_SETTINGS),
        ):
            resp = client.get(self.ENDPOINT)

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_comparisons"] == 42
        assert data["min_comparisons_for_optimization"] == 30

    def test_stats_empty_db(self):
        mock_manager = mock.MagicMock()
        mock_manager.get_statistics.return_value = {
            "total_comparisons": 0,
            "unique_photos": 0,
            "categories": {},
        }

        app, client = _make_app_and_client()
        _override_auth(app, _edition_user())

        with (
            mock.patch.dict("sys.modules", {"comparison": _make_comparison_module(mock_manager)}),
            mock.patch(f"{_ROUTER_MODULE}.get_comparison_mode_settings", return_value=_COMPARISON_SETTINGS),
        ):
            resp = client.get(self.ENDPOINT)

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_comparisons"] == 0
        assert data["unique_photos"] == 0


# ---------------------------------------------------------------------------
# TestComparisonReset
# ---------------------------------------------------------------------------

class TestComparisonReset:
    """POST /api/comparison/reset"""

    ENDPOINT = "/api/comparison/reset"

    def test_reset_deletes_all(self):
        conn_mock = mock.MagicMock()

        app, client = _make_app_and_client()
        _override_auth(app, _edition_user())

        with mock.patch(f"{_ROUTER_MODULE}.get_db", _cm(conn_mock)):
            resp = client.post(self.ENDPOINT)

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

        # Verify DELETE was called on all 3 tables
        execute_calls = [str(c) for c in conn_mock.execute.call_args_list]
        assert any("DELETE FROM comparisons" in c for c in execute_calls)
        assert any("DELETE FROM learned_scores" in c for c in execute_calls)
        assert any("DELETE FROM weight_optimization_runs" in c for c in execute_calls)
        conn_mock.commit.assert_called_once()

    def test_reset_requires_edition(self):
        app, client = _make_app_and_client(raise_server_exceptions=False)
        _override_auth(app, _regular_user())

        resp = client.post(self.ENDPOINT)

        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# TestComparisonHistory
# ---------------------------------------------------------------------------

class TestComparisonHistory:
    """GET /api/comparison/history"""

    ENDPOINT = "/api/comparison/history"

    def test_history_returns_list(self):
        mock_manager = mock.MagicMock()
        mock_manager.get_comparison_history_filtered.return_value = {
            "comparisons": [
                {"id": 1, "photo_a": "/a.jpg", "photo_b": "/b.jpg", "winner": "/a.jpg"},
                {"id": 2, "photo_a": "/c.jpg", "photo_b": "/d.jpg", "winner": "/d.jpg"},
            ],
            "total": 2,
        }

        app, client = _make_app_and_client()
        _override_auth(app, _edition_user())

        with mock.patch.dict("sys.modules", {"comparison": _make_comparison_module(mock_manager)}):
            resp = client.get(self.ENDPOINT)

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["comparisons"]) == 2
        assert data["total"] == 2

    def test_history_pagination(self):
        mock_manager = mock.MagicMock()
        mock_manager.get_comparison_history_filtered.return_value = {
            "comparisons": [
                {"id": 3, "photo_a": "/e.jpg", "photo_b": "/f.jpg", "winner": "/e.jpg"},
            ],
            "total": 50,
        }

        app, client = _make_app_and_client()
        _override_auth(app, _edition_user())

        with mock.patch.dict("sys.modules", {"comparison": _make_comparison_module(mock_manager)}):
            resp = client.get(self.ENDPOINT, params={"limit": 10, "offset": 20})

        assert resp.status_code == 200
        # Verify the manager was called with correct pagination params
        mock_manager.get_comparison_history_filtered.assert_called_once_with(
            limit=10,
            offset=20,
            category=None,
            winner=None,
            start_date=None,
            end_date=None,
        )

    def test_history_requires_edition(self):
        app, client = _make_app_and_client(raise_server_exceptions=False)
        _override_auth(app, _regular_user())

        resp = client.get(self.ENDPOINT)

        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# TestWeightSnapshots
# ---------------------------------------------------------------------------

class TestWeightSnapshots:
    """GET /api/config/weight_snapshots and POST /api/config/save_snapshot"""

    LIST_ENDPOINT = "/api/config/weight_snapshots"
    SAVE_ENDPOINT = "/api/config/save_snapshot"

    def test_list_snapshots(self):
        # Use _DictRow (a real dict subclass) so dict(row) works naturally
        row1 = _DictRow(
            id=1,
            timestamp="2025-01-01T00:00:00",
            category="portrait",
            weights=json.dumps({"aesthetic_percent": 35}),
            description="initial",
            accuracy_before=None,
            accuracy_after=None,
            comparisons_used=None,
            created_by="manual",
        )
        row2 = _DictRow(
            id=2,
            timestamp="2025-01-02T00:00:00",
            category="landscape",
            weights=json.dumps({"aesthetic_percent": 40}),
            description="tuned",
            accuracy_before=0.7,
            accuracy_after=0.85,
            comparisons_used=50,
            created_by="optimizer",
        )

        conn_mock = mock.MagicMock()
        cursor_mock = mock.MagicMock()
        cursor_mock.__iter__ = lambda self: iter([row1, row2])
        conn_mock.execute.return_value = cursor_mock

        app, client = _make_app_and_client()
        _override_auth(app, _edition_user())

        with mock.patch(f"{_ROUTER_MODULE}.get_db", _cm(conn_mock)):
            resp = client.get(self.LIST_ENDPOINT)

        assert resp.status_code == 200
        data = resp.json()
        assert "snapshots" in data
        assert len(data["snapshots"]) == 2
        # Weights should be parsed from JSON string to dict
        assert data["snapshots"][0]["weights"] == {"aesthetic_percent": 35}
        assert data["snapshots"][1]["description"] == "tuned"

    def test_list_snapshots_empty(self):
        conn_mock = mock.MagicMock()
        cursor_mock = mock.MagicMock()
        cursor_mock.__iter__ = lambda self: iter([])
        conn_mock.execute.return_value = cursor_mock

        app, client = _make_app_and_client()
        _override_auth(app, _edition_user())

        with mock.patch(f"{_ROUTER_MODULE}.get_db", _cm(conn_mock)):
            resp = client.get(self.LIST_ENDPOINT)

        assert resp.status_code == 200
        data = resp.json()
        assert data["snapshots"] == []

    def test_save_snapshot_success(self):
        mock_config = mock.MagicMock()
        mock_config.get_weights.return_value = {"aesthetic_percent": 35, "composition_percent": 20}

        conn_mock = mock.MagicMock()
        cursor_mock = mock.MagicMock()
        cursor_mock.lastrowid = 42
        conn_mock.execute.return_value = cursor_mock

        app, client = _make_app_and_client()
        _override_auth(app, _edition_user())

        with (
            mock.patch(f"{_ROUTER_MODULE}.get_db", _cm(conn_mock)),
            mock.patch.dict("sys.modules", {"config": mock.MagicMock(ScoringConfig=lambda *a, **k: mock_config)}),
        ):
            resp = client.post(self.SAVE_ENDPOINT, json={
                "category": "portrait",
                "description": "test snapshot",
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["snapshot_id"] == 42

    def test_save_snapshot_requires_edition(self):
        app, client = _make_app_and_client(raise_server_exceptions=False)
        _override_auth(app, _regular_user())

        resp = client.post(self.SAVE_ENDPOINT, json={
            "category": "portrait",
            "description": "attempt",
        })

        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# TestComparisonEdit
# ---------------------------------------------------------------------------

class TestComparisonEdit:
    """POST /api/comparison/edit"""

    ENDPOINT = "/api/comparison/edit"

    def test_edit_success(self):
        mock_manager = mock.MagicMock()
        mock_manager.edit_comparison.return_value = True

        app, client = _make_app_and_client()
        _override_auth(app, _edition_user())

        with mock.patch.dict("sys.modules", {"comparison": _make_comparison_module(mock_manager)}):
            resp = client.post(self.ENDPOINT, json={"id": 1, "winner": "/a.jpg"})

        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_edit_not_found(self):
        mock_manager = mock.MagicMock()
        mock_manager.edit_comparison.return_value = False

        app, client = _make_app_and_client(raise_server_exceptions=False)
        _override_auth(app, _edition_user())

        with mock.patch.dict("sys.modules", {"comparison": _make_comparison_module(mock_manager)}):
            resp = client.post(self.ENDPOINT, json={"id": 999, "winner": "/a.jpg"})

        assert resp.status_code == 404

    def test_edit_requires_edition(self):
        app, client = _make_app_and_client(raise_server_exceptions=False)
        _override_auth(app, _regular_user())

        resp = client.post(self.ENDPOINT, json={"id": 1, "winner": "/a.jpg"})

        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# TestComparisonDelete
# ---------------------------------------------------------------------------

class TestComparisonDelete:
    """POST /api/comparison/delete"""

    ENDPOINT = "/api/comparison/delete"

    def test_delete_success(self):
        mock_manager = mock.MagicMock()
        mock_manager.delete_comparison.return_value = True

        app, client = _make_app_and_client()
        _override_auth(app, _edition_user())

        with mock.patch.dict("sys.modules", {"comparison": _make_comparison_module(mock_manager)}):
            resp = client.post(self.ENDPOINT, json={"id": 5})

        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_delete_not_found(self):
        mock_manager = mock.MagicMock()
        mock_manager.delete_comparison.return_value = False

        app, client = _make_app_and_client(raise_server_exceptions=False)
        _override_auth(app, _edition_user())

        with mock.patch.dict("sys.modules", {"comparison": _make_comparison_module(mock_manager)}):
            resp = client.post(self.ENDPOINT, json={"id": 999})

        assert resp.status_code == 404

    def test_delete_requires_edition(self):
        app, client = _make_app_and_client(raise_server_exceptions=False)
        _override_auth(app, _regular_user())

        resp = client.post(self.ENDPOINT, json={"id": 1})

        assert resp.status_code == 403
