"""The one static-token contract, shared by every login-less token-gated router.

Facet has two such surfaces — the kiosk / photo-frame endpoints (``frame.tokens``)
and the inbound Immich webhook (``immich.webhook.token_env``) — and they must
answer identically, because each of the three refusals says something different
to the caller:

* **nothing configured ⇒ 404.** An unconfigured feature is indistinguishable
  from one that was never built. A 401 here would confirm the endpoint exists
  and turn "is this install running Facet?" into "now go guess the token".
* **nothing supplied ⇒ 401.** A caller that simply forgot to send it.
* **wrong token ⇒ 403.** Compared constant-time as UTF-8 bytes, so a non-ASCII
  configured secret is a clean rejection instead of the 500 a str-vs-bytes
  ``compare_digest`` raises, and the comparison leaks no length prefix.

Where the two surfaces legitimately differ — where the secret lives, and how a
caller may present it (query param, custom header, ``Authorization: Bearer``) —
stays in the router. Only the verdict is shared.
"""

import hmac

from fastapi import HTTPException, Request

from api.auth import RateLimiter


class TokenFailureLimiter:
    """Rate-limits FAILED static-token attempts per peer IP.

    Static-token surfaces are offline-guessing targets (an operator-chosen
    frame or webhook secret), and unlike a login there is no username to key
    the bucket by. Only failures consume budget: a legitimate kiosk polling
    every photo never throttles itself, while a guesser is held to
    ``max_failures`` per window per peer address.
    """

    def __init__(self, max_failures: int = 10, window_seconds: int = 60):
        self._max = max_failures
        self._window_s = window_seconds
        self._limiter = RateLimiter(max_attempts=max_failures, window_seconds=window_seconds)

    def reset(self) -> None:
        """Drop every recorded failure — the test-isolation seam."""
        self._limiter = RateLimiter(max_attempts=self._max, window_seconds=self._window_s)

    def allowed(self, key: str) -> bool:
        """False when this peer has exhausted its failure budget."""
        return self._limiter.is_allowed(key, register=False)

    precheck = allowed

    def register_failure(self, key: str) -> None:
        self._limiter.is_allowed(key)

    @property
    def window_seconds(self) -> int:
        return self._window_s


def require_static_token_throttled(request: Request, expected, provided, feature: str,
                                   limiter: TokenFailureLimiter) -> None:
    """``require_static_token`` with per-peer-IP failure throttling.

    The 429 pre-check does not consume budget; a 401/403 from the token check
    registers one failure for this peer before propagating.
    """
    client_ip = request.client.host if request.client else "unknown"
    if not limiter.precheck(client_ip):
        raise HTTPException(status_code=429, detail="Too many token failures. Try again later.",
                            headers={"Retry-After": str(limiter.window_seconds)})
    try:
        require_static_token(expected, provided, feature)
    except HTTPException:
        limiter.register_failure(client_ip)
        raise


def require_static_token(expected, provided, feature: str) -> None:
    """Authorize *provided* against *expected*, or raise the right HTTPException.

    *expected* is either one configured secret or a list of them (a frame
    install issues one per device). Blank entries are dropped, so a list of
    empty strings disables the feature exactly like an unset secret — the
    "empty means the whole feature 404s" idiom the shipped config relies on.

    *feature* names the surface in the 404 detail ("Frame feature", "Immich
    webhook"); the 401/403 details are deliberately generic.
    """
    candidates = [expected] if isinstance(expected, str) else list(expected or [])
    candidates = [t for t in candidates if isinstance(t, str) and t]
    if not candidates:
        raise HTTPException(status_code=404, detail=f"{feature} is disabled")
    if not provided:
        raise HTTPException(status_code=401, detail="Token required")
    supplied = provided.encode("utf-8")
    if not any(hmac.compare_digest(t.encode("utf-8"), supplied) for t in candidates):
        raise HTTPException(status_code=403, detail="Invalid token")
