"""
JWT authentication for the FastAPI API server.

Replaces Flask session-based auth with stateless JWT tokens.
Supports all 4 auth modes: no-password, legacy password, edition password, multi-user RBAC.
"""

import collections
import hmac
import hashlib
import ipaddress
import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, cast
from urllib.parse import urlsplit

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from api.config import (
    JWT_ALGORITHM, JWT_EXPIRY_HOURS,
    VIEWER_CONFIG,
    _CONFIG_PATH,
    config_load_failed,
    is_burned_password,
    is_multi_user_enabled
)

VIEWER_PASSWORD_KEY = 'password'
EDITION_PASSWORD_KEY = 'edition_password'
TRUSTED_LOCAL_EDITING_KEY = 'trusted_local_editing'
# Still the right advice when viewer.trusted_local_editing is on: that opt-in
# never applies once an edition password is set, and a request it refuses
# (forwarded, cross-origin, non-loopback) can only edit through the password.
OPEN_INSTALL_EDIT_DETAIL = 'Set viewer.edition_password to enable editing'

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

    While the config cannot be read no token is accepted: the empty config it
    degrades to hashes to the same generation an open-install token carries, so
    the comparison below would wave that token through.
    """
    if config_load_failed():
        return None
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
    and would hand library access to anonymous callers. Such an install is
    treated as locked; only a genuinely absent config, or a configured-and-
    empty password, stays open. An open install is READ-ONLY: it grants library
    access, never edition rights -- not even to a token that carries an
    edition claim (see CurrentUser.is_edition). The one exception is the
    ``viewer.trusted_local_editing`` opt-in (see _trusted_local_editing).
    """
    if config_load_failed() or is_multi_user_enabled():
        return False
    return not VIEWER_CONFIG.get(password_key, '')


def _is_loopback_host(host):
    """True when binding ``host`` keeps the server reachable from this machine only.

    ``localhost`` and every loopback address qualify (an IPv4-mapped IPv6 one
    included, which ``ipaddress`` only recognises from Python 3.13). A wildcard
    (``0.0.0.0``, ``::``, empty) or any other hostname does not: it resolves to
    whatever interface the operator named, which is not known to be local.
    """
    if host.lower() == 'localhost':
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return (getattr(address, 'ipv4_mapped', None) or address).is_loopback


def open_install_exposure_warning(bind_host):
    """The startup warning for an open install that may be reachable beyond loopback, else None.

    An empty ``viewer.password`` (the shipped default) serves every request
    anonymously, originals included; ``viewer.py`` binds ``0.0.0.0`` by default
    and the Docker image relies on that. ``_is_open_install`` is the verdict the
    server itself uses for an anonymous caller, so this cannot disagree with it:
    a multi-user install or one whose config failed to load is locked, not open.

    ``bind_host`` is what ``viewer.py`` exported for its children
    (``api.BIND_HOST_ENV``). ``None`` or empty means the app was started some
    other way (``uvicorn api:create_app --factory ...``), whose bind address
    this process cannot see: the warning is then host-agnostic, because staying
    silent would hide the exposure from exactly the launches that bypass
    ``viewer.py``.
    """
    if not _is_open_install(VIEWER_PASSWORD_KEY):
        return None
    advice = ("Set viewer.password, or keep it local (--host 127.0.0.1; in Docker, "
              "publish the port as 127.0.0.1:5000:5000).")
    if not bind_host:
        return ("viewer.password is empty: anyone who can reach the viewer's port can browse "
                f"and download the whole library. {advice}")
    if _is_loopback_host(bind_host):
        return None
    shown = f"[{bind_host}]" if ':' in bind_host else bind_host
    return (f"viewer.password is empty and the viewer listens on {shown}: anyone who can reach "
            f"this port can browse and download the whole library. {advice}")


# Headers a reverse proxy or CDN adds to name the original client. Their
# presence means the loopback peer is a relay, not the user's browser.
_PROXY_HEADERS = frozenset({
    'forwarded', 'via', 'x-real-ip', 'x-client-ip', 'true-client-ip',
    'cf-connecting-ip', 'x-original-forwarded-for',
})
_LOCAL_HOST_RE = re.compile(r'(localhost|127\.0\.0\.1|\[::1\])(?::[0-9]{1,5})?', re.IGNORECASE)
_DEFAULT_PORTS = {'http': 80, 'https': 443}


