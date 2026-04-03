"""
Authentication router.

Handles login, logout, edition auth, and auth status.
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request

from api.auth import (
    create_access_token, verify_password, verify_legacy_password,
    upgrade_legacy_password, _login_limiter,
    CurrentUser, get_optional_user, require_authenticated,
    is_edition_enabled, is_edition_authenticated,
)
from api.config import (
    VIEWER_CONFIG, is_multi_user_enabled, get_user_config
)
from api.models.auth import (
    LoginRequest, LoginResponse, EditionLoginRequest, AuthStatusResponse
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request):
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
        return LoginResponse(
            access_token=token,
            user={
                'user_id': body.username,
                'role': user.get('role', 'user'),
                'display_name': user.get('display_name', body.username),
            }
        )
    else:
        # Legacy single-password mode
        password = VIEWER_CONFIG.get('password', '')
        if not password:
            # No password required — return a token for no-auth mode
            token = create_access_token({'sub': '_anonymous', 'role': 'user'})
            return LoginResponse(access_token=token)

        if not verify_legacy_password(body.password, password):
            raise HTTPException(status_code=401, detail="Invalid password")

        # Upgrade plaintext password to PBKDF2 hash on first successful login
        # (idempotent — checks on-disk value, not stale in-memory VIEWER_CONFIG)
        upgrade_legacy_password('password', body.password)

        token = create_access_token({'sub': '_legacy', 'role': 'user'})
        return LoginResponse(access_token=token)


@router.post("/edition/login", response_model=LoginResponse)
def edition_login(body: EditionLoginRequest, request: Request):
    """Authenticate for edition mode (legacy single-user only)."""
    client_ip = request.client.host if request.client else "unknown"
    if not _login_limiter.is_allowed(client_ip):
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again later.")

    if is_multi_user_enabled():
        raise HTTPException(status_code=400, detail="Use /api/auth/login for multi-user auth")
    edition_password = VIEWER_CONFIG.get('edition_password', '')
    if not edition_password or not verify_legacy_password(body.password, edition_password):
        raise HTTPException(status_code=401, detail="Invalid password")

    # Upgrade plaintext edition password to PBKDF2 hash
    # (idempotent — checks on-disk value, not stale in-memory VIEWER_CONFIG)
    upgrade_legacy_password('edition_password', body.password)

    token = create_access_token({
        'sub': '_legacy',
        'role': 'user',
        'edition': True,
    })
    return LoginResponse(access_token=token)


@router.post("/edition/logout", response_model=LoginResponse)
def edition_logout(user: CurrentUser = Depends(require_authenticated)):
    """Drop edition privileges and return a non-edition token."""
    token = create_access_token({
        'sub': user.user_id or '_legacy',
        'role': user.role,
        'display_name': user.display_name,
    })
    return LoginResponse(access_token=token)


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
        user_id=user.user_id if user else None,
        user_role=user.role if user else None,
        display_name=user.display_name if user else None,
        features=VIEWER_CONFIG.get('features', {}),
        download_profiles=profile_names,
    )


