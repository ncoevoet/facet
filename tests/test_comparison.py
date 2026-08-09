"""
Tests for the comparison API router -- pairwise ranking, stats, history, snapshots.

Uses mock-based approach (no real DB). Follows patterns from test_faces.py.
"""

import json
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from api import create_app
from api.auth import CurrentUser, require_authenticated

_AUTH_MODULE = "api.auth"
_ROUTER_MODULE = "api.routers.comparison"
_REPO_CONFIG_PATH = Path(__file__).resolve().parent.parent / "scoring_config.json"

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


# ---------------------------------------------------------------------------
# TestCategoryPriorities
# ---------------------------------------------------------------------------

class TestCategoryPriorities:
    """GET/POST /api/config/category_priorities"""

    ENDPOINT = "/api/config/category_priorities"

    def test_get_anonymous_401(self):
        # No-password legacy mode auto-authenticates anonymous callers, so a
        # true 401 needs multi-user mode (matches tests/test_rbac.py).
        app, client = _make_app_and_client(raise_server_exceptions=False)
        with mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=True):
            resp = client.get(self.ENDPOINT)
        assert resp.status_code == 401

    def test_get_requires_edition_403(self):
        app, client = _make_app_and_client(raise_server_exceptions=False)
        _override_auth(app, _regular_user())
        resp = client.get(self.ENDPOINT)
        assert resp.status_code == 403

    def test_get_returns_evaluation_order(self):
        mock_config = mock.MagicMock()
        mock_config.get_categories.return_value = [
            {"name": "silhouette", "priority": 42, "filters": {"is_silhouette": True}},
            {"name": "sports", "priority": 71, "filters": {"shutter_speed_max": 0.02}},
            {"name": "default", "priority": 999, "filters": {}},
        ]

        app, client = _make_app_and_client()
        _override_auth(app, _edition_user())

        with mock.patch.dict("sys.modules", {"config": mock.MagicMock(ScoringConfig=lambda *a, **k: mock_config)}):
            resp = client.get(self.ENDPOINT)

        assert resp.status_code == 200
        data = resp.json()
        assert [c["name"] for c in data["categories"]] == ["silhouette", "sports", "default"]
        assert data["categories"][0]["priority"] == 42

    def test_post_anonymous_401(self):
        app, client = _make_app_and_client(raise_server_exceptions=False)
        with mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=True):
            resp = client.post(self.ENDPOINT, json={"order": ["sports", "silhouette"]})
        assert resp.status_code == 401

    def test_post_requires_edition_403(self):
        app, client = _make_app_and_client(raise_server_exceptions=False)
        _override_auth(app, _regular_user())
        resp = client.post(self.ENDPOINT, json={"order": ["sports", "silhouette"]})
        assert resp.status_code == 403

    def test_post_calls_writer_reloads_and_clears_cache(self):
        app, client = _make_app_and_client()
        _override_auth(app, _edition_user())

        with (
            mock.patch(
                "api.config_writes.update_category_priorities",
                return_value="/tmp/scoring_config.json.backup.20260731",
            ) as mock_writer,
            mock.patch(f"{_ROUTER_MODULE}.reload_config") as mock_reload,
            mock.patch(f"{_ROUTER_MODULE}.invalidate_stats_cache") as mock_invalidate,
        ):
            resp = client.post(self.ENDPOINT, json={"order": ["sports", "silhouette", "default"]})

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["backup"] == "/tmp/scoring_config.json.backup.20260731"

        mock_writer.assert_called_once()
        call_args = mock_writer.call_args[0]
        assert call_args[1] == ["sports", "silhouette", "default"]
        mock_reload.assert_called_once()
        mock_invalidate.assert_called_once()

    def test_post_bad_order_returns_400(self):
        from fastapi import HTTPException

        app, client = _make_app_and_client(raise_server_exceptions=False)
        _override_auth(app, _edition_user())

        with mock.patch(
            "api.config_writes.update_category_priorities",
            side_effect=HTTPException(status_code=400, detail="order must be a permutation of existing categories"),
        ):
            resp = client.post(self.ENDPOINT, json={"order": ["not_a_real_category"]})

        assert resp.status_code == 400

    def test_priority_round_trip(self):
        """POSTing an order, then GETting, reflects the same evaluation order."""
        app, client = _make_app_and_client()
        _override_auth(app, _edition_user())

        new_order = [
            {"name": "sports", "priority": 42, "filters": {}},
            {"name": "silhouette", "priority": 71, "filters": {}},
        ]
        mock_config = mock.MagicMock()
        mock_config.get_categories.return_value = new_order

        with (
            mock.patch("api.config_writes.update_category_priorities", return_value=None),
            mock.patch(f"{_ROUTER_MODULE}.reload_config"),
            mock.patch(f"{_ROUTER_MODULE}.invalidate_stats_cache"),
            mock.patch.dict("sys.modules", {"config": mock.MagicMock(ScoringConfig=lambda *a, **k: mock_config)}),
        ):
            post_resp = client.post(self.ENDPOINT, json={"order": ["sports", "silhouette"]})
            get_resp = client.get(self.ENDPOINT)

        assert post_resp.status_code == 200
        assert get_resp.status_code == 200
        assert [c["name"] for c in get_resp.json()["categories"]] == ["sports", "silhouette"]


