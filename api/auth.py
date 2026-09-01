"""
JWT authentication for the FastAPI API server.

Replaces Flask session-based auth with stateless JWT tokens.
Supports all 4 auth modes: no-password, legacy password, edition password, multi-user RBAC.
"""

import collections
import hmac
import hashlib
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from api.config import (
    JWT_ALGORITHM, JWT_EXPIRY_HOURS,
    VIEWER_CONFIG,
    config_load_failed,
    is_multi_user_enabled
)

VIEWER_PASSWORD_KEY = 'password'
EDITION_PASSWORD_KEY = 'edition_password'

VIEWER_GENERATION_CLAIM = 'pv'
EDITION_GENERATION_CLAIM = 'ev'
GENERATION_DIGEST_LENGTH = 12


# --- JWT TOKEN MANAGEMENT ---

_bearer_scheme = HTTPBearer(auto_error=False)


def password_generation(password_key: str) -> str:
    """Short digest naming the CURRENT stored value behind ``password_key``.

    Taken over what is on disk — the PBKDF2 hash once the password has been
    upgraded, never the plaintext the user typed — so it changes exactly when
    the password changes and discloses nothing about it. Tokens carry it, which
    is what lets a password change age out tokens minted under the previous one:
    nothing else invalidates a JWT server-side.
    """
    stored = VIEWER_CONFIG.get(password_key, '') or ''
    return hashlib.sha256(stored.encode('utf-8')).hexdigest()[:GENERATION_DIGEST_LENGTH]


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token bound to the current password generations."""
    # Read the secret through the module rather than the import-time bound
    # name: reload_config() rebinds api.config.JWT_SECRET in place, and a
    # snapshot taken at import time would keep signing with a rotated-out
    # secret until process restart. Mirrors frame._secret().
    from api import config

    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(hours=JWT_EXPIRY_HOURS))
    to_encode['exp'] = expire
    to_encode['iat'] = datetime.now(timezone.utc)
    to_encode[VIEWER_GENERATION_CLAIM] = password_generation(VIEWER_PASSWORD_KEY)
    to_encode[EDITION_GENERATION_CLAIM] = password_generation(EDITION_PASSWORD_KEY)
    return jwt.encode(to_encode, config.JWT_SECRET, algorithm=JWT_ALGORITHM)


def _match_password_generations(payload: dict) -> Optional[dict]:
    """Age ``payload`` against the passwords stored right now.

    A token that predates the current ``viewer.password`` is treated exactly as
    no token at all, so rotating it logs every session out. An outdated
    ``viewer.edition_password`` is narrower: the session survives with its
    edition claim stripped, so rotating that one revokes edition rights
    everywhere without logging anyone out. A token carrying neither claim was
    minted before tokens were bound at all and is likewise stale — accepting it
    would leave exactly the hole the claims exist to close.
    """
    viewer_generation = payload.get(VIEWER_GENERATION_CLAIM)
    edition_generation = payload.get(EDITION_GENERATION_CLAIM)
    if viewer_generation is None or edition_generation is None:
        return None
    if viewer_generation != password_generation(VIEWER_PASSWORD_KEY):
        return None
    if edition_generation != password_generation(EDITION_PASSWORD_KEY):
        payload['edition'] = False
    return payload


def decode_access_token(token: str) -> Optional[dict]:
    """Decode a JWT access token. Returns None if invalid or stale.

    Staleness is decided by :func:`_match_password_generations`: signature and
    expiry alone cannot express "this password has since changed", and no token
    is revocable server-side otherwise.
    """
    from api import config  # fresh read — see create_access_token

    try:
        payload = jwt.decode(token, config.JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except (jwt.InvalidTokenError, jwt.ExpiredSignatureError):
        return None
    return _match_password_generations(payload)


AUTH_COOKIE_NAME = 'facet_auth'


def set_auth_cookie(response, token: str) -> None:
    """Mirror the freshest JWT in an HttpOnly cookie.

    Browser-native requests that cannot carry an Authorization header
    (<img> tags, EventSource) would otherwise be anonymous and see nothing
    on a locked deployment. The cookie is honored only for safe methods
    (see get_optional_user), so state-changing routes stay Bearer-only.
    """
    response.set_cookie(
        AUTH_COOKIE_NAME, token,
        max_age=JWT_EXPIRY_HOURS * 3600,
        httponly=True, samesite='lax', path='/',
    )


def clear_auth_cookie(response) -> None:
    """Remove the auth cookie (logout)."""
    response.delete_cookie(AUTH_COOKIE_NAME, path='/')


# --- USER INFO FROM TOKEN ---

def _is_open_install(password_key):
    """True when the install legitimately has no lock behind ``password_key``.

    A scoring_config.json that exists but failed to parse yields a config with
    no passwords at all, which reads exactly like a deliberately open install
    and would hand edition rights to anonymous callers. Such an install is
    treated as locked; only a genuinely absent config, or a configured-and-
    empty password, stays open.
    """
    if config_load_failed() or is_multi_user_enabled():
        return False
    return not VIEWER_CONFIG.get(password_key, '')


class CurrentUser:
    """Represents the current authenticated user."""
    __slots__ = ('user_id', 'role', 'display_name', 'edition_authenticated')

    def __init__(self, user_id=None, role='user', display_name='',
                 edition_authenticated=False):
        self.user_id = user_id
        self.role = role
        self.display_name = display_name
        self.edition_authenticated = edition_authenticated

    @property
    def is_authenticated(self):
        return self.user_id is not None or self._is_no_password_mode()

    @property
    def is_edition(self):
        if is_multi_user_enabled():
            return self.role in ('admin', 'superadmin')
        if _is_open_install(EDITION_PASSWORD_KEY):
            return True
        return self.edition_authenticated

    @property
    def is_superadmin(self):
        return self.role == 'superadmin'

    def _is_no_password_mode(self):
        return _is_open_install(VIEWER_PASSWORD_KEY)


# --- DEPENDENCY INJECTION ---

async def get_optional_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> Optional[CurrentUser]:
    """Extract user from JWT token if present, without requiring auth."""
    token = credentials.credentials if credentials else None
    if token is None and request.method in ('GET', 'HEAD'):
        # <img> and EventSource requests cannot carry the Authorization
        # header; fall back to the HttpOnly login cookie for safe methods
        # only, so state-changing routes stay Bearer-only (no CSRF surface).
        token = request.cookies.get(AUTH_COOKIE_NAME)

    payload = decode_access_token(token) if token else None
    if payload is None:
        # No password mode — everyone is authenticated. A stale token, whether
        # it arrived in the cookie or as a Bearer, must not lock an open
        # install out: the same request carrying no token at all is let in.
        if _is_open_install(VIEWER_PASSWORD_KEY):
            return CurrentUser()
        return None

    # Share-client (proofing) tokens grant access ONLY through
    # require_share_client, which decodes the raw bearer itself. They must never
    # authenticate the regular surface: otherwise a shared-album link would
    # become a full authenticated (and, in empty-edition-password mode, edition)
    # session on every get_optional_user endpoint.
    if payload.get('role') == SHARE_CLIENT_ROLE:
        return None

    return CurrentUser(
        user_id=payload.get('sub'),
        role=payload.get('role', 'user'),
        display_name=payload.get('display_name', ''),
        edition_authenticated=payload.get('edition', False),
    )


async def require_authenticated(
    user: Optional[CurrentUser] = Depends(get_optional_user),
) -> CurrentUser:
    """Require an authenticated user. Raises 401 if not authenticated."""
    if user is None or not user.is_authenticated:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def require_edition(
    user: CurrentUser = Depends(require_authenticated),
) -> CurrentUser:
    """Require edition-level access. Raises 403 if not authorized."""
    if not user.is_edition:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Edition access required",
        )
    return user


async def require_auth(
    user: CurrentUser = Depends(require_authenticated),
) -> CurrentUser:
    """Require authenticated user for rating/favorite actions.

    In multi-user mode, any logged-in user passes.
    In legacy mode, checks edition authentication.
    """
    if is_multi_user_enabled():
        if not user.user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    else:
        if not user.is_edition:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Edition disabled")
    return user


async def require_superadmin(
    user: CurrentUser = Depends(require_authenticated),
) -> CurrentUser:
    """Require superadmin access."""
    if not is_multi_user_enabled():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Multi-user mode required")
    if not user.is_superadmin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Superadmin access required")
    return user


# --- SHARE CLIENT SESSIONS (proofing on shared albums) ---

SHARE_CLIENT_ROLE = 'share_client'


def create_share_client_token(album_id: int, client_name: str = '') -> str:
    """Mint a short-lived JWT for a proofing client on one shared album.

    The token is scoped to a single album (``sub: share:<album_id>``) and a
    dedicated role. ``get_optional_user`` rejects that role outright, so the
    token authenticates nothing but ``require_share_client`` on this album's
    picks routes. Expiry comes from ``viewer.proofing.session_minutes``
    (default 1440 = 24h).
    """
    minutes = int((VIEWER_CONFIG.get('proofing', {}) or {}).get('session_minutes', 1440))
    return create_access_token(
        {
            'sub': f'share:{album_id}',
            'role': SHARE_CLIENT_ROLE,
            'album_id': album_id,
            'client_name': client_name,
        },
        expires_delta=timedelta(minutes=minutes),
    )


async def require_share_client(
    album_id: int,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> dict:
    """Require a share-client JWT bound to the path's ``album_id``.

    Validates the bearer token's role AND that it was minted for the same
    album as the route being called — a session for album A can never write
    picks on album B. Raises 403 otherwise.
    """
    payload = decode_access_token(credentials.credentials) if credentials else None
    if (
        payload is None
        or payload.get('role') != SHARE_CLIENT_ROLE
        or payload.get('album_id') != album_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Share session required",
        )
    return payload


# --- PASSWORD HASHING (multi-user) ---

def hash_password(password: str) -> str:
    """Hash a password using PBKDF2-HMAC-SHA256. Returns 'salt_hex:dk_hex'."""
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    return f"{salt.hex()}:{dk.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password against a stored 'salt_hex:dk_hex' hash."""
    try:
        salt_hex, dk_hex = stored_hash.split(':')
        salt = bytes.fromhex(salt_hex)
        expected_dk = bytes.fromhex(dk_hex)
        actual_dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
        return hmac.compare_digest(actual_dk, expected_dk)
    except (ValueError, AttributeError):
        return False