def _origin(parts):
    """``(scheme, host, port)`` of a ``urlsplit`` result, the port defaulted from the scheme."""
    return parts.scheme, parts.hostname, parts.port or _DEFAULT_PORTS.get(parts.scheme)


def _trusted_local_editing_enabled():
    """The opt-in is on and the install has neither a browse nor an edition password.

    An operator who set ``viewer.edition_password`` expects it to be asked for,
    so the opt-in never overrides one; ``_is_open_install`` also keeps a failed
    config load and multi-user mode out.
    """
    return (VIEWER_CONFIG.get(TRUSTED_LOCAL_EDITING_KEY) is True
            and _is_open_install(VIEWER_PASSWORD_KEY)
            and _is_open_install(EDITION_PASSWORD_KEY))


def _is_proxied(request: Request) -> bool:
    return any(name.lower() in _PROXY_HEADERS or name.lower().startswith('x-forwarded-')
               for name in request.headers.keys())


def _is_loopback_peer(request: Request) -> bool:
    """The TCP peer itself is loopback. Raises ValueError for a non-IP peer.

    An IPv4-mapped peer (``::ffff:127.0.0.1``, what a dual-stack listener reports
    for a local IPv4 browser) is judged by its IPv4 address: ``is_loopback`` on
    the mapped form differs between Python 3.12 patch releases (gh-117566).
    """
    if request.client is None:
        return False
    address = ipaddress.ip_address(request.client.host)
    return (getattr(address, 'ipv4_mapped', None) or address).is_loopback


def _local_target_origin(request: Request):
    """Origin the browser addressed, or None unless it is a loopback name over http(s)."""
    hosts = request.headers.getlist('host')
    if (len(hosts) != 1 or not _LOCAL_HOST_RE.fullmatch(hosts[0])
            or request.url.scheme not in _DEFAULT_PORTS):
        return None
    return _origin(urlsplit(f'{request.url.scheme}://{hosts[0]}'))


def _same_origin_browser_metadata(request: Request, target_origin) -> bool:
    """Sec-Fetch-Site, Origin and Referer, when present, all name ``target_origin``."""
    sites = request.headers.getlist('sec-fetch-site')
    if len(sites) > 1 or (sites and sites[0] not in ('same-origin', 'none')):
        return False
    for name in ('origin', 'referer'):
        values = request.headers.getlist(name)
        if len(values) > 1:
            return False
        if not values:
            continue
        parts = urlsplit(values[0])
        if parts.username is not None or parts.password is not None or _origin(parts) != target_origin:
            return False
        if name == 'origin' and (parts.path not in ('', '/') or parts.query or parts.fragment):
            return False
    return True


def request_is_local(request: Request) -> bool:
    """The request came from a browser or tool on the machine running Facet.

    The boundary only, independent of any opt-in: no proxy header, a loopback TCP peer,
    a loopback ``Host`` over http(s), and same-origin browser metadata. Every check fails
    closed. The loopback peer is the real boundary: Host, Origin, Referer and
    Sec-Fetch-Site are client-controlled and only refuse, and an unmarked reverse proxy
    on the same host is indistinguishable from the user's browser.
    """
    try:
        if _is_proxied(request) or not _is_loopback_peer(request):
            return False
        target_origin = _local_target_origin(request)
        return target_origin is not None and _same_origin_browser_metadata(request, target_origin)
    except (ValueError, TypeError):
        return False


def _trusted_local_editing(request: Request) -> bool:
    """Whether ``viewer.trusted_local_editing`` grants this request edition.

    Derived from the request alone, never from a token claim: the opt-in is on, the
    install has no passwords, and the request passes :func:`request_is_local`. That is
    why the option must never run behind a reverse proxy.
    """
    return _trusted_local_editing_enabled() and request_is_local(request)


class _HttpView:
    """The three request attributes ``request_is_local`` reads, with a WebSocket's scheme mapped."""

    __slots__ = ('headers', 'client', 'url')

    def __init__(self, connection):
        self.headers = connection.headers
        self.client = connection.client
        self.url = connection.url.replace(scheme={'ws': 'http', 'wss': 'https'}.get(connection.url.scheme, connection.url.scheme))


def request_is_local_for(request) -> bool:
    """:func:`request_is_local` for anything that carries the request's headers, peer and URL.

    Accepts a ``Request``, a ``WebSocket`` or an ASGI scope's ``Request``. A WebSocket handshake
    addresses ``ws://`` or ``wss://``, which ``_local_target_origin`` would refuse outright, so the
    scheme is mapped to its HTTP twin first. Fails closed on anything it cannot read.
    """
    try:
        return request_is_local(cast(Request, _HttpView(request)))
    except (AttributeError, TypeError, ValueError):
        return False


