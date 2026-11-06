"""Rate limits and response caps for the agent surface.

In-memory and per process, like ``api.auth._login_limiter``. The clock is
injectable so the tests never sleep.
"""

import copy
import json
import threading
import time
from collections import defaultdict, deque
from typing import Callable, Optional

from api.token_auth import TokenFailureLimiter

WINDOW_SECONDS = 60.0
FAILED_AUTH_MAX = 10
# Past this many tracked addresses a failure sweeps the ones whose window has expired
# (at most once per window), so an attacker rotating source addresses cannot grow the
# map without bound nor make every failure scan it.
FAILURE_SWEEP_THRESHOLD = 10000

_clock: Callable[[], float] = time.monotonic
_lock = threading.Lock()
_calls: dict[tuple[int | str, bool], deque] = defaultdict(deque)
_auth_failures = TokenFailureLimiter(FAILED_AUTH_MAX, WINDOW_SECONDS,
                                     sweep_threshold=FAILURE_SWEEP_THRESHOLD, clock=lambda: now())


def set_clock(clock: Optional[Callable[[], float]]) -> None:
    """Replace the monotonic clock (tests); ``None`` restores the real one."""
    global _clock
    _clock = clock or time.monotonic


def now() -> float:
    return _clock()


def reset_limits() -> None:
    from api.agent import nonce
    with _lock:
        _calls.clear()
    _auth_failures.reset()
    nonce.reset()


def check_rate(rate_key: int | str, write: bool, per_min: int) -> tuple[bool, float]:
    """Record one call for ``rate_key`` (a token id, or ``inpage:<principal>``); return ``(allowed, retry_after_s)``.

    Reads and writes keep separate windows, so a burst of searches cannot starve
    the (much smaller) write budget, and the other way round.
    """
    current = now()
    with _lock:
        window = _calls[(rate_key, write)]
        while window and window[0] <= current - WINDOW_SECONDS:
            window.popleft()
        if len(window) >= per_min:
            return False, max(1.0, round(window[0] + WINDOW_SECONDS - current, 1))
        window.append(current)
        return True, 0.0


def auth_blocked(client_ip: str) -> bool:
    """True once ``client_ip`` has failed bearer authentication too often."""
    return _auth_failures.blocked(client_ip)


def record_auth_failure(client_ip: str) -> None:
    _auth_failures.register_failure(client_ip)


def encoded_size(envelope: dict) -> int:
    return len(json.dumps(envelope, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8"))


def fit_envelope(envelope: dict, max_rows: int, max_bytes: int) -> dict:
    """Cap a result envelope at ``max_rows`` rows and ``max_bytes`` serialized bytes.

    Tail rows are dropped (never the middle of a row), ``truncated: true`` is set,
    and the output stays valid JSON. ``total`` is left alone so the caller still
    learns how many rows exist, and ``returned`` says how many came back. An envelope without a ``data.rows`` list that is
    over the byte cap becomes a ``too_large`` error rather than being cut mid-text.
    """
    data = envelope.get("data")
    rows = data.get("rows") if isinstance(data, dict) else None
    if not isinstance(data, dict) or not isinstance(rows, list):
        if encoded_size(envelope) <= max_bytes:
            return envelope
        return {"ok": False, "error": "too_large",
                "message": "The result exceeds the byte cap; narrow the request."}
    if len(rows) <= max_rows and encoded_size(envelope) <= max_bytes:
        return envelope
    capped = copy.copy(envelope)
    capped["data"] = dict(data)
    capped["data"]["rows"] = rows[:max_rows]
    capped["truncated"] = True
    while capped["data"]["rows"] and encoded_size(capped) > max_bytes:
        kept = capped["data"]["rows"]
        capped["data"]["rows"] = kept[:len(kept) // 2 if len(kept) > 8 else len(kept) - 1]
    returned = len(capped["data"]["rows"])
    capped["returned"] = returned
    # Where to resume: a paged tool re-asks with a page size the cap allows, an offset tool
    # continues after the last row it returned.
    if isinstance(data.get("offset"), int):
        capped["next_offset"] = data["offset"] + returned
    page, per_page = data.get("page"), data.get("per_page")
    if isinstance(page, int) and isinstance(per_page, int) and returned:
        resume = (page - 1) * per_page + returned
        capped["suggested_per_page"] = returned
        # Pages of ``returned`` rows express the resume point only when it falls on a page
        # boundary; otherwise a row offset is all that is exact.
        if resume % returned == 0:
            capped["next_page"] = resume // returned + 1
        else:
            capped["next_offset"] = resume
    return capped
