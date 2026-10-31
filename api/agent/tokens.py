"""Agent bearer tokens: mint, verify, list, revoke, and per-call level resolution.

A token is ``fct_`` + 256 bits from the CSPRNG; only its SHA-256 and a short
display prefix are stored (``mcp_tokens``, a side table). Tokens never expire but
are revocable, and they are bound to the credentials of their owner at mint time:

* multi-user -- ``user_gen`` digests the user's ``password_hash`` (the role is live);
* single password -- ``user_gen`` is the viewer-password generation and
  ``edition_gen`` the edition-password generation (``api.auth.password_generation``);
* open install -- the principal is the fixed ``_anonymous`` and the token is read-only, with two
  exceptions, both for a /mcp request that passed the same-machine boundary (set by
  :func:`verify_request` from the request itself):

  - under ``viewer.trusted_local_editing`` (no password at all) an ``edition`` token resolves to
    ``edition`` (``TokenGrant.trusted_local``). Any password lowers it again, and clearing the
    password revives it;
  - with ``viewer.edition_password`` set, an ``edition`` token minted from an edition session
    resolves to ``edition`` (``TokenGrant.local``) while that password is unchanged: ``edition_gen``
    is checked as on a single password. The token is a bearer secret on an install anyone can read,
    so the locality check is what keeps a LAN or proxied caller at ``readonly``.

``TokenGrant.resolve`` re-derives the EFFECTIVE level on EVERY call as
``min(token.level, live level)``. The internal JWT is minted fresh with CURRENT
generation claims, so without this comparison a rotated password would silently
re-bless an old token.
"""

import hashlib
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Optional

from api.auth import (
    EDITION_PASSWORD_KEY, CurrentUser, VIEWER_PASSWORD_KEY, _is_open_install, _trusted_local_editing_enabled,
    password_generation, request_is_local_for, trusted_local_for,
)
from api.config import config_load_failed, get_user_config, is_multi_user_enabled
from api.database import get_db
from api.db_helpers import retry_on_locked

TOKEN_PREFIX = "fct_"
DISPLAY_PREFIX_LENGTH = 12
MAX_TOKEN_LENGTH = 200
MAX_LIVE_TOKENS_PER_USER = 20
TOUCH_INTERVAL_SECONDS = 60.0
LEVELS = ("readonly", "user", "edition")
OPEN_PRINCIPAL = "_anonymous"
LEGACY_PRINCIPAL = "_legacy"
GENERATION_LENGTH = 16

PUBLIC_COLUMNS = ("id", "user_id", "name", "token_prefix", "level", "created_at",
                  "last_used_at", "revoked", "revoked_at")

_last_touched: dict[int, float] = {}
_touch_lock = threading.Lock()


def level_rank(level: str) -> int:
    return LEVELS.index(level)


def effective_requirement(min_level: str) -> str:
    """The level a caller really needs for a tool declared at ``min_level``.

    ``user`` is a multi-user rung: single-password mode has no middle rung (the rating
    routes demand edition there), so the honest requirement is ``edition``.
    """
    return "edition" if min_level == "user" and install_mode() != "multi" else min_level