# ---------------------------------------------------------------------------
# TestScoringContextsEndpoint
# ---------------------------------------------------------------------------

class TestScoringContextsEndpoint:
    """GET /api/config/scoring_contexts"""

    ENDPOINT = "/api/config/scoring_contexts"

    def test_returns_configured_contexts_with_effective_order(self):
        mock_config = mock.MagicMock()
        mock_config.get_scoring_contexts.return_value = {
            "default": {"label_key": "ctx.default", "promote": [], "excluded": [], "suggest_from_moments": []},
            "action_stage": {
                "label_key": "ctx.action_stage",
                "promote": ["sports"],
                "excluded": ["silhouette"],
                "suggest_from_moments": ["sports_action"],
            },
        }
        mock_config.resolve_context_order.side_effect = lambda name: (
            [("sports", object()), ("default", object())] if name == "action_stage"
            else [("silhouette", object()), ("sports", object()), ("default", object())]
        )

        app, client = _make_app_and_client()

        with mock.patch.dict("sys.modules", {"config": mock.MagicMock(ScoringConfig=lambda *a, **k: mock_config)}):
            resp = client.get(self.ENDPOINT)

        assert resp.status_code == 200
        contexts = {c["name"]: c for c in resp.json()["contexts"]}
        assert contexts["action_stage"]["excluded"] == ["silhouette"]
        assert contexts["action_stage"]["effective_order"] == ["sports", "default"]
        assert contexts["default"]["effective_order"][0] == "silhouette"


# ---------------------------------------------------------------------------
# TestUpdateScoringContext
# ---------------------------------------------------------------------------