def trusted_local_for(request) -> bool:
    """``_trusted_local_editing`` for anything :func:`request_is_local_for` accepts."""
    return _trusted_local_editing_enabled() and request_is_local_for(request)


class CurrentUser:
    """Represents the current authenticated user."""
    __slots__ = ('user_id', 'role', 'display_name', 'edition_authenticated', 'agent',
                 'trusted_local_editing')

    def __init__(self, user_id=None, role='user', display_name='',
                 edition_authenticated=False, agent=False, trusted_local_editing=False):
        self.user_id = user_id
        self.role = role
        self.display_name = display_name
        self.edition_authenticated = edition_authenticated
        self.agent = agent
        self.trusted_local_editing = trusted_local_editing

    @classmethod
    def from_payload(cls, payload, trusted_local_editing=False):
        """The user a decoded access-token payload describes.

        A REQUEST-derived trust (``trusted_local_editing``) is never applied to an agent request (the
        ``mcp`` claim): its level is its grant. The one local path for an agent is the server-signed
        ``mcp_local`` claim, which ``ResolvedGrant.jwt_claims`` writes only for a grant whose real /mcp
        request passed the boundary; it still needs the opt-in to be on and the install passwordless NOW.
        """
        agent = bool(payload.get('mcp'))
        if agent:
            trusted_local_editing = (payload.get('mcp_local') is True and payload.get('sub') is None
                                     and payload.get('edition') is True and _trusted_local_editing_enabled())
        return cls(
            user_id=payload.get('sub'),
            role=payload.get('role', 'user'),
            display_name=payload.get('display_name', ''),
            edition_authenticated=payload.get('edition', False),
            agent=agent,
            trusted_local_editing=trusted_local_editing,
        )

    @property
    def is_agent_request(self):
        """True when the request carries the agent layer's internal JWT (the ``mcp`` claim).

        Routes that LEARN from a user's decisions (pairwise comparisons, the auto-retrain
        counter) skip recording for such a request: an assistant's mass edit is not the user's taste.
        """
        return self.agent

    @property
    def is_authenticated(self):
        return self.user_id is not None or self._is_no_password_mode()

    @property
    def is_edition(self):
        # viewer.trusted_local_editing: derived per request (get_optional_user, or the signed
        # ``mcp_local`` claim for an agent), and only ever true on a single-user install with no
        # passwords at all (see _trusted_local_editing_enabled), so it overrides nothing below.
        if self.trusted_local_editing:
            return True
        if is_multi_user_enabled():
            return self.role in ('admin', 'superadmin')
        # An edition claim counts only while an edition password backs it: a
        # token minted earlier (e.g. a multi-user admin token after ``users``
        # was removed) must not grant edition on an install that is now open.
        # A failed config load is not "open" (see _is_open_install), so it
        # stays on the locked path.
        return self.edition_authenticated and not _is_open_install(EDITION_PASSWORD_KEY)

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
            return CurrentUser(trusted_local_editing=_trusted_local_editing(request))
        return None

    # Share-client (proofing) tokens grant access ONLY through
    # require_share_client, which decodes the raw bearer itself. They must never
    # authenticate the regular surface: otherwise a shared-album link would
    # become a full authenticated session on every get_optional_user endpoint.
    if payload.get('role') == SHARE_CLIENT_ROLE or payload.get('purpose'):
        return None

    return CurrentUser.from_payload(payload, trusted_local_editing=_trusted_local_editing(request))


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


async def require_human_session(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
    user: CurrentUser = Depends(require_authenticated),
) -> CurrentUser:
    """``require_authenticated`` that refuses an agent's internal credential.

    The 60-second JWTs the MCP layer mints for its own in-process calls carry an
    ``mcp`` claim. The routes that mint, list and revoke agent tokens use this so an
    agent can never create or widen a token of its own.
    """
    payload = decode_access_token(credentials.credentials) if credentials else None
    if payload is not None and payload.get('mcp'):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Agent credentials cannot manage agent tokens",
        )
    return user


def _edition_refusal(locked_detail):
    """The 403 for a caller without edition rights.

    On an open install (no edition password) no session can ever hold edition,
    so the detail says how to enable editing instead of a dead-end refusal.
    """
    detail = OPEN_INSTALL_EDIT_DETAIL if _is_open_install(EDITION_PASSWORD_KEY) else locked_detail
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


