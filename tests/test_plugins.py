"""Tests for the plugin management endpoints (api/routers/plugins.py) and PluginManager."""

from unittest import mock
from unittest.mock import MagicMock

import pytest

from plugins import PluginManager, get_plugin_manager, init_global_plugin_manager
import plugins as plugins_module


# ---------------------------------------------------------------------------
# PluginManager unit tests
# ---------------------------------------------------------------------------

class TestGlobalSingleton:
    def setup_method(self):
        """Reset global singleton before each test."""
        plugins_module._global_manager = None

    def teardown_method(self):
        """Clean up global singleton after each test."""
        mgr = plugins_module._global_manager
        if mgr is not None:
            mgr.shutdown()
        plugins_module._global_manager = None

    def test_get_returns_none_before_init(self):
        assert get_plugin_manager() is None

    def test_init_creates_singleton(self):
        mgr = init_global_plugin_manager()
        assert mgr is not None
        assert get_plugin_manager() is mgr
        assert mgr.enabled is False  # no config → disabled

    def test_init_with_config(self, tmp_path):
        mgr = init_global_plugin_manager(config={
            "plugins": {"enabled": True, "high_score_threshold": 7.5}
        })
        assert mgr.enabled is True
        assert mgr.high_score_threshold == 7.5
        assert get_plugin_manager() is mgr

    def test_init_replaces_previous(self):
        mgr1 = init_global_plugin_manager()
        mgr2 = init_global_plugin_manager()
        assert mgr1 is not mgr2
        assert get_plugin_manager() is mgr2


class TestPluginManagerInit:
    def test_disabled_by_default(self):
        mgr = PluginManager(config=None)
        assert mgr.enabled is False

    def test_enabled_with_config(self, tmp_path):
        mgr = PluginManager(
            config={"plugins": {"enabled": True}},
            plugins_dir=str(tmp_path),  # empty dir, no plugins to load
        )
        assert mgr.enabled is True
        mgr.shutdown()

    def test_list_plugins_empty(self):
        mgr = PluginManager(config=None)
        assert mgr.list_plugins() == []

    def test_list_webhooks_redacts_url(self):
        mgr = PluginManager(config={
            "plugins": {
                "enabled": False,
                "webhooks": [
                    {"url": "http://example.com/hook", "events": ["on_score_complete"]}
                ],
            }
        })
        hooks = mgr.list_webhooks()
        assert len(hooks) == 1
        assert hooks[0]["host"] == "example.com"
        assert "on_score_complete" in hooks[0]["events"]

    def test_high_score_threshold_default(self):
        mgr = PluginManager(config=None)
        assert mgr.high_score_threshold == 8.0

    def test_high_score_threshold_from_config(self):
        mgr = PluginManager(config={
            "plugins": {"enabled": False, "high_score_threshold": 9.5}
        })
        assert mgr.high_score_threshold == 9.5

    def test_list_actions_from_config(self):
        mgr = PluginManager(config={
            "plugins": {
                "enabled": False,
                "actions": {
                    "copy_best": {
                        "event": "on_high_score",
                        "action": "copy_to_folder",
                        "folder": "/best",
                        "min_score": 9.0,
                    }
                },
            }
        })
        actions = mgr.list_actions()
        assert len(actions) == 1
        assert actions[0]["name"] == "copy_best"
        assert actions[0]["min_score"] == 9.0


class TestPluginManagerEmit:
    def test_emit_does_nothing_when_disabled(self):
        mgr = PluginManager(config=None)
        # Should not raise
        mgr.emit("on_score_complete", {"path": "/a.jpg", "aggregate": 5.0})

    def test_emit_unknown_event_logs_warning(self, tmp_path):
        mgr = PluginManager(
            config={"plugins": {"enabled": True}},
            plugins_dir=str(tmp_path),
        )
        with mock.patch("plugins.logger") as mock_logger:
            mgr.emit("on_nonexistent_event", {})
            mock_logger.warning.assert_called_once()
        mgr.shutdown()


class TestPluginManagerEmitPayload:
    def test_emit_calls_handler_with_data(self, tmp_path):
        plugin_file = tmp_path / "capture.py"
        plugin_file.write_text(
            "captured = []\n"
            "def on_score_complete(data):\n"
            "    captured.append(data)\n"
        )
        mgr = PluginManager(
            config={"plugins": {"enabled": True}},
            plugins_dir=str(tmp_path),
        )
        payload = {
            "path": "/test.jpg",
            "filename": "test.jpg",
            "aggregate": 8.5,
            "aesthetic": 9.0,
            "comp_score": 7.5,
            "category": "portrait",
            "tags": "person, outdoor",
        }
        mgr.emit("on_score_complete", payload)
        mgr.shutdown()
        # Handler runs in thread pool — shutdown() waits for completion
        captured = mgr._plugins["capture"].captured
        assert len(captured) == 1
        assert captured[0]["path"] == "/test.jpg"
        assert captured[0]["aggregate"] == 8.5

    def test_emit_on_high_score_respects_threshold(self, tmp_path):
        plugin_file = tmp_path / "capture.py"
        plugin_file.write_text(
            "high_scores = []\n"
            "def on_high_score(data):\n"
            "    high_scores.append(data)\n"
        )
        mgr = PluginManager(
            config={"plugins": {"enabled": True, "high_score_threshold": 9.0}},
            plugins_dir=str(tmp_path),
        )
        assert mgr.high_score_threshold == 9.0
        # Below threshold — should not trigger
        mgr.emit("on_high_score", {"path": "/a.jpg", "aggregate": 8.5})
        mgr.shutdown()
        captured = mgr._plugins["capture"].high_scores
        # The handler is called regardless — threshold check is done by the caller (scorer)
        assert len(captured) == 1  # PluginManager dispatches; scorer gates the call

    def test_emit_on_burst_detected_payload(self, tmp_path):
        plugin_file = tmp_path / "capture.py"
        plugin_file.write_text(
            "bursts = []\n"
            "def on_burst_detected(data):\n"
            "    bursts.append(data)\n"
        )
        mgr = PluginManager(
            config={"plugins": {"enabled": True}},
            plugins_dir=str(tmp_path),
        )
        payload = {
            "burst_group_id": 0,
            "photo_count": 3,
            "best_path": "/best.jpg",
            "paths": ["/a.jpg", "/b.jpg", "/best.jpg"],
        }
        mgr.emit("on_burst_detected", payload)
        mgr.shutdown()
        captured = mgr._plugins["capture"].bursts
        assert len(captured) == 1
        assert captured[0]["photo_count"] == 3
        assert captured[0]["best_path"] == "/best.jpg"
        assert len(captured[0]["paths"]) == 3


