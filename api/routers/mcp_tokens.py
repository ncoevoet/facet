"""Agent (MCP) token management: mint (plaintext shown once), list, revoke.

Order of checks: the feature flag (404 when off) -> a HUMAN session
(``require_human_session`` refuses the agent's own internal JWT) -> the level rule.
Bearer-only on a password-protected install: a state-changing request never
authenticates from the cookie.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from api.agent import tokens
from api.auth import (
    EDITION_PASSWORD_KEY, CurrentUser, _edition_refusal, _is_open_install, decode_access_token,
    request_is_local, require_human_session,
)
from api.config import get_user_config, is_multi_user_enabled, mcp_settings
from api.models.mcp import (
    McpTokenCreate, McpTokenCreated, McpTokenList, McpTokenRevoked,
)

logger = logging.getLogger(__name__)


def _require_enabled() -> None:
    if not mcp_settings()['enabled']:
        raise HTTPException(status_code=404, detail="Not Found")


def _refuse_agent_token(request: Request) -> None:
    """403 for an agent's own bearer (``fct_...``) on these routes, as the internal JWT gets.

    Without this the generic session check answers 401 ("not a session"), which reads as
    "log in" to an agent that holds a perfectly valid token.
    """
    if (tokens.bearer_token(request.headers) or "").startswith(tokens.TOKEN_PREFIX):
        raise HTTPException(status_code=403, detail="Agent credentials cannot manage agent tokens")


OPEN_INSTALL_LOCAL_ONLY_DETAIL = (
    "Agent tokens on an open install can only be managed from the computer running Facet; "
    "set viewer.password to manage them from another machine")
OPEN_INSTALL_LOCAL_OR_EDITION_DETAIL = (
    "Agent tokens on an open install can only be managed from the computer running Facet "
    "or after logging in with the edition password; "
    "set viewer.password to manage them from another machine")


def _require_local_on_open_install(request: Request, user: CurrentUser = Depends(require_human_session)) -> None:
    """403 on an open or unreadable install unless the caller is local or holds edition.

    Unreadable means the config failed to parse: the password state is unknown, so it is treated as
    open rather than as passworded.

    Every caller there is the shared ``_anonymous`` principal, so without this any peer that
    reaches the viewer could list and revoke the local user's tokens, or fill their cap. Allowed:
    a request from the machine itself (``request_is_local``), or a session whose edition claim an
    edition password backs (``user.is_edition``, from the same ``require_human_session`` the
    routes use, so an agent credential still gets its own refusal first). The opt-in
    ``viewer.trusted_local_editing`` is not consulted: this is a boundary, not the editing opt-in.
    """
    if tokens.install_mode() not in ("open", "unreadable") or user.is_edition or request_is_local(request):
        return
    raise HTTPException(
        status_code=403,
        detail=(OPEN_INSTALL_LOCAL_ONLY_DETAIL if _is_open_install(EDITION_PASSWORD_KEY)
                else OPEN_INSTALL_LOCAL_OR_EDITION_DETAIL))


router = APIRouter(prefix="/api/mcp", tags=["mcp"],
                   dependencies=[Depends(_require_enabled), Depends(_refuse_agent_token),
                                 Depends(_require_local_on_open_install)])


def _granted_level(user: CurrentUser, requested: str) -> str:
    """The level to mint at, or a 403 when the session may not hold ``requested``.

    ``readonly`` is always allowed. ``edition`` needs an edition session. ``user``
    is a multi-user concept (an account's own per-photo rights); on a single
    password it has no meaning -- the rating routes demand edition -- so it is
    capped to ``readonly``. An open install holds ``readonly`` only, except for a session that holds
    edition there: one whose own request passed the loopback boundary under
    ``viewer.trusted_local_editing``, or one logged in with ``viewer.edition_password``
    (``user.is_edition`` is true for nothing else on an open install). Either may mint ``edition``;
    the token then resolves to edition only for a /mcp request that passes the same-machine boundary.
    """
    mode = tokens.install_mode()
    if mode == 'open' and requested == 'edition' and user.is_edition:
        return 'edition'
    if mode in ('open', 'unreadable'):
        return 'readonly'
    if requested == 'edition':
        if not user.is_edition:
            raise _edition_refusal("Edition access required to mint an edition token")
        return 'edition'
    if requested == 'user' and mode == 'multi':
        return 'user'
    return 'readonly'


def session_claims(request: Request) -> Optional[dict]:
    """The decoded claims of the request's own bearer JWT (the session), or None."""
    secret = tokens.bearer_token(request.headers)
    return decode_access_token(secret) if secret else None


def _shared_principal_scope(user: CurrentUser) -> Optional[int]:
    """The highest token rank this session may see and revoke, or None when it is unbounded.

    On a single password every session shares one principal (``_legacy``), so a
    viewer-only session would otherwise list and revoke the tokens an edition
    session minted. There the session may only manage tokens at or below its own
    level. In multi-user mode the owner scoping already isolates accounts.
    """
    if tokens.install_mode() == 'multi':
        return None
    return tokens.level_rank(tokens.session_level(user))


@router.post(
    "/tokens",
    response_model=McpTokenCreated,
    responses={
        401: {"description": "Authentication required."},
        403: {"description": "The session may not hold the requested level, an agent credential was used, or the install is open and the request is not local."},
        404: {"description": "The agent endpoint is disabled (viewer.mcp.enabled)."},
        412: {"description": "The owner already has the maximum number of live tokens."},
    },
)
def create_token(body: McpTokenCreate, user: CurrentUser = Depends(require_human_session)):
    """Mint a token. The plaintext is in this response and nowhere else, ever."""
    principal = tokens.session_principal(user.user_id)
    if not principal or (tokens.install_mode() == 'multi' and get_user_config(principal) is None):
        raise HTTPException(status_code=401, detail="Authentication required")
    level = _granted_level(user, body.level)
    try:
        row, plaintext = tokens.mint(principal, body.name, level, tokens.session_level(user),
                                     tokens.MAX_LIVE_TOKENS_PER_USER)
    except tokens.TokenLimitReached:
        raise HTTPException(
            status_code=412,
            detail=f"At most {tokens.MAX_LIVE_TOKENS_PER_USER} live tokens per user; revoke one first")
    logger.info("MCP token %d minted (level %s)", row['id'], level)
    return {**row, 'token': plaintext}


@router.get(
    "/tokens",
    response_model=McpTokenList,
    responses={
        401: {"description": "Authentication required."},
        403: {"description": "Superadmin access required, an agent credential was used, or the install is open and the request is not local."},
        404: {"description": "The agent endpoint is disabled (viewer.mcp.enabled)."},
    },
)
def list_tokens(
    all: int = Query(0, description="1 lists every owner's tokens (superadmin only)"),
    user: CurrentUser = Depends(require_human_session),
):
    """The caller's own tokens, newest first. Never the secret or its hash."""
    if all:
        if not (is_multi_user_enabled() and user.is_superadmin):
            raise HTTPException(status_code=403, detail="Superadmin access required")
        return {'tokens': tokens.list_tokens(None)}
    rows = tokens.list_tokens(tokens.session_principal(user.user_id))
    ceiling = _shared_principal_scope(user)
    if ceiling is not None:
        rows = [row for row in rows if tokens.level_rank(row['level']) <= ceiling]
    return {'tokens': rows}


@router.delete(
    "/tokens/{token_id}",
    response_model=McpTokenRevoked,
    responses={
        401: {"description": "Authentication required."},
        403: {"description": "An agent credential was used, the token's level is above the session's, or the install is open and the request is not local."},
        404: {"description": "No such live token, or the endpoint is disabled."},
    },
)
def revoke_token(token_id: int, user: CurrentUser = Depends(require_human_session)):
    """Revoke one of the caller's tokens (any token, for a superadmin)."""
    owner: Optional[str] = None if (is_multi_user_enabled() and user.is_superadmin) else tokens.session_principal(user.user_id)
    ceiling = _shared_principal_scope(user)
    if ceiling is not None:
        target = next((row for row in tokens.list_tokens(owner) if row['id'] == token_id), None)
        if target is not None and tokens.level_rank(target['level']) > ceiling:
            raise _edition_refusal("Edition access required to revoke an edition token")
    if not tokens.revoke(token_id, owner):
        raise HTTPException(status_code=404, detail="Token not found")
    logger.info("MCP token %d revoked", token_id)
    return {'ok': True, 'id': token_id}
