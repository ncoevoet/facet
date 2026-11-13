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
import re
import socket
import ssl
import threading
import time
from urllib.parse import urljoin, urlsplit, urlunsplit

from plugins import _first_public_address
from utils import google_maps_link

ALLOWED_HOSTS = frozenset({'maps.app.goo.gl', 'goo.gl', 'maps.google.com', 'www.google.com', 'google.com'})
MAX_HOPS = 5
TIMEOUT_SECONDS = 5.0
_MAX_LOCATION = google_maps_link.MAX_INPUT
_REDIRECTS = {301, 302, 303, 307, 308}
_USER_AGENT = 'Mozilla/5.0 (compatible; Facet place link resolver)'
# urlsplit silently drops tab/CR/LF, so the parsed host can differ from the raw
# string's: a link carrying one is refused outright rather than parsed.
_CONTROL = re.compile(r'[\x00-\x1f\x7f]')
_UNSAFE = re.compile(r'[\x00-\x20\x7f]')


class LinkError(Exception):
    """A link that cannot be turned into coordinates; ``code`` is the 422 detail."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def is_resolvable(url: str) -> bool:
    """An http(s) URL on an allowed host, without credentials, a port, whitespace or controls."""
    if _UNSAFE.search(url):
        return False
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    return (parts.scheme in ('http', 'https') and (parts.hostname or '') in ALLOWED_HOSTS
            and parts.username is None and parts.password is None and port in (None, 443))


def public_address(host: str, timeout: float = TIMEOUT_SECONDS) -> str:
    """The first resolved address of *host*, refusing it if ANY address is not public.

    Native DNS cannot be interrupted, so the lookup runs on a daemon thread that is
    abandoned at *timeout*; it ends when the system resolver gives up.
    """
    result: dict = {}

    def lookup() -> None:
        try:
            result['infos'] = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        except OSError:
            pass
    worker = threading.Thread(target=lookup, name='facet-maps-link-dns', daemon=True)
    worker.start()
    worker.join(timeout)
    if 'infos' not in result:
        raise LinkError('unreachable')
    try:
        chosen = _first_public_address(result['infos'])
    except ValueError as exc:
        raise LinkError('unsupported_host') from exc
    if chosen is None:
        raise LinkError('unreachable')
    return chosen


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connect to the address that passed ``public_address``; verify TLS for the hostname.

    A socket timeout restarts on every byte, so a server trickling header lines
    could hold a request open indefinitely; ``expire`` (run by a watchdog at the
    deadline) shuts the active socket down instead.
    """

    def __init__(self, host: str, address: str, timeout: float):
        self._tls = ssl.create_default_context()
        super().__init__(host, 443, timeout=timeout, context=self._tls)
        self._address = address
        self._socket_lock = threading.Lock()
        self._active: socket.socket | None = None
        self.expired = False

    def expire(self) -> None:
        with self._socket_lock:
            self.expired = True
            active = self._active
        if active is not None:
            # close() alone need not wake a thread blocked in recv; shutdown() does.
            try:
                active.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            active.close()

    def _track(self, sock: socket.socket) -> None:
        with self._socket_lock:
            if self.expired:
                raise TimeoutError
            self._active = sock

    def connect(self) -> None:
        raw = socket.create_connection((self._address, 443), timeout=self.timeout)
        try:
            self._track(raw)
            self.sock = self._tls.wrap_socket(raw, server_hostname=self.host)
            self._track(self.sock)
        except BaseException:
            raw.close()
            raise

    def finish(self) -> None:
        self.close()
        with self._socket_lock:
            active, self._active = self._active, None
        if active is not None:
            active.close()


def fetch_location(url: str, timeout: float) -> tuple[int, str | None]:
    """One GET of an allowed URL within *timeout*: ``(status, Location header)``; the body is never read."""
    deadline = time.monotonic() + timeout
    parts = urlsplit(url)
    host = parts.hostname or ''
    address = public_address(host, timeout)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError
    conn = _PinnedHTTPSConnection(host, address, remaining)
    watchdog = threading.Timer(remaining, conn.expire)
    watchdog.name = 'facet-maps-link-deadline'
    watchdog.daemon = True
    watchdog.start()
    try:
        target = (parts.path or '/') + (f'?{parts.query}' if parts.query else '')
        conn.request('GET', target, headers={'User-Agent': _USER_AGENT, 'Accept': 'text/html'})
        response = conn.getresponse()
        status, location = response.status, response.getheader('Location')
        # A shut-down socket reads as end of headers, not as an error.
        if conn.expired:
            raise TimeoutError
        return status, location
    finally:
        watchdog.cancel()
        conn.finish()
        watchdog.join()


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
        if _CONTROL.search(current):
            raise LinkError('invalid_link')
        if not is_resolvable(current):
            raise LinkError('unsupported_host')
        # Rebuilt from the parsed parts the allowlist judged, never from the raw
        # string. Every allowed host serves https; an http:// link is never fetched in clear.
        parts = urlsplit(current)
        target = urlunsplit(('https', parts.hostname, parts.path, parts.query, ''))
        # Capped: on a coarse clock (deadline - now) can round a hair above the budget.
        remaining = min(TIMEOUT_SECONDS, deadline - time.monotonic())
        if remaining <= 0:
            raise LinkError('unreachable')
        try:
            status, location = fetch_location(target, remaining)
        except (OSError, http.client.HTTPException, ValueError) as exc:
            raise LinkError('unreachable') from exc
        if status not in _REDIRECTS or not location or len(location) > _MAX_LOCATION:
            raise LinkError('no_coordinates')
        current = urljoin(target, location)
        # A relative Location joined to a long target can outgrow what
        # parse_url reads; such a URL could only be fetched, never read.
        if len(current) > google_maps_link.MAX_INPUT:
            raise LinkError('no_coordinates')
    pair = google_maps_link.parse_url(current)
    if pair:
        return pair
    raise LinkError('too_many_redirects')
