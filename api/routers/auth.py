"""
Authentication router.

Handles login, logout, edition auth, and auth status.
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from api.auth import (
    create_access_token, verify_password, verify_legacy_password,
    upgrade_legacy_password, _login_limiter, _is_open_install, VIEWER_PASSWORD_KEY,
    EDITION_PASSWORD_KEY,
    CurrentUser, get_optional_user, require_authenticated,
    is_edition_enabled, is_edition_authenticated,
    set_auth_cookie, clear_auth_cookie,
)
from api.config import (
    VIEWER_CONFIG, is_multi_user_enabled, get_user_config
)
from api.models.auth import (
    LoginRequest, LoginResponse, EditionLoginRequest, AuthStatusResponse
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

_CONFIG_UNREADABLE_DETAIL = "Configuration could not be read; refusing to authenticate."


def _refuse_if_config_unreadable(password_key):
    """503 when an EMPTY stored password means "unreadable", not "no lock".

    The one place that decision is made. An empty password means two different
    things: an install that deliberately runs without a gate, and one whose
    config could not be read, where VIEWER_CONFIG is the shipped defaults and
    every password in it is empty. Minting a session in the second case hands a
    full library to an anonymous caller on a deployment the operator locked.
    :func:`api.auth._is_open_install` is the predicate that separates them — it
    short-circuits on ``config_load_failed()`` — and both login endpoints ask it
    the same way, so a third auth surface cannot reintroduce the value check by
    copying whichever of the two it happened to read first.
    """
    if not _is_open_install(password_key):
        raise HTTPException(status_code=503, detail=_CONFIG_UNREADABLE_DETAIL)


@router.post(
    "/login",
    response_model=LoginResponse,
    responses={
        # Declared so the generated client types carry it. FastAPI documents
        # only 200 and 422 for a route whose failures are all raised
        # HTTPExceptions, so this status was invisible to `npm run gen:api` --
        # and the client cannot type a status the schema does not mention.
        503: {"description": "Configuration could not be read; refusing to authenticate."},
        401: {"description": "Invalid credentials."},
        429: {"description": "Too many login attempts."},
    },
)
def login(body: LoginRequest, request: Request, response: Response):
    """Authenticate and receive a JWT token.

    In multi-user mode: requires username + password.
    In legacy mode: requires password only (matches viewer password).
    """
    client_ip = request.client.host if request.client else "unknown"
    if not _login_limiter.is_allowed(client_ip):
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again later.")

    multi_user = is_multi_user_enabled()

    if multi_user:
        if not body.username:
            raise HTTPException(status_code=400, detail="Username required")
        user = get_user_config(body.username)
        if not user or not verify_password(body.password, user.get('password_hash', '')):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        token = create_access_token({
            'sub': body.username,
            'role': user.get('role', 'user'),
            'display_name': user.get('display_name', body.username),
            'edition': user.get('role', 'user') in ('admin', 'superadmin'),
        })
        set_auth_cookie(response, token)
        return LoginResponse(
            access_token=token,
            user={
                'user_id': body.username,
                'role': user.get('role', 'user'),
                'display_name': user.get('display_name', body.username),
            }
        )
    else:
        # Legacy single-password mode.
        #
        # Ask :func:`_is_open_install` rather than reading the password out of
        # VIEWER_CONFIG — see :func:`_refuse_if_config_unreadable` for why the
        # value cannot answer the question.
        password = VIEWER_CONFIG.get(VIEWER_PASSWORD_KEY, '')
        if _is_open_install(VIEWER_PASSWORD_KEY):
            # No password required — return a token for no-auth mode
            token = create_access_token({'sub': '_anonymous', 'role': 'user'})
            set_auth_cookie(response, token)
            return LoginResponse(access_token=token)
        if not password:
            _refuse_if_config_unreadable(VIEWER_PASSWORD_KEY)

        if not verify_legacy_password(body.password, password):
            raise HTTPException(status_code=401, detail="Invalid password")

        # Upgrade plaintext password to PBKDF2 hash on first successful login
        # (idempotent — checks on-disk value, not stale in-memory VIEWER_CONFIG)
        upgrade_legacy_password(VIEWER_PASSWORD_KEY, body.password)

        token = create_access_token({'sub': '_legacy', 'role': 'user'})
        set_auth_cookie(response, token)
        return LoginResponse(access_token=token)


@router.post(
    "/edition/login",
    response_model=LoginResponse,
    responses={
        503: {"description": "Configuration could not be read; refusing to authenticate."},
        401: {"description": "Invalid password."},
        429: {"description": "Too many login attempts."},
    },
)
def edition_login(body: EditionLoginRequest, request: Request, response: Response):
    """Authenticate for edition mode (legacy single-user only)."""
    client_ip = request.client.host if request.client else "unknown"
    if not _login_limiter.is_allowed(client_ip):
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again later.")

    if is_multi_user_enabled():
        raise HTTPException(status_code=400, detail="Use /api/auth/login for multi-user auth")
    edition_password = VIEWER_CONFIG.get(EDITION_PASSWORD_KEY, '')
    if not edition_password:
        # Empty means two different things, exactly as it does on /login — the
        # shared predicate makes the call. A genuinely open install falls
        # through to the 401 below: there is no edition gate to unlock, so the
        # request is answered rather than reported as a server fault.
        _refuse_if_config_unreadable(EDITION_PASSWORD_KEY)
        raise HTTPException(status_code=401, detail="Invalid password")
    if not verify_legacy_password(body.password, edition_password):
        raise HTTPException(status_code=401, detail="Invalid password")

    # Upgrade plaintext edition password to PBKDF2 hash
    # (idempotent — checks on-disk value, not stale in-memory VIEWER_CONFIG)
    upgrade_legacy_password(EDITION_PASSWORD_KEY, body.password)

    token = create_access_token({
        'sub': '_legacy',
        'role': 'user',
        'edition': True,
    })
    set_auth_cookie(response, token)
    return LoginResponse(access_token=token)


@router.post("/edition/logout", response_model=LoginResponse)
def edition_logout(response: Response, user: CurrentUser = Depends(require_authenticated)):
    """Return a non-edition token for the client to replace its own with.

    Nothing is revoked server-side: the edition token the caller already holds
    stays valid until it expires or ``viewer.edition_password`` is rotated, so
    this only drops the privileges of a client that honours the swap. Rotating
    the edition password is what actually revokes edition rights everywhere.
    """
    token = create_access_token({
        'sub': user.user_id or '_legacy',
        'role': user.role,
        'display_name': user.display_name,
    })
    set_auth_cookie(response, token)
    return LoginResponse(access_token=token)


@router.post("/logout")
def logout(response: Response):
    """Clear the HttpOnly auth cookie; the client drops its Bearer token.

    Logout is a client-side token drop, not a revocation — a JWT already handed
    out cannot be invalidated individually without server-side session state.
    A leaked token is killed by rotating ``viewer.password``, which ages every
    token minted under the old value out at once.
    """
    clear_auth_cookie(response)
    return {"ok": True}


@router.get("/status", response_model=AuthStatusResponse)
def auth_status(user: Optional[CurrentUser] = Depends(get_optional_user)):
    """Get current authentication status and available features."""
    multi_user = is_multi_user_enabled()
    authenticated = user is not None and user.is_authenticated
    edition_auth = is_edition_authenticated(user) if user else False

    from api.raw_processing import get_darktable_profiles
    profile_names = get_darktable_profiles()

    return AuthStatusResponse(
        authenticated=authenticated,
        multi_user=multi_user,
        edition_enabled=is_edition_enabled(),
        edition_authenticated=edition_auth,
        # Through the predicate, not the raw value, for the reason spelled out
        # in :func:`_refuse_if_config_unreadable`. On an install whose config
        # could not be read, VIEWER_CONFIG is the shipped defaults and both
        # passwords are empty, so reading the value answered "no password is
        # required" — the precise wire-level claim the two login endpoints in
        # this file were changed to stop making, while they answer 503 to
        # everyone. One question, one predicate, three consistent answers.
        edition_password_required=(not multi_user) and not _is_open_install(EDITION_PASSWORD_KEY),
        login_password_required=(not multi_user) and not _is_open_install(VIEWER_PASSWORD_KEY),
        user_id=user.user_id if user else None,
        user_role=user.role if user else None,
        display_name=user.display_name if user else None,
        features=VIEWER_CONFIG.get('features', {}),
        download_profiles=profile_names,
    )


