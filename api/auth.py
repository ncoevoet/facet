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
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from api.config import (
    JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRY_HOURS,
    VIEWER_CONFIG,
    is_multi_user_enabled
)


# --- JWT TOKEN MANAGEMENT ---

_bearer_scheme = HTTPBearer(auto_error=False)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(hours=JWT_EXPIRY_HOURS))
    to_encode['exp'] = expire
    to_encode['iat'] = datetime.now(timezone.utc)
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    """Decode a JWT access token. Returns None if invalid."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except (jwt.InvalidTokenError, jwt.ExpiredSignatureError):
        return None


# --- USER INFO FROM TOKEN ---

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
        if not VIEWER_CONFIG.get('edition_password', ''):
            return True
        return self.edition_authenticated

    @property
    def is_superadmin(self):
        return self.role == 'superadmin'

    def _is_no_password_mode(self):
        if is_multi_user_enabled():
            return False
        return not VIEWER_CONFIG.get('password', '')


# --- DEPENDENCY INJECTION ---

async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> Optional[CurrentUser]:
    """Extract user from JWT token if present, without requiring auth."""
    if credentials is None:
        # No password mode — everyone is authenticated
        if not is_multi_user_enabled() and not VIEWER_CONFIG.get('password', ''):
            return CurrentUser()
        return None

    payload = decode_access_token(credentials.credentials)
    if payload is None:
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
    return hmac.compare_digest(candidate, stored)


def upgrade_legacy_password(config_key: str, plaintext: str):
    """Hash a plaintext password and rewrite it in scoring_config.json.

    Called after a successful login against a plaintext password.
    Uses the same atomic write pattern as _load_and_ensure_share_secret().
    """
    from api.config import _CONFIG_PATH, _share_secret_lock, reload_config
    import json
    import shutil
    import tempfile

    hashed = hash_password(plaintext)
    with _share_secret_lock:
        try:
            with open(_CONFIG_PATH) as f:
                config = json.load(f)
        except Exception:
            logger.warning("Cannot upgrade password: failed to read config")
            return
        viewer = config.get('viewer', {})
        if viewer.get(config_key, '') and not _is_hashed(viewer[config_key]):
            viewer[config_key] = hashed
            config['viewer'] = viewer
            shutil.copy2(_CONFIG_PATH, f"{_CONFIG_PATH}.backup")
            dir_name = os.path.dirname(_CONFIG_PATH)
            fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix='.json')
            try:
                with os.fdopen(fd, 'w') as f:
                    json.dump(config, f, indent=2)
                os.replace(tmp_path, _CONFIG_PATH)
                reload_config()
                logger.info("Upgraded plaintext %s to PBKDF2 hash", config_key)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                logger.exception("Failed to upgrade password hash for %s", config_key)


def check_legacy_password_warnings():
    """Log warnings at startup if plaintext passwords are detected."""
    for key in ('password', 'edition_password'):
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
    if not is_multi_user_enabled() and not VIEWER_CONFIG.get('edition_password', ''):
        return True
    return user.is_edition
