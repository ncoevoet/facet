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

from fastapi import HTTPException


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
