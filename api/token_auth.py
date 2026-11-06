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
import math
import threading
import time
from collections import defaultdict, deque
from typing import Callable

from fastapi import HTTPException, Request

# Only a presented-but-wrong secret is a guess: a 401 (nothing supplied) is a caller that
# forgot it, and a 404 (feature disabled) involves no secret at all.
_GUESS_STATUS = 403


class TokenFailureLimiter:
    """Counts FAILED credential attempts per peer address over a sliding window.

    Long-lived operator-chosen secrets (frame tokens, the Immich webhook secret,
    the WebDAV password, assistant bearer tokens) are offline-guessing targets,
    and unlike a login there is no username to key the bucket by. Only failures
    consume budget, so a legitimate kiosk polling every photo never throttles
    itself. Per process: with several uvicorn workers each holds its own budget.

    Past ``sweep_threshold`` tracked addresses a failure sweeps the expired ones,
    at most once per window, so an attacker rotating source addresses can neither
    grow the map without bound nor make every failure scan it. The clock is
    injectable so tests never sleep.
    """

    def __init__(self, max_failures: int = 10, window_seconds: float = 60,
                 sweep_threshold: int = 10000, clock: Callable[[], float] = time.monotonic):
        self._max = max_failures
        self._window = window_seconds
        self._sweep_threshold = sweep_threshold
        self._clock = clock
        self._lock = threading.Lock()
        self._failures: dict[str, deque] = defaultdict(deque)
        self._last_sweep = float("-inf")

    @property
    def retry_after(self) -> str:
        """The ``Retry-After`` value for a 429: the window, in whole seconds."""
        return str(math.ceil(self._window))

    def reset(self) -> None:
        """Drop every recorded failure (test isolation)."""
        with self._lock:
            self._failures.clear()
            self._last_sweep = float("-inf")

    def blocked(self, key: str) -> bool:
        """True once ``key`` has failed ``max_failures`` times within the window."""
        current = self._clock()
        with self._lock:
            window = self._failures.get(key)
            if window is None:
                return False
            while window and window[0] <= current - self._window:
                window.popleft()
            if not window:
                del self._failures[key]
                return False
            return len(window) >= self._max

    def register_failure(self, key: str) -> None:
        current = self._clock()
        with self._lock:
            if len(self._failures) > self._sweep_threshold and current - self._last_sweep >= self._window:
                self._last_sweep = current
                for stale in [k for k, window in self._failures.items()
                              if not window or window[-1] <= current - self._window]:
                    del self._failures[stale]
            self._failures[key].append(current)

    def too_many(self) -> HTTPException:
        return HTTPException(status_code=429, detail="Too many authentication failures. Try again later.",
                             headers={"Retry-After": self.retry_after})


def require_static_token_throttled(request: Request, expected, provided, feature: str,
                                   limiter: TokenFailureLimiter) -> None:
    """``require_static_token`` with per-peer-IP failure throttling.

    A disabled feature answers 404 whatever the budget, and never consumes it, so the
    "disabled feature is indistinguishable from an unbuilt one" posture survives a
    blocked peer. Otherwise a blocked peer gets 429 before any comparison runs, and a
    wrong token (403) registers one failure before propagating.
    """
    client_ip = request.client.host if request.client else "unknown"
    if _configured_tokens(expected) and limiter.blocked(client_ip):
        raise limiter.too_many()
    try:
        require_static_token(expected, provided, feature)
    except HTTPException as ex:
        if ex.status_code == _GUESS_STATUS:
            limiter.register_failure(client_ip)
        raise


def _configured_tokens(expected) -> list[str]:
    """The non-blank configured secrets; empty means the feature is disabled."""
    candidates = [expected] if isinstance(expected, str) else list(expected or [])
    return [t for t in candidates if isinstance(t, str) and t]


def require_static_token(expected, provided, feature: str) -> None:
    """Authorize *provided* against *expected*, or raise the right HTTPException.

    *expected* is either one configured secret or a list of them (a frame
    install issues one per device). Blank entries are dropped, so a list of
    empty strings disables the feature exactly like an unset secret — the
    "empty means the whole feature 404s" idiom the shipped config relies on.

    *feature* names the surface in the 404 detail ("Frame feature", "Immich
    webhook"); the 401/403 details are deliberately generic.
    """
    candidates = _configured_tokens(expected)
    if not candidates:
        raise HTTPException(status_code=404, detail=f"{feature} is disabled")
    if not provided:
        raise HTTPException(status_code=401, detail="Token required")
    supplied = provided.encode("utf-8")
    if not any(hmac.compare_digest(t.encode("utf-8"), supplied) for t in candidates):
        raise HTTPException(status_code=403, detail="Invalid token")
