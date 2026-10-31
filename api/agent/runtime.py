"""The wrapper every tool runs inside: identity, rate limit, caps, audit.

Identity comes from the ``Authorization`` header the SDK exposes as
``ctx.headers``, re-verified against the token table on EVERY call. The header is
a bearer secret that is checked, never a trusted claim, and nothing is stashed in
a ContextVar by the middleware: task propagation through the SDK's dispatch is not
something this code relies on.
"""

import asyncio
import base64
import json
import logging
import time
import uuid
from typing import Any, Awaitable, Callable, Optional, cast

from mcp.server.mcpserver import Context
from mcp.types import CallToolResult, ImageContent, TextContent
from starlette.requests import Request

from api.agent import limits, nonce, tokens
from api.agent.internal_client import err
from api.agent.live_updates import CALL_CONTEXT
from api.agent.tokens import bearer_token
from api.agent.tools_common import TOOL_LEVELS, tool_refusal

logger = logging.getLogger(__name__)

# ASGI scope key under which ``AgentAuthMiddleware`` leaves the request's ``mcp_settings()``
# for the tool wrapper, so one request reads the (clamped) config once.
SETTINGS_SCOPE_KEY = "facet.mcp_settings"
# Scope key under which ``POST /api/mcp/call`` leaves the logged-in session's grant, beside the
# settings: the wrapper then runs the tool for that session instead of verifying a bearer token.
INPAGE_SCOPE_KEY = "facet.inpage_grant"

Handler = Callable[[Any, tokens.ResolvedGrant, dict], Awaitable[dict]]


def to_result(envelope: dict, images: Optional[list] = None) -> CallToolResult:
    """Compact JSON as the text block, after any images; no duplicated structured content."""
    text = json.dumps(envelope, separators=(",", ":"), ensure_ascii=False, default=str)
    content: list = [ImageContent(type="image", data=base64.b64encode(data).decode("ascii"), mime_type=mime)
                     for data, mime in images or ()]
    content.append(TextContent(type="text", text=text))
    return CallToolResult(content=content, is_error=not envelope.get("ok", False))


def _row_count(envelope: dict) -> int:
    data = envelope.get("data")
    rows = data.get("rows") if isinstance(data, dict) else None
    return len(rows) if isinstance(rows, list) else 0


def level_refusal(name: str, resolved: Any, floor: Optional[str] = None) -> Optional[dict]:
    """The ``forbidden_level`` envelope when ``resolved`` is below the tool's floor, else None."""
    floor = floor or TOOL_LEVELS[name]
    if tokens.level_rank(resolved.level) >= tokens.level_rank(floor):
        return None
    needs = tokens.effective_requirement(floor)
    if resolved.inpage:
        return err("forbidden_level", f"This session's level is {resolved.level}; {name} needs "
                   f"{needs}" + (": unlock edition in Facet" if needs == "edition" else ""))
    hint = (" (an open install grants it only to a request from the computer running Facet, addressed as "
            "http://localhost:<port>, holding a Full-editing token minted under viewer.edition_password or "
            "viewer.trusted_local_editing; for remote use set viewer.password and mint an edition token)"
            if needs == "edition" and tokens.install_mode() == "open" else "")
    return err("forbidden_level", f"This token's level is {resolved.level}; {name} needs {needs}{hint}")


async def resolve_context(ctx: Any) -> tuple[Any, Any]:
    """``(grant, resolved)`` for a tool call's context, ``(None, None)`` when it is not valid."""
    session = cast(Request, ctx.request_context.request).scope.get(INPAGE_SCOPE_KEY)
    grant = session if session is not None else await asyncio.to_thread(
        tokens.verify_request, bearer_token(ctx.headers), ctx.request_context.request)
    return grant, (await asyncio.to_thread(grant.resolve) if grant else None)


async def run_tool(ctx: Context, name: str, handler: Handler, *, write: bool = False,
                   min_level: Optional[str] = None, args: Optional[dict] = None) -> CallToolResult:
    """Authenticate, rate-limit and run ``handler``; always return an envelope.

    Handlers never raise to the SDK: transport-level failure is reserved for the
    auth gate (401/403/429), so a tool problem reaches the model as data.

    The tool's floor (``min_level``, else its ``TOOL_LEVELS`` entry) is checked here
    BEFORE the rate limit and before ``handler`` runs, so a refused tool makes no
    upstream call at all (not even a read-only pre-count). The tool's requirement predicate
    (``TOOL_REQUIRES``, and ``ARG_REQUIRES`` against ``args``, the arguments that gate it) is
    checked right after, in the same place, with a ``feature_disabled`` or ``forbidden_level``
    answer, so the list hook and the call agree.
    """
    floor = min_level or TOOL_LEVELS[name]
    started = time.monotonic()
    images: list = []
    settings = cast(Request, ctx.request_context.request).scope[SETTINGS_SCOPE_KEY]
    token_id = None
    actor: Any = "-"
    call_marker = CALL_CONTEXT.set((name, uuid.uuid4().hex))
    try:
        grant, resolved = await resolve_context(ctx)
        if grant is None or resolved is None:
            envelope = err("forbidden_level", "This token is revoked or no longer valid")
        else:
            token_id = grant.token_id
            actor = grant.rate_key
            per_min = settings["write_rate_per_min" if write else "rate_per_min"]
            if (below := level_refusal(name, resolved, floor)) is not None:
                envelope = below
            elif (refusal := tool_refusal(name, resolved, settings, args)) is not None:
                envelope = err(refusal[0], refusal[1])
            else:
                allowed, retry_after = limits.check_rate(grant.rate_key, write, per_min)
                if allowed:
                    envelope = await handler(grant, resolved, settings)
                    # Images ride beside the JSON, so the JSON cap must not see (or count) them.
                    images = envelope.pop("_images", None) or []
                    envelope = limits.fit_envelope(
                        envelope, settings["max_rows"], settings["max_bytes"])
                else:
                    envelope = err("rate_limited", "Too many calls; slow down",
                                   retry_after_s=retry_after)
    except nonce.NonceCapacityError:
        envelope = err("rate_limited", "Too many confirmations are pending; retry in a few minutes",
                       retry_after_s=int(nonce.TTL_SECONDS))
    except Exception:
        logger.exception("Agent tool %s crashed", name)
        envelope = err("upstream_error", "The tool failed unexpectedly")
    else:
        if token_id is not None and envelope.get("error") not in ("forbidden_level", "feature_disabled", "rate_limited"):
            # Best effort, after the result exists: a locked database must not turn a
            # finished call into an error.
            try:
                await asyncio.to_thread(tokens.touch, token_id)
            except Exception as ex:
                logger.warning("Could not stamp last_used_at for MCP token %s: %r", token_id, ex)
    finally:
        CALL_CONTEXT.reset(call_marker)
    # Counts and codes only: never arguments (paths) and never the token.
    logger.info("MCP call actor=%s tool=%s ok=%s code=%s rows=%d ms=%d", actor, name,
                envelope.get("ok"), envelope.get("error", "-"), _row_count(envelope),
                (time.monotonic() - started) * 1000)
    return to_result(envelope, images if envelope.get("ok") else None)
