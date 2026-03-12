"""
Plugin management endpoints.

Exposes loaded plugins, webhook configuration, and a test-webhook helper.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import CurrentUser, require_edition

router = APIRouter(tags=["plugins"])
logger = logging.getLogger(__name__)

# Module-level reference — set by ``init_plugin_manager()``.
_manager = None


def init_plugin_manager(manager) -> None:
    """Store a reference to the application's ``PluginManager``.

    Called once during app startup (see ``api/__init__.py``).
    """
    global _manager
    _manager = manager


def _get_manager():
    if _manager is None:
        raise HTTPException(
            status_code=503, detail="Plugin system not initialised"
        )
    return _manager


# --- Request models ---

class TestWebhookRequest(BaseModel):
    url: str = Field(..., min_length=1, max_length=2000)


# --- Endpoints ---

@router.get("/api/plugins")
async def list_plugins(
    user: Optional[CurrentUser] = Depends(require_edition),
):
    """List loaded plugins, webhooks, and configured actions."""
    mgr = _get_manager()
    return {
        "enabled": mgr.enabled,
        "plugins": mgr.list_plugins(),
        "webhooks": mgr.list_webhooks(),
        "actions": mgr.list_actions(),
    }


@router.post("/api/plugins/test-webhook")
async def test_webhook(
    body: TestWebhookRequest,
    user: Optional[CurrentUser] = Depends(require_edition),
):
    """Send a test payload to *url* and report whether it succeeded."""
    mgr = _get_manager()
    result = mgr.test_webhook(body.url)
    if not result["ok"]:
        logger.warning("Test webhook to %s failed: %s", body.url, result.get("error"))
    return result