async def require_edition(
    user: CurrentUser = Depends(require_authenticated),
) -> CurrentUser:
    """Require edition-level access. Raises 403 if not authorized."""
    if not user.is_edition:
        raise _edition_refusal("Edition access required")
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
            raise _edition_refusal("Edition disabled")
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


def scan_feature_enabled(trusted_local, viewer_config):
    """The one scan-feature rule: ``features.show_scan_button``, waived for a trusted-local caller.

    ``trusted_local`` is the ``viewer.trusted_local_editing`` boundary (a human browser request, or an
    agent whose /mcp request passed it). ``viewer_config`` is the caller's own viewer config dict.
    """
    return bool(trusted_local) or bool(viewer_config.get('features', {}).get('show_scan_button', False))


def scan_access_refusal(multi_user, is_superadmin, is_edition, open_install, trusted_local=False):
    """The ``(status, detail)`` that refuses a scan trigger, or None when it is allowed.

    One pure rule shared by ``require_scan_access`` and the agent's ``start_scan`` /
    ``scan_status`` tools, so the tool and the route cannot disagree. Multi-user mode:
    superadmin only. Single-user mode: edition AND a locked install (an open install is refused
    even for a caller presenting an edition claim, because the route starts an OS subprocess),
    unless ``trusted_local`` -- the caller passed the ``viewer.trusted_local_editing`` boundary (a
    human browser request, or an agent carrying the signed ``mcp_local`` claim).
    """
    if multi_user:
        return None if is_superadmin else (status.HTTP_403_FORBIDDEN, "Superadmin access required")
    if open_install and not trusted_local:
        return status.HTTP_403_FORBIDDEN, "Set viewer.edition_password to enable the scan trigger"
    if not is_edition:
        return status.HTTP_403_FORBIDDEN, "Edition access required"
    return None


async def require_scan_access(
    user: CurrentUser = Depends(require_authenticated),
) -> CurrentUser:
    """Require access to trigger/monitor a library scan.

    Multi-user mode: superadmin only, unchanged. Single-user mode: edition
    access AND a locked install — an open install (empty
    viewer.edition_password) is refused even for a caller presenting an
    edition claim, with the actionable detail below, because this route
    starts an OS subprocess -- unless the caller passed the ``viewer.trusted_local_editing``
    boundary (``user.trusted_local_editing``). Raises 403 in both refusal cases; never 401
    (require_authenticated already covers "no session").
    """
    refusal = scan_access_refusal(
        is_multi_user_enabled(), user.is_superadmin, user.is_edition, _is_open_install(EDITION_PASSWORD_KEY),
        user.trusted_local_editing)
    if refusal is not None:
        raise HTTPException(status_code=refusal[0], detail=refusal[1])
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
    """Verify a password against either a PBKDF2 hash or plaintext value.

    A stored plaintext this project PUBLISHED never verifies, whatever was
    typed. `user` and `admin` shipped as viewer.password and
    viewer.edition_password in the tracked scoring_config.json for a month, so
    an install that never changed them is guarded by a value anyone can read
    out of the public git history — accepting it would authenticate the whole
    internet. Refusing costs the operator a config edit they have to make
    anyway; the boot log names the key and the fix (see
    :func:`check_legacy_password_warnings`), which is why this returns False
    rather than raising a distinct status the client cannot tell apart from a
    wrong password.

    A HASHED store is checked the same way, against the candidate. Refusing
    only the plaintext branch missed the entire population this exists for:
    on releases before the refusal, `verify_legacy_password` accepted `user`
    and `admin` and :func:`upgrade_legacy_password` rewrote them as `salt:dk`
    on the very first successful login — so an install that used the viewer at
    all now stores a HASH of a published password, and every later login sailed
    past a check that only ever looked at the plaintext branch. Asking the
    question of the candidate after a successful verify is exact: a candidate
    that verifies against the stored hash IS the stored password.

    Someone typing "admin" against a password that genuinely is something else
    must still just fail the ordinary way — which it does, because the burned
    check is reached only once the candidate has already verified.
    """
    if not stored:
        return False
    if _is_hashed(stored):
        if not verify_password(candidate, stored):
            return False
        if is_burned_password(candidate):
            logger.error(
                "Refusing a login against a password this project published in "
                "its own git history. It is stored here as a hash because an "
                "earlier release accepted it and hashed it on login, which "
                "protected nothing — the value is still readable in the public "
                "history. Set a new one in %s and restart.", _CONFIG_PATH,
            )
            return False
        return True
    if is_burned_password(stored):
        logger.error(
            "Refusing a login against a password this project published in its "
            "own git history. Set a new one in %s and restart.", _CONFIG_PATH,
        )
        return False
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

    That backup is BEST-EFFORT, like every other caller's — which is what the
    primitive's own docstring promises, and what this caller alone used not to
    honour. It re-raises any OSError that is not ELOOP, and an unwritable
    config directory is an ordinary supported state: a `:ro` /config mount, an
    NFS root_squash export, a full disk, a stray leftover at the backup name.
    Letting that escape turned a CORRECT password into a 500 while a wrong one
    still answered 401 — a status-code oracle an unauthenticated caller could
    use to confirm the password of a server that would not let them in — and
    locked the operator out of an install whose password was fine. Failing the
    upgrade is the right outcome; failing the LOGIN is not.
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
    # What the operator reads, rather than the raw key. `config_key` is a key
    # NAME, never a secret, but it is also the lookup key into a dict whose
    # values are passwords -- which is enough for CodeQL's
    # py/clear-text-logging-sensitive-data to follow the taint to the key and
    # report all three log calls below as leaking a password (it started once
    # the callers passed VIEWER_PASSWORD_KEY / EDITION_PASSWORD_KEY instead of
    # the bare strings). A label chosen by comparison is a literal, so the
    # question does not arise -- and "viewer password" says more to whoever is
    # reading the log than "password" did.
    label = 'viewer password' if config_key == VIEWER_PASSWORD_KEY else 'edition password'
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
            try:
                write_owner_only_backup(_CONFIG_PATH, f"{_CONFIG_PATH}{_CONFIG_BACKUP_SUFFIX}")
            except OSError:
                logger.exception(
                    "Could not back up %s before upgrading the %s; upgrading anyway",
                    _CONFIG_PATH, label,
                )
            try:
                write_user_config(_CONFIG_PATH, config)
                upgraded = True
            except Exception:
                logger.exception("Failed to upgrade the %s hash", label)
    if upgraded:
        reload_config()
        logger.info("Upgraded the plaintext %s to a PBKDF2 hash", label)