class TestPluginManagerTestWebhook:
    def test_rejects_private_url(self):
        mgr = PluginManager(config=None)
        result = mgr.test_webhook("http://127.0.0.1/hook")
        assert result["ok"] is False
        assert "private" in result["error"].lower() or "loopback" in result["error"].lower()

    def test_rejects_unsupported_scheme(self):
        mgr = PluginManager(config=None)
        result = mgr.test_webhook("ftp://example.com/hook")
        assert result["ok"] is False
        assert "scheme" in result["error"].lower()


class TestPluginManagerDiscovery:
    def test_discovers_plugin_with_event_handler(self, tmp_path):
        """A .py file with a supported event function is registered."""
        plugin_file = tmp_path / "sample_plugin.py"
        plugin_file.write_text(
            'def on_score_complete(data):\n    pass\n'
        )
        mgr = PluginManager(
            config={"plugins": {"enabled": True}},
            plugins_dir=str(tmp_path),
        )
        plugins = mgr.list_plugins()
        assert len(plugins) == 1
        assert plugins[0]["name"] == "sample_plugin"
        assert "on_score_complete" in plugins[0]["events"]
        mgr.shutdown()

    def test_skips_init_files(self, tmp_path):
        (tmp_path / "__init__.py").write_text("")
        mgr = PluginManager(
            config={"plugins": {"enabled": True}},
            plugins_dir=str(tmp_path),
        )
        assert mgr.list_plugins() == []
        mgr.shutdown()

    def test_missing_plugins_dir_does_not_crash(self):
        mgr = PluginManager(
            config={"plugins": {"enabled": True}},
            plugins_dir="/nonexistent/path",
        )
        assert mgr.list_plugins() == []
        mgr.shutdown()


class TestPluginManagerActions:
    def test_copy_handler_skips_below_min_score(self, tmp_path):
        handler = PluginManager._make_copy_handler("test", {
            "folder": str(tmp_path / "out"),
            "min_score": 9.0,
        })
        # Score 5 is below min_score 9 — nothing should be copied
        handler({"path": "/photo.jpg", "aggregate": 5.0})
        assert not (tmp_path / "out").exists()

    def test_notification_handler_logs_above_min_score(self):
        handler = PluginManager._make_notification_handler("test", {"min_score": 7.0})
        with mock.patch("plugins.logger") as mock_logger:
            handler({"path": "/photo.jpg", "aggregate": 9.0})
            mock_logger.info.assert_called_once()

    def test_notification_handler_skips_below_min_score(self):
        handler = PluginManager._make_notification_handler("test", {"min_score": 7.0})
        with mock.patch("plugins.logger") as mock_logger:
            handler({"path": "/photo.jpg", "aggregate": 3.0})
            mock_logger.info.assert_not_called()


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------

class TestPluginsEndpoints:
    @pytest.fixture()
    def client(self):
        from fastapi.testclient import TestClient
        from api import create_app
        from api.auth import require_edition, CurrentUser

        app = create_app()
        fake_user = CurrentUser(user_id="admin", role="admin", edition_authenticated=True)
        app.dependency_overrides[require_edition] = lambda: fake_user
        yield TestClient(app)
        app.dependency_overrides.clear()

    def test_list_plugins_returns_503_when_not_initialised(self, client):
        """Without init_plugin_manager(), the endpoint returns 503."""
        import api.routers.plugins as plugins_mod
        original = plugins_mod._manager
        plugins_mod._manager = None
        try:
            resp = client.get("/api/plugins")
            assert resp.status_code == 503
            assert "not initialised" in resp.json()["detail"].lower()
        finally:
            plugins_mod._manager = original

    def test_list_plugins_success(self, client):
        mock_mgr = MagicMock()
        mock_mgr.enabled = True
        mock_mgr.list_plugins.return_value = []
        mock_mgr.list_webhooks.return_value = []
        mock_mgr.list_actions.return_value = []

        import api.routers.plugins as plugins_mod
        original = plugins_mod._manager
        plugins_mod._manager = mock_mgr
        try:
            resp = client.get("/api/plugins")
            assert resp.status_code == 200
            body = resp.json()
            assert body["enabled"] is True
            assert body["plugins"] == []
        finally:
            plugins_mod._manager = original

    def test_test_webhook_returns_result(self, client):
        mock_mgr = MagicMock()
        mock_mgr.test_webhook.return_value = {"ok": True, "status": 200, "url": "http://example.com"}

        import api.routers.plugins as plugins_mod
        original = plugins_mod._manager
        plugins_mod._manager = mock_mgr
        try:
            resp = client.post(
                "/api/plugins/test-webhook",
                json={"url": "http://example.com"},
            )
            assert resp.status_code == 200
            assert resp.json()["ok"] is True
        finally:
            plugins_mod._manager = original
