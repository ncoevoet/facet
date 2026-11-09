"""Resolve a Google Maps short link (``maps.app.goo.gl``, ``goo.gl/maps``) to coordinates.

The browser cannot follow these itself (no CORS on the redirect), so the
viewer does it, under SSRF rules tighter than the webhook ones:

* only ``https`` to a host in ``ALLOWED_HOSTS`` is ever requested: any other
  host, a port, or credentials in the URL ends the walk before a request;
* every address the host resolves to must be globally routable (the webhook
  guard's rule, IPv4-in-IPv6 unwrapped), and the socket connects to the address
  that was checked, with TLS verified against the hostname, so DNS cannot be
  rebound between the check and the connection;
* at most ``MAX_HOPS`` requests within one ``TIMEOUT_SECONDS`` deadline; only the
  status line and headers are read, never the body;
* each URL is parsed for coordinates before it is fetched, so a redirect whose
  ``Location`` already carries the point is never requested.

Nothing about the link is logged.
"""
import http.client
import ipaddress
import socket
import ssl
import time
from urllib.parse import urljoin, urlsplit

from plugins import _embedded_ipv4_unwrapped
from utils import google_maps_link

ALLOWED_HOSTS = frozenset({'maps.app.goo.gl', 'goo.gl', 'maps.google.com', 'www.google.com', 'google.com'})
MAX_HOPS = 5
TIMEOUT_SECONDS = 5.0
_MAX_LOCATION = 4096
_REDIRECTS = {301, 302, 303, 307, 308}
_USER_AGENT = 'Mozilla/5.0 (compatible; Facet place link resolver)'


class LinkError(Exception):
    """A link that cannot be turned into coordinates; ``code`` is the 422 detail."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def is_resolvable(url: str) -> bool:
    """An http(s) URL on an allowed host, without credentials or a port."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    return (parts.scheme in ('http', 'https') and (parts.hostname or '') in ALLOWED_HOSTS
            and parts.username is None and parts.password is None and port in (None, 443))


def public_address(host: str) -> str:
    """The first resolved address of *host*, refusing it if ANY address is not public."""
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise LinkError('unreachable') from exc
    chosen = None
    for info in infos:
        addr = ipaddress.ip_address(info[4][0])
        effective = _embedded_ipv4_unwrapped(addr)
        if not effective.is_global or effective.is_multicast:
            raise LinkError('unsupported_host')
        chosen = chosen or str(addr)
    if chosen is None:
        raise LinkError('unreachable')
    return chosen


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connect to the address that passed ``public_address``; verify TLS for the hostname."""

    def __init__(self, host: str, address: str, timeout: float):
        super().__init__(host, 443, timeout=timeout, context=ssl.create_default_context())
        self._address = address

    def connect(self) -> None:
        raw = socket.create_connection((self._address, 443), timeout=self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def fetch_location(url: str, timeout: float) -> tuple[int, str | None]:
    """One GET of an allowed URL: ``(status, Location header)``; the body is never read."""
    parts = urlsplit(url)
    host = parts.hostname or ''
    address = public_address(host)
    conn = _PinnedHTTPSConnection(host, address, timeout)
    try:
        target = (parts.path or '/') + (f'?{parts.query}' if parts.query else '')
        conn.request('GET', target, headers={'User-Agent': _USER_AGENT, 'Accept': 'text/html'})
        response = conn.getresponse()
        return response.status, response.getheader('Location')
    finally:
        conn.close()


def resolve(url: str) -> tuple[float, float]:
    """Coordinates the link opens on, following allowed redirects only."""
    if not isinstance(url, str) or len(url) > google_maps_link.MAX_INPUT:
        raise LinkError('invalid_link')
    current = url.strip()
    deadline = time.monotonic() + TIMEOUT_SECONDS
    for _ in range(MAX_HOPS):
        pair = google_maps_link.parse_url(current)
        if pair:
            return pair
        if not is_resolvable(current):
            raise LinkError('unsupported_host')
        # Every allowed host serves https; a pasted http:// link is never fetched in clear.
        target = 'https://' + current.split('://', 1)[1]
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise LinkError('unreachable')
        try:
            status, location = fetch_location(target, remaining)
        except LinkError:
            raise
        except (OSError, http.client.HTTPException, ValueError) as exc:
            raise LinkError('unreachable') from exc
        if status not in _REDIRECTS or not location or len(location) > _MAX_LOCATION:
            raise LinkError('no_coordinates')
        current = urljoin(target, location)
    pair = google_maps_link.parse_url(current)
    if pair:
        return pair
    raise LinkError('too_many_redirects')