def check_legacy_password_warnings():
    """Log warnings at startup if plaintext passwords are detected.

    A PUBLISHED plaintext is reported separately and as an ERROR, because the
    two say opposite things. "Will be hashed on next successful login" is
    reassuring and, for `user` or `admin`, wrong twice over: there will be no
    successful login (:func:`verify_legacy_password` refuses them), and hashing
    a value out of the public git history would not have protected anything
    anyway. For a STILL-PLAINTEXT store this is the only place the operator is
    told why their password stopped working, so it names the key and the file.

    A store that is already a HASH of a published password gets no line here,
    and deliberately so: proving it would mean holding `user` and `admin` as
    literals to PBKDF2 the stored value against, and not re-committing those
    plaintexts is the whole reason :data:`api.config._BURNED_PASSWORD_DIGESTS`
    keeps digests instead of values. That install is still refused —
    :func:`verify_legacy_password` asks the question of the CANDIDATE once it
    has verified — and the refusal logs an error naming the file at the moment
    the operator actually hits it, which is when they are looking.
    """
    # ``key`` is a config KEY NAME -- the literal 'password' or
    # 'edition_password' -- and it is the only thing these two log lines
    # interpolate from this loop. The password itself is ``value``, which is
    # never logged, in either branch. CodeQL reports both lines as clear-text
    # logging of a secret (alerts 121 and 122) because ``key`` is the lookup key
    # into a dict whose VALUES are passwords, so its taint follows the key
    # rather than the value. Naming the key is the point: it is what tells the
    # operator which of the two settings to change.
    for key in (VIEWER_PASSWORD_KEY, EDITION_PASSWORD_KEY):
        value = VIEWER_CONFIG.get(key, '')
        if not value or _is_hashed(value):
            continue
        if is_burned_password(value):
            logger.error(
                "%s in %s is a password this project shipped in its own tracked "
                "config, so it is readable in the public git history and every "
                "login against it is refused. Set a new one and restart.",
                key, _CONFIG_PATH,
            )
            continue
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

    An open install (no edition password) grants none: it is read-only --
    except to a request ``viewer.trusted_local_editing`` trusts (a direct
    loopback browser on an install with no passwords; see
    ``_trusted_local_editing``). Share-token visitors are excluded.
    """
    if user is None:
        return False
    return user.is_edition