# --- LEGACY PASSWORD VERIFICATION ---

logger = logging.getLogger(__name__)


def _is_hashed(value: str) -> bool:
    """Return True if value looks like a stored PBKDF2 hash (salt_hex:dk_hex)."""
    parts = value.split(':')
    if len(parts) != 2 or len(parts[0]) != 32 or len(parts[1]) != 64:
        return False
    try:
        bytes.fromhex(parts[0])
        bytes.fromhex(parts[1])
        return True
    except ValueError:
        return False


def verify_legacy_password(candidate: str, stored: str) -> bool:
    """Verify a password against either a PBKDF2 hash or plaintext value."""
    if not stored:
        return False
    if _is_hashed(stored):
        return verify_password(candidate, stored)
    return hmac.compare_digest(candidate.encode('utf-8'), stored.encode('utf-8'))


def upgrade_legacy_password(config_key: str, plaintext: str):
    """Hash a plaintext password and rewrite it in scoring_config.json.

    Called after a successful login against a plaintext password. The
    read-modify-write is held under ``CONFIG_WRITE_LOCK`` — the single lock
    every writer of this file takes — so a concurrent weights, priority or
    scoring-context write can no longer land inside this one's window and be
    overwritten (or overwrite it). The reload happens after the lock is
    released, because it re-reads the file and may take that same lock.

    The pre-upgrade backup is the most sensitive copy this project writes: it
    is the one file still holding the PLAINTEXT password, seconds after a
    successful login. It therefore goes through the shared owner-only backup
    primitive instead of ``shutil.copy2`` plus a ``chmod``, which put those
    bytes on disk at the config's own (0664 under a default umask) mode first
    and only tightened them afterwards.
    """
    from api.config import (
        _CONFIG_BACKUP_SUFFIX,
        _CONFIG_PATH,
        CONFIG_WRITE_LOCK,
        reload_config,
        write_user_config,
    )
    from api.config_writes import write_owner_only_backup
    from config_resolve import load_resolved

    hashed = hash_password(plaintext)
    upgraded = False
    with CONFIG_WRITE_LOCK:
        try:
            config = load_resolved(_CONFIG_PATH)
        except Exception:
            logger.warning("Cannot upgrade password: failed to read config")
            return
        viewer = config.get('viewer', {})
        if viewer.get(config_key, '') and not _is_hashed(viewer[config_key]):
            viewer[config_key] = hashed
            config['viewer'] = viewer
            write_owner_only_backup(_CONFIG_PATH, f"{_CONFIG_PATH}{_CONFIG_BACKUP_SUFFIX}")
            try:
                write_user_config(_CONFIG_PATH, config)
                upgraded = True
            except Exception:
                logger.exception("Failed to upgrade password hash for %s", config_key)
    if upgraded:
        reload_config()
        logger.info("Upgraded plaintext %s to PBKDF2 hash", config_key)