class TestUpdateScoringContext:
    """PUT /api/config/scoring_contexts/{name}"""

    CONTEXT = "action_stage"
    ENDPOINT = f"/api/config/scoring_contexts/{CONTEXT}"
    BODY = {"promote": ["sports"], "excluded": ["silhouette"]}

    def test_anonymous_401(self):
        # No-password legacy mode auto-authenticates anonymous callers, so a
        # true 401 needs multi-user mode (matches tests/test_rbac.py).
        app, client = _make_app_and_client(raise_server_exceptions=False)
        with mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=True):
            resp = client.put(self.ENDPOINT, json=self.BODY)
        assert resp.status_code == 401

    def test_requires_edition_403(self):
        app, client = _make_app_and_client(raise_server_exceptions=False)
        _override_auth(app, _regular_user())
        resp = client.put(self.ENDPOINT, json=self.BODY)
        assert resp.status_code == 403

    def test_calls_writer_reloads_and_clears_cache(self):
        app, client = _make_app_and_client()
        _override_auth(app, _edition_user())

        with (
            mock.patch(
                "api.config_writes.update_scoring_context",
                return_value="/tmp/scoring_config.json.backup.20260808",
            ) as mock_writer,
            mock.patch(f"{_ROUTER_MODULE}.reload_config") as mock_reload,
            mock.patch(f"{_ROUTER_MODULE}.invalidate_stats_cache") as mock_invalidate,
        ):
            resp = client.put(self.ENDPOINT, json=self.BODY)

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["backup"] == "/tmp/scoring_config.json.backup.20260808"

        mock_writer.assert_called_once()
        _, context, promote, excluded = mock_writer.call_args[0]
        assert context == self.CONTEXT
        assert promote == ["sports"]
        assert excluded == ["silhouette"]
        mock_reload.assert_called_once()
        mock_invalidate.assert_called_once()

    @pytest.mark.parametrize("detail", [
        "Unknown categories in promote: not_a_real_category",
        "'default' cannot appear in excluded: it is the pinned catch-all category",
        "Duplicate categories in promote: sports",
    ])
    def test_writer_rejection_surfaces_as_400(self, detail):
        from fastapi import HTTPException

        app, client = _make_app_and_client(raise_server_exceptions=False)
        _override_auth(app, _edition_user())

        with mock.patch(
            "api.config_writes.update_scoring_context",
            side_effect=HTTPException(status_code=400, detail=detail),
        ):
            resp = client.put(self.ENDPOINT, json=self.BODY)

        assert resp.status_code == 400
        assert resp.json()["detail"] == detail

    def test_unknown_context_surfaces_as_404(self, tmp_path):
        """An unknown named resource, answered like every other missing one --
        not folded into the 400s that mean "this body cannot be applied"."""
        import shutil

        config_copy = tmp_path / "scoring_config.json"
        shutil.copy2(_REPO_CONFIG_PATH, config_copy)

        app, client = _make_app_and_client(raise_server_exceptions=False)
        _override_auth(app, _edition_user())

        with (
            mock.patch(f"{_ROUTER_MODULE}._CONFIG_PATH", config_copy),
            mock.patch(f"{_ROUTER_MODULE}.reload_config"),
            mock.patch(f"{_ROUTER_MODULE}.invalidate_stats_cache"),
        ):
            resp = client.put("/api/config/scoring_contexts/not_a_real_context", json=self.BODY)

        assert resp.status_code == 404
        assert "not_a_real_context" in resp.json()["detail"]

    @pytest.mark.parametrize("body", [{"promote": ["sports"]}, {"excluded": ["macro"]}, {}])
    def test_partial_body_is_refused_and_changes_nothing(self, tmp_path, body):
        """A defaulted list silently wiped the omitted one: PUT {"promote": [...]}
        cleared ``excluded`` with no error. Both fields are now required, so a
        partial body dies in validation before any file is touched."""
        import shutil

        config_copy = tmp_path / "scoring_config.json"
        shutil.copy2(_REPO_CONFIG_PATH, config_copy)
        before = config_copy.read_text()

        app, client = _make_app_and_client(raise_server_exceptions=False)
        _override_auth(app, _edition_user())

        with (
            mock.patch(f"{_ROUTER_MODULE}._CONFIG_PATH", config_copy),
            mock.patch(f"{_ROUTER_MODULE}.reload_config"),
            mock.patch(f"{_ROUTER_MODULE}.invalidate_stats_cache"),
        ):
            resp = client.put(self.ENDPOINT, json=body)

        assert resp.status_code == 422
        assert config_copy.read_text() == before

    def test_round_trip_against_a_real_config_copy(self, tmp_path):
        """PUT then GET reports the new delta -- driven through the real writer
        and a real ScoringConfig over a disposable copy of the shipped config,
        so the round trip proves the file write, not a mock."""
        import shutil

        from config.scoring_config import ScoringConfig

        config_copy = tmp_path / "scoring_config.json"
        shutil.copy2(_REPO_CONFIG_PATH, config_copy)

        app, client = _make_app_and_client()
        _override_auth(app, _edition_user())

        config_module = mock.MagicMock(
            ScoringConfig=lambda *a, **k: ScoringConfig(str(config_copy), validate=False),
        )

        with (
            mock.patch(f"{_ROUTER_MODULE}._CONFIG_PATH", config_copy),
            mock.patch(f"{_ROUTER_MODULE}.reload_config"),
            mock.patch(f"{_ROUTER_MODULE}.invalidate_stats_cache"),
            mock.patch.dict("sys.modules", {"config": config_module}),
        ):
            put_resp = client.put(self.ENDPOINT, json={
                "promote": ["wildlife", "macro"],
                "excluded": ["portrait"],
            })
            get_resp = client.get("/api/config/scoring_contexts")

        assert put_resp.status_code == 200
        assert get_resp.status_code == 200

        contexts = {c["name"]: c for c in get_resp.json()["contexts"]}
        updated = contexts[self.CONTEXT]
        assert updated["promote"] == ["wildlife", "macro"]
        assert updated["excluded"] == ["portrait"]
        assert updated["effective_order"][:2] == ["wildlife", "macro"]
        assert "portrait" not in updated["effective_order"]
        # The delta is scoped to one context: every other preset is unchanged.
        assert contexts["motorsport"]["promote"] == ["sports", "vehicle"]