def _lower(a: str, b: str) -> str:
    return a if level_rank(a) <= level_rank(b) else b


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hash(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def install_mode() -> str:
    """``multi`` | ``legacy`` | ``open`` | ``unreadable`` (config failed to parse)."""
    if config_load_failed():
        return "unreadable"
    if is_multi_user_enabled():
        return "multi"
    if _is_open_install(VIEWER_PASSWORD_KEY):
        return "open"
    return "legacy"


def session_principal(user_id: Optional[str]) -> str:
    """The identity a session (and so a token or a bridge tab) is bound to.

    The account in multi-user mode, the shared ``_legacy`` principal on a single
    password, and the fixed ``_anonymous`` on an open install.
    """
    mode = install_mode()
    if mode == "multi":
        return user_id or ""
    return LEGACY_PRINCIPAL if mode == "legacy" else OPEN_PRINCIPAL


def session_level(user: CurrentUser) -> str:
    """``edition`` for a session holding edition rights, else ``readonly``."""
    return "edition" if user.is_edition else "readonly"


def user_generation(user: dict) -> str:
    """Digest of the stored password hash: a changed password kills the token.

    The role is deliberately NOT in it. It is re-read live on every call
    (``_resolve_multi``), so a demotion LOWERS an edition token to ``user`` instead
    of killing it, and a promotion can never raise one past its minted level.
    """
    return hashlib.sha256(str(user.get("password_hash", "")).encode("utf-8")).hexdigest()[:GENERATION_LENGTH]


def snapshot(principal: str) -> tuple[str, str]:
    """``(user_gen, edition_gen)`` for ``principal`` against the live config."""
    mode = install_mode()
    if mode == "multi":
        user = get_user_config(principal)
        if user is None:
            raise ValueError(f"unknown user {principal!r}")
        return user_generation(user), ""
    # An open install pins the edition password too: an edition token minted there under one dies
    # with it (see TokenGrant.resolve).
    return password_generation(VIEWER_PASSWORD_KEY), password_generation(EDITION_PASSWORD_KEY)


def _public(row: sqlite3.Row) -> dict:
    return {column: row[column] for column in PUBLIC_COLUMNS}


def bearer_token(headers: Any) -> Optional[str]:
    """The ``fct_`` secret from an ``Authorization: Bearer`` header, else None."""
    value = (headers or {}).get("authorization") if headers is not None else None
    if not isinstance(value, str):
        return None
    scheme, _, secret = value.partition(" ")
    return secret.strip() if scheme.lower() == "bearer" and secret.strip() else None


class TokenLimitReached(Exception):
    """The principal already holds ``max_live`` live tokens."""


@retry_on_locked()
def mint(principal: str, name: str, level: str, minted_level: str = "readonly",
         max_live: Optional[int] = None) -> tuple[dict, str]:
    """Create a token; return ``(public row, plaintext)``. The plaintext is never stored.

    ``minted_level`` is the level of the minting session; single-password routing caps a
    token's tab reach with it. ``max_live`` is enforced inside the INSERT (the count and the
    insert are one statement under the write lock), so concurrent mints cannot overshoot it;
    :class:`TokenLimitReached` when it is already held.
    """
    plaintext = TOKEN_PREFIX + secrets.token_urlsafe(32)
    user_gen, edition_gen = snapshot(principal)
    cap = -1 if max_live is None else max_live
    with get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO mcp_tokens (user_id, name, token_prefix, token_hash, level, user_gen, "
            "edition_gen, created_at, minted_level) SELECT ?, ?, ?, ?, ?, ?, ?, ?, ? "
            "WHERE ? < 0 OR (SELECT COUNT(*) FROM mcp_tokens WHERE user_id = ? AND revoked = 0) < ?",
            (principal, name, plaintext[:DISPLAY_PREFIX_LENGTH], _hash(plaintext), level,
             user_gen, edition_gen, _now_iso(), minted_level, cap, principal, cap))
        if cursor.rowcount == 0:
            conn.rollback()
            raise TokenLimitReached(principal)
        conn.commit()
        row = conn.execute("SELECT * FROM mcp_tokens WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return _public(row), plaintext


def verify(plaintext: Optional[str]) -> Optional["TokenGrant"]:
    """The grant behind ``plaintext``, or None when unknown, malformed or revoked.

    Liveness against the owner's credentials is NOT decided here -- that is
    :meth:`TokenGrant.resolve`, which runs on every call. The grant is never local or trusted-local:
    only :func:`verify_request` sets those facts, from the request itself.
    """
    if not isinstance(plaintext, str) or not plaintext.startswith(TOKEN_PREFIX) \
            or len(plaintext) > MAX_TOKEN_LENGTH:
        return None
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, user_id, name, level, user_gen, edition_gen, minted_level FROM mcp_tokens "
            "WHERE token_hash = ? AND revoked = 0", (_hash(plaintext),)).fetchone()
    if row is None:
        return None
    return TokenGrant(row["id"], row["user_id"], row["name"], row["level"],
                      row["user_gen"], row["edition_gen"], row["minted_level"] or row["level"])


def verify_request(plaintext: Optional[str], request: Any) -> Optional["TokenGrant"]:
    """:func:`verify`, with ``local`` and ``trusted_local`` derived from the /mcp ``request`` itself (a Request or a WebSocket)."""
    grant = verify(plaintext)
    return None if grant is None else replace(grant, local=request_is_local_for(request),
                                              trusted_local=trusted_local_for(request))


def list_tokens(user_id: Optional[str] = None) -> list[dict]:
    """Token metadata (never the hash), newest first; ``user_id=None`` lists every owner's."""
    sql = "SELECT * FROM mcp_tokens"
    params: tuple = ()
    if user_id is not None:
        sql += " WHERE user_id = ?"
        params = (user_id,)
    with get_db() as conn:
        return [_public(r) for r in conn.execute(sql + " ORDER BY id DESC", params)]


@retry_on_locked()
def revoke(token_id: int, user_id: Optional[str] = None) -> bool:
    """Revoke a live token (only ``user_id``'s when given). False when nothing changed."""
    sql = "UPDATE mcp_tokens SET revoked = 1, revoked_at = ? WHERE id = ? AND revoked = 0"
    params: list = [_now_iso(), token_id]
    if user_id is not None:
        sql += " AND user_id = ?"
        params.append(user_id)
    with get_db() as conn:
        changed = conn.execute(sql, params).rowcount > 0
        conn.commit()
        return changed


@retry_on_locked()
def touch(token_id: int) -> None:
    """Stamp ``last_used_at``, at most once per minute per token."""
    current = time.monotonic()
    with _touch_lock:
        if current - _last_touched.get(token_id, -TOUCH_INTERVAL_SECONDS) < TOUCH_INTERVAL_SECONDS:
            return
        _last_touched[token_id] = current
    with get_db() as conn:
        conn.execute("UPDATE mcp_tokens SET last_used_at = ? WHERE id = ?", (_now_iso(), token_id))
        conn.commit()


@dataclass(frozen=True)
class ResolvedGrant:
    """What a token may do RIGHT NOW."""

    token_id: Optional[int]
    principal: str
    level: str
    role: str
    display_name: str
    anonymous: bool
    minted_level: Optional[str] = None
    # A logged-in human acting through the layer (the in-page agent): no token row behind it.
    inpage: bool = False
    # The calling tab's own selection (``ui_get_selection`` data), sent with an in-page call.
    selection_snapshot: Optional[dict] = None
    # An open-install grant whose /mcp request passed the trusted-local boundary (see TokenGrant.resolve).
    trusted_local: bool = False
    # An open-install edition grant held through ``viewer.edition_password`` from a local /mcp request.
    # Unlike ``trusted_local`` it waives nothing (scanning still needs show_scan_button).
    local_edition: bool = False

    def jwt_claims(self) -> Optional[dict]:
        """Claims for the 60-second internal JWT, or None on an open install.

        The open-install exception is a local Full-editing grant. With ``local_edition`` the JWT
        carries the edition claim under the edition browser session's own ``sub`` (``_legacy``), so
        owner-keyed state (the undo history, sidecar jobs) is shared with the user's edition session;
        ``CurrentUser.is_edition`` honours the claim only while an edition password backs it (and
        ``create_access_token`` pins its generation), exactly as for that session. Under the opt-in (``trusted_local``) it signs NO ``sub`` (the
        open-install browser's own identity is ``user_id=None``; PyJWT refuses a null ``sub``, and an
        undecodable bearer would fall through to the anonymous human path) plus ``mcp_local``, the only way a request-derived trust
        reaches an agent JWT (see ``CurrentUser.from_payload``).

        Role and ``edition`` MATCH the effective level: ``CurrentUser.is_edition``
        is derived from the ROLE, so a read-only token of an admin must not carry
        ``admin`` through, or it would reach edition routes on the role alone.
        """
        if self.anonymous:
            if self.level == "edition" and self.trusted_local:
                return {"role": self.role, "display_name": "", "edition": True, "mcp": True,
                        "mcp_local": True, "mcp_token_id": self.token_id}
            if self.level == "edition" and self.local_edition:
                return {"sub": LEGACY_PRINCIPAL, "role": self.role, "display_name": "", "edition": True,
                        "mcp": True, "mcp_token_id": self.token_id}
            return None
        return {
            "sub": self.principal,
            "role": self.role,
            "display_name": self.display_name,
            "edition": self.level == "edition",
            "mcp": True,
            "mcp_token_id": self.token_id,
        }


@dataclass(frozen=True)
class SessionGrant:
    """A logged-in human acting through the agent layer (the in-page agent).

    The in-page twin of :class:`TokenGrant`, duck-typed the same way for the tool wrapper and
    ``InternalClient``. There is no token row: ``level`` is the level the session's own JWT carries
    and :meth:`resolve` lowers it to what the account holds RIGHT NOW, on every call, so a demotion
    or a rotated password cuts the very next call and a session can never exceed its own JWT.
    ``id`` is the rate-limit key (per user: more tabs cannot multiply the budget); ``nonce_owner``
    adds the tab's session id, so one tab's confirmation cannot be spent by another.
    """

    user_id: Optional[str]
    principal: str
    level: str
    role: str
    display_name: str
    user_gen: str
    edition_gen: str
    session_id: Optional[str] = None
    selection_snapshot: Optional[dict] = None

    @property
    def id(self) -> str:
        return f"inpage:{self.principal}"

    @property
    def rate_key(self) -> str:
        return self.id

    @property
    def nonce_owner(self) -> str:
        return f"{self.id}:{self.session_id}" if self.session_id else self.id

    @property
    def token_id(self) -> Optional[int]:
        return None

    def with_call(self, session_id: Optional[str], selection_snapshot: Optional[dict]) -> "SessionGrant":
        """This grant scoped to one tab's call."""
        return replace(self, session_id=session_id, selection_snapshot=selection_snapshot)

    def resolve(self) -> Optional[ResolvedGrant]:
        """The level the session holds against the live config, or None when it no longer exists."""
        mode = install_mode()
        if mode == "unreadable":
            return None
        if mode == "multi":
            user = get_user_config(self.user_id or "")
            if user is None:
                return None
            role = user.get("role", "user")
            level = _lower(self.level, "edition" if role in ("admin", "superadmin") else "user")
            return ResolvedGrant(None, self.principal, level, role if level == "edition" else "user",
                                 user.get("display_name", self.user_id), False, level, True,
                                 self.selection_snapshot)
        if self.user_gen != password_generation(VIEWER_PASSWORD_KEY):
            return None
        level = _legacy_level(self.level, self.edition_gen)
        return ResolvedGrant(None, self.principal, level, "user", "", mode == "open" and level == "readonly",
                             level, True, self.selection_snapshot)


def _legacy_level(level: str, edition_gen: str) -> str:
    """Single-password mode has no middle rung (the rating routes demand edition): ``edition`` only
    while the edition password is still set and unrotated since the grant was minted, else ``readonly``."""
    edition_live = (
        level == "edition"
        and not _is_open_install(EDITION_PASSWORD_KEY)
        and edition_gen == password_generation(EDITION_PASSWORD_KEY)
    )
    return "edition" if edition_live else "readonly"


def session_grant(user: CurrentUser, claims: Optional[dict] = None) -> Optional[SessionGrant]:
    """The grant for ``user``'s own session, or None when it cannot exist (unreadable config,
    deleted account). ``claims`` are the session JWT's decoded payload: they pin the password
    generations the session was minted under.
    """
    mode = install_mode()
    if mode == "unreadable" or (mode == "multi" and get_user_config(user.user_id or "") is None):
        return None
    level = session_level(user)
    if level == "readonly" and mode == "multi":
        level = "user"
    claims = claims or {}
    return SessionGrant(
        user.user_id, session_principal(user.user_id), level, getattr(user, "role", "user") or "user",
        getattr(user, "display_name", "") or "",
        claims.get("pv") or password_generation(VIEWER_PASSWORD_KEY),
        claims.get("ev") or password_generation(EDITION_PASSWORD_KEY))


@dataclass(frozen=True)
class TokenGrant:
    id: int
    user_id: str
    name: str
    level: str
    user_gen: str
    edition_gen: str
    minted_level: str = "readonly"
    # The /mcp request presenting this token passed the same-machine boundary (``request_is_local``).
    local: bool = False
    # ... and ``viewer.trusted_local_editing`` was on for it. Both default False: fail closed.
    trusted_local: bool = False

    @property
    def rate_key(self) -> int:
        return self.id

    @property
    def nonce_owner(self) -> int:
        return self.id

    @property
    def token_id(self) -> int:
        return self.id

    @property
    def session_id(self) -> Optional[str]:
        return None

    def resolve(self) -> Optional[ResolvedGrant]:
        """Effective grant against the live config, or None when the token is dead."""
        mode = install_mode()
        if mode == "unreadable":
            return None
        if mode == "multi":
            return self._resolve_multi()
        if self.user_id not in (LEGACY_PRINCIPAL, OPEN_PRINCIPAL):
            return None
        if self.user_gen != password_generation(VIEWER_PASSWORD_KEY):
            return None
        if mode == "open":
            if self.user_id != OPEN_PRINCIPAL:
                return None
            if self.trusted_local and _trusted_local_editing_enabled():
                # A local process is as trusted as the local browser: its reach ceiling is edition whatever
                # the row was minted at. A non-local grant keeps the readonly ceiling below.
                return ResolvedGrant(self.id, OPEN_PRINCIPAL, "edition" if self.level == "edition" else "readonly",
                                     "user", "", True, "edition", trusted_local=True)
            if self.local and _legacy_level(self.level, self.edition_gen) == "edition":
                return ResolvedGrant(self.id, OPEN_PRINCIPAL, "edition", "user", "", True, "edition",
                                     local_edition=True)
            return ResolvedGrant(self.id, OPEN_PRINCIPAL, "readonly", "user", "", True, "readonly")
        if self.user_id != LEGACY_PRINCIPAL:
            return None
        level = _legacy_level(self.level, self.edition_gen)
        return ResolvedGrant(self.id, LEGACY_PRINCIPAL, level, "user", "", False, self.minted_level)

    def _resolve_multi(self) -> Optional[ResolvedGrant]:
        user = get_user_config(self.user_id)
        if user is None or self.user_gen != user_generation(user):
            return None
        role = user.get("role", "user")
        live = "edition" if role in ("admin", "superadmin") else "user"
        level = _lower(self.level, live)
        return ResolvedGrant(
            self.id, self.user_id, level, role if level == "edition" else "user",
            user.get("display_name", self.user_id), False)