def check_legacy_password_warnings():
    """Log warnings at startup if plaintext passwords are detected."""
    for key in (VIEWER_PASSWORD_KEY, EDITION_PASSWORD_KEY):
        value = VIEWER_CONFIG.get(key, '')
        if value and not _is_hashed(value):
            logger.warning(
                "Plaintext %s detected in scoring_config.json — "
                "will be hashed on next successful login", key
            )


# --- RATE LIMITING ---

class RateLimiter:
    """Sliding-window rate limiter keyed by string (e.g. IP address)."""

    def __init__(self, max_attempts: int = 5, window_seconds: int = 60):
        self._max = max_attempts
        self._window = window_seconds
        self._lock = threading.Lock()
        self._attempts: dict[str, collections.deque] = {}

    def is_allowed(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            # Periodically prune stale keys to prevent unbounded growth
            if len(self._attempts) > 10000:
                cutoff = now - self._window
                stale = [k for k, dq in self._attempts.items() if not dq or dq[-1] < cutoff]
                for k in stale:
                    del self._attempts[k]
            dq = self._attempts.setdefault(key, collections.deque())
            cutoff = now - self._window
            while dq and dq[0] < cutoff:
                dq.popleft()
            if len(dq) >= self._max:
                return False
            dq.append(now)
            return True


_login_limiter = RateLimiter(max_attempts=5, window_seconds=60)


# --- EDITION MODE HELPERS ---

def is_edition_enabled() -> bool:
    """Check if edition mode is available."""
    return True


def is_edition_authenticated(user: Optional[CurrentUser]) -> bool:
    """Check if user has edition-level access.

    When no edition password is configured (single-user, no lock),
    authenticated users get edition access automatically.
    Share-token visitors are excluded.
    """
    if user is None:
        return False
    if _is_open_install(EDITION_PASSWORD_KEY):
        return True
    return user.is_edition