# ---------------------------------------------------------------------------
# TestOverrideCategory (reworked: sticky side-table override)
# ---------------------------------------------------------------------------

class TestOverrideCategory:
    """POST /api/comparison/override_category"""

    ENDPOINT = "/api/comparison/override_category"

    def test_requires_edition_403(self):
        app, client = _make_app_and_client(raise_server_exceptions=False)
        _override_auth(app, _regular_user())
        resp = client.post(self.ENDPOINT, json={"path": "/a.jpg", "category": "sports"})
        assert resp.status_code == 403

    def test_anonymous_401(self):
        app, client = _make_app_and_client(raise_server_exceptions=False)
        with mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=True):
            resp = client.post(self.ENDPOINT, json={"path": "/a.jpg", "category": "sports"})
        assert resp.status_code == 401

    def test_unknown_category_400(self):
        mock_config = mock.MagicMock()
        mock_config.get_categories.return_value = [{"name": "portrait"}, {"name": "landscape"}]

        app, client = _make_app_and_client(raise_server_exceptions=False)
        _override_auth(app, _edition_user())

        with mock.patch.dict("sys.modules", {"config": mock.MagicMock(ScoringConfig=lambda *a, **k: mock_config)}):
            resp = client.post(self.ENDPOINT, json={"path": "/a.jpg", "category": "not_a_category"})

        assert resp.status_code == 400

    def test_photo_not_found_404(self):
        mock_config = mock.MagicMock()
        mock_config.get_categories.return_value = [{"name": "sports"}]

        conn_mock = mock.MagicMock()
        conn_mock.execute.return_value.fetchone.return_value = None

        app, client = _make_app_and_client(raise_server_exceptions=False)
        _override_auth(app, _edition_user())

        with (
            mock.patch.dict("sys.modules", {"config": mock.MagicMock(ScoringConfig=lambda *a, **k: mock_config)}),
            mock.patch(f"{_ROUTER_MODULE}.get_db", _cm(conn_mock)),
        ):
            resp = client.post(self.ENDPOINT, json={"path": "/missing.jpg", "category": "sports"})

        assert resp.status_code == 404

    def test_valid_category_writes_side_table_and_photos_category(self):
        mock_config = mock.MagicMock()
        mock_config.get_categories.return_value = [{"name": "portrait"}, {"name": "sports"}]

        conn_mock = mock.MagicMock()
        conn_mock.execute.return_value.fetchone.return_value = {"path": "/a.jpg", "category": "silhouette"}

        mock_set_override = mock.MagicMock()
        fake_scoring_overrides_module = mock.MagicMock(set_photo_scoring_override=mock_set_override)

        class _FakeFacet:
            def __init__(self, *a, **k):
                pass

            def calculate_aggregate_logic(self, m):
                return 7.42, m.get('category_override')

        app, client = _make_app_and_client()
        _override_auth(app, _edition_user())

        with (
            mock.patch.dict("sys.modules", {
                "config": mock.MagicMock(ScoringConfig=lambda *a, **k: mock_config),
                "db.scoring_overrides": fake_scoring_overrides_module,
            }),
            mock.patch(f"{_ROUTER_MODULE}.get_db", _cm(conn_mock)),
            mock.patch("processing.scorer.Facet", _FakeFacet),
        ):
            resp = client.post(self.ENDPOINT, json={"path": "/a.jpg", "category": "sports"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["old_category"] == "silhouette"
        assert data["new_category"] == "sports"
        assert data["aggregate"] == 7.42

        # Side-table override was written as a manual, sticky override.
        mock_set_override.assert_called_once()
        _, kwargs = mock_set_override.call_args
        assert kwargs["category_override"] == "sports"
        assert kwargs["source"] == "manual"

        # photos.category AND aggregate were updated together, immediately --
        # D5: a category override must never leave the score stale next to
        # the new category.
        update_calls = [
            c for c in conn_mock.execute.call_args_list
            if c.args and isinstance(c.args[0], str) and "UPDATE photos SET category" in c.args[0]
        ]
        assert len(update_calls) == 1
        assert update_calls[0].args[1][0] == "sports"
        assert update_calls[0].args[1][1] == 7.42

        conn_mock.commit.assert_called_once()


# ---------------------------------------------------------------------------
# TestClearCategoryOverride
# ---------------------------------------------------------------------------

class TestClearCategoryOverride:
    """POST /api/comparison/clear_category_override"""

    ENDPOINT = "/api/comparison/clear_category_override"

    def test_requires_edition_403(self):
        app, client = _make_app_and_client(raise_server_exceptions=False)
        _override_auth(app, _regular_user())
        resp = client.post(self.ENDPOINT, json={"path": "/a.jpg"})
        assert resp.status_code == 403

    def test_anonymous_401(self):
        app, client = _make_app_and_client(raise_server_exceptions=False)
        with mock.patch(f"{_AUTH_MODULE}.is_multi_user_enabled", return_value=True):
            resp = client.post(self.ENDPOINT, json={"path": "/a.jpg"})
        assert resp.status_code == 401

    def test_photo_not_found_404(self):
        conn_mock = mock.MagicMock()
        conn_mock.execute.return_value.fetchone.return_value = None

        app, client = _make_app_and_client(raise_server_exceptions=False)
        _override_auth(app, _edition_user())

        with mock.patch(f"{_ROUTER_MODULE}.get_db", _cm(conn_mock)):
            resp = client.post(self.ENDPOINT, json={"path": "/missing.jpg"})

        assert resp.status_code == 404

    def test_clears_override(self):
        photo_row = {"path": "/a.jpg", "tags": "sunset, beach", "category": "motorsport"}
        conn_mock = mock.MagicMock()
        conn_mock.execute.return_value.fetchone.return_value = photo_row

        mock_clear = mock.MagicMock()
        mock_get_overrides = mock.MagicMock(return_value={"/a.jpg": {"scoring_context": None, "category_override": None}})
        fake_scoring_overrides_module = mock.MagicMock(
            clear_photo_scoring_override=mock_clear,
            get_photo_scoring_overrides=mock_get_overrides,
        )

        class _FakeFacet:
            def __init__(self, *a, **k):
                pass

            def calculate_aggregate_logic(self, m):
                assert m["category_override"] is None
                assert m["scoring_context"] is None
                return 6.11, "landscape"

        app, client = _make_app_and_client()
        _override_auth(app, _edition_user())

        with (
            mock.patch(f"{_ROUTER_MODULE}.get_db", _cm(conn_mock)),
            mock.patch.dict("sys.modules", {"db.scoring_overrides": fake_scoring_overrides_module}),
            mock.patch("processing.scorer.Facet", _FakeFacet),
        ):
            resp = client.post(self.ENDPOINT, json={"path": "/a.jpg"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["old_category"] == "motorsport"
        assert data["new_category"] == "landscape"
        assert data["aggregate"] == 6.11

        mock_clear.assert_called_once()
        args, kwargs = mock_clear.call_args
        assert args[1] == "/a.jpg"
        assert kwargs["field"] == "category_override"

        # photos.category AND aggregate are rewritten together, immediately --
        # D5: clearing an override must never leave the score stale next to
        # the recomputed category.
        update_calls = [
            c for c in conn_mock.execute.call_args_list
            if c.args and isinstance(c.args[0], str) and "UPDATE photos SET category" in c.args[0]
        ]
        assert len(update_calls) == 1
        assert update_calls[0].args[1][0] == "landscape"
        assert update_calls[0].args[1][1] == 6.11

        conn_mock.commit.assert_called_once()

    def test_clear_honors_remaining_scoring_context_override(self):
        """The photo's scoring_context override (independent of the cleared
        category_override) must still steer recomputation -- clearing the
        category pin should not also silently drop a sticky context."""
        photo_row = {"path": "/a.jpg", "tags": "", "category": "motorsport"}
        conn_mock = mock.MagicMock()
        conn_mock.execute.return_value.fetchone.return_value = photo_row

        mock_get_overrides = mock.MagicMock(
            return_value={"/a.jpg": {"scoring_context": "action_stage", "category_override": None}}
        )
        fake_scoring_overrides_module = mock.MagicMock(
            clear_photo_scoring_override=mock.MagicMock(),
            get_photo_scoring_overrides=mock_get_overrides,
        )

        seen = {}

        class _FakeFacet:
            def __init__(self, *a, **k):
                pass

            def calculate_aggregate_logic(self, m):
                seen["scoring_context"] = m["scoring_context"]
                return 5.0, "sports"

        app, client = _make_app_and_client()
        _override_auth(app, _edition_user())

        with (
            mock.patch(f"{_ROUTER_MODULE}.get_db", _cm(conn_mock)),
            mock.patch.dict("sys.modules", {"db.scoring_overrides": fake_scoring_overrides_module}),
            mock.patch("processing.scorer.Facet", _FakeFacet),
        ):
            resp = client.post(self.ENDPOINT, json={"path": "/a.jpg"})

        assert resp.status_code == 200
        assert resp.json()["new_category"] == "sports"
        assert seen["scoring_context"] == "action_stage"


# ---------------------------------------------------------------------------
# TestSuggestFilters
# ---------------------------------------------------------------------------

class TestSuggestFilters:
    """POST /api/comparison/suggest_filters

    D1: shutter_speed is stored as TEXT for every non-null row in the real
    126k-photo library ('1/250'-style fractions and plain decimal strings
    like '0.001'), and it was compared to a numeric filter threshold with a
    bare float()-free `<`/`>` -- raising TypeError -> 500 for the two
    categories (sports, long_exposure) that filter on it. Plus a latent
    photo_data['iso'] = metrics.get('ISO') bug (column is 'iso').
    """

    ENDPOINT = "/api/comparison/suggest_filters"

    def _photo_row(self, **overrides):
        row = {
            "path": "/a.jpg", "category": "silhouette", "tags": "sports,street",
            "face_count": 0, "face_ratio": 0.0, "is_silhouette": 1,
            "is_group_portrait": 0, "is_monochrome": 0, "mean_luminance": 0.3,
            "iso": 800, "shutter_speed": "0.001", "focal_length": 200.0, "f_stop": 2.8,
        }
        row.update(overrides)
        return row

    def test_real_decimal_shutter_speed_string_does_not_500(self):
        """The literal repro: category=silhouette, tags='sports,street',
        shutter_speed='0.001' (TEXT) against the 'sports' filter -- the one
        question ("why isn't this photo sports?") the feature exists to answer."""
        mock_config = mock.MagicMock()
        mock_config.get_categories.return_value = [
            {"name": "sports", "filters": {
                "required_tags": ["sports"], "tag_match_mode": "any", "shutter_speed_max": 0.02,
            }},
        ]

        conn_mock = mock.MagicMock()
        conn_mock.execute.return_value.fetchone.return_value = self._photo_row()

        app, client = _make_app_and_client(raise_server_exceptions=False)

        with (
            mock.patch.dict("sys.modules", {"config": mock.MagicMock(ScoringConfig=lambda *a, **k: mock_config)}),
            mock.patch(f"{_ROUTER_MODULE}.get_db", _cm(conn_mock)),
        ):
            resp = client.post(self.ENDPOINT, json={"path": "/a.jpg", "target_category": "sports"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["no_conflicts"] is True

    def test_fraction_shutter_speed_string_is_coerced_like_category_filter(self):
        """'1/250'-style fractional strings (the real on-disk format) must
        parse the same way CategoryFilter._to_float does, not just avoid
        crashing -- the endpoint has to agree with the real filter evaluation."""
        mock_config = mock.MagicMock()
        mock_config.get_categories.return_value = [
            {"name": "long_exposure", "filters": {"shutter_speed_min": 1.0, "shutter_speed_max": 10.0}},
        ]

        conn_mock = mock.MagicMock()
        conn_mock.execute.return_value.fetchone.return_value = self._photo_row(shutter_speed="1/250")

        app, client = _make_app_and_client(raise_server_exceptions=False)

        with (
            mock.patch.dict("sys.modules", {"config": mock.MagicMock(ScoringConfig=lambda *a, **k: mock_config)}),
            mock.patch(f"{_ROUTER_MODULE}.get_db", _cm(conn_mock)),
        ):
            resp = client.post(self.ENDPOINT, json={"path": "/a.jpg", "target_category": "long_exposure"})

        assert resp.status_code == 200
        data = resp.json()
        conflict = next(c for c in data["conflicts"] if c["filter"] == "shutter_speed_min")
        assert conflict["type"] == "below_minimum"
        assert conflict["actual"] == pytest.approx(1 / 250)

    def test_iso_uses_the_lowercase_db_column(self):
        """Latent bug: photo_data['iso'] read metrics.get('ISO') but the
        column is 'iso', so it was always None -- a false 'missing' conflict
        the moment any category filters on ISO."""
        mock_config = mock.MagicMock()
        mock_config.get_categories.return_value = [
            {"name": "astro", "filters": {"iso_min": 1000}},
        ]

        conn_mock = mock.MagicMock()
        conn_mock.execute.return_value.fetchone.return_value = self._photo_row(category="landscape", iso=800)

        app, client = _make_app_and_client(raise_server_exceptions=False)

        with (
            mock.patch.dict("sys.modules", {"config": mock.MagicMock(ScoringConfig=lambda *a, **k: mock_config)}),
            mock.patch(f"{_ROUTER_MODULE}.get_db", _cm(conn_mock)),
        ):
            resp = client.post(self.ENDPOINT, json={"path": "/a.jpg", "target_category": "astro"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["photo_values"]["iso"] == 800
        conflict = next(c for c in data["conflicts"] if c["filter"] == "iso_min")
        assert conflict["type"] == "below_minimum"
        assert conflict["actual"] == 800
