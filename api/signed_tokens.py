"""Domain-separated HMAC signing for preview tokens and stateless references.

Every caller passes its own domain prefix, so a signature minted for one purpose
never verifies for another. A token is ``base64url(payload, unpadded) + '.' +
hex HMAC-SHA256(secret, domain + payload)``; it is never a viewer authentication
token. Claim layout and expiry stay with each caller: this module only signs and
authenticates bytes.
"""

import base64
import hashlib
import hmac
import json

from api import config


def secret():
    """``config.JWT_SECRET`` as bytes, read per call so a rotated secret applies at once."""
    value = config.JWT_SECRET
    return value.encode('utf-8') if isinstance(value, str) else value


def canonical_json(value, *, ensure_ascii=True, allow_nan=True):
    """Sorted-key, separator-free UTF-8 JSON: the exact bytes a caller signs or hashes."""
    return json.dumps(value, sort_keys=True, ensure_ascii=ensure_ascii, separators=(',', ':'),
                      allow_nan=allow_nan).encode('utf-8')


def sign(domain, payload):
    """Hex HMAC-SHA256 of ``domain + payload`` under the current secret."""
    return hmac.new(secret(), domain + payload, hashlib.sha256).hexdigest()


def issue(domain, payload):
    """A preview token carrying ``payload`` bytes, signed under ``domain``."""
    return base64.urlsafe_b64encode(payload).decode('ascii').rstrip('=') + '.' + sign(domain, payload)


def verify(domain, token, *, strict_base64=False):
    """The JSON claims of an authentic ``issue`` token; raises ``ValueError`` or ``TypeError`` otherwise.

    ``strict_base64`` rejects any character outside the URL-safe alphabet; the lenient
    default discards them before decoding, as ``base64.urlsafe_b64decode`` does. Either way
    the signature is checked over the decoded bytes, so a discarded character cannot forge.
    """
    encoded, signature = token.split('.')
    padded = encoded + '=' * (-len(encoded) % 4)
    payload = (base64.b64decode(padded, altchars=b'-_', validate=True) if strict_base64
               else base64.urlsafe_b64decode(padded))
    if not hmac.compare_digest(signature, sign(domain, payload)):
        raise ValueError('invalid signature')
    return json.loads(payload)
