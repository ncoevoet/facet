"""
Plugin manager for Facet — event hooks, webhooks, and built-in actions.

Plugins are Python modules placed in the ``plugins/`` directory. Each module
can define functions named after supported events (``on_score_complete``,
``on_new_photo``, ``on_burst_detected``, ``on_high_score``). The
``PluginManager`` discovers these modules at startup and dispatches events
to every registered handler plus any configured webhooks.

Webhook delivery and built-in actions run in a thread pool so they never
block the caller.

Expected ``scoring_config.json`` section::

    "plugins": {
        "enabled": true,
        "webhooks": [
            {
                "url": "http://example.com/hook",
                "events": ["on_score_complete", "on_high_score"],
                "min_score": 8.0
            }
        ],
        "actions": {
            "copy_high_scores": {
                "event": "on_high_score",
                "action": "copy_to_folder",
                "folder": "/path/to/best-photos",
                "min_score": 9.0
            }
        }
    }
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import os
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib import request as urllib_request
from urllib.error import URLError

logger = logging.getLogger(__name__)

SUPPORTED_EVENTS = frozenset({
    "on_score_complete",
    "on_new_photo",
    "on_burst_detected",
    "on_high_score",
})


class PluginManager:
    """Discovers plugin modules, manages event hooks, and dispatches events.

    Parameters
    ----------
    config : dict | None
        The full ``scoring_config.json`` dict.  When *None* the manager
        starts with plugins disabled and no webhooks/actions configured.
    plugins_dir : str | None
        Directory to scan for plugin modules.  Defaults to the ``plugins/``
        directory next to this file.
    max_workers : int
        Size of the thread pool used for non-blocking webhook delivery
        and built-in actions.
    """

    def __init__(
        self,
        config: dict | None = None,
        plugins_dir: str | None = None,
        max_workers: int = 4,
    ) -> None:
        self._lock = threading.Lock()
        # {event_name: [(module_name, callable), ...]}
        self._handlers: dict[str, list[tuple[str, Any]]] = {
            evt: [] for evt in SUPPORTED_EVENTS
        }
        self._plugins: dict[str, Any] = {}  # module_name -> module

        plugins_cfg = (config or {}).get("plugins", {})
        self._enabled: bool = plugins_cfg.get("enabled", False)
        self._webhooks: list[dict] = plugins_cfg.get("webhooks", [])
        self._actions: dict[str, dict] = plugins_cfg.get("actions", {})
        self._high_score_threshold: float = plugins_cfg.get("high_score_threshold", 8.0)
        self._pool: ThreadPoolExecutor | None = None
        self._max_workers = max_workers

        if plugins_dir is None:
            plugins_dir = os.path.dirname(os.path.abspath(__file__))
        self._plugins_dir = plugins_dir

        if self._enabled:
            self._pool = ThreadPoolExecutor(max_workers=max_workers)
            self._discover_plugins()
            self._register_actions()

    # ------------------------------------------------------------------
    # Plugin discovery
    # ------------------------------------------------------------------

    def _discover_plugins(self) -> None:
        """Scan *plugins_dir* for ``.py`` modules (skip ``__init__``) and
        register any functions whose names match supported events."""
        if not os.path.isdir(self._plugins_dir):
            logger.warning("Plugins directory not found: %s", self._plugins_dir)
            return

        for filename in sorted(os.listdir(self._plugins_dir)):
            if not filename.endswith(".py") or filename.startswith("__"):
                continue
            module_name = filename[:-3]
            module_path = os.path.join(self._plugins_dir, filename)
            try:
                spec = importlib.util.spec_from_file_location(
                    f"plugins.{module_name}", module_path
                )
                if spec is None or spec.loader is None:
                    continue
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                self._plugins[module_name] = module

                registered = []
                for event in SUPPORTED_EVENTS:
                    handler = getattr(module, event, None)
                    if callable(handler):
                        with self._lock:
                            self._handlers[event].append((module_name, handler))
                        registered.append(event)

                if registered:
                    logger.info(
                        "Loaded plugin '%s' — events: %s",
                        module_name,
                        ", ".join(sorted(registered)),
                    )
                else:
                    logger.debug(
                        "Plugin '%s' loaded but has no event handlers", module_name
                    )
            except Exception:
                logger.exception("Failed to load plugin '%s'", module_name)

    # ------------------------------------------------------------------
    # Built-in actions
    # ------------------------------------------------------------------

    def _register_actions(self) -> None:
        """Create handlers from the ``actions`` config section."""
        for name, action_cfg in self._actions.items():
            event = action_cfg.get("event")
            if event not in SUPPORTED_EVENTS:
                logger.warning(
                    "Action '%s' references unknown event '%s' — skipped",
                    name,
                    event,
                )
                continue

            action_type = action_cfg.get("action")
            if action_type == "copy_to_folder":
                handler = self._make_copy_handler(name, action_cfg)
            elif action_type == "send_notification":
                handler = self._make_notification_handler(name, action_cfg)
            else:
                logger.warning(
                    "Action '%s' has unknown type '%s' — skipped",
                    name,
                    action_type,
                )
                continue

            with self._lock:
                self._handlers[event].append((f"action:{name}", handler))
            logger.info("Registered action '%s' on event '%s'", name, event)

    @staticmethod
    def _make_copy_handler(name: str, cfg: dict):
        """Return a handler that copies a photo to *folder* when
        the score meets *min_score*."""
        folder = cfg.get("folder", "")
        min_score = cfg.get("min_score", 0.0)

        def _handler(data: dict) -> None:
            score = data.get("aggregate") or data.get("score", 0.0)
            if score < min_score:
                return
            src = data.get("path")
            if not src or not os.path.isfile(src):
                logger.warning(
                    "copy_to_folder(%s): source file not found: %s", name, src
                )
                return
            os.makedirs(folder, exist_ok=True)
            dst = os.path.join(folder, os.path.basename(src))
            shutil.copy2(src, dst)
            logger.info("copy_to_folder(%s): copied %s -> %s", name, src, dst)

        return _handler

    @staticmethod
    def _make_notification_handler(name: str, cfg: dict):
        """Return a handler that logs a notification message."""
        min_score = cfg.get("min_score", 0.0)

        def _handler(data: dict) -> None:
            score = data.get("aggregate") or data.get("score", 0.0)
            if score < min_score:
                return
            path = data.get("path", "<unknown>")
            logger.info(
                "NOTIFICATION(%s): photo '%s' scored %.2f",
                name,
                path,
                score,
            )

        return _handler

    # ------------------------------------------------------------------
    # Event emission
    # ------------------------------------------------------------------

    def emit(self, event_name: str, data: dict) -> None:
        """Dispatch *event_name* to all registered handlers and webhooks.

        Handlers and webhooks run in the thread pool so the caller is
        never blocked by slow I/O.

        Parameters
        ----------
        event_name : str
            One of the ``SUPPORTED_EVENTS``.
        data : dict
            Payload passed to every handler and serialised as JSON for
            webhooks.  Typically contains ``path``, ``aggregate``, and
            other score fields.
        """
        if not self._enabled:
            return
        if event_name not in SUPPORTED_EVENTS:
            logger.warning("emit() called with unknown event '%s'", event_name)
            return

        with self._lock:
            handlers = list(self._handlers.get(event_name, []))

        if self._pool is None:
            return

        for module_name, handler in handlers:
            self._pool.submit(self._safe_call, module_name, handler, data)

        for webhook in self._webhooks:
            if event_name in webhook.get("events", []):
                min_score = webhook.get("min_score", 0.0)
                score = data.get("aggregate") or data.get("score", 0.0)
                if score >= min_score:
                    self._pool.submit(
                        self._send_webhook, webhook["url"], event_name, data
                    )

    @staticmethod
    def _safe_call(name: str, handler, data: dict) -> None:
        """Invoke *handler* inside a try/except so one bad plugin cannot
        crash the process."""
        try:
            handler(data)
        except Exception:
            logger.exception("Handler '%s' raised an exception", name)

    @classmethod
    def _send_webhook(cls, url: str, event_name: str, data: dict) -> None:
        """POST JSON payload to *url* after SSRF validation."""
        try:
            cls._validate_webhook_url(url)
        except ValueError as exc:
            logger.error("Webhook %s — %s blocked (SSRF): %s", event_name, url, exc)
            return

        payload = json.dumps(
            {"event": event_name, "data": data},
            default=str,
        ).encode("utf-8")

        req = urllib_request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib_request.urlopen(req, timeout=10) as resp:
                logger.info(
                    "Webhook %s — %s responded %s",
                    event_name,
                    url,
                    resp.status,
                )
        except URLError as exc:
            logger.error("Webhook %s — %s failed: %s", event_name, url, exc)
        except Exception:
            logger.exception("Webhook %s — %s unexpected error", event_name, url)

    # ------------------------------------------------------------------
    # Introspection helpers (used by the API router)
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._enabled

    def list_plugins(self) -> list[dict]:
        """Return metadata about every loaded plugin module."""
        result = []
        for name, module in self._plugins.items():
            events = [
                evt
                for evt in SUPPORTED_EVENTS
                if callable(getattr(module, evt, None))
            ]
            result.append({
                "name": name,
                "file": getattr(module, "__file__", None),
                "events": sorted(events),
                "doc": (getattr(module, "__doc__", None) or "").strip(),
            })
        return result

    def list_webhooks(self) -> list[dict]:
        """Return the configured webhook list (URLs redacted to host only)."""
        from urllib.parse import urlparse

        results = []
        for wh in self._webhooks:
            parsed = urlparse(wh.get("url", ""))
            results.append({
                "host": parsed.hostname or wh.get("url"),
                "events": wh.get("events", []),
                "min_score": wh.get("min_score", 0.0),
            })
        return results

    def list_actions(self) -> list[dict]:
        """Return the configured actions list."""
        return [
            {"name": name, **cfg}
            for name, cfg in self._actions.items()
        ]

    @staticmethod
    def _validate_webhook_url(url: str) -> None:
        """Reject URLs targeting private/loopback networks (SSRF prevention)."""
        import ipaddress
        import socket
        from urllib.parse import urlparse

        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"Unsupported scheme: {parsed.scheme}")
        hostname = parsed.hostname
        if not hostname:
            raise ValueError("No hostname in URL")
        for info in socket.getaddrinfo(hostname, parsed.port or 80):
            addr = ipaddress.ip_address(info[4][0])
            if addr.is_private or addr.is_loopback or addr.is_link_local:
                raise ValueError(f"URL resolves to private address: {addr}")

    def test_webhook(self, url: str) -> dict:
        """Send a test payload to *url* and return the result.

        This runs **synchronously** (called from an API endpoint that
        awaits the result).
        """
        try:
            self._validate_webhook_url(url)
        except ValueError as exc:
            return {"ok": False, "error": str(exc), "url": url}

        test_data = {
            "event": "test",
            "data": {
                "path": "/test/photo.jpg",
                "aggregate": 8.5,
                "aesthetic": 9.0,
                "message": "This is a test webhook from Facet.",
            },
        }
        payload = json.dumps(test_data, default=str).encode("utf-8")
        req = urllib_request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib_request.urlopen(req, timeout=10) as resp:
                return {"ok": True, "status": resp.status, "url": url}
        except URLError as exc:
            return {"ok": False, "error": str(exc), "url": url}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "url": url}

    @property
    def high_score_threshold(self) -> float:
        return self._high_score_threshold

    def shutdown(self) -> None:
        """Shut down the thread pool. Call on application exit."""
        if self._pool is not None:
            self._pool.shutdown(wait=True, cancel_futures=True)


# ------------------------------------------------------------------
# Module-level singleton
# ------------------------------------------------------------------

_global_manager: PluginManager | None = None


def get_plugin_manager() -> PluginManager | None:
    """Return the global PluginManager instance, or *None* if not initialised."""
    return _global_manager


def init_global_plugin_manager(config: dict | None = None) -> PluginManager:
    """Create (or replace) the global PluginManager singleton."""
    global _global_manager
    _global_manager = PluginManager(config=config)
    return _global_manager
